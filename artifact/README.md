# MyOps as a claude.ai artifact

`salesbot.html` is MyOps, your browser-only personal team of AI bots, published as a claude.ai artifact:
https://claude.ai/artifact/6YkVnFET8ApmLsBJfur2pV (a blank copy: https://claude.ai/artifact/9FShvQexbAAvCSA5kNQ3cU)

- The Manager, Recruiter, HR and every hired bot run on Claude through the artifact's `sample`
  capability, on the signed-in viewer's own Claude account. No server or API key needed.
- Every copy of the artifact has its own `db`, so a duplicate starts empty: it opens on a
  "Set up your team" form (name or business, about you, people you work with, goals, voice). The profile is
  saved at `config/profile` and every bot reads it. The Manager can then hire a starting team.
- Profiles: the menu next to the MyOps name switches between profiles (one per business or area
  of life) and adds new ones. Each profile has its own bots, tasks, contacts, drafts, chat,
  profile and Airtable table. The first profile ("main") uses the top-level collections; the
  others live under `spaces/<id>/`, and the list is the `spaces` collection. The open profile is
  remembered per viewer in localStorage.
- "Start fresh" (Team pane) erases the open profile's bots, tasks, contacts, drafts, chat and
  profile ("Delete profile" on any profile but the first also removes it from the menu). Rows
  already synced to Airtable stay in Airtable.
- Core staff: Manager, Recruiter, HR and CTO. The CTO checks every hire's tools against what is
  connected right now (Clay, Airtable, research reports), drops tools that would fail or rejects
  the hire, and answers the Manager's technical questions (`ask_cto` action).
- Long-term memory: chat turns older than the 12 the Manager sees are folded, in batches, into a
  summary at `config/memory`. The quick Claude tier writes it, and it falls back to an extract if
  that call fails. The summary goes into the Manager's prompt.
- Every delegation is logged on the Tasks board (`tasks`) with its status and report.
- Reports tab (`reports` per profile): research written by the MyOps research engine
  (`python -m salesbot.research scan --report-doc report.json`, then stored in the profile's
  `reports` collection). Bots with `research_read` work from the latest report's real numbers;
  the page cannot fetch market data itself.
- The Contacts tab is the team's contact book (leads, clients and other contacts).
- Clay (lead search, emails, web research) and Airtable (contact sync) come from the viewer's
  claude.ai connectors. A copy without an Airtable table can create one from the Contacts tab
  ("Create an Airtable contact table"), which saves its location at `config/airtable`.
- Bots cannot send. Drafted emails and texts wait in the out-tray; approve, copy and send them
  yourself.

Publish changes from Claude Code with the Artifact tool, using the same file path.
