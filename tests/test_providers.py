import pytest

from salesbot.config import Settings
from salesbot.llm import LLMError, LLMGateway, Message, ToolCall, ToolResult
from salesbot.llm.anthropic_provider import AnthropicProvider
from salesbot.llm.gemini_provider import GeminiProvider
from salesbot.llm.openai_provider import OpenAICompatibleProvider
from salesbot.telegram_bot import split_message
from salesbot.tools import ToolError
from salesbot.tools.web import _check_public_url

HISTORY = [
    Message(role="user", text="find acme"),
    Message(role="assistant", text="searching", tool_calls=[ToolCall("t1", "web_search", {"query": "acme"})]),
    Message(role="tool", tool_results=[ToolResult("t1", "web_search", "acme.com", is_error=False)]),
]


def test_gateway_resolve():
    gw = LLMGateway(Settings(xai_model="grok-x"))
    assert gw.resolve("anthropic:claude-opus-5-5") == ("anthropic", "claude-opus-5-5")
    assert gw.resolve("xai") == ("xai", "grok-x")
    with pytest.raises(LLMError):
        gw.resolve("nope:model")
    with pytest.raises(LLMError, match="OPENAI_API_KEY"):
        gw.provider("openai")
    assert gw.available() == ["anthropic"]
    assert LLMGateway(Settings(default_model="xai:grok", gemini_api_key="k")).available() == ["gemini", "xai"]


def test_anthropic_wire_format():
    wire = AnthropicProvider(api_key="test")._to_wire(HISTORY)
    assert wire[1] == {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "searching"},
            {"type": "tool_use", "id": "t1", "name": "web_search", "input": {"query": "acme"}},
        ],
    }
    assert wire[2]["role"] == "user"
    assert wire[2]["content"][0] == {"type": "tool_result", "tool_use_id": "t1", "content": "acme.com", "is_error": False}

    raw = [object()]
    replay = AnthropicProvider(api_key="test")._to_wire([Message(role="assistant", raw=raw, raw_provider="anthropic")])
    assert replay[0]["content"] is raw


def test_openai_wire_format():
    wire = OpenAICompatibleProvider._to_wire("sys", HISTORY)
    assert wire[0] == {"role": "system", "content": "sys"}
    assert wire[2]["tool_calls"][0]["function"] == {"name": "web_search", "arguments": '{"query": "acme"}'}
    assert wire[3] == {"role": "tool", "tool_call_id": "t1", "content": "acme.com"}


def test_gemini_wire_format():
    wire = GeminiProvider(api_key="test")._to_wire(HISTORY)
    assert [c.role for c in wire] == ["user", "model", "user"]
    assert wire[1].parts[1].function_call.name == "web_search"
    assert wire[2].parts[0].function_response.response == {"result": "acme.com"}


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://169.254.169.254/latest", "file:///etc/passwd"])
async def test_web_fetch_blocks_internal_urls(url):
    with pytest.raises(ToolError):
        await _check_public_url(url)


def test_split_message():
    chunks = split_message("a" * 10 + "\n" + "b" * 10, limit=12)
    assert chunks == ["a" * 10, "b" * 10]
    assert split_message("x" * 25, limit=10) == ["x" * 10, "x" * 10, "x" * 5]
