"""Custom exceptions for doxtr_doto extension.

This module provides a consistent exception hierarchy for error handling
throughout the doto extension. All doto-specific exceptions inherit from
DotoError to allow catching all doto errors with a single handler.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from doxtr_doto.sync.conflict import FieldConflict


class DotoError(Exception):
    """Base exception for all doto errors.
    
    All doto-specific exceptions inherit from this class, allowing
    callers to catch all doto errors with a single handler.
    """
    pass


class DotoSyncError(DotoError):
    """Error during bidirectional sync operations.
    
    Raised when sync between RST files and JSON store fails
    due to IO errors, parsing errors, or other issues.
    """
    pass


class DotoConflictError(DotoSyncError):
    """Merge conflict detected during sync.
    
    Raised when both RST and JSON have changed the same field
    since the last sync, and automatic resolution is not possible.
    
    Attributes:
        conflicts: List of FieldConflict objects describing each conflict.
    """
    
    def __init__(
        self,
        conflicts: list["FieldConflict"],
        message: str = "",
    ) -> None:
        self.conflicts = conflicts
        if not message:
            message = f"{len(conflicts)} conflict(s) detected during sync"
        super().__init__(message)


class DotoRstWriteError(DotoError):
    """Error writing to RST file.
    
    Raised when an RST file cannot be read, written, or modified
    due to IO errors or malformed content.
    
    Attributes:
        path: Path to the RST file.
        task_id: The task ID being written (if applicable).
    """
    
    def __init__(
        self,
        path: str,
        task_id: str = "",
        message: str = "",
    ) -> None:
        self.path = path
        self.task_id = task_id
        if not message:
            if task_id:
                message = f"Failed to write task {task_id} to {path}"
            else:
                message = f"Failed to write to {path}"
        super().__init__(message)


class DotoValidationError(DotoError):
    """Validation error for task data.
    
    Raised when task data fails validation checks, such as
    missing required fields or invalid field values.
    """
    pass


class DotoJsonStoreError(DotoError):
    """Error with JSON task store operations.
    
    Raised when the JSON store cannot be read, written, or parsed.
    """
    pass
