# Bewust Renoveren — HACS Integration

Home Assistant custom component for the Bewust Renoveren home monitoring platform.

## Overview

This integration collects sensor data from Home Assistant (CO2, temperature, humidity, pressure) and pushes it to the Bewust Renoveren cloud platform via HTTPS.

## Phase 1 Scope

- Config flow setup wizard (API key + cloud endpoint)
- Sensor selector: map HA entities per room
- Data push coordinator (5-minute interval, retry logic, offline buffering)
- Status sensors: sync status and last sync timestamp

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
4. Enter your API key and cloud endpoint URL
5. Select sensors per room
