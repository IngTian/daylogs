"""Expense categories: a constant tuple, extensible from config.toml.

A table with CRUD endpoints, a colour column and a sort order is the obvious
design and the wrong one here: ten rows that change twice a year do not need a
table, three foreign keys and a service. There is deliberately no `employment`
slug — it would only ever classify income, which daylogs does not track.
"""

from __future__ import annotations

from dataclasses import dataclass

FALLBACK_SLUG = "other"

# Vivid warm-earth palette, also used for the good/bad signals in the UI.
# Each hue's HSV saturation multiplied by 1.55 and value by 1.04, clamped to 1.0.
PALETTE: tuple[str, ...] = (
    "#5f7bbe",
    "#9d81b8",
    "#63af7b",
    "#dc9142",
    "#cc5131",
    "#67acb9",
    "#bf8772",
    "#8d919f",
    "#88ba68",
    "#aaa095",
    "#b7607d",
    "#9ea64c",
    "#cf8626",
    "#78a7ae",
    "#aa6941",
    "#739b8e",
)


@dataclass(frozen=True)
class Category:
    slug: str
    display: str
    color: str


BUILTIN: tuple[Category, ...] = (
    Category("grocery", "Grocery", "#dc9142"),
    Category("restaurant", "Restaurant", "#cc5131"),
    Category("transport", "Transport", "#5f7bbe"),
    Category("housing", "Housing", "#9d81b8"),
    Category("utilities", "Utilities", "#8d919f"),
    Category("subscriptions", "Subscriptions", "#67acb9"),
    Category("entertainment", "Entertainment", "#bf8772"),
    Category("education", "Education", "#63af7b"),
    Category(FALLBACK_SLUG, "Other", "#aaa095"),
)


def auto_color(slug: str) -> str:
    """FNV-1a 32-bit hash into PALETTE. The same slug always yields the same
    colour, so a config-added category looks stable across machines."""
    h = 2166136261
    for ch in slug.encode("utf-8"):
        h ^= ch
        h = (h * 16777619) & 0xFFFFFFFF
    return PALETTE[h % len(PALETTE)]


def all_categories(cfg=None) -> tuple[Category, ...]:
    """Built-ins plus anything config.toml adds. Config cannot shadow a
    built-in — a typo in config should never silently redefine `grocery`."""
    extra = getattr(cfg, "extra_categories", ()) or ()
    builtin_slugs = {c.slug for c in BUILTIN}
    added = tuple(
        Category(slug, display or slug, color or auto_color(slug))
        for slug, display, color in extra
        if slug not in builtin_slugs
    )
    return BUILTIN + added


def slugs(cfg=None) -> frozenset[str]:
    return frozenset(c.slug for c in all_categories(cfg))


def get(slug: str, cfg=None) -> Category | None:
    for c in all_categories(cfg):
        if c.slug == slug:
            return c
    return None
