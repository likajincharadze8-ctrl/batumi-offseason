"""Batumi Off-Season - prototype AI career & benefits navigator (Telegram).
Prototype only: demo knowledge base, in-memory storage. Not for real personal data."""
import json, os, re, io, threading, time, logging
from collections import defaultdict
from flask import Flask
from openai import OpenAI
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Application, CommandHandler, MessageHandler, ContextTypes, filters,
                          ConversationHandler, CallbackQueryHandler)
from docx import Document
from docx.shared import Pt

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
        answer = ask_llm(cid)
    except Exception as e:
        logging.exception(e)
        answer = "Sorry, a technical problem. Please try again or use /advisor."
    history[cid].append({"role": "assistant", "content": answer})
    await update.message.reply_text(answer)

# ---------- /cv : short Q&A, then a Word CV file ----------
CV_NAME, CV_PHONE, CV_EXP, CV_EDU = range(4)
CVQ = {
 "ქართული": ["რეზიუმესთვის რამდენიმე კითხვა 📝\n1/4. შენი სახელი და გვარი?",
             "2/4. ტელეფონი ან ელფოსტა, რომელზეც დაგიკავშირდნენ?",
             "3/4. ჩამოთვალე სამუშაო გამოცდილება: სად, რა თანამდებობაზე და რომელ წლებში. მაგ.: „კაფე X, ოფიციანტი, 2023–2026“",
             "4/4. განათლება ან კურსები (თუ გაქვს). თუ არა, დაწერე „არა“."],
 "Русский": ["Несколько вопросов для резюме 📝\n1/4. Ваше имя и фамилия?",
             "2/4. Телефон или email для связи?",
             "3/4. Опыт работы: где, кем и в какие годы. Например: «Кафе X, официант, 2023–2026»",
             "4/4. Образование или курсы (если есть). Если нет, напишите «нет»."],
 "English": ["A few questions for your CV 📝\n1/4. Your full name?",
             "2/4. Phone or email where employers can reach you?",
             "3/4. Your work experience: where, what role, which years. E.g. 'Cafe X, waiter, 2023-2026'",
             "4/4. Education or courses (if any). If none, write 'none'."],
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

def build_docx(d):
    doc = Document()
    st = doc.styles["Normal"]; st.font.name = "Arial"; st.font.size = Pt(11)
    doc.add_heading(d.get("name", ""), level=0)
    doc.add_paragraph(d.get("contact", ""))
    def section(title, items):
        if items:
            doc.add_heading(title, level=1)
            for it in items:
                doc.add_paragraph(it, style="List Bullet")
    if d.get("summary"):
        doc.add_heading(d.get("h_summary", "Profile"), level=1); doc.add_paragraph(d["summary"])
    exp = [f"{e.get('role','')} — {e.get('place','')} ({e.get('period','')}). {e.get('details','')}".strip()
           for e in d.get("experience", [])]
    section(d.get("h_experience", "Experience"), exp)
    section(d.get("h_skills", "Skills"), d.get("skills", []))
    section(d.get("h_languages", "Languages"), d.get("languages", []))
    section(d.get("h_education", "Education"), d.get("education", []))
    buf = io.BytesIO(); doc.save(buf); buf.seek(0); return buf

async def cv_finish(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    ctx.user_data["cv"]["education"] = update.message.text
    stats["cvs_drafted"] += 1
    await ctx.bot.send_chat_action(cid, "upload_document")
    prompt = ("Create a CV as JSON only, no other text, in the language: " + L(cid) + ". "
              "Use ONLY facts from the answers and our conversation; never invent employers, dates or degrees. "
              "Keys: name, contact, summary (2 sentences), experience (list of {role, place, period, details}), "
              "skills (list), languages (list), education (list), and section titles h_summary, h_experience, "
              "h_skills, h_languages, h_education in that language. Answers: " + json.dumps(ctx.user_data["cv"], ensure_ascii=False))
    try:
        data = parse_json(ask_llm(cid, prompt))
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
    stats["advisor_handoffs"] += 1
    user = query.from_user
    contact = f"@{user.username}" if user.username else user.full_name
    summary = ask_llm(cid, "Write a 5-line summary of my situation for a City Hall employment advisor, in Georgian: "
                           "last job, skills and languages, constraints, what I am looking for, programs that may fit (preliminary). "
                           "Facts from our conversation only.")
    advisor_requests.append({"time": time.strftime("%Y-%m-%d %H:%M"), "lang": L(cid), "summary": summary})
    if ADVISOR_CHAT_ID:
        await ctx.bot.send_message(int(ADVISOR_CHAT_ID),
            f"📥 ახალი მოთხოვნა კონსულტაციაზე\nმომხმარებელი: {contact}\nენა: {L(cid)}\n\n{summary}")
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
                CV_PHONE: [MessageHandler(txt, cv_step("contact", CV_EXP, 2))],
                CV_EXP: [MessageHandler(txt, cv_step("experience", CV_EDU, 3))],
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
