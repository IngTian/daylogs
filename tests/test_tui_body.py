import datetime as dt
from zoneinfo import ZoneInfo

from helpers import go_body

from daylogs.body import add_food, add_weight, list_food, list_weight
from daylogs.estimate import Estimate

WEIGHT_TZ = ZoneInfo("America/Toronto")


async def test_w_logs_a_weight(make_app, db, type_into):
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("w")
        await type_into(pilot, "78.2")
        await pilot.press("enter")
        await pilot.pause()
    rows = list_weight(db)
    assert len(rows) == 1 and rows[0]["kg"] == 78.2


async def test_w_with_a_bad_value_writes_nothing(make_app, db, type_into):
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("w")
        await type_into(pilot, "heavy")
        await pilot.press("enter")
        await pilot.pause()
        assert app.is_running is True
    assert list_weight(db) == []


async def test_weight_header_renders_the_reading(make_app, db, type_into):
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("w")
        await type_into(pilot, "78.2")
        await pilot.press("enter")
        await pilot.pause()
        head = str(app.query_one("#weight-head").content)
    assert "78.2 kg" in head


async def test_f_with_explicit_calories_does_not_call_claude(make_app, db, type_into):
    called = []

    async def runner_json(**kw):
        called.append(kw)
        return Estimate(description="x", kcal=1)

    app = make_app(runner_json=runner_json)
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("f")
        await type_into(pilot, "salad =610")
        await pilot.press("enter")
        await pilot.pause()
        today = app.today()
    rows = list_food(db, date=today)
    assert len(rows) == 1
    assert (rows[0]["kcal"], rows[0]["source"]) == (610, "labeled")
    assert called == []


async def test_f_without_calories_estimates_then_logs_as_estimated(
    make_app, db, type_into, monkeypatch
):
    async def fake_from_text(**kw):
        assert kw["description"] == "chicken caesar salad"
        return Estimate(description="chicken caesar salad", kcal=610)

    monkeypatch.setattr("daylogs.tui.body_tab.estimate.from_text", fake_from_text)
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("f")
        await type_into(pilot, "chicken caesar salad")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        assert app.prompt.label == "confirm food"
        assert app.prompt.value == "chicken caesar salad =610"
        await pilot.press("enter")
        await pilot.pause()
        today = app.today()
    rows = list_food(db, date=today)
    assert len(rows) == 1
    assert (rows[0]["kcal"], rows[0]["source"]) == (610, "estimated")


async def test_an_estimate_can_be_corrected_before_accepting(
    make_app, db, type_into, monkeypatch
):
    async def fake_from_text(**kw):
        return Estimate(description="salad", kcal=610)

    monkeypatch.setattr("daylogs.tui.body_tab.estimate.from_text", fake_from_text)
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("f")
        await type_into(pilot, "salad")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        app.prompt.value = "salad with chicken =780"
        await pilot.press("enter")
        await pilot.pause()
        today = app.today()
    row = list_food(db, date=today)[0]
    assert (row["description"], row["kcal"], row["source"]) == (
        "salad with chicken",
        780,
        "estimated",
    )


async def test_estimate_failure_surfaces_and_logs_nothing(
    make_app, db, type_into, monkeypatch
):
    from daylogs.claude import ClaudeError

    async def boom(**kw):
        raise ClaudeError("no claude")

    monkeypatch.setattr("daylogs.tui.body_tab.estimate.from_text", boom)
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("f")
        await type_into(pilot, "mystery meal")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        assert app.prompt.is_open is False
        today = app.today()
    assert list_food(db, date=today) == []


async def test_p_uses_the_inbox_when_the_clipboard_is_empty(
    make_app, db, make_cfg, tmp_path, monkeypatch
):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    img = inbox / "meal.jpg"
    img.write_bytes(b"\xff\xd8\xff")

    monkeypatch.setattr("daylogs.tui.body_tab.photo.clipboard_image", lambda d: None)

    async def fake_from_image(**kw):
        assert "meal.jpg" in str(kw["image_path"])
        return Estimate(description="ribeye + eggs", kcal=910)

    monkeypatch.setattr("daylogs.tui.body_tab.estimate.from_image", fake_from_image)

    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("p")
        await pilot.pause()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        today = app.today()
    rows = list_food(db, date=today)
    assert len(rows) == 1 and rows[0]["kcal"] == 910
    assert not img.exists()
    assert (inbox / "processed" / "meal.jpg").exists()


async def test_a_failed_photo_estimate_leaves_the_inbox_file_pending(
    make_app, db, tmp_path, monkeypatch
):
    from daylogs.claude import ClaudeError

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    img = inbox / "meal.jpg"
    img.write_bytes(b"\xff\xd8\xff")

    monkeypatch.setattr("daylogs.tui.body_tab.photo.clipboard_image", lambda d: None)

    async def boom(**kw):
        raise ClaudeError("down")

    monkeypatch.setattr("daylogs.tui.body_tab.estimate.from_image", boom)

    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("p")
        await pilot.pause()
        await pilot.pause()
    assert img.exists()
    assert not (inbox / "processed").exists() or not list((inbox / "processed").iterdir())


async def test_p_prefers_the_clipboard_over_the_inbox(make_app, db, tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "meal.jpg").write_bytes(b"x")
    clip = tmp_path / "clip.png"
    clip.write_bytes(b"\x89PNG")

    monkeypatch.setattr("daylogs.tui.body_tab.photo.clipboard_image", lambda d: clip)
    seen = {}

    async def fake_from_image(**kw):
        seen["path"] = str(kw["image_path"])
        return Estimate(description="clip meal", kcal=100)

    monkeypatch.setattr("daylogs.tui.body_tab.estimate.from_image", fake_from_image)

    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("p")
        await pilot.pause()
        await pilot.pause()
    assert "clip.png" in seen["path"]
    assert (inbox / "meal.jpg").exists()


async def test_p_with_nothing_available_opens_the_path_prompt(make_app, db, monkeypatch):
    monkeypatch.setattr("daylogs.tui.body_tab.photo.clipboard_image", lambda d: None)
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("p")
        await pilot.pause()
        assert app.prompt.label == "photo path"


async def test_inbox_line_shows_pending_count(make_app, tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "a.jpg").write_bytes(b"x")
    (inbox / "b.jpg").write_bytes(b"x")
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.pause()
        line = app.query_one("#inbox-line")
        assert line.display is True
        assert "2 photos" in str(line.content)


async def test_inbox_line_hidden_when_empty(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.pause()
        assert app.query_one("#inbox-line").display is False


async def test_bracket_keys_move_the_viewing_date(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.pause()
        start = app.query_one("#body").viewing_date
        await pilot.press("[")
        assert app.query_one("#body").viewing_date < start
        await pilot.press("]")
        assert app.query_one("#body").viewing_date == start


async def test_tab_toggles_the_table_mode(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.pause()
        body = app.query_one("#body")
        assert body.table_mode == "food"
        # Three views now, so `tab` walks rather than toggles, and it must come all the
        # way back round rather than stopping at the end.
        await pilot.press("tab")
        assert body.table_mode == "activity"
        await pilot.press("tab")
        assert body.table_mode == "weight"
        await pilot.press("tab")
        assert body.table_mode == "food"


async def test_x_deletes_the_selected_food_row_and_u_restores_it(make_app, db):
    add_food(db, description="salad", kcal=610, source="labeled", date="2026-08-27", at=1)
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.pause()
        body = app.query_one("#body")
        body.viewing_date = "2026-08-27"
        body.reload()
        await pilot.pause()
        await pilot.press("x")
        await pilot.press("y")
        await pilot.pause()
        assert list_food(db, date="2026-08-27") == []
        await pilot.press("u")
        await pilot.pause()
    rows = list_food(db, date="2026-08-27")
    assert len(rows) == 1 and rows[0]["description"] == "salad"


async def test_x_then_n_cancels_the_delete(make_app, db):
    add_food(db, description="salad", kcal=610, source="labeled", date="2026-08-27", at=1)
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.pause()
        body = app.query_one("#body")
        body.viewing_date = "2026-08-27"
        body.reload()
        await pilot.pause()
        await pilot.press("x")
        await pilot.press("n")
        await pilot.pause()
    assert len(list_food(db, date="2026-08-27")) == 1


async def test_x_with_an_empty_table_does_not_crash(make_app, db):
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.pause()
        await pilot.press("x")
        await pilot.pause()
        assert app.is_running is True


async def test_x_deletes_a_weight_row_in_weight_mode(make_app, db):
    add_weight(db, kg=78.2, date="2026-08-27", at=1)
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.pause()
        await pilot.press("shift+tab")
        await pilot.pause()
        await pilot.press("x")
        await pilot.press("y")
        await pilot.pause()
    assert list_weight(db) == []


async def test_weight_series_renders_a_braille_chart(make_app, db):
    for day, kg in [("2026-08-25", 79.0), ("2026-08-26", 78.6), ("2026-08-27", 78.2)]:
        add_weight(db, kg=kg, date=day, at=int(day[-2:]))
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.pause()
        body = app.query_one("#body")
        body.viewing_date = "2026-08-27"
        body.reload()
        await pilot.pause()
        chart = str(app.query_one("#weight-chart").content)
    assert any(0x2800 <= ord(ch) <= 0x28FF for ch in chart)


async def test_food_header_omits_bmr_without_a_profile(make_app, db):
    add_food(db, description="salad", kcal=610, source="labeled", date="2026-08-27", at=1)
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.pause()
        body = app.query_one("#body")
        body.viewing_date = "2026-08-27"
        body.reload()
        await pilot.pause()
        head = str(app.query_one("#food-head").content)
    assert "610 kcal in" in head
    assert "BMR" not in head


async def test_food_header_shows_net_with_a_profile(make_app, make_cfg, db):
    add_weight(db, kg=80.0, date="2026-08-27", at=1)
    add_food(db, description="salad", kcal=610, source="labeled", date="2026-08-27", at=2)
    cfg = make_cfg(height_cm=180, sex="male", birthday="1996-08-27")
    app = make_app(cfg=cfg)
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.pause()
        body = app.query_one("#body")
        body.viewing_date = "2026-08-27"
        body.reload()
        await pilot.pause()
        head = str(app.query_one("#food-head").content)
    assert "BMR" in head and "net" in head


async def test_photo_path_prompt_rejects_a_non_image(make_app, tmp_path, type_into, monkeypatch):
    monkeypatch.setattr("daylogs.tui.body_tab.photo.clipboard_image", lambda d: None)
    bad = tmp_path / "notes.txt"
    bad.write_text("x")
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("p")
        await pilot.pause()
        app.prompt.value = str(bad)
        await pilot.press("enter")
        await pilot.pause()
        assert app.is_running is True


async def test_stale_weight_is_labelled_with_its_date(make_app, db):
    add_weight(db, kg=80.0, date="2026-07-07", at=1)
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.pause()
        body = app.query_one("#body")
        body.viewing_date = "2026-08-27"
        body.reload()
        await pilot.pause()
        head = str(app.query_one("#weight-head").content)
    assert "80 kg" in head
    assert "last weighed" in head and "Jul 07" in head


async def test_todays_weight_is_not_labelled_stale(make_app, db):
    add_weight(db, kg=78.2, date="2026-08-27", at=1)
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.pause()
        body = app.query_one("#body")
        body.viewing_date = "2026-08-27"
        body.reload()
        await pilot.pause()
        head = str(app.query_one("#weight-head").content)
    assert "last weighed" not in head


# ── profile ──────────────────────────────────────────────────────────────


def _energy(app) -> str:
    from textual.widgets import Static

    content = app.query_one("#energy-body", Static).content
    return content if isinstance(content, str) else content.plain


async def test_energy_panel_names_the_key_not_the_config_file(make_app):
    """Telling someone to edit config.toml is how this panel stayed empty: the
    instruction was correct and nobody was going to leave the app to follow it."""
    app = make_app()
    async with app.run_test(size=(110, 34)) as pilot:
        await pilot.pause()
        text = _energy(app)
    assert "press h" in text
    assert "config.toml" not in text


async def test_h_sets_the_profile_and_bmr_appears_at_once(make_app, db, type_into, tmp_path):
    app = make_app()
    async with app.run_test(size=(110, 34)) as pilot:
        await go_body(pilot, app)
        add_weight(db, kg=80.0, date="2026-08-28", at=1)
        await pilot.press("h")
        await type_into(pilot, "182 male 1995-06-15")
        await pilot.press("enter")
        await pilot.pause()
        text = _energy(app)
        cfg = app.cfg
    assert "BMR" in text
    assert "press h" not in text
    assert (cfg.height_cm, cfg.sex, cfg.birthday) == (182.0, "male", "1995-06-15")
    assert (tmp_path / "config.toml").exists()


async def test_profile_prompt_prefills_with_what_is_already_set(make_app, type_into):
    app = make_app()
    async with app.run_test(size=(110, 34)) as pilot:
        await go_body(pilot, app)
        await pilot.press("h")
        await type_into(pilot, "182 male 1995-06-15")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("h")
        await pilot.pause()
        prefill = app.prompt.value
    assert "182" in prefill and "male" in prefill and "1995-06-15" in prefill


async def test_a_partial_profile_keeps_the_other_fields(make_app, type_into):
    app = make_app()
    async with app.run_test(size=(110, 34)) as pilot:
        await go_body(pilot, app)
        await pilot.press("h")
        await type_into(pilot, "182 male 1995-06-15")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("h")
        app.prompt.value = ""          # clear the prefill, type only a height
        await type_into(pilot, "184")
        await pilot.press("enter")
        await pilot.pause()
        cfg = app.cfg
    assert cfg.height_cm == 184.0
    assert (cfg.sex, cfg.birthday) == ("male", "1995-06-15")


async def test_a_bad_profile_line_keeps_the_text_and_writes_nothing(make_app, type_into):
    app = make_app()
    async with app.run_test(size=(110, 34)) as pilot:
        await go_body(pilot, app)
        await pilot.press("h")
        await type_into(pilot, "purple")
        await pilot.press("enter")
        await pilot.pause()
        still_open = app.prompt.is_open
        kept = app.prompt.value
        cfg = app.cfg
    assert still_open is True
    assert kept == "purple"
    assert cfg.height_cm is None


async def test_weight_deltas_are_coloured_by_direction(make_app, db):
    """Down is good — an assumption, since daylogs stores no goal weight. The arrow
    carries the direction either way, so colour is emphasis, not the only signal."""
    import datetime as dt

    from daylogs.tui.widgets import BAD, GOOD

    now = lambda: dt.datetime(2026, 8, 28, 9, 0)  # noqa: E731
    add_weight(db, kg=82.0, date="2026-08-21", at=1)
    add_weight(db, kg=80.0, date="2026-08-28", at=2)
    app = make_app(now=now)
    async with app.run_test(size=(110, 34)) as pilot:
        await pilot.pause()
        head = str(app.query_one("#weight-head").content)
    assert GOOD in head
    assert BAD not in head


# ── editing a row with enter ─────────────────────────────────────────────


async def test_enter_on_a_weight_row_opens_it_prefilled(make_app, db):
    """Body had no key_activate at all, so enter did nothing here."""
    add_weight(db, kg=78.2, date="2026-08-27", at=1, note="post-run")
    app = make_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await go_body(pilot, app)
        # shift+tab, not tab: the strip is weight / food / activity and food is the
        # default, so `weight` is one step *back* along it.
        await pilot.press("shift+tab")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        label, value = app.prompt.label, app.prompt.value
    assert label == "weigh"
    assert "78.2" in value and "post-run" in value and "2026-08-27" in value


async def test_editing_a_weight_updates_in_place(make_app, db, type_into):
    add_weight(db, kg=78.2, date="2026-08-27", at=1, note="post-run")
    original = list_weight(db)[0]["id"]
    app = make_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await go_body(pilot, app)
        await pilot.press("shift+tab")
        await pilot.press("enter")
        await pilot.pause()
        app.prompt.value = ""
        await type_into(pilot, "81.5")
        await pilot.press("enter")
        await pilot.pause()
    rows = list_weight(db)
    assert len(rows) == 1, "an edit must not insert a second row"
    assert rows[0]["id"] == original
    assert rows[0]["kg"] == 81.5
    assert rows[0]["note"] == "", "what's on the line is authoritative; no note = clear"


async def test_editing_a_weight_never_restamps_the_timestamp(make_app, db, type_into):
    """measured_at is the tie-breaker that decides which of a day's readings counts
    (weight_series takes MAX per day), so an edit must not touch it."""
    add_weight(db, kg=78.2, date="2026-08-27", at=1787223943, note="")
    app = make_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await go_body(pilot, app)
        await pilot.press("shift+tab")
        await pilot.press("enter")
        await pilot.pause()
        app.prompt.value = ""
        await type_into(pilot, "81.5")
        await pilot.press("enter")
        await pilot.pause()
    assert list_weight(db)[0]["measured_at"] == 1787223943


async def test_undoing_an_edit_restores_rather_than_duplicates(make_app, db, type_into):
    """The undo replay used to be a plain INSERT, which is right for a delete and
    wrong for an edit."""
    add_weight(db, kg=78.2, date="2026-08-27", at=1, note="post-run")
    app = make_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await go_body(pilot, app)
        await pilot.press("shift+tab")
        await pilot.press("enter")
        await pilot.pause()
        app.prompt.value = ""
        await type_into(pilot, "99.9")
        await pilot.press("enter")
        await pilot.pause()
        assert list_weight(db)[0]["kg"] == 99.9
        await pilot.press("u")
        await pilot.pause()
    rows = list_weight(db)
    assert len(rows) == 1, "undo of an edit must not insert a second row"
    assert rows[0]["kg"] == 78.2
    assert rows[0]["note"] == "post-run"


async def test_a_bad_edit_keeps_the_text_and_changes_nothing(make_app, db, type_into):
    add_weight(db, kg=78.2, date="2026-08-27", at=1)
    app = make_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await go_body(pilot, app)
        await pilot.press("shift+tab")
        await pilot.press("enter")
        await pilot.pause()
        app.prompt.value = ""
        await type_into(pilot, "heavy")
        await pilot.press("enter")
        await pilot.pause()
        still_open = app.prompt.is_open
        kept = app.prompt.value
    assert still_open is True
    assert kept == "heavy"
    assert list_weight(db)[0]["kg"] == 78.2


async def test_enter_on_a_food_row_edits_it_and_keeps_its_source(make_app, db, type_into):
    """`source` (labelled vs estimated) is provenance the digest reads; editing a
    description must not rewrite it."""
    import datetime as dt

    add_food(db, description="oatmeal", kcal=350, date="2026-08-28", at=1787223943,
             source="estimated")
    now = lambda: dt.datetime(2026, 8, 28, 9, 0)  # noqa: E731
    app = make_app(now=now)
    async with app.run_test(size=(120, 30)) as pilot:
        await go_body(pilot, app)
        await pilot.press("enter")
        await pilot.pause()
        assert app.prompt.label == "food"
        app.prompt.value = ""
        await type_into(pilot, "oatmeal with berries =400")
        await pilot.press("enter")
        await pilot.pause()
    rows = list_food(db, date="2026-08-28")
    assert len(rows) == 1
    assert rows[0]["description"] == "oatmeal with berries"
    assert rows[0]["kcal"] == 400
    assert rows[0]["source"] == "estimated"
    assert rows[0]["ate_at"] == 1787223943, "an unchanged minute keeps the seconds"


async def test_dropping_kcal_on_food_edit_is_rejected(make_app, db, type_into):
    """Dropping =kcal on an edit must be rejected, not silently written as 0.

    Kcal is the row's substance, not optional metadata. render_food always emits
    =kcal, so this only fires when someone deliberately deletes it. Silently
    writing 0 or keeping the old value are both worse than rejecting. Routing an
    edit into the Claude estimator is a deliberate follow-up, not this fix.
    """
    import datetime as dt

    add_food(db, description="oatmeal", kcal=350, date="2026-08-28", at=1, source="labeled")
    now = lambda: dt.datetime(2026, 8, 28, 9, 0)  # noqa: E731
    app = make_app(now=now)
    async with app.run_test(size=(120, 30)) as pilot:
        await go_body(pilot, app)
        await pilot.press("enter")
        await pilot.pause()
        app.prompt.value = ""
        await type_into(pilot, "oatmeal @2026-08-28")
        await pilot.press("enter")
        await pilot.pause()
        still_open = app.prompt.is_open
    assert still_open is True, "dropping =kcal must be rejected"
    rows = list_food(db, date="2026-08-28")
    assert len(rows) == 1
    assert rows[0]["kcal"] == 350, "the original kcal must remain unchanged"


async def test_enter_on_an_empty_table_does_not_crash(make_app):
    app = make_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await go_body(pilot, app)
        await pilot.press("enter")
        await pilot.pause()
        assert app.prompt.is_open is False


async def test_a_rejected_edit_leaves_nothing_on_the_undo_stack(make_app, db, type_into):
    """The pre-image is pushed after the write, not before. Pushing first left an
    entry for `u` to apply to a row that never changed."""
    add_weight(db, kg=78.2, date="2026-08-27", at=1, note="post-run")
    app = make_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await go_body(pilot, app)
        await pilot.press("shift+tab")
        await pilot.press("enter")
        await pilot.pause()
        app.prompt.value = ""
        await type_into(pilot, "heavy")          # rejected by the parser
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        popped = app.undo_stack.pop()
    assert popped is None
    assert list_weight(db)[0]["kg"] == 78.2
async def test_escaping_a_weight_edit_does_not_corrupt_next_entry(make_app, db, type_into):
    """If user arms a weight edit, presses escape, then submits a fresh entry,
    that fresh entry must INSERT, not UPDATE the abandoned row."""
    add_weight(db, kg=78.2, date="2026-08-27", at=1, note="original")
    # Pinned: the seed is dated, and the weight table is span-filtered, so on an
    # unpinned clock the row leaves Body's rolling 1m window on 2026-09-26 —
    # after which `enter` selects nothing and this test passes without arming an
    # edit at all. Verified by probing the table at four dates.
    app = make_app(now=lambda: dt.datetime(2026, 8, 27, 9, 0, tzinfo=WEIGHT_TZ))
    async with app.run_test(size=(120, 30)) as pilot:
        await go_body(pilot, app)
        await pilot.press("shift+tab")
        await pilot.press("enter")
        await pilot.pause()
        assert app.query_one("#body")._editing is not None, (
            # `prompt.is_open` is not enough: `key_activate` opens the prompt
            # whether or not it armed the row, so a broken arming path would sail
            # past it and this test would pass by doing nothing. `_editing` is the
            # state whose lifecycle the test is about, and what `cancel_editing`
            # clears.
            "no edit was armed, so this test proves nothing"
        )
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("w")
        await type_into(pilot, "80.1 fresh")
        await pilot.press("enter")
        await pilot.pause()
    rows = list_weight(db)
    assert len(rows) == 2, "must have two weight rows"
    assert any(r["kg"] == 78.2 and r["note"] == "original" for r in rows)
    assert any(r["kg"] == 80.1 and r["note"] == "fresh" for r in rows)


async def test_escaping_a_food_edit_does_not_corrupt_next_entry(make_app, db, type_into):
    """If user arms a food edit, presses escape, then submits a fresh entry,
    that fresh entry must INSERT, not UPDATE the abandoned row.

    The clock is pinned and the prompt is asserted open, because neither is
    optional here: the food table filters by the viewing date, so an unpinned
    `now` leaves it empty on any day but the seeded one, `enter` arms nothing,
    and every assertion below still passes with the fix removed.
    """
    import datetime as dt

    add_food(db, description="oatmeal", kcal=350, date="2026-08-28", at=1, source="labeled")
    now = lambda: dt.datetime(2026, 8, 28, 9, 0)  # noqa: E731
    app = make_app(now=now)
    async with app.run_test(size=(120, 30)) as pilot:
        await go_body(pilot, app)
        await pilot.press("enter")
        await pilot.pause()
        assert app.query_one("#body")._editing is not None, (
            # `prompt.is_open` is not enough: `key_activate` opens the prompt
            # whether or not it armed the row, so a broken arming path would sail
            # past it and this test would pass by doing nothing. `_editing` is the
            # state whose lifecycle the test is about, and what `cancel_editing`
            # clears.
            "no edit was armed, so this test proves nothing"
        )
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("f")
        await type_into(pilot, "salad =600 @2026-08-28")
        await pilot.press("enter")
        await pilot.pause()
    rows = list_food(db, date="2026-08-28")
    assert len(rows) == 2, "must have two food rows"
    assert any(r["description"] == "oatmeal" and r["kcal"] == 350 for r in rows)
    assert any(r["description"] == "salad" and r["kcal"] == 600 for r in rows)


async def test_empty_submit_on_weight_edit_does_not_corrupt_next_entry(make_app, db, type_into):
    """If user arms a weight edit, clears the line, submits empty, then submits a
    fresh entry, that fresh entry must INSERT, not UPDATE the abandoned row."""
    add_weight(db, kg=78.2, date="2026-08-27", at=1, note="original")
    # Pinned: the seed is dated, and the weight table is span-filtered, so on an
    # unpinned clock the row leaves Body's rolling 1m window on 2026-09-26 —
    # after which `enter` selects nothing and this test passes without arming an
    # edit at all. Verified by probing the table at four dates.
    app = make_app(now=lambda: dt.datetime(2026, 8, 27, 9, 0, tzinfo=WEIGHT_TZ))
    async with app.run_test(size=(120, 30)) as pilot:
        await go_body(pilot, app)
        await pilot.press("shift+tab")
        await pilot.press("enter")
        await pilot.pause()
        assert app.query_one("#body")._editing is not None, (
            # `prompt.is_open` is not enough: `key_activate` opens the prompt
            # whether or not it armed the row, so a broken arming path would sail
            # past it and this test would pass by doing nothing. `_editing` is the
            # state whose lifecycle the test is about, and what `cancel_editing`
            # clears.
            "no edit was armed, so this test proves nothing"
        )
        app.prompt.value = ""
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("w")
        await type_into(pilot, "80.1 fresh")
        await pilot.press("enter")
        await pilot.pause()
    rows = list_weight(db)
    assert len(rows) == 2, "must have two weight rows"
    assert any(r["kg"] == 78.2 and r["note"] == "original" for r in rows)
    assert any(r["kg"] == 80.1 and r["note"] == "fresh" for r in rows)


async def test_empty_submit_on_food_edit_does_not_corrupt_next_entry(make_app, db, type_into):
    """If user arms a food edit, clears the line, submits empty, then submits a
    fresh entry, that fresh entry must INSERT, not UPDATE the abandoned row."""
    import datetime as dt

    add_food(db, description="oatmeal", kcal=350, date="2026-08-28", at=1, source="labeled")
    now = lambda: dt.datetime(2026, 8, 28, 9, 0)  # noqa: E731
    app = make_app(now=now)
    async with app.run_test(size=(120, 30)) as pilot:
        await go_body(pilot, app)
        await pilot.press("enter")
        await pilot.pause()
        assert app.query_one("#body")._editing is not None, (
            # `prompt.is_open` is not enough: `key_activate` opens the prompt
            # whether or not it armed the row, so a broken arming path would sail
            # past it and this test would pass by doing nothing. `_editing` is the
            # state whose lifecycle the test is about, and what `cancel_editing`
            # clears.
            "no edit was armed, so this test proves nothing"
        )
        app.prompt.value = ""
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("f")
        await type_into(pilot, "salad =600 @2026-08-28")
        await pilot.press("enter")
        await pilot.pause()
    rows = list_food(db, date="2026-08-28")
    assert len(rows) == 2, "must have two food rows"
    assert any(r["description"] == "oatmeal" and r["kcal"] == 350 for r in rows)
    assert any(r["description"] == "salad" and r["kcal"] == 600 for r in rows)


async def test_a_parse_error_during_edit_keeps_editing_armed(make_app, db, type_into):
    """If an edit submission fails to parse, the retry must still update the same
    row, not insert a new one."""
    add_weight(db, kg=78.2, date="2026-08-27", at=1, note="original")
    app = make_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await go_body(pilot, app)
        await pilot.press("shift+tab")
        await pilot.press("enter")
        await pilot.pause()
        app.prompt.value = ""
        await type_into(pilot, "heavy")
        await pilot.press("enter")
        await pilot.pause()
        # The prompt is still open with an error. Now submit a valid line.
        app.prompt.value = ""
        await type_into(pilot, "80.1 fixed")
        await pilot.press("enter")
        await pilot.pause()
    rows = list_weight(db)
    assert len(rows) == 1, "must have updated, not inserted"
    assert rows[0]["kg"] == 80.1 and rows[0]["note"] == "fixed"
async def test_editing_a_weight_can_clear_its_note(make_app, db, type_into):
    """A line that omits the note words must clear the column."""
    add_weight(db, kg=78.2, date="2026-08-27", at=1, note="post-run")
    app = make_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await go_body(pilot, app)
        await pilot.press("shift+tab")
        await pilot.press("enter")
        await pilot.pause()
        app.prompt.value = ""
        await type_into(pilot, "78.2 @2026-08-27")
        await pilot.press("enter")
        await pilot.pause()
    rows = list_weight(db)
    assert len(rows) == 1
    assert rows[0]["note"] == "", "omitting note words must clear the note"


async def test_editing_a_weight_with_unchanged_prefill_preserves_note(make_app, db, type_into):
    """Submitting the rendered prefill unchanged must keep the note."""
    add_weight(db, kg=78.2, date="2026-08-27", at=1, note="post-run")
    app = make_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await go_body(pilot, app)
        await pilot.press("shift+tab")
        await pilot.press("enter")
        await pilot.pause()
        # The prefill is "78.2 post-run @2026-08-27". Submit it unchanged.
        await pilot.press("enter")
        await pilot.pause()
    rows = list_weight(db)
    assert len(rows) == 1
    assert rows[0]["note"] == "post-run"


async def test_editing_a_food_with_escaped_at_preserves_timestamp(
    make_app, db, type_into
):
    r"""An escaped \@ inside the description is not a time token — ate_at must not change."""
    import datetime as dt
    add_food(
        db, description="meeting", kcal=300, date="2026-08-28", at=1787223943, source="labeled"
    )
    now = lambda: dt.datetime(2026, 8, 28, 9, 0)  # noqa: E731
    app = make_app(now=now)
    async with app.run_test(size=(120, 30)) as pilot:
        await go_body(pilot, app)
        await pilot.press("enter")
        await pilot.pause()
        app.prompt.value = ""
        await type_into(pilot, r"\@work meeting =300")
        await pilot.press("enter")
        await pilot.pause()
    rows = list_food(db, date="2026-08-28")
    assert len(rows) == 1
    assert rows[0]["description"] == "@work meeting", "the backslash is escape syntax, not content"
    assert rows[0]["ate_at"] == 1787223943, "escaped @ must not trigger a restamp"


# ── the estimate progress indicator (#2) ─────────────────────────────────
#
# The estimate is one opaque subprocess call of up to `estimate_timeout_sec`
# (60 by default). Before this, the only feedback was a 3-second toast, so the
# remaining 57 seconds looked identical to a dropped keypress.
#
# The prompt is CLOSED for the whole wait (on_input_submitted closes on
# success), so the indicator cannot live in its border subtitle — it goes where
# summary_tab already puts "generating…": the panel header and the footer's
# state row.


def _gate():
    """A runner that blocks until released, so a test can observe mid-flight."""
    import asyncio

    started, release = asyncio.Event(), asyncio.Event()

    async def runner(**kw):
        started.set()
        await release.wait()
        return Estimate(description="gated meal", kcal=500)

    return runner, started, release


def _food_head(app) -> str:
    from textual.widgets import Static

    return str(app.query_one("#food-head", Static).content)


def _footer(app) -> str:
    """The footer's PAINTED text.

    Deliberately not `status_hint()`: the footer is a sibling widget rewritten only
    by App.refresh_footer(), so asserting on the method passes while the screen
    stays silent. That is exactly how the first version of this shipped half-dead.
    """
    from daylogs.tui.footer import KeyFooter

    return str(app.query_one(KeyFooter).render())


async def test_the_food_header_shows_estimating_while_the_call_is_in_flight(
    make_app, db, type_into, monkeypatch
):
    runner, started, release = _gate()

    async def gated_from_text(**kw):
        return await runner(**kw)

    monkeypatch.setattr("daylogs.tui.body_tab.estimate.from_text", gated_from_text)
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("f")
        await type_into(pilot, "mystery stew")
        await pilot.press("enter")
        await started.wait()
        await pilot.pause()
        mid = _food_head(app)
        assert app.prompt.is_open is False, "the prompt should be closed during the wait"
        release.set()
        await pilot.pause()
        await pilot.pause()
        after = _food_head(app)
    assert "estimating" in mid.lower(), f"no indicator mid-flight: {mid!r}"
    assert "estimating" not in after.lower(), f"indicator outlived the call: {after!r}"


async def test_the_footer_state_row_shows_estimating_while_in_flight(
    make_app, db, type_into, monkeypatch
):
    runner, started, release = _gate()
    monkeypatch.setattr("daylogs.tui.body_tab.estimate.from_text", runner)
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("f")
        await type_into(pilot, "mystery stew")
        await pilot.press("enter")
        await started.wait()
        await pilot.pause()
        mid = app.query_one("#body").status_hint()
        release.set()
        await pilot.pause()
        await pilot.pause()
        after = app.query_one("#body").status_hint()
    assert "estimating" in mid.lower(), f"footer silent mid-flight: {mid!r}"
    assert "estimating" not in after.lower(), f"footer still busy after: {after!r}"


async def test_the_rendered_footer_shows_and_then_clears_the_indicator(
    make_app, db, type_into, monkeypatch
):
    """The footer half, asserted on the painted widget.

    `_set_estimating` has to call `app.refresh_footer()` itself: `reload()` only
    repaints BodyTab's own widgets, and every other refresh_footer call site is
    driven by a keypress. Without it the footer never shows the indicator during
    the wait, and — worse — a footer painted by any keypress mid-estimate keeps
    claiming an estimate is running long after it finished.
    """
    import asyncio

    started, release = asyncio.Event(), asyncio.Event()

    async def gated(**kw):
        started.set()
        await release.wait()
        return Estimate(description="gated", kcal=500)

    monkeypatch.setattr("daylogs.tui.body_tab.estimate.from_text", gated)
    app = make_app()
    async with app.run_test(size=(120, 34)) as pilot:
        await go_body(pilot, app)
        await pilot.press("f")
        await type_into(pilot, "mystery stew")
        await pilot.press("enter")
        await started.wait()
        await pilot.pause()
        during = _footer(app)
        release.set()
        await pilot.pause()
        await pilot.pause()
        after = _footer(app)
    assert "estimating" in during.lower(), f"painted footer silent mid-estimate: {during!r}"
    assert "estimating" not in after.lower(), (
        f"painted footer still claims an estimate is running: {after!r}"
    )


async def test_a_photo_estimate_does_not_move_the_selected_food_row(
    make_app, db, tmp_path, monkeypatch
):
    """Starting an estimate must not disturb what you were looking at.

    The indicator first repainted via reload(), which calls _fill_table, which does
    table.clear(columns=True) and resets the cursor to row 0.

    The PHOTO path is the one that proves it: `p` opens no prompt, so nothing else
    repaints the tab and _set_estimating was the only thing touching the table. (The
    `f` path already resets the cursor when the prompt opens — pre-existing, and not
    this change's to fix.)
    """
    import asyncio
    import datetime as dt

    from textual.widgets import DataTable

    for i in range(4):
        add_food(db, description=f"row{i}", kcal=100 + i, source="labeled",
                 date="2026-08-28", at=1787000000 + i * 3600)

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "meal.jpg").write_bytes(b"\xff\xd8\xff")
    monkeypatch.setattr("daylogs.tui.body_tab.photo.clipboard_image", lambda d: None)

    started, release = asyncio.Event(), asyncio.Event()

    async def gated(**kw):
        started.set()
        await release.wait()
        return Estimate(description="ribeye", kcal=910)

    monkeypatch.setattr("daylogs.tui.body_tab.estimate.from_image", gated)
    now = lambda: dt.datetime(2026, 8, 28, 9, 0)  # noqa: E731
    app = make_app(now=now)
    async with app.run_test(size=(120, 34)) as pilot:
        await go_body(pilot, app)
        await pilot.pause()
        table = app.query_one("#body-table", DataTable)
        table.focus()
        table.move_cursor(row=3)
        await pilot.pause()
        assert table.cursor_coordinate.row == 3, (
            "could not select row 3 — this test would prove nothing"
        )
        await pilot.press("p")
        await started.wait()
        await pilot.pause()
        during = table.cursor_coordinate.row
        release.set()
        await pilot.pause()
    assert during == 3, f"starting a photo estimate moved the cursor from row 3 to row {during}"


async def test_the_indicator_clears_when_the_estimate_fails(
    make_app, db, type_into, monkeypatch
):
    from daylogs.claude import ClaudeError

    async def boom(**kw):
        raise ClaudeError("no claude")

    monkeypatch.setattr("daylogs.tui.body_tab.estimate.from_text", boom)
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("f")
        await type_into(pilot, "mystery stew")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        head = _food_head(app)
    assert "estimating" not in head.lower(), f"indicator survived a failure: {head!r}"


async def test_the_indicator_clears_when_the_estimate_times_out(
    make_app, db, type_into, monkeypatch
):
    """A timeout reaches the tab as ClaudeError from claude._run's wait_for, so it
    is the same exit as a failure — asserted separately because the issue names
    timeout as its own case."""
    from daylogs.claude import ClaudeError

    async def timed_out(**kw):
        raise ClaudeError("claude -p (json) timed out after 60s")

    monkeypatch.setattr("daylogs.tui.body_tab.estimate.from_text", timed_out)
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("f")
        await type_into(pilot, "mystery stew")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        head = _food_head(app)
    assert "estimating" not in head.lower(), f"indicator survived a timeout: {head!r}"


async def test_a_second_estimate_cancels_the_first_without_clearing_the_indicator(
    make_app, db, type_into, monkeypatch
):
    """The race a boolean flag gets wrong.

    `@work(exclusive=True)` cancels the first worker when the second starts. With
    a bool, the cancelled worker's cleanup clears the flag while its replacement
    is still running, so the screen goes quiet mid-call. An in-flight counter
    goes 1 -> 2 -> 1 and stays truthy.
    """
    import asyncio

    started = asyncio.Event()
    release_second = asyncio.Event()
    calls = []

    async def two_stage(**kw):
        calls.append(kw)
        if len(calls) == 1:
            await asyncio.sleep(3600)          # first call: cancelled, never returns
        started.set()
        await release_second.wait()
        return Estimate(description="second", kcal=400)

    monkeypatch.setattr("daylogs.tui.body_tab.estimate.from_text", two_stage)
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("f")
        await type_into(pilot, "first stew")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("f")
        await type_into(pilot, "second stew")
        await pilot.press("enter")
        await started.wait()
        await pilot.pause()
        await pilot.pause()
        mid = _food_head(app)
        release_second.set()
        await pilot.pause()
        await pilot.pause()
        after = _food_head(app)
    assert len(calls) == 2, f"expected two estimate calls, got {len(calls)}"
    assert "estimating" in mid.lower(), (
        f"the cancelled worker cleared the indicator while the second was in flight: {mid!r}"
    )
    assert "estimating" not in after.lower(), f"indicator outlived the second call: {after!r}"


async def test_the_photo_estimate_shows_the_same_indicator(
    make_app, db, tmp_path, monkeypatch
):
    import asyncio

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "meal.jpg").write_bytes(b"\xff\xd8\xff")
    monkeypatch.setattr("daylogs.tui.body_tab.photo.clipboard_image", lambda d: None)

    started, release = asyncio.Event(), asyncio.Event()

    async def gated(**kw):
        started.set()
        await release.wait()
        return Estimate(description="ribeye", kcal=910)

    monkeypatch.setattr("daylogs.tui.body_tab.estimate.from_image", gated)
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("p")
        await started.wait()
        await pilot.pause()
        mid = _food_head(app)
        release.set()
        await pilot.pause()
        await pilot.pause()
        after = _food_head(app)
    assert "estimating" in mid.lower(), f"no indicator during a photo estimate: {mid!r}"
    assert "estimating" not in after.lower(), f"indicator outlived the photo call: {after!r}"


async def test_no_three_second_toast_is_fired_for_an_estimate(
    make_app, db, type_into, monkeypatch
):
    """The defect itself: a toast whose lifetime is unrelated to the work. The
    indicator replaces it, so firing both would be redundant noise."""
    import asyncio

    started, release = asyncio.Event(), asyncio.Event()
    toasts = []

    async def gated(**kw):
        started.set()
        await release.wait()
        return Estimate(description="x", kcal=1)

    monkeypatch.setattr("daylogs.tui.body_tab.estimate.from_text", gated)
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        app.notify = lambda msg, **kw: toasts.append((msg, kw.get("timeout")))  # type: ignore[method-assign]
        await pilot.press("f")
        await type_into(pilot, "mystery stew")
        await pilot.press("enter")
        await started.wait()
        await pilot.pause()
        release.set()
        await pilot.pause()
    assert not [t for t in toasts if "estimat" in t[0].lower()], (
        f"an estimate toast was still fired: {toasts}"
    )


async def test_no_three_second_toast_is_fired_for_a_photo_estimate(
    make_app, db, tmp_path, monkeypatch
):
    """The photo path had its own copy of the defect ("estimating from photo…",
    also timeout=3). Pinned separately because intercepting only the text path
    leaves this one free to come back."""
    import asyncio

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "meal.jpg").write_bytes(b"\xff\xd8\xff")
    monkeypatch.setattr("daylogs.tui.body_tab.photo.clipboard_image", lambda d: None)

    started, release = asyncio.Event(), asyncio.Event()
    toasts = []

    async def gated(**kw):
        started.set()
        await release.wait()
        return Estimate(description="ribeye", kcal=910)

    monkeypatch.setattr("daylogs.tui.body_tab.estimate.from_image", gated)
    app = make_app()
    async with app.run_test(size=(120, 34)) as pilot:
        await go_body(pilot, app)
        app.notify = lambda msg, **kw: toasts.append((msg, kw.get("timeout")))  # type: ignore[method-assign]
        await pilot.press("p")
        await started.wait()
        await pilot.pause()
        release.set()
        await pilot.pause()
    assert not [t for t in toasts if "estimat" in t[0].lower()], (
        f"a photo estimate toast was still fired: {toasts}"
    )


async def test_only_one_estimate_runs_at_a_time(
    make_app, db, tmp_path, type_into, monkeypatch
):
    """The invariant that makes a plain flag safe.

    Clearing the flag only on the two ending paths is correct *because* a cancelled
    estimate always has a replacement that sets the flag again. That holds only while
    BOTH workers sit in the same exclusive group — `@work`'s group defaults to
    "default", so a photo estimate and a text estimate cancel each other today. Give
    either its own group and the two could run at once, whereupon whichever finished
    first would clear the flag out from under the other and this design would need a
    count instead.

    So this fires a photo estimate and then a text one: same-method presses would
    cancel each other whatever the group is, and would prove nothing.
    """
    import asyncio

    live = 0
    peak = 0
    text_started = asyncio.Event()
    release = asyncio.Event()

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "meal.jpg").write_bytes(b"\xff\xd8\xff")
    monkeypatch.setattr("daylogs.tui.body_tab.photo.clipboard_image", lambda d: None)

    async def image_call(**kw):
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        try:
            await asyncio.sleep(3600)          # expects to be cancelled by the text one
            return Estimate(description="photo", kcal=900)
        finally:
            live -= 1

    async def text_call(**kw):
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        try:
            text_started.set()
            await release.wait()
            return Estimate(description="typed", kcal=100)
        finally:
            live -= 1

    monkeypatch.setattr("daylogs.tui.body_tab.estimate.from_image", image_call)
    monkeypatch.setattr("daylogs.tui.body_tab.estimate.from_text", text_call)

    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("p")                  # photo estimate starts, blocks
        await pilot.pause()
        await pilot.press("f")                  # text estimate should cancel it
        await type_into(pilot, "typed meal")
        await pilot.press("enter")
        await text_started.wait()
        await pilot.pause()
        release.set()
        await pilot.pause()
    assert peak == 1, (
        f"{peak} estimates were live at once — the photo and text workers no longer "
        "share an exclusive group, so a flag is not enough; use a count"
    )


# ── an abandoned photo must not be eaten by the next meal ─────────────────


def _inbox_state(tmp_path):
    inbox = tmp_path / "inbox"
    processed = inbox / "processed"
    return (
        sorted(p.name for p in inbox.glob("*.jpg")),
        sorted(p.name for p in processed.glob("*.jpg")) if processed.exists() else [],
    )


async def test_escaping_a_photo_confirm_does_not_let_the_next_meal_eat_the_photo(
    make_app, db, tmp_path, type_into, monkeypatch
):
    """`_pending_photo` is what says "this inbox file belongs to the row about to be
    written". Walking away from the confirm prompt has to drop it, or the NEXT
    confirmed estimate — a typed meal, nothing to do with the photo — moves the
    file into `processed/` and the photo is gone without ever being logged.
    """
    import asyncio  # noqa: F401

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "meal.jpg").write_bytes(b"\xff\xd8\xff")
    monkeypatch.setattr("daylogs.tui.body_tab.photo.clipboard_image", lambda d: None)
    monkeypatch.setattr(
        "daylogs.tui.body_tab.estimate.from_image",
        lambda **kw: _immediate(Estimate(description="ribeye", kcal=910)),
    )
    monkeypatch.setattr(
        "daylogs.tui.body_tab.estimate.from_text",
        lambda **kw: _immediate(Estimate(description="side salad", kcal=120)),
    )

    app = make_app()
    async with app.run_test(size=(120, 34)) as pilot:
        await go_body(pilot, app)
        await pilot.press("p")
        await pilot.pause()
        await pilot.pause()
        assert app.prompt.label == "confirm food", "the photo estimate never offered"
        await pilot.press("escape")             # changed my mind
        await pilot.pause()
        # Asserted as state, not as loss: the typed estimate below also releases the
        # photo, so with both clears in place the damage is unreachable and only the
        # invariant itself can be pinned here. An abandoned prompt carries nothing
        # forward — that is what keeps it unreachable when someone adds a new route
        # into `confirm food`.
        tab = app.query_one("#body")
        assert tab._pending_photo is None, "escaping the confirm prompt kept the photo armed"
        assert tab._pending is None, "escaping the confirm prompt kept a stale estimate armed"
        await pilot.press("f")                  # a completely unrelated meal
        await type_into(pilot, "side salad")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        await pilot.press("enter")              # accept the typed estimate
        await pilot.pause()
        today = app.today()
    pending, processed = _inbox_state(tmp_path)
    rows = [r["description"] for r in list_food(db, date=today)]
    assert rows == ["side salad"], f"unexpected food rows: {rows}"
    assert pending == ["meal.jpg"], f"the photo was consumed by an unrelated meal: {pending}"
    assert processed == [], f"the photo was moved to processed without being logged: {processed}"


async def test_a_superseded_photo_estimate_does_not_let_the_next_meal_eat_the_photo(
    make_app, db, tmp_path, type_into, monkeypatch
):
    """Same loss by the other route: the photo estimate is still running when a typed
    one supersedes it. The image worker is cancelled, so its `except` — the only
    place that clears `_pending_photo` on failure — never runs.
    """
    import asyncio

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "meal.jpg").write_bytes(b"\xff\xd8\xff")
    monkeypatch.setattr("daylogs.tui.body_tab.photo.clipboard_image", lambda d: None)

    async def never(**kw):
        await asyncio.sleep(3600)

    monkeypatch.setattr("daylogs.tui.body_tab.estimate.from_image", never)
    monkeypatch.setattr(
        "daylogs.tui.body_tab.estimate.from_text",
        lambda **kw: _immediate(Estimate(description="side salad", kcal=120)),
    )

    app = make_app()
    async with app.run_test(size=(120, 34)) as pilot:
        await go_body(pilot, app)
        await pilot.press("p")                  # photo estimate starts, hangs
        await pilot.pause()
        await pilot.press("f")                  # supersedes it
        await type_into(pilot, "side salad")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        assert app.prompt.label == "confirm food", "the typed estimate never offered"
        await pilot.press("enter")
        await pilot.pause()
        today = app.today()
    pending, processed = _inbox_state(tmp_path)
    rows = [r["description"] for r in list_food(db, date=today)]
    assert rows == ["side salad"], f"unexpected food rows: {rows}"
    assert pending == ["meal.jpg"], f"the photo was consumed by an unrelated meal: {pending}"
    assert processed == [], f"the photo was moved to processed without being logged: {processed}"


async def _immediate(value):
    return value


# ── which view am I on ───────────────────────────────────────────────────


def _view_row(app) -> str:
    from textual.widgets import Static

    return str(app.query_one("#body-views", Static).content)


async def test_the_table_header_names_the_view_it_is_showing(make_app, make_cfg, db):
    """The header used to say FOOD unconditionally, including while the table
    below it listed weigh-ins with `date | kg | note` columns and the header
    quoted the day's calorie total. A label that is wrong is worse than absent —
    it is the reason the weight view felt unlocated.
    """
    add_weight(db, kg=80.0, date="2026-08-27", at=1)
    add_food(db, description="salad", kcal=610, source="labeled", date="2026-08-27", at=2)
    cfg = make_cfg(height_cm=180, sex="male", birthday="1996-08-27")
    app = make_app(cfg=cfg)
    async with app.run_test() as pilot:
        body = await go_body(pilot, app)
        body.viewing_date = "2026-08-27"
        body.reload()
        await pilot.pause()
        assert body.table_mode == "food"
        assert "FOOD" in _food_head(app)

        # shift+tab: weight is one step back along weight / food / activity.
        await pilot.press("shift+tab")
        await pilot.pause()
        assert body.table_mode == "weight"
        head = _food_head(app)
    assert "WEIGHT" in head, f"the weight table is not labelled: {head!r}"
    assert "FOOD" not in head, f"still labelled FOOD while showing weigh-ins: {head!r}"
    assert "kcal" not in head, f"a calorie total over the weight table: {head!r}"
    assert "BMR" not in head


async def test_body_lists_every_view_with_the_active_one_marked(make_app, db):
    """Money has always drawn its panes as a visible row; Body had the same toggle and
    drew nothing, so `tab` was undiscoverable."""
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.pause()
        row = _view_row(app)
    for view in ("weight", "food", "activity"):
        assert view in row, f"{view} is missing from the strip: {row!r}"
    assert "[b]food[/b]" in row, f"the active view is not marked: {row!r}"
    assert "[b]weight[/b]" not in row


async def test_tab_moves_the_mark_along_the_strip(make_app, db):
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()
        row = _view_row(app)
    assert "[b]activity[/b]" in row, f"the mark did not follow the tab: {row!r}"
    assert "[b]food[/b]" not in row


# ── TDEE: net against a real maintenance figure ───────────────────────────
# `net` used to compare intake against *resting* expenditure, so a sedentary day
# read as a deficit it wasn't and a hard day understated one. These pin the
# substitution, and — just as important — pin that a profile with no activity level
# still reads exactly as it did before.

# 180 cm, male, born 1996-01-01, weighing 80 kg: Mifflin-St Jeor gives
# 10*80 + 6.25*180 - 5*30 + 5 = 1,780 resting, and 1,780 x 1.2 = 2,136 for a desk
# day. Spelled out so a wrong number is a wrong number, not a recomputed agreement.
_BMR = 1780
_DESK_BURN = 2136
_GYM_BURN = 2848  # x 1.6
DAY = "2026-09-03"


def _profile(make_cfg, **kw):
    return make_cfg(height_cm=180, sex="male", birthday="1996-01-01", **kw)


async def _energy_on(app, date=DAY):
    body = app.query_one("#body")
    body.viewing_date = date
    body.reload()
    return body


def _row(panel: str, label: str) -> str:
    """One labelled line of a panel.

    Asserted per line rather than against the whole blob because the value column is
    right-aligned inside a 7-wide field, so the minus sign is *detached* from its
    digits — `BMR      −  1,780`. A substring check for "−1,780" tests nothing that
    is on the screen.
    """
    for line in panel.splitlines():
        if line.strip().startswith(label):
            return line
    raise AssertionError(f"no {label!r} line in:\n{panel}")


def _has_no_row(panel: str, label: str) -> bool:
    return not any(line.strip().startswith(label) for line in panel.splitlines())


async def test_the_energy_panel_shows_burn_and_how_it_was_derived(
    make_app, make_cfg, db
):
    """The multiplier stays on screen deliberately. A factor rescales every calorie
    judgement for its day, so an inferred number with nothing to make you doubt it
    would quietly become the baseline for everything."""
    add_weight(db, kg=80.0, date=DAY, at=1)
    add_food(db, description="salad", kcal=1200, source="labeled", date=DAY, at=2)
    app = make_app(cfg=_profile(make_cfg, activity="desk"))
    async with app.run_test(size=(110, 34)) as pilot:
        await go_body(pilot, app)
        await _energy_on(app)
        await pilot.pause()
        text = _energy(app)
    assert f"{_BMR:,}" in _row(text, "BMR"), f"resting BMR is gone: {text!r}"
    activity = _row(text, "activity")
    assert "×1.2" in activity, f"the multiplier is not on screen: {activity!r}"
    assert "profile" in activity, f"nothing says where it came from: {activity!r}"
    burn = _row(text, "burn")
    assert "−" in burn and f"{_DESK_BURN:,}" in burn, f"burn line is wrong: {burn!r}"
    assert "-936" in _row(text, "net"), f"net is not 1,200 − 2,136: {text!r}"
    # The arithmetic has to read correctly top to bottom: BMR is a term of `burn`,
    # not a term of `net`, so it must not carry the minus sign any more.
    assert "−" not in _row(text, "BMR"), f"BMR is still subtracted from intake: {text!r}"


async def test_without_a_level_the_energy_panel_is_untouched(make_app, make_cfg, db):
    """Opt-in, all the way down: no level and nothing logged means `net` sits against
    resting BMR exactly as it did before any of this existed."""
    add_weight(db, kg=80.0, date=DAY, at=1)
    add_food(db, description="salad", kcal=1200, source="labeled", date=DAY, at=2)
    app = make_app(cfg=_profile(make_cfg))
    async with app.run_test(size=(110, 34)) as pilot:
        await go_body(pilot, app)
        await _energy_on(app)
        await pilot.pause()
        text = _energy(app)
    bmr = _row(text, "BMR")
    assert "−" in bmr and f"{_BMR:,}" in bmr, f"BMR is not the subtrahend: {bmr!r}"
    assert _has_no_row(text, "burn"), f"a burn line with no factor to build it: {text!r}"
    assert _has_no_row(text, "activity"), f"an activity line, no factor: {text!r}"
    assert "-580" in _row(text, "net"), f"net is not 1,200 − 1,780: {text!r}"


async def test_a_logged_factor_says_it_was_logged(make_app, make_cfg, db):
    """"profile" and "logged" are different claims, and the second one is the one
    worth doubting."""
    from daylogs.body import add_activity

    add_weight(db, kg=80.0, date=DAY, at=1)
    add_food(db, description="salad", kcal=1200, source="labeled", date=DAY, at=2)
    add_activity(db, description="gym 1h", date=DAY, at=3, factor=1.6,
                 source="estimated")
    app = make_app(cfg=_profile(make_cfg, activity="desk"))
    async with app.run_test(size=(110, 34)) as pilot:
        await go_body(pilot, app)
        await _energy_on(app)
        await pilot.pause()
        text = _energy(app)
    activity = _row(text, "activity")
    assert "×1.6" in activity and "logged" in activity, f"origin: {activity!r}"
    assert "profile" not in activity, f"claims the baseline it superseded: {activity!r}"
    assert f"{_GYM_BURN:,}" in _row(text, "burn"), f"burn ignored the log: {text!r}"


async def test_percent_of_maintenance_is_against_burn_not_resting_bmr(
    make_app, make_cfg, db
):
    """Otherwise one panel measures the same day against two different baselines.
    2,136 kcal is exactly 100% of a desk day's burn and 120% of resting BMR, so the
    number itself says which one was used."""
    add_weight(db, kg=80.0, date=DAY, at=1)
    add_food(db, description="lots", kcal=_DESK_BURN, source="labeled", date=DAY, at=2)
    app = make_app(cfg=_profile(make_cfg, activity="desk"))
    async with app.run_test(size=(110, 34)) as pilot:
        await go_body(pilot, app)
        await _energy_on(app)
        await pilot.pause()
        text = _energy(app)
    assert "100% of maintenance" in text, f"not measured against burn: {text!r}"


async def test_the_horizon_average_net_is_per_day(make_app, make_cfg, db):
    """One gym session must not restate a whole window's average net. Measuring the
    window's average intake against *today's* burn would say −1,348 here, and
    against resting BMR −280; per day it is −992.
    """
    from daylogs.body import add_activity

    add_weight(db, kg=80.0, date="2026-09-02", at=1)
    add_food(db, description="a", kcal=2000, source="labeled", date="2026-09-02", at=2)
    add_food(db, description="b", kcal=1000, source="labeled", date=DAY, at=3)
    add_activity(db, description="gym", date=DAY, at=4, factor=1.6, source="estimated")
    app = make_app(cfg=_profile(make_cfg, activity="desk"))
    async with app.run_test(size=(110, 34)) as pilot:
        await go_body(pilot, app)
        await _energy_on(app)
        await pilot.pause()
        text = _energy(app)
    flat = text.replace("−", "-")
    assert "-992" in flat, f"average net is not the mean of per-day nets: {text!r}"
    assert "-1,348" not in flat and "-280" not in flat


async def test_the_food_header_measures_against_burn(make_app, make_cfg, db):
    add_weight(db, kg=80.0, date=DAY, at=1)
    add_food(db, description="salad", kcal=1200, source="labeled", date=DAY, at=2)
    app = make_app(cfg=_profile(make_cfg, activity="desk"))
    async with app.run_test(size=(110, 34)) as pilot:
        await go_body(pilot, app)
        await _energy_on(app)
        await pilot.pause()
        head = str(app.query_one("#food-head").content)
    assert f"{_DESK_BURN:,} burn" in head, f"header still on resting BMR: {head!r}"
    assert "BMR" not in head
    assert "-936 net" in head.replace("−", "-"), f"net is wrong: {head!r}"


# ── BMI ──────────────────────────────────────────────────────────────────


async def test_the_weight_header_carries_bmi(make_app, make_cfg, db):
    """A bare number: no band and no colour. "overweight" is a judgement this app
    does not otherwise make."""
    add_weight(db, kg=81.0, date=DAY, at=1)
    app = make_app(cfg=make_cfg(height_cm=180))
    async with app.run_test(size=(110, 34)) as pilot:
        await go_body(pilot, app)
        await _energy_on(app)
        await pilot.pause()
        head = str(app.query_one("#weight-head").content)
    assert "BMI 25.0" in head, f"no BMI on the weight header: {head!r}"


async def test_the_weight_header_omits_bmi_without_a_height(make_app, db):
    add_weight(db, kg=81.0, date=DAY, at=1)
    app = make_app()
    async with app.run_test(size=(110, 34)) as pilot:
        await go_body(pilot, app)
        await _energy_on(app)
        await pilot.pause()
        head = str(app.query_one("#weight-head").content)
    assert "BMI" not in head, f"BMI with no height to compute it from: {head!r}"


# ── the profile carries the level ─────────────────────────────────────────


async def test_h_sets_the_ordinary_day_level(make_app, db, type_into, tmp_path):
    add_weight(db, kg=80.0, date=DAY, at=1)
    app = make_app()
    async with app.run_test(size=(110, 34)) as pilot:
        await go_body(pilot, app)
        await pilot.press("h")
        await type_into(pilot, "180 male 1996-01-01 desk")
        await pilot.press("enter")
        await pilot.pause()
        cfg = app.cfg
    assert cfg.activity == "desk", f"the level did not reach config: {cfg.activity!r}"
    assert "activity" in (tmp_path / "config.toml").read_text()


async def test_the_profile_prefill_carries_the_level(make_app, type_into):
    """What you can see is what you can edit — a prefill that drops a field silently
    clears it on the next submit."""
    app = make_app()
    async with app.run_test(size=(110, 34)) as pilot:
        await go_body(pilot, app)
        await pilot.press("h")
        await type_into(pilot, "180 male 1996-01-01 heavy")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("h")
        await pilot.pause()
        prefill = app.prompt.value
    assert "heavy" in prefill, f"the level is missing from the prefill: {prefill!r}"


async def test_a_complete_profile_with_no_level_names_the_missing_level(
    make_app, db, type_into
):
    """An empty state names the fix. Resting BMR is not maintenance, and nothing
    else on screen would tell you a level is what turns one into the other."""
    add_weight(db, kg=80.0, date=DAY, at=1)
    app = make_app()
    said = []
    async with app.run_test(size=(110, 34)) as pilot:
        await go_body(pilot, app)
        app.notify = lambda msg, **kw: said.append(msg)
        await pilot.press("h")
        await type_into(pilot, "180 male 1996-01-01")
        await pilot.press("enter")
        await pilot.pause()
    assert said, "saving a profile said nothing at all"
    assert "desk" in said[-1], f"the level is not named as the next step: {said[-1]!r}"


# ── a: logging a day that departs from the baseline ───────────────────────


def _runner_factor(value, seen=None):
    async def runner(**kwargs):
        if seen is not None:
            seen.update(kwargs)
        return {"factor": value}
    return runner


def _act_rows(db, date=DAY):
    from daylogs.body import list_activity
    return list_activity(db, date=date)


async def test_a_opens_the_activity_prompt(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("a")
        await pilot.pause()
        assert app.prompt.is_open and app.prompt.label == "activity"


async def test_a_typed_factor_is_written_without_asking_claude(make_app, db, type_into):
    """`=level` is the escape hatch and the no-LLM path, exactly as `=kcal` is for
    food. It must not spawn a call."""
    called = []

    async def runner(**kwargs):
        called.append(kwargs)
        return {"factor": 1.9}

    app = make_app(runner_json=runner)
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("a")
        await type_into(pilot, "gym 1h =active")
        await pilot.press("enter")
        await pilot.pause()
    rows = _act_rows(db, app.today())
    assert len(rows) == 1
    assert (rows[0]["description"], rows[0]["factor"]) == ("gym 1h", 1.55)
    assert rows[0]["source"] == "labeled", "a typed number is not an estimate"
    assert called == [], "asked Claude for a factor that was given"


async def test_a_without_a_factor_asks_claude_and_offers_the_answer(
    make_app, db, type_into
):
    app = make_app(runner_json=_runner_factor(1.45))
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("a")
        await type_into(pilot, "gym 1h")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        label, value = app.prompt.label, app.prompt.value
    assert label == "confirm activity", f"no review step: {label!r}"
    assert "gym 1h" in value and "=1.45" in value, f"prefill is wrong: {value!r}"
    assert _act_rows(db, app.today()) == [], "wrote the row before it was confirmed"


async def test_confirming_an_inferred_factor_writes_it(make_app, db, type_into):
    app = make_app(runner_json=_runner_factor(1.45))
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("a")
        await type_into(pilot, "gym 1h")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
    rows = _act_rows(db, app.today())
    assert len(rows) == 1
    assert (rows[0]["factor"], rows[0]["source"]) == (1.45, "estimated")


async def test_a_confirm_line_with_the_factor_deleted_still_lands_the_estimate(
    make_app, db, type_into
):
    """The prefill always carries the number, so a submitted line without one means it
    was deleted — and falling back to the inferred value beats writing a NULL the user
    did not ask for. The same rule `confirm food` follows for a deleted `=kcal`."""
    app = make_app(runner_json=_runner_factor(1.45))
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("a")
        await type_into(pilot, "gym 1h")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        app.prompt.value = "gym 1h"          # the factor, deleted
        await pilot.press("enter")
        await pilot.pause()
    rows = _act_rows(db, app.today())
    assert len(rows) == 1
    assert rows[0]["factor"] == 1.45, f"the estimate was dropped: {rows[0]['factor']!r}"


async def test_the_confirm_line_can_be_corrected_before_it_lands(
    make_app, db, type_into
):
    app = make_app(runner_json=_runner_factor(1.45))
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("a")
        await type_into(pilot, "gym 1h")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        app.prompt.value = "gym 90m =1.7"
        await pilot.press("enter")
        await pilot.pause()
    rows = _act_rows(db, app.today())
    assert (rows[0]["description"], rows[0]["factor"]) == ("gym 90m", 1.7)


async def test_the_question_is_about_the_whole_day_not_the_newest_entry(
    make_app, db, type_into
):
    """A PAL is not additive, so two sessions and one session are different days. The
    prompt has to carry both, and the profile's ordinary day too."""
    import datetime as dt
    from zoneinfo import ZoneInfo

    from daylogs.body import add_activity

    add_activity(db, description="swim 2km", date=DAY, at=1, factor=1.5,
                 source="estimated")
    seen = {}
    app = make_app(
        runner_json=_runner_factor(1.6, seen),
        height_cm=180, sex="male", birthday="1996-01-01", activity="desk",
        now=lambda: dt.datetime(2026, 9, 3, 9, 0, tzinfo=ZoneInfo("America/Toronto")),
    )
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("a")
        await type_into(pilot, "gym 1h")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
    assert "swim 2km" in seen["user_prompt"], "the day's earlier activity was dropped"
    assert "gym 1h" in seen["user_prompt"]
    assert "desk" in seen["user_prompt"], "the baseline was not sent"


async def test_a_failed_inference_still_records_what_you_did(make_app, db, type_into):
    """The description is your data; the factor is a guess. Losing "gym 1h" because
    the CLI was missing would be the worse outcome, and a NULL factor is a state the
    schema and `resolved_factor` already handle — the day falls back to the baseline."""
    from daylogs.claude import ClaudeError

    async def runner(**kwargs):
        raise ClaudeError("no cli")

    app = make_app(runner_json=runner)
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("a")
        await type_into(pilot, "gym 1h")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
    rows = _act_rows(db, app.today())
    assert len(rows) == 1, "the activity was lost with the estimate"
    assert rows[0]["factor"] is None
    assert rows[0]["description"] == "gym 1h"


async def test_a_bad_activity_line_keeps_the_text_and_writes_nothing(
    make_app, db, type_into
):
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.press("a")
        await type_into(pilot, "gym =9")
        await pilot.press("enter")
        await pilot.pause()
        still_open, kept = app.prompt.is_open, app.prompt.value
    assert still_open is True
    assert kept == "gym =9"
    assert _act_rows(db, app.today()) == []


# ── the activity sub-view ────────────────────────────────────────────────


async def test_activity_is_a_third_sub_view(make_app, db):
    """Without it the table is invisible and its rows can only be superseded, never
    removed."""
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.pause()
        row = _view_row(app)
    assert "activity" in row, f"the view strip does not list it: {row!r}"


async def test_tab_and_shift_tab_walk_three_views_in_opposite_directions(make_app, db):
    """With two views direction was moot and `prev` was an alias for `next`. With
    three that alias would make shift+tab skip a pane."""
    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        await pilot.pause()
        body = app.query_one("#body")
        start = body.table_mode
        await pilot.press("tab")
        await pilot.pause()
        forward = body.table_mode
        await pilot.press("shift+tab")
        await pilot.pause()
        assert body.table_mode == start, "shift+tab did not undo tab"
        await pilot.press("shift+tab")
        await pilot.pause()
        assert body.table_mode != forward, "shift+tab walks the same way as tab"


async def test_the_activity_table_lists_the_days_rows(make_app, db):
    from daylogs.body import add_activity

    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        add_activity(db, description="gym 1h", date=app.today(), at=1, factor=1.45,
                     source="estimated")
        add_activity(db, description="long walk", date=app.today(), at=2, factor=None,
                     source="estimated")
        body = app.query_one("#body")
        body.table_mode = "activity"
        body.reload()
        await pilot.pause()
        table = app.query_one("#body-table")
        cells = [str(c) for r in range(table.row_count)
                 for c in table.get_row_at(r)]
    assert any("gym 1h" in c for c in cells)
    assert any("×1.45" in c for c in cells), f"the factor is not shown: {cells}"
    assert any(c == "—" for c in cells), f"a factorless row needs a dash: {cells}"


async def test_the_activity_header_names_the_days_factor_and_its_origin(
    make_app, make_cfg, db
):
    from daylogs.body import add_activity

    add_weight(db, kg=80.0, date=DAY, at=1)
    add_activity(db, description="gym", date=DAY, at=2, factor=1.6, source="estimated")
    app = make_app(cfg=_profile(make_cfg, activity="desk"))
    async with app.run_test(size=(110, 34)) as pilot:
        await go_body(pilot, app)
        body = app.query_one("#body")
        body.table_mode = "activity"
        body.viewing_date = DAY
        body.reload()
        await pilot.pause()
        head = str(app.query_one("#food-head").content)
    assert head.startswith("ACTIVITY"), f"the header names the wrong view: {head!r}"
    assert "×1.6" in head and "logged" in head
    assert f"{_GYM_BURN:,}" in head, f"the burn it produces is missing: {head!r}"


async def test_the_activity_header_names_the_fix_when_there_is_no_factor(make_app, db):
    app = make_app()
    async with app.run_test(size=(110, 34)) as pilot:
        await go_body(pilot, app)
        body = app.query_one("#body")
        body.table_mode = "activity"
        body.reload()
        await pilot.pause()
        head = str(app.query_one("#food-head").content)
    assert "press h" in head, f"an empty state that names no fix: {head!r}"


async def test_enter_edits_an_activity_row(make_app, db, type_into):
    from daylogs.body import add_activity

    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        add_activity(db, description="gym", date=app.today(), at=1, factor=1.4,
                     source="estimated")
        body = app.query_one("#body")
        body.table_mode = "activity"
        body.reload()
        await pilot.pause()
        app.query_one("#body-table").focus()
        await pilot.press("enter")
        await pilot.pause()
        assert app.prompt.label == "activity", f"wrong prompt: {app.prompt.label!r}"
        assert "gym" in app.prompt.value and "=1.4" in app.prompt.value
        app.prompt.value = "gym, upper body =1.6"
        await pilot.press("enter")
        await pilot.pause()
    rows = _act_rows(db, app.today())
    assert len(rows) == 1, "an edit inserted a second row"
    assert (rows[0]["description"], rows[0]["factor"]) == ("gym, upper body", 1.6)


async def test_editing_an_activity_does_not_ask_claude(make_app, db, type_into):
    """An edit with no `=` leaves the stored factor alone. Only the entry path infers,
    or fixing a typo would silently re-roll the number."""
    from daylogs.body import add_activity

    called = []

    async def runner(**kwargs):
        called.append(kwargs)
        return {"factor": 1.9}

    app = make_app(runner_json=runner)
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        add_activity(db, description="gym", date=app.today(), at=1, factor=1.4,
                     source="estimated")
        body = app.query_one("#body")
        body.table_mode = "activity"
        body.reload()
        await pilot.pause()
        app.query_one("#body-table").focus()
        await pilot.press("enter")
        await pilot.pause()
        app.prompt.value = "gym, upper body"
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
    rows = _act_rows(db, app.today())
    assert called == [], "an edit triggered an inference"
    assert (rows[0]["description"], rows[0]["factor"]) == ("gym, upper body", 1.4)


async def test_x_deletes_an_activity_and_u_restores_it(make_app, db):
    from daylogs.body import add_activity

    app = make_app()
    async with app.run_test() as pilot:
        await go_body(pilot, app)
        add_activity(db, description="gym", date=app.today(), at=1, factor=1.4,
                     source="estimated")
        body = app.query_one("#body")
        body.table_mode = "activity"
        body.reload()
        await pilot.pause()
        app.query_one("#body-table").focus()
        await pilot.press("x")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        assert _act_rows(db, app.today()) == [], "delete did nothing"
        await pilot.press("u")
        await pilot.pause()
    rows = _act_rows(db, app.today())
    assert len(rows) == 1 and rows[0]["factor"] == 1.4


# ── the weight table follows the window ──────────────────────────────────
# It used to be `list_weight(limit=60)`: no span and no viewed date, so `[`/`]` and
# `+`/`-` moved the chart and the header while the table underneath sat still. The
# header said "60 most recent weigh-ins" precisely because claiming the span would
# have been a lie — which made the honest label a standing admission of the bug.


def _weight_rows(app):
    table = app.query_one("#body-table")
    return [str(table.get_row_at(r)[0]) for r in range(table.row_count)]


async def _weight_view(app, *, date, horizon="1m"):
    body = app.query_one("#body")
    body.table_mode = "weight"
    body.viewing_date = date
    body.horizon = horizon
    body.reload()
    return body


async def test_the_weight_table_lists_only_the_windows_weigh_ins(make_app, db):
    for day in ("2026-06-15", "2026-09-01", "2026-09-02"):
        add_weight(db, kg=80.0, date=day, at=int(day[-2:]))
    app = make_app()
    async with app.run_test(size=(110, 34)) as pilot:
        await go_body(pilot, app)
        await _weight_view(app, date=DAY)
        await pilot.pause()
        rows = _weight_rows(app)
    assert rows == ["2026-09-02", "2026-09-01"], f"not the window's rows: {rows}"


async def test_a_weigh_in_after_the_window_is_excluded(make_app, db):
    """Viewing an older day must not list readings that had not happened yet — the
    same rule the chart and every figure on the tab follow."""
    for day in ("2026-07-05", "2026-09-02"):
        add_weight(db, kg=80.0, date=day, at=int(day[-2:]))
    app = make_app()
    async with app.run_test(size=(110, 34)) as pilot:
        await go_body(pilot, app)
        await _weight_view(app, date="2026-07-10")
        await pilot.pause()
        rows = _weight_rows(app)
    assert rows == ["2026-07-05"], f"leaked a later reading: {rows}"


async def test_zooming_out_brings_more_weigh_ins_into_the_table(make_app, db):
    for day in ("2026-06-15", "2026-09-02"):
        add_weight(db, kg=80.0, date=day, at=int(day[-2:]))
    app = make_app()
    async with app.run_test(size=(110, 34)) as pilot:
        await go_body(pilot, app)
        await _weight_view(app, date=DAY)
        await pilot.pause()
        assert _weight_rows(app) == ["2026-09-02"]
        await pilot.press("minus")          # 1m -> MTD ... keep going to 3m
        await pilot.press("minus")
        await pilot.press("minus")
        await pilot.pause()
        wider = _weight_rows(app)
    assert "2026-06-15" in wider, f"zooming out did not reach the table: {wider}"


async def test_stepping_the_period_moves_the_table(make_app, db):
    for day in ("2026-08-02", "2026-09-02"):
        add_weight(db, kg=80.0, date=day, at=int(day[-2:]))
    app = make_app()
    async with app.run_test(size=(110, 34)) as pilot:
        await go_body(pilot, app)
        await _weight_view(app, date="2026-09-02")
        await pilot.pause()
        assert _weight_rows(app) == ["2026-09-02"]
        for _ in range(31):
            await pilot.press("left_square_bracket")
        await pilot.pause()
        stepped = _weight_rows(app)
    assert stepped == ["2026-08-02"], f"the table did not follow `[`: {stepped}"


async def test_the_weight_header_names_the_window_and_the_count(make_app, db):
    for day in ("2026-09-01", "2026-09-02"):
        add_weight(db, kg=80.0, date=day, at=int(day[-2:]))
    app = make_app()
    async with app.run_test(size=(110, 34)) as pilot:
        await go_body(pilot, app)
        body = await _weight_view(app, date=DAY)
        await pilot.pause()
        head = str(app.query_one("#food-head").content)
        label = body.span().label
    assert head.startswith("WEIGHT")
    assert label in head, f"the header does not name the window: {head!r}"
    assert "2 weigh-ins" in head, f"the header does not count the rows: {head!r}"
    assert "most recent" not in head, "still admitting it ignores the span"


async def test_one_weigh_in_is_not_pluralised(make_app, db):
    add_weight(db, kg=80.0, date="2026-09-02", at=1)
    app = make_app()
    async with app.run_test(size=(110, 34)) as pilot:
        await go_body(pilot, app)
        await _weight_view(app, date=DAY)
        await pilot.pause()
        head = str(app.query_one("#food-head").content)
    assert "1 weigh-in" in head and "1 weigh-ins" not in head, f"{head!r}"


async def test_an_empty_window_names_the_fix(make_app, db):
    """A window with nothing in it is true and useless on its own; it has to say what
    would change it."""
    add_weight(db, kg=80.0, date="2026-01-05", at=1)
    app = make_app()
    async with app.run_test(size=(110, 34)) as pilot:
        await go_body(pilot, app)
        await _weight_view(app, date=DAY)
        await pilot.pause()
        head = str(app.query_one("#food-head").content)
    assert "no weigh-ins" in head, f"{head!r}"
    assert "press w" in head, f"the empty state names no fix: {head!r}"


async def test_the_weight_table_is_newest_first(make_app, db):
    for day in ("2026-08-30", "2026-09-01", "2026-09-02"):
        add_weight(db, kg=80.0, date=day, at=int(day[-2:]))
    app = make_app()
    async with app.run_test(size=(110, 34)) as pilot:
        await go_body(pilot, app)
        await _weight_view(app, date=DAY)
        await pilot.pause()
        rows = _weight_rows(app)
    assert rows == sorted(rows, reverse=True), f"not newest first: {rows}"


async def test_all_time_has_no_lower_bound(make_app, db):
    for day in ("2020-01-01", "2026-09-02"):
        add_weight(db, kg=80.0, date=day, at=1)
    app = make_app()
    async with app.run_test(size=(110, 34)) as pilot:
        await go_body(pilot, app)
        await _weight_view(app, date=DAY, horizon="all")
        await pilot.pause()
        rows = _weight_rows(app)
    assert rows == ["2026-09-02", "2020-01-01"], f"all time dropped a row: {rows}"


async def test_a_meal_estimate_and_a_factor_inference_do_not_cancel_each_other(
    make_app, db, type_into
):
    """The activity worker has its own `@work` group, and nothing tested it — removing
    the token left all tests green.

    The severe direction is this one: with a shared group, pressing `f` during a factor
    inference cancels `_run_factor_estimate` before it writes, so "gym 1h" is never
    recorded at all — a direct violation of "a failed activity inference still records the
    activity". A cancelled worker also never reaches `_set_inferring(False)`, so the
    indicator would stick on forever rather than clearing.
    """
    import asyncio

    release = asyncio.Event()

    async def slow_factor(**kw):
        await release.wait()
        return {"factor": 1.6}

    async def quick_food(**kw):
        return {"description": "salad", "kcal": 120}

    calls = {"n": 0}

    async def runner_json(**kw):
        calls["n"] += 1
        # The factor call is the one carrying a `system_prompt` about PAL; the food
        # estimate is the other. Dispatch on that rather than on call order.
        if "activity level" in str(kw.get("system_prompt", "")).lower():
            return await slow_factor(**kw)
        return await quick_food(**kw)

    app = make_app(runner_json=runner_json)
    async with app.run_test(size=(120, 34)) as pilot:
        await go_body(pilot, app)
        await pilot.press("a")
        await type_into(pilot, "gym 1h")
        await pilot.press("enter")
        await pilot.pause()

        # A meal estimate starts while the inference is still in flight.
        await pilot.press("f")
        await type_into(pilot, "salad")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()

        release.set()
        for _ in range(6):
            await pilot.pause()
        label = app.prompt.label
        body = app.query_one("#body")
        inferring, pending = body._inferring, body._pending_activity
    assert calls["n"] == 2, f"one of the two calls never happened: {calls}"
    # A surviving inference offers its answer, which replaces the food confirm. Sharing
    # the group cancels the factor worker instead, so the label stays "confirm food" and
    # the number is silently never offered — the activity would then only ever be written
    # by the failure path, with no factor.
    assert label == "confirm activity", f"the inference was cancelled: {label!r}"
    assert pending is not None and pending.factor == 1.6
    # A cancelled worker never reaches `_set_inferring(False)`, so the "estimating…"
    # indicator would stick on forever rather than clearing.
    assert inferring is False, "the estimating indicator never cleared"
