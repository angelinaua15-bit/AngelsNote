"""Minute-by-minute background work: reminders, morning plan, evening summary, rollover."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from html import escape

from aiogram import Bot

from . import db, ui
from .handlers import day_screen, summary_screen

log = logging.getLogger("planner.cron")
WINDOW_MIN = 180  # send morning/evening message only within 3h after the chosen time


def _mins(hm: str) -> int:
    h, m = hm.split(":")
    return int(h) * 60 + int(m)


def in_window(now_hm: str, target: str) -> bool:
    d = _mins(now_hm) - _mins(target)
    return 0 <= d < WINDOW_MIN


async def send_reminders(bot: Bot) -> int:
    n = 0
    for t in await db.claim_reminders():
        text, kb = ui.reminder_msg(t)
        try:
            await bot.send_message(t["user_id"], text, reply_markup=kb)
            n += 1
        except Exception:
            log.exception("reminder %s failed", t["id"])
    return n


async def user_tick(bot: Bot, u: dict) -> None:
    now = ui.now_local(u)
    today = now.date()
    hm = now.strftime("%H:%M")
    moved = 0
    if u.get("last_rollover") != today.isoformat():
        moved = await db.rollover(u["id"], today)
        u["last_rollover"] = today.isoformat()

    if u["morning_on"] and u.get("last_morning") != today.isoformat() and in_window(hm, u["morning_time"]):
        await db.update_user(u["id"], last_morning=today.isoformat())
        name = escape(u.get("first_name") or "")
        tasks = await db.day_tasks(u["id"], today)
        n = len(tasks)
        header = f"☀️ <b>Доброго ранку{', ' + name if name else ''}!</b>\n"
        if n:
            header += f"Сьогодні в планах {n} {ui.plural(n, 'задача', 'задачі', 'задач')}. Ти впораєшся 💪"
        else:
            header += "План на сьогодні ще порожній — напиши, що хочеш встигнути ✍️"
        if moved:
            header += f"\n↪️ З учора перенесено: {moved}"
        text, kb = await day_screen(u, today, header=header)
        await bot.send_message(u["id"], text, reply_markup=kb)

    if u["evening_on"] and u.get("last_evening") != today.isoformat() and in_window(hm, u["evening_time"]):
        await db.update_user(u["id"], last_evening=today.isoformat())
        text, kb = await summary_screen(u, today)
        await bot.send_message(u["id"], "Час підбити підсумки ✨\n\n" + text, reply_markup=kb)


async def run(bot: Bot) -> dict:
    sent = await send_reminders(bot)
    users = await db.all_users()
    for u in users:
        try:
            await user_tick(bot, u)
        except Exception:
            log.exception("tick for %s failed", u["id"])
    return {"reminders": sent, "users": len(users)}
