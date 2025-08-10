# GPIO monitoring service
This is a utility service that monitors GPIO pins on a Raspberry Pi and sends server side events when the state of the pins changes.
It consists of a no-dependencies Python script and a CLI utility.

## Installation
You can build your own deb package by using the build-deb.sh script.
Install it as any other deb package, e.g. `sudo dpkg -i gpio-monitoring_0.1.0_all.deb`.

## Usage
Once installed, you can run `gpio-monitor help` to see the available commands.
You can change the exposed port, add and remove pins from monitoring, and optionally set debouncing for each one of them.

You can listen to the server side events on the `/events` endpoint, but you can also use
the console exposed on the root endpoint to see the registered pins and their current status and logs.

### Quick explanation on debouncing
Debouncing is a technique used to ensure that only one event is triggered when a button is pressed or released, even if the button's mechanical contacts bounce. This is important for GPIO monitoring to avoid multiple events being sent for a single action.

If some of your pins seem to trigger multiple times when they really should trigger only one time, try to set a debouncing value for the affected pins.

You can set the debouncing value to LOW, MEDIUM or HIGH: it means, respectively, 3, 5 or 7 values read in 10 tries for considering the status changed.
This script polls every pin every 0.1 seconds, so activating debouncing means a delay of one second in change of a certain confidence level.

As an example: long cables or electrically noisy environments can cause wrongly triggered events, like a magnetic reed sensor that jumps between open and closed (particularly when the circuit is not closed, since it works like an antenna and it picks up noise): debouncing fixes this essentially ignoring the status change if it's not consistent a certain amount of times.
