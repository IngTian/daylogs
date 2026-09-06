import time


def test_animations_are_disabled(make_app):
    """Nothing in this app is worth animating, and off is never slower.

    A specific figure used to be stated here as measured fact — 383 ms -> 106 ms per tab
    switch — while CLAUDE.md and app.py said 383 ms -> 127 ms, and app.py's own "~277 ms
    saved" only adds up against 106. Nothing recorded which of the two was measured, or
    how. Re-measured through this harness (36 switches per level, three fresh apps, both
    orderings): the minimum is 8 ms at *every* level and the median runs 16-17 ms off
    against 20-21 ms on. The direction survives; the magnitude does not.

    That is a limit of the harness rather than a refutation — `pilot.press` returns once
    the key is processed, so it cannot see an animation settle in a real terminal, which
    is where the original number presumably came from. Which is the point: the figure is
    no longer quoted as fact in three places in two different versions, because nothing
    here can re-derive it and a number that cannot be checked is what went stale.

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
    """A ceiling, not a benchmark: loose enough not to flake on shared CI, tight enough
    to catch a switch becoming pathological. Deliberately far above what a healthy switch
    costs here (8 ms at best, ~17 ms typical) — tightening it towards the measurement
    would trade a real guard for a flaky one on a loaded runner."""
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        best = 10.0
        for key in ("2", "3", "1", "2", "3"):
            start = time.perf_counter()
            await pilot.press(key)
            best = min(best, time.perf_counter() - start)
    assert best < 0.30, f"fastest tab switch was {best * 1000:.0f} ms"
