"""Batumi Off-Season - prototype AI career & benefits navigator (Telegram).
Prototype only: demo knowledge base, in-memory storage. Not for real personal data."""
import json, os, threading, time, logging
from collections import defaultdict
from flask import Flask
from openai import OpenAI
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(level=logging.INFO)
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
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

async def cv(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    stats["cvs_drafted"] += 1
    await ctx.bot.send_chat_action(cid, "typing")
    out = ask_llm(cid, "Draft a short one-page CV for me from our conversation, in my language. Use [brackets] for anything I have not told you. Do not invent experience.")
    await update.message.reply_text(out)

async def advisor(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    stats["advisor_handoffs"] += 1
    advisor_requests.append({"time": time.strftime("%Y-%m-%d %H:%M"), "lang": lang_of.get(cid, "?")})
    await update.message.reply_text(
        "✅ Demo: your request for a City Hall advisor is recorded. In the real pilot, an advisor would receive a short summary "
        "of your situation (only with your consent) and contact you to book a time.\n\n"
        "✅ დემო: მერიის კონსულტანტთან შეხვედრის მოთხოვნა მიღებულია. რეალურ პილოტში კონსულტანტი შენი თანხმობით მიიღებს მოკლე შეჯამებას და დაგიკავშირდება.")

async def delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    history.pop(update.effective_chat.id, None)
    await update.message.reply_text("🗑 Your conversation data has been deleted. / შენი მონაცემები წაიშალა.")

# --- minimal staff dashboard (anonymized counts only) ---
web = Flask(__name__)
@web.route("/")
def dashboard():
    rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in sorted(stats.items()))
    reqs = "".join(f"<li>{r['time']} — {r['lang']}</li>" for r in advisor_requests[-20:])
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
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cv", cv))
    app.add_handler(CommandHandler("advisor", advisor))
    app.add_handler(CommandHandler("delete", delete))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling()

if __name__ == "__main__":
    main()
