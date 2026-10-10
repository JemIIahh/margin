import json

import pytest

from fakes import FakeExecutor
from margin.agent.loop import run_agent
from margin.config import ROOT, Settings
from margin.governor import NullGovernor
from margin.model import build_request, is_transient, make_model_client
from margin.model_openai import (
    CACHE,
    OpenAICompatModel,
    TextBlock,
    ToolUseBlock,
    from_openai_response,
    make_litellm_client,
    to_openai_messages,
    to_openai_request,
    to_openai_tools,
)
from margin.pricing import PriceTable, SpendMeter, Usage
from margin.state import RunState

TOOLS = [{"name": "read_file", "description": "Read a file.", "input_schema": {
    "type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False}}]


def test_tools_become_openai_functions():
    assert to_openai_tools(TOOLS) == [
        {"type": "function", "function": {"name": "read_file", "description": "Read a file.",
                                          "parameters": TOOLS[0]["input_schema"]}}
    ]


def test_system_blocks_become_one_system_message_and_keep_the_cache_marker():
    system = [{"type": "text", "text": "Rules.", "cache_control": CACHE}]
    out = to_openai_messages(system, [{"role": "user", "content": "hi"}], cache_last=False)
    assert out[0] == {"role": "system", "content": [{"type": "text", "text": "Rules.", "cache_control": CACHE}]}
    assert out[1] == {"role": "user", "content": "hi"}
    plain = to_openai_messages("Rules.", [], cache_last=False)
    assert plain == [{"role": "system", "content": [{"type": "text", "text": "Rules."}]}]


def test_assistant_text_and_tool_use_become_content_and_tool_calls():
    history = [{"role": "assistant", "content": [
        {"type": "text", "text": "Looking."},
        {"type": "tool_use", "id": "t1", "name": "read_file", "input": {"path": "a.py"}},
    ]}]
    (msg,) = to_openai_messages(None, history, cache_last=False)
    assert msg["content"] == "Looking."
    assert msg["tool_calls"] == [{"id": "t1", "type": "function",
                                  "function": {"name": "read_file", "arguments": '{"path": "a.py"}'}}]


def test_an_assistant_turn_with_only_a_tool_call_has_no_text():
    history = [{"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "x", "input": {}}]}]
    (msg,) = to_openai_messages(None, history, cache_last=False)
    assert msg["content"] is None and msg["tool_calls"][0]["id"] == "t1"


def test_tool_results_become_tool_messages_before_any_text_and_errors_are_marked():
    history = [{"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": "file body"},
        {"type": "tool_result", "tool_use_id": "t2", "content": "boom", "is_error": True},
        {"type": "text", "text": "Budget notice: wrap up."},
    ]}]
    out = to_openai_messages(None, history, cache_last=False)
    assert out == [
        {"role": "tool", "tool_call_id": "t1", "content": "file body"},
        {"role": "tool", "tool_call_id": "t2", "content": "ERROR: boom"},
        {"role": "user", "content": "Budget notice: wrap up."},
    ]


def test_tool_result_content_given_as_blocks_is_flattened():
    history = [{"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}]}]
    assert to_openai_messages(None, history, cache_last=False)[0]["content"] == "ab"


def test_the_moving_cache_breakpoint_goes_on_the_last_user_or_tool_message_only():
    tool_last = [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "body"}]}]
    out = to_openai_messages(None, tool_last, cache_last=True)
    assert out[-1]["content"] == [{"type": "text", "text": "body", "cache_control": CACHE}]
    assistant_last = [{"role": "assistant", "content": [{"type": "text", "text": "done"}]}]
    assert to_openai_messages(None, assistant_last, cache_last=True)[-1]["content"] == "done"
    empty = [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": ""}]}]
    assert to_openai_messages(None, empty, cache_last=True)[-1]["content"] == ""


def params(model="claude-haiku", **over):
    base = build_request(model=model, effort="low", system="Rules.", tools=TOOLS,
                         messages=[{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "x"}]}],
                         max_tokens=16000)
    return {**base, **over}


def test_request_drops_anthropic_only_fields_and_keeps_tools():
    body = to_openai_request(params())
    assert set(body) == {"model", "messages", "max_tokens", "tools"}
    assert body["tools"][0]["function"]["name"] == "read_file"
    assert body["messages"][0]["role"] == "system" and body["messages"][0]["content"][0]["cache_control"] == CACHE


def test_nova_gets_its_output_cap_and_no_moving_breakpoint():
    nova = to_openai_request(params("nova-lite"))
    assert nova["max_tokens"] == 10_000
    assert nova["messages"][-1]["content"] == "x"                    # Nova rejects a breakpoint inside a tool result
    assert nova["messages"][0]["content"][0]["cache_control"] == CACHE  # the system breakpoint is accepted
    claude = to_openai_request(params("claude-haiku"))
    assert claude["max_tokens"] == 16000
    assert claude["messages"][-1]["content"][0]["cache_control"] == CACHE


def test_a_request_without_tools_has_no_tools_key():
    assert "tools" not in to_openai_request(params(tools=[]))


def reply(content=None, tool_calls=None, finish="stop", usage=None):
    return {"model": "claude-haiku", "choices": [{"finish_reason": finish, "message": {
        "role": "assistant", "content": content, "tool_calls": tool_calls}}], "usage": usage or {}}


def call(id_="c1", name="read_file", arguments='{"path": "a.py"}'):
    return {"id": id_, "type": "function", "function": {"name": name, "arguments": arguments}}


def test_text_reply_ends_the_turn():
    r = from_openai_response(reply("done"))
    assert r.stop_reason == "end_turn" and [b.to_dict() for b in r.content] == [{"type": "text", "text": "done"}]


def test_tool_call_reply_becomes_tool_use_blocks_in_order():
    r = from_openai_response(reply("Reading.", [call(), call("c2", "git_diff", "{}")], finish="tool_calls"))
    assert r.stop_reason == "tool_use"
    assert [type(b) for b in r.content] == [TextBlock, ToolUseBlock, ToolUseBlock]
    assert r.content[1].to_dict() == {"type": "tool_use", "id": "c1", "name": "read_file", "input": {"path": "a.py"}}
    assert r.content[2].input == {}


def test_malformed_arguments_become_an_empty_input_so_the_tool_can_explain_what_is_missing():
    r = from_openai_response(reply(None, [call(arguments="{not json")], finish="tool_calls"))
    assert r.stop_reason == "tool_use" and r.content[0].input == {}


def test_a_tool_call_cut_off_by_the_token_limit_is_dropped_and_reported_as_max_tokens():
    r = from_openai_response(reply("I will", [call(arguments='{"path": "a.')], finish="length"))
    assert r.stop_reason == "max_tokens"
    assert [b.type for b in r.content] == ["text"]


@pytest.mark.parametrize("finish, stop", [("stop", "end_turn"), ("length", "max_tokens"),
                                          ("content_filter", "refusal"), ("something_new", "end_turn")])
def test_finish_reasons_map_to_stop_reasons(finish, stop):
    assert from_openai_response(reply("x", finish=finish)).stop_reason == stop


def test_usage_separates_cached_tokens_from_fresh_input():
    usage = {"prompt_tokens": 9140, "completion_tokens": 4, "cache_read_input_tokens": 9127,
             "cache_creation_input_tokens": 0}
    u = from_openai_response(reply("x", usage=usage)).usage
    assert (u.input_tokens, u.output_tokens, u.cache_read_input_tokens, u.cache_creation_input_tokens) == (13, 4, 9127, 0)
    written = from_openai_response(reply("x", usage={"prompt_tokens": 9140, "completion_tokens": 4,
                                                    "prompt_tokens_details": {"cache_creation_tokens": 9127}})).usage
    assert (written.input_tokens, written.cache_creation_input_tokens) == (13, 9127)
    assert from_openai_response(reply("x")).usage.input_tokens == 0


# --- prices: the proxy's own per-call cost headers are the ground truth -----------------------------------------
PRICES = PriceTable.load(ROOT / "pricing.toml")


def test_prices_reproduce_the_proxys_own_costs_for_calls_measured_on_2026_10_10():
    # claude-haiku, 9,127 tokens written to the cache: the proxy billed $0.01259; then read back: $0.00104
    written = Usage(input_tokens=13, output_tokens=4, cache_write_tokens=9127)
    read = Usage(input_tokens=13, output_tokens=4, cache_read_tokens=9127)
    assert PRICES.cost("claude-haiku", written) == pytest.approx(0.01259, abs=1e-5)
    assert PRICES.cost("claude-haiku", read) == pytest.approx(0.00104, abs=1e-5)
    # nova-lite, 9,975 tokens read from cache and 20 generated: $0.00015
    nova = Usage(input_tokens=8, output_tokens=20, cache_read_tokens=9975)
    assert PRICES.cost("nova-lite", nova) == pytest.approx(0.00015, abs=1e-5)


# --- the client over the real openai SDK, with no network --------------------------------------------------------
def make_client(handler, **kwargs):
    httpx2 = pytest.importorskip("httpx2")
    openai = pytest.importorskip("openai")
    http = httpx2.Client(transport=httpx2.MockTransport(handler))
    return OpenAICompatModel(
        openai.OpenAI(api_key="test-key", base_url="https://proxy.test/v1", http_client=http, max_retries=0), **kwargs
    )


def test_create_sends_a_chat_request_and_returns_an_anthropic_shaped_reply():
    httpx2 = pytest.importorskip("httpx2")
    seen = {}

    def handler(request):
        seen.update(path=request.url.path, auth=request.headers["authorization"], body=json.loads(request.content))
        data = reply("Reading.", [call()], finish="tool_calls",
                     usage={"prompt_tokens": 100, "completion_tokens": 10})
        return httpx2.Response(200, json=data, headers={"x-litellm-response-cost": "0.0007"})

    client = make_client(handler)
    response = client.create(**params())
    assert seen["path"] == "/v1/chat/completions" and seen["auth"] == "Bearer test-key"
    assert seen["body"]["model"] == "claude-haiku" and seen["body"]["tools"][0]["function"]["name"] == "read_file"
    assert response.stop_reason == "tool_use" and response.content[1].name == "read_file"
    assert (response.usage.input_tokens, response.usage.output_tokens) == (100, 10)
    assert response.proxy_cost_usd == pytest.approx(0.0007) and client.proxy_cost_usd == pytest.approx(0.0007)
    client.create(**params())
    assert client.proxy_cost_usd == pytest.approx(0.0014)


def test_errors_surface_as_sdk_errors_that_the_loop_retries():
    httpx2 = pytest.importorskip("httpx2")
    openai = pytest.importorskip("openai")

    def limited(request):
        return httpx2.Response(429, json={"error": {"message": "rate limited"}})

    def broken(request):
        return httpx2.Response(500, json={"error": {"message": "boom"}})

    def bad(request):
        return httpx2.Response(400, json={"error": {"message": "malformed"}})

    with pytest.raises(openai.RateLimitError) as limit:
        make_client(limited).create(**params())
    assert is_transient(limit.value)
    with pytest.raises(openai.InternalServerError) as server:
        make_client(broken).create(**params())
    assert is_transient(server.value)
    with pytest.raises(openai.BadRequestError) as client_error:
        make_client(bad).create(**params())
    assert not is_transient(client_error.value)


def test_the_agent_loop_runs_a_tool_turn_through_the_adapter(tmp_path):
    httpx2 = pytest.importorskip("httpx2")
    replies = [
        reply("Reading.", [call()], finish="tool_calls", usage={"prompt_tokens": 800, "completion_tokens": 30}),
        reply("Fixed.", finish="stop", usage={"prompt_tokens": 900, "completion_tokens": 10,
                                              "cache_read_input_tokens": 700}),
    ]
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx2.Response(200, json=replies[len(bodies) - 1])

    executor = FakeExecutor({"read_file": "def add(a, b): ..."})
    meter = SpendMeter(PRICES)
    result = run_agent(
        first_prompt="Fix it.", arm="A", client=make_client(handler), meter=meter, governor=NullGovernor(),
        executor=executor, state=RunState(tmp_path / "run"), prices=PRICES,
        settings=Settings(main_model="claude-haiku", fallback_model="nova-lite"), sleep=lambda s: None,
    )
    assert result.stop == "end_turn" and result.final_text == "Fixed."
    assert executor.calls == [("read_file", {"path": "a.py"})]
    second = bodies[1]["messages"]
    assert [m["role"] for m in second] == ["system", "user", "assistant", "tool"]  # the history round-trips
    assert second[2]["tool_calls"][0]["id"] == "c1" and second[3]["tool_call_id"] == "c1"
    assert meter.total_usd == pytest.approx(
        PRICES.cost("claude-haiku", Usage(800, 30)) + PRICES.cost("claude-haiku", Usage(200, 10, 0, 700))
    )
    assert result.messages[1]["content"][1] == {"type": "tool_use", "id": "c1", "name": "read_file", "input": {"path": "a.py"}}


# --- client factory and settings ---------------------------------------------------------------------------------
def test_make_model_client_chooses_the_provider(monkeypatch):
    pytest.importorskip("openai")
    monkeypatch.setenv("LITELLM_API_KEY", "test-key")
    monkeypatch.setenv("LITELLM_BASE_URL", "https://proxy.test/v1")
    assert isinstance(make_model_client(Settings(provider="litellm")), OpenAICompatModel)
    with pytest.raises(ValueError, match="unknown provider"):
        make_model_client(Settings(provider="bogus"))


def test_the_litellm_client_needs_its_key_and_url(monkeypatch):
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="LITELLM_API_KEY"):
        make_litellm_client()


def test_provider_setting_defaults_to_anthropic_and_reads_the_environment():
    assert Settings().provider == "anthropic"
    assert Settings.from_env({"MARGIN_PROVIDER": "litellm", "MARGIN_MAIN_MODEL": "claude-haiku"}).provider == "litellm"


def test_telemetry_instruments_the_sdk_in_use(monkeypatch):
    import sys
    from types import SimpleNamespace

    from margin import telemetry

    seen = []
    monkeypatch.setitem(sys.modules, "neatlogs", SimpleNamespace(init=lambda **kw: seen.append(kw["instrumentations"])))
    monkeypatch.setattr(telemetry, "_enabled", False)
    monkeypatch.setenv("NEATLOGS_API_KEY", "k")
    monkeypatch.delenv("MARGIN_PROVIDER", raising=False)
    telemetry.init_telemetry("margin", [])
    monkeypatch.setenv("MARGIN_PROVIDER", "litellm")
    telemetry.init_telemetry("margin", [])
    assert seen == [["anthropic"], ["openai"]]


def test_create_returns_a_parsed_completion_so_neatlogs_can_read_token_usage(monkeypatch):
    """neatlogs' openai instrumentation wraps Completions.create and reads `.usage` on what it returns. A raw
    response (with_raw_response) has no `.usage`, which left every LLM span with 0 tokens in the live dashboard."""
    openai_completions = pytest.importorskip("openai.resources.chat.completions")
    httpx2 = pytest.importorskip("httpx2")
    seen = []
    original = openai_completions.Completions.create

    def spy(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        seen.append(getattr(getattr(result, "usage", None), "prompt_tokens", None))
        return result

    monkeypatch.setattr(openai_completions.Completions, "create", spy)   # before the client is built, as instrumentation does

    def handler(request):
        data = reply("ok", usage={"prompt_tokens": 100, "completion_tokens": 10})
        return httpx2.Response(200, json=data, headers={"x-litellm-response-cost": "0.0007"})

    client = make_client(handler)
    out = client.create(**params())
    assert seen == [100]                                   # the instrumented call returned something with usage
    assert out.proxy_cost_usd == pytest.approx(0.0007)     # and the proxy's own cost is still captured, via a hook


def test_a_reply_without_a_cost_header_has_no_proxy_cost_and_does_not_reuse_the_last_one():
    httpx2 = pytest.importorskip("httpx2")
    calls = []

    def handler(request):
        calls.append(1)
        headers = {"x-litellm-response-cost": "0.5"} if len(calls) == 1 else {}
        return httpx2.Response(200, json=reply("ok", usage={"prompt_tokens": 1, "completion_tokens": 1}), headers=headers)

    client = make_client(handler)
    assert client.create(**params()).proxy_cost_usd == pytest.approx(0.5)
    assert client.create(**params()).proxy_cost_usd is None
    assert client.proxy_cost_usd == pytest.approx(0.5)
