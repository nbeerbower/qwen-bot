import os
import asyncio
import logging
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from io import BytesIO
from PIL import Image

load_dotenv()

# Setup logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("qwen-bot")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

# Server/channel restrictions (comma-separated IDs, empty = allow all)
ALLOWED_GUILDS = [int(x.strip()) for x in os.getenv("ALLOWED_GUILDS", "").split(",") if x.strip()]
ALLOWED_CHANNELS = [int(x.strip()) for x in os.getenv("ALLOWED_CHANNELS", "").split(",") if x.strip()]

# DM restrictions (comma-separated user IDs, empty = no DMs allowed)
ALLOWED_DMS = [int(x.strip()) for x in os.getenv("ALLOWED_DMS", "").split(",") if x.strip()]

# Job timeout in seconds
JOB_TIMEOUT = int(os.getenv("JOB_TIMEOUT", "1000"))

# Default inference steps for natural language commands
DEFAULT_GENERATION_STEPS = int(os.getenv("DEFAULT_GENERATION_STEPS", "10"))
DEFAULT_EDIT_STEPS = int(os.getenv("DEFAULT_EDIT_STEPS", "10"))

# Max image dimension (longest side) to prevent OOM on server
MAX_IMAGE_DIMENSION = int(os.getenv("MAX_IMAGE_DIMENSION", "1024"))

# Log config on startup
logger.info(f"API_BASE_URL: {API_BASE_URL}")
logger.info(f"ALLOWED_GUILDS: {ALLOWED_GUILDS if ALLOWED_GUILDS else 'all'}")
logger.info(f"ALLOWED_CHANNELS: {ALLOWED_CHANNELS if ALLOWED_CHANNELS else 'all'}")
logger.info(f"ALLOWED_DMS: {ALLOWED_DMS if ALLOWED_DMS else 'none'}")
logger.info(f"JOB_TIMEOUT: {JOB_TIMEOUT}s")
logger.info(f"DEFAULT_GENERATION_STEPS: {DEFAULT_GENERATION_STEPS}")
logger.info(f"DEFAULT_EDIT_STEPS: {DEFAULT_EDIT_STEPS}")
logger.info(f"MAX_IMAGE_DIMENSION: {MAX_IMAGE_DIMENSION}")


def is_allowed(guild_id: int | None, channel_id: int | None, user_id: int | None = None) -> bool:
    """Check if the bot is allowed to respond in this guild/channel/DM."""
    # Handle DMs (guild_id is None)
    if guild_id is None:
        # DMs are only allowed for users in ALLOWED_DMS list
        if user_id is not None and user_id in ALLOWED_DMS:
            logger.debug(f"DM allowed for user {user_id}")
            return True
        logger.debug(f"DM rejected for user {user_id} (not in ALLOWED_DMS)")
        return False

    # Check guild restriction
    if ALLOWED_GUILDS and guild_id not in ALLOWED_GUILDS:
        logger.debug(f"Guild {guild_id} not in allowed list")
        return False
    # Check channel restriction
    if ALLOWED_CHANNELS and channel_id not in ALLOWED_CHANNELS:
        logger.debug(f"Channel {channel_id} not in allowed list")
        return False
    return True

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


async def poll_job_status(session: aiohttp.ClientSession, job_id: str, timeout: int = None) -> dict:
    if timeout is None:
        timeout = JOB_TIMEOUT
    """Poll for job completion with timeout."""
    logger.info(f"[{job_id}] Starting to poll job status (timeout={timeout}s)")
    processing_start_time = None  # Only set when job starts processing
    poll_count = 0
    while True:
        poll_count += 1
        async with session.get(f"{API_BASE_URL}/status/{job_id}") as resp:
            if resp.status != 200:
                logger.error(f"[{job_id}] Failed to get job status: HTTP {resp.status}")
                raise Exception(f"Failed to get job status: {resp.status}")
            data = await resp.json()

            status = data["status"]
            progress = data.get("progress")
            logger.debug(f"[{job_id}] Poll #{poll_count}: status={status}, progress={progress}")

            if status == "completed":
                if processing_start_time:
                    elapsed = asyncio.get_event_loop().time() - processing_start_time
                    logger.info(f"[{job_id}] Job completed in {elapsed:.1f}s processing time after {poll_count} polls")
                else:
                    logger.info(f"[{job_id}] Job completed after {poll_count} polls")
                return data
            elif status == "failed":
                error = data.get("error", "Job failed")
                logger.error(f"[{job_id}] Job failed: {error}")
                raise Exception(error)
            elif status != "queued" and processing_start_time is None:
                # Job has started processing (not queued anymore)
                processing_start_time = asyncio.get_event_loop().time()
                logger.info(f"[{job_id}] Job started processing")

            # Only apply timeout once processing has started
            if processing_start_time is not None:
                elapsed = asyncio.get_event_loop().time() - processing_start_time
                if elapsed > timeout:
                    logger.error(f"[{job_id}] Job timed out after {elapsed:.1f}s of processing")
                    raise Exception("Job timed out")

            await asyncio.sleep(2)


async def download_image(session: aiohttp.ClientSession, image_url: str) -> bytes:
    """Download image from API server."""
    full_url = f"{API_BASE_URL}{image_url}"
    logger.debug(f"Downloading image from {full_url}")
    async with session.get(full_url) as resp:
        if resp.status != 200:
            logger.error(f"Failed to download image: HTTP {resp.status}")
            raise Exception(f"Failed to download image: {resp.status}")
        data = await resp.read()
        logger.debug(f"Downloaded image: {len(data)} bytes")
        return data


def resize_image_if_needed(image_data: bytes, max_dimension: int = None) -> bytes:
    """Resize image if longest dimension exceeds max_dimension, preserving aspect ratio."""
    if max_dimension is None:
        max_dimension = MAX_IMAGE_DIMENSION

    img = Image.open(BytesIO(image_data))
    original_size = img.size
    width, height = original_size

    # Check if resize is needed
    longest_side = max(width, height)
    if longest_side <= max_dimension:
        logger.debug(f"Image {width}x{height} within limit, no resize needed")
        return image_data

    # Calculate new dimensions preserving aspect ratio
    scale = max_dimension / longest_side
    new_width = int(width * scale)
    new_height = int(height * scale)

    logger.info(f"Resizing image from {width}x{height} to {new_width}x{new_height}")

    # Resize with high quality
    img_resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

    # Save to bytes, preserving format if possible
    output = BytesIO()
    img_format = img.format or "PNG"
    if img_format.upper() == "JPEG":
        img_resized.save(output, format=img_format, quality=95)
    else:
        img_resized.save(output, format=img_format)

    result = output.getvalue()
    logger.debug(f"Resized image: {len(image_data)} -> {len(result)} bytes")
    return result


@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    logger.info(f"Connected to {len(bot.guilds)} guild(s)")
    for guild in bot.guilds:
        logger.info(f"  - {guild.name} (ID: {guild.id})")
    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} slash command(s)")
    except Exception as e:
        logger.error(f"Failed to sync commands: {e}")


@bot.event
async def on_message(message: discord.Message):
    # Ignore messages from the bot itself
    if message.author == bot.user:
        return

    # Check server/channel restrictions
    guild_id = message.guild.id if message.guild else None
    guild_name = message.guild.name if message.guild else "DM"
    channel_name = getattr(message.channel, 'name', 'DM')

    if not is_allowed(guild_id, message.channel.id, message.author.id):
        logger.debug(f"Ignoring message from {message.author} in {guild_name}/#{channel_name} (not allowed)")
        return

    # Check if this is a reply to a bot message with an image -> re-edit mode
    if message.reference and message.content.strip():
        try:
            referenced_msg = await message.channel.fetch_message(message.reference.message_id)
            if referenced_msg.author == bot.user:
                # Check if the referenced message has an image attachment
                ref_image_attachments = [
                    a for a in referenced_msg.attachments
                    if a.content_type and a.content_type.startswith("image/")
                ]
                if ref_image_attachments:
                    logger.info(f"Re-edit request from {message.author} in {guild_name}/#{channel_name}: replying to bot message with {len(ref_image_attachments)} image(s), prompt={message.content.strip()[:50]}...")
                    await handle_reply_edit(message, ref_image_attachments, message.content.strip())
                    return
        except discord.NotFound:
            logger.debug(f"Referenced message not found for reply from {message.author}")
        except Exception as e:
            logger.warning(f"Failed to fetch referenced message: {e}")

    # Check if message has image attachments with text and mentions the bot -> edit mode
    image_attachments = [a for a in message.attachments if a.content_type and a.content_type.startswith("image/")]

    if image_attachments and message.content.strip() and bot.user.mentioned_in(message):
        # Remove the bot mention from the prompt
        prompt = message.content.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip()
        if prompt:
            logger.info(f"Edit request from {message.author} in {guild_name}/#{channel_name}: {len(image_attachments)} image(s), prompt={prompt[:50]}...")
            await handle_edit_message(message, image_attachments, prompt)
            return

    # Check for "draw [prompt]" pattern
    content_lower = message.content.lower().strip()
    if content_lower.startswith("draw "):
        prompt = message.content.strip()[5:].strip()  # Get everything after "draw "
        if prompt:
            logger.info(f"Draw request from {message.author} in {guild_name}/#{channel_name}: {prompt[:50]}...")
            await handle_generate_message(message, prompt)
            return

    # Process other commands
    await bot.process_commands(message)


async def handle_generate_message(message: discord.Message, prompt: str):
    """Handle natural language generation request."""
    # Reply to acknowledge
    reply = await message.reply("Got it, I have enqueued your request.")

    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "prompt": prompt,
                "negative_prompt": "",
                "width": 768,
                "height": 768,
                "num_inference_steps": DEFAULT_GENERATION_STEPS,
                "cfg_scale": 4.0,
                "seed": None
            }

            logger.debug(f"Submitting generate job to API: {payload}")
            async with session.post(f"{API_BASE_URL}/generate", json=payload) as resp:
                if resp.status == 503:
                    logger.warning("Generation pipeline unavailable (503)")
                    await reply.edit(content="Sorry, the generation pipeline is not available right now.")
                    return
                if resp.status != 200:
                    logger.error(f"Failed to submit generate job: HTTP {resp.status}")
                    await reply.edit(content=f"Failed to submit job: {resp.status}")
                    return
                data = await resp.json()
                job_id = data["job_id"]
                logger.info(f"[{job_id}] Generate job submitted for user {message.author}")

            # Poll for completion
            result = await poll_job_status(session, job_id)

            # Download and send image
            image_data = await download_image(session, result["output_image_url"])
            file = discord.File(BytesIO(image_data), filename="generated.png")

            # Ping user with result
            await message.channel.send(
                content=f"{message.author.mention} Here's your image!",
                file=file,
                reference=message
            )
            logger.info(f"[{job_id}] Delivered generated image to {message.author}")

    except Exception as e:
        logger.error(f"Generate request failed for {message.author}: {e}", exc_info=True)
        await message.channel.send(
            content=f"{message.author.mention} Sorry, something went wrong: {str(e)}",
            reference=message
        )


async def handle_edit_message(message: discord.Message, attachments: list, prompt: str):
    """Handle natural language edit request (supports multiple images with 2509/2511 models)."""
    # Reply to acknowledge
    img_count = len(attachments)
    ack_msg = f"Got it, I have enqueued your request with {img_count} image(s)." if img_count > 1 else "Got it, I have enqueued your request."
    reply = await message.reply(ack_msg)

    try:
        async with aiohttp.ClientSession() as session:
            # Prepare multipart form data with all images
            form = aiohttp.FormData()

            for attachment in attachments:
                logger.debug(f"Downloading attachment: {attachment.filename} ({attachment.content_type})")
                image_data = await attachment.read()
                logger.debug(f"Downloaded attachment: {len(image_data)} bytes")

                # Resize image if needed to prevent OOM on server
                image_data = resize_image_if_needed(image_data)

                # Add each image with the same field name (multipart form supports repeated fields)
                form.add_field("images", image_data, filename=attachment.filename, content_type=attachment.content_type)

            form.add_field("prompt", prompt)
            form.add_field("negative_prompt", "")
            form.add_field("num_inference_steps", str(DEFAULT_EDIT_STEPS))
            form.add_field("cfg_scale", "4.0")

            logger.debug(f"Submitting edit job to API")
            async with session.post(f"{API_BASE_URL}/edit", data=form) as resp:
                if resp.status == 503:
                    logger.warning("Edit pipeline unavailable (503)")
                    await reply.edit(content="Sorry, the edit pipeline is not available right now.")
                    return
                if resp.status == 400:
                    error_data = await resp.json()
                    error_detail = error_data.get('detail', 'Unknown error')
                    logger.warning(f"Edit request rejected (400): {error_detail}")
                    await reply.edit(content=f"Invalid request: {error_detail}")
                    return
                if resp.status != 200:
                    logger.error(f"Failed to submit edit job: HTTP {resp.status}")
                    await reply.edit(content=f"Failed to submit job: {resp.status}")
                    return
                data = await resp.json()
                job_id = data["job_id"]
                logger.info(f"[{job_id}] Edit job submitted for user {message.author}")

            # Poll for completion
            result = await poll_job_status(session, job_id)

            # Download and send image
            output_data = await download_image(session, result["output_image_url"])
            file = discord.File(BytesIO(output_data), filename="edited.png")

            # Ping user with result
            await message.channel.send(
                content=f"{message.author.mention} Here's your edited image!",
                file=file,
                reference=message
            )
            logger.info(f"[{job_id}] Delivered edited image to {message.author}")

    except Exception as e:
        logger.error(f"Edit request failed for {message.author}: {e}", exc_info=True)
        await message.channel.send(
            content=f"{message.author.mention} Sorry, something went wrong: {str(e)}",
            reference=message
        )


async def handle_reply_edit(message: discord.Message, attachments: list, prompt: str):
    """Handle edit request by replying to a bot-generated image (supports multiple images with 2509/2511 models)."""
    # Reply to acknowledge
    img_count = len(attachments)
    ack_msg = f"Got it, I have enqueued your request with {img_count} image(s)." if img_count > 1 else "Got it, I have enqueued your request."
    reply = await message.reply(ack_msg)

    try:
        async with aiohttp.ClientSession() as session:
            # Prepare multipart form data with all images from the referenced message
            form = aiohttp.FormData()

            for attachment in attachments:
                logger.debug(f"Downloading bot's previous image: {attachment.filename} ({attachment.content_type})")
                image_data = await attachment.read()
                logger.debug(f"Downloaded attachment: {len(image_data)} bytes")

                # Resize image if needed to prevent OOM on server
                image_data = resize_image_if_needed(image_data)

                # Add each image with the same field name (multipart form supports repeated fields)
                form.add_field("images", image_data, filename=attachment.filename, content_type=attachment.content_type)

            form.add_field("prompt", prompt)
            form.add_field("negative_prompt", "")
            form.add_field("num_inference_steps", str(DEFAULT_EDIT_STEPS))
            form.add_field("cfg_scale", "4.0")

            logger.debug(f"Submitting re-edit job to API")
            async with session.post(f"{API_BASE_URL}/edit", data=form) as resp:
                if resp.status == 503:
                    logger.warning("Edit pipeline unavailable (503)")
                    await reply.edit(content="Sorry, the edit pipeline is not available right now.")
                    return
                if resp.status == 400:
                    error_data = await resp.json()
                    error_detail = error_data.get('detail', 'Unknown error')
                    logger.warning(f"Re-edit request rejected (400): {error_detail}")
                    await reply.edit(content=f"Invalid request: {error_detail}")
                    return
                if resp.status != 200:
                    logger.error(f"Failed to submit re-edit job: HTTP {resp.status}")
                    await reply.edit(content=f"Failed to submit job: {resp.status}")
                    return
                data = await resp.json()
                job_id = data["job_id"]
                logger.info(f"[{job_id}] Re-edit job submitted for user {message.author}")

            # Poll for completion
            result = await poll_job_status(session, job_id)

            # Download and send image
            output_data = await download_image(session, result["output_image_url"])
            file = discord.File(BytesIO(output_data), filename="edited.png")

            # Ping user with result
            await message.channel.send(
                content=f"{message.author.mention} Here's your edited image!",
                file=file,
                reference=message
            )
            logger.info(f"[{job_id}] Delivered re-edited image to {message.author}")

    except Exception as e:
        logger.error(f"Re-edit request failed for {message.author}: {e}", exc_info=True)
        await message.channel.send(
            content=f"{message.author.mention} Sorry, something went wrong: {str(e)}",
            reference=message
        )


@bot.tree.command(name="generate", description="Generate an image from a text prompt")
@app_commands.describe(
    prompt="Description of the image to generate",
    negative_prompt="What to avoid in the image",
    width="Image width (default: 1024)",
    height="Image height (default: 1024)",
    steps="Number of inference steps (default: 8)",
    cfg="CFG scale (default: 4.0)",
    seed="Random seed for reproducibility"
)
async def generate(
    interaction: discord.Interaction,
    prompt: str,
    negative_prompt: str = "",
    width: int = 1024,
    height: int = 1024,
    steps: int = 8,
    cfg: float = 4.0,
    seed: int = None
):
    guild_name = interaction.guild.name if interaction.guild else "DM"
    channel_name = getattr(interaction.channel, 'name', 'DM')
    user = interaction.user

    guild_id = interaction.guild_id
    channel_id = interaction.channel_id
    if not is_allowed(guild_id, channel_id, user.id):
        logger.info(f"/generate blocked for {user} in {guild_name}/#{channel_name} (not allowed)")
        await interaction.response.send_message("This command is not available here.", ephemeral=True)
        return

    logger.info(f"/generate from {user} in {guild_name}/#{channel_name}: prompt={prompt[:50]}..., size={width}x{height}, steps={steps}")
    await interaction.response.defer(thinking=True)

    try:
        async with aiohttp.ClientSession() as session:
            # Submit generation job
            payload = {
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "width": width,
                "height": height,
                "num_inference_steps": steps,
                "cfg_scale": cfg,
                "seed": seed
            }

            logger.debug(f"Submitting generate job to API: {payload}")
            async with session.post(f"{API_BASE_URL}/generate", json=payload) as resp:
                if resp.status == 503:
                    logger.warning(f"Generation pipeline unavailable (503) for {user}")
                    await interaction.followup.send("Generation pipeline is not available.")
                    return
                if resp.status != 200:
                    logger.error(f"Failed to submit generate job: HTTP {resp.status}")
                    await interaction.followup.send(f"Failed to submit job: {resp.status}")
                    return
                data = await resp.json()
                job_id = data["job_id"]
                logger.info(f"[{job_id}] Generate job submitted for {user}")

            await interaction.followup.send(f"Generating image... (Job ID: `{job_id}`)")

            # Poll for completion
            result = await poll_job_status(session, job_id)

            # Download and send image
            image_data = await download_image(session, result["output_image_url"])
            file = discord.File(BytesIO(image_data), filename="generated.png")

            embed = discord.Embed(title="Generated Image", color=0x00ff00)
            embed.add_field(name="Prompt", value=prompt[:1024], inline=False)
            if negative_prompt:
                embed.add_field(name="Negative Prompt", value=negative_prompt[:1024], inline=False)
            embed.add_field(name="Size", value=f"{width}x{height}", inline=True)
            embed.add_field(name="Steps", value=str(steps), inline=True)
            embed.add_field(name="CFG", value=str(cfg), inline=True)
            embed.set_image(url="attachment://generated.png")

            await interaction.channel.send(embed=embed, file=file)
            logger.info(f"[{job_id}] Delivered generated image to {user}")

    except Exception as e:
        logger.error(f"/generate failed for {user}: {e}", exc_info=True)
        await interaction.followup.send(f"Error: {str(e)}")


@bot.tree.command(name="edit", description="Edit an image using AI")
@app_commands.describe(
    image="The image to edit",
    prompt="Instructions for how to edit the image",
    negative_prompt="What to avoid in the edit",
    steps="Number of inference steps (default: 8)",
    cfg="CFG scale (default: 4.0)",
    seed="Random seed for reproducibility"
)
async def edit(
    interaction: discord.Interaction,
    image: discord.Attachment,
    prompt: str,
    negative_prompt: str = "",
    steps: int = 8,
    cfg: float = 4.0,
    seed: int = None
):
    guild_name = interaction.guild.name if interaction.guild else "DM"
    channel_name = getattr(interaction.channel, 'name', 'DM')
    user = interaction.user

    guild_id = interaction.guild_id
    channel_id = interaction.channel_id
    if not is_allowed(guild_id, channel_id, user.id):
        logger.info(f"/edit blocked for {user} in {guild_name}/#{channel_name} (not allowed)")
        await interaction.response.send_message("This command is not available here.", ephemeral=True)
        return

    logger.info(f"/edit from {user} in {guild_name}/#{channel_name}: image={image.filename}, prompt={prompt[:50]}...")
    await interaction.response.defer(thinking=True)

    # Validate attachment is an image
    if not image.content_type or not image.content_type.startswith("image/"):
        logger.warning(f"/edit from {user}: invalid attachment type {image.content_type}")
        await interaction.followup.send("Please attach a valid image file.")
        return

    try:
        async with aiohttp.ClientSession() as session:
            # Download the attachment
            logger.debug(f"Downloading attachment: {image.filename} ({image.content_type})")
            image_data = await image.read()
            logger.debug(f"Downloaded attachment: {len(image_data)} bytes")

            # Resize image if needed to prevent OOM on server
            image_data = resize_image_if_needed(image_data)

            # Prepare multipart form data
            form = aiohttp.FormData()
            form.add_field("images", image_data, filename=image.filename, content_type=image.content_type)
            form.add_field("prompt", prompt)
            form.add_field("negative_prompt", negative_prompt or "")
            form.add_field("num_inference_steps", str(steps))
            form.add_field("cfg_scale", str(cfg))
            if seed is not None:
                form.add_field("seed", str(seed))

            logger.debug(f"Submitting edit job to API")
            async with session.post(f"{API_BASE_URL}/edit", data=form) as resp:
                if resp.status == 503:
                    logger.warning(f"Edit pipeline unavailable (503) for {user}")
                    await interaction.followup.send("Edit pipeline is not available.")
                    return
                if resp.status == 400:
                    error_data = await resp.json()
                    error_detail = error_data.get('detail', 'Unknown error')
                    logger.warning(f"/edit request rejected (400) for {user}: {error_detail}")
                    await interaction.followup.send(f"Invalid request: {error_detail}")
                    return
                if resp.status != 200:
                    logger.error(f"Failed to submit edit job: HTTP {resp.status}")
                    await interaction.followup.send(f"Failed to submit job: {resp.status}")
                    return
                data = await resp.json()
                job_id = data["job_id"]
                logger.info(f"[{job_id}] Edit job submitted for {user}")

            await interaction.followup.send(f"Editing image... (Job ID: `{job_id}`)")

            # Poll for completion
            result = await poll_job_status(session, job_id)

            # Download and send image
            output_data = await download_image(session, result["output_image_url"])
            file = discord.File(BytesIO(output_data), filename="edited.png")

            embed = discord.Embed(title="Edited Image", color=0x0099ff)
            embed.add_field(name="Edit Instructions", value=prompt[:1024], inline=False)
            embed.add_field(name="Steps", value=str(steps), inline=True)
            embed.add_field(name="CFG", value=str(cfg), inline=True)
            embed.set_image(url="attachment://edited.png")

            await interaction.channel.send(embed=embed, file=file)
            logger.info(f"[{job_id}] Delivered edited image to {user}")

    except Exception as e:
        logger.error(f"/edit failed for {user}: {e}", exc_info=True)
        await interaction.followup.send(f"Error: {str(e)}")


@bot.tree.command(name="status", description="Check the status of a job")
@app_commands.describe(job_id="The job ID to check")
async def status(interaction: discord.Interaction, job_id: str):
    user = interaction.user
    guild_name = interaction.guild.name if interaction.guild else "DM"
    channel_name = getattr(interaction.channel, 'name', 'DM')

    guild_id = interaction.guild_id
    channel_id = interaction.channel_id
    if not is_allowed(guild_id, channel_id, user.id):
        logger.info(f"/status blocked for {user} in {guild_name}/#{channel_name} (not allowed)")
        await interaction.response.send_message("This command is not available here.", ephemeral=True)
        return

    logger.info(f"/status from {user}: job_id={job_id}")
    await interaction.response.defer(ephemeral=True)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API_BASE_URL}/status/{job_id}") as resp:
                if resp.status == 404:
                    logger.debug(f"/status: job {job_id} not found")
                    await interaction.followup.send("Job not found.", ephemeral=True)
                    return
                if resp.status != 200:
                    logger.error(f"/status: failed to get job {job_id}: HTTP {resp.status}")
                    await interaction.followup.send(f"Failed to get status: {resp.status}", ephemeral=True)
                    return
                data = await resp.json()
                logger.debug(f"/status: job {job_id} status={data['status']}")

        embed = discord.Embed(title=f"Job Status: {job_id[:8]}...", color=0xffaa00)
        embed.add_field(name="Type", value=data.get("job_type", "unknown"), inline=True)
        embed.add_field(name="Status", value=data["status"], inline=True)

        if data.get("progress") is not None:
            progress_pct = int(data["progress"] * 100)
            embed.add_field(name="Progress", value=f"{progress_pct}%", inline=True)

        if data.get("prompt"):
            embed.add_field(name="Prompt", value=data["prompt"][:1024], inline=False)

        if data.get("error"):
            embed.add_field(name="Error", value=data["error"][:1024], inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    except Exception as e:
        logger.error(f"/status failed for {user}: {e}", exc_info=True)
        await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)


@bot.tree.command(name="queue", description="Show the current job queue status")
async def queue(interaction: discord.Interaction):
    user = interaction.user
    guild_name = interaction.guild.name if interaction.guild else "DM"
    channel_name = getattr(interaction.channel, 'name', 'DM')

    guild_id = interaction.guild_id
    channel_id = interaction.channel_id
    if not is_allowed(guild_id, channel_id, user.id):
        logger.info(f"/queue blocked for {user} in {guild_name}/#{channel_name} (not allowed)")
        await interaction.response.send_message("This command is not available here.", ephemeral=True)
        return

    logger.info(f"/queue from {user} in {guild_name}/#{channel_name}")
    await interaction.response.defer(ephemeral=True)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API_BASE_URL}/queue") as resp:
                if resp.status != 200:
                    logger.error(f"/queue: failed to get queue info: HTTP {resp.status}")
                    await interaction.followup.send(f"Failed to get queue info: {resp.status}", ephemeral=True)
                    return
                data = await resp.json()
                logger.debug(f"/queue: queue_size={data.get('queue_size')}, total={data.get('total_jobs')}")

        embed = discord.Embed(title="Queue Status", color=0x9900ff)
        embed.add_field(name="Queue Size", value=str(data.get("queue_size", 0)), inline=True)
        embed.add_field(name="Total Jobs", value=str(data.get("total_jobs", 0)), inline=True)
        embed.add_field(name="Completed", value=str(data.get("completed_jobs", 0)), inline=True)
        embed.add_field(name="Failed", value=str(data.get("failed_jobs", 0)), inline=True)
        embed.add_field(name="Generation Jobs", value=str(data.get("generation_jobs", 0)), inline=True)
        embed.add_field(name="Edit Jobs", value=str(data.get("edit_jobs", 0)), inline=True)

        if data.get("current_job"):
            embed.add_field(name="Current Job", value=f"`{data['current_job'][:8]}...`", inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    except Exception as e:
        logger.error(f"/queue failed for {user}: {e}", exc_info=True)
        await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)


@bot.tree.command(name="system", description="Show system information")
async def system(interaction: discord.Interaction):
    user = interaction.user
    guild_name = interaction.guild.name if interaction.guild else "DM"
    channel_name = getattr(interaction.channel, 'name', 'DM')

    guild_id = interaction.guild_id
    channel_id = interaction.channel_id
    if not is_allowed(guild_id, channel_id, user.id):
        logger.info(f"/system blocked for {user} in {guild_name}/#{channel_name} (not allowed)")
        await interaction.response.send_message("This command is not available here.", ephemeral=True)
        return

    logger.info(f"/system from {user} in {guild_name}/#{channel_name}")
    await interaction.response.defer(ephemeral=True)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API_BASE_URL}/system/info") as resp:
                if resp.status != 200:
                    logger.error(f"/system: failed to get system info: HTTP {resp.status}")
                    await interaction.followup.send(f"Failed to get system info: {resp.status}", ephemeral=True)
                    return
                data = await resp.json()
                logger.debug(f"/system: device={data.get('device')}, gpu={data.get('gpu_name')}")

        embed = discord.Embed(title="System Information", color=0x00ffaa)
        embed.add_field(name="Device", value=data.get("device", "unknown"), inline=True)
        embed.add_field(name="CUDA Available", value=str(data.get("cuda_available", False)), inline=True)
        embed.add_field(name="Quantization", value=str(data.get("quantization", False)), inline=True)

        if data.get("gpu_name"):
            embed.add_field(name="GPU", value=data["gpu_name"], inline=False)

        if data.get("gpu_memory_allocated"):
            embed.add_field(name="Memory Allocated", value=data["gpu_memory_allocated"], inline=True)
        if data.get("gpu_memory_total"):
            embed.add_field(name="Memory Total", value=data["gpu_memory_total"], inline=True)

        embed.add_field(name="Generation Pipeline", value=data.get("generation_pipeline", "not loaded"), inline=True)
        embed.add_field(name="Edit Pipeline", value=data.get("edit_pipeline", "not loaded"), inline=True)

        await interaction.followup.send(embed=embed, ephemeral=True)

    except Exception as e:
        logger.error(f"/system failed for {user}: {e}", exc_info=True)
        await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        logger.error("DISCORD_TOKEN environment variable not set")
        logger.error("Create a .env file with DISCORD_TOKEN=your_token_here")
        exit(1)

    logger.info("Starting bot...")
    bot.run(DISCORD_TOKEN, log_handler=None)  # Disable default discord.py handler
