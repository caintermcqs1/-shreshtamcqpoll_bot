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
def post_fact(state):
    if state.get("last_fact_date") == today():
        print("Fact already posted today")
        return
    facts = load(os.path.join(HERE, "facts.json"), [])
    if not facts:
        return
    i = state.get("fact_index", 0) % len(facts)
    f = facts[i]
    text = f"💡 <b>{html.escape(f['title'])}</b>\n\n{html.escape(f['text'])}"
    send(text)
    state["fact_index"] = i + 1
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
        if not kw.search(title + " " + desc):
            print("YouTube skip (not CA Inter):", title)
            continue
        # first run: only share a video from the last 7 days, never the old backlog
        if first_run and (now - published).days > 7:
            continue
        new.append((published, vid, title))
    state["yt_seen"] = seen[-300:]
    new.sort()
    if first_run:
        new = new[-1:]
    for _, vid, title in new:
        url = f"https://www.youtube.com/watch?v={vid}"
        text = (
            "🎥 <b>New CA Inter video from CA Ram Harsha Sir!</b>\n\n"
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
