import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from rtpbot import texts
from rtpbot.data import load_catalog
from rtpbot.handlers import build_router


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise SystemExit("BOT_TOKEN is not set")

    cat = load_catalog()
    logging.info("Loaded %d slots from %d providers", len(cat.slots), len(cat.providers))

    bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True))
    dp = Dispatcher()
    dp.include_router(build_router(cat))

    # Profile texts and command menu (set once on every start, harmless to repeat).
    await bot.set_my_description(texts.BOT_DESCRIPTION)
    await bot.set_my_short_description(texts.BOT_SHORT_DESCRIPTION)
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Open the menu"),
            BotCommand(command="top", description="Highest published RTP"),
            BotCommand(command="about", description="How to read RTP and volatility"),
        ]
    )

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
