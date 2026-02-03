import os
import asyncio
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from io import BytesIO

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


async def poll_job_status(session: aiohttp.ClientSession, job_id: str, timeout: int = 300) -> dict:
    """Poll for job completion with timeout."""
    start_time = asyncio.get_event_loop().time()
    while True:
        async with session.get(f"{API_BASE_URL}/status/{job_id}") as resp:
            if resp.status != 200:
                raise Exception(f"Failed to get job status: {resp.status}")
            data = await resp.json()

            if data["status"] == "completed":
                return data
            elif data["status"] == "failed":
                raise Exception(data.get("error", "Job failed"))

            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > timeout:
                raise Exception("Job timed out")

            await asyncio.sleep(2)


async def download_image(session: aiohttp.ClientSession, image_url: str) -> bytes:
    """Download image from API server."""
    full_url = f"{API_BASE_URL}{image_url}"
    async with session.get(full_url) as resp:
        if resp.status != 200:
            raise Exception(f"Failed to download image: {resp.status}")
        return await resp.read()


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")


@bot.event
async def on_message(message: discord.Message):
    # Ignore messages from the bot itself
    if message.author == bot.user:
        return

    # Check if message has image attachments with text -> edit mode
    image_attachments = [a for a in message.attachments if a.content_type and a.content_type.startswith("image/")]

    if image_attachments and message.content.strip():
        await handle_edit_message(message, image_attachments, message.content.strip())
        return

    # Check for "draw [prompt]" pattern
    content_lower = message.content.lower().strip()
    if content_lower.startswith("draw "):
        prompt = message.content.strip()[5:].strip()  # Get everything after "draw "
        if prompt:
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
                "width": 512,
                "height": 512,
                "num_inference_steps": 20,
                "cfg_scale": 4.0,
                "seed": None
            }

            async with session.post(f"{API_BASE_URL}/generate", json=payload) as resp:
                if resp.status == 503:
                    await reply.edit(content="Sorry, the generation pipeline is not available right now.")
                    return
                if resp.status != 200:
                    await reply.edit(content=f"Failed to submit job: {resp.status}")
                    return
                data = await resp.json()
                job_id = data["job_id"]

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

    except Exception as e:
        await message.channel.send(
            content=f"{message.author.mention} Sorry, something went wrong: {str(e)}",
            reference=message
        )


async def handle_edit_message(message: discord.Message, attachments: list, prompt: str):
    """Handle natural language edit request."""
    # Reply to acknowledge
    reply = await message.reply("Got it, I have enqueued your request.")

    try:
        async with aiohttp.ClientSession() as session:
            # Use the first image attachment
            attachment = attachments[0]
            image_data = await attachment.read()

            # Prepare multipart form data
            form = aiohttp.FormData()
            form.add_field("images", image_data, filename=attachment.filename, content_type=attachment.content_type)
            form.add_field("prompt", prompt)
            form.add_field("negative_prompt", "")
            form.add_field("num_inference_steps", "50")
            form.add_field("cfg_scale", "4.0")

            async with session.post(f"{API_BASE_URL}/edit", data=form) as resp:
                if resp.status == 503:
                    await reply.edit(content="Sorry, the edit pipeline is not available right now.")
                    return
                if resp.status == 400:
                    error_data = await resp.json()
                    await reply.edit(content=f"Invalid request: {error_data.get('detail', 'Unknown error')}")
                    return
                if resp.status != 200:
                    await reply.edit(content=f"Failed to submit job: {resp.status}")
                    return
                data = await resp.json()
                job_id = data["job_id"]

            # Poll for completion
            result = await poll_job_status(session, job_id, timeout=600)

            # Download and send image
            output_data = await download_image(session, result["output_image_url"])
            file = discord.File(BytesIO(output_data), filename="edited.png")

            # Ping user with result
            await message.channel.send(
                content=f"{message.author.mention} Here's your edited image!",
                file=file,
                reference=message
            )

    except Exception as e:
        await message.channel.send(
            content=f"{message.author.mention} Sorry, something went wrong: {str(e)}",
            reference=message
        )


@bot.tree.command(name="generate", description="Generate an image from a text prompt")
@app_commands.describe(
    prompt="Description of the image to generate",
    negative_prompt="What to avoid in the image",
    width="Image width (default: 512)",
    height="Image height (default: 512)",
    steps="Number of inference steps (default: 20)",
    cfg="CFG scale (default: 4.0)",
    seed="Random seed for reproducibility"
)
async def generate(
    interaction: discord.Interaction,
    prompt: str,
    negative_prompt: str = "",
    width: int = 512,
    height: int = 512,
    steps: int = 20,
    cfg: float = 4.0,
    seed: int = None
):
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

            async with session.post(f"{API_BASE_URL}/generate", json=payload) as resp:
                if resp.status == 503:
                    await interaction.followup.send("Generation pipeline is not available.")
                    return
                if resp.status != 200:
                    await interaction.followup.send(f"Failed to submit job: {resp.status}")
                    return
                data = await resp.json()
                job_id = data["job_id"]

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

    except Exception as e:
        await interaction.followup.send(f"Error: {str(e)}")


@bot.tree.command(name="edit", description="Edit an image using AI")
@app_commands.describe(
    image="The image to edit",
    prompt="Instructions for how to edit the image",
    negative_prompt="What to avoid in the edit",
    steps="Number of inference steps (default: 50)",
    cfg="CFG scale (default: 4.0)",
    seed="Random seed for reproducibility"
)
async def edit(
    interaction: discord.Interaction,
    image: discord.Attachment,
    prompt: str,
    negative_prompt: str = "",
    steps: int = 50,
    cfg: float = 4.0,
    seed: int = None
):
    await interaction.response.defer(thinking=True)

    # Validate attachment is an image
    if not image.content_type or not image.content_type.startswith("image/"):
        await interaction.followup.send("Please attach a valid image file.")
        return

    try:
        async with aiohttp.ClientSession() as session:
            # Download the attachment
            image_data = await image.read()

            # Prepare multipart form data
            form = aiohttp.FormData()
            form.add_field("images", image_data, filename=image.filename, content_type=image.content_type)
            form.add_field("prompt", prompt)
            form.add_field("negative_prompt", negative_prompt or "")
            form.add_field("num_inference_steps", str(steps))
            form.add_field("cfg_scale", str(cfg))
            if seed is not None:
                form.add_field("seed", str(seed))

            async with session.post(f"{API_BASE_URL}/edit", data=form) as resp:
                if resp.status == 503:
                    await interaction.followup.send("Edit pipeline is not available.")
                    return
                if resp.status == 400:
                    error_data = await resp.json()
                    await interaction.followup.send(f"Invalid request: {error_data.get('detail', 'Unknown error')}")
                    return
                if resp.status != 200:
                    await interaction.followup.send(f"Failed to submit job: {resp.status}")
                    return
                data = await resp.json()
                job_id = data["job_id"]

            await interaction.followup.send(f"Editing image... (Job ID: `{job_id}`)")

            # Poll for completion
            result = await poll_job_status(session, job_id, timeout=600)

            # Download and send image
            output_data = await download_image(session, result["output_image_url"])
            file = discord.File(BytesIO(output_data), filename="edited.png")

            embed = discord.Embed(title="Edited Image", color=0x0099ff)
            embed.add_field(name="Edit Instructions", value=prompt[:1024], inline=False)
            embed.add_field(name="Steps", value=str(steps), inline=True)
            embed.add_field(name="CFG", value=str(cfg), inline=True)
            embed.set_image(url="attachment://edited.png")

            await interaction.channel.send(embed=embed, file=file)

    except Exception as e:
        await interaction.followup.send(f"Error: {str(e)}")


@bot.tree.command(name="status", description="Check the status of a job")
@app_commands.describe(job_id="The job ID to check")
async def status(interaction: discord.Interaction, job_id: str):
    await interaction.response.defer(ephemeral=True)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API_BASE_URL}/status/{job_id}") as resp:
                if resp.status == 404:
                    await interaction.followup.send("Job not found.", ephemeral=True)
                    return
                if resp.status != 200:
                    await interaction.followup.send(f"Failed to get status: {resp.status}", ephemeral=True)
                    return
                data = await resp.json()

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
        await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)


@bot.tree.command(name="queue", description="Show the current job queue status")
async def queue(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API_BASE_URL}/queue") as resp:
                if resp.status != 200:
                    await interaction.followup.send(f"Failed to get queue info: {resp.status}", ephemeral=True)
                    return
                data = await resp.json()

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
        await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)


@bot.tree.command(name="system", description="Show system information")
async def system(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API_BASE_URL}/system/info") as resp:
                if resp.status != 200:
                    await interaction.followup.send(f"Failed to get system info: {resp.status}", ephemeral=True)
                    return
                data = await resp.json()

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
        await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("Error: DISCORD_TOKEN environment variable not set")
        print("Create a .env file with DISCORD_TOKEN=your_token_here")
        exit(1)

    bot.run(DISCORD_TOKEN)
