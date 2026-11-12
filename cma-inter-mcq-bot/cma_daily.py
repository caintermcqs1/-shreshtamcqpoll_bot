"""CMA Inter daily posts (both G1 and G2 topics, Mon–Sat):
  countdown – 9:00 AM exam countdown + today's revision target
  study     – 4:00 PM study content linked to today's MCQs
  fact      – 6:00 PM fun fact / study tip (alternate days)
  night     – 9:00 PM Concept of the Day + Formula/Section of the Day; on Saturday also the weekly recap at 9:30 PM
  recap     – weekly recap only (manual)
  notice    – edit the pinned welcome message and send a schedule announcement (manual)
Content: cma_daily_content.json (date-wise). State: cma_daily_state.json. Exam dates: ICMAI Dec 2026 time table.
"""
import datetime as dt, html, json, os, sys, time, urllib.error, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
TOKEN = os.environ["BOT_TOKEN"]
CHAT = "-1002255328356"
TOPIC = {"g1": 682, "g2": 683}
FIRST_PAPER = {"g1": (dt.date(2026, 12, 10), "P5 Business Laws and Ethics – Thu 10 Dec, 2:00 PM"),
               "g2": (dt.date(2026, 12, 11), "P9 Operations Management and Strategic Management – Fri 11 Dec, 2:00 PM")}
GNAME = {"g1": "Group 1", "g2": "Group 2"}
E = lambda t: html.escape(str(t), quote=False)


def load(name, default):
    try:
        with open(os.path.join(HERE, name), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save(name, data):
    with open(os.path.join(HERE, name), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def send(text, g):
    data = {"chat_id": CHAT, "message_thread_id": TOPIC[g], "text": text, "parse_mode": "HTML",
            "disable_web_page_preview": "true"}
    req = urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data=urllib.parse.urlencode(data).encode())
    with urllib.request.urlopen(req, timeout=30) as r:
        res = json.load(r)
    if not res.get("ok"):
        raise RuntimeError(res)
    print(f"Sent to {g}:", text.splitlines()[0][:70])


def wait_until(h, m):
    now = dt.datetime.now(IST)
    t = now.replace(hour=h, minute=m, second=0, microsecond=0)
    w = (t - now).total_seconds()
    if w > 0:
        print(f"Waiting {int(w)} s until {h:02d}:{m:02d} IST")
        time.sleep(w)


def countdown_text(g, c, today):
    exam, label = FIRST_PAPER[g]
    n = (exam - today).days
    if n < 1:
        return None
    head = f"⏳ <b>CMA INTER DEC 2026 – {n} {'DAY' if n == 1 else 'DAYS'} TO GO!</b>"
    return (f"{head}\n📅 Your first {GNAME[g]} paper: {E(label)}\n"
            f"🎯 <b>Today's target:</b> {E(c[g])}\n"
            "✅ Then attempt today's 10:30 AM MCQs in this topic.\n"
            f"💪 <i>{E(c['mot'])}</i>")


def recap_text(g, today):
    st = load("state.json", {})
    plan = load("plan.json", [])
    monday = today - dt.timedelta(days=today.weekday())
    week = [h for h in st.get("history", []) if h.get("group") == GNAME[g]
            and monday.isoformat() <= h.get("date", "") <= today.isoformat()]
    if not week:
        return None
    rows, votes = [], 0
    for h in week:
        day = next((p for p in plan if p.get("day") == h.get("day") and p.get("group") == h.get("group")), None)
        if not day:
            continue
        for i, r in enumerate(h.get("results", [])):
            if r and r.get("total"):
                votes += r["total"]
                it = day["items"][i]
                rows.append((r["correct"] / r["total"], it["topic"], it["o"][it["ans"]], r["total"]))
    exam, label = FIRST_PAPER[g]
    n = (exam - today).days
    wk = (today - dt.date(2026, 11, 9)).days // 7 + 1
    lines = [f"📊 <b>WEEKLY RECAP – Week {wk} | {GNAME[g]}</b>",
             f"This week: {len(week)} MCQ sets · {votes} votes" + (f" · average {round(100 * sum(x[0] for x in rows) / len(rows))}% correct" if rows else "")]
    if rows:
        rows.sort()
        lines += ["", "❌ <b>Most-missed questions this week:</b>"]
        for k, (p, topic, ans, tot) in enumerate(rows[:3], 1):
            lines.append(f"{k}. {E(topic)} – {round(100 * p)}% correct → Right answer: <b>{E(ans)}</b>")
        lines += ["", f"🔁 <b>Revise before Monday:</b> {E(', '.join(x[1] for x in rows[:3]))}."]
    if n > 0:
        lines.append(f"⏳ {n} days to your first {GNAME[g]} paper ({E(label.split(' – ')[0])}).")
    lines.append("💪 <i>Mistakes in practice cost nothing – fix them this weekend. See you Monday at 10:30 AM!</i>")
    return "\n".join(lines)


def tg(method, data):
    req = urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/{method}", data=urllib.parse.urlencode(data).encode())
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            res = json.load(r)
    except urllib.error.HTTPError as err:
        res = json.load(err)
    print(method, res.get("ok"), res.get("description", ""))
    return res


def notice():
    """Edit the pinned welcome message (id in cma_daily_state.json, default 722) and send a fresh announcement."""
    with open(os.path.join(HERE, "cma_notice.txt"), encoding="utf-8") as f:
        pinned = f.read().strip()
    with open(os.path.join(HERE, "cma_announce.txt"), encoding="utf-8") as f:
        ann = f.read().strip()
    mid = load("cma_daily_state.json", {}).get("pinned_id", 722)
    tg("editMessageText", {"chat_id": CHAT, "message_id": mid, "text": pinned, "parse_mode": "HTML",
                           "disable_web_page_preview": "true"})
    tg("sendMessage", {"chat_id": CHAT, "text": ann, "parse_mode": "HTML", "disable_web_page_preview": "true"})


def main():
    mode = (sys.argv[1] if len(sys.argv) > 1 else "").lower()
    if mode == "notice":
        notice()
        return
    wait = os.environ.get("WAIT", "") == "1"
    times = {"countdown": (9, 0), "study": (16, 0), "fact": (18, 0), "night": (21, 0), "recap": (21, 30)}
    if mode not in times:
        sys.exit("mode must be one of: " + ", ".join(times))
    if wait:
        wait_until(*times[mode])
    today = dt.datetime.now(IST).date()
    if today.weekday() == 6:
        print("Sunday – no posts.")
        return
    key = today.isoformat()
    content = load("cma_daily_content.json", {})
    state = load("cma_daily_state.json", {})
    done = state.setdefault("done", {})
    try:
        for m in (["night", "recap"] if mode == "night" and today.weekday() == 5 else [mode]):
            if m == "recap" and wait and mode == "night":
                wait_until(*times["recap"])
            for g in ("g1", "g2"):
                tag = f"{key}:{m}:{g}"
                if tag in done:
                    print("Already posted", tag)
                    continue
                if m == "countdown":
                    c = content.get("countdown", {}).get(key)
                    text = countdown_text(g, c, today) if c else None
                elif m == "recap":
                    text = recap_text(g, today)
                else:
                    text = content.get(m, {}).get(key, {}).get(g)
                if not text:
                    print("No content for", tag)
                    continue
                send(text, g)
                done[tag] = True
                save("cma_daily_state.json", state)
    finally:
        state["done"] = {k: v for k, v in done.items() if k[:10] >= (today - dt.timedelta(days=14)).isoformat()}
        save("cma_daily_state.json", state)


if __name__ == "__main__":
    main()
