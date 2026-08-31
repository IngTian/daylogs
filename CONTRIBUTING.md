# Contributing

Thanks for looking. One thing to know before you open a PR: **daylogs is
deliberately small, and staying small is the feature.**

It does three things — weight, food, expenses — plus one daily summary. There is
no income tracking, no net worth, no investments, no journal, no sync, no server
and no web UI, and none of those are missing by accident. A PR that adds a fourth
feature is a scope decision, not a detail, so please open an issue first and make
the case. A PR that makes one of the three existing things better needs no
preamble.

## Ground rules

- `pytest -q` and `ruff check .` both clean. CI runs them plus a wheel build and a
  smoke test of the installed console script.
- New behaviour comes with a test. Parsers are pure functions with `now` injected,
  so nothing should depend on when the suite runs.
- No business logic in `daylogs/tui/`. Tabs render and handle keys; arithmetic
  lives in `body.py` / `money.py` / `horizon.py` with tests next to it.
- Keys are declared once, in `daylogs/tui/keymap.py`. Prompt hints are declared
  once, in `daylogs/tui/hints.py`. Tests enforce both — never hand-write a hint.
- Fixtures and examples use obviously-synthetic data. This is a personal-finance
  and body-weight app; nobody's real numbers belong in the repo.

`CLAUDE.md` holds the longer version: the invariants, and the measured reasons
behind the ones that look arbitrary. Worth a skim before a non-trivial change —
several of them exist because the obvious simplification was tried and broke
something.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest -q
```
