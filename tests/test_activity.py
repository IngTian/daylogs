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
    add_food,
    add_weight,
    baseline_factor,
    bmi,
    compute_bmr,
    compute_tdee,
    day_factor,
    day_tdee,
    delete_activity,
    list_activity,
    net_average,
    net_series_between,
    resolved_factor,
    update_activity,
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


# ── where the factor came from ───────────────────────────────────────────
# The origin reaches the screen deliberately. A factor rescales every calorie
# judgement for the day, so a multiplier with nothing to make you doubt it quietly
# becomes the baseline for everything.


def test_the_origin_of_a_baseline_factor_is_the_profile(db, tmp_path):
    assert resolved_factor(db, _cfg(tmp_path, activity="desk"), date=D) == (1.2, "profile")


def test_the_origin_of_an_inferred_factor_is_the_log(db, tmp_path):
    cfg = _cfg(tmp_path, activity="desk")
    add_activity(db, description="gym 1h", date=D, at=100, factor=1.45, source="estimated")
    assert resolved_factor(db, cfg, date=D) == (1.45, "logged")


def test_a_factorless_row_leaves_the_origin_as_the_profile(db, tmp_path):
    """An inference that never landed falls through, origin and all — otherwise the
    panel would claim a logged number it did not get."""
    cfg = _cfg(tmp_path, activity="light")
    add_activity(db, description="gym", date=D, at=100, factor=None, source="estimated")
    assert resolved_factor(db, cfg, date=D) == (1.375, "profile")


def test_no_factor_means_no_origin(db, tmp_path):
    assert resolved_factor(db, _cfg(tmp_path), date=D) == (None, None)


def test_day_factor_is_the_number_resolved_factor_resolves(db, tmp_path):
    """One resolution, two callers: the panel wants the origin, nothing else does.
    Two separate resolutions is how a header and a panel start disagreeing."""
    cfg = _cfg(tmp_path, activity="active")
    for date in (D, "2026-09-02"):
        assert day_factor(db, cfg, date=date) == resolved_factor(db, cfg, date=date)[0]
    add_activity(db, description="hike", date=D, at=100, factor=1.7, source="estimated")
    assert day_factor(db, cfg, date=D) == resolved_factor(db, cfg, date=D)[0] == 1.7


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


# ── a day's burn ─────────────────────────────────────────────────────────
# `day_tdee` is the one place BMR-times-factor is composed. Four surfaces read it,
# and four separate compositions is four chances to measure against a different
# baseline in the same panel.

# 180 cm, male, born 1996-01-01, so 30 on every date used below: Mifflin-St Jeor
# gives 10*80 + 6.25*180 - 5*30 + 5 = 1780. Spelled out rather than recomputed with
# compute_bmr, so a bug in compute_bmr cannot cancel itself out here.
BMR_AT_80KG = 1780


def _bmr_cfg(tmp_path, **kw):
    """A BMR-capable profile. Overridable field by field — a test about a birthday
    has to be able to name its own."""
    base = {"height_cm": 180, "sex": "male", "birthday": "1996-01-01"}
    return _cfg(tmp_path, **{**base, **kw})


def test_a_days_burn_is_its_bmr_scaled_by_its_factor(db, tmp_path):
    cfg = _bmr_cfg(tmp_path, activity="desk")
    add_weight(db, kg=80.0, date=D, at=1)
    assert compute_bmr(cfg, 80.0, today=D) == BMR_AT_80KG
    assert day_tdee(db, cfg, date=D) == round(BMR_AT_80KG * 1.2)


def test_a_days_burn_follows_that_days_own_factor(db, tmp_path):
    cfg = _bmr_cfg(tmp_path, activity="desk")
    add_weight(db, kg=80.0, date="2026-09-01", at=1)
    add_activity(db, description="hike", date=D, at=2, factor=1.6, source="estimated")
    assert day_tdee(db, cfg, date="2026-09-01") == round(BMR_AT_80KG * 1.2)
    assert day_tdee(db, cfg, date=D) == round(BMR_AT_80KG * 1.6)


def test_a_days_burn_uses_the_latest_weight_on_or_before_it(db, tmp_path):
    """The same rule every other reader follows. A week-old weigh-in is the best
    available answer, not a reason to show nothing."""
    cfg = _bmr_cfg(tmp_path, activity="desk")
    add_weight(db, kg=80.0, date="2026-08-27", at=1)
    assert day_tdee(db, cfg, date=D) == round(BMR_AT_80KG * 1.2)


def test_a_days_burn_uses_that_days_age_not_todays(db, tmp_path):
    """Mifflin-St Jeor takes age, and a window can straddle a birthday. Passing
    `today=None` down to `compute_bmr` would date every day in the series by the day
    the app happens to be running, which is the class of bug this repo keeps hitting.

    Born 1996-09-15, so 29 on Sep 10 2026 and 30 on Sep 20 — five kcal apart, which
    is exactly the term `- 5 * age` contributes.
    """
    cfg = _bmr_cfg(tmp_path, activity="desk", birthday="1996-09-15")
    add_weight(db, kg=80.0, date="2026-09-01", at=1)
    younger = day_tdee(db, cfg, date="2026-09-10")
    older = day_tdee(db, cfg, date="2026-09-20")
    assert younger == round((BMR_AT_80KG + 5) * 1.2)
    assert older == round(BMR_AT_80KG * 1.2)
    assert younger != older


def test_there_is_no_burn_before_the_first_weigh_in(db, tmp_path):
    cfg = _bmr_cfg(tmp_path, activity="desk")
    add_weight(db, kg=80.0, date=D, at=1)
    assert day_tdee(db, cfg, date="2026-09-01") is None


def test_there_is_no_burn_without_a_factor(db, tmp_path):
    """No baseline and nothing logged: `net` stays against resting BMR, exactly as
    it did before this existed."""
    cfg = _bmr_cfg(tmp_path)
    add_weight(db, kg=80.0, date=D, at=1)
    assert day_tdee(db, cfg, date=D) is None


def test_there_is_no_burn_without_a_profile(db, tmp_path):
    cfg = _cfg(tmp_path, activity="desk")
    add_weight(db, kg=80.0, date=D, at=1)
    assert day_tdee(db, cfg, date=D) is None


# ── net over a window ────────────────────────────────────────────────────


def test_net_is_computed_per_day_against_that_days_burn(db, tmp_path):
    """The whole reason this is a series and not one subtraction: a factor describes
    a day, so one gym session must not restate a week's worth of net. Measuring the
    window's average intake against *today's* burn is the bug this pins."""
    cfg = _bmr_cfg(tmp_path, activity="desk")
    add_weight(db, kg=80.0, date="2026-09-01", at=1)
    add_food(db, description="a", kcal=2000, source="labeled", date="2026-09-01", at=2)
    add_food(db, description="b", kcal=1000, source="labeled", date="2026-09-02", at=3)
    add_activity(db, description="gym", date="2026-09-02", at=4, factor=1.6,
                 source="estimated")
    assert net_series_between(db, cfg, start="2026-09-01", end="2026-09-02") == [
        ("2026-09-01", 2000 - round(BMR_AT_80KG * 1.2)),
        ("2026-09-02", 1000 - round(BMR_AT_80KG * 1.6)),
    ]


def test_a_day_with_no_food_is_absent_from_net_not_zero(db, tmp_path):
    """A logging gap is not a fast — the same rule kcal_series_between follows."""
    cfg = _bmr_cfg(tmp_path, activity="desk")
    add_weight(db, kg=80.0, date="2026-09-01", at=1)
    add_food(db, description="a", kcal=2000, source="labeled", date="2026-09-01", at=2)
    got = net_series_between(db, cfg, start="2026-09-01", end="2026-09-03")
    assert [d for d, _ in got] == ["2026-09-01"]


def test_a_day_with_food_but_no_burn_is_absent_from_net(db, tmp_path):
    """Before the first weigh-in there is no BMR to scale, so there is no net to
    show. Showing intake as if it were net would read as an enormous surplus."""
    cfg = _bmr_cfg(tmp_path, activity="desk")
    add_food(db, description="a", kcal=2000, source="labeled", date="2026-09-01", at=1)
    add_weight(db, kg=80.0, date="2026-09-02", at=2)
    add_food(db, description="b", kcal=2000, source="labeled", date="2026-09-02", at=3)
    assert net_series_between(db, cfg, start="2026-09-01", end="2026-09-02") == [
        ("2026-09-02", 2000 - round(BMR_AT_80KG * 1.2)),
    ]


def test_net_series_is_bounded_by_the_window(db, tmp_path):
    cfg = _bmr_cfg(tmp_path, activity="desk")
    add_weight(db, kg=80.0, date="2026-08-01", at=1)
    for date in ("2026-08-31", "2026-09-01", "2026-09-02"):
        add_food(db, description="a", kcal=2000, source="labeled", date=date, at=2)
    got = net_series_between(db, cfg, start="2026-09-01", end="2026-09-01")
    assert [d for d, _ in got] == ["2026-09-01"]


def test_net_average_is_the_mean_of_the_days_that_qualify(db, tmp_path):
    cfg = _bmr_cfg(tmp_path, activity="desk")
    add_weight(db, kg=80.0, date="2026-09-01", at=1)
    add_food(db, description="a", kcal=2000, source="labeled", date="2026-09-01", at=2)
    add_food(db, description="b", kcal=1000, source="labeled", date="2026-09-02", at=3)
    add_activity(db, description="gym", date="2026-09-02", at=4, factor=1.6,
                 source="estimated")
    burn = round(BMR_AT_80KG * 1.2) + round(BMR_AT_80KG * 1.6)
    assert net_average(db, cfg, start="2026-09-01", end="2026-09-02") == round(
        (3000 - burn) / 2
    )


def test_net_average_is_none_when_no_day_qualifies(db, tmp_path):
    cfg = _bmr_cfg(tmp_path, activity="desk")
    assert net_average(db, cfg, start="2026-09-01", end=D) is None


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


# ── editing and deleting a logged activity ───────────────────────────────


def test_an_activity_can_be_edited(db):
    rid = add_activity(db, description="gym", date=D, at=100, factor=1.4,
                       source="estimated")
    assert update_activity(db, rid, description="gym 90m", factor=1.6) is True
    row = list_activity(db, date=D)[0]
    assert (row["description"], row["factor"]) == ("gym 90m", 1.6)


def test_an_edit_cannot_set_an_impossible_factor(db):
    """The same clamp the insert has. An edit is a write, and a write that skips the
    clamp is a hole in it."""
    rid = add_activity(db, description="gym", date=D, at=100, factor=1.4,
                       source="estimated")
    with pytest.raises(BodyError):
        update_activity(db, rid, factor=4.0)
    assert list_activity(db, date=D)[0]["factor"] == 1.4, "the row was written anyway"


def test_an_edit_cannot_blank_the_description(db):
    rid = add_activity(db, description="gym", date=D, at=100, factor=1.4,
                       source="estimated")
    with pytest.raises(BodyError):
        update_activity(db, rid, description="   ")


def test_an_edit_cannot_reach_provenance(db):
    """`source` is what the digest reads to know whether a number was inferred. It is
    not something editing a description should rewrite — the same stance food takes."""
    rid = add_activity(db, description="gym", date=D, at=100, factor=1.4,
                       source="estimated")
    with pytest.raises(BodyError):
        update_activity(db, rid, source="labeled")


def test_an_edit_that_names_no_factor_leaves_the_stored_one_alone(db):
    """A factor is not clearable through the prompt, unlike an expense's note. A row
    with no factor is a failed inference, not a state anyone would choose, so the way
    to remove one is `x`. This is also what keeps such a row editable at all: its
    rendered line carries no `=`, and treating that as "clear it" or as an error would
    make the description unfixable."""
    rid = add_activity(db, description="gym", date=D, at=100, factor=1.4,
                       source="estimated")
    update_activity(db, rid, description="gym, upper body")
    row = list_activity(db, date=D)[0]
    assert (row["description"], row["factor"]) == ("gym, upper body", 1.4)


def test_deleting_an_activity_hands_back_the_row_for_undo(db):
    rid = add_activity(db, description="gym", date=D, at=100, factor=1.4,
                       source="estimated")
    row = delete_activity(db, rid)
    assert row["id"] == rid and row["description"] == "gym"
    assert list_activity(db, date=D) == []


def test_deleting_an_activity_that_is_gone_returns_none(db):
    assert delete_activity(db, 9999) is None


def test_deleting_the_latest_inference_restores_the_earlier_one(db, tmp_path):
    """Latest-wins means a delete has to fall back, not fall through to the baseline."""
    cfg = _cfg(tmp_path, activity="desk")
    add_activity(db, description="gym", date=D, at=100, factor=1.5, source="estimated")
    rid = add_activity(db, description="hike", date=D, at=200, factor=1.7,
                       source="estimated")
    assert day_factor(db, cfg, date=D) == 1.7
    delete_activity(db, rid)
    assert day_factor(db, cfg, date=D) == 1.5
