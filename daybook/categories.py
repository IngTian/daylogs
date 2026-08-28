"""Expense categories: a constant tuple, extensible from config.toml.

A table with CRUD endpoints, a colour column and a sort order is the obvious
design and the wrong one here: ten rows that change twice a year do not need a
table, three foreign keys and a service. There is deliberately no `employment`
slug — it would only ever classify income, which daybook does not track.
"""

from __future__ import annotations

from dataclasses import dataclass

FALLBACK_SLUG = "other"

# Muted warm-earth palette, also used for the good/bad signals in the UI.
PALETTE: tuple[str, ...] = (
    "#7c8db7",
    "#a08fb1",
    "#79a888",
    "#d4a574",
    "#c47864",
    "#7faab2",
    "#b89588",
    "#8e9099",
    "#94b380",
    "#a39d96",
    "#b07a8c",
    "#9ba068",
    "#c79a5e",
    "#86a3a7",
    "#a37b62",
    "#7c958d",
)


@dataclass(frozen=True)
class Category:
    slug: str
    display: str
    color: str


BUILTIN: tuple[Category, ...] = (
    Category("grocery", "Grocery", "#d4a574"),
    Category("restaurant", "Restaurant", "#c47864"),
    Category("transport", "Transport", "#7c8db7"),
    Category("housing", "Housing", "#a08fb1"),
    Category("utilities", "Utilities", "#8e9099"),
    Category("subscriptions", "Subscriptions", "#7faab2"),
    Category("entertainment", "Entertainment", "#b89588"),
    Category("education", "Education", "#79a888"),
    Category(FALLBACK_SLUG, "Other", "#a39d96"),
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
