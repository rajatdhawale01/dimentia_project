
# Remove the duplicates and keep this up top:
import os
import requests
from functools import wraps
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort


#load_dotenv() 

app = Flask(__name__)
app.secret_key = "replace-with-a-strong-secret-key"


RECAPTCHA_SITE_KEY = '6LdMetgrAAAAAMYFn4ibFJVeKSG0KnGekxiTBgW7'
RECAPTCHA_SECRET_KEY = '6LdMetgrAAAAABt6VK9jYB-e7h8T4eLUGlhmo9Hf'

# Demo users (username -> password); in real apps use a DB + hashing
DEMO_USERS = {
    "rajat": "pass123",
    "admin": "admin123",
    "guest": "guest"
}

def verify_recaptcha(response_token, remote_ip=None):
    """
    Returns True/False based on Google reCAPTCHA verification.
    """
    if not RECAPTCHA_SECRET_KEY:
        # If not configured, skip (useful for quick dev); flip to False to enforce always.
        return True

    payload = {
        "secret": RECAPTCHA_SECRET_KEY,
        "response": response_token,
    }
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

@app.route("/")
@login_required
def home():
    return render_template("home.html", user=session.get("user"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        # 1) Verify CAPTCHA
        recaptcha_token = request.form.get("g-recaptcha-response", "")
        user_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
        if not verify_recaptcha(recaptcha_token, user_ip):
            flash("CAPTCHA verification failed. Please try again.", "danger")
            return render_template("login.html", recaptcha_site_key=RECAPTCHA_SITE_KEY), 400

        # 2) Check credentials
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        if username in DEMO_USERS and DEMO_USERS[username] == password:
            session["user"] = username
            flash(f"Welcome, {username}!", "success")
            return redirect(url_for("home"))
        flash("Invalid username or password.", "danger")
        return render_template("login.html", recaptcha_site_key=RECAPTCHA_SITE_KEY), 401

    return render_template("login.html", recaptcha_site_key=RECAPTCHA_SITE_KEY)

@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))





# ---- Customer Gallery Config ----
IMAGE_ROOT = os.path.join(app.static_folder, "customer_images")
ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
# Prefer web-friendly audio first; .mov last (works on Safari; Chrome support depends on codec).
AUDIO_EXTS_PREFERENCE = [".mp3", ".m4a", ".ogg", ".wav", ".mp4", ".mov"]


def list_categories():
    if not os.path.isdir(IMAGE_ROOT):
        return []
    cats = [d for d in os.listdir(IMAGE_ROOT)
            if os.path.isdir(os.path.join(IMAGE_ROOT, d))]
    return sorted(cats, key=str.lower)


def list_images(category):
    """
    Return list of dicts: [{ 'img': <static-rel>, 'audio': <static-rel or None>, 'name': <filename> }, ...]
    Where <static-rel> is relative to /static (usable with url_for('static', filename=...)).
    """
    cat_dir = os.path.join(IMAGE_ROOT, category)
    if not os.path.isdir(cat_dir):
        return []

    items = []
    for f in os.listdir(cat_dir):
        base, ext = os.path.splitext(f)
        if ext.lower() in ALLOWED_IMAGE_EXTS:
            # Find best matching audio with same base name
            audio_rel = None
            for aext in AUDIO_EXTS_PREFERENCE:
                candidate_fs = os.path.join(cat_dir, base + aext)
                if os.path.isfile(candidate_fs):
                    audio_rel = f"customer_images/{category}/{base}{aext}"
                    break
            items.append({
                "img": f"customer_images/{category}/{f}",
                "audio": audio_rel,
                "name": f
            })
    return sorted(items, key=lambda x: x["name"].lower())


@app.route("/customer")
@login_required
def customer():
    # Default: show the first category (if any) or none selected
    categories = list_categories()
    selected = request.args.get("category") or (categories[0] if categories else None)
    images = list_images(selected) if selected else []
    return render_template(
        "customer.html",
        user=session.get("user"),
        categories=categories,
        selected_category=selected,
        images=images
    )

@app.route("/customer/<category>")
@login_required
def customer_category(category):
    categories = list_categories()
    if category not in categories:
        # If someone typed a bad category, show 404 or redirect.
        abort(404)
    images = list_images(category)
    return render_template(
        "customer.html",
        user=session.get("user"),
        categories=categories,
        selected_category=category,
        images=images
    )


@app.route("/client")
@login_required
def client():
    return render_template("client.html", user=session.get("user"))

@app.route("/admin")
@login_required
def admin():
    return render_template("admin.html", user=session.get("user"))

if __name__ == "__main__":
    app.run(debug=True)
