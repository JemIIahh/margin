"""Budget governor: a monotonic ladder driven by spend, progress and the next-call estimate."""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class Rung(IntEnum):
    CONTINUE = 1
    DOWNGRADE = 2
    NARROW = 3
    ABORT = 4


@dataclass(frozen=True)
class Decision:
    rung: Rung
    changed: bool
    reason: str = ""


class NullGovernor:
    """Used by arms A and B: no budget control (the run hard cap still applies in the loop)."""

    rung = Rung.CONTINUE

    def check(self, spend: float, est_next: float, progress_events: int) -> Decision:
        return Decision(Rung.CONTINUE, False)

    def restore(self, rung_name: str, seen_progress: int = 0) -> None:
        return None


class Governor:
    def __init__(self, cap_usd: float, downgrade_at: float = 0.6, narrow_at: float = 0.85):
        self.cap = cap_usd
        self.downgrade_at = downgrade_at
        self.narrow_at = narrow_at
        self.rung = Rung.CONTINUE
        self._seen_progress = 0

    @property
    def seen_progress(self) -> int:
        return self._seen_progress

    def restore(self, rung_name: str, seen_progress: int = 0) -> None:
        self.rung = Rung[rung_name]
        self._seen_progress = seen_progress  # progress already accounted for before the checkpoint is not new

    def check(self, spend: float, est_next: float, progress_events: int) -> Decision:
        progressed = progress_events > self._seen_progress
        self._seen_progress = progress_events
        target, reason = self.rung, ""
        if spend + est_next >= self.cap:
            target = Rung.ABORT
            reason = f"spend ${spend:.4f} plus next call ${est_next:.4f} reaches the cap ${self.cap:.4f}"
        elif spend >= self.narrow_at * self.cap:
            target = Rung.NARROW
            reason = f"spend ${spend:.4f} is at {spend / self.cap:.0%} of the cap"
        elif spend >= self.downgrade_at * self.cap and not progressed:
            target = Rung.DOWNGRADE
            reason = f"no progress at {spend / self.cap:.0%} of the cap"
        target = max(self.rung, target)
        changed = target > self.rung
        self.rung = target
        return Decision(self.rung, changed, reason if changed else "")
