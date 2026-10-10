import json

import pytest

from margin.bench.cfo import cfo_inputs, percentile, render_ari_prompt, render_inputs_table
from margin.cli import main
from margin.ledger import Ledger
from test_ledger import rec


def seeded(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    for n, cost in enumerate([1.0, 2.0, 3.0, 4.0]):
        ledger.append(rec(run_id=f"C{n}", task=f"e{n}", arm="C", cost=cost, price=5.0, solved=n != 3))
        ledger.append(rec(run_id=f"A{n}", task=f"e{n}", arm="A", cost=cost * 2, price=0.0, solved=True))
    return ledger


def test_percentile_is_nearest_rank():
    assert percentile([1, 2, 3, 4], 0.5) == 2
    assert percentile([1, 2, 3, 4], 0.9) == 4
    assert percentile([7], 0.9) == 7
    assert percentile([], 0.5) == 0.0


def test_inputs_for_arm_c(tmp_path):
    inputs = cfo_inputs(seeded(tmp_path), flat_price=6.0)
    c = inputs["C"]
    assert c["runs"] == 4
    assert c["solve_rate"] == pytest.approx(0.75)
    assert c["cost_per_job_p50"] == 2.0 and c["cost_per_job_p90"] == 4.0
    assert c["cost_per_verified_fix"] == pytest.approx(10.0 / 3)   # all spend, including the failed run
    assert c["avg_price"] == pytest.approx(5.0)
    assert c["revenue_per_job"] == pytest.approx(15.0 / 4)        # three verified jobs pay 5.0 each
    assert c["gross_margin"] == pytest.approx((15.0 - 10.0) / 15.0)


def test_flat_price_is_applied_to_arm_a(tmp_path):
    a = cfo_inputs(seeded(tmp_path), flat_price=6.0)["A"]
    assert a["avg_price"] == pytest.approx(6.0)
    assert a["revenue_per_job"] == pytest.approx(6.0)


def test_empty_ledger_yields_no_arms(tmp_path):
    assert cfo_inputs(Ledger(tmp_path / "none.jsonl"), 1.0) == {}


def test_rendered_outputs_contain_the_measured_numbers(tmp_path):
    inputs = cfo_inputs(seeded(tmp_path), flat_price=6.0)
    table = render_inputs_table(inputs)
    assert "| C |" in table and "$10.00" not in table and "$3.33" in table
    prompt = render_ari_prompt(inputs)
    for needle in ("$2.00", "$4.00", "75%", "pricing", "runway"):
        assert needle in prompt


def test_cfo_inputs_command_writes_the_three_files(tmp_path):
    ledger = seeded(tmp_path)
    flat = tmp_path / "flat.json"
    flat.write_text(json.dumps({"flat_price_usd": 6.0}))
    out = tmp_path / "business"
    args = ["cfo-inputs", "--ledger", str(ledger.path), "--flat", str(flat), "--out", str(out)]
    assert main(args) == 0
    assert json.loads((out / "inputs.json").read_text())["C"]["runs"] == 4
    assert "| C |" in (out / "inputs.md").read_text()
    assert "runway" in (out / "ari-prompt.md").read_text()


def test_cfo_inputs_without_data_says_what_is_missing(tmp_path, capsys):
    args = ["cfo-inputs", "--ledger", str(tmp_path / "none.jsonl"), "--flat", str(tmp_path / "none.json"),
            "--out", str(tmp_path / "out")]
    assert main(args) == 1
    assert "calibrate-flat" in capsys.readouterr().out
    flat = tmp_path / "flat.json"
    flat.write_text(json.dumps({"flat_price_usd": 6.0}))
    assert main(["cfo-inputs", "--ledger", str(tmp_path / "none.jsonl"), "--flat", str(flat), "--out", str(tmp_path / "o2")]) == 1
    assert "no evaluation runs" in capsys.readouterr().out
