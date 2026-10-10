"""Hello-trace: proves neatlogs receives our span kinds, attributes, a failing span and the LLM call.

The model call goes through the real provider adapter (`make_model_client`), so whichever SDK the configured
provider uses (anthropic, or openai for the event's LiteLLM proxy) is the one being auto-instrumented.
"""
from margin.config import Settings, load_dotenv

load_dotenv()

from margin import telemetry

telemetry.init_telemetry("margin", ["arm:hello", "version:v0"])  # must precede the first SDK import

from margin.model import build_request, make_model_client


@telemetry.span(kind="WORKFLOW", name="hello.run")
def run() -> str:
    settings = Settings.from_env()
    reply = ""
    with telemetry.trace("turn-0", kind="AGENT", **{"margin.turn": 0, "margin.model": settings.main_model}):
        client = make_model_client(settings)  # imports the SDK here, after neatlogs.init
        params = build_request(
            model=settings.main_model, effort="low", system="You answer in exactly one word.", tools=[],
            messages=[{"role": "user", "content": "Reply with the single word: pong"}], max_tokens=256,
        )
        params.pop("tools")  # an empty tool list is not a valid request on every provider
        msg = client.create(**params)
        reply = next((b.text for b in msg.content if b.type == "text"), "")
        with telemetry.trace("read_file", kind="TOOL", **{"margin.path": "README.md"}):
            pass
        with telemetry.trace(
            "governor", kind="GUARDRAIL", **{"margin.rung": "CONTINUE", "margin.spend_usd": 0.0001}
        ):
            pass
        try:
            with telemetry.trace("injected-failure", kind="TOOL"):
                raise RuntimeError("injected failure to check error rendering")
        except RuntimeError:
            pass
    return reply


if __name__ == "__main__":
    print(run())
    telemetry.shutdown_telemetry()
