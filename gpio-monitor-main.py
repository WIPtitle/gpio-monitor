#!/usr/bin/python3
"""Main entry point for GPIO Monitor server."""

import os
import sys
import socketserver
import threading

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gpio_monitor import ConfigManager, GPIOMonitor, GPIORequestHandler


def main():
    """Start the GPIO Monitor server."""
    # Initialize configuration
    config_manager = ConfigManager()
    config = config_manager.load()
    port = config.get("port", 8787)

    # Initialize monitor
    monitor = GPIOMonitor(config_manager)

    # Set HTML file path
    html_file = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "web",
        "index.html"
    )

    # Set monitor and html_file as class attributes
    GPIORequestHandler.monitor = monitor
    GPIORequestHandler.html_file = html_file

    # Start monitoring thread
    monitor_thread = threading.Thread(target=monitor.monitor_loop, daemon=True)
    monitor_thread.start()

    # Start HTTP server
    with socketserver.ThreadingTCPServer(("", port), GPIORequestHandler) as httpd:
        print(f"GPIO Monitor started on port {port}")
        print(f"Web interface: http://localhost:{port}")
        httpd.serve_forever()


if __name__ == '__main__':
    main()