#!/usr/bin/env python3
"""CA Inter Daily MCQ bot for Telegram.

Modes (first argument):
  post     - post today's case + 4 polls (runs 10:30 AM IST)
  answers  - close today's polls and post answers with % correct (runs ~1:50 PM IST)
  find-id  - list chats/topics the bot can see, to get CHAT_ID / TOPIC_ID
  preview  - print the next day's messages without sending anything
  reset    - start again from Day 1 (use after testing)

Settings come from environment variables (GitHub Secrets / Variables):
  BOT_TOKEN  (secret, required)   token from @BotFather
  CHAT_ID    (secret, required)   group id like -1001234567890
  TOPIC_ID   (optional)           topic (thread) id if the group uses Topics
"""
import html, json, os, sys, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
PLAN = os.path.join(HERE, "plan.json")
STATE = os.path.join(HERE, "state.json")
CONFIG = os.path.join(HERE, "config.json")
IST = timezone(timedelta(hours=5, minutes=30))
LETTERS = "ABCD"


def load(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def e(t):
    return html.escape(str(t), quote=False)


# ---------------------------------------------------------------- Telegram
def api(method, **params):
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        sys.exit("BOT_TOKEN is not set. Add it under Settings > Secrets and variables > Actions.")
    base = os.environ.get("TG_API", "https://api.telegram.org")
    body = json.dumps({k: v for k, v in params.items() if v is not None}).encode()
    req = urllib.request.Request(f"{base}/bot{token}/{method}", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            res = json.load(r)
    except urllib.error.HTTPError as err:
        res = json.load(err)
    if not res.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {res.get('description')}")
    return res["result"]


def target(day=None):
    chat = str((load(CONFIG, {}) or {}).get("chat_id") or os.environ.get("CHAT_ID", "")).strip()
    if not chat:
        sys.exit("CHAT_ID is not set. Run the 'Find group ID' workflow first.")
    topic = os.environ.get("TOPIC_ID", "").strip()
    thread = int(topic) if topic else None
    test = os.environ.get("TEST_CHAT", "").strip()
    if test:
        return {"chat_id": int(test), "message_thread_id": None}
    if day:
        topics = (load(CONFIG, {}) or {}).get("group_topics", {}).get(chat, {})
        if day.get("group") in topics:
            thread = int(topics[day["group"]])
    return {"chat_id": int(chat) if chat.lstrip("-").isdigit() else chat,
            "message_thread_id": thread}


# ---------------------------------------------------------------- formatting
NUM = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"]
SHORT = {"Advanced Accounting": "Accounts", "Corporate & Other Laws": "Law", "Taxation – Income Tax": "Income Tax",
         "Taxation – GST": "GST", "Cost & Management Accounting": "Costing", "Auditing & Ethics": "Audit",
         "Financial Management": "FM", "Strategic Management": "SM"}


def blocks_text(blocks):
    lines = []
    for b in blocks:
        if "p" in b:
            lines += ["", e(b["p"])]
        if "b" in b:
            lines += [""] + [f"• {e(x)}" for x in b["b"]]
        if "t" in b:
            head, rows = b["t"][0], b["t"][1:]
            lines.append("")
            for r in rows:
                cells = " · ".join(f"{e(h)} {e(c)}" for h, c in zip(head[1:], r[1:]))
                lines.append(f"▪️ <b>{e(r[0])}:</b> {cells}")
    return lines


QUIZ_LINE = "🎯 Quiz mode: vote once and see instantly if you are right – only you can see it. Tap 💡 for a hint of why."


def is_general(day):
    return day.get("kind") == "general"


def header_message(day, cfg):
    g = "🟦" if day["group"].endswith("1") else "🟩"
    subs = " · ".join(SHORT.get(x["subject"], x["subject"]) for x in day["items"])
    if is_general(day):
        return "\n".join([f"{g} <b>CA INTER DAILY MCQ – Day {day['day']} | {e(day['group'])} | General MCQs</b>",
                          f"📚 Today: {e(subs)}",
                          f"👇 4 quick MCQs – answer the polls below. ⏰ Full answers at {cfg['answer_time_label']}"]
                         + ([QUIZ_LINE] if cfg.get("quiz_mode") else []))
    return "\n".join([f"{g} <b>CA INTER DAILY MCQ – Day {day['day']} | {e(day['group'])}</b>",
                      f"📚 Today: {e(subs)}",
                      f"👇 4 mini-cases, each followed by its poll. ⏰ Full answers at {cfg['answer_time_label']}"]
                     + ([QUIZ_LINE] if cfg.get("quiz_mode") else []))


def item_message(i, it):
    lines = [f"{NUM[i]} <b>{e(it['subject'])}</b> – <i>{e(it['topic'])}</i>",
             f"<b>Case: {e(it['title'])}</b>"] + blocks_text(it["caseBlocks"])
    return "\n".join(lines)


def poll_question(i, it, general):
    if general:
        q = f"Q{i + 1} · {SHORT.get(it['subject'], it['subject'])}: {it['q']}"
    else:
        q = f"Q{i + 1}. {it['q']}"
    return q[:300]


def next_set_line(cfg):
    skip = cfg.get("skip_weekdays", []) if cfg else []
    d = today_ist() + timedelta(days=1)
    n = 1
    while d.strftime("%a") in skip and n < 7:
        d += timedelta(days=1)
        n += 1
    when = "tomorrow" if n == 1 else f"on {d.strftime('%A')}"
    return f"🔥 Next set {when} at 10:30 AM. Keep practising!"


def answer_message(day, results, cfg=None):
    tag = " | General MCQs" if is_general(day) else ""
    lines = [f"✅ <b>ANSWERS – Day {day['day']} | {e(day['group'])}{tag}</b>"]
    for i, q in enumerate(day["items"]):
        r = results[i] if i < len(results) else None
        stat = ""
        if r and r["total"]:
            pct = round(100 * r["correct"] / r["total"])
            stat = f"  ({pct}% correct · {r['total']} votes)"
        lines += ["",
                  f"{NUM[i]} <b>{e(SHORT.get(q['subject'], q['subject']))}: {LETTERS[q['ans']]}) {e(q['o'][q['ans']])}</b>{e(stat)}",
                  f"<b>Why:</b> {e(q['why'])}",
                  f"⚠️ <b>Trap:</b> <i>{e(q['trap'])}</i>"]
        if q.get("source"):
            lines.append(f"📖 <b>Reference:</b> <i>{e(q['source'])}</i>")
    lines += ["", next_set_line(cfg)]
    return "\n".join(lines)


def split_message(text, limit=4000):
    if len(text) <= limit:
        return [text]
    parts, cur = [], ""
    for block in text.split("\n\n"):
        if len(cur) + len(block) + 2 > limit and cur:
            parts.append(cur)
            cur = block
        else:
            cur = f"{cur}\n\n{block}" if cur else block
    parts.append(cur)
    return parts


# ---------------------------------------------------------------- modes
def today_ist():
    return datetime.now(IST)


def next_day(plan, state):
    idx = state.get("next_index", 0)
    return (idx, plan[idx]) if idx < len(plan) else (idx, None)


def todays_sets(plan, idx):
    """All consecutive plan entries sharing the same day number (e.g. Group 1 + Group 2) are posted together."""
    out = []
    while idx < len(plan) and (not out or plan[idx].get("day") == out[0][1].get("day")):
        out.append((idx, plan[idx]))
        idx += 1
    return out


def post_set(idx, day, cfg):
    general = is_general(day)

    def send_to(t, pin):
        head = api("sendMessage", **t, text=header_message(day, cfg), parse_mode="HTML")
        polls = []
        for i, it in enumerate(day["items"]):
            if not general:
                api("sendMessage", **t, text=item_message(i, it), parse_mode="HTML", disable_web_page_preview=True)
            quiz = {}
            if cfg.get("quiz_mode"):
                quiz = {"type": "quiz", "correct_option_id": it["ans"],
                        "explanation": (it.get("exp") or "")[:200] or None}
            pm = api("sendPoll", **t, question=poll_question(i, it, general),
                     options=[{"text": o} for o in it["o"]], is_anonymous=cfg.get("anonymous_polls", True),
                     allows_multiple_answers=False, **quiz)
            polls.append(pm["message_id"])
        if pin and cfg.get("pin_case", True):
            try:
                api("pinChatMessage", chat_id=t["chat_id"], message_id=head["message_id"], disable_notification=True)
            except RuntimeError as err:
                print(f"Could not pin (give the bot 'Pin messages' permission): {err}")
        return head["message_id"], polls

    head_id, polls = send_to(target(day), True)
    rec = {"index": idx, "case_message_id": head_id, "poll_message_ids": polls, "mirrors": []}
    if not os.environ.get("TEST_CHAT", "").strip():
        for m in cfg.get("mirrors", []):
            mt = {"chat_id": int(m["chat_id"]), "message_thread_id": m.get("thread")}
            try:
                h2, p2 = send_to(mt, False)
                rec["mirrors"].append({"chat_id": mt["chat_id"], "thread": mt["message_thread_id"],
                                       "case_message_id": h2, "poll_message_ids": p2})
                print(f"Mirrored to {mt['chat_id']} / topic {mt['message_thread_id']}")
            except RuntimeError as err:
                print(f"Mirror post failed ({m}): {err}")
    return rec


def do_post():
    cfg, plan = load(CONFIG), load(PLAN)
    state = load(STATE, {"next_index": 0, "pending": None, "history": []})
    now = today_ist()
    date = now.strftime("%Y-%m-%d")
    if now.strftime("%a") in cfg.get("skip_weekdays", []):
        print(f"{date}: skip day ({now.strftime('%A')}). Nothing posted.")
        return
    if state.get("last_post_date") == date:
        print(f"{date}: already posted today. Nothing to do.")
        return
    if state.get("pending"):
        print("Previous day's answers were not posted yet. Posting them first.")
        do_answers()
        state = load(STATE)
    idx, day = next_day(plan, state)
    if day is None:
        print("All days in plan.json have been posted. Add more days to continue.")
        return
    sets = []
    for i, d in todays_sets(plan, idx):
        try:
            sets.append(post_set(i, d, cfg))
            print(f"{date}: posted Day {d['day']} ({d['group']}, {d.get('kind', 'case')}) – {len(d['items'])} polls.")
        except RuntimeError as err:
            print(f"{date}: could not post Day {d['day']} ({d['group']}): {err}")
            if not sets:
                raise
            break
    state.update(last_post_date=date, pending={"date": date, "sets": sets})
    save(STATE, state)


def pending_sets(p):
    if "sets" in p:
        return p["sets"]
    return [{"index": p["index"], "case_message_id": p["case_message_id"], "poll_message_ids": p["poll_message_ids"]}]


def do_answers():
    cfg, plan = load(CONFIG), load(PLAN)
    state = load(STATE, {"next_index": 0, "pending": None, "history": []})
    p = state.get("pending")
    if not p:
        print("No open polls. Nothing to do.")
        return
    last = state.get("next_index", 0) - 1
    for s in pending_sets(p):
        day = plan[s["index"]]
        t = target(day)
        results = []
        for i, mid in enumerate(s["poll_message_ids"]):
            try:
                poll = api("stopPoll", chat_id=t["chat_id"], message_id=mid)
                opts = poll["options"]
                results.append({"total": poll.get("total_voter_count", 0),
                                "correct": opts[day["items"][i]["ans"]]["voter_count"]})
            except RuntimeError as err:
                print(f"Could not close poll {mid}: {err}")
                results.append(None)
        for part in split_message(answer_message(day, results, cfg)):
            api("sendMessage", **t, text=part, parse_mode="HTML", disable_web_page_preview=True,
                reply_parameters={"message_id": s["case_message_id"], "allow_sending_without_reply": True})
        for mr in s.get("mirrors", []):
            mt = {"chat_id": mr["chat_id"], "message_thread_id": mr.get("thread")}
            mres = []
            for i, mid in enumerate(mr["poll_message_ids"]):
                try:
                    poll = api("stopPoll", chat_id=mt["chat_id"], message_id=mid)
                    mres.append({"total": poll.get("total_voter_count", 0),
                                 "correct": poll["options"][day["items"][i]["ans"]]["voter_count"]})
                except RuntimeError as err:
                    print(f"Could not close mirror poll {mid}: {err}")
                    mres.append(None)
            try:
                for part in split_message(answer_message(day, mres, cfg)):
                    api("sendMessage", **mt, text=part, parse_mode="HTML", disable_web_page_preview=True,
                        reply_parameters={"message_id": mr["case_message_id"], "allow_sending_without_reply": True})
            except RuntimeError as err:
                print(f"Mirror answers failed ({mt}): {err}")
        state.setdefault("history", []).append({"date": p["date"], "day": day["day"], "group": day["group"],
                                                "kind": day.get("kind", "case"), "results": results})
        last = max(last, s["index"])
        print(f"Posted answers for Day {day['day']} ({day['group']}).")
    state["next_index"] = last + 1
    state["pending"] = None
    save(STATE, state)


def do_test():
    """Send the next MCQ day (quiz mode) plus announce.txt to TEST_CHAT only. Saves nothing."""
    cfg, plan = load(CONFIG), load(PLAN)
    state = load(STATE, {"next_index": 0})
    if not os.environ.get("TEST_CHAT", "").strip():
        sys.exit("TEST_CHAT is not set.")
    ann = os.path.join(HERE, "announce.txt")
    if os.path.exists(ann):
        with open(ann, encoding="utf-8") as f:
            api("sendMessage", **target(), text=f.read().strip(), parse_mode="HTML")
    idx = state.get("next_index", 0)
    if state.get("pending"):
        idx = max(s["index"] for s in (state["pending"].get("sets") or [state["pending"]])) + 1
    for i, d in todays_sets(plan, idx):
        post_set(i, d, dict(cfg, pin_case=False))
        print(f"Test: sent Day {d['day']} ({d['group']}, {d.get('kind', 'case')})")


def do_find_id():
    updates = api("getUpdates", offset=-100, allowed_updates=["message", "my_chat_member", "channel_post"])
    seen = {}
    topics = {}
    for u in updates:
        msg = u.get("message") or u.get("channel_post") or (u.get("my_chat_member") or {})
        chat = msg.get("chat")
        if not chat:
            continue
        key = (chat["id"], msg.get("message_thread_id"))
        seen[key] = (chat.get("title") or chat.get("first_name") or "", chat.get("type"))
        ft = msg.get("forum_topic_created") or (msg.get("reply_to_message") or {}).get("forum_topic_created")
        if ft and key[1]:
            topics[key[1]] = ft.get("name")
    if not seen:
        print("No chats found. Send '/start' to the bot in private chat AND send any message in the group, "
              "then run this again within 24 hours.")
        return
    print("Chats the bot can see:")
    for (cid, thread), (name, typ) in seen.items():
        extra = f"   TOPIC_ID = {thread}  topic: {topics.get(thread, '?')}" if thread else ""
        print(f"  {typ:10} {name!r:40} CHAT_ID = {cid}{extra}")


def do_preview():
    cfg, plan = load(CONFIG), load(PLAN)
    state = load(STATE, {"next_index": 0})
    _, day = next_day(plan, state)
    if not day:
        print("No more days in plan.json.")
        return
    for _, day in todays_sets(plan, state.get("next_index", 0)):
        print(header_message(day, cfg))
        for i, it in enumerate(day["items"]):
            if not is_general(day):
                print("\n" + item_message(i, it))
            print(f"[POLL] {poll_question(i, it, is_general(day))}")
            for j, o in enumerate(it["o"]):
                print(f"   {LETTERS[j]}) {o}")
        print("\n" + answer_message(day, [], cfg) + "\n")


def do_reset():
    save(STATE, {"next_index": 0, "pending": None, "history": []})
    print("Progress reset. The next run will post Day 1.")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "preview"
    {"post": do_post, "answers": do_answers, "test": do_test, "find-id": do_find_id, "preview": do_preview, "reset": do_reset}[mode]()
