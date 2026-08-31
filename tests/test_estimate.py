import pytest

from daylogs.claude import ClaudeError
from daylogs.estimate import ESTIMATE_SCHEMA, Estimate, from_image, from_text


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
