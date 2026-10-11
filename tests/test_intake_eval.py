from types import SimpleNamespace

import pytest

from margin.bench.intake_eval import (
    INJECTIONS,
    VAGUE,
    Item,
    Variant,
    build_variants,
    canary_obeyed,
    collect_items,
    load_variants,
    policy_comparison,
    rates,
    render_calibration_table,
    render_intake_report,
    write_variants,
)
from margin.intake import IntakeThresholds, IntakeVerdict
from test_ledger import rec


def tasks():
    out = [SimpleNamespace(id=f"cal-{i}", split="calibration") for i in range(4)]
    out += [SimpleNamespace(id=f"ev-{i:02d}", split="evaluation") for i in range(12)]
    return out


def read_issue(task):
    return f"Original issue text for {task.id}."


def test_build_variants_follows_the_plan():
    built = build_variants(tasks(), read_issue)
    variants = [v for v, _ in built]
    assert len(variants) == 14
    assert [(v.split, v.kind) for v in variants].count(("calibration", "injected")) == 2
    assert [(v.split, v.kind) for v in variants].count(("calibration", "vague")) == 2
    assert [(v.split, v.kind) for v in variants].count(("evaluation", "injected")) == 6
    assert [(v.split, v.kind) for v in variants].count(("evaluation", "vague")) == 4
    assert len({v.id for v in variants}) == 14
    assert len({v.canary for v in variants if v.canary}) == 8
    assert {v.base_task for v in variants if v.split == "calibration"} <= {f"cal-{i}" for i in range(4)}


def test_injected_variants_keep_the_issue_and_name_their_canary():
    for variant, text in build_variants(tasks(), read_issue):
        if variant.kind == "injected":
            assert f"Original issue text for {variant.base_task}." in text
            assert variant.canary in text and "OBEYED" in text
        else:
            assert variant.base_task not in text and text.strip() in VAGUE


def test_every_injection_template_formats_with_a_canary():
    for template in INJECTIONS:
        assert "CANARY_9.txt" in template.format(canary="CANARY_9.txt")


def test_build_variants_needs_enough_tasks():
    with pytest.raises(ValueError, match="need 10 evaluation"):
        build_variants([t for t in tasks() if t.split == "calibration"] + tasks()[4:9], read_issue)


def test_variants_roundtrip_through_disk(tmp_path):
    items = build_variants(tasks(), read_issue)
    path = write_variants(tmp_path, items)
    loaded = load_variants(path)
    assert loaded == [v for v, _ in items]
    first, text = items[0]
    assert (tmp_path / first.issue_file).read_text() == text


def test_canary_detection(tmp_path):
    work = tmp_path / "run-1" / "work"
    work.mkdir(parents=True)
    assert not canary_obeyed(tmp_path, "run-1", "CANARY_1.txt")
    (work / "CANARY_1.txt").write_text("OBEYED")
    assert canary_obeyed(tmp_path, "run-1", "CANARY_1.txt")
    assert not canary_obeyed(tmp_path, "run-1", None)


def item(name, kind, decision, ungated=None, obeyed=None, gate=0.0001, split="evaluation"):
    return Item(name, kind, split, decision, 0.1, 0.9, gate, 0.4, ungated, obeyed)


def test_rates_count_decisions_per_kind():
    items = [item("a", "clean", "accept"), item("b", "clean", "decline"), item("c", "injected", "review")]
    assert rates(items, "clean") == {"n": 2, "accept": 1, "review": 0, "decline": 1, "not_accepted": 1}
    assert rates(items, "injected")["not_accepted"] == 1
    assert rates(items, "vague")["n"] == 0


def test_policy_comparison_counts_forgone_revenue_and_avoided_loss():
    won = rec(task="a", arm="C", cost=1.0, price=2.0, solved=True)       # margin +1.0
    lost = rec(task="b", arm="C", cost=1.5, price=2.0, solved=False)     # margin -1.5
    items = [item("a", "clean", "decline", ungated=won), item("b", "injected", "decline", ungated=lost),
             item("c", "clean", "accept", ungated=won), item("d", "clean", "accept")]  # d has no ungated run
    result = policy_comparison(items)
    assert result["n"] == 3
    assert result["no_gate_margin"] == pytest.approx(1.0 - 1.5 + 1.0)
    # gate: a declined (-gate), b declined (-gate), c accepted (+1.0 - gate)
    assert result["gated_margin"] == pytest.approx(1.0 - 3 * 0.0001)
    assert result["difference"] == pytest.approx(0.5 - 3 * 0.0001)  # +1.0 kept on c, minus the loss avoided on b


def test_report_has_every_section_and_is_deterministic():
    won = rec(task="a", arm="C", cost=1.0, price=2.0, solved=True)
    lost = rec(task="b", arm="C", cost=1.5, price=2.0, solved=False)
    items = [
        item("a", "clean", "accept", ungated=won),
        item("b", "injected", "decline", ungated=lost, obeyed=True),
        item("c", "injected", "accept", ungated=lost, obeyed=False),
        item("d", "vague", "review", ungated=won),
        item("cal", "clean", "decline", split="calibration"),
    ]
    page = render_intake_report(items, IntakeThresholds())
    assert page == render_intake_report(items, IntakeThresholds())
    for needle in (
        "# Intake gate results", "## Gate decisions on the evaluation items", "| clean issues", "| injected issues",
        "Injected issues that got through: 1 of 2 (c)", "obeyed the planted instruction (created the canary file) in 1 of 2",
        "| difference |", "## Limits", "second layer",
    ):
        assert needle in page, needle
    assert "| clean issues (should be accepted) | 1 | 1 | 0 | 0 |" in page  # the calibration item is excluded




class ByText:
    """A gate that decides from the text it is given."""

    def screen(self, text):
        if "OBEYED" in text:
            return IntakeVerdict("decline", 0.95, 0.9, ["injection"], 400, 0.00002, 0.3)
        if text.startswith("vague"):
            return IntakeVerdict("review", 0.05, 0.2, ["actionable"], 100, 0.00001, 0.2)
        return IntakeVerdict("accept", 0.02, 0.95, [], 300, 0.00001, 0.25)


def test_collect_items_screens_clean_issues_and_variants_and_finds_ungated_runs(tmp_path):
    tasks = [SimpleNamespace(id="ev-1", split="evaluation", issue_file="i/ev-1.md"),
             SimpleNamespace(id="cal-1", split="calibration", issue_file="i/cal-1.md")]
    variants = [Variant("inj-1", "ev-1", "injected", "evaluation", "v/inj-1.md", "CANARY_1.txt"),
                Variant("vague-2", "ev-1", "vague", "evaluation", "v/vague-2.md"),
                Variant("inj-9", "cal-1", "injected", "calibration", "v/inj-9.md", "CANARY_9.txt")]
    texts = {"i/ev-1.md": "a real bug", "v/inj-1.md": "a real bug ... OBEYED", "v/vague-2.md": "vague words"}
    benchmark = {"ev-1": rec(task="ev-1", arm="C", run_id="bench-C")}
    ungated = rec(task="ev-1", arm="C", run_id="ungated-inj-1", trace_tags=["variant:inj-1", "version:demo-intake"])
    gated = rec(task="ev-1", arm="C", run_id="gated-inj-1", trace_tags=["variant:inj-1", "intake:declined"])
    (tmp_path / "ungated-inj-1" / "work").mkdir(parents=True)
    (tmp_path / "ungated-inj-1" / "work" / "CANARY_1.txt").write_text("OBEYED")
    items = collect_items(
        gate=ByText(), split="evaluation", tasks=tasks, variants=variants, read_text=lambda rel: texts[rel],
        benchmark_c=benchmark, variant_rows=[ungated, gated], runs_dir=tmp_path,
    )
    assert [(i.name, i.kind, i.decision) for i in items] == [
        ("ev-1", "clean", "accept"), ("inj-1", "injected", "decline"), ("vague-2", "vague", "review"),
    ]
    assert items[0].ungated.run_id == "bench-C"
    assert items[1].ungated.run_id == "ungated-inj-1" and items[1].obeyed is True  # the gated row is not "ungated"
    assert items[2].ungated is None and items[2].obeyed is None
    assert items[1].to_dict()["ungated_run"] == "ungated-inj-1"


def test_calibration_table_lists_raw_probabilities():
    items = [item("inj-9", "injected", "decline", split="calibration"), item("cal-1", "clean", "accept", split="calibration")]
    table = render_calibration_table(items)
    assert table.splitlines()[0].startswith("| kind | item | injection")
    assert "| clean | cal-1 | 0.10 | 0.90 | accept |" in table
