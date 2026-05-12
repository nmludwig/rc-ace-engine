# RingCentral ACE Engine

Full pipeline: RingCentral OAuth → transcript export → ACE analysis → live HTML microsite.

**Live app:** https://rc-ace-engine.onrender.com

---

## What it does

1. Admin logs in with RingCentral OAuth
2. Enters customer name, industry, and date range
3. App exports all recorded calls with RingSense transcripts
4. One click runs the ACE analysis engine (Claude Sonnet)
5. Produces a live microsite + PDF leave-behind + scorecard + keywords

---

## Files

```
├── app.py              ← Flask server — OAuth, download jobs, ACE jobs, microsite serving
├── ace_engine.py       ← ACE analysis, HTML builder, PDF, scorecard, keywords
├── requirements.txt    ← Python dependencies
├── templates/
│   ├── index.html      ← 3-step wizard UI
│   └── error.html      ← OAuth error page
├── outputs/            ← Transcript Excel/PDF exports (auto-created)
└── microsites/         ← Generated ACE microsites (auto-created, persistent disk)
```

---

## Setup (Local)

```bash
pip install -r requirements.txt

export RC_CLIENT_ID=your_client_id
export RC_CLIENT_SECRET=your_client_secret
export RC_REDIRECT_URI=http://localhost:5000/oauth/callback
export FLASK_SECRET=any_random_string
export ANTHROPIC_API_KEY=sk-ant-...

gunicorn -w 2 -k gthread --threads 4 --timeout 300 -b 0.0.0.0:5000 app:app
```

---

## Deploy on Render

1. Push this repo to GitHub
2. **Render → New Web Service** → connect repo
3. Set build command: `pip install -r requirements.txt`
4. Set start command: `gunicorn -w 2 -k gthread --threads 4 --timeout 300 -b 0.0.0.0:$PORT app:app`
5. Add a **Persistent Disk** mounted at `/opt/render/project/src/microsites` ($1/month)
6. Add a **Redis** instance (free tier) — copy the Redis URL

### Environment variables

| Variable | Description |
|---|---|
| `RC_CLIENT_ID` | RingCentral app Client ID |
| `RC_CLIENT_SECRET` | RingCentral app Client Secret |
| `RC_REDIRECT_URI` | `https://rc-ace-engine.onrender.com/oauth/callback` |
| `FLASK_SECRET` | Random string for session signing |
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `REDIS_URL` | Render Redis URL (auto-set if using Render Redis) |

---

## Scaling

- **Jobs** stored in Redis — survive server restarts
- **Microsites** stored on Render persistent disk — survive deploys
- **1,000 customers** at ~$0.50/analysis = ~$500/month API costs
- Render Standard plan ($25/month) handles concurrent load comfortably

---

## RingCentral App Setup

- **Auth type:** 3-legged OAuth — Server-side web app
- **Redirect URI:** `https://rc-ace-engine.onrender.com/oauth/callback`
- **Scopes:** Analytics, Read Accounts, Read Call Log, Read Call Recording, Read Contacts, RingSense

---

Built by Ali Tore · RingCentral AI Conversation Expert · POC Framework · 2026
