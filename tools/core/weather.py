"""weather: Current conditions and 3-day forecast via Open-Meteo (free, no key).
Geocoding via Open-Meteo geocoding API. Temps in °F, wind in mph, precip in inches.
"""
import requests

_GEO_URL     = "https://geocoding-api.open-meteo.com/v1/search"
_WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

_WMO = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Icy fog", 51: "Light drizzle", 53: "Moderate drizzle",
    55: "Dense drizzle", 61: "Light rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Light snow", 73: "Moderate snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Light showers", 81: "Moderate showers", 82: "Violent showers",
    85: "Light snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm w/ hail", 99: "Thunderstorm w/ heavy hail",
}


def run(args: dict) -> dict:
    location = args.get("location", "").strip()
    if not location:
        return {"error": "location is required (e.g. 'Boston, MA' or 'London')"}

    try:
        geo = requests.get(
            _GEO_URL,
            params={"name": location, "count": 1, "language": "en", "format": "json"},
            timeout=10,
        ).json()
    except Exception as e:
        return {"error": f"geocoding failed: {e}"}

    locs = geo.get("results", [])
    if not locs:
        return {"error": f"location not found: {location}"}

    loc  = locs[0]
    lat  = loc["latitude"]
    lon  = loc["longitude"]
    name = f"{loc.get('name', location)}, {loc.get('country', '')}"

    try:
        wx = requests.get(
            _WEATHER_URL,
            params={
                "latitude":            lat,
                "longitude":           lon,
                "current":             ("temperature_2m,relative_humidity_2m,"
                                        "apparent_temperature,precipitation,"
                                        "weather_code,wind_speed_10m,wind_direction_10m"),
                "daily":               ("weather_code,temperature_2m_max,temperature_2m_min,"
                                        "precipitation_sum,wind_speed_10m_max"),
                "temperature_unit":    "fahrenheit",
                "wind_speed_unit":     "mph",
                "precipitation_unit":  "inch",
                "forecast_days":       4,
                "timezone":            "auto",
            },
            timeout=10,
        ).json()
    except Exception as e:
        return {"error": f"weather fetch failed: {e}"}

    cur   = wx.get("current", {})
    daily = wx.get("daily", {})

    def wmo(code):
        return _WMO.get(int(code) if code is not None else 0, f"code {code}")

    def _idx(lst, i):
        return lst[i] if isinstance(lst, list) and i < len(lst) else None

    forecast = []
    for i, date in enumerate(daily.get("time", [])):
        forecast.append({
            "date":          date,
            "condition":     wmo(_idx(daily.get("weather_code", []), i)),
            "high_f":        _idx(daily.get("temperature_2m_max", []), i),
            "low_f":         _idx(daily.get("temperature_2m_min", []), i),
            "precip_in":     _idx(daily.get("precipitation_sum", []), i),
            "wind_max_mph":  _idx(daily.get("wind_speed_10m_max", []), i),
        })

    return {
        "location":    name,
        "current": {
            "condition":     wmo(cur.get("weather_code")),
            "temp_f":        cur.get("temperature_2m"),
            "feels_like_f":  cur.get("apparent_temperature"),
            "humidity_pct":  cur.get("relative_humidity_2m"),
            "precip_in":     cur.get("precipitation"),
            "wind_mph":      cur.get("wind_speed_10m"),
            "wind_dir_deg":  cur.get("wind_direction_10m"),
        },
        "forecast": forecast,
    }
