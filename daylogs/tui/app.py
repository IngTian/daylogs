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

from daylogs import claude, summary
from daylogs.body import BodyError
from daylogs.config import update_config
from daylogs.horizon import HorizonError
from daylogs.money import MoneyError
from daylogs.moneyview import ViewError
from daylogs.parse import ParseError
from daylogs.photo import PhotoError
from daylogs.tui import hints, keymap, themes
from daylogs.tui.body_tab import BodyTab
from daylogs.tui.footer import KeyFooter
from daylogs.tui.help import HelpScreen
from daylogs.tui.money_tab import MoneyTab
from daylogs.tui.progress import WorkPopup
from daylogs.tui.prompt import InlinePrompt
from daylogs.tui.summary_tab import SummaryTab
from daylogs.tui.themes import ThemeError
from daylogs.undo import UndoStack

log = logging.getLogger(__name__)

_SCOPE_OF = {"tab-body": "body", "tab-money": "money", "tab-summary": "summary"}
_TAB_OF = {"summary": "tab-summary", "body": "tab-body", "money": "tab-money"}

# Every way a prompt entry can be rejected for being malformed rather than
# broken. These re-open the prompt with the text intact; anything else is a bug
# and propagates.
RETRYABLE = (
    ParseError,
    MoneyError,
    BodyError,
    PhotoError,
    ViewError,
    HorizonError,
    ThemeError,
)


class DaylogsApp(App):
    CSS_PATH = "app.tcss"
    TITLE = "daylogs"

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
        # App-level, not per-tab: a running estimate used to disappear the moment you
        # pressed `3`, and its answer arrived later as a prompt with no explanation.
        self.work_popup = WorkPopup(id="work")
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
        with TabbedContent(initial="tab-summary", id="tabs"):
            with TabPane("1 Day", id="tab-summary"):
                yield SummaryTab(id="summary")
            with TabPane("2 Body", id="tab-body"):
                yield BodyTab(id="body")
            with TabPane("3 Money", id="tab-money"):
                yield MoneyTab(id="money")
        # One bottom-docked container, not two independently docked widgets:
        # docking both made the footer claim the last row and clip the prompt's
        # bottom border.
        with Vertical(id="bottom"):
            # Above the prompt, inside the one bottom-docked container rather than on a
            # layer of its own: floating it would cover the row you are reading, and a
            # second independently-docked widget is what clipped the prompt's border
            # before. Appearing here pushes content up instead of hiding it, in the place
            # the eye already goes for the prompt and the footer.
            yield self.work_popup
            yield self.prompt
            yield self.key_footer

    def on_mount(self) -> None:
        self.sub_title = self.now().strftime("%a %b %d")
        # `resolve`, not `check`: a stale or misspelled name in config.toml must
        # not stop the app over a cosmetic setting.
        self.theme = themes.resolve(self.cfg.theme)
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

    def _tab_for(self, tab_id: str):
        return {
            "tab-body": lambda: self.query_one("#body", BodyTab),
            "tab-money": lambda: self.query_one("#money", MoneyTab),
            "tab-summary": lambda: self.query_one("#summary", SummaryTab),
        }[tab_id]()

    def _active_tab(self):
        return self._tab_for(self.active_tab_id)

    def _prompt_tab(self):
        """The tab an open prompt's answer belongs to — the one that opened it.

        Not `_active_tab()`. `confirm food` and `confirm activity` are opened by a worker
        up to a minute after the keypress, and the popup exists so you can look at another
        tab while you wait; handing the answer to whatever is on screen gave it to a tab
        with no branch for that label and silently dropped a logged meal or activity.
        Falls back to the active tab, so a prompt opened before this existed still routes
        somewhere rather than raising.
        """
        owner = self.prompt.owner
        return self._tab_for(_TAB_OF[owner]) if owner in _TAB_OF else self._active_tab()

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

    def _step_tab(self, delta: int) -> None:
        """Move one tab along, clamped at both ends.

        Clamped rather than wrapped, matching what `[`/`]` already do at the ends
        of the data: `1` `2` `3` reach any tab in a single keystroke, so wrapping
        would buy nothing and make it ambiguous where an arrow lands.

        The order comes from `_TAB_OF`, which already has to agree with the
        TabPane order in `compose` — a test pins that rather than a fourth list
        being kept in step by hand.
        """
        order = tuple(_TAB_OF)
        target = order.index(self.scope) + delta
        if 0 <= target < len(order):
            self.show_scope(order[target])

    def app_prev_tab(self) -> None:
        self._step_tab(-1)

    def app_next_tab(self) -> None:
        self._step_tab(1)

    def app_help(self) -> None:
        self.push_screen(HelpScreen())

    def app_quit(self) -> None:
        self.exit()

    def app_goto(self) -> None:
        self.prompt.open("go to date")

    def app_theme(self) -> None:
        self.prompt.open("theme")

    def _apply_theme(self, value: str) -> None:
        """Set the theme and remember it. Raises ThemeError on an unknown name.

        Handled here rather than in a tab's `handle_prompt` because it is the one
        prompt that means the same thing on every tab — routing it through the
        active tab would need the same method in all three.
        """
        name = themes.check(value)
        self.theme = name
        # update_config edits the file as text, so the user's comments and
        # [[category]] blocks survive, and a new key lands above the first table
        # header rather than inside it.
        update_config(self.cfg.root / "config.toml", {"theme": name})
        self.notify(f"theme {name}", timeout=2)

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
    def _cancel_editing(self, owner: str = "") -> None:
        """Drop an armed edit id so the next entry does not corrupt that row.

        The edit prompts share their labels with the entry prompts now, so an
        abandoned edit has to drop its row id here — otherwise the next plain
        `w` or `e` is consumed as an update of the row you walked away from.

        Routed to the tab that opened the prompt. `owner` is passed in on the cancel path
        because `InlinePrompt.close()` runs before the message is handled and clears it.
        """
        tab = self._tab_for(_TAB_OF[owner]) if owner in _TAB_OF else self._prompt_tab()
        cancel = getattr(tab, "cancel_editing", None)
        if cancel is not None:
            cancel()

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
        # The answer belongs to the tab that ASKED; focus belongs to the tab on SCREEN.
        # They differ only for the two worker-opened confirm prompts, and conflating them
        # both dropped the entry and tried to focus a hidden tab's table.
        tab = self._prompt_tab()
        if not value:
            self._cancel_editing()
            self.prompt.close()
            self._active_tab().focus_default()
            return
        before = (self.prompt.is_open, self.prompt.label)
        try:
            # The one prompt that means the same thing on every tab, so it is
            # answered here instead of in three identical handle_prompt branches.
            if label == "theme":
                self._apply_theme(value)
            else:
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
            self._active_tab().focus_default()
        self.refresh_footer()

    def on_inline_prompt_cancelled(self, event: InlinePrompt.Cancelled) -> None:
        event.stop()
        self._cancel_editing(event.owner)
        self._active_tab().focus_default()

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

    # ── notifications ────────────────────────────────────────────────────
    def begin_work(self, key: str, label: str, timeout_sec: int) -> None:
        """Show `label` in the popup until `end_work(key)`.

        The one place a tab says "this is running". Keyed by job rather than a boolean,
        because a food estimate, an activity inference and the daily read can all be in
        flight at once — the first two have separate worker groups on purpose.
        """
        self.work_popup.begin(key, label, timeout_sec)

    def end_work(self, key: str) -> None:
        self.work_popup.end(key)

    def notify(self, message: str, **kwargs) -> None:
        """Toasts are plain text unless a caller insists otherwise.

        Textual defaults `markup=True`. Every toast in this app interpolates stored text
        — a food description, an expense, a category, a row about to be deleted — and not
        one of them wants markup. So a description containing `[work]` lost the word from
        the write toast *and* from the delete confirmation, which is the dangerous one: a
        confirmation that misquotes the row is asking you to approve something other than
        what it says. One containing `[/b]` raised out of the toast.

        Flipping the default here rather than at forty call sites is what makes it true
        by construction; a caller that genuinely wants markup can still pass
        `markup=True`.
        """
        kwargs.setdefault("markup", False)
        super().notify(message, **kwargs)

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
