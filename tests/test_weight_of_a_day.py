"""Which reading is a day's weight — two named concepts, not three accidental ones.

The app answered this question three ways, and one answer was a written falsehood. With
two readings on a day, `weight_series_between` kept the *latest* (`MAX(measured_at)`), so:

- the trend line, the 7d/30d deltas and the digest all took the later reading;
- a real 82.65 vanished the moment the window widened past `3d`, and the axis then
  labelled the window's top as 81.85 — a range the window does not have;
- and the digest prompt states, verbatim, that `weight_kg` "is the weigh-in on the
  *morning* of target_date, **before** any of the food listed", while being handed the
  11:07 one. The whole temporal-framing block, `next_morning_kg` included, rests on that.

Two concepts now:

- **latest** — "what do I weigh now". The WEIGHT header's headline, and BMI beside it.
- **morning** — the day's first, fasted, comparable reading. The trend line, the deltas
  and the digest.

Picking the *later* reading was not neutral, either: on real data every multi-reading day
was weighed early and again mid-morning, so latest-wins took the low end of every day.
"""

import datetime as dt
from zoneinfo import ZoneInfo

from daylogs.body import (
    add_weight,
    latest_weight,
    morning_weight,
    weight_delta,
    weight_points_between,
    weight_series_between,
)

TZ = ZoneInfo("America/Toronto")


def _at(day: str, hh: int, mm: int) -> int:
    return int(dt.datetime.fromisoformat(f"{day}T{hh:02d}:{mm:02d}").replace(tzinfo=TZ).timestamp())


def _seed(db) -> None:
    """The real shape: an early reading and a mid-morning one, the early one heavier."""
    add_weight(db, kg=82.65, date="2026-09-04", at=_at("2026-09-04", 3, 36))
    add_weight(db, kg=81.75, date="2026-09-04", at=_at("2026-09-04", 11, 7))
    add_weight(db, kg=81.85, date="2026-09-01", at=_at("2026-09-01", 2, 47))
    add_weight(db, kg=80.65, date="2026-09-01", at=_at("2026-09-01", 12, 0))


# ── the two concepts ─────────────────────────────────────────────────────


def test_morning_weight_is_the_days_first_reading(db):
    _seed(db)
    assert morning_weight(db, on_or_before="2026-09-04")["kg"] == 82.65


def test_latest_weight_is_still_the_days_last_reading(db):
    """The header's headline answers "what do I weigh now", and that is unchanged."""
    _seed(db)
    assert latest_weight(db, on_or_before="2026-09-04")["kg"] == 81.75


def test_the_two_differ_on_a_day_weighed_twice(db):
    _seed(db)
    assert morning_weight(db, on_or_before="2026-09-04")["kg"] != (
        latest_weight(db, on_or_before="2026-09-04")["kg"]
    )


def test_they_agree_on_a_day_weighed_once(db):
    add_weight(db, kg=80.0, date="2026-09-03", at=_at("2026-09-03", 7, 0))
    assert (
        morning_weight(db, on_or_before="2026-09-03")["kg"]
        == latest_weight(db, on_or_before="2026-09-03")["kg"]
    )


def test_morning_weight_falls_back_to_an_earlier_day(db):
    """Same staleness rule `latest_weight` follows: a week-old reading is the best
    available answer, not a reason to show nothing. It is that day's *morning* reading."""
    _seed(db)
    assert morning_weight(db, on_or_before="2026-09-03")["kg"] == 81.85
    assert morning_weight(db, on_or_before="2026-09-03")["date"] == "2026-09-01"


def test_morning_weight_is_none_before_the_first_weigh_in(db):
    _seed(db)
    assert morning_weight(db, on_or_before="2026-08-01") is None


# ── the trend takes the morning reading ──────────────────────────────────


def test_the_collapsed_series_keeps_each_days_first_reading(db):
    _seed(db)
    got = weight_series_between(db, start="2026-09-01", end="2026-09-04")
    assert [(d, kg) for d, kg, _ in got] == [("2026-09-01", 81.85), ("2026-09-04", 82.65)]


def test_the_series_reports_the_time_of_the_reading_it_kept(db):
    """The chart places a point at the hour it was taken, so the timestamp has to be the
    kept reading's own — not the day's last."""
    _seed(db)
    got = {d: at for d, _, at in weight_series_between(db, start="2026-09-01", end="2026-09-04")}
    assert got["2026-09-04"] == _at("2026-09-04", 3, 36)


def test_a_delta_compares_morning_to_morning(db):
    """Mixing a morning reading against an evening one measures the time of day as much
    as the trend."""
    add_weight(db, kg=80.0, date="2026-08-29", at=_at("2026-08-29", 4, 0))
    add_weight(db, kg=79.0, date="2026-08-29", at=_at("2026-08-29", 20, 0))
    add_weight(db, kg=81.0, date="2026-09-04", at=_at("2026-09-04", 4, 0))
    add_weight(db, kg=80.5, date="2026-09-04", at=_at("2026-09-04", 20, 0))
    # 81.0 − 80.0, both mornings. Latest-wins would have said 80.5 − 79.0 = +1.5.
    assert weight_delta(db, end_date="2026-09-04", days=7) == 1.0


def test_every_reading_is_still_available_for_the_zoomed_in_view(db):
    """`1d`/`3d` plot every reading; the collapse is only the wide-window rule."""
    _seed(db)
    got = weight_points_between(db, start="2026-09-04", end="2026-09-04")
    assert [kg for _, kg in got] == [82.65, 81.75]


# ── the digest's stated premise ──────────────────────────────────────────


def test_the_payload_reports_the_mornings_weigh_in(db, tmp_path):
    """The prompt says `weight_kg` is the morning reading before any of the listed food.
    It was handed the day's *last* reading, so on any day weighed twice the claim was
    false — and the whole temporal-framing block rests on it."""
    from daylogs.config import Config
    from daylogs.summary import build_payload

    _seed(db)
    cfg = Config(root=tmp_path, db_path=tmp_path / "d.db",
                 inbox_dir=tmp_path / "i", memory_path=tmp_path / "m.md")
    assert build_payload(db, cfg, date="2026-09-04")["body"]["weight_kg"] == 82.65


def test_next_morning_kg_is_also_a_morning_reading(db, tmp_path):
    """It is named for a morning and was the next day's last reading, so
    `next_morning_delta` compared an evening against a morning and called it overnight."""
    from daylogs.config import Config
    from daylogs.summary import build_payload

    _seed(db)
    add_weight(db, kg=81.0, date="2026-09-05", at=_at("2026-09-05", 4, 0))
    add_weight(db, kg=80.2, date="2026-09-05", at=_at("2026-09-05", 19, 0))
    b = build_payload(db, cfg=Config(
        root=tmp_path, db_path=tmp_path / "d.db",
        inbox_dir=tmp_path / "i", memory_path=tmp_path / "m.md",
    ), date="2026-09-04")["body"]
    assert b["next_morning_kg"] == 81.0
    # 81.0 − 82.65, morning to morning.
    assert b["next_morning_delta"] == -1.65


def test_the_prompt_no_longer_claims_more_than_the_payload_delivers():
    from daylogs.summary import SYSTEM_PROMPT

    assert "*first* weigh-in of target_date" in SYSTEM_PROMPT
