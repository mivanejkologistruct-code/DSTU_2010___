from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pandas as pd

from rc_bending.experimental_data import (
    build_comparison_table,
    build_experimental_template_workbook_bytes,
    inspect_reference_experimental_workbook,
    inspect_experimental_workbook,
    load_experimental_dataset,
    load_reference_experimental_dataset,
)
from rc_bending.export import build_results_workbook_bytes
from rc_bending.materials import load_material_catalog
from rc_bending.serviceability import (
    build_serviceability_input,
    build_serviceability_report,
    calculate_deflection_mm_from_curvature,
    validate_serviceability_inputs,
)
from rc_bending.solver import solve_bending_capacity
from rc_bending.ui_helpers import build_section_input_from_draft, validate_draft_inputs
from rc_bending_mcp.adapters import build_draft_inputs, build_serviceability_draft_inputs


def calculate_section_python(section_input: dict[str, object], selected_step: int | None = None) -> dict[str, object]:
    catalog = load_material_catalog()
    draft_inputs = build_draft_inputs(section_input)
    validation_errors = validate_draft_inputs(draft_inputs, catalog)
    if validation_errors:
        raise ValueError(validation_errors[0])

    section = build_section_input_from_draft(draft_inputs, catalog)
    result = solve_bending_capacity(section, catalog, outer_steps=int(draft_inputs.get("outer_steps", 40)))
    selected_point = _resolve_selected_point(result, selected_step)
    workbook_bytes = build_results_workbook_bytes(section, catalog, result, selected_point=selected_point)
    python_result = {
        "selected_step": selected_point.step_index,
        "peak_moment_kNm": result.peak_moment_kNm,
        "neutral_axis_mm": selected_point.neutral_axis_mm,
        "top_strain": selected_point.top_strain,
        "bottom_strain": selected_point.bottom_strain,
        "curve_points": [_serialize_curve_point(point) for point in result.curve_points],
        "selected_point": _serialize_curve_point(selected_point),
        "termination": asdict(result.termination),
    }
    return {
        "catalog": catalog,
        "draft_inputs": draft_inputs,
        "section": section,
        "result": result,
        "selected_point": selected_point,
        "python_result": python_result,
        "workbook_bytes": workbook_bytes,
    }


def calculate_serviceability_python(
    section_input: dict[str, object],
    serviceability_input: dict[str, object],
    selected_step: int | None = None,
) -> dict[str, object]:
    base = calculate_section_python(section_input, selected_step=selected_step)
    serviceability_draft_inputs = build_serviceability_draft_inputs(serviceability_input)
    validation_errors = validate_serviceability_inputs(serviceability_draft_inputs)
    if validation_errors:
        raise ValueError(validation_errors[0])

    active_service_input = build_serviceability_input(serviceability_draft_inputs)
    report = build_serviceability_report(
        base["section"],
        base["draft_inputs"],
        base["selected_point"],
        base["catalog"],
        service_input=active_service_input,
    )
    workbook_bytes = build_results_workbook_bytes(
        base["section"],
        base["catalog"],
        base["result"],
        selected_point=base["selected_point"],
        serviceability_report=report,
    )
    theory_tables = _build_theory_tables(
        base["section"],
        base["result"],
        serviceability_draft_inputs,
    )
    python_result = dict(base["python_result"])
    python_result.update(
        {
            "serviceability_input": asdict(report.input),
            "w_k_mm": report.crack_width.w_k_mm,
            "w_limit_mm": report.crack_width.w_limit_mm,
            "is_within_crack_limit": report.crack_width.is_within_limit,
            "deflection_mm": report.deflection.deflection_mm,
            "deflection_limit_mm": report.deflection.limit.limit_mm,
            "is_within_deflection_limit": report.deflection.is_within_limit,
        }
    )
    base.update(
        {
            "serviceability_draft_inputs": serviceability_draft_inputs,
            "serviceability_report": report,
            "theory_tables": theory_tables,
            "python_result": python_result,
            "workbook_bytes": workbook_bytes,
        }
    )
    return base


def analyze_experimental_workbook_python(
    workbook_path: str | Path,
    section_input: dict[str, object],
    serviceability_input: dict[str, object] | None,
    selected_step: int | None = None,
) -> dict[str, object]:
    workbook_file = Path(workbook_path)
    workbook_bytes = workbook_file.read_bytes()
    section_data = calculate_section_python(section_input, selected_step=selected_step)
    if len(section_data["section"].rebar_layers) == 1:
        dataset = load_reference_experimental_dataset(workbook_bytes)
        inspection = inspect_reference_experimental_workbook(workbook_bytes)
    else:
        dataset = load_experimental_dataset(workbook_bytes)
        inspection = inspect_experimental_workbook(workbook_bytes)
    theory_tables = _build_theory_tables(
        section_data["section"],
        section_data["result"],
        build_serviceability_draft_inputs(serviceability_input) if serviceability_input is not None else None,
    )

    comparison_tables: dict[str, list[dict[str, object]]] = {}
    for sheet_name, series in dataset.series.items():
        theory_df = theory_tables.get(sheet_name)
        if theory_df is None:
            comparison_tables[sheet_name] = []
            continue
        comparison_tables[sheet_name] = build_comparison_table(theory_df, series).to_dict(orient="records")

    return {
        "dataset": dataset,
        "inspection": inspection,
        "python_result": {
            "inspection_status": "ready",
            "inspection_message": inspection.message,
            "loaded_sheet_names": sorted(dataset.series.keys()),
            "comparison_tables": comparison_tables,
            "workbook_path": str(workbook_file),
        },
        "draft_inputs": section_data["draft_inputs"],
        "serviceability_draft_inputs": build_serviceability_draft_inputs(serviceability_input),
    }


def build_experimental_template_python() -> dict[str, object]:
    return {
        "template_bytes": build_experimental_template_workbook_bytes(),
        "python_result": {"template_file_name": "experimental_curves_template.xlsx"},
    }


def _resolve_selected_point(result, selected_step: int | None):
    if selected_step is None:
        return result.peak_point
    for point in result.curve_points:
        if point.step_index == selected_step:
            return point
    raise ValueError(f"Selected step {selected_step} was not found in the calculated curve.")


def _serialize_curve_point(point) -> dict[str, object]:
    return {
        "step_index": point.step_index,
        "top_strain": point.top_strain,
        "bottom_strain": point.bottom_strain,
        "curvature_1_per_m": point.curvature_1_per_m,
        "neutral_axis_mm": point.neutral_axis_mm,
        "axial_residual_kN": point.axial_residual_kN,
        "moment_kNm": point.moment_kNm,
        "state_label": point.state_label,
    }


def _strain_at_depth(top_strain: float, bottom_strain: float, z_mm: float, section_height_mm: float) -> float:
    if section_height_mm == 0.0:
        return 0.0
    return top_strain + (bottom_strain - top_strain) * z_mm / section_height_mm


def _pick_extreme_rebar_layers(section) -> tuple[tuple[int, object], tuple[int, object]]:
    indexed_layers = list(enumerate(section.rebar_layers))
    return min(indexed_layers, key=lambda item: item[1].z_mm), max(indexed_layers, key=lambda item: item[1].z_mm)


def _resolve_rebar_display_sign(section, *, rebar_index: int) -> float:
    indexed_layers = list(enumerate(section.rebar_layers))
    if len(indexed_layers) == 1:
        return -1.0
    bottom_rebar_index = max(indexed_layers, key=lambda item: item[1].z_mm)[0]
    return -1.0 if rebar_index == bottom_rebar_index else 1.0


def _build_theory_tables(section, result, serviceability_draft_inputs: dict[str, object] | None) -> dict[str, pd.DataFrame | None]:
    tables: dict[str, pd.DataFrame | None] = {
        "M_eps_c": pd.DataFrame(
            {
                "ε_c,top, 10^-5": [point.top_strain * 100000.0 for point in result.curve_points],
                "M, кН·м": [point.moment_kNm for point in result.curve_points],
            }
        )
    }
    indexed_layers = list(enumerate(section.rebar_layers))
    if len(indexed_layers) == 1:
        rebar_index, rebar = indexed_layers[0]
        display_sign = _resolve_rebar_display_sign(section, rebar_index=rebar_index)
        tables["M_eps_s_bot"] = pd.DataFrame(
            {
                "ε_s, 10^-5": [
                    display_sign
                    * _strain_at_depth(point.top_strain, point.bottom_strain, rebar.z_mm, section.section_height_mm)
                    * 100000.0
                    for point in result.curve_points
                ],
                "M, кН·м": [point.moment_kNm for point in result.curve_points],
            }
        )
    else:
        top_rebar, bottom_rebar = _pick_extreme_rebar_layers(section)
        top_sign = _resolve_rebar_display_sign(section, rebar_index=top_rebar[0])
        bottom_sign = _resolve_rebar_display_sign(section, rebar_index=bottom_rebar[0])
        tables["M_eps_s_top"] = pd.DataFrame(
            {
                "ε_s, 10^-5": [
                    top_sign
                    * _strain_at_depth(point.top_strain, point.bottom_strain, top_rebar[1].z_mm, section.section_height_mm)
                    * 100000.0
                    for point in result.curve_points
                ],
                "M, кН·м": [point.moment_kNm for point in result.curve_points],
            }
        )
        tables["M_eps_s_bot"] = pd.DataFrame(
            {
                "ε_s, 10^-5": [
                    bottom_sign
                    * _strain_at_depth(point.top_strain, point.bottom_strain, bottom_rebar[1].z_mm, section.section_height_mm)
                    * 100000.0
                    for point in result.curve_points
                ],
                "M, кН·м": [point.moment_kNm for point in result.curve_points],
            }
        )
    if serviceability_draft_inputs is None:
        tables["M_f"] = None
        return tables

    service_input = build_serviceability_input(serviceability_draft_inputs)
    tables["M_f"] = pd.DataFrame(
        {
            "f, мм": [
                calculate_deflection_mm_from_curvature(
                    curvature_1_per_m=point.curvature_1_per_m,
                    span_mm=service_input.span_mm,
                    support_scheme=service_input.support_scheme,
                    a_mm=service_input.a_mm,
                    phi_creep=service_input.phi_creep,
                )
                for point in result.curve_points
            ],
            "M, кН·м": [point.moment_kNm for point in result.curve_points],
        }
    )
    return tables
