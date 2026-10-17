# salesbot

A company of AI bot employees that you run from a chat. You tell the **Manager** what you want;
it delegates to bots on the team, and when nobody fits the job, the **Recruiter** designs a new
bot and **HR** reviews it before it's hired. Each bot can run on a different LLM (Claude, GPT,
Grok or Gemini) and is given only the tools its job needs: web search, email, SMS and a built-in CRM.

You talk to the team over **Telegram** (or a local terminal chat), and it runs anywhere Docker runs.

```
 You (Telegram) ──► Manager ──► delegate_task ──► worker bots ──► tools (web, email, SMS, CRM)
                      │
                      └──► hire_bot ──► Recruiter (designs bot) ──► HR (approve / reject) ──► roster
```

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env        # fill in at least one LLM key and the Telegram settings
set -a; . ./.env; set +a

python -m salesbot chat      # local terminal chat with the Manager
python -m salesbot telegram  # run the Telegram bot
```

Or in the cloud / on a server:

```bash
docker compose up -d --build
```

Data (roster, tasks, approvals, chat memory, leads) lives in SQLite under `SALESBOT_DATA_DIR`
(a Docker volume in compose).

## Talking to the team

Just write normally, e.g.:

- "Hire a bot that finds independent dental clinics in Austin and adds them to the CRM."
- "Ask the lead researcher for 10 more clinics, then have someone draft a friendly intro email to each."
- "Fire the email writer, we don't need it anymore."

Commands (Telegram and terminal chat):

| Command | What it does |
|---|---|
| `/team` | List the bots on the team |
| `/hire <job>` | Hire a bot for a job description (Recruiter + HR) |
| `/fire <name>` | Retire a bot |
| `/pending` | Emails and texts waiting for your approval |
| `/approve <id>` / `/reject <id>` | Send or discard a queued email/text |
| `/reset` | Clear the Manager's memory of this chat |

## Safety defaults

- **Approval queue:** with `SALESBOT_REQUIRE_APPROVAL=true` (the default), bots can only *queue*
  emails and SMS. Nothing is sent until you `/approve` it.
- **Telegram allowlist:** only user IDs in `TELEGRAM_ALLOWED_USER_IDS` can command the team.
- **Least privilege:** each hired bot only gets the tools in its spec; HR is instructed to reject bots
  with more tools than the job needs, or that would spam or deceive.
- **Web fetch** refuses private, loopback and cloud-metadata addresses.

## LLM providers

Models are written as `<provider>:<model>` (or just `<provider>` for its default model):

| Provider | Example | Key |
|---|---|---|
| Anthropic Claude | `anthropic:claude-opus-5-5` | `ANTHROPIC_API_KEY` |
| OpenAI | `openai:gpt-5` | `OPENAI_API_KEY` |
| xAI Grok | `xai:grok-4` | `XAI_API_KEY` |
| Google Gemini | `gemini:gemini-2.5-pro` | `GEMINI_API_KEY` |

The Manager, HR and Recruiter use `SALESBOT_DEFAULT_MODEL`. The Recruiter picks a model for each new
bot from the providers you have keys for. Claude requests use adaptive thinking and server-side
refusal fallbacks.

## Project layout

```
salesbot/
  agents/agent.py      one bot: system prompt + model + tools, runs the tool-calling loop
  agents/team.py       Manager, HR, Recruiter; hiring, delegation, approvals
  llm/                 provider-neutral gateway + Claude / OpenAI / xAI / Gemini adapters
  tools/               web search & fetch, email, SMS, CRM
  store.py             SQLite persistence
  telegram_bot.py      Telegram front-end
  commands.py          slash commands shared by Telegram and terminal chat
tests/                 offline tests using a scripted fake LLM
```

## Tests

```bash
pytest -q
```

## Adding a tool

Create a `Tool(name, description, json_schema, async_handler)` in `salesbot/tools/` and add it to
`CATALOG` in `salesbot/tools/__init__.py`. The Recruiter can then give it to new bots.
