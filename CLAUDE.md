# daylogs — Claude Code context

A single-user terminal app for three things: weight, food, and expenses, plus
one daily summary. Keeping it small is the point, not a side effect: every
feature has to survive daily use, and every layer of complexity has to justify
itself against a simpler version.

## What daylogs is not

Say so plainly if a request drifts into any of these — they were all
deliberately cut, and adding one back is a scope decision, not a detail:

- **No income, no cash balance, no net worth, no projection.** Money answers
  one question: where did it go this month, and am I inside the budget. A
  negative `expense.amount` is a refund, not income.
- No investments, holdings, market data, journal, intel, weather, token
  dashboards, productivity tracking, or exercise logging.
- No HTTP server, no web UI, no MCP server, no workflow engine, no scheduler.
- No fourth feature. Three tabs.

## Layout

```
daylogs/
  config.py   tomllib config + update_config/add_category; DAYLOGS_HOME overrides the root
  db.py       connect + seven-table schema (no schema-migration framework)
  categories.py  constant category tuple, extensible via config.toml
  sigil.py    tokeniser: `!` category, `@` time, `~` note, `=` kcal, `#` cycle
  complete.py tab completion for `!` and `#` vocabularies (no Textual import)
  parse.py    pure grammar parsers on top of sigil.py, and the shared amount/limit rules
  horizon.py  the one time-window concept: Span, Axis, resolve_goto
  moneyview.py  all Money tab state as one value with named transitions
  body.py     weight, food, activity; trend windows; Mifflin-St Jeor BMR,
              activity factor -> TDEE ("burn"), BMI, per-day net series, restamp
  money.py    expenses, recurring, budgets, summarize_span
  claude.py   three `claude -p` subprocess wrappers
  photo.py    clipboard (osascript) / inbox / path acquisition
  estimate.py photo-or-text → calorie estimate
  summary.py  payload + one claude call + persist
  export.py   one CSV per table, table list derived from the schema
  markup.py   legacy <num>/<warn> tags → markdown, for reports already stored
  fmt.py      hhmm / human_date — shared by the data and UI layers
  undo.py     in-memory ring buffer of row pre-images (deletes and edits)
  log.py      rotating file log under ~/.daylogs/logs/
  tui/        app shell, footer prompt, three tabs, pure text widgets
              tab order: Day · Body · Money; Day's scope id is still `summary`
              Body sub-views: weight · food · activity (each name is its table)
    keymap.py   every key, as data — generates bindings, footer and help
    hints.py    every prompt's example and grammar, as data
    common.py   PanelTab: on_resize + panel_width, shared by the two big tabs
    chart.py    braille line charts (no Textual import)
    widgets.py  bars, sparklines, colours, markup escaping (no Textual import)
    progress.py the in-progress popup: one line per running claude call
  __main__.py `day`, `day summary`, `day backup`
```

Keep this map current. It is the first thing a reader (or a fresh session) uses to
find anything, and three modules were once missing from it because each round
appended prose where it was convenient rather than editing the map.

## Invariants

- **`daylogs/tui/keymap.py` is the only place keys are declared.** The bindings,
  the contextual footer, and the `?` overlay are all generated from `KEYMAP`.
  Never hand-write a key hint — that is how a footer starts describing keys that
  aren't bound. Tests enforce no duplicate `(key, scope)` and no tab key
  shadowing an app key.
- **The digit keys are bound to named actions, not tab positions.** `Key("2", …,
  "show_body", …)` calls `show_scope("body")`, so moving a pane without moving its
  digit leaves a tab labelled 3 that `2` jumps to. `tuple(_TAB_OF)` carries the order
  the arrow keys walk and a test asserts it matches the `TabPane` order — change all
  three together or the test will tell you.
- **Measured facts are encoded in `Key` flags; don't "simplify" them away — in
  either direction.** `priority=True` on `tab`/`shift+tab` because an ordinary App
  binding loses to the Screen's focus-next. `bind=False` on `enter` because a
  focused DataTable converts it to `RowSelected` before any binding sees it.
  Priority on a printable key would steal `/`, `+`, `-` and `enter` from the
  prompt — verified, and it breaks entry outright. And `left`/`right` are
  deliberately **not** priority: a `cursor_type="row"` DataTable does not claim
  them, so a plain binding already fires with the table focused, while a focused
  Input keeps its cursor movement. Making them priority breaks arrow keys inside a
  line you are typing *and* lets tabs switch behind the `?` overlay — two tests
  fail on it, which is the intended tripwire.
- **`MoneyView` is the only Money tab state.** Horizon, pane, sort, filters and
  grouping travel as one value with named transitions, because as separate flags
  they are sixteen untested combinations. `anchor` is a **date** (the right-hand
  edge of the span), not a month.
- **Two named weight concepts, and they are not interchangeable.** `latest_weight` is
  "what do I weigh now" — the WEIGHT header's headline, which states the reading's clock
  time so it reads as a reading rather than as *the* number, and the BMI beside it.
  `morning_weight` is the day's **first** reading, taken fasted: the trend line, the
  7d/30d deltas and the digest. One function served both and it was `latest_weight`, so
  the collapse kept `MAX(measured_at)`. On real data every twice-weighed day was measured
  early and again mid-morning, so latest-wins took the low end of every day, hid the high
  reading entirely once the window passed `3d`, and made `summary.py`'s prompt false — it
  states `weight_kg` is the morning weigh-in "before any of the food listed" while being
  handed the mid-morning one. `next_morning_kg` was mislabelled the same way. The
  headline and the trend therefore disagree on a twice-weighed day, on purpose.
- **A chart's y-extent describes the window, not the points it drew.** `frame_chart`
  takes `low`/`high` for the weight chart, which plots one point per day while the window
  may hold several readings per day — fitting to the drawn points labelled the top of a
  week as 81.85 with an 82.65 inside it, the same defect as v1 labelling min/max of the
  last 30 entries as though they were the window. The line then does not touch the panel
  edges, which is the honest picture: the value defining the edge is not on screen.
- **One timezone, and `fmt` takes it as an argument.** `cfg.timezone` defaults to the
  *machine's* zone (`config.system_timezone`, from `TZ` then the `/etc/localtime`
  symlink, else UTC) and is always a real IANA name, so every reader can do
  `ZoneInfo(cfg.timezone)` with no None branch. It used to default to the literal
  `"America/Toronto"` while `fmt.hhmm` read the machine — so on any other machine an
  edit's prefill round-trip moved the row by the offset, reachable from a plain `enter`
  on a food row. `fmt.hhmm`/`fmt.wall` and `body.restamp` therefore **require** the
  zone: a default is precisely how that hid, because every call site looked right. A
  zone *name*, not a tzinfo, because DST has to resolve per timestamp — a captured
  offset renders a January reading with August's rules.
  `date` stays authoritative over `ate_at` when the two disagree after a zone change
  (Aug 27 in Toronto is Aug 28 in Kiritimati), so the render is asserted to be *stable*
  rather than instant-preserving: it settles once instead of creeping on every edit.
- **Activities are assumed to be logged faithfully and in full, every day.** A stated
  premise, not an inference: a day with no activity row *is* an ordinary day and takes
  the profile baseline, and the inference is handed the whole day because the whole day
  is assumed present. So there is no partial-logging machinery and no "did you forget"
  nagging, and none should be added without revisiting this. It does **not** extend to
  food, which is logged sparsely — which is why `kcal_series_between` and
  `net_series_between` still treat a foodless day as absent rather than as a fast.
- **The activity factor is never defaulted, and `body.day_tdee` is the only place
  BMR is multiplied by it.** Assuming `desk` for an unset profile would raise
  maintenance 20% and silently restate every figure on screen and in every digest
  already written, so "no factor" is a real state in which every calorie number sits
  against resting BMR exactly as it did before. Four surfaces read the burn — the
  ENERGY panel, the FOOD header, the Day tab's BODY block, `summary.build_payload` —
  and four separate compositions is four chances for one panel to measure the same
  day against two baselines. `resolved_factor` also returns *where* the factor came
  from, because that reaches the screen: a multiplier rescales every calorie
  judgement for its day, so it must not arrive with nothing to make you doubt it.
  The level keywords are standard PAL bands **re-described** to mean "a day with
  nothing logged" — the textbook labels bake habitual exercise in, and using those
  while also logging hard days counts the exercise twice.
- **A failed activity inference still records the activity, with a NULL factor.**
  The description is the user's data and the multiplier is a guess; losing the first
  because the second failed is the worse outcome. That NULL is the state `db.py` and
  `resolved_factor` already describe — the day falls back to the profile baseline,
  not to resting BMR. It is also why a factor is **not clearable** through the edit
  prompt: `_update` drops None, so a line with no `=` leaves the stored factor
  alone, which is what keeps a factorless row's description fixable at all.
- **Only the entry path infers a factor; an edit never does.** Fixing a typo in a
  description must not silently re-roll the number the whole day is measured
  against. The activity worker also has its **own** `@work` group: sharing the food
  estimate's would mean logging a gym session cancelled a meal estimate still
  running.
- **Net over a window is computed per day, never as one subtraction.** A factor
  describes a single day, so `avg_in − today's burn` lets one gym session restate a
  whole month. `body.net_series_between` pairs each day's intake with that day's own
  burn and skips days that lack either — a day before the first weigh-in has no BMR
  to scale, and showing its intake as net reads as an enormous surplus.
- **`horizon.py` is the single time-window concept**, shared by the Body chart and
  the Money tab. Never add a second one: v2 had chart windows on Body and ranges
  on Money, so `+` meant different things per tab and neither offered MTD or YTD.
  Spend filters by **date**, not by month — filtering by month made a one-week
  horizon silently cover the whole month.
- **A dated series is plotted against its dates, never its index.** `horizon.axis`
  resolves the plot extent and `braille_line(positions=…)` places each point.
  Index spacing rescales the x-axis to the *sample count*, so two weigh-ins a day
  apart drew a smooth month-long climb across a month-wide panel. Tick labels come
  from the axis too — from the data they printed "Aug 27 / Aug 28 / Aug 28".
- **Escape anything non-literal before it reaches markup**, with `widgets.esc`.
  Textual's content markup wants a **backslash**; `rich.markup.escape` is the wrong
  tool because it leaves a bare `[` alone, and `[` is itself a key — its footer
  hint rendered as `[[/] prev`. Filter text is user input and needs this too.
- **Colour is emphasis, never the only signal.** `widgets.GOOD/BAD/WARN` are
  palette hues, not the ANSI names — bare `red`/`green` resolve to `#ff0000` and
  `#008000`, harsh and near-unreadable on this background. An overrun still carries
  `⚠`, a weight change still carries its arrow. Weight colour assumes down-is-good
  because there is no goal weight to compare against.
- **Markup goes on *after* width arithmetic.** The bar builders return plain text
  and callers colour whole finished lines; colouring first makes `len()` count
  colour codes and silently sheds real content. DataTable cells use `rich.Text`,
  not markup, because the table measures columns from the cell's own render.
- **The TREND panel plots one series at a time, and only weight fits its own range.**
  `c` cycles weight · intake · net over the window `+`/`-` already control; the two are
  independent, so zooming must not reset the series. Weight is self-fitted because
  anchored at zero a 70–75 kg band is a flat line at the top of the panel; both calorie
  series pass `include_zero`, because a magnitude fitted to its own minimum reads as a
  climb from nothing and a *signed* net fitted to itself draws the same line whether it
  is a deficit or a surplus. The zero marker is a `┼` on the y-axis, never braille dots
  — dots among the data are indistinguishable from data — and it appears only when zero
  falls strictly inside the extent, because otherwise the extent label already says
  `0`.
- **A sparkline of a magnitude scales `from_zero`.** Fitting to the series' own
  min made six months of level rent land on the lowest glyph, so the
  second-largest spend category rendered as an empty floor. Weight, which only
  means anything relative to itself, keeps min–max.
- **The footer is two rows and generated from `KINDS`.** Row 1 is the tab's state,
  row 2 the keys grouped write+danger / view / nav. Every hint for a scope on one
  line runs past 200 columns — a wall where nothing stands out. It also drops any
  key the active scope has no handler for, asking the app's own resolver so the
  footer and the dispatcher cannot disagree.
- **`config.toml` is written by two functions that write to opposite ends, on
  purpose.** `update_config` inserts scalars **before the first table header**;
  `add_category` appends a `[[category]]` block **after everything**. TOML's scoping
  is positional and both failures are silent, because the file still parses either
  way: a scalar after `[[category]]` is a field of that table and is simply never read
  again, and a table header among the scalars swallows every scalar below it. Both
  edit the file as text so a hand-written comment survives. Neither is the general
  case of the other — don't unify them.
- **`b` prefills from the selected category, and only on the categories pane.** Editing
  a budget otherwise meant reading the amount off the pane and retyping the line;
  `upsert_budget` is keyed on `(month, name)`, so a changed number always replaced the
  line and what was missing was seeing the current one. It writes to
  `view.months()[-1]` — the month **on screen**, not today's, since `[` walks the
  anchor back — and the toast states that month. A group header on the expenses pane is
  the only other row carrying a slug, and it deliberately prefills nothing: that pane
  shows spend, and one key meaning two things depending on whether `G` is on is the
  cost. `budget` is `UNIQUE(month, name)`, not `(month, category)`, so a category can
  hold several lines; `money.budget_line` offers the newest, and the pane keeps summing
  all of them.
- **An empty state names the fix.** A month nobody rolled has no budget rows, and
  "0.00 budget / 1,234.00 over" is true, useless, and reads as stale data. It says
  what `r` would do instead. `money.pending_roll` must agree with
  `roll_month_budgets` or the header promises what the key won't deliver.
- **Panel content sizes itself from the panel**, via `content_size.width`. A
  hardcoded width wider than the panel wraps every row and doubles its height.
  `content_size` is 0 during `on_mount`, so the app re-renders once via
  `call_after_refresh`, and each widget handles its own `on_resize` — `Resize` is
  delivered to widgets, **not** to the App, so an App-level handler never fires.
- **The summary renders through Textual's `Markdown` widget.** Feed it markdown,
  not Rich markup; the prompt is instructed to emit plain markdown and no LaTeX,
  which no terminal renders. `markup.py` only converts legacy `<num>`/`<warn>`
  tags in reports already stored.
- **Part-to-whole is ranked bars, not a pie.** A terminal has ~8 distinguishable
  fill glyphs against 9 categories, so a pie collides and still needs a legend to
  read amounts.
- **A category can net negative, and every renderer has to survive it.** Refunds
  are first-class (`amount < 0`), so a reimbursed bill can outweigh a month's
  charges. Three separate bugs came from assuming otherwise: shares divided by the
  *signed* total summed past 100%, an unclamped bar width went to -44 of 14 cells
  and pushed the amounts off the panel, and the panels filtered `spent > 0` so the
  refund vanished while the header still showed the net. Shares are of **gross**
  spend; a negative row keeps its amount and shows no share.
- **`chart.py` and `widgets.py` import no Textual.** They are pure functions and
  unit-test as such.
- **Work in flight is announced by the popup, app-level, and nowhere else.** A
  `claude -p` call runs for seconds to a minute, so the indicator has to outlive a
  toast — that part was already true as a `"   estimating…"` suffix on the FOOD header
  and `"   generating…"` on SUMMARY. What was wrong is that both lived on the tab that
  started the work: pressing `3` erased every trace of a running estimate and the answer
  arrived later as a prompt with no explanation. `app.begin_work(key, label, timeout)` /
  `end_work(key)` is the only way to say it now, and a tab that grows a second indicator
  is reintroducing the bug. Keyed, not a boolean: a food estimate, an activity inference
  and the daily read can all be in flight at once, and the first two have separate worker
  groups on purpose. Elapsed is shown against the call's own budget (`18s / 60s`) because
  with animations off a static word cannot say "still alive"; the timer exists only while
  a job does. It lives in `#bottom` with the prompt and the footer rather than floating,
  so it pushes content up instead of covering the row you are reading, and costs no rows
  when hidden.
- **Animations stay off** (`self.animation_level = "none"`). Measured: 383 ms →
  127 ms per tab switch. It is an *instance* attribute in textual 8.2; a class
  attribute named `ANIMATION_LEVEL` is a silent no-op.
- **The data layer is fast; don't "optimise" it.** `summarize_month` over a
  few hundred expenses is 0.15 ms and a full tab reload is under 0.6 ms. If
  something feels slow, measure before touching queries — last time the entire
  cost turned out to be a UI animation.
- **No business logic in `daylogs/tui/`.** Tabs render and handle keys.
  Arithmetic belongs in `body.py` / `money.py` / `summary.py`, with tests
  there. A tab that grows a calculation is a bug worth rejecting.
- **Every prompt declares a hint in `daylogs/tui/hints.py`**, and a test greps the
  `prompt.open("…")` call sites to fail when one doesn't. `profile` shipped with a
  working grammar and no way to discover it because the label *was* the placeholder,
  so it vanished on the first keystroke and there was nowhere to put an example. The
  three slots are now: border title = label, placeholder = a copyable example
  (parsed by a test, so it must be valid), border subtitle = the grammar. An error
  takes the subtitle, not the title — the label stays useful while you read it.
- **One grammar, in `parse.py`, on top of `sigil.py`.** A field is marked by a
  sigil at the start of a token, so nothing is scavenged out of free text — which
  is what lets the same line serve entry *and* edit prefill. The previous grammar
  hunted for a category slug and a time token anywhere in the line, and silently
  stored the wrong category whenever a description contained a category word.
  `parse(render(row)) == row` is a tested property, over the corpus of inputs that
  broke the old grammar.
- **`sigil.py` and `complete.py` import no Textual**, like `chart.py` and
  `widgets.py`. Completion is a pure function of (line, cursor, vocabulary); the
  widget only decides when to call it.
- **A prompt's sigils are data on its `Hint`.** Vocabularies resolve at call time
  because `config.toml` can add categories, so a frozen literal would go stale.
- **An edit line carries the columns its table displays, plus expense's write-only
  note.** What you can see is what you can edit. Columns with no visible representation
  stay out of reach: food's `source` is provenance the digest reads, `created_at` must
  survive, `measured_at` is the tie-breaker `weight_series` uses to pick a day's
  reading. Expense's `~note` is currently write-only (settable, faithfully
  round-tripped through the edit prefill, displayed nowhere). An edit writes only
  the fields it parsed. The submitted line is authoritative: drop the note words
  and the note is cleared; submit unchanged and the note survives.
  The one displayed column deliberately **not** in an edit line is recurring's `on`,
  which `o` toggles instead: a boolean's entire edit is a toggle, and as a field every
  recurring line would carry a token that reads "on" almost always. It stayed
  unreachable for four versions — the column rendered `yes` for every row forever while
  `roll_month_budgets` filtered on a flag nothing could set — so the exception is
  written down here rather than left to be rediscovered as a bug.
- **`update_recurring` is keyed by id, and nothing may edit through
  `upsert_recurring`.** That resolves conflicts on `name`, so a rename matches
  nothing and INSERTs a second row; both then look active and the next
  `roll_month_budgets` writes two budget lines for one subscription. `monthly_cost`
  is a stored derived column and is recomputed whenever cost or cycle moves.
  `active` is absent from the ON CONFLICT clause for the same class of reason:
  `s` is add-*or-update* and its grammar cannot express the flag, so
  `active = excluded.active` meant every re-add carried the parameter's `True`
  default — raising a paused subscription's price un-paused it and the next roll
  charged for it. `note` is still overwritten there, on purpose: the recurring
  grammar has no `~note`, so that column is unreachable in both directions and
  fixing half of it would be pretending.
- **Pausing means "not from now on", never "this never happened".** A budget line
  already rolled for the month stays when you pause the item — you may have paid it —
  and next month's roll simply omits it. Same stance `_rename_rolled_budgets` takes on
  a deleted item's line, and the reason there is no un-roll.
- **Undo is an upsert on the primary key**, so one statement means "restore this row
  to these values" — covering a delete (row gone → insert) and an edit (row present
  → update) without the stack needing to know which. A plain INSERT raised on an
  edit's pre-image.
- **A comma is a thousands separator, never a decimal point.** `parse.to_amount`
  rejects a decimal comma before stripping thousands commas, so `12,40` is
  rejected with a suggestion rather than silently becoming 1240. A $12.40 lunch
  typed as `12,40` would have been recorded as $1,240.00; weights escaped only
  because 782 kg trips a plausibility check expenses have no equivalent of.
- **The app owns prompt-error policy.** Tabs let `ParseError`/`MoneyError`/
  `BodyError`/`PhotoError`/`ViewError` propagate; the app re-opens the prompt
  with the text intact. A tab that catches them discards what the user typed.
- **`claude -p` runners are always injected.** `DaylogsApp` takes
  `runner_text` / `runner_json` / `runner_image`; services take `runner=`. No
  test may spawn a subprocess.
- **Parsers stay pure.** `parse.py` takes `now` as an argument. No test result
  may depend on when the suite runs.
- **stdlib `sqlite3`, not an ORM.** Measured: the SQLAlchemy/SQLModel stack
  cost 220 ms of import time for zero remaining consumers.
- **`PRAGMA journal_mode=DELETE`, never WAL.** WAL sidecars sync independently
  under iCloud and corrupt the DB on the receiving device.
- **Hard delete plus session undo.** No `deleted_at` columns, no trash
  service.
- Amounts are positive for a spend. Dates are `TEXT` `YYYY-MM-DD`, local.
  Timestamps are `INTEGER` unix seconds.
- Single runtime dependency: `textual`. Adding another needs a reason that
  beats the standard library.

## Working on it

- Branch `claude/<topic>`; never commit implementation work to `main`.
  Squash-merge one slice per PR. Wait for CI green before merging.
- Gate every change on `pytest -q` **and** `ruff check .`.
- `docs/` is gitignored — a local paper trail (specs, plans, closing notes),
  not part of the repo.
- **The repo is written open-source-clean.** It is private today and may be
  published. No real weights, amounts, names, or `/Users/<name>/` paths in
  tracked files. Category slugs and `America/Toronto` are feature-domain
  values, not personal data. Fixtures use round, obviously-fake numbers.
- Verify dependency changes in a clean env, not just the local conda one. A
  dependency that happens to be installed locally but is missing from
  `pyproject.toml` only fails once CI builds from scratch.
- Push back on scope creep. This project's whole value is that it stayed
  small.

## Prompt tone

The LLM-facing prompts live in `summary.py` (`_VOICE` + `_TASK`) and
`estimate.py`. The summary voice is **objective and tactful** — direct about
what mattered, honest about misses, no grading, no manager-speak, loud on real
wins. It is tuned; preserve it when editing.
