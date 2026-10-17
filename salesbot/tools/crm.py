"""Lightweight built-in CRM: leads stored in SQLite, exportable to CSV."""

from __future__ import annotations

import asyncio
import csv
import os
import time
from typing import Any

from ..store import LEAD_FIELDS
from .base import Tool, ToolContext, ToolError, schema, string

LEAD_PROPS = {
    "name": string("Contact name"),
    "company": string("Company name"),
    "email": string("Email address"),
    "phone": string("Phone number"),
    "status": string("Pipeline stage, e.g. new, contacted, qualified, won, lost"),
    "notes": string("Free-form notes"),
}


async def _add_lead(args: dict[str, Any], ctx: ToolContext) -> str:
    lead_id = await ctx.store.add_lead(**args)
    return f"Added lead #{lead_id} ({args.get('name')})."


async def _update_lead(args: dict[str, Any], ctx: ToolContext) -> str:
    lead_id = int(args.pop("lead_id"))
    if not await ctx.store.update_lead(lead_id, **args):
        raise ToolError(f"Lead #{lead_id} not found or nothing to update.")
    return f"Updated lead #{lead_id}."


async def _find_leads(args: dict[str, Any], ctx: ToolContext) -> str:
    leads = await ctx.store.find_leads(args.get("query", ""), args.get("status", ""))
    if not leads:
        return "No matching leads."
    return "\n".join(
        f"#{l['id']} {l['name']} | {l['company']} | {l['email']} | {l['phone']} | {l['status']} | {l['notes']}"
        for l in leads
    )


def _write_csv(path: str, leads: list[dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["id", *LEAD_FIELDS])
        writer.writeheader()
        writer.writerows(leads)


async def _export_leads(args: dict[str, Any], ctx: ToolContext) -> str:
    leads = await ctx.store.find_leads(limit=100000)
    path = os.path.join(ctx.settings.data_dir, f"leads-{int(time.time())}.csv")
    await asyncio.to_thread(_write_csv, path, leads)
    return f"Exported {len(leads)} leads to {path}."


CRM_ADD_LEAD = Tool(
    "crm_add_lead",
    "Add a new sales lead to the CRM.",
    schema(LEAD_PROPS, ["name"]),
    _add_lead,
)

CRM_UPDATE_LEAD = Tool(
    "crm_update_lead",
    "Update fields on an existing lead (e.g. move it to a new status or add notes).",
    schema({"lead_id": {"type": "integer", "description": "Lead ID"}, **LEAD_PROPS}, ["lead_id"]),
    _update_lead,
)

CRM_FIND_LEADS = Tool(
    "crm_find_leads",
    "Search leads by text and/or status.",
    schema({"query": string("Text to match in name, company, email or notes"), "status": string("Exact status")}),
    _find_leads,
)

CRM_EXPORT_CSV = Tool(
    "crm_export_csv",
    "Export all leads to a CSV spreadsheet file.",
    schema({}),
    _export_leads,
)
