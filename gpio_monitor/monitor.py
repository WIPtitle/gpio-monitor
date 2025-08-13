#!/usr/bin/python3
"""Core monitoring logic for GPIO Monitor."""

import json
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple

# Try both relative and absolute imports for compatibility
try:
    from .config import ConfigManager
    from .gpio_reader import GPIOReader
except ImportError:
    from config import ConfigManager
    from gpio_reader import GPIOReader


class GPIOMonitor:
    """Main GPIO monitoring class."""

    POLL_INTERVAL = 0.1

    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
        self.gpio_reader = GPIOReader()

        # State tracking
        self.physical_states: Dict[int, int] = {}
        self.pending_changes: Dict[int, Dict] = {}
        self.clients = []

        # Configuration
        self.monitored_pins: List[int] = []
        self.pin_config: Dict[str, Dict] = {}

        # Threading
        self.config_lock = threading.Lock()

        # Hardware info
        self.available_pins = self.gpio_reader.get_available_pins()
        self.reserved_pins = self.gpio_reader.get_reserved_pins()

        # Initialize
        self.reload_config()
        self._start_config_watcher()

    def get_physical_state(self, pin: int) -> Optional[int]:
        """Get the physical (actual hardware) state of a pin."""
        with self.config_lock:
            return self.physical_states.get(pin)

    def get_virtual_state(self, pin: int) -> Optional[int]:
        """
        Get the virtual (display) state of a pin.
        Applies inversion if configured.
        """
        with self.config_lock:
            physical = self.physical_states.get(pin)
            if physical is None:
                return None

            # Apply inversion if configured
            pin_cfg = self.pin_config.get(str(pin), {})
            if pin_cfg.get('inverted', False):
                return 1 - physical
            return physical

    def get_all_virtual_states(self) -> Dict[int, int]:
        """Get all pin states with inversion applied."""
        virtual_states = {}
        with self.config_lock:
            for pin, physical_state in self.physical_states.items():
                # Apply inversion if configured
                pin_cfg = self.pin_config.get(str(pin), {})
                if pin_cfg.get('inverted', False):
                    virtual_states[pin] = 1 - physical_state
                else:
                    virtual_states[pin] = physical_state
        return virtual_states

    def reload_config(self):
        """Reload configuration and update monitoring."""
        with self.config_lock:
            config = self.config_manager.load()
            self.monitored_pins = config.get("monitored_pins", [])
            self.pin_config = config.get("pin_config", {})

            # Remove states for pins no longer monitored
            for pin in list(self.physical_states.keys()):
                if pin not in self.monitored_pins:
                    del self.physical_states[pin]
                    if pin in self.pending_changes:
                        del self.pending_changes[pin]

            # Initialize states for new pins
            for pin in self.monitored_pins:
                if pin not in self.physical_states and pin in self.available_pins:
                    self._init_pin_state(pin)

    def _init_pin_state(self, pin: int):
        """Initialize state for a single pin."""
        pin_cfg = self.pin_config.get(str(pin), {})
        pull_mode = pin_cfg.get('pull')

        # Check if debouncing is enabled
        if 'debounce_low' in pin_cfg or 'debounce_high' in pin_cfg:
            # Need multiple initial readings for debounced pins
            readings = []
            for _ in range(10):
                value = self.gpio_reader.read_pin(pin, pull_mode)
                if value != -1:
                    readings.append(value)
                time.sleep(0.1)

            if len(readings) >= 6:
                # Use most common value as initial state
                initial_state = max(set(readings), key=readings.count)
                self.physical_states[pin] = initial_state
        else:
            # No debouncing, just read once
            value = self.gpio_reader.read_pin(pin, pull_mode)
            if value != -1:
                self.physical_states[pin] = value

    def _start_config_watcher(self):
        """Start configuration file watcher thread."""
        thread = threading.Thread(target=self._config_watcher, daemon=True)
        thread.start()

    def _config_watcher(self):
        """Watch for configuration file changes."""
        last_mtime = 0
        while True:
            try:
                current_mtime = self.config_manager.get_config_mtime()
                if current_mtime > last_mtime:
                    last_mtime = current_mtime
                    time.sleep(0.1)  # Small delay to ensure file is fully written
                    self.reload_config()
            except:
                pass
            time.sleep(1)

    def _get_debounce_threshold(self, pin: int, target_state: int) -> Optional[int]:
        """
        Get debounce threshold for a pin based on target state.

        Args:
            pin: GPIO pin number
            target_state: The state we're transitioning TO (0 for LOW, 1 for HIGH)

        Returns:
            Threshold value (1-10) or None if no debouncing
        """
        pin_cfg = self.pin_config.get(str(pin), {})

        if target_state == 0:  # Transitioning to LOW
            return pin_cfg.get('debounce_low')
        else:  # Transitioning to HIGH
            return pin_cfg.get('debounce_high')

    def monitor_loop(self):
        """Main monitoring loop."""
        while True:
            with self.config_lock:
                pins_to_monitor = list(self.monitored_pins)

            for pin in pins_to_monitor:
                if pin not in self.available_pins:
                    continue

                self._process_pin(pin)

            time.sleep(self.POLL_INTERVAL)

    def _process_pin(self, pin: int):
        """Process a single pin reading."""
        pin_cfg = self.pin_config.get(str(pin), {})
        pull_mode = pin_cfg.get('pull')

        current_reading = self.gpio_reader.read_pin(pin, pull_mode)
        if current_reading == -1:
            return

        with self.config_lock:
            if pin not in self.physical_states:
                return

            current_state = self.physical_states[pin]
            debounce_threshold = self._get_debounce_threshold(pin, current_reading)

            if debounce_threshold is None:
                # No debouncing - immediate state change
                if current_reading != current_state:
                    self._handle_state_change(pin, current_reading)
            else:
                # With debouncing
                self._process_debounced_pin(pin, current_reading, current_state, debounce_threshold)

    def _process_debounced_pin(self, pin: int, current_reading: int,
                               current_state: int, threshold: int):
        """Process pin with debouncing logic."""
        if current_reading != current_state:
            # State might be changing
            if pin not in self.pending_changes:
                self.pending_changes[pin] = {
                    'readings': [current_reading],
                    'old_state': current_state,
                    'new_state': current_reading
                }
            else:
                pending = self.pending_changes[pin]
                pending['readings'].append(current_reading)

                if len(pending['readings']) >= 10:
                    new_state_count = pending['readings'].count(pending['new_state'])

                    if new_state_count >= threshold:
                        self._handle_state_change(pin, pending['new_state'],
                                                  confidence=f"{new_state_count}/10")

                    del self.pending_changes[pin]
        else:
            # Current reading matches current state
            if pin in self.pending_changes:
                pending = self.pending_changes[pin]
                pending['readings'].append(current_reading)

                if len(pending['readings']) >= 10:
                    new_state_count = pending['readings'].count(pending['new_state'])
                    target_threshold = self._get_debounce_threshold(pin, pending['new_state'])

                    if new_state_count >= target_threshold:
                        self._handle_state_change(pin, pending['new_state'],
                                                  confidence=f"{new_state_count}/10")

                    del self.pending_changes[pin]

    def _handle_state_change(self, pin: int, new_physical_state: int,
                             confidence: Optional[str] = None):
        """Handle a confirmed state change."""
        self.physical_states[pin] = new_physical_state

        # Get virtual state for display (apply inversion if configured)
        pin_cfg = self.pin_config.get(str(pin), {})
        if pin_cfg.get('inverted', False):
            new_virtual_state = 1 - new_physical_state
        else:
            new_virtual_state = new_physical_state

        # Create event data
        event_data = {
            "pin": pin,
            "state": new_virtual_state,
            "timestamp": int(time.time() * 1000),
            "time": datetime.now().strftime("%H:%M:%S.%f")[:-3]
        }

        if confidence:
            event_data["confidence"] = confidence

        self.broadcast_event("gpio_change", event_data)

    def broadcast_event(self, event_type: str, data: Dict[str, Any]):
        """Broadcast event to all connected clients."""
        message = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

        # Clean up closed clients
        self.clients = [c for c in self.clients if not c.closed]

        # Send to all clients
        for client in self.clients:
            try:
                client.write(message.encode())
                client.flush()
            except:
                pass