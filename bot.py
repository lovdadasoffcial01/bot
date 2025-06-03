import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from telegram.error import TelegramError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from dotenv import load_dotenv
from cloudflare_ai import ask_cloudflare_ai, transcribe_audio, image_to_text, generate_image
from db import Session, Conversation

# Configure logging
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

# Initialize global variables
ADMIN_IDS = set(map(int, os.getenv("ADMIN_IDS", "").split(",")))
MAX_HISTORY_LENGTH = 50
MAX_MESSAGE_LENGTH = 4096

class BotManager:
    def __init__(self):
        self.user_histories: Dict[int, List[Dict[str, str]]] = {}
        self.user_settings: Dict[int, Dict[str, str]] = {}
        self.scheduler = AsyncIOScheduler(
            jobstores={'default': SQLAlchemyJobStore(url='sqlite:///jobs.db')}
        )
        
    def is_admin(self, user_id: int) -> bool:
        """Check if user is an admin"""
        return user_id in ADMIN_IDS
        
    async def split_long_message(self, update: Update, text: str) -> None:
        """Split and send long messages"""
        for i in range(0, len(text), MAX_MESSAGE_LENGTH):
            chunk = text[i:i + MAX_MESSAGE_LENGTH]
            await update.message.reply_text(chunk)
            
    async def set_reminder(self, chat_id: int, text: str, when: datetime) -> str:
        """Set a reminder"""
        job_id = f"reminder_{chat_id}_{int(datetime.now().timestamp())}"
        
        self.scheduler.add_job(
            self._send_reminder,
            'date',
            run_date=when,
            args=[chat_id, text],
            id=job_id
        )
        
        return job_id
        
    async def _send_reminder(self, chat_id: int, text: str):
        """Send reminder message"""
        try:
            await self.application.bot.send_message(
                chat_id=chat_id,
                text=f"⏰ Reminder:\n{text}"
            )
        except TelegramError as e:
            logger.error(f"Failed to send reminder: {e}")
            
    def save_to_db(self, user_id: int, role: str, message: str, message_type: str = "text") -> None:
        """Save conversation to database"""
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

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command"""
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
                "Available Commands:\n"
                "/start - Start bot\n"
                "/help - Show help\n"
                "/clear - Clear chat history\n"
                "/settings - Bot settings\n"
                "/stats - Usage statistics\n"
                "/mode - Change AI mode\n"
                "/remind - Set a reminder\n\n"
                "Features:\n"
                "• Advanced Chat with Context\n"
                "• Image Generation\n"
                "• Voice Transcription\n"
                "• Image Analysis\n"
                "• Reminders System"
            )
            await update.message.reply_text(welcome_msg, reply_markup=reply_markup)
            
            user_id = update.effective_user.id
            if user_id not in self.user_histories:
                self.user_histories[user_id] = []
                
            self.save_to_db(user_id, "assistant", welcome_msg)
            
        except Exception as e:
            logger.error(f"Start command error: {str(e)}")
            await update.message.reply_text("An error occurred. Please try again.")

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle button callbacks"""
        try:
            query = update.callback_query
            if not query:
                return

            await query.answer()
            
            user_id = update.effective_user.id
            mode = query.data.split('_')[1]
            
            self.user_settings[user_id] = self.user_settings.get(user_id, {})
            self.user_settings[user_id]['mode'] = mode
            
            await query.message.reply_text(f"Mode switched to: {mode.capitalize()}")
        except Exception as e:
            logger.error(f"Button handler error: {str(e)}")
            if query:
                await query.message.reply_text("An error occurred while processing your selection.")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle text messages"""
        if not update.message or not update.message.text:
            return
            
        user_id = update.effective_user.id
        
        try:
            if user_id not in self.user_histories:
                self.user_histories[user_id] = []
                
            message_text = update.message.text
            self.save_to_db(user_id, "user", message_text)
            
            # Limit history length
            if len(self.user_histories[user_id]) > MAX_HISTORY_LENGTH:
                self.user_histories[user_id] = self.user_histories[user_id][-MAX_HISTORY_LENGTH:]
                
            # Get user's current mode
            mode = self.user_settings.get(user_id, {}).get('mode', 'chat')
            
            # Handle image generation
            if message_text.lower().startswith(('generate image', 'create image')):
                prompt = message_text.split(' ', 2)[2]
                response = generate_image(prompt)
            else:
                # Process message based on mode
                if mode == 'chat':
                    response = ask_cloudflare_ai(message_text, history=self.user_histories[user_id])
                elif mode == 'image':
                    response = generate_image(message_text)
                else:
                    response = ask_cloudflare_ai(message_text)
                    
            # Handle response based on type
            if response["type"] == "image":
                await update.message.reply_photo(
                    response["data"],
                    caption=response.get("message", "Generated image")
                )
                self.save_to_db(user_id, "assistant", response["message"], "image")
            else:
                await self.split_long_message(update, response["data"])
                self.user_histories[user_id].extend([
                    {"role": "user", "content": message_text},
                    {"role": "assistant", "content": response["data"]}
                ])
                self.save_to_db(user_id, "assistant", response["data"])
                
        except Exception as e:
            logger.error(f"Message handling error: {str(e)}")
            await update.message.reply_text("❌ Sorry, something went wrong. Please try again.")

    async def handle_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle voice messages"""
        if not update.message or not update.message.voice:
            return

        try:
            await update.message.reply_text("🎤 Processing voice message...")
            voice_file = await update.message.voice.get_file()
            voice_bytes = await voice_file.download_as_bytearray()
            
            transcription = transcribe_audio(voice_bytes)
            await update.message.reply_text(f"🔊 Transcription:\n{transcription}")
            
            self.save_to_db(update.effective_user.id, "user", "[Voice Message]", "voice")
            self.save_to_db(update.effective_user.id, "assistant", transcription)
        except Exception as e:
            logger.error(f"Voice processing error: {str(e)}")
            await update.message.reply_text("❌ Sorry, couldn't process the voice message")

    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle photo messages"""
        if not update.message or not update.message.photo:
            return

        try:
            await update.message.reply_text("🖼️ Analyzing image...")
            photo_file = await update.message.photo[-1].get_file()
            photo_bytes = await photo_file.download_as_bytearray()
            
            description = image_to_text(photo_bytes)
            await update.message.reply_text(f"📝 Image description:\n{description}")
            
            self.save_to_db(update.effective_user.id, "user", "[Image]", "image")
            self.save_to_db(update.effective_user.id, "assistant", description)
        except Exception as e:
            logger.error(f"Image processing error: {str(e)}")
            await update.message.reply_text("❌ Sorry, couldn't analyze the image")

    def run(self):
        """Start the bot"""
        try:
            # Create the Application
            self.application = Application.builder().token(BOT_TOKEN).build()
            
            # Add command handlers
            self.application.add_handler(CommandHandler("start", self.start_command))
            self.application.add_handler(CommandHandler("help", self.help_command))
            self.application.add_handler(CommandHandler("clear", self.clear_chat))
            self.application.add_handler(CommandHandler("settings", self.settings))
            self.application.add_handler(CommandHandler("stats", self.stats))
            self.application.add_handler(CommandHandler("remind", self.handle_reminder))
            
            # Add callback query handler
            self.application.add_handler(CallbackQueryHandler(self.button_handler))
            
            # Add message handlers
            self.application.add_handler(MessageHandler(filters.VOICE, self.handle_voice))
            self.application.add_handler(MessageHandler(filters.PHOTO, self.handle_photo))
            self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
            
            # Start the scheduler
            self.scheduler.start()
            
            # Start the bot
            logger.info("Starting bot...")
            self.application.run_polling(allowed_updates=Update.ALL_TYPES)
            
        except Exception as e:
            logger.error(f"Bot startup error: {str(e)}")
            raise

def main():
    """Main entry point"""
    bot_manager = BotManager()
    bot_manager.run()

if __name__ == "__main__":
    main()
