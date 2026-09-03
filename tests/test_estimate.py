import pytest

from daylogs.body import FACTOR_MAX, FACTOR_MIN
from daylogs.claude import ClaudeError
from daylogs.estimate import (
    ESTIMATE_SCHEMA,
    FACTOR_SCHEMA,
    Effort,
    Estimate,
    factor_from_text,
    from_image,
    from_text,
)


async def test_from_text_returns_estimate():
    async def runner(**kwargs):
        assert kwargs["json_schema"] == ESTIMATE_SCHEMA
        assert "chicken caesar salad" in kwargs["user_prompt"]
        return {"description": "chicken caesar salad", "kcal": 610}

    got = await from_text(description="chicken caesar salad", runner=runner, timeout_sec=5)
    assert got == Estimate(description="chicken caesar salad", kcal=610)


async def test_from_text_system_prompt_says_there_is_no_image():
    seen = {}

    async def runner(**kwargs):
        seen.update(kwargs)
        return {"description": "salad", "kcal": 1}

    await from_text(description="salad", runner=runner, timeout_sec=5)
    assert "no image" in seen["system_prompt"]


async def test_from_image_passes_path_and_note(tmp_path):
    img = tmp_path / "p.jpg"
    img.write_bytes(b"x")
    seen = {}

    async def runner(**kwargs):
        seen.update(kwargs)
        return {"description": "ribeye + eggs", "kcal": 910}

    got = await from_image(image_path=img, note="big portion", runner=runner, timeout_sec=5)
    assert got.kcal == 910
    assert str(img.resolve()) in seen["prompt"]
    assert seen["image_path"] == str(img.resolve())
    assert "big portion" in seen["prompt"]


async def test_from_image_tolerates_absent_note(tmp_path):
    img = tmp_path / "p.jpg"
    img.write_bytes(b"x")

    async def runner(**kwargs):
        return {"description": "salad", "kcal": 300}

    got = await from_image(image_path=img, note=None, runner=runner, timeout_sec=5)
    assert got.kcal == 300


@pytest.mark.parametrize(
    "bad",
    [
        {"kcal": 610},
        {"description": "", "kcal": 610},
        {"description": "   ", "kcal": 610},
        {"description": "salad"},
        {"description": "salad", "kcal": "610"},
        {"description": "salad", "kcal": -5},
        {"description": "salad", "kcal": True},
    ],
)
async def test_schema_violations_raise(bad):
    async def runner(**kwargs):
        return bad

    with pytest.raises(ValueError):
        await from_text(description="salad", runner=runner, timeout_sec=5)


async def test_runner_error_propagates_as_claude_error():
    async def runner(**kwargs):
        raise ClaudeError("boom")

    with pytest.raises(ClaudeError):
        await from_text(description="salad", runner=runner, timeout_sec=5)


async def test_description_is_stripped_and_kcal_is_int():
    async def runner(**kwargs):
        return {"description": "  salad  ", "kcal": 610}

    got = await from_text(description="salad", runner=runner, timeout_sec=5)
    assert got.description == "salad" and isinstance(got.kcal, int)


async def test_zero_kcal_is_accepted():
    async def runner(**kwargs):
        return {"description": "black coffee", "kcal": 0}

    assert (await from_text(description="coffee", runner=runner, timeout_sec=5)).kcal == 0


# ── the activity factor ──────────────────────────────────────────────────
# A whole-day PAL multiplier, inferred from the baseline plus what was logged. The
# runner is injected here for the same reason it is above: no test spawns `claude`.


async def test_factor_from_text_returns_the_multiplier():
    async def runner(**kwargs):
        assert kwargs["json_schema"] == FACTOR_SCHEMA
        return {"factor": 1.45}

    got = await factor_from_text(
        activities=["gym 1h"], baseline="desk", runner=runner, timeout_sec=5
    )
    assert got == Effort(factor=1.45)


async def test_the_question_carries_the_baseline_and_the_days_activities():
    """"An ordinary day here is a desk job at 1.2, and today they also did gym 1h" is
    a far better-posed question than "estimate a multiplier"."""
    seen = {}

    async def runner(**kwargs):
        seen.update(kwargs)
        return {"factor": 1.5}

    await factor_from_text(
        activities=["gym 1h", "walked home"], baseline="desk",
        runner=runner, timeout_sec=5,
    )
    assert "desk" in seen["user_prompt"]
    assert "1.2" in seen["user_prompt"], "the baseline's multiplier is not stated"
    assert "gym 1h" in seen["user_prompt"]
    assert "walked home" in seen["user_prompt"], "only the last activity was sent"


async def test_an_unset_baseline_is_named_as_unset_not_silently_assumed():
    """The app never defaults the baseline. Assuming one for this single question is
    different in kind — the answer lands in a confirm prompt the user reads."""
    seen = {}

    async def runner(**kwargs):
        seen.update(kwargs)
        return {"factor": 1.5}

    await factor_from_text(
        activities=["gym"], baseline=None, runner=runner, timeout_sec=5
    )
    assert "not recorded" in seen["user_prompt"]


async def test_the_system_prompt_forbids_counting_exercise_twice():
    """The trap the whole design is built around: the baseline already covers
    occupational movement, so an estimate must adjust from it rather than re-add it."""
    seen = {}

    async def runner(**kwargs):
        seen.update(kwargs)
        return {"factor": 1.5}

    await factor_from_text(activities=["gym"], baseline="desk", runner=runner, timeout_sec=5)
    # Case-insensitive: the prompt shouts a couple of these words at the model on
    # purpose, and the test is about what it says, not how loudly.
    said = seen["system_prompt"].lower()
    assert "twice" in said
    assert "below" in said, "a day may be below its baseline; say so"


@pytest.mark.parametrize("bad", [{}, {"factor": None}, {"factor": "1.45"}, {"factor": True}])
async def test_a_factor_that_is_not_a_number_is_rejected_as_such(bad):
    """Asserted on the *message*, not just on ValueError, so the type guard is really
    pinned. `True` is an `int` in Python and would sail straight through a bare numeric
    check — it fails the range test too, but only because 1.0 happens to sit below the
    floor, which is a coincidence and not a guard.

    `--json-schema` already constrains all of this. It is validated again in Python so
    that a future CLI or model change surfaces as a clear error rather than as a number
    that silently rescales every calorie figure for the day.
    """

    async def runner(**kwargs):
        return bad

    with pytest.raises(ValueError, match="number"):
        await factor_from_text(
            activities=["gym"], baseline="desk", runner=runner, timeout_sec=5
        )


@pytest.mark.parametrize(
    "bad",
    [
        {"factor": 1.19},
        {"factor": 1.91},
        {"factor": 4.0},
        {"factor": 0},
        {"factor": float("nan")},
        {"factor": float("inf")},
    ],
)
async def test_a_factor_outside_the_physiological_range_is_rejected(bad):
    """A hallucinated 4.0 would triple the day's maintenance. `nan` is in here because
    it compares False against both bounds, which is what makes the plain range check
    reject it rather than let it through."""

    async def runner(**kwargs):
        return bad

    with pytest.raises(ValueError, match="between"):
        await factor_from_text(
            activities=["gym"], baseline="desk", runner=runner, timeout_sec=5
        )


@pytest.mark.parametrize("edge", [FACTOR_MIN, FACTOR_MAX])
async def test_the_range_ends_are_accepted(edge):
    async def runner(**kwargs):
        return {"factor": edge}

    got = await factor_from_text(
        activities=["gym"], baseline="desk", runner=runner, timeout_sec=5
    )
    assert got.factor == edge


async def test_a_long_tail_of_decimals_is_trimmed():
    """Three places, because `light` is 1.375. The panel prints the number, and
    `×1.4499999999` is noise."""

    async def runner(**kwargs):
        return {"factor": 1.4499999999}

    got = await factor_from_text(
        activities=["gym"], baseline="desk", runner=runner, timeout_sec=5
    )
    assert got.factor == 1.45


async def test_a_factor_runner_error_propagates_as_claude_error():
    async def runner(**kwargs):
        raise ClaudeError("boom")

    with pytest.raises(ClaudeError):
        await factor_from_text(
            activities=["gym"], baseline="desk", runner=runner, timeout_sec=5
        )
