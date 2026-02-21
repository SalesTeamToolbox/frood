---
name: weather
description: Weather data lookup using wttr.in and Open-Meteo APIs.
always: false
task_types: [research]
---

# Weather Skill

Retrieve weather information for any location.

## Quick Lookup (wttr.in)
```bash
curl -s "wttr.in/CityName?format=3"
```

## Detailed Forecast
```bash
curl -s "wttr.in/CityName?format=j1"
```

## Open-Meteo API (no API key needed)
For programmatic access with JSON:
```
https://api.open-meteo.com/v1/forecast?latitude=LAT&longitude=LON&current_weather=true
```

## Guidelines
- Use wttr.in for quick human-readable weather.
- Use Open-Meteo for structured data in applications.
- Always specify the location clearly.
