# GPIO monitoring service

This is a utility service that monitors GPIO pins on a Raspberry Pi and sends server side events when the state of the pins changes.

## What it does

The service continuously monitors selected GPIO pins and emits real-time events when their state changes (HIGH/LOW). It provides:
- Server-Sent Events (SSE) for real-time state notifications
- REST API for dynamic pin management
- Web dashboard for visual monitoring and managing
- CLI utility for system administration
- Configurable debouncing to filter noise from mechanical switches or electrically noisy environments
- Pull resistor configuration (up/down/none) for proper pin biasing

## How it works

The service runs as a systemd daemon that polls configured GPIO pins every 0.1 seconds. When a state change is detected, it broadcasts an SSE event to all connected clients. The service watches its configuration file for changes and automatically reloads without requiring restarts (except for port changes).

Configuration is stored in `/etc/gpio-monitor/config.json` and includes the monitored pins list, port settings, and per-pin configurations (pull resistors, debouncing levels).

## Installation

You can build your own deb package by using the build-deb.sh script:
```bash
./build-deb.sh
sudo dpkg -i build/gpio-monitor_*_all.deb
```

## Usage

Once installed, you can run `gpio-monitor help` to see the available commands.
You can change the exposed port, add and remove pins from monitoring, and optionally set debouncing for each one of them.

You can listen to the server side events on the `/events` endpoint, but you can also use the console exposed on the root endpoint to see the registered pins and their current status and logs.

### Web Interface
Access the monitoring dashboard at `http://localhost:8787`

### REST API
Complete REST API documentation is available in the `gpio-monitor-openapi.yaml` file, which can be imported into Postman or any OpenAPI-compatible tool. The API allows full CRUD operations on pins and their configurations.

### CLI Commands
The `gpio-monitor` command provides system-level control:
- Pin management (add-pin, remove-pin, list-pins, clear-pins)
- Pin configuration (set-pull, set-debounce, remove-debounce)
- Service control (status, set-port, restart, stop, start, logs)

## Quick explanation on debouncing

Debouncing is a technique used to ensure that only one event is triggered when a button is pressed or released, even if the button's mechanical contacts bounce. This is important for GPIO monitoring to avoid multiple events being sent for a single action.

If some of your pins seem to trigger multiple times when they really should trigger only one time, try to set debouncing values for the affected pins.

The debouncing is asymmetrical: you can set a value for both LOW and HIGH states, which means that the LOW status will be confirmed with an event only when the monitor reads more LOW statuses out of 10 than it's debouncing value, and the same applies to HIGH status and it's debouncing value.

As an example: long cables or electrically noisy environments can cause wrongly triggered events, like a magnetic reed sensor that jumps between open and closed (particularly when the circuit is not closed, since it works like an antenna and it picks up noise): debouncing fixes this essentially ignoring the status change if it's not consistent a certain amount of times.

Note: you can also use debouncing as a confidence level for your sensors, for example if you have a motion sensor setting a debouncing value could help minimize fake readings. 

## System Requirements

- Raspberry Pi with GPIO pins
- Python 3.7 or higher
- Systemd

## Configuration

The service configuration is stored in `/etc/gpio-monitor/config.json`. Changes to this file are automatically detected and applied without service restart (except for port changes).

### Reserved GPIO Pins
Some pins have special functions:
- GPIO 0-1: HAT EEPROM
- GPIO 2-3: I2C interface
- GPIO 14-15: UART interface

The service will warn when adding these pins but allows monitoring if needed.

## Uninstallation

```bash
# Remove package
sudo dpkg -r gpio-monitor

# Remove package and all data
sudo dpkg -r --purge mp3-player-server
```