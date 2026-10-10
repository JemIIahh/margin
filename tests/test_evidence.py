from margin.config import ROOT

TEXT = (ROOT / "EVIDENCE.md").read_text()


def test_evidence_page_is_complete():
    assert "{{" not in TEXT, "fill in every {{...}} placeholder with a real link"


def test_evidence_page_covers_every_required_claim():
    for claim in (
        "The agent improved", "You used neatlogs", "You used Entire", "You used cfo.ai",
        "The agent recovers from failures", "You built in public", "You wrote the code during the hackathon",
        "Known limits",
    ):
        assert claim in TEXT, claim


def test_evidence_links_to_generated_artifacts():
    for path in ("docs/results.md", "docs/business", "docs/evidence/failure-recovery.md", "make verify"):
        assert path in TEXT, path
