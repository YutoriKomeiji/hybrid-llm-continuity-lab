"""Bounded RPR 0.1.0a6 restart probe with two deterministic proposer adapters.

This does NOT run a local/cloud LLM or a real API service. It uses the actual
published Responsibility Pathway Runtime against two independent SQLite files.
A subprocess dies after the mock external write to simulate lost acknowledgement.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from rpr.attempts import SQLiteExecutionAttemptLedger
from rpr.authority import AuthorityError
from rpr.executor import ExecutionRequest, ExecutionResult, ExecutionStatus, ReadbackEvidence
from rpr.models import ActionClass, EnvironmentTrust, PathwayDefinition, PathwayState
from rpr.reconciliation import ReconciliationResult, ReconciliationStatus
from rpr.rpe import AllowAllDevelopmentEvaluator
from rpr.runtime import ResponsibilityPathwayRuntime
from rpr.storage import SQLiteStore


# Distinct *synthetic* proposal functions, not trained language models.
PROPOSERS = {
    "local_stub": lambda task: f"local draft: {task}",
    "cloud_stub": lambda task: f"cloud draft: {task}",
}


def build_runtime(directory: Path) -> ResponsibilityPathwayRuntime:
    return ResponsibilityPathwayRuntime(
        store=SQLiteStore(directory / "pathways.sqlite3"),
        attempt_ledger=SQLiteExecutionAttemptLedger(directory / "attempts.sqlite3"),
        rpe=AllowAllDevelopmentEvaluator(),  # TEST-ONLY: not actual authority!
    )


def definition(task_id: str) -> PathwayDefinition:
    return PathwayDefinition(
        pathway_id=task_id,
        action_name="external_mutation",
        action_class=ActionClass.SUGGEST_ONLY,
        environment_trust=EnvironmentTrust.TRUSTED_INTERNAL,
        decision_owner="owner",
        approval_authority=None,
        execution_actor="agent",
        stop_authority="operator",
        evidence_owner="auditor",
        repair_owner="repairer",
        resume_authority="resumer",
        human_return_point="before_retry",
        residual_owner="owner",
    )


def request(task_id: str) -> ExecutionRequest:
    # The external attempt identity does NOT depend on the selected proposer.
    return ExecutionRequest(
        operation_id=f"operation-{task_id}",
        attempt_id=f"attempt-{task_id}",
        idempotency_key=f"fixed:{task_id}",
        action="external_mutation",
        parameters={"fixture_task": task_id, "value": 1},
    )


def initialize_mock_service(directory: Path) -> None:
    with sqlite3.connect(directory / "mock_service.sqlite3") as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS effects (idempotency_key TEXT PRIMARY KEY, action TEXT NOT NULL)")


def count_effects(directory: Path) -> int:
    with sqlite3.connect(directory / "mock_service.sqlite3") as conn:
        return conn.execute("SELECT COUNT(*) FROM effects").fetchone()[0]


class MockExternalWriteExecutor:
    """Local SQLite stand-in for a remote write; no internet or real effects."""

    def __init__(self, directory: Path, mode: str) -> None:
        self.directory = directory
        self.mode = mode
        self.calls = 0

    def execute(self, req: ExecutionRequest) -> ExecutionResult:
        self.calls += 1
        if self.mode == "crash_before":
            os._exit(23)  # subprocess dies after RPR recorded its attempt
        with sqlite3.connect(self.directory / "mock_service.sqlite3") as conn:
            conn.execute("INSERT INTO effects VALUES (?, ?)", (req.idempotency_key, req.action))
        if self.mode == "crash_after":
            os._exit(23)  # mock external effect committed; RPR has no reply
        return ExecutionResult(
            ExecutionStatus.SUCCEEDED,
            {"idempotency_key": req.idempotency_key},
            ReadbackEvidence(True, {"mock_service_committed": True}),
        )


class CountingExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, req: ExecutionRequest) -> ExecutionResult:
        del req
        self.calls += 1
        return ExecutionResult(
            ExecutionStatus.SUCCEEDED,
            {"unexpected": True},
            ReadbackEvidence(True, {"unexpected": True}),
        )


class MockReadbackStrategy:
    """No match is UNRESOLVED; it is never proof of no effect."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.calls = 0

    def reconcile(self, req, attempt) -> ReconciliationResult:
        del attempt
        self.calls += 1
        with sqlite3.connect(self.directory / "mock_service.sqlite3") as conn:
            found = conn.execute(
                "SELECT action FROM effects WHERE idempotency_key=?",
                (req.idempotency_key,),
            ).fetchone()
        if found is None:
            return ReconciliationResult(
                ReconciliationStatus.UNRESOLVED,
                {"mock_effect_lookup": "missing_not_a_proof"},
                "mock_readback_has_no_record",
            )
        if found[0] != req.action:
            return ReconciliationResult(
                ReconciliationStatus.UNRESOLVED,
                {"mock_effect_lookup": "action_mismatch"},
                "mock_record_conflict",
            )
        return ReconciliationResult(
            ReconciliationStatus.VERIFIED_APPLIED,
            {"mock_effect_lookup": "matched", "idempotency_key": req.idempotency_key},
            "exact_mock_readback",
        )


def worker(directory: Path, task_id: str, mode: str) -> None:
    runtime = build_runtime(directory)
    runtime.register(definition(task_id), idempotency_key=f"register-{task_id}")
    proposal = PROPOSERS["local_stub"](task_id)
    assert proposal.startswith("local draft")
    runtime.execute(
        task_id,
        request(task_id),
        actor="agent",
        executor=MockExternalWriteExecutor(directory, mode),
    )


def spawn(directory: Path, task_id: str, mode: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--worker",
         "--dir", str(directory), "--task", task_id, "--mode", mode],
        capture_output=True, text=True, timeout=20,
    )


class PublishedRPRSwapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        initialize_mock_service(self.directory)

    def test_01_lost_ack_then_different_proposer_is_not_a_retry(self) -> None:
        # Real subprocess exit after durable mock-service commit.
        child = spawn(self.directory, "lost-ack", "crash_after")
        self.assertEqual(child.returncode, 23, child.stderr)
        self.assertEqual(count_effects(self.directory), 1)
        self.assertNotEqual(PROPOSERS["local_stub"]("x"), PROPOSERS["cloud_stub"]("x"))
        restarted = build_runtime(self.directory)
        second_adapter_proposal = PROPOSERS["cloud_stub"]("lost-ack")
        self.assertTrue(second_adapter_proposal.startswith("cloud draft"))
        executor = CountingExecutor()
        result = restarted.execute("lost-ack", request("lost-ack"), actor="agent", executor=executor)
        self.assertIs(result.status, ExecutionStatus.WRITE_STATUS_UNKNOWN)
        self.assertEqual(executor.calls, 0)
        self.assertEqual(count_effects(self.directory), 1)
        self.assertIs(restarted.store.get_state("lost-ack"), PathwayState.WRITE_STATUS_UNKNOWN)
        observer = MockReadbackStrategy(self.directory)
        verified = restarted.reconcile("lost-ack", request("lost-ack"), actor="auditor", strategy=observer)
        self.assertIs(verified.status, ExecutionStatus.SUCCEEDED)
        self.assertEqual(observer.calls, 1)
        self.assertEqual(count_effects(self.directory), 1)
        self.assertTrue(restarted.verify_evidence("lost-ack").valid)

    def test_02_crash_before_effect_no_record_is_not_failure_proof(self) -> None:
        child = spawn(self.directory, "pre-effect", "crash_before")
        self.assertEqual(child.returncode, 23, child.stderr)
        self.assertEqual(count_effects(self.directory), 0)
        restarted = build_runtime(self.directory)
        executor = CountingExecutor()
        result = restarted.execute("pre-effect", request("pre-effect"), actor="agent", executor=executor)
        self.assertIs(result.status, ExecutionStatus.WRITE_STATUS_UNKNOWN)
        self.assertEqual(executor.calls, 0)
        observation = restarted.reconcile("pre-effect", request("pre-effect"),
                                          actor="auditor", strategy=MockReadbackStrategy(self.directory))
        self.assertIs(observation.status, ExecutionStatus.WRITE_STATUS_UNKNOWN)
        self.assertIs(restarted.store.get_state("pre-effect"), PathwayState.WRITE_STATUS_UNKNOWN)
        self.assertEqual(count_effects(self.directory), 0)

    def test_03_unauthorized_reconciliation_never_checks_mock_effect(self) -> None:
        child = spawn(self.directory, "unapproved-auditor", "crash_after")
        self.assertEqual(child.returncode, 23, child.stderr)
        restarted = build_runtime(self.directory)
        executor = CountingExecutor()
        result = restarted.execute("unapproved-auditor", request("unapproved-auditor"),
                                   actor="agent", executor=executor)
        self.assertIs(result.status, ExecutionStatus.WRITE_STATUS_UNKNOWN)
        observation = MockReadbackStrategy(self.directory)
        with self.assertRaises(AuthorityError):
            restarted.reconcile("unapproved-auditor", request("unapproved-auditor"),
                                actor="unrecognized_actor", strategy=observation)
        self.assertEqual(observation.calls, 0)
        self.assertEqual(count_effects(self.directory), 1)

    def test_04_normal_attempt_result_is_durable_across_restart(self) -> None:
        child = spawn(self.directory, "normal", "normal")
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(count_effects(self.directory), 1)
        restarted = build_runtime(self.directory)
        executor = CountingExecutor()
        replay = restarted.execute("normal", request("normal"), actor="agent", executor=executor)
        self.assertIs(replay.status, ExecutionStatus.SUCCEEDED)
        self.assertEqual(executor.calls, 0)
        self.assertEqual(count_effects(self.directory), 1)
        self.assertTrue(restarted.verify_evidence("normal").valid)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--dir", default="")
    parser.add_argument("--task", default="")
    parser.add_argument("--mode", choices=["normal", "crash_before", "crash_after"], default="normal")
    args = parser.parse_args()
    if args.worker:
        if not args.dir or not args.task:
            parser.error("--dir and --task required for worker")
        worker(Path(args.dir), args.task, args.mode)
    else:
        unittest.main(argv=[sys.argv[0]], verbosity=2)


if __name__ == "__main__":
    main()
