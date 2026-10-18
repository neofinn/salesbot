from salesbot.llm import Message, ToolCall, ToolResult
from salesbot.llm.memory import fit, message_tokens
from salesbot.store import AgentSpec

WORKER = "You are Writer. Write short summaries of whatever the Manager sends you, clearly and briefly."


def long_run(n=30):
    msgs = [Message(role="user", text="Research ACME and report.")]
    for i in range(n):
        msgs.append(Message(role="assistant", text=f"step {i}", tool_calls=[ToolCall(id=f"t{i}", name="web_fetch", arguments={"url": f"https://x/{i}"})]))
        msgs.append(Message(role="tool", tool_results=[ToolResult(f"t{i}", "web_fetch", "page text " * 200)]))
    msgs.append(Message(role="assistant", text="Nearly done."))
    return msgs


def test_fit_keeps_request_and_tail_and_pairs():
    msgs = long_run()
    out = fit(msgs, budget=6000)
    assert sum(message_tokens(m) for m in out) <= 6000
    assert out[0].role == "user" and out[0].text.startswith("Research ACME") and "Buffer memory" in out[0].text
    assert "web_fetch" in out[0].text  # folded steps are summarized, not dropped
    assert out[-1].text == "Nearly done."
    assert out[1].role == "assistant"  # never starts with an orphaned tool result
    for i, m in enumerate(out):
        if m.role == "tool":
            assert out[i - 1].tool_calls and out[i - 1].tool_calls[0].id == m.tool_results[0].call_id
    assert fit(msgs[:3], budget=10) == msgs[:3]  # too short to fold
    small = long_run(2)
    assert fit(small, budget=1_000_000) == small  # already fits


def test_fit_history_starting_with_assistant():
    msgs = [Message(role="assistant", text="old reply " * 400)] + long_run(10)
    out = fit(msgs, budget=3000)
    assert out[0].role == "user" and "Buffer memory" in out[0].text


async def test_gateway_condenses_for_small_models(team, fake):
    team.settings.data_dir = team.settings.data_dir  # default context for unknown provider: 32k tokens
    fake.script("Small", ("ok", []))
    big = long_run(80)
    await team.gateway.complete("fake:test", "Small model", big, [])
    sent = fake.calls[-1][1]
    assert len(sent) < len(big) and "Buffer memory" in sent[0].text


async def test_hire_cto_can_move_model_or_reject(team, fake):
    def recruit(name):
        fake.script("the Recruiter", ("", [("submit_candidate", {"name": name, "role": "Writer", "system_prompt": WORKER, "model": "fake:big", "tools": []})]), ("done", []))

    recruit("writer")
    fake.script("the CTO", ("", [("tech_approve", {"model": "fake:small", "notes": "routine work, cheaper model"})]), ("ok", []))
    fake.script("HR for", ("", [("approve_hire", {"reason": "fine"})]), ("ok", []))
    result = await team.hire("Write summaries")
    assert "on fake:small" in result and (await team.store.get_agent("writer")).model == "fake:small"

    recruit("painter")
    fake.script("the CTO", ("", [("tech_reject", {"reason": "needs an image model we don't have"})]), ("ok", []))
    assert await team.hire("Paint pictures") == "The CTO rejected painter: needs an image model we don't have"
    assert await team.store.get_agent("painter") is None


async def test_manager_asks_cto_who_changes_a_bot_model(team, fake):
    await team.store.add_agent(AgentSpec("writer", "Writer", WORKER, "fake:big", []))
    fake.script("the Manager", ("", [("ask_cto", {"question": "Move writer to a cheaper model"})]), ("The CTO moved writer.", []))
    fake.script("the CTO", ("", [("system_status", {}), ("set_bot_model", {"bot_name": "writer", "model": "fake:small"})]), ("Moved writer to fake:small.", []))
    reply = await team.handle("c1", "Make the writer cheaper")
    assert reply == "The CTO moved writer."
    assert (await team.store.get_agent("writer")).model == "fake:small"
    status = [c for c in fake.calls if "You are the CTO" in c[0]][-1][1][-1].tool_results[0].content
    assert '"default_model": "fake:test"' in status and '"writer"' in status


async def test_cto_tool_validation(team, fake):
    fake.script("the CTO", ("", [("set_bot_model", {"bot_name": "ghost", "model": "fake"}), ("set_bot_model", {"bot_name": "x", "model": "nope:1"})]), ("done", []))
    await team.cto().run("try")
    results = [c for c in fake.calls if "You are the CTO" in c[0]][-1][1][-1].tool_results
    assert results[0].is_error and "No active bot" in results[0].content
    assert results[1].is_error and "Unknown LLM provider" in results[1].content
    assert await team.fire("cto") == "cto is core staff and can't be fired."


async def test_long_chat_folds_into_memory(team, fake):
    from salesbot.agents import team as team_mod

    for i in range(team_mod.RECENT_MESSAGES // 2 + team_mod.MEMORY_BATCH // 2):
        fake.script("the Manager", (f"answer {i}", []))
    fake.script("memory keeper", ("- Owner prefers short answers\n- Asked about topics 0-2", []))
    for i in range(team_mod.RECENT_MESSAGES // 2 + team_mod.MEMORY_BATCH // 2):
        await team.handle("chat", f"question {i}")
    memory, upto = await team.store.get_memory("chat")
    assert memory.startswith("- Owner prefers short answers") and upto > 0
    # The next turn sees the memory in the Manager's prompt plus the recent window as messages.
    fake.script("the Manager", ("ok", []))
    await team.handle("chat", "next")
    system, messages, _ = [c for c in fake.calls if "the Manager" in c[0]][-1]
    assert "Long-term memory of this chat" in system and "Owner prefers short answers" in system
    assert len(messages) == team_mod.RECENT_MESSAGES + 1
    # /reset clears both.
    from salesbot.commands import run_command

    await run_command(team, "chat", "/reset")
    assert await team.store.get_memory("chat") == ("", 0)


async def test_memory_falls_back_when_summary_fails(team, fake):
    from salesbot.agents import team as team_mod

    n = team_mod.RECENT_MESSAGES // 2 + team_mod.MEMORY_BATCH // 2
    for i in range(n):
        fake.script("the Manager", (f"answer {i}", []))
    for i in range(n):
        await team.handle("chat2", f"question {i}")  # no memory keeper scripted: the fake raises
    memory, upto = await team.store.get_memory("chat2")
    assert "Owner: question 0" in memory and upto > 0
