"""SQLite persistence: the bot roster, task log, approval queue, chat memory and CRM."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    name TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    system_prompt TEXT NOT NULL,
    model TEXT NOT NULL,
    tools TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent TEXT NOT NULL,
    task TEXT NOT NULL,
    result TEXT,
    status TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS pending_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    result TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    role TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    company TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'new',
    notes TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS apps (
    slug TEXT PRIMARY KEY,
    spec TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    author TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spec TEXT NOT NULL,
    file TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_memory (
    chat_id TEXT PRIMARY KEY,
    summary TEXT NOT NULL,
    upto_id INTEGER NOT NULL,
    updated_at REAL NOT NULL
);
"""

LEAD_FIELDS = ("name", "company", "email", "phone", "status", "notes")


@dataclass
class AgentSpec:
    name: str
    role: str
    system_prompt: str
    model: str
    tools: list[str] = field(default_factory=list)


class Store:
    def __init__(self, path: str) -> None:
        self.path = path
        self._db: aiosqlite.Connection | None = None

    async def open(self) -> Store:
        if self.path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA)
        await self._db.commit()
        return self

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Store is not open")
        return self._db

    # --- roster -----------------------------------------------------------

    async def add_agent(self, spec: AgentSpec) -> None:
        await self.db.execute(
            "INSERT OR REPLACE INTO agents (name, role, system_prompt, model, tools, active, created_at)"
            " VALUES (?, ?, ?, ?, ?, 1, ?)",
            (spec.name, spec.role, spec.system_prompt, spec.model, json.dumps(spec.tools), time.time()),
        )
        await self.db.commit()

    async def get_agent(self, name: str) -> AgentSpec | None:
        async with self.db.execute("SELECT * FROM agents WHERE name = ? AND active = 1", (name,)) as cur:
            row = await cur.fetchone()
        return _row_to_spec(row) if row else None

    async def list_agents(self) -> list[AgentSpec]:
        async with self.db.execute("SELECT * FROM agents WHERE active = 1 ORDER BY created_at") as cur:
            rows = await cur.fetchall()
        return [_row_to_spec(r) for r in rows]

    async def set_agent_model(self, name: str, model: str) -> bool:
        cur = await self.db.execute("UPDATE agents SET model = ? WHERE name = ? AND active = 1", (model, name))
        await self.db.commit()
        return cur.rowcount > 0

    async def retire_agent(self, name: str) -> bool:
        cur = await self.db.execute("UPDATE agents SET active = 0 WHERE name = ? AND active = 1", (name,))
        await self.db.commit()
        return cur.rowcount > 0

    # --- task log ---------------------------------------------------------

    async def log_task(self, agent: str, task: str) -> int:
        cur = await self.db.execute(
            "INSERT INTO tasks (agent, task, status, created_at) VALUES (?, ?, 'running', ?)",
            (agent, task, time.time()),
        )
        await self.db.commit()
        return cur.lastrowid

    async def finish_task(self, task_id: int, result: str, status: str = "done") -> None:
        await self.db.execute("UPDATE tasks SET result = ?, status = ? WHERE id = ?", (result, status, task_id))
        await self.db.commit()

    async def recent_tasks(self, limit: int = 12) -> list[dict[str, Any]]:
        async with self.db.execute(
            "SELECT id, agent, task, result, status, created_at FROM tasks ORDER BY id DESC LIMIT ?", (limit,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    # --- approval queue ---------------------------------------------------

    async def add_pending(self, kind: str, payload: dict[str, Any], requested_by: str) -> int:
        cur = await self.db.execute(
            "INSERT INTO pending_actions (kind, payload, requested_by, created_at) VALUES (?, ?, ?, ?)",
            (kind, json.dumps(payload), requested_by, time.time()),
        )
        await self.db.commit()
        return cur.lastrowid

    async def get_pending(self, action_id: int) -> dict[str, Any] | None:
        async with self.db.execute("SELECT * FROM pending_actions WHERE id = ?", (action_id,)) as cur:
            row = await cur.fetchone()
        return _row_to_action(row) if row else None

    async def list_pending(self) -> list[dict[str, Any]]:
        async with self.db.execute(
            "SELECT * FROM pending_actions WHERE status = 'pending' ORDER BY id"
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_action(r) for r in rows]

    async def resolve_pending(self, action_id: int, status: str, result: str = "") -> bool:
        cur = await self.db.execute(
            "UPDATE pending_actions SET status = ?, result = ? WHERE id = ? AND status = 'pending'",
            (status, result, action_id),
        )
        await self.db.commit()
        return cur.rowcount > 0

    # --- chat memory ------------------------------------------------------

    async def add_chat(self, chat_id: str, role: str, text: str) -> None:
        await self.db.execute(
            "INSERT INTO chat_history (chat_id, role, text, created_at) VALUES (?, ?, ?, ?)",
            (chat_id, role, text, time.time()),
        )
        await self.db.commit()

    async def recent_chat(self, chat_id: str, limit: int = 20) -> list[tuple[str, str]]:
        async with self.db.execute(
            "SELECT role, text FROM chat_history WHERE chat_id = ? ORDER BY id DESC LIMIT ?", (chat_id, limit)
        ) as cur:
            rows = await cur.fetchall()
        return [(r["role"], r["text"]) for r in reversed(rows)]

    async def clear_chat(self, chat_id: str) -> None:
        await self.db.execute("DELETE FROM chat_history WHERE chat_id = ?", (chat_id,))
        await self.db.execute("DELETE FROM chat_memory WHERE chat_id = ?", (chat_id,))
        await self.db.commit()

    async def chat_rows_after(self, chat_id: str, after_id: int) -> list[tuple[int, str, str]]:
        async with self.db.execute(
            "SELECT id, role, text FROM chat_history WHERE chat_id = ? AND id > ? ORDER BY id", (chat_id, after_id)
        ) as cur:
            return [(r["id"], r["role"], r["text"]) for r in await cur.fetchall()]

    # --- mobile apps ------------------------------------------------------------

    async def save_app(self, spec: dict[str, Any]) -> None:
        await self.db.execute(
            "INSERT OR REPLACE INTO apps (slug, spec, updated_at) VALUES (?, ?, ?)",
            (spec["slug"], json.dumps(spec), time.time()),
        )
        await self.db.commit()

    async def get_app(self, slug: str) -> dict[str, Any] | None:
        async with self.db.execute("SELECT spec FROM apps WHERE slug = ?", (slug,)) as cur:
            row = await cur.fetchone()
        return json.loads(row["spec"]) if row else None

    async def list_apps(self) -> list[dict[str, Any]]:
        async with self.db.execute("SELECT spec FROM apps ORDER BY updated_at") as cur:
            return [json.loads(r["spec"]) for r in await cur.fetchall()]

    async def delete_app(self, slug: str) -> bool:
        cur = await self.db.execute("DELETE FROM apps WHERE slug = ?", (slug,))
        await self.db.commit()
        return cur.rowcount > 0

    # --- the Scribe's notes -------------------------------------------------------

    async def save_note(self, title: str, body: str, author: str, note_id: int | None = None) -> int:
        now = time.time()
        if note_id is not None:
            cur = await self.db.execute(
                "UPDATE notes SET title = ?, body = ?, author = ?, updated_at = ? WHERE id = ?",
                (title, body, author, now, note_id),
            )
            await self.db.commit()
            if cur.rowcount == 0:
                raise KeyError(note_id)
            return note_id
        cur = await self.db.execute(
            "INSERT INTO notes (title, body, author, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (title, body, author, now, now),
        )
        await self.db.commit()
        return cur.lastrowid

    async def get_note(self, note_id: int) -> dict[str, Any] | None:
        async with self.db.execute("SELECT * FROM notes WHERE id = ?", (note_id,)) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def list_notes(self, limit: int = 100) -> list[dict[str, Any]]:
        async with self.db.execute(
            "SELECT id, title, author, created_at, updated_at, length(body) AS chars FROM notes "
            "ORDER BY updated_at DESC LIMIT ?", (limit,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def delete_note(self, note_id: int) -> bool:
        cur = await self.db.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        await self.db.commit()
        return cur.rowcount > 0

    # --- the Video Producer's videos ------------------------------------------------

    async def add_video(self, spec: dict[str, Any]) -> int:
        cur = await self.db.execute(
            "INSERT INTO videos (spec, created_at) VALUES (?, ?)", (json.dumps(spec), time.time())
        )
        await self.db.commit()
        return cur.lastrowid

    async def set_video_file(self, video_id: int, file: str) -> None:
        await self.db.execute("UPDATE videos SET file = ? WHERE id = ?", (file, video_id))
        await self.db.commit()

    async def get_video(self, video_id: int) -> dict[str, Any] | None:
        async with self.db.execute("SELECT * FROM videos WHERE id = ?", (video_id,)) as cur:
            row = await cur.fetchone()
        return _row_to_video(row) if row else None

    async def list_videos(self, limit: int = 100) -> list[dict[str, Any]]:
        async with self.db.execute("SELECT * FROM videos ORDER BY id DESC LIMIT ?", (limit,)) as cur:
            return [_row_to_video(r) for r in await cur.fetchall()]

    async def delete_video(self, video_id: int) -> bool:
        cur = await self.db.execute("DELETE FROM videos WHERE id = ?", (video_id,))
        await self.db.commit()
        return cur.rowcount > 0

    async def get_memory(self, chat_id: str) -> tuple[str, int]:
        """The rolling summary of a chat's older turns, and the last message id it covers."""
        async with self.db.execute("SELECT summary, upto_id FROM chat_memory WHERE chat_id = ?", (chat_id,)) as cur:
            row = await cur.fetchone()
        return (row["summary"], row["upto_id"]) if row else ("", 0)

    async def set_memory(self, chat_id: str, summary: str, upto_id: int) -> None:
        await self.db.execute(
            "INSERT OR REPLACE INTO chat_memory (chat_id, summary, upto_id, updated_at) VALUES (?, ?, ?, ?)",
            (chat_id, summary, upto_id, time.time()),
        )
        await self.db.commit()

    # --- settings saved from the web app ------------------------------------

    async def get_settings(self) -> dict[str, str]:
        async with self.db.execute("SELECT key, value FROM settings") as cur:
            rows = await cur.fetchall()
        return {r["key"]: r["value"] for r in rows}

    async def set_settings(self, values: dict[str, str | None]) -> None:
        """Save values; None or "" removes the saved value (falling back to the environment)."""
        for key, value in values.items():
            if value is None or value == "":
                await self.db.execute("DELETE FROM settings WHERE key = ?", (key,))
            else:
                await self.db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        await self.db.commit()

    # --- CRM --------------------------------------------------------------

    async def add_lead(self, **fields: str) -> int:
        values = {k: str(fields.get(k) or "") for k in LEAD_FIELDS}
        values["status"] = values["status"] or "new"
        now = time.time()
        cur = await self.db.execute(
            "INSERT INTO leads (name, company, email, phone, status, notes, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (*(values[k] for k in LEAD_FIELDS), now, now),
        )
        await self.db.commit()
        return cur.lastrowid

    async def update_lead(self, lead_id: int, **fields: str) -> bool:
        updates = {k: str(v) for k, v in fields.items() if k in LEAD_FIELDS and v is not None}
        if not updates:
            return False
        assignments = ", ".join(f"{k} = ?" for k in updates)
        cur = await self.db.execute(
            f"UPDATE leads SET {assignments}, updated_at = ? WHERE id = ?",
            (*updates.values(), time.time(), lead_id),
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def find_leads(self, query: str = "", status: str = "", limit: int = 50) -> list[dict[str, Any]]:
        sql = "SELECT * FROM leads WHERE 1 = 1"
        params: list[Any] = []
        if query:
            sql += " AND (name LIKE ? OR company LIKE ? OR email LIKE ? OR notes LIKE ?)"
            params += [f"%{query}%"] * 4
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY id LIMIT ?"
        params.append(limit)
        async with self.db.execute(sql, params) as cur:
            rows = await cur.fetchall()
        return [{k: r[k] for k in ("id", *LEAD_FIELDS)} for r in rows]


def _row_to_spec(row: aiosqlite.Row) -> AgentSpec:
    return AgentSpec(
        name=row["name"],
        role=row["role"],
        system_prompt=row["system_prompt"],
        model=row["model"],
        tools=json.loads(row["tools"]),
    )


def _row_to_action(row: aiosqlite.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "payload": json.loads(row["payload"]),
        "requested_by": row["requested_by"],
        "status": row["status"],
        "result": row["result"],
    }


def _row_to_video(row: aiosqlite.Row) -> dict[str, Any]:
    return {"id": row["id"], **json.loads(row["spec"]), "file": row["file"], "created_at": row["created_at"]}


def spec_to_dict(spec: AgentSpec) -> dict[str, Any]:
    return asdict(spec)
