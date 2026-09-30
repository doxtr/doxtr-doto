"""Doto roles for cross-referencing tasks.

This module re-exports the doto role and reference resolver from doto_ref.
"""

from doxtr_doto.roles.doto_ref import doto_role, resolve_doto_xref

__all__ = ["doto_role", "resolve_doto_xref"]
