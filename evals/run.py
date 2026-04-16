"""Run deterministic regression evals for high-risk agent behaviors."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.messages import ToolMessage

from onboarding_agent.mcp_server.tools_tracker import _resolve_stage_for_update
from onboarding_agent.observability.evals import evaluate_agent_response


@dataclass(frozen=True)
class EvalOutcome:
    name: str
    passed: bool
    reason: str


def main() -> int:
    parser = argparse.ArgumentParser(description="Run onboarding-agent regression evals.")
    parser.add_argument(
        "--cases-dir",
        default=str(Path(__file__).with_name("cases")),
        help="Directory containing JSON eval case files.",
    )
    args = parser.parse_args()

    outcomes = run_cases(Path(args.cases_dir))
    for outcome in outcomes:
        status = "PASS" if outcome.passed else "FAIL"
        print(f"{status} {outcome.name}: {outcome.reason}")
    return 0 if all(outcome.passed for outcome in outcomes) else 1


def run_cases(cases_dir: Path) -> list[EvalOutcome]:
    outcomes: list[EvalOutcome] = []
    for path in sorted(cases_dir.glob("*.json")):
        with path.open(encoding="utf-8") as handle:
            case = json.load(handle)
        if not isinstance(case, dict):
            outcomes.append(EvalOutcome(path.name, False, "Case file must contain a JSON object."))
            continue
        outcomes.append(run_case(case, source=path.name))
    return outcomes


def run_case(case: dict[str, Any], *, source: str = "") -> EvalOutcome:
    name = str(case.get("name") or source or "unnamed")
    case_type = str(case.get("type") or "").strip()
    if case_type == "trace_behavior":
        return _run_trace_behavior_case(name, case)
    if case_type == "stage_resolution":
        return _run_stage_resolution_case(name, case)
    if case_type == "vacancy_filter":
        return _run_vacancy_filter_case(name, case)
    return EvalOutcome(name, False, f"Unsupported case type: {case_type or '<missing>'}.")


def _run_trace_behavior_case(name: str, case: dict[str, Any]) -> EvalOutcome:
    messages = [
        ToolMessage(
            content=json.dumps(message.get("content", {}), sort_keys=True),
            tool_call_id=str(index),
            name=str(message.get("name", "")),
        )
        for index, message in enumerate(case.get("tool_messages", []), start=1)
        if isinstance(message, dict)
    ]
    results = evaluate_agent_response(messages, str(case.get("reply_text", "")))
    result_by_name = {result.name: result for result in results}
    expected = case.get("expected_evals", {})
    if not isinstance(expected, dict):
        return EvalOutcome(name, False, "expected_evals must be an object.")
    for eval_name, expected_passed in expected.items():
        result = result_by_name.get(str(eval_name))
        if result is None:
            return EvalOutcome(name, False, f"Eval {eval_name} did not run.")
        if result.passed is not bool(expected_passed):
            return EvalOutcome(
                name,
                False,
                f"Eval {eval_name} expected {bool(expected_passed)} but got {result.passed}: {result.reason}",
            )
    payload_expectations = case.get("payload_contains", [])
    if isinstance(payload_expectations, list):
        for expected_payload in payload_expectations:
            if not isinstance(expected_payload, dict):
                continue
            if not _any_payload_contains(messages, expected_payload):
                return EvalOutcome(name, False, f"No tool payload contained {expected_payload}.")
    return EvalOutcome(name, True, "Trace behavior matched expected eval outcomes.")


def _run_stage_resolution_case(name: str, case: dict[str, Any]) -> EvalOutcome:
    result = _resolve_stage_for_update(str(case.get("input", "")))
    expected_field = str(case.get("expected_field", ""))
    if bool(result.get("success")) is not bool(case.get("expected_success", True)):
        return EvalOutcome(name, False, f"Expected success={case.get('expected_success')} but got {result}.")
    if expected_field and str(result.get("field", "")) != expected_field:
        return EvalOutcome(name, False, f"Expected {expected_field!r} but got {result.get('field')!r}.")
    return EvalOutcome(name, True, "Stage resolver matched expected canonical field.")


def _run_vacancy_filter_case(name: str, case: dict[str, Any]) -> EvalOutcome:
    categories = case.get("categories", [])
    if not isinstance(categories, list):
        return EvalOutcome(name, False, "categories must be a list.")
    vacancies = [
        str(category.get("group", ""))
        for category in categories
        if isinstance(category, dict)
        and int(category.get("current_count", 0)) < int(category.get("max_capacity", 0))
    ]
    expected = [str(value) for value in case.get("expected_vacancies", [])]
    if vacancies != expected:
        return EvalOutcome(name, False, f"Expected vacancies {expected}, got {vacancies}.")
    return EvalOutcome(name, True, "Vacancy filter excluded full and over-capacity groups.")


def _any_payload_contains(messages: list[ToolMessage], expected: dict[str, Any]) -> bool:
    for message in messages:
        try:
            payload = json.loads(str(message.content))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and all(payload.get(key) == value for key, value in expected.items()):
            return True
    return False


if __name__ == "__main__":
    sys.exit(main())
