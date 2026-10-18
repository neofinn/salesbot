from salesbot.commands import run_command
from salesbot.store import AgentSpec

WORKER_PROMPT = "You are LeadBot. Research companies and record them as leads in the CRM, then report back."


async def test_hire_then_delegate_end_to_end(team, fake):
    fake.script(
        "the Manager",
        ("", [("list_team", {})]),
        ("", [("hire_bot", {"job_description": "Find leads and store them in the CRM"})]),
        ("", [("delegate_task", {"bot_name": "leadbot", "task": "Add Acme Corp as a lead"})]),
        ("Hired leadbot and it added Acme Corp.", []),
    )
    fake.script(
        "the Recruiter",
        (
            "",
            [
                (
                    "submit_candidate",
                    {
                        "name": "leadbot",
                        "role": "Lead researcher",
                        "system_prompt": WORKER_PROMPT,
                        "model": "fake:test",
                        "tools": ["crm_add_lead", "web_search"],
                    },
                )
            ],
        ),
        ("Submitted leadbot.", []),
    )
    fake.script("the CTO", ("", [("tech_approve", {"notes": "fake:test fits"})]), ("Approved.", []))
    fake.script("HR for", ("", [("approve_hire", {"reason": "least privilege"})]), ("Approved.", []))
    fake.script(
        "LeadBot",
        ("", [("crm_add_lead", {"name": "Jane Doe", "company": "Acme Corp"})]),
        ("Added Acme Corp.", []),
    )

    reply = await team.handle("chat1", "Find me leads")

    assert reply == "Hired leadbot and it added Acme Corp."
    roster = await team.roster()
    assert [b.name for b in roster] == ["leadbot"]
    assert roster[0].tools == ["crm_add_lead", "web_search"]
    leads = await team.store.find_leads("Acme")
    assert leads[0]["name"] == "Jane Doe"
    # The worker only saw the tools it was hired with.
    worker_calls = [c for c in fake.calls if "LeadBot" in c[0]]
    assert worker_calls[0][2] == ["crm_add_lead", "web_search"]
    # Chat memory is kept for the next turn.
    assert await team.store.recent_chat("chat1") == [
        ("user", "Find me leads"),
        ("assistant", "Hired leadbot and it added Acme Corp."),
    ]


async def test_recruiter_gets_validation_errors_and_hr_can_reject(team, fake):
    fake.script(
        "the Recruiter",
        (
            "",
            [
                (
                    "submit_candidate",
                    {"name": "Bad Name", "role": "x", "system_prompt": "short", "model": "fake", "tools": ["rm_rf"]},
                )
            ],
        ),
        ("", [("submit_candidate", {"name": "spammer", "role": "Mass mailer", "system_prompt": WORKER_PROMPT, "model": "fake", "tools": ["send_email"]})]),
        ("done", []),
    )
    fake.script("the CTO", ("", [("tech_approve", {"notes": "ok"})]), ("Approved.", []))
    fake.script("HR for", ("", [("reject_hire", {"reason": "unsolicited bulk email"})]), ("Rejected.", []))

    result = await team.hire("Email everyone")

    assert result == "HR rejected spammer: unsolicited bulk email"
    assert await team.roster() == []
    # The first, invalid submission was bounced back to the recruiter as a tool error.
    second_call_messages = [c for c in fake.calls if "the Recruiter" in c[0]][1][1]
    error = second_call_messages[-1].tool_results[0]
    assert error.is_error and "unknown tools: rm_rf" in error.content and "name must be" in error.content


async def test_outbound_email_waits_for_approval(team, fake, monkeypatch):
    await team.store.add_agent(AgentSpec("mailer", "Sends follow-ups", WORKER_PROMPT.replace("LeadBot", "Mailer"), "fake", ["send_email"]))
    fake.script(
        "Mailer",
        ("", [("send_email", {"to": "jane@acme.test", "subject": "Hi", "body": "Hello Jane"})]),
        ("Queued.", []),
    )
    sent = []

    async def fake_deliver(settings, payload):
        sent.append(payload)
        return f"Email sent to {payload['to']}."

    monkeypatch.setitem(__import__("salesbot.tools.outbound", fromlist=["DELIVERERS"]).DELIVERERS, "email", fake_deliver)

    await team.delegate("mailer", "Follow up with Jane")
    assert sent == []
    pending = await run_command(team, "c", "/pending")
    assert "#1 email by mailer to jane@acme.test - Hi" in pending

    assert await run_command(team, "c", "/approve 1") == "Action #1: Email sent to jane@acme.test."
    assert sent == [{"to": "jane@acme.test", "subject": "Hi", "body": "Hello Jane"}]
    assert await run_command(team, "c", "/approve 1") == "No pending action #1."


async def test_commands(team):
    assert "Commands" in await run_command(team, "c", "/help")
    assert await run_command(team, "c", "hello") is None
    assert "No worker bots" in await run_command(team, "c", "/team@SalesBot")
    assert await run_command(team, "c", "/fire manager") == "manager is core staff and can't be fired."
    assert await run_command(team, "c", "/reject 9") == "No pending action #9."


async def test_unknown_tool_and_step_limit(team, fake):
    team.settings.max_agent_steps = 2
    await team.store.add_agent(AgentSpec("looper", "Loops", WORKER_PROMPT.replace("LeadBot", "Looper"), "fake", []))
    fake.script("Looper", ("", [("nope", {})]), ("", [("nope", {})]))
    assert await team.delegate("looper", "go") == "looper stopped after 2 steps without finishing."
    tool_msg = [c for c in fake.calls if "Looper" in c[0]][1][1][-1]
    assert tool_msg.tool_results[0].is_error


async def test_crm_export_csv(team, fake, settings):
    await team.store.add_lead(name="Jane", company="Acme", email="jane@acme.test")
    await team.store.add_agent(AgentSpec("exporter", "Exports", WORKER_PROMPT.replace("LeadBot", "Exporter"), "fake", ["crm_export_csv"]))
    fake.script("Exporter", ("", [("crm_export_csv", {})]), ("Exported.", []))
    await team.delegate("exporter", "export")
    result = [c for c in fake.calls if "Exporter" in c[0]][1][1][-1].tool_results[0]
    assert not result.is_error and "Exported 1 leads" in result.content
    path = result.content.split(" to ", 1)[1].rstrip(".")
    assert open(path).read().splitlines() == ["id,name,company,email,phone,status,notes", "1,Jane,Acme,jane@acme.test,,new,"]


async def test_provider_failure_gives_friendly_reply(team, fake):
    async def boom(*args, **kwargs):
        raise RuntimeError("401 invalid x-api-key")

    fake.complete = boom
    reply = await team.handle("c", "hi")
    assert reply.startswith("The Manager couldn't reach its AI model (fake:test): 401 invalid x-api-key")
