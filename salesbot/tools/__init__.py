"""Catalog of tools that hired bots can be given."""

from __future__ import annotations

from .base import Tool, ToolContext, ToolError
from .codebook import CODE_REFERENCE
from .crm import CRM_ADD_LEAD, CRM_EXPORT_CSV, CRM_FIND_LEADS, CRM_UPDATE_LEAD
from .github import GITHUB_REPO, GITHUB_SEARCH
from .openclaw import OPENCLAW_BROWSE
from .stocks import STOCK_ANALYZE, STOCK_FILTER, STOCK_SCREEN
from .outbound import SEND_EMAIL, SEND_SMS, execute_action
from .web import WEB_FETCH, WEB_SEARCH

CATALOG: dict[str, Tool] = {
    t.name: t
    for t in (
        WEB_SEARCH,
        WEB_FETCH,
        GITHUB_SEARCH,
        GITHUB_REPO,
        OPENCLAW_BROWSE,
        STOCK_ANALYZE,
        STOCK_SCREEN,
        STOCK_FILTER,
        CODE_REFERENCE,
        SEND_EMAIL,
        SEND_SMS,
        CRM_ADD_LEAD,
        CRM_UPDATE_LEAD,
        CRM_FIND_LEADS,
        CRM_EXPORT_CSV,
    )
}

__all__ = ["CATALOG", "Tool", "ToolContext", "ToolError", "execute_action"]
