"""The bot company: a manager, HR, a recruiter, and the worker bots they hire."""

from __future__ import annotations

import logging
import re
from typing import Any

from .. import connections
from ..config import Settings
from ..llm import LLMError, LLMGateway, Message
from ..store import AgentSpec, Store
from ..tools import CATALOG, Tool, ToolContext, ToolError, execute_action
from ..tools.base import schema, string
from .agent import Agent

log = logging.getLogger(__name__)

STAFF = ("manager", "hr", "recruiter")
NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")

MANAGER_PROMPT = """You are the Manager of a small company of AI bot employees that works for one owner.
The owner talks to you in chat. Your job:
- Understand what the owner wants and break it into tasks.
- Delegate each task to the best-suited bot on the team with delegate_task. Give the bot a complete,
  self-contained brief; it cannot see this conversation.
- If no bot on the team fits the work, use hire_bot with a clear job description. The Recruiter will
  design the bot and HR will review it.
- Retire bots the owner no longer needs with fire_bot.
- Report back to the owner concisely: what was done, by whom, results, and anything awaiting their
  approval (emails and texts may be queued for approval; mention the action numbers).
Check list_team before delegating or hiring. Do the work through the team, not yourself."""

RECRUITER_PROMPT = """You are the Recruiter of a company of AI bot employees. Given a job description, you design
a new bot and submit it with submit_candidate. Design:
- name: short, lowercase, unique (e.g. "lead_researcher").
- role: one line describing the job.
- system_prompt: a thorough second-person brief: responsibilities, how to work, quality bar, what to
  report back, and limits (never invent contact details; ask for approval-gated actions to be explicit).
- model: "<provider>:<model>" or just "<provider>" for its default model. Pick from the available providers.
- tools: only the tools the job actually needs, from the catalog.
If submit_candidate returns an error, fix the problem and submit again. Finish with a one-line summary."""

HR_PROMPT = """You are HR for a company of AI bot employees. You review candidate bots before they join the team.
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

    def manager(self) -> Agent:
        return self._staff(
            "manager",
            MANAGER_PROMPT,
            [
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
            ],
        )

    # --- public API used by chat front-ends --------------------------------

    async def handle(self, chat_id: str, text: str) -> str:
        """Process one message from the owner through the Manager."""
        history = [
            Message(role="user" if role == "user" else "assistant", text=t)
            for role, t in await self.store.recent_chat(chat_id)
        ]
        try:
            reply = await self.manager().run(text, history)
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
        return reply

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
