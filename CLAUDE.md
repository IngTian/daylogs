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
  config.py   tomllib config + update_config; DAYLOGS_HOME overrides the data root
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
    keymap.py   every key, as data — generates bindings, footer and help
    hints.py    every prompt's example and grammar, as data
    common.py   PanelTab: on_resize + panel_width, shared by the two big tabs
    chart.py    braille line charts (no Textual import)
    widgets.py  bars, sparklines, colours, markup escaping (no Textual import)
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
- **A sparkline of a magnitude scales `from_zero`.** Fitting to the series' own
  min made six months of level rent land on the lowest glyph, so the
  second-largest spend category rendered as an empty floor. Weight, which only
  means anything relative to itself, keeps min–max.
- **The footer is two rows and generated from `KINDS`.** Row 1 is the tab's state,
  row 2 the keys grouped write+danger / view / nav. Every hint for a scope on one
  line runs past 200 columns — a wall where nothing stands out. It also drops any
  key the active scope has no handler for, asking the app's own resolver so the
  footer and the dispatcher cannot disagree.
- **`config.toml` is written through `config.update_config`**, which inserts new
  scalars **before the first table header**. A scalar after `[[category]]` is a
  field of that table as far as TOML cares — it still parses, so nothing complains,
  and the setting is simply never read.
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
- **`update_recurring` is keyed by id, and nothing may edit through
  `upsert_recurring`.** That resolves conflicts on `name`, so a rename matches
  nothing and INSERTs a second row; both then look active and the next
  `roll_month_budgets` writes two budget lines for one subscription. `monthly_cost`
  is a stored derived column and is recomputed whenever cost or cycle moves.
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
