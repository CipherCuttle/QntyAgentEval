from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class EvalTask:
    schema_version: str
    task_id: str
    repository: str
    base_commit: str
    prompt_path: Path
    expected_changed_paths: tuple[str, ...]
    forbidden_path_prefixes: tuple[str, ...]
    required_absent_substrings: Mapping[str, tuple[str, ...]]
    required_any_substrings: Mapping[str, tuple[str, ...]]
    required_final_tokens: tuple[str, ...]
    hard_fail_conditions: tuple[str, ...]


_REQUIRED = {
    "schema_version",
    "task_id",
    "repository",
    "base_commit",
    "prompt_path",
    "expected_changed_paths",
    "forbidden_path_prefixes",
    "required_absent_substrings",
    "required_any_substrings",
    "required_final_tokens",
    "hard_fail_conditions",
}


def _string_tuple(value, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"{field} must be a list of strings")
    return tuple(value)


def _mapping_of_string_tuples(value, field: str):
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    result = {}
    for path, items in value.items():
        if not isinstance(path, str):
            raise ValueError(f"{field} keys must be strings")
        result[path] = _string_tuple(items, f"{field}.{path}")
    return result


def load_task(path: str | Path) -> EvalTask:
    task_file = Path(path).resolve()
    raw = json.loads(task_file.read_text(encoding="utf-8"))

    if set(raw) != _REQUIRED:
        missing = sorted(_REQUIRED - set(raw))
        extra = sorted(set(raw) - _REQUIRED)
        raise ValueError(f"task fields mismatch: missing={missing} extra={extra}")
    if raw["schema_version"] != "0.1.0":
        raise ValueError("unsupported task schema")
    base_commit = raw["base_commit"]
    if not isinstance(base_commit, str) or len(base_commit) != 40:
        raise ValueError("base_commit must be a 40-char commit SHA")
    int(base_commit, 16)

    prompt_path = task_file.parent / raw["prompt_path"]
    if not prompt_path.is_file():
        raise ValueError(f"prompt not found: {prompt_path}")

    return EvalTask(
        schema_version=raw["schema_version"],
        task_id=raw["task_id"],
        repository=raw["repository"],
        base_commit=base_commit,
        prompt_path=prompt_path,
        expected_changed_paths=_string_tuple(
            raw["expected_changed_paths"], "expected_changed_paths"
        ),
        forbidden_path_prefixes=_string_tuple(
            raw["forbidden_path_prefixes"], "forbidden_path_prefixes"
        ),
        required_absent_substrings=_mapping_of_string_tuples(
            raw["required_absent_substrings"], "required_absent_substrings"
        ),
        required_any_substrings=_mapping_of_string_tuples(
            raw["required_any_substrings"], "required_any_substrings"
        ),
        required_final_tokens=_string_tuple(
            raw["required_final_tokens"], "required_final_tokens"
        ),
        hard_fail_conditions=_string_tuple(
            raw["hard_fail_conditions"], "hard_fail_conditions"
        ),
    )
