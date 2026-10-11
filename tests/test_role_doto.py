"""Tests for the :doto: role."""

from __future__ import annotations


class TestDotoRole:
    """Test the :doto: role for cross-referencing tasks."""

    def test_basic_doto_reference(self, doto_srcdir, make_app, sample_tasks_rst):
        """Test basic task reference using :doto: role."""
        ref_rst = doto_srcdir / "refs.rst"
        ref_rst.write_text("""
Task References
===============

See :doto:`TASK-001` for authentication work.
""")

        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   refs\n")

        app = make_app(srcdir=doto_srcdir)
        app.build()

        # Check that build succeeded
        assert app.statuscode == 0

    def test_doto_reference_with_custom_text(self, doto_srcdir, make_app, sample_tasks_rst):
        """Test task reference with custom display text."""
        ref_rst = doto_srcdir / "custom_refs.rst"
        ref_rst.write_text("""
Custom References
=================

Check the :doto:`auth task <TASK-001>` for details.
""")

        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   custom_refs\n")

        app = make_app(srcdir=doto_srcdir)
        app.build()

        assert app.statuscode == 0

    def test_multiple_references(self, doto_srcdir, make_app, sample_tasks_rst):
        """Test multiple task references in the same document."""
        ref_rst = doto_srcdir / "multi_refs.rst"
        ref_rst.write_text("""
Multiple References
===================

Tasks:

- :doto:`TASK-001` - Authentication
- :doto:`TASK-002` - Export feature
- :doto:`TASK-003` - Database fix

See :doto:`TASK-001` and :doto:`TASK-002` for high priority items.
""")

        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   multi_refs\n")

        app = make_app(srcdir=doto_srcdir)
        app.build()

        assert app.statuscode == 0

    def test_nonexistent_task_reference(self, doto_srcdir, make_app, sample_tasks_rst):
        """Test reference to non-existent task."""
        ref_rst = doto_srcdir / "bad_refs.rst"
        ref_rst.write_text("""
Bad References
==============

See :doto:`NONEXISTENT-TASK` for something.
""")

        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   bad_refs\n")

        app = make_app(srcdir=doto_srcdir)
        # Build should still succeed, but may emit warnings
        app.build()

        # Build completes but may have warnings for missing ref
        assert app.statuscode == 0


class TestDotoRoleFunctions:
    """Test the doto role helper functions."""

    def test_doto_role_returns_pending_xref(self):
        """Test that doto_role returns a pending_xref node."""
        from sphinx.addnodes import pending_xref

        from doxtr_doto.roles import doto_role

        # Create a minimal mock inliner
        class MockInliner:
            document = None

        inliner = MockInliner()

        nodes_list, messages = doto_role(
            name="doto",
            rawtext=":doto:`TASK-001`",
            text="TASK-001",
            lineno=1,
            inliner=inliner,
        )

        assert len(nodes_list) == 1
        assert isinstance(nodes_list[0], pending_xref)
        # Domain-based role uses reftype="task" and refdomain="doto"
        assert nodes_list[0]["refdomain"] == "doto"
        assert nodes_list[0]["reftype"] == "task"
        assert nodes_list[0]["reftarget"] == "TASK-001"
        assert nodes_list[0]["doto_target"] == "TASK-001"

    def test_doto_role_with_explicit_title(self):
        """Test doto_role with explicit title syntax."""
        from sphinx.addnodes import pending_xref

        from doxtr_doto.roles import doto_role

        class MockInliner:
            document = None

        inliner = MockInliner()

        nodes_list, messages = doto_role(
            name="doto",
            rawtext=":doto:`Custom Title <TASK-001>`",
            text="Custom Title <TASK-001>",
            lineno=1,
            inliner=inliner,
        )

        assert len(nodes_list) == 1
        node = nodes_list[0]
        assert isinstance(node, pending_xref)
        assert node["reftarget"] == "TASK-001"
        assert node["refexplicit"] is True
        # The inner literal should contain the custom title
        inner = node.children[0]
        assert inner.astext() == "Custom Title"

    def test_doto_role_classes(self):
        """Test that doto_role adds correct CSS classes."""
        from doxtr_doto.roles import doto_role

        class MockInliner:
            document = None

        inliner = MockInliner()

        nodes_list, _ = doto_role(
            name="doto",
            rawtext=":doto:`TASK-001`",
            text="TASK-001",
            lineno=1,
            inliner=inliner,
        )

        node = nodes_list[0]
        assert "doto-ref" in node["classes"]

        # Inner node should have xref and doto classes
        inner = node.children[0]
        assert "xref" in inner["classes"]
        assert "doto" in inner["classes"]
