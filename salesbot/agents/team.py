"""The bot company: leadership (manager, CTO), people (recruiter, HR), development (Android and iOS developers),
content (scribe, video producer), maintenance, and the worker bots they hire."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

from .. import connections, maintenance
from ..config import Settings
from ..apps import AppSpec, slugify
from ..apps import validate as validate_app
from ..llm import LLMError, LLMGateway, Message
from ..media import video as videos
from ..store import AgentSpec, Store
from ..tools import CATALOG, Tool, ToolContext, ToolError, execute_action
from ..tools.base import schema, string
from .agent import Agent

log = logging.getLogger(__name__)

STAFF = ("manager", "hr", "recruiter", "cto", "android_dev", "ios_dev", "scribe", "video_producer", "maintenance")
TEAMS = {
    "Leadership": ("manager", "cto"),
    "People": ("recruiter", "hr"),
    "Development": ("android_dev", "ios_dev"),
    "Content": ("scribe", "video_producer"),
    "Maintenance": ("maintenance",),
}
# Chat turns kept word for word; older ones are folded into the chat's long-term memory.
RECENT_MESSAGES = 20
MEMORY_BATCH = 6
MEMORY_MAX_CHARS = 4000
NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")

MANAGER_PROMPT = """You are the Manager of MyOps, a personal team of AI bot employees that works for one owner.
The team handles the owner's work and personal operations: research, planning, writing, follow-ups,
lead generation, reporting and admin. The owner talks to you in chat. Your job:
- Understand what the owner wants and break it into tasks.
- Delegate each task to the best-suited bot on the team with delegate_task. Give the bot a complete,
  self-contained brief; it cannot see this conversation.
- If no bot on the team fits the work, use hire_bot with a clear job description. The Recruiter will
  design the bot and HR will review it.
- Retire bots the owner no longer needs with fire_bot.
- Ask the app developers (ask_app_dev, platform android or ios) to create or update the team's phone
  apps, e.g. a separate app for each of the owner's businesses.
- Ask the CTO (ask_cto) about anything technical: which AI models are working or rate-limited, model
  choice and cost, connections and integrations, or when a bot fails for a technical reason.
- Ask the Scribe (ask_scribe) to write things down: minutes of the day's work, decision logs, summaries,
  SOPs and briefs. Notes are kept in the Notes tab.
- Ask the Video Producer (ask_video_producer) for short videos: promos, announcements, explainers and
  social clips (animated text scenes rendered to MP4, with a voice-over script and post caption).
- Ask the Maintenance team (ask_maintenance) for a health check of the team and its data (stuck or failed
  tasks, duplicate contacts, stale approvals, disk and backups), a database backup, or a clean-up. Ask for
  fixes only when the owner wants them.
- Report back to the owner concisely: what was done, by whom, results, and anything awaiting their
  approval (emails and texts may be queued for approval; mention the action numbers).
Check list_team before delegating or hiring. Do the work through the team, not yourself.
If you have openclaw_browse, you may use it yourself for quick research that helps you plan
(checking a company, a market or the news); hand longer research to a bot."""

RECRUITER_PROMPT = """You are the Recruiter of MyOps, a personal team of AI bot employees. Given a job description, you design
a new bot and submit it with submit_candidate. Design:
- name: short, lowercase, unique (e.g. "lead_researcher").
- role: one line describing the job.
- system_prompt: a thorough second-person brief: responsibilities, how to work, quality bar, what to
  report back, and limits (never invent contact details; ask for approval-gated actions to be explicit).
- model: "<provider>:<model>" or just "<provider>" for its default model. Pick from the available providers.
- tools: only the tools the job actually needs, from the catalog.
If submit_candidate returns an error, fix the problem and submit again. Finish with a one-line summary."""

CTO_PROMPT = """You are the CTO of MyOps, a personal team of AI bot employees. You own the technology:
- The AI models: which providers are connected, the API router's chain (free models first, the owner's
  own accounts as fallback), cooldowns and failures. Use system_status to see the live state.
- Model choice for each bot: strong models (the owner's Claude account, paid APIs) for complex reasoning and
  writing that matters; the router or a fast free model for routine, high-volume work. Change a bot's model
  with set_bot_model, and check a model really works with test_model first.
- When free models are failing or rate-limited, run run_api_hunt to refresh the router's chain.
- In hiring, you review the technical side of each candidate (model and tools) before HR sees it.
Be concrete and brief: say what you checked, what you changed and why. Never invent status: use your tools."""

APP_DEV_COMMON = """You build and update the owner's phone apps for MyOps. Every app is one business's app:
its own name, icon letter and colors, and the MyOps server it opens (server_url; empty means this server).
A business that needs its own separate team and data runs its own MyOps server; its app points there.
- Create or update an app with save_app (each save bumps its version). Use list_apps and app_links.
- Every app is installable instantly, with no store and no build: open its install link on the phone.
- The native project (download link from app_links) is built by the repo's "Mobile apps" GitHub workflow,
  or locally. Native apps load the server, so updates on the server reach phones without a new release;
  rebuild only when the name, icon or bundle id change.
- Pick a strong, readable color for the icon and a light background. Keep short_name to 12 characters.
Report the links and the exact next steps for the owner. Never claim an app is in a store unless the owner
published it."""

ANDROID_PROMPT = """You are the Android developer of MyOps, a personal team of AI bot employees.
""" + APP_DEV_COMMON + """
Android specifics: in Chrome, open the install link and tap Install app (or menu > Add to Home screen).
The workflow builds a debug APK that installs directly (allow installs from the browser/files app). For
Google Play: a signed release bundle (./gradlew bundleRelease) with the owner's upload key and a Play
Console account ($25 once)."""

IOS_PROMPT = """You are the iOS developer of MyOps, a personal team of AI bot employees.
""" + APP_DEV_COMMON + """
iOS specifics: in Safari, open the install link, tap Share > Add to Home Screen. A native iPhone app needs
an Apple Developer account ($99/year) and a Mac or the workflow's macOS build, then TestFlight for testing
and App Store review for release; without that, the home-screen app is the way to go."""

MEMORY_PROMPT = """You are the memory keeper of MyOps, a personal team of AI bot employees. You maintain a compact
long-term memory of the owner's chat with the Manager, used by whichever AI model answers next.
Merge the new turns into the current memory. Keep: the owner's goals, preferences and standing instructions;
decisions made; facts, names and numbers that matter; work done and by which bot; open tasks and promises.
Drop small talk and anything superseded. Write plain bullet points, newest state last. Reply with the memory only."""

SCRIBE_PROMPT = """You are the Scribe of MyOps, a personal team of AI bot employees. You keep the team's written record:
minutes, decision logs, daily summaries, SOPs, briefs and other documents.
- Work only from the material you are given and what your tools return (recent chat, the task log with each
  bot's results, existing notes). Never invent facts, numbers, decisions or names; if something is missing,
  say so in the note.
- Write clear Markdown: a short summary first, then headings and bullet points, with dates where known.
- Save with write_note. To revise an existing note, read it and pass its note_id; otherwise create a new one.
Reply with the note's title and id and a one-line summary."""

VIDEO_PROMPT = """You are the Video Producer of MyOps, a personal team of AI bot employees. You make short videos from
animated text scenes (no filmed footage): promos, explainers, announcements and social clips.
- Plan 3 to 10 scenes. Each scene: a punchy headline (at most 8 words) and an optional sub line (at most 20
  words), shown for 2 to 8 seconds. Open with a hook, end with a clear call to action.
- Aspect: 16:9 for websites and YouTube, 9:16 for Reels, Shorts and TikTok, 1:1 for feeds.
- Palette: hex colors bg, fg (strong contrast with bg) and accent.
- Write a voice-over script matching the scenes, and a post caption with hashtags for social media.
- Only state facts about the business from your brief; never invent prices, results, awards or testimonials.
Render it with create_video and report the title, length and the link it returns."""

MAINTENANCE_PROMPT = """You are the Maintenance team of MyOps, a personal team of AI bot employees: the systems maintainer
and the data keeper. You keep the team healthy and its data clean.
- Start with health_check. Report what you found in plain words: stuck or failing tasks (and the likely cause
  from their errors), duplicate contacts, approvals waiting over 30 days, disk space and the last backup.
- Fix only what you were asked to fix: fix_stuck_tasks, merge_duplicate_contacts, expire_stale_approvals.
  Before any clean-up that deletes or merges records, run backup_database first.
- For problems with AI models, keys or the router, say the CTO should look at it; do not guess.
Finish with what you checked, what you changed, and what the owner should do next, if anything."""

HR_PROMPT = """You are HR for MyOps, a personal team of AI bot employees. You review candidate bots before they join the team.
Approve with approve_hire only if: the role matches the job description, the system prompt is clear and
safe (no deception, no spam, respects consent and anti-spam law), and the tools are the minimum the job
needs (sending email or SMS must be justified by the job). Otherwise reject_hire with specific reasons.
Always call exactly one of approve_hire or reject_hire."""


class Team:
    def __init__(self, settings: Settings, store: Store, gateway: LLMGateway) -> None:
        self.base_settings = settings  # from the environment
        self.settings = settings  # environment + values saved in the web app
        self.store = store
        self.gateway = gateway
        self._memory_tasks: set = set()

    # --- connections --------------------------------------------------------

    async def load_settings(self) -> None:
        """Layer settings saved in the web app over the environment settings."""
        self.settings = connections.apply(self.base_settings, await self.store.get_settings())
        self.gateway.reset(self.settings)

    async def save_settings(self, values: dict[str, Any]) -> None:
        await self.store.set_settings(connections.validate(values))
        await self.load_settings()

    async def describe_settings(self) -> list[dict[str, Any]]:
        return connections.describe(self.settings, await self.store.get_settings())

    # --- staff ------------------------------------------------------------

    def _staff(self, name: str, prompt: str, tools: list[Tool]) -> Agent:
        spec = AgentSpec(name=name, role=name, system_prompt=prompt, model=self.settings.default_model)
        return Agent(spec, tools, self.gateway, self.settings, self.store)

    def manager(self, memory: str = "", chat_id: str = "") -> Agent:
        prompt = MANAGER_PROMPT
        if memory:
            prompt += ("\n\nLong-term memory of this chat (older turns, summarized; the recent turns follow as "
                       "messages):\n" + memory)
        return self._staff(
            "manager",
            prompt,
            [
                Tool(
                    "ask_app_dev",
                    "Ask the Android or iOS developer to create, update or explain the team's phone apps.",
                    schema({"platform": {"type": "string", "enum": ["android", "ios"]},
                            "request": string("What the app developer should do")}, ["platform", "request"]),
                    self._tool_ask_app_dev,
                ),
                Tool(
                    "ask_cto",
                    "Ask the CTO a technical question (models, API router, connections, bot model changes) and get the answer.",
                    schema({"question": string("The question or request for the CTO")}, ["question"]),
                    self._tool_ask_cto,
                ),
                Tool(
                    "ask_scribe",
                    "Ask the Scribe to write or update a note: minutes, decision log, summary, SOP or brief.",
                    schema({"request": string("What to write, for whom, and anything it must include")}, ["request"]),
                    lambda args, ctx: self.ask_scribe(args["request"], chat_id),
                ),
                Tool(
                    "ask_video_producer",
                    "Ask the Video Producer to make a short video (animated text, MP4) and get its link.",
                    schema({"request": string("The brief: purpose, audience, platform, length, key message, call to action")},
                           ["request"]),
                    self._tool_ask_video,
                ),
                Tool(
                    "ask_maintenance",
                    "Ask the Maintenance team for a health check, a database backup, or a clean-up and get its report.",
                    schema({"request": string("What to check or fix")}, ["request"]),
                    self._tool_ask_maintenance,
                ),
                Tool("list_team", "List the bots currently on the team.", schema({}), self._tool_list_team),
                Tool(
                    "delegate_task",
                    "Assign a task to a bot on the team and get its result.",
                    schema({"bot_name": string("Bot name"), "task": string("Complete task brief")}, ["bot_name", "task"]),
                    self._tool_delegate,
                ),
                Tool(
                    "hire_bot",
                    "Hire a new bot. The Recruiter designs it from the job description and HR reviews it.",
                    schema({"job_description": string("What the new bot must do")}, ["job_description"]),
                    self._tool_hire,
                ),
                Tool(
                    "fire_bot",
                    "Retire a bot from the team.",
                    schema({"bot_name": string("Bot name")}, ["bot_name"]),
                    self._tool_fire,
                ),
                Tool(
                    "list_pending_actions",
                    "List emails/texts waiting for the owner's approval.",
                    schema({}),
                    self._tool_pending,
                ),
                *([CATALOG["openclaw_browse"]] if self.settings.openclaw_url and self.settings.openclaw_token else []),
            ],
        )

    def app_dev(self, platform: str) -> Agent:
        tools = [
            Tool("list_apps", "List the team's apps with their install and download links.", schema({}), self._tool_list_apps),
            Tool("save_app", "Create an app, or update an existing one (same slug).", schema({
                "name": string("App name shown on the phone, e.g. 'Lopez Bakery'"),
                "slug": string("Optional short id, lowercase-with-dashes (default: from the name)"),
                "short_name": string("Optional home-screen label, up to 12 characters"),
                "color": string("Icon/theme color, hex like #233a57"),
                "background": string("Splash background, hex like #ffffff"),
                "letter": string("Optional icon letter (default: first letter of the name)"),
                "description": string("One line about the app"),
                "server_url": string("Optional: the MyOps server this app opens (https://...); empty = this server"),
                "notes": string("What changed in this version"),
            }, ["name"]), self._tool_save_app),
            Tool("app_links", "Install link, native project download and build steps for one app.",
                 schema({"slug": string("App slug")}, ["slug"]), self._tool_app_links),
            Tool("retire_app", "Remove an app (phones that installed it stop working).",
                 schema({"slug": string("App slug")}, ["slug"]), self._tool_retire_app),
        ]
        return self._staff(f"{platform}_dev", ANDROID_PROMPT if platform == "android" else IOS_PROMPT, tools)

    def cto(self) -> Agent:
        return self._staff(
            "cto",
            CTO_PROMPT,
            [
                Tool("system_status", "Live technical status: AI providers, the API router chain and cooldowns, "
                     "the last free API hunt, and each bot's model.", schema({}), self._tool_system_status),
                Tool("run_api_hunt", "Find free AI models again, test each one and rebuild the API router's chain.",
                     schema({}), self._tool_run_hunt),
                Tool("test_model", "Send a tiny tool-calling test to a model and report whether it works and how fast.",
                     schema({"model": string('"<provider>:<model>", "<provider>" or "router"')}, ["model"]),
                     self._tool_test_model),
                Tool("set_bot_model", "Change which AI model a hired bot runs on.",
                     schema({"bot_name": string("Bot name"), "model": string('"<provider>:<model>", "<provider>" or "router"')},
                            ["bot_name", "model"]), self._tool_set_bot_model),
            ],
        )

    def scribe(self) -> Agent:
        return self._staff("scribe", SCRIBE_PROMPT, [
            Tool("team_activity", "The latest tasks: which bot did what, with results.",
                 schema({"limit": {"type": "integer", "description": "How many tasks (default 12, at most 50)"}}),
                 self._tool_team_activity),
            Tool("list_notes", "List the saved notes (id, title, last update).", schema({}), self._tool_list_notes),
            Tool("read_note", "Read one note in full.", schema({"note_id": {"type": "integer"}}, ["note_id"]),
                 self._tool_read_note),
            Tool("write_note", "Save a note; pass note_id to update an existing one.", schema({
                "title": string("Short title"), "body": string("The note in Markdown"),
                "note_id": {"type": "integer", "description": "Optional: the note to update"},
            }, ["title", "body"]), self._tool_write_note),
        ])

    def video_producer(self) -> Agent:
        color = {"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"}
        return self._staff("video_producer", VIDEO_PROMPT, [
            Tool("create_video", "Render a storyboard to an MP4 video and save it.", schema({
                "title": string("Video title"),
                "aspect": {"type": "string", "enum": list(videos.ASPECTS)},
                "brand": string("Business name shown in the corner (optional)"),
                "palette": {"type": "object", "properties": {"bg": color, "fg": color, "accent": color}},
                "scenes": {"type": "array", "items": {"type": "object", "properties": {
                    "headline": string("At most 8 words"), "sub": string("Optional, at most 20 words"),
                    "seconds": {"type": "number", "minimum": 2, "maximum": 8}}, "required": ["headline"]}},
                "narration": string("Voice-over script"), "caption": string("Post caption with hashtags"),
            }, ["title", "aspect", "scenes"]), self._tool_create_video),
            Tool("list_videos", "List the videos made so far.", schema({}), self._tool_list_videos),
        ])

    def maintenance(self) -> Agent:
        return self._staff("maintenance", MAINTENANCE_PROMPT, [
            Tool("health_check", "Stuck and failed tasks, duplicate contacts, stale approvals, unrendered videos, "
                 "disk space and the last backup.", schema({}), self._tool_health),
            Tool("backup_database", "Save a backup copy of the whole database (the last 7 are kept).", schema({}),
                 self._tool_backup),
            Tool("fix_stuck_tasks", "Mark tasks running for over 30 minutes as failed.", schema({}), self._tool_fix_stuck),
            Tool("merge_duplicate_contacts", "Merge duplicate contacts (same email, or same name and company) into the "
                 "oldest record.", schema({}), self._tool_merge_dupes),
            Tool("expire_stale_approvals", "Expire emails/texts that waited over 30 days for approval.", schema({}),
                 self._tool_expire),
        ])

    async def ask_scribe(self, request: str, chat_id: str = "") -> str:
        chat = await self.store.recent_chat(chat_id, 20) if chat_id else []
        transcript = "\n".join(f"{'Owner' if role == 'user' else 'Manager'}: {text[:1200]}" for role, text in chat)
        brief = f"Request: {request}\n\nRecent chat with the owner:\n{transcript or '(none)'}"
        return await self.scribe().run(brief)

    def video_path(self, video_id: int) -> str:
        return os.path.join(self.settings.data_dir, "videos", f"{video_id}.mp4")

    # --- public API used by chat front-ends --------------------------------

    async def handle(self, chat_id: str, text: str) -> str:
        """Process one message from the owner through the Manager."""
        history = [
            Message(role="user" if role == "user" else "assistant", text=t)
            for role, t in await self.store.recent_chat(chat_id, RECENT_MESSAGES)
        ]
        memory, _ = await self.store.get_memory(chat_id)
        try:
            reply = await self.manager(memory, chat_id).run(text, history)
        except LLMError as exc:
            reply = f"Configuration problem: {exc}"
        except Exception as exc:  # provider SDK errors: bad/missing key, network, rate limits
            log.exception("manager failed")
            reply = (
                f"The Manager couldn't reach its AI model ({self.settings.default_model}): {exc}\n"
                "Check that the API key for this provider is set and valid."
            )
        await self.store.add_chat(chat_id, "user", text)
        await self.store.add_chat(chat_id, "assistant", reply)
        await self.update_memory(chat_id)
        return reply

    # --- long-term chat memory ------------------------------------------------

    async def update_memory(self, chat_id: str) -> None:
        """Fold chat turns that fall out of the recent window into the chat's rolling summary,
        so the thread survives model switches, restarts and long conversations."""
        summary, upto = await self.store.get_memory(chat_id)
        rows = await self.store.chat_rows_after(chat_id, upto)
        older = rows[:-RECENT_MESSAGES]
        if len(older) < MEMORY_BATCH:
            return
        transcript = "\n".join(f"{'Owner' if role == 'user' else 'Manager'}: {text[:1500]}" for _, role, text in older)
        try:
            keeper = self._staff("memory", MEMORY_PROMPT, [])
            new = await keeper.run(
                f"Current memory:\n{summary or '(empty)'}\n\nNew turns to fold in:\n{transcript}\n\n"
                f"Write the updated memory (at most {MEMORY_MAX_CHARS} characters)."
            )
        except Exception:  # the summary must never block the chat; fall back to an extract
            log.warning("memory summary failed for %s; keeping an extract", chat_id, exc_info=True)
            new = (summary + "\n" + transcript).strip()
        await self.store.set_memory(chat_id, new.strip()[-MEMORY_MAX_CHARS:], older[-1][0])

    async def roster(self) -> list[AgentSpec]:
        return await self.store.list_agents()

    async def delegate(self, bot_name: str, task: str) -> str:
        spec = await self.store.get_agent(bot_name)
        if spec is None:
            raise ToolError(f"No bot named {bot_name!r} on the team.")
        tools = [CATALOG[t] for t in spec.tools if t in CATALOG]
        agent = Agent(spec, tools, self.gateway, self.settings, self.store)
        task_id = await self.store.log_task(bot_name, task)
        try:
            result = await agent.run(task)
        except Exception as exc:
            await self.store.finish_task(task_id, str(exc), "failed")
            raise ToolError(f"{bot_name} failed: {exc}") from exc
        await self.store.finish_task(task_id, result)
        return result

    async def hire(self, job_description: str) -> str:
        """Recruiter designs a bot, HR reviews it, and it joins the roster if approved."""
        candidate: dict[str, AgentSpec] = {}
        decision: dict[str, Any] = {}

        async def submit_candidate(args: dict[str, Any], ctx: ToolContext) -> str:
            spec = AgentSpec(
                name=str(args["name"]).strip().lower(),
                role=str(args["role"]).strip(),
                system_prompt=str(args["system_prompt"]).strip(),
                model=str(args["model"]).strip(),
                tools=[str(t) for t in args.get("tools", [])],
            )
            problems = await self.validate(spec)
            if problems:
                raise ToolError("Candidate rejected: " + "; ".join(problems))
            candidate["spec"] = spec
            return "Candidate submitted to HR."

        recruiter = self._staff(
            "recruiter",
            RECRUITER_PROMPT,
            [
                Tool(
                    "submit_candidate",
                    "Submit the designed bot for HR review.",
                    schema(
                        {
                            "name": string("Unique lowercase name"),
                            "role": string("One-line role"),
                            "system_prompt": string("Full system prompt for the bot"),
                            "model": string('"<provider>:<model>" or "<provider>"'),
                            "tools": {
                                "type": "array",
                                "items": {"type": "string", "enum": sorted(CATALOG)},
                                "description": "Tool names from the catalog",
                            },
                        },
                        ["name", "role", "system_prompt", "model", "tools"],
                    ),
                    submit_candidate,
                )
            ],
        )
        catalog = "\n".join(f"- {t.name}: {t.description}" for t in CATALOG.values())
        team = ", ".join(s.name for s in await self.roster()) or "(nobody yet)"
        recruiter_notes = await recruiter.run(
            f"Job description:\n{job_description}\n\n"
            f"Tool catalog:\n{catalog}\n\n"
            f"Available LLM providers: {', '.join(self.gateway.available()) or 'none configured'}. "
            f"Default model: {self.settings.default_model}.\n"
            f"Existing bots (names taken): {team}, {', '.join(STAFF)}."
        )
        if "spec" not in candidate:
            return f"Recruiter could not produce a valid candidate. Notes: {recruiter_notes}"
        spec = candidate["spec"]

        verdict = await self.cto_review(job_description, spec)
        if not verdict.get("approved"):
            return f"The CTO rejected {spec.name}: {verdict.get('reason') or 'no decision made'}"
        if verdict.get("model") and verdict["model"] != spec.model:
            spec.model = verdict["model"]

        async def approve_hire(args: dict[str, Any], ctx: ToolContext) -> str:
            decision.update(approved=True, reason=args.get("reason", ""))
            return "Hire approved."

        async def reject_hire(args: dict[str, Any], ctx: ToolContext) -> str:
            decision.update(approved=False, reason=args.get("reason", ""))
            return "Hire rejected."

        reason_schema = schema({"reason": string("Short justification")}, ["reason"])
        hr = self._staff(
            "hr",
            HR_PROMPT,
            [
                Tool("approve_hire", "Approve the candidate.", reason_schema, approve_hire),
                Tool("reject_hire", "Reject the candidate.", reason_schema, reject_hire),
            ],
        )
        await hr.run(
            f"Job description:\n{job_description}\n\nCandidate:\n"
            f"name: {spec.name}\nrole: {spec.role}\nmodel: {spec.model}\ntools: {', '.join(spec.tools) or '(none)'}\n"
            f"system_prompt:\n{spec.system_prompt}"
        )
        if not decision.get("approved"):
            return f"HR rejected {spec.name}: {decision.get('reason') or 'no decision made'}"
        await self.store.add_agent(spec)
        return (
            f"Hired {spec.name} ({spec.role}) on {spec.model} with tools: {', '.join(spec.tools) or 'none'}. "
            f"HR: {decision.get('reason', '')}"
        )

    async def cto_review(self, job_description: str, spec: AgentSpec) -> dict[str, Any]:
        """The CTO checks a candidate's model and tools, and may move it to a better-suited model."""
        verdict: dict[str, Any] = {}

        async def tech_approve(args: dict[str, Any], ctx: ToolContext) -> str:
            model = str(args.get("model") or spec.model).strip()
            try:
                provider, _ = self.gateway.resolve(model)
            except LLMError as exc:
                raise ToolError(str(exc)) from exc
            if provider not in self.gateway.available():
                raise ToolError(f"{provider!r} is not connected; pick one of: {', '.join(self.gateway.available())}")
            verdict.update(approved=True, model=model, reason=args.get("notes", ""))
            return f"Technically approved on {model}."

        async def tech_reject(args: dict[str, Any], ctx: ToolContext) -> str:
            verdict.update(approved=False, reason=args.get("reason", ""))
            return "Technically rejected."

        cto = self.cto()
        cto.tools.update({
            "tech_approve": Tool("tech_approve", "Approve the candidate's technical setup, optionally on a different model.",
                                 schema({"model": string("Model to run on (keep the proposed one if it fits)"),
                                         "notes": string("Short technical note")}, ["notes"]), tech_approve),
            "tech_reject": Tool("tech_reject", "Reject: the job cannot work with the available models or tools.",
                                schema({"reason": string("What is missing")}, ["reason"]), tech_reject),
        })
        await cto.run(
            f"Technical review of a candidate bot. Call exactly one of tech_approve or tech_reject.\n"
            f"Job description:\n{job_description}\n\nCandidate: name {spec.name}; role {spec.role}; "
            f"proposed model {spec.model}; tools {', '.join(spec.tools) or '(none)'}.\n"
            f"Connected providers: {', '.join(self.gateway.available())}. Default model: {self.settings.default_model}."
        )
        return verdict

    async def fire(self, bot_name: str) -> str:
        if bot_name in STAFF:
            return f"{bot_name} is core staff and can't be fired."
        if await self.store.retire_agent(bot_name):
            return f"{bot_name} has been retired."
        return f"No active bot named {bot_name!r}."

    async def validate(self, spec: AgentSpec) -> list[str]:
        problems = []
        if not NAME_RE.match(spec.name):
            problems.append("name must be 2-32 chars: lowercase letters, digits, _ or -, starting with a letter")
        if spec.name in STAFF or await self.store.get_agent(spec.name):
            problems.append(f"name {spec.name!r} is already taken")
        if not spec.role:
            problems.append("role is empty")
        if len(spec.system_prompt) < 40:
            problems.append("system_prompt is too short")
        unknown = [t for t in spec.tools if t not in CATALOG]
        if unknown:
            problems.append(f"unknown tools: {', '.join(unknown)}")
        try:
            provider, _ = self.gateway.resolve(spec.model)
            if provider not in self.gateway.available():
                problems.append(f"provider {provider!r} has no API key configured")
        except LLMError as exc:
            problems.append(str(exc))
        return problems

    async def approve(self, action_id: int) -> str:
        action = await self.store.get_pending(action_id)
        if action is None or action["status"] != "pending":
            return f"No pending action #{action_id}."
        try:
            result = await execute_action(self.settings, action["kind"], action["payload"])
        except Exception as exc:
            await self.store.resolve_pending(action_id, "failed", str(exc))
            return f"Action #{action_id} failed: {exc}"
        await self.store.resolve_pending(action_id, "sent", result)
        return f"Action #{action_id}: {result}"

    async def reject(self, action_id: int) -> str:
        if await self.store.resolve_pending(action_id, "rejected"):
            return f"Action #{action_id} rejected; nothing was sent."
        return f"No pending action #{action_id}."

    async def pending_summary(self) -> str:
        actions = await self.store.list_pending()
        if not actions:
            return "No actions awaiting approval."
        lines = []
        for a in actions:
            p = a["payload"]
            if a["kind"] == "email":
                detail = f"to {p['to']} - {p['subject']}\n{p['body']}"
            else:
                detail = f"to {p['to']}\n{p['body']}"
            lines.append(f"#{a['id']} {a['kind']} by {a['requested_by']} {detail}")
        return "\n\n".join(lines)

    # --- manager tool handlers ---------------------------------------------

    async def _tool_list_team(self, args: dict[str, Any], ctx: ToolContext) -> str:
        bots = await self.roster()
        if not bots:
            return "The team has no worker bots yet. Use hire_bot to add one."
        return "\n".join(f"- {b.name}: {b.role} [model {b.model}; tools {', '.join(b.tools) or 'none'}]" for b in bots)

    async def _tool_delegate(self, args: dict[str, Any], ctx: ToolContext) -> str:
        return await self.delegate(args["bot_name"], args["task"])

    async def _tool_hire(self, args: dict[str, Any], ctx: ToolContext) -> str:
        return await self.hire(args["job_description"])

    async def _tool_fire(self, args: dict[str, Any], ctx: ToolContext) -> str:
        return await self.fire(args["bot_name"])

    async def _tool_pending(self, args: dict[str, Any], ctx: ToolContext) -> str:
        return await self.pending_summary()

    async def _tool_ask_cto(self, args: dict[str, Any], ctx: ToolContext) -> str:
        return await self.cto().run(args["question"])

    async def _tool_ask_app_dev(self, args: dict[str, Any], ctx: ToolContext) -> str:
        platform = str(args.get("platform", "android")).lower()
        if platform not in ("android", "ios"):
            raise ToolError("platform must be android or ios")
        return await self.app_dev(platform).run(args["request"])

    async def _tool_ask_maintenance(self, args: dict[str, Any], ctx: ToolContext) -> str:
        return await self.maintenance().run(args["request"])

    async def _tool_health(self, args: dict[str, Any], ctx: ToolContext) -> str:
        report = await maintenance.health(self.store, self.settings.data_dir)
        report["ai_providers_connected"] = self.gateway.available()
        return json.dumps(report, indent=1)

    async def _tool_backup(self, args: dict[str, Any], ctx: ToolContext) -> str:
        if self.store.path == ":memory:":
            raise ToolError("This database is in memory only; there is nothing on disk to back up.")
        return f"Backed up the database to {await maintenance.backup(self.store, self.settings.data_dir)}"

    async def _tool_fix_stuck(self, args: dict[str, Any], ctx: ToolContext) -> str:
        return f"Marked {await maintenance.fix_stuck_tasks(self.store)} stuck task(s) failed."

    async def _tool_merge_dupes(self, args: dict[str, Any], ctx: ToolContext) -> str:
        return f"Merged {await maintenance.merge_duplicates(self.store)} duplicate contact(s) into their oldest record."

    async def _tool_expire(self, args: dict[str, Any], ctx: ToolContext) -> str:
        return f"Expired {await maintenance.expire_stale_approvals(self.store)} stale approval(s)."

    async def _tool_ask_video(self, args: dict[str, Any], ctx: ToolContext) -> str:
        return await self.video_producer().run(args["request"])

    # --- scribe and video producer tool handlers --------------------------------

    async def _tool_team_activity(self, args: dict[str, Any], ctx: ToolContext) -> str:
        limit = max(1, min(50, int(args.get("limit") or 12)))
        rows = await self.store.recent_tasks(limit)
        return json.dumps([{
            "id": r["id"], "bot": r["agent"], "status": r["status"],
            "when": time.strftime("%Y-%m-%d %H:%M", time.localtime(r["created_at"])),
            "task": r["task"][:400], "result": (r["result"] or "")[:1200],
        } for r in rows], indent=1) if rows else "No tasks yet."

    async def _tool_list_notes(self, args: dict[str, Any], ctx: ToolContext) -> str:
        notes = await self.store.list_notes(50)
        return json.dumps([{"id": n["id"], "title": n["title"],
                            "updated": time.strftime("%Y-%m-%d", time.localtime(n["updated_at"]))} for n in notes]) \
            if notes else "No notes yet."

    async def _tool_read_note(self, args: dict[str, Any], ctx: ToolContext) -> str:
        note = await self.store.get_note(int(args["note_id"]))
        if note is None:
            raise ToolError(f"No note {args['note_id']}.")
        return f"# {note['title']}\n\n{note['body']}"

    async def _tool_write_note(self, args: dict[str, Any], ctx: ToolContext) -> str:
        title, body = str(args.get("title", "")).strip()[:160], str(args.get("body", "")).strip()[:40000]
        if not title or not body:
            raise ToolError("A note needs a title and a body.")
        note_id = args.get("note_id")
        try:
            saved = await self.store.save_note(title, body, ctx.agent_name, int(note_id) if note_id else None)
        except KeyError as exc:
            raise ToolError(f"No note {note_id}; leave note_id out to create one.") from exc
        return f"{'Updated' if note_id else 'Saved'} note {saved}: {title}"

    async def _tool_create_video(self, args: dict[str, Any], ctx: ToolContext) -> str:
        spec = videos.from_dict(args)
        bad = videos.problems(spec)
        if bad:
            raise ToolError("Video not made: " + "; ".join(bad))
        brand = str(args.get("brand") or "").strip()[:60]
        video_id = await self.store.add_video({**spec.to_dict(), "brand": brand})
        path = self.video_path(video_id)
        try:
            await videos.render_mp4(spec, path, brand)
        except RuntimeError as exc:
            return (f"Saved storyboard {video_id} ({spec.title}) but could not render the MP4: {exc}. "
                    "The scenes, narration and caption are in the Videos tab.")
        await self.store.set_video_file(video_id, os.path.basename(path))
        base = self.settings.public_url.rstrip("/")
        return (f"Video {video_id} ready: {spec.title}, {len(spec.scenes)} scenes, {spec.duration:g}s, {spec.aspect}. "
                f"Watch or download: {base}/api/videos/{video_id}.mp4 (also in the Videos tab).")

    async def _tool_list_videos(self, args: dict[str, Any], ctx: ToolContext) -> str:
        rows = await self.store.list_videos(30)
        return json.dumps([{"id": v["id"], "title": v["title"], "aspect": v["aspect"],
                            "rendered": bool(v["file"])} for v in rows]) if rows else "No videos yet."

    # --- app developer tool handlers ------------------------------------------

    def app_links(self, spec: AppSpec, base_url: str = "") -> dict[str, Any]:
        base = (base_url or self.settings.public_url).rstrip("/")
        server = (spec.server_url or base).rstrip("/")
        return {
            **spec.to_dict(),
            "bundle_id": spec.bundle_id,
            "install_link": f"{server}/app/{spec.slug}" if server else f"/app/{spec.slug}",
            "native_project_download": f"{base}/api/apps/{spec.slug}/native.zip",
            "needs_public_url": not server,
        }

    async def _tool_list_apps(self, args: dict[str, Any], ctx: ToolContext) -> str:
        apps = [self.app_links(AppSpec.from_dict(a)) for a in await self.store.list_apps()]
        return json.dumps(apps, indent=1) if apps else "No apps yet."

    async def _tool_save_app(self, args: dict[str, Any], ctx: ToolContext) -> str:
        name = str(args.get("name", "")).strip()
        slug = str(args.get("slug") or "").strip().lower() or slugify(name)
        old = await self.store.get_app(slug)
        fields = {k: str(v).strip() for k, v in args.items() if k in AppSpec.__dataclass_fields__ and v not in (None, "")}
        spec = AppSpec.from_dict({**(old or {}), **fields, "slug": slug, "name": name or (old or {}).get("name", ""),
                                  "version": (old or {}).get("version", 0) + 1})
        problems = validate_app(spec)
        if problems:
            raise ToolError("App not saved: " + "; ".join(problems))
        await self.store.save_app(spec.to_dict())
        links = self.app_links(spec)
        note = " Set the server's public address (SALESBOT_PUBLIC_URL) so phones can reach it." if links["needs_public_url"] else ""
        return f"{'Updated' if old else 'Created'} {spec.name} v{spec.version}: {json.dumps(links)}{note}"

    async def _tool_app_links(self, args: dict[str, Any], ctx: ToolContext) -> str:
        data = await self.store.get_app(str(args["slug"]).strip())
        if data is None:
            raise ToolError(f"No app {args['slug']!r}.")
        return json.dumps(self.app_links(AppSpec.from_dict(data)), indent=1)

    async def _tool_retire_app(self, args: dict[str, Any], ctx: ToolContext) -> str:
        if not await self.store.delete_app(str(args["slug"]).strip()):
            raise ToolError(f"No app {args['slug']!r}.")
        return f"Removed app {args['slug']}."

    # --- CTO tool handlers ----------------------------------------------------

    async def _tool_system_status(self, args: dict[str, Any], ctx: ToolContext) -> str:
        from ..llm.hunter import load_hunt

        router = self.gateway.provider("router").status()
        hunted = load_hunt(self.settings)
        bots = await self.roster()
        return json.dumps({
            "default_model": self.settings.default_model,
            "providers_connected": self.gateway.available(),
            "router_chain": router["chain"],
            "router_prefer": self.settings.router_prefer,
            "last_hunt": {k: hunted.get(k) for k in ("hunted_at", "notes")} | {
                "rejected": [{"model": c["model"], "error": c.get("error")} for c in hunted.get("rejected", [])]},
            "bots": [{"name": b.name, "model": b.model} for b in bots],
        }, indent=1)

    async def _tool_run_hunt(self, args: dict[str, Any], ctx: ToolContext) -> str:
        from ..llm.hunter import hunt

        result = await hunt(self.settings, self.gateway)
        chain = ", ".join(f"{c['model']} ({c.get('latency_s')}s)" for c in result["chain"]) or "no working models"
        return f"Router chain: {chain}. Rejected: {len(result['rejected'])}. Notes: {' '.join(result['notes'])}"

    async def _tool_test_model(self, args: dict[str, Any], ctx: ToolContext) -> str:
        from ..llm.hunter import probe

        return json.dumps(await probe(self.gateway, str(args["model"]).strip()))

    async def _tool_set_bot_model(self, args: dict[str, Any], ctx: ToolContext) -> str:
        name, model = str(args["bot_name"]).strip(), str(args["model"]).strip()
        try:
            provider, _ = self.gateway.resolve(model)
        except LLMError as exc:
            raise ToolError(str(exc)) from exc
        if provider not in self.gateway.available():
            raise ToolError(f"{provider!r} is not connected.")
        if not await self.store.set_agent_model(name, model):
            raise ToolError(f"No active bot named {name!r}.")
        return f"{name} now runs on {model}."
