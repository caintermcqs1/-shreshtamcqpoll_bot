"""Extras for the CA Inter MCQ group: daily fact, promotions,
official ICAI Intermediate announcements, and CA Inter YouTube videos.

Usage: python extras.py <fact|promo|check|all>
State is kept in extras_state.json (separate from the MCQ state.json).
"""
import datetime as dt
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "extras_state.json")
CFG_FILE = os.path.join(HERE, "extras_config.json")
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"

TOKEN = os.environ["BOT_TOKEN"]
try:
    with open(os.path.join(HERE, "config.json"), encoding="utf-8") as _f:
        _chat = json.load(_f).get("chat_id")
except (FileNotFoundError, ValueError):
    _chat = None
CHAT_ID = str(_chat or os.environ["CHAT_ID"]).strip()
TOPIC_ID = os.environ.get("TOPIC_ID", "").strip()


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def today():
    return dt.datetime.now(IST).date().isoformat()


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def send(text, preview=False, where="general"):
    data = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "false" if preview else "true",
    }
    thread = (load(CFG_FILE, {}).get("topics", {}).get(CHAT_ID, {}) or {}).get(where)
    if thread:
        data["message_thread_id"] = thread
    elif TOPIC_ID:
        data["message_thread_id"] = TOPIC_ID
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data=urllib.parse.urlencode(data).encode(),
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        res = json.load(r)
    if not res.get("ok"):
        raise RuntimeError(res)
    print("Sent:", text.splitlines()[0][:80])
    return res["result"]["message_id"]


def post_notice():
    """Post notice.txt (trusted HTML written by us) and pin it."""
    with open(os.path.join(HERE, "notice.txt"), encoding="utf-8") as f:
        text = f.read().strip()
    mid = send(text)
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TOKEN}/pinChatMessage",
        data=urllib.parse.urlencode({"chat_id": CHAT_ID, "message_id": mid,
                                     "disable_notification": "true"}).encode(),
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        print("Pinned:", json.load(r).get("ok"))


# ---------------- daily fact ----------------
def todays_group():
    """Group of today's MCQ day (from the MCQ bot's state), or None."""
    st = load(os.path.join(HERE, "state.json"), {}) or {}
    t = today()
    for h in reversed(st.get("history", [])):
        if h.get("date") == t:
            return h.get("group")
    p = st.get("pending")
    if p and p.get("date") == t:
        plan = load(os.path.join(HERE, "plan.json"), []) or []
        if p.get("index", 0) < len(plan):
            return plan[p["index"]].get("group")
    return None


MOTIVATION = [
    "Jan 2027 is not far – every hour you study today is a mark you collect in the exam hall.",
    "ICAI doesn't check how hard the paper was – it checks how well you prepared. Prepare well.",
    "The pass list has room for everyone who refuses to give up.",
    "40 in each, 50 in aggregate – one chapter at a time, one paper at a time.",
    "Reading is learning; writing answers is passing. Practise one question today.",
    "RTPs, MTPs and PYQs are your best teachers – don't leave them for the last week.",
    "Three revisions turn \"I've read it\" into \"I can write it\".",
    "Standards, sections and formats – learn them once properly, revise them many times.",
    "Every CA was once a CA Inter student who doubted themselves – and kept going anyway.",
    "A tough chapter is not a wall, it's a step. Climb it today.",
    "Compare yourself with who you were yesterday, not with the topper.",
    "Failure in a mock is free; failure in the exam is costly. Make your mistakes now.",
    "Phone down, book open – the next 2 hours decide more than you think.",
    "Consistency beats talent when talent doesn't stay consistent.",
    "\"CA\" next to your name is built by small daily habits – start today's habit now.",
    "Small steps every day add up to a big result. Keep going! 💪",
    "You don't have to be perfect – just better than yesterday.",
    "Every page you revise today is one less worry in the exam hall.",
    "Discipline beats motivation. Show up, open the book, start.",
    "The CA tag is earned one chapter at a time – today's chapter counts.",
    "Tough syllabus, tougher you. Keep pushing! 🔥",
    "Consistency is your superpower. One more hour today.",
    "Don't count the days, make the days count.",
    "Mistakes in practice mean fewer mistakes in the exam. Keep practising.",
    "Your future self will thank you for the effort you put in today.",
    "Revision is where marks are made. Don't skip it.",
    "Believe in your preparation – it is stronger than you think.",
    "Focus on progress, not perfection. 🚀",
    "Every topper was once a beginner who refused to quit.",
    "Study now, celebrate later. 🎯",
    "One concept clear today = one question right in the exam.",
    "Stay calm, stay consistent, stay confident.",
    "The pain of discipline is lighter than the pain of regret.",
    "Write answers, not just read them – the exam rewards practice.",
    "You are closer to your goal than you were yesterday. Keep going! ✨",
]


def post_fact(state):
    """6 PM: post in BOTH group topics every day; all topics get a Study Tip one day and a Fun Fact the next."""
    if state.get("last_fact_date") == today():
        print("Fact/tip already posted today")
        return
    facts = load(os.path.join(HERE, "facts.json"), []) or []
    tips = load(os.path.join(HERE, "tips.json"), []) or []
    step = state.get("fact_cycle", 0)
    want = "tip" if step % 2 == 0 else "fact"
    for group, g in (("Group 1", "g1"), ("Group 2", "g2")):
        kind_key = f"next_kind_{g}"
        kind = want
        pool = [f for f in (facts if kind == "fact" else tips) if f.get("group") == group]
        if not pool:
            kind = "fact"
            pool = [f for f in facts if f.get("group") == group]
            if not pool:
                continue
        key = f"{kind}_index_{g}"
        i = state.get(key, 0) % len(pool)
        f = pool[i]
        head = "💡 <b>Fun Fact" if kind == "fact" else "📚 <b>Study Tip"
        text = (f"{head} – {html.escape(f.get('subject', 'CA Inter'))}</b>\n\n"
                f"<b>{html.escape(f['title'])}</b>\n{html.escape(f['text'])}")
        if f.get("link"):
            text += f"\n\n📌 <b>Link to your syllabus:</b> {html.escape(f['link'])}"
        if f.get("source"):
            text += f"\n\n<i>Source: {html.escape(f['source'])}</i>"
        if kind == "tip":
            mi = state.get("motivation_index", 0) % len(MOTIVATION)
            text += f"\n\n🔥 <b>Today's motivation:</b> <i>{html.escape(MOTIVATION[mi])}</i>"
            state["motivation_index"] = mi + 1
        try:
            send(text, where=g)
        except Exception as e:
            print(f"{group}: could not send: {e}")
            continue
        state[key] = i + 1
        state[kind_key] = "tip" if kind == "fact" else "fact"
        state["fact_cycle"] = step + 1
    state["last_fact_date"] = today()


# ---------------- promotion ----------------
def post_promo(state):
    if state.get("last_promo_date") == today():
        print("Promo already posted today")
        return
    promos = load(os.path.join(HERE, "promos.json"), [])
    if not promos:
        return
    i = state.get("promo_index", 0) % len(promos)
    send(promos[i]["text"], preview=True)  # promo text is trusted HTML written by us
    state["promo_index"] = i + 1
    state["last_promo_date"] = today()


# ---------------- ICAI official announcements ----------------
ICAI_URL = "https://www.icai.org/category/announcements"
ITEM_RE = re.compile(r'<li[^>]*class=["\'][^"\']*list-group-item[^"\']*["\'][^>]*>\s*<a[^>]*?href\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.S | re.I)


def clean(s):
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def check_icai(state, cfg):
    try:
        page = fetch(ICAI_URL)
    except Exception as e:
        print("ICAI fetch failed:", e)
        state["icai_fail_count"] = state.get("icai_fail_count", 0) + 1
        return
    items = ITEM_RE.findall(page)
    if not items:
        print("ICAI page format changed: no items found. Page length", len(page))
        print("ICAI page start:", re.sub(r"\s+", " ", page[:600]))
        i = page.find("list-group-item")
        print("ICAI around list-group-item:", re.sub(r"\s+", " ", page[max(0, i - 100):i + 400]) if i >= 0 else "not present")
        state["icai_fail_count"] = state.get("icai_fail_count", 0) + 1
        return
    state["icai_fail_count"] = 0
    kw = re.compile(cfg.get("icai_keywords", r"\binter(mediate)?\b"), re.I)
    seen = state.setdefault("icai_seen", [])
    first_run = not seen
    new = []
    for href, title in items:
        title = clean(title)
        url = urllib.parse.urljoin(ICAI_URL, href)
        key = title  # some items share a URL (e.g. results portal), so key on title
        if key in seen:
            continue
        seen.append(key)
        if not first_run and kw.search(title):
            new.append((title, url))
    state["icai_seen"] = seen[-300:]
    if first_run:
        print(f"ICAI: first run, marked {len(items)} existing items as seen")
    for title, url in reversed(new):  # oldest first
        text = (
            "📢 <b>ICAI Official Update – CA Intermediate</b>\n\n"
            f"{html.escape(title)}\n\n"
            f'🔗 Official link: <a href="{html.escape(url)}">{html.escape(url)}</a>\n'
            "<i>Source: icai.org</i>"
        )
        send(text, where="updates")


# ---------------- YouTube (CA Inter only) ----------------
def channel_id(cfg, state):
    if state.get("yt_channel_id"):
        return state["yt_channel_id"]
    page = fetch(cfg["youtube_channel_url"])
    m = re.search(r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]{22})"', page) or \
        re.search(r'"channelId":"(UC[\w-]{22})"', page) or \
        re.search(r'"externalId":"(UC[\w-]{22})"', page)
    if not m:
        raise RuntimeError("Could not find YouTube channel id")
    state["yt_channel_id"] = m.group(1)
    return m.group(1)


def check_youtube(state, cfg):
    if not cfg.get("youtube_channel_url"):
        return
    try:
        cid = channel_id(cfg, state)
        feed = fetch(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}")
    except Exception as e:
        print("YouTube fetch failed:", e)
        return
    ns = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
          "media": "http://search.yahoo.com/mrss/"}
    root = ET.fromstring(feed)
    kw = re.compile(cfg.get("youtube_keywords", r"\binter(mediate)?\b"), re.I)
    motiv = re.compile(cfg["youtube_motivation_keywords"], re.I) if cfg.get("youtube_motivation_keywords") else None
    excl = re.compile(cfg["youtube_exclude_keywords"], re.I) if cfg.get("youtube_exclude_keywords") else None
    seen = state.setdefault("yt_seen", [])
    first_run = not seen
    now = dt.datetime.now(dt.timezone.utc)
    new = []
    for e in root.findall("a:entry", ns):
        vid = e.findtext("yt:videoId", "", ns)
        title = e.findtext("a:title", "", ns)
        desc = e.findtext("media:group/media:description", "", ns)
        published = dt.datetime.fromisoformat(e.findtext("a:published", "", ns))
        if vid in seen:
            continue
        seen.append(vid)
        # title only: every description mentions CA Inter
        if kw.search(title):
            is_motiv = False
        elif motiv and motiv.search(title) and not (excl and excl.search(title)):
            is_motiv = True
        else:
            print("YouTube skip:", title)
            continue
        # first run: only share a video from the last 7 days, never the old backlog
        if first_run and (now - published).days > 7:
            continue
        new.append((published, vid, title, is_motiv))
    state["yt_seen"] = seen[-300:]
    new.sort()
    if first_run:
        new = new[-1:]
    for _, vid, title, is_motiv in new:
        url = f"https://www.youtube.com/watch?v={vid}"
        head = ("🔥 <b>New video from CA Ram Harsha YouTube Channel!</b>" if is_motiv
                else "🎥 <b>New CA Inter video from CA Ram Harsha YouTube Channel!</b>")
        text = (
            f"{head}\n\n"
            f"{html.escape(title)}\n\n"
            f"▶️ Watch now: {url}\n"
            "👍 Like, share with your friends & subscribe for more!"
        )
        send(text, preview=True, where="updates")


def main():
    mode = (sys.argv[1] if len(sys.argv) > 1 else "check").lower()
    state = load(STATE_FILE, {})
    cfg = load(CFG_FILE, {})
    if mode == "youtube":
        try:
            check_youtube(state, cfg)
        finally:
            save_state(state)
        return
    if mode == "notice":
        post_notice()
        return
    try:
        if mode in ("fact", "all"):
            post_fact(state)
        if mode in ("promo", "all"):
            post_promo(state)
        if mode in ("check", "fact", "all"):
            check_icai(state, cfg)
            check_youtube(state, cfg)
    finally:
        save_state(state)


if __name__ == "__main__":
    main()
