"""The app shell: three tabs, one footer prompt, one background summary run.

Keys are declared once in keymap.py and dispatched here, so a key can mean
different things per tab without any tab needing focus to receive it, and the
footer and help overlay cannot drift from what is actually bound.

Runners are injected so tests never spawn `claude`. `now` is injected so the
autorun decision and every date default are testable.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable
from zoneinfo import ZoneInfo

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Header, Input, TabbedContent, TabPane

from daybook import claude, summary
from daybook.body import BodyError
from daybook.horizon import HorizonError
from daybook.money import MoneyError
from daybook.moneyview import ViewError
from daybook.parse import ParseError
from daybook.photo import PhotoError
from daybook.tui import hints, keymap
from daybook.tui.body_tab import BodyTab
from daybook.tui.footer import KeyFooter
from daybook.tui.help import HelpScreen
from daybook.tui.money_tab import MoneyTab
from daybook.tui.prompt import InlinePrompt
from daybook.tui.summary_tab import SummaryTab
from daybook.undo import UndoStack

log = logging.getLogger(__name__)

_SCOPE_OF = {"tab-body": "body", "tab-money": "money", "tab-summary": "summary"}
_TAB_OF = {"body": "tab-body", "money": "tab-money", "summary": "tab-summary"}

# Every way a prompt entry can be rejected for being malformed rather than
# broken. These re-open the prompt with the text intact; anything else is a bug
# and propagates.
RETRYABLE = (ParseError, MoneyError, BodyError, PhotoError, ViewError, HorizonError)


class DaybookApp(App):
    CSS_PATH = "app.tcss"
    TITLE = "daybook"

    # Side-by-side panels need room for a label, a bar and two amounts each. Below
    # ~100 columns one of those has to give, and squeezing both panels dropped the
    # bars and truncated the figures. Stacking them instead gives each the full
    # width, which is what the `-narrow` class does in app.tcss.
    HORIZONTAL_BREAKPOINTS = [(0, "-narrow"), (100, "-wide")]

    BINDINGS = [
        Binding(key, action, desc, show=False, priority=priority)
        for key, action, desc, priority in keymap.app_bindings()
    ]

    def __init__(
        self,
        cfg,
        conn,
        *,
        runner_text=None,
        runner_json=None,
        runner_image=None,
        now=None,
    ) -> None:
        super().__init__()
        # Measured: TabbedContent's underline animation cost ~277 ms of every tab
        # switch (383 ms -> 127 ms with it off). Nothing here is worth animating.
        # This is an *instance* attribute in textual 8.2, set from
        # constants.TEXTUAL_ANIMATIONS in App.__init__, so a class attribute
        # named ANIMATION_LEVEL would be a silent no-op.
        self.animation_level = "none"
        self.cfg = cfg
        self.conn = conn
        self.runner_text = runner_text or claude.run_oneshot_text
        self.runner_json = runner_json or claude.run_oneshot_json
        self.runner_image = runner_image or claude.run_with_image_json
        self._now_factory = now or self._real_now
        self.undo_stack = UndoStack()
        self.prompt = InlinePrompt()
        self.key_footer = KeyFooter()
        self.summary_worker_started = False
        self._confirm: Callable[[], None] | None = None

    # ── clock ────────────────────────────────────────────────────────────
    def _real_now(self) -> dt.datetime:
        return dt.datetime.now(ZoneInfo(self.cfg.timezone))

    def now(self) -> dt.datetime:
        return self._now_factory()

    def today(self) -> str:
        return self.now().date().isoformat()

    # ── layout ───────────────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with TabbedContent(initial="tab-body", id="tabs"):
            with TabPane("1 Body", id="tab-body"):
                yield BodyTab(id="body")
            with TabPane("2 Money", id="tab-money"):
                yield MoneyTab(id="money")
            with TabPane("3 Summary", id="tab-summary"):
                yield SummaryTab(id="summary")
        # One bottom-docked container, not two independently docked widgets:
        # docking both made the footer claim the last row and clip the prompt's
        # bottom border.
        with Vertical(id="bottom"):
            yield self.prompt
            yield self.key_footer

    def on_mount(self) -> None:
        self.sub_title = self.now().strftime("%a %b %d")
        self.refresh_tabs()
        self._active_tab().focus_default()
        self.refresh_footer()
        # Panels size their charts from their own width, which is still 0 during
        # on_mount — so render once more after the first layout, or the first
        # paint uses a fallback width and wastes a third of the panel.
        self.call_after_refresh(self._after_layout)
        self._maybe_autorun_summary()

    def _after_layout(self) -> None:
        self.refresh_tabs()
        self.refresh_footer()

    # ── tabs ─────────────────────────────────────────────────────────────
    @property
    def active_tab_id(self) -> str:
        return self.query_one("#tabs", TabbedContent).active

    @property
    def scope(self) -> str:
        return _SCOPE_OF[self.active_tab_id]

    def _active_tab(self):
        return {
            "tab-body": lambda: self.query_one("#body", BodyTab),
            "tab-money": lambda: self.query_one("#money", MoneyTab),
            "tab-summary": lambda: self.query_one("#summary", SummaryTab),
        }[self.active_tab_id]()

    def show_scope(self, scope: str) -> None:
        if self.prompt.is_open or scope not in _TAB_OF:
            return
        self.query_one("#tabs", TabbedContent).active = _TAB_OF[scope]
        tab = self._active_tab()
        tab.reload()
        tab.focus_default()
        self.refresh_footer()

    def refresh_tabs(self) -> None:
        for query, kind in (("#body", BodyTab), ("#money", MoneyTab), ("#summary", SummaryTab)):
            self.query_one(query, kind).reload()

    def refresh_footer(self) -> None:
        tab = self._active_tab()
        hint = tab.status_hint() if hasattr(tab, "status_hint") else ""
        self.key_footer.update_for(self.scope, hint, live=self.handler_for)

    def handler_for(self, action: str):
        """The callable an action resolves to in the active scope, or None.

        The footer asks this so it cannot advertise a key that does nothing: `tab`
        and `+` are app-scope, but the Summary tab implements neither sub-views nor
        horizons, so both were being drawn and were dead on press. Same resolution
        order as `action_dispatch`, deliberately — two answers to "what does this
        key do here" is how a generated footer starts lying like a hand-written one.
        """
        tab = self._active_tab()
        return getattr(tab, f"key_{action}", None) or getattr(self, f"app_{action}", None)

    # ── dispatch ─────────────────────────────────────────────────────────
    def action_dispatch(self, key: str) -> None:
        """One entry point for every key.

        Resolve the key in the active tab's scope, then prefer the tab's
        `key_<action>` over the app's `app_<action>`. A tab that doesn't
        implement a handler simply ignores the key — which is how one key means
        three different things without three binding tables.
        """
        if self.prompt.is_open:
            # `tab` is a priority App binding, so the focused Input never sees it.
            # Completion therefore has to be driven from here.
            if key == "tab":
                vocab = hints.vocab_for(hints.for_label(self.prompt.label), self.cfg)
                self.prompt.complete_now(vocab)
            return
        entry = keymap.lookup(key, self.scope)
        if entry is None:
            return
        # Any key other than the confirmation itself abandons a pending confirm.
        self._confirm = None
        fn = self.handler_for(entry.action)
        if fn is not None:
            fn()
        self.refresh_footer()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """enter on a focused DataTable arrives as this message rather than as a
        key binding, so activation is routed from here."""
        if self.prompt.is_open:
            return
        tab = self._active_tab()
        fn = getattr(tab, "key_activate", None)
        if fn is not None:
            event.stop()
            fn()
            self.refresh_footer()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input is self.prompt:
            vocab = hints.vocab_for(hints.for_label(self.prompt.label), self.cfg)
            self.prompt.refresh_candidates(vocab)

    # ── app-scope handlers ───────────────────────────────────────────────
    def app_show_body(self) -> None:
        self.show_scope("body")

    def app_show_money(self) -> None:
        self.show_scope("money")

    def app_show_summary(self) -> None:
        self.show_scope("summary")

    def app_help(self) -> None:
        self.push_screen(HelpScreen())

    def app_quit(self) -> None:
        self.exit()

    def app_goto(self) -> None:
        self.prompt.open("go to date")

    def app_back(self) -> None:
        """`esc` unwinds one step. When the active tab has nothing to unwind,
        nothing happens — esc never quits."""
        tab = self._active_tab()
        fn = getattr(tab, "key_back", None)
        if fn is not None and fn():
            tab.reload()

    def app_undo(self) -> None:
        item = self.undo_stack.pop()
        if item is None:
            self.notify("nothing to undo", timeout=3)
            return
        table, row = item
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        # An upsert on the primary key rather than a plain INSERT, so one statement
        # means "restore this row to these values" whether the row is gone (undoing a
        # delete) or present with different values (undoing an edit). A plain INSERT
        # raises on an edit's pre-image; delete-then-insert would churn the id and
        # invalidate the table's cached id list.
        sets = ", ".join(f"{c} = excluded.{c}" for c in row if c != "id")
        try:
            self.conn.execute(
                f"INSERT INTO {table} ({cols}) VALUES ({marks})"
                f" ON CONFLICT(id) DO UPDATE SET {sets}",
                tuple(row.values()),
            )
        except Exception as e:  # noqa: BLE001 - a failed undo must not kill the app
            self.notify_error(f"undo failed: {e}")
            return
        self.notify(f"restored {table} row", timeout=3)
        self.refresh_tabs()

    # ── prompt plumbing ──────────────────────────────────────────────────
    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle first, close only on success.

        v1 closed the prompt and then handled, so a parse error fired a toast and
        threw away what you typed. The tabs no longer catch those exceptions —
        the app owns the retry policy, in one place.
        """
        if event.input is not self.prompt:
            return
        event.stop()
        label, value = self.prompt.label, event.value.strip()
        tab = self._active_tab()
        if not value:
            self.prompt.close()
            tab.focus_default()
            return
        before = (self.prompt.is_open, self.prompt.label)
        try:
            tab.handle_prompt(label, value)
        except RETRYABLE as e:
            self.prompt.show_error(str(e))
            self.prompt.focus()
            return
        self.prompt.remember(label, value)
        # A handler may deliberately chain to another prompt — an uncategorised
        # expense re-opens as "fix category". Closing unconditionally would stomp
        # it, so only close the prompt we were given.
        if (self.prompt.is_open, self.prompt.label) == before:
            self.prompt.close()
            tab.focus_default()
        self.refresh_footer()

    def on_inline_prompt_cancelled(self, event: InlinePrompt.Cancelled) -> None:
        event.stop()
        tab = self._active_tab()
        # The edit prompts share their labels with the entry prompts now, so an
        # abandoned edit has to drop its row id here — otherwise the next plain
        # `w` or `e` is consumed as an update of the row you walked away from.
        cancel = getattr(tab, "cancel_editing", None)
        if cancel is not None:
            cancel()
        tab.focus_default()

    # ── confirm ──────────────────────────────────────────────────────────
    def ask_confirm(self, message: str, callback: Callable[[], None]) -> None:
        self._confirm = callback
        self.notify(message, timeout=8)

    def on_key(self, event) -> None:
        if self._confirm is None or self.prompt.is_open:
            return
        event.stop()
        callback, self._confirm = self._confirm, None
        if event.key in ("y", "Y"):
            callback()
        else:
            self.notify("cancelled", timeout=2)

    # ── errors ───────────────────────────────────────────────────────────
    def notify_error(self, message: str) -> None:
        log.warning("ui error: %s", message)
        self.notify(message, severity="warning", timeout=8)

    # ── summary autorun ──────────────────────────────────────────────────
    def _maybe_autorun_summary(self) -> None:
        """Generate yesterday's summary unattended, once, if it is missing and the
        day is far enough along that a summary is worth reading."""
        if self.now().hour < self.cfg.summary_after_hour:
            return
        target = summary.target_date(self.today())
        if summary.get_report(self.conn, target) is not None:
            return
        self.summary_worker_started = True
        self.query_one("#summary", SummaryTab).generate(target)
