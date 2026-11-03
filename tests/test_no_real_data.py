"""The no-real-data rule, enforced instead of remembered.

CLAUDE.md: "No real weights, amounts, names, or `/Users/<name>/` paths in tracked files.
Note the sdist carries the full source, so anything committed is public whatever the GitHub
setting says. Fixtures use round, obviously-fake numbers."

That rule has now failed four times in five weeks, every time the same way: a comment
explaining *why* some code exists reaches for the number that motivated it, and the number
that motivated it is the owner's own. Commit `e6d966b` was titled "Replace real amounts in
CLAUDE.md and a test comment with fixtures" — and the identical leak reappeared five weeks
later, in the very bullets that state the rule, and shipped in three releases before anyone
noticed. Remembering is what keeps failing, so this file greps instead.

What it can and cannot do, stated plainly so nobody trusts it further than it goes:

- It catches **amounts**. The signature of the leak is a money figure in prose with no
  fixture anywhere behind it — a real charge gets quoted once, in the comment, and appears
  in no test and no screenshot fixture, because it was never a test value.
- It cannot catch **names**. `Tradingview` is a vendor the owner pays and `Backups` is the
  fixture that replaced it, and nothing mechanical distinguishes them. Reviewing prose for
  names is still a human job.
- It deliberately does **not** hold a denylist of the owner's real figures, which would be
  the leak wearing a test's clothes.
"""

import ast
import io
import pathlib
import re
import tokenize

ROOT = pathlib.Path(__file__).resolve().parent.parent

# `1,234.56` or `12.40` — a money-shaped literal in prose. Two decimals is what makes it
# read as an amount rather than a count; `fmt`/`widgets.money` print exactly this shape.
AMOUNT = re.compile(r"\b\d{1,3}(?:,\d{3})*\.\d{2}\b")

# Prose figures that are not money, each with the reason it is here. Keep this list tiny:
# every entry is a place the heuristic cannot help, so a long list means the heuristic has
# stopped being worth running. An amount that is genuinely an example belongs in a fixture a
# test uses, which is the whole point — that is the fix, not an entry here.
NOT_MONEY = {
    "1.04",  # categories.py: a PAL activity factor
    "1.45",  # hints.py: a PAL activity factor
    "1.55",  # categories.py, parse.py: a PAL activity factor
    "0.15",  # money_tab.py: milliseconds, the measured summarize_month timing
    "239.95",  # money.py: an illustrative price in the thousands-separator rule
}


def _prose_lines(path: pathlib.Path) -> list[tuple[int, str]]:
    """Every comment and docstring in a module, with its line number.

    Comments come from `tokenize` and docstrings from `ast`, because neither sees the other:
    `tokenize` does not know a string is a docstring, and `ast` discards comments entirely.
    """
    src = path.read_text()
    out = [
        (t.start[0], t.string)
        for t in tokenize.generate_tokens(io.StringIO(src).readline)
        if t.type == tokenize.COMMENT
    ]
    for node in ast.walk(ast.parse(src)):
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            out.append((node.lineno, node.value.value))
    return out


def _fixture_corpus() -> str:
    """Everything a fake number is allowed to come from: the tests and the screenshot
    fixture. A number used by neither was not invented for this repo."""
    files = list((ROOT / "tests").rglob("*.py")) + [ROOT / "tools" / "screenshots.py"]
    return "\n".join(f.read_text() for f in files if f != pathlib.Path(__file__))


def test_no_amount_in_prose_lacks_a_fixture_behind_it():
    """An amount quoted in a comment must be one the tests actually use.

    This is the mechanical form of "fixtures use round, obviously-fake numbers": if a figure
    explains a behaviour, a test exercises that behaviour, so the figure is in the test. One
    that appears only in prose came from somewhere else — and the only other place numbers
    come from here is the owner's database.
    """
    corpus = _fixture_corpus()
    offenders: dict[str, set[str]] = {}
    for path in sorted((ROOT / "daylogs").rglob("*.py")):
        for lineno, text in _prose_lines(path):
            for found in AMOUNT.findall(text):
                if found in NOT_MONEY or found.replace(",", "") in NOT_MONEY:
                    continue
                if found in corpus or found.replace(",", "") in corpus:
                    continue
                rel = path.relative_to(ROOT)
                offenders.setdefault(f"{rel}:{lineno}", set()).add(found)
    assert offenders == {}, (
        "these amounts appear in prose but in no test or screenshot fixture, so nothing "
        f"in the repo generates them: { {k: sorted(v) for k, v in offenders.items()} } — "
        "replace them with a number a test uses, or add to NOT_MONEY with the reason"
    )


def test_the_scan_actually_reads_the_prose():
    """Positive control, through the same two extractors.

    An absence assertion cannot tell "nothing to find" from "stopped looking" — this repo
    has already shipped a grep guard that passed with its predicate short-circuited. If the
    glob breaks or `_prose_lines` returns nothing, the test above goes green forever; this
    one collapses to zero and fails instead.

    The floors are far below the real counts (hundreds of prose lines, and `money.py` alone
    carries dozens of amounts) so that ordinary editing cannot trip it.
    """
    modules = list((ROOT / "daylogs").rglob("*.py"))
    assert len(modules) >= 15, f"the module glob found almost nothing: {len(modules)}"

    prose = [pair for path in modules for pair in _prose_lines(path)]
    assert len(prose) >= 200, (
        f"the prose extractors returned almost nothing ({len(prose)} blocks) — "
        "the assertion above proves nothing"
    )

    # And the regex still matches the shape it is for, on real repo prose rather than a
    # literal written here: an allowlisted figure the scan is known to reach.
    seen = {m for _, text in prose for m in AMOUNT.findall(text)}
    assert seen & {"239.95"}, (
        f"the amount regex matched none of the known figures in prose: {sorted(seen)[:10]}"
    )


def test_no_home_directory_paths_are_tracked():
    """`/Users/<name>/` names the owner. Checked over prose *and* code, unlike the amount
    scan, because a hardcoded path is as likely in a default as in a comment — and CLAUDE.md
    records a session that hardcoded an interpreter path which then stopped existing.
    """
    pattern = re.compile(r"/Users/[A-Za-z0-9._-]+/")
    offenders = []
    for path in sorted(ROOT.rglob("*.py")):
        if "/.venv/" in str(path) or path == pathlib.Path(__file__):
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno}")
    for name in ("README.md", "CLAUDE.md"):
        text = (ROOT / name).read_text()
        for lineno, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{name}:{lineno}")
    assert offenders == [], f"these name a real home directory: {offenders}"
