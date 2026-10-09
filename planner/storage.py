"""aiogram FSM storage kept in Supabase (serverless has no memory between requests)."""
from __future__ import annotations

from typing import Any, Dict, Optional

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StorageKey

from .db import db


class SupabaseStorage(BaseStorage):
    def __init__(self) -> None:
        self._cache: dict[tuple[int, int], dict] = {}

    def reset_cache(self) -> None:
        self._cache.clear()

    async def _row(self, key: StorageKey) -> dict:
        k = (key.user_id, key.chat_id)
        if k not in self._cache:
            rows = await db.select("fsm", {"user_id": f"eq.{key.user_id}", "chat_id": f"eq.{key.chat_id}"})
            self._cache[k] = rows[0] if rows else {"state": None, "data": {}}
        return self._cache[k]

    async def _save(self, key: StorageKey, **values) -> None:
        row = await self._row(key)
        row.update(values)
        await db.insert("fsm", {"user_id": key.user_id, "chat_id": key.chat_id,
                                "state": row.get("state"), "data": row.get("data") or {}},
                        upsert_on="user_id,chat_id")

    async def set_state(self, key: StorageKey, state=None) -> None:
        value = state.state if isinstance(state, State) else state
        row = await self._row(key)
        if row.get("state") == value and value is None:
            return
        await self._save(key, state=value)

    async def get_state(self, key: StorageKey) -> Optional[str]:
        return (await self._row(key)).get("state")

    async def set_data(self, key: StorageKey, data: Dict[str, Any]) -> None:
        row = await self._row(key)
        if not data and not row.get("data"):
            return
        await self._save(key, data=dict(data))

    async def get_data(self, key: StorageKey) -> Dict[str, Any]:
        return dict((await self._row(key)).get("data") or {})

    async def close(self) -> None:
        pass
