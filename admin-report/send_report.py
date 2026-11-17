"""Send admin-report/report.txt (trusted HTML written by us) to the MCQ'S poll admin group (workflow 20).
Long reports are split into several messages (max ~3,900 chars each) at blank lines. A line '=====' forces a new message."""
import json, os, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN = os.environ["BOT_TOKEN"]
CHAT = os.environ.get("ADMIN_CHAT", "-1004340727881")  # MCQ'S poll group (admins only)
LIMIT = 3900


def chunks(text):
    out, cur = [], ""
    for block in text.replace("\n=====\n", "\n\n\u0000\n\n").split("\n\n"):
        if block.strip() == "\u0000":
            if cur.strip():
                out.append(cur.strip())
            cur = ""
            continue
        while len(block) > LIMIT:
            cut = block.rfind("\n", 0, LIMIT)
            if cut <= 0:
                cut = LIMIT
            out.append(block[:cut]); block = block[cut:]
        if len(cur) + len(block) + 2 > LIMIT and cur.strip():
            out.append(cur.strip()); cur = ""
        cur += block + "\n\n"
    if cur.strip():
        out.append(cur.strip())
    return out


def send(text):
    data = {"chat_id": CHAT, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"}
    req = urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data=urllib.parse.urlencode(data).encode())
    with urllib.request.urlopen(req, timeout=30) as r:
        res = json.load(r)
    print("sendMessage", res.get("ok"), res.get("description", ""))
    if not res.get("ok"):
        raise SystemExit(1)


with open(os.path.join(HERE, "report.txt"), encoding="utf-8") as f:
    parts = chunks(f.read().strip())
for i, p in enumerate(parts):
    send(p)
    time.sleep(1.2)
print(len(parts), "message(s) sent")
