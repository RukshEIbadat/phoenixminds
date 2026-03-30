"""
PhoenixMinds — Complete Production Backend
Flask + OpenAI + Anthropic Claude + Google Gemini + Groq + Whisper
Real-time Translation · AI Evaluation · IEP Generation · Medication Safety
"""

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response, stream_with_context
import csv, os, json, time, hashlib
from functools import wraps
from collections import defaultdict
import re

# ── Optional heavy imports (fail gracefully) ──────────────────────────────────
try:
    from openai import OpenAI
    openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY",""))
    OPENAI_OK = True
except Exception:
    openai_client = None
    OPENAI_OK = False

try:
    import anthropic
    claude_client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY",""))
    CLAUDE_OK = True
except Exception:
    claude_client = None
    CLAUDE_OK = False

try:
    import google.generativeai as genai
    genai.configure(api_key=os.environ.get("GOOGLE_API_KEY",""))
    GEMINI_OK = True
except Exception:
    GEMINI_OK = False

try:
    from groq import Groq
    groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY",""))
    GROQ_OK = True
except Exception:
    groq_client = None
    GROQ_OK = False

# ── Flask app ─────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(__file__)
DATA_DIR   = os.path.join(BASE_DIR, "data")
EVALS_DIR  = os.path.join(DATA_DIR, "evaluations")
JOURNEY_DIR= os.path.join(DATA_DIR, "journeys")
IEP_DIR    = os.path.join(DATA_DIR, "ieps")
MEDS_DIR   = os.path.join(DATA_DIR, "medications")

for d in [DATA_DIR, EVALS_DIR, JOURNEY_DIR, IEP_DIR, MEDS_DIR]:
    os.makedirs(d, exist_ok=True)

USERS_CSV = os.path.join(DATA_DIR, "users.csv")
CONDITIONS_CSV = os.path.join(DATA_DIR, "conditions.csv")

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET","phoenixminds-2026-ultra-secure-key-change-me")

# ── User management ────────────────────────────────────────────────────────────
def ensure_users_csv():
    if not os.path.exists(USERS_CSV):
        with open(USERS_CSV,"w",newline="",encoding="utf-8") as f:
            csv.writer(f).writerow(["id","fullname","email","password_hash","role","specialization","country","phone","is_admin","created_at"])

def hash_pw(pw): return hashlib.sha256(pw.encode()).hexdigest()

def read_users():
    if not os.path.exists(USERS_CSV): return []
    with open(USERS_CSV,newline="",encoding="utf-8") as f:
        return list(csv.DictReader(f))

def find_user(email):
    email = (email or "").strip().lower()
    for u in read_users():
        if u.get("email","").strip().lower() == email:
            return u
    return None

def find_user_by_id(uid):
    for u in read_users():
        if u.get("id","") == uid:
            return u
    return None

def add_user(fullname, email, password, role, spec="", country="", phone="", is_admin="0"):
    ensure_users_csv()
    if find_user(email): return False, "Email already registered"
    uid = f"pm_{int(time.time()*1000)}"
    with open(USERS_CSV,"a",newline="",encoding="utf-8") as f:
        csv.writer(f).writerow([uid,fullname,email,hash_pw(password),role,spec,country,phone,is_admin,time.strftime("%Y-%m-%dT%H:%M:%S")])
    return True, uid

def ensure_admin():
    ensure_users_csv()
    if not find_user("admin@phoenixminds.org"):
        add_user("Admin PhoenixMinds","admin@phoenixminds.org","Admin@2026","Admin","Platform Administration","Pakistan","",is_admin="1")
    if not find_user("demo@phoenixminds.org"):
        add_user("Ayesha Khan","demo@phoenixminds.org","Demo@2026","Parent / Caregiver","","Pakistan","+92-300-1234567")

ensure_admin()

def login_required(f):
    @wraps(f)
    def w(*a,**k):
        if not session.get("user"):
            dest = request.path
            flash("Please log in to continue.","info")
            return redirect(url_for("login", next=dest))
        return f(*a,**k)
    return w

def admin_required(f):
    @wraps(f)
    def w(*a,**k):
        u = session.get("user",{})
        if not u.get("is_admin"):
            flash("Admin access required.","error")
            return redirect(url_for("home"))
        return f(*a,**k)
    return w

@app.context_processor
def inject_session():
    user = session.get("user")
    return {"session_user": user, "session_user_name": (user["fullname"] if user else None), "is_admin": bool(user and user.get("is_admin"))}

# ── Conditions loader ──────────────────────────────────────────────────────────
def load_conditions():
    conditions, symptoms_set = [], set()
    if not os.path.exists(CONDITIONS_CSV): return [], []
    with open(CONDITIONS_CSV,newline="",encoding="utf-8") as f:
        for row in csv.DictReader(f):
            def sc(s): return [x.strip().lower() for x in (s or "").split("|") if x.strip()]
            row["symptom_list"] = sc(row.get("symptoms",""))
            row["synonym_list"]  = sc(row.get("synonyms",""))
            row["red_flag_list"] = sc(row.get("red_flags",""))
            row["referral_list"] = sc(row.get("referral_to",""))
            conditions.append(row)
            for s in row["symptom_list"]: symptoms_set.add(s)
    return conditions, sorted(symptoms_set)

CONDITIONS, SYMPTOM_BANK = load_conditions()

def score_conditions(selected):
    if not selected: return []
    sel = set(s.strip().lower() for s in selected if s.strip())
    results = []
    for c in CONDITIONS:
        cs = set(c["symptom_list"])
        if not cs: continue
        inter = cs & sel
        jaccard = len(inter)/len(cs)
        score = (len(inter)*1.2)+(jaccard*1.0)
        results.append((round(score,4), len(inter), c, sorted(inter)))
    results.sort(key=lambda t:(-t[0],-t[1],t[2].get("condition","")))
    return results

# ── AI HELPERS ────────────────────────────────────────────────────────────────

def ai_translate(text, target_lang, source_lang="auto"):
    """Multi-provider translation cascade: Groq fast → Claude precise → GPT-4o fallback"""
    if not text or target_lang in ("en","English"): return text
    prompt = f"""Translate the following text to {target_lang}. Return ONLY the translated text, nothing else. Preserve all formatting, medical terminology accuracy is critical.

Text: {text}"""
    # Groq fastest (free tier)
    if GROQ_OK:
        try:
            r = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role":"user","content":prompt}],
                max_tokens=2000, temperature=0.1
            )
            return r.choices[0].message.content.strip()
        except Exception: pass
    # Claude for accuracy
    if CLAUDE_OK:
        try:
            r = claude_client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2000,
                messages=[{"role":"user","content":prompt}]
            )
            return r.content[0].text.strip()
        except Exception: pass
    # GPT-4o fallback
    if OPENAI_OK:
        try:
            r = openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role":"user","content":prompt}],
                max_tokens=2000, temperature=0.1
            )
            return r.choices[0].message.content.strip()
        except Exception: pass
    return text

def ai_generate_iep(child_name, age, diagnosis, curriculum, concerns, riasec_code=""):
    """Generate a full SMART IEP using Claude/GPT-4o"""
    prompt = f"""You are a specialist special education consultant. Generate a complete, evidence-based Individual Education Program (IEP) for:

Child: {child_name}
Age: {age}
Diagnosis: {diagnosis}
Curriculum: {curriculum}
Primary Concerns: {concerns}
RIASEC Interest Profile: {riasec_code if riasec_code else 'Not assessed'}

Generate a professional IEP with:
1. Present Levels of Performance (PLOP) — 3 domains
2. 5 SMART Annual Goals — each with measurable criteria, timeline, domain
3. 3 Short-Term Objectives per goal
4. Accommodations & Modifications list
5. Related Services (specify frequency)
6. Home Programme recommendations
7. Progress monitoring method

Format as structured JSON with keys: plop, goals, accommodations, services, home_programme, monitoring
Each goal must have: domain, goal_text, criteria, timeline, objectives array, riasec_alignment"""

    if CLAUDE_OK:
        try:
            r = claude_client.messages.create(
                model="claude-sonnet-4-6", max_tokens=4000,
                messages=[{"role":"user","content":prompt}]
            )
            text = r.content[0].text.strip()
            if text.startswith("{") or "```json" in text:
                text = re.sub(r"```json|```","",text).strip()
                return json.loads(text)
        except Exception as e:
            pass

    if OPENAI_OK:
        try:
            r = openai_client.chat.completions.create(
                model="gpt-4o", messages=[{"role":"user","content":prompt}],
                max_tokens=4000, temperature=0.3,
                response_format={"type":"json_object"}
            )
            return json.loads(r.choices[0].message.content)
        except Exception: pass

    # Fallback structured IEP
    return {
        "plop": [
            {"domain":"Communication","strengths":f"{child_name} demonstrates emerging functional communication","needs":"Requires support with expressive language and social pragmatics"},
            {"domain":"Academic","strengths":"Shows strengths in visual-spatial tasks and pattern recognition","needs":f"Requires modified instruction aligned to {curriculum} standards"},
            {"domain":"Social-Emotional","strengths":"Engages well in structured 1:1 activities","needs":"Support needed for peer interaction and self-regulation in group settings"}
        ],
        "goals": [
            {"domain":"Communication","goal_text":f"By end of term, {child_name} will use 3-4 word functional phrases in 4 of 5 opportunities","criteria":"80% accuracy across 3 consecutive sessions","timeline":"1 academic term","objectives":["Identify 10 core vocabulary items","Use 2-word combinations in structured activities","Generalise phrases to classroom setting"],"riasec_alignment":riasec_code},
            {"domain":"Literacy","goal_text":f"By end of term, {child_name} will decode CVC words with 80% accuracy","criteria":"80% accuracy on weekly probe","timeline":"1 academic term","objectives":["Master all consonant sounds","Blend 2-phoneme words","Read 20 decodable CVC words independently"],"riasec_alignment":""},
            {"domain":"Social","goal_text":f"By end of term, {child_name} will initiate peer interaction in 3 of 5 structured play opportunities","criteria":"3 of 5 observed opportunities","timeline":"1 academic term","objectives":["Identify preferred peers","Use greeting script","Sustain joint play for 3 minutes"],"riasec_alignment":""},
            {"domain":"Self-Regulation","goal_text":f"By end of term, {child_name} will use a 3-step calming strategy independently when dysregulated","criteria":"Independently 4 of 5 occurrences","timeline":"1 academic term","objectives":["Identify 3 emotions on visual scale","Request a break using AAC/words","Complete 3-step calming sequence"],"riasec_alignment":""},
            {"domain":"Fine Motor","goal_text":f"By end of term, {child_name} will form all letters with correct pencil grip","criteria":"90% legibility on weekly writing sample","timeline":"1 academic term","objectives":["Maintain tripod grip for 5 min","Trace letter formations","Copy from whiteboard independently"],"riasec_alignment":""}
        ],
        "accommodations":["Extended time on all assessments","Preferential seating near teacher","Visual schedules and timers","Modified/shortened assignments","Frequent movement breaks","AAC device access at all times","Noise-reducing headphones available"],
        "services":["Speech-Language Therapy: 2x per week, 30 min, pull-out and push-in","Occupational Therapy: 1x per week, 45 min","ABA/Behaviour Support: 10 hours per week","Specialist Teacher: daily support in core subjects"],
        "home_programme":["15 min daily phonics practice using decodable readers","10 min fine motor warm-up (play-dough, lacing)","Visual bedtime routine with symbol schedule","Weekend community outing aligned to RIASEC interests","Daily communication book between home and school"],
        "monitoring":{"method":"Data collection on each goal during therapy and classroom sessions","frequency":"Weekly progress notes; monthly data review","review_date":"End of current academic term","responsible_persons":["Class Teacher","Speech-Language Pathologist","Occupational Therapist","Parent/Caregiver"]}
    }

def ai_evaluate_symptoms(symptoms, free_text="", child_name="", age=""):
    """AI-powered clinical evaluation using Claude + GPT-4o ensemble"""
    rule_based = score_conditions(symptoms)
    top_rule = rule_based[:5]

    if not (CLAUDE_OK or OPENAI_OK or GROQ_OK):
        return {"rule_based": top_rule, "ai_analysis": None, "error": "No AI provider available"}

    conditions_text = "\n".join([f"- {c[2].get('condition','?')} ({c[1]} symptom matches, score {c[0]})" for c in top_rule]) if top_rule else "No matches from database"
    prompt = f"""You are a consultant paediatric neurologist reviewing an early developmental screening. This is a CLINICAL DECISION SUPPORT tool — not a diagnosis. A qualified clinician must confirm all findings.

Child: {child_name if child_name else 'Unknown'}, Age: {age if age else 'Unknown'}
Selected observations: {', '.join(symptoms) if symptoms else 'None'}
Additional notes: {free_text if free_text else 'None'}
Rule-based matches:\n{conditions_text}

Provide a clinical summary in JSON with:
- summary: 2-3 sentence clinical narrative
- primary_concern: most likely area of concern (single string)
- confidence: percentage (0-100)
- differential: array of 3 conditions with name, confidence_pct, rationale, recommended_specialist
- red_flags: array of urgent concerns requiring immediate referral
- next_steps: array of recommended assessments
- disclaimer: professional disclaimer string

Be appropriately cautious. Do not use language that implies diagnosis."""

    if CLAUDE_OK:
        try:
            r = claude_client.messages.create(
                model="claude-sonnet-4-6", max_tokens=2000,
                messages=[{"role":"user","content":prompt}]
            )
            text = re.sub(r"```json|```","",r.content[0].text).strip()
            ai_result = json.loads(text)
            return {"rule_based":top_rule,"ai_analysis":ai_result}
        except Exception: pass

    if OPENAI_OK:
        try:
            r = openai_client.chat.completions.create(
                model="gpt-4o", max_tokens=2000, temperature=0.2,
                response_format={"type":"json_object"},
                messages=[{"role":"user","content":prompt}]
            )
            return {"rule_based":top_rule,"ai_analysis":json.loads(r.choices[0].message.content)}
        except Exception: pass

    return {"rule_based":top_rule,"ai_analysis":None}

# ── ROUTES — MAIN PAGES ────────────────────────────────────────────────────────

@app.route("/")
def home():
    return render_template("main.html")

@app.route("/services")
def services():
    return render_template("services.html")

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/contact", methods=["GET","POST"])
def contact():
    if request.method == "POST":
        p = request.form
        f_path = os.path.join(DATA_DIR,"contact_messages.csv")
        is_new = not os.path.exists(f_path)
        with open(f_path,"a",newline="",encoding="utf-8") as f:
            w = csv.writer(f)
            if is_new: w.writerow(["name","email","subject","message","sent_at"])
            w.writerow([p.get("name",""),p.get("email",""),p.get("subject",""),p.get("message",""),time.strftime("%Y-%m-%dT%H:%M:%S")])
        flash("Message sent! We will reply within 24 hours.","success")
        return redirect(url_for("contact"))
    return render_template("contact.html")

# ── AUTH ────────────────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET","POST"])
def login():
    next_url = request.args.get("next","")
    if request.method == "POST":
        email = (request.form.get("email","")).strip().lower()
        pw    = (request.form.get("password","")).strip()
        user  = find_user(email)
        if user and user.get("password_hash","") == hash_pw(pw):
            session["user"] = {
                "id":user.get("id",""),
                "fullname":user.get("fullname",""),
                "email":user.get("email",""),
                "role":user.get("role",""),
                "is_admin": user.get("is_admin","0") == "1"
            }
            flash(f"Welcome back, {user.get('fullname','').split()[0]}!","success")
            if user.get("is_admin","0") == "1":
                return redirect(url_for("admin_panel"))
            to = request.form.get("next","") or next_url
            return redirect(to if to.startswith("/") else url_for("dashboard"))
        flash("Invalid email or password.","error")
    return render_template("login.html", next=next_url)

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        p = request.form
        fullname = p.get("fullname","").strip()
        email    = p.get("email","").strip().lower()
        pw       = p.get("password","")
        pw2      = p.get("password2","")
        role     = p.get("role","")
        spec     = p.get("specialization","")
        country  = p.get("country","")
        phone    = p.get("phone","")
        if not all([fullname,email,pw,role]):
            flash("Please fill all required fields.","error")
            return render_template("create_account.html")
        if pw != pw2:
            flash("Passwords do not match.","error")
            return render_template("create_account.html")
        if len(pw) < 6:
            flash("Password must be at least 6 characters.","error")
            return render_template("create_account.html")
        ok, msg = add_user(fullname,email,pw,role,spec,country,phone)
        if ok:
            session["user"] = {"id":msg,"fullname":fullname,"email":email,"role":role,"is_admin":False}
            flash("Account created! Welcome to PhoenixMinds.","success")
            return redirect(url_for("dashboard"))
        flash(msg,"error")
    return render_template("create_account.html")

@app.route("/logout")
def logout():
    session.pop("user",None)
    flash("You have been logged out.","info")
    return redirect(url_for("home"))

# ── DASHBOARD ───────────────────────────────────────────────────────────────────

@app.route("/dashboard")
@login_required
def dashboard():
    user = session["user"]
    role = user.get("role","").lower()
    journeys = []
    for fn in os.listdir(JOURNEY_DIR):
        if fn.endswith(".json"):
            try:
                with open(os.path.join(JOURNEY_DIR,fn)) as f:
                    journeys.append(json.load(f))
            except: pass
    ieps = []
    for fn in os.listdir(IEP_DIR):
        if fn.endswith(".json"):
            try:
                with open(os.path.join(IEP_DIR,fn)) as f:
                    ieps.append(json.load(f))
            except: pass
    stats = {"children":len(journeys),"ieps":len(ieps),"evals":len(os.listdir(EVALS_DIR)),"users":len(read_users())}
    return render_template("dashboard.html", stats=stats, journeys=journeys, ieps=ieps)

# ── ADMIN ────────────────────────────────────────────────────────────────────────

@app.route("/admin")
@login_required
@admin_required
def admin_panel():
    users = read_users()
    journeys = []
    for fn in os.listdir(JOURNEY_DIR):
        if fn.endswith(".json"):
            try:
                with open(os.path.join(JOURNEY_DIR,fn)) as f: journeys.append(json.load(f))
            except: pass
    evals = []
    for fn in os.listdir(EVALS_DIR):
        if fn.endswith(".json"):
            try:
                with open(os.path.join(EVALS_DIR,fn)) as f: evals.append(json.load(f))
            except: pass
    contacts = []
    cf = os.path.join(DATA_DIR,"contact_messages.csv")
    if os.path.exists(cf):
        with open(cf,newline="",encoding="utf-8") as f:
            contacts = list(csv.DictReader(f))
    stats = {
        "total_users":len(users),"total_journeys":len(journeys),
        "total_evals":len(evals),"total_messages":len(contacts),
        "conditions":len(CONDITIONS),"languages":50
    }
    return render_template("admin.html", users=users, journeys=journeys, evals=evals, contacts=contacts, stats=stats)

# ── JOURNEY ─────────────────────────────────────────────────────────────────────

@app.route("/journey")
@login_required
def journey():
    return render_template("journey.html")

@app.post("/api/journey")
@login_required
def api_create_journey():
    payload = request.get_json(silent=True, force=True) or {}
    child = payload.get("child",{})
    if not child.get("name"):
        return jsonify({"ok":False,"error":"Child name required"}), 400
    ts    = int(time.time())
    uid   = session["user"].get("id","unknown")
    fname = f"journey_{uid}_{ts}.json"
    payload["created_by"] = uid
    payload["created_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open(os.path.join(JOURNEY_DIR,fname),"w",encoding="utf-8") as f:
        json.dump(payload,f,ensure_ascii=False,indent=2)
    return jsonify({"ok":True,"id":fname})

# ── EVALUATION ───────────────────────────────────────────────────────────────────

@app.route("/evaluation", methods=["GET","POST"])
def evaluation():
    if request.method == "POST":
        selected = request.form.getlist("symptoms")
        free_text = request.form.get("free_text","").strip()
        child_name = request.form.get("child_name","").strip()
        age = request.form.get("age","").strip()
        if free_text:
            for token in [t.strip() for t in free_text.split(",") if t.strip()]:
                selected.append(token)
        result = ai_evaluate_symptoms(selected, free_text, child_name, age)
        # save
        ts = int(time.time())
        fname = f"eval_{ts}.json"
        with open(os.path.join(EVALS_DIR,fname),"w",encoding="utf-8") as f:
            json.dump({"selected":selected,"free_text":free_text,"child":child_name,"age":age,"result":result,"saved_at":time.strftime("%Y-%m-%dT%H:%M:%S")},f,ensure_ascii=False,indent=2)
        return render_template("evaluation_report.html", selected=selected, result=result, child_name=child_name, age=age)
    return render_template("evaluation.html", symptom_bank=SYMPTOM_BANK)

# ── IEP ──────────────────────────────────────────────────────────────────────────

@app.route("/iep")
def iep():
    ieps = []
    for fn in os.listdir(IEP_DIR):
        if fn.endswith(".json"):
            try:
                with open(os.path.join(IEP_DIR,fn)) as f: ieps.append(json.load(f))
            except: pass
    return render_template("iep.html", ieps=ieps)

@app.post("/api/generate-iep")
def api_generate_iep():
    d = request.get_json(silent=True,force=True) or {}
    child_name  = d.get("child_name","Child")
    age         = d.get("age","")
    diagnosis   = d.get("diagnosis","")
    curriculum  = d.get("curriculum","Cambridge")
    concerns    = d.get("concerns","")
    riasec      = d.get("riasec","")
    if not diagnosis:
        return jsonify({"ok":False,"error":"Diagnosis required"}), 400
    iep_data = ai_generate_iep(child_name,age,diagnosis,curriculum,concerns,riasec)
    ts    = int(time.time())
    uid   = session.get("user",{}).get("id","anon")
    fname = f"iep_{uid}_{ts}.json"
    save_obj = {"child_name":child_name,"age":age,"diagnosis":diagnosis,"curriculum":curriculum,"iep":iep_data,"created_at":time.strftime("%Y-%m-%dT%H:%M:%S"),"created_by":uid}
    with open(os.path.join(IEP_DIR,fname),"w",encoding="utf-8") as f:
        json.dump(save_obj,f,ensure_ascii=False,indent=2)
    return jsonify({"ok":True,"iep":iep_data,"id":fname})

# ── CHILD PROFILE ───────────────────────────────────────────────────────────────

@app.route("/child")
def child_profile():
    journeys = []
    for fn in os.listdir(JOURNEY_DIR):
        if fn.endswith(".json"):
            try:
                with open(os.path.join(JOURNEY_DIR,fn)) as f: journeys.append(json.load(f))
            except: pass
    return render_template("child.html", journeys=journeys)

# ── CONNECT ──────────────────────────────────────────────────────────────────────

@app.route("/connect")
def connect():
    return render_template("connect.html")

# ── MEDICATION ───────────────────────────────────────────────────────────────────

@app.route("/medications")
@login_required
def medications():
    uid = session["user"].get("id","")
    meds_file = os.path.join(MEDS_DIR, f"meds_{uid}.json")
    meds = []
    if os.path.exists(meds_file):
        with open(meds_file) as f: meds = json.load(f)
    return render_template("medications.html", meds=meds)

@app.post("/api/medications/save")
@login_required
def api_save_meds():
    uid = session["user"].get("id","")
    d = request.get_json(silent=True,force=True) or {}
    meds = d.get("meds",[])
    meds_file = os.path.join(MEDS_DIR, f"meds_{uid}.json")
    with open(meds_file,"w") as f: json.dump(meds,f,ensure_ascii=False,indent=2)
    return jsonify({"ok":True})

@app.post("/api/medications/confirm")
@login_required
def api_confirm_med():
    d = request.get_json(silent=True,force=True) or {}
    uid = session["user"].get("id","")
    meds_file = os.path.join(MEDS_DIR, f"meds_{uid}.json")
    if os.path.exists(meds_file):
        with open(meds_file) as f: meds = json.load(f)
        for m in meds:
            if m.get("id") == d.get("med_id"):
                if "confirmations" not in m: m["confirmations"] = []
                m["confirmations"].append({"timestamp":time.strftime("%Y-%m-%dT%H:%M:%S"),"by":uid})
        with open(meds_file,"w") as f: json.dump(meds,f,ensure_ascii=False,indent=2)
    return jsonify({"ok":True})

# ── TRANSLATION API ──────────────────────────────────────────────────────────────

@app.post("/api/translate")
def api_translate():
    d = request.get_json(silent=True,force=True) or {}
    text        = d.get("text","")
    target_lang = d.get("target_lang","English")
    source_lang = d.get("source_lang","auto")
    if not text: return jsonify({"ok":True,"translated":""})
    translated = ai_translate(text, target_lang, source_lang)
    return jsonify({"ok":True,"translated":translated})

# ── VOICE TRANSCRIPTION ──────────────────────────────────────────────────────────

@app.post("/api/transcribe")
def api_transcribe():
    if not OPENAI_OK:
        return jsonify({"ok":False,"error":"OpenAI not configured"}), 400
    if "audio" not in request.files:
        return jsonify({"ok":False,"error":"No audio file"}), 400
    audio_file = request.files["audio"]
    lang = request.form.get("language","")
    try:
        kwargs = {"model":"whisper-1","file":(audio_file.filename or "audio.webm", audio_file.stream, audio_file.content_type)}
        if lang: kwargs["language"] = lang[:2].lower()
        transcript = openai_client.audio.transcriptions.create(**kwargs)
        return jsonify({"ok":True,"text":transcript.text})
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)}), 500

# ── CHAT / AI ASSISTANT ──────────────────────────────────────────────────────────

@app.post("/api/chat")
def api_chat():
    d = request.get_json(silent=True,force=True) or {}
    messages = d.get("messages",[])
    lang = d.get("language","English")
    system = f"""You are Phoenix, the compassionate AI assistant for PhoenixMinds — a platform helping children with developmental, cognitive and learning needs. You support parents, educators, therapists and healthcare professionals.

Current interface language: {lang}
Always respond in {lang}. Be warm, professional, evidence-based and never alarmist. Never provide diagnoses — always recommend qualified clinicians. For crisis situations, always provide emergency contacts first."""

    if CLAUDE_OK:
        try:
            r = claude_client.messages.create(
                model="claude-sonnet-4-6", max_tokens=1500,
                system=system,
                messages=messages
            )
            return jsonify({"ok":True,"reply":r.content[0].text})
        except Exception: pass

    if GROQ_OK:
        try:
            msgs = [{"role":"system","content":system}] + messages
            r = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile", max_tokens=1500, temperature=0.7,
                messages=msgs
            )
            return jsonify({"ok":True,"reply":r.choices[0].message.content})
        except Exception: pass

    if OPENAI_OK:
        try:
            msgs = [{"role":"system","content":system}] + messages
            r = openai_client.chat.completions.create(
                model="gpt-4o", max_tokens=1500, temperature=0.7,
                messages=msgs
            )
            return jsonify({"ok":True,"reply":r.choices[0].message.content})
        except Exception as e:
            return jsonify({"ok":False,"error":str(e)}), 500

    return jsonify({"ok":False,"error":"No AI provider available"}), 500

# ── RIASEC ───────────────────────────────────────────────────────────────────────

@app.route("/riasec")
def riasec():
    return render_template("riasec.html")

@app.post("/api/riasec/score")
def api_riasec_score():
    d = request.get_json(silent=True,force=True) or {}
    scores = d.get("scores",{})  # {R:x, I:x, A:x, S:x, E:x, C:x}
    child_name = d.get("child_name","")
    if not scores:
        return jsonify({"ok":False,"error":"No scores provided"}), 400
    sorted_codes = sorted(scores.items(), key=lambda x:-x[1])
    top3 = "".join([c for c,_ in sorted_codes[:3]])
    descriptions = {
        "R":"Realistic — Learns through hands-on doing; responds to tangible, physical and constructive activities. Prefers tools, nature, building and physical activity.",
        "I":"Investigative — Loves to explore, research and solve puzzles. Drawn to science, maths, data and discovery. May have intense focused interests (common in ASD profiles).",
        "A":"Artistic — Expressive and creative. Communicates best through art, music, drama and imagination. Highly responsive to music therapy and creative interventions.",
        "S":"Social — Warm and people-oriented. Motivated by helping, teaching and belonging. Social connections are strong intrinsic motivators for engagement.",
        "E":"Enterprising — Natural leader with strong opinions and decision-making drive. Responds well to choice-making, leadership roles and responsibility tasks.",
        "C":"Conventional — Thrives with structure, routines and predictability. Visual schedules, organised environments and step-by-step procedures are highly effective."
    }
    therapy_alignment = {
        "R":{"aba_reinforcers":["Construction sets","Tool play","Outdoor time","Sensory bins"],"ot_activities":["Heavy work","Clay","Building blocks","Mechanical toys"],"iep_themes":["STEM projects","Woodwork","Horticulture","Robotics club"]},
        "I":{"aba_reinforcers":["Science kits","Puzzles","Coding games","Fact books"],"ot_activities":["Science experiments (fine motor)","Lego","Logic puzzles"],"iep_themes":["Science club","Maths enrichment","Lego Mindstorms","Research projects"]},
        "A":{"aba_reinforcers":["Art supplies","Musical instruments","Craft materials","Drama props"],"ot_activities":["Finger painting","Sensory art","Clay sculpting","Drama therapy"],"iep_themes":["Art therapy integration","Music therapy","Drama club","Creative writing"]},
        "S":{"aba_reinforcers":["Peer play","Group games","Caring for class pet","Community activities"],"ot_activities":["Group sensory play","Cooperative games","Buddy activities"],"iep_themes":["Buddy programmes","Peer tutoring","Community projects","Social skills groups"]},
        "E":{"aba_reinforcers":["Choice boards","Leadership games","Shop play","Decision-making activities"],"ot_activities":["Responsibility tasks","Task mastery activities","Planning activities"],"iep_themes":["Class monitor","Student council (adapted)","Debate club","Enterprise projects"]},
        "C":{"aba_reinforcers":["Sorting","Organising","Schedule boards","Checklists"],"ot_activities":["Filing","Categorising","Precision craft tasks","Data recording"],"iep_themes":["Classroom helper","Library assistant","Data collection roles","Structured routines"]}
    }
    primary_code = sorted_codes[0][0] if sorted_codes else "R"
    result = {
        "top_three_code":top3,
        "primary_code":primary_code,
        "ranked_codes":sorted_codes,
        "primary_description":descriptions.get(primary_code,""),
        "therapy_alignment":therapy_alignment.get(primary_code,{}),
        "all_descriptions":{k:descriptions[k] for k,_ in sorted_codes},
        "profile_summary":f"{child_name} shows a {top3} profile, indicating primary strengths in {descriptions.get(sorted_codes[0][0],'').split('—')[0].strip()} with secondary interests in {descriptions.get(sorted_codes[1][0],'').split('—')[0].strip() if len(sorted_codes)>1 else 'various areas'}." if child_name else f"The {top3} profile indicates primary strengths in {descriptions.get(primary_code,'').split('—')[0].strip()}."
    }
    return jsonify({"ok":True,"result":result})

# ── HOME ROUTINE ─────────────────────────────────────────────────────────────────

@app.route("/routine")
@login_required
def routine():
    uid = session["user"].get("id","")
    routine_file = os.path.join(DATA_DIR, f"routine_{uid}.json")
    routine_data = []
    if os.path.exists(routine_file):
        with open(routine_file) as f: routine_data = json.load(f)
    return render_template("routine.html", routine_data=routine_data)

@app.post("/api/routine/save")
@login_required
def api_save_routine():
    uid = session["user"].get("id","")
    d = request.get_json(silent=True,force=True) or {}
    items = d.get("items",[])
    with open(os.path.join(DATA_DIR,f"routine_{uid}.json"),"w") as f:
        json.dump(items,f,ensure_ascii=False,indent=2)
    return jsonify({"ok":True})

# ── PROFILE PAGE ─────────────────────────────────────────────────────────────────

@app.route("/profile")
@login_required
def profile():
    user = find_user(session["user"]["email"])
    journeys=[]
    for fn in os.listdir(JOURNEY_DIR):
        if fn.endswith(".json"):
            try:
                with open(os.path.join(JOURNEY_DIR,fn)) as f:
                    j=json.load(f)
                    if j.get("created_by")==session["user"].get("id"): journeys.append(j)
            except: pass
    return render_template("profile.html", user=user, journeys=journeys)

@app.post("/api/profile/update")
@login_required
def api_update_profile():
    d = request.get_json(silent=True,force=True) or {}
    # Read all users, update matching one, rewrite
    users = read_users()
    uid = session["user"].get("id","")
    updated = False
    for u in users:
        if u.get("id") == uid:
            if d.get("fullname"): u["fullname"] = d["fullname"]
            if d.get("phone"):    u["phone"]    = d["phone"]
            if d.get("country"):  u["country"]  = d["country"]
            if d.get("specialization"): u["specialization"] = d["specialization"]
            updated = True
    if updated:
        fields = list(users[0].keys()) if users else ["id","fullname","email","password_hash","role","specialization","country","phone","is_admin","created_at"]
        with open(USERS_CSV,"w",newline="",encoding="utf-8") as f:
            w = csv.DictWriter(f,fieldnames=fields)
            w.writeheader()
            w.writerows(users)
        session["user"]["fullname"] = d.get("fullname",session["user"]["fullname"])
    return jsonify({"ok":updated})

# ── HEALTH CHECK ─────────────────────────────────────────────────────────────────

@app.route("/api/health")
def health():
    return jsonify({
        "status":"ok","platform":"PhoenixMinds","version":"3.0.0",
        "ai_providers":{"openai":OPENAI_OK,"claude":CLAUDE_OK,"gemini":GEMINI_OK,"groq":GROQ_OK},
        "conditions_loaded":len(CONDITIONS),"symptom_bank":len(SYMPTOM_BANK)
    })

if __name__ == "__main__":
    port = int(os.environ.get("LUMINA_PORT",5000))
    app.run(host="0.0.0.0", port=port, debug=False)
