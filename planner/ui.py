"""All texts and keyboards. Visual language lives here."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

from aiogram.types import (InlineKeyboardButton as B, InlineKeyboardMarkup, KeyboardButton,
                           ReplyKeyboardMarkup)

WD = ["понеділок", "вівторок", "середа", "четвер", "пʼятниця", "субота", "неділя"]
WD_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]
MONTHS = ["січня", "лютого", "березня", "квітня", "травня", "червня", "липня", "серпня",
          "вересня", "жовтня", "листопада", "грудня"]
PRIO = {3: "🔴", 2: "🟡", 1: "🟢", 0: "▫️"}
PRIO_NAME = {3: "Високий", 2: "Середній", 1: "Низький", 0: "Без пріоритету"}

# ---------- main reply keyboard ----------
BTN_TODAY = "📅 Сьогодні"
BTN_TOMORROW = "🌅 Завтра"
BTN_ADD = "➕ Задача"
BTN_NOTE = "📝 Нотатка"
BTN_WEEK = "🗓 Тиждень"
BTN_SUMMARY = "🌙 Підсумок дня"
BTN_STATS = "📊 Статистика"
BTN_SETTINGS = "⚙️ Налаштування"
MENU_BUTTONS = {BTN_TODAY, BTN_TOMORROW, BTN_ADD, BTN_NOTE, BTN_WEEK, BTN_SUMMARY, BTN_STATS, BTN_SETTINGS}


def main_kb() -> ReplyKeyboardMarkup:
    rows = [[BTN_TODAY, BTN_TOMORROW], [BTN_ADD, BTN_NOTE], [BTN_WEEK, BTN_SUMMARY], [BTN_STATS, BTN_SETTINGS]]
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=t) for t in r] for r in rows],
                               resize_keyboard=True, is_persistent=True,
                               input_field_placeholder="Напиши задачу… напр. «Звіт завтра 14:00 #робота !!»")


def ikb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[r for r in rows if r])


CANCEL_KB = ikb([[B(text="✖️ Скасувати", callback_data="cancel")]])


# ---------- formatting helpers ----------
def tzinfo(user: dict) -> ZoneInfo:
    try:
        return ZoneInfo(user.get("tz") or "Europe/Kyiv")
    except Exception:
        return ZoneInfo("Europe/Kyiv")


def now_local(user: dict) -> datetime:
    return datetime.now(tzinfo(user))


def today(user: dict) -> date:
    return now_local(user).date()


def d_long(d: date) -> str:
    return f"{WD[d.weekday()]}, {d.day} {MONTHS[d.month - 1]}"


def d_title(d: date, t: date) -> str:
    rel = {0: "Сьогодні", 1: "Завтра", -1: "Вчора", 2: "Післязавтра"}.get((d - t).days)
    return f"{rel} · {d_long(d)}" if rel else d_long(d).capitalize()


def d_short(d: date, t: date) -> str:
    rel = {0: "Сьогодні", 1: "Завтра", -1: "Вчора"}.get((d - t).days)
    return rel or f"{WD_SHORT[d.weekday()]}, {d.day:02d}.{d.month:02d}"


def bar(done: int, total: int, width: int = 10) -> str:
    if total == 0:
        return "▱" * width
    full = round(width * done / total)
    return "▰" * full + "▱" * (width - full)


def plural(n: int, one: str, few: str, many: str) -> str:
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return one
    if 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        return few
    return many


def remind_local(task: dict, user: dict) -> datetime | None:
    if not task.get("remind_at"):
        return None
    return datetime.fromisoformat(task["remind_at"].replace("Z", "+00:00")).astimezone(tzinfo(user))


def task_line(t: dict, user: dict, with_date: bool = False, tday: date | None = None) -> str:
    title = escape(t["title"])
    if t["done"]:
        s = f"✅ <s>{title}</s>"
    else:
        s = f"{PRIO[t['priority']]} {title}"
    extra = []
    r = remind_local(t, user)
    if r and not t["done"]:
        extra.append(f"⏰ {r:%H:%M}")
    if t.get("tag"):
        extra.append(f"#{escape(t['tag'])}")
    if t.get("moved") and not t["done"]:
        extra.append(f"↪️{t['moved']}")
    if with_date and tday:
        extra.append(d_short(date.fromisoformat(t["due"]), tday).lower())
    if extra:
        s += "  <i>" + " · ".join(extra) + "</i>"
    return s


def short(s: str, n: int = 28) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


# ---------- day view ----------
def day_view(user: dict, day: date, tasks: list[dict], notes_n: int, overdue: int = 0,
             header: str = "") -> tuple[str, InlineKeyboardMarkup]:
    t = today(user)
    done = sum(1 for x in tasks if x["done"])
    total = len(tasks)
    lines = []
    if header:
        lines += [header, ""]
    lines.append(f"📅 <b>{d_title(day, t)}</b>")
    if total:
        pct = round(100 * done / total)
        lines.append(f"<code>{bar(done, total)}</code>  {done}/{total} · {pct}%")
        lines.append("")
        undone = [x for x in tasks if not x["done"]]
        finished = [x for x in tasks if x["done"]]
        for x in undone:
            lines.append(task_line(x, user))
        if undone and finished:
            lines.append("")
        for x in finished:
            lines.append(task_line(x, user))
        if done == total:
            lines += ["", "🎉 <b>Усе виконано!</b> Ти неймовірна."]
    else:
        lines += ["", "<i>Тут поки порожньо.</i>",
                  "Просто напиши мені задачу — я додам її на цей день ✨"]
    if notes_n:
        lines += ["", f"📝 {notes_n} {plural(notes_n, 'нотатка', 'нотатки', 'нотаток')}"]
    if overdue and day == t:
        lines += ["", f"⚠️ Є прострочені задачі: {overdue}"]

    rows = []
    iso = day.isoformat()
    for x in tasks:
        mark = "✅" if x["done"] else "⬜"
        rows.append([B(text=f"{mark} {short(x['title'])}", callback_data=f"tg:{x['id']}"),
                     B(text="⋯", callback_data=f"to:{x['id']}")])
    prev_d, next_d = (day - timedelta(days=1)).isoformat(), (day + timedelta(days=1)).isoformat()
    nav_mid = B(text="• Сьогодні •" if day == t else "↩︎ Сьогодні", callback_data=f"d:{t.isoformat()}")
    rows.append([B(text="◀️", callback_data=f"d:{prev_d}"), nav_mid, B(text="▶️", callback_data=f"d:{next_d}")])
    rows.append([B(text="➕ Задача", callback_data=f"add:{iso}"),
                 B(text=f"📝 Нотатки{f' ({notes_n})' if notes_n else ''}", callback_data=f"n:{iso}")])
    undone_n = total - done
    if undone_n and day <= t:
        rows.append([B(text=f"➡️ Невиконане ({undone_n}) → на завтра", callback_data=f"pp:{iso}")])
    if overdue and day == t:
        rows.append([B(text=f"↪️ Забрати прострочені ({overdue}) на сьогодні", callback_data="ovd")])
    return "\n".join(lines), ikb(rows)


# ---------- task card ----------
def task_view(user: dict, t: dict) -> tuple[str, InlineKeyboardMarkup]:
    td = today(user)
    due = date.fromisoformat(t["due"])
    head = "✅" if t["done"] else PRIO[t["priority"]]
    title = f"<s>{escape(t['title'])}</s>" if t["done"] else escape(t["title"])
    lines = [f"{head} <b>{title}</b>", ""]
    lines.append(f"📅  {d_title(due, td)}")
    r = remind_local(t, user)
    if r:
        state = " <i>(вже було)</i>" if t.get("reminded") else ""
        when = f"{r:%H:%M}" if r.date() == due else f"{d_short(r.date(), td).lower()}, {r:%H:%M}"
        lines.append(f"⏰  Нагадування: {when}{state}")
    lines.append(f"🔥  {PRIO_NAME[t['priority']]}")
    if t.get("tag"):
        lines.append(f"🏷  #{escape(t['tag'])}")
    if t.get("moved"):
        n = t["moved"]
        lines.append(f"↪️  Переносилась {n} {plural(n, 'раз', 'рази', 'разів')}")
    lines.append("")
    lines.append("Статус: <b>виконано</b> 🎉" if t["done"] else "Статус: <b>в процесі</b>")

    i = t["id"]
    rows = [
        [B(text="↩️ Повернути в роботу" if t["done"] else "✅ Виконано", callback_data=f"tt:{i}")],
        [B(text="⏰ Нагадати", callback_data=f"rm:{i}"), B(text="🔥 Пріоритет", callback_data=f"pr:{i}")],
        [B(text="➡️ На завтра", callback_data=f"tm:{i}"), B(text="📅 Інша дата", callback_data=f"dt:{i}")],
        [B(text="🏷 Тег", callback_data=f"tag:{i}"), B(text="✏️ Назва", callback_data=f"ed:{i}")],
        [B(text="🗑 Видалити", callback_data=f"del:{i}"), B(text="« До дня", callback_data=f"d:{t['due']}")],
    ]
    if t["done"]:
        rows = [rows[0], rows[4]]
    return "\n".join(lines), ikb(rows)


def date_picker(user: dict, tid: int) -> InlineKeyboardMarkup:
    t = today(user)
    days = [t + timedelta(days=k) for k in range(0, 10)]
    btns = [B(text=d_short(d, t), callback_data=f"sd:{tid}:{d.isoformat()}") for d in days]
    rows = [btns[k:k + 2] for k in range(0, len(btns), 2)]
    rows.append([B(text="✍️ Ввести дату", callback_data=f"sdc:{tid}"), B(text="« Назад", callback_data=f"to:{tid}")])
    return ikb(rows)


def remind_picker(user: dict, task: dict) -> InlineKeyboardMarkup:
    i = task["id"]
    now = now_local(user)
    due = date.fromisoformat(task["due"])
    rows = []
    if due <= now.date():
        rows.append([B(text="через 30 хв", callback_data=f"sr:{i}:30m"),
                     B(text="через 1 год", callback_data=f"sr:{i}:1h"),
                     B(text="через 3 год", callback_data=f"sr:{i}:3h")])
    presets = []
    for hh in (9, 12, 15, 18, 20):
        if due > now.date() or hh > now.hour:
            presets.append(B(text=f"{hh:02d}:00", callback_data=f"sr:{i}:{hh}"))
    if presets:
        rows.append(presets)
    rows.append([B(text="✍️ Свій час", callback_data=f"src:{i}")])
    if task.get("remind_at"):
        rows.append([B(text="🔕 Прибрати нагадування", callback_data=f"sr:{i}:x")])
    rows.append([B(text="« Назад", callback_data=f"to:{i}")])
    return ikb(rows)


def prio_picker(tid: int) -> InlineKeyboardMarkup:
    return ikb([
        [B(text="🔴 Високий", callback_data=f"sp:{tid}:3"), B(text="🟡 Середній", callback_data=f"sp:{tid}:2")],
        [B(text="🟢 Низький", callback_data=f"sp:{tid}:1"), B(text="▫️ Без", callback_data=f"sp:{tid}:0")],
        [B(text="« Назад", callback_data=f"to:{tid}")],
    ])


def tag_picker(tid: int, tags: list[str]) -> InlineKeyboardMarkup:
    btns = [B(text=f"#{t}", callback_data=f"st:{tid}:{t}") for t in tags]
    rows = [btns[k:k + 3] for k in range(0, len(btns), 3)]
    rows.append([B(text="✍️ Новий тег", callback_data=f"stc:{tid}"), B(text="🚫 Без тегу", callback_data=f"st:{tid}:")])
    rows.append([B(text="« Назад", callback_data=f"to:{tid}")])
    return ikb(rows)


def confirm_delete(tid: int) -> InlineKeyboardMarkup:
    return ikb([[B(text="🗑 Так, видалити", callback_data=f"dely:{tid}"),
                 B(text="Ні", callback_data=f"to:{tid}")]])


# ---------- notes ----------
def notes_view(user: dict, day: date, notes: list[dict], deleting: bool = False) -> tuple[str, InlineKeyboardMarkup]:
    t = today(user)
    lines = [f"📝 <b>Нотатки</b> · {d_title(day, t).lower() if (day - t).days in (-1, 0, 1, 2) else d_long(day)}", ""]
    if not notes:
        lines.append("<i>Нотаток на цей день ще немає.</i>")
    for k, n in enumerate(notes, 1):
        ts = datetime.fromisoformat(n["created_at"].replace("Z", "+00:00")).astimezone(tzinfo(user))
        lines.append(f"<b>{k}.</b> <i>{ts:%H:%M}</i>\n{escape(n['body'])}\n")
    iso = day.isoformat()
    rows = []
    if deleting:
        btns = [B(text=f"🗑 {k}", callback_data=f"nd:{n['id']}:{iso}") for k, n in enumerate(notes, 1)]
        rows += [btns[k:k + 5] for k in range(0, len(btns), 5)]
        rows.append([B(text="Готово", callback_data=f"n:{iso}")])
    else:
        rows.append([B(text="➕ Нотатка", callback_data=f"na:{iso}")]
                    + ([B(text="🗑 Видалити", callback_data=f"ndm:{iso}")] if notes else []))
        rows.append([B(text="« До дня", callback_data=f"d:{iso}")])
    return "\n".join(lines).rstrip(), ikb(rows)


# ---------- summary ----------
def summary_view(user: dict, day: date, done: list[dict], left: list[dict], notes: list[dict],
                 tomorrow: list[dict]) -> tuple[str, InlineKeyboardMarkup]:
    t = today(user)
    lines = [f"🌙 <b>Підсумок дня</b> · {d_long(day)}", ""]
    total = len(done) + len(left)
    if total:
        lines.append(f"<code>{bar(len(done), total)}</code>  {len(done)}/{total}")
        lines.append("")
    if done:
        lines.append(f"✅ <b>Зроблено · {len(done)}</b>")
        lines += [f"  • {escape(x['title'])}" for x in done]
        lines.append("")
    if left:
        lines.append(f"⏳ <b>Залишилось · {len(left)}</b>")
        lines += [f"  • {PRIO[x['priority']]} {escape(x['title'])}" for x in left]
        lines.append("")
    if not done and not left:
        lines += ["<i>Сьогодні задач не було.</i>", ""]
    if notes:
        lines.append(f"📝 <b>Нотатки · {len(notes)}</b>")
        lines += [f"  • {escape(short(n['body'].replace(chr(10), ' '), 80))}" for n in notes]
        lines.append("")
    lines.append(f"🌅 <b>Завтра · {len(tomorrow)}</b>")
    if tomorrow:
        lines += [f"  • {PRIO[x['priority']]} {escape(x['title'])}" for x in tomorrow]
    else:
        lines.append("  <i>ще нічого не заплановано</i>")
    if total and not left:
        lines += ["", "Ідеальний день — усе закрито 💫"]
    elif done:
        lines += ["", "Гарна робота. Відпочивай 🤍"]

    iso = day.isoformat()
    tmr = (day + timedelta(days=1)).isoformat()
    rows = []
    if left:
        rows.append([B(text=f"➡️ Перенести {len(left)} на завтра", callback_data=f"pp:{iso}")])
    rows.append([B(text="🌅 Спланувати завтра", callback_data=f"d:{tmr}"),
                 B(text="📝 Нотатка дня", callback_data=f"na:{iso}")])
    return "\n".join(lines).rstrip(), ikb(rows)


# ---------- week ----------
def week_view(user: dict, start: date, tasks: list[dict]) -> tuple[str, InlineKeyboardMarkup]:
    t = today(user)
    end = start + timedelta(days=6)
    lines = [f"🗓 <b>Тиждень</b> · {start.day} {MONTHS[start.month - 1]} — {end.day} {MONTHS[end.month - 1]}", ""]
    rows = []
    tot_all = done_all = 0
    for k in range(7):
        d = start + timedelta(days=k)
        ds = [x for x in tasks if x["due"] == d.isoformat()]
        dn = sum(1 for x in ds if x["done"])
        tot_all += len(ds)
        done_all += dn
        label = f"{WD_SHORT[d.weekday()]} {d.day:02d}.{d.month:02d}"
        mark = " ←" if d == t else ""
        if ds:
            lines.append(f"<code>{label}  {bar(dn, len(ds), 6)} {dn}/{len(ds)}</code>{mark}")
        else:
            lines.append(f"<code>{label}  {'·' * 6} —</code>{mark}")
        btn = f"{'• ' if d == t else ''}{WD_SHORT[d.weekday()]} {d.day}" + (f" · {len(ds) - dn}" if len(ds) - dn else "")
        rows.append(B(text=btn, callback_data=f"d:{d.isoformat()}"))
    if tot_all:
        lines += ["", f"Разом: {done_all}/{tot_all} · {round(100 * done_all / tot_all)}%"]
    kb = [rows[0:4], rows[4:7],
          [B(text="◀️ Попередній", callback_data=f"w:{(start - timedelta(days=7)).isoformat()}"),
           B(text="Наступний ▶️", callback_data=f"w:{(start + timedelta(days=7)).isoformat()}")]]
    return "\n".join(lines), ikb(kb)


# ---------- stats ----------
def stats_view(s: dict) -> str:
    lines = ["📊 <b>Статистика</b>", ""]
    td, tt = s["today_done"], s["today_total"]
    wd, wt = s["week_done"], s["week_total"]
    lines.append(f"Сьогодні: <code>{bar(td, tt, 8)}</code> {td}/{tt}")
    lines.append(f"Тиждень:  <code>{bar(wd, wt, 8)}</code> {wd}/{wt}" + (f" · {round(100 * wd / wt)}%" if wt else ""))
    lines.append("")
    st = s["streak"]
    lines.append(f"🔥 Серія: <b>{st} {plural(st, 'день', 'дні', 'днів')}</b> поспіль з виконаними задачами")
    lines.append(f"🏆 Рекорд: <b>{s['best']}</b> {plural(s['best'], 'задача', 'задачі', 'задач')} за день")
    lines.append(f"✅ Всього виконано: <b>{s['all_done']}</b>  ·  📝 нотаток: <b>{s['notes']}</b>")
    lines += ["", "<b>Останні 7 днів</b>"]
    days = s.get("days") or []
    mx = max([x["n"] for x in days] + [1])
    chart = []
    for x in days:
        d = date.fromisoformat(x["d"])
        n = x["n"]
        blocks = "█" * round(10 * n / mx) if n else ""
        chart.append(f"{WD_SHORT[d.weekday()]} {blocks:<10} {n}")
    lines.append("<code>" + "\n".join(chart) + "</code>")
    if s.get("tags"):
        lines += ["", "<b>Теги тижня</b>"]
        lines.append("  ".join(f"#{escape(x['tag'])} · {x['n']}" for x in s["tags"]))
    return "\n".join(lines)


# ---------- settings ----------
def settings_view(u: dict) -> tuple[str, InlineKeyboardMarkup]:
    on = lambda v: "увімкнено ✅" if v else "вимкнено"
    lines = [
        "⚙️ <b>Налаштування</b>", "",
        f"☀️ Ранковий план о <b>{u['morning_time']}</b> — {on(u['morning_on'])}",
        f"🌙 Вечірній підсумок о <b>{u['evening_time']}</b> — {on(u['evening_on'])}",
        f"↪️ Автоперенос невиконаного на наступний день — {on(u['auto_rollover'])}",
        f"🌍 Часовий пояс: {u['tz']}",
    ]
    kb = ikb([
        [B(text=("☀️ Вимкнути ранок" if u["morning_on"] else "☀️ Увімкнути ранок"), callback_data="s:mo"),
         B(text="🕘 Час ранку", callback_data="s:mt")],
        [B(text=("🌙 Вимкнути вечір" if u["evening_on"] else "🌙 Увімкнути вечір"), callback_data="s:eo"),
         B(text="🕘 Час вечора", callback_data="s:et")],
        [B(text=("↪️ Вимкнути автоперенос" if u["auto_rollover"] else "↪️ Увімкнути автоперенос"), callback_data="s:ar")],
    ])
    return "\n".join(lines), kb


def time_picker(kind: str) -> InlineKeyboardMarkup:
    hours = ["06:30", "07:00", "07:30", "08:00", "08:30", "09:00", "09:30", "10:00", "11:00"] if kind == "m" else \
        ["18:00", "19:00", "20:00", "20:30", "21:00", "21:30", "22:00", "22:30", "23:00"]
    btns = [B(text=h, callback_data=f"sst:{kind}:{h}") for h in hours]
    return ikb([btns[0:3], btns[3:6], btns[6:9], [B(text="« Назад", callback_data="s:back")]])


# ---------- reminder ----------
def reminder_msg(t: dict) -> tuple[str, InlineKeyboardMarkup]:
    txt = f"⏰ <b>Нагадування</b>\n\n{PRIO[t['priority']]} <b>{escape(t['title'])}</b>"
    if t.get("tag"):
        txt += f"\n<i>#{escape(t['tag'])}</i>"
    i = t["id"]
    kb = ikb([
        [B(text="✅ Зроблено", callback_data=f"rd:{i}")],
        [B(text="💤 15 хв", callback_data=f"sz:{i}:15"), B(text="💤 1 год", callback_data=f"sz:{i}:60"),
         B(text="➡️ Завтра", callback_data=f"tm:{i}")],
    ])
    return txt, kb


HELP = (
    "🪴 <b>Як користуватись планером</b>\n\n"
    "<b>Додати задачу</b> — просто напиши її текстом. Можна кілька — кожна з нового рядка.\n\n"
    "Розумний запис:\n"
    "• <code>завтра</code>, <code>післязавтра</code>, <code>пт</code>, <code>в понеділок</code>, <code>12.10</code> — дата\n"
    "• <code>14:00</code> або <code>о 14:00</code> — нагадування\n"
    "• <code>#робота</code> — тег\n"
    "• <code>!</code> <code>!!</code> <code>!!!</code> — пріоритет\n\n"
    "Приклад: <code>Зідзвон з командою завтра о 14:00 #робота !!</code>\n\n"
    "<b>Задачі</b> — тицяй на задачу у списку, щоб відмітити ✅, або на «⋯», щоб змінити дату, "
    "нагадування, тег чи пріоритет.\n\n"
    "<b>Команди</b>\n"
    "/today — сьогодні · /tomorrow — завтра · /week — тиждень\n"
    "/n <i>текст</i> — швидка нотатка\n"
    "/done — підсумок дня · /stats — статистика\n"
    "/find <i>слово</i> — пошук по задачах і нотатках\n"
    "/settings — нагадування й автоперенос\n\n"
    "Щоранку я надішлю план на день, а ввечері — підсумок. Невиконане саме переїде на наступний день."
)
