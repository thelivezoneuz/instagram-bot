import os
import re
import json
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

# Temporary search results cache (per user)
search_cache = {}

# Favourites file path
FAVOURITES_FILE = "favourites.json"


# ─────────────────────────────────────────
# Favourites helper functions
# ─────────────────────────────────────────

def load_favourites():
    """Load all favourites from JSON file."""
    if os.path.exists(FAVOURITES_FILE):
        with open(FAVOURITES_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_favourites(data):
    """Save all favourites to JSON file."""
    with open(FAVOURITES_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def get_user_favourites(user_id: str):
    """Get favourites list for a specific user."""
    data = load_favourites()
    return data.get(user_id, [])

def add_to_favourites(user_id: str, title: str, url: str):
    """Add a song to user's favourites."""
    data = load_favourites()
    if user_id not in data:
        data[user_id] = []

    # Check if already in favourites
    for item in data[user_id]:
        if item['url'] == url:
            return False  # Already exists

    data[user_id].append({'title': title, 'url': url})
    save_favourites(data)
    return True

def remove_from_favourites(user_id: str, index: int):
    """Remove a song from user's favourites by index."""
    data = load_favourites()
    if user_id in data and 0 <= index < len(data[user_id]):
        removed = data[user_id].pop(index)
        save_favourites(data)
        return removed['title']
    return None


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
        "Just type any song name → pick YouTube or SoundCloud\n\n"
        "⭐ Favourites:\n"
        "Save your favourite songs and download them anytime!\n"
        "Use /favourites to see your saved songs\n\n"
        "🎤 Voice Search:\n"
        "Send a voice message saying the song name"
    )


# ─────────────────────────────────────────
# /favourites command — show saved songs
# ─────────────────────────────────────────
async def favourites_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    favs = get_user_favourites(user_id)

    if not favs:
        await update.message.reply_text(
            "⭐ Your favourites list is empty!\n\n"
            "Search for a song, then tap ⭐ Add to Favourites to save it here."
        )
        return

    keyboard = []
    for i, fav in enumerate(favs):
        title = fav['title']
        label = f"🎵 {title}"
        if len(label) > 60:
            label = label[:57] + "..."
        keyboard.append([
            InlineKeyboardButton(label, callback_data=f"fav_play_{i}"),
            InlineKeyboardButton("🗑️", callback_data=f"fav_del_{i}")
        ])

    keyboard.append([InlineKeyboardButton("❌ Close", callback_data="cancel")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"⭐ Your Favourites ({len(favs)} songs)\n\nTap a song to download or 🗑️ to remove:",
        reply_markup=reply_markup
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
async def ask_platform(update: Update, context, song_name: str):
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
                        full_url = entry.get('webpage_url') or entry.get('url', '')

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
                f"❌ No results found on {platform_name}.\n\nTry the other platform or a different name."
            )
            return

        # Save in cache
        user_id = query.from_user.id
        search_cache[user_id] = results

        # Build result buttons
        keyboard = []
        for i, result in enumerate(results):
            label = f"{i+1}. {source_label} {result['title']} [{result['duration']}]"
            if len(label) > 64:
                label = label[:61] + "..."
            keyboard.append([InlineKeyboardButton(label, callback_data=f"pick_{i}")])

        # Switch platform
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
# Download music from URL and send as audio
# ─────────────────────────────────────────
async def download_and_send(message, media_url: str, title: str, user_id: str, show_fav_button: bool = True):
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

                    # Add to favourites button
                    if show_fav_button:
                        keyboard = [[
                            InlineKeyboardButton(
                                "⭐ Add to Favourites",
                                callback_data=f"fav_add_{user_id}_{media_url[:80]}"
                            )
                        ]]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                    else:
                        reply_markup = None

                    await message.reply_audio(
                        audio=open(file_path, 'rb'),
                        title=title,
                        caption=f"🎵 {title}",
                        reply_markup=reply_markup
                    )
                    return True

        return False

    except Exception as e:
        await message.reply_text(f"❌ Download failed:\n{str(e)}")
        return False


# ─────────────────────────────────────────
# Handle ALL button clicks
# ─────────────────────────────────────────
async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # ── Cancel / Close ──
    if data == "cancel":
        await query.edit_message_text("❌ Cancelled.")
        return

    # ── Platform chosen ──
    if data.startswith("platform_"):
        parts = data.split("_", 2)
        platform = parts[1]
        song_name = parts[2]
        await search_music(query, song_name, platform)
        return

    # ── User picked a search result ──
    if data.startswith("pick_"):
        index = int(data.split("_")[1])
        user_id = query.from_user.id
        str_user_id = str(user_id)

        if user_id not in search_cache or index >= len(search_cache[user_id]):
            await query.edit_message_text("❌ Session expired. Please search again.")
            return

        result = search_cache[user_id][index]
        media_url = result['url']
        title = result['title']

        # Save full URL to a separate cache for favourites use
        if str_user_id not in search_cache:
            search_cache[str_user_id] = {}
        search_cache[f"url_{user_id}"] = {'title': title, 'url': media_url}

        await query.edit_message_text(f"⏳ Downloading: {title}\nPlease wait...")
        success = await download_and_send(query.message, media_url, title, str_user_id)

        if success:
            await query.edit_message_text(f"✅ Downloaded: {title}")
        return

    # ── Add to Favourites button under audio ──
    if data.startswith("fav_add_"):
        # Format: fav_add_userid_url
        parts = data.split("_", 3)
        user_id = parts[2]
        partial_url = parts[3]

        # Get full URL from cache
        cache_key = f"url_{user_id}"
        if cache_key in search_cache:
            full_url = search_cache[cache_key]['url']
            title = search_cache[cache_key]['title']
        else:
            full_url = partial_url
            title = "Unknown"

        added = add_to_favourites(user_id, title, full_url)
        if added:
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(f"⭐ Added to favourites: {title}")
        else:
            await query.answer("Already in favourites!", show_alert=True)
        return

    # ── Play from favourites ──
    if data.startswith("fav_play_"):
        index = int(data.split("_")[2])
        user_id = str(query.from_user.id)
        favs = get_user_favourites(user_id)

        if index >= len(favs):
            await query.answer("Song not found!", show_alert=True)
            return

        fav = favs[index]
        await query.edit_message_text(f"⏳ Downloading: {fav['title']}\nPlease wait...")
        success = await download_and_send(query.message, fav['url'], fav['title'], user_id, show_fav_button=False)

        if success:
            await query.edit_message_text(f"✅ Downloaded: {fav['title']}")
        return

    # ── Delete from favourites ──
    if data.startswith("fav_del_"):
        index = int(data.split("_")[2])
        user_id = str(query.from_user.id)
        removed = remove_from_favourites(user_id, index)

        if removed:
            # Refresh the favourites list
            favs = get_user_favourites(user_id)
            if not favs:
                await query.edit_message_text("⭐ Your favourites list is now empty.")
                return

            keyboard = []
            for i, fav in enumerate(favs):
                label = f"🎵 {fav['title']}"
                if len(label) > 60:
                    label = label[:57] + "..."
                keyboard.append([
                    InlineKeyboardButton(label, callback_data=f"fav_play_{i}"),
                    InlineKeyboardButton("🗑️", callback_data=f"fav_del_{i}")
                ])
            keyboard.append([InlineKeyboardButton("❌ Close", callback_data="cancel")])
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                f"🗑️ Removed: {removed}\n\n⭐ Your Favourites ({len(favs)} songs):",
                reply_markup=reply_markup
            )
        return


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
    app.add_handler(CommandHandler("favourites", favourites_command))
    app.add_handler(CallbackQueryHandler(handle_button))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ Bot is running! Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
