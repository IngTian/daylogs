from datetime import datetime

import pytest

from daylogs.body import (
    BodyError,
    add_food,
    add_weight,
    age_from_birthday,
    compute_bmr,
    day_kcal,
    delete_food,
    delete_weight,
    latest_weight,
    list_food,
    list_weight,
    restamp,
    update_food,
    update_weight,
    weight_delta,
    weight_series,
)
from daylogs.config import Config


def _cfg(tmp_path, **kw):
    return Config(
        root=tmp_path,
        db_path=tmp_path / "d.db",
        inbox_dir=tmp_path / "inbox",
        memory_path=tmp_path / "memory.md",
        **kw,
    )


# ── weight ───────────────────────────────────────────────────────────────
def test_add_and_read_weight(db):
    wid = add_weight(db, kg=78.2, date="2026-08-27", at=1000, note="post-run")
    row = latest_weight(db)
    assert row["id"] == wid
    assert row["kg"] == 78.2
    assert row["note"] == "post-run"


def test_latest_weight_respects_cutoff(db):
    add_weight(db, kg=79.0, date="2026-08-20", at=1)
    add_weight(db, kg=78.2, date="2026-08-27", at=2)
    assert latest_weight(db, on_or_before="2026-08-24")["kg"] == 79.0


def test_latest_weight_none_on_empty(db):
    assert latest_weight(db) is None


def test_list_weight_newest_first_and_since_filter(db):
    add_weight(db, kg=79.0, date="2026-08-20", at=1)
    add_weight(db, kg=78.2, date="2026-08-27", at=2)
    assert [r["kg"] for r in list_weight(db)] == [78.2, 79.0]
    assert [r["kg"] for r in list_weight(db, since="2026-08-25")] == [78.2]


def test_weight_series_one_point_per_day_last_reading_wins(db):
    add_weight(db, kg=79.0, date="2026-08-25", at=10)
    add_weight(db, kg=78.6, date="2026-08-25", at=20)
    add_weight(db, kg=78.2, date="2026-08-27", at=30)
    series = weight_series(db, end_date="2026-08-27", days=7)
    assert series == [("2026-08-25", 78.6), ("2026-08-27", 78.2)]


def test_weight_series_excludes_outside_window(db):
    add_weight(db, kg=90.0, date="2026-07-01", at=1)
    add_weight(db, kg=78.2, date="2026-08-27", at=2)
    assert weight_series(db, end_date="2026-08-27", days=7) == [("2026-08-27", 78.2)]


def test_weight_series_empty_when_no_data(db):
    assert weight_series(db, end_date="2026-08-27", days=30) == []


def test_weight_delta_uses_oldest_in_window(db):
    add_weight(db, kg=78.6, date="2026-08-21", at=1)
    add_weight(db, kg=78.2, date="2026-08-27", at=2)
    assert weight_delta(db, end_date="2026-08-27", days=7) == pytest.approx(-0.4)


def test_weight_delta_none_with_single_point(db):
    add_weight(db, kg=78.2, date="2026-08-27", at=1)
    assert weight_delta(db, end_date="2026-08-27", days=7) is None


def test_weight_delta_none_when_empty(db):
    assert weight_delta(db, end_date="2026-08-27", days=7) is None


def test_delete_weight_returns_row_for_undo(db):
    wid = add_weight(db, kg=78.2, date="2026-08-27", at=1)
    row = delete_weight(db, wid)
    assert row["kg"] == 78.2
    assert latest_weight(db) is None
    assert delete_weight(db, wid) is None


def test_update_weight(db):
    wid = add_weight(db, kg=78.2, date="2026-08-27", at=1)
    assert update_weight(db, wid, kg=79.0) is True
    assert latest_weight(db)["kg"] == 79.0


def test_update_weight_rejects_unknown_field(db):
    wid = add_weight(db, kg=78.2, date="2026-08-27", at=1)
    with pytest.raises(BodyError):
        update_weight(db, wid, bogus=1)


def test_add_weight_rejects_bad_values(db):
    with pytest.raises(BodyError):
        add_weight(db, kg=0, date="2026-08-27", at=1)
    with pytest.raises(BodyError):
        add_weight(db, kg=78.2, date="27-08-2026", at=1)
    with pytest.raises(BodyError):
        add_weight(db, kg=78.2, date="2026-02-30", at=1)


# ── food ─────────────────────────────────────────────────────────────────
def test_food_day_totals_and_order(db):
    add_food(db, description="yogurt", kcal=320, source="estimated", date="2026-08-27", at=30)
    add_food(db, description="salad", kcal=610, source="labeled", date="2026-08-27", at=10)
    add_food(db, description="other day", kcal=999, source="labeled", date="2026-08-26", at=5)
    rows = list_food(db, date="2026-08-27")
    assert [r["description"] for r in rows] == ["salad", "yogurt"]
    assert day_kcal(db, date="2026-08-27") == 930


def test_day_kcal_zero_when_empty(db):
    assert day_kcal(db, date="2026-08-27") == 0


def test_add_food_rejects_unknown_source(db):
    with pytest.raises(BodyError):
        add_food(db, description="x", kcal=10, source="guessed", date="2026-08-27", at=1)


def test_add_food_rejects_blank_description_and_negative_kcal(db):
    with pytest.raises(BodyError):
        add_food(db, description="   ", kcal=10, source="labeled", date="2026-08-27", at=1)
    with pytest.raises(BodyError):
        add_food(db, description="x", kcal=-1, source="labeled", date="2026-08-27", at=1)


def test_update_food_changes_only_given_fields(db):
    fid = add_food(
        db, description="salad", kcal=610, source="estimated", date="2026-08-27", at=1
    )
    assert update_food(db, fid, kcal=700, source="labeled") is True
    row = list_food(db, date="2026-08-27")[0]
    assert (row["kcal"], row["source"], row["description"]) == (700, "labeled", "salad")


def test_update_food_rejects_bad_source(db):
    fid = add_food(db, description="x", kcal=1, source="labeled", date="2026-08-27", at=1)
    with pytest.raises(BodyError):
        update_food(db, fid, source="guessed")


def test_update_food_unknown_id_returns_false(db):
    assert update_food(db, 999, kcal=1) is False


def test_delete_food_returns_row(db):
    fid = add_food(db, description="salad", kcal=610, source="labeled", date="2026-08-27", at=1)
    assert delete_food(db, fid)["kcal"] == 610
    assert list_food(db, date="2026-08-27") == []


# ── BMR (Mifflin-St Jeor) ───────────────────────────────────────────────
def test_bmr_male(tmp_path):
    cfg = _cfg(tmp_path, height_cm=180, sex="male", birthday="1996-08-27")
    # 10*80 + 6.25*180 - 5*30 + 5 = 800 + 1125 - 150 + 5 = 1780
    assert compute_bmr(cfg, 80.0, today="2026-08-27") == 1780


def test_bmr_female(tmp_path):
    cfg = _cfg(tmp_path, height_cm=165, sex="female", birthday="1996-08-27")
    # 10*60 + 6.25*165 - 5*30 - 161 = 600 + 1031.25 - 150 - 161 = 1320.25 -> 1320
    assert compute_bmr(cfg, 60.0, today="2026-08-27") == 1320


def test_bmr_none_without_weight_or_profile(tmp_path):
    full = _cfg(tmp_path, height_cm=180, sex="male", birthday="1996-08-27")
    assert compute_bmr(full, None) is None
    assert compute_bmr(_cfg(tmp_path), 80.0) is None
    assert compute_bmr(_cfg(tmp_path, height_cm=180, sex="male"), 80.0) is None
    assert compute_bmr(_cfg(tmp_path, height_cm=180, birthday="1996-08-27"), 80.0) is None


def test_age_from_birthday_handles_pre_birthday():
    assert age_from_birthday("1996-08-28", today="2026-08-27") == 29
    assert age_from_birthday("1996-08-27", today="2026-08-27") == 30
    assert age_from_birthday(None, today="2026-08-27") is None
    assert age_from_birthday("garbage", today="2026-08-27") is None


# ── restamp ──────────────────────────────────────────────────────────────
def test_restamp_returns_none_when_the_minute_is_unchanged():
    """Stored timestamps carry seconds and the grammar only has HH:MM, so
    re-deriving unconditionally would shave the seconds off every edit."""
    at = int(datetime(2026, 8, 20, 7, 5, 43).timestamp())
    assert restamp(at, date="2026-08-20", hhmm="07:05") is None


def test_restamp_returns_a_new_timestamp_when_the_minute_changed():
    at = int(datetime(2026, 8, 20, 7, 5, 43).timestamp())
    out = restamp(at, date="2026-08-20", hhmm="08:30")
    assert out is not None
    assert datetime.fromtimestamp(out) == datetime(2026, 8, 20, 8, 30)


def test_restamp_uses_the_given_date_not_the_stored_one():
    at = int(datetime(2026, 8, 20, 7, 5, 43).timestamp())
    out = restamp(at, date="2026-07-01", hhmm="09:15")
    assert datetime.fromtimestamp(out) == datetime(2026, 7, 1, 9, 15)


def test_restamp_drops_the_seconds_only_when_it_actually_rewrites():
    at = int(datetime(2026, 8, 20, 7, 5, 43).timestamp())
    assert datetime.fromtimestamp(restamp(at, date="2026-08-20", hhmm="07:06")).second == 0


def test_restamp_handles_midnight():
    at = int(datetime(2026, 8, 20, 23, 59, 12).timestamp())
    out = restamp(at, date="2026-08-20", hhmm="00:00")
    assert datetime.fromtimestamp(out) == datetime(2026, 8, 20, 0, 0)
