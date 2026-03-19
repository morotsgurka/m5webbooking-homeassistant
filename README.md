# M5 Web Booking | Home Assistant Integration

![M5 Web Booking](custom_components/m5webbooking/brand/logo.png)

Custom Home Assistant integration for Electrolux M5 Web Booking, also known as ELS Boka Direkt.

## What It Does

- Creates one binary sensor per resource/room to show if it is currently occupied.
- Creates a calendar entity with your own bookings.
- Makes it easy to build automations for notifications or announcements in your home.

## Installation

### HACS (recommended)
If you do not have HACS installed yet, visit https://hacs.xyz for installation instructions.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=morotsgurka&repository=m5webbooking-homeassistant&category=integration)

1. Open HACS in Home Assistant.
2. Add this repository as a custom integration repository.
3. Install **M5 Web Booking**.
4. Restart Home Assistant.
5. Go to **Settings -> Devices & services -> Add integration** and add **M5 Web Booking**.

### Manual

1. Copy `custom_components/m5webbooking` into your Home Assistant `config/custom_components` folder.
2. Restart Home Assistant.
3. Add the integration from **Settings -> Devices & services**.

## Configuration

Configuration is done through the Home Assistant UI when you add the integration.

You provide:
- Address/endpoint to your M5 Web Booking instance
- Username
- Password

## Debug Logging

If you need to troubleshoot, enable debug logging in `configuration.yaml`:

```yaml
logger:
	default: warning
	logs:
		custom_components.m5webbooking: debug
```