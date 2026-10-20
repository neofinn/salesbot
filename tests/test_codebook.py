from salesbot import codebook
from salesbot.store import AgentSpec
from salesbot.tools import CATALOG


def test_chapters_load_and_detect():
    names = codebook.chapters()
    assert {"method", "python", "javascript", "typescript", "html-css", "sql", "bash"} <= set(names)
    assert all(codebook.chapter(n).startswith("# ") for n in names)
    assert codebook.detect("Build a landing page website with a contact form") == ["javascript", "html-css"]
    assert codebook.detect("write a python script to clean the sqlite database") == ["python", "sql", "bash"]
    assert codebook.is_coding("fix the bug in my API") and not codebook.is_coding("plan my week")


def test_for_task_respects_budget():
    text = codebook.for_task("python and sql and bash and html", max_chars=5000)
    assert text.startswith("Code book") and "# Method" in text and len(text) < 5200
    assert "# Python" in text


async def test_coding_bot_gets_codebook(team, fake):
    await team.store.add_agent(AgentSpec("coder", "Writes Python scripts", "You write code.", "fake:test", []))
    fake.script("You write code.", ("", [("code_reference", {"language": "python"})]), ("done", []))
    assert await team.delegate("coder", "Write a python script that sums a CSV column") == "done"
    system = [c for c in fake.calls if "You write code." in c[0]][-1][0]
    assert "# Method" in system and "# Python" in system
    result = [c for c in fake.calls if "You write code." in c[0]][-1][1][-1].tool_results[0]
    assert not result.is_error and "## Pitfalls" in result.content
    assert "code_reference" in CATALOG


async def test_non_coding_bot_does_not(team, fake):
    await team.store.add_agent(AgentSpec("planner", "Plans the week", "You plan.", "fake:test", []))
    fake.script("You plan.", ("ok", []))
    await team.delegate("planner", "Plan my week around my goals")
    assert "# Method" not in [c for c in fake.calls if "You plan." in c[0]][-1][0]
