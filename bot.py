import os
import logging
from khl import Bot, Message

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bot")

TOKEN = os.getenv("KOOK_BOT_TOKEN")
bot = Bot(token=TOKEN)

@bot.command()
async def hi(msg: Message):
    await msg.reply("你好！")

@bot.command()
async def help(msg: Message):
    await msg.reply("命令: /hi, /help")

if __name__ == "__main__":
    bot.run()
