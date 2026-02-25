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

# Browser headers to avoid getting blocked
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}


# ─────────────────────────────────────────
# /start command
# ─────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hi! I'm your All-in-One Media Bot!\n\n"
        "Here's what I can do:\n\n"
        "📸 Instagram Downloader:\n"
        "Send any Instagram link → I'll download it\n\n"
        "🎵 Music Search:\n"
        "Just type any song name → pick your source:\n"
        "• YouTube 🎬\n"
        "• SoundCloud ☁️\n\n"
        "Example: Shape of You\n"
        "Example: Blinding Lights The Weeknd\n\n"
        "🎤 Voice Search:\n"
        "Send a voice message saying the song name"
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

    # Otherwise treat as music search — first ask which platform
    await ask_platform(update, context, text)


# ─────────────────────────────────────────
# Ask user which platform to search
# ─────────────────────────────────────────
async def ask_platform(update: Update, context: ContextTypes.DEFAULT_TYPE, song_name: str):
    keyboard = [
        [
            InlineKeyboardButton("🎬 YouTube", callback_data=f"platform_yt_{song_name}"),
            InlineKeyboardButton("☁️ SoundCloud", callback_data=f"platform_sc_{song_name}"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"🎵 Search: *{song_name}*\n\nChoose a platform:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


# ─────────────────────────────────────────
# Search music on chosen platform
# ─────────────────────────────────────────
async def search_music(update_or_query, song_name: str, platform: str, is_query: bool = False):

    if is_query:
        await update_or_query.edit_message_text(
            f"🔍 Searching on {'YouTube' if platform == 'yt' else 'SoundCloud'} for: {song_name}\n⏳ Please wait..."
        )
        reply_func = update_or_query.message.reply_text
    else:
        await update_or_query.message.reply_text(
            f"🔍 Searching on {'YouTube' if platform == 'yt' else 'SoundCloud'} for: {song_name}\n⏳ Please wait..."
        )
        reply_func = update_or_query.message.reply_text

    try:
        results = []

        # Choose search prefix based on platform
        if platform == 'yt':
            search_query = f'ytsearch5:{song_name}'
            source_label = '🎬 YT'
        else:
            search_query = f'scsearch5:{song_name}'
            source_label = '☁️ SC'

        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': 'in_playlist',
            'http_headers': HEADERS,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(search_query, download=False)

            if info and 'entries' in info:
                for entry in info['entries']:
                    if entry:
                        title = entry.get('title', 'Unknown')
                        video_id = entry.get('id', '')
                        duration_sec = entry.get('duration', 0)
                        url = entry.get('url') or entry.get('webpage_url', '')

                        # Format duration
                        if duration_sec:
                            mins = int(duration_sec) // 60
                            secs = int(duration_sec) % 60
                            duration = f"{mins}:{secs:02d}"
                        else:
                            duration = "?"

                        if video_id or url:
                            results.append({
                                'title': title,
                                'id': video_id,
                                'url': url,
                                'duration': duration,
                                'platform': platform
                            })

        if not results:
            await reply_func("❌ No results found. Try a different song name.")
            return

        # Build result buttons
        keyboard = []
        for i, result in enumerate(results):
            label = f"{i+1}. {source_label} {result['title']} [{result['duration']}]"
            if len(label) > 64:
                label = label[:61] + "..."

            # Store platform + id in callback
            callback = f"dl_{platform}_{result['id']}"
            keyboard.append([InlineKeyboardButton(label, callback_data=callback)])

        # Add search on other platform option
        other_platform = 'sc' if platform == 'yt' else 'yt'
        other_label = '☁️ Search on SoundCloud instead' if platform == 'yt' else '🎬 Search on YouTube instead'
        keyboard.append([
            InlineKeyboardButton(other_label, callback_data=f"platform_{other_platform}_{song_name}")
        ])
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await reply_func(
            f"🎵 Found {len(results)} results for: *{song_name}*\n\nPick one to download:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

    except Exception as e:
        await reply_func(f"❌ Search failed. Please try again.\nError: {str(e)}")


# ─────────────────────────────────────────
# Handle ALL button clicks
# ─────────────────────────────────────────
async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    # ── Cancel ──
    if data == "cancel":
        await query.edit_message_text("❌ Cancelled.")
        return

    # ── Platform chosen — search on that platform ──
    # Format: platform_yt_song name  OR  platform_sc_song name
    if data.startswith("platform_"):
        parts = data.split("_", 2)   # ["platform", "yt", "song name"]
        platform = parts[1]          # "yt" or "sc"
        song_name = parts[2]         # "song name"
        await search_music(query, song_name, platform, is_query=True)
        return

    # ── Download chosen ──
    # Format: dl_yt_videoid  OR  dl_sc_videoid
    if data.startswith("dl_"):
        parts = data.split("_", 2)   # ["dl", "yt", "videoid"]
        platform = parts[1]          # "yt" or "sc"
        video_id = parts[2]          # video id

        # Build the full URL
        if platform == 'yt':
            media_url = f"https://www.youtube.com/watch?v={video_id}"
        else:
            media_url = f"https://soundcloud.com/{video_id}" if '/' in video_id else video_id

        await query.edit_message_text("⏳ Downloading your song... please wait.")

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                ydl_opts = {
                    'format': 'bestaudio/best',
                    'outtmpl': os.path.join(tmpdir, '%(title)s.%(ext)s'),
                    'quiet': True,
                    'no_warnings': True,
                    'http_headers': HEADERS,
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }],
                }

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(media_url, download=True)
                    title = info.get('title', 'Unknown')

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
                await ask_platform(update, context, song_name)

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
