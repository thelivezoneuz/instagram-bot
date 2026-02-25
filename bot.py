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

# We store search results temporarily here
# Key = user_id, Value = list of results
search_cache = {}


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

    # Otherwise treat as music search
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
# Search music and show results as buttons
# ─────────────────────────────────────────
async def search_music(query, song_name: str, platform: str):
    platform_name = 'YouTube' if platform == 'yt' else 'SoundCloud'
    source_label = '🎬' if platform == 'yt' else '☁️'

    await query.edit_message_text(
        f"🔍 Searching on {platform_name} for: {song_name}\n⏳ Please wait..."
    )

    try:
        results = []

        search_query = f'ytsearch5:{song_name}' if platform == 'yt' else f'scsearch5:{song_name}'

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
                        duration_sec = entry.get('duration', 0)
                        # ✅ Always get the full webpage URL
                        full_url = entry.get('webpage_url') or entry.get('url', '')

                        # Format duration
                        if duration_sec:
                            mins = int(duration_sec) // 60
                            secs = int(duration_sec) % 60
                            duration = f"{mins}:{secs:02d}"
                        else:
                            duration = "?"

                        if full_url:
                            results.append({
                                'title': title,
                                'url': full_url,
                                'duration': duration,
                            })

        if not results:
            await query.edit_message_text(
                f"❌ No results found on {platform_name}.\n\nTry the other platform or a different song name."
            )
            return

        # ✅ Save results in cache using user id
        user_id = query.from_user.id
        search_cache[user_id] = results

        # Build result buttons using index (to avoid URL issues in callback_data)
        keyboard = []
        for i, result in enumerate(results):
            label = f"{i+1}. {source_label} {result['title']} [{result['duration']}]"
            if len(label) > 64:
                label = label[:61] + "..."
            # Use index number in callback — safe and short
            keyboard.append([InlineKeyboardButton(label, callback_data=f"pick_{i}")])

        # Switch platform option
        other_platform = 'sc' if platform == 'yt' else 'yt'
        other_label = '☁️ Try SoundCloud instead' if platform == 'yt' else '🎬 Try YouTube instead'
        keyboard.append([
            InlineKeyboardButton(other_label, callback_data=f"platform_{other_platform}_{song_name}")
        ])
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            f"🎵 Found {len(results)} results for: *{song_name}*\n\nPick one to download:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

    except Exception as e:
        await query.edit_message_text(f"❌ Search failed. Please try again.\nError: {str(e)}")


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

    # ── Platform chosen ──
    # Format: platform_yt_song name OR platform_sc_song name
    if data.startswith("platform_"):
        parts = data.split("_", 2)
        platform = parts[1]
        song_name = parts[2]
        await search_music(query, song_name, platform)
        return

    # ── User picked a result by index ──
    # Format: pick_0, pick_1, pick_2 etc.
    if data.startswith("pick_"):
        index = int(data.split("_")[1])
        user_id = query.from_user.id

        # Get URL from cache
        if user_id not in search_cache or index >= len(search_cache[user_id]):
            await query.edit_message_text("❌ Session expired. Please search again.")
            return

        result = search_cache[user_id][index]
        media_url = result['url']
        title = result['title']

        await query.edit_message_text(f"⏳ Downloading: {title}\nPlease wait...")

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
                    title = info.get('title', title)

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
                await ask_platform(update, None, song_name)

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
