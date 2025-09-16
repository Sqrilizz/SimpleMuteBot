---

# SimpleMuteBot

A Discord moderation bot with automatic message filters and multi-language support.

## Key Features

### Language Support

* Automatic server language detection
* Easy setup via `/setup`
* Supports Russian and English
* Localized responses and commands

### Automatic Filters

1. **Anti-Spam** – Mutes users for flooding and spamming
2. **Anti-Caps** – Mutes users for excessive use of uppercase letters
3. **Link Filter** – Protects against unwanted links
4. **Auto-Unmute** – Automatically removes mute after the set duration

### Moderation Commands

* `/mute` (`/мут`) – Mute a user
* `/unmute` (`/размут`) – Remove mute
* `/ban` (`/бан`) – Ban a user
* `/unban` (`/разбан`) – Unban a user
* `/kick` (`/кик`) – Kick a user
* `/timeout` – Temporary restriction
* `/setup` – Configure the bot

### Logging

* Detailed logging of all actions
* Customizable log channel
* Mute history tracking

### Filter Management Commands

* `/filterstats` – Show filter statistics
* `/filterrules` – Show filter rules

## Quick Start

### Installation

1. Clone the repository:

```bash
git clone https://github.com/your-username/SimpleMuteBot.git
cd SimpleMuteBot
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

### Configuration

1. Create a bot in the [Discord Developer Portal](https://discord.com/developers/applications)

2. Invite the bot to your server with permissions:

   * Read/Send Messages
   * Ban Members
   * Timeouts
   * Manage Roles

3. Configure `config.py`:

```python
DISCORD_TOKEN = "your_bot_token"
LOG_CHANNEL_ID = 1234567890  # Log channel ID
SUPPRESS_LOGS = False  # Disable console logs
```

4. Run the bot:

```bash
python main.py
```

5. Set the server language:

```
/setup language: English
```

## Advanced Settings

### Filter Configuration

File: `filter_config.py`

```python
FILTER_CONFIG = {
    "spam": {
        "threshold": 3,  # Number of messages
        "time_window": 120,  # Time in seconds
        "mute_duration": "5m"  # Mute duration
    },
    "caps": {
        "threshold": 0.75,  # Caps percentage
        "min_length": 5,  # Minimum message length
        "mute_duration": "5m"
    },
    "links": {
        "mute_duration": "10m",
        "forbidden_links": ["discord.gg", "t.me"],  # Removed
        "allowed_websites": ["youtube.com", "github.com"]  # Allowed
    }
}
```

## Run

```bash
python main.py
```

## Run Web Panel

```bash
python webpanel.py
```

## Filter Rules

### Spam

* Monitors user message count
* Exceeding the limit → automatic mute
* Example: 3 messages in 2 minutes → 5-minute mute

### Caps

* Checks uppercase percentage
* Ignores messages shorter than 5 characters
* Default: more than 75% uppercase letters

### Links

* **Forbidden**: Discord, Telegram links (removed)
* **Allowed**: YouTube, GitHub, Wikipedia, etc. (allowed)
* **Other**: All other links → 10-minute mute
