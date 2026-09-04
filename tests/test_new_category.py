"""Adding a category from inside the app, and budgeting it for the month on screen.

Adding one used to mean editing `config.toml` by hand and restarting: `update_config`
writes top-level scalars only, and deliberately inserts them *before* the first table
header, so it cannot write a `[[category]]` block at all.

Two rules that pull in opposite directions and both matter:

- a **scalar** must land before the first table header, or TOML reads it as a field of
  that table and the setting is silently never read again;
- a **table block** must land after everything, for the same reason from the other side.

So `add_category` appends where `update_config` prepends, on purpose.
"""

import tomllib

import pytest

from daylogs.categories import all_categories, auto_color, slugs
from daylogs.config import add_category, load_config
from daylogs.parse import ParseError, parse_category

# ── the grammar ──────────────────────────────────────────────────────────


def test_a_slug_alone_is_enough():
    r = parse_category("gym")
    assert (r.slug, r.display) == ("gym", None)


def test_the_rest_of_the_line_is_the_display_name():
    r = parse_category("gym Gym & Pool")
    assert (r.slug, r.display) == ("gym", "Gym & Pool")


def test_the_slug_is_lowercased_but_the_display_name_is_not():
    """`!GYM` is not a token anyone types, and `all_categories` matches on the slug."""
    r = parse_category("GYM Gym")
    assert (r.slug, r.display) == ("gym", "Gym")


@pytest.mark.parametrize("bad", ["gym/pool", "gym.pool", "gym!", "!gym", "gym#1", "-gym"])
def test_a_slug_that_could_not_be_typed_as_a_sigil_token_is_rejected(bad):
    """The slug's whole job is to be typed as `!gym`, so it has to be one sigil-free
    token of the characters the tokeniser leaves alone.

    Only the *first* token is the slug — `gym club` is the valid slug-plus-display form,
    not a bad slug, which is why it is not in this list.
    """
    with pytest.raises(ParseError):
        parse_category(bad)


def test_a_space_makes_the_rest_a_display_name_not_a_bad_slug():
    assert parse_category("gym club").display == "club"


def test_an_empty_line_is_rejected():
    for raw in ("", "   "):
        with pytest.raises(ParseError, match="slug"):
            parse_category(raw)


def test_a_slug_that_already_exists_is_rejected_loudly(make_cfg):
    """`all_categories` silently drops a config entry that shadows a built-in — which is
    right for a hand-edited file and wrong for a prompt, where the user would get no
    feedback at all and assume it worked."""
    with pytest.raises(ParseError, match="grocery"):
        parse_category("grocery Groceries", known_slugs=slugs())


def test_a_slug_that_a_previous_add_created_is_also_rejected(make_cfg):
    cfg = make_cfg(extra_categories=(("gym", "Gym", ""),))
    with pytest.raises(ParseError, match="gym"):
        parse_category("gym Again", known_slugs=slugs(cfg))


def test_without_a_known_slug_set_nothing_is_rejected_for_existing():
    """The grammar stays pure: it takes the vocabulary rather than reaching for config."""
    assert parse_category("grocery").slug == "grocery"


# ── writing it to config.toml ────────────────────────────────────────────


def test_adding_a_category_writes_a_readable_block(tmp_path):
    add_category(tmp_path / "config.toml", slug="gym", display="Gym")
    data = tomllib.loads((tmp_path / "config.toml").read_text())
    assert data["category"] == [{"slug": "gym", "display": "Gym"}]


def test_the_display_name_is_omitted_when_absent(tmp_path):
    """`all_categories` already falls back to the slug, so writing `display = "gym"`
    would just be noise that goes stale if the fallback ever changes."""
    add_category(tmp_path / "config.toml", slug="gym", display=None)
    data = tomllib.loads((tmp_path / "config.toml").read_text())
    assert data["category"] == [{"slug": "gym"}]


def test_a_second_category_appends_rather_than_replacing(tmp_path):
    add_category(tmp_path / "config.toml", slug="gym", display="Gym")
    add_category(tmp_path / "config.toml", slug="books", display="Books")
    data = tomllib.loads((tmp_path / "config.toml").read_text())
    assert [c["slug"] for c in data["category"]] == ["gym", "books"]


def test_existing_scalars_comments_and_blocks_survive(tmp_path):
    """The file is edited as text precisely so a hand-written comment is not lost, and
    a category added by the prompt must not cost you the ones you wrote yourself."""
    path = tmp_path / "config.toml"
    path.write_text(
        "# my settings\n"
        'timezone = "Asia/Tokyo"\n'
        "height_cm = 180.0\n"
        "\n"
        "# a category I added by hand\n"
        "[[category]]\n"
        'slug = "books"\n'
        'color = "#123456"\n'
    )
    add_category(path, slug="gym", display="Gym")
    text = path.read_text()
    assert "# my settings" in text
    assert "# a category I added by hand" in text
    data = tomllib.loads(text)
    assert data["timezone"] == "Asia/Tokyo"
    assert data["height_cm"] == 180.0
    assert [c["slug"] for c in data["category"]] == ["books", "gym"]
    assert data["category"][0]["color"] == "#123456"


def test_a_block_lands_after_the_scalars_not_among_them(tmp_path):
    """The mirror image of `update_config`'s rule. A scalar written after a table header
    becomes a field of that table; a table header written among the scalars swallows
    every scalar below it. Both are silent — the file still parses."""
    path = tmp_path / "config.toml"
    path.write_text('timezone = "UTC"\n')
    add_category(path, slug="gym", display="Gym")
    add_category(path, slug="books", display=None)
    lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    first_header = next(i for i, ln in enumerate(lines) if ln.startswith("[["))
    assert lines[first_header - 1].startswith("timezone"), lines
    data = tomllib.loads(path.read_text())
    assert data["timezone"] == "UTC", "a scalar was swallowed by the table block"


def test_the_new_category_is_live_on_the_next_load(tmp_path):
    """No restart: the value the app re-reads has to carry it."""
    add_category(tmp_path / "config.toml", slug="gym", display="Gym")
    cfg = load_config(tmp_path)
    assert "gym" in slugs(cfg)
    added = next(c for c in all_categories(cfg) if c.slug == "gym")
    assert added.display == "Gym"
    assert added.color == auto_color("gym"), "the colour should be the stable hash"


def test_a_quote_in_the_display_name_does_not_break_the_file(tmp_path):
    path = tmp_path / "config.toml"
    add_category(path, slug="gym", display='He said "hi"')
    data = tomllib.loads(path.read_text())
    assert data["category"][0]["display"] == 'He said "hi"'


# ── from inside the app ──────────────────────────────────────────────────
# The two keys are one flow: `n` adds a category, `b` gives it a budget. `n`'s toast
# says so, because a brand-new category is not yet a row in the pane — `summarize_span`
# lists only categories with a budget or a spend — so there is nothing on screen to
# confirm the write.

import datetime as dt  # noqa: E402

from helpers import all_expenses, go_money  # noqa: E402

from daylogs.money import add_expense, list_budget, upsert_budget  # noqa: E402

NOW = dt.datetime(2026, 8, 28, 9, 0)


async def test_n_adds_a_category_and_it_is_usable_on_the_next_keystroke(
    make_app, db, type_into, tmp_path
):
    """No restart. `hints.vocab_for` resolving at call time is what makes this work, and
    this is the case it was written for."""
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await go_money(pilot, app)
        await pilot.press("n")
        await type_into(pilot, "gym Gym & Pool")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("e")
        await type_into(pilot, "20 protein !gym")
        await pilot.press("enter")
        await pilot.pause()
    rows = all_expenses(db)
    assert len(rows) == 1, "the expense was rejected — the new slug was not live"
    assert rows[0]["category"] == "gym"
    assert tomllib.loads((tmp_path / "config.toml").read_text())["category"] == [
        {"slug": "gym", "display": "Gym & Pool"}
    ]


async def test_the_new_category_toast_names_the_key_and_the_month(make_app, type_into):
    said = []
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await go_money(pilot, app)
        app.notify = lambda msg, **kw: said.append(str(msg))
        await pilot.press("n")
        await type_into(pilot, "gym Gym")
        await pilot.press("enter")
        await pilot.pause()
    assert said, "adding a category said nothing at all"
    assert "gym" in said[0] and "b" in said[0]
    assert "2026-08" in said[0], f"the toast has to name the month b writes to: {said[0]}"


async def test_a_duplicate_slug_reopens_the_prompt_and_writes_nothing(
    make_app, type_into, tmp_path
):
    """The app's error policy, applied to a new prompt: a ParseError keeps the line."""
    app = make_app(now=lambda: NOW)
    async with app.run_test() as pilot:
        await go_money(pilot, app)
        await pilot.press("n")
        await type_into(pilot, "grocery Groceries")
        await pilot.press("enter")
        await pilot.pause()
        assert app.prompt.is_open is True
        assert "grocery Groceries" in app.prompt.value
    assert not (tmp_path / "config.toml").exists(), "a rejected line still wrote the file"


async def test_b_prefills_the_selected_categorys_line(make_app, db):
    """`render_budget` had no caller before this: no budget row is selectable anywhere,
    so the one renderer for the grammar was dead code."""
    upsert_budget(db, month="2026-08", name="Food", category="grocery", amount=500.0)
    add_expense(db, amount=12.0, description="milk", category="grocery", date="2026-08-04")
    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 34)) as pilot:
        await go_money(pilot, app)
        await pilot.press("b")
        await pilot.pause()
        assert app.prompt.value == "500.00 Food !grocery"


async def test_b_is_blank_when_the_selected_category_has_no_budget_yet(make_app, db):
    """Half a line is a prefill that cannot be submitted — `parse_budget` requires a
    leading amount — so a category with no line is typed fresh."""
    add_expense(db, amount=12.0, description="lunch", category="restaurant", date="2026-08-04")
    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 34)) as pilot:
        await go_money(pilot, app)
        await pilot.press("b")
        await pilot.pause()
        assert app.prompt.value == ""


async def test_b_is_blank_on_the_expenses_pane(make_app, db):
    """An expense row is not a category, and its id would prefill someone else's line."""
    upsert_budget(db, month="2026-08", name="Food", category="grocery", amount=500.0)
    add_expense(db, amount=12.0, description="milk", category="grocery", date="2026-08-04")
    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 34)) as pilot:
        money_tab = await go_money(pilot, app)
        await pilot.press("tab")
        await pilot.pause()
        assert money_tab.view.pane == "expenses"
        await pilot.press("b")
        await pilot.pause()
        assert app.prompt.value == ""


async def test_b_writes_to_the_month_on_screen_and_says_which(make_app, db, type_into):
    """`[` walks the anchor back. Writing this month's budget while looking at July is
    the same class of wrongness as a header naming a window the query ignores."""
    said = []
    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 34)) as pilot:
        await go_money(pilot, app)
        await pilot.press("left_square_bracket")
        await pilot.pause()
        app.notify = lambda msg, **kw: said.append(str(msg))
        await pilot.press("b")
        await type_into(pilot, "500 !grocery")
        await pilot.press("enter")
        await pilot.pause()
    assert list_budget(db, month="2026-07"), "b wrote to the wrong month"
    assert list_budget(db, month="2026-08") == []
    assert "2026-07" in said[0], f"the toast must name the month: {said[0]}"


async def test_editing_a_budget_replaces_the_line_rather_than_adding_one(
    make_app, db, type_into
):
    """`upsert_budget` is keyed on (month, name), so a changed amount has always replaced
    the line. What was missing was seeing the current value in the prompt."""
    upsert_budget(db, month="2026-08", name="Food", category="grocery", amount=500.0)
    add_expense(db, amount=12.0, description="milk", category="grocery", date="2026-08-04")
    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 34)) as pilot:
        await go_money(pilot, app)
        await pilot.press("b")
        await pilot.pause()
        app.prompt.value = "650 Food !grocery"
        await pilot.press("enter")
        await pilot.pause()
    rows = list_budget(db, month="2026-08")
    assert len(rows) == 1, f"editing added a second line: {[dict(r) for r in rows]}"
    assert rows[0]["amount"] == 650.0


async def test_b_is_blank_on_a_grouped_expense_header_too(make_app, db):
    """The reachable half of the pane guard. A group header on the expenses pane is the
    only row outside the categories pane that carries a slug, so without the pane check
    `b` there would prefill a budget line from a pane showing spend — one key meaning two
    things depending on whether `G` is on."""
    upsert_budget(db, month="2026-08", name="Food", category="grocery", amount=500.0)
    add_expense(db, amount=12.0, description="milk", category="grocery", date="2026-08-04")
    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 34)) as pilot:
        money_tab = await go_money(pilot, app)
        await pilot.press("tab")
        await pilot.press("G")
        await pilot.pause()
        assert (money_tab.view.pane, money_tab.view.grouped) == ("expenses", True)
        assert money_tab._selected_group() == "grocery", "not on the group header"
        await pilot.press("b")
        await pilot.pause()
        assert app.prompt.value == ""


async def test_two_lines_in_one_category_prefill_the_newest(make_app, db):
    """`budget` is UNIQUE(month, name), not (month, category), so a Rent line and a
    Storage line can both be housing while the pane shows one summed row. Which one `b`
    offers is arbitrary; that it is *stable* is not, so the newest is pinned here. The
    pane's own figures keep summing both — this is a lookup for editing, not a total."""
    upsert_budget(db, month="2026-08", name="Rent", category="housing", amount=1200.0)
    upsert_budget(db, month="2026-08", name="Storage", category="housing", amount=100.0)
    add_expense(db, amount=12.0, description="key", category="housing", date="2026-08-04")
    app = make_app(now=lambda: NOW)
    async with app.run_test(size=(120, 34)) as pilot:
        await go_money(pilot, app)
        await pilot.press("b")
        await pilot.pause()
        assert app.prompt.value == "100.00 Storage !housing"
        app.prompt.value = "150 Storage !housing"
        await pilot.press("enter")
        await pilot.pause()
    rows = {r["name"]: r["amount"] for r in list_budget(db, month="2026-08")}
    assert rows == {"Rent": 1200.0, "Storage": 150.0}, "editing one line disturbed the other"
