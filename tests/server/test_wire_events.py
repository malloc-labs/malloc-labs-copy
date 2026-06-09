from copy_653.server.wire_events import _claimed_symbols_event


def test_claimed_symbols_event_accepts_koch_probe_phase():
    event = _claimed_symbols_event(
        ("K", "M"),
        koch_set_session=9,
        koch_gears=[3, 3, 3, 3, 3],
        koch_warm_up=False,
        probe_phase="challenge-block",
    )

    assert event["koch_set_session"] == 9
    assert event["koch_gears"] == [3, 3, 3, 3, 3]
    assert event["koch_warm_up"] is False
    assert event["probe_phase"] == "challenge-block"
