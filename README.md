# YT Summary Bot

A Telegram bot that produces a comprehensive summary of any YouTube video, detailed enough to replace watching it.

Send a YouTube link and the bot replies with an overview, a bullet list of key points, and a full written summary of the content.

## How it works

1. You send a YouTube URL to the bot
2. The bot fetches the video's transcript via YouTube's caption system
3. The transcript is sent to Claude API which produces a structured summary
4. The bot replies with the summary, split across multiple messages if needed

## Requirements

- Python 3.10+
- A Telegram account
- An Anthropic API account (pay-as-you-go credits)

## Setup

### 1. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/yt-summary.git
cd yt-summary
python3 -m venv venv
source venv/bin/activate
pip install python-telegram-bot anthropic youtube-transcript-api python-dotenv
```

### 2. Create a Telegram bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot` and follow the prompts
3. Copy the token BotFather gives you

### 3. Get your Telegram user ID

1. Search for **@userinfobot** on Telegram and start it
2. Copy your numeric user ID

### 4. Get a Claude API key

1. Sign up at [console.anthropic.com](https://console.anthropic.com)
2. Go to **API Keys** → **Create Key** — copy it (shown once only)
3. Add billing credits under **Plans & Billing**

### 5. Configure secrets

```bash
cp .env.example .env
```

Edit `.env`:

```
TELEGRAM_TOKEN=        # From BotFather
ANTHROPIC_API_KEY=     # From console.anthropic.com
ALLOWED_USER_ID=       # Your numeric Telegram user ID from @userinfobot
```

### 6. Test manually

```bash
source venv/bin/activate
python3 bot.py
```

Send a YouTube URL to your bot. It will reply with a structured summary.

Press `Ctrl+C` to stop when done testing.

### 7. Run as a background service (Linux/systemd)

```bash
sudo cp yt-summary.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now yt-summary
```

### 8. Auto-restart on file changes

```bash
sudo cp yt-summary-watch.path /etc/systemd/system/
sudo cp yt-summary-watch.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now yt-summary-watch.path
```

## Managing the service

```bash
# Check status
sudo systemctl status yt-summary

# View logs (live)
journalctl -u yt-summary -f

# Restart manually
sudo systemctl restart yt-summary

# Stop
sudo systemctl stop yt-summary
```

## Limitations

- Only works for videos that have captions (auto-generated or manual)
- Very long videos (3+ hours) will have their transcript trimmed to fit the model's context window

## Secrets reference

| Secret | Where to get it |
|--------|----------------|
| `TELEGRAM_TOKEN` | @BotFather on Telegram |
| `ANTHROPIC_API_KEY` | console.anthropic.com → API Keys |
| `ALLOWED_USER_ID` | Your numeric Telegram user ID — get it from @userinfobot |
