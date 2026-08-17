#!/usr/bin/python3
"""Configuration management for GPIO Monitor."""

import json
import os
import tempfile
from typing import Dict, List, Any

# Config path from env var, default to /etc for production
CONFIG_FILE = os.environ.get("GPIO_MONITOR_CONFIG_PATH", "/etc/gpio-monitor/config.json")
DEFAULT_PORT = 8787


def load_config() -> Dict[str, Any]:
    """Load configuration from file (standalone function for CLI compatibility)."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            # Corrupt/truncated config -> fall back to defaults instead of crashing.
            pass
    return {"port": DEFAULT_PORT, "monitored_pins": [], "pin_config": {}}


def atomic_write_json(path: str, data: Dict[str, Any]) -> None:
    """Crash-safe JSON write: temp file + fsync + atomic rename + dir fsync.

    On power loss the target is left as either the complete old file or the
    complete new one -- never truncated.
    """
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
        dir_fd = os.open(directory, os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save_config(config: Dict[str, Any]) -> None:
    """Save configuration to file (standalone function for CLI compatibility)."""
    atomic_write_json(CONFIG_FILE, config)


class ConfigManager:
    """Manages GPIO Monitor configuration."""

    def __init__(self, config_file: str = CONFIG_FILE):
        self.config_file = config_file
        self._ensure_config_dir()

    def _ensure_config_dir(self):
        """Ensure configuration directory exists."""
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)

    def load(self) -> Dict[str, Any]:
        """Load configuration from file. Creates default config if not exists."""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                # Corrupt/truncated config -> recreate a fresh default below.
                pass
        # Create default config file (missing or corrupt)
        default_config = self.get_default_config()
        self.save(default_config)
        return default_config

    def save(self, config: Dict[str, Any]) -> None:
        """Save configuration to file (crash-safe atomic write)."""
        self._ensure_config_dir()
        atomic_write_json(self.config_file, config)

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