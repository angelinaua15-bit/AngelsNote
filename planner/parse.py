"""Quick-add parser: "Зідзвон з командою завтра о 14:00 #робота !!" -> structured task."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional

WEEKDAYS = {
    "пн": 0, "понеділок": 0, "понеділка": 0,
    "вт": 1, "вівторок": 1, "вівторка": 1,
    "ср": 2, "середа": 2, "середу": 2,
    "чт": 3, "четвер": 3, "четверга": 3,
    "пт": 4, "пʼятниця": 4, "пʼятницю": 4, "п'ятниця": 4, "п'ятницю": 4, "пятниця": 4, "пятницю": 4,
    "сб": 5, "субота": 5, "суботу": 5,
    "нд": 6, "неділя": 6, "неділю": 6,
}
REL = {"сьогодні": 0, "завтра": 1, "післязавтра": 2}
PREP = {"в", "у", "о", "об", "на", "до"}

TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
DATE_RE = re.compile(r"^(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?$")
TAG_RE = re.compile(r"^#([\w\-]{1,20})", re.UNICODE)


@dataclass
class Parsed:
    title: str
    due: date
    priority: int = 0
    tag: Optional[str] = None
    at: Optional[time] = None
    date_given: bool = False


def parse_time(s: str) -> Optional[time]:
    m = TIME_RE.match(s.strip())
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return None
    return time(h, mi)


def parse_date(s: str, today: date) -> Optional[date]:
    s = s.strip().lower().rstrip(".,")
    if s in REL:
        return today + timedelta(days=REL[s])
    if s in WEEKDAYS:
        delta = (WEEKDAYS[s] - today.weekday()) % 7
        return today + timedelta(days=delta or 7)
    m = DATE_RE.match(s)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        y = m.group(3)
        year = (int(y) + 2000 if len(y) == 2 else int(y)) if y else today.year
        try:
            res = date(year, mo, d)
        except ValueError:
            return None
        if not y and res < today - timedelta(days=60):
            res = date(year + 1, mo, d)
        return res
    return None


def parse_line(line: str, today: date, default_day: Optional[date] = None) -> Optional[Parsed]:
    tokens = line.strip().split()
    if not tokens:
        return None
    keep: list[str] = []
    due: Optional[date] = None
    at: Optional[time] = None
    prio = 0
    tag = None
    for tok in tokens:
        low = tok.lower().rstrip(",.")
        if re.fullmatch(r"!{1,3}", tok):
            prio = max(prio, len(tok))
            continue
        m = TAG_RE.match(tok)
        if m and len(m.group(0)) == len(tok.rstrip(",.")):
            tag = tag or m.group(1).lower()
            continue
        t = parse_time(low)
        if t and at is None:
            at = t
            if keep and keep[-1].lower() in PREP:
                keep.pop()
            continue
        d = parse_date(low, today) if due is None else None
        if d:
            due = d
            if keep and keep[-1].lower() in PREP:
                keep.pop()
            continue
        keep.append(tok)
    title = " ".join(keep).strip(" ,.-—")
    if not title:
        return None
    title = title[0].upper() + title[1:]
    return Parsed(title=title[:200], due=due or default_day or today, priority=prio, tag=tag, at=at,
                  date_given=due is not None)


def parse_many(text: str, today: date, default_day: Optional[date] = None) -> list[Parsed]:
    out = []
    for line in text.splitlines():
        line = re.sub(r"^\s*(?:[-•*▪️]|\d+[.)])\s*", "", line)
        p = parse_line(line, today, default_day)
        if p:
            out.append(p)
    return out


def parse_when(text: str, base_day: date, today: date) -> Optional[tuple[date, time]]:
    """For custom reminder input: "18:30", "завтра 10:00", "12.10 9:15"."""
    d, t = base_day, None
    for tok in text.lower().split():
        if tok in PREP:
            continue
        tt = parse_time(tok)
        if tt:
            t = tt
            continue
        dd = parse_date(tok, today)
        if dd:
            d = dd
            continue
        return None
    return (d, t) if t else None


def combine(d: date, t: time, tz) -> datetime:
    return datetime.combine(d, t, tzinfo=tz)
