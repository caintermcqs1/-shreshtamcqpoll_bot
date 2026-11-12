"""Updates for the CMA Inter group: ICMAI official notices and CMA Inter YouTube videos.

Usage: python cma_extras.py <check|icmai|youtube|notice>
State is kept in cma_extras_state.json.
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
STATE_FILE = os.path.join(HERE, "cma_extras_state.json")
CFG_FILE = os.path.join(HERE, "cma_extras_config.json")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
TOKEN = os.environ["BOT_TOKEN"]


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8", errors="replace")


def send(cfg, text, topic, preview=False):
    data = {"chat_id": cfg["chat_id"], "text": text, "parse_mode": "HTML",
            "disable_web_page_preview": "false" if preview else "true"}
    if topic:
        data["message_thread_id"] = topic
    req = urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                                 data=urllib.parse.urlencode(data).encode())
    with urllib.request.urlopen(req, timeout=30) as r:
        res = json.load(r)
    if not res.get("ok"):
        raise RuntimeError(res)
    print("Sent:", text.splitlines()[0][:80])


def clean(s):
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


# ---------------- ICMAI ----------------
ICMAI_SOURCES = [
    ("https://icmai.in/ClntStudents/UpdateandAnnouncements", False),  # student announcements: all
    ("https://icmai.in/ClntAbout/Updates", True),                     # general updates: student-related only
]
STUDENT_RE = re.compile(r"\b(inter(mediate)?|students?|exam(ination)?s?|admit\s*card|results?|time\s*table|"
                        r"syllabus|mock|registration|e-?learning|study\s*material|CMA\s*course)\b", re.I)
INTER_RE = re.compile(r"\binter(mediate)?\b", re.I)
OTHER_RE = re.compile(r"\b(foundation|final|CAT|members?|PCMAs?|practising|tender|chapter)\b", re.I)
LINK_RE = re.compile(r'<a[^>]*?href\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.S | re.I)


def icmai_items(url):
    page = fetch(url)
    i = page.find("disciplinary-wrap")
    if i < 0:
        raise RuntimeError("ICMAI page format changed (no disciplinary-wrap)")
    j = page.find("</ul>", i)
    block = page[i:j if j > 0 else None]
    out = []
    for href, title in LINK_RE.findall(block):
        title = re.sub(r"\bNew\s*$", "", clean(title)).strip()
        if len(title) > 10:
            out.append((title, urllib.parse.urljoin(url, href.strip()).replace(" ", "%20")))
    return out


def wanted(title, needs_student):
    if needs_student and not STUDENT_RE.search(title):
        return False
    if OTHER_RE.search(title) and not INTER_RE.search(title):
        return False
    return True


def check_icmai(state, cfg):
    seen = state.setdefault("icmai_seen", [])
    first_run = not seen
    first_post = re.compile(cfg.get("icmai_first_run_post", r"$^"), re.I)
    new = []
    for url, needs_student in ICMAI_SOURCES:
        try:
            items = icmai_items(url)
        except Exception as e:
            print("ICMAI fetch failed:", url, e)
            continue
        print(f"ICMAI: {len(items)} items on {url}")
        for title, link in items:
            if title in seen:
                continue
            seen.append(title)
            if not wanted(title, needs_student):
                print("ICMAI skip:", title)
                continue
            if first_run and not first_post.search(title):
                continue  # first run: don't post the old backlog
            new.append((title, link))
    state["icmai_seen"] = seen[-400:]
    for title, link in new:
        text = ("📢 <b>ICMAI Official Update – CMA Intermediate</b>\n\n"
                f"{html.escape(title)}\n\n"
                f'🔗 Official link: <a href="{html.escape(link)}">Open on icmai.in</a>\n'
                "<i>Source: icmai.in</i>")
        send(cfg, text, cfg["topics"]["icmai"])


# ---------------- YouTube (CMA Inter videos) ----------------
def check_youtube(state, cfg):
    cid = cfg["youtube_channel_id"]
    try:
        feed = fetch(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}")
    except Exception as e:
        print("YouTube fetch failed:", e)
        return
    ns = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
    root = ET.fromstring(feed)
    kw = re.compile(cfg["youtube_keywords"], re.I)
    seen = state.setdefault("yt_seen", [])
    first_run = not seen
    now = dt.datetime.now(dt.timezone.utc)
    new = []
    for e in root.findall("a:entry", ns):
        vid = e.findtext("yt:videoId", "", ns)
        title = e.findtext("a:title", "", ns)
        published = dt.datetime.fromisoformat(e.findtext("a:published", "", ns))
        if vid in seen:
            continue
        seen.append(vid)
        if not kw.search(title):
            print("YouTube skip:", title)
            continue
        if first_run and (now - published).days > 7:
            continue
        new.append((published, vid, title))
    state["yt_seen"] = seen[-300:]
    new.sort()
    if first_run:
        new = new[-1:]
    for _, vid, title in new:
        text = ("🎥 <b>New CMA Inter video from CA Ram Harsha YouTube Channel!</b>\n\n"
                f"{html.escape(title)}\n\n"
                f"▶️ Watch now: https://www.youtube.com/watch?v={vid}\n"
                "👍 Like, share with your friends & subscribe for more!")
        send(cfg, text, cfg["topics"]["updates"], preview=True)


def post_notice(cfg):
    """Post cma_notice.txt (trusted HTML written by us) in General and pin it."""
    with open(os.path.join(HERE, "cma_notice.txt"), encoding="utf-8") as f:
        text = f.read().strip()
    data = {"chat_id": cfg["chat_id"], "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"}
    req = urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                                 data=urllib.parse.urlencode(data).encode())
    with urllib.request.urlopen(req, timeout=30) as r:
        res = json.load(r)
    if not res.get("ok"):
        raise RuntimeError(res)
    mid = res["result"]["message_id"]
    print("Sent notice", mid)
    req = urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/pinChatMessage",
                                 data=urllib.parse.urlencode({"chat_id": cfg["chat_id"], "message_id": mid,
                                                              "disable_notification": "false"}).encode())
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print("Pinned:", json.load(r).get("ok"))
    except Exception as e:
        print("Could not pin (give the bot 'Pin messages' permission):", e)


def main():
    mode = (sys.argv[1] if len(sys.argv) > 1 else "check").lower()
    state = load(STATE_FILE, {})
    cfg = load(CFG_FILE, {})
    if mode == "notice":
        post_notice(cfg)
        return
    try:
        if mode in ("check", "icmai"):
            check_icmai(state, cfg)
        if mode in ("check", "youtube"):
            check_youtube(state, cfg)
    finally:
        save_state(state)


if __name__ == "__main__":
    main()
