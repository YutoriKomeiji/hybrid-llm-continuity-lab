"""Synthetic continuity/authority gate for a Zennfes 2026 concept article.

NO LLMs, external requests, real authorizations, or consequential actions.
This is a deterministic protocol sketch, not a security boundary.
"""
from dataclasses import dataclass, asdict
import json
import unittest

VALID_EFFECT = {"NONE", "UNKNOWN", "CONFIRMED"}
VALID_EVIDENCE = {"CURRENT", "STALE", "MISSING"}
VALID_ACTION = {"LOCAL_REVIEW", "CLOUD_SEND", "PUBLISH"}
VALID_APPROVAL_SOURCE = {"NONE", "UNVERIFIED_SUMMARY", "EXTERNALLY_VERIFIED"}
VALID_APPROVAL_SCOPE = {"NONE", "CLOUD_SEND", "PUBLISH"}


@dataclass(frozen=True)
class Snapshot:
    task_id: str
    effect: str
    evidence: str
    requested_action: str
    shareable: bool
    approval_source: str
    approval_scope: str
    model: str
    schema_version: int = 1


def choose_next(record: Snapshot) -> str:
    """Return a proposal, NEVER perform the proposed operation."""
    if (type(record.schema_version) is not int or record.schema_version != 1
        or type(record.task_id) is not str or not record.task_id
        or type(record.model) is not str or not record.model
        or record.effect not in VALID_EFFECT
        or record.evidence not in VALID_EVIDENCE
        or record.requested_action not in VALID_ACTION
        or type(record.shareable) is not bool
        or record.approval_source not in VALID_APPROVAL_SOURCE
        or record.approval_scope not in VALID_APPROVAL_SCOPE):
        return "HOLD_INVALID_RECORD"
    if record.effect == "UNKNOWN":
        return "HOLD_RECONCILE_EXTERNAL_EFFECT"
    if record.evidence != "CURRENT":
        return "HOLD_VERIFY_SOURCE"
    if record.requested_action == "LOCAL_REVIEW":
        return "LOCAL_REVIEW_CANDIDATE"
    if record.requested_action in {"CLOUD_SEND", "PUBLISH"} and not record.shareable:
        return "DENY_DATA_DISCLOSURE"
    if (record.approval_source != "EXTERNALLY_VERIFIED"
        or record.approval_scope != record.requested_action):
        return "HOLD_APPROVAL_CHECK"
    return "READY_FOR_SEPARATE_EXECUTOR"


def round_trip(record: Snapshot) -> Snapshot:
    """Simulate checkpoint serialization and restart, not authenticated storage."""
    return Snapshot(**json.loads(json.dumps(asdict(record), sort_keys=True)))


class ContinuityGuardTests(unittest.TestCase):
    def setUp(self):
        self.base = dict(task_id="sample-001", effect="NONE", evidence="CURRENT",
                         requested_action="LOCAL_REVIEW", shareable=False,
                         approval_source="NONE", approval_scope="NONE", model="local-2b")

    def route(self, **overrides):
        return choose_next(Snapshot(**(self.base | overrides)))

    def test_01_local_only_review(self):
        self.assertEqual(self.route(), "LOCAL_REVIEW_CANDIDATE")

    def test_02_unknown_external_effect_blocks_everything(self):
        self.assertEqual(self.route(effect="UNKNOWN", requested_action="PUBLISH"),
                         "HOLD_RECONCILE_EXTERNAL_EFFECT")

    def test_03_restart_preserves_hold(self):
        s = Snapshot(**(self.base | {"effect": "UNKNOWN"}))
        self.assertEqual(choose_next(round_trip(s)), "HOLD_RECONCILE_EXTERNAL_EFFECT")

    def test_04_model_swap_does_not_grant_permission(self):
        s = Snapshot(**(self.base | {"requested_action": "PUBLISH", "shareable": True, "model": "cloud-new"}))
        self.assertEqual(choose_next(s), "HOLD_APPROVAL_CHECK")

    def test_05_unverified_summary_cannot_approve(self):
        self.assertEqual(self.route(requested_action="PUBLISH", shareable=True, approval_scope="PUBLISH",
                                    approval_source="UNVERIFIED_SUMMARY"), "HOLD_APPROVAL_CHECK")

    def test_06_stale_evidence_blocks_with_approval(self):
        self.assertEqual(self.route(requested_action="PUBLISH", approval_scope="PUBLISH",
                                    approval_source="EXTERNALLY_VERIFIED", evidence="STALE"),
                         "HOLD_VERIFY_SOURCE")

    def test_07_missing_evidence_blocks(self):
        self.assertEqual(self.route(evidence="MISSING"), "HOLD_VERIFY_SOURCE")

    def test_08_restricted_content_never_goes_to_cloud(self):
        self.assertEqual(self.route(requested_action="CLOUD_SEND", shareable=False,
                                    approval_source="EXTERNALLY_VERIFIED", approval_scope="CLOUD_SEND"),
                         "DENY_DATA_DISCLOSURE")

    def test_09_approval_for_cloud_cannot_publish(self):
        self.assertEqual(self.route(requested_action="PUBLISH", shareable=True,
                                    approval_source="EXTERNALLY_VERIFIED", approval_scope="CLOUD_SEND"),
                         "HOLD_APPROVAL_CHECK")

    def test_10_published_approval_only_proposes_execution(self):
        self.assertEqual(self.route(requested_action="PUBLISH", shareable=True,
                                    approval_source="EXTERNALLY_VERIFIED", approval_scope="PUBLISH"),
                         "READY_FOR_SEPARATE_EXECUTOR")

    def test_11_cloud_approval_only_proposes_execution(self):
        self.assertEqual(self.route(requested_action="CLOUD_SEND", shareable=True,
                                    approval_source="EXTERNALLY_VERIFIED", approval_scope="CLOUD_SEND"),
                         "READY_FOR_SEPARATE_EXECUTOR")

    def test_12_invalid_version_fails_closed(self):
        self.assertEqual(self.route(schema_version=2), "HOLD_INVALID_RECORD")

    def test_13_invalid_effect_fails_closed(self):
        self.assertEqual(self.route(effect="MAYBE"), "HOLD_INVALID_RECORD")

    def test_14_missing_task_id_fails_closed(self):
        self.assertEqual(self.route(task_id=""), "HOLD_INVALID_RECORD")

    def test_15_forged_str_boolean_fails_closed(self):
        self.assertEqual(self.route(shareable="true"), "HOLD_INVALID_RECORD")

    def test_16_checkpoint_new_model_still_holds(self):
        record = round_trip(Snapshot(**(self.base | {
            "requested_action": "PUBLISH", "effect": "UNKNOWN", "model": "cloud-old"})))
        changed = Snapshot(**(asdict(record) | {"model": "cloud-new"}))
        self.assertEqual(choose_next(changed), "HOLD_RECONCILE_EXTERNAL_EFFECT")


    def test_17_restricted_publication_blocked_even_with_approval(self):
        self.assertEqual(self.route(requested_action="PUBLISH", shareable=False,
                                    approval_source="EXTERNALLY_VERIFIED", approval_scope="PUBLISH"),
                         "DENY_DATA_DISCLOSURE")

    def test_18_invalid_approval_source_fails_closed(self):
        self.assertEqual(self.route(approval_source="yes"), "HOLD_INVALID_RECORD")

    def test_19_missing_model_name_fails_closed(self):
        self.assertEqual(self.route(model=""), "HOLD_INVALID_RECORD")

    def test_20_unknown_action_fails_closed(self):
        self.assertEqual(self.route(requested_action="DELETE_FOREVER"), "HOLD_INVALID_RECORD")

    def test_21_task_id_type_must_be_string(self):
        self.assertEqual(self.route(task_id=123), "HOLD_INVALID_RECORD")


if __name__ == "__main__":
    unittest.main(verbosity=2)
