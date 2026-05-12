#!/usr/bin/env python3
"""
ACE Engine — Analysis + output builders
Called by app.py's ACE job worker.
"""

import re, json, textwrap
from datetime import datetime
from pathlib import Path

import anthropic

# ══════════════════════════════════════════════════════════════
# ANALYSIS — Claude API call
# ══════════════════════════════════════════════════════════════

ANALYSIS_PROMPT = """
You are an expert business analyst specializing in call center operations,
revenue optimization, and customer experience for B2B companies.

CUSTOMER CONTEXT:
- Company: {customer}
- Industry: {industry}
- Total calls in dataset: {call_count}
- Date range: {date_range}

TRANSCRIPT DATA:
{transcript}

Analyze the transcripts and return ONLY valid JSON — no preamble, no markdown fences.

{{
  "summary": {{
    "company": "{customer}", "industry": "{industry}",
    "total_calls": {call_count}, "date_range": "{date_range}",
    "total_talk_time_estimate": "X hrs Y min",
    "unresolved_rate_pct": 0, "repeat_contact_rate_pct": 0,
    "internal_call_time_pct": 0, "dead_end_parts_minutes": 0,
    "key_departures_or_risks": ""
  }},
  "issues": [{{
    "rank": 1, "name": "", "category": "",
    "occurrence_score": 5, "impact_score": 5,
    "urgency_score": 5, "risk_score": 5,
    "total_score": 20, "tier": "Critical",
    "summary": "", "evidence": ["", ""],
    "weekly_projection": "", "cost_of_inaction": "", "rc_ai_fix": ""
  }}],
  "emerging_issues": [{{"name": "", "summary": "", "evidence": ""}}],
  "metrics": {{
    "unresolved_calls_per_week": 0, "dead_end_parts_mins_per_week": 0,
    "repeat_contacts_per_week": 0, "routing_friction_pct": 0,
    "at_risk_accounts_count": 0, "reps_below_avg_count": 0
  }},
  "rep_performance": [{{"name": "", "estimated_resolution_pct": 80, "tier": "strong"}}],
  "customer_intent": {{
    "top_intents": [{{
      "intent": "", "description": "", "call_count": 0,
      "pct_of_total": 0, "resolution_rate": "", "example": ""
    }}],
    "intent_summary": ""
  }},
  "competitors_mentioned": [{{
    "name": "", "risk_level": "", "total_mentions": 0,
    "comparison_contexts": [{{
      "context_type": "", "description": "",
      "frequency": "", "example_quote": ""
    }}],
    "recommendations": ""
  }}],
  "pricing_and_margin": {{
    "gp_floor_violations": [{{"description": "", "evidence": "", "estimated_impact": ""}}],
    "discounts_and_specials_mentioned": [{{"type": "", "description": "",
      "frequency": "", "rep_consistency": "", "example": ""}}],
    "pricing_summary": ""
  }},
  "customer_frustrations": [{{
    "theme": "", "description": "", "frequency": "",
    "root_cause": "", "customer_sentiment": "",
    "example_quote": "", "rep_handling": "", "business_impact": ""
  }}],
  "product_feedback": [{{
    "product_category": "", "sku_or_part_number": "",
    "feedback_type": "", "description": "", "frequency": "",
    "customer_impact": "", "root_cause": "", "example_quote": ""
  }}],
  "unresolved_issues": {{
    "total_unresolved_calls": 0, "unresolved_rate_pct": 0,
    "top_themes": [{{
      "rank": 1, "theme": "", "description": "",
      "call_count": 0, "pct_of_unresolved": 0,
      "recurring_signal": "", "customer_impact": "", "root_cause": ""
    }}],
    "unresolved_summary": ""
  }},
  "at_risk_customers": {{
    "total_risk_signals_detected": 0, "total_at_risk_customers": 0,
    "risk_signal_distribution": [{{
      "topic": "", "signal_count": 0, "pct_of_total_signals": 0,
      "description": "", "example_customers": [], "retention_risk": ""
    }}],
    "risk_summary": ""
  }},
  "at_risk_accounts": [{{"account": "", "reason": "", "urgency": ""}}],
  "scorecard_questions": [{{
    "number": 1, "category": "", "question": "",
    "context": "", "scoring": ""
  }}],
  "keywords": [{{
    "number": 1, "group": "", "term": "", "rationale": ""
  }}]
}}

SCORING: occurrence 1-5, impact 1-5, urgency 1-5, risk 1-5. Total max 20.
Tiers: Critical (16-20), High (11-15), Medium (6-10).

REQUIREMENTS:
- Identify 6-9 issues grounded in actual transcript evidence
- customer_intent: at least 5 top intents ranked by call volume
- competitors_mentioned: all named competitors with all comparison contexts
- customer_frustrations: at least 4 themes with root causes
- product_feedback: at least 3 patterns
- unresolved_issues: exactly 5 ranked themes
- at_risk_customers: exactly 5 topic buckets ranked by signal count
- scorecard_questions: exactly 20 questions in 5 categories
- keywords: exactly 25 terms — no individual person names
- Rep tiers: strong (70%+), developing (50-69%), needs_coaching (<50%)
- Ground every finding in actual transcript evidence
- Weekly projections assume a 5-day work week
"""

def run_ace_analysis(transcript: str, customer: str, industry: str,
                     call_count: int, date_range: str) -> dict:
    client = anthropic.Anthropic()
    trunc  = transcript[:90000] if len(transcript) > 90000 else transcript
    prompt = ANALYSIS_PROMPT.format(
        customer=customer, industry=industry,
        call_count=call_count, date_range=date_range,
        transcript=trunc
    )
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = msg.content[0].text.strip()
    raw = re.sub(r'^```json\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    return json.loads(raw)


# ══════════════════════════════════════════════════════════════
# HTML MICROSITE BUILDER
# ══════════════════════════════════════════════════════════════

def _tc(tier):
    return {"Critical":"#E24B4A","High":"#BA7517","Medium":"#378ADD"}.get(tier,"#378ADD")
def _tb(tier):
    return {"Critical":"#FCEBEB","High":"#FAEEDA","Medium":"#E6F1FB"}.get(tier,"#E6F1FB")
def _tt(tier):
    return {"Critical":"#791F1F","High":"#633806","Medium":"#0C447C"}.get(tier,"#0C447C")
def esc(s):
    if not isinstance(s, str): s = str(s)
    return s.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('"','&quot;')


def build_html(data: dict, out_dir: Path, slug: str):
    s            = data["summary"]
    issues       = sorted(data["issues"], key=lambda x: -x["total_score"])
    metrics      = data.get("metrics", {})
    competitors  = data.get("competitors_mentioned", [])
    frustrations = data.get("customer_frustrations", [])
    intents      = (data.get("customer_intent") or {}).get("top_intents", [])
    intent_sum   = (data.get("customer_intent") or {}).get("intent_summary", "")
    product_fb   = data.get("product_feedback", [])
    unresolved   = data.get("unresolved_issues", {})
    at_risk_c    = data.get("at_risk_customers", {})
    reps         = data.get("rep_performance", [])
    critical_cnt = sum(1 for i in issues if i.get("tier") == "Critical")

    # Issue cards
    issue_html = ""
    for iss in issues:
        tier  = iss.get("tier","Medium")
        score = iss.get("total_score",0)
        pct   = score/20*100
        ev    = "".join(f"<li>{esc(e)}</li>" for e in (iss.get("evidence") or [])[:4])
        issue_html += f"""
        <div class="card issue-card">
          <div class="issue-header">
            <div class="issue-meta">
              <span class="badge" style="background:{_tb(tier)};color:{_tt(tier)}">{esc(tier)}</span>
              <span class="cat">{esc(iss.get('category',''))}</span>
            </div>
            <div class="score" style="color:{_tc(tier)}">{score}<span>/20</span></div>
          </div>
          <h3>{esc(iss.get('name',''))}</h3>
          <div class="bar-wrap"><div class="bar-track">
            <div class="bar-fill" style="background:{_tc(tier)}" data-width="{pct}"></div>
          </div></div>
          <p class="summary-text">{esc(iss.get('summary',''))}</p>
          <div class="detail-grid">
            <div><div class="dl">Evidence</div><ul class="ev-list">{ev}</ul></div>
            <div>
              <div class="dl">Weekly projection</div>
              <p class="accent-text">{esc(iss.get('weekly_projection',''))}</p>
              <div class="dl" style="margin-top:12px">RC AI fix</div>
              <p class="muted-text">{esc(iss.get('rc_ai_fix',''))}</p>
            </div>
          </div>
        </div>"""

    # Competitors
    comp_html = ""
    for comp in competitors:
        ctx = "".join(f"""<div class="ctx-chip">
          <div class="ctx-type">{esc(c.get('context_type',''))}</div>
          <div class="ctx-desc">{esc(c.get('description',''))}</div>
        </div>""" for c in (comp.get("comparison_contexts") or [])[:4])
        comp_html += f"""<div class="card comp-card">
          <div class="comp-head">
            <div class="comp-name">{esc(comp.get('name',''))}</div>
            <div class="comp-mentions">{comp.get('total_mentions','')} mentions</div>
          </div>
          <div class="ctx-grid">{ctx}</div>
          <div class="comp-rec">→ {esc(comp.get('recommendations',''))}</div>
        </div>"""

    # Frustrations
    frust_html = ""
    for fr in frustrations[:4]:
        frust_html += f"""<div class="card frust-card">
          <div class="frust-theme">{esc(fr.get('theme',''))}</div>
          <div class="frust-freq">{esc(fr.get('frequency',''))}</div>
          <div class="frust-row"><span class="fl">Root cause</span><span>{esc(fr.get('root_cause',''))}</span></div>
          <blockquote>{esc(fr.get('example_quote',''))}</blockquote>
        </div>"""

    # Intents
    max_calls  = max((i.get("call_count",0) for i in intents), default=1)
    intent_html = ""
    for it in intents[:6]:
        p = it.get("call_count",0)/max_calls*100
        intent_html += f"""<div class="intent-row">
          <div class="intent-name">{esc(it.get('intent',''))}</div>
          <div class="bar-track intent-bar-wrap">
            <div class="bar-fill intent-bar" data-width="{p}"></div>
          </div>
          <div class="intent-stats">
            <span class="intent-pct">{it.get('pct_of_total',0)}%</span>
            <span class="intent-calls">{it.get('call_count',0)} calls</span>
          </div>
          <div class="intent-res">{esc(it.get('resolution_rate',''))}</div>
        </div>"""

    # Reps
    reps_sorted = sorted(reps, key=lambda r: -r.get("estimated_resolution_pct",0))
    rep_html = ""
    for r in reps_sorted[:10]:
        pct = r.get("estimated_resolution_pct",0)
        col = "#1D9E75" if pct>=70 else "#BA7517" if pct>=50 else "#E24B4A"
        rep_html += f"""<div class="rep-row">
          <div class="rep-name">{esc(r.get('name',''))}</div>
          <div class="bar-track"><div class="bar-fill" style="background:{col}" data-width="{pct}"></div></div>
          <div class="rep-pct" style="color:{col}">{pct}%</div>
        </div>"""

    # Unresolved
    unres_html = ""
    for t in (unresolved.get("top_themes") or [])[:5]:
        unres_html += f"""<div class="unres-row">
          <div class="unres-rank">#{t.get('rank','')}</div>
          <div>
            <div class="unres-theme">{esc(t.get('theme',''))}</div>
            <div class="unres-meta">{t.get('call_count',0)} calls · {t.get('pct_of_unresolved',0)}% of unresolved</div>
            <div class="unres-cause">{esc(t.get('root_cause',''))}</div>
          </div>
        </div>"""

    # Risk
    dist     = (at_risk_c.get("risk_signal_distribution") or [])[:5]
    max_sig  = max((d.get("signal_count",0) for d in dist), default=1)
    risk_html = ""
    for d in dist:
        p   = d.get("signal_count",0)/max_sig*100
        lvl = d.get("retention_risk","Medium")
        rc  = _tc(lvl)
        risk_html += f"""<div class="risk-row">
          <div class="risk-topic">{esc(d.get('topic',''))}</div>
          <div class="bar-track"><div class="bar-fill" style="background:{rc}" data-width="{p}"></div></div>
          <div class="risk-right">
            <span class="risk-count" style="color:{rc}">{d.get('signal_count',0)}</span>
            <span class="badge" style="background:{_tb(lvl)};color:{_tt(lvl)}">{esc(lvl)}</span>
          </div>
        </div>"""

    # Products
    prod_html = ""
    for pf in product_fb[:6]:
        ft = pf.get("feedback_type","")
        bg = "#FCEBEB" if "complaint" in ft.lower() else "#E1F5EE" if "positive" in ft.lower() else "#F7F7F5"
        prod_html += f"""<div class="prod-card" style="background:{bg}">
          <div class="prod-cat">{esc(pf.get('product_category',''))}</div>
          <div class="prod-type">{esc(ft)}</div>
          <div class="prod-desc">{esc(pf.get('description',''))}</div>
          <div class="prod-freq">{esc(pf.get('frequency',''))}</div>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RingCentral ACE — {esc(s['company'])}</title>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{
  --orange:#FF6A00;--dark:#1A1A1A;--mid:#4A4A4A;--light:#888;
  --rule:#E8E8E8;--bg:#F7F7F5;--white:#fff;
  --critical:#E24B4A;--high:#BA7517;--blue:#185FA5;--green:#1D9E75;
  --r:8px;--sh:0 2px 12px rgba(0,0,0,.07);--shl:0 8px 32px rgba(0,0,0,.10)
}}
html{{scroll-behavior:smooth}}
body{{font-family:-apple-system,'Helvetica Neue',Arial,sans-serif;background:var(--bg);color:var(--dark);line-height:1.5}}
a{{color:inherit;text-decoration:none}}

/* NAV */
.nav{{position:sticky;top:0;z-index:100;background:var(--dark);border-bottom:2px solid var(--orange);display:flex;align-items:center;justify-content:space-between;padding:0 32px;height:52px}}
.nav-brand{{display:flex;align-items:center;gap:6px}}
.nav-rc{{color:var(--orange);font-weight:700;font-size:14px}}
.nav-prod{{color:#fff;font-size:14px}}
.nav-links{{display:flex;gap:4px}}
.nav-links a{{color:#aaa;font-size:12px;padding:6px 10px;border-radius:4px;transition:.15s}}
.nav-links a:hover{{color:#fff;background:rgba(255,255,255,.08)}}
.nav-conf{{color:#555;font-size:11px}}

/* HERO */
.hero{{background:linear-gradient(135deg,#FF7A35 0%,#FFB347 40%,#D4A5C9 75%,#A8C8E8 100%);padding:72px 32px 64px;position:relative;overflow:hidden}}
.hero::after{{content:'';position:absolute;inset:0;background:linear-gradient(to bottom,rgba(0,0,0,.18),rgba(0,0,0,.05))}}
.hero-in{{position:relative;z-index:1;max-width:1100px;margin:0 auto}}
.eyebrow{{display:inline-block;background:rgba(255,255,255,.22);color:#fff;font-size:11px;font-weight:600;letter-spacing:.1em;padding:4px 12px;border-radius:20px;margin-bottom:20px;text-transform:uppercase}}
.hero h1{{font-family:Georgia,serif;font-size:clamp(36px,5vw,58px);font-weight:700;color:#fff;line-height:1.1;text-shadow:0 2px 16px rgba(0,0,0,.25);margin-bottom:16px}}
.hero-sub{{font-size:16px;color:rgba(255,255,255,.88);max-width:560px;margin-bottom:40px;line-height:1.6}}
.kpi-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:32px}}
.kpi{{background:rgba(255,255,255,.92);border-radius:var(--r);padding:20px 16px 16px;backdrop-filter:blur(8px);box-shadow:var(--shl);transition:.2s}}
.kpi:hover{{transform:translateY(-2px)}}
.kpi-val{{font-size:36px;font-weight:700;line-height:1;margin-bottom:4px;letter-spacing:-.03em}}
.kpi-val.red{{color:var(--critical)}}.kpi-val.amb{{color:var(--high)}}.kpi-val.dark{{color:var(--dark)}}
.kpi-lbl{{font-size:11px;color:var(--light);text-transform:uppercase;letter-spacing:.06em;font-weight:500}}
.kpi-sub{{font-size:11px;color:var(--mid);margin-top:4px}}
.cta{{display:inline-flex;align-items:center;gap:8px;background:var(--dark);color:#fff;padding:12px 24px;border-radius:6px;font-size:14px;font-weight:600;transition:.15s}}
.cta:hover{{background:#333;transform:translateY(-1px)}}
.cta::after{{content:'↓';font-size:16px}}

/* LAYOUT */
.main{{max-width:1100px;margin:0 auto;padding:0 32px 80px}}
.section{{margin-top:64px}}
.sec-head{{display:flex;align-items:center;gap:12px;margin-bottom:24px;padding-bottom:14px;border-bottom:1px solid var(--rule)}}
.sec-bar{{width:4px;height:22px;background:var(--orange);border-radius:2px;flex-shrink:0}}
.sec-title{{font-size:20px;font-weight:700;letter-spacing:-.02em}}
.sec-sub{{font-size:13px;color:var(--light);margin-left:auto}}

/* CARDS */
.card{{background:var(--white);border-radius:var(--r);border:1px solid var(--rule);box-shadow:var(--sh);transition:.2s}}
.card:hover{{box-shadow:var(--shl)}}
.issue-card{{padding:24px}}
.issue-header{{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}}
.issue-meta{{display:flex;align-items:center;gap:8px}}
.badge{{font-size:11px;font-weight:700;padding:3px 10px;border-radius:20px;letter-spacing:.04em}}
.cat{{font-size:12px;color:var(--light)}}
.score{{font-size:28px;font-weight:700;letter-spacing:-.03em}}
.score span{{font-size:14px;color:var(--light);font-weight:400}}
.issue-card h3{{font-size:18px;font-weight:700;margin-bottom:10px}}
.bar-wrap{{margin-bottom:14px}}
.bar-track{{height:6px;background:var(--rule);border-radius:3px;overflow:hidden}}
.bar-fill{{height:100%;border-radius:3px;width:0;transition:width 1s cubic-bezier(.4,0,.2,1) .2s}}
.summary-text{{font-size:14px;color:var(--mid);line-height:1.6;margin-bottom:16px}}
.detail-grid{{display:grid;grid-template-columns:1fr 1fr;gap:20px;padding-top:16px;border-top:1px solid var(--rule)}}
.dl{{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--light);margin-bottom:8px}}
.ev-list{{padding-left:16px;font-size:13px;color:var(--mid);line-height:1.7}}
.ev-list li{{margin-bottom:4px}}
.accent-text{{font-size:13px;color:var(--critical);font-weight:600;line-height:1.6}}
.muted-text{{font-size:13px;color:var(--mid);line-height:1.6}}

/* GRIDS */
.two-col{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}
.three-col{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}}
@media(max-width:720px){{.two-col,.three-col{{grid-template-columns:1fr}}}}

/* COMPETITORS */
.comp-card{{overflow:hidden}}
.comp-head{{background:#E6F1FB;padding:14px 18px;display:flex;align-items:center;justify-content:space-between}}
.comp-name{{font-size:16px;font-weight:700;color:#0C447C}}
.comp-mentions{{font-size:12px;color:var(--blue);font-weight:600}}
.ctx-grid{{padding:14px 18px;display:flex;flex-direction:column;gap:10px}}
.ctx-chip{{background:var(--bg);border-radius:5px;padding:10px 12px;border-left:3px solid var(--orange)}}
.ctx-type{{font-size:12px;font-weight:700;margin-bottom:3px}}
.ctx-desc{{font-size:12px;color:var(--mid);line-height:1.5}}
.comp-rec{{margin:0 18px 14px;padding:10px 12px;background:#FFF8F0;border-radius:5px;font-size:12px;color:#854F0B;line-height:1.5}}

/* FRUSTRATIONS */
.frust-card{{padding:20px}}
.frust-theme{{font-size:15px;font-weight:700;margin-bottom:4px}}
.frust-freq{{font-size:12px;color:var(--high);font-weight:600;margin-bottom:12px}}
.frust-row{{display:flex;gap:8px;margin-bottom:6px;font-size:13px}}
.fl{{font-weight:600;color:var(--light);min-width:90px;font-size:12px}}
.frust-card blockquote{{margin-top:12px;padding:10px 14px;border-left:3px solid var(--rule);background:var(--bg);font-size:12px;color:var(--mid);font-style:italic;line-height:1.6;border-radius:0 4px 4px 0}}

/* INTENTS */
.intent-list{{display:flex;flex-direction:column;gap:14px}}
.intent-row{{background:var(--white);border-radius:var(--r);border:1px solid var(--rule);padding:16px 20px;display:grid;grid-template-columns:220px 1fr 120px 200px;align-items:center;gap:16px;box-shadow:var(--sh)}}
@media(max-width:900px){{.intent-row{{grid-template-columns:1fr}}}}
.intent-name{{font-size:14px;font-weight:600}}
.intent-bar-wrap{{height:8px}}
.intent-bar{{background:var(--orange)}}
.intent-stats{{display:flex;flex-direction:column;align-items:flex-end}}
.intent-pct{{font-size:18px;font-weight:700;line-height:1}}
.intent-calls{{font-size:11px;color:var(--light)}}
.intent-res{{font-size:12px;color:var(--mid)}}

/* REPS */
.rep-list{{display:flex;flex-direction:column;gap:10px}}
.rep-row{{display:grid;grid-template-columns:160px 1fr 52px;align-items:center;gap:12px}}
.rep-name{{font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.rep-pct{{font-size:13px;font-weight:700;text-align:right}}

/* UNRESOLVED */
.unres-list{{display:flex;flex-direction:column;gap:12px}}
.unres-row{{background:#FFF0E8;border-radius:var(--r);border:1px solid #FFD0A8;padding:16px 20px;display:flex;gap:16px;align-items:flex-start}}
.unres-rank{{width:32px;height:32px;background:var(--critical);color:#fff;border-radius:6px;font-weight:700;font-size:14px;display:flex;align-items:center;justify-content:center;flex-shrink:0}}
.unres-theme{{font-size:14px;font-weight:700;margin-bottom:3px}}
.unres-meta{{font-size:12px;color:var(--critical);font-weight:600;margin-bottom:4px}}
.unres-cause{{font-size:12px;color:var(--mid)}}

/* RISK */
.risk-headline{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:24px}}
.risk-stat{{background:#FCEBEB;border-radius:var(--r);padding:20px 24px;text-align:center}}
.risk-val{{font-size:48px;font-weight:700;color:var(--critical);line-height:1;margin-bottom:4px}}
.risk-lbl{{font-size:12px;color:#791F1F;font-weight:600;text-transform:uppercase;letter-spacing:.06em}}
.risk-list{{display:flex;flex-direction:column;gap:14px}}
.risk-row{{display:grid;grid-template-columns:220px 1fr 140px;align-items:center;gap:12px}}
@media(max-width:720px){{.risk-row{{grid-template-columns:1fr}}}}
.risk-topic{{font-size:13px;font-weight:500}}
.risk-right{{display:flex;align-items:center;gap:8px;justify-content:flex-end}}
.risk-count{{font-size:15px;font-weight:700}}

/* PRODUCTS */
.prod-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}}
.prod-card{{border-radius:var(--r);padding:16px;border:1px solid var(--rule);box-shadow:var(--sh)}}
.prod-cat{{font-size:14px;font-weight:700;margin-bottom:4px}}
.prod-type{{font-size:11px;font-weight:600;color:var(--light);text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px}}
.prod-desc{{font-size:13px;color:var(--mid);line-height:1.5;margin-bottom:6px}}
.prod-freq{{font-size:12px;color:var(--light)}}

/* SOLUTION STRIP */
.solution{{background:var(--dark);border-radius:var(--r);padding:32px;margin-top:64px}}
.solution h2{{font-size:18px;font-weight:700;color:#fff;margin-bottom:6px}}
.solution-sub{{font-size:14px;color:#888;margin-bottom:28px}}
.caps{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px}}
.cap{{background:rgba(255,255,255,.06);border-radius:6px;padding:16px;border:1px solid rgba(255,255,255,.08)}}
.cap-num{{font-size:22px;font-weight:700;color:var(--orange);margin-bottom:8px}}
.cap-title{{font-size:13px;font-weight:700;color:#fff;margin-bottom:6px}}
.cap-body{{font-size:12px;color:#888;line-height:1.6}}

/* DOWNLOAD BAR */
.dl-bar{{background:var(--white);border:1px solid var(--rule);border-radius:var(--r);padding:20px 24px;margin-top:32px;display:flex;align-items:center;gap:16px;box-shadow:var(--sh)}}
.dl-bar-label{{font-size:13px;font-weight:600;color:var(--dark);margin-right:auto}}
.dl-btn{{display:inline-flex;align-items:center;gap:6px;padding:8px 16px;border-radius:5px;font-size:12px;font-weight:600;background:var(--bg);border:1px solid var(--rule);color:var(--dark);transition:.15s}}
.dl-btn:hover{{background:var(--orange);color:#fff;border-color:var(--orange)}}

/* FOOTER */
.footer{{margin-top:64px;padding:32px;border-top:1px solid var(--rule);display:flex;justify-content:space-between;align-items:center;font-size:12px;color:var(--light)}}
.footer-rc{{color:var(--orange);font-weight:700}}
.panel{{background:var(--white);border-radius:var(--r);border:1px solid var(--rule);padding:24px;box-shadow:var(--sh)}}
</style>
</head>
<body>

<nav class="nav">
  <div class="nav-brand">
    <span class="nav-rc">RingCentral</span>
    <span class="nav-prod">AI Conversation Expert</span>
  </div>
  <div class="nav-links">
    <a href="#issues">Issues</a>
    <a href="#intent">Intent</a>
    <a href="#competitors">Competitors</a>
    <a href="#performance">Reps</a>
    <a href="#unresolved">Unresolved</a>
    <a href="#risk">Risk</a>
  </div>
  <span class="nav-conf">CONFIDENTIAL · POC</span>
</nav>

<section class="hero">
  <div class="hero-in">
    <div class="eyebrow">ACE Analysis · {esc(s.get('industry',''))}</div>
    <h1>What your calls<br>are telling you</h1>
    <p class="hero-sub">{esc(s['total_calls'])} calls analyzed · {esc(s['date_range'])} · {esc(s['total_talk_time_estimate'])} total · {esc(s['company'])}</p>
    <div class="kpi-grid">
      <div class="kpi"><div class="kpi-val red">~{s['unresolved_rate_pct']}%</div><div class="kpi-lbl">Unresolved rate</div><div class="kpi-sub">~{metrics.get('unresolved_calls_per_week',0)} calls/week</div></div>
      <div class="kpi"><div class="kpi-val amb">~{s['repeat_contact_rate_pct']}%</div><div class="kpi-lbl">Repeat contact rate</div><div class="kpi-sub">~{metrics.get('repeat_contacts_per_week',0)} contacts/week</div></div>
      <div class="kpi"><div class="kpi-val amb">~{s['internal_call_time_pct']}%</div><div class="kpi-lbl">Internal call time</div><div class="kpi-sub">Not serving customers</div></div>
      <div class="kpi"><div class="kpi-val red">{critical_cnt}</div><div class="kpi-lbl">Critical issues</div><div class="kpi-sub">Requiring immediate action</div></div>
      <div class="kpi"><div class="kpi-val dark">{s['total_calls']}</div><div class="kpi-lbl">Calls analyzed</div><div class="kpi-sub">{esc(s['date_range'])}</div></div>
      <div class="kpi"><div class="kpi-val red">{at_risk_c.get('total_at_risk_customers',0)}</div><div class="kpi-lbl">At-risk customers</div><div class="kpi-sub">{at_risk_c.get('total_risk_signals_detected',0)} risk signals</div></div>
    </div>
    <a href="#issues" class="cta">See the full analysis</a>
  </div>
</section>

<main class="main">

<div class="dl-bar">
  <span class="dl-bar-label">Download outputs for {esc(s['company'])}</span>
  <a href="download/pdf" class="dl-btn">📄 Leave-behind PDF</a>
  <a href="download/scorecard" class="dl-btn">✅ Scorecard</a>
  <a href="download/keywords" class="dl-btn">🔍 Keywords</a>
</div>

<section class="section" id="issues">
  <div class="sec-head"><div class="sec-bar"></div><h2 class="sec-title">Priority issues — scored &amp; ranked</h2><span class="sec-sub">Occurrence · Impact · Urgency · Risk · Max 20 pts</span></div>
  <div style="display:flex;flex-direction:column;gap:16px">{issue_html}</div>
</section>

<section class="section" id="intent">
  <div class="sec-head"><div class="sec-bar"></div><h2 class="sec-title">Why customers are calling</h2><span class="sec-sub">Intent analysis by call volume</span></div>
  <div class="intent-list">{intent_html}</div>
  {"<p style='font-size:13px;color:var(--mid);margin-top:16px;line-height:1.6'>" + esc(intent_sum) + "</p>" if intent_sum else ""}
</section>

<section class="section" id="competitors">
  <div class="sec-head"><div class="sec-bar"></div><h2 class="sec-title">Competitor intelligence</h2><span class="sec-sub">Surfaced from call transcripts</span></div>
  <div class="three-col">{comp_html}</div>
</section>

<section class="section" id="frustrations">
  <div class="sec-head"><div class="sec-bar"></div><h2 class="sec-title">Top customer frustrations</h2><span class="sec-sub">Recurring themes with root causes</span></div>
  <div class="two-col">{frust_html}</div>
</section>

<section class="section" id="performance">
  <div class="sec-head"><div class="sec-bar"></div><h2 class="sec-title">Rep resolution performance</h2><span class="sec-sub">Estimated from transcript data</span></div>
  <div class="two-col">
    <div class="panel"><div class="rep-list">{rep_html}</div></div>
    <div class="panel">
      <div class="dl" style="margin-bottom:16px">Product feedback</div>
      <div class="prod-grid">{prod_html}</div>
    </div>
  </div>
</section>

<section class="section" id="unresolved">
  <div class="sec-head"><div class="sec-bar"></div><h2 class="sec-title">What isn't getting resolved</h2><span class="sec-sub">{unresolved.get('total_unresolved_calls',0)} unresolved · {unresolved.get('unresolved_rate_pct',0)}% unresolved rate</span></div>
  <div class="unres-list">{unres_html}</div>
  {"<p style='font-size:13px;color:var(--mid);margin-top:16px;line-height:1.6'>" + esc(unresolved.get('unresolved_summary','')) + "</p>" if unresolved.get('unresolved_summary') else ""}
</section>

<section class="section" id="risk">
  <div class="sec-head"><div class="sec-bar"></div><h2 class="sec-title">Customer retention risk signals</h2><span class="sec-sub">Distribution across top risk topics</span></div>
  <div class="risk-headline">
    <div class="risk-stat"><div class="risk-val">{at_risk_c.get('total_risk_signals_detected',0)}</div><div class="risk-lbl">Risk signals detected</div></div>
    <div class="risk-stat"><div class="risk-val">{at_risk_c.get('total_at_risk_customers',0)}</div><div class="risk-lbl">At-risk customers</div></div>
  </div>
  <div class="risk-list">{risk_html}</div>
  {"<p style='font-size:13px;color:var(--mid);margin-top:16px;line-height:1.6'>" + esc(at_risk_c.get('risk_summary','')) + "</p>" if at_risk_c.get('risk_summary') else ""}
</section>

<div class="solution">
  <h2>What RC AI Conversation Expert delivers</h2>
  <div class="solution-sub">Every issue found. Every pattern tracked. Starting day one.</div>
  <div class="caps">
    <div class="cap"><div class="cap-num">01</div><div class="cap-title">Unresolved issue tracking</div><div class="cap-body">Every callback promise auto-flagged. Ticket created. Alert if not resolved within SLA.</div></div>
    <div class="cap"><div class="cap-num">02</div><div class="cap-title">Customer retention signals</div><div class="cap-body">At-risk count, risk signal totals, and topic distribution surfaced automatically.</div></div>
    <div class="cap"><div class="cap-num">03</div><div class="cap-title">Competitor intelligence</div><div class="cap-body">Every competitor mention categorized by comparison context weekly.</div></div>
    <div class="cap"><div class="cap-num">04</div><div class="cap-title">Frustration &amp; product signals</div><div class="cap-body">Recurring objections and SKU patterns surfaced before they compound.</div></div>
    <div class="cap"><div class="cap-num">05</div><div class="cap-title">Rep coaching &amp; margin health</div><div class="cap-body">Resolution rates, GP violations, and pricing discipline tracked per rep.</div></div>
  </div>
</div>

</main>

<footer class="footer">
  <div><span class="footer-rc">RingCentral</span> AI Conversation Expert · Proof of Concept · Confidential</div>
  <span>Analysis based on {s['total_calls']} calls · {esc(s['date_range'])} · Built by Ali Tore</span>
</footer>

<script>
const obs = new IntersectionObserver(entries => {{
  entries.forEach(e => {{
    if (!e.isIntersecting) return;
    e.target.querySelectorAll('[data-width]').forEach(b => b.style.width = b.dataset.width + '%');
    obs.unobserve(e.target);
  }});
}}, {{threshold: 0.15}});
document.querySelectorAll('.card,.intent-row,.rep-row,.risk-row,.intent-list,.rep-list,.risk-list')
  .forEach(el => obs.observe(el));
window.addEventListener('load', () => {{
  document.querySelectorAll('[data-width]').forEach(b => {{
    if (b.getBoundingClientRect().top < window.innerHeight)
      setTimeout(() => b.style.width = b.dataset.width + '%', 100);
  }});
}});
</script>
</body>
</html>"""

    html_path = out_dir / "index.html"
    html_path.write_text(html, encoding="utf-8")
    return str(html_path)


# ══════════════════════════════════════════════════════════════
# LEAVE-BEHIND PDF BUILDER
# ══════════════════════════════════════════════════════════════

def build_leave_behind_pdf(data: dict, out_path: str):
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.pdfgen import canvas
    from reportlab.lib.colors import HexColor, white

    W, H = letter
    M  = 0.42 * inch
    CW = W - 2 * M

    RC_ORANGE   = HexColor('#FF6A00')
    DARK        = HexColor('#1A1A1A')
    MID         = HexColor('#4A4A4A')
    LIGHT       = HexColor('#7A7A7A')
    RULE        = HexColor('#E8E8E8')
    BG_LIGHT    = HexColor('#F7F7F5')
    CRITICAL    = HexColor('#E24B4A')
    HIGH_COL    = HexColor('#BA7517')
    HIGH_BG     = HexColor('#FAEEDA')
    CRIT_BG     = HexColor('#FCEBEB')
    CRIT_TEXT   = HexColor('#791F1F')
    HIGH_TEXT   = HexColor('#633806')
    BLUE_BG     = HexColor('#E6F1FB')
    BLUE_TEXT   = HexColor('#185FA5')
    WHITE       = white

    s           = data["summary"]
    issues      = sorted(data["issues"], key=lambda x: -x["total_score"])[:5]
    metrics     = data.get("metrics", {})
    reps        = data.get("rep_performance", [])
    competitors = data.get("competitors_mentioned", [])
    at_risk     = data.get("at_risk_accounts", [])
    frustrations= data.get("customer_frustrations", [])
    unresolved  = data.get("unresolved_issues", {})
    at_risk_c   = data.get("at_risk_customers", {})

    def pill(c, x, y, w, h, bg, fg, label, radius=3):
        c.setFillColor(bg); c.roundRect(x, y, w, h, radius, fill=1, stroke=0)
        c.setFillColor(fg); c.setFont('Helvetica-Bold', 6.5)
        c.drawCentredString(x + w/2, y + h/2 - 2.5, label)

    def hbar(c, x, y, w, h, val, maxval, fill_color, bg_color=None):
        if bg_color is None: bg_color = RULE
        c.setFillColor(bg_color); c.roundRect(x, y, w, h, 2, fill=1, stroke=0)
        c.setFillColor(fill_color)
        c.roundRect(x, y, max(3, (val/maxval)*w), h, 2, fill=1, stroke=0)

    def sec_hdr(c, x, y, w, label, ann=''):
        c.setFillColor(DARK); c.setFont('Helvetica-Bold', 7)
        c.drawString(x, y, label.upper())
        lw = c.stringWidth(label.upper(), 'Helvetica-Bold', 7)
        if ann:
            c.setFillColor(LIGHT); c.setFont('Helvetica', 6.5)
            c.drawRightString(x+w, y, ann)
        c.setStrokeColor(RULE); c.setLineWidth(0.5)
        aw = c.stringWidth(ann, 'Helvetica', 6.5) + 5 if ann else 0
        c.line(x+lw+6, y+2.5, x+w-aw, y+2.5)

    cv = canvas.Canvas(out_path, pagesize=letter)

    # Header
    cv.setFillColor(DARK); cv.rect(0, H-0.62*inch, W, 0.62*inch, fill=1, stroke=0)
    cv.setFillColor(RC_ORANGE); cv.setFont('Helvetica-Bold', 13)
    cv.drawString(M, H-0.38*inch, 'RingCentral')
    rw = cv.stringWidth('RingCentral','Helvetica-Bold',13)
    cv.setFillColor(WHITE); cv.setFont('Helvetica', 13)
    cv.drawString(M+rw+5, H-0.38*inch, 'AI Conversation Expert')
    cv.setFillColor(HexColor('#AAAAAA')); cv.setFont('Helvetica', 7.5)
    cv.drawRightString(W-M, H-0.38*inch, f'CONFIDENTIAL · POC · {s["company"].upper()}')

    ty = H - 0.62*inch - 0.22*inch
    cv.setFillColor(DARK); cv.setFont('Helvetica-Bold', 16)
    cv.drawString(M, ty, 'What your calls are telling you')
    cv.setFillColor(LIGHT); cv.setFont('Helvetica', 7.5)
    cv.drawString(M, ty-13,
        f'{s["total_calls"]} calls · {s["date_range"]} · {s["total_talk_time_estimate"]} · '
        f'{s.get("industry","")} · {s["company"]}'[:120])

    # KPI pills
    my = ty - 13 - 22
    kpis = [
        (str(s["total_calls"]),                   'calls analyzed'),
        (s["total_talk_time_estimate"],            'total talk time'),
        (f'~{s["unresolved_rate_pct"]}%',         'unresolved rate'),
        (f'~{s["internal_call_time_pct"]}%',      'internal call time'),
        (f'~{s["repeat_contact_rate_pct"]}%',     'repeat contact rate'),
        (str(len(at_risk)) if at_risk else '—',   'at-risk accounts'),
    ]
    pw = (CW - 5*6)/6; ph = 28
    for i, (val, lbl) in enumerate(kpis):
        px = M + i*(pw+6)
        cv.setFillColor(BG_LIGHT); cv.roundRect(px, my-ph, pw, ph, 4, fill=1, stroke=0)
        cv.setFillColor(DARK); cv.setFont('Helvetica-Bold', 10)
        cv.drawCentredString(px+pw/2, my-14, val)
        cv.setFillColor(LIGHT); cv.setFont('Helvetica', 5.5)
        cv.drawCentredString(px+pw/2, my-23, lbl.upper())

    div_y = my - ph - 10
    cv.setStrokeColor(RULE); cv.setLineWidth(0.5); cv.line(M, div_y, W-M, div_y)

    col1_x = M; col1_w = CW*0.54
    col2_x = M + col1_w + 14; col2_w = CW - col1_w - 14
    cy = div_y - 14
    sec_hdr(cv, col1_x, cy, col1_w, f'Top {len(issues)} priority issues — scored', s.get("date_range",""))

    iy = cy - 14
    bar_max_w = col1_w - 96
    for iss in issues:
        row_h = 27; tier = iss["tier"]
        bar_color = CRITICAL if tier=="Critical" else HIGH_COL if tier=="High" else HexColor('#378ADD')
        cv.setFillColor(BG_LIGHT)
        cv.roundRect(col1_x, iy-row_h+2, col1_w, row_h, 3, fill=1, stroke=0)
        hbar(cv, col1_x+6, iy-row_h+9, bar_max_w, 7, iss["total_score"], 20, bar_color, RULE)
        cv.setFillColor(bar_color); cv.setFont('Helvetica-Bold', 8)
        cv.drawString(col1_x+6+bar_max_w+4, iy-row_h+9, f'{iss["total_score"]}/20')
        tier_bg = CRITICAL if tier=="Critical" else HIGH_COL
        tier_fg = WHITE if tier=="Critical" else HIGH_TEXT
        pill(cv, col1_x+col1_w-38, iy-row_h+9, 36, 10, tier_bg, tier_fg, tier)
        cv.setFillColor(DARK); cv.setFont('Helvetica-Bold', 7.5)
        cv.drawString(col1_x+6, iy-8, iss["name"][:60])
        cv.setFillColor(LIGHT); cv.setFont('Helvetica', 6.5)
        cv.drawString(col1_x+6, iy-17, iss["category"])
        iy -= row_h + 4

    if reps:
        rp_y = iy - 14
        sec_hdr(cv, col1_x, rp_y, col1_w, 'Rep resolution rate — estimate')
        rep_bar_w = col1_w - 90; rry = rp_y - 12
        for r in reps[:8]:
            pct = r["estimated_resolution_pct"]
            col = HexColor('#1D9E75') if pct>=70 else HIGH_COL if pct>=50 else CRITICAL
            cv.setFillColor(MID); cv.setFont('Helvetica', 6.5)
            cv.drawString(col1_x, rry, r["name"][:22])
            hbar(cv, col1_x+78, rry-1, rep_bar_w, 6, pct, 100, col, RULE)
            cv.setFillColor(col); cv.setFont('Helvetica-Bold', 6.5)
            cv.drawString(col1_x+78+rep_bar_w+4, rry, f'{pct}%')
            rry -= 10

    # Right column
    ry2 = div_y - 14
    sec_hdr(cv, col2_x, ry2, col2_w, 'Quantitative findings', s["total_talk_time_estimate"])
    op_metrics = [
        (f'~{s["unresolved_rate_pct"]}%', 'Unresolved call rate',
         f'~{metrics.get("unresolved_calls_per_week",0)} calls/week',
         CRITICAL if s["unresolved_rate_pct"]>40 else HIGH_COL,
         CRIT_BG  if s["unresolved_rate_pct"]>40 else HIGH_BG,
         CRIT_TEXT if s["unresolved_rate_pct"]>40 else HIGH_TEXT,
         'Critical' if s["unresolved_rate_pct"]>40 else 'High'),
        (f'~{s["internal_call_time_pct"]}%', 'Internal vs customer-facing',
         'Not serving customers', HIGH_COL, HIGH_BG, HIGH_TEXT, 'High'),
        (f'~{s["repeat_contact_rate_pct"]}%', 'Repeat contact rate',
         f'~{metrics.get("repeat_contacts_per_week",0)} repeat contacts/week',
         HIGH_COL, HIGH_BG, HIGH_TEXT, 'High'),
        (f'{metrics.get("at_risk_accounts_count",0)}+', 'At-risk accounts',
         'Relationship-dependent revenue at risk',
         CRITICAL if metrics.get("at_risk_accounts_count",0)>0 else HIGH_COL,
         CRIT_BG  if metrics.get("at_risk_accounts_count",0)>0 else HIGH_BG,
         CRIT_TEXT if metrics.get("at_risk_accounts_count",0)>0 else HIGH_TEXT,
         'Critical' if metrics.get("at_risk_accounts_count",0)>0 else 'Monitor'),
    ]
    omy = ry2 - 14
    for val, label, proj, bc, pbg, pfg, tier in op_metrics:
        row_h = 29
        cv.setFillColor(BG_LIGHT)
        cv.roundRect(col2_x, omy-row_h+2, col2_w, row_h, 3, fill=1, stroke=0)
        cv.setFillColor(bc); cv.setFont('Helvetica-Bold', 14)
        cv.drawString(col2_x+7, omy-13, val)
        vw = cv.stringWidth(val, 'Helvetica-Bold', 14)
        cv.setFillColor(DARK); cv.setFont('Helvetica-Bold', 7)
        cv.drawString(col2_x+7+vw+7, omy-7, label)
        cv.setFillColor(LIGHT); cv.setFont('Helvetica', 6.5)
        cv.drawString(col2_x+7+vw+7, omy-16, proj[:45])
        tbg = CRITICAL if tier=='Critical' else HIGH_COL if tier=='High' else HexColor('#378ADD')
        tfg = WHITE if tier=='Critical' else HIGH_TEXT
        pill(cv, col2_x+col2_w-38, omy-16, 36, 10, tbg, tfg, tier)
        omy -= row_h + 4

    if competitors:
        ci_y = omy - 10
        sec_hdr(cv, col2_x, ci_y, col2_w, 'Competitor intelligence surfaced')
        ccy = ci_y - 13
        for comp in competitors[:3]:
            contexts  = comp.get("comparison_contexts", [])
            ctx_str   = ", ".join(c.get("context_type","") for c in contexts[:3])
            row_h     = 26
            cv.setFillColor(BLUE_BG)
            cv.roundRect(col2_x, ccy-row_h+4, col2_w, row_h, 3, fill=1, stroke=0)
            cv.setFillColor(BLUE_TEXT); cv.setFont('Helvetica-Bold', 7)
            cv.drawString(col2_x+6, ccy-row_h+row_h-6,
                f'{comp["name"][:20]}' + (f' ({comp.get("total_mentions","")} mentions)'
                                          if comp.get("total_mentions") else ''))
            cv.setFillColor(LIGHT); cv.setFont('Helvetica', 6)
            cv.drawString(col2_x+6, ccy-row_h+7, ctx_str[:65])
            ccy -= row_h + 4
        omy = ccy - 4

    if frustrations:
        fr_y = omy - 10
        sec_hdr(cv, col2_x, fr_y, col2_w, 'Top customer frustrations')
        fry = fr_y - 13
        for fr in frustrations[:3]:
            cv.setFillColor(HexColor('#FFF3CD'))
            cv.roundRect(col2_x, fry-16, col2_w, 18, 3, fill=1, stroke=0)
            cv.setFillColor(HexColor('#664D00')); cv.setFont('Helvetica-Bold', 7)
            cv.drawString(col2_x+6, fry-5, fr.get("theme","")[:35])
            cv.setFillColor(LIGHT); cv.setFont('Helvetica', 6)
            cv.drawString(col2_x+6, fry-12, fr.get("root_cause","")[:65])
            fry -= 22

    # Bottom strip
    strip_h = 38; strip_y = 0.48*inch
    cv.setFillColor(DARK); cv.rect(0, strip_y, W, strip_h, fill=1, stroke=0)
    cv.setFillColor(RC_ORANGE); cv.setFont('Helvetica-Bold', 8.5)
    cv.drawString(M, strip_y+25, 'What RingCentral AI Conversation Expert delivers:')
    solutions = ['Auto-flag every unresolved call','Capture knowledge before walkout',
                 'Surface compliance risks instantly','Track competitor & pricing signals',
                 'Rep coaching from real call data']
    sx = M; sw = CW/len(solutions)
    for sol in solutions:
        cv.setFillColor(WHITE); cv.setFont('Helvetica', 6.5)
        words = sol.split()
        cv.drawString(sx, strip_y+14, ' '.join(words[:4]))
        if len(words)>4: cv.drawString(sx, strip_y+6, ' '.join(words[4:]))
        sx += sw

    cv.setFillColor(LIGHT); cv.setFont('Helvetica', 6)
    cv.drawString(M, 0.30*inch,
        f'Analysis based on {s["total_calls"]} inbound calls · {s["date_range"]}. '
        f'All findings derived from transcript data.')
    cv.drawRightString(W-M, 0.30*inch,
        'RingCentral AI Conversation Expert · Proof of Concept · Confidential')
    cv.setStrokeColor(RC_ORANGE); cv.setLineWidth(2); cv.line(0, 0.44*inch, W, 0.44*inch)
    cv.save()


# ══════════════════════════════════════════════════════════════
# SCORECARD + KEYWORDS
# ══════════════════════════════════════════════════════════════

def build_scorecard(data: dict, out_path: str, customer: str):
    s         = data["summary"]
    questions = data.get("scorecard_questions", [])
    lines = [
        "=" * 72,
        "RingCentral AI Conversation Expert — Call Scorecard",
        f"Customer: {customer}",
        f"Generated: {datetime.now().strftime('%B %d, %Y')}",
        f"Dataset: {s['total_calls']} calls · {s['date_range']}",
        "=" * 72, "",
        "INSTRUCTIONS",
        "  Each question is scored Yes / Partial / No by ACE on every call.",
        "  Review monthly and adjust thresholds as patterns change.", "",
    ]
    current_cat = ""
    for q in questions:
        cat = q.get("category", "General")
        if cat != current_cat:
            lines += ["", f"── {cat.upper()} " + "─" * (50 - len(cat))]
            current_cat = cat
        lines += ["", f"Q{q['number']:02d}. {q['question']}"]
        if q.get("context"):
            for ln in textwrap.wrap(f"  Context: {q['context']}", 70):
                lines.append(ln)
        if q.get("scoring"):
            for ln in textwrap.wrap(f"  Scoring: {q['scoring']}", 70):
                lines.append(ln)
    lines += ["", "=" * 72,
              "© 2026 RingCentral · Confidential · AI Conversation Expert", "=" * 72]
    Path(out_path).write_text("\n".join(lines))


def build_keywords(data: dict, out_path: str, customer: str):
    s        = data["summary"]
    keywords = data.get("keywords", [])
    lines = [
        "=" * 72,
        "RingCentral AI Conversation Expert — Keyword Tracking Configuration",
        f"Customer: {customer}",
        f"Generated: {datetime.now().strftime('%B %d, %Y')}",
        f"Dataset: {s['total_calls']} calls · {s['date_range']}",
        "=" * 72, "",
        "CONFIGURATION NOTE",
        "  Enter these as ACE topic tracking terms. Configure each to catch",
        "  natural language variants. Pair each keyword with its corresponding",
        "  scorecard question where possible.", "",
    ]
    current_group = ""
    for kw in keywords:
        group = kw.get("group", "General")
        if group != current_group:
            lines += ["", f"── {group.upper()} " + "─" * (50 - len(group))]
            current_group = group
        lines += ["", f"KW{kw['number']:02d}. \"{kw['term']}\""]
        if kw.get("rationale"):
            for ln in textwrap.wrap(f"  {kw['rationale']}", 70):
                lines.append(ln)
    lines += ["", "=" * 72,
              "© 2026 RingCentral · Confidential · AI Conversation Expert", "=" * 72]
    Path(out_path).write_text("\n".join(lines))
