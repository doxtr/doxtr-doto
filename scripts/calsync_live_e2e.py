#!/usr/bin/env python3
"""Live, autonomous end-to-end test harness for doto two-way calendar sync.

This script is the maintainer's "trust but verify" tool: it exercises doto's
*real* two-way Google Calendar sync against a dedicated throwaway calendar, with
no mocks. It plays the role of "the other user / external program" by hitting
Google Calendar directly (via ``google-api-python-client`` using the cached
token) to create / update / delete events, then drives ``doto calsync`` and
asserts the local task store reflects reality.

Why direct Google access (independent of doto's own provider)? So the harness is
a genuine external observer: it never routes a create/delete through doto's code
when simulating "the other user", which keeps the test honest about what the
real calendar contains.

Isolation
---------
Every run uses a fresh temp doto project (its own ``.doto.toml`` + ``.doto/``),
so it never touches the real repo's state. doto is driven as a subprocess with
``--config <tmp>/.doto.toml`` and ``cwd`` set to the temp project. The OAuth
token cache is deliberately left at its default (``~/.config/doto``) so the
existing, refresh-verified Google token is reused (``DOTO_CONFIG`` is *not* set,
which would otherwise relocate the token lookup).

Run tagging
-----------
Every event and task the harness creates is prefixed with a per-run tag
``E2E-<uuid8>-`` so cleanup is precise and concurrent runs never collide. The
pre-existing events already on the test calendar are *never* deleted; the
harness also tolerates them (they get imported as tasks on the first sync, which
is correct two-way behaviour, so assertions key on E2E-tagged items only).

Scenarios (each independently runnable, each prints PASS/FAIL)
--------------------------------------------------------------
* ``remote_only_new``  (a): the other user adds new event(s) to Google -- both
  the >1 case and the exactly-1 case. After ``doto calsync sync`` (two-way),
  the new remote events must be imported as new doto tasks with correct
  title/due.
* ``local_only``       (b): tasks created only locally, then synced; they must
  appear on Google with doto-owned UIDs and correct fields.
* ``both_sides``       (c): events created locally AND on the remote (both the
  >1-each case and the exactly-1-each case) then a single sync; local-created
  push up, remote-created import down, no duplication.
* ``remote_delete``    (d): delete a previously-imported remote event, re-sync;
  the local task must be archived (soft delete), per the implemented semantics.

Implemented inbound semantics actually tested (verified against engine.py):
* Pull imports only *non*-doto-owned remote events as new tasks (doto-owned
  round-trip through push and are skipped by pull).
* An imported remote event's ``summary -> title``, ``description -> body``
  (with a trailing ``[doto:...]`` back-reference stripped), ``start/due -> due``
  (date-only for all-day, else ``YYYY-MM-DDTHH:MM``), status ``open``.
* A previously-imported remote event the user deletes -> local task
  ``archived = True`` (ARCHIVE_LOCAL), never hard-deleted.
* Conflict policy on a doto-owned item edited both sides: local-wins.

Usage
-----
    python scripts/calsync_live_e2e.py            # run all scenarios + cleanup
    python scripts/calsync_live_e2e.py --cleanup  # delete leftover E2E-* events
    python scripts/calsync_live_e2e.py --scenario remote_only_new
    python scripts/calsync_live_e2e.py --keep     # don't delete temp dir (debug)

Exit code is non-zero if any scenario fails. Cleanup runs in a ``finally`` so the
calendar is left as it was found even on failure.

Local-only (never runs in CI)
-----------------------------
This harness talks to a **real** Google Calendar using a developer's cached
OAuth token, so it must never run unattended in CI. It is intentionally kept
outside ``tests/`` (pytest's ``testpaths``) so it is never collected, and it
also **refuses to run** unless the developer explicitly opts in:

* set ``DOTO_CALSYNC_LIVE_E2E=1`` to enable a run, and
* it hard-refuses when a CI environment is detected (``CI`` / ``GITHUB_ACTIONS``
  / ``CONTINUOUS_INTEGRATION``) even if the opt-in var is set, so a leaked
  token plus a misconfigured workflow cannot silently hammer a real calendar.

Credentials are supplied locally via the normal ``doto calsync login`` token
cache (``~/.config/doto/calsync-tokens/google.json``); nothing secret lives in
this file or the repo.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import uuid
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

# --- Constants --------------------------------------------------------------

TEST_CALENDAR_ID = (
    "75171cef82263a820b132bce0ab6ad3a0a0f31369e1dc68dedc0a150a3689d51@group.calendar.google.com"
)
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
RUN_TAG_PREFIX = "E2E-"
# Shared prefix for *all* runs, so --cleanup can sweep orphans from any run.
GLOBAL_PREFIX = RUN_TAG_PREFIX

# Eventual-consistency polling knobs.
POLL_TIMEOUT_S = 60.0
POLL_INTERVAL_S = 2.0


# --- Google direct client (the "other user") -------------------------------


def _token_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() / "doto" if xdg else Path.home() / ".config" / "doto"
    return base / "calsync-tokens" / "google.json"


def build_google_service() -> Any:
    """Build a Google Calendar service from the cached, refresh-verified token.

    Fails loudly with a maintainer-facing message if the token is missing or
    cannot refresh (the app is in Google 'Testing' mode, so refresh tokens can
    expire after ~7 days).
    """
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ModuleNotFoundError as exc:  # pragma: no cover - env dependent
        _die(
            f"Missing Google client libraries ({exc}). Install the calendar extra:\n"
            "  pip install 'doxtr-doto[calendar]'"
        )

    tok = _token_path()
    if not tok.exists():
        _die(
            f"No cached Google token at {tok}.\n"
            "Re-run 'doto calsync login' to authenticate, then try again."
        )
    try:
        info = json.loads(tok.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _die(f"Cached Google token at {tok} is unreadable: {exc}\nRe-run 'doto calsync login'.")

    creds = Credentials.from_authorized_user_info(info, SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as exc:  # noqa: BLE001 - want the raw reason surfaced
                _die(
                    "Google token refresh FAILED -- the harness cannot talk to the "
                    f"calendar.\nReason: {exc}\n\n"
                    "The dev OAuth app is in Google 'Testing' mode, so refresh tokens "
                    "expire ~7 days after issue.\nRe-run 'doto calsync login' to mint a "
                    "fresh token, then re-run this harness."
                )
            # Persist the refreshed token so doto's subprocess reuses it.
            try:
                tok.write_text(_creds_to_json(creds), encoding="utf-8")
            except OSError:
                pass
        else:
            _die(
                "Cached Google token is invalid and has no usable refresh token.\n"
                "Re-run 'doto calsync login' to re-authenticate."
            )
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _creds_to_json(creds: Any) -> str:
    return json.dumps(
        {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": list(creds.scopes or SCOPES),
        },
        indent=2,
    )


class GoogleDirect:
    """Thin wrapper over the Google Calendar API used by the harness itself."""

    def __init__(self, service: Any, calendar_id: str) -> None:
        self.svc = service
        self.cal = calendar_id
        # Remote-ids this run created, for precise teardown.
        self.created_ids: list[str] = []

    def create_timed_event(self, summary: str, start: datetime, minutes: int = 30) -> dict:
        """Create a timed VEVENT; naive-local wall-clock stamped with local tz."""
        from doxtr_doto.calsync.providers._shared import local_tz_name

        tz = local_tz_name()
        end = start + timedelta(minutes=minutes)
        body = {
            "summary": summary,
            "description": "created by live e2e harness",
            "start": {"dateTime": start.isoformat(), "timeZone": tz},
            "end": {"dateTime": end.isoformat(), "timeZone": tz},
        }
        ev = self.svc.events().insert(calendarId=self.cal, body=body).execute()
        self.created_ids.append(ev["id"])
        return ev

    def create_all_day_event(self, summary: str, day: date) -> dict:
        """Create an all-day VEVENT on ``day``."""
        body = {
            "summary": summary,
            "description": "created by live e2e harness",
            "start": {"date": day.isoformat()},
            "end": {"date": (day + timedelta(days=1)).isoformat()},
        }
        ev = self.svc.events().insert(calendarId=self.cal, body=body).execute()
        self.created_ids.append(ev["id"])
        return ev

    def update_summary(self, event_id: str, summary: str) -> dict:
        ev = self.svc.events().get(calendarId=self.cal, eventId=event_id).execute()
        ev["summary"] = summary
        return self.svc.events().update(calendarId=self.cal, eventId=event_id, body=ev).execute()

    def delete_event(self, event_id: str) -> None:
        try:
            self.svc.events().delete(calendarId=self.cal, eventId=event_id).execute()
        except Exception as exc:  # noqa: BLE001 - already-gone is fine
            if "deleted" not in str(exc).lower() and "not found" not in str(exc).lower():
                raise

    def list_all(self) -> list[dict]:
        out: list[dict] = []
        token: str | None = None
        while True:
            resp = (
                self.svc.events()
                .list(
                    calendarId=self.cal,
                    singleEvents=True,
                    showDeleted=False,
                    maxResults=250,
                    pageToken=token,
                )
                .execute()
            )
            for item in resp.get("items", []):
                if item.get("status") == "cancelled":
                    continue
                out.append(item)
            token = resp.get("nextPageToken")
            if not token:
                break
        return out

    def find_by_summary(self, summary: str) -> list[dict]:
        return [e for e in self.list_all() if e.get("summary") == summary]

    def find_by_prefix(self, prefix: str) -> list[dict]:
        return [e for e in self.list_all() if (e.get("summary") or "").startswith(prefix)]


# --- doto temp project + CLI driver -----------------------------------------


class DotoProject:
    """An isolated temp doto project driven via the ``doto`` CLI."""

    def __init__(
        self,
        root: Path,
        calendar_id: str,
        direction: str = "two-way",
        id_prefix: str = "DOTO",
    ) -> None:
        self.root = root
        self.calendar_id = calendar_id
        self.id_prefix = id_prefix
        self.config_path = root / ".doto.toml"
        self.json_path = root / ".doto" / "tasks.json"
        self._write_config(direction)

    def _write_config(self, direction: str) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / ".doto").mkdir(parents=True, exist_ok=True)
        # Keep global state out of the shared/home location: pin it inside the
        # temp project so the harness never touches real global state.
        #
        # A per-run unique ``id_prefix`` is essential: doto builds each pushed
        # event's iCalUID from the task id (``doto-<id>@doxtr-doto``). A fixed
        # prefix would collide with doto-owned events left on the calendar by a
        # previous run or by manual testing, and Google rejects a duplicate
        # iCalUID with HTTP 409. The unique prefix guarantees every run mints
        # fresh, non-colliding UIDs.
        self.config_path.write_text(
            "\n".join(
                [
                    "[doto]",
                    'json_file = ".doto/tasks.json"',
                    f'id_prefix = "{self.id_prefix}"',
                    f'state_file = "{(self.root / ".doto" / "global.json")}"',
                    "",
                    "[calendar]",
                    "enabled = true",
                    'provider = "google"',
                    f'calendar = "{self.calendar_id}"',
                    'event_mode = "event"',
                    f'direction = "{direction}"',
                    "all_day_for_dateless = true",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        # Critically do NOT set DOTO_CONFIG: that would relocate both the global
        # state AND the OAuth token cache lookup. We want the real cached Google
        # token at ~/.config/doto to be used. state_file in .doto.toml isolates
        # global state instead.
        env.pop("DOTO_CONFIG", None)
        return env

    def run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        cmd = ["doto", "--config", str(self.config_path), *args]
        proc = subprocess.run(
            cmd,
            cwd=str(self.root),
            env=self._env(),
            capture_output=True,
            text=True,
        )
        if check and proc.returncode != 0:
            raise RuntimeError(
                f"doto {' '.join(args)} exited {proc.returncode}\n"
                f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
            )
        return proc

    # -- task-store helpers -------------------------------------------------
    def load_tasks(self) -> dict[str, dict]:
        if not self.json_path.exists():
            return {}
        data = json.loads(self.json_path.read_text(encoding="utf-8"))
        tasks = data.get("tasks", {})
        return dict(tasks)

    def add_task(self, title: str, due: str) -> str:
        """Create a local task via the CLI; return the new task id."""
        proc = self.run("add", title, "--due", due)
        # Prefer parsing the store (robust to output format changes).
        before = getattr(self, "_last_ids", set())
        tasks = self.load_tasks()
        new = [tid for tid in tasks if tid not in before]
        if not new:
            raise RuntimeError(f"add did not create a task:\n{proc.stdout}\n{proc.stderr}")
        # Pick the task whose title matches (there may be imports too).
        for tid in new:
            if tasks[tid].get("title") == title:
                return tid
        return new[0]

    def tasks_by_title(self, title: str) -> list[tuple[str, dict]]:
        return [(tid, t) for tid, t in self.load_tasks().items() if t.get("title") == title]


# --- polling helpers --------------------------------------------------------


def poll_until(
    predicate: Callable[[], bool],
    *,
    timeout: float = POLL_TIMEOUT_S,
    interval: float = POLL_INTERVAL_S,
    desc: str = "",
) -> bool:
    """Poll ``predicate`` until True or timeout. Returns the final result."""
    deadline = time.monotonic() + timeout
    last = False
    while time.monotonic() < deadline:
        last = bool(predicate())
        if last:
            return True
        time.sleep(interval)
    return last


# --- scenario framework -----------------------------------------------------


class ScenarioResult:
    def __init__(self, name: str, passed: bool, detail: str = "") -> None:
        self.name = name
        self.passed = passed
        self.detail = detail


class Harness:
    def __init__(self, keep: bool = False) -> None:
        self.run_id = uuid.uuid4().hex[:8]
        self.tag = f"{RUN_TAG_PREFIX}{self.run_id}-"
        self.keep = keep
        self.tmp = Path(tempfile.mkdtemp(prefix=f"doto-e2e-{self.run_id}-"))
        self.svc = build_google_service()
        self.g = GoogleDirect(self.svc, TEST_CALENDAR_ID)
        self.results: list[ScenarioResult] = []

    # -- lifecycle ----------------------------------------------------------
    def new_project(self, name: str, direction: str = "two-way") -> DotoProject:
        root = self.tmp / name
        # Per-run, per-scenario id prefix -> unique doto-owned iCalUIDs that
        # never collide with events left by earlier runs. Alnum only (ids feed
        # straight into the UID).
        id_prefix = f"E2E{self.run_id}{_slug(name)}"
        return DotoProject(root, TEST_CALENDAR_ID, direction=direction, id_prefix=id_prefix)

    def teardown(self) -> None:
        """Delete every event this run created, then drop the temp dir."""
        print(f"\n[cleanup] run {self.run_id}: removing E2E events + temp project")
        # Delete by remote-id first (precise), then sweep by this run's summary
        # prefix AND by doto-owned UID prefix. The UID sweep matters because a
        # push can mint a doto-owned event whose *summary* is an imported
        # event's (non-E2E) title -- those are only identifiable by their
        # ``doto-E2E<run_id>...@doxtr-doto`` UID, not by summary.
        for eid in list(self.g.created_ids):
            self.g.delete_event(eid)
        swept = 0
        uid_marker = f"doto-E2E{self.run_id}"
        for ev in self.g.list_all():
            summary = ev.get("summary") or ""
            uid = ev.get("iCalUID") or ""
            if summary.startswith(self.tag) or uid.startswith(uid_marker):
                self.g.delete_event(ev["id"])
                swept += 1
        print(f"[cleanup] deleted {len(self.g.created_ids)} tracked + {swept} swept event(s)")
        if self.keep:
            print(f"[cleanup] keeping temp project at {self.tmp}")
        else:
            shutil.rmtree(self.tmp, ignore_errors=True)
            print(f"[cleanup] removed {self.tmp}")

    # -- scenario runner ----------------------------------------------------
    def run_scenario(self, fn: Callable[[], None]) -> None:
        name = fn.__name__
        print(f"\n=== SCENARIO: {name} ===")
        try:
            fn()
        except AssertionError as exc:
            print(f"[FAIL] {name}: {exc}")
            self.results.append(ScenarioResult(name, False, str(exc)))
        except Exception as exc:  # noqa: BLE001 - report, keep going
            print(f"[FAIL] {name}: unexpected error: {exc}")
            traceback.print_exc()
            self.results.append(ScenarioResult(name, False, repr(exc)))
        else:
            print(f"[PASS] {name}")
            self.results.append(ScenarioResult(name, True))

    # -- scenarios ----------------------------------------------------------
    def remote_only_new(self) -> None:
        """(a) Other user adds remote events (>1 and ==1); sync imports them.

        After a two-way ``sync`` in a fresh project, the newly created remote
        events (which are NOT doto-owned) must appear as local tasks with the
        right title and due.
        """
        proj = self.new_project("remote_only_new")

        # --- the >1 case: two new remote events ---------------------------
        day = _future_date(3)
        s_multi_a = f"{self.tag}remote-multi-A"
        s_multi_b = f"{self.tag}remote-multi-B"
        start_a = datetime.combine(day, datetime.min.time()).replace(hour=9)
        self.g.create_timed_event(s_multi_a, start_a, minutes=30)
        self.g.create_all_day_event(s_multi_b, day + timedelta(days=1))

        # --- the ==1 case: exactly one new remote event -------------------
        s_single = f"{self.tag}remote-single"
        start_single = datetime.combine(_future_date(5), datetime.min.time()).replace(hour=14)
        self.g.create_timed_event(s_single, start_single, minutes=45)

        # Wait for Google to make them listable (eventual consistency).
        want = {s_multi_a, s_multi_b, s_single}
        ok = poll_until(
            lambda: want.issubset({e.get("summary") for e in self.g.find_by_prefix(self.tag)}),
            desc="remote events visible",
        )
        assert ok, "remote events did not become visible on the calendar in time"

        proj.run("calsync", "sync")

        # Each remote event must now be a local task with correct title+due.
        tasks = proj.load_tasks()

        def _one(title: str) -> dict:
            hits = [t for t in tasks.values() if t.get("title") == title]
            assert len(hits) == 1, f"expected exactly 1 task titled {title!r}, got {len(hits)}"
            return hits[0]

        t_a = _one(s_multi_a)
        assert t_a.get("due") == f"{day.isoformat()}T09:00", f"timed due wrong: {t_a.get('due')}"
        t_b = _one(s_multi_b)
        assert t_b.get("due") == (day + timedelta(days=1)).isoformat(), (
            f"all-day due wrong: {t_b.get('due')}"
        )
        t_s = _one(s_single)
        assert t_s.get("due") == f"{_future_date(5).isoformat()}T14:00", (
            f"single timed due wrong: {t_s.get('due')}"
        )
        for t in (t_a, t_b, t_s):
            assert t.get("status") == "open", f"imported task should be open: {t.get('status')}"
        print(
            f"  imported 3 remote events as tasks (>1 and ==1 cases): {s_multi_a}, "
            f"{s_multi_b}, {s_single}"
        )

        # Idempotency: a second sync imports nothing new for these titles.
        proj.run("calsync", "sync")
        tasks2 = proj.load_tasks()
        for title in (s_multi_a, s_multi_b, s_single):
            n = len([t for t in tasks2.values() if t.get("title") == title])
            assert n == 1, f"second sync duplicated {title!r} (now {n})"
        print("  second sync did not duplicate (idempotent)")

    def local_only(self) -> None:
        """(b) Local-only tasks pushed; appear on Google with doto UIDs."""
        from doxtr_doto.calsync.model import make_uid

        proj = self.new_project("local_only")

        day = _future_date(4)
        title1 = f"{self.tag}local-A"
        title2 = f"{self.tag}local-B"
        # Timed + date-only (all-day) to cover both projections.
        proj.add_task(title1, f"{day.isoformat()}T10:00")
        proj.add_task(title2, day.isoformat())

        proj.run("calsync", "sync")

        tasks = proj.load_tasks()
        ids = {t.get("title"): tid for tid, t in tasks.items()}
        assert title1 in ids and title2 in ids, "local tasks missing from store"
        uid1 = make_uid(ids[title1])
        uid2 = make_uid(ids[title2])

        def _remote_has_uids() -> bool:
            events = self.g.find_by_prefix(self.tag)
            uids = {e.get("iCalUID") for e in events}
            return uid1 in uids and uid2 in uids

        assert poll_until(_remote_has_uids), (
            "pushed tasks did not appear on Google with doto-owned iCalUIDs"
        )

        events = {e.get("iCalUID"): e for e in self.g.find_by_prefix(self.tag)}
        ev1 = events[uid1]
        assert ev1.get("summary") == title1, f"remote summary wrong: {ev1.get('summary')}"
        assert ev1["start"].get("dateTime", "").startswith(f"{day.isoformat()}T10:00"), (
            f"timed start wrong: {ev1['start']}"
        )
        ev2 = events[uid2]
        assert ev2.get("summary") == title2
        assert ev2["start"].get("date") == day.isoformat(), f"all-day start wrong: {ev2['start']}"
        print(f"  pushed 2 local tasks to Google with doto UIDs {uid1}, {uid2}")

    def both_sides(self) -> None:
        """(c) Local + remote creations, single sync; both reconcile, no dupes.

        Covers both the >1-each case and the exactly-one-each case in one
        project/sync: 2 local + 2 remote, plus 1 local + 1 remote.
        """
        from doxtr_doto.calsync.model import make_uid

        proj = self.new_project("both_sides")
        day = _future_date(6)

        # Local side: 2 (multi) + 1 (single) = 3 local tasks.
        local_titles = [
            f"{self.tag}both-local-A",
            f"{self.tag}both-local-B",
            f"{self.tag}both-local-single",
        ]
        for i, t in enumerate(local_titles):
            proj.add_task(t, f"{day.isoformat()}T{9 + i:02d}:00")

        # Remote side: 2 (multi) + 1 (single) = 3 remote events (not doto-owned).
        remote_titles = [
            f"{self.tag}both-remote-A",
            f"{self.tag}both-remote-B",
            f"{self.tag}both-remote-single",
        ]
        base = datetime.combine(day, datetime.min.time())
        for i, t in enumerate(remote_titles):
            self.g.create_timed_event(t, base.replace(hour=13 + i), minutes=30)

        # Ensure remote creations are visible before the single sync.
        assert poll_until(
            lambda: set(remote_titles).issubset(
                {e.get("summary") for e in self.g.find_by_prefix(self.tag)}
            )
        ), "remote events for both_sides not visible in time"

        # A single two-way sync does pull-then-push.
        proj.run("calsync", "sync")

        tasks = proj.load_tasks()
        titles_now = [t.get("title") for t in tasks.values()]

        # Remote-created imported down exactly once each.
        for t in remote_titles:
            n = titles_now.count(t)
            assert n == 1, f"remote->local import count for {t!r} is {n}, expected 1"

        # Local-created pushed up with doto UIDs, exactly once each on Google.
        ids = {t.get("title"): tid for tid, t in tasks.items()}
        want_uids = {make_uid(ids[t]) for t in local_titles}

        def _pushed() -> bool:
            uids = [e.get("iCalUID") for e in self.g.find_by_prefix(self.tag)]
            return all(u in uids for u in want_uids)

        assert poll_until(_pushed), "local tasks were not all pushed to Google"
        remote_events = self.g.find_by_prefix(self.tag)
        for u in want_uids:
            n = sum(1 for e in remote_events if e.get("iCalUID") == u)
            assert n == 1, f"local->remote push duplicated uid {u} ({n} copies)"

        # No duplication: remote-created events were NOT re-pushed as doto-owned
        # copies (they are not doto-owned, pull imports but push must not touch).
        for t in remote_titles:
            copies = [e for e in remote_events if e.get("summary") == t]
            assert len(copies) == 1, f"remote event {t!r} got duplicated on Google ({len(copies)})"

        # Second sync is a no-op for counts (idempotency / no runaway dupes).
        proj.run("calsync", "sync")
        tasks2 = proj.load_tasks()
        titles2 = [t.get("title") for t in tasks2.values()]
        for t in remote_titles + local_titles:
            assert titles2.count(t) == 1, f"second sync changed task count for {t!r}"
        print("  both-sides reconciled (3 local pushed, 3 remote imported, no dupes)")

    def remote_delete(self) -> None:
        """(d) Delete a previously-imported remote event -> local task archived."""
        proj = self.new_project("remote_delete")
        day = _future_date(7)
        title = f"{self.tag}remote-del"
        ev = self.g.create_timed_event(
            title, datetime.combine(day, datetime.min.time()).replace(hour=11), minutes=30
        )
        assert poll_until(lambda: bool(self.g.find_by_summary(title))), (
            "remote event for delete scenario not visible in time"
        )

        # First sync imports it as a local task.
        proj.run("calsync", "sync")
        hits = proj.tasks_by_title(title)
        assert len(hits) == 1, f"expected 1 imported task, got {len(hits)}"
        task_id, task = hits[0]
        assert not task.get("archived"), "imported task should start un-archived"
        print(f"  imported remote event as task {task_id}")

        # The other user deletes the event remotely.
        self.g.delete_event(ev["id"])
        assert poll_until(lambda: not self.g.find_by_summary(title)), (
            "remote event did not disappear after delete"
        )

        # Re-sync: the local task must be archived (soft delete), not removed.
        proj.run("calsync", "sync")
        tasks = proj.load_tasks()
        assert task_id in tasks, "task should still exist (soft delete), not be hard-deleted"
        assert tasks[task_id].get("archived") is True, (
            f"task {task_id} should be archived after remote delete; "
            f"archived={tasks[task_id].get('archived')}"
        )
        assert tasks[task_id].get("archived_on"), "archived_on timestamp should be set"
        print(f"  task {task_id} archived after remote delete (soft delete honoured)")

    # -- summary ------------------------------------------------------------
    def print_summary(self) -> bool:
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        width = max((len(r.name) for r in self.results), default=10)
        all_ok = True
        for r in self.results:
            status = "PASS" if r.passed else "FAIL"
            line = f"  {r.name.ljust(width)}  {status}"
            if not r.passed and r.detail:
                line += f"   ({r.detail})"
            print(line)
            all_ok = all_ok and r.passed
        print("=" * 60)
        print(f"RESULT: {'ALL PASS' if all_ok else 'FAILURES PRESENT'}  (run {self.run_id})")
        return all_ok


# --- helpers ----------------------------------------------------------------


def _future_date(days_ahead: int) -> date:
    return date.today() + timedelta(days=days_ahead)


def _slug(name: str) -> str:
    """Reduce a scenario name to an alnum fragment safe inside a doto id."""
    return "".join(c for c in name.title() if c.isalnum())


def _die(msg: str) -> None:
    print(f"\nFATAL: {msg}", file=sys.stderr)
    sys.exit(2)


ALL_SCENARIOS = ["remote_only_new", "local_only", "both_sides", "remote_delete"]


def cleanup_only() -> int:
    """Sweep the calendar for any leftover E2E-* events from any run.

    Matches both (1) events whose *summary* carries the E2E run tag and (2)
    doto-owned events whose *UID* was minted by an E2E run
    (``doto-E2E...@doxtr-doto``) -- the latter can be a doto-owned copy of an
    imported event whose title is not E2E-tagged, so a summary-only sweep would
    miss it. Pre-existing non-E2E events (including unrelated doto-owned ones)
    are left untouched.
    """
    svc = build_google_service()
    g = GoogleDirect(svc, TEST_CALENDAR_ID)

    def _is_e2e(ev: dict) -> bool:
        summary = ev.get("summary") or ""
        uid = ev.get("iCalUID") or ""
        return summary.startswith(GLOBAL_PREFIX) or uid.startswith("doto-E2E")

    leftovers = [e for e in g.list_all() if _is_e2e(e)]
    print(f"[cleanup] found {len(leftovers)} leftover E2E-* event(s)")
    for ev in leftovers:
        print(f"  deleting {ev.get('summary')!r} ({ev.get('iCalUID')})")
        g.delete_event(ev["id"])
    remaining = [e for e in g.list_all() if _is_e2e(e)]
    if remaining:
        print(f"[cleanup] WARNING: {len(remaining)} E2E-* event(s) still present")
        return 1
    print("[cleanup] calendar clean: no E2E-* events remain")
    return 0


def _live_run_guard() -> str | None:
    """Refuse to run in CI / without explicit opt-in.

    The harness mutates a real Google Calendar with a developer's cached OAuth
    token, so it must only run locally when a developer deliberately enables it.
    Returns an error message to print (and abort) when the run is not allowed,
    or ``None`` when it is safe to proceed.
    """
    ci_markers = ("CI", "GITHUB_ACTIONS", "CONTINUOUS_INTEGRATION")
    detected = [name for name in ci_markers if os.environ.get(name)]
    if detected:
        return (
            "Refusing to run the live calsync e2e harness: CI environment "
            f"detected ({', '.join(detected)}). This harness hits a real Google "
            "Calendar with a developer's credentials and is local-only by "
            "design."
        )
    if os.environ.get("DOTO_CALSYNC_LIVE_E2E") != "1":
        return (
            "Refusing to run the live calsync e2e harness: it talks to a real "
            "Google Calendar using your cached OAuth token. Set "
            "DOTO_CALSYNC_LIVE_E2E=1 to opt in, e.g.:\n\n"
            "    DOTO_CALSYNC_LIVE_E2E=1 python scripts/calsync_live_e2e.py\n"
        )
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live two-way calsync e2e harness")
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Delete any leftover E2E-* events from the test calendar and exit.",
    )
    parser.add_argument(
        "--scenario",
        choices=ALL_SCENARIOS,
        action="append",
        help="Run only the named scenario (repeatable). Default: all.",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep the temp project dir for debugging (events are still cleaned).",
    )
    args = parser.parse_args(argv)

    guard_error = _live_run_guard()
    if guard_error is not None:
        print(guard_error, file=sys.stderr)
        return 2

    if args.cleanup:
        return cleanup_only()

    harness = Harness(keep=args.keep)
    print(f"Live calsync e2e harness -- run {harness.run_id}")
    print(f"  temp project: {harness.tmp}")
    print(f"  calendar:     {TEST_CALENDAR_ID}")
    print(f"  run tag:      {harness.tag}")

    scenarios = args.scenario or ALL_SCENARIOS
    fn_map = {
        "remote_only_new": harness.remote_only_new,
        "local_only": harness.local_only,
        "both_sides": harness.both_sides,
        "remote_delete": harness.remote_delete,
    }
    try:
        for name in scenarios:
            harness.run_scenario(fn_map[name])
        all_ok = harness.print_summary()
    finally:
        harness.teardown()
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
