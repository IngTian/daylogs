from daybook.markup import to_markdown


def test_num_becomes_bold():
    assert to_markdown("spent <num>$23.04</num> today") == "spent **$23.04** today"


def test_win_becomes_bold():
    assert to_markdown("<win>clean staircase</win>") == "**clean staircase**"


def test_warn_gets_a_glyph_not_a_colour():
    """Markdown has no colour spans, and a warning encoded in colour alone was
    never a good idea."""
    assert to_markdown("<warn>over by 47</warn>") == "**\u26a0 over by 47**"


def test_multiple_tags_all_converted():
    assert to_markdown("<num>1</num> and <num>2</num>") == "**1** and **2**"


def test_tag_spanning_a_newline():
    assert to_markdown("<warn>over\nbudget</warn>") == "**\u26a0 over\nbudget**"


def test_plain_markdown_passes_through_untouched():
    src = "## Body\n\nHeld **steady** at 78.2 kg.\n\n- one\n- two\n"
    assert to_markdown(src) == src


def test_headings_are_preserved_for_the_markdown_widget():
    assert to_markdown("## Money") == "## Money"


def test_unknown_tags_are_left_alone():
    assert "<repo>" in to_markdown("<repo>daybook</repo>")


def test_unmatched_tag_does_not_crash():
    assert to_markdown("<num>oops") == "<num>oops"


def test_empty_tag_is_dropped():
    assert to_markdown("a <num></num> b") == "a  b"


def test_empty_string():
    assert to_markdown("") == ""

