from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, Update

from . import config, handlers, jobs
from .db import db
from .storage import SupabaseStorage

logging.basicConfig(level=logging.INFO)

storage = SupabaseStorage()
dp = Dispatcher(storage=storage)
dp.include_router(handlers.router)
dp.update.outer_middleware(handlers.UserMW())

COMMANDS = [
    BotCommand(command="today", description="📅 План на сьогодні"),
    BotCommand(command="tomorrow", description="🌅 План на завтра"),
    BotCommand(command="week", description="🗓 Тиждень"),
    BotCommand(command="done", description="🌙 Підсумок дня"),
    BotCommand(command="n", description="📝 Швидка нотатка"),
    BotCommand(command="find", description="🔎 Пошук"),
    BotCommand(command="stats", description="📊 Статистика"),
    BotCommand(command="settings", description="⚙️ Налаштування"),
    BotCommand(command="help", description="🪴 Як користуватись"),
]


def make_bot() -> Bot:
    return Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML,
                                                              link_preview_is_disabled=True))


async def handle_update(body: dict) -> None:
    bot = make_bot()
    await db.open()
    storage.reset_cache()
    try:
        update = Update.model_validate(body, context={"bot": bot})
        await dp.feed_update(bot, update)
    finally:
        await db.close()
        await bot.session.close()


async def handle_cron() -> dict:
    bot = make_bot()
    await db.open()
    try:
        return await jobs.run(bot)
    finally:
        await db.close()
        await bot.session.close()


async def setup(host: str) -> dict:
    bot = make_bot()
    try:
        url = f"https://{host}/api/webhook"
        await bot.set_webhook(url, secret_token=config.WEBHOOK_SECRET,
                              allowed_updates=["message", "callback_query"], drop_pending_updates=True)
        await bot.set_my_commands(COMMANDS)
        await bot.set_my_short_description("Особистий планер: задачі, нотатки, нагадування і підсумки дня 🪴")
        await bot.set_my_description(
            "🪴 Твій особистий планер у Telegram\n\n"
            "• задачі на день з пріоритетами й тегами\n• нагадування в потрібний час\n"
            "• нотатки\n• ранковий план і вечірній підсумок\n• автоперенос невиконаного\n• статистика й серії\n\n"
            "Натисни «Почати» 👇")
        me = await bot.get_me()
        info = await bot.get_webhook_info()
        return {"ok": True, "bot": me.username, "webhook": info.url, "pending": info.pending_update_count}
    finally:
        await bot.session.close()
