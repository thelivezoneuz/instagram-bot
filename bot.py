import os
import re
import yt_dlp
import tempfile
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

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
        "🎵 Music Search:\n"
        "Just type any song name → I'll show you 5 options\n"
        "Example: Shape of You\n"
        "Example: Blinding Lights The Weeknd\n\n"
        "🎤 Voice Search:\n"
        "Send a voice message saying the song name → I'll find it"
    )


# ─────────────────────────────────────────
# Handle all text messages
# ─────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # Check if it's an Instagram link
    match = re.search(INSTAGRAM_REGEX, text)
    if match:
        url = match.group(0)
        await update.message.reply_text("⏳ Downloading Instagram media... please wait.")
        await download_instagram(update, url)
        return

    # Otherwise treat as music search
    await search_music(update, context, text)


# ─────────────────────────────────────────
# Search music — shows 5 results as buttons
# ─────────────────────────────────────────
async def search_music(update: Update, context: ContextTypes.DEFAULT_TYPE, song_name: str):
    await update.message.reply_text(f"🔍 Searching for: {song_name}\n⏳ Please wait...")

    try:
        results = []

        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': 'in_playlist',
            'default_search': f'ytsearch5:{song_name}',
            # These headers make yt-dlp look like a real browser
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept-Language': 'en-US,en;q=0.9',
            },
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f'ytsearch5:{song_name}', download=False)

            if info and 'entries' in info:
                for entry in info['entries']:
                    if entry:
                        title = entry.get('title', 'Unknown')
                        video_id = entry.get('id', '')
                        duration_sec = entry.get('duration', 0)

                        # Format duration as mm:ss
                        if duration_sec:
                            mins = int(duration_sec) // 60
                            secs = int(duration_sec) % 60
                            duration = f"{mins}:{secs:02d}"
                        else:
                            duration = "?"

                        if video_id:
                            results.append({
                                'title': title,
                                'id': video_id,
                                'duration': duration
                            })

        if not results:
            await update.message.reply_text(
                "❌ No results found.\n\n"
                "Please try again with a different song name."
            )
            return

        # Build inline buttons — one per result
        keyboard = []
        for i, result in enumerate(results):
            label = f"{i+1}. 🎵 {result['title']} [{result['duration']}]"
            if len(label) > 64:
                label = label[:61] + "..."
            keyboard.append([
                InlineKeyboardButton(label, callback_data=f"dl_{result['id']}")
            ])

        # Cancel button
        keyboard.append([
            InlineKeyboardButton("❌ Cancel", callback_data="cancel")
        ])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"🎵 Found {len(results)} results for: *{song_name}*\n\nPick one to download:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

    except Exception as e:
        await update.message.reply_text(
            f"❌ Search failed. Please try again.\n\nError: {str(e)}"
        )


# ─────────────────────────────────────────
# Handle button clicks (user picks a song)
# ─────────────────────────────────────────
async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # User clicked Cancel
    if query.data == "cancel":
        await query.edit_message_text("❌ Search cancelled.")
        return

    # User picked a song
    if query.data.startswith("dl_"):
        video_id = query.data[3:]
        youtube_url = f"https://www.youtube.com/watch?v={video_id}"

        await query.edit_message_text("⏳ Downloading your song... please wait.")

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                ydl_opts = {
                    'format': 'bestaudio/best',
                    'outtmpl': os.path.join(tmpdir, '%(title)s.%(ext)s'),
                    'quiet': True,
                    'no_warnings': True,
                    'http_headers': {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    },
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }],
                }

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(youtube_url, download=True)
                    title = info.get('title', 'Unknown')

                # Find and send the mp3
                for file in os.listdir(tmpdir):
                    if file.endswith('.mp3'):
                        file_path = os.path.join(tmpdir, file)
                        await query.message.reply_audio(
                            audio=open(file_path, 'rb'),
                            title=title,
                            caption=f"🎵 {title}"
                        )
                        await query.edit_message_text(f"✅ Downloaded: {title}")
                        return

            await query.edit_message_text("❌ Could not download. Please try again.")

        except Exception as e:
            await query.edit_message_text(f"❌ Download failed:\n{str(e)}")


# ─────────────────────────────────────────
# Instagram downloader
# ─────────────────────────────────────────
async def download_instagram(update: Update, url: str):
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
        await update.message.reply_text(f"❌ Instagram download failed:\n{str(e)}")


# ─────────────────────────────────────────
# Voice message handler
# ─────────────────────────────────────────
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎤 Voice received! Transcribing...")

    try:
        voice = update.message.voice
        voice_file = await context.bot.get_file(voice.file_id)

        with tempfile.TemporaryDirectory() as tmpdir:
            voice_path = os.path.join(tmpdir, "voice.ogg")
            await voice_file.download_to_drive(voice_path)

            try:
                import speech_recognition as sr
                from pydub import AudioSegment

                wav_path = os.path.join(tmpdir, "voice.wav")
                audio = AudioSegment.from_ogg(voice_path)
                audio.export(wav_path, format="wav")

                recognizer = sr.Recognizer()
                with sr.AudioFile(wav_path) as source:
                    audio_data = recognizer.record(source)
                    song_name = recognizer.recognize_google(audio_data)

                await update.message.reply_text(f"🔍 I heard: {song_name}")
                await search_music(update, context, song_name)

            except ImportError:
                await update.message.reply_text(
                    "⚠️ Voice recognition is not available.\n\n"
                    "Please type the song name instead."
                )

    except Exception as e:
        await update.message.reply_text(f"❌ Could not process voice:\n{str(e)}")


# ─────────────────────────────────────────
# Start the bot
# ─────────────────────────────────────────
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_button))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ Bot is running! Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
