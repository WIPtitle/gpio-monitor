#!/usr/bin/python3

import sys
import json
import os
import subprocess

CONFIG_FILE = "/etc/gpio-monitor/config.json"
SERVICE_NAME = "gpio-monitor.service"


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {"port": 8787, "monitored_pins": [], "pin_config": {}}


def save_config(config):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)


def get_available_pins():
    """Test which GPIO pins are available"""
    available = []
    for pin in range(28):
        try:
            result = subprocess.run(['gpioget', 'gpiochip0', str(pin)],
                                    capture_output=True, text=True, timeout=0.1)
            if result.returncode == 0:
                available.append(pin)
        except:
            pass

    if not available:
        available = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
                     16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27]

    return sorted(available)


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


def add_pin(pin):
    try:
        pin = int(pin)
        available = get_available_pins()
        reserved = get_pin_info()

        if pin not in available:
            print(f"Error: GPIO {pin} is not available on this device")
            print(f"Available pins: {available}")
            sys.exit(1)

        if pin in reserved:
            print(f"Warning: GPIO {pin} has a special function: {reserved[pin]}")
            print("This pin may not work correctly if the function is in use")
            response = input("Continue anyway? (y/N): ")
            if response.lower() != 'y':
                print("Aborted")
                sys.exit(0)

        config = load_config()
        monitored = config.get("monitored_pins", [])

        if pin in monitored:
            print(f"GPIO {pin} is already being monitored")
        else:
            monitored.append(pin)
            monitored.sort()
            config["monitored_pins"] = monitored
            save_config(config)
            print(f"Added GPIO {pin} to monitoring")
            print(f"Currently monitoring: {monitored}")

    except ValueError:
        print("Error: Invalid pin number")
        sys.exit(1)


def remove_pin(pin):
    try:
        pin = int(pin)
        config = load_config()
        monitored = config.get("monitored_pins", [])

        if pin not in monitored:
            print(f"GPIO {pin} is not being monitored")
        else:
            monitored.remove(pin)
            config["monitored_pins"] = monitored

            # Also remove pin configuration
            pin_config = config.get("pin_config", {})
            if str(pin) in pin_config:
                del pin_config[str(pin)]
                config["pin_config"] = pin_config

            save_config(config)
            print(f"Removed GPIO {pin} from monitoring")
            print(f"Currently monitoring: {monitored if monitored else 'None'}")

    except ValueError:
        print("Error: Invalid pin number")
        sys.exit(1)


def set_inverted(pin):
    """Set inverted logic for a GPIO pin"""
    try:
        pin = int(pin)

        config = load_config()
        monitored = config.get("monitored_pins", [])

        if pin not in monitored:
            print(f"Error: GPIO {pin} is not being monitored")
            print(f"Add it first with: gpio-monitor add-pin {pin}")
            sys.exit(1)

        pin_config = config.get("pin_config", {})
        if str(pin) not in pin_config:
            pin_config[str(pin)] = {}

        pin_config[str(pin)]['inverted'] = True

        print(f"Set GPIO {pin} to inverted logic")
        print("Pin will now show HIGH when physically LOW and vice versa")

        config["pin_config"] = pin_config
        save_config(config)

    except ValueError:
        print("Error: Invalid pin number")
        sys.exit(1)


def remove_inverted(pin):
    """Remove inverted logic for a GPIO pin"""
    try:
        pin = int(pin)

        config = load_config()
        monitored = config.get("monitored_pins", [])

        if pin not in monitored:
            print(f"Error: GPIO {pin} is not being monitored")
            sys.exit(1)

        pin_config = config.get("pin_config", {})
        if str(pin) in pin_config and 'inverted' in pin_config[str(pin)]:
            del pin_config[str(pin)]['inverted']
            print(f"Removed inverted logic from GPIO {pin}")
            print("Pin will now show actual physical state")
        else:
            print(f"GPIO {pin} does not have inverted logic configured")

        config["pin_config"] = pin_config
        save_config(config)

    except ValueError:
        print("Error: Invalid pin number")
        sys.exit(1)


def set_debounce(args):
    """Set debounce thresholds for a GPIO pin

    Expected format: <pin> LOW <low_value> HIGH <high_value>
    """
    if len(args) != 5:
        print("Error: Invalid format")
        print("Usage: gpio-monitor set-debounce <pin> LOW <1-10> HIGH <1-10>")
        print("Example: gpio-monitor set-debounce 17 LOW 6 HIGH 8")
        sys.exit(1)

    try:
        pin = int(args[0])

        # Parse LOW and HIGH values
        low_idx = args.index('LOW') if 'LOW' in args else -1
        high_idx = args.index('HIGH') if 'HIGH' in args else -1

        if low_idx == -1 or high_idx == -1:
            print("Error: Must specify both LOW and HIGH thresholds")
            print("Usage: gpio-monitor set-debounce <pin> LOW <1-10> HIGH <1-10>")
            sys.exit(1)

        low_value = int(args[low_idx + 1])
        high_value = int(args[high_idx + 1])

        # Validate values
        if not (1 <= low_value <= 10) or not (1 <= high_value <= 10):
            print("Error: Threshold values must be between 1 and 10")
            print("  1  = minimum filtering (fastest response)")
            print("  5  = balanced filtering")
            print("  10 = maximum filtering (most stable)")
            sys.exit(1)

        config = load_config()
        monitored = config.get("monitored_pins", [])

        if pin not in monitored:
            print(f"Error: GPIO {pin} is not being monitored")
            print(f"Add it first with: gpio-monitor add-pin {pin}")
            sys.exit(1)

        pin_config = config.get("pin_config", {})
        if str(pin) not in pin_config:
            pin_config[str(pin)] = {}

        pin_config[str(pin)]['debounce_low'] = low_value
        pin_config[str(pin)]['debounce_high'] = high_value

        print(f"Set GPIO {pin} debouncing:")
        print(f"  HIGH→LOW transition: {low_value}/10 readings required")
        print(f"  LOW→HIGH transition: {high_value}/10 readings required")
        print("Events will be delayed by ~1 second for stability")

        config["pin_config"] = pin_config
        save_config(config)

    except ValueError as e:
        print(f"Error: Invalid value - {e}")
        print("Usage: gpio-monitor set-debounce <pin> LOW <1-10> HIGH <1-10>")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


def remove_debounce(pin):
    """Remove debounce configuration for a GPIO pin"""
    try:
        pin = int(pin)

        config = load_config()
        monitored = config.get("monitored_pins", [])

        if pin not in monitored:
            print(f"Error: GPIO {pin} is not being monitored")
            sys.exit(1)

        pin_config = config.get("pin_config", {})
        removed = False

        if str(pin) in pin_config:
            if 'debounce_low' in pin_config[str(pin)]:
                del pin_config[str(pin)]['debounce_low']
                removed = True
            if 'debounce_high' in pin_config[str(pin)]:
                del pin_config[str(pin)]['debounce_high']
                removed = True

        if removed:
            print(f"Removed debouncing from GPIO {pin}")
            print("Events will now be emitted immediately on state change")
        else:
            print(f"GPIO {pin} does not have debouncing configured")

        config["pin_config"] = pin_config
        save_config(config)

    except ValueError:
        print("Error: Invalid pin number")
        sys.exit(1)


def list_pins():
    config = load_config()
    monitored = config.get("monitored_pins", [])
    available = get_available_pins()
    reserved = get_pin_info()
    pin_config = config.get("pin_config", {})

    print("GPIO Pin Status")
    print("-" * 60)
    print(f"Monitored pins: {monitored if monitored else 'None'}")
    print(f"Available pins: {available}")

    if monitored:
        print("\nPin Configuration:")
        for pin in monitored:
            configs = []
            if str(pin) in pin_config:
                cfg = pin_config[str(pin)]
                if 'pull' in cfg:
                    configs.append(f"pull-{cfg['pull']}")
                if 'debounce_low' in cfg and 'debounce_high' in cfg:
                    configs.append(f"debounce(L:{cfg['debounce_low']}/10, H:{cfg['debounce_high']}/10)")
                if cfg.get('inverted', False):
                    configs.append("INVERTED")

            config_str = ", ".join(configs) if configs else "no special config"
            print(f"  GPIO {pin:2d}: {config_str}")

    if reserved:
        print("\nPins with special functions:")
        for pin, function in sorted(reserved.items()):
            status = " (MONITORED)" if pin in monitored else ""
            print(f"  GPIO {pin:2d}: {function}{status}")

    safe_pins = [p for p in available if p not in reserved]
    print(f"\nGeneral purpose pins: {safe_pins}")

    not_monitored = [p for p in available if p not in monitored]
    if not_monitored:
        print(f"Not monitored: {not_monitored}")


def clear_pins():
    config = load_config()
    config["monitored_pins"] = []
    config["pin_config"] = {}  # Also clear pin configurations
    save_config(config)
    print("Cleared all monitored pins")


def set_port(port):
    try:
        port = int(port)
        if port < 1 or port > 65535:
            print("Error: Port must be between 1 and 65535")
            sys.exit(1)

        config = load_config()
        old_port = config.get("port", 8787)

        if old_port == port:
            print(f"Port is already set to {port}")
            return

        config["port"] = port
        save_config(config)

        print(f"Port set to {port}")
        print("Port changes require service restart")
        restart_service()

    except ValueError:
        print("Error: Invalid port number")
        sys.exit(1)


def restart_service():
    print("Restarting service...")
    try:
        subprocess.run(["systemctl", "restart", SERVICE_NAME], check=True)
        print("Service restarted successfully")
    except subprocess.CalledProcessError:
        print("Error: Failed to restart service")
        print("Try: sudo systemctl restart gpio-monitor")


def get_status():
    config = load_config()
    monitored = config.get("monitored_pins", [])
    port = config.get("port", 8787)

    print(f"Current port: {port}")
    print(f"Monitored pins: {monitored if monitored else 'None'}")

    try:
        result = subprocess.run(["systemctl", "is-active", SERVICE_NAME],
                                capture_output=True, text=True)
        status = result.stdout.strip()
        print(f"Service status: {status}")

        if status == "active":
            print(f"Web interface: http://localhost:{port}")
    except:
        print("Service status: unknown")


def set_pull(pin, mode):
    """Set pull resistor for a GPIO pin"""
    try:
        pin = int(pin)
        if mode not in ['up', 'down', 'none']:
            print("Error: Mode must be 'up', 'down', or 'none'")
            sys.exit(1)

        config = load_config()
        monitored = config.get("monitored_pins", [])

        if pin not in monitored:
            print(f"Error: GPIO {pin} is not being monitored")
            print(f"Add it first with: gpio-monitor add-pin {pin}")
            sys.exit(1)

        pin_config = config.get("pin_config", {})
        if str(pin) not in pin_config:
            pin_config[str(pin)] = {}

        if mode == 'none':
            pin_config[str(pin)].pop('pull', None)
            print(f"Removed pull resistor configuration for GPIO {pin}")
        else:
            pin_config[str(pin)]['pull'] = mode
            print(f"Set GPIO {pin} to pull-{mode}")
            print(f"GPIO {pin} will be read with pull-{mode} bias")

        config["pin_config"] = pin_config
        save_config(config)

    except ValueError:
        print("Error: Invalid pin number")
        sys.exit(1)


def show_help():
    print("GPIO Monitor Control")
    print("")
    print("Pin Management:")
    print("  gpio-monitor add-pin <pin>           Add a GPIO pin to monitor")
    print("  gpio-monitor remove-pin <pin>        Remove a GPIO pin from monitoring")
    print("  gpio-monitor list-pins               List all monitored and available pins")
    print("  gpio-monitor clear-pins              Remove all pins from monitoring")
    print("")
    print("Pin Configuration:")
    print("  gpio-monitor set-pull <pin> <mode>   Set pull resistor (up/down/none)")
    print("  gpio-monitor set-debounce <pin> LOW <1-10> HIGH <1-10>")
    print("                                        Set asymmetric debouncing thresholds")
    print("  gpio-monitor remove-debounce <pin>   Remove debouncing")
    print("  gpio-monitor set-inverted <pin>      Set inverted logic when reading state (HIGH ↔ LOW) (doesn't change internal state")
    print("  gpio-monitor remove-inverted <pin>   Remove inverted logic")
    print("")
    print("Service Control:")
    print("  gpio-monitor status                  Show current configuration and status")
    print("  gpio-monitor set-port <port>         Set the monitor port (requires restart)")
    print("  gpio-monitor restart                  Restart the monitor service")
    print("  gpio-monitor stop                     Stop the monitor service")
    print("  gpio-monitor start                    Start the monitor service")
    print("  gpio-monitor logs                     Show service logs")
    print("")
    print("REST API:")
    print("  OpenAPI schema: /usr/share/doc/gpio-monitor/gpio-monitor-openapi.yaml")
    print("")
    print("Debounce thresholds (1-10):")
    print("  LOW threshold:  Applied for HIGH → LOW transitions")
    print("  HIGH threshold: Applied for LOW → HIGH transitions")
    print("  1  = one read of value for status change ")
    print("  5  = five reads of value for status change")
    print("  10 = ten reads of value for status change")
    print("")
    print("Example:")
    print("  gpio-monitor set-debounce 17 LOW 6 HIGH 8")
    print("  → Requires 6/10 readings of LOW for HIGH → LOW transition")
    print("  → Requires 8/10 readings of HIGH for LOW → HIGH transition")


def main():
    if len(sys.argv) < 2:
        show_help()
        sys.exit(0)

    command = sys.argv[1]

    if command == "status":
        get_status()
    elif command == "add-pin" and len(sys.argv) == 3:
        add_pin(sys.argv[2])
    elif command == "remove-pin" and len(sys.argv) == 3:
        remove_pin(sys.argv[2])
    elif command == "set-pull" and len(sys.argv) == 4:
        set_pull(sys.argv[2], sys.argv[3])
    elif command == "set-debounce" and len(sys.argv) >= 7:
        # Pass all arguments after 'set-debounce' and pin number
        set_debounce(sys.argv[2:])
    elif command == "remove-debounce" and len(sys.argv) == 3:
        remove_debounce(sys.argv[2])
    elif command == "set-inverted" and len(sys.argv) == 3:
        set_inverted(sys.argv[2])
    elif command == "remove-inverted" and len(sys.argv) == 3:
        remove_inverted(sys.argv[2])
    elif command == "list-pins":
        list_pins()
    elif command == "clear-pins":
        clear_pins()
    elif command == "set-port" and len(sys.argv) == 3:
        set_port(sys.argv[2])
    elif command == "restart":
        subprocess.run(["systemctl", "restart", SERVICE_NAME])
        print("Service restarted")
    elif command == "stop":
        subprocess.run(["systemctl", "stop", SERVICE_NAME])
        print("Service stopped")
    elif command == "start":
        subprocess.run(["systemctl", "start", SERVICE_NAME])
        print("Service started")
    elif command == "logs":
        subprocess.run(["journalctl", "-u", SERVICE_NAME, "-n", "50", "--no-pager"])
    elif command == "help" or command == "--help" or command == "-h":
        show_help()
    else:
        print(f"Unknown command: {command}")
        print("Use 'gpio-monitor help' for usage information")
        sys.exit(1)


if __name__ == "__main__":
    main()