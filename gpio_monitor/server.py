#!/usr/bin/python3
"""HTTP server for GPIO Monitor."""

import http.server
import json
import os
import time
from typing import Any, Dict

# Try both relative and absolute imports for compatibility
try:
    from .monitor import GPIOMonitor
except ImportError:
    from monitor import GPIOMonitor


class GPIORequestHandler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler for GPIO Monitor."""

    # These will be set by the factory function in main
    monitor = None
    html_file = None

    def do_OPTIONS(self):
        """Handle CORS preflight requests."""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        """Handle GET requests."""
        if self.path == '/':
            self._serve_html()
        elif self.path == '/events':
            self._serve_sse()
        elif self.path == '/api/pins':
            self._get_all_pins()
        elif self.path.startswith('/api/pins/') and self.path.endswith('/state'):
            self._get_pin_state()
        elif self.path == '/api/dev-mode':
            self._get_dev_mode()
        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        """Handle POST requests."""
        if self.path.startswith('/api/pins/') and self.path.endswith('/trigger'):
            self._trigger_pin()
        elif self.path.startswith('/api/pins/'):
            self._add_pin()
        else:
            self.send_error(404, "Not Found")

    def do_PUT(self):
        """Handle PUT requests."""
        if self.path == '/api/dev-mode':
            self._set_dev_mode()
        elif self.path.startswith('/api/pins/') and '/pull' in self.path:
            self._set_pull()
        elif self.path.startswith('/api/pins/') and '/debounce' in self.path:
            self._set_debounce()
        elif self.path.startswith('/api/pins/') and '/inverted' in self.path:
            self._set_inverted()
        else:
            self.send_error(404, "Not Found")

    def do_DELETE(self):
        """Handle DELETE requests."""
        if self.path == '/api/pins':
            self._clear_all_pins()
        elif self.path.startswith('/api/pins/') and self.path.endswith('/debounce'):
            self._remove_debounce()
        elif self.path.startswith('/api/pins/') and self.path.endswith('/inverted'):
            self._remove_inverted()
        elif self.path.startswith('/api/pins/'):
            self._remove_pin()
        else:
            self.send_error(404, "Not Found")

    def _serve_html(self):
        """Serve the HTML dashboard."""
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()

        if os.path.exists(self.html_file):
            with open(self.html_file, 'r', encoding='utf-8') as f:
                content = f.read()
        else:
            content = "<html><body><h1>GPIO Monitor</h1><p>HTML file not found.</p></body></html>"

        self.wfile.write(content.encode())

    def _serve_sse(self):
        """Serve Server-Sent Events stream."""
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'keep-alive')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

        # Register client
        self.monitor.clients.append(self.wfile)

        # Send initial state
        init_data = {
            "pins": self.monitor.get_all_virtual_states(),
            "monitored": self.monitor.get_current_monitored_pins(),
            "available": self.monitor.get_current_available_pins(),
            "timestamp": int(time.time() * 1000),
            "dev_mode": self.monitor.dev_mode
        }

        self.wfile.write(f"event: init\ndata: {json.dumps(init_data)}\n\n".encode())
        self.wfile.flush()

        # Keep connection alive
        try:
            while True:
                time.sleep(1)
                self.wfile.write(f": heartbeat\n\n".encode())
                self.wfile.flush()
        except:
            pass

    def _get_all_pins(self):
        """Get all pins information."""
        config = self.monitor.config_manager.load()

        response = {
            "monitored": self.monitor.get_current_monitored_pins(),
            "available": self.monitor.get_current_available_pins(),
            "reserved": self.monitor.reserved_pins,
            "states": self.monitor.get_all_virtual_states(),
            "config": config.get("pin_config", {}) if not self.monitor.dev_mode else {},
            "dev_mode": self.monitor.dev_mode
        }
        self._send_json_response(200, response)

    def _get_pin_state(self):
        """Get a single pin state."""
        try:
            pin = int(self.path.split('/')[3])
            state = self.monitor.get_virtual_state(pin)

            if state is not None:
                self._send_json_response(200, {"pin": pin, "state": state})
            else:
                self._send_json_response(404, {"error": f"Pin {pin} not monitored"})
        except:
            self._send_json_response(400, {"error": "Invalid pin number"})

    def _add_pin(self):
        """Add a pin to monitoring."""
        try:
            pin = int(self.path.split('/')[3])

            # Dev mode: use separate in-memory pin list
            if self.monitor.dev_mode:
                result = self.monitor.add_dev_pin(pin)
                if "error" in result:
                    self._send_json_response(400, result)
                else:
                    self._send_json_response(200, result)
                return

            # Real mode: check hardware availability
            if pin not in self.monitor.available_pins:
                self._send_json_response(400, {"error": f"GPIO {pin} not available (no hardware detected)"})
                return

            config = self.monitor.config_manager.load()
            monitored = config.get("monitored_pins", [])

            if pin in monitored:
                self._send_json_response(409, {"error": f"GPIO {pin} already monitored"})
            else:
                monitored.append(pin)
                monitored.sort()
                config["monitored_pins"] = monitored
                self.monitor.config_manager.save(config)

                # Reload monitor config
                self.monitor.reload_config()

                response = {
                    "message": f"Added GPIO {pin} to monitoring",
                    "monitored": monitored
                }

                if pin in self.monitor.reserved_pins:
                    response["warning"] = f"GPIO {pin} has special function: {self.monitor.reserved_pins[pin]}"

                self._send_json_response(200, response)
        except:
            self._send_json_response(400, {"error": "Invalid pin number"})

    def _remove_pin(self):
        """Remove a pin from monitoring."""
        try:
            pin = int(self.path.split('/')[3])

            # Dev mode: use separate in-memory pin list
            if self.monitor.dev_mode:
                result = self.monitor.remove_dev_pin(pin)
                if "error" in result:
                    self._send_json_response(404, result)
                else:
                    self._send_json_response(200, result)
                return

            # Real mode
            config = self.monitor.config_manager.load()
            monitored = config.get("monitored_pins", [])

            if pin not in monitored:
                self._send_json_response(404, {"error": f"GPIO {pin} not monitored"})
            else:
                monitored.remove(pin)
                config["monitored_pins"] = monitored

                # Remove pin config if exists
                pin_config = config.get("pin_config", {})
                if str(pin) in pin_config:
                    del pin_config[str(pin)]
                    config["pin_config"] = pin_config

                self.monitor.config_manager.save(config)
                self.monitor.reload_config()

                self._send_json_response(200, {
                    "message": f"Removed GPIO {pin} from monitoring",
                    "monitored": monitored
                })
        except:
            self._send_json_response(400, {"error": "Invalid pin number"})

    def _clear_all_pins(self):
        """Clear all monitored pins."""
        if self.monitor.dev_mode:
            # Dev mode: clear in-memory pins
            with self.monitor.config_lock:
                self.monitor.dev_monitored_pins.clear()
                self.monitor.dev_pin_states.clear()
                self.monitor.instant_triggers.clear()
            self._send_json_response(200, {"message": "Cleared all dev mode pins"})
            return

        # Real mode
        config = self.monitor.config_manager.load()
        config["monitored_pins"] = []
        config["pin_config"] = {}
        self.monitor.config_manager.save(config)
        self.monitor.reload_config()

        self._send_json_response(200, {"message": "Cleared all monitored pins"})

    def _set_pull(self):
        """Set pull resistor for a pin."""
        try:
            pin = int(self.path.split('/')[3])
            data = self._get_request_body()

            mode = data.get('mode', '').lower()
            if mode not in ['up', 'down', 'none']:
                self._send_json_response(400, {"error": "Mode must be 'up', 'down', or 'none'"})
                return

            config = self.monitor.config_manager.load()
            if pin not in config.get("monitored_pins", []):
                self._send_json_response(404, {"error": f"GPIO {pin} not monitored"})
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
            self.monitor.config_manager.save(config)
            self.monitor.reload_config()

            self._send_json_response(200, {"message": message})
        except:
            self._send_json_response(400, {"error": "Invalid request"})

    def _set_debounce(self):
        """Set debounce configuration for a pin."""
        try:
            pin = int(self.path.split('/')[3])
            data = self._get_request_body()

            low_threshold = data.get('low')
            high_threshold = data.get('high')

            if not isinstance(low_threshold, int) or not isinstance(high_threshold, int):
                self._send_json_response(400, {"error": "Both 'low' and 'high' must be integers"})
                return

            if not (1 <= low_threshold <= 10) or not (1 <= high_threshold <= 10):
                self._send_json_response(400, {"error": "Thresholds must be between 1 and 10"})
                return

            config = self.monitor.config_manager.load()
            if pin not in config.get("monitored_pins", []):
                self._send_json_response(404, {"error": f"GPIO {pin} not monitored"})
                return

            pin_config = config.get("pin_config", {})
            if str(pin) not in pin_config:
                pin_config[str(pin)] = {}

            pin_config[str(pin)]['debounce_low'] = low_threshold
            pin_config[str(pin)]['debounce_high'] = high_threshold

            config["pin_config"] = pin_config
            self.monitor.config_manager.save(config)
            self.monitor.reload_config()

            message = f"Set GPIO {pin} debouncing: LOW={low_threshold}/10, HIGH={high_threshold}/10"
            self._send_json_response(200, {"message": message})
        except:
            self._send_json_response(400, {"error": "Invalid request"})

    def _remove_debounce(self):
        """Remove debounce configuration from a pin."""
        try:
            pin = int(self.path.split('/')[3])

            config = self.monitor.config_manager.load()
            if pin not in config.get("monitored_pins", []):
                self._send_json_response(404, {"error": f"GPIO {pin} not monitored"})
                return

            pin_config = config.get("pin_config", {})
            if str(pin) in pin_config:
                removed = False
                if 'debounce_low' in pin_config[str(pin)]:
                    del pin_config[str(pin)]['debounce_low']
                    removed = True
                if 'debounce_high' in pin_config[str(pin)]:
                    del pin_config[str(pin)]['debounce_high']
                    removed = True

                message = ("Removed debouncing from GPIO " + str(pin) if removed
                           else f"GPIO {pin} does not have debouncing configured")
            else:
                message = f"GPIO {pin} does not have debouncing configured"

            config["pin_config"] = pin_config
            self.monitor.config_manager.save(config)
            self.monitor.reload_config()

            self._send_json_response(200, {"message": message})
        except:
            self._send_json_response(400, {"error": "Invalid pin number"})

    def _set_inverted(self):
        """Set inverted logic for a pin."""
        try:
            pin = int(self.path.split('/')[3])

            config = self.monitor.config_manager.load()
            if pin not in config.get("monitored_pins", []):
                self._send_json_response(404, {"error": f"GPIO {pin} not monitored"})
                return

            pin_config = config.get("pin_config", {})
            if str(pin) not in pin_config:
                pin_config[str(pin)] = {}

            pin_config[str(pin)]['inverted'] = True

            config["pin_config"] = pin_config
            self.monitor.config_manager.save(config)
            self.monitor.reload_config()

            self._send_json_response(200, {"message": f"Set GPIO {pin} to inverted logic"})
        except:
            self._send_json_response(400, {"error": "Invalid request"})

    def _remove_inverted(self):
        """Remove inverted logic from a pin."""
        try:
            pin = int(self.path.split('/')[3])

            config = self.monitor.config_manager.load()
            if pin not in config.get("monitored_pins", []):
                self._send_json_response(404, {"error": f"GPIO {pin} not monitored"})
                return

            pin_config = config.get("pin_config", {})
            if str(pin) in pin_config and 'inverted' in pin_config[str(pin)]:
                del pin_config[str(pin)]['inverted']
                message = f"Removed inverted logic from GPIO {pin}"
            else:
                message = f"GPIO {pin} does not have inverted logic configured"

            config["pin_config"] = pin_config
            self.monitor.config_manager.save(config)
            self.monitor.reload_config()

            self._send_json_response(200, {"message": message})
        except:
            self._send_json_response(400, {"error": "Invalid pin number"})

    # ==================== Dev Mode Endpoints ====================

    def _get_dev_mode(self):
        """Get current dev mode status."""
        response = self.monitor.get_dev_mode()
        self._send_json_response(200, response)

    def _set_dev_mode(self):
        """Enable or disable dev mode."""
        try:
            data = self._get_request_body()
            enabled = data.get('enabled')

            if not isinstance(enabled, bool):
                self._send_json_response(400, {"error": "'enabled' must be a boolean"})
                return

            result = self.monitor.set_dev_mode(enabled)
            self._send_json_response(200, result)
        except:
            self._send_json_response(400, {"error": "Invalid request"})

    def _trigger_pin(self):
        """Trigger a pin state change in dev mode."""
        try:
            # Extract pin number from path: /api/pins/{pin}/trigger
            parts = self.path.split('/')
            pin = int(parts[3])

            data = self._get_request_body()
            mode = data.get('mode', 'instant')

            if mode not in ['instant', 'endless']:
                self._send_json_response(400, {"error": "Mode must be 'instant' or 'endless'"})
                return

            result = self.monitor.trigger_pin(pin, mode)

            if 'error' in result:
                self._send_json_response(400, result)
            else:
                self._send_json_response(200, result)
        except ValueError:
            self._send_json_response(400, {"error": "Invalid pin number"})
        except:
            self._send_json_response(400, {"error": "Invalid request"})

    # ==================== End Dev Mode Endpoints ====================

    def _get_request_body(self) -> Dict[str, Any]:
        """Get and parse request body."""
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        return json.loads(post_data)

    def _send_json_response(self, code: int, data: Dict[str, Any]):
        """Send JSON response."""
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass