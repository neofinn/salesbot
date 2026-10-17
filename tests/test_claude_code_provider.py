import json
import stat
import sys

import pytest

from salesbot.llm import LLMError, LLMGateway, Message, ToolCall, ToolResult, ToolSpec
from salesbot.llm.claude_code_provider import ClaudeCodeProvider
from salesbot.config import Settings

TOOLS = [ToolSpec("list_team", "List the team.", {"type": "object", "properties": {}})]


def fake_cli(tmp_path, payload: dict, exit_code: int = 0) -> str:
    """A stand-in `claude` executable that records its input and prints `payload`."""
    script = tmp_path / "claude"
    log = tmp_path / "calls.jsonl"
    script.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        f"open({str(log)!r}, 'a').write(json.dumps({{'argv': sys.argv[1:], 'stdin': sys.stdin.read()}}) + '\\n')\n"
        f"print({json.dumps(json.dumps(payload))})\n"
        f"sys.exit({exit_code})\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def calls(tmp_path) -> list[dict]:
    return [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()]


async def test_maps_structured_output_to_tool_calls(tmp_path):
    cli = fake_cli(tmp_path, {"is_error": False, "structured_output": {"text": "", "tool_calls": [{"name": "list_team", "arguments": {}}]}})
    history = [
        Message(role="user", text="who is here?"),
        Message(role="assistant", tool_calls=[ToolCall("c1", "list_team", {})]),
        Message(role="tool", tool_results=[ToolResult("c1", "list_team", "nobody", is_error=False)]),
    ]
    resp = await ClaudeCodeProvider(cli=cli).complete("default", "You are the Manager.", history, TOOLS)

    assert [c.name for c in resp.tool_calls] == ["list_team"]
    assert resp.stop_reason == "tool_use"
    call = calls(tmp_path)[0]
    argv = call["argv"]
    assert argv[argv.index("--tools") + 1] == ""
    assert "--model" not in argv
    system = argv[argv.index("--system-prompt") + 1]
    assert system.startswith("You are the Manager.") and "- list_team: List the team." in system
    assert '<tool_result id="c1" name="list_team" status="ok">\nnobody\n</tool_result>' in call["stdin"]


async def test_final_text_and_model_flag(tmp_path):
    cli = fake_cli(tmp_path, {"is_error": False, "structured_output": {"text": "All done.", "tool_calls": []}})
    resp = await ClaudeCodeProvider(cli=cli).complete("claude-sonnet-5-5", "sys", [Message(role="user", text="hi")], [])
    assert resp.text == "All done." and resp.tool_calls == []
    argv = calls(tmp_path)[0]["argv"]
    assert argv[argv.index("--model") + 1] == "claude-sonnet-5-5"
    assert argv[argv.index("--system-prompt") + 1] == "sys"


async def test_cli_errors_raise_llm_error(tmp_path):
    cli = fake_cli(tmp_path, {"is_error": True, "result": "Not logged in"}, exit_code=1)
    with pytest.raises(LLMError, match="Not logged in"):
        await ClaudeCodeProvider(cli=cli).complete("default", "sys", [Message(role="user", text="hi")], [])


def test_gateway_uses_cli_when_installed(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CLI", fake_cli(tmp_path, {}))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("SALESBOT_DEFAULT_MODEL", raising=False)
    settings = Settings.from_env()
    assert settings.default_model == "claude_code"
    gateway = LLMGateway(settings)
    assert gateway.configured() == ["claude_code"]
    assert gateway.resolve("claude_code") == ("claude_code", "default")
    assert isinstance(gateway.provider("claude_code"), ClaudeCodeProvider)


def test_response_schema_limits_tool_names():
    from salesbot.llm.claude_code_provider import response_schema

    assert response_schema(TOOLS)["properties"]["tool_calls"]["items"]["properties"]["name"]["enum"] == ["list_team"]
    assert response_schema([])["properties"]["tool_calls"]["maxItems"] == 0
