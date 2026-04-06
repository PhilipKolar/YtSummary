import os
import re
import logging

import anthropic
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

ALLOWED_USER_ID = int(os.environ["ALLOWED_USER_ID"])

claude = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

MAX_TRANSCRIPT_CHARS = 400_000
TELEGRAM_MAX_CHARS = 4000  # Telegram message limit is 4096, leave a small buffer


def extract_video_id(text):
    match = re.search(r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([A-Za-z0-9_-]{11})', text)
    return match.group(1) if match else None


def format_timestamp(seconds):
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


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
• 3-5 bullets maximum. Each bullet max 10 words. Most important takeaways only.

📝 *Summary*
3-5 short sentences, each on its own line with a blank line between them. No walls of text.

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
        transcript = build_transcript(video_id)
    except TranscriptsDisabled:
        await update.message.reply_text("Transcripts are disabled for this video.")
        return
    except NoTranscriptFound:
        await update.message.reply_text("No transcript found for this video.")
        return
    except Exception as e:
        log.exception("Failed to fetch transcript")
        await update.message.reply_text(f"Failed to fetch transcript: {e}")
        return

    await update.message.reply_text("Summarising...")

    try:
        summary = ""
        async with claude.messages.stream(
            model="claude-opus-4-6",
            max_tokens=1024,
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
