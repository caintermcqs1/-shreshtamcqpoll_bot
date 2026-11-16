"""Approval requests via Telegram.

Any new content / change that needs the user's OK is added to approvals/approvals.json with
status "new". This script (workflow 18) then:
  1. send  – posts each "new" request to the MCQ'S poll group with ✅ Approve / ❌ Reject buttons
             (first sends any "attachment_text" messages / repo "files", e.g. full MCQs or preview PDFs);
  2. poll  – reads button taps (getUpdates), records approved / rejected + who + when,
             edits the message to show the result, and runs the optional "on_approve" /
             "on_reject" workflow dispatch;
             a text reply to the request message is saved as a comment;
  3. remind – a request still pending after 24 h gets one reminder per day.
Claude sessions read approvals.json to see the decision before making anything live.
"""
import datetime as dt
import html
import json
import os
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(HERE, "approvals.json")
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
TOKEN = os.environ["BOT_TOKEN"]
GH_TOKEN = os.environ.get("GH_TOKEN", "")
REPO = os.environ.get("GITHUB_REPOSITORY", "caintermcqs1/-shreshtamcqpoll_bot")
CHAT = os.environ.get("APPROVAL_CHAT", "-1004340727881")  # MCQ'S poll group (admins only)
now = dt.datetime.now(IST)


def load():
    with open(DATA, encoding="utf-8") as f:
        return json.load(f)


def save(d):
    with open(DATA, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
        f.write("\n")


def api(method, **params):
    req = urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/{method}",
                                 data=json.dumps(params).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        res = json.loads(r.read())
    if not res.get("ok"):
        raise RuntimeError(f"{method}: {res}")
    return res["result"]


def send_file(path, caption, reply_to=None):
    boundary = "----apv" + now.strftime("%H%M%S%f")
    with open(os.path.join(ROOT, path), "rb") as f:
        content = f.read()
    parts = []
    fields = {"chat_id": CHAT, "caption": caption[:1000]}
    if reply_to:
        fields["reply_to_message_id"] = str(reply_to)
    for k, v in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    name = os.path.basename(path)
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="{name}"\r\n'
                 f'Content-Type: application/octet-stream\r\n\r\n'.encode() + content + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/sendDocument", data=b"".join(parts),
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())["result"]["message_id"]


def dispatch(action):
    if not action or not GH_TOKEN:
        return "no action"
    body = {"ref": "main"}
    if action.get("inputs"):
        body["inputs"] = action["inputs"]
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/actions/workflows/{action['workflow']}/dispatches",
        data=json.dumps(body).encode(), method="POST",
        headers={"Authorization": f"Bearer {GH_TOKEN}", "Accept": "application/vnd.github+json"})
    try:
        urllib.request.urlopen(req, timeout=30).read()
        return f"started {action['workflow']}"
    except Exception as e:
        return f"dispatch failed: {e}"


def esc(s):
    return html.escape(str(s), quote=False)


def request_text(it):
    lines = [f"🔔 <b>APPROVAL NEEDED</b> – #{esc(it['id'])}", f"<b>{esc(it['title'])}</b>"]
    if it.get("group"):
        lines.append(f"Group: {esc(it['group'])}")
    if it.get("goes_live"):
        lines.append(f"Goes live: {esc(it['goes_live'])}")
    lines.append("")
    lines += [esc(x) for x in it.get("details", [])]
    if it.get("if_rejected"):
        lines += ["", f"<i>If rejected: {esc(it['if_rejected'])}</i>"]
    lines += ["", "Tap ✅ Approve or ❌ Reject. To suggest a change, reply to this message."]
    return "\n".join(lines)[:4000]


def keyboard(it):
    return {"inline_keyboard": [[{"text": "✅ Approve", "callback_data": f"apv:{it['id']}:ok"},
                                 {"text": "❌ Reject", "callback_data": f"apv:{it['id']}:no"}]]}


def do_send(d):
    changed = False
    for it in d["items"]:
        if it.get("status") != "new":
            continue
        first = None
        for t in it.get("attachment_text", []):
            api("sendMessage", chat_id=CHAT, text=t[:4000], disable_web_page_preview=True)
        for p in it.get("files", []):
            try:
                mid = send_file(p, f"#{it['id']} – {os.path.basename(p)}")
                first = first or mid
            except Exception as e:
                print("File send failed", p, e)
        m = api("sendMessage", chat_id=CHAT, text=request_text(it), parse_mode="HTML",
                disable_web_page_preview=True, reply_markup=keyboard(it))
        it.update(status="pending", message_id=m["message_id"], sent_at=now.isoformat(timespec="minutes"),
                  last_reminder=now.date().isoformat())
        print("Sent request", it["id"])
        changed = True
    return changed


def is_admin(user_id):
    try:
        st = api("getChatMember", chat_id=CHAT, user_id=user_id)["status"]
        return st in ("creator", "administrator")
    except Exception as e:
        print("getChatMember failed", e)
        return False


def do_poll(d):
    changed = False
    offset = d.get("update_offset", 0)
    ups = api("getUpdates", offset=offset, timeout=0, allowed_updates=["callback_query", "message"])
    by_id = {it["id"]: it for it in d["items"]}
    by_msg = {it.get("message_id"): it for it in d["items"] if it.get("message_id")}
    for u in ups:
        offset = max(offset, u["update_id"] + 1)
        cq = u.get("callback_query")
        if cq and str(cq.get("data", "")).startswith("apv:"):
            _, iid, ans = cq["data"].split(":", 2)
            it = by_id.get(iid)
            who = cq["from"].get("first_name", "") + (" " + cq["from"].get("last_name", "")).rstrip()
            if not it:
                api("answerCallbackQuery", callback_query_id=cq["id"], text="Unknown request")
                continue
            if str(cq["message"]["chat"]["id"]) != CHAT or not is_admin(cq["from"]["id"]):
                api("answerCallbackQuery", callback_query_id=cq["id"], text="Only group admins can approve.")
                continue
            if it.get("status") in ("approved", "rejected"):
                api("answerCallbackQuery", callback_query_id=cq["id"], text=f"Already {it['status']}")
                continue
            ok = ans == "ok"
            it.update(status="approved" if ok else "rejected", decided_by=who,
                      decided_at=dt.datetime.now(IST).isoformat(timespec="minutes"))
            result = dispatch(it.get("on_approve") if ok else it.get("on_reject"))
            it["action_result"] = result
            mark = "✅ APPROVED" if ok else "❌ REJECTED"
            stamp = dt.datetime.now(IST).strftime("%d %b %I:%M %p")
            try:
                api("editMessageText", chat_id=CHAT, message_id=it["message_id"], parse_mode="HTML",
                    disable_web_page_preview=True,
                    text=request_text(it).rsplit("\n\nTap", 1)[0] + f"\n\n<b>{mark}</b> by {esc(who)} – {stamp}")
            except Exception as e:
                print("edit failed", e)
            api("answerCallbackQuery", callback_query_id=cq["id"], text=f"{mark} – noted")
            print(iid, it["status"], who, result)
            changed = True
            continue
        msg = u.get("message")
        if msg and str(msg["chat"]["id"]) == CHAT and msg.get("reply_to_message"):
            it = by_msg.get(msg["reply_to_message"]["message_id"])
            if it and msg.get("text"):
                who = msg["from"].get("first_name", "")
                it.setdefault("comments", []).append(
                    {"by": who, "at": dt.datetime.now(IST).isoformat(timespec="minutes"), "text": msg["text"]})
                api("sendMessage", chat_id=CHAT, reply_to_message_id=msg["message_id"],
                    text=f"📝 Comment saved for #{it['id']}. Claude will act on it in the next session.")
                changed = True
    if offset != d.get("update_offset", 0):
        d["update_offset"] = offset
        changed = True
    return changed


def do_remind(d):
    changed = False
    if not (9 <= now.hour < 21):
        return False
    for it in d["items"]:
        if it.get("status") != "pending" or it.get("last_reminder") == now.date().isoformat():
            continue
        api("sendMessage", chat_id=CHAT, reply_to_message_id=it["message_id"],
            text=f"⏰ Reminder: #{it['id']} is still waiting for approval – please tap ✅ or ❌ above.")
        it["last_reminder"] = now.date().isoformat()
        changed = True
    return changed


if __name__ == "__main__":
    d = load()
    c = do_send(d)
    c = do_poll(d) or c
    c = do_remind(d) or c
    if c:
        save(d)
    print("pending:", [i["id"] for i in d["items"] if i.get("status") == "pending"])
