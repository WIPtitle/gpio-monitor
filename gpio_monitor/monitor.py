#!/usr/bin/python3
"""Core monitoring logic for GPIO Monitor."""

import json
import queue
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
    INSTANT_TRIGGER_DURATION = 1.0  # seconds

    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
        self.gpio_reader = GPIOReader()

        # State tracking
        self.physical_states: Dict[int, int] = {}
        self.pending_changes: Dict[int, Dict] = {}

        # SSE subscribers: each is its own fresh, empty queue.Queue so a new
        # subscriber only ever receives events broadcast after it subscribes
        # (never a backlog), and one slow/flaky client can never block
        # delivery to the others (or to the monitor loop).
        self.clients: List["queue.Queue[str]"] = []
        self.clients_lock = threading.Lock()

        # Configuration
        self.monitored_pins: List[int] = []
        self.pin_config: Dict[str, Dict] = {}

        # Threading
        self.config_lock = threading.Lock()

        # Hardware info
        self.available_pins = self.gpio_reader.get_available_pins()
        self.reserved_pins = self.gpio_reader.get_reserved_pins()

        # Dev mode state - completely separate from real mode
        self.dev_mode = False
        self.dev_monitored_pins: List[int] = []  # Pins monitored in dev mode (in-memory only)
        self.dev_pin_states: Dict[int, int] = {}  # Simulated states in dev mode
        self.instant_triggers: Dict[int, Tuple[float, int]] = {}  # pin -> (end_time, original_state)
        self.dev_available_pins = list(range(28))  # All pins 0-27 available in dev mode

        # Initialize
        self.reload_config()
        self._start_config_watcher()

    def get_current_monitored_pins(self) -> List[int]:
        """Get the list of currently monitored pins based on mode."""
        with self.config_lock:
            return list(self.dev_monitored_pins if self.dev_mode else self.monitored_pins)

    def get_current_available_pins(self) -> List[int]:
        """Get the list of available pins based on mode."""
        with self.config_lock:
            return list(self.dev_available_pins if self.dev_mode else self.available_pins)

    def get_physical_state(self, pin: int) -> Optional[int]:
        """Get the physical (actual hardware or dev mode) state of a pin."""
        with self.config_lock:
            if self.dev_mode:
                if pin not in self.dev_monitored_pins:
                    return None
                return self.dev_pin_states.get(pin)
            if pin not in self.monitored_pins:
                return None
            return self.physical_states.get(pin)

    def get_virtual_state(self, pin: int) -> Optional[int]:
        """
        Get the virtual (display) state of a pin.
        Applies inversion if configured (only in real mode, dev mode has no config).
        """
        with self.config_lock:
            if self.dev_mode:
                if pin not in self.dev_monitored_pins:
                    return None
                # Dev mode: no inversion, just return raw state
                return self.dev_pin_states.get(pin)
            else:
                if pin not in self.monitored_pins:
                    return None
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
            if self.dev_mode:
                # Dev mode: return dev states directly (no inversion)
                for pin in self.dev_monitored_pins:
                    virtual_states[pin] = self.dev_pin_states.get(pin, 0)
            else:
                # Real mode: apply inversion from config
                for pin in self.monitored_pins:
                    physical_state = self.physical_states.get(pin)
                    if physical_state is not None:
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

            if self.dev_mode:
                # Dev mode: manage dev_pin_states
                for pin in list(self.dev_pin_states.keys()):
                    if pin not in self.monitored_pins:
                        del self.dev_pin_states[pin]
                        if pin in self.instant_triggers:
                            del self.instant_triggers[pin]

                # Initialize new pins with LOW (0)
                for pin in self.monitored_pins:
                    if pin not in self.dev_pin_states:
                        self.dev_pin_states[pin] = 0
            else:
                # Real mode: manage physical_states
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

    # ==================== Dev Mode Methods ====================

    def set_dev_mode(self, enabled: bool) -> Dict[str, Any]:
        """
        Enable or disable dev mode.
        Dev mode is completely separate from real mode - separate pins, separate states.
        """
        with self.config_lock:
            if enabled and not self.dev_mode:
                # Entering dev mode - start fresh (don't copy from real mode)
                # Keep existing dev pins if any, or start empty
                pass
            elif not enabled and self.dev_mode:
                # Exiting dev mode - clear dev states and instant triggers
                self.dev_monitored_pins.clear()
                self.dev_pin_states.clear()
                self.instant_triggers.clear()

            self.dev_mode = enabled
            return {"dev_mode": self.dev_mode}

    def get_dev_mode(self) -> Dict[str, Any]:
        """Get current dev mode status."""
        with self.config_lock:
            return {
                "dev_mode": self.dev_mode,
                "dev_pins": list(self.dev_monitored_pins),
                "instant_triggers": {
                    pin: {
                        "remaining": max(0, end_time - time.time()),
                        "original_state": orig_state
                    }
                    for pin, (end_time, orig_state) in self.instant_triggers.items()
                }
            }

    def add_dev_pin(self, pin: int) -> Dict[str, Any]:
        """Add a pin in dev mode (in-memory only, not persisted)."""
        with self.config_lock:
            if not self.dev_mode:
                return {"error": "Dev mode is not enabled"}

            if pin < 0 or pin > 27:
                return {"error": f"Invalid pin {pin}. Must be 0-27"}

            if pin in self.dev_monitored_pins:
                return {"error": f"Pin {pin} already monitored in dev mode"}

            self.dev_monitored_pins.append(pin)
            self.dev_monitored_pins.sort()
            self.dev_pin_states[pin] = 0  # Default to LOW

            return {
                "message": f"Added GPIO {pin} to dev mode monitoring",
                "monitored": list(self.dev_monitored_pins)
            }

    def remove_dev_pin(self, pin: int) -> Dict[str, Any]:
        """Remove a pin in dev mode."""
        with self.config_lock:
            if not self.dev_mode:
                return {"error": "Dev mode is not enabled"}

            if pin not in self.dev_monitored_pins:
                return {"error": f"Pin {pin} not monitored in dev mode"}

            self.dev_monitored_pins.remove(pin)
            if pin in self.dev_pin_states:
                del self.dev_pin_states[pin]
            if pin in self.instant_triggers:
                del self.instant_triggers[pin]

            return {
                "message": f"Removed GPIO {pin} from dev mode monitoring",
                "monitored": list(self.dev_monitored_pins)
            }

    def trigger_pin(self, pin: int, mode: str) -> Dict[str, Any]:
        """
        Trigger a pin state change in dev mode.

        Args:
            pin: GPIO pin number
            mode: "instant" (1 second then revert) or "endless" (permanent toggle)

        Returns:
            Result dict with new state info
        """
        with self.config_lock:
            if not self.dev_mode:
                return {"error": "Dev mode is not enabled"}

            if pin not in self.dev_monitored_pins:
                return {"error": f"Pin {pin} is not being monitored in dev mode"}

            # Get current state (from dev states or default to 0)
            current_state = self.dev_pin_states.get(pin, 0)
            new_state = 1 - current_state  # Toggle

            if mode == "instant":
                # Check if already in instant trigger
                if pin in self.instant_triggers:
                    return {"error": f"Pin {pin} is already in instant trigger mode"}

                # Store original state and set end time
                self.instant_triggers[pin] = (
                    time.time() + self.INSTANT_TRIGGER_DURATION,
                    current_state
                )
                self.dev_pin_states[pin] = new_state

            elif mode == "endless":
                # Clear any instant trigger for this pin
                if pin in self.instant_triggers:
                    del self.instant_triggers[pin]
                self.dev_pin_states[pin] = new_state

            else:
                return {"error": f"Invalid mode '{mode}'. Use 'instant' or 'endless'"}

            # Trigger the state change event
            self._handle_state_change(pin, new_state)

            return {
                "pin": pin,
                "mode": mode,
                "new_state": new_state,
                "reverts_at": self.instant_triggers[pin][0] if pin in self.instant_triggers else None
            }

    def _check_instant_triggers(self):
        """Check and revert any expired instant triggers."""
        current_time = time.time()
        expired = []

        with self.config_lock:
            for pin, (end_time, original_state) in self.instant_triggers.items():
                if current_time >= end_time:
                    expired.append((pin, original_state))

            for pin, original_state in expired:
                del self.instant_triggers[pin]
                self.dev_pin_states[pin] = original_state
                self._handle_state_change(pin, original_state)

    # ==================== End Dev Mode Methods ====================

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
            # Check for expired instant triggers in dev mode
            if self.dev_mode:
                self._check_instant_triggers()

            with self.config_lock:
                pins_to_monitor = list(self.monitored_pins)
                is_dev_mode = self.dev_mode

            for pin in pins_to_monitor:
                # In dev mode, all pins are available
                if not is_dev_mode and pin not in self.available_pins:
                    continue

                # In dev mode, we don't poll hardware - state changes come from API
                if not is_dev_mode:
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

    def subscribe(self) -> "queue.Queue[str]":
        """
        Register a new SSE subscriber.

        Returns a brand-new, empty queue that will only ever receive events
        broadcast from this point forward - no historical/buffered events.
        """
        client_queue: "queue.Queue[str]" = queue.Queue(maxsize=1000)
        with self.clients_lock:
            self.clients.append(client_queue)
        return client_queue

    def unsubscribe(self, client_queue: "queue.Queue[str]") -> None:
        """Remove a subscriber's queue, e.g. once its connection drops."""
        with self.clients_lock:
            if client_queue in self.clients:
                self.clients.remove(client_queue)

    def broadcast_event(self, event_type: str, data: Dict[str, Any]):
        """Broadcast event to all connected clients (non-blocking)."""
        message = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

        with self.clients_lock:
            clients_snapshot = list(self.clients)

        # Enqueue for each subscriber; never blocks on a client's own socket
        # I/O, so a stalled/flaky client can't delay delivery to anyone else.
        for client_queue in clients_snapshot:
            try:
                client_queue.put_nowait(message)
            except queue.Full:
                pass