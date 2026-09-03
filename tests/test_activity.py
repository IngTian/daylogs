"""Activity, the day factor, TDEE and BMI.

`net` used to compare intake against *resting* expenditure, so a sedentary day read
as a deficit it wasn't and a hard day understated one. The profile now says what an
ordinary day is, and only days that depart from it get logged.
"""

import pytest

from daylogs.body import (
    ACTIVITY_LEVELS,
    FACTOR_MAX,
    FACTOR_MIN,
    BodyError,
    add_activity,
    baseline_factor,
    bmi,
    compute_tdee,
    day_factor,
    list_activity,
)
from daylogs.config import Config

D = "2026-09-03"


def _cfg(tmp_path, **kw):
    base = dict(
        root=tmp_path,
        db_path=tmp_path / "t.db",
        inbox_dir=tmp_path / "inbox",
        memory_path=tmp_path / "m.md",
    )
    return Config(**{**base, **kw})


# ── the baseline ─────────────────────────────────────────────────────────


def test_the_levels_are_the_standard_multipliers(tmp_path):
    assert ACTIVITY_LEVELS == {"desk": 1.2, "light": 1.375, "active": 1.55, "heavy": 1.725}


def test_a_baseline_keyword_resolves_to_its_multiplier(tmp_path):
    assert baseline_factor(_cfg(tmp_path, activity="desk")) == 1.2
    assert baseline_factor(_cfg(tmp_path, activity="heavy")) == 1.725


def test_no_baseline_means_no_factor(tmp_path):
    """Not defaulted on purpose: assuming `desk` would raise maintenance 20% and
    silently restate every number already on screen and in every past digest."""
    assert baseline_factor(_cfg(tmp_path)) is None


def test_an_unknown_baseline_keyword_does_not_raise(tmp_path):
    """config.toml is hand-edited, so a typo must not stop the app."""
    assert baseline_factor(_cfg(tmp_path, activity="offisce")) is None


# ── resolving a day's factor ─────────────────────────────────────────────


def test_a_day_with_no_activity_uses_the_baseline(db, tmp_path):
    """The common case, and the reason the baseline exists: an ordinary day needs no
    typing at all."""
    cfg = _cfg(tmp_path, activity="desk")
    assert day_factor(db, cfg, date=D) == 1.2


def test_a_logged_inference_beats_the_baseline(db, tmp_path):
    cfg = _cfg(tmp_path, activity="desk")
    add_activity(db, description="gym 1h", date=D, at=100, factor=1.45, source="estimated")
    assert day_factor(db, cfg, date=D) == 1.45


def test_the_latest_inference_wins(db, tmp_path):
    """Re-logging supersedes — the same rule two weigh-ins on one day follow."""
    cfg = _cfg(tmp_path, activity="desk")
    add_activity(db, description="gym", date=D, at=100, factor=1.4, source="estimated")
    add_activity(db, description="and a hike", date=D, at=200, factor=1.7, source="estimated")
    assert day_factor(db, cfg, date=D) == 1.7


def test_a_row_with_no_factor_falls_back_to_the_baseline(db, tmp_path):
    """An inference that never landed — no CLI, a timeout — must not poison the day
    with nothing. This is the case the three-step resolution exists for."""
    cfg = _cfg(tmp_path, activity="light")
    add_activity(db, description="gym", date=D, at=100, factor=None, source="estimated")
    assert day_factor(db, cfg, date=D) == 1.375


def test_a_failed_inference_does_not_hide_an_earlier_good_one(db, tmp_path):
    cfg = _cfg(tmp_path, activity="desk")
    add_activity(db, description="gym", date=D, at=100, factor=1.5, source="estimated")
    add_activity(db, description="walk", date=D, at=200, factor=None, source="estimated")
    assert day_factor(db, cfg, date=D) == 1.5


def test_no_activity_and_no_baseline_means_no_factor(db, tmp_path):
    assert day_factor(db, _cfg(tmp_path), date=D) is None


def test_another_days_activity_does_not_leak(db, tmp_path):
    cfg = _cfg(tmp_path, activity="desk")
    add_activity(db, description="gym", date="2026-09-02", at=100, factor=1.6,
                 source="estimated")
    assert day_factor(db, cfg, date=D) == 1.2


# ── clamping ─────────────────────────────────────────────────────────────


def test_a_factor_outside_the_physiological_range_is_rejected(db):
    """A wrong factor does not misreport one row — it rescales every calorie
    judgement for the day, so a hallucinated 4.0 must never be stored."""
    for bad in (1.19, 1.91, 4.0, 0.0, -1.0):
        with pytest.raises(BodyError):
            add_activity(db, description="x", date=D, at=1, factor=bad, source="estimated")


def test_the_range_ends_themselves_are_accepted(db):
    add_activity(db, description="lo", date=D, at=1, factor=FACTOR_MIN, source="labeled")
    add_activity(db, description="hi", date=D, at=2, factor=FACTOR_MAX, source="labeled")
    assert [r["factor"] for r in list_activity(db, date=D)] == [FACTOR_MIN, FACTOR_MAX]


def test_a_day_may_be_less_active_than_its_baseline(db, tmp_path):
    """Illness is real, so the inference is floored at the physiological minimum
    rather than at the baseline."""
    cfg = _cfg(tmp_path, activity="active")
    add_activity(db, description="in bed, unwell", date=D, at=1, factor=1.2,
                 source="estimated")
    assert day_factor(db, cfg, date=D) == 1.2


def test_an_empty_description_is_rejected(db):
    with pytest.raises(BodyError):
        add_activity(db, description="   ", date=D, at=1, factor=1.3, source="estimated")


# ── TDEE ─────────────────────────────────────────────────────────────────


def test_tdee_scales_bmr_by_the_factor():
    assert compute_tdee(1788, 1.4) == 2503


def test_tdee_is_none_when_either_input_is_missing():
    assert compute_tdee(None, 1.4) is None
    assert compute_tdee(1788, None) is None


# ── BMI ──────────────────────────────────────────────────────────────────


def test_bmi_needs_a_weight_and_a_height(tmp_path):
    assert bmi(_cfg(tmp_path, height_cm=180), 81.0) == 25.0
    assert bmi(_cfg(tmp_path, height_cm=180), None) is None
    assert bmi(_cfg(tmp_path), 81.0) is None


def test_bmi_is_a_bare_number(tmp_path):
    """No band, no colour: "over"/"obese" is a judgement this app does not make."""
    assert isinstance(bmi(_cfg(tmp_path, height_cm=175), 81.4), float)


def test_activities_are_listed_oldest_first(db):
    add_activity(db, description="second", date=D, at=200, factor=1.3, source="estimated")
    add_activity(db, description="first", date=D, at=100, factor=1.3, source="estimated")
    assert [r["description"] for r in list_activity(db, date=D)] == ["first", "second"]
