"""
Сайт погоды «Небосвод» — Flask + SQLite.

Запуск:  python app.py   (или run.bat в Windows)
Сайт:    http://127.0.0.1:5000
Админка: http://127.0.0.1:5000/admin   логин admin / пароль admin123
"""
import functools
import os
import re
import secrets
import sqlite3
import sys
import tempfile
import threading
import webbrowser
from datetime import date, datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Flask и зависимости лежат в папке vendor — сайт запускается без интернета и pip
sys.path.insert(0, os.path.join(BASE_DIR, "vendor"))

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template,
                   request, send_file, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import database as db
import weather_service as ws

app = Flask(__name__)
app.config["DATABASE"] = os.environ.get("WEATHER_DB", os.path.join(BASE_DIR, "weather.db"))
app.config["JSON_AS_ASCII"] = False
app.json.ensure_ascii = False


def _secret_key():
    path = os.path.join(BASE_DIR, ".secret_key")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            key = f.read().strip()
            if key:
                return key
    key = secrets.token_hex(32)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(key)
    except OSError:
        pass
    return key


app.secret_key = _secret_key()
db.init_db(app.config["DATABASE"])

# ------------------------------------------------------------------ утилиты

WEEKDAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
WEEKDAYS_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
              "августа", "сентября", "октября", "ноября", "декабря"]
SOURCES = {"manual": "введено администратором", "demo": "демо-данные", "open-meteo": "Open-Meteo"}


def get_db():
    if "db" not in g:
        g.db = db.connect(app.config["DATABASE"])
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def parse_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date() if isinstance(value, str) else value


def day_label(value):
    d = parse_date(value)
    delta = (d - date.today()).days
    if delta == 0:
        return "Сегодня"
    if delta == 1:
        return "Завтра"
    return WEEKDAYS[d.weekday()]


def day_month(value):
    d = parse_date(value)
    return f"{d.day} {MONTHS_GEN[d.month - 1]}"


def fmt_temp(value):
    v = round(float(value))
    return f"+{v}°" if v > 0 else f"{v}°".replace("-", "−")


def fmt_dt(value):
    try:
        dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return value or ""
    return f"{dt.day} {MONTHS_GEN[dt.month - 1]}, {dt:%H:%M}"


app.jinja_env.filters.update(day_label=day_label, day_month=day_month, temp=fmt_temp, dt=fmt_dt,
                             weekday_short=lambda v: WEEKDAYS_SHORT[parse_date(v).weekday()])


@app.context_processor
def inject_globals():
    return {
        "CONDITIONS": db.CONDITIONS,
        "SOURCES": SOURCES,
        "csrf_token": csrf_token,
        "current_user": session.get("username"),
        "today": date.today(),
        "unread_count": _unread_count() if session.get("username") else 0,
    }


def _unread_count():
    return get_db().execute("SELECT COUNT(*) FROM feedback WHERE is_read = 0").fetchone()[0]


# ------------------------------------------------------------------ защита

def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


@app.before_request
def check_csrf():
    if request.method == "POST":
        token = request.form.get("_csrf") or request.headers.get("X-CSRF-Token")
        if not token or token != session.get("_csrf"):
            abort(400, description="Срок действия формы истёк. Обновите страницу и попробуйте снова.")


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("username"):
            return redirect(url_for("admin_login", next=request.path))
        user = get_db().execute("SELECT id FROM users WHERE username = ?", (session["username"],)).fetchone()
        if user is None:  # пользователя удалили
            session.clear()
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)
    return wrapped


def log(action):
    db.log_action(get_db(), session.get("username", "?"), action)


# ------------------------------------------------------------------ данные о погоде

def active_cities():
    return get_db().execute(
        """SELECT c.*, w.temperature, w.condition, w.humidity, w.wind_speed
           FROM cities c LEFT JOIN current_weather w ON w.city_id = c.id
           WHERE c.is_active = 1 ORDER BY c.name"""
    ).fetchall()


def resolve_city(cities):
    """Город из ?city=, затем из cookie, иначе первый в списке."""
    ids = {c["id"]: c for c in cities}
    for raw in (request.args.get("city"), request.cookies.get("city_id")):
        if raw and raw.isdigit() and int(raw) in ids:
            return ids[int(raw)]
    return cities[0] if cities else None


def city_weather(city_id):
    conn = get_db()
    current = conn.execute("SELECT * FROM current_weather WHERE city_id = ?", (city_id,)).fetchone()
    forecast = conn.execute(
        "SELECT * FROM forecasts WHERE city_id = ? AND forecast_date >= ? ORDER BY forecast_date LIMIT 7",
        (city_id, date.today().isoformat()),
    ).fetchall()
    return current, forecast


def weather_to_json(city, current, forecast):
    return {
        "city": {"id": city["id"], "name": city["name"], "country": city["country"],
                 "description": city["description"]},
        "current": None if current is None else {
            "temperature": current["temperature"],
            "temperature_text": fmt_temp(current["temperature"]),
            "feels_like": current["feels_like"],
            "feels_like_text": fmt_temp(current["feels_like"]),
            "humidity": current["humidity"],
            "pressure": current["pressure"],
            "wind_speed": current["wind_speed"],
            "condition": current["condition"],
            "condition_label": db.CONDITIONS.get(current["condition"], current["condition"]),
            "source": SOURCES.get(current["source"], current["source"]),
            "updated_at": fmt_dt(current["updated_at"]),
        },
        "forecast": [{
            "date": f["forecast_date"],
            "label": day_label(f["forecast_date"]),
            "short": WEEKDAYS_SHORT[parse_date(f["forecast_date"]).weekday()],
            "day_month": day_month(f["forecast_date"]),
            "temp_min": f["temp_min"],
            "temp_max": f["temp_max"],
            "temp_min_text": fmt_temp(f["temp_min"]),
            "temp_max_text": fmt_temp(f["temp_max"]),
            "condition": f["condition"],
            "condition_label": db.CONDITIONS.get(f["condition"], f["condition"]),
            "precipitation": f["precipitation"],
        } for f in forecast],
    }


def remember_city(response, city):
    if city is not None:
        response.set_cookie("city_id", str(city["id"]), max_age=60 * 60 * 24 * 365, samesite="Lax")
    return response


# ------------------------------------------------------------------ публичные страницы

@app.route("/")
def index():
    cities = active_cities()
    city = resolve_city(cities)
    current, forecast = city_weather(city["id"]) if city else (None, [])
    resp = app.make_response(render_template(
        "index.html", page="now", cities=cities, city=city, current=current, forecast=forecast,
        data=weather_to_json(city, current, forecast) if city else None))
    return remember_city(resp, city)


@app.route("/forecast")
def forecast_page():
    cities = active_cities()
    city = resolve_city(cities)
    current, forecast = city_weather(city["id"]) if city else (None, [])
    resp = app.make_response(render_template(
        "forecast.html", page="forecast", cities=cities, city=city, current=current, forecast=forecast,
        data=weather_to_json(city, current, forecast) if city else None))
    return remember_city(resp, city)


@app.route("/cities")
def cities_page():
    return render_template("cities.html", page="cities", cities=active_cities(),
                           selected=request.cookies.get("city_id"))


@app.route("/feedback", methods=["GET", "POST"])
def feedback_page():
    form = {"name": "", "email": "", "message": ""}
    errors = {}
    if request.method == "POST":
        form = {k: request.form.get(k, "").strip() for k in form}
        if len(form["name"]) < 2:
            errors["name"] = "Укажите имя (минимум 2 символа)."
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", form["email"]):
            errors["email"] = "Укажите корректный e-mail."
        if len(form["message"]) < 5:
            errors["message"] = "Сообщение слишком короткое."
        if len(form["message"]) > 2000:
            errors["message"] = "Сообщение длиннее 2000 символов."
        if not errors:
            get_db().execute(
                "INSERT INTO feedback (name, email, message, created_at) VALUES (?, ?, ?, ?)",
                (form["name"], form["email"], form["message"], db.now_str()))
            get_db().commit()
            flash("Спасибо! Сообщение отправлено администратору.", "success")
            return redirect(url_for("feedback_page", sent=1))
    stats = get_db().execute(
        "SELECT (SELECT COUNT(*) FROM cities WHERE is_active=1) AS cities, "
        "(SELECT COUNT(*) FROM forecasts) AS forecasts").fetchone()
    return render_template("feedback.html", page="feedback", form=form, errors=errors,
                           sent=request.args.get("sent"), stats=stats)


@app.route("/api/weather/<int:city_id>")
def api_weather(city_id):
    city = get_db().execute("SELECT * FROM cities WHERE id = ? AND is_active = 1", (city_id,)).fetchone()
    if city is None:
        return jsonify({"error": "Город не найден"}), 404
    current, forecast = city_weather(city_id)
    resp = jsonify(weather_to_json(city, current, forecast))
    return remember_city(resp, city)


@app.route("/api/cities")
def api_cities():
    return jsonify([{
        "id": c["id"], "name": c["name"], "country": c["country"],
        "temperature": c["temperature"], "condition": c["condition"],
    } for c in active_cities()])


# ------------------------------------------------------------------ админ: вход

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("username"):
        return redirect(url_for("admin_dashboard"))
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            token = session.get("_csrf")
            session.clear()
            session["username"] = user["username"]
            if token:
                session["_csrf"] = token
            log("Вход в панель администратора")
            get_db().commit()
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/admin") else url_for("admin_dashboard"))
        error = "Неверный логин или пароль"
    return render_template("admin/login.html", page="admin", error=error)


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("username", None)
    flash("Вы вышли из панели администратора.", "info")
    return redirect(url_for("index"))


# ------------------------------------------------------------------ админ: обзор

@app.route("/admin")
@login_required
def admin_dashboard():
    conn = get_db()
    stats = conn.execute("""SELECT
        (SELECT COUNT(*) FROM cities) AS cities,
        (SELECT COUNT(*) FROM cities WHERE is_active = 1) AS active,
        (SELECT COUNT(*) FROM forecasts) AS forecasts,
        (SELECT COUNT(*) FROM feedback) AS feedback,
        (SELECT COUNT(*) FROM feedback WHERE is_read = 0) AS unread,
        (SELECT COUNT(*) FROM users) AS users""").fetchone()
    extremes = conn.execute("""SELECT c.name, w.temperature FROM current_weather w
        JOIN cities c ON c.id = w.city_id WHERE c.is_active = 1 ORDER BY w.temperature""").fetchall()
    log_rows = conn.execute("SELECT * FROM action_log ORDER BY id DESC LIMIT 8").fetchall()
    feedback = conn.execute("SELECT * FROM feedback ORDER BY id DESC LIMIT 4").fetchall()
    return render_template("admin/dashboard.html", page="admin", section="dashboard", stats=stats,
                           coldest=extremes[0] if extremes else None,
                           warmest=extremes[-1] if extremes else None,
                           log_rows=log_rows, feedback=feedback)


@app.route("/admin/refresh", methods=["POST"])
@login_required
def admin_refresh():
    """Обновить погоду из интернета (все города или один)."""
    conn = get_db()
    city_id = request.form.get("city_id")
    if city_id:
        cities = conn.execute("SELECT * FROM cities WHERE id = ?", (city_id,)).fetchall()
    else:
        cities = conn.execute("SELECT * FROM cities WHERE is_active = 1").fetchall()
    ok, errors = 0, []
    for city in cities:
        try:
            ws.update_city(conn, city, timeout=6)
            ok += 1
        except ws.WeatherServiceError as exc:
            errors.append(f"{city['name']}: {exc}")
            if ok == 0 and len(errors) >= 2:  # интернета явно нет — не ждём остальные города
                break
    if ok:
        log(f"Обновлена погода из Open-Meteo ({ok} гор.)")
        conn.commit()
        flash(f"Погода обновлена из интернета для {ok} город(ов).", "success")
    if errors:
        flash("Не удалось получить данные из интернета. Сайт продолжает работать на данных из базы. "
              + errors[0], "error")
    return redirect(request.form.get("back") or url_for("admin_dashboard"))


@app.route("/admin/demo", methods=["POST"])
@login_required
def admin_demo():
    conn = get_db()
    cities = conn.execute("SELECT * FROM cities").fetchall()
    for city in cities:
        db.generate_demo_weather(conn, city)
    log("Сгенерированы демо-данные погоды")
    conn.commit()
    flash(f"Демо-данные сгенерированы для {len(cities)} город(ов).", "success")
    return redirect(request.form.get("back") or url_for("admin_dashboard"))


# ------------------------------------------------------------------ админ: города

def _city_form_data():
    f = request.form
    data = {
        "name": f.get("name", "").strip(),
        "country": f.get("country", "").strip() or "Россия",
        "latitude": f.get("latitude", "").strip().replace(",", "."),
        "longitude": f.get("longitude", "").strip().replace(",", "."),
        "description": f.get("description", "").strip(),
        "is_active": 1 if f.get("is_active") else 0,
    }
    errors = {}
    if len(data["name"]) < 2:
        errors["name"] = "Введите название города."
    for key, lim in (("latitude", 90), ("longitude", 180)):
        try:
            val = float(data[key])
            if not -lim <= val <= lim:
                raise ValueError
            data[key] = val
        except ValueError:
            errors[key] = f"Число от −{lim} до {lim}."
    return data, errors


@app.route("/admin/cities")
@login_required
def admin_cities():
    q = request.args.get("q", "").strip()
    rows = get_db().execute(
        """SELECT c.*, w.temperature, w.condition, w.updated_at,
                  (SELECT COUNT(*) FROM forecasts f WHERE f.city_id = c.id) AS fc_count
           FROM cities c LEFT JOIN current_weather w ON w.city_id = c.id
           WHERE c.name LIKE ? ORDER BY c.name""", (f"%{q}%",)).fetchall()
    return render_template("admin/cities.html", page="admin", section="cities", rows=rows, q=q)


@app.route("/admin/cities/new", methods=["GET", "POST"])
@app.route("/admin/cities/<int:city_id>/edit", methods=["GET", "POST"])
@login_required
def admin_city_form(city_id=None):
    conn = get_db()
    city = None
    if city_id:
        city = conn.execute("SELECT * FROM cities WHERE id = ?", (city_id,)).fetchone()
        if city is None:
            abort(404)
    data, errors = (dict(city) if city else {"is_active": 1, "country": "Россия"}), {}
    if request.method == "POST":
        data, errors = _city_form_data()
        if not errors:
            try:
                if city:
                    conn.execute("""UPDATE cities SET name=?, country=?, latitude=?, longitude=?,
                                    description=?, is_active=? WHERE id=?""",
                                 (data["name"], data["country"], data["latitude"], data["longitude"],
                                  data["description"], data["is_active"], city_id))
                    log(f"Изменён город «{data['name']}»")
                    flash(f"Город «{data['name']}» сохранён.", "success")
                else:
                    cur = conn.execute("""INSERT INTO cities (name, country, latitude, longitude, description,
                                          is_active, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                                       (data["name"], data["country"], data["latitude"], data["longitude"],
                                        data["description"], data["is_active"], db.now_str()))
                    new_city = conn.execute("SELECT * FROM cities WHERE id = ?", (cur.lastrowid,)).fetchone()
                    try:  # сначала пробуем реальную погоду, без интернета — демо
                        ws.update_city(conn, new_city, timeout=5)
                        note = "погода загружена из Open-Meteo"
                    except ws.WeatherServiceError:
                        db.generate_demo_weather(conn, new_city)
                        note = "нет интернета — заполнены демо-данные"
                    log(f"Добавлен город «{data['name']}»")
                    flash(f"Город «{data['name']}» добавлен ({note}).", "success")
                conn.commit()
                return redirect(url_for("admin_cities"))
            except sqlite3.IntegrityError:
                conn.rollback()
                errors["name"] = "Город с таким названием уже есть."
    return render_template("admin/city_form.html", page="admin", section="cities", city=city,
                           data=data, errors=errors)


@app.route("/admin/cities/<int:city_id>/toggle", methods=["POST"])
@login_required
def admin_city_toggle(city_id):
    conn = get_db()
    city = conn.execute("SELECT * FROM cities WHERE id = ?", (city_id,)).fetchone() or abort(404)
    conn.execute("UPDATE cities SET is_active = 1 - is_active WHERE id = ?", (city_id,))
    log(f"{'Скрыт' if city['is_active'] else 'Показан'} город «{city['name']}»")
    conn.commit()
    flash(f"Город «{city['name']}» {'скрыт с сайта' if city['is_active'] else 'снова показан на сайте'}.", "info")
    return redirect(url_for("admin_cities"))


@app.route("/admin/cities/<int:city_id>/delete", methods=["POST"])
@login_required
def admin_city_delete(city_id):
    conn = get_db()
    city = conn.execute("SELECT * FROM cities WHERE id = ?", (city_id,)).fetchone() or abort(404)
    conn.execute("DELETE FROM cities WHERE id = ?", (city_id,))
    log(f"Удалён город «{city['name']}»")
    conn.commit()
    flash(f"Город «{city['name']}» и его прогнозы удалены.", "success")
    return redirect(url_for("admin_cities"))


@app.route("/admin/geocode")
@login_required
def admin_geocode():
    name = request.args.get("name", "").strip()
    if not name:
        return jsonify({"error": "Введите название"}), 400
    try:
        return jsonify({"results": ws.geocode(name, timeout=6)})
    except ws.WeatherServiceError as exc:
        return jsonify({"error": f"Нет связи с сервисом поиска координат. Введите их вручную. ({exc})"}), 503


# ------------------------------------------------------------------ админ: текущая погода

def _weather_form():
    f = request.form
    data, errors = {}, {}
    fields = {"temperature": (float, -90, 60), "feels_like": (float, -100, 70), "humidity": (int, 0, 100),
              "pressure": (int, 600, 820), "wind_speed": (float, 0, 80)}
    for key, (typ, lo, hi) in fields.items():
        raw = f.get(key, "").strip().replace(",", ".").replace("−", "-")
        try:
            val = typ(float(raw)) if typ is int else typ(raw)
            if not lo <= val <= hi:
                raise ValueError
            data[key] = val
        except ValueError:
            data[key] = raw
            errors[key] = f"Значение от {lo} до {hi}."
    data["condition"] = f.get("condition")
    if data["condition"] not in db.CONDITIONS:
        errors["condition"] = "Выберите состояние."
    return data, errors


@app.route("/admin/weather")
@login_required
def admin_weather():
    rows = get_db().execute(
        """SELECT c.id, c.name, c.is_active, w.* FROM cities c
           LEFT JOIN current_weather w ON w.city_id = c.id ORDER BY c.name""").fetchall()
    return render_template("admin/weather.html", page="admin", section="weather", rows=rows)


@app.route("/admin/weather/<int:city_id>", methods=["GET", "POST"])
@login_required
def admin_weather_edit(city_id):
    conn = get_db()
    city = conn.execute("SELECT * FROM cities WHERE id = ?", (city_id,)).fetchone() or abort(404)
    row = conn.execute("SELECT * FROM current_weather WHERE city_id = ?", (city_id,)).fetchone()
    data = dict(row) if row else {"condition": "clear"}
    errors = {}
    if request.method == "POST":
        data, errors = _weather_form()
        if not errors:
            conn.execute("""INSERT OR REPLACE INTO current_weather (city_id, temperature, feels_like, humidity,
                            pressure, wind_speed, condition, source, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, 'manual', ?)""",
                         (city_id, data["temperature"], data["feels_like"], data["humidity"], data["pressure"],
                          data["wind_speed"], data["condition"], db.now_str()))
            log(f"Изменена текущая погода: {city['name']}")
            conn.commit()
            flash(f"Текущая погода для города «{city['name']}» сохранена.", "success")
            return redirect(url_for("admin_weather"))
    return render_template("admin/weather_form.html", page="admin", section="weather", city=city,
                           data=data, errors=errors)


# ------------------------------------------------------------------ админ: прогнозы

@app.route("/admin/forecasts")
@login_required
def admin_forecasts():
    conn = get_db()
    cities = conn.execute("SELECT id, name FROM cities ORDER BY name").fetchall()
    city_id = request.args.get("city", type=int) or (cities[0]["id"] if cities else None)
    show_past = request.args.get("past") == "1"
    sql = "SELECT * FROM forecasts WHERE city_id = ?"
    params = [city_id]
    if not show_past:
        sql += " AND forecast_date >= ?"
        params.append(date.today().isoformat())
    rows = conn.execute(sql + " ORDER BY forecast_date", params).fetchall()
    return render_template("admin/forecasts.html", page="admin", section="forecasts", cities=cities,
                           city_id=city_id, rows=rows, show_past=show_past)


@app.route("/admin/forecasts/new", methods=["GET", "POST"])
@app.route("/admin/forecasts/<int:fc_id>/edit", methods=["GET", "POST"])
@login_required
def admin_forecast_form(fc_id=None):
    conn = get_db()
    cities = conn.execute("SELECT id, name FROM cities ORDER BY name").fetchall()
    row = None
    if fc_id:
        row = conn.execute("SELECT * FROM forecasts WHERE id = ?", (fc_id,)).fetchone() or abort(404)
    data = dict(row) if row else {"city_id": request.args.get("city", type=int),
                                  "forecast_date": date.today().isoformat(), "condition": "clear",
                                  "precipitation": 0}
    errors = {}
    if request.method == "POST":
        f = request.form
        data = {"city_id": f.get("city_id", type=int), "forecast_date": f.get("forecast_date", ""),
                "condition": f.get("condition"), "temp_min": f.get("temp_min", ""),
                "temp_max": f.get("temp_max", ""), "precipitation": f.get("precipitation", "")}
        if not any(c["id"] == data["city_id"] for c in cities):
            errors["city_id"] = "Выберите город."
        try:
            parse_date(data["forecast_date"])
        except ValueError:
            errors["forecast_date"] = "Укажите дату."
        if data["condition"] not in db.CONDITIONS:
            errors["condition"] = "Выберите состояние."
        for key, lo, hi in (("temp_min", -90, 60), ("temp_max", -90, 60), ("precipitation", 0, 100)):
            try:
                val = float(str(data[key]).replace(",", ".").replace("−", "-"))
                if not lo <= val <= hi:
                    raise ValueError
                data[key] = int(val) if key == "precipitation" else val
            except ValueError:
                errors[key] = f"Значение от {lo} до {hi}."
        if not errors and data["temp_min"] > data["temp_max"]:
            errors["temp_min"] = "Минимум не может быть больше максимума."
        if not errors:
            try:
                vals = (data["city_id"], data["forecast_date"], data["temp_min"], data["temp_max"],
                        data["condition"], data["precipitation"])
                if row:
                    conn.execute("""UPDATE forecasts SET city_id=?, forecast_date=?, temp_min=?, temp_max=?,
                                    condition=?, precipitation=? WHERE id=?""", vals + (fc_id,))
                    log(f"Изменён прогноз на {data['forecast_date']}")
                else:
                    conn.execute("""INSERT INTO forecasts (city_id, forecast_date, temp_min, temp_max,
                                    condition, precipitation) VALUES (?, ?, ?, ?, ?, ?)""", vals)
                    log(f"Добавлен прогноз на {data['forecast_date']}")
                conn.commit()
                flash("Прогноз сохранён.", "success")
                return redirect(url_for("admin_forecasts", city=data["city_id"]))
            except sqlite3.IntegrityError:
                conn.rollback()
                errors["forecast_date"] = "На эту дату у города уже есть прогноз."
    return render_template("admin/forecast_form.html", page="admin", section="forecasts", row=row,
                           cities=cities, data=data, errors=errors)


@app.route("/admin/forecasts/<int:fc_id>/delete", methods=["POST"])
@login_required
def admin_forecast_delete(fc_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM forecasts WHERE id = ?", (fc_id,)).fetchone() or abort(404)
    conn.execute("DELETE FROM forecasts WHERE id = ?", (fc_id,))
    log(f"Удалён прогноз на {row['forecast_date']}")
    conn.commit()
    flash("Прогноз удалён.", "success")
    return redirect(url_for("admin_forecasts", city=row["city_id"]))


# ------------------------------------------------------------------ админ: сообщения

@app.route("/admin/feedback")
@login_required
def admin_feedback():
    rows = get_db().execute("SELECT * FROM feedback ORDER BY is_read, id DESC").fetchall()
    return render_template("admin/feedback.html", page="admin", section="feedback", rows=rows)


@app.route("/admin/feedback/<int:fb_id>/read", methods=["POST"])
@login_required
def admin_feedback_read(fb_id):
    conn = get_db()
    conn.execute("UPDATE feedback SET is_read = 1 - is_read WHERE id = ?", (fb_id,))
    conn.commit()
    return redirect(url_for("admin_feedback"))


@app.route("/admin/feedback/<int:fb_id>/delete", methods=["POST"])
@login_required
def admin_feedback_delete(fb_id):
    conn = get_db()
    conn.execute("DELETE FROM feedback WHERE id = ?", (fb_id,))
    log(f"Удалено сообщение #{fb_id}")
    conn.commit()
    flash("Сообщение удалено.", "success")
    return redirect(url_for("admin_feedback"))


# ------------------------------------------------------------------ админ: пользователи

@app.route("/admin/users", methods=["GET", "POST"])
@login_required
def admin_users():
    conn = get_db()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "create":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            if not re.fullmatch(r"[A-Za-z0-9_.-]{3,30}", username):
                flash("Логин: 3–30 латинских букв, цифр или символов _ . -", "error")
            elif len(password) < 6:
                flash("Пароль должен быть не короче 6 символов.", "error")
            else:
                try:
                    conn.execute("INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                                 (username, generate_password_hash(password), db.now_str()))
                    log(f"Добавлен администратор «{username}»")
                    conn.commit()
                    flash(f"Администратор «{username}» добавлен.", "success")
                except sqlite3.IntegrityError:
                    flash("Такой логин уже занят.", "error")
        elif action == "password":
            user = conn.execute("SELECT * FROM users WHERE username = ?", (session["username"],)).fetchone()
            old, new, rep = (request.form.get(k, "") for k in ("old", "new", "repeat"))
            if not check_password_hash(user["password_hash"], old):
                flash("Текущий пароль введён неверно.", "error")
            elif len(new) < 6:
                flash("Новый пароль должен быть не короче 6 символов.", "error")
            elif new != rep:
                flash("Новые пароли не совпадают.", "error")
            else:
                conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                             (generate_password_hash(new), user["id"]))
                log("Изменён собственный пароль")
                conn.commit()
                flash("Пароль изменён.", "success")
        return redirect(url_for("admin_users"))
    rows = conn.execute("SELECT id, username, created_at FROM users ORDER BY id").fetchall()
    return render_template("admin/users.html", page="admin", section="users", rows=rows)


@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@login_required
def admin_user_delete(user_id):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone() or abort(404)
    if user["username"] == session["username"]:
        flash("Нельзя удалить самого себя.", "error")
    elif conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] <= 1:
        flash("Нельзя удалить последнего администратора.", "error")
    else:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        log(f"Удалён администратор «{user['username']}»")
        conn.commit()
        flash(f"Администратор «{user['username']}» удалён.", "success")
    return redirect(url_for("admin_users"))


# ------------------------------------------------------------------ админ: база данных

SQL_EXAMPLES = [
    ("Все города", "SELECT * FROM cities ORDER BY name;"),
    ("Самые тёплые сейчас", "SELECT c.name, w.temperature, w.condition\nFROM current_weather w\n"
                            "JOIN cities c ON c.id = w.city_id\nORDER BY w.temperature DESC;"),
    ("Средняя температура прогноза", "SELECT c.name, ROUND(AVG((f.temp_min + f.temp_max) / 2), 1) AS avg_temp\n"
                                     "FROM forecasts f JOIN cities c ON c.id = f.city_id\n"
                                     "GROUP BY c.name ORDER BY avg_temp DESC;"),
    ("Дни с осадками > 70%", "SELECT c.name, f.forecast_date, f.precipitation\nFROM forecasts f\n"
                             "JOIN cities c ON c.id = f.city_id\nWHERE f.precipitation > 70\n"
                             "ORDER BY f.forecast_date;"),
    ("Структура таблиц", "SELECT name, sql FROM sqlite_master WHERE type = 'table';"),
]


@app.route("/admin/database", methods=["GET", "POST"])
@login_required
def admin_database():
    conn = get_db()
    tables = []
    for t in ("cities", "current_weather", "forecasts", "feedback", "users", "action_log"):
        cols = conn.execute(f"PRAGMA table_info({t})").fetchall()
        count = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        tables.append({"name": t, "count": count, "columns": cols})

    query = request.form.get("query", SQL_EXAMPLES[1][1]) if request.method == "POST" else \
        request.args.get("q", SQL_EXAMPLES[1][1])
    result, error = None, None
    if request.method == "POST" or "q" in request.args:
        stripped = re.sub(r"--.*?$|/\*.*?\*/", "", query, flags=re.S | re.M).strip().rstrip(";").strip()
        if not re.match(r"(?is)^(select|with|pragma)\b", stripped) or ";" in stripped:
            error = "В консоли разрешены только запросы на чтение (SELECT / WITH / PRAGMA), по одному. " \
                    "Изменять данные можно через разделы панели."
        else:
            ro = db.connect(app.config["DATABASE"], readonly=True)
            try:
                cur = ro.execute(stripped)
                rows = cur.fetchmany(500)
                result = {"columns": [d[0] for d in cur.description or []],
                          "rows": [list(r) for r in rows], "limited": len(rows) == 500}
            except sqlite3.Error as exc:
                error = f"Ошибка SQL: {exc}"
            finally:
                ro.close()
    return render_template("admin/database.html", page="admin", section="database", tables=tables,
                           query=query, result=result, error=error, examples=SQL_EXAMPLES,
                           db_size=os.path.getsize(app.config["DATABASE"]) // 1024)


@app.route("/admin/database/backup")
@login_required
def admin_backup():
    tmp = os.path.join(tempfile.gettempdir(), f"weather_backup_{secrets.token_hex(4)}.db")
    src = sqlite3.connect(app.config["DATABASE"])
    dst = sqlite3.connect(tmp)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    log("Скачана резервная копия базы")
    get_db().commit()
    return send_file(tmp, as_attachment=True,
                     download_name=f"weather_backup_{datetime.now():%Y-%m-%d_%H-%M}.db")


@app.route("/admin/log")
@login_required
def admin_log():
    rows = get_db().execute("SELECT * FROM action_log ORDER BY id DESC LIMIT 300").fetchall()
    return render_template("admin/log.html", page="admin", section="log", rows=rows)


# ------------------------------------------------------------------ ошибки

@app.errorhandler(404)
def not_found(_e):
    return render_template("error.html", page="", code=404, message="Такой страницы нет — возможно, её унесло ветром."), 404


@app.errorhandler(400)
def bad_request(e):
    return render_template("error.html", page="", code=400, message=e.description), 400


@app.errorhandler(500)
def server_error(_e):
    return render_template("error.html", page="", code=500, message="Внутренняя ошибка сервера."), 500


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):  # кириллица в любой консоли Windows
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    host, port = "127.0.0.1", int(os.environ.get("PORT", 5000))
    url = f"http://{host}:{port}"
    print("=" * 60)
    print(f"  Сайт погоды запущен:  {url}")
    print(f"  Панель администратора: {url}/admin  (admin / admin123)")
    print("  Остановить сервер: Ctrl+C")
    print("=" * 60)
    if "--no-browser" not in sys.argv:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host=host, port=port, debug=False)
