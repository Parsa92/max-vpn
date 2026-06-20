import asyncio
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
import config
from database import init_db
from sales_bot.handlers import router

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("sales_bot")


async def main():
    await init_db()
    logger.info("Database initialized")

    bot = Bot(token=config.BOT_TOKEN, parse_mode=ParseMode.HTML)
    dp = Dispatcher()
    dp.include_router(router)

    logger.info("Sales bot starting...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
