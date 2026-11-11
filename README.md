# Batumi Off-Season (prototype)

Free AI career and benefits navigator for Batumi seasonal workers. Telegram bot + anonymized staff dashboard.
Prototype for the Cities Deliver application. Demo knowledge base only; not for real personal data.

## Run on Render
1. Push this folder to a GitHub repo.
2. Render → New → Web Service → connect the repo.
3. Build command: `pip install -r requirements.txt` · Start command: `python bot.py`
4. Environment variables: `TELEGRAM_BOT_TOKEN` and either `GEMINI_API_KEY` (free, aistudio.google.com) or `OPENAI_API_KEY`. Optional `MODEL`.
5. Open the service URL to see the dashboard. Talk to the bot in Telegram.

Commands: /start, /cv, /advisor, /delete. License: MIT.
