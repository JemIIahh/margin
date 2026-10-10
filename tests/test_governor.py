from margin.governor import Governor, NullGovernor, Rung


def test_continue_below_thresholds():
    g = Governor(cap_usd=1.0)
    d = g.check(spend=0.3, est_next=0.05, progress_events=0)
    assert d.rung == Rung.CONTINUE and not d.changed


def test_downgrade_at_sixty_percent_without_progress():
    g = Governor(cap_usd=1.0)
    d = g.check(spend=0.62, est_next=0.05, progress_events=0)
    assert d.rung == Rung.DOWNGRADE and d.changed
    assert "no progress" in d.reason


def test_no_downgrade_while_making_progress():
    g = Governor(cap_usd=1.0)
    assert g.check(0.62, 0.05, progress_events=1).rung == Rung.CONTINUE
    assert g.check(0.62, 0.05, progress_events=1).rung == Rung.DOWNGRADE  # next check: none since


def test_narrow_at_eighty_five_percent():
    g = Governor(cap_usd=1.0)
    g.check(0.62, 0.05, 0)
    d = g.check(0.86, 0.05, 0)
    assert d.rung == Rung.NARROW and d.changed


def test_jump_straight_to_narrow_skips_downgrade():
    g = Governor(cap_usd=1.0)
    d = g.check(0.9, 0.05, 0)
    assert d.rung == Rung.NARROW


def test_abort_when_next_call_would_reach_the_cap():
    g = Governor(cap_usd=1.0)
    d = g.check(0.9, 0.11, 0)
    assert d.rung == Rung.ABORT and d.changed
    assert "cap" in d.reason


def test_rungs_never_decrease():
    g = Governor(cap_usd=1.0)
    g.check(0.9, 0.05, 0)
    d = g.check(0.1, 0.01, progress_events=5)
    assert d.rung == Rung.NARROW and not d.changed


def test_cap_smaller_than_one_call_aborts_immediately():
    g = Governor(cap_usd=0.01)
    assert g.check(0.0, 0.04, 0).rung == Rung.ABORT


def test_restore_sets_the_rung():
    g = Governor(cap_usd=1.0)
    g.restore("DOWNGRADE")
    assert g.rung == Rung.DOWNGRADE
    assert not g.check(0.62, 0.05, 0).changed


def test_null_governor_never_intervenes():
    g = NullGovernor()
    d = g.check(spend=999.0, est_next=999.0, progress_events=0)
    assert d.rung == Rung.CONTINUE and not d.changed
    g.restore("ABORT")
    assert g.rung == Rung.CONTINUE


def test_restore_resyncs_the_progress_counter_so_old_progress_is_not_counted_twice():
    g = Governor(cap_usd=1.0)
    g.restore("CONTINUE", seen_progress=3)
    d = g.check(0.62, 0.05, progress_events=3)       # nothing new since the checkpoint
    assert d.rung == Rung.DOWNGRADE and "no progress" in d.reason
    fresh = Governor(cap_usd=1.0)
    fresh.restore("CONTINUE", seen_progress=3)
    assert fresh.check(0.62, 0.05, progress_events=4).rung == Rung.CONTINUE    # one new event since the checkpoint
    NullGovernor().restore("ABORT", seen_progress=9)                           # same surface, ignored
