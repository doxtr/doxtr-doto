"""Type definitions for doxtr_doto extension.

This module provides type-safe accessors for extended attributes
that doto adds to the Sphinx BuildEnvironment. These accessors
eliminate the need for `type: ignore[attr-defined]` comments.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, TypedDict

if TYPE_CHECKING:
    from doxtr_doto.collectors import DotoEnvironment
    from doxtr_doto.sync.json_store import JsonTaskStore


class DotoSyncData(TypedDict, total=False):
    """Sync-related data stored in BuildEnvironment.
    
    Attributes:
        json_store: The JsonTaskStore instance for the current build.
        rst_updates: List of pending RST updates as (action, file, task_id, data) tuples.
    """
    json_store: "JsonTaskStore"
    rst_updates: list[tuple[str, str, str, dict[str, Any]]]


class DotoExtendedEnv(Protocol):
    """Protocol for BuildEnvironment with doto extensions.
    
    This protocol defines the attributes that doto adds to the
    Sphinx BuildEnvironment for type checking purposes.
    """
    
    doto_data: "DotoEnvironment"
    doto_sync_data: DotoSyncData
    doto_virtual_docs: dict[str, str]
    doto_temp_files: list[Path]
    docname: str


def get_doto_sync_data(env: Any) -> DotoSyncData:
    """Get or create doto sync data on environment.
    
    Type-safe accessor for env.doto_sync_data. Creates an empty
    DotoSyncData dict if one doesn't exist.
    
    Args:
        env: Sphinx BuildEnvironment.
        
    Returns:
        DotoSyncData dictionary.
    """
    if not hasattr(env, "doto_sync_data"):
        env.doto_sync_data = {}
    return env.doto_sync_data


def set_doto_sync_data(env: Any, key: str, value: Any) -> None:
    """Set a value in doto sync data.
    
    Type-safe setter for env.doto_sync_data values.
    
    Args:
        env: Sphinx BuildEnvironment.
        key: Key to set (e.g., "json_store", "rst_updates").
        value: Value to set.
    """
    sync_data = get_doto_sync_data(env)
    sync_data[key] = value  # type: ignore[literal-required]


def get_doto_virtual_docs(env: Any) -> dict[str, str]:
    """Get or create virtual docs storage on environment.
    
    Type-safe accessor for env.doto_virtual_docs. Creates an empty
    dict if one doesn't exist.
    
    Args:
        env: Sphinx BuildEnvironment.
        
    Returns:
        Dictionary mapping docname to content.
    """
    if not hasattr(env, "doto_virtual_docs"):
        env.doto_virtual_docs = {}
    return env.doto_virtual_docs


def set_doto_virtual_doc(env: Any, docname: str, content: str) -> None:
    """Set a virtual document's content.
    
    Type-safe setter for virtual document content.
    
    Args:
        env: Sphinx BuildEnvironment.
        docname: Document name.
        content: RST content for the virtual document.
    """
    virtual_docs = get_doto_virtual_docs(env)
    virtual_docs[docname] = content


def get_doto_temp_files(env: Any) -> list[Path]:
    """Get or create temp files list on environment.
    
    Type-safe accessor for env.doto_temp_files. Creates an empty
    list if one doesn't exist.
    
    Args:
        env: Sphinx BuildEnvironment.
        
    Returns:
        List of temporary file paths.
    """
    if not hasattr(env, "doto_temp_files"):
        env.doto_temp_files = []
    return env.doto_temp_files


def add_doto_temp_file(env: Any, path: Path) -> None:
    """Add a temporary file to the tracking list.
    
    Type-safe method to track a temporary file for cleanup.
    
    Args:
        env: Sphinx BuildEnvironment.
        path: Path to the temporary file.
    """
    temp_files = get_doto_temp_files(env)
    temp_files.append(path)
