"""Send admin-report/report.txt (trusted HTML written by us) to the MCQ'S poll admin group. Manual only (workflow 20)."""
import json, os, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN = os.environ["BOT_TOKEN"]
CHAT = os.environ.get("ADMIN_CHAT", "-1004340727881")  # MCQ'S poll group (admins only)

with open(os.path.join(HERE, "report.txt"), encoding="utf-8") as f:
    text = f.read().strip()
data = {"chat_id": CHAT, "text": text[:4096], "parse_mode": "HTML", "disable_web_page_preview": "true"}
req = urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data=urllib.parse.urlencode(data).encode())
with urllib.request.urlopen(req, timeout=30) as r:
    res = json.load(r)
print("sendMessage", res.get("ok"), res.get("description", ""))
if not res.get("ok"):
    raise SystemExit(1)
