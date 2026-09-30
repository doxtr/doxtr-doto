"""Tests for validation edge cases with custom statuses/priorities."""

from __future__ import annotations

import pytest


@pytest.fixture
def validation_build(tmp_path):
    """Helper fixture for validation tests with custom config."""
    def _build(rst_content: str, conf_content: str) -> tuple[int, str]:
        """
        Build with custom config and return (status_code, warnings).
        
        Args:
            rst_content: The body of tasks.rst.
            conf_content: Full conf.py content.
            
        Returns:
            Tuple of (status_code, warning_output).
        """
        src = tmp_path / "src"
        src.mkdir()
        out = tmp_path / "out"

        (src / "conf.py").write_text(conf_content)
        (src / "index.rst").write_text(
            "Test\n====\n\n"
            ".. toctree::\n\n"
            "   tasks\n"
        )
        (src / "tasks.rst").write_text(
            "Tasks\n=====\n\n" + rst_content
        )

        from io import StringIO
        from sphinx.application import Sphinx
        
        warning_stream = StringIO()
        
        try:
            app = Sphinx(
                srcdir=str(src),
                confdir=str(src),
                outdir=str(out),
                doctreedir=str(tmp_path / ".doctrees"),
                buildername="html",
                warning=warning_stream,
            )
            app.build()
            return app.statuscode, warning_stream.getvalue()
        except Exception as e:
            return 1, str(e)

    return _build


class TestCustomStatuses:
    """Tests for custom status validation."""
    
    def test_custom_statuses_accepted(self, validation_build):
        """Custom statuses in config should be accepted."""
        status_code, warnings = validation_build(
            rst_content='''
.. doto:: Custom status task
   :id: TASK-001
   :status: review
''',
            conf_content='''
extensions = ['doxtr_doto']
master_doc = 'index'
doto_statuses = ['todo', 'doing', 'review', 'done']
doto_default_status = 'todo'
''',
        )
        
        # Should build without errors
        assert status_code == 0
        assert 'invalid' not in warnings.lower()
    
    def test_default_statuses_work(self, validation_build):
        """Default statuses should work without custom config."""
        status_code, warnings = validation_build(
            rst_content='''
.. doto:: Open task
   :id: TASK-001
   :status: open

.. doto:: In progress task
   :id: TASK-002
   :status: in-progress

.. doto:: Blocked task
   :id: TASK-003
   :status: blocked

.. doto:: Done task
   :id: TASK-004
   :status: done
''',
            conf_content='''
extensions = ['doxtr_doto']
master_doc = 'index'
''',
        )
        
        assert status_code == 0


class TestCustomPriorities:
    """Tests for custom priority validation."""
    
    def test_custom_priorities_accepted(self, validation_build):
        """Custom priorities in config should be accepted."""
        status_code, warnings = validation_build(
            rst_content='''
.. doto:: Custom priority task
   :id: TASK-001
   :priority: p0
''',
            conf_content='''
extensions = ['doxtr_doto']
master_doc = 'index'
doto_priorities = ['p0', 'p1', 'p2', 'p3']
doto_default_priority = 'p2'
''',
        )
        
        assert status_code == 0
        assert 'invalid' not in warnings.lower()
    
    def test_default_priorities_work(self, validation_build):
        """Default priorities should work without custom config."""
        status_code, warnings = validation_build(
            rst_content='''
.. doto:: Low priority
   :id: TASK-001
   :priority: low

.. doto:: Medium priority
   :id: TASK-002
   :priority: medium

.. doto:: High priority
   :id: TASK-003
   :priority: high

.. doto:: Critical priority
   :id: TASK-004
   :priority: critical
''',
            conf_content='''
extensions = ['doxtr_doto']
master_doc = 'index'
''',
        )
        
        assert status_code == 0


class TestRequiredFields:
    """Tests for required field validation."""
    
    def test_required_field_provided_succeeds(self, validation_build):
        """Task with required field should succeed."""
        status_code, warnings = validation_build(
            rst_content='''
.. doto:: Has assignee
   :id: TASK-001
   :assignee: alice
''',
            conf_content='''
extensions = ['doxtr_doto']
master_doc = 'index'
doto_required_fields = ['assignee']
''',
        )
        
        assert status_code == 0
    
    def test_multiple_required_fields_all_provided(self, validation_build):
        """Task with all required fields should succeed."""
        status_code, warnings = validation_build(
            rst_content='''
.. doto:: Full task
   :id: TASK-001
   :assignee: alice
   :priority: high
   :due: 2026-12-31
''',
            conf_content='''
extensions = ['doxtr_doto']
master_doc = 'index'
doto_required_fields = ['assignee', 'due']
''',
        )
        
        assert status_code == 0


class TestIdValidation:
    """Tests for task ID validation."""
    
    def test_task_with_id_succeeds(self, validation_build):
        """Task with valid ID should succeed."""
        status_code, warnings = validation_build(
            rst_content='''
.. doto:: Valid task
   :id: TASK-001
''',
            conf_content='''
extensions = ['doxtr_doto']
master_doc = 'index'
''',
        )
        
        assert status_code == 0
    
    def test_custom_id_prefix_works(self, validation_build):
        """Custom ID prefix should work."""
        status_code, warnings = validation_build(
            rst_content='''
.. doto:: Custom prefix task
   :id: PROJ-001
''',
            conf_content='''
extensions = ['doxtr_doto']
master_doc = 'index'
doto_id_prefix = 'PROJ'
''',
        )
        
        assert status_code == 0


class TestDueDateValidation:
    """Tests for due date validation."""
    
    def test_valid_iso_date(self, validation_build):
        """Valid ISO date should be accepted."""
        status_code, warnings = validation_build(
            rst_content='''
.. doto:: Future task
   :id: TASK-001
   :due: 2026-12-31
''',
            conf_content='''
extensions = ['doxtr_doto']
master_doc = 'index'
''',
        )
        
        assert status_code == 0
    
    def test_relative_date_formats(self, validation_build):
        """Relative date formats should work."""
        status_code, warnings = validation_build(
            rst_content='''
.. doto:: Tomorrow task
   :id: TASK-001
   :due: +1d
''',
            conf_content='''
extensions = ['doxtr_doto']
master_doc = 'index'
''',
        )
        
        # Relative dates are parsed during sync, build should not error
        assert status_code == 0


class TestTagsValidation:
    """Tests for tags field validation."""
    
    def test_single_tag(self, validation_build):
        """Single tag should work."""
        status_code, warnings = validation_build(
            rst_content='''
.. doto:: Single tag task
   :id: TASK-001
   :tags: feature
''',
            conf_content='''
extensions = ['doxtr_doto']
master_doc = 'index'
''',
        )
        
        assert status_code == 0
    
    def test_multiple_tags(self, validation_build):
        """Multiple tags should work."""
        status_code, warnings = validation_build(
            rst_content='''
.. doto:: Multi tag task
   :id: TASK-001
   :tags: feature, backend, urgent
''',
            conf_content='''
extensions = ['doxtr_doto']
master_doc = 'index'
''',
        )
        
        assert status_code == 0
    
    def test_tags_with_spaces(self, validation_build):
        """Tags with spaces in values should work."""
        status_code, warnings = validation_build(
            rst_content='''
.. doto:: Spaced tag task
   :id: TASK-001
   :tags: feature, user story
''',
            conf_content='''
extensions = ['doxtr_doto']
master_doc = 'index'
''',
        )
        
        assert status_code == 0


class TestDependsOnValidation:
    """Tests for depends-on field validation."""
    
    def test_single_dependency(self, validation_build):
        """Single dependency should work."""
        status_code, warnings = validation_build(
            rst_content='''
.. doto:: Base task
   :id: TASK-001

.. doto:: Dependent task
   :id: TASK-002
   :depends-on: TASK-001
''',
            conf_content='''
extensions = ['doxtr_doto']
master_doc = 'index'
''',
        )
        
        assert status_code == 0
    
    def test_multiple_dependencies(self, validation_build):
        """Multiple dependencies should work."""
        status_code, warnings = validation_build(
            rst_content='''
.. doto:: Base task 1
   :id: TASK-001

.. doto:: Base task 2
   :id: TASK-002

.. doto:: Dependent task
   :id: TASK-003
   :depends-on: TASK-001, TASK-002
''',
            conf_content='''
extensions = ['doxtr_doto']
master_doc = 'index'
''',
        )
        
        assert status_code == 0
