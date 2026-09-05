"""The in-progress popup: what is running right now, for as long as it runs.

Three calls can be in flight — a food estimate, an activity-factor inference and the
daily read — and every one of them is a `claude -p` subprocess taking seconds to a
minute. That needs an indicator that outlives a toast, which is why there was a
`"   estimating…"` suffix on the FOOD header and a `"   generating…"` one on SUMMARY: a
3-second toast fired against a call allowed 60 seconds vanished while you were still
waiting, indistinguishable from a dropped keypress.

Two things were still wrong with the suffixes, and the popup fixes both:

- **They lived on the tab that started the work.** Press `f`, then `3`, and every trace
  of a running estimate was gone; the answer arrived later as a prompt with no
  explanation. The popup is app-level, so the work is visible from wherever you are.
- **A static word cannot tell you it is still alive.** Animations are off in this app for
  measured reasons, so the popup shows elapsed against the budget the call is actually
  allowed — `18s / 60s` — and ticks once a second. One repaint per second of a three-row
  widget, not per frame, and only while something is running.

`render_jobs` is pure and takes its clock, like every other formatter here: a test that
depends on when the suite runs is worse than no test.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from textual.widgets import Static

from daylogs.tui.widgets import esc

# One line per job, so two concurrent calls read as two things rather than one vague
# "busy". The food estimate and the activity inference have separate worker groups on
# purpose — logging a gym session must not cancel a meal estimate — so concurrency here
# is a designed state, not an edge case.
_GLYPH = "•"


@dataclass(frozen=True)
class Job:
    """One thing in flight. `started` is a monotonic reading, not a wall clock: the
    display is an elapsed duration, and a wall clock can step sideways under it."""

    key: str
    label: str
    started: float
    timeout_sec: int


def render_jobs(jobs, *, now: float) -> str:
    """The popup's text: one line per job, elapsed against its own budget.

    Markup, so the label can be emphasised — and `esc` on the way in, because a label
    reaching content markup unescaped is the defect `widgets.esc` exists for. These
    labels are literals today; the escape is what keeps that from being load-bearing.
    """
    lines = []
    for j in jobs:
        elapsed = max(0, int(now - j.started))
        lines.append(f"{_GLYPH} {esc(j.label)}   [$text-muted]{elapsed}s / {j.timeout_sec}s[/]")
    return "\n".join(lines)


class WorkPopup(Static):
    """Shows every running job, and nothing at all when nothing is running.

    Owns its own timer rather than being repainted by the tabs: the tabs know when work
    starts and stops, which is all they should have to know. The timer exists only while
    a job does, so an idle app has no periodic work — the animation-level decision was
    made on measured tab-switch cost, and a always-on ticker would spend it back.
    """

    def __init__(self, *, clock=time.monotonic, **kw) -> None:
        super().__init__("", **kw)
        self._clock = clock
        self._jobs: dict[str, Job] = {}
        self._timer = None
        self.display = False

    def begin(self, key: str, label: str, timeout_sec: int) -> None:
        """Start (or restart) the job under `key`.

        Keyed, so ending one job cannot hide another's line, and re-beginning the same
        key restarts its clock — which is what a superseded estimate should look like:
        the second call's elapsed time, not the first's.
        """
        self._jobs[key] = Job(
            key=key, label=label, started=self._clock(), timeout_sec=int(timeout_sec)
        )
        self._sync()

    def end(self, key: str) -> None:
        """Finish the job under `key`. Absent keys are fine — a worker that was
        cancelled and one that failed both end up here, sometimes twice."""
        self._jobs.pop(key, None)
        self._sync()

    def _sync(self) -> None:
        running = bool(self._jobs)
        self.display = running
        self._repaint()
        if running and self._timer is None and self.is_mounted:
            self._timer = self.set_interval(1.0, self._repaint)
        elif not running and self._timer is not None:
            self._timer.stop()
            self._timer = None

    def _repaint(self) -> None:
        self.update(render_jobs(tuple(self._jobs.values()), now=self._clock()))
