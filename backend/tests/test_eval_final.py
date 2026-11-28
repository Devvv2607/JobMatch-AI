"""The final-run plumbing (app/eval/final.py): block filling and section mapping."""

from app.eval.final import demote, fill, sections

PAGE = """# Title

<!-- BEGIN:status -->
_pending_
<!-- END:status -->

Hand-written text stays.

<!-- BEGIN:metrics -->
_pending metrics_
<!-- END:metrics -->

<!-- BEGIN:untouched -->
keep me
<!-- END:untouched -->
"""


def test_fill_replaces_only_named_blocks_and_is_repeatable() -> None:
    text, filled = fill(PAGE, {"status": "Final run.", "metrics": "| a | b |"})
    assert filled == ["status", "metrics"]
    assert "Final run." in text and "| a | b |" in text
    assert "_pending_" not in text and "Hand-written text stays." in text
    assert "keep me" in text
    again, _ = fill(text, {"status": "Second run."})
    assert "Second run." in again and "Final run." not in again
    assert again.count("<!-- BEGIN:status -->") == 1


def test_sections_split_on_level_two_headings_and_demote() -> None:
    md = "# R\n\n## Labels\nx\n\n## Key results\n- y\n### sub\nz\n"
    found = sections(md)
    assert list(found) == ["## Labels", "## Key results"]
    assert found["## Key results"].splitlines() == ["## Key results", "- y", "### sub", "z"]
    assert demote(found["## Key results"]).splitlines()[0] == "### Key results"
    assert "#### sub" in demote(found["## Key results"])
