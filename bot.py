import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, MessageHandler,
    CommandHandler, filters, ContextTypes
)
from openai import OpenAI

# ── Logging ──────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── OpenRouter Client ─────────────────────────────────────
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],
    default_headers={
        "HTTP-Referer": "https://github.com/your-repo",
        "X-Title": "Nemotron Telegram Bot"
    }
)

MODEL = "nvidia/nemotron-3-super-120b-a12b:free"

SYSTEM_PROMPT = """You are a helpful, smart, and concise AI assistant.
Format your responses cleanly:
- Use plain text, avoid markdown symbols like **, ##, or ---
- Use numbered lists (1. 2. 3.) when listing items
- Keep responses clear and well structured
- Be direct and helpful"""

# ── Per-user conversation memory ─────────────────────────
conversation_history: dict[int, list] = {}
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


# ── Telegram App ──────────────────────────────────────────
bot_app = ApplicationBuilder().token(os.environ["TELEGRAM_TOKEN"]).build()


# ── Handlers ──────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.first_name
    await update.message.reply_text(
        f"👋 Hey {user}! I'm powered by Nemotron Ultra.\n\n"
        f"Just send me a message to get started.\n"
        f"Use /clear to reset our conversation."
    )


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conversation_history.pop(user_id, None)
    await update.message.reply_text("🗑 Conversation cleared! Starting fresh.")


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
        response = client.chat.completions.create(
            model=MODEL,
            messages=history,
            max_tokens=1024,
            temperature=0.7
        )

        reply = response.choices[0].message.content.strip()
        history.append({"role": "assistant", "content": reply})
        trim_history(user_id)

        await update.message.reply_text(reply)

    except Exception as e:
        logger.error(f"API error: {e}")
        await update.message.reply_text(
            "⚠️ Something went wrong. Please try again in a moment."
        )


bot_app.add_handler(CommandHandler("start", start))
bot_app.add_handler(CommandHandler("clear", clear))
bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))


# ── FastAPI + Lifespan ────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await bot_app.initialize()
    webhook_url = os.environ["WEBHOOK_URL"]
    await bot_app.bot.set_webhook(
        url=f"{webhook_url}/webhook",
        drop_pending_updates=True
    )
    logger.info(f"Webhook set to {webhook_url}/webhook")
    yield
    # Shutdown
    await bot_app.shutdown()


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def root():
    return {"status": "Nemotron Bot is running"}


@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, bot_app.bot)
    await bot_app.process_update(update)
    return {"ok": True}        history.append({"role": "assistant", "content": reply})
        trim_history(user_id)

        # Send reply — plain text is safest for varied responses
        await update.message.reply_text(reply)

    except Exception as e:
        logger.error(f"API error: {e}")
        await update.message.reply_text(
            "⚠️ Something went wrong. Please try again in a moment."
        )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Exception: {context.error}")


# ── Main ──────────────────────────────────────────────────
def main():
    token = os.environ["TELEGRAM_TOKEN"]

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    logger.info("Bot is running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
