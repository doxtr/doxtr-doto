"""RST write-back must not crash on files mixing doto directives.

Regression tests for a crash during bidirectional sync RST write-back:

    doto: Error SyncAction.UPDATEing task <id> in <docname>:
    'Values' object has no attribute 'env'

Root cause: ``_parse_rst_for_directives`` parses RST with a STANDALONE
docutils ``Parser`` whose settings have no Sphinx ``env``. During a real
build the real ``doto-list`` / ``doto-summary`` directives
(``SphinxDirective`` subclasses whose ``run()`` reads ``self.env``) are
registered globally. Standalone parsing then invoked them and raised
``AttributeError: 'Values' object has no attribute 'env'``.

The fix registers env-free parser stubs for ``doto``, ``doto-list`` and
``doto-summary`` before every standalone parse. These tests register the
REAL list/summary directives globally first to reproduce the build-time
state, then assert the write-back helpers parse without raising.
"""

from __future__ import annotations

import pytest
from docutils.parsers.rst import directives

from doxtr_doto.directives.doto_list import DotoListDirective
from doxtr_doto.directives.doto_summary import DotoSummaryDirective
from doxtr_doto.sync.rst_writer import (
    _parse_rst_for_directives,
    insert_id_into_directive_at_line,
    update_directive_in_content,
)


@pytest.fixture
def real_list_summary_registered():
    """Register the REAL env-dependent list/summary directives globally.

    This mirrors the state during a real Sphinx build, which is what
    triggered the original crash. Without the fix, standalone parsing would
    invoke these directives' ``run()`` and raise on ``self.env``.
    """
    directives.register_directive("doto-list", DotoListDirective)
    directives.register_directive("doto-summary", DotoSummaryDirective)
    yield


class TestMixedDirectivesParsing:
    """Parsing must succeed when list/summary directives are present."""

    def test_parse_with_doto_list_does_not_raise(self, real_list_summary_registered):
        """A file mixing ``.. doto::`` and ``.. doto-list::`` parses cleanly."""
        content = (
            ".. doto:: Task\n"
            "   :id: tid-L358\n"
            "   :status: open\n"
            "\n"
            ".. doto-list::\n"
            "   :status: open\n"
        )
        result = _parse_rst_for_directives(content)
        ids = [d["options"].get("id") for d in result]
        assert ids == ["tid-L358"]

    def test_parse_with_doto_summary_does_not_raise(self, real_list_summary_registered):
        """A file mixing ``.. doto::`` and ``.. doto-summary::`` parses."""
        content = ".. doto:: Task\n   :id: tid-L999\n\n.. doto-summary::\n   :group-by: status\n"
        result = _parse_rst_for_directives(content)
        ids = [d["options"].get("id") for d in result]
        assert ids == ["tid-L999"]

    def test_parse_with_both_list_and_summary(self, real_list_summary_registered):
        """Both list and summary present at once still parses the doto."""
        content = (
            ".. doto-summary::\n"
            "   :group-by: status\n"
            "\n"
            ".. doto:: Task\n"
            "   :id: tid-L1\n"
            "\n"
            ".. doto-list::\n"
            "   :status: open\n"
        )
        result = _parse_rst_for_directives(content)
        ids = [d["options"].get("id") for d in result]
        assert ids == ["tid-L1"]


class TestMixedDirectivesUpdate:
    """update_directive_in_content works amid list/summary directives."""

    def test_update_field_with_list_and_summary_present(self, real_list_summary_registered):
        """A doto field updates even with list/summary in the same file."""
        content = (
            ".. doto:: Task\n"
            "   :id: tid-L358\n"
            "   :status: open\n"
            "\n"
            ".. doto-list::\n"
            "   :status: open\n"
            "\n"
            ".. doto-summary::\n"
            "   :group-by: status\n"
        )
        updated = update_directive_in_content(content, "tid-L358", {"status": "done"})
        assert ":status: done" in updated
        assert ":status: open" not in updated.split(".. doto-list::")[0]
        # The list/summary directives are left intact.
        assert ".. doto-list::" in updated
        assert ".. doto-summary::" in updated


class TestMixedDirectivesInsertId:
    """insert_id_into_directive_at_line works amid list directives."""

    def test_insert_id_into_bare_directive_with_list_present(self, real_list_summary_registered):
        """A bare ``.. doto::`` gets its id even when a list is present.

        This is the exact write-back scenario that triggered the bug.
        """
        content = ".. doto:: Bare task\n\n.. doto-list::\n   :status: open\n"
        result = insert_id_into_directive_at_line(content, 1, "noter-L358")

        lines = result.split("\n")
        assert lines[0] == ".. doto:: Bare task"
        assert lines[1] == "   :id: noter-L358"
        # The list directive is untouched (still a single doto directive).
        assert result.count(".. doto::") == 1
        assert ".. doto-list::" in result


class TestDotoRoleParsing:
    """The ``:doto:`` role must parse env-free during standalone parsing.

    The role only builds a ``pending_xref`` node at parse time; env is read
    later in ``resolve_doto_xref`` during the resolve phase. So no role stub
    is needed, but we guard that parsing content with a role never raises.
    """

    def test_content_with_doto_role_parses(self, real_list_summary_registered):
        """Content containing a ``:doto:`` role parses without raising."""
        from docutils.parsers.rst import roles

        from doxtr_doto.roles.doto_ref import doto_role

        roles.register_canonical_role("doto", doto_role)

        content = ".. doto:: Task\n   :id: tid-L2\n\nSee :doto:`OTHER-1` for context.\n"
        result = _parse_rst_for_directives(content)
        ids = [d["options"].get("id") for d in result]
        assert ids == ["tid-L2"]


class TestGloballyRegisteredEnvDirectives:
    """Write-back must survive ANY globally-registered env-touching directive.

    The earlier fix only stubbed ``doto``/``doto-list``/``doto-summary``. But a
    real Sphinx build registers many other directives globally (e.g.
    ``toctree``), several of which read ``self.env`` in ``run()``. When such a
    directive appeared in a file being updated, the standalone parse invoked it
    and still raised ``'Values' object has no attribute 'env'``.

    The parse now scopes the global directive/role registries to just the
    env-free doto stubs, so any other directive resolves as "unknown" (a
    harmless system_message) instead of running env-dependent code.
    """

    @pytest.fixture
    def env_touching_directive(self):
        """Register a directive whose ``run()`` reads ``self.env`` globally.

        Mirrors a ``SphinxDirective`` (e.g. ``toctree``) that would raise when
        executed by the standalone, env-less parser. Restores the previous
        ``toctree`` registration afterwards.
        """
        from docutils.parsers.rst import Directive

        class EnvTouchingDirective(Directive):
            has_content = True
            optional_arguments = 1
            final_argument_whitespace = True
            option_spec = {"maxdepth": directives.unchanged}

            def run(self):
                # Reads env exactly like a SphinxDirective would; raises
                # AttributeError under the standalone parser.
                _ = self.state.document.settings.env
                return []

        saved = directives._directives.get("toctree")
        directives.register_directive("toctree", EnvTouchingDirective)
        yield
        if saved is not None:
            directives.register_directive("toctree", saved)
        else:
            directives._directives.pop("toctree", None)

    def test_update_with_env_directive_does_not_raise(self, env_touching_directive):
        """UPDATE succeeds when an env-touching directive is in the file."""
        content = (
            "Title\n"
            "=====\n"
            "\n"
            ".. toctree::\n"
            "   :maxdepth: 2\n"
            "\n"
            "   somedoc\n"
            "\n"
            ".. doto:: Task\n"
            "   :id: noter-L379\n"
            "   :status: todo\n"
        )
        result = update_directive_in_content(content, "noter-L379", {"status": "done"})
        assert ":status: done" in result
        # The env-touching directive is left untouched.
        assert ".. toctree::" in result

    def test_parse_with_env_directive_does_not_raise(self, env_touching_directive):
        """Parsing a file with an env-touching directive returns doto info."""
        content = ".. toctree::\n   :maxdepth: 2\n\n   somedoc\n\n.. doto:: Task\n   :id: tid-L1\n"
        result = _parse_rst_for_directives(content)
        ids = [d["options"].get("id") for d in result]
        assert ids == ["tid-L1"]

    def test_global_registry_restored_after_parse(self, env_touching_directive):
        """The global directive registry is restored after a parse."""
        before = directives._directives.get("toctree")
        _parse_rst_for_directives(".. doto:: Task\n   :id: tid-L1\n")
        after = directives._directives.get("toctree")
        assert before is after
        assert before is not None
