"""Tab 2 — weight and food for one day.

Holds no arithmetic. Weight deltas come from body.weight_delta, the day's calorie
total from body.day_kcal, BMR from body.compute_bmr, and the plot from chart.py.
What lives here is key handling, the estimate review flow, and rendering.
"""

from __future__ import annotations

import datetime as dt

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Static

from daylogs import body, estimate, parse, photo, sigil
from daylogs import horizon as hz
from daylogs.config import load_config, update_config
from daylogs.fmt import hhmm, human_date, wall
from daylogs.parse import (
    ParseError,
    parse_activity,
    parse_food,
    parse_profile,
    parse_weigh,
)
from daylogs.tui import chart
from daylogs.tui.common import PanelTab
from daylogs.tui.widgets import burn_bar, mark, sparkline, trend_style, view_row

_CHART_H = 8
_YLABEL_W = 7
# Deliberately not horizon.DEFAULT ("MTD"). A weight trend reads better over a
# rolling month than over a month-to-date window that is one day wide on the 1st;
# Money wants MTD because a budget is a calendar-month thing. The horizon *list* is
# shared, the starting point is per-tab.
_DEFAULT_HORIZON = "1m"
# Shown in the FOOD header and the footer's state row for as long as an estimate is
# actually running. It replaces a 3-second toast that fired against a call allowed
# 60 seconds — so it vanished while you were still waiting, indistinguishable from
# a dropped keypress. Same spacing convention as summary_tab's "generating…".
_ESTIMATING = "   estimating…"
# The sub-views `tab` walks, in the order the strip draws them. Named so the header,
# the strip and the toggle cannot disagree about what exists. Each name is also its
# table's name, which is what lets the row lookup, the edit prefill and the delete
# handler stay one branch each instead of three.
_VIEWS = ("weight", "food", "activity")
# The series the TREND panel plots, in the order `c` walks them. One panel rather than
# a fourth one: side by side, three panels do not fit 110 columns, and the axis, the
# horizon and the width arithmetic already live here. Weight stays in the cycle because
# it is the same question about the same window.
_CHARTS = ("weight", "intake", "net")
# A safety net on the weight query, not an advertised number. The table is filtered by
# the tab's span now, so the header states the count it actually got; this only bounds
# a pathological "all time". Matches money's `_LIMIT_CAP` in spirit — and if it ever
# bites, the header says so rather than silently showing a prefix.
_WEIGHT_CAP = 2000


class BodyTab(PanelTab):
    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.viewing_date = ""
        self.table_mode = "food"
        self.horizon = _DEFAULT_HORIZON
        # Which series the TREND panel plots. Independent of `horizon` and of
        # `table_mode` on purpose: "what am I looking at" and "over what window" are
        # two questions, and zooming must not reset the answer to the first.
        self.chart_mode = "weight"
        self._pending: estimate.Estimate | None = None
        self._pending_photo: tuple[object, bool] | None = None
        self._ids: list[int] = []
        # The row an open edit prompt belongs to. InlinePrompt carries a label and
        # text but no id, so the tab holds the identity between open and submit.
        self._editing: tuple[str, int] | None = None
        # An estimate is running. Set at the top of the worker and cleared on the two
        # paths that end one — deliberately NOT in a `finally`, which is the tempting
        # shape and the wrong one here. `@work(exclusive=True)` only ever cancels this
        # worker because a replacement is starting, and the replacement sets the flag
        # itself; a `finally` would clear it in the gap between the two and blink the
        # indicator off mid-estimate. Same shape as summary_tab's `busy`.
        self._estimating = False
        # An activity factor is being inferred. A separate flag *and* a separate worker
        # group from the food estimate: the two are unrelated questions, and sharing
        # the exclusive group would mean logging a gym session silently killed a meal
        # estimate you were still waiting on.
        self._inferring = False
        # The inferred factor waiting to be confirmed, so the confirm line can be
        # submitted unchanged and still land a number.
        self._pending_activity: estimate.Effort | None = None
        # The FOOD header without the estimate suffix, kept so the suffix can be
        # painted on and off without recomputing the line or touching the table.
        self._food_head = ""

    def compose(self) -> ComposeResult:
        yield Static(id="weight-head", classes="pane-title")
        # Two panels side by side: the trend, and the energy balance. v2 left the
        # right two-thirds of the screen empty.
        with Horizontal(classes="panel-row"):
            with Vertical(classes="panel", id="panel-trend"):
                yield Static(id="trend-title", classes="panel-title")
                yield Static(id="weight-chart", classes="chart")
            with Vertical(classes="panel", id="panel-energy"):
                yield Static("ENERGY", classes="panel-title")
                yield Static(id="energy-body", classes="panel-body")
        yield Static(id="food-head", classes="pane-title")
        # Same position and class as Money's pane strip, so both tabs answer
        # "which view am I on" in the same place on screen.
        yield Static(id="body-views", classes="muted")
        yield DataTable(id="body-table", cursor_type="row")
        yield Static(id="inbox-line", classes="muted")

    def on_mount(self) -> None:
        self.viewing_date = self.app.today()

    def focus_default(self) -> None:
        self.query_one("#body-table", DataTable).focus()

    def cancel_editing(self) -> None:
        """Drop everything an abandoned prompt was carrying.

        Not just the edit id. `_pending_photo` says "this inbox file belongs to the
        row about to be written", and it is consumed — the file is *moved* into
        `processed/` — by whichever `confirm food` submission comes next. Leave it
        armed after someone escapes the confirm prompt and the next typed meal, with
        nothing to do with the photo, eats it: no food row for it, and it vanishes
        from the inbox count with no message. `_pending` is dropped for the same
        reason, so a stale estimate cannot supply calories to an unrelated line.
        """
        self._editing = None
        self._pending = None
        self._pending_photo = None
        self._pending_activity = None

    def span(self) -> hz.Span:
        return hz.resolve(self.horizon, anchor=self.viewing_date or self.app.today())

    def status_hint(self) -> str:
        date = self.viewing_date or self.app.today()
        parts = [self.horizon]
        if date != self.app.today():
            parts.insert(0, human_date(date))
        if self._estimating or self._inferring:
            parts.append(_ESTIMATING.strip())
        return " · ".join(parts)

    # ── rendering ────────────────────────────────────────────────────────
    def reload(self) -> None:
        conn, cfg = self.app.conn, self.app.cfg
        date = self.viewing_date or self.app.today()

        latest = body.latest_weight(conn, on_or_before=date)
        kg = latest["kg"] if latest else None
        if kg is None:
            head = "WEIGHT   no weigh-in yet — press w"
        else:
            d7 = body.weight_delta(conn, end_date=date, days=7)
            d30 = body.weight_delta(conn, end_date=date, days=30)
            head = f"WEIGHT   {kg:g} kg"
            # A bare number, next to the weight it restates. No band and no colour:
            # "overweight" is a judgement this app does not otherwise make, and there
            # is no BMI chart for the same reason — it is the weight curve times a
            # constant.
            index = body.bmi(cfg, kg)
            if index is not None:
                head += f"   BMI {index:.1f}"
            head += f"   {_delta(d7, '7d')}   {_delta(d30, '30d')}"
            # The reading is the latest *on or before* the viewed day, which can
            # be much older. Showing a stale number as today's is the kind of
            # quiet wrongness that makes a tracker untrustworthy.
            if latest["date"] != date:
                head += f"   (last weighed {human_date(latest['date'])})"
        span = self.span()
        head += f"   ·  {span.label}"
        self.query_one("#weight-head", Static).update(head)

        # Plot against real time, not point index. Two readings a day apart were
        # being spread across a month-wide panel as a smooth climb; at their true
        # positions they sit together at the right edge with the unweighed weeks
        # visibly empty, which is the honest picture.
        #
        # How many points depends on how wide the window is. Over a month the
        # per-day collapse keeps the trend readable, because weight swings a kilo
        # inside a day. Over one to three days that collapse hides exactly what you
        # zoomed in for, so every reading is plotted.
        self.query_one("#trend-title", Static).update(
            "TREND   " + view_row(_CHARTS, self.chart_mode)
        )
        self.query_one("#weight-chart", Static).update(
            "\n".join(self._chart_rows(conn, cfg, span))
        )

        kcal = body.day_kcal(conn, date=date)
        bmr = body.compute_bmr(cfg, kg, today=date)
        # Resolved through the data layer rather than multiplied here: four surfaces
        # read the same burn, and four compositions is four chances for one panel to
        # measure the same day against two different baselines.
        factor, origin = body.resolved_factor(conn, cfg, date=date)
        burn = body.day_tdee(conn, cfg, date=date)
        self.query_one("#energy-body", Static).update(
            self._energy_panel(
                conn, cfg, date=date, kcal=kcal, bmr=bmr,
                burn=burn, factor=factor, origin=origin, span=span,
            )
        )

        # Filled before the header is composed, so the weight header can state the
        # count the query actually returned rather than a number it hopes is right.
        self._fill_table(date, span)

        # The header describes the table directly beneath it, so it has to follow
        # table_mode. It used to read "FOOD … kcal in / BMR → net" unconditionally,
        # including while the table listed weigh-ins — a label that is wrong is
        # worse than one that is missing.
        if self.table_mode == "weight":
            # It names the span now. It used to say "60 most recent" *because*
            # `list_weight` ignored the span and the viewed date, so claiming the window
            # would have been a lie — an honest label standing in for a fix.
            n = len(self._ids)
            if n == 0:
                self._food_head = (
                    f"WEIGHT   {span.label}   no weigh-ins — press w, or - to widen"
                )
            else:
                capped = "  (capped)" if n >= _WEIGHT_CAP else ""
                self._food_head = (
                    f"WEIGHT   {span.label}   {n} weigh-in{'' if n == 1 else 's'}{capped}"
                )
        elif self.table_mode == "activity":
            # The factor, its origin and the burn it produces — the same three facts
            # the ENERGY panel shows, because this header sits above the rows that
            # produced them and a header that omitted them would read as a bare log.
            head = f"ACTIVITY   {human_date(date)}"
            if factor is None:
                # An empty state names the fix. Nothing logged and no baseline means
                # there is no factor at all, and `h` is what changes that.
                head += "   no day factor — press h to set an ordinary day"
            else:
                head += f"   day ×{factor:g} {origin}"
                if burn is not None:
                    head += f"   →  {burn:,} burn"
            self._food_head = head
        else:
            label = human_date(date)
            if burn is not None:
                # "burn", not "BMR": with a factor the baseline is what the day
                # actually cost, and naming it BMR would be measuring against resting
                # expenditure while claiming otherwise.
                self._food_head = (
                    f"FOOD   {label}   {kcal:,} kcal in / {burn:,} burn"
                    f" → {kcal - burn:+,} net"
                )
            elif bmr is None:
                self._food_head = f"FOOD   {label}   {kcal:,} kcal in"
            else:
                self._food_head = (
                    f"FOOD   {label}   {kcal:,} kcal in / {bmr:,} BMR → {kcal - bmr:+,} net"
                )
        self._paint_food_head()
        self.query_one("#body-views", Static).update(view_row(_VIEWS, self.table_mode))

        pending = photo.pending_count(cfg.inbox_dir)
        line = self.query_one("#inbox-line", Static)
        line.update(f"{pending} photo{'s' if pending != 1 else ''} in inbox — press p")
        line.display = pending > 0

    def _local(self, epoch: int) -> dt.datetime:
        """An epoch as a wall-clock time in the configured zone.

        The conversion belongs here rather than in `horizon`, which is pure and has
        no business knowing about `cfg`. A UTC reading at 02:00 Toronto is the
        previous evening locally, and plotting it on the wrong day is the same class
        of bug as the date traps this repo keeps hitting.
        """
        return wall(epoch, self.app.cfg.timezone)

    def _chart_rows(self, conn, cfg, span) -> list[str]:
        """The TREND panel's plot, for whichever series is selected.

        All three share the axis, the horizon and the panel width; what differs is the
        data and whether zero belongs in the vertical extent. Weight fits itself —
        anchored at zero a 70-75 kg series is a flat line at the top of the panel —
        while a calorie series is a magnitude from zero, and a signed net is unreadable
        without knowing which side of zero it sits on.
        """
        # Width from the panel, not a constant: a hardcoded width wider than the panel
        # makes every chart row wrap, doubling its height and looking broken.
        common = dict(
            width=self._chart_width(), height=_CHART_H, ylabel_width=_YLABEL_W, unit=""
        )
        if self.chart_mode == "weight":
            # Plot against real time, not point index. Two readings a day apart were
            # being spread across a month-wide panel as a smooth climb; at their true
            # positions they sit together at the right edge with the unweighed weeks
            # visibly empty, which is the honest picture.
            #
            # How many points depends on how wide the window is. Over a month the
            # per-day collapse keeps the trend readable, because weight swings a kilo
            # inside a day. Over one to three days that collapse hides exactly what you
            # zoomed in for, so every reading is plotted.
            if span.hourly:
                moments = body.weight_points_between(conn, start=span.start, end=span.end)
            else:
                moments = [
                    (at, kg_) for _, kg_, at in
                    body.weight_series_between(conn, start=span.start, end=span.end)
                ]
            when = [self._local(at) for at, _ in moments]
            ax = hz.axis(span, [w.date().isoformat() for w in when])
            return chart.frame_chart(
                [v for _, v in moments],
                x_labels=ax.labels(),
                positions=ax.fractions_at(when),
                **common,
            )

        if self.chart_mode == "intake":
            series = body.kcal_series_between(conn, start=span.start, end=span.end)
        else:
            # Each day against its own burn. `body.net_series_between` skips days with
            # no food and days with no resolvable burn, so a gap stays a gap rather
            # than plotting as a day of nothing eaten.
            series = body.net_series_between(conn, cfg, start=span.start, end=span.end)
        # A day is a day here, however wide the window: calories are totalled per day,
        # so there is no finer resolution for an hourly horizon to reveal.
        ax = hz.axis(span, [d for d, _ in series])
        return chart.frame_chart(
            [float(v) for _, v in series],
            x_labels=ax.labels(),
            positions=ax.fractions([d for d, _ in series]),
            include_zero=True,
            **common,
        )

    def _chart_width(self) -> int:
        """Braille cells inside the trend panel, after the y labels and the axis."""
        return max(16, self.panel_width("#panel-trend", minimum=24) - _YLABEL_W - 1)

    def _energy_panel(
        self, conn, cfg, *, date, kcal, bmr, burn, factor, origin, span
    ) -> str:
        """Intake against maintenance for the day, then the same over the horizon.

        A calorie count means nothing without a baseline, which is why the baseline
        sits next to it rather than on its own line elsewhere.

        With an activity factor the baseline is `burn` — what the day actually cost —
        and the two rows that derive it stay on screen. That is deliberate: a factor
        rescales every calorie judgement for its day, so an inferred number with
        nothing to make you doubt it would quietly become the baseline for everything.
        Without a factor every line here is exactly what it was before.
        """
        lines: list[str] = []
        if bmr is None:
            lines.append(f"  in        {kcal:>7,} kcal")
            # Name the key, not the file. Telling someone to edit config.toml is
            # how this panel stayed empty: the fix was real but nobody was going
            # to leave the app to apply it.
            lines.append("  BMR             —   press h to set height,")
            lines.append("                      sex and birthday")
        else:
            # What `net` is measured against, and the one value the bar and the
            # percentage may use — naming it once is what keeps this panel from
            # measuring the same day against two different baselines.
            against = bmr if burn is None else burn
            lines.append(f"  in        {kcal:>7,} kcal")
            if burn is None:
                lines.append(f"  BMR      −{bmr:>7,}")
            else:
                # BMR and activity derive `burn`; `in`, `burn` and `net` are the sum.
                # So BMR drops its minus sign: it is no longer a term of `net`, and a
                # column of signs that does not add up is worse than no signs.
                lines.append(f"  BMR       {bmr:>7,}")
                lines.append(f"  activity  {f'×{factor:g}':>7}  {origin}")
                lines.append(f"  burn     −{against:>7,}")
            lines.append("            ─────────")
            lines.append(f"  net       {kcal - against:>+7,}")
            if kcal:
                lines.append("")
                bar_w = max(10, self.panel_width("#panel-energy", minimum=24) - 6)
                lines.append(f"  {burn_bar(kcal, against, width=bar_w, marker_frac=None)}")
                lines.append(f"  {round(kcal / against * 100)}% of maintenance")

        avg = body.kcal_average(conn, start=span.start, end=span.end)
        logged = body.kcal_series_between(conn, start=span.start, end=span.end)
        lines.append("")
        lines.append(f"  over {span.horizon}")
        if avg is None:
            lines.append("    no food logged in this window")
        else:
            lines.append(f"    avg in    {avg:>7,} kcal  ({len(logged)} days logged)")
            # Per day, not this average minus today's burn: a factor describes one
            # day, so a single gym session must not restate the whole window.
            avg_net = body.net_average(conn, cfg, start=span.start, end=span.end)
            if avg_net is not None:
                lines.append(f"    avg net   {avg_net:>+7,}")
            spark_w = max(10, self.panel_width("#panel-energy", minimum=24) - 6)
            lines.append(
                # Calories are a magnitude from zero, so scale from zero: a run of
                # similar days is a plateau, not a floor.
                f"    {sparkline([float(v) for _, v in logged], width=spark_w, from_zero=True)}"
            )
        return "\n".join(lines)

    def _fill_table(self, date: str, span) -> None:
        table = self.query_one("#body-table", DataTable)
        table.clear(columns=True)
        self._ids = []
        if self.table_mode == "weight":
            table.add_columns("date", "kg", "note")
            # Bounded by the span, like the chart above it. `span.start` is None for
            # "all time", which `list_weight` reads as no lower bound.
            rows = body.list_weight(
                self.app.conn, since=span.start, until=span.end, limit=_WEIGHT_CAP
            )
            for r in rows:
                table.add_row(r["date"], f"{r['kg']:g}", Text(r["note"] or ""))
                self._ids.append(r["id"])
        elif self.table_mode == "activity":
            table.add_columns("time", "description", "factor", "src")
            for r in body.list_activity(self.app.conn, date=date):
                table.add_row(
                    hhmm(r["logged_at"], self.app.cfg.timezone),
                    Text(r["description"]),
                    # A dash, not a blank: an inference that never landed is a state
                    # worth seeing, because the day quietly used the baseline instead.
                    "—" if r["factor"] is None else f"×{r['factor']:g}",
                    "lab" if r["source"] == "labeled" else "est",
                )
                self._ids.append(r["id"])
        else:
            table.add_columns("time", "description", "kcal", "src")
            for r in body.list_food(self.app.conn, date=date):
                table.add_row(
                    hhmm(r["ate_at"], self.app.cfg.timezone),
                    # Text, not str: a `str` cell is parsed as markup, so a description
                    # containing `[/b]` raised out of the render and one containing
                    # `[work]` quietly lost the word.
                    Text(r["description"]),
                    f"{r['kcal']:,}",
                    "lab" if r["source"] == "labeled" else "est",
                )
                self._ids.append(r["id"])

    def _selected_row(self):
        table = self.query_one("#body-table", DataTable)
        row = table.cursor_row
        if row is None or not (0 <= row < len(self._ids)):
            return None
        row_id = self._ids[row]
        # The view name is the table name, which is why this is not a three-way branch.
        which = self.table_mode
        return self.app.conn.execute(
            f"SELECT * FROM {which} WHERE id = ?", (row_id,)
        ).fetchone()

    # ── keys ─────────────────────────────────────────────────────────────
    def key_weigh(self) -> None:
        self.app.prompt.open("weigh")

    def key_profile(self) -> None:
        cfg = self.app.cfg
        current = " ".join(
            str(v)
            for v in (
                f"{cfg.height_cm:g}" if cfg.height_cm else "",
                cfg.sex or "",
                cfg.birthday or "",
                cfg.activity or "",
                cfg.timezone,
            )
            if v
        )
        self.app.prompt.open("profile", prefill=current)

    def key_food(self) -> None:
        self.app.prompt.open("food")

    def key_activity(self) -> None:
        self.app.prompt.open("activity")

    def key_activate(self) -> None:
        """enter edits the row under the cursor.

        Body had no key_activate at all, so enter did nothing here — the edit path
        was specified in the original design and never wired up.
        """
        row = self._selected_row()
        if row is None:
            self.app.notify("no row selected", timeout=3)
            return
        if self.table_mode == "weight":
            self._editing = ("weight", row["id"])
            self.app.prompt.open("weigh", prefill=parse.render_weigh(row))
        elif self.table_mode == "activity":
            self._editing = ("activity", row["id"])
            self.app.prompt.open(
                "activity", prefill=parse.render_activity(row, self.app.cfg.timezone)
            )
        else:
            self._editing = ("food", row["id"])
            self.app.prompt.open(
                "food", prefill=parse.render_food(row, self.app.cfg.timezone)
            )

    def key_next_subview(self) -> None:
        self._step_subview(1)

    def key_prev_subview(self) -> None:
        self._step_subview(-1)

    def _step_subview(self, delta: int) -> None:
        """Walk the strip. Directional now that there are three views — while there
        were two, `prev` was an alias for `next` and shift+tab happened to be right."""
        self.table_mode = _VIEWS[(_VIEWS.index(self.table_mode) + delta) % len(_VIEWS)]
        self.reload()

    def key_prev_period(self) -> None:
        self._shift_day(-1)

    def key_next_period(self) -> None:
        self._shift_day(1)

    def _shift_day(self, delta: int) -> None:
        base = dt.date.fromisoformat(self.viewing_date or self.app.today())
        self.viewing_date = (base + dt.timedelta(days=delta)).isoformat()
        self.reload()

    def key_jump_now(self) -> None:
        self.viewing_date = self.app.today()
        self.reload()

    def key_next_chart(self) -> None:
        """Walk the TREND panel's series. One key rather than three, and cycling
        rather than a prompt, because it is the same shape as `tab` on the sub-views."""
        self.chart_mode = _CHARTS[(_CHARTS.index(self.chart_mode) + 1) % len(_CHARTS)]
        self.reload()

    def key_zoom_in(self) -> None:
        # HORIZONS runs short -> long, so magnifying is a step *back* along it.
        self.horizon = hz.next_horizon(self.horizon, -1)
        self.reload()

    def key_zoom_out(self) -> None:
        self.horizon = hz.next_horizon(self.horizon, 1)
        self.reload()

    def key_back(self) -> bool:
        return False

    def key_delete(self) -> None:
        row = self._selected_row()
        if row is None:
            self.app.notify("nothing selected", timeout=3)
            return
        mode = self.table_mode
        if mode == "weight":
            label = f"{row['kg']:g} kg on {row['date']}"
        elif mode == "activity":
            factor = "no factor" if row["factor"] is None else f"×{row['factor']:g}"
            label = f"{row['description']} ({factor})"
        else:
            label = f"{row['description']} ({row['kcal']:,} kcal)"
        self.app.ask_confirm(
            f"delete {label}?   y/n", lambda: self._do_delete(mode, row["id"])
        )

    def _do_delete(self, mode: str, row_id: int) -> None:
        table = mode
        fn = {
            "weight": body.delete_weight,
            "food": body.delete_food,
            "activity": body.delete_activity,
        }[mode]
        row = fn(self.app.conn, row_id)
        if row is None:
            return
        self.app.undo_stack.push(table, row)
        self.app.notify("deleted · u to undo", timeout=4)
        self.reload()

    def key_photo(self) -> None:
        cfg = self.app.cfg
        clip = photo.clipboard_image(cfg.root / ".tmp")
        if clip is not None:
            self._estimate_photo(clip, from_inbox=False)
            return
        nxt = photo.next_inbox_image(cfg.inbox_dir)
        if nxt is not None:
            self._estimate_photo(nxt, from_inbox=True)
            return
        self.app.prompt.open("photo path")

    def _estimate_photo(self, path, *, from_inbox: bool) -> None:
        self._pending_photo = (path, from_inbox)
        self._run_image_estimate(path)

    # ── workers ──────────────────────────────────────────────────────────
    def _paint_food_head(self) -> None:
        suffix = _ESTIMATING if (self._estimating or self._inferring) else ""
        self.query_one("#food-head", Static).update(self._food_head + suffix)

    def _set_estimating(self, running: bool) -> None:
        """Repaint only the two places the indicator appears.

        Deliberately not `reload()`. That calls `_fill_table`, which does
        `table.clear(columns=True)` and so resets the DataTable cursor to row 0 —
        starting an estimate would throw away whichever food row you had selected.
        And `reload()` could not show the footer half anyway: the footer is a
        sibling widget, rewritten only by `App.refresh_footer()`, so without this
        call `status_hint()`'s suffix never reaches the screen and a footer painted
        by some other keypress mid-estimate would never be cleared.
        """
        self._estimating = running
        self._paint_food_head()
        self.app.refresh_footer()

    def _set_inferring(self, running: bool) -> None:
        """The activity-factor counterpart, repainting the same two places."""
        self._inferring = running
        self._paint_food_head()
        self.app.refresh_footer()

    @work(exclusive=True)
    async def _run_image_estimate(self, path) -> None:
        self._set_estimating(True)
        try:
            est = await estimate.from_image(
                image_path=path,
                note=None,
                runner=self.app.runner_image,
                timeout_sec=self.app.cfg.estimate_timeout_sec,
                model=self.app.cfg.claude_model,
            )
        except Exception as e:  # noqa: BLE001 - surfaced to the user, not swallowed
            self._pending_photo = None
            self._set_estimating(False)
            self.app.notify_error(f"photo estimate failed: {e}")
            return
        self._set_estimating(False)
        self._offer(est)

    @work(exclusive=True)
    async def _run_text_estimate(self, description: str) -> None:
        # A typed estimate supersedes any photo waiting to be confirmed — it shares
        # the exclusive group, so starting this cancels the image worker, and a
        # cancelled worker never reaches the `except` that would have released the
        # photo. Left armed, the file would be consumed by THIS estimate's confirm.
        self._pending_photo = None
        self._set_estimating(True)
        try:
            est = await estimate.from_text(
                description=description,
                runner=self.app.runner_json,
                timeout_sec=self.app.cfg.estimate_timeout_sec,
                model=self.app.cfg.claude_model,
            )
        except Exception as e:  # noqa: BLE001 - surfaced to the user, not swallowed
            self._set_estimating(False)
            self.app.notify_error(f"estimate failed: {e}")
            return
        self._set_estimating(False)
        self._offer(est)

    def _offer(self, est: estimate.Estimate) -> None:
        """Show the estimate as an editable line. Correcting it goes through the
        same grammar as typing it, so there is one code path, not two."""
        self._pending = est
        self.app.prompt.open("confirm food", f"{sigil.escape(est.description)} ={est.kcal}")

    # ── prompt handling ──────────────────────────────────────────────────
    def handle_prompt(self, label: str, value: str) -> None:
        """Malformed input raises; the app catches it, keeps the text, and shows
        why. Catching it here would discard the line the user typed."""
        if not value:
            self._pending = None
            self._pending_photo = None
            return
        if label == "weigh":
            self._submit_weigh(value)
        elif label == "food":
            self._submit_food(value)
        elif label == "confirm food":
            self._submit_confirmed_food(value)
        elif label == "activity":
            self._submit_activity(value)
        elif label == "confirm activity":
            self._submit_confirmed_activity(value)
        elif label == "photo path":
            self._estimate_photo(photo.resolve_path(value), from_inbox=False)
        elif label == "go to date":
            self._submit_goto(value)
        elif label == "profile":
            self._submit_profile(value)

    def _take_editing(self, which: str) -> int | None:
        """The id an open edit prompt belongs to, consumed once.

        Cleared on read so a stale id cannot be reused by the next submission — the
        row may have been deleted in between.
        """
        if self._editing is None or self._editing[0] != which:
            return None
        _, row_id = self._editing
        self._editing = None
        return row_id


    def _submit_profile(self, value: str) -> None:
        """Persist to config.toml and reload, so BMR appears on this keystroke.

        `load_config` is re-read from the app's own root rather than the default,
        or a DAYLOGS_HOME-based run would write one file and read another.
        """
        profile = parse_profile(value)
        update_config(self.app.cfg.root / "config.toml", profile.fields())
        self.app.cfg = load_config(self.app.cfg.root)
        cfg = self.app.cfg
        if body.compute_bmr(cfg, 70.0, today=self.app.today()) is None:
            missing = ", ".join(
                name
                for name, ok in (
                    ("height", cfg.height_cm),
                    ("sex", cfg.sex),
                    ("birthday", cfg.birthday),
                )
                if not ok
            )
            self.app.notify(f"saved — still need {missing} for BMR", timeout=5)
        elif body.baseline_factor(cfg) is None:
            # An empty state names the fix. Resting BMR is not maintenance, and
            # nothing else on screen would tell you that a level is what turns one
            # into the other.
            self.app.notify(
                "profile saved — add desk, light, active or heavy for maintenance",
                timeout=6,
            )
        else:
            self.app.notify("profile saved", timeout=3)
        self.app.refresh_tabs()

    def _submit_goto(self, value: str) -> None:
        # One shared rule. This used to build a throwaway MoneyView as a parser and
        # then re-derive the date itself, which broke the day the month branch
        # started returning the month's last day.
        self.viewing_date = hz.resolve_goto(value)
        self.reload()

    def _submit_weigh(self, value: str) -> None:
        r = parse_weigh(value, now=self.app.now())
        row_id = self._take_editing("weight")
        if row_id is None:
            body.add_weight(self.app.conn, kg=r.kg, date=r.date, at=r.at, note=r.note)
            self.viewing_date = r.date
            self.reload()
            d7 = body.weight_delta(self.app.conn, end_date=r.date, days=7)
            trend = "" if d7 is None else f" · {'▼' if d7 < 0 else '▲'}{abs(d7):g} vs 7d"
            self.app.notify(f"{r.kg:g} kg logged{trend}", timeout=4)
            return
        before = self.app.conn.execute(
            "SELECT * FROM weight WHERE id = ?", (row_id,)
        ).fetchone()
        if before is None:
            self.app.notify("that row is gone", timeout=3)
            return
        # measured_at is deliberately absent: render_weigh emits no time, so an edit
        # cannot re-stamp the reading that weight_series uses to pick the day.
        body.update_weight(self.app.conn, row_id, kg=r.kg, date=r.date, note=r.note or "")
        self.app.undo_stack.push("weight", dict(before))
        self.app.notify(f"{r.kg:g} kg on {r.date} · u to undo", timeout=4)
        self.reload()

    def _line_sets_a_time(self, value: str) -> bool:
        r"""Whether the line actually carried an @time.

        Not `"@" in value`: an escaped `\@` inside a description is a plain word, and
        reading raw text for a sigil is the scavenging this grammar exists to remove.
        """
        for tok in sigil.tokenize(value):
            if tok.sigil == "@" and parse.TIME_RE.match(tok.value.split("/")[-1]):
                return True
        return False

    def _submit_food(self, value: str) -> None:
        r = parse_food(value, now=self.app.now())
        row_id = self._take_editing("food")
        if row_id is None:
            if r.kcal is None:
                self._run_text_estimate(r.description)
                return
            self._write_food(r, source="labeled")
            return
        before = self.app.conn.execute(
            "SELECT * FROM food WHERE id = ?", (row_id,)
        ).fetchone()
        if before is None:
            self.app.notify("that row is gone", timeout=3)
            return
        # render_food emits ate_at as @date/time. Only restamp if the user actually
        # set a time — an escaped \@ in the description is not a time token.
        if not self._line_sets_a_time(value):
            at = before["ate_at"]
        else:
            tz = self.app.cfg.timezone
            before_minute = wall(before["ate_at"], tz).strftime("%Y-%m-%d %H:%M")
            parsed_minute = wall(r.at, tz).strftime("%Y-%m-%d %H:%M")
            if before_minute == parsed_minute:
                at = before["ate_at"]
            else:
                at = body.restamp(before["ate_at"], date=r.date, hhmm=hhmm(r.at, tz), tz=tz)
                if at is None:
                    at = before["ate_at"]
        # `source` is deliberately absent from the grammar: it is provenance
        # (labelled vs estimated) that the digest reads, not something an edit of the
        # description should rewrite. Pre-image after the write.
        if r.kcal is None:
            raise ParseError("kcal is required — give =kcal or leave the row unchanged")
        body.update_food(
            self.app.conn, row_id, description=r.description, kcal=r.kcal,
            date=r.date, ate_at=at
        )
        self.app.undo_stack.push("food", dict(before))
        self.app.notify(f"{r.description} · {r.kcal:,} kcal · u to undo", timeout=4)
        self.reload()

    def _submit_confirmed_food(self, value: str) -> None:
        r = parse_food(value, now=self.app.now())
        if r.kcal is None and self._pending is not None:
            r = type(r)(
                description=r.description,
                kcal=self._pending.kcal,
                date=r.date,
                at=r.at,
            )
        self._write_food(r, source="estimated")
        self._pending = None
        # Only consume the inbox file once the row is actually written. A failed
        # estimate must leave the photo pending, not silently eat it.
        if self._pending_photo is not None:
            path, from_inbox = self._pending_photo
            if from_inbox:
                photo.mark_processed(path, self.app.cfg.inbox_dir)
            self._pending_photo = None

    def _submit_activity(self, value: str) -> None:
        """Entry or edit, on one line. An edit updates; entry with no `=` asks Claude.

        The two paths diverge on the missing factor deliberately. On entry, no number
        means "work one out". On an edit it means "leave the stored one alone" — fixing
        a typo in a description must not silently re-roll the number the day is
        measured against, and it is also what keeps a factorless row editable, since
        its rendered line carries no `=` to begin with.
        """
        r = parse_activity(value, now=self.app.now())
        row_id = self._take_editing("activity")
        if row_id is not None:
            before = self.app.conn.execute(
                "SELECT * FROM activity WHERE id = ?", (row_id,)
            ).fetchone()
            if before is None:
                self.app.notify("that row is gone", timeout=3)
                return
            # Only restamp when the minute actually moved, so the seconds survive —
            # `logged_at` is the tie-breaker `resolved_factor` uses to pick a day's
            # latest inference, and the grammar's only time token is HH:MM.
            at = body.restamp(
                before["logged_at"], date=r.date,
                hhmm=hhmm(r.at, self.app.cfg.timezone), tz=self.app.cfg.timezone,
            )
            body.update_activity(
                self.app.conn, row_id,
                description=r.description, factor=r.factor, date=r.date,
                logged_at=at,
            )
            self.app.undo_stack.push("activity", dict(before))
            self.app.notify(f"{r.description} · u to undo", timeout=4)
            self.reload()
            return
        if r.factor is None:
            self._run_factor_estimate(r)
            return
        self._write_activity(r, source="labeled")

    def _submit_confirmed_activity(self, value: str) -> None:
        r = parse_activity(value, now=self.app.now())
        if r.factor is None and self._pending_activity is not None:
            r = type(r)(
                description=r.description,
                factor=self._pending_activity.factor,
                date=r.date,
                at=r.at,
            )
        self._pending_activity = None
        self._write_activity(r, source="estimated")

    def _write_activity(self, r, *, source: str) -> None:
        body.add_activity(
            self.app.conn,
            description=r.description,
            date=r.date,
            at=r.at,
            factor=r.factor,
            source=source,
        )
        self.viewing_date = r.date
        self.reload()
        # The useful answer is not "saved" but what the day now costs. When there is no
        # BMR the factor has nothing to scale, and saying so names the fix rather than
        # letting the entry look like it did nothing.
        burn = body.day_tdee(self.app.conn, self.app.cfg, date=r.date)
        shown = "no factor" if r.factor is None else f"×{r.factor:g}"
        if burn is None:
            self.app.notify(
                f"{r.description} · {shown} — press h for a height, sex and birthday"
                " to turn it into a burn figure",
                timeout=6,
            )
        else:
            self.app.notify(f"{r.description} · {shown} · {burn:,} burn", timeout=4)

    @work(exclusive=True, group="activity")
    async def _run_factor_estimate(self, r) -> None:
        """Infer the day's factor, then offer it for review.

        Its own worker group, not the food estimate's: they are unrelated questions,
        and sharing a group would mean logging a gym session cancelled a meal estimate
        that was still running.

        A failed inference still records what you did, with a NULL factor — the state
        the schema and `resolved_factor` already handle, where the day falls back to
        the profile baseline. The description is the user's data; the factor is a
        guess, and losing the first because the second failed is the worse outcome.
        """
        self._set_inferring(True)
        logged = [
            row["description"]
            for row in body.list_activity(self.app.conn, date=r.date)
        ]
        try:
            effort = await estimate.factor_from_text(
                # The day, not the entry: a PAL is not additive, so two sessions and
                # one session are different days.
                activities=[*logged, r.description],
                baseline=self.app.cfg.activity,
                runner=self.app.runner_json,
                timeout_sec=self.app.cfg.estimate_timeout_sec,
                model=self.app.cfg.claude_model,
            )
        except Exception as e:  # noqa: BLE001 - surfaced to the user, not swallowed
            self._set_inferring(False)
            self._write_activity(r, source="estimated")
            self.app.notify_error(
                f"factor estimate failed: {e} — logged with no factor, so the day"
                " uses your ordinary-day level"
            )
            return
        self._set_inferring(False)
        self._pending_activity = effort
        self.app.prompt.open(
            "confirm activity",
            f"{sigil.escape(r.description)} ={effort.factor:g}",
        )

    def _write_food(self, r, *, source: str) -> None:
        body.add_food(
            self.app.conn,
            description=r.description,
            kcal=r.kcal or 0,
            source=source,
            date=r.date,
            at=r.at,
        )
        self.viewing_date = r.date
        self.reload()
        total = body.day_kcal(self.app.conn, date=r.date)
        latest = body.latest_weight(self.app.conn, on_or_before=r.date)
        bmr = body.compute_bmr(self.app.cfg, latest["kg"] if latest else None, today=r.date)
        # The useful answer is not "saved" but where the day now stands.
        against = f"{total:,} today" if bmr is None else f"{total - bmr:+,} vs BMR"
        self.app.notify(f"{r.description} · {r.kcal or 0:,} kcal · {against}", timeout=4)


def _delta(value: float | None, label: str) -> str:
    """A weight change, coloured down-is-good.

    That direction is an assumption, and the only one available: daylogs stores no
    goal weight, so "good" has to come from somewhere. Losing reads as progress
    for the person who built a weight tracker. The arrow carries the direction
    regardless, so the colour adds emphasis rather than being the only signal —
    which matters if the assumption is ever wrong for you.
    """
    if value is None:
        return f"— vs {label}"
    arrow = "▼" if value < 0 else ("▲" if value > 0 else "→")
    return mark(f"{arrow} {abs(value):g} vs {label}", trend_style(value))


