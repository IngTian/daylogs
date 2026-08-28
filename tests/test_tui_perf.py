import time


def test_animations_are_disabled(make_app):
    """383 ms -> 106 ms per tab switch, measured.

    `animation_level` is an instance attribute in textual 8.2, populated from
    constants.TEXTUAL_ANIMATIONS during App.__init__ — a class attribute named
    ANIMATION_LEVEL does nothing at all, so this asserts the instance.
    """
    assert make_app().animation_level == "none"


async def test_animations_stay_disabled_once_running(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.animation_level == "none"


async def test_tab_switch_is_not_pathologically_slow(make_app):
    """A ceiling, not a benchmark: loose enough not to flake on shared CI,
    tight enough to catch the animation coming back (which cost ~383 ms)."""
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        best = 10.0
        for key in ("2", "3", "1", "2", "3"):
            start = time.perf_counter()
            await pilot.press(key)
            best = min(best, time.perf_counter() - start)
    assert best < 0.30, f"fastest tab switch was {best * 1000:.0f} ms"
