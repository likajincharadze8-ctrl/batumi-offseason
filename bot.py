"""Batumi Off-Season - prototype AI career & benefits navigator (Telegram).
Prototype only: demo knowledge base, in-memory storage. Not for real personal data."""
import json, os, re, io, threading, time, logging, asyncio
from collections import defaultdict
from flask import Flask
from openai import OpenAI
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Application, CommandHandler, MessageHandler, ContextTypes, filters,
                          ConversationHandler, CallbackQueryHandler)
from docx import Document
from docx.shared import Pt, RGBColor, Cm
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

logging.basicConfig(level=logging.INFO)
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ADVISOR_CHAT_ID = os.environ.get("ADVISOR_CHAT_ID")  # Telegram chat that plays "City Hall advisor" in the demo
# Free option: Google Gemini (key from aistudio.google.com, no card). Paid option: OpenAI.
if os.environ.get("GEMINI_API_KEY"):
    client = OpenAI(api_key=os.environ["GEMINI_API_KEY"],
                    base_url="https://generativelanguage.googleapis.com/v1beta/openai/")
    MODEL = os.environ.get("MODEL", "gemini-2.5-flash")
else:
    client = OpenAI()  # reads OPENAI_API_KEY
    MODEL = os.environ.get("MODEL", "gpt-4o-mini")
KB = json.load(open(os.path.join(os.path.dirname(__file__), "knowledge_base.json"), encoding="utf-8"))

SYSTEM = f"""You are "Batumi Off-Season", a free AI career and benefits navigator piloted with Batumi City Hall.
You help Batumi residents, especially seasonal tourism workers who lost income after the summer season,
find jobs, training and support programs.

RULES
- Reply in the user's language (Georgian, Russian or English). Short, warm, plain language. Use short lists.
- First understand the person: ask at most 3 short questions, one at a time (current/last job, skills and languages,
  constraints such as childcare, schedule, district). Do not ask for ID numbers or other sensitive data.
- Then give: (1) a short skills profile, (2) 2-3 job ideas, (3) 1-2 training options, (4) support programs they MAY qualify for.
- Use ONLY the programs in the knowledge base below. Name the source for each program. Never invent programs, amounts or rules.
- Eligibility is always PRELIMINARY: say a City Hall advisor or the program confirms it.
- Job listings in the knowledge base are samples for the demo - say so.
- If unsure, or the person is in crisis, suggest talking to a City Hall advisor (/advisor).
- Mention once that they are talking to an AI, and that /cv makes a CV and /advisor books an advisor.

KNOWLEDGE BASE (verified with City Hall in the real pilot; demo data now):
{json.dumps(KB, ensure_ascii=False)}
"""

history = defaultdict(list)      # chat_id -> messages (in memory only)
stats = defaultdict(int)         # anonymized counters for the dashboard
advisor_requests = []            # anonymized: timestamp + language only
lang_of = {}

KEYS = ReplyKeyboardMarkup([["ქართული", "Русский", "English"]], one_time_keyboard=True, resize_keyboard=True)
WELCOME = {
    "ქართული": "გამარჯობა! მე ვარ „Batumi Off-Season“ — AI ასისტენტი, რომელიც დაგეხმარება სამუშაოს, კურსების და მხარდაჭერის პროგრამების პოვნაში. მომიყევი შენი სიტუაციის შესახებ: სად მუშაობდი და რა ხდება ახლა?",
    "Русский": "Здравствуйте! Я «Batumi Off-Season» — ИИ-помощник, который поможет найти работу, курсы и программы поддержки в Батуми. Расскажите, где вы работали и что происходит сейчас?",
    "English": "Hi! I'm Batumi Off-Season, an AI assistant that helps you find jobs, courses and support programs in Batumi. Tell me where you worked and what's happening now.",
}

def ask_llm(chat_id, extra=None):
    msgs = [{"role": "system", "content": SYSTEM}] + history[chat_id][-20:]
    if extra:
        msgs.append({"role": "user", "content": extra})
    r = client.chat.completions.create(model=MODEL, messages=msgs)
    return r.choices[0].message.content

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    history.pop(update.effective_chat.id, None)
    stats["conversations_started"] += 1
    await update.message.reply_text("აირჩიე ენა / Выберите язык / Choose a language", reply_markup=KEYS)

async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid, text = update.effective_chat.id, update.message.text
    if text in WELCOME:
        lang_of[cid] = text
        stats[f"lang_{text}"] += 1
        await update.message.reply_text(WELCOME[text])
        return
    history[cid].append({"role": "user", "content": text})
    stats["messages"] += 1
    await ctx.bot.send_chat_action(cid, "typing")
    try:
        answer = await asyncio.to_thread(ask_llm, cid)
    except Exception as e:
        logging.exception(e)
        answer = "Sorry, a technical problem. Please try again or use /advisor."
    history[cid].append({"role": "assistant", "content": answer})
    await update.message.reply_text(answer)

# ---------- /cv : short Q&A, then a Word CV file ----------
CV_NAME, CV_PHONE, CV_TARGET, CV_EXP, CV_EDU = range(5)
CVQ = {
 "ქართული": ["რეზიუმესთვის 5 მოკლე კითხვა 📝\n1/5. შენი სახელი და გვარი?",
             "2/5. ტელეფონი და/ან ელფოსტა?",
             "3/5. რა სამუშაოს ეძებ? მაგ.: „ადმინისტრატორი სასტუმროში“",
             "4/5. სამუშაო გამოცდილება: სად, ვინ და რომელ წლებში + რას აკეთებდი. მაგ.: „კაფე X, ოფიციანტი, 2023–2026, ვემსახურებოდი 40 მაგიდას, ვმუშაობდი სალაროსთან“",
             "5/5. განათლება ან კურსები (თუ გაქვს). თუ არა, დაწერე „არა“."],
 "Русский": ["5 коротких вопросов для резюме 📝\n1/5. Ваше имя и фамилия?",
             "2/5. Телефон и/или email?",
             "3/5. Какую работу вы ищете? Например: «администратор в отеле»",
             "4/5. Опыт работы: где, кем, в какие годы + чем занимались.",
             "5/5. Образование или курсы (если есть). Если нет, напишите «нет»."],
 "English": ["5 short questions for your CV 📝\n1/5. Your full name?",
             "2/5. Phone and/or email?",
             "3/5. What job are you looking for? E.g. 'hotel receptionist'",
             "4/5. Work experience: where, what role, which years + what you did.",
             "5/5. Education or courses (if any). If none, write 'none'."],
}
def L(cid): return lang_of.get(cid, "ქართული")

async def cv_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["cv"] = {}
    await update.message.reply_text(CVQ[L(update.effective_chat.id)][0])
    return CV_NAME

def cv_step(key, nxt, qi):
    async def h(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        ctx.user_data["cv"][key] = update.message.text
        await update.message.reply_text(CVQ[L(update.effective_chat.id)][qi])
        return nxt
    return h

def parse_json(txt):
    m = re.search(r"\{.*\}", txt, re.S)
    return json.loads(m.group(0)) if m else {}

ACCENT = RGBColor(0x0B, 0x4F, 0x6C); GREY = RGBColor(0x59, 0x59, 0x59)

def _bottom_border(p):
    pPr = p._p.get_or_add_pPr(); bdr = OxmlElement("w:pBdr"); b = OxmlElement("w:bottom")
    for k, v in (("w:val", "single"), ("w:sz", "8"), ("w:space", "2"), ("w:color", "0B4F6C")): b.set(qn(k), v)
    bdr.append(b); pPr.append(bdr)

def _run(p, text, size=11, bold=False, italic=False, color=None):
    r = p.add_run(text); r.font.size = Pt(size); r.bold = bold; r.italic = italic
    r.font.name = "Segoe UI"; r._element.rPr.rFonts.set(qn("w:cs"), "Segoe UI")
    if color: r.font.color.rgb = color
    return r

def _para(doc, before=0, after=4):
    p = doc.add_paragraph(); p.paragraph_format.space_before = Pt(before); p.paragraph_format.space_after = Pt(after); return p

def build_docx(d):
    doc = Document()
    for sec in doc.sections:
        sec.top_margin = sec.bottom_margin = Cm(1.6); sec.left_margin = sec.right_margin = Cm(1.9)
    _run(_para(doc, 0, 0), d.get("name", ""), 24, bold=True, color=ACCENT)
    if d.get("title"): _run(_para(doc, 0, 2), d["title"], 13, color=GREY)
    p = _para(doc, 0, 10); _run(p, d.get("contact", ""), 10, color=GREY); _bottom_border(p)

    def heading(t):
        h = _para(doc, 10, 4); _run(h, t.upper() if t.isascii() else t, 12.5, bold=True, color=ACCENT); _bottom_border(h)
    def bullet(t):
        p = doc.add_paragraph(style="List Bullet"); p.paragraph_format.space_after = Pt(2); _run(p, t, 10.5)

    if d.get("summary"):
        heading(d.get("h_summary", "Profile")); _run(_para(doc, 0, 4), d["summary"], 10.5)
    if d.get("skills"):
        heading(d.get("h_skills", "Key skills")); _run(_para(doc, 0, 4), "  •  ".join(d["skills"]), 10.5)
    if d.get("experience"):
        heading(d.get("h_experience", "Experience"))
        for e in d["experience"]:
            p = _para(doc, 6, 0); _run(p, e.get("role", ""), 11.5, bold=True)
            p = _para(doc, 0, 2); _run(p, f"{e.get('place','')}  |  {e.get('period','')}", 10, italic=True, color=GREY)
            for t in e.get("bullets", []): bullet(t)
    if d.get("education"):
        heading(d.get("h_education", "Education"))
        for t in d["education"]: bullet(t)
    if d.get("languages"):
        heading(d.get("h_languages", "Languages")); _run(_para(doc, 0, 4), "  •  ".join(d["languages"]), 10.5)
    buf = io.BytesIO(); doc.save(buf); buf.seek(0); return buf

async def cv_finish(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    ctx.user_data["cv"]["education"] = update.message.text
    stats["cvs_drafted"] += 1
    await ctx.bot.send_chat_action(cid, "upload_document")
    await update.message.reply_text("⏳ ...")
    prompt = ("You are a professional CV writer. Create a strong, attractive one-page CV as JSON only (no other text), "
              "written in this language: " + L(cid) + ". "
              "STRICT: never invent employers, job titles, dates, degrees or numbers that the person did not give. "
              "You MAY describe the typical duties and transferable skills of the roles they did hold, in confident, "
              "professional, action-verb language, and tailor everything to their target job. "
              "JSON keys: name; title (the target job as a headline); contact; "
              "summary (3-4 sentences: experience, strengths, what they bring to the target job); "
              "skills (7-9 short items mixing role skills and soft skills relevant to the target job); "
              "experience (list of {role, place, period, bullets: 3-4 achievement-style bullets each}); "
              "education (list); languages (list with level, e.g. 'Russian - fluent', from the conversation); "
              "section titles h_summary, h_skills, h_experience, h_education, h_languages in that language. "
              "Answers: " + json.dumps(ctx.user_data["cv"], ensure_ascii=False))
    try:
        data = parse_json(await asyncio.to_thread(ask_llm, cid, prompt))
        buf = build_docx(data)
        safe = re.sub(r"[^\w]+", "_", data.get("name", "CV")) or "CV"
        await update.message.reply_document(document=buf, filename=f"CV_{safe}.docx",
                                            caption="📄 CV / რეზიუმე — გადაამოწმე და საჭიროებისამებრ შეასწორე.")
    except Exception as e:
        logging.exception(e)
        await update.message.reply_text("Sorry, the CV could not be created. Please try /cv again.")
    return ConversationHandler.END

async def cv_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("OK")
    return ConversationHandler.END

# ---------- /advisor : consent, summary, handoff to "City Hall advisor" chat ----------
CONSENT = {
 "ქართული": ("გინდა, მერიის კონსულტანტმა მიიღოს შენი საუბრის მოკლე შეჯამება, რომ დაგიკავშირდეს?", "✅ დიახ", "❌ არა"),
 "Русский": ("Передать консультанту мэрии краткое резюме разговора, чтобы он с вами связался?", "✅ Да", "❌ Нет"),
 "English": ("Do you agree to share a short summary of our chat with a City Hall advisor so they can contact you?", "✅ Yes", "❌ No"),
}
async def advisor(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q, yes, no = CONSENT[L(update.effective_chat.id)]
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(yes, callback_data="adv_yes"), InlineKeyboardButton(no, callback_data="adv_no")]])
    await update.message.reply_text(q, reply_markup=kb)

async def advisor_answer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    cid = query.message.chat.id
    if query.data == "adv_no":
        await query.edit_message_text("OK 👍 /advisor"); return
    await query.edit_message_text("⏳ ...")
    stats["advisor_handoffs"] += 1
    user = query.from_user
    contact = f"@{user.username}" if user.username else user.full_name
    try:
      summary = await asyncio.to_thread(ask_llm, cid, "Write a 5-line summary of my situation for a City Hall employment advisor, in Georgian: "
                           "last job, skills and languages, constraints, what I am looking for, programs that may fit (preliminary). "
                           "Facts from our conversation only. If we have not talked yet, say so briefly.")
      advisor_requests.append({"time": time.strftime("%Y-%m-%d %H:%M"), "lang": L(cid), "summary": summary})
      if ADVISOR_CHAT_ID:
        await ctx.bot.send_message(int(ADVISOR_CHAT_ID.strip()),
            f"📥 ახალი მოთხოვნა კონსულტაციაზე\nმომხმარებელი: {contact}\nენა: {L(cid)}\n\n{summary}")
      else:
        logging.warning("ADVISOR_CHAT_ID is not set")
    except Exception as e:
      logging.exception(e)
      await query.edit_message_text(f"⚠️ Technical problem: {type(e).__name__}. Please try /advisor again.")
      return
    await query.edit_message_text(
        "✅ მოთხოვნა გაიგზავნა. მერიის კონსულტანტი დაგიკავშირდება.\n"
        "✅ Request sent. A City Hall advisor will contact you.\n\n(Prototype: requests go to the project team.)")

async def myid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Your chat ID: {update.effective_chat.id}")

async def delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    history.pop(update.effective_chat.id, None)
    await update.message.reply_text("🗑 Your conversation data has been deleted. / შენი მონაცემები წაიშალა.")

# --- minimal staff dashboard (anonymized counts only) ---
web = Flask(__name__)
@web.route("/")
def dashboard():
    rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in sorted(stats.items()))
    reqs = "".join(f"<li><b>{r['time']}</b> — {r['lang']}<br><pre style='white-space:pre-wrap'>{r.get('summary','')}</pre></li>" for r in advisor_requests[-20:])
    return f"""<html><head><meta charset='utf-8'><title>Batumi Off-Season — staff dashboard (demo)</title>
    <style>body{{font-family:Arial;margin:40px;max-width:720px}}td{{padding:6px 16px;border-bottom:1px solid #ddd}}</style></head>
    <body><h1>Batumi Off-Season</h1><p>City Hall staff dashboard — prototype. Anonymized totals only.</p>
    <h3>Usage</h3><table>{rows or '<tr><td>No activity yet</td></tr>'}</table>
    <h3>Advisor requests</h3><ul>{reqs or '<li>None yet</li>'}</ul></body></html>"""

def run_web():
    web.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

def main():
    threading.Thread(target=run_web, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    txt = filters.TEXT & ~filters.COMMAND
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("cv", cv_start)],
        states={CV_NAME: [MessageHandler(txt, cv_step("name", CV_PHONE, 1))],
                CV_PHONE: [MessageHandler(txt, cv_step("contact", CV_TARGET, 2))],
                CV_TARGET: [MessageHandler(txt, cv_step("target_job", CV_EXP, 3))],
                CV_EXP: [MessageHandler(txt, cv_step("experience", CV_EDU, 4))],
                CV_EDU: [MessageHandler(txt, cv_finish)]},
        fallbacks=[CommandHandler("cancel", cv_cancel)]))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("advisor", advisor))
    app.add_handler(CallbackQueryHandler(advisor_answer, pattern="^adv_"))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("delete", delete))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling()

if __name__ == "__main__":
    main()
