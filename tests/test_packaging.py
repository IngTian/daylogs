"""Guards on things that only break once the package is *installed*.

The stylesheet is loaded by path at runtime, so a missing package-data
declaration produces a wheel that imports fine and then crashes on startup.
An editable install cannot reproduce that, which is exactly why it needs a
test of its own.
"""

from importlib.resources import files
from pathlib import Path

from daybook.tui.app import DaybookApp


def test_stylesheet_ships_as_package_data():
    css = files("daybook.tui").joinpath("app.tcss")
    assert css.is_file(), "app.tcss must live inside the daybook.tui package"


def test_css_path_matches_the_file_that_exists():
    """CSS_PATH is resolved relative to app.py. If either the constant or the
    filename is renamed without the other, the app starts unstyled rather than
    failing loudly — so assert they agree."""
    assert DaybookApp.CSS_PATH == "app.tcss"
    module_dir = Path(files("daybook.tui").joinpath("app.tcss").__fspath__()).parent
    assert (module_dir / DaybookApp.CSS_PATH).is_file()
