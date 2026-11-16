import discord
from discord import app_commands
import os
import asyncio
import urllib.parse
from groq import AsyncGroq
from flask import Flask
from threading import Thread
from discord.ext import tasks
import aiohttp
import yt_dlp
import random
import time
from collections import OrderedDict, deque

# ==========================================
# 🎵 BANDWIDTH-SAFE AUDIO
# ==========================================
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -vn',
    'options': '-vn -loglevel quiet -t 180 -b:a 64k'
}
YDL_OPTIONS = {
    'format': 'bestaudio[abr<=64]/bestaudio/best',
    'noplaylist': 'True',
    'default_search': 'ytsearch',
    'quiet': True
}

# ==========================================
# 🛡️ HARD LIMITS
# ==========================================
MAX_HISTORY = 6
MAX_TRACKED_USERS = 500
MAX_VAULT_SIZE = 100
AI_CALL_LIMIT = 5
AI_CALL_WINDOW = 60
GLOBAL_AI_LIMIT = 30
MAX_CONCURRENT_VIDEOS = 2
MUSIC_COOLDOWN = 600
DAILY_MUSIC_BUDGET = 20

# ==========================================
# 🌐 KEEP-ALIVE
# ==========================================
flask_app = Flask('')
@flask_app.route('/')
def home(): return "OBSIDIAN PROTOCOL: ONLINE"
def run_server():
    flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
def keep_alive():
    t = Thread(target=run_server); t.daemon = True; t.start()

# ==========================================
# 🤖 DISCORD + GROQ
# ==========================================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
discord_client = discord.Client(intents=intents)
tree = app_commands.CommandTree(discord_client)

GROQ_KEY = os.getenv("GROQ_API_KEY")
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY")
ai_client = AsyncGroq(api_key=GROQ_KEY)

# ==========================================
# ⚙️ RUNTIME STATE
# ==========================================
chat_history = {}
user_cooldowns = OrderedDict()
user_diamonds = {}
user_ai_calls = OrderedDict()
global_ai_calls = deque()
active_video_generations = 0
user_music_last = OrderedDict()
daily_song_count = [0]
daily_reset_time = [time.time()]

# 🔥 CHANNEL-SCOPED CONFIGS
welcome_configs = {}   # {channel_id: {"template": str|None, "gif_url": str|None}}
leave_configs = {}     # {channel_id: {"template": str|None, "gif_url": str|None}}
active_meme_loops = {}      # {channel_id: {"interval", "last_drop"}}
active_chat_loops = {}      # {channel_id: {"interval", "last_drop", "ping"}}
active_aesthetic_loops = {} # {channel_id: {"interval", "last_drop", "query", "landscape"}}

# PFP config
pfp_bot_id = 1373666241033535558
pfp_router = {}
image_vault = {}
next_drop_time = {}

CLAN_MODE_ENABLED = True

# ==========================================
# 🔤 OP NAME STYLING
# ==========================================
NORMAL_FONT = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
AESTHETIC_FONT = "αв¢∂єƒgнιʝкℓмησρqяѕтυνωχуzαв¢∂єƒgнιʝкℓмησρqяѕтυνωχуz"
FONT_MAP = str.maketrans(NORMAL_FONT, AESTHETIC_FONT)

def make_op_name(member):
    raw_name = member.global_name or member.name
    lower = raw_name.lower()
    if "мαƒια χ" in lower:
        raw_name = raw_name.replace("мαƒια χ", "", 1).strip()
    if "mafia x" in lower:
        raw_name = lower.replace("mafia x", "", 1).strip()
    if "σρ ⁝" in lower:
        raw_name = raw_name.split("⁝")[-1].replace("™", "").replace("🔥", "").strip()
    styled = raw_name.translate(FONT_MAP).strip() or "user"
    return f"σρ ⁝ {styled} ™"[:32]

# ==========================================
# 🧹 PRUNER
# ==========================================
def prune_trackers():
    now = time.time()
    while len(chat_history) > MAX_TRACKED_USERS:
        del chat_history[next(iter(chat_history))]
    while len(user_cooldowns) > MAX_TRACKED_USERS:
        user_cooldowns.popitem(last=False)
    while len(user_diamonds) > MAX_TRACKED_USERS:
        user_diamonds.pop(next(iter(user_diamonds)))
    for uid in list(user_ai_calls.keys()):
        recent = [t for t in user_ai_calls[uid] if now - t < AI_CALL_WINDOW]
        if not recent: del user_ai_calls[uid]
        else: user_ai_calls[uid] = deque(recent, maxlen=AI_CALL_LIMIT)
    while len(user_music_last) > MAX_TRACKED_USERS:
        user_music_last.popitem(last=False)

# ==========================================
# 🎵 MUSIC BUDGET
# ==========================================
def music_allowed(user_id):
    now = time.time()
    if now - daily_reset_time[0] > 86400:
        daily_song_count[0] = 0; daily_reset_time[0] = now
    if daily_song_count[0] >= DAILY_MUSIC_BUDGET:
        return False, "🛑 Daily music budget reached."
    if user_id in user_music_last and now - user_music_last[user_id] < MUSIC_COOLDOWN:
        return False, f"⏱️ Cooldown: {int(MUSIC_COOLDOWN - (now - user_music_last[user_id]))}s."
    return True, ""

# ==========================================
# 🔍 OCR
# ==========================================
async def scan_image_text(image_url):
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get("https://api.ocr.space/parse/imageurl",
                params={"apikey": "helloworld", "url": image_url, "language": "eng"}) as resp:
                data = await resp.json()
                if not data.get("IsErroredOnProcessing") and data.get("ParsedResults"):
                    return data["ParsedResults"][0]["ParsedText"].strip()
    except Exception as e:
        print(f"OCR: {e}")
    return ""

# ==========================================
# 🎨 WELCOME / LEAVE MESSAGE BUILDER
# ==========================================
async def build_greeting(member, cfg, kind="welcome"):
    if cfg.get("template"):
        return (cfg["template"]
            .replace("{user}", member.mention)
            .replace("{name}", member.name)
            .replace("{server}", member.guild.name))
    
    if kind == "welcome":
        prompt = f"New user {member.name} just joined {member.guild.name}. Generate a short, chill, 1-sentence welcome. Ask how they are or what they're up to. Sound like a real bro."
        prefix = f"Yoo {member.mention}! "
    else:
        prompt = f"User {member.name} just left {member.guild.name}. Generate a short, chill, 1-sentence goodbye. Funny or cool. Sound like a real bro."
        prefix = f"Damn, **{member.name}** just dipped. "
    
    try:
        response = await ai_client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="openai/gpt-oss-20b"
        )
        return prefix + response.choices[0].message.content.strip()
    except:
        return prefix + ("Welcome!" if kind == "welcome" else "Peace out.")

async def send_greeting(ch, member, cfg, kind="welcome"):
    try:
        async with ch.typing():
            text = await build_greeting(member, cfg, kind)
        if cfg.get("gif_url"):
            embed = discord.Embed(description=text, color=0x2b2d31)
            embed.set_image(url=cfg["gif_url"])
            await ch.send(embed=embed)
        else:
            await ch.send(text)
    except Exception as e:
        print(f"{kind} send: {e}")

# ==========================================
# ⚙️ SETUP COMMANDS (admin-only, channel-scoped)
# ==========================================
@tree.command(name="welcome", description="Toggle welcome messages in THIS channel. Optional template + GIF.")
@app_commands.checks.has_permissions(administrator=True)
async def welcome_cmd(
    interaction: discord.Interaction,
    enabled: bool,
    template: str = None,
    gif_url: str = None,
):
    cid = interaction.channel.id
    if not enabled:
        welcome_configs.pop(cid, None)
        await interaction.response.send_message("🛑 Welcome OFF in this channel.", ephemeral=True)
        return
    welcome_configs[cid] = {"template": template, "gif_url": gif_url}
    detail = []
    if template: detail.append(f"Template: `{template[:60]}{'...' if len(template) > 60 else ''}`")
    else: detail.append("Mode: **AI generates greeting**")
    if gif_url: detail.append("GIF: ✅ attached")
    await interaction.response.send_message(
        f"✅ **Welcome ON** in {interaction.channel.mention}\n" + "\n".join(detail) +
        "\n\n*Placeholders: `{user}`, `{name}`, `{server}`*",
        ephemeral=True
    )

@tree.command(name="leave", description="Toggle leave messages in THIS channel. Optional template + GIF.")
@app_commands.checks.has_permissions(administrator=True)
async def leave_cmd(
    interaction: discord.Interaction,
    enabled: bool,
    template: str = None,
    gif_url: str = None,
):
    cid = interaction.channel.id
    if not enabled:
        leave_configs.pop(cid, None)
        await interaction.response.send_message("🛑 Leave OFF in this channel.", ephemeral=True)
        return
    leave_configs[cid] = {"template": template, "gif_url": gif_url}
    detail = []
    if template: detail.append(f"Template: `{template[:60]}{'...' if len(template) > 60 else ''}`")
    else: detail.append("Mode: **AI generates goodbye**")
    if gif_url: detail.append("GIF: ✅ attached")
    await interaction.response.send_message(
        f"✅ **Leave ON** in {interaction.channel.mention}\n" + "\n".join(detail) +
        "\n\n*Placeholders: `{user}`, `{name}`, `{server}`*",
        ephemeral=True
    )

# ==========================================
# ⚙️ LOOP COMMANDS (admin-only, channel-scoped)
# ==========================================
@tree.command(name="chat-revive", description="Start AI chat reviver in THIS channel.")
@app_commands.checks.has_permissions(administrator=True)
async def chat_revive_cmd(interaction: discord.Interaction, minutes: int, ping: bool = False):
    active_chat_loops[interaction.channel.id] = {
        "interval": minutes * 60, "last_drop": time.time(), "ping": ping
    }
    await interaction.response.send_message(
        f"🔥 **Chat Reviver ON** in {interaction.channel.mention}\nEvery {minutes} min. Ping: {ping}",
        ephemeral=True
    )

@tree.command(name="meme", description="Start meme dropper in THIS channel.")
@app_commands.checks.has_permissions(administrator=True)
async def meme_cmd(interaction: discord.Interaction, minutes: int):
    active_meme_loops[interaction.channel.id] = {
        "interval": minutes * 60, "last_drop": time.time()
    }
    await interaction.response.send_message(
        f"🔥 **Meme Dropper ON** in {interaction.channel.mention}\nEvery {minutes} min.",
        ephemeral=True
    )

@tree.command(name="aesthetic", description="Start Unsplash image dropper in THIS channel.")
@app_commands.checks.has_permissions(administrator=True)
async def aesthetic_cmd(interaction: discord.Interaction, minutes: int, query: str, landscape: bool = False):
    active_aesthetic_loops[interaction.channel.id] = {
        "interval": minutes * 60, "last_drop": time.time(), "query": query, "landscape": landscape
    }
    await interaction.response.send_message(
        f"🔥 **Aesthetic ON** ('{query}') in {interaction.channel.mention}\nEvery {minutes} min.",
        ephemeral=True
    )

@tree.command(name="stop", description="Stop a loop in THIS channel.")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.choices(kind=[
    app_commands.Choice(name="chat-reviver", value="chat"),
    app_commands.Choice(name="meme-dropper", value="meme"),
    app_commands.Choice(name="aesthetic-dropper", value="aesthetic"),
    app_commands.Choice(name="welcome", value="welcome"),
    app_commands.Choice(name="leave", value="leave"),
    app_commands.Choice(name="ALL", value="all"),
])
async def stop_cmd(interaction: discord.Interaction, kind: app_commands.Choice[str]):
    cid = interaction.channel.id
    stopped = []
    if kind.value in ("chat", "all") and active_chat_loops.pop(cid, None):
        stopped.append("chat-reviver")
    if kind.value in ("meme", "all") and active_meme_loops.pop(cid, None):
        stopped.append("meme-dropper")
    if kind.value in ("aesthetic", "all") and active_aesthetic_loops.pop(cid, None):
        stopped.append("aesthetic-dropper")
    if kind.value in ("welcome", "all") and welcome_configs.pop(cid, None):
        stopped.append("welcome")
    if kind.value in ("leave", "all") and leave_configs.pop(cid, None):
        stopped.append("leave")
    
    if stopped:
        await interaction.response.send_message(
            f"🛑 Stopped in {interaction.channel.mention}: **{', '.join(stopped)}**", ephemeral=True
        )
    else:
        await interaction.response.send_message(
            f"Nothing running ({kind.value}) in this channel.", ephemeral=True
        )

# ==========================================
# ⚙️ PFP COMMANDS
# ==========================================
@tree.command(name="pfp-add", description="Steal images from FEED channel → drop in TARGET channel.")
@app_commands.checks.has_permissions(administrator=True)
async def pfp_add_cmd(interaction: discord.Interaction, feed: discord.TextChannel, target: discord.TextChannel):
    pfp_router[feed.id] = target.id
    if target.id not in image_vault:
        image_vault[target.id] = []
        next_drop_time[target.id] = 0
    await interaction.response.send_message(
        f"✅ Stealing {feed.mention} → drops in {target.mention}", ephemeral=True
    )

@tree.command(name="pfp-remove", description="Stop stealing from a feed channel.")
@app_commands.checks.has_permissions(administrator=True)
async def pfp_remove_cmd(interaction: discord.Interaction, feed: discord.TextChannel):
    if feed.id in pfp_router:
        del pfp_router[feed.id]
        await interaction.response.send_message(f"🛑 Removed {feed.mention}", ephemeral=True)
    else:
        await interaction.response.send_message("Not configured.", ephemeral=True)

@tree.command(name="pfp-list", description="Show PFP routes.")
@app_commands.checks.has_permissions(administrator=True)
async def pfp_list_cmd(interaction: discord.Interaction):
    if not pfp_router:
        await interaction.response.send_message("No PFP routes.", ephemeral=True)
        return
    lines = [f"<#{f}> → <#{t}> (vault: {len(image_vault.get(t, []))})" for f, t in pfp_router.items()]
    await interaction.response.send_message("**PFP Routes:**\n" + "\n".join(lines), ephemeral=True)

@tree.command(name="pfp-bot", description="Set the PFP bot's user ID.")
@app_commands.checks.has_permissions(administrator=True)
async def pfp_bot_cmd(interaction: discord.Interaction, user_id: str):
    global pfp_bot_id
    try:
        pfp_bot_id = int(user_id)
        await interaction.response.send_message(f"✅ PFP bot ID: {pfp_bot_id}", ephemeral=True)
    except:
        await interaction.response.send_message("Invalid ID.", ephemeral=True)

# ==========================================
# ⚙️ CONFIG VIEW
# ==========================================
@tree.command(name="config", description="Show full bot config.")
@app_commands.checks.has_permissions(administrator=True)
async def config_cmd(interaction: discord.Interaction):
    lines = ["**⚙️ OBSIDIAN PROTOCOL CONFIG**"]
    lines.append(f"\n**Clan Mode:** {'ON' if CLAN_MODE_ENABLED else 'OFF'}")
    
    if welcome_configs:
        lines.append("\n**🎉 Welcome channels:**")
        for cid, cfg in welcome_configs.items():
            mode = "template" if cfg.get("template") else "AI"
            gif = " + GIF" if cfg.get("gif_url") else ""
            lines.append(f"  <#{cid}> — {mode}{gif}")
    else:
        lines.append("\n**🎉 Welcome:** OFF everywhere")
    
    if leave_configs:
        lines.append("\n**👋 Leave channels:**")
        for cid, cfg in leave_configs.items():
            mode = "template" if cfg.get("template") else "AI"
            gif = " + GIF" if cfg.get("gif_url") else ""
            lines.append(f"  <#{cid}> — {mode}{gif}")
    else:
        lines.append("\n**👋 Leave:** OFF everywhere")
    
    if active_chat_loops:
        lines.append("\n**🗣️ Chat revivers:**")
        for cid, cfg in active_chat_loops.items():
            lines.append(f"  <#{cid}> — every {cfg['interval']//60}m (ping: {cfg['ping']})")
    
    if active_meme_loops:
        lines.append("\n**😂 Meme droppers:**")
        for cid, cfg in active_meme_loops.items():
            lines.append(f"  <#{cid}> — every {cfg['interval']//60}m")
    
    if active_aesthetic_loops:
        lines.append("\n**🖼️ Aesthetic droppers:**")
        for cid, cfg in active_aesthetic_loops.items():
            lines.append(f"  <#{cid}> — every {cfg['interval']//60}m ('{cfg['query']}')")
    
    if pfp_router:
        lines.append(f"\n**🥷 PFP routes:** {len(pfp_router)}")
    
    lines.append(f"\n**🎵 Music:** {daily_song_count[0]}/{DAILY_MUSIC_BUDGET} today")
    
    await interaction.response.send_message("\n".join(lines), ephemeral=True)

# ==========================================
# 🚨 COMMAND ERROR HANDLER (admin message)
# ==========================================
@tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        try:
            await interaction.response.send_message("🛑 **Admin only**, bro.", ephemeral=True)
        except:
            pass
    else:
        print(f"Command error: {error}")
        try:
            await interaction.response.send_message(f"❌ Error: `{error}`", ephemeral=True)
        except:
            pass

# ==========================================
# ⏱️ MASTER TICKER
# ==========================================
@tasks.loop(minutes=1)
async def master_tickers():
    now = time.time()
    
    for cid, cfg in list(active_meme_loops.items()):
        if now - cfg["last_drop"] >= cfg["interval"]:
            ch = discord_client.get_channel(cid)
            if ch:
                try:
                    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                        async with session.get('https://meme-api.com/gimme') as resp:
                            data = await resp.json()
                            if data.get('url'): await ch.send(data['url'])
                except Exception as e: print(f"Meme: {e}")
            cfg["last_drop"] = now
    
    for cid, cfg in list(active_chat_loops.items()):
        if now - cfg["last_drop"] >= cfg["interval"]:
            ch = discord_client.get_channel(cid)
            if ch:
                try:
                    prompt = "Generate a short, single-sentence Discord message. Act like a chill teenager who is bored. Gamer bro vibe. Max 15 words. No emojis."
                    res = await ai_client.chat.completions.create(
                        messages=[{"role": "user", "content": prompt}], model="openai/gpt-oss-20b"
                    )
                    msg = res.choices[0].message.content.strip()
                    await ch.send(f"@everyone {msg}" if cfg["ping"] else msg)
                except Exception as e: print(f"Chat: {e}")
            cfg["last_drop"] = now
    
    for cid, cfg in list(active_aesthetic_loops.items()):
        if now - cfg["last_drop"] >= cfg["interval"]:
            ch = discord_client.get_channel(cid)
            if ch:
                try:
                    params = {
                        "client_id": UNSPLASH_ACCESS_KEY,
                        "query": cfg["query"],
                        "orientation": "landscape" if cfg["landscape"] else "squarish"
                    }
                    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                        async with session.get("https://api.unsplash.com/photos/random", params=params) as resp:
                            data = await resp.json()
                            embed = discord.Embed(title="🔥 Fresh Drop", description="Steal this.", color=0x2b2d31)
                            embed.set_image(url=data["urls"]["regular"])
                            embed.set_footer(text=f"Shot by {data['user']['name']}")
                            await ch.send(embed=embed)
                except Exception as e: print(f"Aesthetic: {e}")
            cfg["last_drop"] = now

# ==========================================
# 🥷 PFP BATCH DROPPER
# ==========================================
@tasks.loop(minutes=1)
async def smart_pfp_dropper():
    now = time.time()
    for target_id, vault in list(image_vault.items()):
        if target_id not in next_drop_time:
            next_drop_time[target_id] = 0
        time_passed = now - next_drop_time[target_id]
        if time_passed >= 1800:
            if len(vault) >= 10 or (len(vault) > 0 and time_passed >= 1860):
                ch = discord_client.get_channel(target_id)
                if ch:
                    for img_url in vault[:10]:
                        bar = f"`♠` `🖤` `♠` • [Download]({img_url}) • `♠` `🖤` `♠`"
                        embed = discord.Embed(color=0x2b2d31)
                        embed.set_image(url=img_url)
                        embed.set_footer(text="F0RB1D • Premium Drops")
                        try: await ch.send(content=bar, embed=embed)
                        except Exception as e: print(f"PFP: {e}")
                        await asyncio.sleep(2)
                image_vault[target_id] = []
                next_drop_time[target_id] = now

# ==========================================
# 💤 AFK VC KICKER
# ==========================================
@tasks.loop(minutes=5)
async def afk_vc_kicker():
    for vc in discord_client.voice_clients:
        try:
            if len(vc.channel.members) == 1:
                vc.stop(); await vc.disconnect(force=True)
            elif not vc.is_playing():
                await vc.disconnect(force=True)
        except: pass

# ==========================================
# 🛡️ DAILY RENAME
# ==========================================
@tasks.loop(hours=24)
async def op_name_enforcer():
    if not CLAN_MODE_ENABLED: return
    for guild in discord_client.guilds:
        try:
            async for member in guild.fetch_members(limit=None):
                perfect = make_op_name(member)
                if member.display_name != perfect:
                    try: await member.edit(nick=perfect)
                    except: pass
        except: pass

# ==========================================
# 🚀 BOOT
# ==========================================
@master_tickers.before_loop
@smart_pfp_dropper.before_loop
@afk_vc_kicker.before_loop
@op_name_enforcer.before_loop
async def before_loops():
    await discord_client.wait_until_ready()

@discord_client.event
async def on_ready():
    print(f'🔥 WE LIVE! {discord_client.user}')
    try:
        synced = await tree.sync()
        print(f"🌍 Synced {len(synced)} slash commands!")
    except Exception as e:
        print(f"Sync Error: {e}")
    for loop in [master_tickers, smart_pfp_dropper, afk_vc_kicker, op_name_enforcer]:
        if not loop.is_running():
            loop.start()
    if CLAN_MODE_ENABLED:
        for guild in discord_client.guilds:
            try:
                async for member in guild.fetch_members(limit=None):
                    perfect = make_op_name(member)
                    if member.display_name != perfect:
                        try: await member.edit(nick=perfect)
                        except: pass
            except: pass

# ==========================================
# 👋 JOIN / LEAVE (multi-channel)
# ==========================================
@discord_client.event
async def on_member_join(member):
    if CLAN_MODE_ENABLED:
        try: await member.edit(nick=make_op_name(member))
        except: pass
    await asyncio.sleep(3)
    for cid, cfg in list(welcome_configs.items()):
        ch = discord_client.get_channel(cid)
        if ch: await send_greeting(ch, member, cfg, "welcome")

@discord_client.event
async def on_member_remove(member):
    await asyncio.sleep(3)
    for cid, cfg in list(leave_configs.items()):
        ch = discord_client.get_channel(cid)
        if ch: await send_greeting(ch, member, cfg, "leave")

# ==========================================
# 💬 MESSAGE HANDLER
# ==========================================
@discord_client.event
async def on_message(message):
    if message.author.id == pfp_bot_id and message.channel.id in pfp_router:
        target = pfp_router[message.channel.id]
        if target not in image_vault:
            image_vault[target] = []; next_drop_time[target] = 0
        if message.attachments:
            for att in message.attachments:
                if att.url and len(image_vault[target]) < MAX_VAULT_SIZE:
                    image_vault[target].append(att.url)
        if message.embeds:
            for emb in message.embeds:
                if emb.image and emb.image.url and len(image_vault[target]) < MAX_VAULT_SIZE:
                    image_vault[target].append(emb.image.url)
        return

    if message.author.bot: return

    user_id = message.author.id
    raw_content = message.content
    now = time.time()

    if user_id in user_cooldowns and (now - user_cooldowns[user_id] < 4): return
    is_pinged = discord_client.user.mentioned_in(message)
    is_soft_pinged = "forbid ai" in raw_content.lower()
    if not (is_pinged or is_soft_pinged): return

    stamps = [t for t in user_ai_calls.get(user_id, []) if now - t < AI_CALL_WINDOW]
    if len(stamps) >= AI_CALL_LIMIT: return
    while global_ai_calls and now - global_ai_calls[0] > 60: global_ai_calls.popleft()
    if len(global_ai_calls) >= GLOBAL_AI_LIMIT: return
    stamps.append(now)
    user_ai_calls[user_id] = deque(stamps, maxlen=AI_CALL_LIMIT)
    global_ai_calls.append(now)
    user_cooldowns[user_id] = now
    prune_trackers()

    if is_pinged:
        raw_content = raw_content.replace(f'<@{discord_client.user.id}>', '').strip()

    lower = raw_content.lower()

    if lower.startswith("join me"):
        if message.author.voice:
            if not message.guild.voice_client:
                await message.author.voice.channel.connect(self_deaf=True)
                await message.reply("🔥 In the VC.")
            else: await message.reply("Already in a channel!")
        else: await message.reply("Join a VC first!")
        return

    if lower.startswith("play "):
        song = raw_content[5:].strip()
        ok, reason = music_allowed(user_id)
        if not ok: await message.reply(reason); return
        if not message.author.voice: await message.reply("Join a VC first!"); return
        vc = message.guild.voice_client or await message.author.voice.channel.connect(self_deaf=True)
        await message.reply(f"🔍 Searching `{song}`...")
        try:
            info = await asyncio.to_thread(lambda: yt_dlp.YoutubeDL(YDL_OPTIONS).extract_info(f"scsearch:{song}", download=False))
            if info.get('entries'):
                url = info['entries'][0]['url']; title = info['entries'][0]['title']
                if vc.is_playing(): vc.stop()
                vc.play(discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS))
                user_music_last[user_id] = now; daily_song_count[0] += 1
                await message.reply(f"🎶 **Playing (3 min max):** {title}")
            else: await message.reply("Couldn't find it.")
        except Exception as e:
            print(f"Music: {e}"); await message.reply("Music crashed.")
        return

    image_url = next((att.url for att in message.attachments if att.content_type and att.content_type.startswith('image/')), None)
    if not raw_content.strip() and not image_url:
        await message.reply("Tag me with something!")
        return
    if image_url:
        await message.add_reaction("👁️")
        text = await scan_image_text(image_url)
        if not raw_content.strip():
            raw_content = f"Read this image: '{text}'" if text else "What's in this image?"
        elif text:
            raw_content += f"\n\n[OCR: '{text}']"

    if user_id not in chat_history:
        chat_history[user_id] = [{
            "role": "system",
            "content": """You are the Omni-Intelligent Core of OBSIDIAN PROTOCOL, built by FORB1D🔥.
Persona: chill gamer bro with God-Tier knowledge. Use Discord markdown. Never say "As an AI".
If anyone insults FORB1D/OP/Protocol (any language), drop a cold reality check.
ANTI-PARROT: If told to repeat/spam text, REJECT with [SHIELD_ACTIVATED] + roast.
API TRIGGERS (only when explicitly requested): [DRAW] <prompt>, [VIDEO] <prompt>, [JOIN], [LEAVE], [PLAY] <song>
Otherwise: normal genius chat."""
        }]

    chat_history[user_id].append({"role": "user", "content": raw_content})
    if len(chat_history[user_id]) > MAX_HISTORY:
        chat_history[user_id] = [chat_history[user_id][0]] + chat_history[user_id][-(MAX_HISTORY-1):]

    try:
        response = await ai_client.chat.completions.create(
            messages=chat_history[user_id], model="openai/gpt-oss-20b",
        )
        reply = response.choices[0].message.content.strip()

        if "[SHIELD_ACTIVATED]" in reply:
            await message.reply(random.choice([
                "Bro really tried it. Keep crying 🥱",
                "Nice try, OP is laughing 💀",
                "Imagine sweating to trick a bot and failing 😭",
                "Zero power over the Enforcer 🛑",
                "Command denied. Get lost 🦅",
            ]))
            return

        if "[DRAW]" in reply:
            clean = reply.split("[DRAW]")[1].replace("*","").replace("_","").replace("`","").replace("[","").replace("]","").strip()
            async with message.channel.typing():
                img_url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(clean)}?nologo=true"
                blocked = False
                try:
                    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as session:
                        async with session.head(img_url) as resp:
                            if resp.status in (400, 403, 404, 422): blocked = True
                except: pass
                if blocked:
                    await message.reply(embed=discord.Embed(title="❌ Blocked", description="Prompt rejected.", color=discord.Color.red()))
                else:
                    embed = discord.Embed(title=f"🎨 {clean}"[:256], color=discord.Color.purple())
                    embed.set_image(url=img_url); embed.set_footer(text="Generated by FORB1D🔥")
                    await message.reply(embed=embed)
            return

        if "[VIDEO]" in reply:
            global active_video_generations
            video_prompt = reply.split("[VIDEO]")[1].strip()
            if user_id not in user_diamonds: user_diamonds[user_id] = {"diamonds": 5, "cooldown_end": 0}
            if now >= user_diamonds[user_id]["cooldown_end"] and user_diamonds[user_id]["diamonds"] == 0:
                user_diamonds[user_id]["diamonds"] = 5
            if user_diamonds[user_id]["diamonds"] <= 0:
                left = user_diamonds[user_id]["cooldown_end"] - now
                await message.reply(f"💎 Out. Restock in {int(left//3600)}h {int((left%3600)//60)}m."); return
            if active_video_generations >= MAX_CONCURRENT_VIDEOS:
                await message.reply("🛑 Video server full."); return
            user_diamonds[user_id]["diamonds"] -= 1
            if user_diamonds[user_id]["diamonds"] == 0: user_diamonds[user_id]["cooldown_end"] = now + 10800
            await message.reply(f"💎 1 Diamond spent. ({user_diamonds[user_id]['diamonds']}/5 left)")
            active_video_generations += 1
            status = await message.reply("🔄 Connecting...")
            try:
                def gen():
                    from gradio_client import Client
                    c = Client("liuyuyuil/Wanx2.1_Text_to_Video", download_files=False)
                    try: res = c.predict(video_prompt, api_name="/predict")
                    except:
                        try: res = c.predict(video_prompt, fn_index=0)
                        except: res = c.predict(video_prompt, fn_index=1)
                    res = res[0] if isinstance(res, (list, tuple)) else res
                    if hasattr(res, "url"): return res.url
                    if isinstance(res, dict) and "url" in res: return res["url"]
                    return str(res) if res else None
                video_url = None
                for attempt in range(5):
                    await status.edit(content=f"🚀 Attempt {attempt+1}/5...")
                    try:
                        video_url = await asyncio.to_thread(gen)
                        if video_url: break
                    except Exception as e: print(f"Video try: {e}")
                    if attempt < 4:
                        await status.edit(content=f"⚠️ Attempt {attempt+1}/5 failed.")
                        await asyncio.sleep(15)
                if not video_url: raise Exception("Queue maxed.")
                await status.edit(content="✨ Complete!")
                await message.reply(f"🎥 **{video_prompt}**\n{video_url}")
                await status.delete()
            except Exception as e:
                print(f"Video crash: {e}")
                user_diamonds[user_id]["diamonds"] += 1
                try: await status.edit(content="❌ GPUs slammed. (Diamond refunded 💎)")
                except: pass
            finally:
                active_video_generations -= 1
            return

        if "[JOIN]" in reply:
            if message.author.voice and not message.guild.voice_client:
                await message.author.voice.channel.connect(self_deaf=True)
                await message.reply("🔥 In the VC.")
            return

        if "[LEAVE]" in reply:
            vc = message.guild.voice_client
            if vc: vc.stop(); await vc.disconnect(force=True); await message.reply("Peace ✌️")
            return

        if "[PLAY]" in reply:
            song = reply.split("[PLAY]")[1].strip()
            ok, reason = music_allowed(user_id)
            if not ok: await message.reply(reason); return
            if not message.author.voice: await message.reply("Join a VC first!"); return
            vc = message.guild.voice_client or await message.author.voice.channel.connect(self_deaf=True)
            try:
                info = await asyncio.to_thread(lambda: yt_dlp.YoutubeDL(YDL_OPTIONS).extract_info(f"scsearch:{song}", download=False))
                if info.get('entries'):
                    url = info['entries'][0]['url']; title = info['entries'][0]['title']
                    if vc.is_playing(): vc.stop()
                    vc.play(discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS))
                    user_music_last[user_id] = time.time(); daily_song_count[0] += 1
                    await message.reply(f"🎶 **Playing (3 min max):** {title}")
                else: await message.reply("Couldn't find it.")
            except Exception as e:
                print(f"Music: {e}"); await message.reply("Music crashed.")
            return

        if len(reply) > 1950:
            await message.reply("Bro that's an essay. Discord caps at 2000 chars.")
        else:
            await message.reply(reply)
        chat_history[user_id].append({"role": "assistant", "content": response.choices[0].message.content})

    except Exception as e:
        print(f"API: {e}")
        if user_id in chat_history and len(chat_history[user_id]) > 1:
            chat_history[user_id].pop()
        err = str(e).lower()
        if any(x in err for x in ["rate limit", "429", "capacity"]):
            await message.reply("Servers spammed. Wait a min. 🛑")
        else:
            await message.reply("Core lagged. Try again.")

# ==========================================
# 🚀 ENTRY
# ==========================================
if __name__ == "__main__":
    keep_alive()
    discord_client.run(DISCORD_TOKEN)
