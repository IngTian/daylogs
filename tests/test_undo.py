from daylogs.undo import UndoStack


def test_push_pop_is_lifo():
    s = UndoStack()
    s.push("weight", {"id": 1})
    s.push("food", {"id": 2})
    assert s.pop() == ("food", {"id": 2})
    assert s.pop() == ("weight", {"id": 1})
    assert s.pop() is None


def test_ring_buffer_drops_oldest():
    s = UndoStack(limit=2)
    for i in range(5):
        s.push("weight", {"id": i})
    # Asserted by draining rather than by len(): `__len__` existed only to be
    # asserted, so it was deleted with the rest of the dead code. The bound it
    # described is real, and popping proves it more directly.
    assert s.pop()[1]["id"] == 4
    assert s.pop()[1]["id"] == 3
    assert s.pop() is None


def test_push_copies_the_row_so_later_mutation_does_not_leak():
    s = UndoStack()
    row = {"id": 1, "kg": 78.2}
    s.push("weight", row)
    row["kg"] = 99.9
    assert s.pop()[1]["kg"] == 78.2

