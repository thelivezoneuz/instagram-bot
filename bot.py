import os
import re
import yt_dlp
import tempfile
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# Load your secret token from the .env file
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# This pattern detects Instagram links in messages
INSTAGRAM_REGEX = r'https?://(www\.)?instagram\.com/(p|reel|tv|stories)/[\w\-]+'


# ─────────────────────────────────────────
# /start command — greeting message
# ─────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hi! I'm your All-in-One Media Bot!\n\n"
        "Here's what I can do:\n\n"
        "📸 Instagram Downloader:\n"
        "Send any Instagram link → I'll download it\n\n"
        "🎵 Music Downloader:\n"
        "Type /music <song name> → I'll find and send it\n"
        "Example: /music Shape of You Ed Sheeran\n\n"
        "🎤 Voice Search:\n"
        "Send a voice message saying the song name → I'll find it"
    )


# ─────────────────────────────────────────
# Instagram downloader — handles links
# ─────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    # Check if the message contains an Instagram link
    match = re.search(INSTAGRAM_REGEX, text)
    if not match:
        await update.message.reply_text(
            "❌ I didn't understand that.\n\n"
            "📸 Send an Instagram link to download media\n"
            "🎵 Use /music <song name> to download music\n"
            "🎤 Send a voice message to search by voice"
        )
        return

    url = match.group(0)
    await update.message.reply_text("⏳ Downloading Instagram media... please wait.")

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            ydl_opts = {
                'outtmpl': os.path.join(tmpdir, '%(title)s.%(ext)s'),
                'quiet': True,
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(url, download=True)

            for file in os.listdir(tmpdir):
                file_path = os.path.join(tmpdir, file)
                ext = file.split('.')[-1].lower()

                if ext in ['mp4', 'mov', 'webm']:
                    await update.message.reply_video(video=open(file_path, 'rb'))
                elif ext in ['jpg', 'jpeg', 'png', 'webp']:
                    await update.message.reply_photo(photo=open(file_path, 'rb'))
                else:
                    await update.message.reply_document(document=open(file_path, 'rb'))

    except Exception as e:
        await update.message.reply_text(f"❌ Something went wrong:\n{str(e)}")


# ─────────────────────────────────────────
# Music downloader — /music <song name>
# ─────────────────────────────────────────
async def music_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "❌ Please provide a song name!\n\n"
            "Example: /music Shape of You Ed Sheeran"
        )
        return

    song_name = ' '.join(context.args)
    await download_music(update, song_name)


# ─────────────────────────────────────────
# Voice message handler — user speaks song name
# ─────────────────────────────────────────
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎤 Voice received! Transcribing your message...")

    try:
        voice = update.message.voice
        voice_file = await context.bot.get_file(voice.file_id)

        with tempfile.TemporaryDirectory() as tmpdir:
            voice_path = os.path.join(tmp
