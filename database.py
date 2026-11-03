"""
Работа с базой данных SQLite: схема, начальные (демо) данные, вспомогательные функции.

Таблицы:
    users            — администраторы сайта
    cities           — города
    current_weather  — текущая погода (одна запись на город)
    forecasts        — прогноз по дням
    feedback         — сообщения из формы обратной связи
    action_log       — журнал действий администраторов
"""
import math
import os
import random
import sqlite3
from datetime import date, datetime, timedelta

from werkzeug.security import generate_password_hash

# Погодные состояния, которые понимает сайт (ключ -> подпись)
CONDITIONS = {
    "clear": "Ясно",
    "partly": "Переменная облачность",
    "cloudy": "Пасмурно",
    "fog": "Туман",
    "rain": "Дождь",
    "snow": "Снег",
    "storm": "Гроза",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS cities (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    country     TEXT    NOT NULL DEFAULT 'Россия',
    latitude    REAL    NOT NULL,
    longitude   REAL    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS current_weather (
    city_id     INTEGER PRIMARY KEY REFERENCES cities(id) ON DELETE CASCADE,
    temperature REAL    NOT NULL,
    feels_like  REAL    NOT NULL,
    humidity    INTEGER NOT NULL,
    pressure    INTEGER NOT NULL,          -- мм рт. ст.
    wind_speed  REAL    NOT NULL,          -- м/с
    condition   TEXT    NOT NULL,
    source      TEXT    NOT NULL DEFAULT 'manual',
    updated_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS forecasts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    city_id       INTEGER NOT NULL REFERENCES cities(id) ON DELETE CASCADE,
    forecast_date TEXT    NOT NULL,        -- ГГГГ-ММ-ДД
    temp_min      REAL    NOT NULL,
    temp_max      REAL    NOT NULL,
    condition     TEXT    NOT NULL,
    precipitation INTEGER NOT NULL DEFAULT 0,   -- вероятность осадков, %
    UNIQUE (city_id, forecast_date)
);

CREATE TABLE IF NOT EXISTS feedback (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL,
    email      TEXT    NOT NULL,
    message    TEXT    NOT NULL,
    is_read    INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS action_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username   TEXT NOT NULL,
    action     TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_forecasts_city_date ON forecasts(city_id, forecast_date);
"""

# Города для начального наполнения: название, широта, долгота, поправка к климату, описание
SEED_CITIES = [
    ("Москва", 55.7558, 37.6173, 0.0, "Столица России, крупнейший город страны."),
    ("Санкт-Петербург", 59.9343, 30.3351, 1.0, "Культурная столица на берегу Финского залива."),
    ("Казань", 55.7963, 49.1088, -0.5, "Столица Татарстана на берегу Волги."),
    ("Екатеринбург", 56.8389, 60.6057, -2.0, "Крупный город на Среднем Урале."),
    ("Новосибирск", 55.0084, 82.9357, -4.0, "Крупнейший город Сибири на реке Обь."),
    ("Сочи", 43.6028, 39.7342, 5.0, "Курорт на Черноморском побережье."),
    ("Калининград", 54.7104, 20.4522, 3.0, "Самый западный областной центр России."),
    ("Владивосток", 43.1155, 131.8855, -1.0, "Порт на берегу Тихого океана."),
    ("Мурманск", 68.9585, 33.0827, 1.0, "Крупнейший город за Полярным кругом."),
]
CLIMATE_OFFSET = {name: off for name, _, _, off, _ in SEED_CITIES}


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def connect(path, readonly=False):
    if readonly:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ---------------------------------------------------------------- демо-данные

def _climate_temp(latitude, day, name=""):
    """Примерная средняя температура для широты и дня года (для демо-данных)."""
    lat = abs(latitude)
    mean = 27 - 0.4 * lat
    amplitude = max(0.3 * lat - 2, 2)
    doy = day.timetuple().tm_yday
    return mean - amplitude * math.cos(2 * math.pi * (doy - 20) / 365) + CLIMATE_OFFSET.get(name, 0)


def _pick_condition(rng, temp):
    if temp <= -1:
        pool = [("snow", 4), ("cloudy", 3), ("partly", 2), ("clear", 2), ("fog", 1)]
    elif temp <= 3:
        pool = [("cloudy", 4), ("rain", 3), ("snow", 2), ("partly", 2), ("fog", 1), ("clear", 1)]
    else:
        pool = [("partly", 3), ("cloudy", 3), ("rain", 3), ("clear", 2), ("fog", 1), ("storm", 1)]
    names, weights = zip(*pool)
    return rng.choices(names, weights)[0]


PRECIP_BY_CONDITION = {"clear": (0, 10), "partly": (5, 30), "cloudy": (20, 50),
                       "fog": (10, 30), "rain": (60, 95), "snow": (60, 95), "storm": (70, 100)}


def generate_demo_weather(conn, city, days=7):
    """Заполняет текущую погоду и прогноз города правдоподобными демо-значениями."""
    today = date.today()
    rng = random.Random(f"{city['id']}-{today.isoformat()}")

    base = _climate_temp(city["latitude"], today, city["name"])
    temp = round(base + rng.uniform(-2.5, 2.5), 1)
    cond = _pick_condition(rng, temp)
    wind = round(rng.uniform(1, 9), 1)
    conn.execute(
        """INSERT OR REPLACE INTO current_weather
           (city_id, temperature, feels_like, humidity, pressure, wind_speed, condition, source, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'demo', ?)""",
        (city["id"], temp, round(temp - wind * 0.6, 1), rng.randint(55, 95),
         rng.randint(735, 770), wind, cond, now_str()),
    )

    for i in range(days):
        day = today + timedelta(days=i)
        mid = _climate_temp(city["latitude"], day, city["name"]) + rng.uniform(-3, 3)
        spread = rng.uniform(3, 8)
        c = cond if i == 0 else _pick_condition(rng, mid)
        lo, hi = PRECIP_BY_CONDITION[c]
        conn.execute(
            """INSERT OR REPLACE INTO forecasts
               (city_id, forecast_date, temp_min, temp_max, condition, precipitation)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (city["id"], day.isoformat(), round(mid - spread / 2, 1), round(mid + spread / 2, 1),
             c, rng.randint(lo, hi)),
        )


def ensure_fresh_forecasts(conn):
    """Если у города не осталось прогноза на сегодня и далее — достраивает демо-прогноз."""
    today = date.today().isoformat()
    cities = conn.execute(
        """SELECT * FROM cities c WHERE NOT EXISTS
           (SELECT 1 FROM forecasts f WHERE f.city_id = c.id AND f.forecast_date >= ?)""",
        (today,),
    ).fetchall()
    for city in cities:
        generate_demo_weather(conn, city)
    return len(cities)


def seed(conn):
    for name, lat, lon, _, descr in SEED_CITIES:
        conn.execute(
            "INSERT INTO cities (name, country, latitude, longitude, description, created_at) VALUES (?, 'Россия', ?, ?, ?, ?)",
            (name, lat, lon, descr, now_str()),
        )
    for city in conn.execute("SELECT * FROM cities").fetchall():
        generate_demo_weather(conn, city)
    conn.execute(
        "INSERT INTO feedback (name, email, message, created_at) VALUES (?, ?, ?, ?)",
        ("Иван", "ivan@example.com", "Отличный сайт! Добавьте, пожалуйста, Тулу.", now_str()),
    )


def init_db(path):
    conn = connect(path)
    conn.executescript(SCHEMA)
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        conn.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            ("admin", generate_password_hash("admin123"), now_str()),
        )
    if conn.execute("SELECT COUNT(*) FROM cities").fetchone()[0] == 0:
        seed(conn)
    else:
        ensure_fresh_forecasts(conn)
    conn.commit()
    conn.close()


def log_action(conn, username, action):
    conn.execute(
        "INSERT INTO action_log (username, action, created_at) VALUES (?, ?, ?)",
        (username, action, now_str()),
    )
