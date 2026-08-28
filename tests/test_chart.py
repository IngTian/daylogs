from daybook.tui.chart import braille_line, frame_chart

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
