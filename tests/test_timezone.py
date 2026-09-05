"""One zone, used by everything that stores or shows a clock time.

The bug this closes: `Config.timezone` defaulted to the literal `"America/Toronto"`
while `fmt.hhmm` rendered in the *machine's* zone. On a machine in any other zone the
two disagreed by the offset, so an edit's prefill round-trip — render a stored
timestamp, parse it back — moved the row. Food was affected as much as anything;
`test_food_round_trips` simply never asserted the timestamp.

The fix is one zone: `timezone` defaults to the machine's own, `h` can set it, and
every render takes it explicitly so a call site cannot quietly fall back to a
different one.
"""

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from daylogs.body import restamp
from daylogs.config import Config, load_config, system_timezone
from daylogs.fmt import hhmm, wall
from daylogs.parse import ParseError, parse_activity, parse_food, parse_profile, render_food

# 2026-08-27 07:05:43 in Toronto (UTC-4 in August) is 11:05:43 UTC.
STAMP = int(dt.datetime(2026, 8, 27, 7, 5, 43, tzinfo=ZoneInfo("America/Toronto")).timestamp())


# ── the default is the machine, not a literal ────────────────────────────


def test_the_detected_zone_is_one_zoneinfo_accepts():
    ZoneInfo(system_timezone())


def test_tz_in_the_environment_wins():
    """Which is also how the suite pins a zone: running under `TZ=UTC` has to make the
    config agree with the process, or the two disagree inside the tests themselves."""
    import os
    from unittest import mock

    with mock.patch.dict(os.environ, {"TZ": "Asia/Tokyo"}):
        assert system_timezone() == "Asia/Tokyo"


def test_a_nonsense_tz_in_the_environment_is_ignored():
    import os
    from unittest import mock

    with mock.patch.dict(os.environ, {"TZ": "Mars/Olympus_Mons"}):
        ZoneInfo(system_timezone())


def test_the_default_is_the_detected_zone(tmp_path):
    assert load_config(tmp_path).timezone == system_timezone()


def test_an_explicit_zone_overrides_the_machine(tmp_path):
    (tmp_path / "config.toml").write_text('timezone = "Europe/Berlin"\n')
    assert load_config(tmp_path).timezone == "Europe/Berlin"


def test_an_unknown_zone_in_the_file_falls_back_rather_than_crashing(tmp_path):
    """config.toml is hand-edited, and a typo there must not stop the app — the same
    stance the theme and the activity level take."""
    (tmp_path / "config.toml").write_text('timezone = "Mars/Olympus_Mons"\n')
    assert load_config(tmp_path).timezone == system_timezone()


# ── rendering takes the zone explicitly ──────────────────────────────────


def test_wall_reads_a_stamp_in_the_zone_it_is_given():
    assert wall(STAMP, "America/Toronto").strftime("%H:%M") == "07:05"
    assert wall(STAMP, "UTC").strftime("%H:%M") == "11:05"


def test_hhmm_reads_a_stamp_in_the_zone_it_is_given():
    assert hhmm(STAMP, "America/Toronto") == "07:05"
    assert hhmm(STAMP, "UTC") == "11:05"


def test_hhmm_requires_a_zone():
    """No default. A default is exactly how the old bug hid: every call site looked
    correct and silently used the machine's zone instead of the configured one."""
    with pytest.raises(TypeError):
        hhmm(STAMP)


def test_wall_honours_daylight_saving_per_timestamp():
    """A captured fixed offset would render a January stamp with August's offset. The
    zone name carries the rules, which is why the config stores a name."""
    january = int(dt.datetime(2026, 1, 15, 7, 5, tzinfo=ZoneInfo("America/Toronto")).timestamp())
    assert wall(january, "America/Toronto").strftime("%H:%M") == "07:05"
    assert wall(STAMP, "America/Toronto").strftime("%H:%M") == "07:05"
    # Same wall clock, four hours apart in UTC terms — the offsets really do differ.
    assert wall(january, "UTC").strftime("%H:%M") == "12:05"
    assert wall(STAMP, "UTC").strftime("%H:%M") == "11:05"


def test_restamp_rebuilds_the_stamp_in_the_zone_it_is_given():
    """The other half of `restamp`, and the half the comparison tests cannot see: the
    *value* it returns. Built in the machine's zone instead, an edited time would land
    at the right clock reading in the wrong zone — silently off by the offset.
    """
    for tz, at_that_clock in (("UTC", "2026-08-27 08:30"), ("America/Toronto", "2026-08-27 08:30")):
        out = restamp(STAMP, date="2026-08-27", hhmm="08:30", tz=tz)
        assert wall(out, tz).strftime("%Y-%m-%d %H:%M") == at_that_clock
    # And the two really are different instants — four hours apart in August, so a
    # zone-blind rebuild could not satisfy both lines above at once.
    assert restamp(STAMP, date="2026-08-27", hhmm="08:30", tz="UTC") != restamp(
        STAMP, date="2026-08-27", hhmm="08:30", tz="America/Toronto"
    )


def test_restamp_compares_in_the_zone_it_is_given():
    """`restamp` decides whether the minute moved. Comparing in a different zone than
    the line was rendered in makes every edit look like a time change and rewrites a
    column that is a tie-breaker."""
    assert restamp(STAMP, date="2026-08-27", hhmm="07:05", tz="America/Toronto") is None
    assert restamp(STAMP, date="2026-08-27", hhmm="11:05", tz="UTC") is None
    assert restamp(STAMP, date="2026-08-27", hhmm="07:05", tz="UTC") is not None


# ── the round trip the old contract could not make ───────────────────────


@pytest.mark.parametrize("tz", ["America/Toronto", "UTC", "Asia/Tokyo"])
def test_a_food_row_round_trips_to_the_minute(tz):
    """The assertion the old code could not make. `render_food` used the machine's zone
    and `parse_food` used the configured one, so this failed by the offset whenever they
    differed — which is the whole bug, and it was reachable from a plain `enter` on a
    food row.

    Zones where the stored `date` and the stamp's wall-clock date agree, which is every
    zone a row was actually entered in. The other case is the test below.
    """
    row = dict(description="oatmeal", kcal=350, date="2026-08-27", ate_at=STAMP)
    now = dt.datetime(2026, 8, 27, 19, 40, tzinfo=ZoneInfo(tz))
    got = parse_food(render_food(row, tz), now=now)
    assert got.description == "oatmeal"
    assert got.kcal == 350
    assert got.date == "2026-08-27"
    assert wall(got.at, tz).strftime("%Y-%m-%d %H:%M") == (
        wall(STAMP, tz).strftime("%Y-%m-%d %H:%M")
    )


@pytest.mark.parametrize(
    "tz", ["America/Toronto", "UTC", "Asia/Tokyo", "Pacific/Kiritimati", "Pacific/Midway"]
)
def test_rendering_a_food_row_is_stable_under_a_round_trip(tz):
    """The property the edit prompt actually needs: open it twice, submit unchanged
    twice, and nothing drifts.

    Stated as stability rather than as instant-preservation because those differ in one
    real case. `date` and `ate_at` are separate columns, and after a zone change they can
    disagree about which day the stamp falls on — a row stored on Aug 27 from Toronto is
    Aug 28 in Kiritimati (UTC+14). `date` is authoritative there: it is what every query
    filters on and what the user said the food belonged to, so the render keeps it and
    shows the time in the zone you are now in. Re-parsing that then moves `ate_at` onto
    the stated date, which is the consistent outcome — and it is *stable*, so it happens
    at most once rather than creeping on every edit.
    """
    row = dict(description="oatmeal", kcal=350, date="2026-08-27", ate_at=STAMP)
    now = dt.datetime(2026, 8, 27, 19, 40, tzinfo=ZoneInfo(tz))
    once = render_food(row, tz)
    parsed = parse_food(once, now=now)
    twice = render_food(
        dict(description=parsed.description, kcal=parsed.kcal, date=parsed.date,
             ate_at=parsed.at),
        tz,
    )
    assert twice == once, f"the edit prefill drifts in {tz}"


# ── the profile carries it ───────────────────────────────────────────────


def test_the_profile_accepts_a_zone_by_name():
    assert parse_profile("America/Toronto").timezone == "America/Toronto"
    assert parse_profile("UTC").timezone == "UTC"


def test_a_zone_does_not_collide_with_the_other_profile_fields():
    p = parse_profile("180 male 1990-01-01 desk Europe/Berlin")
    assert (p.height_cm, p.sex, p.birthday, p.activity) == (180.0, "male", "1990-01-01", "desk")
    assert p.timezone == "Europe/Berlin"


def test_a_zone_name_keeps_its_capitals():
    """`ZoneInfo` keys are case-sensitive, so the level and sex lookups must not be the
    thing that sees this word — they lowercase, and `america/toronto` is not a zone."""
    assert parse_profile("America/Toronto").timezone == "America/Toronto"


def test_a_word_that_is_neither_a_field_nor_a_zone_is_still_an_error():
    with pytest.raises(ParseError, match="purple"):
        parse_profile("purple")


def test_an_activity_line_is_unaffected_by_the_zone_setting():
    """A sanity check on the sigil grammar: adding a zone to the profile must not make
    a slash-containing word meaningful anywhere else."""
    r = parse_activity("gym 1h", now=dt.datetime(2026, 8, 27, 9, 0, tzinfo=ZoneInfo("UTC")))
    assert r.description == "gym 1h"


def test_the_config_field_round_trips_through_a_profile_input():
    from daylogs.parse import ProfileInput

    assert ProfileInput(timezone="Asia/Tokyo").fields() == {"timezone": "Asia/Tokyo"}


def test_a_configs_zone_is_always_usable(tmp_path):
    """Every reader does `ZoneInfo(cfg.timezone)`, so an unusable value is a crash on
    the next keystroke rather than a bad render."""
    for text in ('timezone = "UTC"\n', 'timezone = ""\n', "", 'timezone = "nope/nope"\n'):
        (tmp_path / "config.toml").write_text(text)
        ZoneInfo(load_config(tmp_path).timezone)


def test_a_config_built_directly_defaults_to_the_machines_zone(tmp_path):
    """The dataclass default, which `load_config` never reaches — it always resolves the
    zone itself. It matters anyway: the test fixtures and any direct construction get
    this value, so a literal here would put a hardcoded zone back into everything that
    does not go through the file, and the mismatch would be reintroduced inside the
    tests themselves.
    """
    cfg = Config(
        root=tmp_path,
        db_path=tmp_path / "d.db",
        inbox_dir=tmp_path / "inbox",
        memory_path=tmp_path / "m.md",
    )
    assert cfg.timezone == system_timezone()
    ZoneInfo(cfg.timezone)


def test_no_module_hardcodes_a_zone():
    """The bug in one assertion: a zone-name literal anywhere in the app's *code*.

    Checked through the AST rather than by grepping lines, because the docstrings
    explaining this very bug name the zone — a line-based check flags its own
    explanation. Docstrings are excluded; every other string constant is code.
    """
    import ast
    import pathlib

    def docstring_ids(tree):
        out = set()
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if (
                isinstance(body, list)
                and body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                out.add(id(body[0].value))
        return out

    offenders = []
    for path in (pathlib.Path(__file__).resolve().parents[1] / "daylogs").rglob("*.py"):
        tree = ast.parse(path.read_text())
        skip = docstring_ids(tree)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in skip
                # A zone name always has a region prefix, so this skips the thousands of
                # ordinary strings before doing a tz-database lookup on any of them.
                and "/" in node.value
                and _looks_like_zone(node.value)
            ):
                offenders.append(f"{path.name}:{node.lineno} {node.value!r}")
    assert not offenders, f"a zone name is hardcoded in the app: {offenders}"


def _looks_like_zone(text: str) -> bool:
    from daylogs.config import is_zone

    return is_zone(text)


# ── module purity ────────────────────────────────────────────────────────


def test_only_the_ui_layer_imports_textual():
    """CLAUDE.md names four modules as Textual-free — `chart.py`, `widgets.py`,
    `sigil.py`, `complete.py` — plus a data layer that must not import the UI at all, and
    nothing enforced any of it. `config.py` even carries a duplicated theme-name literal
    whose *only* purpose is preserving that property.

    An allowlist, not a list of pure modules. Enumerating the pure ones leaves a *new*
    pure module unprotected by default, which is the same failure as "three modules were
    once missing from the map". Adding an import to a pure module fails here; adding a
    genuinely new UI module means updating one set, deliberately.

    Transitive too: importing `daylogs.tui.anything` pulls Textual in, so it counts.
    """
    import ast
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "daylogs"
    impure: set[str] = set()
    for path in sorted(src.rglob("*.py")):
        rel = str(path.relative_to(src))
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(n == "textual" or n.startswith("textual.") for n in names):
                impure.add(rel)
            if any(n == "daylogs.tui" or n.startswith("daylogs.tui.") for n in names):
                impure.add(rel)

    allowed = {
        "tui/__init__.py",
        "tui/app.py",
        "tui/body_tab.py",
        "tui/chart.py",
        "tui/common.py",
        "tui/footer.py",
        "tui/help.py",
        "tui/hints.py",
        "tui/keymap.py",
        "tui/money_tab.py",
        "tui/progress.py",
        "tui/prompt.py",
        "tui/summary_tab.py",
        "tui/themes.py",
        "tui/widgets.py",
        "__main__.py",
    }
    assert impure <= allowed, (
        "these modules reach the UI layer and should not: "
        f"{sorted(impure - allowed)}"
    )


def test_the_modules_claimed_textual_free_really_are():
    """The four CLAUDE.md names outright, asserted by name as well as by the allowlist
    above — because these four are the ones whose whole point is unit-testing as plain
    functions, and a reader looking for that promise should find it stated."""
    import ast
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "daylogs"
    for rel in ("tui/chart.py", "tui/widgets.py", "sigil.py", "complete.py"):
        text = (src / rel).read_text()
        for node in ast.walk(ast.parse(text)):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            assert not any(m.split(".")[0] == "textual" for m in mods), (
                f"{rel} imports textual, and its docstring promises it does not"
            )
