import os
import asyncio
import logging
import tempfile
import subprocess
import signal
import httpx
import json

from khl import Bot, Message

# 日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("kook-bot")

# 获取 Token
TOKEN = os.getenv("KOOK_BOT_TOKEN")

# 创建 Bot
bot = Bot(token=TOKEN)

# 存储
voice_channels = {}
voice_info = {}
ffmpeg_processes = {}

# ========== 音乐下载 ==========
async def download_music(query: str):
    """网易云音乐下载"""
    try:
        api = "https://netease-cloud-music-api-gamma.vercel.app"
        
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{api}/search?keywords={query}&limit=1", timeout=10)
            data = r.json()
            
            if data.get("code") != 200 or not data.get("result", {}).get("songs"):
                return None, "未找到歌曲"
            
            song = data["result"]["songs"][0]
            song_id = song["id"]
            song_name = song["name"]
            
            r = await client.get(f"{api}/song/url?id={song_id}", timeout=10)
            data = r.json()
            
            if data.get("code") != 200:
                return None, "获取链接失败"
            
            music_url = data.get("data", [{}])[0].get("url")
            if not music_url:
                return None, "无法播放（可能是VIP歌曲）"
            
            r = await client.get(music_url, timeout=30)
            if len(r.content) < 10000:
                return None, "文件太小"
            
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
            tmp.write(r.content)
            tmp.close()
            
            return tmp.name, song_name
            
    except Exception as e:
        logger.error(f"下载错误: {e}")
        return None, str(e)

# ========== 语音功能 ==========
async def join_voice(guild_id: str, channel_id: str):
    """加入语音频道"""
    try:
        # 使用 httpx 直接调用 API
        async with httpx.AsyncClient() as client:
            r = await client.post(
                "https://www.kookapp.cn/api/v3/voice/join",
                headers={"Authorization": f"Bot {TOKEN}"},
                json={"channel_id": channel_id},
                timeout=10.0
            )
            result = r.json()
            logger.info(f"Join voice result: {result}")
        
        if result.get("code") == 0 and result.get("data", {}).get("ip"):
            voice_channels[guild_id] = channel_id
            voice_info[guild_id] = result["data"]
            return True, result["data"]
        else:
            error = result.get("message", "未知错误")
            return False, error
            
    except Exception as e:
        logger.error(f"Join voice error: {e}")
        return False, str(e)

async def leave_voice(guild_id: str):
    """离开语音频道"""
    try:
        if guild_id in ffmpeg_processes:
            try:
                ffmpeg_processes[guild_id].terminate()
                del ffmpeg_processes[guild_id]
            except:
                pass
        
        channel_id = voice_channels.get(guild_id)
        if channel_id:
            async with httpx.AsyncClient() as client:
                await client.post(
                    "https://www.kookapp.cn/api/v3/voice/leave",
                    headers={"Authorization": f"Bot {TOKEN}"},
                    json={"channel_id": channel_id},
                    timeout=10.0
                )
        
        voice_channels.pop(guild_id, None)
        voice_info.pop(guild_id, None)
        return True
        
    except Exception as e:
        logger.error(f"Leave voice error: {e}")
        return False

async def play_music(guild_id: str, audio_file: str):
    """播放音乐"""
    try:
        info = voice_info.get(guild_id)
        if not info:
            return False, "没有语音连接信息"
        
        ip = info.get("ip")
        port = info.get("port")
        ssrc = info.get("ssrc", 0)
        
        cmd = [
            "ffmpeg", "-re", "-i", audio_file,
            "-ar", "48000", "-ac", "2",
            "-c:a", "libopus", "-b:a", "128k",
            "-f", "rtp",
            f"rtp://{ip}:{port}?ssrc={ssrc}"
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE
        )
        
        ffmpeg_processes[guild_id] = process
        await process.communicate()
        
        if guild_id in ffmpeg_processes:
            del ffmpeg_processes[guild_id]
        
        return True, "播放完成"
        
    except Exception as e:
        logger.error(f"Play error: {e}")
        return False, str(e)

# ========== 命令（带 / 前缀）==========

@bot.command(name="hi")
async def cmd_hi(msg: Message):
    await msg.reply("🎵 你好！音乐机器人已就绪")

@bot.command(name="join")
async def cmd_join(msg: Message, channel_id: str):
    await msg.reply(f"🎤 正在加入频道 {channel_id}...")
    
    guild_id = msg.ctx.guild.id if msg.ctx.guild else None
    if not guild_id:
        await msg.reply("❌ 无法获取服务器ID")
        return
    
    success, result = await join_voice(guild_id, channel_id)
    
    if success:
        await msg.reply(f"✅ 已加入！\nIP: {result.get('ip')}:{result.get('port')}")
    else:
        await msg.reply(f"❌ 加入失败: {result}")

@bot.command(name="leave")
async def cmd_leave(msg: Message):
    guild_id = msg.ctx.guild.id if msg.ctx.guild else None
    if not guild_id or guild_id not in voice_channels:
        await msg.reply("⚠️ 当前不在语音频道")
        return
    
    await leave_voice(guild_id)
    await msg.reply("👋 已离开语音频道")

@bot.command(name="play")
async def cmd_play(msg: Message, *, query: str):
    guild_id = msg.ctx.guild.id if msg.ctx.guild else None
    if not guild_id or guild_id not in voice_channels:
        await msg.reply("⚠️ 请先使用 /join 加入语音频道")
        return
    
    await msg.reply(f"🔍 搜索: {query}")
    
    file_path, song_name = await download_music(query)
    
    if not file_path:
        await msg.reply(f"❌ 失败: {song_name}")
        return
    
    await msg.reply(f"▶️ 开始播放: {song_name}")
    asyncio.create_task(play_music(guild_id, file_path))

@bot.command(name="stop")
async def cmd_stop(msg: Message):
    guild_id = msg.ctx.guild.id if msg.ctx.guild else None
    if not guild_id:
        await msg.reply("⚠️ 无法获取服务器ID")
        return
        
    if guild_id in ffmpeg_processes:
        ffmpeg_processes[guild_id].terminate()
        await msg.reply("⏹️ 已停止")
    else:
        await msg.reply("⚠️ 当前没有播放")

@bot.command(name="help")
async def cmd_help(msg: Message):
    help_text = """**命令列表**
/hi - 测试
/join <频道ID> - 加入语音频道
/leave - 离开语音频道
/play <歌名> - 播放音乐
/stop - 停止播放"""
    await msg.reply(help_text)

# ========== 启动 ==========
if __name__ == "__main__":
    bot.run()
