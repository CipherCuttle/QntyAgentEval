import json
from datetime import datetime, timezone

from qntyageval.breadth_v2 import (
    EXPECTED_EXCLUDED,
    EXPECTED_FAMILIES,
    EXPECTED_IDENTITIES,
    EXPECTED_VARIANTS,
    MINIMUM_COMPLETE_HOURS,
    EXPECTED_PATHS,
    SEALED_T0,
    _builder_from_observed,
    _canonical_digest,
)
from qntyageval.remote import (
    V2_ISSUE_TITLE,
    V2_TASK_ID,
    parse_request_v2,
)


def observed_values():
    return {
        "CONTRACT_ID": "BREADTH_V2_SEALED_FORWARD_OBSERVATION_V0",
        "CONTRACT_VERSION": "V0",
        "SCREEN_ID": EXPECTED_IDENTITIES["registered_screen_id"],
        "DEVELOPMENT_CAMPAIGN_COMMIT": EXPECTED_IDENTITIES["development_campaign_commit"],
        "DEVELOPMENT_DECISION_IDENTITY": EXPECTED_IDENTITIES["development_decision_identity"],
        "DEVELOPMENT_MANIFEST_IDENTITY": EXPECTED_IDENTITIES["development_manifest_identity"],
        "PREREGISTRATION_COMMIT": EXPECTED_IDENTITIES["preregistration_commit"],
        "PREREGISTRATION_CONTRACT_IDENTITY": "QNTYLAB_BREADTH_V2_20260810",
        "ELIGIBLE_FAMILIES": EXPECTED_FAMILIES,
        "ELIGIBLE_VARIANT_IDS": EXPECTED_VARIANTS,
        "EXCLUDED_DEVELOPMENT_FAIL_FAMILIES": EXPECTED_EXCLUDED,
        "INPUT_UNIVERSE_IDENTITY": EXPECTED_IDENTITIES["input_universe_sha256"],
        "MINIMUM_COMPLETE_HOURS": MINIMUM_COMPLETE_HOURS,
        "_EVIDENCE_TIMESTAMPS": (
            ("input_bundle_materiality_merge", "2026-08-10T18:12:54Z", "d4ad8a3e11d4a58f028c51fca89f903d6186e888"),
        ),
    }


def test_v2_request_is_strict_and_allowlisted():
    body = "QNTY_EVAL_REQUEST_V2\n" + json.dumps({
        "schema_version": "0.3.0", "task_id": V2_TASK_ID,
        "target_repo": "CipherCuttle/QntyLab", "target_sha": "A" * 40,
    }, separators=(",", ":"))
    assert parse_request_v2(V2_ISSUE_TITLE, body)["target_sha"] == "a" * 40


def test_mutating_survivor_changes_evaluator_reconstructed_contract():
    values = observed_values()
    original = _builder_from_observed(values)
    values["ELIGIBLE_VARIANT_IDS"] = {**EXPECTED_VARIANTS, "PRICE_BREAKOUT": EXPECTED_VARIANTS["PRICE_BREAKOUT"][:-1]}
    mutated = _builder_from_observed(values)
    assert mutated["eligible_variant_ids"] != original["eligible_variant_ids"]
    assert mutated["contract_digest"] != original["contract_digest"]


def test_mutating_t0_or_horizon_cannot_reconcile_frozen_expectations():
    values = observed_values()
    values["MINIMUM_COMPLETE_HOURS"] = MINIMUM_COMPLETE_HOURS - 1
    contract = _builder_from_observed(values)
    assert contract["minimum_complete_hours"] != MINIMUM_COMPLETE_HOURS
    assert contract["SEALED_T0"] == SEALED_T0


def test_clock_status_fields_are_excluded_from_identity_digest():
    values = observed_values()
    contract = _builder_from_observed(values)
    identity = {k: v for k, v in contract.items() if k not in {"observation_status", "sealed_adjudication_authorized", "contract_digest"}}
    active = _canonical_digest(identity)
    mature = _canonical_digest(identity)
    assert active == mature == contract["contract_digest"]


def test_unexpected_path_and_artifact_mutations_are_not_reconcilable():
    assert sorted((*EXPECTED_PATHS, "unexpected.txt")) != sorted(EXPECTED_PATHS)
    artifact = _builder_from_observed(observed_values())
    artifact["eligible_families"] = ["PRICE_BREAKOUT"]
    assert artifact["eligible_families"] != list(EXPECTED_FAMILIES)
