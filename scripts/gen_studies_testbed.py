#!/usr/bin/env python3
"""Generate the ``studies/`` test bed for the doto extension.

Creates a realistic school/university folder tree under ``studies/`` with:

* RST content pages for each subject (so the chapter renders in Sphinx), and
* a self-contained *doto repository* (``.doto.toml`` + ``.doto/tasks.json``)
  inside each main subject folder.

Each subject repo gets its own ``id_prefix`` (MATHS, PHYS, ENG, ...), tasks in
every status (open / in-progress / blocked / done), a dependency or two, tags,
assignees, due dates and -- importantly -- ``worklogs`` (logged time) so the
CLI/TUI stats and time views have something to aggregate.

The generated schema matches ``doxtr_doto.sync.json_store`` (version 5):
tasks carry ``worklogs`` as ``{"started_at", "stopped_at"}`` ISO-8601 pairs.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Output roots. By default the tree is written under the real docs chapter
# location so it can be dropped straight into the dox repo at
# ``source/extensions/doto/studies``. ``build()`` can retarget these at any
# directory (e.g. a pytest ``tmp_path``) without touching the generators.
#
# ``ROOT``/``HS``/``UNI`` are module-level so the many ``gen_*`` functions can
# reference them directly; ``_retarget()`` rebinds them for one build and
# restores them afterwards so importing this module for tests never clobbers
# the default output location.
# ---------------------------------------------------------------------------
DEFAULT_ROOT = Path(__file__).resolve().parent.parent / "studies"

ROOT = DEFAULT_ROOT
HS = ROOT / "highschool"
UNI = ROOT / "university"

SCHEMA_VERSION = 5

# A fixed "now" so generated timestamps/worklogs are deterministic and the
# relative due dates look sensible against each other (mid-semester).
NOW = datetime(2026, 5, 18, 9, 0, 0)  # a Monday morning


def iso(dt: datetime) -> str:
    """ISO-8601 string with a local-looking offset (keeps parsers happy)."""
    return dt.isoformat()


def worklog(start: datetime, minutes: int) -> dict[str, str]:
    """A closed work session of ``minutes`` length starting at ``start``."""
    return {"started_at": iso(start), "stopped_at": iso(start + timedelta(minutes=minutes))}


def open_worklog(start: datetime) -> dict[str, str | None]:
    """An *open* (still running) work session."""
    return {"started_at": iso(start), "stopped_at": None}


# ---------------------------------------------------------------------------
# .doto.toml template (mirrors cli/commands/init.py DEFAULT_DOTO_TOML).
# ---------------------------------------------------------------------------
def doto_toml(prefix: str) -> str:
    return f"""\
[doto]
# Source directory (relative to this file)
# source_dir = "."

# JSON task store location
json_file = ".doto/tasks.json"

# Inbox file for new/reopened tasks
inbox_file = "tasks/inbox.rst"

# ID generation
id_prefix = "{prefix}"
id_sequential = true

# Defaults for new tasks
default_priority = "medium"
default_status = "open"

# Display settings
date_format = "%Y-%m-%d"
color = "auto"

# Valid values
statuses = ["open", "in-progress", "blocked", "done"]
priorities = ["low", "medium", "high", "critical"]
"""


def task(
    *,
    title: str,
    status: str,
    priority: str = "medium",
    assignee: str | None = None,
    due: str | None = None,
    tags: list[str] | None = None,
    depends_on: list[str] | None = None,
    body: str | None = None,
    created: datetime,
    worklogs: list[dict] | None = None,
    progress: int | None = None,
    archived: bool = False,
) -> dict:
    """Build a schema-correct task dict (json_store version 5)."""
    updated = created + timedelta(days=1)
    return {
        "title": title,
        "assignee": assignee,
        "priority": priority,
        "status": status,
        "due": due,
        "tags": tags or [],
        "depends_on": depends_on or [],
        "body": body,
        "progress": progress,
        "raci": {"responsible": [assignee], "accountable": [assignee]} if assignee else None,
        "created": iso(created),
        "updated": iso(updated),
        "archived": archived,
        "archived_on": iso(updated) if archived else None,
        "worklogs": worklogs or [],
        "_sync": {"rst_file": None, "rst_line": None, "rst_hash": None, "snapshot": None},
    }


def write_repo(folder: Path, prefix: str, tasks: dict[str, dict]) -> None:
    """Write ``.doto.toml``, ``.doto/tasks.json`` and an inbox for a subject."""
    (folder / ".doto").mkdir(parents=True, exist_ok=True)
    (folder / ".doto.toml").write_text(doto_toml(prefix), encoding="utf-8")

    store = {
        "version": SCHEMA_VERSION,
        "updated": iso(NOW),
        "tasks": tasks,
        "series": {},
    }
    (folder / ".doto" / "tasks.json").write_text(
        json.dumps(store, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # Minimal inbox so `doto add` has a landing file in Sphinx mode.
    tasks_dir = folder / "tasks"
    tasks_dir.mkdir(exist_ok=True)
    (tasks_dir / "inbox.rst").write_text(
        "Task Inbox\n==========\n\n"
        "New tasks created via the CLI land here until filed into a page.\n",
        encoding="utf-8",
    )


def rst(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.lstrip("\n"), encoding="utf-8")


# ===========================================================================
# Subject definitions. Each produces a repo with tasks across all states and
# some logged time. Due dates/worklogs are anchored around NOW (2026-05-18).
# ===========================================================================
def gen_maths() -> None:
    base = HS / "maths"
    c = NOW - timedelta(days=20)
    tasks = {
        "MATHS-001": task(
            title="Review limits and continuity",
            status="done",
            priority="medium",
            assignee="sam",
            due="2026-05-04",
            tags=["calculus", "revision"],
            body="Work through the chapter on limits; redo the epsilon-delta proofs.",
            created=c,
            worklogs=[
                worklog(datetime(2026, 4, 29, 14, 0), 95),
                worklog(datetime(2026, 4, 30, 16, 30), 60),
            ],
            progress=100,
        ),
        "MATHS-002": task(
            title="Problem set 7: derivatives",
            status="in-progress",
            priority="high",
            assignee="sam",
            due="2026-05-22",
            tags=["calculus", "homework"],
            depends_on=["MATHS-001"],
            body="Chain rule, implicit differentiation, related rates (Q1-Q12).",
            created=c + timedelta(days=5),
            worklogs=[
                worklog(datetime(2026, 5, 15, 10, 0), 75),
                worklog(datetime(2026, 5, 17, 20, 15), 50),
            ],
            progress=60,
        ),
        "MATHS-003": task(
            title="Prepare for integration techniques exam",
            status="open",
            priority="high",
            assignee="sam",
            due="2026-06-10",
            tags=["calculus", "exam"],
            body="Partial fractions, trig substitution, integration by parts.",
            created=c + timedelta(days=8),
            worklogs=[],
            progress=0,
        ),
        "MATHS-004": task(
            title="Linear algebra: eigenvalues worksheet",
            status="blocked",
            priority="medium",
            assignee="jordan",
            due="2026-05-28",
            tags=["linear-algebra", "homework"],
            depends_on=["MATHS-002"],
            body="Blocked: need the lecturer's note on diagonalisation first.",
            created=c + timedelta(days=10),
            worklogs=[worklog(datetime(2026, 5, 16, 13, 0), 40)],
            progress=20,
        ),
        "MATHS-005": task(
            title="Submit old statistics assignment (resit)",
            status="done",
            priority="low",
            assignee="jordan",
            due="2026-04-20",
            tags=["statistics"],
            created=c - timedelta(days=5),
            worklogs=[worklog(datetime(2026, 4, 18, 9, 30), 120)],
            progress=100,
            archived=True,
        ),
    }
    write_repo(base, "MATHS", tasks)

    rst(base / "index.rst", """
Maths
=====

Notes, problem sets, and revision material for mathematics -- from school
algebra through to first-year university calculus and linear algebra.

.. toctree::
   :maxdepth: 1

   calculus/index
   linear-algebra
   statistics
   tasks/inbox

Open tasks for this subject
---------------------------

.. doto-list::
   :status: open, in-progress, blocked
""")
    rst(base / "calculus" / "index.rst", """
Calculus
========

.. toctree::
   :maxdepth: 1

   limits
   derivatives

The two central ideas of calculus are the *derivative* (instantaneous rate of
change) and the *integral* (accumulated change). The Fundamental Theorem of
Calculus ties them together.
""")
    rst(base / "calculus" / "limits.rst", """
Limits and Continuity
=====================

A function :math:`f` has limit :math:`L` as :math:`x \\to a` if the values of
:math:`f(x)` can be made arbitrarily close to :math:`L` by taking :math:`x`
sufficiently close to :math:`a`.

Key results
-----------

* Squeeze theorem
* :math:`\\lim_{x\\to 0} \\frac{\\sin x}{x} = 1`
* A function is continuous at :math:`a` when
  :math:`\\lim_{x\\to a} f(x) = f(a)`.
""")
    rst(base / "calculus" / "derivatives.rst", """
Derivatives
===========

The derivative measures the instantaneous rate of change of a function.

Rules
-----

* Power rule, product rule, quotient rule
* Chain rule: :math:`(f \\circ g)' = (f' \\circ g)\\cdot g'`
* Implicit differentiation for curves given by :math:`F(x, y) = 0`.
""")
    rst(base / "linear-algebra.rst", """
Linear Algebra
==============

Vectors, matrices, and the linear maps between vector spaces.

Topics
------

* Systems of linear equations and Gaussian elimination
* Determinants and invertibility
* Eigenvalues, eigenvectors, and diagonalisation
""")
    rst(base / "statistics.rst", """
Statistics
==========

Descriptive and inferential statistics.

Topics
------

* Measures of centre and spread
* Probability distributions (binomial, normal)
* Hypothesis testing and confidence intervals
""")


def gen_physics() -> None:
    base = HS / "physics"
    c = NOW - timedelta(days=18)
    tasks = {
        "PHYS-001": task(
            title="Lab report: projectile motion",
            status="done",
            priority="high",
            assignee="sam",
            due="2026-05-06",
            tags=["mechanics", "lab"],
            body="Write up the projectile experiment; include error analysis.",
            created=c,
            worklogs=[
                worklog(datetime(2026, 5, 3, 15, 0), 110),
                worklog(datetime(2026, 5, 5, 19, 0), 80),
            ],
            progress=100,
        ),
        "PHYS-002": task(
            title="Derive the equations of motion",
            status="in-progress",
            priority="medium",
            assignee="sam",
            due="2026-05-21",
            tags=["mechanics"],
            body="From constant acceleration, derive v, s, and v^2 relations.",
            created=c + timedelta(days=4),
            worklogs=[worklog(datetime(2026, 5, 16, 11, 0), 45)],
            progress=40,
        ),
        "PHYS-003": task(
            title="Read chapter on electromagnetism",
            status="open",
            priority="medium",
            assignee="jordan",
            due="2026-05-30",
            tags=["electromagnetism", "reading"],
            created=c + timedelta(days=7),
            worklogs=[],
            progress=0,
        ),
        "PHYS-004": task(
            title="Set up oscilloscope for AC experiment",
            status="blocked",
            priority="high",
            assignee="jordan",
            due="2026-05-25",
            tags=["electromagnetism", "lab"],
            depends_on=["PHYS-003"],
            body="Blocked: the lab's second oscilloscope is out for repair.",
            created=c + timedelta(days=9),
            worklogs=[open_worklog(datetime(2026, 5, 18, 8, 30))],
            progress=10,
        ),
    }
    write_repo(base, "PHYS", tasks)

    rst(base / "index.rst", """
Physics
=======

Classical mechanics, electromagnetism, and the lab work that goes with them.

.. toctree::
   :maxdepth: 1

   mechanics
   electromagnetism
   tasks/inbox

.. doto-summary::
   :show-chart: true
   :chart-type: bar
""")
    rst(base / "mechanics.rst", """
Mechanics
=========

Newton's laws and the kinematics of motion.

Equations of motion (constant acceleration)
-------------------------------------------

* :math:`v = u + at`
* :math:`s = ut + \\tfrac{1}{2}at^2`
* :math:`v^2 = u^2 + 2as`
""")
    rst(base / "electromagnetism.rst", """
Electromagnetism
================

Electric and magnetic fields and their unification in Maxwell's equations.

Topics
------

* Coulomb's law and electric fields
* Magnetic force on moving charges
* Electromagnetic induction (Faraday's law)
""")


def gen_english() -> None:
    base = HS / "english"
    c = NOW - timedelta(days=15)
    tasks = {
        "ENG-001": task(
            title="Essay: themes in Macbeth",
            status="in-progress",
            priority="high",
            assignee="sam",
            due="2026-05-24",
            tags=["literature", "essay"],
            body="1500 words on ambition and guilt. Draft intro + three body paragraphs.",
            created=c,
            worklogs=[
                worklog(datetime(2026, 5, 14, 18, 0), 90),
                worklog(datetime(2026, 5, 17, 15, 30), 65),
            ],
            progress=55,
        ),
        "ENG-002": task(
            title="Read Chapters 1-5 of the set novel",
            status="done",
            priority="low",
            assignee="sam",
            due="2026-05-10",
            tags=["literature", "reading"],
            created=c + timedelta(days=2),
            worklogs=[worklog(datetime(2026, 5, 9, 20, 0), 70)],
            progress=100,
        ),
        "ENG-003": task(
            title="Prepare oral presentation on persuasive techniques",
            status="open",
            priority="medium",
            assignee="jordan",
            due="2026-06-02",
            tags=["language", "presentation"],
            created=c + timedelta(days=5),
            worklogs=[],
            progress=0,
        ),
        "ENG-004": task(
            title="Peer review Alex's essay",
            status="blocked",
            priority="low",
            assignee="jordan",
            due="2026-05-23",
            tags=["essay"],
            depends_on=["ENG-001"],
            body="Blocked until my own draft (ENG-001) is finished.",
            created=c + timedelta(days=6),
            worklogs=[],
            progress=0,
        ),
    }
    write_repo(base, "ENG", tasks)

    rst(base / "index.rst", """
English
=======

Literature study and language/composition work.

.. toctree::
   :maxdepth: 1

   literature
   language
   tasks/inbox
""")
    rst(base / "literature.rst", """
Literature
==========

Close reading, theme analysis, and essay writing.

Working on
----------

* Macbeth -- ambition, guilt, the supernatural
* Narrative structure and unreliable narrators
""")
    rst(base / "language.rst", """
Language and Composition
========================

Rhetoric, persuasive techniques, and structured writing.

Persuasive techniques
----------------------

* Ethos, pathos, logos
* Rhetorical questions, tricolon, anaphora
""")


def gen_german() -> None:
    base = HS / "german"
    c = NOW - timedelta(days=14)
    tasks = {
        "GER-001": task(
            title="Lernen: Dativ und Akkusativ Präpositionen",
            status="in-progress",
            priority="medium",
            assignee="sam",
            due="2026-05-20",
            tags=["grammar", "vocab"],
            body="Wechselpräpositionen: aus/bei/mit vs. durch/für/gegen.",
            created=c,
            worklogs=[worklog(datetime(2026, 5, 15, 17, 0), 55)],
            progress=50,
        ),
        "GER-002": task(
            title="Vokabeltest Kapitel 4 vorbereiten",
            status="open",
            priority="high",
            assignee="sam",
            due="2026-05-27",
            tags=["vocab", "test"],
            created=c + timedelta(days=3),
            worklogs=[],
            progress=0,
        ),
        "GER-003": task(
            title="Aufsatz: Mein letzter Urlaub",
            status="done",
            priority="medium",
            assignee="jordan",
            due="2026-05-08",
            tags=["writing"],
            created=c + timedelta(days=1),
            worklogs=[worklog(datetime(2026, 5, 7, 16, 0), 85)],
            progress=100,
        ),
    }
    write_repo(base, "GER", tasks)

    rst(base / "index.rst", """
German
======

Deutsch als Fremdsprache -- grammar, vocabulary, and composition.

.. toctree::
   :maxdepth: 1

   grammar
   vocabulary
   tasks/inbox
""")
    rst(base / "grammar.rst", """
Grammar
=======

Cases, prepositions, and verb conjugation.

Die vier Fälle
--------------

* Nominativ (subject)
* Akkusativ (direct object)
* Dativ (indirect object)
* Genitiv (possession)
""")
    rst(base / "vocabulary.rst", """
Vocabulary
==========

Thematic word lists and spaced-repetition decks.

Themen
------

* Reisen und Urlaub
* Schule und Studium
* Alltag und Freizeit
""")


def gen_biology() -> None:
    base = HS / "biology"
    c = NOW - timedelta(days=16)
    tasks = {
        "BIO-001": task(
            title="Label cell diagram (plant vs animal)",
            status="done",
            priority="low",
            assignee="sam",
            due="2026-05-09",
            tags=["cells", "homework"],
            created=c,
            worklogs=[worklog(datetime(2026, 5, 8, 14, 0), 40)],
            progress=100,
        ),
        "BIO-002": task(
            title="Essay: natural selection and adaptation",
            status="in-progress",
            priority="high",
            assignee="sam",
            due="2026-05-26",
            tags=["evolution", "essay"],
            created=c + timedelta(days=4),
            worklogs=[worklog(datetime(2026, 5, 16, 19, 0), 70)],
            progress=45,
        ),
        "BIO-003": task(
            title="Dissection lab prep",
            status="blocked",
            priority="medium",
            assignee="jordan",
            due="2026-05-29",
            tags=["lab"],
            body="Blocked: awaiting the signed consent/safety form.",
            created=c + timedelta(days=6),
            worklogs=[],
            progress=0,
        ),
        "BIO-004": task(
            title="Revise photosynthesis equations",
            status="open",
            priority="medium",
            assignee="jordan",
            due="2026-06-01",
            tags=["cells", "revision"],
            created=c + timedelta(days=8),
            worklogs=[],
            progress=0,
        ),
    }
    write_repo(base, "BIO", tasks)

    rst(base / "index.rst", """
Biology
=======

Cells, genetics, evolution, and the lab work in between.

.. toctree::
   :maxdepth: 1

   cells
   evolution
   tasks/inbox
""")
    rst(base / "cells.rst", """
Cells
=====

The basic structural and functional unit of living organisms.

Organelles
----------

* Nucleus -- stores genetic material
* Mitochondria -- site of respiration
* Chloroplasts (plants) -- site of photosynthesis
""")
    rst(base / "evolution.rst", """
Evolution
=========

Change in heritable characteristics of populations over generations.

Mechanisms
----------

* Natural selection
* Genetic drift
* Gene flow and mutation
""")


def gen_chemistry() -> None:
    base = HS / "chemistry"
    c = NOW - timedelta(days=17)
    tasks = {
        "CHEM-001": task(
            title="Balance redox equations worksheet",
            status="in-progress",
            priority="high",
            assignee="sam",
            due="2026-05-23",
            tags=["reactions", "homework"],
            created=c,
            worklogs=[
                worklog(datetime(2026, 5, 15, 16, 0), 60),
                worklog(datetime(2026, 5, 17, 11, 0), 35),
            ],
            progress=65,
        ),
        "CHEM-002": task(
            title="Titration lab report",
            status="done",
            priority="high",
            assignee="sam",
            due="2026-05-07",
            tags=["lab"],
            created=c + timedelta(days=1),
            worklogs=[worklog(datetime(2026, 5, 6, 13, 30), 130)],
            progress=100,
        ),
        "CHEM-003": task(
            title="Memorise the first 20 elements",
            status="open",
            priority="low",
            assignee="jordan",
            due="2026-05-31",
            tags=["periodic-table", "revision"],
            created=c + timedelta(days=5),
            worklogs=[],
            progress=0,
        ),
        "CHEM-004": task(
            title="Organic chemistry naming practice",
            status="blocked",
            priority="medium",
            assignee="jordan",
            due="2026-06-03",
            tags=["organic"],
            depends_on=["CHEM-001"],
            body="Blocked: finish the redox worksheet first for the shared notation.",
            created=c + timedelta(days=7),
            worklogs=[],
            progress=0,
        ),
    }
    write_repo(base, "CHEM", tasks)

    rst(base / "index.rst", """
Chemistry
=========

Atomic structure, reactions, and organic chemistry.

.. toctree::
   :maxdepth: 1

   periodic-table
   reactions
   tasks/inbox
""")
    rst(base / "periodic-table.rst", """
The Periodic Table
==================

Elements arranged by atomic number and recurring chemical properties.

Trends
------

* Atomic radius decreases across a period
* Electronegativity increases across a period
* Reactivity of metals increases down a group
""")
    rst(base / "reactions.rst", """
Chemical Reactions
==================

Conservation of mass and the rearrangement of atoms.

Types
-----

* Synthesis and decomposition
* Single and double displacement
* Redox (oxidation-reduction)
""")


def gen_computer_basics() -> None:
    base = HS / "computer-basics"
    c = NOW - timedelta(days=12)
    tasks = {
        "COMP-001": task(
            title="Touch-typing practice to 40 wpm",
            status="done",
            priority="low",
            assignee="sam",
            due="2026-05-11",
            tags=["skills"],
            created=c,
            worklogs=[
                worklog(datetime(2026, 5, 9, 18, 0), 30),
                worklog(datetime(2026, 5, 10, 18, 0), 30),
            ],
            progress=100,
        ),
        "COMP-002": task(
            title="Write first Python script (hello world + loops)",
            status="in-progress",
            priority="medium",
            assignee="sam",
            due="2026-05-25",
            tags=["programming", "python"],
            created=c + timedelta(days=2),
            worklogs=[worklog(datetime(2026, 5, 16, 20, 0), 50)],
            progress=50,
        ),
        "COMP-003": task(
            title="Learn basic shell commands (ls, cd, mkdir)",
            status="open",
            priority="medium",
            assignee="jordan",
            due="2026-05-28",
            tags=["cli"],
            created=c + timedelta(days=4),
            worklogs=[],
            progress=0,
        ),
    }
    write_repo(base, "COMP", tasks)

    rst(base / "index.rst", """
Computer Basics
===============

Foundational digital skills: typing, files, the command line, and a first
taste of programming.

.. toctree::
   :maxdepth: 1

   files-and-folders
   command-line
   programming
   tasks/inbox
""")
    rst(base / "files-and-folders.rst", """
Files and Folders
=================

How data is organised on disk.

Concepts
--------

* Files vs directories (folders)
* Absolute vs relative paths
* File extensions and types
""")
    rst(base / "command-line.rst", """
The Command Line
================

Interacting with the computer by typing commands.

Essential commands
------------------

* ``ls`` -- list directory contents
* ``cd`` -- change directory
* ``mkdir`` -- make a directory
""")
    rst(base / "programming.rst", """
First Steps in Programming
==========================

Variables, loops, and functions in Python.

.. code-block:: python

   for i in range(5):
       print("hello", i)
""")


def gen_history() -> None:
    base = HS / "history"
    c = NOW - timedelta(days=13)
    tasks = {
        "HIST-001": task(
            title="Source analysis: causes of WWI",
            status="in-progress",
            priority="high",
            assignee="sam",
            due="2026-05-24",
            tags=["modern", "essay"],
            created=c,
            worklogs=[worklog(datetime(2026, 5, 16, 15, 0), 80)],
            progress=50,
        ),
        "HIST-002": task(
            title="Timeline of the Industrial Revolution",
            status="done",
            priority="low",
            assignee="jordan",
            due="2026-05-10",
            tags=["modern"],
            created=c + timedelta(days=2),
            worklogs=[worklog(datetime(2026, 5, 9, 14, 0), 60)],
            progress=100,
        ),
        "HIST-003": task(
            title="Read set text on the Cold War",
            status="open",
            priority="medium",
            assignee="sam",
            due="2026-06-04",
            tags=["modern", "reading"],
            created=c + timedelta(days=4),
            worklogs=[],
            progress=0,
        ),
    }
    write_repo(base, "HIST", tasks)

    rst(base / "index.rst", """
History
=======

Modern world history, source analysis, and essay technique.

.. toctree::
   :maxdepth: 1

   modern-history
   tasks/inbox
""")
    rst(base / "modern-history.rst", """
Modern History
==============

From the Industrial Revolution to the late twentieth century.

Themes
------

* Causes and consequences of the World Wars
* Industrialisation and social change
* The Cold War and decolonisation
""")


def gen_highschool_index() -> None:
    rst(HS / "index.rst", """
High School
===========

Subject notes and task repositories from secondary school. Each subject is
its own *doto repository* (``.doto.toml`` + ``.doto/tasks.json``) with its own
task-ID prefix, e.g. a task in ``maths/`` becomes ``MATHS-001``.

.. toctree::
   :maxdepth: 1

   maths/index
   physics/index
   chemistry/index
   biology/index
   english/index
   german/index
   history/index
   computer-basics/index
""")


# ===========================================================================
# University programme: BSc Computer Science at (fictional) Riverford
# University. Each module is its own doto repository. Years 1 and 2 cover the
# typical core load a CS undergraduate takes, plus a general academic-writing
# module -- roughly the normal 6 modules per year.
# ===========================================================================
def _uni_module(
    folder_name: str,
    prefix: str,
    title: str,
    code: str,
    description: str,
    topics: list[str],
    tasks: dict[str, dict],
) -> None:
    """Create one university module: a doto repo plus an index page."""
    base = UNI / folder_name
    write_repo(base, prefix, tasks)
    topic_lines = "\n".join(f"* {t}" for t in topics)
    rst(base / "index.rst", f"""
{title}
{"=" * len(title)}

**Module code:** {code}

{description}

Syllabus
--------

{topic_lines}

.. toctree::
   :maxdepth: 1

   tasks/inbox

Outstanding work
----------------

.. doto-list::
   :status: open, in-progress, blocked
""")


def gen_university() -> None:
    y1 = NOW - timedelta(days=22)
    y2 = NOW - timedelta(days=19)

    # --- Year 1 -----------------------------------------------------------
    _uni_module(
        "cs101-programming",
        "CS101",
        "CS101: Introduction to Programming",
        "CS101",
        "First principles of programming in Python: expressions, control flow,\n"
        "functions, and basic data structures.",
        ["Variables and types", "Conditionals and loops", "Functions and scope",
         "Lists, dicts, and files"],
        {
            "CS101-001": task(
                title="Lab 1: environment setup and hello world",
                status="done", priority="low", assignee="sam", due="2026-05-02",
                tags=["lab"], created=y1,
                worklogs=[worklog(datetime(2026, 4, 27, 10, 0), 50)], progress=100,
            ),
            "CS101-002": task(
                title="Assignment 1: temperature converter",
                status="done", priority="medium", assignee="sam", due="2026-05-09",
                tags=["assignment"], created=y1 + timedelta(days=3),
                worklogs=[worklog(datetime(2026, 5, 6, 14, 0), 90),
                          worklog(datetime(2026, 5, 7, 16, 0), 40)], progress=100,
            ),
            "CS101-003": task(
                title="Assignment 2: text-based number guessing game",
                status="in-progress", priority="high", assignee="sam", due="2026-05-23",
                tags=["assignment"], depends_on=["CS101-002"],
                body="Loops, random module, input validation.",
                created=y1 + timedelta(days=8),
                worklogs=[worklog(datetime(2026, 5, 16, 19, 0), 70)], progress=55,
            ),
            "CS101-004": task(
                title="Revise for midterm quiz",
                status="open", priority="medium", assignee="sam", due="2026-06-05",
                tags=["exam"], created=y1 + timedelta(days=10),
                worklogs=[], progress=0,
            ),
        },
    )
    _uni_module(
        "cs102-discrete-maths",
        "DISC",
        "CS102: Discrete Mathematics",
        "CS102",
        "The mathematical foundations of computer science: logic, sets,\n"
        "relations, and proof techniques.",
        ["Propositional and predicate logic", "Set theory", "Functions and relations",
         "Proof by induction", "Combinatorics"],
        {
            "DISC-001": task(
                title="Problem sheet 3: induction proofs",
                status="in-progress", priority="high", assignee="sam", due="2026-05-22",
                tags=["homework", "proofs"], created=y1,
                worklogs=[worklog(datetime(2026, 5, 15, 13, 0), 65),
                          worklog(datetime(2026, 5, 17, 10, 0), 40)], progress=50,
            ),
            "DISC-002": task(
                title="Problem sheet 2: set identities",
                status="done", priority="medium", assignee="sam", due="2026-05-08",
                tags=["homework"], created=y1 - timedelta(days=4),
                worklogs=[worklog(datetime(2026, 5, 7, 15, 0), 80)], progress=100,
            ),
            "DISC-003": task(
                title="Read lecture notes on combinatorics",
                status="open", priority="low", assignee="jordan", due="2026-05-30",
                tags=["reading"], created=y1 + timedelta(days=6),
                worklogs=[], progress=0,
            ),
            "DISC-004": task(
                title="Group study session on relations",
                status="blocked", priority="low", assignee="jordan", due="2026-05-26",
                tags=["study-group"],
                body="Blocked: waiting for the group to agree a room/time.",
                created=y1 + timedelta(days=7), worklogs=[], progress=0,
            ),
        },
    )
    _uni_module(
        "cs103-calculus",
        "CALC",
        "MA110: Calculus for Computing",
        "MA110",
        "Single-variable calculus with applications to algorithm analysis.",
        ["Limits and derivatives", "Integration", "Series and growth rates",
         "Big-O intuition from asymptotics"],
        {
            "CALC-001": task(
                title="Weekly tutorial exercises (week 6)",
                status="done", priority="medium", assignee="sam", due="2026-05-12",
                tags=["tutorial"], created=y1,
                worklogs=[worklog(datetime(2026, 5, 11, 17, 0), 60)], progress=100,
            ),
            "CALC-002": task(
                title="Practice past-paper integration questions",
                status="open", priority="high", assignee="sam", due="2026-06-08",
                tags=["exam"], created=y1 + timedelta(days=5),
                worklogs=[], progress=0,
            ),
            "CALC-003": task(
                title="Tutorial exercises (week 7)",
                status="in-progress", priority="medium", assignee="sam", due="2026-05-19",
                tags=["tutorial"], created=y1 + timedelta(days=7),
                worklogs=[worklog(datetime(2026, 5, 17, 14, 0), 35)], progress=40,
            ),
        },
    )

    # --- Year 2 -----------------------------------------------------------
    _uni_module(
        "cs201-data-structures",
        "DSA",
        "CS201: Data Structures and Algorithms",
        "CS201",
        "Core data structures and the design and analysis of algorithms.",
        ["Arrays, lists, stacks, queues", "Trees and heaps", "Hash tables",
         "Sorting and searching", "Big-O analysis", "Graph algorithms"],
        {
            "DSA-001": task(
                title="Implement a binary search tree",
                status="in-progress", priority="high", assignee="sam", due="2026-05-24",
                tags=["coursework", "trees"], created=y2,
                worklogs=[worklog(datetime(2026, 5, 14, 20, 0), 95),
                          worklog(datetime(2026, 5, 17, 21, 0), 60)], progress=60,
            ),
            "DSA-002": task(
                title="Big-O analysis worksheet",
                status="done", priority="medium", assignee="sam", due="2026-05-10",
                tags=["homework"], created=y2 - timedelta(days=3),
                worklogs=[worklog(datetime(2026, 5, 9, 16, 0), 75)], progress=100,
            ),
            "DSA-003": task(
                title="Coursework 2: shortest-path implementation",
                status="blocked", priority="high", assignee="sam", due="2026-06-06",
                tags=["coursework", "graphs"], depends_on=["DSA-001"],
                body="Blocked: build the graph structure (DSA-001) before Dijkstra.",
                created=y2 + timedelta(days=6), worklogs=[], progress=0,
            ),
            "DSA-004": task(
                title="Review sorting algorithm complexities",
                status="open", priority="low", assignee="jordan", due="2026-06-02",
                tags=["revision"], created=y2 + timedelta(days=8),
                worklogs=[], progress=0,
            ),
        },
    )
    _uni_module(
        "cs202-databases",
        "DB",
        "CS202: Databases",
        "CS202",
        "Relational data modelling, SQL, and transaction management.",
        ["ER modelling", "Relational algebra", "SQL (DDL and DML)",
         "Normalisation", "Transactions and ACID"],
        {
            "DB-001": task(
                title="Design ER diagram for library system",
                status="done", priority="medium", assignee="sam", due="2026-05-11",
                tags=["coursework", "modelling"], created=y2,
                worklogs=[worklog(datetime(2026, 5, 10, 13, 0), 100)], progress=100,
            ),
            "DB-002": task(
                title="Write SQL queries for coursework part 2",
                status="in-progress", priority="high", assignee="sam", due="2026-05-25",
                tags=["coursework", "sql"], depends_on=["DB-001"],
                created=y2 + timedelta(days=4),
                worklogs=[worklog(datetime(2026, 5, 16, 18, 0), 85)], progress=50,
            ),
            "DB-003": task(
                title="Revise normalisation (1NF-3NF, BCNF)",
                status="open", priority="medium", assignee="sam", due="2026-06-09",
                tags=["exam"], created=y2 + timedelta(days=7),
                worklogs=[], progress=0,
            ),
        },
    )
    _uni_module(
        "cs203-computer-systems",
        "SYS",
        "CS203: Computer Systems and Architecture",
        "CS203",
        "How programs run on hardware: representation, assembly, memory,\n"
        "and the operating system.",
        ["Number representation", "CPU and instruction sets", "Assembly basics",
         "Memory hierarchy and caching", "Processes and scheduling"],
        {
            "SYS-001": task(
                title="Lab: two's complement arithmetic",
                status="done", priority="low", assignee="jordan", due="2026-05-06",
                tags=["lab"], created=y2,
                worklogs=[worklog(datetime(2026, 5, 5, 11, 0), 55)], progress=100,
            ),
            "SYS-002": task(
                title="Assembly assignment: loop in x86-64",
                status="in-progress", priority="high", assignee="jordan", due="2026-05-27",
                tags=["assignment", "assembly"], created=y2 + timedelta(days=5),
                worklogs=[worklog(datetime(2026, 5, 17, 12, 0), 65)], progress=45,
            ),
            "SYS-003": task(
                title="Read chapter on cache memory",
                status="blocked", priority="medium", assignee="sam", due="2026-05-29",
                tags=["reading"],
                body="Blocked: library e-book licence is at capacity.",
                created=y2 + timedelta(days=6), worklogs=[], progress=0,
            ),
            "SYS-004": task(
                title="Summarise process scheduling algorithms",
                status="open", priority="medium", assignee="sam", due="2026-06-07",
                tags=["revision"], created=y2 + timedelta(days=9),
                worklogs=[], progress=0,
            ),
        },
    )
    _uni_module(
        "cs204-software-engineering",
        "SE",
        "CS204: Software Engineering",
        "CS204",
        "Working in a team to build software: process, version control,\n"
        "testing, and the group project.",
        ["Agile and Scrum", "Git and collaboration", "Requirements and design",
         "Unit testing and CI", "Group project"],
        {
            "SE-001": task(
                title="Group project: write the requirements document",
                status="in-progress", priority="high", assignee="sam", due="2026-05-21",
                tags=["group-project"], created=y2,
                worklogs=[worklog(datetime(2026, 5, 15, 15, 0), 90)], progress=65,
            ),
            "SE-002": task(
                title="Set up the team Git repository and CI",
                status="done", priority="medium", assignee="jordan", due="2026-05-09",
                tags=["group-project", "tooling"], created=y2 - timedelta(days=2),
                worklogs=[worklog(datetime(2026, 5, 8, 14, 0), 70)], progress=100,
            ),
            "SE-003": task(
                title="Write unit tests for the parser module",
                status="blocked", priority="high", assignee="sam", due="2026-05-28",
                tags=["group-project", "testing"], depends_on=["SE-001"],
                body="Blocked: parser interface isn't finalised until the requirements are signed off.",
                created=y2 + timedelta(days=5), worklogs=[], progress=0,
            ),
            "SE-004": task(
                title="Prepare sprint 2 retrospective notes",
                status="open", priority="low", assignee="jordan", due="2026-06-01",
                tags=["group-project"], created=y2 + timedelta(days=8),
                worklogs=[], progress=0,
            ),
        },
    )
    _uni_module(
        "ac100-academic-writing",
        "AW",
        "AC100: Academic Writing and Research Skills",
        "AC100",
        "A general-education module on scholarly writing, referencing, and\n"
        "research methods -- taken alongside the core CS modules.",
        ["Essay structure", "Referencing (IEEE/APA)", "Literature searching",
         "Avoiding plagiarism", "Presentation skills"],
        {
            "AW-001": task(
                title="Reflective essay on study habits",
                status="done", priority="low", assignee="sam", due="2026-05-05",
                tags=["essay"], created=y1,
                worklogs=[worklog(datetime(2026, 5, 4, 16, 0), 75)], progress=100,
            ),
            "AW-002": task(
                title="Annotated bibliography for research assignment",
                status="in-progress", priority="medium", assignee="sam", due="2026-05-26",
                tags=["research"], created=y1 + timedelta(days=6),
                worklogs=[worklog(datetime(2026, 5, 16, 11, 0), 60)], progress=40,
            ),
            "AW-003": task(
                title="Prepare 5-minute presentation",
                status="open", priority="medium", assignee="jordan", due="2026-06-03",
                tags=["presentation"], created=y1 + timedelta(days=9),
                worklogs=[], progress=0,
            ),
        },
    )

    rst(UNI / "index.rst", """
University
==========

BSc Computer Science at Riverford University (a fictional institution used for
test data). Each module below is its own *doto repository* with its own
task-ID prefix. The set is a typical full first- and second-year load: the
core CS modules plus a general academic-writing module.

Year 1
------

.. toctree::
   :maxdepth: 1

   cs101-programming/index
   cs102-discrete-maths/index
   cs103-calculus/index
   ac100-academic-writing/index

Year 2
------

.. toctree::
   :maxdepth: 1

   cs201-data-structures/index
   cs202-databases/index
   cs203-computer-systems/index
   cs204-software-engineering/index
""")


def gen_root_index() -> None:
    rst(ROOT / "index.rst", """
Studies
=======

A worked example data set for the ``doto`` extension: a student's study notes
that grew over time, from secondary-school subjects through to a first- and
second-year university programme. Each subject/module folder is its own *doto
repository* (it has a ``.doto.toml`` and a ``.doto/tasks.json``), so you can
test cross-repo discovery, filtering, aggregation, and time-tracking.

Each subject uses its own task-ID prefix -- a task created in
``highschool/maths/`` becomes ``MATHS-001``, one in
``university/cs101-programming/`` becomes ``CS101-001``, and so on.

.. toctree::
   :maxdepth: 2

   highschool/index
   university/index

Try it out
----------

From any subject/module folder (for example ``highschool/maths/`` or
``university/cs201-data-structures/``)::

   doto list                 # tasks in this repo
   doto list --status open   # filter by status
   doto stats --by-status    # aggregate counts
   doto timesheet            # logged time
   doto tui                  # interactive view

To discover and aggregate across every subject, run from ``studies/``::

   doto repos rescan .
   doto repos
""")


def _run_generators() -> None:
    """Run every ``gen_*`` builder against the current ``ROOT``/``HS``/``UNI``."""
    gen_root_index()
    gen_highschool_index()
    gen_maths()
    gen_physics()
    gen_chemistry()
    gen_biology()
    gen_english()
    gen_german()
    gen_history()
    gen_computer_basics()
    gen_university()


def _discover_metadata(root: Path) -> dict:
    """Read back the generated repos into a plain-data summary.

    Deriving the summary from disk (rather than hardcoding it) keeps a single
    source of truth: tests that assert on counts/prefixes/states exercise the
    exact bytes the generators wrote.

    Returns:
        A dict with:
          * ``root``: the test-bed root (``Path``).
          * ``repos``: list of per-repo dicts, each with ``name``, ``path``
            (``Path`` to the repo folder), ``prefix``, ``task_count`` and
            ``statuses`` (a ``{status: count}`` dict).
          * ``total_tasks``: int across all repos.
          * ``status_totals``: ``{status: count}`` across all repos.
    """
    import collections
    import re

    repos: list[dict] = []
    status_totals: collections.Counter[str] = collections.Counter()
    total = 0
    for tasks_json in sorted(root.rglob(".doto/tasks.json")):
        repo_dir = tasks_json.parent.parent
        prefix = None
        toml = repo_dir / ".doto.toml"
        if toml.is_file():
            m = re.search(r'id_prefix\s*=\s*"([^"]+)"', toml.read_text(encoding="utf-8"))
            if m:
                prefix = m.group(1)
        data = json.loads(tasks_json.read_text(encoding="utf-8"))
        statuses: collections.Counter[str] = collections.Counter()
        for t in data["tasks"].values():
            statuses[t["status"]] += 1
        repos.append(
            {
                "name": repo_dir.name,
                "path": repo_dir,
                "prefix": prefix,
                "task_count": len(data["tasks"]),
                "statuses": dict(statuses),
            }
        )
        status_totals.update(statuses)
        total += len(data["tasks"])
    return {
        "root": root,
        "repos": repos,
        "total_tasks": total,
        "status_totals": dict(status_totals),
    }


def build(root: Path | str | None = None, *, clean: bool = True) -> dict:
    """Generate the whole ``studies`` test bed under ``root``.

    This is the importable entry point used by both the CLI (``main``) and the
    test suite. It temporarily retargets the module-level output roots at
    ``root`` so the (many) ``gen_*`` builders write there, then restores them,
    so importing this module and calling ``build(tmp_path)`` from a test never
    disturbs the default ``studies/`` location.

    Args:
        root: Directory to write ``studies/<...>`` into. The tree is written
            *at* ``root`` itself (so ``root`` becomes the ``studies`` root).
            Defaults to the repo's ``studies/`` folder.
        clean: Remove ``root`` first for a reproducible tree. Defaults True.

    Returns:
        The metadata summary from :func:`_discover_metadata`.
    """
    global ROOT, HS, UNI
    target = DEFAULT_ROOT if root is None else Path(root)

    saved = (ROOT, HS, UNI)
    ROOT, HS, UNI = target, target / "highschool", target / "university"
    try:
        if clean and ROOT.exists():
            import shutil

            shutil.rmtree(ROOT)
        _run_generators()
        return _discover_metadata(ROOT)
    finally:
        ROOT, HS, UNI = saved


def main() -> None:
    meta = build()
    print(
        f"Generated studies test bed at {meta['root']}: "
        f"{len(meta['repos'])} repos, {meta['total_tasks']} tasks "
        f"({meta['status_totals']})"
    )


if __name__ == "__main__":
    main()
