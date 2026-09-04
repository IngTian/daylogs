from daylogs.tui.chart import braille_line, frame_chart

BLANK = "⠀"


def test_dimensions_are_exact():
    rows = braille_line([1, 2, 3, 4], width=20, height=6)
    assert len(rows) == 6
    assert all(len(r) == 20 for r in rows)


def test_every_char_is_braille():
    for row in braille_line([1, 5, 2, 8], width=16, height=4):
        for ch in row:
            assert 0x2800 <= ord(ch) <= 0x28FF


def test_empty_series_gives_blank_rows_not_a_crash():
    rows = braille_line([], width=10, height=3)
    assert len(rows) == 3
    assert set("".join(rows)) == {BLANK}


def test_zero_width_or_height_does_not_crash():
    assert braille_line([1, 2], width=0, height=3) == ["", "", ""]
    assert braille_line([1, 2], width=10, height=0) == []


def test_single_point_plots_something():
    rows = braille_line([5.0], width=10, height=3)
    assert "".join(rows).strip(BLANK)


def test_flat_series_does_not_divide_by_zero():
    rows = braille_line([4.0, 4.0, 4.0], width=12, height=4)
    assert len(rows) == 4
    assert "".join(rows).strip(BLANK)


def test_negative_values_are_handled():
    rows = braille_line([-5.0, 0.0, 5.0], width=12, height=4)
    assert "".join(rows).strip(BLANK)


def test_rising_series_ends_higher_than_it_starts():
    """Row 0 is the top, so a rising series must put ink nearer the top on the
    right than on the left."""
    rows = braille_line(list(range(20)), width=20, height=6)
    left = [i for i, r in enumerate(rows) if r[0] != BLANK]
    right = [i for i, r in enumerate(rows) if r[-1] != BLANK]
    assert min(right) < min(left)


def test_falling_series_is_the_mirror():
    rows = braille_line(list(range(20, 0, -1)), width=20, height=6)
    left = [i for i, r in enumerate(rows) if r[0] != BLANK]
    right = [i for i, r in enumerate(rows) if r[-1] != BLANK]
    assert min(left) < min(right)


def test_a_full_ramp_spans_nearly_every_row():
    height = 8
    rows = braille_line(list(range(64)), width=32, height=height)
    occupied = {i for i, r in enumerate(rows) if r.strip(BLANK)}
    assert len(occupied) >= height - 1


def test_frame_has_y_labels_axis_and_x_labels():
    out = frame_chart([1, 2, 3], width=20, height=4, x_labels=("Jan", "Jul"), unit="kg")
    assert len(out) == 6
    assert "kg" in out[0]
    assert "│" in out[0]
    assert "└" in out[-2]
    assert "Jan" in out[-1] and "Jul" in out[-1]


def test_frame_labels_the_real_extent_of_the_data():
    out = frame_chart([79.9, 84.8, 80.1], width=20, height=4)
    text = "\n".join(out)
    assert "84.8" in text
    assert "79.9" in text


def test_frame_empty_series_renders_a_message_not_a_crash():
    out = frame_chart([], width=20, height=4)
    assert len(out) >= 1
    assert "no data" in "\n".join(out).lower()


def test_frame_rows_are_uniform_width():
    out = frame_chart([1, 2, 3], width=24, height=5, x_labels=("a", "b"))
    assert len({len(r) for r in out}) == 1


def test_frame_without_x_labels_still_uniform():
    out = frame_chart([1, 2, 3], width=24, height=5)
    assert len({len(r) for r in out}) == 1




# ── positions: real time on the x-axis ──────────────────────────────────────


def test_positions_put_clustered_points_at_the_right_edge():
    """Index spacing spread two adjacent readings across the whole width, drawing
    a month-long climb that never happened."""
    rows = braille_line([80.0, 81.0], width=20, height=4, positions=[0.97, 1.0])
    left_half = [r[:10] for r in rows]
    assert "".join(left_half).strip(BLANK) == ""
    assert "".join(r[-2:] for r in rows).strip(BLANK)


def test_positions_are_clamped_to_the_axis():
    rows = braille_line([1.0, 2.0], width=10, height=3, positions=[-5.0, 9.0])
    assert all(len(r) == 10 for r in rows)
    assert "".join(rows).strip(BLANK)


def test_positions_shorter_than_values_falls_back_to_index():
    rows = braille_line([1.0, 2.0, 3.0], width=12, height=3, positions=[0.0])
    assert "".join(rows).strip(BLANK)


def test_without_positions_index_spacing_is_unchanged():
    a = braille_line([1.0, 5.0, 2.0], width=16, height=4)
    b = braille_line([1.0, 5.0, 2.0], width=16, height=4, positions=None)
    assert a == b


def test_frame_chart_forwards_positions():
    clustered = frame_chart([80.0, 81.0], width=24, height=4, positions=[0.96, 1.0])
    spread = frame_chart([80.0, 81.0], width=24, height=4)
    assert clustered != spread


def test_last_x_label_reaches_the_right_edge():
    """Dividing by the label count parked the final tick two-thirds along, so the
    axis looked like it stopped early."""
    out = frame_chart([1, 2, 3], width=40, height=4, x_labels=("Jul 30", "Aug 13", "Aug 28"))
    label_row = out[-1]
    assert label_row.rstrip().endswith("Aug 28")
    assert label_row.index("Jul 30") < label_row.index("Aug 13") < label_row.index("Aug 28")


# ── an explicit extent, and a zero reference ─────────────────────────────
# A weight series means something relative to itself, so it fits its own min-max. A
# calorie series does not: `net` is signed, and a chart that cannot show where zero
# falls cannot tell a deficit from a surplus.


def test_an_explicit_extent_overrides_the_series_own_range():
    """Two charts drawn on the same axis have to be comparable, which they are not
    when each fits itself."""
    fitted = braille_line([4.0, 5.0], width=8, height=4)
    forced = braille_line([4.0, 5.0], width=8, height=4, low=0.0, high=10.0)
    assert fitted != forced


def test_values_outside_an_explicit_extent_are_clipped_not_crashed():
    rows = braille_line([-50.0, 500.0], width=8, height=4, low=0.0, high=10.0)
    assert len(rows) == 4 and all(len(r) == 8 for r in rows)


def test_include_zero_puts_zero_at_the_top_of_an_all_deficit_chart():
    """The common case: every day under maintenance. Zero is the ceiling, so the top
    label is what carries it and no mid-chart rule is needed."""
    rows = frame_chart([-500.0, -900.0, -300.0], width=20, height=5, include_zero=True)
    assert rows[0].split("│")[0].strip() == "0", f"top label is not zero: {rows[0]!r}"
    assert "-900" in rows[4], f"bottom label is not the deepest deficit: {rows[4]!r}"


def test_include_zero_puts_zero_at_the_bottom_of_an_all_surplus_chart():
    rows = frame_chart([500.0, 900.0], width=20, height=5, include_zero=True)
    assert rows[4].split("│")[0].strip() == "0", f"bottom label is not zero: {rows[4]!r}"
    assert "900" in rows[0]


def test_a_series_that_straddles_zero_gets_a_marked_zero_row():
    """Only here is a rule needed, and it has to be on the axis rather than drawn in
    braille — a dotted line among data dots would be indistinguishable from data."""
    rows = frame_chart([-600.0, 600.0], width=20, height=5, include_zero=True)
    marked = [r for r in rows if "┼" in r]
    assert len(marked) == 1, f"expected exactly one zero row: {rows}"
    assert marked[0].split("┼")[0].strip() == "0", f"zero row is unlabelled: {marked[0]!r}"
    assert marked[0] is not rows[0] and marked[0] is not rows[4]


def test_the_zero_row_sits_between_the_extremes():
    rows = frame_chart([-600.0, 600.0], width=20, height=7, include_zero=True)
    index = next(i for i, r in enumerate(rows) if "┼" in r)
    assert 0 < index < 6, f"the zero row is at an extreme: {index}"


def test_without_include_zero_nothing_is_marked_and_the_fit_is_unchanged():
    """Weight must keep its own min-max fit: anchored at zero a 70-75 kg series is a
    flat line at the top of the panel."""
    plain = frame_chart([70.0, 75.0], width=20, height=5)
    assert not any("┼" in r for r in plain)
    assert "75" in plain[0] and "70" in plain[4]


def test_include_zero_does_not_mark_a_row_when_zero_is_an_extreme():
    """A `┼` on the top or bottom row would duplicate what the extent label says."""
    rows = frame_chart([0.0, 900.0], width=20, height=5, include_zero=True)
    assert not any("┼" in r for r in rows)


def test_a_zero_that_rounds_onto_an_extreme_row_is_not_marked():
    """The harder case, and the one the row guard actually exists for: zero is strictly
    inside the extent, but so close to an end that it lands on the first or last row —
    whose label is the extent, not zero. Marking it would claim zero sits at 1,000.
    """
    for values in ([-1000.0, 1.0], [-1.0, 1000.0]):
        rows = frame_chart(values, width=20, height=5, include_zero=True)
        marked = [r for r in rows if "┼" in r]
        assert not marked, f"{values} marked a row whose label is the extent: {rows}"


def test_frame_rows_stay_uniform_width_with_a_zero_row():
    rows = frame_chart([-600.0, 600.0], width=20, height=5, include_zero=True,
                       x_labels=("Aug 01", "Aug 30"))
    assert len({len(r) for r in rows}) == 1, f"ragged rows: {[len(r) for r in rows]}"


def test_a_flat_zero_series_does_not_divide_by_zero():
    rows = frame_chart([0.0, 0.0], width=12, height=4, include_zero=True)
    assert len(rows) == 6


# ── the axis describes the window, not just the drawn points ─────────────


def test_an_explicit_extent_widens_the_labels_beyond_the_plotted_points():
    """The weight chart draws one point per day but the window may hold several readings
    per day, so the extent has to come from the window. Otherwise the labels claim a range
    the window does not have — the same defect as v1 plotting the last 30 entries while
    labelling as though it described the requested window.
    """
    rows = frame_chart([81.85, 81.75], width=20, height=5, low=80.65, high=82.65)
    assert "82.65" in rows[0], f"the top label is not the window's max: {rows[0]!r}"
    assert "80.65" in rows[4], f"the bottom label is not the window's min: {rows[4]!r}"


def test_a_widened_extent_leaves_the_line_off_the_panel_edges():
    """The consequence, and it is the honest one: nothing plotted reaches the top row,
    because the reading that defines it is not one of the drawn points."""
    tight = frame_chart([81.85, 81.75], width=20, height=6)
    wide = frame_chart([81.85, 81.75], width=20, height=6, low=80.65, high=82.65)
    plot = lambda rows: [r.split("│", 1)[1] for r in rows if "│" in r]  # noqa: E731
    assert plot(tight)[0].strip("⠀"), "the tight fit should touch the top row"
    assert not plot(wide)[0].strip("⠀"), "a widened extent must not touch the top row"


def test_an_explicit_extent_is_ignored_when_absent():
    assert frame_chart([81.85, 81.75], width=20, height=5) == frame_chart(
        [81.85, 81.75], width=20, height=5, low=None, high=None
    )
