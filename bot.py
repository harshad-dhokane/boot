import os
import logging
import httpx
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, MessageHandler,
    CommandHandler, filters, ContextTypes
)

# ── Logging ───────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

MODEL = "nvidia/nemotron-3-super-120b-a12b:free"
OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]

SYSTEM_PROMPT = """You are a helpful, smart, and concise AI assistant.
Format your responses cleanly:
- Use plain text, avoid markdown symbols like **, ##, or ---
- Use numbered lists (1. 2. 3.) when listing items
- Keep responses clear and well structured
- Be direct and helpful"""

# ── Reusable HTTP client (no reconnect overhead) ──────────
_http_client = httpx.AsyncClient(timeout=60)

# ── Per-user conversation memory ─────────────────────────
conversation_history: dict = {}
MAX_HISTORY = 10


def get_history(user_id: int) -> list:
    if user_id not in conversation_history:
        conversation_history[user_id] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]
    return conversation_history[user_id]


def trim_history(user_id: int):
    history = conversation_history[user_id]
    if len(history) > MAX_HISTORY + 1:
        conversation_history[user_id] = [history[0]] + history[-(MAX_HISTORY):]


# ── OpenRouter call ───────────────────────────────────────
async def call_openrouter(messages: list) -> str:
    response = await _http_client.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/your-repo",
            "X-Title": "Nemotron Telegram Bot"
        },
        json={
            "model": MODEL,
            "messages": messages,
            "max_tokens": 1024,
            "temperature": 0.7
        }
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()


# ── Telegram app + init guard ─────────────────────────────
bot_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
_initialized = False


async def ensure_initialized():
    global _initialized
    if not _initialized:
        await bot_app.initialize()
        _initialized = True


# ── Handlers ──────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.first_name
    await update.message.reply_text(
        f"Hey {user}! I'm powered by Nemotron Super.\n\n"
        f"Send me any message to get started.\n"
        f"Use /clear to reset our conversation."
    )


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conversation_history.pop(user_id, None)
    await update.message.reply_text("Conversation cleared! Starting fresh.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_message = update.message.text

    logger.info(f"User {user_id}: {user_message[:60]}")

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing"
    )

    history = get_history(user_id)
    history.append({"role": "user", "content": user_message})

    try:
        reply = await call_openrouter(history)
        history.append({"role": "assistant", "content": reply})
        trim_history(user_id)
        await update.message.reply_text(reply)

    except Exception as e:
        logger.error(f"API error: {e}")
        await update.message.reply_text(
            "Something went wrong. Please try again in a moment."
        )


bot_app.add_handler(CommandHandler("start", start))
bot_app.add_handler(CommandHandler("clear", clear))
bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))


# ── FastAPI ───────────────────────────────────────────────
app = FastAPI()


@app.get("/")
async def root():
    return {"status": "Nemotron Bot is running"}


@app.get("/setup")
async def setup():
    await ensure_initialized()
    webhook_url = os.environ["WEBHOOK_URL"]
    await bot_app.bot.set_webhook(
        url=f"{webhook_url}/webhook",
        drop_pending_updates=True
    )
    return {"status": "Webhook set", "url": f"{webhook_url}/webhook"}


@app.post("/webhook")
async def webhook(request: Request):
    await ensure_initialized()
    data = await request.json()
    update = Update.de_json(data, bot_app.bot)
    await bot_app.process_update(update)
    return {"ok": True}
