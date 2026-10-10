import json

from margin.bench.report import quote_coverage, render_receipts_page, render_results
from margin.cli import main
from margin.ledger import Ledger
from margin.quote import Features
from test_ledger import rec

FLAT = {"flat_price_usd": 3.0, "mean_cost_usd": 2.0, "n": 2, "markup": 0.5}


def write_manifest(tmp_path) -> str:
    """The task manifest the report checks the ledger against: two calibration and two evaluation tasks."""
    entry = (
        '[[task]]\nid = "{id}"\nsplit = "{split}"\nrepo = "r"\nbase_commit = "b"\nfix_commit = "f"\n'
        'issue_url = "u"\nissue_file = "i"\ntarget_tests = []\ntest_files = []\n'
    )
    path = tmp_path / "tasks.toml"
    path.write_text("".join(entry.format(id=i, split=sp) for i, sp in
                            [("cal1", "calibration"), ("cal2", "calibration"), ("e1", "evaluation"), ("e2", "evaluation")]))
    return str(path)


def feat(i):
    return Features(i, 3, 1000, 2.0).to_dict()


def build_ledger(tmp_path) -> Ledger:
    ledger = Ledger(tmp_path / "ledger.jsonl")
    plan = [("cal1", "calibration"), ("cal2", "calibration"), ("e1", "evaluation"), ("e2", "evaluation")]
    for n, (task, split) in enumerate(plan):
        for arm, cost in (("A", 2.0), ("B", 1.5)):
            row = rec(run_id=f"{arm}{n}", task=task, arm=arm, cost=cost, price=0.0,
                      features=feat(100 + 40 * n) if arm == "B" else {})
            row.split = split
            ledger.append(row)
    for n, task in enumerate(["e1", "e2"]):
        row = rec(run_id=f"C{n}", task=task, arm="C", cost=1.0, price=2.4,
                  quote={"p50": 1.2, "lo": 0.8, "hi": 1.6}, features=feat(180 + 40 * n),
                  rung_events=[{"turn": 2, "rung": "DOWNGRADE", "reason": "no progress"}])
        ledger.append(row)
    return ledger


def test_quote_coverage_counts_out_of_sample_hits(tmp_path):
    b_rows = list(build_ledger(tmp_path).latest("B").values())
    coverage = quote_coverage(b_rows)
    assert coverage["n"] == 4 and 0 <= coverage["covered"] <= 4
    assert quote_coverage([])["coverage"] is None


def test_results_page_has_every_section_and_is_deterministic(tmp_path):
    ledger = build_ledger(tmp_path)
    page = render_results(ledger, FLAT)
    assert page == render_results(ledger, FLAT)
    for needle in (
        "# Results", "Flat price", "## Arms on the evaluation tasks", "| A | 2 |", "| C | 2 |",
        "## Quote accuracy", "## Per task", "| e1 |", "DOWNGRADE",
    ):
        assert needle in page, needle
    assert "$0.80–$1.60" in page


def test_report_command_writes_then_checks(tmp_path):
    ledger = build_ledger(tmp_path)
    flat = tmp_path / "flat.json"
    flat.write_text(json.dumps(FLAT))
    out, html = tmp_path / "results.md", tmp_path / "receipts.html"
    base = ["report", "--ledger", str(ledger.path), "--flat", str(flat), "--out", str(out), "--html", str(html),
            "--tasks-file", write_manifest(tmp_path)]
    assert main(base) == 0
    assert out.exists() and html.exists()
    assert main([*base, "--check"]) == 0
    out.write_text(out.read_text() + "tampered")
    assert main([*base, "--check"]) == 1


def test_receipts_page_escapes_task_ids_and_shows_governor_events():
    row = rec(task="<b>x</b>", arm="C", quote={"p50": 1.0, "lo": 0.5, "hi": 2.0},
              rung_events=[{"turn": 1, "rung": "ABORT", "reason": "cap & more"}])
    page = render_receipts_page([row])
    assert "&lt;b&gt;x&lt;/b&gt;" in page and "<b>x</b>" not in page
    assert "ABORT" in page and "cap &amp; more" in page and "verified" in page


def test_receipts_page_writes_a_negative_margin_with_the_sign_first_and_shows_what_was_billed():
    lost = rec(task="lost", arm="C", solved=False, cost=0.13, price=0.22, quote={"p50": 0.1, "lo": 0.05, "hi": 0.15})
    won = rec(task="won", arm="C", solved=True, cost=0.05, price=0.20, quote={"p50": 0.1, "lo": 0.05, "hi": 0.15})
    page = render_receipts_page([lost, won])
    assert "-$0.13" in page and "$-0.13" not in page
    assert "<dt>Billed</dt><dd>$0.00</dd>" in page and "<dt>Billed</dt><dd>$0.20</dd>" in page


def test_report_without_a_flat_price_says_what_to_run_instead_of_crashing(tmp_path, capsys):
    ledger = build_ledger(tmp_path)
    args = ["report", "--ledger", str(ledger.path), "--flat", str(tmp_path / "missing.json"),
            "--out", str(tmp_path / "r.md"), "--html", str(tmp_path / "r.html")]
    assert main(args) == 1
    assert "calibrate-flat" in capsys.readouterr().out


def test_report_refuses_a_flat_price_the_ledger_does_not_support(tmp_path, capsys):
    """make verify must regenerate the published numbers from the stored ledger, the flat price included."""
    ledger = build_ledger(tmp_path)
    flat = tmp_path / "flat.json"
    flat.write_text(json.dumps({**FLAT, "flat_price_usd": 9.99}))
    args = ["report", "--ledger", str(ledger.path), "--flat", str(flat),
            "--out", str(tmp_path / "r.md"), "--html", str(tmp_path / "r.html"), "--tasks-file", write_manifest(tmp_path)]
    assert main(args) == 1 and "calibrate-flat" in capsys.readouterr().out
    assert main([*args, "--check"]) == 1
