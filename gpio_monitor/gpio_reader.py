#!/usr/bin/python3
"""GPIO hardware interaction for GPIO Monitor."""

import subprocess
from typing import Dict, List, Optional


def get_available_pins() -> List[int]:
    """Get list of all available GPIO pins (standalone function for CLI compatibility)."""
    available_pins = []

    for pin in range(28):
        try:
            result = subprocess.run(
                ['gpioget', 'gpiochip0', str(pin)],
                capture_output=True,
                text=True,
                timeout=0.1
            )
            if result.returncode == 0:
                available_pins.append(pin)
        except:
            pass

    # Fallback to common Raspberry Pi GPIO pins if detection fails
    if not available_pins:
        available_pins = list(range(2, 28))

    return sorted(available_pins)


def get_reserved_pins() -> Dict[int, str]:
    """Get pins with special functions (standalone function for CLI compatibility)."""
    return {
        0: "ID_SD (HAT EEPROM)",
        1: "ID_SC (HAT EEPROM)",
        2: "SDA1 (I2C)",
        3: "SCL1 (I2C)",
        14: "TXD0 (UART)",
        15: "RXD0 (UART)"
    }


class GPIOReader:
    """Handles reading GPIO pins from hardware."""

    @staticmethod
    def get_available_pins() -> List[int]:
        """Get list of all available GPIO pins on this Raspberry Pi."""
        return get_available_pins()

    @staticmethod
    def get_reserved_pins() -> Dict[int, str]:
        """Get pins with special functions."""
        return get_reserved_pins()

    @staticmethod
    def read_pin(pin: int, pull_mode: Optional[str] = None) -> int:
        """
        Read a single GPIO pin value.

        Args:
            pin: GPIO pin number
            pull_mode: Optional pull resistor mode ('up', 'down', or None)

        Returns:
            Pin value (0 or 1), or -1 on error
        """
        try:
            cmd = ['gpioget']

            if pull_mode:
                bias_flag = {
                    'up': 'pull-up',
                    'down': 'pull-down',
                    'none': 'disable'
                }.get(pull_mode, 'disable')
                cmd.append(f'--bias={bias_flag}')

            cmd.extend(['gpiochip0', str(pin)])

            result = subprocess.run(cmd, capture_output=True, text=True)
            return int(result.stdout.strip())
        except:
            return -1