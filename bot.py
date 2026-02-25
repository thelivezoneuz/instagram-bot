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
            voice_path = os.path.join(tmpdir, "voice.ogg")
            await voice_file.download_to_drive(voice_path)

            try:
                import speech_recognition as sr
                from pydub import AudioSegment

                # Convert ogg to wav
                wav_path = os.path.join(tmpdir, "voice.wav")
                audio = AudioSegment.from_ogg(voice_path)
                audio.export(wav_path, format="wav")

                # Recognize speech using Google
                recognizer = sr.Recognizer()
                with sr.AudioFile(wav_path) as source:
                    audio_data = recognizer.record(source)
                    song_name = recognizer.recognize_google(audio_data)

                await update.message.reply_text(f"🔍 I heard: {song_name}\nSearching...")
                await download_music(update, song_name)

            except ImportError:
                await update.message.reply_text(
                    "⚠️ Voice recognition is not available.\n\n"
                    "Please type the song name instead:\n"
                    "Example: /music Shape of You Ed Sheeran"
                )

    except Exception as e:
        await update.message.reply_text(f"❌ Could not process voice message:\n{str(e)}")


# ─────────────────────────────────────────
# Core music download function
# ─────────────────────────────────────────
async def download_music(update: Update, song_name: str):
    await update.message.reply_text(f"🎵 Searching for: {song_name}\n⏳ Please wait...")

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(tmpdir, '%(title)s.%(ext)s'),
                'quiet': True,
                'default_search': 'ytsearch1',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(song_name, download=True)
                if 'entries' in info:
                    title = info['entries'][0].get('title', song_name)
                else:
                    title = info.get('title', song_name)

            for file in os.listdir(tmpdir):
                if file.endswith('.mp3'):
                    file_path = os.path.join(tmpdir, file)
                    await update.message.reply_audio(
                        audio=open(file_path, 'rb'),
                        title=title,
                        caption=f"🎵 {title}"
                    )
                    return

            await update.message.reply_text("❌ Could not find that song. Try a different name.")

    except Exception as e:
        await update.message.reply_text(f"❌ Music download failed:\n{str(e)}")


# ─────────────────────────────────────────
# Start the bot
# ─────────────────────────────────────────
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("music", music_command))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ Bot is running! Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
