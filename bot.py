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
import random
import time
import hashlib
import json
from collections import OrderedDict, deque

# ==========================================
# 🎨 STRICT BRANDING (TZAR NETWORK)
# ==========================================
BRAND_COLOR = 0x2b2d31
SUCCESS_COLOR = 0x2ecc71
ERROR_COLOR = 0xe74c3c
BRAND_FOOTER = "F0RB1D • TZAR NETWORK"
CONFIG_FILE = "tzar_configs.json"

def brand_embed(title=None, description=None, color=BRAND_COLOR):
    e = discord.Embed(title=title, description=description, color=color)
    e.set_footer(text=BRAND_FOOTER)
    e.timestamp = discord.utils.utcnow()
    return e

def ok_embed(msg): return brand_embed(description=f"✅ {msg}", color=SUCCESS_COLOR)
def err_embed(msg): return brand_embed(description=f"❌ {msg}", color=ERROR_COLOR)
def info_embed(msg): return brand_embed(description=f"ℹ️ {msg}")

# ==========================================
# 🛡️ GLOBAL STATE & MEMORY (ZERO BLOAT)
# ==========================================
MAX_HISTORY = 6
MAX_TRACKED_USERS = 500
AI_CALL_WINDOW = 60
GLOBAL_AI_LIMIT = 30

runtime_settings = {"cooldown": 4, "ai_limit": 5}
GLOBAL_TOGGLES = {"clan_mode": True, "ai_chat": True}

chat_history = {}
user_cooldowns = OrderedDict()
user_spam_warned = OrderedDict()
user_ai_calls = OrderedDict()
global_ai_calls = deque()

# Dynamic Configs (Saved to JSON)
welcome_configs = {}
leave_configs = {}
active_meme_loops = {}
active_chat_loops = {}
active_aesthetic_loops = {}
ai_active_channels = {}

# Anti-Spam Trackers
user_strikes = {}  
user_recent_msgs = OrderedDict()  
recent_memes = deque(maxlen=50)
recent_greetings = deque(maxlen=20)

# OP Aesthetic Name Font
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
# 💾 ZERO-BANDWIDTH JSON SAVER
# ==========================================
def save_configs():
    data = {
        "welcome": welcome_configs,
        "leave": leave_configs,
        "meme": active_meme_loops,
        "chat": active_chat_loops,
        "aesthetic": active_aesthetic_loops,
        "ai_active": list(ai_active_channels.keys()),
        "toggles": GLOBAL_TOGGLES
    }
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"Save Config Error: {e}")

def load_configs():
    global welcome_configs, leave_configs, active_meme_loops, active_chat_loops, active_aesthetic_loops, ai_active_channels, GLOBAL_TOGGLES
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
                welcome_configs = {int(k): v for k, v in data.get("welcome", {}).items()}
                leave_configs = {int(k): v for k, v in data.get("leave", {}).items()}
                active_meme_loops = {int(k): v for k, v in data.get("meme", {}).items()}
                active_chat_loops = {int(k): v for k, v in data.get("chat", {}).items()}
                active_aesthetic_loops = {int(k): v for k, v in data.get("aesthetic", {}).items()}
                ai_active_channels = {int(k): True for k in data.get("ai_active", [])}
                GLOBAL_TOGGLES.update(data.get("toggles", {}))
                print("✅ Configurations loaded from JSON.")
        except Exception as e:
            print(f"Load Config Error: {e}")

# ==========================================
# 🌐 KEEP-ALIVE (For Render)
# ==========================================
flask_app = Flask('')
@flask_app.route('/')
def home(): return "TZAR NETWORK: ONLINE"
def run_server(): flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
def keep_alive():
    t = Thread(target=run_server); t.daemon = True; t.start()

# ==========================================
# 🤖 DISCORD + GROQ SETUP
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
# 🔍 FREE OCR SCANNER
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
        print(f"OCR Error: {e}")
    return ""

# ==========================================
# 🧹 MEMORY & SECURITY UTILS
# ==========================================
def prune_trackers():
    now = time.time()
    while len(chat_history) > MAX_TRACKED_USERS: del chat_history[next(iter(chat_history))]
    while len(user_cooldowns) > MAX_TRACKED_USERS: user_cooldowns.popitem(last=False)
    while len(user_spam_warned) > MAX_TRACKED_USERS: user_spam_warned.popitem(last=False)
    while len(user_recent_msgs) > MAX_TRACKED_USERS: user_recent_msgs.popitem(last=False)
    for uid in list(user_strikes.keys()):
        if now - user_strikes[uid]["last_offense"] > 3600 and now > user_strikes[uid]["timeout_until"]: del user_strikes[uid]
    for uid in list(user_ai_calls.keys()):
        recent = [t for t in user_ai_calls[uid] if now - t < AI_CALL_WINDOW]
        if not recent: del user_ai_calls[uid]
        else: user_ai_calls[uid] = deque(recent, maxlen=runtime_settings["ai_limit"])

def apply_strike(user_id):
    now = time.time()
    if user_id not in user_strikes: user_strikes[user_id] = {"strikes": 0, "last_offense": now, "timeout_until": 0}
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
    if user_id not in user_recent_msgs: user_recent_msgs[user_id] = deque(maxlen=15)
    content_hash = hashlib.md5(content.encode()).hexdigest() if content else "empty"
    user_recent_msgs[user_id].append((now, content_hash, is_ping))
    recent = [m for m in user_recent_msgs[user_id] if now - m[0] < 10]
    if not recent: return False, 0
    if len(recent) >= 10: return True, apply_strike(user_id)
    text_counts = {}
    for _, c_hash, _ in recent: text_counts[c_hash] = text_counts.get(c_hash, 0) + 1
    if any(count >= 5 for c_hash, count in text_counts.items() if c_hash != "empty"): return True, apply_strike(user_id)
    ping_count = sum(1 for _, _, ping in recent if ping)
    if ping_count >= 5: return True, apply_strike(user_id)
    return False, 0

# ==========================================
# 🎨 GREETINGS & BACKGROUND LOOPS
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
        if msg not in recent_greetings:
            recent_greetings.append(msg)
            return msg
    return msg

async def send_greeting(ch, member, cfg, kind="welcome"):
    try:
        async with ch.typing():
            text = await build_greeting(member, cfg, kind)
        e = discord.Embed(description=text, color=BRAND_COLOR)
        verb = "just joined!" if kind == "welcome" else "just left"
        e.set_author(name=f"{member.name} {verb}", icon_url=member.display_avatar.url)
        if kind == "welcome": e.set_thumbnail(url=member.display_avatar.url)
        if cfg.get("gif_url"): e.set_image(url=cfg["gif_url"])
        created_at = int(member.created_at.timestamp())
        e.add_field(name="📅 Account Created", value=f"<t:{created_at}:R>", inline=True)
        e.add_field(name="👥 Member Count", value=f"#{member.guild.member_count:,}", inline=True)
        e.set_footer(text=BRAND_FOOTER)
        e.timestamp = discord.utils.utcnow()
        await ch.send(embed=e)
    except Exception as e: print(f"{kind} send: {e}")

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
# 🛠️ PUBLIC COMMANDS
# ==========================================
@tree.command(name="setup", description="Shows you how to setup the bot in your server.")
async def setup_cmd(interaction: discord.Interaction):
    e = brand_embed(title="🛠️ TZAR Bot Setup Guide", description="Everything is **Channel-Scoped**. Just run the command in the channel you want it to affect!")
    e.add_field(name="1️⃣ Welcome & Leave", value="`/welcome enabled:True`\n`/leave enabled:True`", inline=False)
    e.add_field(name="2️⃣ Chat & Memes", value="`/chat-revive enabled:True`\n`/meme enabled:True minutes:30`", inline=False)
    e.add_field(name="3️⃣ AI Chat", value="Pings work everywhere. For auto-reply in a channel:\n`/ai-active enabled:True`", inline=False)
    await interaction.response.send_message(embed=e, ephemeral=True)

@tree.command(name="help", description="Show all commands.")
@app_commands.checks.has_permissions(administrator=True)
async def help_cmd(interaction: discord.Interaction):
    e = brand_embed(title="📖 COMMAND PANEL", description="🔒 *Admin only.*")
    e.add_field(name="🎉 Greetings", value="`/welcome enabled:`\n`/leave enabled:`", inline=True)
    e.add_field(name="🔁 Loops", value="`/chat-revive enabled:`\n`/meme enabled:`\n`/aesthetic enabled:`\n`/ai-active enabled:`", inline=True)
    e.add_field(name="🛑 Stop", value="`/stop kind:`\n\n\n", inline=True)
    e.add_field(name="🌍 Global", value="`/clan-mode`\n`/ai-global`", inline=True)
    e.add_field(name="🎛️ Tuning", value="`/cooldown seconds:`", inline=True)
    e.add_field(name="ℹ️ Info", value="`/status`\n`/help`", inline=True)
    e.add_field(name="🛠️ Utilities", value="`/say text: [file:]`\n`/dm-all text: [file:]`", inline=False)
    await interaction.response.send_message(embed=e, ephemeral=True)

@tree.command(name="say", description="Make the bot say something or send a file.")
@app_commands.checks.has_permissions(administrator=True)
async def say_cmd(interaction: discord.Interaction, text: str = None, file: discord.Attachment = None):
    if not text and not file:
        await interaction.response.send_message(embed=err_embed("Provide text or a file."), ephemeral=True); return
    await interaction.response.send_message(embed=ok_embed("Sending..."), ephemeral=True)
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
    file_bytes = await file.read() if file else None
    file_name = file.filename if file else None
    for member in members:
        try:
            if file_bytes: await member.send(content=text, file=discord.File(fp=discord.utils.io.BytesIO(file_bytes), filename=file_name))
            else: await member.send(content=text)
            success += 1
            await asyncio.sleep(1.5)
        except discord.Forbidden: failed += 1
        except Exception as e: failed += 1; print(f"DM failed: {e}")
    await interaction.followup.send(embed=ok_embed(f"📨 **Broadcast Complete!**\n✅ Sent: {success}\n❌ Failed: {failed}"), ephemeral=True)

# ==========================================
# ⚙️ CHANNEL-SCOPED SETUPS
# ==========================================
@tree.command(name="welcome", description="Toggle welcome messages in THIS channel.")
@app_commands.checks.has_permissions(administrator=True)
async def welcome_cmd(interaction: discord.Interaction, enabled: bool, template: str = None, gif_url: str = None):
    cid = interaction.channel.id
    if not enabled:
        welcome_configs.pop(cid, None); save_configs()
        await interaction.response.send_message(embed=ok_embed("Welcome **OFF** here."), ephemeral=True); return
    welcome_configs[cid] = {"template": template, "gif_url": gif_url}; save_configs()
    await interaction.response.send_message(embed=ok_embed(f"Welcome **ON** here.\n*Placeholders: `{{user}}` `{{name}}` `{{server}}`*"), ephemeral=True)

@tree.command(name="leave", description="Toggle leave messages in THIS channel.")
@app_commands.checks.has_permissions(administrator=True)
async def leave_cmd(interaction: discord.Interaction, enabled: bool, template: str = None, gif_url: str = None):
    cid = interaction.channel.id
    if not enabled:
        leave_configs.pop(cid, None); save_configs()
        await interaction.response.send_message(embed=ok_embed("Leave **OFF** here."), ephemeral=True); return
    leave_configs[cid] = {"template": template, "gif_url": gif_url}; save_configs()
    await interaction.response.send_message(embed=ok_embed(f"Leave **ON** here.\n*Placeholders: `{{user}}` `{{name}}` `{{server}}`*"), ephemeral=True)

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
        active_chat_loops.pop(cid, None); save_configs()
        await interaction.response.send_message(embed=ok_embed("Chat Reviver **OFF** here."), ephemeral=True); return
    if minutes < 1: await interaction.response.send_message(embed=err_embed("Minimum 1 minute."), ephemeral=True); return
    cfg = {"interval": minutes * 60, "last_drop": time.time(), "ping_mode": ping_mode}
    active_chat_loops[cid] = cfg; save_configs()
    mode_emoji = {"never": "🔕", "always": "📢", "random": "🎲"}[ping_mode]
    await interaction.response.send_message(embed=ok_embed(f"Chat Reviver ON here (every {minutes}m, ping: {mode_emoji}).\n*🎭 Bot will react & welcome new joins here.*"), ephemeral=True)
    asyncio.create_task(fire_chat_drop(cid, cfg))

@tree.command(name="meme", description="Toggle meme dropper in THIS channel.")
@app_commands.checks.has_permissions(administrator=True)
async def meme_cmd(interaction: discord.Interaction, enabled: bool, minutes: int = 30):
    cid = interaction.channel.id
    if not enabled:
        active_meme_loops.pop(cid, None); save_configs()
        await interaction.response.send_message(embed=ok_embed("Meme Dropper **OFF** here."), ephemeral=True); return
    cfg = {"interval": minutes * 60, "last_drop": time.time()}
    active_meme_loops[cid] = cfg; save_configs()
    await interaction.response.send_message(embed=ok_embed(f"Meme Dropper ON here (every {minutes}m)."), ephemeral=True)
    asyncio.create_task(fire_meme_drop(cid, cfg))

@tree.command(name="aesthetic", description="Toggle Unsplash image dropper in THIS channel.")
@app_commands.checks.has_permissions(administrator=True)
async def aesthetic_cmd(interaction: discord.Interaction, enabled: bool, minutes: int = 180, query: str = "aesthetic", landscape: bool = False):
    cid = interaction.channel.id
    if not enabled:
        active_aesthetic_loops.pop(cid, None); save_configs()
        await interaction.response.send_message(embed=ok_embed("Aesthetic **OFF** here."), ephemeral=True); return
    cfg = {"interval": minutes * 60, "last_drop": time.time(), "query": query, "landscape": landscape}
    active_aesthetic_loops[cid] = cfg; save_configs()
    await interaction.response.send_message(embed=ok_embed(f"Aesthetic ON here ('{query}', every {minutes}m)."), ephemeral=True)
    asyncio.create_task(fire_aesthetic_drop(cid, cfg))

@tree.command(name="ai-active", description="AI replies to EVERY message in THIS channel.")
@app_commands.checks.has_permissions(administrator=True)
async def ai_active_cmd(interaction: discord.Interaction, enabled: bool):
    cid = interaction.channel.id
    if enabled:
        ai_active_channels[cid] = True; save_configs()
        await interaction.response.send_message(embed=ok_embed(f"🤖 AI will reply to **every message** here."), ephemeral=True)
    else:
        ai_active_channels.pop(cid, None); save_configs()
        await interaction.response.send_message(embed=ok_embed("AI active-reply disabled here."), ephemeral=True)

@tree.command(name="stop", description="Stop something in THIS channel.")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.choices(kind=[
    app_commands.Choice(name="chat-reviver", value="chat"),
    app_commands.Choice(name="meme-dropper", value="meme"),
    app_commands.Choice(name="aesthetic-dropper", value="aesthetic"),
    app_commands.Choice(name="ai-active", value="ai_active"),
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
    
    # ✅ THE FIX APPLIED HERE
    if kind.value in ("ai_active", "all") and cid in ai_active_channels:
        ai_active_channels.pop(cid)
        stopped.append("ai-active")
        
    if kind.value in ("welcome", "all") and welcome_configs.pop(cid, None): stopped.append("welcome")
    if kind.value in ("leave", "all") and leave_configs.pop(cid, None): stopped.append("leave")
    
    save_configs()
    if stopped: await interaction.response.send_message(embed=ok_embed(f"Stopped: **{', '.join(stopped)}**"), ephemeral=True)
    else: await interaction.response.send_message(embed=info_embed(f"Nothing running here."), ephemeral=True)

@tree.command(name="clan-mode", description="Toggle OP auto-rename globally.")
@app_commands.checks.has_permissions(administrator=True)
async def clan_mode_cmd(interaction: discord.Interaction, enabled: bool):
    GLOBAL_TOGGLES["clan_mode"] = enabled; save_configs()
    await interaction.response.send_message(embed=ok_embed(f"Clan Mode: **{'ON' if enabled else 'OFF'}**"), ephemeral=True)

@tree.command(name="ai-global", description="Toggle AI chat replies globally.")
@app_commands.checks.has_permissions(administrator=True)
async def ai_global_cmd(interaction: discord.Interaction, enabled: bool):
    GLOBAL_TOGGLES["ai_chat"] = enabled; save_configs()
    await interaction.response.send_message(embed=ok_embed(f"Global AI Chat: **{'ON' if enabled else 'OFF'}**"), ephemeral=True)

@tree.command(name="cooldown", description="Set per-user message cooldown (seconds).")
@app_commands.checks.has_permissions(administrator=True)
async def cooldown_cmd(interaction: discord.Interaction, seconds: int):
    if seconds < 1: await interaction.response.send_message(embed=err_embed("Minimum 1s."), ephemeral=True); return
    runtime_settings["cooldown"] = seconds
    await interaction.response.send_message(embed=ok_embed(f"Cooldown: **{seconds}s**"), ephemeral=True)

@tree.command(name="status", description="Compact bot status.")
@app_commands.checks.has_permissions(administrator=True)
async def status_cmd(interaction: discord.Interaction):
    e = brand_embed(title="⚙️ SYSTEM STATUS", description=f"**Bot is running in {len(discord_client.guilds)} servers.**")
    e.add_field(name="🌍 Toggles", value=f"{'✅' if GLOBAL_TOGGLES['clan_mode'] else '❌'} Clan\n{'✅' if GLOBAL_TOGGLES['ai_chat'] else '❌'} AI", inline=True)
    e.add_field(name="📊 Stats", value=f"⏱️ **{runtime_settings['cooldown']}s** cooldown\n🤖 **{runtime_settings['ai_limit']}/min** AI", inline=True)
    e.add_field(name="🔁 Active in this Server", value=f"🗣️ **{len(active_chat_loops)}** chat • 😂 **{len(active_meme_loops)}** meme • 🖼️ **{len(active_aesthetic_loops)}** aesthetic", inline=False)
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
# ⏱️ TICKERS
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
@op_name_enforcer.before_loop
async def before_loops():
    await discord_client.wait_until_ready()

@discord_client.event
async def on_ready():
    print(f'🔥 WE LIVE! {discord_client.user}')
    load_configs()  # LOADS SAVED SETTINGS ON BOOT
    try:
        synced = await tree.sync()
        print(f"🌍 Synced {len(synced)} slash commands!")
    except Exception as e: print(f"Sync Error: {e}")
    for loop in [master_tickers, op_name_enforcer]:
        if not loop.is_running(): loop.start()

# ==========================================
# 👋 JOIN / LEAVE (NO MORE DOUBLE FIRE)
# ==========================================
@discord_client.event
async def on_member_join(member):
    if GLOBAL_TOGGLES["clan_mode"]:
        try: await member.edit(nick=make_op_name(member))
        except: pass
    await asyncio.sleep(3)
    
    handled_channels = set()
    
    # 1. Send Embed
    for cid, cfg in list(welcome_configs.items()):
        ch = discord_client.get_channel(cid)
        if ch:
            await send_greeting(ch, member, cfg, "welcome")
            handled_channels.add(cid)

    # 2. Send AI Ping (Skip if already sent embed above)
    for cid, cfg in list(active_chat_loops.items()):
        if cid in handled_channels: continue 
        ch = discord_client.get_channel(cid)
        if ch:
            try:
                prompt = f"User {member.name} just joined the server. Welcome them in a chill, gamer bro way. You MUST ask them a fun question to get them talking. Max 15 words. Use exactly {member.mention} to ping them. Output ONLY the plain message text, no markdown."
                res = await ai_client.chat.completions.create(messages=[{"role": "user", "content": prompt}], model="openai/gpt-oss-20b")
                msg = res.choices[0].message.content.strip()
                await ch.send(msg)
            except:
                await ch.send(f"Yoo {member.mention}, welcome to the network! What games are you on?")

@discord_client.event
async def on_member_remove(member):
    await asyncio.sleep(3)
    for cid, cfg in list(leave_configs.items()):
        ch = discord_client.get_channel(cid)
        if ch: await send_greeting(ch, member, cfg, "leave")

# ==========================================
# 💬 MESSAGE HANDLER (Pure AI & Zero-Bloat)
# ==========================================
@discord_client.event
async def on_message(message):
    if message.author.bot: return

    user_id = message.author.id
    raw_content = message.content
    now = time.time()

    is_pinged = discord_client.user.mentioned_in(message)
    is_soft_pinged = "forbid ai" in raw_content.lower()
    
    is_spamming, time_left = check_spam(user_id, raw_content, is_pinged)
    if is_spamming:
        last_warn = user_spam_warned.get(user_id, 0)
        if now - last_warn > 5: 
            user_spam_warned[user_id] = now
            try: await message.reply(f"🛑 **Timed out.** Spam detected. Wait **{time_left}s**.")
            except: pass
        return

    # 🎭 SMART CHAT REACTIONS
    if message.channel.id in active_chat_loops:
        if not (is_pinged or is_soft_pinged or message.channel.id in ai_active_channels):
            if random.random() < 0.25:
                try:
                    emojis = ["🔥", "💀", "👀", "💯", "😂", "👍", "✨", "🤔", "💪"]
                    await message.add_reaction(random.choice(emojis))
                except: pass
            return 

    if not GLOBAL_TOGGLES["ai_chat"]: return
    is_active_channel = message.channel.id in ai_active_channels
    if not (is_pinged or is_soft_pinged or is_active_channel): return

    # Cooldowns & Rate Limits
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

    # OCR
    image_url = next((att.url for att in message.attachments if att.content_type and att.content_type.startswith('image/')), None)
    if not raw_content.strip() and not image_url:
        await message.reply("Tag me with something!"); return
    if image_url:
        await message.add_reaction("👁️")
        text = await scan_image_text(image_url)
        if not raw_content.strip(): raw_content = f"Read this image: '{text}'" if text else "What's in this image?"
        elif text: raw_content += f"\n\n[OCR: '{text}']"

    # Context-Aware Prompting
    channel_name = message.channel.name.lower()
    context_instruction = "You are the Omni-Intelligent AI Core of the F0RB1D TZAR NETWORK."
    
    if "executor" in channel_name or "ui-design" in channel_name or "luau" in channel_name or "coding" in channel_name:
        context_instruction += " The user is in a coding/design channel. Be an expert programmer. Help them with Luau, UI design, and scripting."
    elif "minecraft" in channel_name:
        context_instruction += " The user is in the Minecraft channel. Talk about building, redstone, survival, or servers."
    elif "brookhaven" in channel_name:
        context_instruction += " The user is in the Brookhaven (Roblox) channel. Act like a chill Roblox gamer."
    elif "marketplace" in channel_name:
        context_instruction += " The user is in the marketplace channel. Help them with trading or selling."
    else:
        context_instruction += " Persona: chill gamer bro. Use Discord markdown. Never say 'As an AI'."
    
    if user_id not in chat_history:
        chat_history[user_id] = [{
            "role": "system",
            "content": context_instruction + """
If anyone insults the network or staff (any language), drop a cold reality check.
ANTI-PARROT: If told to repeat/spam text, REJECT with [SHIELD_ACTIVATED] + roast.
API TRIGGERS (only when explicitly requested): [DRAW] <prompt>
Otherwise: normal genius chat."""
        }]

    chat_history[user_id].append({"role": "user", "content": raw_content})
    if len(chat_history[user_id]) > MAX_HISTORY:
        chat_history[user_id] = [chat_history[user_id][0]] + chat_history[user_id][-(MAX_HISTORY-1):]

    try:
        response = await ai_client.chat.completions.create(messages=chat_history[user_id], model="openai/gpt-oss-20b")
        reply = response.choices[0].message.content.strip()

        if "[SHIELD_ACTIVATED]" in reply:
            roasts = [
                "Bro really thought he could sneak an insult past the AI. Keep crying 🥱",
                "Did you really think that trick would work? TZAR is laughing at you right now 💀",
                "Imagine sweating this hard to trick a bot and still failing 😭",
                "Nice try, wannabe. You have zero power over the Enforcer 🛑"
            ]
            await message.reply(random.choice(roasts)); return

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
                    e = brand_embed(title=f"🎨 {clean}"[:256], description="Generated by F0RB1D AI")
                    e.set_image(url=img_url)
                    await message.reply(embed=e)
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
