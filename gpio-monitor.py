#!/usr/bin/python3

import http.server
import socketserver
import subprocess
import json
import time
import threading
import os
import sys
from datetime import datetime

CONFIG_FILE = "/etc/gpio-monitor/config.json"
DEFAULT_PORT = 8787
POLL_INTERVAL = 0.1


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {"port": DEFAULT_PORT, "monitored_pins": [], "pin_config": {}}


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


config = load_config()
PORT = config.get("port", DEFAULT_PORT)
MONITORED_PINS = config.get("monitored_pins", [])
PIN_CONFIG = config.get("pin_config", {})


def configure_pin_pull(pin, pull_mode):
    """Configure pull resistor for a GPIO pin using gpioset with bias
    pull_mode: 'up', 'down', or 'none'
    """
    try:
        bias_flag = {
            'up': 'pull-up',
            'down': 'pull-down',
            'none': 'disable'
        }.get(pull_mode)

        if bias_flag:
            # Note: gpioset with bias doesn't persist, but gpioget with bias does read correctly
            # The monitoring loop will use gpioget with the same bias
            print(f"GPIO{pin} configured for pull-{pull_mode}")
    except Exception as e:
        print(f"Note: Could not configure pull resistor for GPIO{pin}")


class GPIOMonitor:
    def __init__(self):
        self.gpio_states = {}
        self.gpio_pending_changes = {}  # Track pending state changes for debouncing
        self.clients = []
        self.monitored_pins = MONITORED_PINS
        self.available_pins = get_available_gpio_pins()

        if self.monitored_pins:
            print(f"Monitoring {len(self.monitored_pins)} GPIO pins: {self.monitored_pins}")
        else:
            print("No GPIO pins configured for monitoring")
            print("Use 'gpio-monitor add-pin <number>' to add pins to monitor")

        self.init_states()

    def init_states(self):
        # Need 10 initial readings before setting any state
        initial_readings = {}

        for pin in self.monitored_pins:
            if pin in self.available_pins:
                # Configure pull resistor if specified
                pin_cfg = PIN_CONFIG.get(str(pin), {})
                if 'pull' in pin_cfg:
                    configure_pin_pull(pin, pin_cfg['pull'])

                # Collect 10 initial readings
                readings = []
                for _ in range(10):
                    try:
                        value = self.read_gpio(pin)
                        if value != -1:
                            readings.append(value)
                    except:
                        pass
                    time.sleep(0.1)

                # Set initial state only if we have enough consistent readings
                if len(readings) >= 6:
                    # Use most common value as initial state
                    initial_state = max(set(readings), key=readings.count)
                    self.gpio_states[pin] = initial_state
                    print(f"GPIO{pin} initial state: {initial_state}")
                else:
                    # Not enough readings, state remains undefined
                    print(f"GPIO{pin} initial state: undefined (insufficient readings)")

    def read_gpio(self, pin):
        """Read GPIO with appropriate bias if configured"""
        try:
            # Check if pin has pull configuration
            pin_cfg = PIN_CONFIG.get(str(pin), {})

            if 'pull' in pin_cfg:
                bias_flag = {
                    'up': 'pull-up',
                    'down': 'pull-down',
                    'none': 'disable'
                }.get(pin_cfg['pull'], 'disable')

                # Read with bias
                result = subprocess.run(['gpioget', '--bias=' + bias_flag, 'gpiochip0', str(pin)],
                                        capture_output=True, text=True)
            else:
                # Read without bias
                result = subprocess.run(['gpioget', 'gpiochip0', str(pin)],
                                        capture_output=True, text=True)

            return int(result.stdout.strip())
        except:
            return -1

    def monitor_loop(self):
        while True:
            if self.monitored_pins:
                for pin in self.monitored_pins:
                    if pin in self.available_pins:
                        current_reading = self.read_gpio(pin)

                        # Skip if invalid reading
                        if current_reading == -1:
                            continue

                        # Check if we have an established state for this pin
                        if pin not in self.gpio_states:
                            # No initial state yet, skip
                            continue

                        current_state = self.gpio_states[pin]

                        # Check if this reading differs from current state
                        if current_reading != current_state:
                            # Potential state change detected
                            if pin not in self.gpio_pending_changes:
                                # Start tracking this potential change
                                self.gpio_pending_changes[pin] = {
                                    'readings': [current_reading],
                                    'old_state': current_state,
                                    'new_state': current_reading
                                }
                            else:
                                # Add to existing pending change readings
                                pending = self.gpio_pending_changes[pin]
                                pending['readings'].append(current_reading)

                                # Check if we have collected 10 readings
                                if len(pending['readings']) >= 10:
                                    # Count how many readings match the new state
                                    new_state_count = pending['readings'].count(pending['new_state'])

                                    if new_state_count >= 6:
                                        # Confirmed state change
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

                                    # Clear pending change regardless of outcome
                                    del self.gpio_pending_changes[pin]
                        else:
                            # Reading matches current state
                            if pin in self.gpio_pending_changes:
                                # We were tracking a potential change
                                pending = self.gpio_pending_changes[pin]
                                pending['readings'].append(current_reading)

                                # Check if we have 10 readings
                                if len(pending['readings']) >= 10:
                                    # Count readings for new state
                                    new_state_count = pending['readings'].count(pending['new_state'])

                                    if new_state_count >= 6:
                                        # Confirmed state change
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

                                    # Clear pending change
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

    def get_html_page(self):
        return '''<!DOCTYPE html>
<html>
<head>
    <title>GPIO Monitor</title>
    <style>
        body { 
            font-family: monospace; 
            background: #1a1a1a; 
            color: #0f0;
            padding: 20px;
        }
        h1 { color: #0f0; }
        .warning {
            background: #440;
            border: 1px solid #ff0;
            color: #ff0;
            padding: 10px;
            margin: 20px 0;
            border-radius: 5px;
        }
        .pin-container {
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 10px;
            margin: 20px 0;
        }
        .pin {
            padding: 10px;
            text-align: center;
            border: 2px solid #333;
            border-radius: 5px;
            transition: all 0.3s;
        }
        .pin.high {
            background: #f00;
            color: #fff;
            border-color: #f00;
            box-shadow: 0 0 10px #f00;
        }
        .pin.low {
            background: #111;
            color: #666;
        }
        #events {
            max-height: 300px;
            overflow-y: auto;
            border: 1px solid #333;
            padding: 10px;
            background: #0a0a0a;
        }
        .event {
            padding: 3px 0;
            border-bottom: 1px solid #222;
        }
        .event.rising { color: #f00; }
        .event.falling { color: #666; }
        .status {
            padding: 5px;
            background: #030;
            border: 1px solid #0f0;
            margin-bottom: 10px;
        }
        .info {
            background: #003;
            border: 1px solid #00f;
            color: #88f;
            padding: 10px;
            margin: 10px 0;
            border-radius: 5px;
        }
        code {
            background: #000;
            padding: 2px 5px;
            border: 1px solid #444;
        }
    </style>
</head>
<body>
    <h1>GPIO Real-time Monitor</h1>
    <div class="status">Status: <span id="status">Connecting...</span></div>
    <div id="no-pins-warning" class="warning" style="display:none">
        No GPIO pins are being monitored!<br>
        Configure pins using the command line:<br>
        <code>sudo gpio-monitor add-pin 17</code><br>
        <code>sudo gpio-monitor add-pin 27</code><br>
        <code>sudo gpio-monitor list-pins</code>
    </div>

    <div class="info">
        <strong>Monitored Pins:</strong> <span id="monitored-pins">Loading...</span><br>
        <strong>Available Pins:</strong> <span id="available-pins">Loading...</span>
    </div>

    <h2>Pin States:</h2>
    <div id="pins" class="pin-container"></div>

    <h2>Events Log:</h2>
    <div id="events"></div>

    <script>
        const eventSource = new EventSource('/events');
        const pinStates = {};
        let eventCount = 0;
        let monitoredPins = [];

        eventSource.onopen = () => {
            document.getElementById('status').textContent = 'Connected';
        };

        eventSource.addEventListener('init', (e) => {
            const data = JSON.parse(e.data);
            monitoredPins = data.monitored || [];

            document.getElementById('monitored-pins').textContent = 
                monitoredPins.length > 0 ? monitoredPins.join(', ') : 'None';
            document.getElementById('available-pins').textContent = 
                data.available ? data.available.join(', ') : 'Unknown';

            if (monitoredPins.length === 0) {
                document.getElementById('no-pins-warning').style.display = 'block';
                document.getElementById('pins').innerHTML = '<div style="color: #666;">No pins configured</div>';
            } else {
                document.getElementById('no-pins-warning').style.display = 'none';
                for (const [pin, state] of Object.entries(data.pins)) {
                    updatePin(pin, state);
                }
            }
        });

        eventSource.addEventListener('gpio_rising', handleGpioEvent);
        eventSource.addEventListener('gpio_falling', handleGpioEvent);

        function handleGpioEvent(e) {
            const data = JSON.parse(e.data);
            updatePin(data.pin, data.state);
            logEvent(e.type, data);
        }

        function updatePin(pin, state) {
            let pinDiv = document.getElementById('pin-' + pin);
            if (!pinDiv) {
                pinDiv = document.createElement('div');
                pinDiv.id = 'pin-' + pin;
                pinDiv.className = 'pin';
                document.getElementById('pins').appendChild(pinDiv);
            }

            pinDiv.className = 'pin ' + (state == 1 ? 'high' : 'low');
            pinDiv.innerHTML = '<strong>GPIO ' + pin + '</strong><br>' + (state == 1 ? 'HIGH' : 'LOW');
        }

        function logEvent(type, data) {
            eventCount++;
            const eventDiv = document.createElement('div');
            eventDiv.className = 'event ' + type.replace('gpio_', '');

            const arrow = data.state == 1 ? 'UP' : 'DOWN';
            eventDiv.textContent = '#' + eventCount + ' [' + data.time + '] GPIO' + data.pin + ': ' + data.previous + ' to ' + data.state + ' ' + arrow;

            const container = document.getElementById('events');
            container.insertBefore(eventDiv, container.firstChild);

            while (container.children.length > 50) {
                container.removeChild(container.lastChild);
            }
        }

        eventSource.onerror = () => {
            document.getElementById('status').textContent = 'Disconnected';
        };
    </script>
</body>
</html>'''

    def log_message(self, format, *args):
        pass


if __name__ == '__main__':
    monitor_thread = threading.Thread(target=monitor.monitor_loop, daemon=True)
    monitor_thread.start()

    with socketserver.TCPServer(("", PORT), SSEHandler) as httpd:
        print(f"GPIO Monitor started on port {PORT}")
        print(f"Open: http://localhost:{PORT}")
        print(f"SSE Endpoint: http://localhost:{PORT}/events")
        if MONITORED_PINS:
            print(f"Monitoring pins: {MONITORED_PINS}")
        else:
            print("No pins configured. Use 'gpio-monitor add-pin <number>' to add pins")
        httpd.serve_forever()