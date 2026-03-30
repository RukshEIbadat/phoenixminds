from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import csv
import os
from collections import defaultdict

from functools import wraps
from urllib.parse import urlparse

def login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            # Remember where the user wanted to go
            dest = request.path
            flash("Please log in to continue.", "info")
            return redirect(url_for("login", next=dest))
        return view_func(*args, **kwargs)
    return wrapper

# ---------- Folders (create if missing) ----------
BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

EVALUATIONS_DIR = os.path.join(DATA_DIR, "evaluations")
os.makedirs(EVALUATIONS_DIR, exist_ok=True)

FAMILY_DIR = os.path.join(DATA_DIR, "journeys")
os.makedirs(FAMILY_DIR, exist_ok=True)

USERS_CSV = os.path.join(DATA_DIR, "users.csv")
CONDITIONS_CSV = os.path.join(DATA_DIR, "conditions.csv")  # master list

# ---------- Flask ----------
app = Flask(__name__)
app.secret_key = "change-me-to-a-strong-secret"   # needed for sessions

# ---------- Ensure users CSV exists ----------
if not os.path.exists(USERS_CSV):
    with open(USERS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["fullname", "email", "password", "role", "specialization"])

# ---------- Users helpers ----------
def read_users():
    users = []
    if os.path.exists(USERS_CSV):
        with open(USERS_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                users.append(row)
    return users

def find_user(email):
    email = (email or "").strip().lower()
    for u in read_users():
        if u["email"].strip().lower() == email:
            return u
    return None

def add_user(fullname, email, password, role, specialization):
    if find_user(email):  # prevent duplicate email
        return False
    with open(USERS_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([fullname, email, password, role, specialization])
    return True

# ---------- Admin seed (optional) ----------
def ensure_admin_account():
    admin_email = "admin@phoenixminds.com"
    admin_pass = "admin123"   # change to a strong password
    if not find_user(admin_email):
        with open(USERS_CSV, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Admin", admin_email, admin_pass, "Admin", ""])
        print("Admin account created:", admin_email, admin_pass)

ensure_admin_account()

# ---------- Conditions loader ----------
def load_conditions():
    """
    Reads conditions.csv and returns:
      - conditions: list of dicts
      - symptom_bank: sorted list of unique symptoms
    """
    conditions = []
    symptoms_set = set()

    if not os.path.exists(CONDITIONS_CSV):
        return [], []

    with open(CONDITIONS_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            def split_clean(s):
                if not s:
                    return []
                return [x.strip().lower() for x in s.split("|") if x.strip()]

            row["symptom_list"] = split_clean(row.get("symptoms", ""))
            row["synonym_list"] = split_clean(row.get("synonyms", ""))
            row["red_flag_list"] = split_clean(row.get("red_flags", ""))
            row["referral_list"] = split_clean(row.get("referral_to", ""))
            conditions.append(row)

            for s in row["symptom_list"]:
                symptoms_set.add(s)

    symptom_bank = sorted(symptoms_set)
    return conditions, symptom_bank

CONDITIONS, SYMPTOM_BANK = load_conditions()

# ---------- Simple matcher ----------
def score_conditions(selected):
    """
    selected: list[str] of chosen symptoms (lowercase)
    Returns sorted list of (score, match_count, condition_dict)
    """
    if not selected:
        return []

    sel_set = set(s.strip().lower() for s in selected if s.strip())
    results = []
    for c in CONDITIONS:
        c_syms = set(c["symptom_list"])
        inter = c_syms.intersection(sel_set)
        if not c_syms:
            continue
        jaccard = len(inter) / len(c_syms)
        score = (len(inter) * 1.2) + (jaccard * 1.0)
        results.append((round(score, 4), len(inter), c, sorted(list(inter))))

    results.sort(key=lambda t: (-t[0], -t[1], t[2].get("condition", "")))
    return results

# ---------- Session helpers in templates ----------
@app.context_processor
def inject_session_flags():
    user = session.get("user")
    return {
        "session_user": user,
        "session_user_name": (user["fullname"] if user else None),
    }

# ---------- Routes ----------
@app.route("/")
def home():
    return render_template("main.html")

@app.route("/services")
def services():
    return render_template("services.html")

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        contacts_csv = os.path.join(DATA_DIR, "contact_messages.csv")
        is_new = not os.path.exists(contacts_csv)
        with open(contacts_csv, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if is_new:
                writer.writerow(["name", "email", "subject", "message"])
            writer.writerow([
                request.form.get("name","").strip(),
                request.form.get("email","").strip().lower(),
                request.form.get("subject","").strip(),
                request.form.get("message","").strip()
            ])
        flash("Thanks! Your message has been sent.", "success")
        return redirect(url_for("contact"))
    return render_template("contact.html")

# ----- New journey (family dossier) -----
@app.route("/journey", methods=["GET"])
@login_required
def journey():
    return render_template("journey.html")

@app.post("/api/journey")
@login_required
def api_create_journey():
    import time, json
    payload = request.get_json(silent=True, force=True) or {}
    child = payload.get("child", {})
    if not child.get("name"):
        return jsonify({"ok": False, "error": "Child name is required"}), 400

    ts = int(time.time())
    fname = f"journey_{ts}.json"
    fpath = os.path.join(FAMILY_DIR, fname)
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return jsonify({"ok": True, "id": fname})

# ----- Child / IEP / Connect pages -----
@app.route("/child")
def child_profile():
    return render_template("child.html")

@app.route("/iep")
def iep():
    return render_template("iep.html")

@app.route("/connect")
def connect():
    return render_template("connect.html")

# ----- Auth -----
@app.route("/login", methods=["GET", "POST"])
def login():
    next_url = request.args.get("next")  # e.g., /journey
    if request.method == "POST":
        # Pull from POST and normalize
        email = (request.form.get("email") or "").strip().lower()
        password = (request.form.get("password") or "").strip()

        user = find_user(email)
        if user and user.get("password", "").strip() == password:
            session["user"] = {
                "fullname": user.get("fullname", ""),
                "email": user.get("email", ""),
                "role": user.get("role", ""),
            }
            flash("Welcome back!", "success")

            # Prefer a local 'next' target if present
            to = (request.form.get("next") or request.args.get("next") or "").strip()
            if to.startswith("/"):
                return redirect(to)
            return redirect(url_for("home"))

        flash("Invalid email or password.", "error")

    return render_template("login.html", next=next_url)

@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("You have been logged out.", "info")
    return redirect(url_for("home"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        fullname = request.form.get("fullname", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "")
        specialization = request.form.get("specialization", "")

        if not (fullname and email and password and role):
            flash("Please fill in all required fields.", "error")
            return render_template("create_account.html")

        if add_user(fullname, email, password, role, specialization):
            session["user"] = {"fullname": fullname, "email": email, "role": role}
            flash("Account created successfully!", "success")
            return redirect(url_for("home"))
        else:
            flash("An account with that email already exists.", "error")
    return render_template("create_account.html")

# ---------- Evaluation ----------
@app.post("/api/evaluation", endpoint="api_create_evaluation")
def api_create_evaluation():
    """
    Minimal API to accept the evaluation JSON payload from the front-end.
    Saves a copy to data/evaluations for now; you can replace with DB logic later.
    """
    payload = request.get_json(silent=True, force=True) or {}
    required = ["child_first_name", "child_last_name", "dob", "caregiver_name", "email"]
    missing = [k for k in required if not payload.get(k)]
    if missing:
        return jsonify({"ok": False, "error": f"Missing fields: {', '.join(missing)}"}), 400

    import time, json
    ts = int(time.time())
    fname = f"evaluation_{ts}.json"
    fpath = os.path.join(EVALUATIONS_DIR, fname)
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return jsonify({"ok": True, "id": fname, "saved_to": fpath}), 201

@app.route("/evaluation", methods=["GET", "POST"])
def evaluation():
    if request.method == "POST":
        selected = request.form.getlist("symptoms")
        free_text = request.form.get("free_text", "").strip().lower()
        if free_text:
            for token in [t.strip() for t in free_text.split(",") if t.strip()]:
                selected.append(token)

        matches = score_conditions(selected)
        top = matches[:8]

        referrals = defaultdict(int)
        red_flags = set()
        for _, _, c, inter in top:
            for ref in c["referral_list"]:
                referrals[ref] += 1
            for rf in c["red_flag_list"]:
                red_flags.add(rf)

        referral_list = sorted(referrals.items(), key=lambda x: (-x[1], x[0]))

        return render_template(
            "evaluation_report.html",
            selected=selected,
            results=top,
            referral_list=referral_list,
            red_flags=sorted(list(red_flags)),
        )

    return render_template("evaluation.html", symptom_bank=SYMPTOM_BANK)

# ---------- Main ----------
if __name__ == "__main__":
    app.run(debug=True)