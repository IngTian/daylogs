import pytest
from helpers import all_expenses

from daylogs.money import (
    MoneyError,
    add_expense,
    delete_expense,
    update_expense,
)


def _add(db, **kw):
    base = dict(amount=12.40, description="lunch", category="restaurant", date="2026-08-27")
    return add_expense(db, **{**base, **kw})


def test_add_and_list(db):
    eid = _add(db)
    rows = all_expenses(db)
    assert len(rows) == 1
    assert rows[0]["id"] == eid
    assert rows[0]["amount"] == 12.40
    assert rows[0]["category"] == "restaurant"
    assert rows[0]["created_at"] > 0


def test_list_sorted_newest_first(db):
    _add(db, date="2026-08-01", description="first")
    _add(db, date="2026-08-27", description="last")
    assert [r["description"] for r in all_expenses(db)] == ["last", "first"]


def test_negative_amount_allowed_as_refund(db):
    eid = _add(db, amount=-24.99, description="returned shoes")
    assert all_expenses(db)[0]["id"] == eid


def test_zero_amount_rejected(db):
    with pytest.raises(MoneyError, match="non-zero"):
        _add(db, amount=0)


def test_empty_description_rejected(db):
    with pytest.raises(MoneyError, match="description"):
        _add(db, description="   ")


def test_unknown_category_rejected(db):
    with pytest.raises(MoneyError, match="category"):
        _add(db, category="nonexistent")


def test_bad_date_rejected(db):
    with pytest.raises(MoneyError):
        _add(db, date="27-08-2026")
    with pytest.raises(MoneyError):
        _add(db, date="2026-02-30")


def test_update_changes_only_given_fields(db):
    eid = _add(db)
    assert update_expense(db, eid, amount=15.0, category="grocery") is True
    row = all_expenses(db)[0]
    assert (row["amount"], row["category"], row["description"]) == (15.0, "grocery", "lunch")


def test_update_validates_category_and_date(db):
    eid = _add(db)
    with pytest.raises(MoneyError):
        update_expense(db, eid, category="nope")
    with pytest.raises(MoneyError):
        update_expense(db, eid, date="nope")


def test_update_rejects_unknown_field(db):
    eid = _add(db)
    with pytest.raises(MoneyError):
        update_expense(db, eid, bogus=1)


def test_update_unknown_id_returns_false(db):
    assert update_expense(db, 999, amount=1.0) is False


def test_delete_returns_row_for_undo(db):
    eid = _add(db)
    row = delete_expense(db, eid)
    assert row["description"] == "lunch"
    assert all_expenses(db) == []
    assert delete_expense(db, eid) is None

