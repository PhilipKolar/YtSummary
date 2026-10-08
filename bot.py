import asyncio
import os
import re
import logging
from urllib.parse import urlparse, parse_qs

import anthropic
import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

ALLOWED_USER_ID = int(os.environ["ALLOWED_USER_ID"])

claude = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

MODEL = "claude-sonnet-5-5"
EFFORT = "low"  # summarising needs little reasoning; low keeps it fast and cheap

MAX_TRANSCRIPT_CHARS = 400_000
TELEGRAM_MAX_CHARS = 4000  # Telegram message limit is 4096, leave a small buffer


VIDEO_ID_RE = re.compile(r"[A-Za-z0-9_-]{11}")
YOUTUBE_PATH_PREFIXES = ("embed", "live", "shorts", "v")


def extract_video_id(text):
    """Pull a video ID out of any common YouTube URL (watch, youtu.be, /live/, /shorts/, /embed/)."""
    for token in text.split():
        url = urlparse(token if "//" in token else "//" + token)
        host = (url.hostname or "").lower()
        if host == "youtu.be":
            parts = url.path.strip("/").split("/")
            candidate = parts[0] if parts else ""
        elif host == "youtube.com" or host.endswith(".youtube.com"):
            parts = url.path.strip("/").split("/")
            if parts[0] in YOUTUBE_PATH_PREFIXES and len(parts) > 1:
                candidate = parts[1]
            else:
                candidate = parse_qs(url.query).get("v", [""])[0]
        else:
            continue
        if VIDEO_ID_RE.fullmatch(candidate):
            return candidate
    return None


def format_timestamp(seconds):
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


LIVE_MESSAGES = {
    "is_live": "That stream is still live. Send the link again once it has ended.",
    "is_upcoming": "That stream hasn't started yet.",
    "post_live": "That stream has just ended and YouTube is still processing it. Try again in a few minutes.",
}


def get_live_status(video_id):
    """Return yt-dlp's live_status (is_live, is_upcoming, post_live, was_live, not_live) or None if unknown."""
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
        return info.get("live_status")
    except Exception as e:
        message = str(e)
        if "will begin" in message or "Premieres in" in message:
            return "is_upcoming"
        log.warning("Could not determine live status for %s: %s", video_id, message)
        return None


def build_transcript(video_id):
    api = YouTubeTranscriptApi()
    entries = api.fetch(video_id)
    lines = [f"[{format_timestamp(e.start)}] {e.text}" for e in entries]
    text = "\n".join(lines)
    if len(text) > MAX_TRANSCRIPT_CHARS:
        text = text[:MAX_TRANSCRIPT_CHARS] + "\n[transcript truncated]"
    return text


def split_message(text, max_chars=TELEGRAM_MAX_CHARS):
    """Split a long message into chunks at paragraph boundaries."""
    if len(text) <= max_chars:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_chars:
            chunks.append(text)
            break
        # Find last paragraph break within limit
        split_at = text.rfind("\n\n", 0, max_chars)
        if split_at == -1:
            # Fall back to last newline
            split_at = text.rfind("\n", 0, max_chars)
        if split_at == -1:
            # Fall back to hard cut
            split_at = max_chars
        chunks.append(text[:split_at].strip())
        text = text[split_at:].strip()

    return chunks


PROMPT = """You are summarising a YouTube video transcript for display in Telegram.

Structure your response exactly like this:

📌 *Key Points*
• 2-7 bullets, scaled to how much the video actually covers: a short single-topic clip needs only a couple, a long wide-ranging one needs more. Each bullet max 10 words. Most important takeaways only, no filler.

📝 *Summary*
2-8 short sentences, scaled the same way, each on its own line with a blank line between them. No walls of text.

Use this exact formatting — asterisks for bold headers, bullet points with •. Do not add any other headers or sections.

TRANSCRIPT:
"""


def is_allowed(update: Update) -> bool:
    return update.effective_user.id == ALLOWED_USER_ID


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    await update.message.reply_text("Send me a YouTube link and I'll summarise it.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return

    video_id = extract_video_id(update.message.text.strip())
    if not video_id:
        await update.message.reply_text("Send me a YouTube URL.")
        return

    await update.message.reply_text("Fetching transcript...")

    try:
        transcript = await asyncio.to_thread(build_transcript, video_id)
    except Exception as e:
        # Streams that are live, upcoming or still processing report "subtitles disabled",
        # so check for that before blaming the video.
        live_status = await asyncio.to_thread(get_live_status, video_id)
        if live_status in LIVE_MESSAGES:
            await update.message.reply_text(LIVE_MESSAGES[live_status])
        elif isinstance(e, TranscriptsDisabled):
            await update.message.reply_text("Transcripts are disabled for this video.")
        elif isinstance(e, NoTranscriptFound):
            await update.message.reply_text("No transcript found for this video.")
        else:
            log.exception("Failed to fetch transcript")
            await update.message.reply_text(f"Failed to fetch transcript: {e}")
        return

    await update.message.reply_text("Summarising...")

    try:
        summary = ""
        async with claude.messages.stream(
            model=MODEL,
            max_tokens=4096,  # headroom in case the model thinks before answering
            output_config={"effort": EFFORT},
            messages=[{"role": "user", "content": PROMPT + transcript}],
        ) as stream:
            async for text in stream.text_stream:
                summary += text
        summary = summary.strip()
    except Exception as e:
        log.exception("Failed to generate summary")
        await update.message.reply_text(f"Failed to generate summary: {e}")
        return

    for chunk in split_message(summary):
        await update.message.reply_text(chunk, parse_mode="Markdown")


app = ApplicationBuilder().token(os.environ["TELEGRAM_TOKEN"]).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

log.info("Bot started")
app.run_polling()
