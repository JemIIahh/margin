from margin.errors import TransientModelError
from margin.model import build_request, is_transient


def test_request_shape_avoids_parameters_the_models_reject():
    params = build_request(
        model="claude-sonnet-5-5", effort="medium", system="SYS", tools=[{"name": "t"}],
        messages=[{"role": "user", "content": "hi"}], max_tokens=16000,
    )
    for forbidden in ("temperature", "top_p", "top_k", "thinking", "tool_choice"):
        assert forbidden not in params
    assert params["output_config"] == {"effort": "medium"}
    assert params["cache_control"] == {"type": "ephemeral"}
    assert params["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert params["system"][0]["text"] == "SYS"


def test_transient_classification():
    assert is_transient(TransientModelError("overloaded"))
    assert not is_transient(ValueError("bad"))
