# --- imports (deduped) ---
import os
import requests
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort

import uuid
from datetime import datetime
from werkzeug.utils import secure_filename


# ----------------- app config -----------------
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "replace-with-a-strong-secret-key")

UPLOAD_FOLDER = os.path.join(app.static_folder, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
ALLOWED_UPLOADS = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}

# reCAPTCHA keys (use env in prod)
RECAPTCHA_SITE_KEY = os.getenv("RECAPTCHA_SITE_KEY", "6LeKdPwrAAAAAKKbjpvL6ocnR2sL89xfQYJYT0uZ")
RECAPTCHA_SECRET_KEY = os.getenv("RECAPTCHA_SECRET_KEY", "6LeKdPwrAAAAAF-hj2VOmvfE55KLGqSXMLyRBdbw")

# Demo users (username -> {password, role})  roles: admin | patient | caretaker
DEMO_USERS = {
    "rajat":  {"password": "pass123",  "role": "patient"},
    "admin":  {"password": "admin123", "role": "admin"},
    "guest":  {"password": "guest",    "role": "caretaker"},
}

# ---- Optional: Customer Gallery config (used by patient gallery too) ----
IMAGE_ROOT = os.path.join(app.static_folder, "customer_images")
ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
AUDIO_EXTS_PREFERENCE = [".mp3", ".m4a", ".ogg", ".wav", ".mp4", ".mov"]

# ----------------- In-memory Patient "DB" -----------------
# {username: {tasks, meds, notes, appts, files, mood, reminders, activities}}
PATIENT_DB = {}

def _ensure_patient(username):
    if username not in PATIENT_DB:
        PATIENT_DB[username] = {
            "tasks": [
                {"id": str(uuid.uuid4()), "title": "Morning walk", "done": False},
                {"id": str(uuid.uuid4()), "title": "Breakfast", "done": False},
            ],
            "meds": [
                {"id": str(uuid.uuid4()), "name": "Vitamin B12", "time": "09:00", "taken_today": False},
            ],
            "notes": [],
            "appts": [],
            "files": [],
            "mood": "🙂 Calm",
            # NEW: memory reminders & activities for hub pages
            "reminders": [
                {"id": str(uuid.uuid4()), "title": "Call grandson Aarav",
                 "dt": datetime.now().isoformat(timespec="minutes"), "kind": "family", "active": True},
            ],
            "activities": [
                {"id": str(uuid.uuid4()), "title": "Listen to favorite song", "done_today": False},
                {"id": str(uuid.uuid4()), "title": "5-min breathing", "done_today": False},
            ],
        }

def _dt_pretty(dt_str):
    try:
        return datetime.fromisoformat(dt_str).strftime("%b %d, %Y · %I:%M %p")
    except Exception:
        return dt_str


# ----------------- helpers -----------------
def verify_recaptcha(response_token, remote_ip=None):
    """Return True/False based on Google reCAPTCHA verification."""
    if not RECAPTCHA_SECRET_KEY:
        return True
    payload = {"secret": RECAPTCHA_SECRET_KEY, "response": response_token}
    if remote_ip:
        payload["remoteip"] = remote_ip
    try:
        r = requests.post("https://www.google.com/recaptcha/api/siteverify", data=payload, timeout=5)
        data = r.json()
        return bool(data.get("success"))
    except Exception:
        return False


def login_required(view_fn):
    @wraps(view_fn)
    def wrapped(*args, **kwargs):
        if "user" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return view_fn(*args, **kwargs)
    return wrapped


def role_required(*roles):
    """Use as @role_required('admin') or @role_required('patient','caretaker')."""
    def decorator(view_fn):
        @wraps(view_fn)
        def wrapped(*args, **kwargs):
            if "user" not in session:
                flash("Please log in to continue.", "warning")
                return redirect(url_for("login"))
            if session.get("role") not in roles:
                abort(403)
            return view_fn(*args, **kwargs)
        return wrapped
    return decorator


def user_roles_map():
    """Expose username -> role for optional UI hints on login page."""
    return {u: info["role"] for u, info in DEMO_USERS.items()}


# ----------------- error pages -----------------
@app.errorhandler(403)
def forbidden(_):
    return render_template("403.html"), 403


# ----------------- PUBLIC: content-first landing -----------------
@app.route("/")
def landing():
    """Public, content-focused page about dementia; tiny Sign in link only."""
    return render_template("landing.html")


# ----------------- Auth -----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        # 1) Verify CAPTCHA
        recaptcha_token = request.form.get("g-recaptcha-response", "")
        user_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
        if not verify_recaptcha(recaptcha_token, user_ip):
            flash("CAPTCHA verification failed. Please try again.", "danger")
            return redirect(url_for("login"))

        # 2) Check credentials
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        user = DEMO_USERS.get(username)

        if user and user["password"] == password:
            session["user"] = username
            session["role"] = user["role"]
            if user["role"] == "patient":
                _ensure_patient(username)
            flash(f"Welcome, {username}!", "success")
            return redirect(url_for("home"))

        flash("Invalid username or password.", "danger")
        return redirect(url_for("login"))

    # GET: dedicated login page
    return render_template(
        "login.html",
        recaptcha_site_key=RECAPTCHA_SITE_KEY,
        roles_map=user_roles_map()  # optional: for “Detected role” hint
    )


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("landing"))


# ----------------- Private pages -----------------
@app.route("/home")
@login_required
def home():
    """Common home page after login. Patients are sent to the hub."""
    role = session.get("role")
    if role == "patient":
        return redirect(url_for("patient_hub"))
    return render_template("home.html", user=session.get("user"), role=role)


# ---- Gallery helpers (used by /customer and patient gallery) ----
def list_categories():
    if not os.path.isdir(IMAGE_ROOT):
        return []
    return sorted(
        [d for d in os.listdir(IMAGE_ROOT) if os.path.isdir(os.path.join(IMAGE_ROOT, d))],
        key=str.lower
    )


def list_images(category):
    cat_dir = os.path.join(IMAGE_ROOT, category)
    if not os.path.isdir(cat_dir):
        return []
    items = []
    for f in os.listdir(cat_dir):
        base, ext = os.path.splitext(f)
        if ext.lower() in ALLOWED_IMAGE_EXTS:
            audio_rel = None
            for aext in AUDIO_EXTS_PREFERENCE:
                candidate = os.path.join(cat_dir, base + aext)
                if os.path.isfile(candidate):
                    audio_rel = f"customer_images/{category}/{base}{aext}"
                    break
            items.append({
                "img": f"customer_images/{category}/{f}",
                "audio": audio_rel,
                "name": f
            })
    return sorted(items, key=lambda x: x["name"].lower())


# ----------------- Existing gallery page (any logged-in user) -----------------
@app.route("/customer")
@login_required
def customer():
    categories = list_categories()
    selected = request.args.get("category") or (categories[0] if categories else None)
    images = list_images(selected) if selected else []
    return render_template(
        "customer.html",
        user=session.get("user"),
        role=session.get("role"),
        categories=categories,
        selected_category=selected,
        images=images
    )


# ----------------- Role dashboards -----------------
@app.route("/admin")
@role_required("admin")
def admin_home():
    return render_template("admin.html", user=session.get("user"), role=session.get("role"))


# === PATIENT: Hub + Feature Pages ===
@app.route("/patient")
@role_required("patient")
def patient_redirect_to_hub():
    """Keep /patient for compatibility; send to hub."""
    return redirect(url_for("patient_hub"))

@app.route("/patient/hub", methods=["GET"])
@role_required("patient")
def patient_hub():
    username = session.get("user")
    _ensure_patient(username)
    return render_template("patient_home.html", user=username, role=session.get("role"))

@app.route("/patient/gallery", methods=["GET"])
@role_required("patient")
def patient_gallery():
    categories = list_categories()
    selected = request.args.get("category") or (categories[0] if categories else None)
    images = list_images(selected) if selected else []
    return render_template("patient_gallery.html",
                           user=session.get("user"), role=session.get("role"),
                           categories=categories, selected_category=selected, images=images)

@app.route("/patient/meds", methods=["GET"])
@role_required("patient")
def patient_meds():
    username = session.get("user")
    _ensure_patient(username)
    data = PATIENT_DB[username]
    return render_template("patient_meds.html", user=username, role=session.get("role"), data=data)

@app.route("/patient/mood", methods=["GET"])
@role_required("patient")
def patient_mood():
    username = session.get("user")
    _ensure_patient(username)
    data = PATIENT_DB[username]
    return render_template("patient_mood.html", user=username, role=session.get("role"), data=data)

@app.route("/patient/memory", methods=["GET"])
@role_required("patient")
def patient_memory():
    username = session.get("user")
    _ensure_patient(username)
    data = PATIENT_DB[username]
    view = {"reminders": [{**r, "dt_pretty": _dt_pretty(r["dt"])} for r in data["reminders"]]}
    return render_template("patient_memory.html", user=username, role=session.get("role"), data=data, view=view)

@app.route("/patient/activities", methods=["GET"])
@role_required("patient")
def patient_activities():
    username = session.get("user")
    _ensure_patient(username)
    data = PATIENT_DB[username]
    return render_template("patient_activities.html", user=username, role=session.get("role"), data=data)

@app.route("/patient/games", methods=["GET"])
@role_required("patient")
def patient_games():
    return render_template("patient_games.html", user=session.get("user"), role=session.get("role"))

@app.route("/patient/dashboard", methods=["GET"])
@role_required("patient")
def patient_dashboard():
    username = session.get("user")
    _ensure_patient(username)
    d = PATIENT_DB[username]

    # --- core counts
    tasks_total = len(d["tasks"]); tasks_done = sum(1 for t in d["tasks"] if t["done"])
    meds_total = len(d["meds"]); meds_taken = sum(1 for m in d["meds"] if m["taken_today"])
    notes_count = len(d["notes"]); appts_count = len(d["appts"])
    reminders_active = sum(1 for r in d["reminders"] if r.get("active"))
    activities_done = sum(1 for a in d["activities"] if a["done_today"])
    mood = d["mood"]

    # --- next medication (today)
    from datetime import time as _time
    now = datetime.now().time()
    def _parse_hhmm(s):
        try:
            hh, mm = s.split(":")
            return _time(int(hh), int(mm))
        except Exception:
            return None
    future_meds = []
    for m in d["meds"]:
        t = _parse_hhmm(m["time"])
        if t:
            future_meds.append((t, m))
    future_meds.sort(key=lambda x: x[0])
    next_med = None
    for t, m in future_meds:
        if t >= now and not m["taken_today"]:
            next_med = {"name": m["name"], "time": t.strftime("%I:%M %p")}
            break

    # --- upcoming (next 3) appointments & reminders
    def _dt_key(x):  # safe sort key
        try:
            return datetime.fromisoformat(x["dt"])
        except Exception:
            return datetime.max
    appts_upcoming = sorted(d["appts"], key=_dt_key)[:3]
    rem_upcoming = sorted([r for r in d["reminders"] if r.get("active")], key=_dt_key)[:3]
    # pretty
    for a in appts_upcoming:
        a["dt_pretty"] = _dt_pretty(a["dt"])
    for r in rem_upcoming:
        r["dt_pretty"] = _dt_pretty(r["dt"])

    # --- simple 7-day trends (demo-friendly, deterministic)
    # meds adherence today:
    today_adherence = round(100 * meds_taken / meds_total, 1) if meds_total else 0.0
    # smooth historical pattern anchored to today
    base = [72, 81, 65, 90, 76, 84]
    meds_trend = base + [today_adherence]

    # mood score mapping for sparkline
    mood_map = {"😀 Cheerful": 5, "🙂 Calm": 4, "😐 Okay": 3, "😴 Tired": 2, "🙁 Low": 1}
    today_mood_score = mood_map.get(mood, 3)
    mood_trend = [3, 4, 3, 5, 2, 4, today_mood_score]

    # --- today metrics
    today_str = datetime.now().strftime("%Y-%m-%d")
    notes_today = sum(1 for n in d["notes"] if str(n.get("ts", "")).startswith(today_str))
    files_count = len(d["files"])

    stats = {
        "tasks": (tasks_done, tasks_total),
        "meds": (meds_taken, meds_total),
        "notes": notes_count,
        "appts": appts_count,
        "reminders_active": reminders_active,
        "activities_done": activities_done,
        "mood": mood,
        "notes_today": notes_today,
        "files_count": files_count,
    }

    viz = {
        "adherence_trend": meds_trend,   # 7 numbers (0–100)
        "mood_trend": mood_trend,        # 7 ints (1–5)
        "today_adherence": today_adherence
    }

    context = {
        "user": username,
        "role": session.get("role"),
        "stats": stats,
        "data": d,
        "next_med": next_med,
        "appts_upcoming": appts_upcoming,
        "rem_upcoming": rem_upcoming,
        "viz": viz,
    }
    return render_template("patient_dashboard.html", **context)


# === PATIENT: Actions & Uploads ===
@app.route("/patient/action", methods=["POST"])
@role_required("patient")
def patient_action():
    username = session.get("user")
    _ensure_patient(username)
    data = PATIENT_DB[username]
    action = request.form.get("action", "")
    ref = request.referrer

    # -------- Tasks --------
    if action == "add_task":
        title = request.form.get("task_title", "").strip()
        if title:
            data["tasks"].append({"id": str(uuid.uuid4()), "title": title, "done": False})
            flash("Task added.", "success")
        return redirect(ref or url_for("patient_hub"))

    if action == "toggle_task":
        tid = request.form.get("task_id")
        for t in data["tasks"]:
            if t["id"] == tid:
                t["done"] = not t["done"]
                break
        return redirect(ref or url_for("patient_hub"))

    if action == "delete_task":
        tid = request.form.get("task_id")
        data["tasks"] = [t for t in data["tasks"] if t["id"] != tid]
        return redirect(ref or url_for("patient_hub"))

    # -------- Meds --------
    if action == "add_med":
        name = request.form.get("med_name", "").strip()
        tm = request.form.get("med_time", "").strip()
        if name and tm:
            data["meds"].append({"id": str(uuid.uuid4()), "name": name, "time": tm, "taken_today": False})
            flash("Medication added.", "success")
        return redirect(ref or url_for("patient_meds"))

    if action == "toggle_med":
        mid = request.form.get("med_id")
        for m in data["meds"]:
            if m["id"] == mid:
                m["taken_today"] = not m["taken_today"]
                break
        return redirect(ref or url_for("patient_meds"))

    if action == "delete_med":
        mid = request.form.get("med_id")
        data["meds"] = [m for m in data["meds"] if m["id"] != mid]
        return redirect(ref or url_for("patient_meds"))

    # -------- Mood & Notes --------
    if action == "set_mood_and_note":
        mood = request.form.get("mood", "").strip() or data["mood"]
        note = request.form.get("note", "").strip()
        data["mood"] = mood
        if note:
            data["notes"].insert(0, {"id": str(uuid.uuid4()), "mood": mood, "text": note,
                                     "ts": datetime.now().strftime("%Y-%m-%d %H:%M")})
            flash("Mood & note saved.", "success")
        else:
            flash("Mood saved.", "success")
        return redirect(ref or url_for("patient_mood"))

    if action == "delete_note":
        nid = request.form.get("note_id")
        data["notes"] = [n for n in data["notes"] if n["id"] != nid]
        return redirect(ref or url_for("patient_mood"))

    # -------- Appointments (shown on hub or dashboard) --------
    if action == "add_appt":
        title = request.form.get("appt_title", "").strip()
        dt = request.form.get("appt_dt", "").strip()
        if title and dt:
            data["appts"].append({"id": str(uuid.uuid4()), "title": title, "dt": dt})
            flash("Appointment added.", "success")
        return redirect(ref or url_for("patient_hub"))

    if action == "delete_appt":
        aid = request.form.get("appt_id")
        data["appts"] = [a for a in data["appts"] if a["id"] != aid]
        return redirect(ref or url_for("patient_hub"))

    # -------- Files (delete from list & disk) --------
    if action == "delete_file":
        fname = request.form.get("file_name", "")
        data["files"] = [f for f in data["files"] if f["name"] != fname]
        try:
            os.remove(os.path.join(UPLOAD_FOLDER, fname))
        except Exception:
            pass
        flash("File removed.", "info")
        return redirect(ref or url_for("patient_hub"))

    # -------- Memory reminders --------
    if action == "add_reminder":
        title = request.form.get("rem_title", "").strip()
        dt = request.form.get("rem_dt", "").strip()
        kind = request.form.get("rem_kind", "general").strip()
        active = bool(request.form.get("rem_active"))
        if title and dt:
            data["reminders"].insert(0, {"id": str(uuid.uuid4()), "title": title,
                                         "dt": dt, "kind": kind, "active": active})
            flash("Reminder added.", "success")
        return redirect(url_for("patient_memory"))

    if action == "toggle_reminder":
        rid = request.form.get("rem_id")
        for r in data["reminders"]:
            if r["id"] == rid:
                r["active"] = not r["active"]
                break
        return redirect(url_for("patient_memory"))

    if action == "delete_reminder":
        rid = request.form.get("rem_id")
        data["reminders"] = [r for r in data["reminders"] if r["id"] != rid]
        return redirect(url_for("patient_memory"))

    # -------- Activities --------
    if action == "add_activity":
        title = request.form.get("act_title", "").strip()
        if title:
            data["activities"].append({"id": str(uuid.uuid4()), "title": title, "done_today": False})
            flash("Activity added.", "success")
        return redirect(url_for("patient_activities"))

    if action == "toggle_activity":
        aid = request.form.get("act_id")
        for a in data["activities"]:
            if a["id"] == aid:
                a["done_today"] = not a["done_today"]
                break
        return redirect(url_for("patient_activities"))

    if action == "delete_activity":
        aid = request.form.get("act_id")
        data["activities"] = [a for a in data["activities"] if a["id"] != aid]
        return redirect(url_for("patient_activities"))

    flash("Unknown action.", "warning")
    return redirect(url_for("patient_hub"))


@app.route("/patient/upload", methods=["POST"])
@role_required("patient")
def patient_upload():
    username = session.get("user")
    _ensure_patient(username)
    f = request.files.get("file")
    if not f or f.filename == "":
        flash("No file selected.", "warning")
        return redirect(url_for("patient_hub"))
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_UPLOADS:
        flash("Unsupported file type.", "danger")
        return redirect(url_for("patient_hub"))

    safe = secure_filename(f"{username}_{uuid.uuid4().hex}{ext}")
    f.save(os.path.join(UPLOAD_FOLDER, safe))
    PATIENT_DB[username]["files"].insert(0, {"name": safe})
    flash("File uploaded.", "success")
    return redirect(url_for("patient_hub"))


# ----------------- Caretaker -----------------
@app.route("/caretaker")
@role_required("caretaker")
def caretaker_home():
    return render_template("caretaker.html", user=session.get("user"), role=session.get("role"))


# ----------------- main -----------------
if __name__ == "__main__":
    app.run(debug=True)
