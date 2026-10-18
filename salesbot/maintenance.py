"""The Maintenance team's checks and safe fixes: stuck tasks, duplicate contacts, stale approvals, backups."""

from __future__ import annotations

import glob
import os
import shutil
import time
from typing import Any

from .store import Store

STUCK_SECONDS = 30 * 60
STALE_SECONDS = 30 * 24 * 3600
KEEP_BACKUPS = 7
STAGES = ("new", "contacted", "qualified", "proposal", "won", "lost")


def contact_key(lead: dict[str, Any]) -> str:
    """Two contacts are the same person when their email matches, or (without email) name and company."""
    email = (lead.get("email") or "").strip().lower()
    if email:
        return "e:" + email
    name = (lead.get("name") or "").strip().lower()
    return f"n:{name}|{(lead.get('company') or '').strip().lower()}" if name else ""


def duplicate_groups(leads: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for lead in leads:
        key = contact_key(lead)
        if key:
            groups.setdefault(key, []).append(lead)
    return [sorted(g, key=lambda x: x["id"]) for g in groups.values() if len(g) > 1]


def backup_dir(data_dir: str) -> str:
    return os.path.join(data_dir, "backups")


def _dir_size(path: str) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


async def health(store: Store, data_dir: str, now: float | None = None) -> dict[str, Any]:
    now = now or time.time()
    running = await store.tasks_with_status("running")
    stuck = [t for t in running if now - t["created_at"] > STUCK_SECONDS]
    failed = await store.tasks_with_status("failed", since=now - 7 * 24 * 3600)
    dupes = duplicate_groups(await store.all_leads())
    stale = await store.pending_before(now - STALE_SECONDS)
    backups = sorted(glob.glob(os.path.join(backup_dir(data_dir), "*.db")))
    videos = await store.list_videos()
    disk = shutil.disk_usage(data_dir if os.path.isdir(data_dir) else ".")
    return {
        "stuck_tasks": [{"id": t["id"], "bot": t["agent"], "task": t["task"][:200]} for t in stuck],
        "failed_tasks_7d": [{"id": t["id"], "bot": t["agent"], "error": (t["result"] or "")[:300]} for t in failed[-10:]],
        "failed_count_7d": len(failed),
        "duplicate_contacts": [[{"id": x["id"], "name": x["name"], "email": x["email"]} for x in g] for g in dupes[:10]],
        "duplicate_count": sum(len(g) - 1 for g in dupes),
        "approvals_waiting_over_30_days": [{"id": a["id"], "kind": a["kind"], "by": a["requested_by"]} for a in stale],
        "videos_not_rendered": [v["id"] for v in videos if not v["file"]],
        "data_dir_mb": round(_dir_size(data_dir) / 1e6, 1) if os.path.isdir(data_dir) else 0,
        "disk_free_gb": round(disk.free / 1e9, 1),
        "last_backup": os.path.basename(backups[-1]) if backups else None,
    }


async def fix_stuck_tasks(store: Store, now: float | None = None) -> int:
    now = now or time.time()
    stuck = [t for t in await store.tasks_with_status("running") if now - t["created_at"] > STUCK_SECONDS]
    for t in stuck:
        await store.finish_task(t["id"], "Marked failed by Maintenance: no result after 30 minutes.", "failed")
    return len(stuck)


async def merge_duplicates(store: Store) -> int:
    """Merge each duplicate group into its oldest record: fill empty fields, keep the furthest pipeline
    stage, join the notes, then delete the extra records."""
    merged = 0
    for keep, *rest in duplicate_groups(await store.all_leads()):
        group = [keep, *rest]
        patch: dict[str, str] = {}
        for f in ("name", "company", "email", "phone"):
            if not keep[f]:
                value = next((x[f] for x in rest if x[f]), "")
                if value:
                    patch[f] = value
        stage = max((x["status"] for x in group), key=lambda s: STAGES.index(s) if s in STAGES else 0)
        if stage != keep["status"]:
            patch["status"] = stage
        notes = "\n".join(dict.fromkeys(n.strip() for n in (x["notes"] for x in group) if n and n.strip()))
        if notes != (keep["notes"] or "").strip():
            patch["notes"] = notes[:4000]
        if patch:
            await store.update_lead(keep["id"], **patch)
        for x in rest:
            await store.delete_lead(x["id"])
            merged += 1
    return merged


async def expire_stale_approvals(store: Store, now: float | None = None) -> int:
    now = now or time.time()
    stale = await store.pending_before(now - STALE_SECONDS)
    for a in stale:
        await store.resolve_pending(a["id"], "expired", "Expired by Maintenance after 30 days without a decision.")
    return len(stale)


async def backup(store: Store, data_dir: str, keep: int = KEEP_BACKUPS) -> str:
    folder = backup_dir(data_dir)
    path = os.path.join(folder, time.strftime("myops-%Y%m%d-%H%M%S.db"))
    await store.backup(path)
    for old in sorted(glob.glob(os.path.join(folder, "myops-*.db")))[:-keep]:
        os.remove(old)
    return path
