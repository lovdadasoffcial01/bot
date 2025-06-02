import logging
import os
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, constants
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from telegram.error import TelegramError
from dotenv import load_dotenv
from cloudflare_ai import ask_cloudflare_ai, transcribe_audio, image_to_text
from db import Session, Conversation

# Configure logging with more detailed format
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("No BOT_TOKEN found in environment variables")

# Store user chat histories and settings with type hints
user_histories: dict = {}
user_settings: dict = {}

# Maximum history length to prevent memory issues
MAX_HISTORY_LENGTH = 50
MAX_MESSAGE_LENGTH = 4096  # Telegram's message length limit

async def split_long_message(update: Update, text: str) -> None:
    """Split and send long messages within Telegram's limits."""
    for i in range(0, len(text), MAX_MESSAGE_LENGTH):
        chunk = text[i:i + MAX_MESSAGE_LENGTH]
        await update.message.reply_text(chunk)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command."""
    if not update.message:
        return

    try:
        keyboard = [
            [
                InlineKeyboardButton("💬 Chat", callback_data='mode_chat'),
                InlineKeyboardButton("🎨 Image Gen", callback_data='mode_image')
            ],
            [
                InlineKeyboardButton("🎤 Voice", callback_data='mode_voice'),
                InlineKeyboardButton("📷 Image Analysis", callback_data='mode_analysis')
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        welcome_msg = (
            "🤖 Welcome to Advanced AI Assistant!\n\n"
            "🔹 Commands:\n"
            "/start - Start bot\n"
            "/help - Show help\n"
            "/clear - Clear chat history\n"
            "/settings - Bot settings\n"
            "/stats - Usage statistics\n"
            "/mode - Change AI mode\n"
            "/translate <text> - Translate text\n"
            "/summarize <text> - Summarize text\n"
            "/code <prompt> - Generate code\n\n"
            "🔹 Features:\n"
            "• Advanced Chat with Context\n"
            "• Image Generation\n"
            "• Voice Transcription\n"
            "• Image Analysis\n"
            "• Code Generation\n"
            "• Text Translation\n"
            "• Text Summarization"
        )
        await update.message.reply_text(welcome_msg, reply_markup=reply_markup)

        # Initialize user history if not exists
        user_id = update.effective_user.id
        if user_id not in user_histories:
            user_histories[user_id] = []

        save_to_db(update.effective_user.id, "assistant", welcome_msg)
    except Exception as e:
        logger.error(f"Start command error: {str(e)}")
        await update.message.reply_text("An error occurred. Please try again.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle button callbacks."""
    try:
        query = update.callback_query
        if not query:
            return

        await query.answer()

        user_id = update.effective_user.id
        mode = query.data.split('_')[1]

        user_settings[user_id] = user_settings.get(user_id, {})
        user_settings[user_id]['mode'] = mode

        await query.message.reply_text(f"Mode switched to: {mode.capitalize()}")
    except Exception as e:
        logger.error(f"Button handler error: {str(e)}")
        if query:
            await query.message.reply_text("An error occurred while processing your selection.")

async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /settings command."""
    if not update.message:
        return

    try:
        user_id = update.effective_user.id
        if user_id not in user_settings:
            user_settings[user_id] = {'mode': 'chat'}

        settings_text = (
            "⚙️ Current Settings:\n"
            f"Mode: {user_settings[user_id]['mode'].capitalize()}\n\n"
            "Use /mode to change the current mode."
        )
        await update.message.reply_text(settings_text)
    except Exception as e:
        logger.error(f"Settings error: {str(e)}")
        await update.message.reply_text("Error fetching settings.")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /stats command."""
    if not update.message:
        return

    try:
        user_id = update.effective_user.id
        with Session() as session:
            total_messages = session.query(Conversation).filter_by(user_id=str(user_id)).count()
            user_messages = session.query(Conversation).filter_by(user_id=str(user_id), is_user=True).count()
            bot_messages = session.query(Conversation).filter_by(user_id=str(user_id), is_user=False).count()

        stats_msg = (
            "📊 Your Usage Statistics:\n\n"
            f"Total messages: {total_messages}\n"
            f"Your messages: {user_messages}\n"
            f"Bot responses: {bot_messages}\n"
        )
        await update.message.reply_text(stats_msg)
    except Exception as e:
        logger.error(f"Stats error: {str(e)}")
        await update.message.reply_text("Error fetching statistics.")

async def translate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /translate command."""
    if not update.message:
        return

    try:
        text = ' '.join(context.args)
        if not text:
            await update.message.reply_text("Please provide text to translate.")
            return

        prompt = f"Translate the following text to English: {text}"
        response = ask_cloudflare_ai(prompt)
        await split_long_message(update, response["data"])
    except Exception as e:
        logger.error(f"Translation error: {str(e)}")
        await update.message.reply_text("Translation failed.")

async def summarize(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /summarize command."""
    if not update.message:
        return

    try:
        text = ' '.join(context.args)
        if not text:
            await update.message.reply_text("Please provide text to summarize.")
            return

        prompt = f"Summarize the following text: {text}"
        response = ask_cloudflare_ai(prompt)
        await split_long_message(update, response["data"])
    except Exception as e:
        logger.error(f"Summarization error: {str(e)}")
        await update.message.reply_text("Summarization failed.")

async def code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /code command."""
    if not update.message:
        return

    try:
        prompt = ' '.join(context.args)
        if not prompt:
            await update.message.reply_text("Please provide a code generation prompt.")
            return

        response = ask_cloudflare_ai(prompt, model="qwancoder")
        code_response = f"```\n{response['data']}\n```"
        await split_long_message(update, code_response)
    except Exception as e:
        logger.error(f"Code generation error: {str(e)}")
        await update.message.reply_text("Code generation failed.")

def save_to_db(user_id: int, role: str, message: str, message_type: str = "text") -> None:
    """Save conversation to database."""
    try:
        with Session() as session:
            conv = Conversation(
                user_id=str(user_id),
                role=role,
                message=message,
                type=message_type,
                is_user=(role == "user")
            )
            session.add(conv)
            session.commit()
    except Exception as e:
        logger.error(f"Database error: {str(e)}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /help command."""
    if not update.message:
        return

    try:
        help_text = (
            "📚 Available Commands:\n\n"
            "/start - Start bot\n"
            "/help - Show this message\n"
            "/clear - Clear chat history\n"
            "/settings - Bot settings\n"
            "/stats - Usage statistics\n"
            "/mode - Change AI mode\n"
            "/translate <text> - Translate text\n"
            "/summarize <text> - Summarize text\n"
            "/code <prompt> - Generate code\n\n"
            "💡 Features:\n"
            "• Send text messages for chat\n"
            "• Type 'generate image ...' for image creation\n"
            "• Send voice messages for transcription\n"
            "• Send images for analysis\n"
            "• Use /code for programming help\n"
            "• Use /translate for translations\n"
            "• Use /summarize for text summaries"
        )
        await update.message.reply_text(help_text)
        save_to_db(update.effective_user.id, "assistant", help_text)
    except Exception as e:
        logger.error(f"Help command error: {str(e)}")
        await update.message.reply_text("An error occurred. Please try again.")

async def clear_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /clear command."""
    if not update.message:
        return

    try:
        user_id = update.effective_user.id
        user_histories[user_id] = []
        await update.message.reply_text("✨ Chat history cleared!")
        save_to_db(user_id, "system", "Chat history cleared")
    except Exception as e:
        logger.error(f"Clear chat error: {str(e)}")
        await update.message.reply_text("Failed to clear chat history.")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle voice messages."""
    if not update.message or not update.message.voice:
        return

    try:
        await update.message.reply_text("🎤 Processing voice message...")
        voice_file = await update.message.voice.get_file()
        voice_bytes = await voice_file.download_as_bytearray()

        transcription = transcribe_audio(voice_bytes)
        await update.message.reply_text(f"🔊 Transcription:\n{transcription}")

        save_to_db(update.effective_user.id, "user", "[Voice Message]", "voice")
        save_to_db(update.effective_user.id, "assistant", transcription)
    except Exception as e:
        logger.error(f"Voice processing error: {str(e)}")
        await update.message.reply_text("❌ Sorry, couldn't process the voice message")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle photo messages."""
    if not update.message or not update.message.photo:
        return

    try:
        await update.message.reply_text("🖼️ Analyzing image...")
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()

        description = image_to_text(photo_bytes)
        await update.message.reply_text(f"📝 Image description:\n{description}")

        save_to_db(update.effective_user.id, "user", "[Image]", "image")
        save_to_db(update.effective_user.id, "assistant", description)
    except Exception as e:
        logger.error(f"Image processing error: {str(e)}")
        await update.message.reply_text("❌ Sorry, couldn't analyze the image")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text messages."""
    if not update.message or not update.message.text:
        return

    try:
        user_id = update.effective_user.id
        if user_id not in user_histories:
            user_histories[user_id] = []

        message_text = update.message.text
        save_to_db(user_id, "user", message_text)

        # Limit history length
        if len(user_histories[user_id]) > MAX_HISTORY_LENGTH:
            user_histories[user_id] = user_histories[user_id][-MAX_HISTORY_LENGTH:]

        # Get user's current mode
        mode = user_settings.get(user_id, {}).get('mode', 'chat')

        # Process message based on mode
        if mode == 'chat':
            response = ask_cloudflare_ai(message_text, history=user_histories[user_id])
        elif mode == 'image' and message_text.lower().startswith('generate'):
            response = ask_cloudflare_ai(message_text, model="stable_diffusion")
        else:
            response = ask_cloudflare_ai(message_text)

        # Handle response based on type
        if response["type"] == "image":
            await update.message.reply_photo(
                response["data"],
                caption=response.get("message", "Generated image")
            )
            save_to_db(user_id, "assistant", response["message"], "image")
        else:
            await split_long_message(update, response["data"])
            user_histories[user_id].extend([
                {"role": "user", "content": message_text},
                {"role": "assistant", "content": response["data"]}
            ])
            save_to_db(user_id, "assistant", response["data"])

    except Exception as e:
        logger.error(f"Message handling error: {str(e)}")
        await update.message.reply_text("❌ Sorry, something went wrong. Please try again.")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors in the dispatcher."""
    logger.error(f"Update {update} caused error {context.error}")

def main() -> None:
    """Start the bot."""
    try:
        # Create the Application with error handler
        application = Application.builder().token(BOT_TOKEN).build()
        application.add_error_handler(error_handler)

        # Add command handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("clear", clear_chat))
        application.add_handler(CommandHandler("settings", settings))
        application.add_handler(CommandHandler("stats", stats))
        application.add_handler(CommandHandler("translate", translate))
        application.add_handler(CommandHandler("summarize", summarize))
        application.add_handler(CommandHandler("code", code))

        # Add callback query handler
        application.add_handler(CallbackQueryHandler(button_handler))

        # Add message handlers
        application.add_handler(MessageHandler(filters.VOICE, handle_voice))
        application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        # Start the bot
        logger.info("Starting bot...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)

    except Exception as e:
        logger.error(f"Bot startup error: {str(e)}")
        raise

if __name__ == "__main__":
    main()
