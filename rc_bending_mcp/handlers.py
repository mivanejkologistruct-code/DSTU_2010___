from __future__ import annotations

from math import isclose
from pathlib import Path
from typing import Any

from rc_bending_mcp.adapters import build_catalog_payload
from rc_bending_mcp.artifacts import resolve_output_dir, write_bytes_artifact, write_json_artifact
from rc_bending_mcp.domain import (
    analyze_experimental_workbook_python,
    build_experimental_template_python,
    calculate_section_python,
    calculate_serviceability_python,
)
from rc_bending_mcp.ui_runner import StreamlitUIRunner, UIUnavailableError


SECTION_METRICS = ("peak_moment_kNm", "selected_step", "neutral_axis_mm", "top_strain", "bottom_strain")
SERVICEABILITY_METRICS = ("peak_moment_kNm", "selected_step", "w_k_mm", "deflection_mm")
EXPERIMENTAL_METRICS = ("inspection_status", "loaded_sheet_names")


def execute_get_catalogs() -> dict[str, object]:
    return _build_response(
        status="ok",
        messages=["Loaded calculator catalogs."],
        python_result=build_catalog_payload(),
        ui_result=None,
        comparison=None,
        artifacts=[],
    )


def execute_calculate_section(
    section_input: dict[str, object],
    selected_step: int | None = None,
    output_dir: str | Path | None = None,
    ui_runner: object | None = None,
) -> dict[str, object]:
    try:
        domain = calculate_section_python(section_input, selected_step=selected_step)
    except ValueError as error:
        return _build_response("invalid_input", [str(error)], None, None, None, [])

    run_dir = resolve_output_dir("calculate_section", output_dir)
    artifacts = [
        write_bytes_artifact(run_dir / "bending_results.xlsx", domain["workbook_bytes"], label="Results workbook", kind="xlsx")
    ]
    return _finalize_with_ui(
        output_dir=run_dir,
        python_result=domain["python_result"],
        artifacts=artifacts,
        ui_runner=ui_runner,
        metrics=SECTION_METRICS,
        ui_result_loader=lambda runner: runner.run_section(
            draft_inputs=domain["draft_inputs"],
            selected_step=domain["python_result"]["selected_step"],
            expected_python_result=domain["python_result"],
            output_dir=run_dir,
        ),
        intro_message="Calculated section response through the direct Python path.",
    )


def execute_calculate_serviceability(
    section_input: dict[str, object],
    serviceability_input: dict[str, object],
    selected_step: int | None = None,
    output_dir: str | Path | None = None,
    ui_runner: object | None = None,
) -> dict[str, object]:
    try:
        domain = calculate_serviceability_python(section_input, serviceability_input, selected_step=selected_step)
    except ValueError as error:
        return _build_response("invalid_input", [str(error)], None, None, None, [])

    run_dir = resolve_output_dir("calculate_serviceability", output_dir)
    artifacts = [
        write_bytes_artifact(run_dir / "bending_results.xlsx", domain["workbook_bytes"], label="Results workbook", kind="xlsx")
    ]
    return _finalize_with_ui(
        output_dir=run_dir,
        python_result=domain["python_result"],
        artifacts=artifacts,
        ui_runner=ui_runner,
        metrics=SERVICEABILITY_METRICS,
        ui_result_loader=lambda runner: runner.run_serviceability(
            draft_inputs=domain["draft_inputs"],
            serviceability_draft_inputs=domain["serviceability_draft_inputs"],
            selected_step=domain["python_result"]["selected_step"],
            expected_python_result=domain["python_result"],
            output_dir=run_dir,
        ),
        intro_message="Calculated serviceability response through the direct Python path.",
    )


def execute_analyze_experimental_workbook(
    workbook_path: str,
    section_input: dict[str, object],
    serviceability_input: dict[str, object] | None = None,
    selected_step: int | None = None,
    output_dir: str | Path | None = None,
    ui_runner: object | None = None,
) -> dict[str, object]:
    try:
        domain = analyze_experimental_workbook_python(
            workbook_path,
            section_input,
            serviceability_input,
            selected_step=selected_step,
        )
    except (OSError, ValueError) as error:
        return _build_response("invalid_input", [str(error)], None, None, None, [])

    run_dir = resolve_output_dir("analyze_experimental_workbook", output_dir)
    return _finalize_with_ui(
        output_dir=run_dir,
        python_result=domain["python_result"],
        artifacts=[],
        ui_runner=ui_runner,
        metrics=EXPERIMENTAL_METRICS,
        ui_result_loader=lambda runner: runner.run_experimental(
            draft_inputs=domain["draft_inputs"],
            serviceability_draft_inputs=domain["serviceability_draft_inputs"],
            workbook_path=workbook_path,
            expected_python_result=domain["python_result"],
            output_dir=run_dir,
        ),
        intro_message="Loaded the experimental workbook through the direct Python path.",
    )


def execute_build_experimental_template(output_dir: str | Path | None = None) -> dict[str, object]:
    domain = build_experimental_template_python()
    run_dir = resolve_output_dir("build_experimental_template", output_dir)
    template_path = run_dir / "experimental_curves_template.xlsx"
    artifacts = [
        write_bytes_artifact(template_path, domain["template_bytes"], label="Experimental template", kind="xlsx")
    ]
    response = _build_response(
        "ok",
        ["Experimental template workbook created."],
        {"template_path": str(template_path), **domain["python_result"]},
        None,
        None,
        artifacts,
    )
    response["artifacts"].append(write_json_artifact(run_dir / "summary.json", response, label="Run summary"))
    return response


def _finalize_with_ui(
    *,
    output_dir: Path,
    python_result: dict[str, object],
    artifacts: list[dict[str, str]],
    ui_runner: object | None,
    metrics: tuple[str, ...],
    ui_result_loader,
    intro_message: str,
) -> dict[str, object]:
    messages = [intro_message]
    runner = ui_runner or StreamlitUIRunner()
    try:
        raw_ui_result = ui_result_loader(runner)
    except UIUnavailableError as error:
        response = _build_response("ui_unavailable", messages + [str(error)], python_result, None, None, artifacts)
        response["artifacts"].append(write_json_artifact(output_dir / "summary.json", response, label="Run summary"))
        return response
    except Exception as error:
        response = _build_response("failed", messages + [str(error)], python_result, None, None, artifacts)
        response["artifacts"].append(write_json_artifact(output_dir / "summary.json", response, label="Run summary"))
        return response

    ui_result, ui_artifacts, ui_messages = _normalize_ui_result(raw_ui_result)
    response = _build_response(
        "ok",
        messages + ui_messages,
        python_result,
        ui_result,
        _compare_results(python_result, ui_result, metrics),
        artifacts + ui_artifacts,
    )
    if response["comparison"]["mismatches"]:
        response["status"] = "ui_mismatch"
    response["artifacts"].append(write_json_artifact(output_dir / "summary.json", response, label="Run summary"))
    return response


def _normalize_ui_result(raw_ui_result: Any) -> tuple[dict[str, object], list[dict[str, str]], list[str]]:
    if isinstance(raw_ui_result, dict) and "payload" in raw_ui_result:
        return raw_ui_result["payload"], list(raw_ui_result.get("artifacts", [])), list(raw_ui_result.get("messages", []))
    if not isinstance(raw_ui_result, dict):
        raise ValueError("UI runner returned an unsupported payload type.")
    return raw_ui_result, [], []


def _compare_results(python_result: dict[str, object], ui_result: dict[str, object], metrics: tuple[str, ...]) -> dict[str, object]:
    mismatches: list[dict[str, object]] = []
    checked: list[dict[str, object]] = []
    for metric in metrics:
        python_value = python_result.get(metric)
        ui_value = ui_result.get(metric)
        matched = _values_match(python_value, ui_value)
        checked.append({"metric": metric, "python_value": python_value, "ui_value": ui_value, "matched": matched})
        if not matched:
            mismatches.append({"metric": metric, "python_value": python_value, "ui_value": ui_value})
    return {"matched": not mismatches, "checked_metrics": checked, "mismatches": mismatches}


def _values_match(left: object, right: object) -> bool:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return isclose(float(left), float(right), rel_tol=1e-6, abs_tol=1e-6)
    return left == right


def _build_response(
    status: str,
    messages: list[str],
    python_result: dict[str, object] | None,
    ui_result: dict[str, object] | None,
    comparison: dict[str, object] | None,
    artifacts: list[dict[str, str]],
) -> dict[str, object]:
    return {
        "status": status,
        "messages": messages,
        "python_result": python_result,
        "ui_result": ui_result,
        "comparison": comparison,
        "artifacts": artifacts,
    }
