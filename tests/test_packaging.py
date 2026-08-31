"""Guards on things that only break once the package is *installed*.

The stylesheet is loaded by path at runtime, so a missing package-data
declaration produces a wheel that imports fine and then crashes on startup.
An editable install cannot reproduce that, which is exactly why it needs a
test of its own.
"""

from importlib.resources import files
from pathlib import Path

from daylogs.tui.app import DaylogsApp


def test_stylesheet_ships_as_package_data():
    css = files("daylogs.tui").joinpath("app.tcss")
    assert css.is_file(), "app.tcss must live inside the daylogs.tui package"


def test_css_path_matches_the_file_that_exists():
    """CSS_PATH is resolved relative to app.py. If either the constant or the
    filename is renamed without the other, the app starts unstyled rather than
    failing loudly — so assert they agree."""
    assert DaylogsApp.CSS_PATH == "app.tcss"
    module_dir = Path(files("daylogs.tui").joinpath("app.tcss").__fspath__()).parent
    assert (module_dir / DaylogsApp.CSS_PATH).is_file()


def test_the_declared_version_matches_the_package():
    """`pyproject.toml` and `__version__` are two places carrying one fact.

    Nothing forced them to agree, so a bump could touch one and leave the other —
    and the symptom is `day --version` disagreeing with the wheel anyone installed,
    which is the kind of thing nobody notices until it matters.
    """
    import pathlib
    import tomllib

    from daylogs import __version__

    root = pathlib.Path(__file__).resolve().parents[1]
    declared = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    assert declared == __version__, (
        f"pyproject says {declared}, daylogs.__version__ says {__version__}"
    )
