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
import hashlib
from collections import OrderedDict, deque

# ==========================================
# 🎨 BRANDING
# ==========================================
BRAND_COLOR = 0x2b2d31
SUCCESS_COLOR = 0x2ecc71
ERROR_COLOR = 0xe74c3c
BRAND_FOOTER = "F0RB1D • OBSIDIAN PROTOCOL"

def brand_embed(title=None, description=None, color=BRAND_COLOR):
    e = discord.Embed(title=title, description=description, color=color)
    e.set_footer(text=BRAND_FOOTER)
    e.timestamp = discord.utils.utcnow()
    return e

def ok_embed(msg): return brand_embed(description=f"✅ {msg}", color=SUCCESS_COLOR)
def err_embed(msg): return brand_embed(description=f"❌ {msg}", color=ERROR_COLOR)
def info_embed(msg): return brand_embed(description=f"ℹ️ {msg}")

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
# 🛡️ HARD LIMITS & STATE
# ==========================================
MAX_HISTORY = 6
MAX_TRACKED_USERS = 500
AI_CALL_WINDOW = 60
GLOBAL_AI_LIMIT = 30
MAX_CONCURRENT_VIDEOS = 2
MUSIC_COOLDOWN = 600

runtime_settings = {"cooldown": 4, "daily_songs": 20, "ai_limit": 5}
GLOBAL_TOGGLES = {"clan_mode": True, "music": True, "ai_chat": True}

chat_history = {}
user_cooldowns = OrderedDict()
user_spam_warned = OrderedDict()
user_diamonds = {}
user_ai_calls = OrderedDict()
global_ai_calls = deque()
active_video_generations = 0
user_music_last = OrderedDict()
daily_song_count = [0]
daily_reset_time = [time.time()]

welcome_configs = {}
leave_configs = {}
active_meme_loops = {}
active_chat_loops = {}
active_aesthetic_loops = {}
ai_auto_channels = {}

# 🚨 SECURITY & ANTI-SPAM STATE
user_strikes = {}  
user_recent_msgs = OrderedDict()  
recent_memes = deque(maxlen=50)
recent_greetings = deque(maxlen=20)

# ==========================================
# 🌐 KEEP-ALIVE
# ==========================================
flask_app = Flask('')
@flask_app.route('/')
def home(): return "OBSIDIAN PROTOCOL: FORTRESS"
def run_server(): flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
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
# 🔤 OP NAME STYLING
# ==========================================
NORMAL_FONT = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
AESTHETIC_FONT = "αв¢∂єƒgнιʝкℓмησρqяѕтυνωχуzαв¢∂єƒgнιʝкℓмησρqяѕтυνωχуz"
FONT_MAP = str.maketrans(NORMAL_FONT, AESTHETIC_FONT)

def make_op_name(member):
    raw_name = member.global_name or member.name
    lower = raw_name.lower()
    if "мαƒια χ" in lower: raw_name = raw_name.replace("мαƒια χ", "", 1).strip()
    if "mafia x" in lower: raw_name = lower.replace("mafia x", "", 1).strip()
    if "σρ ⁝" in lower: raw_name = raw_name.split("⁝")[-1].replace("™", "").replace("🔥", "").strip()
    styled = raw_name.translate(FONT_MAP).strip() or "user"
    return f"σρ ⁝ {styled} ™"[:32]

# ==========================================
# 🧹 PRUNER
# ==========================================
def prune_trackers():
    now = time.time()
    while len(chat_history) > MAX_TRACKED_USERS: del chat_history[next(iter(chat_history))]
    while len(user_cooldowns) > MAX_TRACKED_USERS: user_cooldowns.popitem(last=False)
    while len(user_spam_warned) > MAX_TRACKED_USERS: user_spam_warned.popitem(last=False)
    while len(user_recent_msgs) > MAX_TRACKED_USERS: user_recent_msgs.popitem(last=False)
    for uid in list(user_strikes.keys()):
        if now - user_strikes[uid]["last_offense"] > 3600 and now > user_strikes[uid]["timeout_until"]:
            del user_strikes[uid]
    for uid in list(user_ai_calls.keys()):
        recent = [t for t in user_ai_calls[uid] if now - t < AI_CALL_WINDOW]
        if not recent: del user_ai_calls[uid]
        else: user_ai_calls[uid] = deque(recent, maxlen=runtime_settings["ai_limit"])
    while len(user_music_last) > MAX_TRACKED_USERS: user_music_last.popitem(last=False)

def music_allowed(user_id):
    if not GLOBAL_TOGGLES["music"]: return False, "🛑 Music disabled."
    now = time.time()
    if now - daily_reset_time[0] > 86400:
        daily_song_count[0] = 0; daily_reset_time[0] = now
    if daily_song_count[0] >= runtime_settings["daily_songs"]: return False, "🛑 Daily music budget reached."
    if user_id in user_music_last and now - user_music_last[user_id] < MUSIC_COOLDOWN:
        return False, f"⏱️ Cooldown: {int(MUSIC_COOLDOWN - (now - user_music_last[user_id]))}s."
    return True, ""

# ==========================================
# 🚨 ADVANCED ANTI-SPAM (With Visible Warning)
# ==========================================
def apply_strike(user_id):
    now = time.time()
    if user_id not in user_strikes:
        user_strikes[user_id] = {"strikes": 0, "last_offense": now, "timeout_until": 0}
    data = user_strikes[user_id]
    if now - data["last_offense"] > 3600: data["strikes"] = 0
    data["strikes"] += 1
    data["last_offense"] = now
    
    if data["strikes"] == 1: timeout = 60
    elif data["strikes"] == 2: timeout = 300
    elif data["strikes"] == 3: timeout = 900
    else: timeout = 3600
    data["timeout_until"] = now + timeout
    return timeout

def check_spam(user_id, content, is_ping):
    now = time.time()
    if user_id in user_strikes and now < user_strikes[user_id]["timeout_until"]:
        return True, int(user_strikes[user_id]["timeout_until"] - now)
        
    if user_id not in user_recent_msgs: user_recent_msgs[user_id] = deque(maxlen=5)
    content_hash = hashlib.md5(content.encode()).hexdigest() if content else "empty"
    user_recent_msgs[user_id].append((now, content_hash, is_ping))
    
    recent = [m for m in user_recent_msgs[user_id] if now - m[0] < 10]
    if not recent: return False, 0
    
    text_counts = {}
    for _, c_hash, _ in recent: text_counts[c_hash] = text_counts.get(c_hash, 0) + 1
    if any(count >= 3 for c_hash, count in text_counts.items() if c_hash != "empty"):
        t = apply_strike(user_id); return True, t
        
    ping_count = sum(1 for _, _, ping in recent if ping)
    if ping_count >= 3:
        t = apply_strike(user_id); return True, t
    return False, 0

# ==========================================
# 🎨 PRO GREETING BUILDER (Anti-Repetition)
# ==========================================
async def build_greeting(member, cfg, kind="welcome"):
    for attempt in range(3):
        if cfg.get("template"):
            msg = cfg["template"].replace("{user}", member.mention).replace("{name}", member.name).replace("{server}", member.guild.name)
        else:
            if kind == "welcome":
                prompt = f"New user {member.name} just joined {member.guild.name}. Generate a short, chill, 1-sentence welcome. Ask how they are. Sound like a real bro."
                prefix = f"Yoo {member.mention}! "
            else:
                prompt = f"User {member.name} just left {member.guild.name}. Generate a short, chill, 1-sentence goodbye. Funny or cool. Sound like a real bro."
                prefix = f"Damn, **{member.name}** just dipped. "
            try:
                response = await ai_client.chat.completions.create(messages=[{"role": "user", "content": prompt}], model="openai/gpt-oss-20b")
                msg = prefix + response.choices[0].message.content.strip()
            except: msg = prefix + ("Welcome!" if kind == "welcome" else "Peace out.")

        # Check for duplicates
        if msg not in recent_greetings:
            recent_greetings.append(msg)
            return msg
    return msg # Fallback if 3 attempts all match somehow

async def send_greeting(ch, member, cfg, kind="welcome"):
    try:
        async with ch.typing():
            text = await build_greeting(member, cfg, kind)
        
        e = discord.Embed(description=text, color=BRAND_COLOR)
        verb = "just joined!" if kind == "welcome" else "just left"
        e.set_author(name=f"{member.name} {verb}", icon_url=member.display_avatar.url)
        
        if kind == "welcome":
            e.set_thumbnail(url=member.display_avatar.url)
            
        if cfg.get("gif_url"): e.set_image(url=cfg["gif_url"])
        
        # Pro Fields
        created_at = int(member.created_at.timestamp())
        e.add_field(name="📅 Account Created", value=f"<t:{created_at}:R>", inline=True)
        e.add_field(name="👥 Member Count", value=f"#{member.guild.member_count:,}", inline=True)
        
        e.set_footer(text=BRAND_FOOTER)
        e.timestamp = discord.utils.utcnow()
        await ch.send(embed=e)
    except Exception as e: print(f"{kind} send: {e}")

# ==========================================
# 🔥 BACKGROUND FIRE FUNCTIONS (Anti-Repetition)
# ==========================================
def should_ping(mode):
    if mode == "always": return True
    if mode == "random": return random.random() < 0.25
    return False

async def fire_chat_drop(cid, cfg):
    ch = discord_client.get_channel(cid)
    if not ch: return
    try:
        prompt = "Generate a short, single-sentence Discord message. Act like a chill teenager who is bored. Gamer bro vibe. Max 15 words. No emojis."
        res = await ai_client.chat.completions.create(messages=[{"role": "user", "content": prompt}], model="openai/gpt-oss-20b")
        msg = res.choices[0].message.content.strip()
        await ch.send(f"@everyone {msg}" if should_ping(cfg.get("ping_mode", "never")) else msg)
    except Exception as e: print(f"Chat drop: {e}")

async def fire_meme_drop(cid, cfg):
    ch = discord_client.get_channel(cid)
    if not ch: return
    for attempt in range(3):
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                async with session.get('https://meme-api.com/gimme') as resp:
                    data = await resp.json()
                    url = data.get('url')
                    if url and url not in recent_memes:
                        recent_memes.append(url)
                        await ch.send(url)
                        return
        except Exception as e: print(f"Meme drop: {e}")

async def fire_aesthetic_drop(cid, cfg):
    ch = discord_client.get_channel(cid)
    if not ch: return
    try:
        params = {"client_id": UNSPLASH_ACCESS_KEY, "query": cfg["query"], "orientation": "landscape" if cfg["landscape"] else "squarish"}
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.get("https://api.unsplash.com/photos/random", params=params) as resp:
                data = await resp.json()
                e = brand_embed(title="🔥 Fresh Drop", description="Steal this for your profile.")
                e.set_image(url=data["urls"]["regular"])
                e.set_footer(text=f"📸 {data['user']['name']} • {BRAND_FOOTER}")
                await ch.send(embed=e)
    except Exception as e: print(f"Aesthetic drop: {e}")

# ==========================================
# 🛠️ POWER COMMANDS (/say, /dm-all)
# ==========================================
@tree.command(name="say", description="Make the bot say something or send a file.")
@app_commands.checks.has_permissions(administrator=True)
async def say_cmd(interaction: discord.Interaction, text: str = None, file: discord.Attachment = None):
    if not text and not file:
        await interaction.response.send_message(embed=err_embed("Provide text or a file."), ephemeral=True); return
    
    await interaction.response.send_message(embed=ok_embed("Sending..."), ephemeral=True)
    
    # 🗑️ Try to delete the user's slash command message for clean chat
    try: await interaction.delete_original_response()
    except: pass
    
    kwargs = {}
    if text: kwargs["content"] = text
    if file: kwargs["file"] = await file.to_file()
    await interaction.channel.send(**kwargs)

@tree.command(name="dm-all", description="DM a message/file to everyone in the server.")
@app_commands.checks.has_permissions(administrator=True)
async def dm_all_cmd(interaction: discord.Interaction, text: str = None, file: discord.Attachment = None):
    if not text and not file:
        await interaction.response.send_message(embed=err_embed("Provide text or a file."), ephemeral=True); return
        
    await interaction.response.send_message(embed=info_embed("📨 Broadcast started. Sending DMs..."), ephemeral=True)
    
    members = [m for m in interaction.guild.members if not m.bot]
    success, failed = 0, 0
    
    # Grab file bytes once to save bandwidth (don't re-download per user)
    file_bytes = await file.read() if file else None
    file_name = file.filename if file else None
    
    for member in members:
        try:
            if file_bytes:
                await member.send(content=text, file=discord.File(fp=discord.utils.io.BytesIO(file_bytes), filename=file_name))
            else:
                await member.send(content=text)
            success += 1
            await asyncio.sleep(1.5) # Prevent Discord 429 Rate Limit ban
        except discord.Forbidden:
            failed += 1 # DMs closed
        except Exception as e:
            failed += 1
            print(f"DM failed for {member.name}: {e}")
            
    await interaction.followup.send(embed=ok_embed(f"📨 **Broadcast Complete!**\n✅ Sent: {success}\n❌ Failed (DMs closed): {failed}"), ephemeral=True)

# ==========================================
# ⚙️ SLASH COMMANDS (SETUP)
# ==========================================
@tree.command(name="welcome", description="Toggle welcome messages in THIS channel.")
@app_commands.checks.has_permissions(administrator=True)
async def welcome_cmd(interaction: discord.Interaction, enabled: bool, template: str = None, gif_url: str = None):
    cid = interaction.channel.id
    if not enabled:
        welcome_configs.pop(cid, None)
        await interaction.response.send_message(embed=ok_embed("Welcome **OFF** here."), ephemeral=True); return
    welcome_configs[cid] = {"template": template, "gif_url": gif_url}
    e = brand_embed(title="🎉 Welcome ON", description=f"**Channel:** {interaction.channel.mention}\n**Mode:** {'📝 template' if template else '🤖 AI-generated'}\n\n*Placeholders: `{{user}}` `{{name}}` `{{server}}`*")
    await interaction.response.send_message(embed=e, ephemeral=True)

@tree.command(name="leave", description="Toggle leave messages in THIS channel.")
@app_commands.checks.has_permissions(administrator=True)
async def leave_cmd(interaction: discord.Interaction, enabled: bool, template: str = None, gif_url: str = None):
    cid = interaction.channel.id
    if not enabled:
        leave_configs.pop(cid, None)
        await interaction.response.send_message(embed=ok_embed("Leave **OFF** here."), ephemeral=True); return
    leave_configs[cid] = {"template": template, "gif_url": gif_url}
    e = brand_embed(title="👋 Leave ON", description=f"**Channel:** {interaction.channel.mention}\n**Mode:** {'📝 template' if template else '🤖 AI-generated'}\n\n*Placeholders: `{{user}}` `{{name}}` `{{server}}`*")
    await interaction.response.send_message(embed=e, ephemeral=True)

@tree.command(name="chat-revive", description="Toggle AI chat reviver in THIS channel.")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.choices(ping_mode=[
    app_commands.Choice(name="🔕 Never ping", value="never"),
    app_commands.Choice(name="📢 Always ping", value="always"),
    app_commands.Choice(name="🎲 Random (~25%)", value="random"),
])
async def chat_revive_cmd(interaction: discord.Interaction, enabled: bool, minutes: int = 120, ping_mode: str = "never"):
    cid = interaction.channel.id
    if not enabled:
        active_chat_loops.pop(cid, None)
        await interaction.response.send_message(embed=ok_embed("Chat Reviver **OFF** here."), ephemeral=True); return
    if minutes < 1:
        await interaction.response.send_message(embed=err_embed("Minimum 1 minute."), ephemeral=True); return
    cfg = {"interval": minutes * 60, "last_drop": time.time(), "ping_mode": ping_mode}
    active_chat_loops[cid] = cfg
    mode_emoji = {"never": "🔕", "always": "📢", "random": "🎲"}[ping_mode]
    await interaction.response.send_message(embed=ok_embed(f"Chat Reviver ON here (every {minutes}m, ping: {mode_emoji}).\n*🎭 Bot will react to active chat msgs.*"), ephemeral=True)
    asyncio.create_task(fire_chat_drop(cid, cfg))

@tree.command(name="meme", description="Toggle meme dropper in THIS channel.")
@app_commands.checks.has_permissions(administrator=True)
async def meme_cmd(interaction: discord.Interaction, enabled: bool, minutes: int = 30):
    cid = interaction.channel.id
    if not enabled:
        active_meme_loops.pop(cid, None)
        await interaction.response.send_message(embed=ok_embed("Meme Dropper **OFF** here."), ephemeral=True); return
    cfg = {"interval": minutes * 60, "last_drop": time.time()}
    active_meme_loops[cid] = cfg
    await interaction.response.send_message(embed=ok_embed(f"Meme Dropper ON here (every {minutes}m)."), ephemeral=True)
    asyncio.create_task(fire_meme_drop(cid, cfg))

@tree.command(name="aesthetic", description="Toggle Unsplash image dropper in THIS channel.")
@app_commands.checks.has_permissions(administrator=True)
async def aesthetic_cmd(interaction: discord.Interaction, enabled: bool, minutes: int = 180, query: str = "aesthetic", landscape: bool = False):
    cid = interaction.channel.id
    if not enabled:
        active_aesthetic_loops.pop(cid, None)
        await interaction.response.send_message(embed=ok_embed("Aesthetic **OFF** here."), ephemeral=True); return
    cfg = {"interval": minutes * 60, "last_drop": time.time(), "query": query, "landscape": landscape}
    active_aesthetic_loops[cid] = cfg
    await interaction.response.send_message(embed=ok_embed(f"Aesthetic ON here ('{query}', every {minutes}m)."), ephemeral=True)
    asyncio.create_task(fire_aesthetic_drop(cid, cfg))

@tree.command(name="ai-auto", description="AI replies to EVERY message in THIS channel.")
@app_commands.checks.has_permissions(administrator=True)
async def ai_auto_cmd(interaction: discord.Interaction, enabled: bool):
    cid = interaction.channel.id
    if enabled:
        ai_auto_channels[cid] = True
        await interaction.response.send_message(embed=ok_embed(f"🤖 AI will reply to **every message** here."), ephemeral=True)
    else:
        ai_auto_channels.pop(cid, None)
        await interaction.response.send_message(embed=ok_embed("AI auto-reply disabled here."), ephemeral=True)

@tree.command(name="stop", description="Stop something in THIS channel.")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.choices(kind=[
    app_commands.Choice(name="chat-reviver", value="chat"),
    app_commands.Choice(name="meme-dropper", value="meme"),
    app_commands.Choice(name="aesthetic-dropper", value="aesthetic"),
    app_commands.Choice(name="ai-auto", value="ai_auto"),
    app_commands.Choice(name="welcome", value="welcome"),
    app_commands.Choice(name="leave", value="leave"),
    app_commands.Choice(name="ALL", value="all"),
])
async def stop_cmd(interaction: discord.Interaction, kind: app_commands.Choice[str]):
    cid = interaction.channel.id
    stopped = []
    if kind.value in ("chat", "all") and active_chat_loops.pop(cid, None): stopped.append("chat")
    if kind.value in ("meme", "all") and active_meme_loops.pop(cid, None): stopped.append("meme")
    if kind.value in ("aesthetic", "all") and active_aesthetic_loops.pop(cid, None): stopped.append("aesthetic")
    if kind.value in ("ai_auto", "all") and ai_auto_channels.pop(cid, None): stopped.append("ai-auto")
    if kind.value in ("welcome", "all") and welcome_configs.pop(cid, None): stopped.append("welcome")
    if kind.value in ("leave", "all") and leave_configs.pop(cid, None): stopped.append("leave")
    if stopped: await interaction.response.send_message(embed=ok_embed(f"Stopped: **{', '.join(stopped)}**"), ephemeral=True)
    else: await interaction.response.send_message(embed=info_embed(f"Nothing running here."), ephemeral=True)

@tree.command(name="status", description="Compact bot status.")
@app_commands.checks.has_permissions(administrator=True)
async def status_cmd(interaction: discord.Interaction):
    e = brand_embed(title="⚙️ OBSIDIAN PROTOCOL", description="**Live System Status**")
    e.add_field(name="🌍 Toggles", value=f"{'✅' if GLOBAL_TOGGLES['clan_mode'] else '❌'} Clan\n{'✅' if GLOBAL_TOGGLES['music'] else '❌'} Music\n{'✅' if GLOBAL_TOGGLES['ai_chat'] else '❌'} AI", inline=True)
    e.add_field(name="📊 Stats", value=f"🎵 **{daily_song_count[0]}/{runtime_settings['daily_songs']}**\n⏱️ **{runtime_settings['cooldown']}s** cooldown\n🤖 **{runtime_settings['ai_limit']}/min** AI", inline=True)
    e.add_field(name="🔁 Active Loops", value=f"🗣️ **{len(active_chat_loops)}** chat • 😂 **{len(active_meme_loops)}** meme • 🖼️ **{len(active_aesthetic_loops)}** aesthetic", inline=False)
    e.add_field(name="📌 Configs", value=f"🎉 **{len(welcome_configs)}** welcome • 💔 **{len(leave_configs)}** leave\n🤖 **{len(ai_auto_channels)}** AI-auto", inline=False)
    await interaction.response.send_message(embed=e, ephemeral=True)

# ==========================================
# 🚨 ERROR HANDLER
# ==========================================
@tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        try: await interaction.response.send_message(embed=err_embed("**Admin only**, bro."), ephemeral=True)
        except: pass
    else:
        print(f"Command error: {error}")
        try: await interaction.response.send_message(embed=err_embed(f"`{error}`"), ephemeral=True)
        except: pass

# ==========================================
# ⏱️ TICKERS & BACKGROUND TASKS
# ==========================================
@tasks.loop(seconds=30)
async def master_tickers():
    now = time.time()
    for cid, cfg in list(active_chat_loops.items()):
        if now - cfg["last_drop"] >= cfg["interval"]:
            cfg["last_drop"] = now
            asyncio.create_task(fire_chat_drop(cid, cfg))
    for cid, cfg in list(active_meme_loops.items()):
        if now - cfg["last_drop"] >= cfg["interval"]:
            cfg["last_drop"] = now
            asyncio.create_task(fire_meme_drop(cid, cfg))
    for cid, cfg in list(active_aesthetic_loops.items()):
        if now - cfg["last_drop"] >= cfg["interval"]:
            cfg["last_drop"] = now
            asyncio.create_task(fire_aesthetic_drop(cid, cfg))

@tasks.loop(minutes=5)
async def afk_vc_kicker():
    for vc in discord_client.voice_clients:
        try:
            if len(vc.channel.members) == 1: vc.stop(); await vc.disconnect(force=True)
            elif not vc.is_playing(): await vc.disconnect(force=True)
        except: pass

@tasks.loop(hours=24)
async def op_name_enforcer():
    if not GLOBAL_TOGGLES["clan_mode"]: return
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
    except Exception as e: print(f"Sync Error: {e}")
    for loop in [master_tickers, afk_vc_kicker, op_name_enforcer]:
        if not loop.is_running(): loop.start()
    if GLOBAL_TOGGLES["clan_mode"]:
        for guild in discord_client.guilds:
            try:
                async for member in guild.fetch_members(limit=None):
                    perfect = make_op_name(member)
                    if member.display_name != perfect:
                        try: await member.edit(nick=perfect)
                        except: pass
            except: pass

# ==========================================
# 👋 JOIN / LEAVE
# ==========================================
@discord_client.event
async def on_member_join(member):
    if GLOBAL_TOGGLES["clan_mode"]:
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
    if message.author.bot: return

    user_id = message.author.id
    raw_content = message.content
    now = time.time()

    # 🚨 SECURITY CHECK
    is_pinged = discord_client.user.mentioned_in(message)
    is_soft_pinged = "forbid ai" in raw_content.lower()
    
    is_spamming, time_left = check_spam(user_id, raw_content, is_pinged)
    if is_spamming:
        # 🛑 NO MORE GHOSTING
        last_warn = user_spam_warned.get(user_id, 0)
        if now - last_warn > 5: 
            user_spam_warned[user_id] = now
            try: await message.reply(f"🛑 **Timed out.** Spam detected. Wait **{time_left}s**.")
            except: pass
        return

    # 🎭 SMART CHAT REACTIONS
    if message.channel.id in active_chat_loops and not (is_pinged or is_soft_pinged):
        if random.random() < 0.25:
            try:
                emojis = ["🔥", "💀", "👀", "💯", "😂", "👍", "✨", "🤔", "💪"]
                await message.add_reaction(random.choice(emojis))
            except: pass
        return 

    if not GLOBAL_TOGGLES["ai_chat"]: return
    is_auto_channel = message.channel.id in ai_auto_channels
    if not (is_pinged or is_soft_pinged or is_auto_channel): return

    # 🛡️ AI COOLDOWN
    if user_id in user_cooldowns and (now - user_cooldowns[user_id] < runtime_settings["cooldown"]):
        last_warn = user_spam_warned.get(user_id, 0)
        if now - last_warn > 20:
            user_spam_warned[user_id] = now
            remain = int(runtime_settings["cooldown"] - (now - user_cooldowns[user_id])) + 1
            try: await message.reply(f"⏱️ Chill bro — wait **{remain}s**.", delete_after=5)
            except: pass
        return

    stamps = [t for t in user_ai_calls.get(user_id, []) if now - t < AI_CALL_WINDOW]
    if len(stamps) >= runtime_settings["ai_limit"]: return
    while global_ai_calls and now - global_ai_calls[0] > 60: global_ai_calls.popleft()
    if len(global_ai_calls) >= GLOBAL_AI_LIMIT: return

    stamps.append(now)
    user_ai_calls[user_id] = deque(stamps, maxlen=runtime_settings["ai_limit"])
    global_ai_calls.append(now)
    user_cooldowns[user_id] = now
    prune_trackers()

    if is_pinged: raw_content = raw_content.replace(f'<@{discord_client.user.id}>', '').strip()

    # 🎵 MUSIC
    lower = raw_content.lower()
    if lower.startswith("join me"):
        if not GLOBAL_TOGGLES["music"]: await message.reply("🛑 Music disabled."); return
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
        except Exception as e: print(f"Music: {e}"); await message.reply("Music crashed.")
        return

    # OCR
    image_url = next((att.url for att in message.attachments if att.content_type and att.content_type.startswith('image/')), None)
    if not raw_content.strip() and not image_url:
        await message.reply("Tag me with something!"); return
    if image_url:
        await message.add_reaction("👁️")
        text = await scan_image_text(image_url)
        if not raw_content.strip(): raw_content = f"Read this image: '{text}'" if text else "What's in this image?"
        elif text: raw_content += f"\n\n[OCR: '{text}']"

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
        response = await ai_client.chat.completions.create(messages=chat_history[user_id], model="openai/gpt-oss-20b")
        reply = response.choices[0].message.content.strip()

        if "[SHIELD_ACTIVATED]" in reply:
            await message.reply(random.choice(["Bro really tried it. Keep crying 🥱", "Nice try, OP is laughing 💀", "Imagine sweating to trick a bot and failing 😭", "Zero power over the Enforcer 🛑", "Command denied. Get lost 🦅"])); return

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
                if blocked: await message.reply(embed=err_embed("Prompt rejected by generator."))
                else:
                    e = brand_embed(title=f"🎨 {clean}"[:256], description="Generated by FORB1D🔥")
                    e.set_image(url=img_url)
                    await message.reply(embed=e)
            return

        if "[VIDEO]" in reply:
            global active_video_generations
            video_prompt = reply.split("[VIDEO]")[1].strip()
            if user_id not in user_diamonds: user_diamonds[user_id] = {"diamonds": 5, "cooldown_end": 0}
            if now >= user_diamonds[user_id]["cooldown_end"] and user_diamonds[user_id]["diamonds"] == 0: user_diamonds[user_id]["diamonds"] = 5
            if user_diamonds[user_id]["diamonds"] <= 0:
                left = user_diamonds[user_id]["cooldown_end"] - now
                await message.reply(embed=err_embed(f"Out of diamonds. Restock in {int(left//3600)}h {int((left%3600)//60)}m.")); return
            if active_video_generations >= MAX_CONCURRENT_VIDEOS: await message.reply(embed=err_embed("Video server full.")); return
            user_diamonds[user_id]["diamonds"] -= 1
            if user_diamonds[user_id]["diamonds"] == 0: user_diamonds[user_id]["cooldown_end"] = now + 10800
            await message.reply(embed=info_embed(f"💎 1 Diamond spent. ({user_diamonds[user_id]['diamonds']}/5 left)"))
            active_video_generations += 1
            status = await message.reply(embed=info_embed("🔄 Connecting..."))
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
                    try: await status.edit(embed=info_embed(f"🚀 Attempt {attempt+1}/5..."))
                    except: pass
                    try:
                        video_url = await asyncio.to_thread(gen)
                        if video_url: break
                    except Exception as e: print(f"Video try: {e}")
                    if attempt < 4:
                        try: await status.edit(embed=info_embed(f"⚠️ Attempt {attempt+1}/5 failed. Retrying..."))
                        except: pass
                        await asyncio.sleep(15)
                if not video_url: raise Exception("Queue maxed.")
                await status.delete()
                await message.reply(f"🎥 **{video_prompt}**\n{video_url}")
            except Exception as e:
                print(f"Video crash: {e}")
                user_diamonds[user_id]["diamonds"] += 1
                try: await status.edit(embed=err_embed("GPUs slammed. (Diamond refunded 💎)"))
                except: pass
            finally: active_video_generations -= 1
            return

        if "[JOIN]" in reply:
            if not GLOBAL_TOGGLES["music"]: await message.reply("🛑 Music disabled."); return
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
            except Exception as e: print(f"Music: {e}"); await message.reply("Music crashed.")
            return

        if len(reply) > 1950: await message.reply(embed=err_embed("Response too long."))
        else: await message.reply(reply)
        chat_history[user_id].append({"role": "assistant", "content": response.choices[0].message.content})
    except Exception as e:
        print(f"API: {e}")
        if user_id in chat_history and len(chat_history[user_id]) > 1: chat_history[user_id].pop()
        err = str(e).lower()
        if any(x in err for x in ["rate limit", "429", "capacity"]): await message.reply(embed=err_embed("Servers spammed. Wait a min."))
        else: await message.reply(embed=err_embed("Core lagged. Try again."))

# ==========================================
# 🚀 ENTRY
# ==========================================
if __name__ == "__main__":
    keep_alive()
    discord_client.run(DISCORD_TOKEN)
