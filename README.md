# salesbot

A company of AI bot employees that you run from a chat. You tell the **Manager** what you want;
it delegates to bots on the team, and when nobody fits the job, the **Recruiter** designs a new
bot and **HR** reviews it before it's hired. Each bot can run on a different LLM (Claude, GPT,
Grok or Gemini) and is given only the tools its job needs: web search, email, SMS and a built-in CRM.

You talk to the team from a **web app**, over **Telegram**, or in a terminal chat, and it runs anywhere Docker runs.

```
 You (Telegram) ──► Manager ──► delegate_task ──► worker bots ──► tools (web, email, SMS, CRM)
                      │
                      └──► hire_bot ──► Recruiter (designs bot) ──► HR (approve / reject) ──► roster
```

## Deploy (get your own link)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/neofinn/salesbot)

1. Click the button and connect your GitHub account. Render reads `render.yaml`, builds the Docker
   image, and gives you a permanent `https://salesbot-xxxx.onrender.com` link with a 1 GB disk for data.
2. In the Render dashboard, open the service's **Environment** tab and copy `SALESBOT_WEB_TOKEN`
   (generated for you). That's your sign-in token.
3. Open your link, sign in, and use **Connections** to connect an AI (see below).

Any host that runs Docker works the same way (Railway, Fly.io, a VPS with `docker compose up -d`);
set `SALESBOT_WEB_TOKEN` and mount a volume at `/data`.

## Connections

Open **Connections** in the web app header (it opens by itself until an AI is connected):

- **Sign in with OpenRouter**: one click, no key to copy. OpenRouter's OAuth sign-in hands the app an
  API key for your OpenRouter account, which gives the team Claude, GPT, Grok, Gemini and more.
- **Or paste API keys** for Anthropic, OpenAI, xAI or Gemini, then press **Test** to check each one.
- **Claude Code CLI**: if the server has Claude Code installed and signed in, it shows as connected
  automatically (not in the Docker image).
- Email (SMTP), text messages (Twilio), web search (Brave) and the approval switch live here too.

Keys saved here are stored in the app's database on your server's disk and override environment
variables; secrets are never sent back to the browser (only a masked hint). Leave
**Model for Manager, HR and Recruiter** empty to use whichever AI is connected.

## Quick start (local)

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env        # fill in at least one LLM key and the Telegram settings
set -a; . ./.env; set +a

python -m salesbot web       # web app on http://127.0.0.1:8000 (open Connections to add an AI)
python -m salesbot telegram  # Telegram bot
python -m salesbot chat      # terminal chat with the Manager
```

Or in the cloud / on a server (set `SALESBOT_WEB_TOKEN` in `.env` first):

```bash
docker compose up -d --build                       # web app on port 8000
docker compose --profile telegram up -d --build    # web app + Telegram bot
```

## Web app

Chat with the Manager on the left, and on the right manage the **Team** (hire / fire),
**Approvals** (approve or reject queued emails and texts) and **Leads**. Header pills show which
providers and channels are configured. Works on phones too.

Anywhere other than localhost, the web app requires `SALESBOT_WEB_TOKEN`; you sign in with it once
(stored in an HTTP-only cookie), or send it as `Authorization: Bearer <token>` to the JSON API under
`/api/`. It listens on `SALESBOT_WEB_HOST`/`SALESBOT_WEB_PORT` (or `PORT`, as set by most hosts).

Data (roster, tasks, approvals, chat memory, leads) lives in SQLite under `SALESBOT_DATA_DIR`
(a Docker volume in compose).

## Talking to the team

Just write normally, e.g.:

- "Hire a bot that finds independent dental clinics in Austin and adds them to the CRM."
- "Ask the lead researcher for 10 more clinics, then have someone draft a friendly intro email to each."
- "Fire the email writer, we don't need it anymore."

Commands (web chat, Telegram and terminal chat):

| Command | What it does |
|---|---|
| `/team` | List the bots on the team |
| `/hire <job>` | Hire a bot for a job description (Recruiter + HR) |
| `/fire <name>` | Retire a bot |
| `/pending` | Emails and texts waiting for your approval |
| `/approve <id>` / `/reject <id>` | Send or discard a queued email/text |
| `/reset` | Clear the Manager's memory of this chat |

## OpenClaw browser agent (optional)

[OpenClaw](https://docs.openclaw.ai) (formerly Clawdbot) is a self-hosted agent with a real
browser. Salesbot can hand it research while the Manager, HR and your approval queue stay in
charge:

- **Python app:** enable the Gateway's OpenAI-compatible endpoint
  (`gateway.http.endpoints.chatCompletions.enabled: true`), then set the OpenClaw Gateway URL and
  token in Connections (or `OPENCLAW_URL` / `OPENCLAW_TOKEN`). The Manager can then call
  `openclaw_browse` itself, and the Recruiter can give it to hired bots. The task brief tells
  OpenClaw to research only: no logins, purchases, posts or messages.
- **claude.ai artifact:** the page can't reach a Gateway on your machine, so the two share the
  Airtable lead table instead. Copy `integrations/openclaw/salesbot-leads/` into your OpenClaw
  skills folder and set `AIRTABLE_TOKEN` and `SALESBOT_AIRTABLE_BASE`. OpenClaw adds the leads it
  finds there, and "Import from Airtable" on the Leads tab brings them into the team.

OpenClaw runs with your computer's permissions. Keep its Gateway on localhost or a private
network, install skills only from sources you trust, and keep sending behind approval.

## Safety defaults

- **Approval queue:** with `SALESBOT_REQUIRE_APPROVAL=true` (the default), bots can only *queue*
  emails and SMS. Nothing is sent until you `/approve` it.
- **Web sign-in:** the web app refuses to listen beyond localhost without `SALESBOT_WEB_TOKEN`.
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
| OpenRouter | `openrouter` (auto-routes) or `openrouter:<vendor>/<model>` | `OPENROUTER_API_KEY` or **Sign in with OpenRouter** |
| Claude via Claude Code CLI | `claude_code` or `claude_code:<model>` | none: uses the signed-in `claude` CLI |

**No API key?** If `ANTHROPIC_API_KEY` is unset and the [Claude Code](https://code.claude.com) CLI is
installed and signed in, salesbot defaults to `claude_code`. Each turn runs `claude -p` with Claude
Code's own tools disabled; salesbot's tools are described in the prompt and called through a JSON
schema. It's slower than the API (a few seconds per turn), so for an always-on deployment prefer an
API key. The Docker image doesn't include the CLI.

The Manager, HR and Recruiter use `SALESBOT_DEFAULT_MODEL`. The Recruiter picks a model for each new
bot from the providers you have keys for. Claude requests use adaptive thinking and server-side
refusal fallbacks.

## Project layout

```
salesbot/
  agents/agent.py      one bot: system prompt + model + tools, runs the tool-calling loop
  agents/team.py       Manager, HR, Recruiter; hiring, delegation, approvals
  llm/                 provider-neutral gateway + Claude API / Claude Code CLI / OpenAI / xAI / Gemini
  tools/               web search & fetch, OpenClaw browsing, email, SMS, CRM
  store.py             SQLite persistence
  webapp.py, web/      web app (FastAPI + a single-page UI)
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
