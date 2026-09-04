import pytest

from daylogs.config import load_config, system_timezone, update_config


def test_defaults_when_no_file(tmp_path):
    cfg = load_config(tmp_path)
    assert cfg.root == tmp_path
    assert cfg.db_path == tmp_path / "daylogs.db"
    assert cfg.inbox_dir == tmp_path / "inbox"
    assert cfg.memory_path == tmp_path / "memory.md"
    # The machine's zone, not a literal. See test_timezone.py for why.
    assert cfg.timezone == system_timezone()
    assert cfg.summary_after_hour == 6
    assert cfg.summary_timeout_sec == 120
    assert cfg.estimate_timeout_sec == 60
    assert cfg.height_cm is None
    assert cfg.claude_model is None
    assert cfg.extra_categories == ()


def test_reads_toml_and_expands_user(tmp_path):
    (tmp_path / "config.toml").write_text(
        'timezone = "UTC"\n'
        "height_cm = 170\n"
        'sex = "female"\n'
        'birthday = "1990-01-01"\n'
        "summary_after_hour = 9\n"
        'db_path = "custom/other.db"\n'
        "\n"
        "[[category]]\n"
        'slug = "gym"\n'
        'display = "Gym"\n'
        'color = "#9ba068"\n'
    )
    cfg = load_config(tmp_path)
    assert cfg.timezone == "UTC"
    assert cfg.height_cm == 170.0
    assert cfg.sex == "female"
    assert cfg.birthday == "1990-01-01"
    assert cfg.summary_after_hour == 9
    assert cfg.db_path == tmp_path / "custom" / "other.db"
    assert cfg.extra_categories == (("gym", "Gym", "#9ba068"),)


def test_env_override_selects_root(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYLOGS_HOME", str(tmp_path / "elsewhere"))
    cfg = load_config()
    assert cfg.root == tmp_path / "elsewhere"


def test_malformed_toml_raises_with_path_in_message(tmp_path):
    (tmp_path / "config.toml").write_text("timezone = \n")
    with pytest.raises(ValueError, match="config.toml"):
        load_config(tmp_path)


def test_unknown_keys_are_ignored_not_fatal(tmp_path):
    (tmp_path / "config.toml").write_text('nonsense_key = 1\ntimezone = "UTC"\n')
    assert load_config(tmp_path).timezone == "UTC"


def test_absolute_db_path_is_respected(tmp_path):
    (tmp_path / "config.toml").write_text(f'db_path = "{tmp_path / "abs.db"}"\n')
    assert load_config(tmp_path).db_path == tmp_path / "abs.db"


# ── update_config ────────────────────────────────────────────────────────


def test_update_config_creates_a_missing_file(tmp_path):
    path = tmp_path / "sub" / "config.toml"
    update_config(path, {"height_cm": 170.0, "sex": "female"})
    cfg = load_config(path.parent)
    assert cfg.height_cm == 170.0
    assert cfg.sex == "female"


def test_update_config_replaces_a_key_instead_of_duplicating_it(tmp_path):
    path = tmp_path / "config.toml"
    update_config(path, {"height_cm": 170.0})
    update_config(path, {"height_cm": 181.5})
    assert path.read_text().count("height_cm") == 1
    assert load_config(tmp_path).height_cm == 181.5


def test_update_config_preserves_comments_and_other_keys(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("# hand-written\nsummary_after_hour = 9\n")
    update_config(path, {"sex": "male"})
    text = path.read_text()
    assert "# hand-written" in text
    assert load_config(tmp_path).summary_after_hour == 9
    assert load_config(tmp_path).sex == "male"


def test_new_keys_go_before_a_table_not_after_it(tmp_path):
    """A scalar written after `[[category]]` becomes a field *of that table*. The
    file still parses, so nothing complains — the setting is just never read."""
    path = tmp_path / "config.toml"
    path.write_text('[[category]]\nslug = "gym"\ndisplay = "Gym"\n')
    update_config(path, {"height_cm": 180.0})
    text = path.read_text()
    assert text.index("height_cm") < text.index("[[category]]")
    cfg = load_config(tmp_path)
    assert cfg.height_cm == 180.0
    assert cfg.extra_categories == (("gym", "Gym", ""),)


def test_update_config_does_not_touch_a_matching_key_inside_a_table(tmp_path):
    """`display` exists inside [[category]]; a top-level write must not hijack it."""
    path = tmp_path / "config.toml"
    path.write_text('[[category]]\nslug = "gym"\ndisplay = "Gym"\n')
    update_config(path, {"display": "nope"})
    cfg = load_config(tmp_path)
    assert cfg.extra_categories == (("gym", "Gym", ""),)


def test_update_config_quotes_strings_and_escapes_quotes(tmp_path):
    path = tmp_path / "config.toml"
    update_config(path, {"claude_model": 'a "quoted" name'})
    assert load_config(tmp_path).claude_model == 'a "quoted" name'


def test_update_config_result_is_always_valid_toml(tmp_path):
    import tomllib

    path = tmp_path / "config.toml"
    path.write_text('# c\ntimezone = "UTC"\n\n[[category]]\nslug = "gym"\n')
    update_config(path, {"height_cm": 180.0, "sex": "male", "birthday": "1990-01-01"})
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    assert data["height_cm"] == 180.0
    assert data["timezone"] == "UTC"
    assert data["category"] == [{"slug": "gym"}]


def test_update_config_leaves_no_temp_file_behind(tmp_path):
    path = tmp_path / "config.toml"
    update_config(path, {"height_cm": 180.0})
    assert [p.name for p in tmp_path.iterdir()] == ["config.toml"]


# ── theme ────────────────────────────────────────────────────────────────


def test_theme_defaults_to_gruvbox(tmp_path):
    """The default is a string chosen from a list Textual owns; test_themes.py
    guards that the name still exists there."""
    from daylogs.config import load_config

    assert load_config(tmp_path).theme == "gruvbox"


def test_theme_is_read_from_config(tmp_path):
    from daylogs.config import load_config

    (tmp_path / "config.toml").write_text('theme = "nord"\n')
    assert load_config(tmp_path).theme == "nord"


def test_an_unreadable_theme_value_does_not_break_loading(tmp_path):
    """config.py stays pure — it does not know which names are valid, so a wrong
    one loads fine and the TUI layer resolves it. Validating here would drag
    Textual into the config module."""
    from daylogs.config import load_config

    (tmp_path / "config.toml").write_text('theme = "nonsense"\n')
    assert load_config(tmp_path).theme == "nonsense"
