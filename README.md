# MyOps

Your personal team of AI bot employees, run from a chat. It handles your work and personal
operations: research, planning, writing and email drafts, follow-ups, lead generation, reporting
and admin. You tell the **Manager** what you want;
it delegates to bots on the team, and when nobody fits the job, the **Recruiter** designs a new
bot and **HR** reviews it before it's hired. Each bot can run on a different LLM (Claude, GPT,
Grok, Gemini, Groq, local Ollama models such as Qwen, or the API router) and is given only the tools its job needs: web search, OpenClaw browsing, email, SMS
and a built-in contact book (CRM).

The code lives in the `salesbot` Python package (the project's original name), so commands still
read `python -m salesbot ...`.

You talk to the team from a **web app**, over **Telegram**, or in a terminal chat, and it runs anywhere Docker runs.

```
 You (Telegram) ──► Manager ──► delegate_task ──► worker bots ──► tools (web, email, SMS, CRM)
                      │
                      ├──► hire_bot ──► Recruiter (designs bot) ──► CTO (model & tools) ──► HR (approve / reject) ──► roster
                      ├──► ask_cto ──► CTO (router status, free API hunt, model changes)
                      └──► ask_app_dev ──► Android / iOS developers (phone apps per business)
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
**Model for Manager, HR, Recruiter and CTO** empty to use whichever AI is connected.

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
| `/hire <job>` | Hire a bot for a job description (Recruiter + CTO + HR) |
| `/fire <name>` | Retire a bot |
| `/pending` | Emails and texts waiting for your approval |
| `/approve <id>` / `/reject <id>` | Send or discard a queued email/text |
| `/reset` | Clear the Manager's memory of this chat |

## API router and free API hunter

Set the staff model (or any bot's model) to `router` and MyOps sends each request through a
chain of models. When one is rate-limited, out of quota or failing, it is put on cooldown and
the next one answers. Free tiers can be stacked this way, with your paid accounts as the last
resort.

The **free API hunter** builds that chain for you. Run it with `python -m salesbot hunt` or
"Hunt free APIs" in Connections; it refreshes daily while the router is in use. It:

1. Lists free models from several sources:
   - OpenRouter's free models with tool support (a free OpenRouter key is needed to use them).
   - Gemini's free-tier Flash models.
   - Groq's free tier.
   - A local Ollama server (e.g. Qwen).
   - Your signed-in Claude Code CLI and any paid API keys.
2. Sends each one a tiny request that has to come back as a tool call, so it only keeps models
   that work with your keys and can drive the agents.
3. Orders them free first (`ROUTER_PREFER=free`) or your own accounts first (`quality`), and
   saves the chain to `data/router.json`.

Set `ROUTER_MODELS` to pin your own chain instead, e.g. `gemini:gemini-2.5-flash, groq, claude_code`.

## CTO and buffer memory

**The CTO** is core staff alongside the Manager, HR and the Recruiter, and owns the technology.

- **Tools:** `system_status` shows connected providers, the router chain with cooldowns, the last
  hunt and each bot's model. `run_api_hunt`, `test_model` and `set_bot_model` act on them.
- **Hiring:** every hire gets a CTO review between the Recruiter and HR. The CTO approves the
  candidate's model and tools, moves it to a better-suited model, or rejects a job the connected
  models can't do.
- **Advice:** the Manager asks the CTO technical questions with `ask_cto`.

**Buffer memory** keeps context when the API router switches models.

- **Fitting the conversation:** before every call, the conversation is fitted to the target
  model's context window (measured by the hunter, or a per-provider default). If it doesn't fit,
  the opening request and the newest messages stay verbatim and the middle is folded into a
  summary. A tool call is never separated from its result.
- **Long-term memory per chat:** turns older than the last 20 messages are folded, in batches,
  into a rolling summary by a memory keeper (`chat_memory` table). The summary goes into the
  Manager's prompt, so the thread survives provider switches, restarts and long chats. `/reset`
  clears it.

## Phone apps: Android and iOS developers

Two more core staff, **android_dev** and **ios_dev**, build and update the team's phone apps. Ask
the Manager, e.g. "Make an app for Lopez Bakery in orange", or use the Apps tab. Each business gets
its own app, with its own name, icon letter, colors and the MyOps server it opens (`server_url`).
A business that needs a fully separate team and data runs its own MyOps server and gets an app
pointing there.

- **Instant install, no store:** every app is live at `https://<server>/app/<slug>`.
  - It is a web app with its own manifest, icons and service worker.
  - Android: open it in Chrome and tap Install app.
  - iPhone: open it in Safari, then Share > Add to Home Screen.
- **Native Android and iOS:** "Native project" in the Apps tab downloads a Capacitor project.
  1. Unzip it into `apps/<slug>/` in this repo.
  2. The **Mobile apps** workflow (`.github/workflows/mobile.yml`) builds an installable Android APK
     on every push, and an iOS simulator build on demand.
  3. App store releases need your Google Play ($25 once) or Apple Developer ($99/year) account
     to sign them.
- **Updates:** both kinds of app load the team from the server, so changes reach phones at once.
  Rebuild a native app only when its name, icon or bundle id change; each save bumps its version.

Set `SALESBOT_PUBLIC_URL` (the https address phones use to reach the server) for app links and
native projects.

## OpenClaw browser agent (optional)

[OpenClaw](https://docs.openclaw.ai) (formerly Clawdbot) is a self-hosted agent with a real
browser. MyOps can hand it research while the Manager, HR and your approval queue stay in
charge:

- **Python app:** enable the Gateway's OpenAI-compatible endpoint
  (`gateway.http.endpoints.chatCompletions.enabled: true`), then set the OpenClaw Gateway URL and
  token in Connections (or `OPENCLAW_URL` / `OPENCLAW_TOKEN`). The Manager can then call
  `openclaw_browse` itself, and the Recruiter can give it to hired bots. The task brief tells
  OpenClaw to research only: no logins, purchases, posts or messages.
- **claude.ai artifact:** the page can't reach a Gateway on your machine, so the two share the
  Airtable contact table instead. Copy `integrations/openclaw/myops-contacts/` into your OpenClaw
  skills folder and set `AIRTABLE_TOKEN` and `MYOPS_AIRTABLE_BASE`. OpenClaw adds the contacts it
  finds there, and "Import from Airtable" on the Contacts tab brings them into the team.

OpenClaw runs with your computer's permissions. Keep its Gateway on localhost or a private
network, install skills only from sources you trust, and keep sending behind approval.

## Stock research

`salesbot/research/` is a research engine for a stock-analysis team. It uses real data and needs
no API keys:

- **Prices:** daily bars from Yahoo Finance's chart API.
- **Financials:** latest-quarter revenue, EPS and margins from the companies' own SEC EDGAR XBRL
  filings.
- **Technical analysis:**
  - Stage-2 trend template: price above the 50, 150 and 200-day averages, with the 200-day rising.
  - 52-week range, the 20-day base and its pivot, and base tightness.
  - RSI, ATR, volume dry-up, and 6-month strength vs SPY.
  - A breakout score and a stop idea.
- **Fundamental analysis:** revenue and EPS growth year over year, revenue acceleration, margins,
  and a stale-data guard.

```bash
python -m salesbot.research analyze NVDA                 # one stock, as JSON
python -m salesbot.research scan --top 500 --limit 12    # stocks near a breakout among the 500 largest
python -m salesbot.research scan --tickers AAPL,MSFT --report-doc report.json
```

Bots in the Python app can be given `stock_analyze` and `stock_screen`. In the claude.ai
artifact, a scan saved with `--report-doc` goes into a profile's `reports` collection. It shows on
the Reports tab, and bots with the `research_read` permission analyse its numbers. The page
itself cannot fetch market data. SEC asks automated clients to identify themselves, so set
`SEC_USER_AGENT` to "your-app your-email". Everything here is research, not financial advice.

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
Code's own tools disabled; MyOps's tools are described in the prompt and called through a JSON
schema. It's slower than the API (a few seconds per turn), so for an always-on deployment prefer an
API key. The Docker image doesn't include the CLI.

The Manager, HR, Recruiter and CTO use `SALESBOT_DEFAULT_MODEL`. The Recruiter picks a model for each new
bot from the providers you have keys for. Claude requests use adaptive thinking and server-side
refusal fallbacks.

## Project layout

```
salesbot/
  agents/agent.py      one bot: system prompt + model + tools, runs the tool-calling loop
  agents/team.py       Manager, HR, Recruiter, CTO, Android/iOS devs; hiring, delegation, approvals, chat memory
  apps/                phone apps: icons, installable web app, Capacitor native projects
  llm/                 provider-neutral gateway + Claude API / Claude Code CLI / OpenAI / xAI / Gemini
  tools/               web search & fetch, OpenClaw browsing, stock research, email, SMS, CRM
  research/            stock research engine (prices, SEC financials, technicals, breakout scan)
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
