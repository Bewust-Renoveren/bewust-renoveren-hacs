# Bewust Renoveren — HACS Integration

Home Assistant custom component for the Bewust Renoveren home monitoring platform.

## Overview

This integration auto-discovers supported sensors in Home Assistant (CO2, temperature, humidity, air pressure, particulates, VOC, energy, and more by `device_class`) and pushes their readings, together with their HA area, to the Bewust Renoveren platform via HTTPS.

## v2 Scope

- Config flow setup wizard: enter an existing API key, or self-register a new customer on-site using an installer code (the server mints the API key automatically)
- Sensor auto-discovery by `device_class` -- no manual room mapping
- Area resolution: entity -> device -> area registry, sent with every reading
- Data push coordinator (15-minute default interval, retry logic 1s/4s/16s)
- Persistent on-disk offline queue (~7 days, oldest-first drain, survives HA restarts)
- Diagnostic sensors: sync status, last sync timestamp, queued batches

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots menu, select "Custom repositories"
3. Add `https://github.com/Bewust-Renoveren/bewust-renoveren-hacs` as an Integration
4. Install "Bewust Renoveren"
5. Restart Home Assistant

### Manual

1. Copy `custom_components/bewust_renoveren/` to your Home Assistant `custom_components/` directory
2. Restart Home Assistant

## Configuration

1. Go to Settings > Devices & Services
2. Click "Add Integration"
3. Search for "Bewust Renoveren"
4. Choose "I have an API key" (enter your key + cloud endpoint) or "Register a new customer" (installer enters the installer code + customer details on-site; the API key is issued automatically)
5. Select the push interval

Sensors are discovered automatically -- no manual room mapping needed.
