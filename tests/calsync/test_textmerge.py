"""Tests for the line-level three-way (diff3) text merge.

Covers the git-style behaviors the calendar merge relies on: one-sided edits
taken verbatim, identical edits collapsed, disjoint edits combined, and true
divergences wrapped in ``<<<<<<<``/``=======``/``>>>>>>>`` markers.
"""

from __future__ import annotations

from doxtr_doto.calsync.textmerge import merge_three_way


class TestMergeThreeWay:
    def test_identical_sides_no_conflict(self):
        out = merge_three_way("a\nb", "a\nX", "a\nX")
        assert out.text == "a\nX"
        assert out.conflicted is False

    def test_only_local_changed(self):
        out = merge_three_way("a\nb\nc", "a\nB\nc", "a\nb\nc")
        assert out.text == "a\nB\nc"
        assert out.conflicted is False

    def test_only_remote_changed(self):
        out = merge_three_way("a\nb\nc", "a\nb\nc", "a\nb\nC")
        assert out.text == "a\nb\nC"
        assert out.conflicted is False

    def test_disjoint_line_edits_combine_without_conflict(self):
        out = merge_three_way("l1\nl2\nl3\nl4", "L1\nl2\nl3\nl4", "l1\nl2\nl3\nL4")
        assert out.text == "L1\nl2\nl3\nL4"
        assert out.conflicted is False

    def test_true_divergence_same_line_conflicts(self):
        out = merge_three_way("a\nb\nc", "a\nLOCAL\nc", "a\nREMOTE\nc")
        assert out.conflicted is True
        assert "<<<<<<< local (doto)" in out.text
        assert "=======" in out.text
        assert ">>>>>>> remote (calendar)" in out.text
        assert "LOCAL" in out.text
        assert "REMOTE" in out.text
        # Unchanged context lines are preserved verbatim.
        assert out.text.splitlines()[0] == "a"
        assert out.text.splitlines()[-1] == "c"

    def test_custom_labels(self):
        out = merge_three_way("x", "y", "z", local_label="MINE", remote_label="THEIRS")
        assert "<<<<<<< MINE" in out.text
        assert ">>>>>>> THEIRS" in out.text

    def test_empty_base_equal_sides(self):
        out = merge_three_way("", "same", "same")
        assert out.text == "same"
        assert out.conflicted is False

    def test_empty_base_divergent_sides_conflict(self):
        out = merge_three_way("", "mine", "theirs")
        assert out.conflicted is True
        assert "mine" in out.text and "theirs" in out.text

    def test_middle_insertion_one_side(self):
        # Local inserts a line in the middle; remote unchanged -> take local.
        out = merge_three_way("a\nc", "a\nb\nc", "a\nc")
        assert out.text == "a\nb\nc"
        assert out.conflicted is False

    def test_deletion_one_side(self):
        # Remote deletes a line; local unchanged -> take remote (deletion).
        out = merge_three_way("a\nb\nc", "a\nb\nc", "a\nc")
        assert out.text == "a\nc"
        assert out.conflicted is False

    def test_trailing_newline_is_not_a_conflict(self):
        # A trailing-newline-only difference must never surface as a conflict.
        # (The fast path returns the local text verbatim, trailing newline and
        # all; the point is simply that it is not flagged as a divergence.)
        out = merge_three_way("a\nb", "a\nb\n", "a\nb")
        assert out.conflicted is False
        assert out.text.rstrip("\n") == "a\nb"
