"""Conflict detection and reporting for bidirectional sync."""

from __future__ import annotations

from dataclasses import dataclass


class ConflictError(Exception):
    """Exception raised when merge conflicts are detected.
    
    Attributes:
        conflicts: List of FieldConflict objects describing the conflicts.
        message: Human-readable error message.
    """
    
    def __init__(self, conflicts: list["FieldConflict"], message: str = "") -> None:
        self.conflicts = conflicts
        if not message:
            message = format_conflict_error(conflicts)
        super().__init__(message)


@dataclass
class FieldConflict:
    """Represents a conflict in a single field during 3-way merge.
    
    Attributes:
        field: Name of the conflicting field.
        base: Value from the snapshot (last synced state).
        rst: Current value from the RST file.
        json: Current value from the JSON file.
        rst_file: Path to the RST file containing the task.
        task_id: The task identifier.
    """
    field: str
    base: object
    rst: object
    json: object
    rst_file: str
    task_id: str


def format_conflict_error(conflicts: list[FieldConflict]) -> str:
    """Format conflict errors with resolution guidance.
    
    Creates a detailed error message showing:
    - Which task has conflicts
    - Which fields have conflicting changes
    - The base, RST, and JSON values for each
    - Resolution options
    
    Args:
        conflicts: List of FieldConflict objects.
        
    Returns:
        Formatted error message string.
    """
    if not conflicts:
        return "No conflicts detected."
    
    # Group conflicts by task
    by_task: dict[str, list[FieldConflict]] = {}
    for conflict in conflicts:
        if conflict.task_id not in by_task:
            by_task[conflict.task_id] = []
        by_task[conflict.task_id].append(conflict)
    
    lines = ["ERROR: Merge conflicts detected during bidirectional sync", ""]
    
    for task_id, task_conflicts in by_task.items():
        # Get RST file from first conflict (all should be same for a task)
        rst_file = task_conflicts[0].rst_file
        
        lines.append(f"Task {task_id}:")
        lines.append(f"  RST file: {rst_file}")
        lines.append("")
        
        for conflict in task_conflicts:
            lines.append(f"  Field '{conflict.field}' has conflicting changes:")
            lines.append(f"    - Base (last sync):  {_format_value(conflict.base)}")
            lines.append(f"    - In RST file:       {_format_value(conflict.rst)}")
            lines.append(f"    - In JSON file:      {_format_value(conflict.json)}")
            lines.append("")
    
    lines.append("Resolution options:")
    lines.append("  1. Edit the RST file to set the desired value, then rebuild")
    lines.append("  2. Edit .doto/tasks.json to set the desired value, then rebuild")
    
    # Add CLI resolution commands if there's only one task
    if len(by_task) == 1:
        task_id = list(by_task.keys())[0]
        lines.append(f"  3. Run: doto resolve {task_id} --use-rst    (use RST values)")
        lines.append(f"  4. Run: doto resolve {task_id} --use-json   (use JSON values)")
    else:
        lines.append("  3. Run: doto resolve <task-id> --use-rst    (use RST values)")
        lines.append("  4. Run: doto resolve <task-id> --use-json   (use JSON values)")
    
    return "\n".join(lines)


def _format_value(value: object) -> str:
    """Format a value for display in conflict messages.
    
    Args:
        value: The value to format.
        
    Returns:
        String representation suitable for display.
    """
    if value is None:
        return "(not set)"
    if isinstance(value, list):
        if not value:
            return "(empty list)"
        return ", ".join(str(v) for v in value)
    return str(value)
