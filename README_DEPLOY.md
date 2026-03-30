# PhoenixMinds — Complete Deployment Guide
## phoenixminds.org on Cloudflare + Mac M2 (Local Dev)

---

## STEP 1 — Install Dependencies (Mac M2)

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install all packages
pip install -r requirements.txt
```

---

## STEP 2 — Set Up Environment Variables

Create a `.env` file in your project root:

```bash
# Core AI
OPENAI_API_KEY=sk-...         # Your OpenAI key
ANTHROPIC_API_KEY=sk-ant-...  # Your Claude key
GOOGLE_API_KEY=...            # Your Google AI key
GROQ_API_KEY=gsk_...          # Your Groq key

# Translation
GOOGLE_CSE_API_KEY=AIz...     # Google Cloud Translation
DEEPL_API_KEY=...             # DeepL API (optional)
HUGGINGFACE_API_KEY=hf_...    # For NLLB-200 fallback

# Flask
FLASK_SECRET=your-super-secret-key-change-this-NOW
FLASK_ENV=production
```

Load it automatically:
```bash
# At top of app.py — already included:
# from dotenv import load_dotenv; load_dotenv()
```

---

## STEP 3 — Project Structure

```
phoenixminds/
├── app.py                      ← Main Flask backend
├── phoenix_translate.py        ← Translation engine
├── requirements.txt
├── .env                        ← API keys (never commit)
├── .gitignore
├── templates/
│   ├── base.html
│   ├── main.html
│   ├── login.html
│   ├── create_account.html
│   ├── dashboard.html
│   ├── admin.html
│   ├── evaluation.html
│   ├── evaluation_report.html
│   ├── iep.html
│   ├── journey.html
│   ├── child.html
│   ├── medications.html
│   ├── routine.html
│   ├── riasec.html
│   ├── connect.html
│   ├── services.html
│   ├── about.html
│   ├── contact.html
│   └── profile.html
├── static/
│   └── css/
│       └── style.css           ← (optional extra styles)
└── data/
    ├── users.csv               ← auto-created
    ├── evaluations/            ← auto-created
    ├── journeys/               ← auto-created
    ├── ieps/                   ← auto-created
    └── medications/            ← auto-created
```

---

## STEP 4 — Run Locally (Mac M2)

```bash
# Activate environment
source .venv/bin/activate

# Run development server
python app.py
# → http://localhost:5000

# Or with auto-reload
FLASK_ENV=development flask run --port=5000 --debug
```

**Test credentials:**
- Admin: `admin@phoenixminds.org` / `Admin@2026`
- Demo: `demo@phoenixminds.org` / `Demo@2026`

---

## STEP 5 — Deploy to phoenixminds.org (Cloudflare)

### Option A: Cloudflare Workers + Python (Recommended)

PhoenixMinds uses Flask which requires a Python WSGI server.
Cloudflare Workers does NOT support Python natively.

**Best approach: VPS + Cloudflare Proxy**

1. Get a VPS (DigitalOcean $6/mo, AWS Lightsail $5/mo, or Hetzner €3.5/mo)
2. Deploy Flask on the VPS
3. Point phoenixminds.org through Cloudflare (orange cloud = CDN + DDoS protection)

### Option B: Cloudflare Pages + Python Backend on Render (Free)

For free deployment:

**Backend on Render.com (free tier):**
```bash
# Create render.yaml in project root:
services:
  - type: web
    name: phoenixminds-api
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: gunicorn app:app --bind 0.0.0.0:$PORT
    envVars:
      - key: OPENAI_API_KEY
        sync: false
      - key: ANTHROPIC_API_KEY
        sync: false
```

**Cloudflare DNS Setup:**
1. Log in to Cloudflare Dashboard
2. Select phoenixminds.org
3. Go to DNS → Add Record
4. Type: CNAME, Name: @, Target: your-render-app.onrender.com
5. Enable orange cloud (proxied)

### Option C: Deploy on Mac M2 (Local Server, Home/Office)

```bash
# Install gunicorn
pip install gunicorn

# Run production server
gunicorn app:app --bind 0.0.0.0:5000 --workers 4

# Keep running with screen or tmux
screen -S phoenix
gunicorn app:app --bind 0.0.0.0:5000 --workers 4

# Ctrl+A, D to detach
```

Then in Cloudflare:
- Use Cloudflare Tunnel (free) to expose your Mac's localhost to the internet
```bash
# Install cloudflared
brew install cloudflared

# Create tunnel
cloudflared tunnel create phoenixminds
cloudflared tunnel route dns phoenixminds phoenixminds.org

# Run tunnel
cloudflared tunnel run phoenixminds
```

---

## STEP 6 — Cloudflare Tunnel (Easiest - Recommended for Mac)

This is the **cleanest** approach — no server needed, runs directly from your Mac M2:

```bash
# 1. Install cloudflared
brew install cloudflared

# 2. Authenticate
cloudflared tunnel login

# 3. Create tunnel
cloudflared tunnel create phoenixminds

# 4. Configure (create ~/.cloudflared/config.yml)
cat > ~/.cloudflared/config.yml << EOF
tunnel: phoenixminds
credentials-file: /Users/YOUR_USERNAME/.cloudflared/TUNNEL_ID.json

ingress:
  - hostname: phoenixminds.org
    service: http://localhost:5000
  - hostname: www.phoenixminds.org
    service: http://localhost:5000
  - service: http_status:404
EOF

# 5. Add DNS record
cloudflared tunnel route dns phoenixminds phoenixminds.org
cloudflared tunnel route dns phoenixminds www.phoenixminds.org

# 6. Start everything
# Terminal 1: Start Flask
source .venv/bin/activate && gunicorn app:app --bind 0.0.0.0:5000 --workers 2

# Terminal 2: Start tunnel
cloudflared tunnel run phoenixminds
```

phoenixminds.org is now live — zero VPS cost!

---

## STEP 7 — SSL/HTTPS

Cloudflare handles SSL automatically. No certificate needed on your server.
Set SSL/TLS mode to "Full" in Cloudflare Dashboard → SSL/TLS.

---

## STEP 8 — Add conditions.csv Database

The evaluation engine reads from `data/conditions.csv`. Format:
```
condition,category,symptoms,synonyms,red_flags,referral_to,description
"Autism Spectrum Disorder (ASD)","Neurodevelopmental","limited eye contact|delayed speech|repetitive behaviours|echolalia","ASD|autism","language regression|self-injury","Paediatric Neurologist|Child Psychologist","Neurodevelopmental condition..."
```

---

## ADMIN PANEL ACCESS

1. Login with: `admin@phoenixminds.org` / `Admin@2026`
2. You are automatically redirected to `/admin`
3. The admin panel shows: Users, Child Journeys, Evaluations, Messages, Conditions DB, Analytics

**Change admin password:**
Edit `app.py` line:
```python
add_user("Admin PhoenixMinds","admin@phoenixminds.org","YOUR_NEW_PASSWORD","Admin",...)
```
Then delete `data/users.csv` and restart — it will recreate with new password.

---

## TRANSLATION ENGINE USAGE

```python
from phoenix_translate import PhoenixTranslator

t = PhoenixTranslator()

# Basic translation
result = t.translate("Hello, how are you?", target="Urdu")
print(result.text)  # اردو میں ترجمہ
print(result.provider)  # groq / claude / openai / google / deepl

# Clinical translation (uses most accurate provider)
result = t.translate(
    "The child shows signs of sensory processing disorder.",
    target="Arabic",
    is_clinical=True
)

# Detect language
detected = t.detect_language("Merhaba, nasılsın?")
print(detected)  # {'code': 'tr', 'name': 'Turkish', 'confidence': 0.85}

# REST API (already wired into app.py)
# POST /api/translate  {"text":"...", "target_lang":"Urdu", "is_clinical":true}
# POST /api/v1/translate  (full translation engine endpoint)
```

---

## SUPPORT

Founder: Ruksh E Ibadat
Platform: phoenixminds.org
Email: contact@phoenixminds.org
