# daybook

A terminal app for three things: what you weigh, what you eat, and what you
spend — plus one short daily read of all of it, written by Claude.

One command. One process. No server, no browser, no ports.

```
 🐄                                    daybook — Fri Aug 28
 1 Day  2 Body  3 Money
╸━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 TODAY   Fri Aug 28
╭──────────────────────────────────────────────╮╭──────────────────────────────────────────────╮
│ BODY                                         ││ MONEY                                        │
│   weight      71.0 kg  ▼0.2 vs 7d           ││   spent      1,200.00 of 1,500.00            │
│   in        1,600 / 1,450 BMR                ││   left         300.00                        │
│   net         +150 kcal                      ││   burn           80% on day 28/31            │
│   logged         2 meals                     ││                                              │
╰──────────────────────────────────────────────╯╰──────────────────────────────────────────────╯
 SUMMARY   Thu Aug 27   generated 06:10
  Body: steady at 71 kg, down slightly over the week. Intake was 1,600 kcal
  with a +150 net, comfortably above maintenance.

  Money: spent 1,200 of 1,500 budget, tracking well for the month.

 Thu Aug 27
 r regenerate · u undo   ? keys   [ prev · ] next · t today · g go to date · q quit
```

## What it is, and what it isn't

Three things, deliberately. There is no income tracking, no net worth, no cash
projection, no investments, no journal, no sync, no server and no web UI. Money
answers one question: where did it go this period, and am I inside the budget.

The design rule: **anything that doesn't survive daily use doesn't ship.**

## Install

```bash
conda create -n daybook python=3.12
conda activate daybook
pip install -e '.[dev]'
```

**Requirements.** Python 3.12+ and any terminal with truecolour. macOS and Linux;
not tested on Windows.

The [Claude Code CLI](https://claude.com/claude-code) on `PATH` is needed for
calorie estimation and the daily summary — everything else works without it, and
the app degrades to plain messages rather than failing.

Pasting a photo from the clipboard uses `osascript`, so that one path is macOS
only. The inbox folder and a pasted file path work anywhere.

## Use

```bash
day                            # the TUI
day summary                    # generate yesterday's summary, print to stdout
day summary --date 2026-08-20  # a specific day
day backup ~/Drive/daybook     # consistent DB copy (cron-friendly)
day export ~/Drive/daybook     # one CSV per table, readable anywhere
day --version
```

To run `day` from any shell without activating the environment, symlink the
console script somewhere on your `PATH`:

```bash
ln -sf "$(command -v day)" ~/.local/bin/day
```

`build_binary.sh` produces a standalone PyInstaller executable for a machine
with no Python — but it starts in ~4,770 ms against ~60 ms for the symlink,
because `--onefile` unpacks 15 MB on every launch. Prefer the symlink locally.

### Keys

Press `?` for the full map at any time — it's generated from the same table the
bindings and the footer come from, so it can't be out of date.

The footer is two rows: what you're looking at on top (range, sort, filters), and
the keys below, grouped into actions, view controls and navigation and coloured by
group. On a narrow terminal it sheds navigation keys first and never `?` or `q`.

**Everywhere**

| Key | Does |
|---|---|
| `1` `2` `3` | Day / Body / Money |
| `←` `→` | previous / next tab — stops at the ends rather than wrapping |
| `tab` `shift+tab` | next / previous sub-view *within* the tab (Body, Money) |
| `[` `]` | previous / next period — report on Day, day on Body, month on Money |
| `t` | **jump to now** — today, this month, newest report |
| `g` | go to a date (`2026-06-15` or `2026-06`) |
| `+` `-` | widen / narrow the time horizon (Body, Money): `1w` `1m` `MTD` `3m` `YTD` `1y` `all` |
| `?` | the full keymap |
| `u` | undo the last delete or edit |
| `esc` | back out one step — never quits |
| `q` | quit |

`t` and `g` are why `[` / `]` stepping one period at a time is fine: you're
never more than two keystrokes from anywhere.

**Day — `1`** · `r` regenerates the daily read. `[` `]` browse earlier ones; the
figures above them are always today's.

**Body — `2`**

| Key | Does |
|---|---|
| `w` | weigh in |
| `f` | log food |
| `p` | log food from a photo |
| `h` | set height, sex and birthday (for BMR) |
| `enter` | edit the selected row |
| `x` | delete the selected row (confirm with `y`) |

**Money — `3`**

| Key | Does |
|---|---|
| `e` | log an expense |
| `b` | set a budget line |
| `s` | add or update a recurring item |
| `r` | roll active recurring items into the month's budget |
| `d` `c` `k` | sort by date / cost / category — press again to flip direction |
| `/` | filter by text |
| `G` | group the expense list by category |
| `enter` | drill into a category, fold a group, or edit the selected row |
| `x` | delete the selected row (confirm with `y`) |

### What you type

| Prompt | Type | Result |
|---|---|---|
| `weigh ›` | `78.2` | logged now |
| `weigh ›` | `78.2 post-run @07:30` | with a note, at a time |
| `food ›` | `chicken salad =610` | labelled — no LLM call |
| `food ›` | `chicken salad` | Claude estimates; review and accept |
| `expense ›` | `12.40 lunch !restaurant` | amount, description, category |
| `expense ›` | `127 Grocery Item X !grocery ~receipt in wallet` | with a note |
| `expense ›` | `-24.99 returned shoes !grocery` | a refund |
| `budget ›` | `500 !grocery` | named after the category |
| `recurring ›` | `20.99 Streaming !subscriptions #monthly` | monthly |

Sigils mark the fields, so nothing is ever taken out of your own words:

    !  a category                   tab completes
    #  a cycle                      tab completes
    @  a date and/or a time         @2026-08-24  @08-24  @14:30  @08-24/14:30
    ~  a note (may contain spaces)
    =  calories

Everything unsigiled is the description. The first token is the amount. `\` escapes
a leading sigil, so `\!important` is just a word.

Every prompt shows what it wants, in three places and no extra screen rows:

```
╭─ profile › ───────────────────────────────────────╮
│ 180 male 1990-01-01                               │   the example, greyed
╰─ height · m/f · birthday — any order, partial ok ─╯   the grammar, persistent
```

The example is the placeholder, so it gets out of the way as soon as you type. The
grammar stays, because that's the part you still want halfway through a line. Every
example is a line the parser actually accepts — a test parses all of them.

Every write answers with its consequence, not just an acknowledgement —
`78.2 kg logged · ▼0.4 vs 7d`, or `12.40 lunch → restaurant 289.50 of 200.00 ⚠`.

A rejected entry **keeps your text** and shows why on the bottom border, so one
wrong character costs one correction rather than a retype.

Amounts take `$` and thousands separators (`$1,240.50`), but a comma is never a
decimal point — `12,40` is rejected with a suggestion rather than quietly becoming
1240.

### Editing

`enter` acts on whatever is under the cursor: a weight, food, expense or recurring
row opens for editing, a category drills in, a group folds.

Editing prefills the same grammar you used for entry. The submitted line is
authoritative: drop the note words and the note is cleared; submit unchanged and
the note survives. Food entries always require `=kcal` — dropping it is rejected
rather than silently zeroing the calories. Each line carries exactly the columns
that row's table shows, so what you can see is what you can edit.

`u` undoes an edit as well as a delete.

### Time horizons

One list serves both tabs, so `+` and `-` mean the same thing everywhere:

    1w · 1m · MTD · 3m · YTD · 1y · all

`1w`/`1m`/`3m`/`1y` look back from the day you're on; `MTD` and `YTD` run from the
start of that month or year. `[` and `]` then step by one whole horizon — on `MTD`
that's a calendar month, so you compare the same elapsed slice of the previous
month rather than a ragged window.

`g 2026-06` lands on the **last** day of June, so under `MTD` you get all of it.

### Reading money

Over several months the budget column is the **sum** of those months' lines.

Green means inside the budget, amber means within 10% of a cap, red means over —
alongside the `⚠` glyph, never instead of it. On Body, a falling weight is green and
a rising one red; there's no goal weight to compare against, so that's an
assumption, and the arrow carries the direction either way.

A month nobody has rolled yet has no budget at all, and the header says so and
names the key rather than reporting a meaningless "0.00 budget".

The burn bar's `┃` marker is how far through the month you are — 84% of budget
spent on day 27 of 31 is fine, the same number on day 12 is not. It only appears
for the current single month, because burn-against-elapsed means nothing across a
quarter; the bar says so when it's hidden.

### Panels

**Day** shows BODY beside MONEY — today's weight and trend, intake against BMR,
this month's spend against its budget and how far through the month you are — with
the generated daily read scrolling underneath. The figures are always today's; the
read is dated by the day it describes, which is why each half carries its own date.

**Body** shows TREND (the braille chart) beside ENERGY — intake against BMR for
the day, then the average and a sparkline over the horizon.

**Money** shows BUDGET vs SPENT beside WHERE IT WENT. The first scales each bar to
that category's own cap, so "how close to this limit" is readable per row; the
second is a ranked share list.

Ranked bars rather than pie charts, deliberately: a terminal has about eight
distinguishable fill glyphs and there are nine categories, so a pie collides — and
you still need a legend to read any amount.

Shares are of **gross** spend. A refund can push a category below zero for the
window — a reimbursed bill, a returned order — and such a row keeps its amount but
shows no share, because a part-to-whole has no negative slice. It still appears on
both panels, so the rows and the header total reconcile.

### The weight chart

A braille line chart: 2×4 dots per cell, so an 8-row by 48-column chart carries
96×32 dot resolution. The width follows the panel, so a wider terminal buys more
horizontal detail.

Points sit at their real dates, not spread evenly across the panel. Two weigh-ins a
day apart show up as two weigh-ins a day apart, with the weeks you didn't step on
the scale visibly empty — a gap is information.

It's a line rather than bars deliberately. Weight sits in a narrow band, and a
bar or filled area implies a meaningful zero baseline — anchored at your minimum
it would render as a solid block whose only readable feature is its top edge.
Spend is a magnitude from zero, so bars stay correct there.

### The daily summary

One `claude -p` call, once a day, over whatever the other two tabs recorded. It
runs unattended the first time you open the app after `summary_after_hour`, and `r`
regenerates it.

A report is dated by the day it *describes*, not the day it runs — a summary of
today would be reading a half-finished day, so the target is yesterday.

Anything you put in `memory.md` (see Configuration) is passed along as context for
who you are, so the summary can be about you rather than about a table of numbers.

### Any entry prompt

In the weigh / food / expense prompts, `@2026-08-25` or `@08-25` sets the date
and `@13:05` sets the time, wherever you put them in the line.

Everywhere: `esc` cancels, `↑` / `↓` walk that prompt's history.

## Configuration

Optional. `~/Documents/daybook/config.toml`; every key has a default.

```toml
timezone             = "America/Toronto"
height_cm            = 170          # BMR input
sex                  = "female"     # BMR constant term only
birthday             = "1990-01-01" # age, for BMR
claude_model         = ""           # empty = CLI default
summary_after_hour   = 6
summary_timeout_sec  = 120
estimate_timeout_sec = 60

# Paths. Relative values resolve against the data root above.
db_path              = "daybook.db"
inbox_dir            = "inbox"      # phone photos land here
memory_path          = "memory.md"  # free text passed to the daily summary

[[category]]
slug    = "gym"
display = "Gym"
color   = "#9ba068"
```

Built-in categories: `grocery`, `restaurant`, `transport`, `housing`,
`utilities`, `subscriptions`, `entertainment`, `education`, `other`. Adding
one needs no code change — just a `[[category]]` block.

Height, sex and birthday only feed the Mifflin-St Jeor BMR line. Leave them
out and the Body tab shows calories without a maintenance baseline. You don't have
to edit the file for those three — `h` on the Body tab writes them here for you,
keeping your comments and `[[category]]` blocks intact.

## Photos from a phone

Three ways in, tried in that order when you press `p`:

1. **Clipboard** — screenshot or Continuity Camera, then `p`.
2. **Inbox** — on the phone: Photos → Share → Save to Files →
   `daybook/inbox`. The Body tab shows a pending count; `p` takes the oldest
   and moves it to `inbox/processed/` once the row is written. Shoot at lunch,
   log at night.
3. **Path** — paste or drag a file into the prompt.

A failed estimate leaves the file pending rather than silently consuming it.

## Data

SQLite, six tables, at `~/Documents/daybook/daybook.db`. Logs at
`~/.daybook/logs/`. Override the data root with `DAYBOOK_HOME`.

The connection runs `PRAGMA journal_mode=DELETE` on purpose. WAL's `-wal` and
`-shm` sidecars can sync independently of the main file under iCloud Drive and
corrupt the database on the receiving device; rollback-journal keeps SQLite to
one file. daybook is read-heavy, so the write cost is noise.

**Back it up.** A synced folder is not a backup: it replicates a deletion or a
corruption as faithfully as it replicates a write. `day backup <dir>` writes a
consistent copy via `VACUUM INTO`; point it somewhere else you own and run it
from cron.

**And get it out.** A backup only daybook can open is a weaker promise than a file
anything can read, so `day export <dir>` writes one CSV per table into a dated
subdirectory — `weight`, `food`, `expense`, `recurring`, `budget`, `report`, with
the schema's own column names as headers. The table list comes from the database
rather than a hand-kept list, so nothing is silently left out. It prints the
directory on stdout and per-table row counts on stderr, so `cd "$(day export
~/Drive/daybook)"` works and cron logs stay readable.

CSV, because every table is flat and "open it in a spreadsheet" is the point. The
one cost: CSV cannot tell an empty note from an absent one — both come out blank.
It is an export, not an import; loading it back in is not supported.

## Development

```bash
pytest
ruff check .
```

Runtime dependency: `textual`. Everything else is the standard library.

Design notes:

- Business logic never lives in `daybook/tui/`. Tabs render and handle keys;
  arithmetic lives in `body.py` / `money.py` / `summary.py` with tests.
- The `claude -p` runners are always injected, so no test spawns a subprocess.
- Parsers in `parse.py` are pure functions with `now` passed in — no test
  depends on when it runs.
- Deletes are hard, with a session-scoped undo ring. That drops a `deleted_at`
  column from every table, the active/in-use query wrappers, a trash service,
  and a partial unique index.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Short version: improvements to the three
existing features are welcome; a fourth feature needs an issue first, because
staying small is the point.

## Licence

MIT — see [LICENSE](LICENSE).
