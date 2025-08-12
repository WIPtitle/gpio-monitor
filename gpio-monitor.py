#!/usr/bin/python3

import http.server
import json
import os
import socketserver
import subprocess
import threading
import time
from datetime import datetime

CONFIG_FILE = "/etc/gpio-monitor/config.json"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
HTML_FILE = os.path.join(SCRIPT_DIR, "index.html")
DEFAULT_PORT = 8787
POLL_INTERVAL = 0.1


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {"port": DEFAULT_PORT, "monitored_pins": [], "pin_config": {}}


def save_config(config):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)


def get_available_gpio_pins():
    """Get list of all available GPIO pins on this Raspberry Pi"""
    available_pins = []

    for pin in range(28):
        try:
            result = subprocess.run(['gpioget', 'gpiochip0', str(pin)],
                                    capture_output=True, text=True,
                                    timeout=0.1)
            if result.returncode == 0:
                available_pins.append(pin)
        except:
            pass

    if not available_pins:
        available_pins = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
                          16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27]

    return sorted(available_pins)


def get_pin_info():
    """Get pin categories and warnings"""
    reserved_pins = {
        0: "ID_SD (HAT EEPROM)",
        1: "ID_SC (HAT EEPROM)",
        2: "SDA1 (I2C)",
        3: "SCL1 (I2C)",
        14: "TXD0 (UART)",
        15: "RXD0 (UART)"
    }
    return reserved_pins


class GPIOMonitor:
    def __init__(self):
        self.gpio_states = {}
        self.gpio_pending_changes = {}
        self.clients = []
        self.config_lock = threading.Lock()
        self.available_pins = get_available_gpio_pins()
        self.reserved_pins = get_pin_info()

        # Load initial config
        self.reload_config()

        # Start config watcher thread
        self.config_watcher_thread = threading.Thread(target=self.config_watcher, daemon=True)
        self.config_watcher_thread.start()

    def reload_config(self):
        """Reload configuration and update monitoring"""
        with self.config_lock:
            config = load_config()
            self.monitored_pins = config.get("monitored_pins", [])
            self.pin_config = config.get("pin_config", {})

            # Remove states for pins no longer monitored
            for pin in list(self.gpio_states.keys()):
                if pin not in self.monitored_pins:
                    del self.gpio_states[pin]
                    if pin in self.gpio_pending_changes:
                        del self.gpio_pending_changes[pin]

            # Initialize states for new pins
            for pin in self.monitored_pins:
                if pin not in self.gpio_states and pin in self.available_pins:
                    self.init_pin_state(pin)

    def init_pin_state(self, pin):
        """Initialize state for a single pin"""
        pin_cfg = self.pin_config.get(str(pin), {})

        # Check if debouncing is enabled for this pin
        if 'debounce' in pin_cfg:
            # Need 10 initial readings for debounced pins
            readings = []
            for _ in range(10):
                try:
                    value = self.read_gpio(pin)
                    if value != -1:
                        readings.append(value)
                except:
                    pass
                time.sleep(0.1)

            if len(readings) >= 6:
                initial_state = max(set(readings), key=readings.count)
                self.gpio_states[pin] = initial_state
        else:
            # No debouncing, just read once
            try:
                value = self.read_gpio(pin)
                if value != -1:
                    self.gpio_states[pin] = value
            except:
                pass

    def config_watcher(self):
        """Watch for config file changes"""
        last_mtime = 0
        while True:
            try:
                if os.path.exists(CONFIG_FILE):
                    current_mtime = os.path.getmtime(CONFIG_FILE)
                    if current_mtime > last_mtime:
                        last_mtime = current_mtime
                        time.sleep(0.1)  # Small delay to ensure file is fully written
                        self.reload_config()
            except:
                pass
            time.sleep(1)

    def read_gpio(self, pin):
        """Read GPIO with appropriate bias if configured"""
        try:
            pin_cfg = self.pin_config.get(str(pin), {})

            if 'pull' in pin_cfg:
                bias_flag = {
                    'up': 'pull-up',
                    'down': 'pull-down',
                    'none': 'disable'
                }.get(pin_cfg['pull'], 'disable')

                result = subprocess.run(['gpioget', '--bias=' + bias_flag, 'gpiochip0', str(pin)],
                                        capture_output=True, text=True)
            else:
                result = subprocess.run(['gpioget', 'gpiochip0', str(pin)],
                                        capture_output=True, text=True)

            return int(result.stdout.strip())
        except:
            return -1

    def get_debounce_threshold(self, pin):
        """Get debounce threshold for a pin"""
        pin_cfg = self.pin_config.get(str(pin), {})
        debounce_level = pin_cfg.get('debounce', None)

        if debounce_level is None:
            return None

        thresholds = {
            'LOW': 3,
            'MEDIUM': 5,
            'HIGH': 7
        }
        return thresholds.get(debounce_level, None)

    def get_pin_state(self, pin):
        """Get current state of a pin"""
        with self.config_lock:
            if pin in self.gpio_states:
                return self.gpio_states[pin]
            return None

    def monitor_loop(self):
        while True:
            with self.config_lock:
                pins_to_monitor = list(self.monitored_pins)

            for pin in pins_to_monitor:
                if pin in self.available_pins:
                    current_reading = self.read_gpio(pin)

                    if current_reading == -1:
                        continue

                    with self.config_lock:
                        if pin not in self.gpio_states:
                            continue

                        current_state = self.gpio_states[pin]
                        debounce_threshold = self.get_debounce_threshold(pin)

                        # Process state change
                        if debounce_threshold is None:
                            if current_reading != current_state:
                                old_value = current_state
                                new_value = current_reading
                                self.gpio_states[pin] = new_value

                                event_type = "rising" if new_value == 1 else "falling"

                                event_data = {
                                    "pin": pin,
                                    "state": new_value,
                                    "previous": old_value,
                                    "timestamp": int(time.time() * 1000),
                                    "time": datetime.now().strftime("%H:%M:%S.%f")[:-3]
                                }

                                self.broadcast_event(f"gpio_{event_type}", event_data)
                        else:
                            # Debouncing logic
                            if current_reading != current_state:
                                if pin not in self.gpio_pending_changes:
                                    self.gpio_pending_changes[pin] = {
                                        'readings': [current_reading],
                                        'old_state': current_state,
                                        'new_state': current_reading
                                    }
                                else:
                                    pending = self.gpio_pending_changes[pin]
                                    pending['readings'].append(current_reading)

                                    if len(pending['readings']) >= 10:
                                        new_state_count = pending['readings'].count(pending['new_state'])

                                        if new_state_count >= debounce_threshold:
                                            old_value = pending['old_state']
                                            new_value = pending['new_state']

                                            self.gpio_states[pin] = new_value

                                            event_type = "rising" if new_value == 1 else "falling"

                                            event_data = {
                                                "pin": pin,
                                                "state": new_value,
                                                "previous": old_value,
                                                "timestamp": int(time.time() * 1000),
                                                "time": datetime.now().strftime("%H:%M:%S.%f")[:-3],
                                                "confidence": f"{new_state_count}/10"
                                            }

                                            self.broadcast_event(f"gpio_{event_type}", event_data)

                                        del self.gpio_pending_changes[pin]
                            else:
                                if pin in self.gpio_pending_changes:
                                    pending = self.gpio_pending_changes[pin]
                                    pending['readings'].append(current_reading)

                                    if len(pending['readings']) >= 10:
                                        new_state_count = pending['readings'].count(pending['new_state'])

                                        if new_state_count >= debounce_threshold:
                                            old_value = pending['old_state']
                                            new_value = pending['new_state']

                                            self.gpio_states[pin] = new_value

                                            event_type = "rising" if new_value == 1 else "falling"

                                            event_data = {
                                                "pin": pin,
                                                "state": new_value,
                                                "previous": old_value,
                                                "timestamp": int(time.time() * 1000),
                                                "time": datetime.now().strftime("%H:%M:%S.%f")[:-3],
                                                "confidence": f"{new_state_count}/10"
                                            }

                                            self.broadcast_event(f"gpio_{event_type}", event_data)

                                        del self.gpio_pending_changes[pin]

            time.sleep(POLL_INTERVAL)

    def broadcast_event(self, event_type, data):
        message = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

        self.clients = [c for c in self.clients if not c.closed]

        for client in self.clients:
            try:
                client.write(message.encode())
                client.flush()
            except:
                pass


monitor = GPIOMonitor()


class SSEHandler(http.server.BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(self.get_html_page().encode())

        elif self.path == '/events':
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

            monitor.clients.append(self.wfile)

            init_data = {
                "pins": monitor.gpio_states,
                "monitored": monitor.monitored_pins,
                "available": monitor.available_pins,
                "timestamp": int(time.time() * 1000)
            }
            self.wfile.write(f"event: init\ndata: {json.dumps(init_data)}\n\n".encode())
            self.wfile.flush()

            try:
                while True:
                    time.sleep(1)
                    self.wfile.write(f": heartbeat\n\n".encode())
                    self.wfile.flush()
            except:
                pass

        elif self.path == '/api/pins':
            # GET all pins info
            config = load_config()
            response = {
                "monitored": monitor.monitored_pins,
                "available": monitor.available_pins,
                "reserved": monitor.reserved_pins,
                "states": monitor.gpio_states,
                "config": config.get("pin_config", {})
            }
            self.send_json_response(200, response)

        elif self.path.startswith('/api/pins/') and self.path.endswith('/state'):
            # GET pin state
            try:
                pin = int(self.path.split('/')[3])
                state = monitor.get_pin_state(pin)
                if state is not None:
                    self.send_json_response(200, {"pin": pin, "state": state})
                else:
                    self.send_json_response(404, {"error": f"Pin {pin} not monitored"})
            except:
                self.send_json_response(400, {"error": "Invalid pin number"})

        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        if self.path.startswith('/api/pins/'):
            # POST to add a pin
            try:
                pin = int(self.path.split('/')[3])

                if pin not in monitor.available_pins:
                    self.send_json_response(400, {"error": f"GPIO {pin} not available"})
                    return

                config = load_config()
                monitored = config.get("monitored_pins", [])

                if pin in monitored:
                    self.send_json_response(409, {"error": f"GPIO {pin} already monitored"})
                else:
                    monitored.append(pin)
                    monitored.sort()
                    config["monitored_pins"] = monitored
                    save_config(config)

                    # Reload monitor config immediately
                    monitor.reload_config()

                    response = {
                        "message": f"Added GPIO {pin} to monitoring",
                        "monitored": monitored
                    }

                    if pin in monitor.reserved_pins:
                        response["warning"] = f"GPIO {pin} has special function: {monitor.reserved_pins[pin]}"

                    self.send_json_response(200, response)
            except:
                self.send_json_response(400, {"error": "Invalid pin number"})
        else:
            self.send_error(404, "Not Found")

    def do_PUT(self):
        if self.path.startswith('/api/pins/') and '/pull' in self.path:
            # PUT to set pull resistor
            try:
                pin = int(self.path.split('/')[3])
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data)

                mode = data.get('mode', '').lower()
                if mode not in ['up', 'down', 'none']:
                    self.send_json_response(400, {"error": "Mode must be 'up', 'down', or 'none'"})
                    return

                config = load_config()
                monitored = config.get("monitored_pins", [])

                if pin not in monitored:
                    self.send_json_response(404, {"error": f"GPIO {pin} not monitored"})
                    return

                pin_config = config.get("pin_config", {})
                if str(pin) not in pin_config:
                    pin_config[str(pin)] = {}

                if mode == 'none':
                    pin_config[str(pin)].pop('pull', None)
                    message = f"Removed pull resistor for GPIO {pin}"
                else:
                    pin_config[str(pin)]['pull'] = mode
                    message = f"Set GPIO {pin} to pull-{mode}"

                config["pin_config"] = pin_config
                save_config(config)

                # Reload monitor config immediately
                monitor.reload_config()

                self.send_json_response(200, {"message": message})
            except:
                self.send_json_response(400, {"error": "Invalid request"})

        elif self.path.startswith('/api/pins/') and '/debounce' in self.path:
            # PUT to set debounce
            try:
                pin = int(self.path.split('/')[3])
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data)

                level = data.get('level', '').upper()
                if level not in ['LOW', 'MEDIUM', 'HIGH']:
                    self.send_json_response(400, {"error": "Level must be 'LOW', 'MEDIUM', or 'HIGH'"})
                    return

                config = load_config()
                monitored = config.get("monitored_pins", [])

                if pin not in monitored:
                    self.send_json_response(404, {"error": f"GPIO {pin} not monitored"})
                    return

                pin_config = config.get("pin_config", {})
                if str(pin) not in pin_config:
                    pin_config[str(pin)] = {}

                pin_config[str(pin)]['debounce'] = level

                thresholds = {'LOW': 3, 'MEDIUM': 5, 'HIGH': 7}
                message = f"Set GPIO {pin} debouncing to {level} ({thresholds[level]}/10 readings)"

                config["pin_config"] = pin_config
                save_config(config)

                # Reload monitor config immediately
                monitor.reload_config()

                self.send_json_response(200, {"message": message})
            except:
                self.send_json_response(400, {"error": "Invalid request"})
        else:
            self.send_error(404, "Not Found")

    def do_DELETE(self):
        if self.path == '/api/pins':
            # DELETE all pins
            config = load_config()
            config["monitored_pins"] = []
            save_config(config)

            # Reload monitor config immediately
            monitor.reload_config()

            self.send_json_response(200, {"message": "Cleared all monitored pins"})

        elif self.path.startswith('/api/pins/') and self.path.endswith('/debounce'):
            # DELETE debounce setting
            try:
                pin = int(self.path.split('/')[3])

                config = load_config()
                monitored = config.get("monitored_pins", [])

                if pin not in monitored:
                    self.send_json_response(404, {"error": f"GPIO {pin} not monitored"})
                    return

                pin_config = config.get("pin_config", {})
                if str(pin) in pin_config and 'debounce' in pin_config[str(pin)]:
                    del pin_config[str(pin)]['debounce']
                    message = f"Removed debouncing from GPIO {pin}"
                else:
                    message = f"GPIO {pin} does not have debouncing configured"

                config["pin_config"] = pin_config
                save_config(config)

                # Reload monitor config immediately
                monitor.reload_config()

                self.send_json_response(200, {"message": message})
            except:
                self.send_json_response(400, {"error": "Invalid pin number"})

        elif self.path.startswith('/api/pins/'):
            # DELETE a pin
            try:
                pin = int(self.path.split('/')[3])

                config = load_config()
                monitored = config.get("monitored_pins", [])

                if pin not in monitored:
                    self.send_json_response(404, {"error": f"GPIO {pin} not monitored"})
                else:
                    monitored.remove(pin)
                    config["monitored_pins"] = monitored

                    # Remove pin config if exists
                    pin_config = config.get("pin_config", {})
                    if str(pin) in pin_config:
                        del pin_config[str(pin)]
                        config["pin_config"] = pin_config

                    save_config(config)

                    # Reload monitor config immediately
                    monitor.reload_config()

                    self.send_json_response(200, {
                        "message": f"Removed GPIO {pin} from monitoring",
                        "monitored": monitored
                    })
            except:
                self.send_json_response(400, {"error": "Invalid pin number"})
        else:
            self.send_error(404, "Not Found")

    def send_json_response(self, code, data):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def get_html_page(self):
        if os.path.exists(HTML_FILE):
            with open(HTML_FILE, 'r', encoding='utf-8') as f:
                return f.read()
        else:
            return "<html><body><h1>GPIO Monitor</h1><p>HTML file not found.</p></body></html>"

    def log_message(self, format, *args):
        pass


if __name__ == '__main__':
    config = load_config()
    PORT = config.get("port", DEFAULT_PORT)

    monitor_thread = threading.Thread(target=monitor.monitor_loop, daemon=True)
    monitor_thread.start()

    with socketserver.ThreadingTCPServer(("", PORT), SSEHandler) as httpd:
        print(f"GPIO Monitor started on port {PORT}")
        print(f"Web interface: http://localhost:{PORT}")
        httpd.serve_forever()