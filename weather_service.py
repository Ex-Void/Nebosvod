"""
Загрузка реальной погоды из открытого API Open-Meteo (https://open-meteo.com).
Ключ API не нужен. Если интернета нет — функции выбрасывают WeatherServiceError,
а сайт продолжает работать на данных из базы.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

from database import now_str

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
HPA_TO_MMHG = 0.750062


class WeatherServiceError(Exception):
    pass


def wmo_to_condition(code):
    """Код погоды WMO -> состояние сайта."""
    code = int(code or 0)
    if code == 0:
        return "clear"
    if code in (1, 2):
        return "partly"
    if code == 3:
        return "cloudy"
    if code in (45, 48):
        return "fog"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow"
    if code >= 95:
        return "storm"
    if 51 <= code <= 82:
        return "rain"
    return "cloudy"


def _get_json(url, params, timeout):
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={"User-Agent": "WeatherSite/1.0 (student project)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise WeatherServiceError(f"Сервис погоды недоступен: {exc}") from exc


def fetch_weather(latitude, longitude, timeout=8):
    data = _get_json(FORECAST_URL, {
        "latitude": latitude,
        "longitude": longitude,
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,pressure_msl,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "wind_speed_unit": "ms",
        "timezone": "auto",
        "forecast_days": 7,
    }, timeout)
    try:
        cur = data["current"]
        current = {
            "temperature": round(float(cur["temperature_2m"]), 1),
            "feels_like": round(float(cur["apparent_temperature"]), 1),
            "humidity": int(cur["relative_humidity_2m"]),
            "pressure": int(round(float(cur["pressure_msl"]) * HPA_TO_MMHG)),
            "wind_speed": round(float(cur["wind_speed_10m"]), 1),
            "condition": wmo_to_condition(cur["weather_code"]),
        }
        d = data["daily"]
        forecast = []
        for i, day in enumerate(d["time"]):
            precip = (d.get("precipitation_probability_max") or [None] * len(d["time"]))[i]
            forecast.append({
                "date": day,
                "temp_min": round(float(d["temperature_2m_min"][i]), 1),
                "temp_max": round(float(d["temperature_2m_max"][i]), 1),
                "condition": wmo_to_condition(d["weather_code"][i]),
                "precipitation": int(precip or 0),
            })
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise WeatherServiceError(f"Неожиданный ответ сервиса: {exc}") from exc
    return current, forecast


def update_city(conn, city, timeout=8):
    """Скачивает погоду для города и сохраняет её в базу."""
    current, forecast = fetch_weather(city["latitude"], city["longitude"], timeout)
    conn.execute(
        """INSERT OR REPLACE INTO current_weather
           (city_id, temperature, feels_like, humidity, pressure, wind_speed, condition, source, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'open-meteo', ?)""",
        (city["id"], current["temperature"], current["feels_like"], current["humidity"],
         current["pressure"], current["wind_speed"], current["condition"], now_str()),
    )
    for f in forecast:
        conn.execute(
            """INSERT OR REPLACE INTO forecasts
               (city_id, forecast_date, temp_min, temp_max, condition, precipitation)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (city["id"], f["date"], f["temp_min"], f["temp_max"], f["condition"], f["precipitation"]),
        )


def geocode(name, timeout=8):
    """Поиск координат города по названию."""
    data = _get_json(GEOCODE_URL, {"name": name, "count": 5, "language": "ru", "format": "json"}, timeout)
    return [
        {
            "name": r.get("name"),
            "country": r.get("country", ""),
            "region": r.get("admin1", ""),
            "latitude": r.get("latitude"),
            "longitude": r.get("longitude"),
        }
        for r in data.get("results", []) or []
    ]
