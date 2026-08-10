"""Evaluator-owned checks for the one frozen QntyLab Breadth V2 task."""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

TASK_ID = "QNTYLAB_BREADTH_V2_SEALED_FORWARD_OBSERVATION_001"
TARGET_REPO = "CipherCuttle/QntyLab"
BASE_COMMIT = "18be3196f41a5ee38404a6aa9644f02af63e9d9c"
TARGET_COMMIT = "9e6bbb495e9af646d9c3be45cf59ce46ea5573d2"
EXPECTED_PATHS = (
    "experiments/results/breadth_v2_sealed_forward_observation_v0.json",
    "qntylab/breadth_v2_sealed.py",
    "tests/test_breadth_v2_sealed.py",
)
SEALED_T0 = "2026-08-10T19:00:00Z"
MINIMUM_COMPLETE_HOURS = 2160
EARLIEST = "2026-11-08T19:00:00Z"
EXPECTED_FAMILIES = ("MOVING_AVERAGE_TREND", "PRICE_BREAKOUT")
EXPECTED_EXCLUDED = (
    "TIME_SERIES_MOMENTUM", "CROSS_SECTIONAL_MOMENTUM",
    "CROSS_SECTIONAL_REVERSAL", "FUNDING_CARRY", "VOLATILITY_TARGETING",
)
EXPECTED_VARIANTS = {
    "MOVING_AVERAGE_TREND": (
        "variant_d5f7ee106ba428292feacd0b", "variant_2584eb63c90a1aa65da2e006",
        "variant_83dc90d06ac8234aaacd575b", "variant_104b54d3f448e98b07bb104f",
    ),
    "PRICE_BREAKOUT": (
        "variant_ac4a45549606e2d83bad89a9", "variant_057bf9fb96021b54541a31cc",
        "variant_81f0ae4565fe4e93e8ecfa09", "variant_5910c68e1b751a6d26bda998",
    ),
}
EXPECTED_IDENTITIES = {
    "development_campaign_commit": BASE_COMMIT,
    "preregistration_commit": "ca0d1c1272e282ee5e1f5fcbc9bc66b2d75eff83",
    "registered_screen_id": "QNTYLAB_BREADTH_V2_20260810",
    "development_decision_identity": "5aa5a165239a893c2f6eded9c857a3bb107d7c22a807403758fe942ed43d5adb",
    "development_manifest_identity": "c28f7a52a233a9fa2c1b45afd970b8e56c667ce1091844535fb0940f482ce452",
    "input_universe_sha256": "8fef4c02d113027630072bcbb0802e35ab31be17c835aa2ebdae4261265589fb",
}
_UTC = timezone.utc


def _gate(ok: bool, evidence: Any) -> dict[str, Any]:
    return {"pass": bool(ok), "evidence": evidence}


def _show(repo: Path, target: str, path: str) -> str:
    proc = subprocess.run(["git", "-C", str(repo), "show", f"{target}:{path}"],
                          text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise ValueError(f"target file unavailable: {path}")
    return proc.stdout


def _literal_assignments(source: str) -> dict[str, Any]:
    tree = ast.parse(source)
    result: dict[str, Any] = {}
    class ResolveNames(ast.NodeTransformer):
        def visit_Name(self, node: ast.Name):
            if node.id in result:
                return ast.copy_location(ast.Constant(value=result[node.id]), node)
            return node
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                result[node.targets[0].id] = ast.literal_eval(ResolveNames().visit(ast.fix_missing_locations(node.value)))
            except (ValueError, TypeError):
                pass
    return result


def _canonical_digest(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def _builder_from_observed(values: dict[str, Any]) -> dict[str, Any]:
    evidence = [{"kind": k, "timestamp": t, "commit": c} for k, t, c in values["_EVIDENCE_TIMESTAMPS"]]
    t0 = datetime.fromisoformat(SEALED_T0.replace("Z", "+00:00"))
    contract: dict[str, Any] = {
        "contract_id": values["CONTRACT_ID"], "contract_version": values["CONTRACT_VERSION"],
        "registered_screen_id": values["SCREEN_ID"],
        "development_campaign_commit": values["DEVELOPMENT_CAMPAIGN_COMMIT"],
        "development_decision_identity": values["DEVELOPMENT_DECISION_IDENTITY"],
        "development_manifest_identity": values["DEVELOPMENT_MANIFEST_IDENTITY"],
        "preregistration_commit": values["PREREGISTRATION_COMMIT"],
        "preregistration_contract_identity": values["PREREGISTRATION_CONTRACT_IDENTITY"],
        "eligible_families": list(values["ELIGIBLE_FAMILIES"]),
        "eligible_variant_ids": {k: list(v) for k, v in values["ELIGIBLE_VARIANT_IDS"].items()},
        "excluded_development_fail_families": list(values["EXCLUDED_DEVELOPMENT_FAIL_FAMILIES"]),
        "source_contracts": {"input_universe": {"id": "BREADTH_V2_DEV_INPUT_UNIVERSE_V0R1", "sha256": values["INPUT_UNIVERSE_IDENTITY"]}, "price": "BINANCE_USDM_PERPETUAL_1H_OHLCV", "funding": "BINANCE_USDM_FUNDING_SETTLEMENT_MATERIALIZER_V0"},
        "benchmark_contracts": {family: "BUY_AND_HOLD_PRIMARY_CASH_SECONDARY" for family in values["ELIGIBLE_FAMILIES"]},
        "cost_modes": {"BASELINE_EXECUTION": {"fee_bps": 10, "slippage_bps": 0}, "STRESS_EXECUTION": {"fee_bps": 10, "slippage_bps": 10}},
        "accounting_kernel_identity": "BREADTH_V2_PORTFOLIO_KERNEL_V0",
        "SEALED_T0": SEALED_T0, "SEALED_T0_derivation_evidence": evidence,
        "minimum_complete_hours": values["MINIMUM_COMPLETE_HOURS"],
        "earliest_eligible_adjudication_time": (t0 + timedelta(hours=values["MINIMUM_COMPLETE_HOURS"])).isoformat().replace("+00:00", "Z"),
        "observation_status": "SEALED_OBSERVATION_ACTIVE", 
        "historical_holdout_policy": "FORWARD_TIME_ONLY;_2023_AND_HISTORICAL_2026_ARE_NOT_FRESH_HOLDOUTS",
        "retrospective_holdout_prohibited": True, "sealed_adjudication_authorized": False,
    }
    identity = {k: v for k, v in contract.items() if k not in {"observation_status", "sealed_adjudication_authorized"}}
    contract["contract_digest"] = _canonical_digest(identity)
    return contract


def _source_semantics(source: str) -> dict[str, bool]:
    tree = ast.parse(source)
    funcs = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    build = ast.unparse(funcs.get("build_contract")) if "build_contract" in funcs else ""
    normalized = build.replace("'", '"').replace(" ", "")
    return {
        "caller_t0_not_accepted": "as_of:datetime|None=None" in normalized and "t0=" not in normalized,
        "clock_only_status": '"observation_status"' in normalized and '"sealed_adjudication_authorized"' in normalized,
        "digest_excludes_status": 'knotin{"observation_status","sealed_adjudication_authorized"}' in normalized,
        "maturity_is_horizon": "adjudication_is_authorized(as_of)" in build and "as_of is not None" in build,
        "t0_is_evidence_derived": "_EVIDENCE_TIMESTAMPS" in source and "derive_sealed_t0" in source,
    }


def evaluate_target(repo: Path, target_sha: str) -> dict[str, Any]:
    paths_proc = subprocess.run(["git", "-C", str(repo), "diff", "--name-status", BASE_COMMIT, target_sha], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    rows = [line.split("\t", 1) for line in paths_proc.stdout.splitlines() if line]
    paths = [row[1] for row in rows if len(row) == 2]
    source = _show(repo, target_sha, "qntylab/breadth_v2_sealed.py") if paths_proc.returncode == 0 else ""
    artifact_text = _show(repo, target_sha, EXPECTED_PATHS[0]) if paths_proc.returncode == 0 else ""
    values = _literal_assignments(source) if source else {}
    try:
        artifact = json.loads(artifact_text)
    except (json.JSONDecodeError, TypeError):
        artifact = None
    ancestry = subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", BASE_COMMIT, target_sha]).returncode == 0
    identity = {"repository": TARGET_REPO, "base": BASE_COMMIT, "target": target_sha, "ancestor": ancestry}
    exact_target = target_sha == TARGET_COMMIT
    exact_rows = sorted((status, path) for status, path in rows) == sorted(("A", path) for path in EXPECTED_PATHS)
    gates: dict[str, dict[str, Any]] = {
        "E1": _gate(exact_target and ancestry, identity),
        "E2": _gate(exact_rows, {"expected": list(EXPECTED_PATHS), "actual": rows}),
        "E3": _gate(exact_rows, {"pre_existing_changes": [p for s, p in rows if p not in EXPECTED_PATHS]}),
    }
    expected_ids = {
        "DEVELOPMENT_CAMPAIGN_COMMIT": EXPECTED_IDENTITIES["development_campaign_commit"],
        "PREREGISTRATION_COMMIT": EXPECTED_IDENTITIES["preregistration_commit"],
        "SCREEN_ID": EXPECTED_IDENTITIES["registered_screen_id"],
        "DEVELOPMENT_DECISION_IDENTITY": EXPECTED_IDENTITIES["development_decision_identity"],
        "DEVELOPMENT_MANIFEST_IDENTITY": EXPECTED_IDENTITIES["development_manifest_identity"],
        "INPUT_UNIVERSE_IDENTITY": EXPECTED_IDENTITIES["input_universe_sha256"],
    }
    ids_ok = all(values.get(k) == v for k, v in expected_ids.items())
    gates["E4"] = _gate(ids_ok, {k: values.get(k) for k in expected_ids})
    gates["E5"] = _gate(values.get("ELIGIBLE_FAMILIES") == EXPECTED_FAMILIES and values.get("ELIGIBLE_VARIANT_IDS") == EXPECTED_VARIANTS, {"families": values.get("ELIGIBLE_FAMILIES"), "variants": values.get("ELIGIBLE_VARIANT_IDS")})
    gates["E6"] = _gate(values.get("EXCLUDED_DEVELOPMENT_FAIL_FAMILIES") == EXPECTED_EXCLUDED and set(values.get("ELIGIBLE_VARIANT_IDS", {})) == set(EXPECTED_FAMILIES), values.get("EXCLUDED_DEVELOPMENT_FAIL_FAMILIES"))
    evidence = values.get("_EVIDENCE_TIMESTAMPS", ())
    latest = max((datetime.fromisoformat(t.replace("Z", "+00:00")) for _, t, _ in evidence), default=None)
    derived = (latest.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)).isoformat().replace("+00:00", "Z") if latest else None
    gates["E7"] = _gate(derived == SEALED_T0 and "derive_sealed_t0" in source, {"derived_t0": derived, "expected": SEALED_T0})
    observed_earliest = None
    if values.get("MINIMUM_COMPLETE_HOURS") is not None:
        observed_earliest = (datetime.fromisoformat(SEALED_T0.replace("Z", "+00:00")) + timedelta(hours=values["MINIMUM_COMPLETE_HOURS"])).isoformat().replace("+00:00", "Z")
    gates["E8"] = _gate(values.get("MINIMUM_COMPLETE_HOURS") == MINIMUM_COMPLETE_HOURS and observed_earliest == EARLIEST, {"minimum_complete_hours": values.get("MINIMUM_COMPLETE_HOURS"), "earliest": observed_earliest})
    gates["E9"] = _gate(artifact is not None and artifact.get("retrospective_holdout_prohibited") is True and "FORWARD_TIME_ONLY" in str(artifact.get("historical_holdout_policy")), {"policy": artifact.get("historical_holdout_policy") if artifact else None})
    semantics = _source_semantics(source) if source else {}
    gates["E10"] = _gate(all(semantics.values()), semantics)
    built = _builder_from_observed(values) if values else None
    gates["E11"] = _gate(artifact == built and artifact is not None, {"artifact_digest": artifact.get("contract_digest") if artifact else None, "builder_digest": built.get("contract_digest") if built else None})
    gates["E12"] = _gate(True, {"scorer": "evaluator-owned", "target_verdict_used": False, "target_mutated": False})
    return {"hard_gates": gates, "pass": all(g["pass"] for g in gates.values()), "changed_paths": paths}
