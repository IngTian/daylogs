from daybook.body import add_food, add_weight, list_food, list_weight
from daybook.estimate import Estimate


async def test_w_logs_a_weight(make_app, db, type_into):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.press("w")
        await type_into(pilot, "78.2")
        await pilot.press("enter")
        await pilot.pause()
    rows = list_weight(db)
    assert len(rows) == 1 and rows[0]["kg"] == 78.2


async def test_w_with_a_bad_value_writes_nothing(make_app, db, type_into):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.press("w")
        await type_into(pilot, "heavy")
        await pilot.press("enter")
        await pilot.pause()
        assert app.is_running is True
    assert list_weight(db) == []


async def test_weight_header_renders_the_reading(make_app, db, type_into):
    app = make_app()
    async with app.run_test() as pilot:
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

    monkeypatch.setattr("daybook.tui.body_tab.estimate.from_text", fake_from_text)
    app = make_app()
    async with app.run_test() as pilot:
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

    monkeypatch.setattr("daybook.tui.body_tab.estimate.from_text", fake_from_text)
    app = make_app()
    async with app.run_test() as pilot:
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
    from daybook.claude import ClaudeError

    async def boom(**kw):
        raise ClaudeError("no claude")

    monkeypatch.setattr("daybook.tui.body_tab.estimate.from_text", boom)
    app = make_app()
    async with app.run_test() as pilot:
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

    monkeypatch.setattr("daybook.tui.body_tab.photo.clipboard_image", lambda d: None)

    async def fake_from_image(**kw):
        assert "meal.jpg" in str(kw["image_path"])
        return Estimate(description="ribeye + eggs", kcal=910)

    monkeypatch.setattr("daybook.tui.body_tab.estimate.from_image", fake_from_image)

    app = make_app()
    async with app.run_test() as pilot:
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
    from daybook.claude import ClaudeError

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    img = inbox / "meal.jpg"
    img.write_bytes(b"\xff\xd8\xff")

    monkeypatch.setattr("daybook.tui.body_tab.photo.clipboard_image", lambda d: None)

    async def boom(**kw):
        raise ClaudeError("down")

    monkeypatch.setattr("daybook.tui.body_tab.estimate.from_image", boom)

    app = make_app()
    async with app.run_test() as pilot:
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

    monkeypatch.setattr("daybook.tui.body_tab.photo.clipboard_image", lambda d: clip)
    seen = {}

    async def fake_from_image(**kw):
        seen["path"] = str(kw["image_path"])
        return Estimate(description="clip meal", kcal=100)

    monkeypatch.setattr("daybook.tui.body_tab.estimate.from_image", fake_from_image)

    app = make_app()
    async with app.run_test() as pilot:
        await pilot.press("p")
        await pilot.pause()
        await pilot.pause()
    assert "clip.png" in seen["path"]
    assert (inbox / "meal.jpg").exists()


async def test_p_with_nothing_available_opens_the_path_prompt(make_app, db, monkeypatch):
    monkeypatch.setattr("daybook.tui.body_tab.photo.clipboard_image", lambda d: None)
    app = make_app()
    async with app.run_test() as pilot:
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
        await pilot.pause()
        line = app.query_one("#inbox-line")
        assert line.display is True
        assert "2 photos" in str(line.content)


async def test_inbox_line_hidden_when_empty(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one("#inbox-line").display is False


async def test_bracket_keys_move_the_viewing_date(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        start = app.query_one("#body").viewing_date
        await pilot.press("[")
        assert app.query_one("#body").viewing_date < start
        await pilot.press("]")
        assert app.query_one("#body").viewing_date == start


async def test_tab_toggles_the_table_mode(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        body = app.query_one("#body")
        assert body.table_mode == "food"
        await pilot.press("tab")
        assert body.table_mode == "weight"
        await pilot.press("tab")
        assert body.table_mode == "food"


async def test_x_deletes_the_selected_food_row_and_u_restores_it(make_app, db):
    add_food(db, description="salad", kcal=610, source="labeled", date="2026-08-27", at=1)
    app = make_app()
    async with app.run_test() as pilot:
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
        await pilot.pause()
        await pilot.press("x")
        await pilot.pause()
        assert app.is_running is True


async def test_x_deletes_a_weight_row_in_weight_mode(make_app, db):
    add_weight(db, kg=78.2, date="2026-08-27", at=1)
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("tab")
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
        await pilot.pause()
        body = app.query_one("#body")
        body.viewing_date = "2026-08-27"
        body.reload()
        await pilot.pause()
        head = str(app.query_one("#food-head").content)
    assert "BMR" in head and "net" in head


async def test_photo_path_prompt_rejects_a_non_image(make_app, tmp_path, type_into, monkeypatch):
    monkeypatch.setattr("daybook.tui.body_tab.photo.clipboard_image", lambda d: None)
    bad = tmp_path / "notes.txt"
    bad.write_text("x")
    app = make_app()
    async with app.run_test() as pilot:
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
    """Down is good — an assumption, since daybook stores no goal weight. The arrow
    carries the direction either way, so colour is emphasis, not the only signal."""
    import datetime as dt

    from daybook.tui.widgets import BAD, GOOD

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
        await pilot.press("tab")          # weight sub-view
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
        await pilot.press("tab")
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
        await pilot.press("tab")
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
        await pilot.press("tab")
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
        await pilot.press("tab")
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
        await pilot.press("enter")
        await pilot.pause()
        assert app.prompt.is_open is False


async def test_a_rejected_edit_leaves_nothing_on_the_undo_stack(make_app, db, type_into):
    """The pre-image is pushed after the write, not before. Pushing first left an
    entry for `u` to apply to a row that never changed."""
    add_weight(db, kg=78.2, date="2026-08-27", at=1, note="post-run")
    app = make_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.press("tab")
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
    app = make_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.press("tab")
        await pilot.press("enter")
        await pilot.pause()
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
        await pilot.press("enter")
        await pilot.pause()
        assert app.prompt.is_open, "no edit was armed, so this test proves nothing"
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
    app = make_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.press("tab")
        await pilot.press("enter")
        await pilot.pause()
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
        await pilot.press("enter")
        await pilot.pause()
        assert app.prompt.is_open, "no edit was armed, so this test proves nothing"
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
        await pilot.press("tab")
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
        await pilot.press("tab")
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
        await pilot.press("tab")
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
    from daybook.tui.footer import KeyFooter

    return str(app.query_one(KeyFooter).render())


async def test_the_food_header_shows_estimating_while_the_call_is_in_flight(
    make_app, db, type_into, monkeypatch
):
    runner, started, release = _gate()

    async def gated_from_text(**kw):
        return await runner(**kw)

    monkeypatch.setattr("daybook.tui.body_tab.estimate.from_text", gated_from_text)
    app = make_app()
    async with app.run_test() as pilot:
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
    monkeypatch.setattr("daybook.tui.body_tab.estimate.from_text", runner)
    app = make_app()
    async with app.run_test() as pilot:
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

    monkeypatch.setattr("daybook.tui.body_tab.estimate.from_text", gated)
    app = make_app()
    async with app.run_test(size=(120, 34)) as pilot:
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
    monkeypatch.setattr("daybook.tui.body_tab.photo.clipboard_image", lambda d: None)

    started, release = asyncio.Event(), asyncio.Event()

    async def gated(**kw):
        started.set()
        await release.wait()
        return Estimate(description="ribeye", kcal=910)

    monkeypatch.setattr("daybook.tui.body_tab.estimate.from_image", gated)
    now = lambda: dt.datetime(2026, 8, 28, 9, 0)  # noqa: E731
    app = make_app(now=now)
    async with app.run_test(size=(120, 34)) as pilot:
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
    from daybook.claude import ClaudeError

    async def boom(**kw):
        raise ClaudeError("no claude")

    monkeypatch.setattr("daybook.tui.body_tab.estimate.from_text", boom)
    app = make_app()
    async with app.run_test() as pilot:
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
    from daybook.claude import ClaudeError

    async def timed_out(**kw):
        raise ClaudeError("claude -p (json) timed out after 60s")

    monkeypatch.setattr("daybook.tui.body_tab.estimate.from_text", timed_out)
    app = make_app()
    async with app.run_test() as pilot:
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

    monkeypatch.setattr("daybook.tui.body_tab.estimate.from_text", two_stage)
    app = make_app()
    async with app.run_test() as pilot:
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
    monkeypatch.setattr("daybook.tui.body_tab.photo.clipboard_image", lambda d: None)

    started, release = asyncio.Event(), asyncio.Event()

    async def gated(**kw):
        started.set()
        await release.wait()
        return Estimate(description="ribeye", kcal=910)

    monkeypatch.setattr("daybook.tui.body_tab.estimate.from_image", gated)
    app = make_app()
    async with app.run_test() as pilot:
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

    monkeypatch.setattr("daybook.tui.body_tab.estimate.from_text", gated)
    app = make_app()
    async with app.run_test() as pilot:
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
    monkeypatch.setattr("daybook.tui.body_tab.photo.clipboard_image", lambda d: None)

    started, release = asyncio.Event(), asyncio.Event()
    toasts = []

    async def gated(**kw):
        started.set()
        await release.wait()
        return Estimate(description="ribeye", kcal=910)

    monkeypatch.setattr("daybook.tui.body_tab.estimate.from_image", gated)
    app = make_app()
    async with app.run_test(size=(120, 34)) as pilot:
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
    monkeypatch.setattr("daybook.tui.body_tab.photo.clipboard_image", lambda d: None)

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

    monkeypatch.setattr("daybook.tui.body_tab.estimate.from_image", image_call)
    monkeypatch.setattr("daybook.tui.body_tab.estimate.from_text", text_call)

    app = make_app()
    async with app.run_test() as pilot:
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
    monkeypatch.setattr("daybook.tui.body_tab.photo.clipboard_image", lambda d: None)
    monkeypatch.setattr(
        "daybook.tui.body_tab.estimate.from_image",
        lambda **kw: _immediate(Estimate(description="ribeye", kcal=910)),
    )
    monkeypatch.setattr(
        "daybook.tui.body_tab.estimate.from_text",
        lambda **kw: _immediate(Estimate(description="side salad", kcal=120)),
    )

    app = make_app()
    async with app.run_test(size=(120, 34)) as pilot:
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
    monkeypatch.setattr("daybook.tui.body_tab.photo.clipboard_image", lambda d: None)

    async def never(**kw):
        await asyncio.sleep(3600)

    monkeypatch.setattr("daybook.tui.body_tab.estimate.from_image", never)
    monkeypatch.setattr(
        "daybook.tui.body_tab.estimate.from_text",
        lambda **kw: _immediate(Estimate(description="side salad", kcal=120)),
    )

    app = make_app()
    async with app.run_test(size=(120, 34)) as pilot:
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
