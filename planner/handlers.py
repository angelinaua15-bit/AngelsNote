from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from html import escape
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter, or_f
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, Update

from . import config, db, ui
from .parse import parse_date, parse_many, parse_when

log = logging.getLogger("planner")
router = Router()


class S(StatesGroup):
    add = State()
    note = State()
    title = State()
    date = State()
    remind = State()
    tag = State()


# ---------------------------------------------------------------- middleware
class UserMW(BaseMiddleware):
    async def __call__(self, handler: Callable[[Update, dict], Awaitable[Any]], event: Update, data: dict):
        fu = data.get("event_from_user")
        if fu is None or fu.is_bot:
            return
        user = await db.get_user(fu.id)
        if not user:
            if config.PRIVATE and await db.any_user():
                if event.message:
                    await event.message.answer("🔒 Це особистий планер, і в нього вже є власниця.")
                elif event.callback_query:
                    await event.callback_query.answer("🔒 Особистий планер", show_alert=True)
                return
            user = await db.create_user(fu.id, fu.first_name)
        t = ui.today(user)
        if user.get("last_rollover") != t.isoformat():
            await db.rollover(user["id"], t)
            user["last_rollover"] = t.isoformat()
        data["user"] = user
        return await handler(event, data)


# ---------------------------------------------------------------- helpers
async def show(target: Message | CallbackQuery, text: str, kb=None) -> None:
    if isinstance(target, CallbackQuery):
        try:
            await target.message.edit_text(text, reply_markup=kb)
            return
        except TelegramBadRequest as e:
            if "not modified" in str(e):
                return
            await target.message.answer(text, reply_markup=kb)
            return
    await target.answer(text, reply_markup=kb)


async def day_screen(user: dict, day: date, header: str = ""):
    uid = user["id"]
    t = ui.today(user)
    want_ovd = day == t and not user.get("auto_rollover", True)
    tasks, nn, ovd = await asyncio.gather(
        db.day_tasks(uid, day), db.notes_count(uid, day),
        db.overdue_count(uid, t) if want_ovd else asyncio.sleep(0, 0))
    return ui.day_view(user, day, tasks, nn, ovd or 0, header=header)


async def summary_screen(user: dict, day: date):
    uid = user["id"]
    done, planned, notes, tomorrow = await asyncio.gather(
        db.done_on(uid, day), db.day_tasks(uid, day), db.day_notes(uid, day),
        db.day_tasks(uid, day + timedelta(days=1)))
    left = [x for x in planned if not x["done"]]
    tomorrow = [x for x in tomorrow if not x["done"]]
    return ui.summary_view(user, day, done, left, notes, tomorrow)


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def iso(s: str) -> date:
    return date.fromisoformat(s)


async def prompt(target: Message | CallbackQuery, text: str) -> None:
    msg = target.message if isinstance(target, CallbackQuery) else target
    await msg.answer(text, reply_markup=ui.CANCEL_KB)
    if isinstance(target, CallbackQuery):
        await target.answer()


def remind_iso(user: dict, d: date, hh: int, mm: int = 0) -> str:
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=ui.tzinfo(user)).isoformat()


async def add_from_text(user: dict, text: str, default_day: date | None) -> str | None:
    """Returns header for the resulting day view, or None if nothing parsed."""
    t = ui.today(user)
    now = ui.now_local(user)
    items = parse_many(text, t, default_day)
    if not items:
        return None
    rows = []
    for p in items:
        row = {"user_id": user["id"], "title": p.title, "due": p.due.isoformat(),
               "priority": p.priority, "tag": p.tag}
        if p.at:
            dt = datetime.combine(p.due, p.at, tzinfo=ui.tzinfo(user))
            if dt > now:
                row["remind_at"] = dt.isoformat()
        rows.append(row)
    for r in rows:
        r.setdefault("remind_at", None)
    created = await db.add_tasks(rows)
    if len(created) == 1:
        c = created[0]
        bits = [ui.d_short(iso(c["due"]), t).lower()]
        r = ui.remind_local(c, user)
        if r:
            bits.append(f"⏰ {r:%H:%M}")
        if c.get("tag"):
            bits.append(f"#{escape(c['tag'])}")
        if c["priority"]:
            bits.append(ui.PRIO[c["priority"]])
        return f"✨ Додано: <b>{escape(c['title'])}</b>\n<i>{' · '.join(bits)}</i>"
    n = len(created)
    return f"✨ Додано {n} {ui.plural(n, 'задачу', 'задачі', 'задач')}"


# ---------------------------------------------------------------- commands & menu
@router.message(CommandStart(), StateFilter("*"))
async def cmd_start(m: Message, state: FSMContext, user: dict):
    await state.clear()
    name = escape(m.from_user.first_name or "")
    await m.answer(
        f"Привіт{', ' + name if name else ''}! 🪴\n\n"
        "Я твій особистий планер. Пиши мені задачі просто текстом — "
        "я розберу дату, час, тег і пріоритет. Щоранку надішлю план, а ввечері — підсумок дня.\n\n"
        "Спробуй: <code>Підготувати звіт завтра о 11:00 #робота !!</code>\n\n"
        "Усі підказки — /help",
        reply_markup=ui.main_kb())
    text, kb = await day_screen(user, ui.today(user))
    await m.answer(text, reply_markup=kb)


@router.message(Command("help"), StateFilter("*"))
async def cmd_help(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(ui.HELP, reply_markup=ui.main_kb())


@router.message(StateFilter("*"), or_f(F.text == ui.BTN_TODAY, Command("today")))
async def menu_today(m: Message, state: FSMContext, user: dict):
    await state.clear()
    text, kb = await day_screen(user, ui.today(user))
    await m.answer(text, reply_markup=kb)


@router.message(StateFilter("*"), or_f(F.text == ui.BTN_TOMORROW, Command("tomorrow")))
async def menu_tomorrow(m: Message, state: FSMContext, user: dict):
    await state.clear()
    text, kb = await day_screen(user, ui.today(user) + timedelta(days=1))
    await m.answer(text, reply_markup=kb)


@router.message(StateFilter("*"), F.text == ui.BTN_ADD)
async def menu_add(m: Message, state: FSMContext, user: dict):
    await state.set_state(S.add)
    await state.set_data({"day": ui.today(user).isoformat()})
    await prompt(m, "➕ <b>Що додати на сьогодні?</b>\n\nМожна кілька задач — кожну з нового рядка. "
                    "Дата, час, #тег і ! теж працюють.")


@router.message(StateFilter("*"), F.text == ui.BTN_NOTE)
async def menu_note(m: Message, state: FSMContext, user: dict):
    await state.set_state(S.note)
    await state.set_data({"day": ui.today(user).isoformat()})
    await prompt(m, "📝 <b>Пиши нотатку</b> — думку, ідею, результат зустрічі, що завгодно.")


@router.message(StateFilter("*"), or_f(F.text == ui.BTN_WEEK, Command("week")))
async def menu_week(m: Message, state: FSMContext, user: dict):
    await state.clear()
    start = week_start(ui.today(user))
    tasks = await db.range_tasks(user["id"], start, start + timedelta(days=6))
    text, kb = ui.week_view(user, start, tasks)
    await m.answer(text, reply_markup=kb)


@router.message(StateFilter("*"), or_f(F.text == ui.BTN_SUMMARY, Command("done")))
async def menu_summary(m: Message, state: FSMContext, user: dict):
    await state.clear()
    text, kb = await summary_screen(user, ui.today(user))
    await m.answer(text, reply_markup=kb)


@router.message(StateFilter("*"), or_f(F.text == ui.BTN_STATS, Command("stats")))
async def menu_stats(m: Message, state: FSMContext, user: dict):
    await state.clear()
    s = await db.stats(user["id"], ui.today(user))
    await m.answer(ui.stats_view(s))


@router.message(StateFilter("*"), or_f(F.text == ui.BTN_SETTINGS, Command("settings")))
async def menu_settings(m: Message, state: FSMContext, user: dict):
    await state.clear()
    text, kb = ui.settings_view(user)
    await m.answer(text, reply_markup=kb)


@router.message(StateFilter("*"), Command("n", "note"))
async def cmd_note(m: Message, command: CommandObject, state: FSMContext, user: dict):
    day = ui.today(user)
    if not command.args:
        await state.set_state(S.note)
        await state.set_data({"day": day.isoformat()})
        await prompt(m, "📝 <b>Пиши нотатку</b>")
        return
    await state.clear()
    await db.add_note(user["id"], day, command.args.strip())
    await m.answer("📝 Нотатку збережено")


@router.message(StateFilter("*"), Command("find"))
async def cmd_find(m: Message, command: CommandObject, state: FSMContext, user: dict):
    await state.clear()
    q = (command.args or "").strip()
    if len(q) < 2:
        await m.answer("🔎 Напиши, що шукати: <code>/find звіт</code>")
        return
    tasks, notes = await db.search(user["id"], q)
    t = ui.today(user)
    if not tasks and not notes:
        await m.answer(f"🔎 За запитом «{escape(q)}» нічого не знайшла")
        return
    lines = [f"🔎 <b>Пошук:</b> {escape(q)}", ""]
    if tasks:
        lines.append(f"<b>Задачі · {len(tasks)}</b>")
        lines += [ui.task_line(x, user, with_date=True, tday=t) for x in tasks]
        lines.append("")
    if notes:
        lines.append(f"<b>Нотатки · {len(notes)}</b>")
        for n in notes:
            lines.append(f"• <i>{ui.d_short(iso(n['day']), t)}</i> — {escape(ui.short(n['body'].replace(chr(10), ' '), 90))}")
    rows = [[ui.B(text=f"{'✅' if x['done'] else '⬜'} {ui.short(x['title'], 34)}", callback_data=f"to:{x['id']}")]
            for x in tasks[:8]]
    await m.answer("\n".join(lines).rstrip(), reply_markup=ui.ikb(rows) if rows else None)


# ---------------------------------------------------------------- state inputs
@router.message(S.add, F.text)
async def st_add(m: Message, state: FSMContext, user: dict):
    data = await state.get_data()
    day = iso(data.get("day")) if data.get("day") else ui.today(user)
    header = await add_from_text(user, m.text, day)
    if not header:
        await m.answer("Не бачу тексту задачі 🙈 Спробуй ще раз", reply_markup=ui.CANCEL_KB)
        return
    await state.clear()
    items = parse_many(m.text, ui.today(user), day)
    target = items[0].due if items and all(p.due == items[0].due for p in items) else day
    text, kb = await day_screen(user, target, header=header)
    await m.answer(text, reply_markup=kb)


@router.message(S.note, F.text)
async def st_note(m: Message, state: FSMContext, user: dict):
    data = await state.get_data()
    day = iso(data.get("day")) if data.get("day") else ui.today(user)
    await state.clear()
    await db.add_note(user["id"], day, m.text.strip())
    notes = await db.day_notes(user["id"], day)
    text, kb = ui.notes_view(user, day, notes)
    await m.answer("📝 Збережено\n\n" + text, reply_markup=kb)


async def _task_from_state(state: FSMContext, user: dict) -> dict | None:
    data = await state.get_data()
    tid = data.get("tid")
    return await db.get_task(user["id"], int(tid)) if tid else None


@router.message(S.title, F.text)
async def st_title(m: Message, state: FSMContext, user: dict):
    t = await _task_from_state(state, user)
    await state.clear()
    if not t:
        return
    t = await db.update_task(user["id"], t["id"], title=m.text.strip()[:200])
    text, kb = ui.task_view(user, t)
    await m.answer(text, reply_markup=kb)


@router.message(S.date, F.text)
async def st_date(m: Message, state: FSMContext, user: dict):
    d = parse_date(m.text, ui.today(user))
    if not d:
        await m.answer("Не розібрала дату 🤔 Напиши, наприклад, <code>15.10</code> або <code>пт</code>",
                       reply_markup=ui.CANCEL_KB)
        return
    t = await _task_from_state(state, user)
    await state.clear()
    if not t:
        return
    t = await move_task(user, t, d)
    text, kb = ui.task_view(user, t)
    await m.answer(text, reply_markup=kb)


@router.message(S.remind, F.text)
async def st_remind(m: Message, state: FSMContext, user: dict):
    t = await _task_from_state(state, user)
    if not t:
        await state.clear()
        return
    res = parse_when(m.text, iso(t["due"]), ui.today(user))
    if not res:
        await m.answer("Напиши час у форматі <code>18:30</code> або <code>завтра 10:00</code>",
                       reply_markup=ui.CANCEL_KB)
        return
    d, tm = res
    when = datetime.combine(d, tm, tzinfo=ui.tzinfo(user))
    if when <= ui.now_local(user):
        await m.answer("Цей час уже минув ⌛ Обери пізніший", reply_markup=ui.CANCEL_KB)
        return
    await state.clear()
    t = await db.update_task(user["id"], t["id"], remind_at=when.isoformat(), reminded=False)
    text, kb = ui.task_view(user, t)
    await m.answer(f"⏰ Нагадаю {ui.d_short(d, ui.today(user)).lower()} о {tm:%H:%M}\n\n" + text, reply_markup=kb)


@router.message(S.tag, F.text)
async def st_tag(m: Message, state: FSMContext, user: dict):
    t = await _task_from_state(state, user)
    await state.clear()
    if not t:
        return
    tag = m.text.strip().lstrip("#").split()[0].lower()[:20] if m.text.strip().lstrip("#") else None
    t = await db.update_task(user["id"], t["id"], tag=tag)
    text, kb = ui.task_view(user, t)
    await m.answer(text, reply_markup=kb)


# ---------------------------------------------------------------- quick add (default)
@router.message(StateFilter(None), F.text & ~F.text.startswith("/"))
async def quick_add(m: Message, user: dict):
    header = await add_from_text(user, m.text, None)
    if not header:
        return
    items = parse_many(m.text, ui.today(user))
    target = items[0].due if all(p.due == items[0].due for p in items) else ui.today(user)
    text, kb = await day_screen(user, target, header=header)
    await m.answer(text, reply_markup=kb)


@router.message(StateFilter(None))
async def other(m: Message):
    await m.answer("Я розумію текст ✍️ Напиши задачу або натисни кнопку в меню. Підказки — /help")


# ---------------------------------------------------------------- callbacks: navigation
@router.callback_query(F.data == "cancel")
async def cb_cancel(c: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await c.message.edit_text("<i>Скасовано</i>")
    except TelegramBadRequest:
        pass
    await c.answer()


@router.callback_query(F.data.startswith("d:"))
async def cb_day(c: CallbackQuery, state: FSMContext, user: dict):
    await state.clear()
    text, kb = await day_screen(user, iso(c.data[2:]))
    await show(c, text, kb)
    await c.answer()


@router.callback_query(F.data.startswith("w:"))
async def cb_week(c: CallbackQuery, user: dict):
    start = iso(c.data[2:])
    tasks = await db.range_tasks(user["id"], start, start + timedelta(days=6))
    text, kb = ui.week_view(user, start, tasks)
    await show(c, text, kb)
    await c.answer()


@router.callback_query(F.data.startswith("add:"))
async def cb_add(c: CallbackQuery, state: FSMContext, user: dict):
    day = iso(c.data[4:])
    await state.set_state(S.add)
    await state.set_data({"day": day.isoformat()})
    await prompt(c, f"➕ <b>Що додати на {ui.d_short(day, ui.today(user)).lower()}?</b>\n\n"
                    "Кожна задача — з нового рядка.")


# ---------------------------------------------------------------- callbacks: tasks
def _tid(data: str) -> int:
    return int(data.split(":")[1])


async def set_done(user: dict, t: dict, done: bool) -> dict:
    return await db.update_task(user["id"], t["id"], done=done,
                                done_day=ui.today(user).isoformat() if done else None)


async def move_task(user: dict, t: dict, d: date) -> dict:
    values: dict = {"due": d.isoformat()}
    old = iso(t["due"])
    if d != old:
        values["moved"] = (t.get("moved") or 0) + 1
    r = ui.remind_local(t, user)
    if r:
        new_r = datetime.combine(d, r.timetz())
        if new_r > ui.now_local(user):
            values["remind_at"] = new_r.isoformat()
            values["reminded"] = False
        else:
            values["remind_at"] = None
    return await db.update_task(user["id"], t["id"], **values)


@router.callback_query(F.data.startswith("tg:"))
async def cb_toggle_list(c: CallbackQuery, user: dict):
    t = await db.get_task(user["id"], _tid(c.data))
    if not t:
        await c.answer("Задачу не знайдено")
        return
    t = await set_done(user, t, not t["done"])
    day = iso(t["due"])
    text, kb = await day_screen(user, day)
    await show(c, text, kb)
    if t["done"]:
        tasks = await db.day_tasks(user["id"], day)
        if tasks and all(x["done"] for x in tasks):
            await c.answer("🎉 Усі задачі на день виконано!", show_alert=True)
            return
        await c.answer("✅ Готово!")
    else:
        await c.answer("↩️ Повернула в роботу")


@router.callback_query(F.data.startswith("to:"))
async def cb_open(c: CallbackQuery, state: FSMContext, user: dict):
    await state.clear()
    t = await db.get_task(user["id"], _tid(c.data))
    if not t:
        await c.answer("Задачу не знайдено (можливо, видалена)")
        return
    text, kb = ui.task_view(user, t)
    await show(c, text, kb)
    await c.answer()


@router.callback_query(F.data.startswith("tt:"))
async def cb_toggle_card(c: CallbackQuery, user: dict):
    t = await db.get_task(user["id"], _tid(c.data))
    if not t:
        await c.answer()
        return
    t = await set_done(user, t, not t["done"])
    text, kb = ui.task_view(user, t)
    await show(c, text, kb)
    await c.answer("✅ Виконано!" if t["done"] else "↩️ У роботі")


async def _card_with(c: CallbackQuery, user: dict, question: str, kb_fn):
    t = await db.get_task(user["id"], _tid(c.data))
    if not t:
        await c.answer()
        return
    text, _ = ui.task_view(user, t)
    await show(c, f"{text}\n\n<b>{question}</b>", kb_fn(t))
    await c.answer()


@router.callback_query(F.data.startswith("rm:"))
async def cb_remind_menu(c: CallbackQuery, user: dict):
    await _card_with(c, user, "⏰ Коли нагадати?", lambda t: ui.remind_picker(user, t))


@router.callback_query(F.data.startswith("sr:"))
async def cb_remind_set(c: CallbackQuery, user: dict):
    _, tid, code = c.data.split(":")
    t = await db.get_task(user["id"], int(tid))
    if not t:
        await c.answer()
        return
    now = ui.now_local(user)
    due = iso(t["due"])
    if code == "x":
        t = await db.update_task(user["id"], t["id"], remind_at=None, reminded=False)
        toast = "🔕 Нагадування прибрано"
    else:
        if code.endswith("m") or code.endswith("h"):
            mins = int(code[:-1]) * (60 if code.endswith("h") else 1)
            when = now + timedelta(minutes=mins)
        else:
            when = datetime.combine(due, datetime.min.time(), tzinfo=ui.tzinfo(user)).replace(hour=int(code))
        t = await db.update_task(user["id"], t["id"], remind_at=when.isoformat(), reminded=False)
        toast = f"⏰ Нагадаю о {when:%H:%M}"
    text, kb = ui.task_view(user, t)
    await show(c, text, kb)
    await c.answer(toast)


@router.callback_query(F.data.startswith("src:"))
async def cb_remind_custom(c: CallbackQuery, state: FSMContext):
    await state.set_state(S.remind)
    await state.set_data({"tid": _tid(c.data)})
    await prompt(c, "⏰ Напиши час: <code>18:30</code>, <code>завтра 10:00</code> або <code>15.10 9:00</code>")


@router.callback_query(F.data.startswith("pr:"))
async def cb_prio_menu(c: CallbackQuery, user: dict):
    await _card_with(c, user, "🔥 Пріоритет:", lambda t: ui.prio_picker(t["id"]))


@router.callback_query(F.data.startswith("sp:"))
async def cb_prio_set(c: CallbackQuery, user: dict):
    _, tid, p = c.data.split(":")
    t = await db.update_task(user["id"], int(tid), priority=int(p))
    if t:
        text, kb = ui.task_view(user, t)
        await show(c, text, kb)
    await c.answer()


@router.callback_query(F.data.startswith("tm:"))
async def cb_tomorrow(c: CallbackQuery, user: dict):
    t = await db.get_task(user["id"], _tid(c.data))
    if not t:
        await c.answer()
        return
    t = await move_task(user, t, ui.today(user) + timedelta(days=1))
    text, kb = ui.task_view(user, t)
    await show(c, text, kb)
    await c.answer("➡️ Перенесено на завтра")


@router.callback_query(F.data.startswith("dt:"))
async def cb_date_menu(c: CallbackQuery, user: dict):
    await _card_with(c, user, "📅 На який день?", lambda t: ui.date_picker(user, t["id"]))


@router.callback_query(F.data.startswith("sd:"))
async def cb_date_set(c: CallbackQuery, user: dict):
    _, tid, d = c.data.split(":")
    t = await db.get_task(user["id"], int(tid))
    if not t:
        await c.answer()
        return
    t = await move_task(user, t, iso(d))
    text, kb = ui.task_view(user, t)
    await show(c, text, kb)
    await c.answer("📅 Дату змінено")


@router.callback_query(F.data.startswith("sdc:"))
async def cb_date_custom(c: CallbackQuery, state: FSMContext):
    await state.set_state(S.date)
    await state.set_data({"tid": _tid(c.data)})
    await prompt(c, "📅 Напиши дату: <code>15.10</code>, <code>пт</code>, <code>в понеділок</code>…")


@router.callback_query(F.data.startswith("tag:"))
async def cb_tag_menu(c: CallbackQuery, user: dict):
    tags = await db.recent_tags(user["id"])
    await _card_with(c, user, "🏷 Обери тег:", lambda t: ui.tag_picker(t["id"], tags))


@router.callback_query(F.data.startswith("st:"))
async def cb_tag_set(c: CallbackQuery, user: dict):
    _, tid, tag = c.data.split(":", 2)
    t = await db.update_task(user["id"], int(tid), tag=tag or None)
    if t:
        text, kb = ui.task_view(user, t)
        await show(c, text, kb)
    await c.answer()


@router.callback_query(F.data.startswith("stc:"))
async def cb_tag_custom(c: CallbackQuery, state: FSMContext):
    await state.set_state(S.tag)
    await state.set_data({"tid": _tid(c.data)})
    await prompt(c, "🏷 Напиши новий тег одним словом, напр. <code>навчання</code>")


@router.callback_query(F.data.startswith("ed:"))
async def cb_edit(c: CallbackQuery, state: FSMContext, user: dict):
    t = await db.get_task(user["id"], _tid(c.data))
    if not t:
        await c.answer()
        return
    await state.set_state(S.title)
    await state.set_data({"tid": t["id"]})
    await prompt(c, f"✏️ Напиши нову назву\n\nЗараз: <code>{escape(t['title'])}</code>")


@router.callback_query(F.data.startswith("del:"))
async def cb_del(c: CallbackQuery, user: dict):
    await _card_with(c, user, "Точно видалити задачу?", lambda t: ui.confirm_delete(t["id"]))


@router.callback_query(F.data.startswith("dely:"))
async def cb_del_yes(c: CallbackQuery, user: dict):
    t = await db.get_task(user["id"], _tid(c.data))
    if t:
        await db.delete_task(user["id"], t["id"])
        text, kb = await day_screen(user, iso(t["due"]))
        await show(c, text, kb)
    await c.answer("🗑 Видалено")


@router.callback_query(F.data.startswith("pp:"))
async def cb_postpone(c: CallbackQuery, user: dict):
    day = iso(c.data[3:])
    tmr = ui.today(user) + timedelta(days=1)
    if day >= tmr:
        await c.answer()
        return
    n = await db.postpone_undone(user["id"], day, tmr)
    header = f"➡️ Перенесено на завтра: {n}" if n else ""
    text, kb = await day_screen(user, day, header=header)
    await show(c, text, kb)
    await c.answer(f"➡️ {n} → завтра")


@router.callback_query(F.data == "ovd")
async def cb_overdue(c: CallbackQuery, user: dict):
    t = ui.today(user)
    n = await db.move_overdue(user["id"], t)
    text, kb = await day_screen(user, t)
    await show(c, text, kb)
    await c.answer(f"↪️ Забрала {n}")


# ---------------------------------------------------------------- callbacks: reminders
@router.callback_query(F.data.startswith("rd:"))
async def cb_rem_done(c: CallbackQuery, user: dict):
    t = await db.get_task(user["id"], _tid(c.data))
    if t:
        t = await set_done(user, t, True)
        await show(c, f"✅ <s>{escape(t['title'])}</s>\n<i>Виконано — так тримати!</i>")
    await c.answer("✅")


@router.callback_query(F.data.startswith("sz:"))
async def cb_snooze(c: CallbackQuery, user: dict):
    _, tid, mins = c.data.split(":")
    when = ui.now_local(user) + timedelta(minutes=int(mins))
    t = await db.update_task(user["id"], int(tid), remind_at=when.isoformat(), reminded=False)
    if t:
        await show(c, f"💤 <b>{escape(t['title'])}</b>\n<i>Нагадаю ще раз о {when:%H:%M}</i>",
                   ui.ikb([[ui.B(text="📋 Відкрити задачу", callback_data=f"to:{t['id']}")]]))
    await c.answer("💤 Відкладено")


# ---------------------------------------------------------------- callbacks: notes
@router.callback_query(F.data.startswith("n:"))
async def cb_notes(c: CallbackQuery, state: FSMContext, user: dict):
    await state.clear()
    day = iso(c.data[2:])
    notes = await db.day_notes(user["id"], day)
    text, kb = ui.notes_view(user, day, notes)
    await show(c, text, kb)
    await c.answer()


@router.callback_query(F.data.startswith("na:"))
async def cb_note_add(c: CallbackQuery, state: FSMContext, user: dict):
    day = iso(c.data[3:])
    await state.set_state(S.note)
    await state.set_data({"day": day.isoformat()})
    await prompt(c, f"📝 <b>Нотатка на {ui.d_short(day, ui.today(user)).lower()}</b> — пиши")


@router.callback_query(F.data.startswith("ndm:"))
async def cb_note_del_mode(c: CallbackQuery, user: dict):
    day = iso(c.data[4:])
    notes = await db.day_notes(user["id"], day)
    text, kb = ui.notes_view(user, day, notes, deleting=True)
    await show(c, text + "\n\n<b>Яку видалити?</b>", kb)
    await c.answer()


@router.callback_query(F.data.startswith("nd:"))
async def cb_note_del(c: CallbackQuery, user: dict):
    _, nid, d = c.data.split(":")
    await db.delete_note(user["id"], int(nid))
    day = iso(d)
    notes = await db.day_notes(user["id"], day)
    text, kb = ui.notes_view(user, day, notes, deleting=bool(notes))
    await show(c, text, kb)
    await c.answer("🗑 Видалено")


# ---------------------------------------------------------------- callbacks: settings
@router.callback_query(F.data.startswith("s:"))
async def cb_settings(c: CallbackQuery, user: dict):
    key = c.data[2:]
    if key in ("mo", "eo", "ar"):
        col = {"mo": "morning_on", "eo": "evening_on", "ar": "auto_rollover"}[key]
        user = await db.update_user(user["id"], **{col: not user[col]})
    elif key in ("mt", "et"):
        kind = key[0]
        text, _ = ui.settings_view(user)
        q = "☀️ О котрій надсилати план на день?" if kind == "m" else "🌙 О котрій надсилати підсумок?"
        await show(c, f"{text}\n\n<b>{q}</b>", ui.time_picker(kind))
        await c.answer()
        return
    text, kb = ui.settings_view(user)
    await show(c, text, kb)
    await c.answer()


@router.callback_query(F.data.startswith("sst:"))
async def cb_settings_time(c: CallbackQuery, user: dict):
    _, kind, hm = c.data.split(":", 2)
    col = "morning_time" if kind == "m" else "evening_time"
    user = await db.update_user(user["id"], **{col: hm})
    text, kb = ui.settings_view(user)
    await show(c, text, kb)
    await c.answer(f"🕘 {hm}")


@router.callback_query()
async def cb_fallback(c: CallbackQuery):
    await c.answer()
