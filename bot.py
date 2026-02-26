import os
import re
import json
import yt_dlp
import tempfile
import requests
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

# Load your secret token from the .env file
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# OMDB API key — free movie database (get yours at omdbapi.com)
OMDB_API_KEY = os.getenv("OMDB_API_KEY", "trilogy")

# Instagram link pattern
INSTAGRAM_REGEX = r'https?://(www\.)?instagram\.com/(p|reel|tv|stories)/[\w\-]+'

# Browser headers
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}

# Memory caches
search_cache = {}       # music search results
last_download = {}      # last downloaded song per user
movie_cache = {}        # movie search results per user

# Favourites file
FAVOURITES_FILE = "favourites.json"


# ─────────────────────────────────────────
# Favourites helpers
# ─────────────────────────────────────────
def load_favourites():
    if os.path.exists(FAVOURITES_FILE):
        with open(FAVOURITES_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_favourites(data):
    with open(FAVOURITES_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def get_user_favourites(user_id: str):
    return load_favourites().get(user_id, [])

def add_to_favourites(user_id: str, title: str, url: str):
    data = load_favourites()
    if user_id not in data:
        data[user_id] = []
    for item in data[user_id]:
        if item['url'] == url:
            return False
    data[user_id].append({'title': title, 'url': url})
    save_favourites(data)
    return True

def remove_from_favourites(user_id: str, index: int):
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
        "━━━━━━━━━━━━━━━━━━\n"
        "📸 INSTAGRAM\n"
        "Send any Instagram link → download it\n\n"
        "🎵 MUSIC\n"
        "Type a song name → pick & download\n"
        "Example: Blinding Lights\n\n"
        "🎬 MOVIES & SERIES\n"
        "Type /movie <name> → get info & links\n"
        "Example: /movie Inception\n"
        "Example: /movie Breaking Bad\n\n"
        "⭐ FAVOURITES\n"
        "Type /favourites → your saved songs\n\n"
        "🎤 VOICE SEARCH\n"
        "Send a voice message → music search\n"
        "━━━━━━━━━━━━━━━━━━"
    )


# ─────────────────────────────────────────
# /movie command — search films & series
# ─────────────────────────────────────────
async def movie_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "🎬 Please provide a movie or series name!\n\n"
            "Examples:\n"
            "/movie Inception\n"
            "/movie Breaking Bad\n"
            "/movie Avatar"
        )
        return

    query_text = ' '.join(context.args)
    await search_movie(update, query_text)


async def search_movie(update, query_text: str):
    msg = await update.message.reply_text(f"🔍 Searching for: {query_text}\n⏳ Please wait...")

    try:
        # Search OMDB for movies/series
        response = requests.get(
            f"http://www.omdbapi.com/?s={query_text}&apikey={OMDB_API_KEY}&type=",
            timeout=10
        )
        data = response.json()

        if data.get('Response') == 'False' or 'Search' not in data:
            await msg.edit_text(
                f"❌ No results found for: {query_text}\n\nTry a different name."
            )
            return

        results = data['Search'][:8]  # Show max 8 results
        user_id = str(update.effective_user.id)
        movie_cache[user_id] = results

        keyboard = []
        for i, item in enumerate(results):
            title = item.get('Title', 'Unknown')
            year = item.get('Year', '?')
            media_type = item.get('Type', 'movie')
            emoji = '🎬' if media_type == 'movie' else '📺'
            label = f"{emoji} {title} ({year})"
            if len(label) > 60:
                label = label[:57] + "..."
            keyboard.append([InlineKeyboardButton(label, callback_data=f"mv{i}")])

        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        await msg.edit_text(
            f"🎬 Found {len(results)} results for: *{query_text}*\n\nPick one for details:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

    except Exception as e:
        await msg.edit_text(f"❌ Search failed:\n{str(e)}")


async def show_movie_details(query, imdb_id: str):
    await query.edit_message_text("⏳ Loading details...")

    try:
        response = requests.get(
            f"http://www.omdbapi.com/?i={imdb_id}&apikey={OMDB_API_KEY}&plot=full",
            timeout=10
        )
        data = response.json()

        if data.get('Response') == 'False':
            await query.edit_message_text("❌ Could not load details.")
            return

        title = data.get('Title', 'Unknown')
        year = data.get('Year', '?')
        genre = data.get('Genre', '?')
        rating = data.get('imdbRating', '?')
        plot = data.get('Plot', 'No description available.')
        runtime = data.get('Runtime', '?')
        director = data.get('Director', '?')
        actors = data.get('Actors', '?')
        media_type = data.get('Type', 'movie')
        total_seasons = data.get('totalSeasons', '')
        language = data.get('Language', '?')
        awards = data.get('Awards', '')

        # Build info message
        emoji = '🎬' if media_type == 'movie' else '📺'
        seasons_text = f"\n📅 Seasons: {total_seasons}" if total_seasons else ""

        info = (
            f"{emoji} *{title}* ({year})\n"
            f"━━━━━━━━━━━━━━━\n"
            f"⭐ IMDb: {rating}/10\n"
            f"🎭 Genre: {genre}\n"
            f"⏱ Runtime: {runtime}"
            f"{seasons_text}\n"
            f"🌍 Language: {language}\n"
            f"🎥 Director: {director}\n"
            f"👥 Cast: {actors}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📖 {plot}\n"
        )

        if awards and awards != 'N/A':
            info += f"━━━━━━━━━━━━━━━\n🏆 {awards}\n"

        # Build watch links buttons
        keyboard = [
            [
                InlineKeyboardButton("▶️ Watch on YouTube", url=f"https://www.youtube.com/results?search_query={title}+{year}+full+movie"),
            ],
            [
                InlineKeyboardButton("🔍 Search on Google", url=f"https://www.google.com/search?q=watch+{title}+{year}+online+free"),
            ],
            [
                InlineKeyboardButton("📊 IMDb Page", url=f"https://www.imdb.com/title/{imdb_id}"),
            ],
            [InlineKeyboardButton("🔙 Back to results", callback_data="mvback")],
        ]

        # Add trailer button
        keyboard.insert(0, [
            InlineKeyboardButton("🎞 Watch Trailer", url=f"https://www.youtube.com/results?search_query={title}+{year}+official+trailer"),
        ])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            info,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

    except Exception as e:
        await query.edit_message_text(f"❌ Failed to load details:\n{str(e)}")


# ─────────────────────────────────────────
# /favourites command
# ─────────────────────────────────────────
async def favourites_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    favs = get_user_favourites(user_id)

    if not favs:
        await update.message.reply_text(
            "⭐ Your favourites list is empty!\n\n"
            "Search for a song and tap ⭐ Add to Favourites."
        )
        return

    await show_favourites_menu(update.message, user_id, favs)


async def show_favourites_menu(message, user_id: str, favs: list, edit: bool = False):
    keyboard = []
    for i, fav in enumerate(favs):
        label = f"🎵 {fav['title']}"
        if len(label) > 55:
            label = label[:52] + "..."
        keyboard.append([
            InlineKeyboardButton(label, callback_data=f"fp{i}"),
            InlineKeyboardButton("🗑️", callback_data=f"fd{i}")
        ])
    keyboard.append([InlineKeyboardButton("❌ Close", callback_data="cancel")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = f"⭐ Your Favourites ({len(favs)} songs)\n\nTap to download or 🗑️ to remove:"

    if edit:
        await message.edit_text(text, reply_markup=reply_markup)
    else:
        await message.reply_text(text, reply_markup=reply_markup)


# ─────────────────────────────────────────
# Handle all text messages
# ─────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # Instagram link
    match = re.search(INSTAGRAM_REGEX, text)
    if match:
        url = match.group(0)
        await update.message.reply_text("⏳ Downloading Instagram media... please wait.")
        await download_instagram(update, url)
        return

    # Otherwise music search
    await ask_platform(update, text)


# ─────────────────────────────────────────
# Ask platform for music
# ─────────────────────────────────────────
async def ask_platform(update, song_name: str):
    short_name = song_name[:40] if len(song_name) > 40 else song_name
    keyboard = [
        [
            InlineKeyboardButton("🎬 YouTube", callback_data=f"pyt_{short_name}"),
            InlineKeyboardButton("☁️ SoundCloud", callback_data=f"psc_{short_name}"),
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
# Search music
# ─────────────────────────────────────────
async def search_music(query, song_name: str, platform: str):
    platform_name = 'YouTube' if platform == 'yt' else 'SoundCloud'
    source_label = '🎬' if platform == 'yt' else '☁️'

    await query.edit_message_text(f"🔍 Searching {platform_name}: {song_name}\n⏳ Please wait...")

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
                            results.append({'title': title, 'url': full_url, 'duration': duration})

        if not results:
            await query.edit_message_text(f"❌ No results on {platform_name}. Try the other platform.")
            return

        user_id = query.from_user.id
        search_cache[user_id] = results

        keyboard = []
        for i, result in enumerate(results):
            label = f"{i+1}. {source_label} {result['title']} [{result['duration']}]"
            if len(label) > 64:
                label = label[:61] + "..."
            keyboard.append([InlineKeyboardButton(label, callback_data=f"pick{i}")])

        short_name = song_name[:35] if len(song_name) > 35 else song_name
        other = 'sc' if platform == 'yt' else 'yt'
        other_label = '☁️ Try SoundCloud' if platform == 'yt' else '🎬 Try YouTube'
        keyboard.append([InlineKeyboardButton(other_label, callback_data=f"p{other}_{short_name}")])
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"🎵 {len(results)} results for: *{song_name}*\n\nPick one:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

    except Exception as e:
        await query.edit_message_text(f"❌ Search failed.\nError: {str(e)}")


# ─────────────────────────────────────────
# Download and send audio
# ─────────────────────────────────────────
async def download_and_send(message, media_url: str, title: str, user_id: str, show_fav_btn: bool = True):
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
                    last_download[user_id] = {'title': title, 'url': media_url}

                    if show_fav_btn:
                        keyboard = [[InlineKeyboardButton("⭐ Add to Favourites", callback_data="favadd")]]
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
    user_id = str(query.from_user.id)
    int_user_id = query.from_user.id

    # ── Cancel ──
    if data == "cancel":
        await query.edit_message_text("❌ Cancelled.")
        return

    # ── Platform chosen ──
    if data.startswith("pyt_") or data.startswith("psc_"):
        platform = data[1:3]
        song_name = data[4:]
        await search_music(query, song_name, platform)
        return

    # ── Music result picked ──
    if data.startswith("pick"):
        index = int(data[4:])
        if int_user_id not in search_cache or index >= len(search_cache[int_user_id]):
            await query.edit_message_text("❌ Session expired. Please search again.")
            return
        result = search_cache[int_user_id][index]
        await query.edit_message_text(f"⏳ Downloading: {result['title']}\nPlease wait...")
        success = await download_and_send(query.message, result['url'], result['title'], user_id)
        if success:
            await query.edit_message_text(f"✅ Downloaded: {result['title']}")
        return

    # ── Add to Favourites ──
    if data == "favadd":
        if user_id not in last_download:
            await query.answer("❌ Could not find song info.", show_alert=True)
            return
        info = last_download[user_id]
        added = add_to_favourites(user_id, info['title'], info['url'])
        if added:
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(f"⭐ Saved: {info['title']}")
        else:
            await query.answer("Already in favourites!", show_alert=True)
        return

    # ── Play from favourites ──
    if data.startswith("fp"):
        index = int(data[2:])
        favs = get_user_favourites(user_id)
        if index >= len(favs):
            await query.answer("Song not found!", show_alert=True)
            return
        fav = favs[index]
        await query.edit_message_text(f"⏳ Downloading: {fav['title']}\nPlease wait...")
        success = await download_and_send(query.message, fav['url'], fav['title'], user_id, show_fav_btn=False)
        if success:
            await query.edit_message_text(f"✅ Downloaded: {fav['title']}")
        return

    # ── Delete from favourites ──
    if data.startswith("fd"):
        index = int(data[2:])
        removed = remove_from_favourites(user_id, index)
        if removed:
            favs = get_user_favourites(user_id)
            if not favs:
                await query.edit_message_text(f"🗑️ Removed: {removed}\n\n⭐ Favourites list is now empty.")
                return
            await show_favourites_menu(query, user_id, favs, edit=True)
        return

    # ── Movie result picked ──
    if data.startswith("mv") and not data.startswith("mvback"):
        index = int(data[2:])
        if user_id not in movie_cache or index >= len(movie_cache[user_id]):
            await query.edit_message_text("❌ Session expired. Please search again.")
            return
        item = movie_cache[user_id][index]
        imdb_id = item.get('imdbID', '')
        # Save last search for back button
        movie_cache[f"last_{user_id}"] = movie_cache[user_id]
        await show_movie_details(query, imdb_id)
        return

    # ── Back to movie results ──
    if data == "mvback":
        results = movie_cache.get(f"last_{user_id}", [])
        if not results:
            await query.edit_message_text("❌ Session expired. Please search again.")
            return
        keyboard = []
        for i, item in enumerate(results):
            title = item.get('Title', 'Unknown')
            year = item.get('Year', '?')
            media_type = item.get('Type', 'movie')
            emoji = '🎬' if media_type == 'movie' else '📺'
            label = f"{emoji} {title} ({year})"
            if len(label) > 60:
                label = label[:57] + "..."
            keyboard.append([InlineKeyboardButton(label, callback_data=f"mv{i}")])
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "🎬 Pick a movie or series:",
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
                await ask_platform(update, song_name)

            except ImportError:
                await update.message.reply_text(
                    "⚠️ Voice recognition not available.\n\nPlease type the song name instead."
                )

    except Exception as e:
        await update.message.reply_text(f"❌ Could not process voice:\n{str(e)}")


# ─────────────────────────────────────────
# Start the bot
# ─────────────────────────────────────────
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("movie", movie_command))
    app.add_handler(CommandHandler("favourites", favourites_command))
    app.add_handler(CallbackQueryHandler(handle_button))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ Bot is running! Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
