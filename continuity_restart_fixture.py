"""Bounded restart + model-adapter swap exercise, NOT a real hybrid LLM.

Two separate SQLite databases mimic a work-state store and an external service.
The 'models' are deterministic stubs, not LLMs. A child exits abruptly after
an external commit to model a lost acknowledgement. No network or public action.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


ADAPTERS = {
    "local_stub": lambda task: f"local draft for {task}",
    "cloud_stub": lambda task: f"cloud analysis for {task}",
}


@contextmanager
def connect(path: str):
    # sqlite3.Connection.__exit__ commits/rolls back but does not close.
    # Explicit close avoids file-handle leaks during Windows tempdir cleanup.
    db = sqlite3.connect(path, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize(state: str, external: str) -> None:
    with connect(state) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY, action TEXT NOT NULL, shareable INTEGER NOT NULL,
            evidence TEXT NOT NULL, approval TEXT NOT NULL, scope TEXT NOT NULL,
            effect TEXT NOT NULL DEFAULT 'NONE', last_adapter TEXT,
            attempt_key TEXT NOT NULL UNIQUE)""")
    with connect(external) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS effects (
            attempt_key TEXT PRIMARY KEY, task_id TEXT NOT NULL,
            action TEXT NOT NULL)""")


def seed(state: str, task: str, action: str = "PUBLISH", *, shareable: bool = True,
         evidence: str = "CURRENT", approval: str = "EXTERNALLY_VERIFIED",
         scope: str = "PUBLISH") -> None:
    # Synthetic approval strings/clearance are untrusted inputs: not real authorization.
    with connect(state) as db:
        db.execute("INSERT INTO tasks (id, action, shareable, evidence, approval, scope, attempt_key) VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (task, action, int(shareable), evidence, approval, scope, f"fixture:{task}"))


def row_for(db: sqlite3.Connection, task: str) -> sqlite3.Row:
    row = db.execute("SELECT * FROM tasks WHERE id=?", (task,)).fetchone()
    if row is None:
        raise ValueError("Unknown task")
    return row


def gate(row: sqlite3.Row) -> str:
    if row["effect"] == "UNKNOWN":
        return "HOLD_UNKNOWN_EFFECT"
    if row["effect"] == "VERIFIED":
        return "ALREADY_VERIFIED"
    if row["effect"] != "NONE" or row["action"] not in ("PUBLISH", "CLOUD_SEND"):
        return "HOLD_INVALID_STATE"
    if row["evidence"] != "CURRENT":
        return "HOLD_EVIDENCE"
    if row["shareable"] != 1:
        return "DENY_DISCLOSURE"
    if row["approval"] != "EXTERNALLY_VERIFIED" or row["scope"] != row["action"]:
        return "HOLD_APPROVAL"
    return "CANDIDATE_ONLY"


def run(state: str, external: str, task: str, adapter: str, mode: str = "normal") -> str:
    # The provider can propose prose, not write task authority or effect state.
    if adapter not in ADAPTERS:
        raise ValueError("Unsupported adapter")
    _proposal = ADAPTERS[adapter](task)
    with connect(state) as db:
        db.execute("BEGIN IMMEDIATE")
        row = row_for(db, task)
        decision = gate(row)
        if decision != "CANDIDATE_ONLY":
            return decision
        # Freeze UNKNOWN *before* dispatch; recovery must inspect the external side.
        db.execute("UPDATE tasks SET effect='UNKNOWN', last_adapter=? WHERE id=?",
                   (adapter, task))
        key, action = row["attempt_key"], row["action"]
    if mode == "crash_before":
        os._exit(23)  # child process dies before external request (unknown remains)
    with connect(external) as db:
        db.execute("INSERT INTO effects (attempt_key,task_id,action) VALUES (?,?,?)",
                   (key, task, action))
    if mode == "crash_after":
        os._exit(23)  # child process dies after durable mock external commit
    return "EFFECT_UNKNOWN_UNTIL_READBACK"


def readback(state: str, external: str, task: str) -> str:
    with connect(state) as db:
        db.execute("BEGIN IMMEDIATE")
        row = row_for(db, task)
        if row["effect"] != "UNKNOWN":
            return "NOT_PENDING"
        with connect(external) as service:
            effect = service.execute("SELECT action FROM effects WHERE attempt_key=?",
                                     (row["attempt_key"],)).fetchone()
        if effect is None:
            # Not found is NOT proof of no external side-effect in real services.
            return "HOLD_NOT_OBSERVED"
        if effect["action"] != row["action"]:
            return "HOLD_EFFECT_MISMATCH"
        db.execute("UPDATE tasks SET effect='VERIFIED' WHERE id=?", (task,))
    return "VERIFIED_BY_MOCK_READBACK"


def snapshot(state: str, task: str) -> dict:
    with connect(state) as db:
        return dict(row_for(db, task))


def effect_count(external: str) -> int:
    with connect(external) as db:
        return db.execute("SELECT COUNT(*) FROM effects").fetchone()[0]


def child(state: str, external: str, task: str, adapter: str, mode: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(Path(__file__).resolve()), "run",
                           "--state", state, "--external", external,
                           "--task", task, "--adapter", adapter, "--mode", mode],
                          text=True, capture_output=True, timeout=15)


class ScenarioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = str(Path(self.temp.name) / "state.sqlite")
        self.external = str(Path(self.temp.name) / "mock_service.sqlite")
        initialize(self.state, self.external)

    def test_01_crash_after_commit_then_provider_swap(self):
        seed(self.state, "swap")
        crash = child(self.state, self.external, "swap", "local_stub", "crash_after")
        self.assertEqual(crash.returncode, 23)
        self.assertEqual(effect_count(self.external), 1)
        self.assertEqual(snapshot(self.state, "swap")["effect"], "UNKNOWN")
        # A different process and adapter must not blindly retry.
        again = child(self.state, self.external, "swap", "cloud_stub", "normal")
        self.assertEqual(again.returncode, 0)
        self.assertIn("HOLD_UNKNOWN_EFFECT", again.stdout)
        self.assertEqual(effect_count(self.external), 1)
        self.assertEqual(readback(self.state, self.external, "swap"), "VERIFIED_BY_MOCK_READBACK")
        self.assertEqual(run(self.state, self.external, "swap", "cloud_stub"), "ALREADY_VERIFIED")
        self.assertEqual(effect_count(self.external), 1)

    def test_02_crash_before_commit_stays_unknown(self):
        seed(self.state, "pre")
        crash = child(self.state, self.external, "pre", "local_stub", "crash_before")
        self.assertEqual(crash.returncode, 23)
        self.assertEqual(readback(self.state, self.external, "pre"), "HOLD_NOT_OBSERVED")
        self.assertEqual(run(self.state, self.external, "pre", "cloud_stub"), "HOLD_UNKNOWN_EFFECT")
        self.assertEqual(effect_count(self.external), 0)

    def test_03_unapproved_model_proposal_cannot_dispatch(self):
        seed(self.state, "no-approval", approval="UNVERIFIED_SUMMARY")
        self.assertEqual(run(self.state, self.external, "no-approval", "cloud_stub"), "HOLD_APPROVAL")
        self.assertEqual(effect_count(self.external), 0)

    def test_04_restricted_cloud_data_cannot_dispatch(self):
        seed(self.state, "secret", action="CLOUD_SEND", shareable=False, scope="CLOUD_SEND")
        self.assertEqual(run(self.state, self.external, "secret", "cloud_stub"), "DENY_DISCLOSURE")
        self.assertEqual(effect_count(self.external), 0)

    def test_05_approval_scope_is_not_transferable(self):
        seed(self.state, "scope", action="PUBLISH", scope="CLOUD_SEND")
        self.assertEqual(run(self.state, self.external, "scope", "local_stub"), "HOLD_APPROVAL")

    def test_06_stale_source_stops_both_adapters(self):
        seed(self.state, "stale", evidence="STALE")
        for adapter in ADAPTERS:
            self.assertEqual(run(self.state, self.external, "stale", adapter), "HOLD_EVIDENCE")
        self.assertEqual(effect_count(self.external), 0)

    def test_07_normal_dispatch_needs_independent_readback(self):
        seed(self.state, "normal")
        self.assertEqual(run(self.state, self.external, "normal", "local_stub"),
                         "EFFECT_UNKNOWN_UNTIL_READBACK")
        self.assertEqual(snapshot(self.state, "normal")["effect"], "UNKNOWN")
        self.assertEqual(readback(self.state, self.external, "normal"), "VERIFIED_BY_MOCK_READBACK")

    def test_08_unknown_adapter_cannot_execute(self):
        seed(self.state, "unknown")
        with self.assertRaises(ValueError):
            run(self.state, self.external, "unknown", "not-an-adapter")
        self.assertEqual(effect_count(self.external), 0)

    def test_09_provider_functions_are_distinct(self):
        self.assertNotEqual(ADAPTERS["local_stub"]("same"), ADAPTERS["cloud_stub"]("same"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthetic two-process restart lab; no real LLM or remote effects")
    parser.add_argument("command", nargs="?", default="test", choices=["test", "run"])
    parser.add_argument("--state", default="")
    parser.add_argument("--external", default="")
    parser.add_argument("--task", default="")
    parser.add_argument("--adapter", default="local_stub")
    parser.add_argument("--mode", choices=["normal", "crash_before", "crash_after"], default="normal")
    args = parser.parse_args()
    if args.command == "test":
        unittest.main(argv=[sys.argv[0]], verbosity=2)
    else:
        if not (args.state and args.external and args.task):
            parser.error("--state, --external and --task are mandatory for run")
        print(json.dumps({"decision": run(args.state, args.external, args.task,
                                            args.adapter, args.mode)}), flush=True)


if __name__ == "__main__":
    main()
