#!/usr/bin/python3
"""Configuration management for GPIO Monitor."""

import json
import os
from typing import Dict, List, Any

CONFIG_FILE = "/etc/gpio-monitor/config.json"
DEFAULT_PORT = 8787


def load_config() -> Dict[str, Any]:
    """Load configuration from file (standalone function for CLI compatibility)."""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {"port": DEFAULT_PORT, "monitored_pins": [], "pin_config": {}}


def save_config(config: Dict[str, Any]) -> None:
    """Save configuration to file (standalone function for CLI compatibility)."""
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)


class ConfigManager:
    """Manages GPIO Monitor configuration."""

    def __init__(self, config_file: str = CONFIG_FILE):
        self.config_file = config_file
        self._ensure_config_dir()

    def _ensure_config_dir(self):
        """Ensure configuration directory exists."""
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)

    def load(self) -> Dict[str, Any]:
        """Load configuration from file."""
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r') as f:
                return json.load(f)
        return self.get_default_config()

    def save(self, config: Dict[str, Any]) -> None:
        """Save configuration to file."""
        self._ensure_config_dir()
        with open(self.config_file, 'w') as f:
            json.dump(config, f, indent=2)

    def get_default_config(self) -> Dict[str, Any]:
        """Get default configuration."""
        return {
            "port": DEFAULT_PORT,
            "monitored_pins": [],
            "pin_config": {}
        }

    def get_config_mtime(self) -> float:
        """Get configuration file modification time."""
        if os.path.exists(self.config_file):
            return os.path.getmtime(self.config_file)
        return 0