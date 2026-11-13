"""Health check: every 30 min, verify that each scheduled post of the day really went out.

If a post is missing 15 min after its time, re-run its workflow automatically (up to 3 tries)
and tell the admins in the MCQ test group. Also reports failed workflow runs and a daily summary.
Bot guards in each script prevent double posts, so a re-run is always safe.
"""
import datetime as dt
import json
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "health_state.json")
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
TOKEN = os.environ["BOT_TOKEN"]
GH_TOKEN = os.environ.get("GH_TOKEN", "")
REPO = os.environ.get("GITHUB_REPOSITORY", "caintermcqs1/-shreshtamcqpoll_bot")
ALERT_CHAT = os.environ.get("ALERT_CHAT", "-1004340727881")  # MCQ'S poll test group (admins only)
GRACE = dt.timedelta(minutes=15)
MAX_TRIES = 3

now = dt.datetime.now(IST)
today = now.date().isoformat()
weekday = now.weekday()  # Mon=0 … Sun=6


def load(rel, default):
    try:
        with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return default


def tg(text):
    data = json.dumps({"chat_id": ALERT_CHAT, "text": text, "parse_mode": "HTML",
                       "disable_web_page_preview": True}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=30).read()
    except Exception as e:
        print("Alert failed:", e)


def gh(method, path, body=None):
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {GH_TOKEN}",
                                          "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        txt = r.read()
        return json.loads(txt) if txt else {}


def dispatch(wf, inputs=None):
    body = {"ref": "main"}
    if inputs:
        body["inputs"] = inputs
    try:
        gh("POST", f"/actions/workflows/{wf}/dispatches", body)
        return True
    except Exception as e:
        print("Dispatch failed:", wf, e)
        return False


# ---------------- what should have been posted today ----------------
ca = load("ca-inter-mcq-bot/state.json", {})
ca_plan = load("ca-inter-mcq-bot/plan.json", [])
ex = load("ca-inter-mcq-bot/extras_state.json", {})
study = load("ca-inter-mcq-bot/study.json", {})
promos = load("ca-inter-mcq-bot/promos.json", [])
cma = load("cma-inter-mcq-bot/state.json", {})
cma_plan = load("cma-inter-mcq-bot/plan.json", [])
cd_content = load("cma-inter-mcq-bot/cma_daily_content.json", {})
cd_done = load("cma-inter-mcq-bot/cma_daily_state.json", {}).get("done", {})


def mcq_applies(st, plan):
    return st.get("last_post_date") == today or st.get("next_index", 0) < len(plan)


def answers_ok(st):
    p = st.get("pending")
    return not (p and p.get("date") == today)


def cma_daily(mode):
    return all(f"{today}:{mode}:{g}" in cd_done for g in ("g1", "g2"))


def cma_has(mode):
    if mode == "countdown":
        return today in cd_content.get("countdown", {})
    return bool(cd_content.get(mode, {}).get(today))


# name, label, due (h, m), applies, ok, workflow, inputs
CHECKS = [
    ("cma_countdown", "CMA 9 AM countdown", (9, 0), lambda: cma_has("countdown"), lambda: cma_daily("countdown"),
     "11-cma-daily.yml", {"mode": "countdown"}),
    ("ca_mcq", "CA Inter 10:30 AM MCQs", (10, 30), lambda: mcq_applies(ca, ca_plan),
     lambda: ca.get("last_post_date") == today, "1-post-mcqs.yml", None),
    ("cma_mcq", "CMA Inter 10:30 AM MCQs", (10, 30), lambda: mcq_applies(cma, cma_plan),
     lambda: cma.get("last_post_date") == today, "4-cma-post-mcqs.yml", None),
    ("ca_study", "CA Inter 4 PM study content", (16, 0), lambda: bool(study.get(today)),
     lambda: ex.get("study_last_date") == today, "3-post-extras.yml", {"mode": "study"}),
    ("cma_study", "CMA 4 PM study content", (16, 0), lambda: cma_has("study"), lambda: cma_daily("study"),
     "11-cma-daily.yml", {"mode": "study"}),
    ("ca_fact", "CA Inter 6 PM tip/fact", (18, 0), lambda: True,
     lambda: ex.get("last_fact_date") == today, "3-post-extras.yml", {"mode": "fact"}),
    ("cma_fact", "CMA 6 PM tip/fact", (18, 0), lambda: cma_has("fact"), lambda: cma_daily("fact"),
     "11-cma-daily.yml", {"mode": "fact"}),
    ("ca_promo", "CA Inter 7 PM promotion (Tue/Thu)", (19, 0), lambda: weekday in (1, 3) and bool(promos),
     lambda: ex.get("last_promo_date") == today, "3-post-extras.yml", {"mode": "promo"}),
    ("ca_answers", "CA Inter 8:30 PM answers", (20, 30), lambda: ca.get("last_post_date") == today,
     lambda: answers_ok(ca), "2-post-answers.yml", None),
    ("cma_answers", "CMA Inter 8:30 PM answers", (20, 30), lambda: cma.get("last_post_date") == today,
     lambda: answers_ok(cma), "5-cma-post-answers.yml", None),
    ("cma_night", "CMA 9 PM concept + formula", (21, 0), lambda: cma_has("night"), lambda: cma_daily("night"),
     "11-cma-daily.yml", {"mode": "night"}),
]


def main():
    hs = load("health-check/health_state.json", {})
    if hs.get("date") != today:
        hs = {"date": today, "tries": {}, "alerted": [], "fixed": [], "runs_reported": hs.get("runs_reported", [])[-200:]}
    tries, alerted, fixed = hs["tries"], hs["alerted"], hs["fixed"]
    lines_ok, lines_bad = [], []

    if weekday != 6:  # Sunday: no scheduled posts to check
        for name, label, (h, m), applies, ok, wf, inputs in CHECKS:
            due = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if now < due + GRACE or not applies():
                continue
            if ok():
                lines_ok.append(label)
                if name in tries and name not in fixed:
                    fixed.append(name)
                    tg(f"✅ <b>Fixed:</b> {label} is now posted.")
                continue
            n = tries.get(name, 0)
            if n < MAX_TRIES:
                started = dispatch(wf, inputs)
                tries[name] = n + 1
                if name not in alerted:
                    alerted.append(name)
                    tg(f"⚠️ <b>Health check {now:%H:%M}:</b> {label} was NOT posted on time.\n"
                       f"{'🔁 Re-run started automatically – it will post now.' if started else '❌ Could not start the re-run.'}")
                lines_bad.append(f"{label} (re-run {n + 1})")
            else:
                lines_bad.append(f"{label} – still missing after {MAX_TRIES} re-runs")
                if f"{name}:gaveup" not in alerted:
                    alerted.append(f"{name}:gaveup")
                    tg(f"🚨 <b>{label} is still missing</b> after {MAX_TRIES} automatic re-runs. Please tell Claude.")

        # mirror (FRATERNITY) copies of today's MCQs
        for st, label in ((ca, "CA Inter"), (cma, "CMA Inter")):
            p = st.get("pending") or {}
            if p.get("date") == today and any(not s.get("mirrors") for s in p.get("sets", [])):
                fixable = label == "CA Inter" and now.hour < 20 and tries.get("mirror_ca", 0) < 2
                if fixable:
                    tries["mirror_ca"] = tries.get("mirror_ca", 0) + 1
                    started = dispatch("6-mirror-now.yml")
                if f"mirror:{label}" not in alerted:
                    alerted.append(f"mirror:{label}")
                    tg(f"⚠️ <b>{label} MCQs</b> were posted in the group but one set is missing in the FRATERNITY topic today."
                       + ("\n🔁 Copying it there now automatically." if fixable and started else "\nPlease tell Claude."))

    # ICAI site unreachable for a long time
    if ex.get("icai_fail_count", 0) >= 4 and "icai_fail" not in alerted:
        alerted.append("icai_fail")
        tg("⚠️ The ICAI update check has failed 4 times in a row (icai.org not reachable from GitHub). Please tell Claude.")

    # failed workflow runs (any workflow) in the last 3 hours
    if GH_TOKEN:
        try:
            since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
            runs = gh("GET", f"/actions/runs?status=failure&created=%3E{since}&per_page=30").get("workflow_runs", [])
            for r in runs:
                if r["id"] in hs["runs_reported"] or r.get("name", "").startswith("13."):
                    continue
                hs["runs_reported"].append(r["id"])
                tg(f"⚠️ <b>Workflow failed:</b> {r.get('name')} ({r.get('event')}) at "
                   f"{dt.datetime.fromisoformat(r['created_at'].replace('Z', '+00:00')).astimezone(IST):%d %b %H:%M}.\n"
                   f"{r.get('html_url')}")
        except Exception as e:
            print("Run list failed:", e)

    # one end-of-day summary
    if now.hour * 60 + now.minute >= 21 * 60 + 30 and not hs.get("summary_sent") and weekday != 6:
        hs["summary_sent"] = True
        txt = f"📋 <b>Daily posting report – {now:%a %d %b}</b>\n"
        txt += "".join(f"\n✅ {x}" for x in lines_ok) + "".join(f"\n❌ {x}" for x in lines_bad)
        if fixed:
            txt += "\n\n🔁 Auto-fixed today: " + ", ".join(fixed)
        tg(txt)

    print("OK:", lines_ok)
    print("Missing:", lines_bad)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(hs, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
