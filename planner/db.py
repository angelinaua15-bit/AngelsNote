"""Thin async wrapper over Supabase PostgREST."""
from __future__ import annotations

from datetime import date
from typing import Any

import httpx

from . import config


class DB:
    def __init__(self) -> None:
        self.c: httpx.AsyncClient | None = None

    async def open(self) -> None:
        self.c = httpx.AsyncClient(
            base_url=f"{config.SUPABASE_URL}/rest/v1",
            headers={
                "apikey": config.SUPABASE_KEY,
                "Authorization": f"Bearer {config.SUPABASE_KEY}",
                "x-bot-secret": config.BOT_SECRET,
                "Content-Type": "application/json",
            },
            timeout=15,
        )

    async def close(self) -> None:
        if self.c:
            await self.c.aclose()
            self.c = None

    @staticmethod
    def _ok(r: httpx.Response) -> Any:
        if r.status_code >= 400:
            raise RuntimeError(f"DB {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else None

    async def select(self, table: str, params: dict | None = None) -> list[dict]:
        return self._ok(await self.c.get(f"/{table}", params=params or {})) or []

    async def insert(self, table: str, row: dict | list, upsert_on: str | None = None) -> list[dict]:
        headers = {"Prefer": "return=representation"}
        params = {}
        if upsert_on:
            headers["Prefer"] += ",resolution=merge-duplicates"
            params["on_conflict"] = upsert_on
        return self._ok(await self.c.post(f"/{table}", json=row, params=params, headers=headers)) or []

    async def update(self, table: str, filters: dict, values: dict) -> list[dict]:
        r = await self.c.patch(f"/{table}", params=filters, json=values,
                               headers={"Prefer": "return=representation"})
        return self._ok(r) or []

    async def delete(self, table: str, filters: dict) -> None:
        self._ok(await self.c.delete(f"/{table}", params=filters))

    async def rpc(self, fn: str, args: dict | None = None) -> Any:
        return self._ok(await self.c.post(f"/rpc/{fn}", json=args or {}))


db = DB()


# ---------- users ----------
async def get_user(uid: int) -> dict | None:
    rows = await db.select("users", {"id": f"eq.{uid}"})
    return rows[0] if rows else None


async def any_user() -> bool:
    return bool(await db.select("users", {"select": "id", "limit": "1"}))


async def create_user(uid: int, first_name: str | None) -> dict:
    rows = await db.insert("users", {"id": uid, "first_name": first_name}, upsert_on="id")
    return rows[0]


async def update_user(uid: int, **values) -> dict:
    rows = await db.update("users", {"id": f"eq.{uid}"}, values)
    return rows[0] if rows else {}


async def all_users() -> list[dict]:
    return await db.select("users")


async def rollover(uid: int, today: date) -> int:
    return int(await db.rpc("rollover", {"p_uid": uid, "p_today": today.isoformat()}) or 0)


# ---------- tasks ----------
ORDER = "done.asc,priority.desc,remind_at.asc.nullslast,id.asc"


async def day_tasks(uid: int, day: date) -> list[dict]:
    return await db.select("tasks", {"user_id": f"eq.{uid}", "due": f"eq.{day.isoformat()}", "order": ORDER})


async def done_on(uid: int, day: date) -> list[dict]:
    return await db.select("tasks", {"user_id": f"eq.{uid}", "done": "is.true",
                                     "done_day": f"eq.{day.isoformat()}", "order": "priority.desc,id.asc"})


async def range_tasks(uid: int, start: date, end: date) -> list[dict]:
    return await db.select("tasks", {
        "select": "id,due,done",
        "user_id": f"eq.{uid}",
        "and": f"(due.gte.{start.isoformat()},due.lte.{end.isoformat()})",
    })


async def overdue_count(uid: int, today: date) -> int:
    rows = await db.select("tasks", {"select": "id", "user_id": f"eq.{uid}", "done": "is.false",
                                     "due": f"lt.{today.isoformat()}"})
    return len(rows)


async def move_overdue(uid: int, today: date) -> int:
    rows = await db.update("tasks", {"user_id": f"eq.{uid}", "done": "is.false", "due": f"lt.{today.isoformat()}"},
                           {"due": today.isoformat()})
    return len(rows)


async def get_task(uid: int, tid: int) -> dict | None:
    rows = await db.select("tasks", {"id": f"eq.{tid}", "user_id": f"eq.{uid}"})
    return rows[0] if rows else None


async def add_tasks(rows: list[dict]) -> list[dict]:
    return await db.insert("tasks", rows)


async def update_task(uid: int, tid: int, **values) -> dict | None:
    rows = await db.update("tasks", {"id": f"eq.{tid}", "user_id": f"eq.{uid}"}, values)
    return rows[0] if rows else None


async def delete_task(uid: int, tid: int) -> None:
    await db.delete("tasks", {"id": f"eq.{tid}", "user_id": f"eq.{uid}"})


async def postpone_undone(uid: int, src: date, dst: date) -> int:
    return int(await db.rpc("postpone_undone", {"p_uid": uid, "p_from": src.isoformat(),
                                                "p_to": dst.isoformat()}) or 0)


async def recent_tags(uid: int) -> list[str]:
    rows = await db.select("tasks", {"select": "tag", "user_id": f"eq.{uid}", "tag": "not.is.null",
                                     "order": "id.desc", "limit": "60"})
    seen: list[str] = []
    for r in rows:
        if r["tag"] not in seen:
            seen.append(r["tag"])
    return seen[:6]


async def claim_reminders() -> list[dict]:
    return await db.rpc("claim_reminders") or []


async def stats(uid: int, today: date) -> dict:
    return await db.rpc("user_stats", {"p_uid": uid, "p_today": today.isoformat()})


def _like(q: str) -> str:
    q = q.replace("*", "").replace(",", " ").replace("(", " ").replace(")", " ")
    return f"*{q}*"


async def search(uid: int, q: str) -> tuple[list[dict], list[dict]]:
    tasks = await db.select("tasks", {"user_id": f"eq.{uid}", "title": f"ilike.{_like(q)}",
                                      "order": "due.desc", "limit": "15"})
    notes = await db.select("notes", {"user_id": f"eq.{uid}", "body": f"ilike.{_like(q)}",
                                      "order": "day.desc", "limit": "10"})
    return tasks, notes


# ---------- notes ----------
async def day_notes(uid: int, day: date) -> list[dict]:
    return await db.select("notes", {"user_id": f"eq.{uid}", "day": f"eq.{day.isoformat()}", "order": "id.asc"})


async def add_note(uid: int, day: date, body: str) -> dict:
    return (await db.insert("notes", {"user_id": uid, "day": day.isoformat(), "body": body}))[0]


async def delete_note(uid: int, nid: int) -> None:
    await db.delete("notes", {"id": f"eq.{nid}", "user_id": f"eq.{uid}"})


async def notes_count(uid: int, day: date) -> int:
    rows = await db.select("notes", {"select": "id", "user_id": f"eq.{uid}", "day": f"eq.{day.isoformat()}"})
    return len(rows)
