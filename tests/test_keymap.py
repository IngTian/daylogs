from daylogs.tui import keymap as km


def test_no_duplicate_key_within_a_scope():
    seen = set()
    for k in km.KEYMAP:
        pair = (k.key, k.scope)
        assert pair not in seen, f"{k.key!r} defined twice in scope {k.scope!r}"
        seen.add(pair)


def test_no_tab_key_shadows_an_app_key():
    app_keys = {k.key for k in km.KEYMAP if k.scope == "app"}
    for k in km.KEYMAP:
        if k.scope != "app":
            assert k.key not in app_keys, f"{k.key!r} in {k.scope!r} shadows an app key"


def test_every_scope_and_kind_is_declared():
    for k in km.KEYMAP:
        assert k.scope in km.SCOPES
        assert k.kind in km.KINDS


def test_the_promised_navigation_keys_exist():
    app = {k.key for k in km.keys_for("app")}
    for key in (
        "1", "2", "3", "tab", "shift+tab", "left_square_bracket",
        "right_square_bracket", "t", "g", "plus", "equals_sign", "minus", "question_mark",
        "u", "escape", "q",
    ):
        assert key in app, f"missing app key {key!r}"


def test_scoped_write_keys_exist():
    body = {k.key for k in km.keys_for("body")}
    money = {k.key for k in km.keys_for("money")}
    summary = {k.key for k in km.keys_for("summary")}
    assert {"w", "f", "p", "a", "x"} <= body
    assert {"e", "b", "s", "r", "x", "d", "c", "k", "slash", "G", "enter"} <= money
    assert "r" in summary


def test_r_means_different_things_in_two_scopes():
    assert km.lookup("r", "money").action == "roll"
    assert km.lookup("r", "summary").action == "generate"


def test_lookup_falls_back_to_app_scope():
    assert km.lookup("q", "money").action == "quit"
    assert km.lookup("t", "summary").action == "jump_now"
    assert km.lookup("nonexistent", "money") is None


def test_body_does_not_get_money_only_keys():
    assert km.lookup("slash", "body") is None
    assert km.lookup("e", "body") is None


def test_app_bindings_covers_every_bindable_key_exactly_once():
    keys = [b[0] for b in km.app_bindings()]
    assert len(keys) == len(set(keys)), "a key is bound twice at app level"
    assert set(keys) == {k.key for k in km.KEYMAP if k.bind}


def test_app_binding_actions_are_dispatch_calls():
    for key, action, _, _prio in km.app_bindings():
        assert action == f"dispatch('{key}')"


def test_enter_is_not_bound_because_datatable_owns_it():
    """Measured: a focused DataTable converts enter into RowSelected, so an App
    binding never fires. Activation rides that message instead."""
    assert km.lookup("enter", "money").bind is False
    assert "enter" not in {b[0] for b in km.app_bindings()}


def test_only_tab_keys_are_priority():
    """Measured: an ordinary binding for tab loses to the Screen's focus-next.
    Priority on printable keys is unnecessary (Textual still routes characters to
    a focused Input) and on enter/slash/plus it would break the prompt outright."""
    prio = {b[0] for b in km.app_bindings() if b[3]}
    assert prio == {"tab", "shift+tab"}


def test_no_printable_key_is_priority():
    for k in km.KEYMAP:
        if k.priority:
            assert k.key in ("tab", "shift+tab"), (
                f"{k.key!r} is priority; a printable priority key can steal "
                "characters from the prompt"
            )


def test_footer_keys_are_a_subset_and_respect_the_flag():
    for scope in km.SCOPES:
        shown = km.footer_keys(scope)
        assert all(k.footer for k in shown)
        allowed = set(km.keys_for(scope)) | set(km.keys_for("app"))
        assert set(shown) <= allowed


def test_footer_for_a_tab_includes_app_keys_too():
    keys = {k.key for k in km.footer_keys("money")}
    assert "t" in keys and "q" in keys


def test_footer_puts_scope_verbs_before_app_keys():
    order = [k.scope for k in km.footer_keys("body")]
    assert order[0] == "body"
    assert order[-1] == "app"


def test_help_groups_are_keyed_by_kind_and_cover_everything():
    groups = km.help_groups()
    assert set(groups) <= set(km.KINDS)
    assert sum(len(v) for v in groups.values()) == len(km.KEYMAP)


def test_every_action_is_a_valid_handler_suffix():
    for k in km.KEYMAP:
        assert k.action.isidentifier(), f"{k.action!r} is not a valid handler suffix"


def test_labels_are_present_and_short():
    for k in km.KEYMAP:
        assert k.label, f"{k.key!r} has no label"
        assert len(k.label) <= 24


def test_a_logs_an_activity_and_only_on_body():
    """Body-scoped, not app: there is nothing to log an activity against on Money, and
    an app-scope `a` would shadow any future tab's own use of the letter."""
    assert km.lookup("a", "body").action == "activity"
    assert km.lookup("a", "money") is None
    assert km.lookup("a", "summary") is None
