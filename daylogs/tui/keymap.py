"""The keymap, as data.

Bindings, the contextual footer, and the `?` overlay are all generated from
KEYMAP. That is the point: a hand-written footer can name a key that isn't bound,
or omit one that is — a footer that writes its own spans by hand can do both.
Deriving all three from one table makes that class of bug unrepresentable.

`scope` is "app" (works everywhere) or a tab id. A key may mean different things
in different tab scopes — `r` rolls recurring items on Money and regenerates the
summary on Summary — but a tab key may never shadow an app key, which a test
enforces.

Key names are Textual's own (`left_square_bracket`, not `[`); every one here was
verified against a running app rather than guessed.
"""

from __future__ import annotations

from dataclasses import dataclass

SCOPES = ("app", "body", "money", "summary")
KINDS = ("nav", "view", "write", "danger")


@dataclass(frozen=True)
class Key:
    key: str        # Textual key name
    label: str      # shown in the footer and the help overlay
    action: str     # -> the tab's key_<action>(), else the app's app_<action>()
    scope: str
    kind: str
    footer: bool = True
    bind: bool = True       # False = delivered by another route, not a Binding
    priority: bool = False  # True = must beat Screen/DataTable default bindings
    pin: bool = False       # True = never dropped from a narrow footer


KEYMAP: tuple[Key, ...] = (
    # ── app: navigation ──────────────────────────────────────────────────
    # The digits match the visible tab numbers. They dispatch to *named* actions,
    # not positions, so moving a pane without moving its digit leaves a tab
    # labelled 3 that 2 jumps to.
    Key("1", "day", "show_summary", "app", "nav", footer=False),
    Key("2", "body", "show_body", "app", "nav", footer=False),
    Key("3", "money", "show_money", "app", "nav", footer=False),
    # Walk the tabs, the way 1/2/3 jump to them. NOT priority — measured, not
    # assumed: on this Textual version a `cursor_type="row"` DataTable does not
    # claim left/right, so a plain binding already fires with the table focused,
    # while a focused Input still gets the keys first and keeps its cursor
    # movement. With priority=True both fire, so editing a line you typed would
    # switch tabs *and* leave the cursor stuck. Same trap as printable keys.
    # footer=False: the footer is already full, and `?` lists them.
    Key("left", "prev tab", "prev_tab", "app", "nav", footer=False),
    Key("right", "next tab", "next_tab", "app", "nav", footer=False),
    # priority: measured — an ordinary App binding for tab loses to the Screen's
    # focus-next, so the key would move focus instead of changing sub-view.
    # Priority is safe here because Textual still delivers printable characters
    # to a focused Input; tab and shift+tab are never text.
    Key("tab", "next view", "next_subview", "app", "nav", priority=True),
    Key("shift+tab", "prev view", "prev_subview", "app", "nav", footer=False, priority=True),
    Key("left_square_bracket", "prev", "prev_period", "app", "nav"),
    Key("right_square_bracket", "next", "next_period", "app", "nav"),
    Key("t", "today", "jump_now", "app", "nav"),
    Key("g", "go to date", "goto", "app", "nav"),
    # A magnifying glass, not a window size: `+` shortens the horizon and shows
    # it in more detail, `-` pulls back. It read the other way round until 0.3.0
    # — `+` was labelled "wider" while calling an action named `zoom_in` — which
    # disagreed with every map and image viewer, and with itself.
    #
    # `equals_sign` is the same action: `+` needs shift on every layout this runs
    # on and `=` is the same physical key without it. Off the footer so the hint
    # is not drawn twice; `?` lists it.
    Key("plus", "zoom in", "zoom_in", "app", "view"),
    Key("equals_sign", "zoom in", "zoom_in", "app", "view", footer=False),
    Key("minus", "zoom out", "zoom_out", "app", "view", footer=False),
    # Uppercase, like `G` on Money: a shifted key for something done rarely, and it
    # leaves `t` (jump to now) alone, which is pressed constantly. Off the footer —
    # already full — and listed by `?`.
    Key("T", "theme", "theme", "app", "view", footer=False),
    # ── app: meta ────────────────────────────────────────────────────────
    # pinned: `?` is how you discover everything else and `q` is how you leave.
    # Without pinning they sit last in the footer and are the first things a
    # narrow terminal drops — exactly backwards.
    Key("question_mark", "keys", "help", "app", "view", pin=True),
    Key("u", "undo", "undo", "app", "danger"),
    Key("escape", "back", "back", "app", "nav", footer=False),
    Key("q", "quit", "quit", "app", "nav", pin=True),
    # ── body ─────────────────────────────────────────────────────────────
    Key("w", "weigh", "weigh", "body", "write"),
    Key("f", "food", "food", "body", "write"),
    Key("p", "photo", "photo", "body", "write"),
    Key("h", "profile", "profile", "body", "write"),
    # Only for a day that departs from the profile's ordinary day, which is why there
    # is no daily prompt for it: a field you must retype every day is one that gets
    # skipped, and then `net` sits on the wrong baseline.
    Key("a", "activity", "activity", "body", "write"),
    # bind=False for the same reason as money's: a focused DataTable converts
    # enter into RowSelected before any binding sees it.
    Key("enter", "edit", "activate", "body", "nav", bind=False),
    Key("x", "delete", "delete", "body", "danger"),
    # Which series the TREND panel plots. A view control, not a write: it changes what
    # you are looking at over the window `+`/`-` already control, and the two are
    # independent. Body-scoped, so it does not collide with Money's `c` (by cost).
    Key("c", "chart", "next_chart", "body", "view"),
    # ── money ────────────────────────────────────────────────────────────
    Key("e", "expense", "expense", "money", "write"),
    Key("b", "budget", "budget", "money", "write"),
    Key("s", "recurring", "recurring", "money", "write"),
    Key("r", "roll", "roll", "money", "write"),
    Key("d", "by date", "sort_date", "money", "view"),
    Key("c", "by cost", "sort_cost", "money", "view"),
    Key("k", "by category", "sort_category", "money", "view"),
    Key("slash", "filter", "filter", "money", "view"),
    Key("G", "group", "toggle_group", "money", "view"),
    # bind=False: a focused DataTable turns enter into its own RowSelected
    # message, so an App binding never sees it. Activation rides that message
    # instead — the native path, rather than fighting the widget for the key.
    Key("enter", "open", "activate", "money", "nav", bind=False),
    Key("x", "delete", "delete", "money", "danger"),
    # ── summary ──────────────────────────────────────────────────────────
    Key("r", "regenerate", "generate", "summary", "write"),
)


def keys_for(scope: str) -> tuple[Key, ...]:
    return tuple(k for k in KEYMAP if k.scope == scope)


def footer_keys(scope: str) -> tuple[Key, ...]:
    """Scope-specific keys first, then app keys — the tab's own verbs are what
    the user is looking for, and a narrow terminal drops from the right."""
    app = tuple(k for k in keys_for("app") if k.footer)
    if scope == "app":
        return app
    return tuple(k for k in keys_for(scope) if k.footer) + app


def lookup(key: str, scope: str) -> Key | None:
    """Resolve in the tab's scope first, then fall back to app scope."""
    for k in KEYMAP:
        if k.key == key and k.scope == scope:
            return k
    for k in KEYMAP:
        if k.key == key and k.scope == "app":
            return k
    return None


def app_bindings() -> list[tuple[str, str, str, bool]]:
    """(key, action, description, priority) for App.BINDINGS — one binding per
    distinct bindable key. Which handler runs is resolved from the active scope
    at press time, which is how one key means three things without three binding
    tables.

    Keys marked `bind=False` are excluded: they arrive by another route.
    """
    priority: dict[str, bool] = {}
    for k in KEYMAP:
        if not k.bind:
            continue
        priority[k.key] = priority.get(k.key, False) or k.priority
    return [(key, f"dispatch('{key}')", "", prio) for key, prio in priority.items()]


def help_groups() -> dict[str, tuple[Key, ...]]:
    return {
        kind: tuple(k for k in KEYMAP if k.kind == kind)
        for kind in KINDS
        if any(k.kind == kind for k in KEYMAP)
    }
