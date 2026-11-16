"""Backup PDF of everything the bots posted (CA Inter + CMA Inter) for a date range.

Usage: python backup/make_backup.py START END [--send]
  START/END = YYYY-MM-DD (IST dates, inclusive) or 'today' / 'week' (Mon–Sat of the current week) / 'all'.
  --send  posts the PDF to the MCQ'S poll test group (admins) with sendDocument.
Rebuilt from the bots' own data + state files, so it shows exactly what each post contained.
"""
import datetime as dt, html, json, os, re, sys, urllib.request, uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
ALERT_CHAT = os.environ.get("ALERT_CHAT", "-1004340727881")
FIRST_DAY = dt.date(2026, 11, 10)
L = "ABCD"


def load(rel, default=None):
    try:
        with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return default


# ---------------------------------------------------------------- text cleaning for the PDF font
KEEP = set("₹–—‘’“”•…→←≈×÷−√≤≥✓²³°½¼¾§©®™€£·")


def clean(s):
    s = str(s).replace("️", "").replace("✅", "✓").replace("✔", "✓")
    return "".join(ch for ch in s if ord(ch) < 0x2000 or ch in KEEP).strip()


def esc(s):
    return html.escape(clean(s), quote=False)


def from_html(s):
    """Telegram HTML -> reportlab mini-markup (keep b/i, line breaks)."""
    s = clean(s)
    s = re.sub(r"<(?!/?(b|i)>)[^>]+>", "", s)
    s = s.replace("\n", "<br/>")
    return re.sub(r"^(<br/>)+", "", s)


# ---------------------------------------------------------------- data
def plan_entry(plan, day, group):
    return next((p for p in plan if p.get("day") == day and p.get("group") == group), None)


def mcq_sets(folder, d):
    st, plan = load(f"{folder}/state.json", {}), load(f"{folder}/plan.json", [])
    out = []
    for h in st.get("history", []):
        if h.get("date") == d:
            e = plan_entry(plan, h["day"], h["group"])
            if e:
                out.append((e, h.get("results", []), True))
    p = st.get("pending") or {}
    if p.get("date") == d:
        for s in p.get("sets", []):
            if s["index"] < len(plan):
                out.append((plan[s["index"]], [], False))
    return out


def ca_fact_tip_by_date():
    """CA 6 PM posts. The bot keeps counters only, so replay its rule: from 11 Nov, Mon–Sat, both topics,
    Study Tip one day and Fun Fact the next (10 Nov: one Group 1 tip). Checked against the saved counters."""
    ex = load("ca-inter-mcq-bot/extras_state.json", {})
    facts, tips = load("ca-inter-mcq-bot/facts.json", []), load("ca-inter-mcq-bot/tips.json", [])
    last = ex.get("last_fact_date")
    res, cnt = {}, {"tip_g1": 1, "tip_g2": 0, "fact_g1": 0, "fact_g2": 0}
    pool = lambda kind, grp: [f for f in (facts if kind == "fact" else tips) if f.get("group") == grp]
    t0 = pool("tip", "Group 1")
    if t0:
        res["2026-11-10"] = [("Group 1", "tip", t0[0])]
    d, step = dt.date(2026, 11, 11), 0
    while last and d.isoformat() <= last:
        if d.weekday() != 6:
            kind = "tip" if step % 2 == 0 else "fact"
            for grp, g in (("Group 1", "g1"), ("Group 2", "g2")):
                pl = pool(kind, grp)
                if pl:
                    k = f"{kind}_{g}"
                    res.setdefault(d.isoformat(), []).append((grp, kind, pl[cnt[k] % len(pl)]))
                    cnt[k] += 1
            step += 1
        d += dt.timedelta(days=1)
    ok = (cnt["tip_g1"] == ex.get("tip_index_g1", cnt["tip_g1"]) and cnt["tip_g2"] == ex.get("tip_index_g2", cnt["tip_g2"])
          and cnt["fact_g1"] == ex.get("fact_index_g1", cnt["fact_g1"]) and cnt["fact_g2"] == ex.get("fact_index_g2", cnt["fact_g2"]))
    return res, ok


# ---------------------------------------------------------------- PDF
def build(start, end, path):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, KeepTogether

    fd = "/usr/share/fonts/truetype/dejavu/"
    pdfmetrics.registerFont(TTFont("DV", fd + "DejaVuSans.ttf"))
    pdfmetrics.registerFont(TTFont("DVB", fd + "DejaVuSans-Bold.ttf"))
    pdfmetrics.registerFont(TTFont("DVI", fd + "DejaVuSans-Oblique.ttf"))
    pdfmetrics.registerFont(TTFont("DVBI", fd + "DejaVuSans-BoldOblique.ttf"))
    pdfmetrics.registerFontFamily("DV", normal="DV", bold="DVB", italic="DVI", boldItalic="DVBI")
    NAVY, TEAL, GREY = colors.HexColor("#1F3A5F"), colors.HexColor("#0F766E"), colors.HexColor("#5B6470")
    S = lambda n, **k: ParagraphStyle(n, **({"fontName": "DV", "fontSize": 9, "leading": 12.5} | k))
    st = {"title": S("t", fontSize=20, leading=26, textColor=NAVY, fontName="DVB"),
          "sub": S("s", fontSize=10.5, textColor=GREY),
          "date": S("d", fontSize=15, leading=20, textColor=colors.white, fontName="DVB"),
          "course": S("c", fontSize=12.5, leading=17, textColor=NAVY, fontName="DVB", spaceBefore=8, spaceAfter=3),
          "slot": S("sl", fontSize=10.5, leading=14, textColor=TEAL, fontName="DVB", spaceBefore=6, spaceAfter=2),
          "body": S("b"), "small": S("sm", fontSize=8, leading=11, textColor=GREY),
          "q": S("q", fontName="DVB", spaceBefore=4), "opt": S("o", leftIndent=10),
          "case": S("ca", leftIndent=6, textColor=colors.HexColor("#333333"))}
    P = lambda t, s="body": Paragraph(t, st[s])

    def date_bar(d):
        t = Table([[P(d.strftime("%A, %d %B %Y"), "date")]], colWidths=[180 * mm])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NAVY), ("LEFTPADDING", (0, 0), (-1, -1), 8),
                               ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        return t

    def mcq_block(e, results, closed):
        out = [P(f"{esc(e['group'])} – {'General MCQs' if e.get('kind') == 'general' else 'Mini-case MCQs'} (Day {e['day']})", "slot")]
        for i, it in enumerate(e["items"]):
            blk = [P(f"Q{i + 1}. {esc(it['subject'])} – <i>{esc(it['topic'])}</i>", "q")]
            if it.get("caseBlocks"):
                if it.get("title"):
                    blk.append(P(f"<b>Case: {esc(it['title'])}</b>", "case"))
                for b in it["caseBlocks"]:
                    if "p" in b:
                        blk.append(P(esc(b["p"]), "case"))
                    for x in b.get("b", []):
                        blk.append(P("• " + esc(x), "case"))
                    if "t" in b:
                        head = b["t"][0]
                        for r in b["t"][1:]:
                            blk.append(P("▪ <b>" + esc(r[0]) + ":</b> " + " · ".join(f"{esc(h)} {esc(c)}" for h, c in zip(head[1:], r[1:])), "case"))
            blk.append(P(esc(it["q"])))
            for k, o in enumerate(it["o"]):
                mark = "  ✓" if k == it["ans"] else ""
                blk.append(P(f"{L[k]}) {'<b>' if mark else ''}{esc(o)}{mark}{'</b>' if mark else ''}", "opt"))
            r = results[i] if i < len(results) else None
            res = (f" · Poll: {round(100 * r['correct'] / r['total'])}% correct ({r['total']} votes)" if r and r.get("total")
                   else ("" if closed else " · Poll still open (answers at 8:30 PM)"))
            blk.append(P(f"<b>Answer: {L[it['ans']]}</b>{esc(res)}"))
            blk.append(P(f"<b>Why:</b> {esc(it.get('why', ''))}"))
            if it.get("trap"):
                blk.append(P(f"<b>Trap:</b> <i>{esc(it['trap'])}</i>"))
            if it.get("source"):
                blk.append(P(f"Reference: {esc(it['source'])}", "small"))
            out.append(KeepTogether(blk))
        return out

    ca_study = load("ca-inter-mcq-bot/study.json", {})
    ex = load("ca-inter-mcq-bot/extras_state.json", {})
    ca_ft, ft_ok = ca_fact_tip_by_date()
    cdc = load("cma-inter-mcq-bot/cma_daily_content.json", {})
    done = load("cma-inter-mcq-bot/cma_daily_state.json", {}).get("done", {})
    os.environ.setdefault("BOT_TOKEN", "x")
    sys.path.insert(0, os.path.join(ROOT, "cma-inter-mcq-bot"))
    import cma_daily

    story = [P("SHRESHTA – Daily Posts Backup", "title"),
             P(f"CA Inter ENROLLED Students Group + CMA Inter ENROLLED Course Students · {start:%d %b %Y} – {end:%d %b %Y}", "sub"),
             P(f"Generated {dt.datetime.now(IST):%d %b %Y, %I:%M %p} IST. MCQs with correct answers, explanations and poll results; "
               "4 PM study posts; 6 PM tips/facts; CMA countdown and 9 PM posts. (ICAI / YouTube update links and promotions are not included.)", "small"),
             Spacer(1, 6)]
    n_days = 0
    d = start
    while d <= end:
        ds = d.isoformat()
        ca_sets, cma_sets = mcq_sets("ca-inter-mcq-bot", ds), mcq_sets("cma-inter-mcq-bot", ds)
        ca_s = ca_study.get(ds) if ds <= (ex.get("study_last_date") or "") else None
        cma_items = [(m, g) for m in ("countdown", "study", "fact", "night", "recap") for g in ("g1", "g2") if f"{ds}:{m}:{g}" in done]
        if not (ca_sets or ca_s or ca_ft.get(ds) or cma_sets or cma_items):
            d += dt.timedelta(days=1)
            continue
        if n_days:
            story.append(PageBreak())
        n_days += 1
        story += [date_bar(d), Spacer(1, 4)]
        # ---- CA Inter
        if ca_sets or ca_s or ca_ft.get(ds):
            story.append(P("CA INTER", "course"))
            if ca_sets:
                story.append(P("10:30 AM – MCQ polls (answers posted at 8:30 PM)", "slot"))
                for e, r, c in ca_sets:
                    story += mcq_block(e, r, c)
            if ca_s:
                story.append(P("4:00 PM – Study content", "slot"))
                for g, grp in (("g1", "Group 1"), ("g2", "Group 2")):
                    p = ca_s.get(g)
                    if p:
                        story.append(P(f"<b>{grp} · {esc(p.get('format', ''))} – {esc(p.get('subject', ''))}</b>"))
                        story.append(P(f"<b>{esc(p.get('title', ''))}</b><br/>" + esc(p.get("body", "")).replace("\n", "<br/>")))
                        if p.get("link"):
                            story.append(P(esc(p["link"]), "small"))
            if ca_ft.get(ds):
                story.append(P("6:00 PM – Study Tip / Fun Fact", "slot"))
                for grp, kind, f in ca_ft[ds]:
                    story.append(P(f"<b>{grp} · {'Study Tip' if kind == 'tip' else 'Fun Fact'} – {esc(f.get('subject', ''))}: {esc(f['title'])}</b>"))
                    txt = esc(f["text"]) + (f"<br/>Link to syllabus: {esc(f['link'])}" if f.get("link") else "") + \
                        (f"<br/><i>Source: {esc(f['source'])}</i>" if f.get("source") else "")
                    story.append(P(txt))
                if not ft_ok:
                    story.append(P("(6 PM list rebuilt from the bot's counters – please cross-check in the group.)", "small"))
        # ---- CMA Inter
        if cma_sets or cma_items:
            story.append(P("CMA INTER", "course"))
            labels = {"countdown": "9:00 AM – Countdown", "study": "4:00 PM – Study content", "fact": "6:00 PM – Fun Fact / Study Tip",
                      "night": "9:00 PM – Concept + Formula / Section of the Day", "recap": "9:30 PM – Weekly recap"}

            def daily(mode):
                if not any(m == mode for m, _ in cma_items):
                    return
                story.append(P(labels[mode], "slot"))
                for m, g in cma_items:
                    if m != mode:
                        continue
                    if m == "countdown":
                        c = cdc.get("countdown", {}).get(ds)
                        txt = cma_daily.countdown_text(g, c, d) if c else None
                    elif m == "recap":
                        txt = cma_daily.recap_text(g, d)
                    else:
                        txt = cdc.get(m, {}).get(ds, {}).get(g)
                    if txt:
                        story.append(P(f"<b>{'Group 1' if g == 'g1' else 'Group 2'}</b><br/>" + from_html(txt)))
            daily("countdown")
            if cma_sets:
                story.append(P("10:30 AM – MCQ polls (answers posted at 8:30 PM)", "slot"))
                for e, r, c in cma_sets:
                    story += mcq_block(e, r, c)
            for mode in ("study", "fact", "night", "recap"):
                daily(mode)
        d += dt.timedelta(days=1)
    if not n_days:
        story.append(P("No posts in this period (Sunday / holiday).", "body"))

    def footer(c, doc):
        c.saveState()
        c.setFont("DV", 7.5)
        c.setFillColor(GREY)
        c.drawString(15 * mm, 9 * mm, f"Daily posts backup · {start:%d %b} – {end:%d %b %Y}")
        c.drawRightString(195 * mm, 9 * mm, f"Page {doc.page}")
        c.restoreState()

    SimpleDocTemplate(path, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm, bottomMargin=16 * mm,
                      title="Daily Posts Backup", author="SHRESHTA").build(story, onFirstPage=footer, onLaterPages=footer)
    return n_days


def send_document(path, caption):
    token = os.environ["BOT_TOKEN"]
    b = uuid.uuid4().hex
    with open(path, "rb") as f:
        data = f.read()
    parts = []
    for k, v in (("chat_id", ALERT_CHAT), ("caption", caption)):
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append(f'--{b}\r\nContent-Disposition: form-data; name="document"; filename="{os.path.basename(path)}"\r\n'
                 f"Content-Type: application/pdf\r\n\r\n".encode() + data + b"\r\n")
    parts.append(f"--{b}--\r\n".encode())
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendDocument", data=b"".join(parts),
                                 headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        print("sendDocument:", json.load(r).get("ok"))


def parse(a, today):
    if a == "today":
        return today
    if a == "all":
        return FIRST_DAY
    return dt.date.fromisoformat(a)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    today = dt.datetime.now(IST).date()
    if args and args[0] == "week":
        end = today
        start = today - dt.timedelta(days=today.weekday())
    else:
        start = parse(args[0] if args else "today", today)
        end = parse(args[1], today) if len(args) > 1 else (today if args and args[0] == "all" else start)
    name = (f"Daily_Posts_Backup_{start:%d%b%Y}.pdf" if start == end else f"Daily_Posts_Backup_{start:%d%b}-{end:%d%b%Y}.pdf")
    out = os.path.join(os.environ.get("OUT_DIR", "."), name)
    n = build(start, end, out)
    print("Built", out, "days:", n)
    if "--send" in sys.argv:
        label = start.strftime("%d %b %Y") if start == end else f"{start:%d %b} – {end:%d %b %Y}"
        send_document(out, f"Backup of all posts – {label} (CA Inter + CMA Inter). Save this file.")
