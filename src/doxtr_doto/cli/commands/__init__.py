"""doto CLI commands.

This package contains all CLI command implementations.
Commands are registered in cli/main.py.
"""

from __future__ import annotations

from doxtr_doto.cli.commands.add import add
from doxtr_doto.cli.commands.archive import archive
from doxtr_doto.cli.commands.completion import completion
from doxtr_doto.cli.commands.config import config_cmd
from doxtr_doto.cli.commands.deps import deps
from doxtr_doto.cli.commands.done import done
from doxtr_doto.cli.commands.export import export
from doxtr_doto.cli.commands.git import git_cmd
from doxtr_doto.cli.commands.init import init
from doxtr_doto.cli.commands.list import list_tasks
from doxtr_doto.cli.commands.next import next_task
from doxtr_doto.cli.commands.reopen import reopen
from doxtr_doto.cli.commands.resolve import resolve
from doxtr_doto.cli.commands.search import search
from doxtr_doto.cli.commands.series import series
from doxtr_doto.cli.commands.show import show
from doxtr_doto.cli.commands.stats import stats
from doxtr_doto.cli.commands.tree import tree
from doxtr_doto.cli.commands.update import update

__all__ = [
    "add",
    "archive",
    "completion",
    "config_cmd",
    "deps",
    "done",
    "export",
    "git_cmd",
    "init",
    "list_tasks",
    "next_task",
    "reopen",
    "resolve",
    "search",
    "series",
    "show",
    "stats",
    "tree",
    "update",
]
