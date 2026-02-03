# Qwen Image Bot

A Discord bot for generating and editing images using the Qwen Image Studio API.

## Features

- **Image Generation** - Generate images from text prompts using natural language or slash commands
- **Image Editing** - Edit images by uploading and describing changes
- **Re-editing** - Reply to bot-generated images to iteratively refine them
- **Automatic Image Resizing** - Large images are automatically resized (max 1024px on longest side) before upload to prevent server OOM errors
- **Job Queue** - View queue status and check on individual job progress
- **Server/Channel Restrictions** - Optionally restrict bot to specific servers or channels

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Create a Discord bot at https://discord.com/developers/applications
   - Create a new application
   - Go to "Bot" and create a bot
   - Copy the token
   - Enable "Message Content Intent" under Privileged Gateway Intents

3. Configure environment:
   ```bash
   cp .env.example .env
   # Edit .env with your Discord token and API URL
   ```

4. Invite the bot to your server with this URL (replace CLIENT_ID):
   ```
   https://discord.com/api/oauth2/authorize?client_id=CLIENT_ID&permissions=277025467456&scope=bot%20applications.commands
   ```

5. Make sure Qwen Image Studio is running, then start the bot:
   ```bash
   python bot.py
   ```

## Usage

### Natural Language (Chat)

**Generate an image:**
```
draw a cat sitting on a rainbow
```

**Edit an image:**
Upload an image and include your edit instructions in the message:
```
[attached image] make the sky purple
```

The bot will reply "Got it, I have enqueued your request" and ping you when done.

### Slash Commands

| Command | Description |
|---------|-------------|
| `/generate` | Generate an image with full options |
| `/edit` | Edit an uploaded image with full options |
| `/status` | Check the status of a job |
| `/queue` | Show current queue status |
| `/system` | Show system/GPU information |

### /generate options
- `prompt` - Description of the image to generate (required)
- `negative_prompt` - What to avoid
- `width` - Image width (default: 1024)
- `height` - Image height (default: 1024)
- `steps` - Inference steps (default: 20)
- `cfg` - CFG scale (default: 4.0)
- `seed` - Random seed for reproducibility

### /edit options
- `image` - Image attachment to edit (required)
- `prompt` - Edit instructions (required)
- `negative_prompt` - What to avoid
- `steps` - Inference steps (default: 8)
- `cfg` - CFG scale (default: 4.0)
- `seed` - Random seed for reproducibility

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DISCORD_TOKEN` | Discord bot token (required) | - |
| `API_BASE_URL` | Qwen Image Studio API URL | `http://localhost:8000` |
| `ALLOWED_GUILDS` | Comma-separated guild IDs to allow (empty = all) | - |
| `ALLOWED_CHANNELS` | Comma-separated channel IDs to allow (empty = all) | - |
| `LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR) | `INFO` |
| `JOB_TIMEOUT` | Job processing timeout in seconds | `1000` |
| `DEFAULT_GENERATION_STEPS` | Inference steps for natural language generation | `10` |
| `DEFAULT_EDIT_STEPS` | Inference steps for natural language edits | `10` |
| `MAX_IMAGE_DIMENSION` | Max image dimension before auto-resize | `1024` |
