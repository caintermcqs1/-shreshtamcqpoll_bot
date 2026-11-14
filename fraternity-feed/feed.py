"""Shares every new video from Sir's YouTube channel (videos + Shorts)
into the SHRESHTA's FRATERNITY main group (General).

Usage: python feed.py <youtube|recent|latest|info>
State: feed_state.json (videos already seen / shared).
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
STATE_FILE = os.path.join(HERE, "feed_state.json")
CFG_FILE = os.path.join(HERE, "feed_config.json")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
TOKEN = os.environ["BOT_TOKEN"]


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


CFG = load(CFG_FILE, {})


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def tg(method, data):
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TOKEN}/{method}",
        data=urllib.parse.urlencode(data).encode(),
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            res = json.load(r)
    except urllib.error.HTTPError as e:
        res = json.loads(e.read().decode() or "{}")
    if not res.get("ok"):
        raise RuntimeError(res)
    return res["result"]


def send(text):
    data = {"chat_id": CFG["chat_id"], "text": text, "parse_mode": "HTML",
            "disable_web_page_preview": "false"}
    if CFG.get("topic_id"):
        data["message_thread_id"] = CFG["topic_id"]
    tg("sendMessage", data)
    print("Sent:", text.splitlines()[0][:80])


def info():
    chat = tg("getChat", {"chat_id": CFG["chat_id"]})
    print("Chat:", chat.get("id"), chat.get("type"), chat.get("title"), "forum" if chat.get("is_forum") else "")


def channel_page_videos():
    base = CFG["youtube_channel_url"].rstrip("/")
    ids = []
    for path, pat in (("videos", r"i\.ytimg\.com/vi/([\w-]{11})/"), ("shorts", r"shorts-shelf-item-([\w-]{11})"),
                      ("streams", r"i\.ytimg\.com/vi/([\w-]{11})/")):
        try:
            page = fetch(f"{base}/{path}")
        except Exception as e:
            print("YouTube page fetch failed:", path, e)
            continue
        found = []
        for vid in re.findall(pat, page):
            if vid not in found:
                found.append(vid)
        ids += found[:6]
    return ids


def video_title(vid):
    data = json.loads(fetch(f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid}&format=json"))
    return data.get("title", "")


def check_youtube(state):
    seen = state.setdefault("yt_seen", [])
    first_run = not state.get("feed_seeded")
    now = dt.datetime.now(dt.timezone.utc)
    new = []
    try:
        feed = fetch(f"https://www.youtube.com/feeds/videos.xml?channel_id={CFG['youtube_channel_id']}")
        ns = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
        shared = state.setdefault("shared", [])
        for e in ET.fromstring(feed).findall("a:entry", ns):
            vid = e.findtext("yt:videoId", "", ns)
            published = dt.datetime.fromisoformat(e.findtext("a:published", "", ns))
            recent = (now - published).total_seconds() <= 24 * 3600
            if vid in shared:
                continue
            # safety net: anything Sir published in the last 24 h that was never sent here gets sent,
            # even if an earlier run had already marked it as seen
            if vid in seen and not recent:
                continue
            if vid not in seen:
                seen.append(vid)
            if first_run and not recent:
                continue   # first run: skip the old backlog
            new.append((published, vid, e.findtext("a:title", "", ns)))
        state["feed_seeded"] = True
    except Exception as e:
        print("YouTube feed failed:", e)
    page_ids = channel_page_videos()
    if page_ids and not state.get("yt_page_seeded"):
        seen += [v for v in page_ids if v not in seen]
        state["yt_page_seeded"] = True
        page_ids = []
    for vid in page_ids:
        if vid in seen:
            continue
        try:
            title = video_title(vid)
        except Exception as e:
            print("YouTube title failed:", vid, e)
            continue
        seen.append(vid)
        new.append((now, vid, title))
    state["yt_seen"] = seen[-400:]
    new.sort()
    for _, vid, title in new:
        if vid in state.setdefault("shared", []):
            continue
        post_video(vid, title)
        state["shared"].append(vid)
        save_state(state)


def post_video(vid, title):
    text = (
        "\U0001f3a5 <b>New video from CA Ram Harsha YouTube Channel!</b>\n\n"
        f"{html.escape(title)}\n\n"
        f"\u25b6\ufe0f Watch now: https://www.youtube.com/watch?v={vid}\n"
        "\U0001f44d Like, share with your friends & subscribe for more!"
    )
    send(text)


def post_latest(state):
    """Manual: post Sir's newest long video now (sample / catch-up)."""
    page = fetch(CFG["youtube_channel_url"].rstrip("/") + "/videos")
    vid = re.search(r"i\.ytimg\.com/vi/([\w-]{11})/", page).group(1)
    post_video(vid, video_title(vid))
    seen = state.setdefault("yt_seen", [])
    if vid not in seen:
        seen.append(vid)


AGE = re.compile(r'(?:"content"|"simpleText"):"[^"\d]{0,20}(\d+)\s*(seconds?|minutes?|mins?|hours?|hrs?|days?|s|m|h|d)\b[^"]*ago"', re.I)


def recent_from_pages(hours):
    """(vid, age_hours) for long videos and lives whose 'x ago' label is within <hours> (channel pages)."""
    base = CFG["youtube_channel_url"].rstrip("/")
    out = []
    for path in ("videos", "streams"):
        try:
            page = fetch(f"{base}/{path}")
        except Exception as e:
            print("Page failed:", path, e)
            continue
        print("Page", path, len(page), "chars,", page.count('"contentId"'), "contentId,", page.count('"publishedTimeText"'), "publishedTimeText")
        for m in re.finditer(r'"(?:contentId|videoId)":"([\w-]{11})"', page):
            vid = m.group(1)
            a = AGE.search(page, m.end(), m.end() + 8000)
            if not a:
                continue
            n, unit = int(a.group(1)), a.group(2).lower()
            age = n / 3600 if unit.startswith("s") else n / 60 if unit.startswith("m") else n if unit.startswith("h") else n * 24
            print("Video", vid, a.group(0)[11:], round(age, 1), "h")
            if age < hours and vid not in [v for v, _ in out]:
                out.append((vid, age))
    return out


def post_recent(state, hours=24):
    """Manual: post every long video / live from the last <hours> hours that wasn't shared here yet (oldest first)."""
    shared = state.setdefault("shared", [])
    seen = state.setdefault("yt_seen", [])
    found = [x for x in recent_from_pages(hours) if x[0] not in shared]
    # videos listed by hand in feed_config.json "post_now" (used when the page can't be read)
    for vid in CFG.get("post_now", []):
        if vid not in shared and vid not in [v for v, _ in found]:
            found.append((vid, 99))
    for vid, _ in sorted(found, key=lambda x: -x[1]):
        post_video(vid, video_title(vid))
        shared.append(vid)
        if vid not in seen:
            seen.append(vid)
        save_state(state)
    print("Posted", len(found), "recent video(s)")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "youtube"
    state = load(STATE_FILE, {})
    if mode == "info":
        info()
        return
    try:
        if mode == "latest":
            post_latest(state)
        elif mode == "recent":
            post_recent(state)
        else:
            check_youtube(state)
    finally:
        save_state(state)


if __name__ == "__main__":
    main()
