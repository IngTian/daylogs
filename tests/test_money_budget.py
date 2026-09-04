import pytest

from daylogs.money import (
    MoneyError,
    delete_recurring,
    list_budget,
    list_recurring,
    monthly_equivalent,
    pending_roll,
    roll_month_budgets,
    summarize_month,
    update_recurring,
    upsert_budget,
    upsert_recurring,
)


# ── recurring ────────────────────────────────────────────────────────────
def test_monthly_equivalent_divides_annual_by_twelve():
    assert monthly_equivalent(120.0, "annually") == 10.0
    assert monthly_equivalent(20.99, "monthly") == 20.99
    assert monthly_equivalent(100.0, "annually") == pytest.approx(8.33)


def test_monthly_equivalent_rejects_unknown_cycle():
    with pytest.raises(MoneyError, match="cycle"):
        monthly_equivalent(10.0, "weekly")


def test_upsert_recurring_creates_then_updates_by_name(db):
    first = upsert_recurring(
        db, name="streaming", cost=20.99, cycle="monthly", category="subscriptions"
    )
    second = upsert_recurring(
        db, name="streaming", cost=24.99, cycle="monthly", category="subscriptions"
    )
    assert first == second
    rows = list_recurring(db)
    assert len(rows) == 1
    assert rows[0]["cost"] == 24.99
    assert rows[0]["monthly_cost"] == 24.99


def test_upsert_recurring_stores_monthly_cost_for_annual(db):
    upsert_recurring(
        db, name="cloud storage", cost=120.0, cycle="annually", category="subscriptions"
    )
    row = list_recurring(db)[0]
    assert (row["cost"], row["monthly_cost"], row["cycle"]) == (120.0, 10.0, "annually")


def test_upsert_recurring_rejects_bad_inputs(db):
    with pytest.raises(MoneyError):
        upsert_recurring(db, name="", cost=1.0, cycle="monthly", category="subscriptions")
    with pytest.raises(MoneyError):
        upsert_recurring(db, name="x", cost=0, cycle="monthly", category="subscriptions")
    with pytest.raises(MoneyError):
        upsert_recurring(db, name="x", cost=1.0, cycle="weekly", category="subscriptions")
    with pytest.raises(MoneyError):
        upsert_recurring(db, name="x", cost=1.0, cycle="monthly", category="nope")


def test_recurring_sorted_by_monthly_cost_desc(db):
    upsert_recurring(db, name="small", cost=5.0, cycle="monthly", category="subscriptions")
    upsert_recurring(db, name="big", cost=50.0, cycle="monthly", category="subscriptions")
    assert [r["name"] for r in list_recurring(db)] == ["big", "small"]


def test_active_only_filter_and_toggle(db):
    rid = upsert_recurring(db, name="gym", cost=50.0, cycle="monthly", category="entertainment")
    assert len(list_recurring(db, active_only=True)) == 1
    assert update_recurring(db, rid, active=False) is True
    assert list_recurring(db, active_only=True) == []
    assert len(list_recurring(db)) == 1


def test_delete_recurring_returns_row(db):
    rid = upsert_recurring(db, name="gym", cost=50.0, cycle="monthly", category="entertainment")
    assert delete_recurring(db, rid)["name"] == "gym"
    assert list_recurring(db) == []


# ── budgets ──────────────────────────────────────────────────────────────
def test_upsert_budget_creates_then_updates_by_month_and_name(db):
    a = upsert_budget(db, month="2026-08", name="Grocery", category="grocery", amount=500)
    b = upsert_budget(db, month="2026-08", name="Grocery", category="grocery", amount=550)
    assert a == b
    rows = list_budget(db, month="2026-08")
    assert len(rows) == 1 and rows[0]["amount"] == 550


def test_same_name_different_month_is_a_separate_line(db):
    upsert_budget(db, month="2026-08", name="Grocery", category="grocery", amount=500)
    upsert_budget(db, month="2026-09", name="Grocery", category="grocery", amount=520)
    assert len(list_budget(db, month="2026-08")) == 1
    assert len(list_budget(db, month="2026-09")) == 1


def test_budget_rejects_bad_inputs(db):
    with pytest.raises(MoneyError):
        upsert_budget(db, month="2026-8", name="x", category="grocery", amount=1)
    with pytest.raises(MoneyError):
        upsert_budget(db, month="2026-08", name="", category="grocery", amount=1)
    with pytest.raises(MoneyError):
        upsert_budget(db, month="2026-08", name="x", category="grocery", amount=-1)
    with pytest.raises(MoneyError):
        upsert_budget(db, month="2026-08", name="x", category="nope", amount=1)
    with pytest.raises(MoneyError):
        upsert_budget(db, month="2026-08", name="x", category="grocery", amount=1, source="magic")


def test_budget_zero_amount_is_allowed(db):
    upsert_budget(db, month="2026-08", name="x", category="grocery", amount=0)
    assert list_budget(db, month="2026-08")[0]["amount"] == 0


def test_roll_creates_one_line_per_active_recurring(db):
    upsert_recurring(db, name="streaming", cost=20.99, cycle="monthly", category="subscriptions")
    upsert_recurring(
        db, name="cloud storage", cost=120.0, cycle="annually", category="subscriptions"
    )
    inactive = upsert_recurring(
        db, name="old gym", cost=50.0, cycle="monthly", category="entertainment"
    )
    update_recurring(db, inactive, active=False)

    assert roll_month_budgets(db, month="2026-08") == 2
    rows = {r["name"]: r for r in list_budget(db, month="2026-08")}
    assert set(rows) == {"streaming", "cloud storage"}
    assert rows["cloud storage"]["amount"] == 10.0
    assert rows["streaming"]["source"] == "recurring"


def test_roll_is_idempotent(db):
    upsert_recurring(db, name="streaming", cost=20.99, cycle="monthly", category="subscriptions")
    assert roll_month_budgets(db, month="2026-08") == 1
    assert roll_month_budgets(db, month="2026-08") == 0
    assert len(list_budget(db, month="2026-08")) == 1


def test_roll_does_not_overwrite_a_manual_line_of_the_same_name(db):
    upsert_recurring(db, name="streaming", cost=20.99, cycle="monthly", category="subscriptions")
    upsert_budget(db, month="2026-08", name="streaming", category="subscriptions", amount=99.0)
    assert roll_month_budgets(db, month="2026-08") == 0
    row = list_budget(db, month="2026-08")[0]
    assert (row["amount"], row["source"]) == (99.0, "manual")


def test_roll_with_no_recurring_items_returns_zero(db):
    assert roll_month_budgets(db, month="2026-08") == 0


# ── pending_roll ────────────────────────────────────────────────────────────


def test_pending_roll_reports_what_a_roll_would_add(db):
    upsert_recurring(db, name="Rent", category="housing", cost=750, cycle="monthly")
    upsert_recurring(db, name="Phone", category="utilities", cost=60, cycle="monthly")
    assert pending_roll(db, month="2026-08") == (2, 810.0)


def test_pending_roll_skips_names_already_budgeted(db):
    upsert_recurring(db, name="Rent", category="housing", cost=750, cycle="monthly")
    upsert_recurring(db, name="Phone", category="utilities", cost=60, cycle="monthly")
    upsert_budget(db, month="2026-08", name="Rent", category="housing", amount=800)
    assert pending_roll(db, month="2026-08") == (1, 60.0)


def test_pending_roll_ignores_inactive_items(db):
    upsert_recurring(db, name="Rent", category="housing", cost=750, cycle="monthly")
    upsert_recurring(
        db, name="Old", category="other", cost=99, cycle="monthly", active=False
    )
    assert pending_roll(db, month="2026-08") == (1, 750.0)


def test_pending_roll_is_zero_when_nothing_to_do(db):
    assert pending_roll(db, month="2026-08") == (0, 0.0)


def test_pending_roll_matches_what_roll_actually_creates(db):
    """If these two disagree the header promises a number the key won't deliver."""
    upsert_recurring(db, name="Rent", category="housing", cost=750, cycle="monthly")
    upsert_recurring(db, name="Gym", category="other", cost=40, cycle="monthly")
    count, _ = pending_roll(db, month="2026-08")
    assert roll_month_budgets(db, month="2026-08") == count
    assert pending_roll(db, month="2026-08") == (0, 0.0)


# ── update_recurring ────────────────────────────────────────────────────────


def test_update_recurring_renames_in_place_instead_of_inserting(db):
    """upsert_recurring resolves conflicts on `name`, so a rename matches nothing and
    INSERTs. Both rows then look active and the next roll writes two budget lines for
    one subscription."""
    upsert_recurring(db, name="streaming", category="subscriptions", cost=20, cycle="monthly")
    row_id = list_recurring(db)[0]["id"]
    update_recurring(db, row_id, name="streaming plus")
    rows = list_recurring(db)
    assert len(rows) == 1
    assert rows[0]["id"] == row_id
    assert rows[0]["name"] == "streaming plus"


def test_update_recurring_recomputes_the_derived_monthly_cost(db):
    """roll_month_budgets reads monthly_cost, so a stale value would land in next
    month's budget with nothing on screen connecting the two."""
    upsert_recurring(db, name="Cloud", category="subscriptions", cost=120, cycle="annually")
    row_id = list_recurring(db)[0]["id"]
    assert list_recurring(db)[0]["monthly_cost"] == 10.0
    update_recurring(db, row_id, cycle="monthly")
    assert list_recurring(db)[0]["monthly_cost"] == 120.0
    update_recurring(db, row_id, cost=60)
    assert list_recurring(db)[0]["monthly_cost"] == 60.0


def test_update_recurring_rejects_a_name_that_already_exists(db):
    upsert_recurring(db, name="Rent", category="housing", cost=750, cycle="monthly")
    upsert_recurring(db, name="Gym", category="other", cost=40, cycle="monthly")
    gym = [r for r in list_recurring(db) if r["name"] == "Gym"][0]
    with pytest.raises(MoneyError, match="already exists"):
        update_recurring(db, gym["id"], name="Rent")
    assert len(list_recurring(db)) == 2


def test_update_recurring_keeping_its_own_name_is_not_a_collision(db):
    upsert_recurring(db, name="Rent", category="housing", cost=750, cycle="monthly")
    row_id = list_recurring(db)[0]["id"]
    update_recurring(db, row_id, name="Rent", cost=800)
    assert list_recurring(db)[0]["cost"] == 800.0


def test_update_recurring_rejects_a_nonpositive_cost(db):
    upsert_recurring(db, name="Rent", category="housing", cost=750, cycle="monthly")
    row_id = list_recurring(db)[0]["id"]
    with pytest.raises(MoneyError, match="positive"):
        update_recurring(db, row_id, cost=0)


def test_update_recurring_rejects_an_unknown_column(db):
    upsert_recurring(db, name="Rent", category="housing", cost=750, cycle="monthly")
    row_id = list_recurring(db)[0]["id"]
    with pytest.raises(MoneyError, match="cannot update"):
        update_recurring(db, row_id, monthly_cost=1)


def test_update_recurring_leaves_untouched_columns_alone(db):
    upsert_recurring(
        db, name="Rent", category="housing", cost=750, cycle="monthly", note="lease"
    )
    row_id = list_recurring(db)[0]["id"]
    update_recurring(db, row_id, cost=800)
    row = list_recurring(db)[0]
    assert row["note"] == "lease"
    assert row["active"] == 1


def test_update_recurring_on_a_missing_row_is_false_not_a_crash(db):
    assert update_recurring(db, 999, cost=10) is False


# ── a rename must not double the budget ──────────────────────────────────


def test_renaming_a_recurring_item_then_re_rolling_does_not_double_the_budget(db, make_cfg):
    """The budget rows are keyed by `name` and recurring items are keyed by `id`, so a
    rename left the old month's line behind and the next roll added a second one for the
    same subscription. Reproduced at 24.99 -> 49.98.

    This corrupts the one number the Money tab exists to answer, and it is the harm
    `update_recurring`'s own docstring says keying by id was meant to prevent — it fixed
    the duplicate *recurring* row and left the duplicate *budget* row in place.
    """
    cfg = make_cfg()
    rid = upsert_recurring(db, name="Streaming", cost=24.99, cycle="monthly",
                           category="subscriptions", cfg=cfg)
    roll_month_budgets(db, month="2026-09", cfg=cfg)
    update_recurring(db, rid, name="Streaming Plus")
    roll_month_budgets(db, month="2026-09", cfg=cfg)

    names = sorted(b["name"] for b in list_budget(db, month="2026-09"))
    assert names == ["Streaming Plus"], f"the orphaned line survived: {names}"
    total = summarize_month(db, month="2026-09", today="2026-09-04", cfg=cfg).total_budget
    assert total == 24.99, f"one subscription, {total} of budget"


def test_a_hand_set_budget_line_survives_a_re_roll(db, make_cfg):
    """The reconciliation only removes lines the roll itself created. A number you typed
    is yours — `roll_month_budgets` has never overwritten one and still must not."""
    cfg = make_cfg()
    upsert_recurring(db, name="Streaming", cost=24.99, cycle="monthly",
                     category="subscriptions", cfg=cfg)
    upsert_budget(db, month="2026-09", name="Groceries", category="grocery",
                  amount=400.0, source="manual", cfg=cfg)
    roll_month_budgets(db, month="2026-09", cfg=cfg)
    roll_month_budgets(db, month="2026-09", cfg=cfg)
    rows = {b["name"]: b["amount"] for b in list_budget(db, month="2026-09")}
    assert rows == {"Groceries": 400.0, "Streaming": 24.99}, rows


def test_a_deleted_recurring_item_keeps_the_month_it_was_already_rolled_into(db, make_cfg):
    """A month you already paid for keeps its line. Reconciliation is about a *rename*
    leaving a stale duplicate, not about retroactively rewriting a month's budget — the
    next month's roll simply will not include it."""
    cfg = make_cfg()
    rid = upsert_recurring(db, name="Streaming", cost=24.99, cycle="monthly",
                           category="subscriptions", cfg=cfg)
    roll_month_budgets(db, month="2026-09", cfg=cfg)
    delete_recurring(db, rid)
    names = sorted(b["name"] for b in list_budget(db, month="2026-09"))
    assert names == ["Streaming"], f"a paid month lost its line: {names}"


def test_pending_roll_agrees_with_the_roll_after_a_rename(db, make_cfg):
    """CLAUDE.md requires these two to agree, because the empty state promises what the
    key will deliver. A rename is exactly where they could drift."""
    cfg = make_cfg()
    rid = upsert_recurring(db, name="Streaming", cost=24.99, cycle="monthly",
                           category="subscriptions", cfg=cfg)
    roll_month_budgets(db, month="2026-09", cfg=cfg)
    update_recurring(db, rid, name="Streaming Plus")

    # Nothing is pending, because the rename carried the line with it rather than
    # orphaning it — so there is nothing for a roll to re-add. The number that matters is
    # that both functions say the same thing; a count of 1 here would mean the line was
    # left behind, which is the bug.
    count, total = pending_roll(db, month="2026-09")
    created = roll_month_budgets(db, month="2026-09", cfg=cfg)
    assert (count, created) == (0, 0), f"pending said {count}, roll created {created}"
    assert total == 0.0
    assert [b["name"] for b in list_budget(db, month="2026-09")] == ["Streaming Plus"]


def test_a_rename_leaves_a_hand_set_line_of_the_same_name_alone(db, make_cfg):
    """`source` is the discriminator, not the name. A line you typed called "Streaming"
    is your number for that name; renaming the subscription must not drag it along, or an
    edit to a subscription silently rewrites a budget you set by hand."""
    cfg = make_cfg()
    rid = upsert_recurring(db, name="Streaming", cost=24.99, cycle="monthly",
                           category="subscriptions", cfg=cfg)
    upsert_budget(db, month="2026-09", name="Streaming", category="subscriptions",
                  amount=99.0, source="manual", cfg=cfg)
    # A line under the *new* name too, so the duplicate-drop path is exercised and not
    # just the rename path. Without the source filter on the delete, this is the shape
    # that quietly removes the 99.00 you typed.
    upsert_budget(db, month="2026-09", name="Streaming Plus", category="subscriptions",
                  amount=15.0, source="manual", cfg=cfg)
    update_recurring(db, rid, name="Streaming Plus")
    rows = {b["name"]: (b["amount"], b["source"]) for b in list_budget(db, month="2026-09")}
    assert rows == {
        "Streaming": (99.0, "manual"),
        "Streaming Plus": (15.0, "manual"),
    }, rows


def test_a_rename_onto_a_name_that_already_has_a_line_drops_the_duplicate(db, make_cfg):
    """`budget` is UNIQUE(month, name), so without this the rename's UPDATE would raise
    instead of doubling — a different failure, not a fixed one.

    The month keeps the line that was already there. That follows
    `roll_month_budgets`'s own documented stance — it has never overwritten an existing
    line — and the alternative would let editing one subscription silently restate
    another's number.
    """
    cfg = make_cfg()
    streaming = upsert_recurring(db, name="Streaming", cost=24.99, cycle="monthly",
                                 category="subscriptions", cfg=cfg)
    music = upsert_recurring(db, name="Music", cost=9.99, cycle="monthly",
                             category="subscriptions", cfg=cfg)
    roll_month_budgets(db, month="2026-09", cfg=cfg)
    delete_recurring(db, music)          # its paid month keeps the line
    update_recurring(db, streaming, name="Music")

    rows = {b["name"]: b["amount"] for b in list_budget(db, month="2026-09")}
    assert rows == {"Music": 9.99}, f"expected one line, kept as it was: {rows}"


def test_a_rename_carries_the_line_in_every_month_it_was_rolled_into(db, make_cfg):
    """Not just the current month. A re-roll of any past month would otherwise double it
    there, and `[` walks back through past months."""
    cfg = make_cfg()
    rid = upsert_recurring(db, name="Streaming", cost=24.99, cycle="monthly",
                           category="subscriptions", cfg=cfg)
    for month in ("2026-07", "2026-08", "2026-09"):
        roll_month_budgets(db, month=month, cfg=cfg)
    update_recurring(db, rid, name="Streaming Plus")
    for month in ("2026-07", "2026-08", "2026-09"):
        names = [b["name"] for b in list_budget(db, month=month)]
        assert names == ["Streaming Plus"], f"{month} kept a stale line: {names}"
        assert roll_month_budgets(db, month=month, cfg=cfg) == 0
