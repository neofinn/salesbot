# Salesbot as a claude.ai artifact

`salesbot.html` is a browser-only, multi-agent operations team published as a claude.ai artifact:
https://claude.ai/artifact/6YkVnFET8ApmLsBJfur2pV (a blank copy: https://claude.ai/artifact/9FShvQexbAAvCSA5kNQ3cU)

- The Manager, Recruiter, HR and every hired bot run on Claude through the artifact's `sample`
  capability, on the signed-in viewer's own Claude account. No server or API key needed.
- Every copy of the artifact has its own `db`, so a duplicate starts empty: it opens on a
  "Set up your operation" form (company, what it does, customers, goals, voice). The profile is
  saved at `config/profile` and every bot reads it. The Manager can then hire a starting team.
- "Start a new operation" (Team pane) erases this copy's bots, tasks, leads, drafts, chat and
  profile. Rows already synced to Airtable stay in Airtable.
- Every delegation is logged on the Tasks board (`tasks`) with its status and report.
- Clay (lead search, emails, web research) and Airtable (lead sync) come from the viewer's
  claude.ai connectors. A copy without an Airtable table can create one from the Leads tab
  ("Create an Airtable lead table"), which saves its location at `config/airtable`.
- Bots cannot send. Drafted emails and texts wait in the out-tray; approve, copy and send them
  yourself.

Publish changes from Claude Code with the Artifact tool, using the same file path.
