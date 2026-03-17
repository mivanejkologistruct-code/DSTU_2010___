from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass
from html import escape
import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st
import altair as alt

from rc_bending.experimental_data import (
    DetectedExperimentalBlock,
    ExperimentalDataset,
    SUPPORTED_EXPERIMENTAL_SHEETS,
    WorkbookInspectionResult,
    _load_legacy_supported_dataset,
    build_comparison_table,
    build_experimental_template_workbook_bytes,
    inspect_experimental_workbook,
    load_experimental_dataset,
)
from rc_bending.export import build_results_workbook_bytes
from rc_bending.materials import load_material_catalog
from rc_bending.models import ChartLimitAnnotation
from rc_bending.section_drawing import build_section_drawing_svg
from rc_bending.serviceability_drawing import build_serviceability_scheme_svg
from rc_bending.serviceability import (
    DEFLECTION_LIMIT_PROFILE_LABELS,
    LOAD_DURATION_LABELS,
    SUPPORT_SCHEME_LABELS,
    build_serviceability_input,
    build_serviceability_report,
    calculate_deflection_mm_from_curvature,
    validate_serviceability_inputs,
)
from rc_bending.solver import build_layer_force_table, solve_bending_capacity
from rc_bending.ui_helpers import (
    BOTTOM_FACE,
    TOP_FACE,
    build_section_input_from_draft,
    copy_draft_inputs,
    default_draft_inputs,
    default_serviceability_inputs,
    derive_draft_geometry,
    validate_draft_inputs,
)
from rc_bending_mcp.adapters import build_draft_inputs as build_mcp_draft_inputs
from rc_bending_mcp.adapters import build_serviceability_draft_inputs as build_mcp_serviceability_draft_inputs

AUTHOR_PROFILES = (
    {
        "name": "Іванейко М.М.",
        "role": "Автор проєкту.",
        "description": "Співавтор концепції застосунку та структури подання розрахункової методики.",
    },
    {
        "name": "Іванейко В.М.",
        "role": "Автор проєкту.",
        "description": "Співавтор прикладного сценарію використання та інженерної інтерпретації результатів.",
    },
)


@dataclass(frozen=True)
class ChartAnnotationOverlay:
    annotation: ChartLimitAnnotation
    color: str
    text_mode: str = "symbol"
    label_position: str = "above"
    label_text: str | None = None
    manual_dx: int = 0
    manual_dy: int = 0


@dataclass(frozen=True)
class DeflectionReferenceState:
    deflection_mm: float
    moment_kNm: float | None
    concrete_strain_e5: float | None
    top_rebar_strain_e5: float | None
    bottom_rebar_strain_e5: float | None
    within_range: bool


CHART_LABEL_OFFSET_SUBJECTS = {
    "concrete_moment_strain": {
        "limit": "граничної деформації бетону",
        "max": "εmax бетону",
    },
    "top_rebar_moment_strain": {
        "limit": "граничної деформації верхньої арматури",
        "max": "εmax верхньої арматури",
    },
    "bottom_rebar_moment_strain": {
        "limit": "граничної деформації нижньої арматури",
        "max": "εmax нижньої арматури",
    },
    "deflection_mf": {
        "limit": "нормативної межі прогину",
    },
}

EXPERIMENTAL_CHART_CONFIG = {
    "deflection_mf": {"sheet_name": "M_f", "x_field": "f, мм"},
    "concrete_moment_strain": {"sheet_name": "M_eps_c", "x_field": "ε_c,top, 10^-5"},
    "top_rebar_moment_strain": {"sheet_name": "M_eps_s_top", "x_field": "ε_s, 10^-5"},
    "bottom_rebar_moment_strain": {"sheet_name": "M_eps_s_bot", "x_field": "ε_s, 10^-5"},
}

EXPERIMENTAL_OVERLAY_COLOR = "#b45309"
THEORY_OVERLAY_COLOR = "#1d4ed8"


def _to_promille(value: float) -> float:
    return value * 1000.0


def _to_strain_e5(value: float) -> float:
    return value * 100000.0


def _format_optional_number(value: float | int | None, *, digits: int = 2) -> str:
    if value is None:
        return "не застосовується"
    if isinstance(value, int):
        return str(value)
    return f"{value:.{digits}f}"


def _default_chart_label_offsets() -> dict[str, dict[str, dict[str, int]]]:
    return {
        chart_id: {annotation_id: {"dx": 0, "dy": 0} for annotation_id in annotations}
        for chart_id, annotations in CHART_LABEL_OFFSET_SUBJECTS.items()
    }


def _is_offset_leaf(candidate: object) -> bool:
    return (
        isinstance(candidate, dict)
        and isinstance(candidate.get("dx"), int)
        and isinstance(candidate.get("dy"), int)
    )


def _load_chart_label_offsets() -> dict[str, dict[str, dict[str, int]]]:
    defaults = _default_chart_label_offsets()
    candidate = st.session_state.get("chart_label_offsets")
    merged_offsets = _default_chart_label_offsets()

    if isinstance(candidate, dict):
        for chart_id, annotation_subjects in CHART_LABEL_OFFSET_SUBJECTS.items():
            chart_candidate = candidate.get(chart_id)
            if _is_offset_leaf(chart_candidate):
                legacy_offset = {"dx": int(chart_candidate["dx"]), "dy": int(chart_candidate["dy"])}
                for annotation_id in annotation_subjects:
                    merged_offsets[chart_id][annotation_id] = dict(legacy_offset)
                continue
            if not isinstance(chart_candidate, dict):
                continue
            for annotation_id in annotation_subjects:
                annotation_candidate = chart_candidate.get(annotation_id)
                if _is_offset_leaf(annotation_candidate):
                    merged_offsets[chart_id][annotation_id] = {
                        "dx": int(annotation_candidate["dx"]),
                        "dy": int(annotation_candidate["dy"]),
                    }

    st.session_state.chart_label_offsets = merged_offsets
    return st.session_state.chart_label_offsets


def _render_chart_label_offset_controls(
    chart_label_offsets: dict[str, dict[str, dict[str, int]]],
    *,
    chart_id: str,
) -> dict[str, dict[str, int]]:
    annotation_subjects = CHART_LABEL_OFFSET_SUBJECTS[chart_id]
    current_offsets = chart_label_offsets.get(chart_id, {})
    st.caption("Якщо підпис накладається на криву, скоригуйте його вручну по осях X та Y.")
    chart_label_offsets[chart_id] = {}
    for annotation_id, subject in annotation_subjects.items():
        annotation_offsets = current_offsets.get(annotation_id, {"dx": 0, "dy": 0})
        st.markdown(f"**Підпис: {subject}**")
        dx_col, dy_col = st.columns(2)
        dx_value = dx_col.slider(
            f"Зсув X підпису {subject}",
            min_value=-80,
            max_value=80,
            value=int(annotation_offsets["dx"]),
            step=1,
            key=f"chart_label_offset_{chart_id}_{annotation_id}_dx",
        )
        dy_value = dy_col.slider(
            f"Зсув Y підпису {subject}",
            min_value=-80,
            max_value=80,
            value=int(annotation_offsets["dy"]),
            step=1,
            key=f"chart_label_offset_{chart_id}_{annotation_id}_dy",
        )
        chart_label_offsets[chart_id][annotation_id] = {"dx": int(dx_value), "dy": int(dy_value)}
    st.session_state.chart_label_offsets = chart_label_offsets
    return chart_label_offsets[chart_id]


def _resolve_selected_step(result) -> int:
    default_step = result.curve_points[-1].step_index
    candidate = st.session_state.get("selected_curve_step", default_step)
    try:
        selected_step = int(candidate)
    except (TypeError, ValueError):
        selected_step = default_step
    step_indexes = {point.step_index for point in result.curve_points}
    if selected_step not in step_indexes:
        selected_step = default_step
        st.session_state.selected_curve_step = selected_step
    return selected_step


def _strain_at_depth(top_strain: float, bottom_strain: float, z_mm: float, section_height_mm: float) -> float:
    if section_height_mm == 0.0:
        return 0.0
    return top_strain + (bottom_strain - top_strain) * z_mm / section_height_mm


def _sort_chart_df(df: pd.DataFrame, *, x_field: str) -> pd.DataFrame:
    return df.sort_values(by=[x_field, "Крок"], kind="mergesort").reset_index(drop=True)


def _load_experimental_dataset_from_session() -> tuple[ExperimentalDataset | None, str | None]:
    workbook_bytes = st.session_state.get("experimental_workbook_bytes")
    if not isinstance(workbook_bytes, (bytes, bytearray)) or not workbook_bytes:
        return None, None
    try:
        return load_experimental_dataset(bytes(workbook_bytes)), None
    except ValueError as error:
        return None, str(error)


def _load_pending_experimental_inspection(
    state: MutableMapping[str, object],
) -> tuple[WorkbookInspectionResult | None, str | None]:
    workbook_bytes = state.get("experimental_pending_workbook_bytes")
    if not isinstance(workbook_bytes, (bytes, bytearray)) or not workbook_bytes:
        return None, None
    inspection = state.get("experimental_pending_inspection")
    if not isinstance(inspection, WorkbookInspectionResult):
        inspection = inspect_experimental_workbook(bytes(workbook_bytes))
        state["experimental_pending_inspection"] = inspection
    file_name = state.get("experimental_pending_workbook_name")
    return inspection, str(file_name) if file_name else None


def _load_pending_experimental_inspection_from_session() -> tuple[WorkbookInspectionResult | None, str | None]:
    return _load_pending_experimental_inspection(st.session_state)


def _clear_pending_experimental_upload_state(state: MutableMapping[str, object]) -> None:
    for key in (
        "experimental_pending_workbook_bytes",
        "experimental_pending_workbook_name",
        "experimental_pending_inspection",
    ):
        state.pop(key, None)


def _apply_uploaded_experimental_workbook(
    state: MutableMapping[str, object],
    *,
    workbook_bytes: bytes,
    file_name: str,
) -> str | None:
    try:
        legacy_dataset = _load_legacy_supported_dataset(workbook_bytes)
    except ValueError as error:
        _clear_pending_experimental_upload_state(state)
        return str(error)

    if legacy_dataset is not None:
        state["experimental_workbook_bytes"] = workbook_bytes
        state["experimental_workbook_name"] = file_name
        _clear_pending_experimental_upload_state(state)
        return None

    inspection = inspect_experimental_workbook(workbook_bytes)
    state["experimental_pending_workbook_bytes"] = workbook_bytes
    state["experimental_pending_workbook_name"] = file_name
    state["experimental_pending_inspection"] = inspection
    return None if inspection.status == "ready" and inspection.dataset is not None else inspection.message


def _confirm_pending_experimental_workbook(state: MutableMapping[str, object]) -> str | None:
    inspection, pending_file_name = _load_pending_experimental_inspection(state)
    workbook_bytes = state.get("experimental_pending_workbook_bytes")
    if not isinstance(workbook_bytes, (bytes, bytearray)) or not workbook_bytes or inspection is None:
        return "Немає підготовленого Excel-файлу для підтвердження."
    if inspection.status != "ready" or inspection.dataset is None:
        return inspection.message

    state["experimental_workbook_bytes"] = bytes(workbook_bytes)
    state["experimental_workbook_name"] = pending_file_name or "Без назви"
    _clear_pending_experimental_upload_state(state)
    return None


def _clear_experimental_dataset_state() -> None:
    _clear_pending_experimental_upload_state(st.session_state)
    for key in ("experimental_workbook_bytes", "experimental_workbook_name", "experimental_workbook_upload"):
        st.session_state.pop(key, None)


def _build_detected_experimental_block_html(block: DetectedExperimentalBlock) -> str:
    preview_rows = "; ".join(
        f"{escape(str(left_value))} | {escape(str(right_value))}" for left_value, right_value in block.preview_rows
    )
    evidence = ", ".join(escape(label) for label in block.evidence_labels)
    fragments = [
        '<div class="experimental-upload-status__block" data-role="experimental-detected-block">',
        (
            '<div class="experimental-upload-status__meta">'
            f"{escape(block.target_graph)}: {escape(block.cell_range)}"
            "</div>"
        ),
        (
            '<div class="experimental-upload-status__meta">'
            f"Аркуш: {escape(block.sheet_name)}; шапка: {escape(block.headers[0])} / {escape(block.headers[1])}."
            "</div>"
        ),
    ]
    if evidence:
        fragments.append(
            '<div class="experimental-upload-status__meta">'
            f"Ознаки збігу: {evidence}."
            "</div>"
        )
    if preview_rows:
        fragments.append(
            '<div class="experimental-upload-status__meta">'
            f"Прев’ю: {preview_rows}."
            "</div>"
        )
    fragments.append("</div>")
    return "".join(fragments)


def _build_experimental_pending_action_html(*, inspection: WorkbookInspectionResult) -> str:
    if inspection.status == "ready" and inspection.dataset is not None:
        message = (
            "Графіки ще не показуються, бо файл лише проаналізовано. "
            "Натисніть кнопку `Підтвердити та показати графіки`, щоб зробити ці дані активними."
        )
    else:
        message = (
            "Графіки ще не показуються, бо цей файл ще не можна підтвердити. "
            "Перевірте відсутні або конфліктні блоки й завантажте уточнений Excel."
        )
    return (
        '<div class="experimental-upload-status__action" data-role="experimental-upload-action">'
        f"{escape(message)}"
        "</div>"
    )


def _build_experimental_upload_status_html(
    dataset: ExperimentalDataset | None,
    *,
    file_name: str | None,
    error_message: str | None,
    pending_inspection: WorkbookInspectionResult | None = None,
    pending_file_name: str | None = None,
) -> str:
    fragments = ['<section class="experimental-upload-status" data-role="experimental-upload-status">']
    if error_message:
        fragments.append(f'<div class="experimental-upload-status__error">{escape(error_message)}</div>')

    if pending_inspection is not None:
        pending_name = pending_file_name or "Без назви"
        fragments.extend(
            [
                (
                    '<div class="experimental-upload-status__title" data-role="experimental-upload-pending">'
                    f"Очікує підтвердження: {escape(pending_name)}"
                    "</div>"
                ),
                (
                    '<div class="experimental-upload-status__meta">'
                    f"Результат аналізу: {escape(pending_inspection.message)}"
                    "</div>"
                ),
            ]
        )
        fragments.append(_build_experimental_pending_action_html(inspection=pending_inspection))
        if pending_inspection.detected_blocks:
            fragments.extend(
                _build_detected_experimental_block_html(block) for block in pending_inspection.detected_blocks
            )
        if pending_inspection.missing_graphs:
            fragments.append(
                '<div class="experimental-upload-status__meta">'
                f"Не знайдено: {escape(', '.join(pending_inspection.missing_graphs))}."
                "</div>"
            )
        if pending_inspection.conflicts:
            conflicts_text = "; ".join(
                f"{target_graph}: {', '.join(cell_ranges)}"
                for target_graph, cell_ranges in pending_inspection.conflicts.items()
            )
            fragments.append(
                '<div class="experimental-upload-status__meta">'
                f"Конфлікти: {escape(conflicts_text)}."
                "</div>"
            )
        if dataset is not None and file_name:
            fragments.append(
                '<div class="experimental-upload-status__meta">'
                f"Активний файл поки що не змінено: {escape(file_name)}."
                "</div>"
            )
    elif dataset is None:
        fragments.extend(
            [
                '<div class="experimental-upload-status__title">Файл експериментальних кривих не завантажено.</div>',
                (
                    '<div class="experimental-upload-status__meta">Очікувані аркуші: '
                    f"{escape(', '.join(SUPPORTED_EXPERIMENTAL_SHEETS))}.</div>"
                ),
            ]
        )
    else:
        recognized = list(dataset.series)
        missing = [sheet_name for sheet_name in SUPPORTED_EXPERIMENTAL_SHEETS if sheet_name not in dataset.series]
        active_name = file_name or "Без назви"
        fragments.extend(
            [
                f'<div class="experimental-upload-status__title">Активний файл: {escape(active_name)}</div>',
                (
                    '<div class="experimental-upload-status__meta">Розпізнано аркуші: '
                    f"{escape(', '.join(recognized))}.</div>"
                ),
            ]
        )
        if missing:
            fragments.append(
                '<div class="experimental-upload-status__meta">Ще не завантажено: '
                f"{escape(', '.join(missing))}.</div>"
            )
        if dataset.ignored_sheets:
            fragments.append(
                '<div class="experimental-upload-status__meta">Проігноровано аркуші: '
                f"{escape(', '.join(dataset.ignored_sheets))}.</div>"
            )
        fragments.append(
            '<div class="experimental-upload-status__meta">'
            "Підтримуються канонічний шаблон Excel або сирий лабораторний Excel з 4 таблицями на одному аркуші."
            "</div>"
        )

    fragments.append("</section>")
    return "".join(fragments)


def _experimental_chart_df(dataset: ExperimentalDataset | None, *, chart_id: str) -> pd.DataFrame | None:
    if dataset is None:
        return None
    config = EXPERIMENTAL_CHART_CONFIG[chart_id]
    return dataset.get_chart_df(config["sheet_name"])


def _render_experimental_comparison(
    theory_df: pd.DataFrame,
    *,
    dataset: ExperimentalDataset | None,
    chart_id: str,
) -> None:
    if dataset is None:
        return

    config = EXPERIMENTAL_CHART_CONFIG[chart_id]
    series = dataset.series.get(config["sheet_name"])
    if series is None:
        st.markdown(
            '<div class="chart-note" data-role="experimental-missing-note">'
            "Експериментальні дані для цього графіка не завантажені."
            "</div>",
            unsafe_allow_html=True,
        )
        return

    st.caption("Таблиця відхилень між експериментом і теоретичною кривою для однакових значень осі X.")
    st.dataframe(build_comparison_table(theory_df, series), width="stretch", hide_index=True)


def _build_curve_chart_df(result) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Крок": [point.step_index for point in result.curve_points],
            "M, кН·м": [point.moment_kNm for point in result.curve_points],
            "κ, 1/м": [point.curvature_1_per_m for point in result.curve_points],
            "ε_c,top, 10^-5": [_to_strain_e5(point.top_strain) for point in result.curve_points],
            "ε_c,bot, 10^-5": [_to_strain_e5(point.bottom_strain) for point in result.curve_points],
        }
    )


def _build_deflection_curve_df(result, service_input) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Крок": [point.step_index for point in result.curve_points],
            "M, кН·м": [point.moment_kNm for point in result.curve_points],
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
        }
    )


def _build_theoretical_deflection_reference_df(
    deflection_curve_df: pd.DataFrame,
    concrete_moment_df: pd.DataFrame,
    top_rebar_df: pd.DataFrame,
    bottom_rebar_df: pd.DataFrame,
) -> pd.DataFrame:
    return (
        deflection_curve_df.loc[:, ["Крок", "M, кН·м", "f, мм"]]
        .merge(concrete_moment_df.loc[:, ["Крок", "ε_c,top, 10^-5"]], on="Крок", how="inner")
        .merge(
            top_rebar_df.loc[:, ["Крок", "ε_s, 10^-5"]].rename(columns={"ε_s, 10^-5": "ε_s,top, 10^-5"}),
            on="Крок",
            how="inner",
        )
        .merge(
            bottom_rebar_df.loc[:, ["Крок", "ε_s, 10^-5"]].rename(columns={"ε_s, 10^-5": "ε_s,bot, 10^-5"}),
            on="Крок",
            how="inner",
        )
        .sort_values(by="Крок", kind="mergesort")
        .reset_index(drop=True)
    )


def _interpolate_series_value(
    left_x: float,
    right_x: float,
    left_value: float,
    right_value: float,
    target_x: float,
) -> float:
    if abs(right_x - left_x) <= 1e-9:
        return right_value
    ratio = (target_x - left_x) / (right_x - left_x)
    return left_value + ratio * (right_value - left_value)


def _build_theoretical_state_at_deflection(
    theory_df: pd.DataFrame,
    *,
    target_deflection_mm: float,
) -> DeflectionReferenceState:
    empty_state = DeflectionReferenceState(
        deflection_mm=target_deflection_mm,
        moment_kNm=None,
        concrete_strain_e5=None,
        top_rebar_strain_e5=None,
        bottom_rebar_strain_e5=None,
        within_range=False,
    )
    if theory_df.empty:
        return empty_state

    step_sorted = theory_df.sort_values(by="Крок", kind="mergesort").reset_index(drop=True)
    first_deflection = float(step_sorted.iloc[0]["f, мм"])
    last_deflection = float(step_sorted.iloc[-1]["f, мм"])
    tolerance = 1e-9
    if target_deflection_mm < min(first_deflection, last_deflection) - tolerance or target_deflection_mm > max(first_deflection, last_deflection) + tolerance:
        return empty_state

    for _, row in step_sorted.iterrows():
        deflection_value = float(row["f, мм"])
        if abs(deflection_value - target_deflection_mm) <= tolerance:
            return DeflectionReferenceState(
                deflection_mm=target_deflection_mm,
                moment_kNm=float(row["M, кН·м"]),
                concrete_strain_e5=float(row["ε_c,top, 10^-5"]),
                top_rebar_strain_e5=float(row["ε_s,top, 10^-5"]),
                bottom_rebar_strain_e5=float(row["ε_s,bot, 10^-5"]),
                within_range=True,
            )

    for index in range(1, len(step_sorted)):
        left = step_sorted.iloc[index - 1]
        right = step_sorted.iloc[index]
        left_deflection = float(left["f, мм"])
        right_deflection = float(right["f, мм"])
        if not (min(left_deflection, right_deflection) - tolerance <= target_deflection_mm <= max(left_deflection, right_deflection) + tolerance):
            continue
        return DeflectionReferenceState(
            deflection_mm=target_deflection_mm,
            moment_kNm=_interpolate_series_value(
                left_deflection,
                right_deflection,
                float(left["M, кН·м"]),
                float(right["M, кН·м"]),
                target_deflection_mm,
            ),
            concrete_strain_e5=_interpolate_series_value(
                left_deflection,
                right_deflection,
                float(left["ε_c,top, 10^-5"]),
                float(right["ε_c,top, 10^-5"]),
                target_deflection_mm,
            ),
            top_rebar_strain_e5=_interpolate_series_value(
                left_deflection,
                right_deflection,
                float(left["ε_s,top, 10^-5"]),
                float(right["ε_s,top, 10^-5"]),
                target_deflection_mm,
            ),
            bottom_rebar_strain_e5=_interpolate_series_value(
                left_deflection,
                right_deflection,
                float(left["ε_s,bot, 10^-5"]),
                float(right["ε_s,bot, 10^-5"]),
                target_deflection_mm,
            ),
            within_range=True,
        )

    return empty_state


def _build_experimental_deflection_annotation(
    experimental_df: pd.DataFrame | None,
    *,
    target_deflection_mm: float,
) -> ChartLimitAnnotation:
    label = "exp @ f_u"
    if experimental_df is None or experimental_df.empty:
        return ChartLimitAnnotation(label=label, target_strain=target_deflection_mm, moment_kNm=None, within_chart_range=False)

    experimental_sorted = experimental_df.sort_values(by="f, мм", kind="mergesort").reset_index(drop=True)
    x_values = [float(value) for value in experimental_sorted["f, мм"].tolist()]
    moment_values = [float(value) for value in experimental_sorted["M, кН·м"].tolist()]
    tolerance = 1e-9
    if target_deflection_mm < x_values[0] - tolerance or target_deflection_mm > x_values[-1] + tolerance:
        return ChartLimitAnnotation(label=label, target_strain=target_deflection_mm, moment_kNm=None, within_chart_range=False)

    for x_value, moment_value in zip(x_values, moment_values, strict=True):
        if abs(x_value - target_deflection_mm) <= tolerance:
            return ChartLimitAnnotation(label=label, target_strain=target_deflection_mm, moment_kNm=moment_value, within_chart_range=True)

    for index in range(1, len(x_values)):
        left_x = x_values[index - 1]
        right_x = x_values[index]
        if not (left_x <= target_deflection_mm <= right_x):
            continue
        return ChartLimitAnnotation(
            label=label,
            target_strain=target_deflection_mm,
            moment_kNm=_interpolate_series_value(left_x, right_x, moment_values[index - 1], moment_values[index], target_deflection_mm),
            within_chart_range=True,
        )

    return ChartLimitAnnotation(label=label, target_strain=target_deflection_mm, moment_kNm=None, within_chart_range=False)


def _build_theory_deflection_annotation(theoretical_state: DeflectionReferenceState) -> ChartLimitAnnotation:
    return ChartLimitAnnotation(
        label="theory @ f_u",
        target_strain=theoretical_state.deflection_mm,
        moment_kNm=theoretical_state.moment_kNm,
        within_chart_range=theoretical_state.within_range,
    )


def _build_theory_material_annotation(
    theoretical_state: DeflectionReferenceState,
    *,
    chart_id: str,
) -> ChartLimitAnnotation:
    target_value = {
        "concrete_moment_strain": theoretical_state.concrete_strain_e5,
        "top_rebar_moment_strain": theoretical_state.top_rebar_strain_e5,
        "bottom_rebar_moment_strain": theoretical_state.bottom_rebar_strain_e5,
    }[chart_id]
    return ChartLimitAnnotation(
        label="theory @ f_u",
        target_strain=0.0 if target_value is None else float(target_value),
        moment_kNm=theoretical_state.moment_kNm,
        within_chart_range=theoretical_state.within_range and target_value is not None,
    )


def _format_reference_metric(name: str, value: float | None, *, unit: str, digits: int = 2) -> str:
    if value is None:
        return f"{name} = поза діапазоном"
    return f"{name} = {_format_optional_number(value, digits=digits)} {unit}"


def _build_experimental_reference_summary_html(
    *,
    chart_id: str,
    target_deflection_mm: float,
    theoretical_state: DeflectionReferenceState,
    experimental_annotation: ChartLimitAnnotation | None,
    limit_annotation: ChartLimitAnnotation,
    max_annotation: ChartLimitAnnotation,
) -> str:
    fragments = [
        '<article class="chart-explanation-card experimental-reference-card" data-role="experimental-reference-card">',
        '<div class="chart-explanation-card__eyebrow">Контрольні точки comparison-графіка</div>',
    ]
    if chart_id == "deflection_mf":
        fragments.extend(
            [
                '<div class="chart-explanation-card__title">Нормативний прогин f_u</div>',
                f'<div class="chart-explanation-card__value">f_u = {_format_optional_number(target_deflection_mm, digits=2)} мм</div>',
                f'<div class="chart-explanation-card__value">{escape(_format_reference_metric("M_theory(f_u)", theoretical_state.moment_kNm, unit="кН·м"))}</div>',
            ]
        )
        if experimental_annotation is None or experimental_annotation.moment_kNm is None:
            fragments.append('<div class="chart-explanation-card__status">M_exp(f_u) = поза діапазоном експерименту</div>')
        else:
            fragments.append(
                f'<div class="chart-explanation-card__value">{escape(_format_reference_metric("M_exp(f_u)", experimental_annotation.moment_kNm, unit="кН·м"))}</div>'
            )
        fragments.append("</article>")
        return "".join(fragments)

    value_by_chart = {
        "concrete_moment_strain": ("ε_c(theory @ f_u)", theoretical_state.concrete_strain_e5),
        "top_rebar_moment_strain": ("ε_s(theory @ f_u)", theoretical_state.top_rebar_strain_e5),
        "bottom_rebar_moment_strain": ("ε_s(theory @ f_u)", theoretical_state.bottom_rebar_strain_e5),
    }
    label, value = value_by_chart[chart_id]
    fragments.extend(
        [
            '<div class="chart-explanation-card__title">Теорія при нормативному прогині</div>',
            f'<div class="chart-explanation-card__value">{escape(_format_reference_metric(label, value, unit="·10^-5"))}</div>',
            f'<div class="chart-explanation-card__value">{escape(_format_reference_metric("M_theory(f_u)", theoretical_state.moment_kNm, unit="кН·м"))}</div>',
            f'<div class="chart-explanation-card__value">{escape(_format_reference_metric(limit_annotation.label, limit_annotation.target_strain, unit="·10^-5"))}</div>',
            f'<div class="chart-explanation-card__value">{escape(_format_reference_metric(f"M({limit_annotation.label})", limit_annotation.moment_kNm, unit="кН·м"))}</div>',
            f'<div class="chart-explanation-card__value">{escape(_format_reference_metric(max_annotation.label, max_annotation.target_strain, unit="·10^-5"))}</div>',
            f'<div class="chart-explanation-card__value">{escape(_format_reference_metric(f"M({max_annotation.label})", max_annotation.moment_kNm, unit="кН·м"))}</div>',
        ]
    )
    fragments.append("</article>")
    return "".join(fragments)


def _build_concrete_moment_strain_df(result) -> pd.DataFrame:
    return _sort_chart_df(
        pd.DataFrame(
            {
                "Крок": [point.step_index for point in result.curve_points],
                "M, кН·м": [point.moment_kNm for point in result.curve_points],
                "ε_c,top, 10^-5": [_to_strain_e5(point.top_strain) for point in result.curve_points],
            }
        ),
        x_field="ε_c,top, 10^-5",
    )


def _build_deflection_annotation_callout_text(annotation: ChartLimitAnnotation) -> str:
    return annotation.label


def _build_concrete_strain_chart_df(selected_strain_profile) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "z, мм": [point.z_mm for point in selected_strain_profile],
            "ε_c, 10^-5": [_to_strain_e5(point.strain) for point in selected_strain_profile],
        }
    )


def _pick_extreme_rebar_layers(section) -> tuple[tuple[int, object], tuple[int, object]]:
    indexed_layers = list(enumerate(section.rebar_layers, start=1))
    top_rebar = min(indexed_layers, key=lambda item: item[1].z_mm)
    bottom_rebar = max(indexed_layers, key=lambda item: item[1].z_mm)
    return top_rebar, bottom_rebar


def _build_rebar_strain_values_e5(section, result, *, rebar_index: int) -> list[float]:
    rebar = section.rebar_layers[rebar_index - 1]
    return [
        _to_strain_e5(
            _strain_at_depth(
                point.top_strain,
                point.bottom_strain,
                rebar.z_mm,
                section.section_height_mm,
            )
        )
        for point in result.curve_points
    ]


def _build_rebar_moment_strain_df(section, result, *, rebar_index: int) -> pd.DataFrame:
    return _sort_chart_df(
        pd.DataFrame(
            {
                "Крок": [point.step_index for point in result.curve_points],
                "M, кН·м": [point.moment_kNm for point in result.curve_points],
                "ε_s, 10^-5": _build_rebar_strain_values_e5(section, result, rebar_index=rebar_index),
            }
        ),
        x_field="ε_s, 10^-5",
    )


def _sorted_curve_pairs(points, x_values: list[float]) -> list[tuple[float, object]]:
    return sorted(zip(x_values, points, strict=True), key=lambda item: (item[0], item[1].step_index))


def _optional_secondary_limit(
    primary_strain: float,
    secondary_strain: float,
    *,
    label: str,
    tolerance: float = 1e-6,
) -> tuple[str | None, float | None]:
    if abs(primary_strain - secondary_strain) <= tolerance:
        return None, None
    return label, secondary_strain


def _build_limit_annotation(points, *, x_values: list[float], target_strain: float, label: str) -> ChartLimitAnnotation:
    if not points:
        raise ValueError("At least one curve point is required for a limit annotation.")
    if len(points) != len(x_values):
        raise ValueError("Point and strain sequences must have matching lengths.")

    sorted_pairs = _sorted_curve_pairs(points, x_values)
    sorted_x_values = [item[0] for item in sorted_pairs]
    sorted_points = [item[1] for item in sorted_pairs]

    tolerance = 1e-9
    x_min = sorted_x_values[0]
    x_max = sorted_x_values[-1]
    within_chart_range = x_min - tolerance <= target_strain <= x_max + tolerance
    if not within_chart_range:
        return ChartLimitAnnotation(
            label=label,
            target_strain=target_strain,
            moment_kNm=None,
            within_chart_range=False,
        )

    for x_value, point in zip(sorted_x_values, sorted_points, strict=True):
        if abs(x_value - target_strain) <= tolerance:
            return ChartLimitAnnotation(
                label=label,
                target_strain=target_strain,
                moment_kNm=point.moment_kNm,
                within_chart_range=True,
            )

    for index in range(1, len(sorted_points)):
        left_x = sorted_x_values[index - 1]
        right_x = sorted_x_values[index]
        if not (left_x <= target_strain <= right_x):
            continue
        if abs(right_x - left_x) <= tolerance:
            moment_kNm = sorted_points[index].moment_kNm
        else:
            ratio = (target_strain - left_x) / (right_x - left_x)
            moment_kNm = sorted_points[index - 1].moment_kNm + ratio * (
                sorted_points[index].moment_kNm - sorted_points[index - 1].moment_kNm
            )
        return ChartLimitAnnotation(
            label=label,
            target_strain=target_strain,
            moment_kNm=moment_kNm,
            within_chart_range=True,
        )

    return ChartLimitAnnotation(
        label=label,
        target_strain=target_strain,
        moment_kNm=None,
        within_chart_range=True,
    )


def _resolve_limit_sign(values: list[float]) -> float:
    for value in reversed(values):
        if abs(value) > 1e-9:
            return -1.0 if value < 0.0 else 1.0
    return 1.0


def _build_concrete_limit_annotation(section, catalog, result) -> ChartLimitAnnotation:
    concrete_class = section.concrete_layers[0].concrete_class
    display_limit = catalog.display_limits.concrete[concrete_class]
    annotation = _build_limit_annotation(
        result.curve_points,
        x_values=[_to_strain_e5(point.top_strain) for point in result.curve_points],
        target_strain=display_limit.strain_e5,
        label=display_limit.label,
    )
    return ChartLimitAnnotation(
        label=annotation.label,
        target_strain=annotation.target_strain,
        moment_kNm=annotation.moment_kNm,
        within_chart_range=annotation.within_chart_range,
    )


def _build_rebar_limit_annotation(section, catalog, result, *, rebar_index: int) -> ChartLimitAnnotation:
    rebar = section.rebar_layers[rebar_index - 1]
    strain_values = _build_rebar_strain_values_e5(section, result, rebar_index=rebar_index)
    target_sign = _resolve_limit_sign(strain_values)
    display_limit = catalog.display_limits.steel[rebar.steel_class]
    display_target = target_sign * display_limit.strain_e5
    solver_target = _to_strain_e5(target_sign * catalog.steel[rebar.steel_class].epsilon_ud)
    secondary_label, secondary_strain = _optional_secondary_limit(display_target, solver_target, label="ε_ud")
    annotation = _build_limit_annotation(
        result.curve_points,
        x_values=strain_values,
        target_strain=display_target,
        label=display_limit.label,
    )
    return ChartLimitAnnotation(
        label=annotation.label,
        target_strain=annotation.target_strain,
        moment_kNm=annotation.moment_kNm,
        within_chart_range=annotation.within_chart_range,
        secondary_label=secondary_label,
        secondary_strain=secondary_strain,
    )


def _build_last_curve_point_annotation(
    result,
    *,
    x_values: list[float],
    label: str = "εmax",
) -> ChartLimitAnnotation:
    if not result.curve_points:
        raise ValueError("At least one curve point is required for an extreme-point annotation.")
    if len(result.curve_points) != len(x_values):
        raise ValueError("Point and strain sequences must have matching lengths.")

    last_point = result.curve_points[-1]
    return ChartLimitAnnotation(
        label=label,
        target_strain=x_values[-1],
        moment_kNm=last_point.moment_kNm,
        within_chart_range=True,
    )


def _build_concrete_last_point_annotation(result) -> ChartLimitAnnotation:
    return _build_last_curve_point_annotation(
        result,
        x_values=[_to_strain_e5(point.top_strain) for point in result.curve_points],
    )


def _build_rebar_last_point_annotation(section, result, *, rebar_index: int) -> ChartLimitAnnotation:
    return _build_last_curve_point_annotation(
        result,
        x_values=_build_rebar_strain_values_e5(section, result, rebar_index=rebar_index),
    )


def _resolve_annotation_label_style(
    target_strain: float,
    *,
    x_domain_min: float,
    x_domain_max: float,
    reverse_x: bool,
) -> tuple[str, int]:
    domain_span = x_domain_max - x_domain_min
    if abs(domain_span) <= 1e-9:
        return "left", 8

    normalized = (target_strain - x_domain_min) / domain_span
    normalized = max(0.0, min(1.0, normalized))
    screen_position = 1.0 - normalized if reverse_x else normalized
    if screen_position >= 0.72:
        return "right", -8
    return "left", 8


def _build_moment_strain_annotation_layers(
    annotation: ChartLimitAnnotation,
    *,
    x_field: str,
    x_axis_origin: float,
    x_domain_min: float,
    x_domain_max: float,
    y_axis_origin: float,
    y_label_value: float,
    reverse_x: bool = False,
    color: str = "#8c5a3a",
    text_mode: str = "symbol",
    label_position: str = "above",
    label_text: str | None = None,
    manual_dx: int = 0,
    manual_dy: int = 0,
) -> list[alt.Chart]:
    if text_mode not in {"symbol", "none"}:
        raise ValueError("Annotation text mode must be either 'symbol' or 'none'.")
    if label_position not in {"above", "below"}:
        raise ValueError("Annotation label position must be either 'above' or 'below'.")

    show_text = text_mode == "symbol"
    label_text = label_text or annotation.label
    label_align, label_dx = _resolve_annotation_label_style(
        annotation.target_strain,
        x_domain_min=x_domain_min,
        x_domain_max=x_domain_max,
        reverse_x=reverse_x,
    )
    in_range_baseline = "top" if label_position == "below" else "bottom"
    in_range_dy = 8 if label_position == "below" else -6
    if annotation.moment_kNm is None:
        annotation_df = pd.DataFrame(
            {
                x_field: [annotation.target_strain],
                f"{x_field}__axis": [annotation.target_strain],
                "M, кН·м": [y_label_value],
                "M__axis": [y_axis_origin],
                "Підпис": [label_text],
            }
        )
        layers = [
            alt.Chart(annotation_df).mark_rule(color=color, strokeDash=[7, 4], strokeWidth=2).encode(
                x=alt.X(f"{x_field}:Q"),
                x2=alt.X2(f"{x_field}__axis:Q"),
                y=alt.Y("M__axis:Q"),
                y2=alt.Y2("M, кН·м:Q"),
            ),
        ]
        if show_text:
            layers.append(
                alt.Chart(annotation_df).mark_text(
                    color=color,
                    align=label_align,
                    baseline="top",
                    dx=label_dx + manual_dx,
                    dy=8 + manual_dy,
                    fontSize=11,
                    fontWeight="bold",
                ).encode(
                    x=alt.X(f"{x_field}:Q"),
                    y=alt.Y("M, кН·м:Q"),
                    text="Підпис:N",
                )
            )
        return layers

    annotation_df = pd.DataFrame(
        {
            x_field: [annotation.target_strain],
            f"{x_field}__axis": [x_axis_origin],
            "M, кН·м": [annotation.moment_kNm],
            "M__axis": [y_axis_origin],
            "Підпис": [label_text],
        }
    )
    layers = [
        alt.Chart(annotation_df).mark_rule(color=color, strokeDash=[7, 4], strokeWidth=2).encode(
            x=alt.X(f"{x_field}:Q"),
            x2=alt.X2(f"{x_field}:Q"),
            y=alt.Y("M__axis:Q"),
            y2=alt.Y2("M, кН·м:Q"),
        ),
        alt.Chart(annotation_df).mark_rule(color=color, strokeDash=[7, 4], strokeWidth=2).encode(
            x=alt.X(f"{x_field}__axis:Q"),
            x2=alt.X2(f"{x_field}:Q"),
            y=alt.Y("M, кН·м:Q"),
            y2=alt.Y2("M, кН·м:Q"),
        ),
        alt.Chart(annotation_df).mark_point(color=color, filled=True, size=150).encode(
            x=alt.X(f"{x_field}:Q"),
            y=alt.Y("M, кН·м:Q"),
            tooltip=[x_field, "M, кН·м", "Підпис"],
        ),
    ]
    if show_text:
        layers.append(
            alt.Chart(annotation_df).mark_text(
                color=color,
                align=label_align,
                baseline=in_range_baseline,
                dx=label_dx + manual_dx,
                dy=in_range_dy + manual_dy,
                fontSize=11,
                fontWeight="bold",
            ).encode(
                x=alt.X(f"{x_field}:Q"),
                y=alt.Y("M, кН·м:Q"),
                text="Підпис:N",
            )
        )
    return layers


def _build_limit_chart_layers(
    annotation: ChartLimitAnnotation,
    *,
    x_field: str,
    x_axis_origin: float,
    x_domain_min: float,
    x_domain_max: float,
    y_axis_origin: float,
    y_label_value: float,
    reverse_x: bool = False,
    color: str = "#8c5a3a",
) -> list[alt.Chart]:
    return _build_moment_strain_annotation_layers(
        annotation,
        x_field=x_field,
        x_axis_origin=x_axis_origin,
        x_domain_min=x_domain_min,
        x_domain_max=x_domain_max,
        y_axis_origin=y_axis_origin,
        y_label_value=y_label_value,
        reverse_x=reverse_x,
        color=color,
    )


def _build_moment_strain_chart(
    chart_df: pd.DataFrame,
    *,
    x_field: str,
    selected_step: int,
    tooltip_fields: list[str],
    annotations: list[ChartAnnotationOverlay],
    experimental_df: pd.DataFrame | None = None,
) -> alt.LayerChart:
    step_sorted_df = chart_df.sort_values(by="Крок", kind="mergesort").reset_index(drop=True)
    first_step_x = float(step_sorted_df.iloc[0][x_field])
    last_step_x = float(step_sorted_df.iloc[-1][x_field])
    reverse_x = last_step_x < first_step_x
    x_domain_min = float(chart_df[x_field].min())
    x_domain_max = float(chart_df[x_field].max())
    x_axis_origin = x_domain_max if reverse_x else x_domain_min
    y_axis_origin = min(0.0, float(chart_df["M, кН·м"].min()))
    y_label_value = float(chart_df["M, кН·м"].max())

    base_chart = (
        alt.Chart(chart_df)
        .mark_line(point=True)
        .encode(
            x=alt.X(f"{x_field}:Q", title=x_field, scale=alt.Scale(reverse=reverse_x)),
            y=alt.Y("M, кН·м:Q", title="M, кН·м"),
            order=alt.Order("Крок:Q"),
            tooltip=tooltip_fields,
        )
        .properties(height=320)
    )
    layers: list[alt.Chart] = [base_chart]
    if experimental_df is not None and not experimental_df.empty:
        layers.append(
            alt.Chart(experimental_df)
            .mark_line(color=EXPERIMENTAL_OVERLAY_COLOR, point=True, strokeDash=[8, 4], strokeWidth=3)
            .encode(
                x=alt.X(f"{x_field}:Q", scale=alt.Scale(reverse=reverse_x)),
                y=alt.Y("M, кН·м:Q"),
                tooltip=[x_field, "M, кН·м"],
            )
        )
    selected_chart = (
        alt.Chart(chart_df[chart_df["Крок"] == selected_step])
        .mark_point(color="#c2410c", filled=True, size=180)
        .encode(
            x=alt.X(f"{x_field}:Q", scale=alt.Scale(reverse=reverse_x)),
            y=alt.Y("M, кН·м:Q"),
            tooltip=tooltip_fields,
        )
    )

    layers.append(selected_chart)
    for overlay in annotations:
        layers.extend(
            _build_moment_strain_annotation_layers(
                overlay.annotation,
                x_field=x_field,
                x_axis_origin=x_axis_origin,
                x_domain_min=x_domain_min,
                x_domain_max=x_domain_max,
                y_axis_origin=y_axis_origin,
                y_label_value=y_label_value,
                reverse_x=reverse_x,
                color=overlay.color,
                text_mode=overlay.text_mode,
                label_position=overlay.label_position,
                label_text=overlay.label_text,
                manual_dx=overlay.manual_dx,
                manual_dy=overlay.manual_dy,
            )
        )
    return alt.layer(*layers)


def _build_experimental_primary_chart(
    *,
    x_field: str,
    experimental_df: pd.DataFrame | None,
    theory_df: pd.DataFrame | None = None,
    show_theory: bool,
    annotations: list[ChartAnnotationOverlay] | None = None,
) -> alt.LayerChart:
    candidate_frames = [
        frame
        for frame in (
            experimental_df.sort_values(by=x_field, kind="mergesort").reset_index(drop=True)
            if experimental_df is not None and not experimental_df.empty
            else None,
            theory_df.sort_values(by=[x_field, "Крок"], kind="mergesort").reset_index(drop=True)
            if theory_df is not None and not theory_df.empty and "Крок" in theory_df.columns
            else theory_df.sort_values(by=x_field, kind="mergesort").reset_index(drop=True)
            if theory_df is not None and not theory_df.empty
            else None,
        )
        if frame is not None and not frame.empty
    ]
    if not candidate_frames:
        raise ValueError("At least one dataset is required to build the experimental chart.")

    reference_df = candidate_frames[0]
    first_x = float(reference_df.iloc[0][x_field])
    last_x = float(reference_df.iloc[-1][x_field])
    reverse_x = last_x < first_x
    x_domain_min = min(float(frame[x_field].min()) for frame in candidate_frames)
    x_domain_max = max(float(frame[x_field].max()) for frame in candidate_frames)
    x_axis_origin = x_domain_max if reverse_x else x_domain_min
    y_axis_origin = min(0.0, min(float(frame["M, кН·м"].min()) for frame in candidate_frames))
    y_label_value = max(float(frame["M, кН·м"].max()) for frame in candidate_frames)

    layers: list[alt.Chart] = []
    if experimental_df is not None and not experimental_df.empty:
        experimental_sorted = experimental_df.sort_values(by=x_field, kind="mergesort").reset_index(drop=True)
        layers.append(
            alt.Chart(experimental_sorted)
            .mark_line(color=EXPERIMENTAL_OVERLAY_COLOR, point=True, strokeWidth=3)
            .encode(
                x=alt.X(f"{x_field}:Q", title=x_field, scale=alt.Scale(reverse=reverse_x)),
                y=alt.Y("M, кН·м:Q", title="M, кН·м"),
                tooltip=[x_field, "M, кН·м"],
            )
        )

    if show_theory and theory_df is not None and not theory_df.empty:
        theory_sorted = (
            theory_df.sort_values(by=[x_field, "Крок"], kind="mergesort").reset_index(drop=True)
            if "Крок" in theory_df.columns
            else theory_df.sort_values(by=x_field, kind="mergesort").reset_index(drop=True)
        )
        theory_chart = (
            alt.Chart(theory_sorted)
            .mark_line(color=THEORY_OVERLAY_COLOR, point=True, strokeDash=[6, 4], strokeWidth=2.2)
            .encode(
                x=alt.X(f"{x_field}:Q", title=x_field, scale=alt.Scale(reverse=reverse_x)),
                y=alt.Y("M, кН·м:Q", title="M, кН·м"),
                tooltip=([x_field, "M, кН·м", "Крок"] if "Крок" in theory_sorted.columns else [x_field, "M, кН·м"]),
            )
        )
        if "Крок" in theory_sorted.columns:
            theory_chart = theory_chart.encode(order=alt.Order("Крок:Q"))
        layers.append(theory_chart)

    for overlay in annotations or []:
        layers.extend(
            _build_moment_strain_annotation_layers(
                overlay.annotation,
                x_field=x_field,
                x_axis_origin=x_axis_origin,
                x_domain_min=x_domain_min,
                x_domain_max=x_domain_max,
                y_axis_origin=y_axis_origin,
                y_label_value=y_label_value,
                reverse_x=reverse_x,
                color=overlay.color,
                text_mode=overlay.text_mode,
                label_position=overlay.label_position,
                label_text=overlay.label_text,
                manual_dx=overlay.manual_dx,
                manual_dy=overlay.manual_dy,
            )
        )

    return alt.layer(*layers).properties(height=320)


def _build_chart_limit_badges_html(items: list[tuple[str, ChartLimitAnnotation]]) -> str:
    fragments = ['<div class="chart-limit-badges" data-role="chart-limit-badges">']
    for title, annotation in items:
        fragments.extend(
            [
                '<article class="chart-limit-badge" data-role="chart-limit-badge">',
                '<div class="chart-limit-badge__eyebrow">Нормативна межа на графіку</div>',
                f'<div class="chart-limit-badge__title">{escape(title)}</div>',
                (
                    '<div class="chart-limit-badge__value">'
                    f'{escape(annotation.label)} = {_format_optional_number(annotation.target_strain, digits=2)} ·10^-5'
                    "</div>"
                ),
            ]
        )
        if annotation.moment_kNm is not None:
            fragments.append(
                '<div class="chart-limit-badge__meta">'
                f'M_limit = {annotation.moment_kNm:.2f} кН·м'
                "</div>"
            )
        else:
            fragments.append('<div class="chart-limit-badge__meta">Поза розрахованим діапазоном</div>')
        if annotation.secondary_label is not None and annotation.secondary_strain is not None:
            fragments.append(
                (
                    '<div class="chart-limit-badge__note" data-role="chart-limit-secondary">'
                    f'Solver: {escape(annotation.secondary_label)} = '
                    f'{_format_optional_number(annotation.secondary_strain, digits=2)} ·10^-5'
                    "</div>"
                )
            )
        fragments.append("</article>")
    fragments.append("</div>")
    return "".join(fragments)


def _build_chart_explanation_html(
    *,
    chart_title: str,
    subject_line: str,
    definition: str,
    value_lines: list[str],
    status_lines: list[str] | None = None,
    note_lines: list[str] | None = None,
) -> str:
    fragments = [
        '<article class="chart-explanation-card" data-role="chart-explanation-card">',
        '<div class="chart-explanation-card__eyebrow">Пояснення позначень</div>',
        f'<div class="chart-explanation-card__title" data-role="chart-explanation-title">{escape(chart_title)}</div>',
        f'<div class="chart-explanation-card__meta">{escape(subject_line)}</div>',
        f'<p class="chart-explanation-card__copy">{escape(definition)}</p>',
    ]
    for value_line in value_lines:
        fragments.append(f'<div class="chart-explanation-card__value">{escape(value_line)}</div>')
    for status_line in status_lines or []:
        fragments.append(f'<div class="chart-explanation-card__status">{escape(status_line)}</div>')
    for note_line in note_lines or []:
        fragments.append(f'<div class="chart-explanation-card__note">{escape(note_line)}</div>')
    fragments.append("</article>")
    return "".join(fragments)


def _build_annotation_callout_text(annotation: ChartLimitAnnotation) -> str:
    return annotation.label


def _build_concrete_chart_explanation_html(
    *,
    chart_title: str,
    concrete_class: str,
    limit_annotation: ChartLimitAnnotation,
    max_annotation: ChartLimitAnnotation,
) -> str:
    status_lines = ["εmax показує останню фактично досягнуту точку розрахунку."]
    if limit_annotation.moment_kNm is None:
        status_lines.insert(0, "Нормативна межа не потрапила в побудовану криву.")
    else:
        status_lines.insert(0, "Нормативна межа потрапляє в побудовану криву.")
    return _build_chart_explanation_html(
        chart_title=chart_title,
        subject_line=f"Матеріал: {concrete_class}, верхня грань перерізу",
        definition=(
            f"{limit_annotation.label} є нормативна гранична деформація стиснутого бетону для класу {concrete_class}."
        ),
        value_lines=[
            f"{limit_annotation.label} = {_format_optional_number(limit_annotation.target_strain, digits=2)} ·10^-5",
            f"{max_annotation.label} = {_format_optional_number(max_annotation.target_strain, digits=2)} ·10^-5",
            f"M({max_annotation.label}) = {_format_optional_number(max_annotation.moment_kNm, digits=2)} кН·м",
        ],
        note_lines=(
            [
                "Це нормативна межа для бетону; εmax — остання фактично досягнута точка.",
                f"M({limit_annotation.label}) = {_format_optional_number(limit_annotation.moment_kNm, digits=2)} кН·м",
            ]
            if limit_annotation.moment_kNm is not None
            else ["Це нормативна межа для бетону; εmax — остання фактично досягнута точка."]
        ),
        status_lines=status_lines,
    )


def _build_rebar_chart_explanation_html(
    *,
    chart_title: str,
    rebar_label: str,
    steel_class: str,
    z_mm: float,
    limit_annotation: ChartLimitAnnotation,
    max_annotation: ChartLimitAnnotation,
) -> str:
    note_lines: list[str] = []
    branch_label = "від’ємній" if limit_annotation.target_strain < 0 else "додатній"
    sign_label = "«-»" if limit_annotation.target_strain < 0 else "«+»"
    note_lines.append(
        f"На графіку межу показано на {branch_label} гілці кривої, тому значення відкладене зі знаком {sign_label}."
    )
    return _build_chart_explanation_html(
        chart_title=chart_title,
        subject_line=f"{rebar_label}, {steel_class}, z = {z_mm:.1f} мм",
        definition=f"{limit_annotation.label} є деформація текучості арматури класу {steel_class}.",
        value_lines=[
            f"{limit_annotation.label} = {_format_optional_number(limit_annotation.target_strain, digits=2)} ·10^-5",
            f"M({limit_annotation.label}) = {_format_optional_number(limit_annotation.moment_kNm, digits=2)} кН·м",
            f"{max_annotation.label} = {_format_optional_number(max_annotation.target_strain, digits=2)} ·10^-5",
            f"M({max_annotation.label}) = {_format_optional_number(max_annotation.moment_kNm, digits=2)} кН·м",
        ],
        note_lines=note_lines,
    )


def _build_analytics_summary_df(section, result) -> pd.DataFrame:
    top_rebar, bottom_rebar = _pick_extreme_rebar_layers(section)
    return pd.DataFrame(
        {
            "Крок": [point.step_index for point in result.curve_points],
            "M, кН·м": [point.moment_kNm for point in result.curve_points],
            "κ, 1/м": [point.curvature_1_per_m for point in result.curve_points],
            "ε_c,top, 10^-5": [_to_strain_e5(point.top_strain) for point in result.curve_points],
            "ε_s,top, 10^-5": [
                _to_strain_e5(
                    _strain_at_depth(
                        point.top_strain,
                        point.bottom_strain,
                        top_rebar[1].z_mm,
                        section.section_height_mm,
                    )
                )
                for point in result.curve_points
            ],
            "ε_s,bot, 10^-5": [
                _to_strain_e5(
                    _strain_at_depth(
                        point.top_strain,
                        point.bottom_strain,
                        bottom_rebar[1].z_mm,
                        section.section_height_mm,
                    )
                )
                for point in result.curve_points
            ],
        }
    )


def _describe_termination_reason(reason_code: str) -> str:
    mapping = {
        "completed_at_concrete_limit": "Розрахунок завершено за критерієм бетону.",
        "no_tension_equilibrium_at_steel_limit": (
            "Розрахунок завершено після досягнення граничного стану розтягнутої арматури."
        ),
        "no_compression_equilibrium_at_upper_bound": (
            "Розрахунок завершено, бо стискувальна зона бетону більше не забезпечує рівновагу."
        ),
        "high_axial_residual_after_iteration": (
            "Розрахунок зупинено: числова нев'язка стала надто великою; це не матеріальне руйнування."
        ),
    }
    return mapping.get(reason_code, reason_code)


def _build_termination_narrative(result) -> str:
    termination = result.termination
    attempted_step = termination.attempted_step
    attempted_strain_note = ""
    if termination.attempted_top_strain is not None:
        attempted_strain_note = (
            " Спроба продовжити криву вела до деформації "
            f"{_to_strain_e5(termination.attempted_top_strain):.2f} ·10^-5."
        )

    if termination.last_step == result.peak_point.step_index:
        peak_note = (
            f"Остання побудована точка одночасно є піком несучої здатності: "
            f"M_Rd = {result.peak_moment_kNm:.2f} кН·м."
        )
    else:
        peak_note = (
            f"Пік несучої здатності було пройдено на кроці {result.peak_point.step_index} "
            f"з моментом {result.peak_moment_kNm:.2f} кН·м; далі крива перейшла на спадну гілку."
        )

    if termination.reason_code == "completed_at_concrete_limit":
        cause_note = (
            f" Визначальним став бетон: на кроці {termination.last_step} досягнуто "
            "граничний бетонний критерій у стиснутій зоні."
        )
    elif termination.reason_code == "no_tension_equilibrium_at_steel_limit":
        attempted_phrase = (
            f" на спробі кроку {attempted_step}" if attempted_step is not None else " на наступному кроці"
        )
        cause_note = (
            " Визначальною стала арматура: після досягнення граничного стану "
            f"розтягнутої арматури{attempted_phrase} переріз уже не врівноважився."
        )
    elif termination.reason_code == "no_compression_equilibrium_at_upper_bound":
        attempted_phrase = (
            f" на спробі кроку {attempted_step}" if attempted_step is not None else " на наступному кроці"
        )
        cause_note = (
            " Розрахунок зупинився за стискувальною зоною: "
            f"бетон у стиску{attempted_phrase} вже не забезпечив рівновагу перерізу."
        )
    elif termination.reason_code == "high_axial_residual_after_iteration":
        attempted_phrase = (
            f" на спробі кроку {attempted_step}" if attempted_step is not None else ""
        )
        cause_note = (
            f" Зупинка сталася{attempted_phrase} через те, що числова збіжність була втрачена: "
            f"нев'язка сил зросла до {abs(termination.residual_kN):.2f} кН. "
            "Це не матеріальне руйнування, а межа достовірного продовження кривої."
        )
    else:
        cause_note = f" Причина завершення: {termination.reason_code}."

    return f"{peak_note}{cause_note}{attempted_strain_note} На графіках останню побудовану точку позначено як εmax."


def _build_termination_summary_html(result) -> str:
    termination = result.termination
    raw_cards = [
        ("Причина", _describe_termination_reason(termination.reason_code), "reason"),
        ("Останній крок", str(termination.last_step), "last-step"),
        ("Останній момент, кН·м", f"{termination.last_moment_kNm:.2f}", "last-moment"),
        (
            "Попередній крок",
            None if termination.previous_step is None else str(termination.previous_step),
            "previous-step",
        ),
        (
            "Попередній момент, кН·м",
            None if termination.previous_moment_kNm is None else f"{termination.previous_moment_kNm:.2f}",
            "previous-moment",
        ),
        (
            "Крок, який вже не вдалося побудувати",
            None if termination.attempted_step is None else str(termination.attempted_step),
            "attempted-step",
        ),
        (
            "Деформація на невдалій спробі, 10^-5",
            (
                None
                if termination.attempted_top_strain is None
                else f"{_to_strain_e5(termination.attempted_top_strain):.2f}"
            ),
            "attempted-strain",
        ),
        (
            "Похибка врівноваження сил, кН",
            f"{termination.residual_kN:.4f}" if abs(termination.residual_kN) > 1e-9 else None,
            "residual",
        ),
    ]
    cards = [(label, value, role) for label, value, role in raw_cards if value is not None]

    fragments = [
        '<section class="termination-panel" data-role="termination-panel">',
        '<div class="termination-panel__eyebrow">Завершення розрахунку</div>',
        '<h3 class="termination-panel__title">Як завершився розрахунок</h3>',
        (
            '<p class="termination-panel__help-note" data-role="termination-help-note">'
            "Тут показано, на якій точці зупинився розрахунок і що це означає для побудованої кривої."
            "</p>"
        ),
        '<div class="termination-panel__grid">',
    ]
    for label, value, role in cards:
        fragments.extend(
            [
                '<article class="termination-panel__card" data-role="termination-card">',
                f'<div class="termination-panel__label">{escape(label)}</div>',
                (
                    f'<div class="termination-panel__value" data-role="termination-value-{role}">'
                    f"{escape(value)}</div>"
                ),
                "</article>",
            ]
        )
    fragments.extend(
        [
            "</div>",
            (
                '<p class="termination-panel__narrative" data-role="termination-narrative">'
                f"{escape(_build_termination_narrative(result))}</p>"
            ),
            "</section>",
        ]
    )
    return "".join(fragments)


def _is_draft_shape(candidate: object) -> bool:
    if not isinstance(candidate, dict):
        return False

    required_keys = {"section_height_mm", "section_width_mm", "outer_steps", "concrete_layers", "rebar_layers"}
    if not required_keys.issubset(candidate):
        return False

    concrete_layers = candidate.get("concrete_layers")
    rebar_layers = candidate.get("rebar_layers")
    return (
        isinstance(concrete_layers, list)
        and len(concrete_layers) == 2
        and isinstance(rebar_layers, list)
        and len(rebar_layers) == 2
    )


def _is_serviceability_shape(candidate: object) -> bool:
    if not isinstance(candidate, dict):
        return False

    required_keys = {
        "span_mm",
        "support_scheme",
        "a_mm",
        "phi_creep",
        "deflection_limit_profile",
        "available_gap_mm",
        "w_limit_mm",
        "load_duration",
    }
    return required_keys.issubset(candidate)


def _merge_serviceability_defaults(candidate: object) -> dict[str, object]:
    merged = default_serviceability_inputs()
    if isinstance(candidate, dict):
        merged.update(candidate)
    return merged


def _load_state() -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
    defaults = default_draft_inputs()
    serviceability_defaults = default_serviceability_inputs()

    if not _is_draft_shape(st.session_state.get("draft_inputs")):
        st.session_state.draft_inputs = copy_draft_inputs(defaults)
    if not _is_draft_shape(st.session_state.get("active_inputs")):
        st.session_state.active_inputs = copy_draft_inputs(defaults)
    if not _is_serviceability_shape(st.session_state.get("serviceability_draft_inputs")):
        st.session_state.serviceability_draft_inputs = copy_draft_inputs(serviceability_defaults)
    else:
        st.session_state.serviceability_draft_inputs = _merge_serviceability_defaults(st.session_state.serviceability_draft_inputs)
    if not _is_serviceability_shape(st.session_state.get("serviceability_active_inputs")):
        st.session_state.serviceability_active_inputs = copy_draft_inputs(serviceability_defaults)
    else:
        st.session_state.serviceability_active_inputs = _merge_serviceability_defaults(st.session_state.serviceability_active_inputs)

    return (
        st.session_state.draft_inputs,
        st.session_state.active_inputs,
        st.session_state.serviceability_draft_inputs,
        st.session_state.serviceability_active_inputs,
    )


def _automation_mode_enabled() -> bool:
    if os.getenv("RC_BENDING_AUTOMATION") == "1":
        return True
    try:
        return str(st.query_params.get("automation", "")).strip() == "1"
    except Exception:
        return False


def _load_automation_request() -> dict[str, object] | None:
    if not _automation_mode_enabled():
        return None
    request_path = os.getenv("RC_BENDING_AUTOMATION_INPUT")
    if not request_path:
        try:
            request_path = st.query_params.get("automation_input")
        except Exception:
            request_path = None
    if not request_path:
        return None
    if st.session_state.get("_automation_request_path") == request_path:
        cached = st.session_state.get("_automation_request")
        return cached if isinstance(cached, dict) else None
    payload = json.loads(Path(str(request_path)).read_text(encoding="utf-8"))
    st.session_state._automation_request_path = str(request_path)
    st.session_state._automation_request = payload
    return payload


def _apply_automation_request(
    request: dict[str, object] | None,
    *,
    catalog,
    draft_inputs: dict[str, object],
    active_inputs: dict[str, object],
    serviceability_draft_inputs: dict[str, object],
    serviceability_active_inputs: dict[str, object],
) -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
    if not request:
        return draft_inputs, active_inputs, serviceability_draft_inputs, serviceability_active_inputs

    section_input = request.get("section_input")
    if isinstance(section_input, dict):
        automated_draft = build_mcp_draft_inputs(section_input)
        draft_inputs = copy_draft_inputs(automated_draft)
        active_inputs = copy_draft_inputs(automated_draft)
        st.session_state.draft_inputs = draft_inputs
        st.session_state.active_inputs = active_inputs

    serviceability_input = request.get("serviceability_input")
    if isinstance(serviceability_input, dict):
        automated_serviceability = build_mcp_serviceability_draft_inputs(serviceability_input)
        serviceability_draft_inputs = copy_draft_inputs(automated_serviceability)
        serviceability_active_inputs = copy_draft_inputs(automated_serviceability)
        st.session_state.serviceability_draft_inputs = serviceability_draft_inputs
        st.session_state.serviceability_active_inputs = serviceability_active_inputs

    selected_step = request.get("selected_step")
    if selected_step not in {None, ""}:
        st.session_state.selected_curve_step = int(selected_step)

    workbook_path = request.get("workbook_path")
    if workbook_path:
        workbook_bytes = Path(str(workbook_path)).read_bytes()
        st.session_state.experimental_workbook_bytes = workbook_bytes
        st.session_state.experimental_workbook_name = Path(str(workbook_path)).name
        st.session_state.pop("experimental_pending_workbook_bytes", None)
        st.session_state.pop("experimental_pending_workbook_name", None)
        st.session_state.pop("experimental_pending_inspection", None)

    if validate_draft_inputs(active_inputs, catalog):
        raise ValueError("Automation request contains invalid section inputs.")
    if validate_serviceability_inputs(serviceability_active_inputs):
        raise ValueError("Automation request contains invalid serviceability inputs.")
    return draft_inputs, active_inputs, serviceability_draft_inputs, serviceability_active_inputs


def _render_hidden_automation_payload(data_role: str, payload: dict[str, object]) -> None:
    st.markdown(
        (
            f'<div data-role="{data_role}" style="position:absolute;left:-99999px;top:auto;width:1px;height:1px;overflow:hidden;">'
            f"{escape(json.dumps(payload, ensure_ascii=False))}"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def _build_section_automation_payload(result, selected_point) -> dict[str, object]:
    return {
        "selected_step": selected_point.step_index,
        "peak_moment_kNm": result.peak_moment_kNm,
        "neutral_axis_mm": selected_point.neutral_axis_mm,
        "top_strain": selected_point.top_strain,
        "bottom_strain": selected_point.bottom_strain,
    }


def _build_serviceability_automation_payload(result, selected_point, serviceability_report) -> dict[str, object]:
    payload = _build_section_automation_payload(result, selected_point)
    payload.update(
        {
            "w_k_mm": serviceability_report.crack_width.w_k_mm,
            "deflection_mm": serviceability_report.deflection.deflection_mm,
        }
    )
    return payload


def _build_experimental_automation_payload(
    *,
    experimental_dataset: ExperimentalDataset | None,
    experimental_error: str | None,
    experimental_file_name: str | None,
) -> dict[str, object]:
    return {
        "inspection_status": "ready" if experimental_dataset is not None else ("error" if experimental_error else "empty"),
        "loaded_sheet_names": sorted(experimental_dataset.series.keys()) if experimental_dataset is not None else [],
        "experimental_file_name": experimental_file_name,
        "experimental_error": experimental_error,
    }


def _build_concrete_preview_df(derived: dict[str, object]) -> pd.DataFrame:
    rows = list(derived["concrete_rows"])
    return pd.DataFrame(
        {
            "Шар": [row["layer"] for row in rows],
            "b, мм": [row["width_mm"] for row in rows],
            "h, мм": [row["height_mm"] for row in rows],
            "Клас": [row["concrete_class"] for row in rows],
            "Статус": [row["status"] for row in rows],
        }
    )


def _build_rebar_preview_df(derived: dict[str, object]) -> pd.DataFrame:
    rows = list(derived["rebar_rows"])
    return pd.DataFrame(
        {
            "Шар": [row["layer"] for row in rows],
            "Грань": [row["face"] for row in rows],
            "a, мм": [row["distance_mm"] for row in rows],
            "z, мм": [row["z_mm"] for row in rows],
            "n, шт.": [row["bar_count"] for row in rows],
            "d, мм": [row["diameter_mm"] for row in rows],
            "Клас": [row["steel_class"] for row in rows],
            "Статус": [row["status"] for row in rows],
        }
    )


def _build_force_summary_df(layer_force_rows: list[dict[str, float | int | str]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Шар": [f"{'B' if row['kind'] == 'concrete' else 'A'}{row['index']}" for row in layer_force_rows],
            "N, кН": [row["force_kN"] for row in layer_force_rows],
            "ε, ‰": [_to_promille(float(row["strain"])) for row in layer_force_rows],
            "σ, МПа": [row["stress_mpa"] for row in layer_force_rows],
        }
    )


def _build_custom_css() -> str:
    return """
    <style>
    html, body, [class*="css"] {
        font-family: "Trebuchet MS", Verdana, sans-serif;
        color: #123047;
    }
    h1, h2, h3, h4, h5, h6 {
        font-family: "Palatino Linotype", "Book Antiqua", Palatino, serif;
        color: #10253d;
        letter-spacing: 0.01em;
    }
    [data-testid="block-container"] {
        max-width: 1480px;
        padding-top: 2.25rem;
        padding-bottom: 3rem;
    }
    [data-testid="stAppViewContainer"] {
        position: relative;
        background:
            radial-gradient(circle at top left, rgba(117, 171, 214, 0.22), transparent 28%),
            radial-gradient(circle at top right, rgba(203, 130, 72, 0.16), transparent 22%),
            linear-gradient(180deg, #f6f8fb 0%, #ecf2f8 48%, #eef4f9 100%);
    }
    [data-testid="stAppViewContainer"]::before {
        content: "";
        position: fixed;
        inset: 0;
        pointer-events: none;
        opacity: 0.42;
        background-image:
            linear-gradient(rgba(54, 89, 124, 0.08) 1px, transparent 1px),
            linear-gradient(90deg, rgba(54, 89, 124, 0.08) 1px, transparent 1px);
        background-size: 44px 44px;
        mask-image: linear-gradient(180deg, rgba(0, 0, 0, 0.45), transparent 62%);
    }
    [data-testid="stHeader"] {
        background: transparent;
    }
    [data-testid="stToolbar"] {
        right: 1rem;
    }
    [data-testid="stMainBlockContainer"] {
        position: relative;
        z-index: 1;
    }
    [data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 28px;
        border: 1px solid rgba(126, 152, 177, 0.34);
        background: linear-gradient(180deg, rgba(255, 255, 255, 0.72), rgba(247, 250, 253, 0.78));
        box-shadow: 0 28px 70px rgba(16, 37, 61, 0.08);
        backdrop-filter: blur(16px);
    }
    [data-testid="stMetric"] {
        padding: 1rem 1.05rem;
        border-radius: 24px;
        border: 1px solid rgba(127, 151, 176, 0.28);
        background: linear-gradient(180deg, rgba(255,255,255,0.96) 0%, rgba(242,247,251,0.92) 100%);
        box-shadow: 0 18px 40px rgba(16, 37, 61, 0.07);
    }
    [data-testid="stMetricLabel"] p {
        color: #58708b;
        font-size: 0.84rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }
    [data-testid="stMetricValue"] {
        font-family: "Palatino Linotype", "Book Antiqua", Palatino, serif;
        color: #10253d;
    }
    .stButton button, .stDownloadButton button {
        min-height: 3rem;
        border: 1px solid #1a5a86;
        border-radius: 999px;
        background: linear-gradient(135deg, #174c73 0%, #1e678d 100%);
        color: #f6fbff;
        font-weight: 700;
        letter-spacing: 0.02em;
        box-shadow: 0 12px 28px rgba(23, 76, 115, 0.24);
    }
    .stButton button:hover, .stDownloadButton button:hover {
        border-color: #214a67;
        background: linear-gradient(135deg, #123f61 0%, #1a5a86 100%);
        color: #ffffff;
    }
    .stButton button:disabled {
        opacity: 0.5;
        box-shadow: none;
    }
    .experimental-upload-status {
        display: grid;
        gap: 0.7rem;
        padding: 0.25rem 0;
    }
    .experimental-upload-status__title {
        color: #153754;
        font-size: 1.02rem;
        font-weight: 800;
    }
    .experimental-upload-status__meta {
        color: #335066;
        line-height: 1.55;
    }
    .experimental-upload-status__error {
        padding: 0.9rem 1rem;
        border-radius: 18px;
        border: 1px solid rgba(152, 62, 48, 0.22);
        background: linear-gradient(180deg, rgba(255, 241, 238, 0.98) 0%, rgba(255, 232, 225, 0.94) 100%);
        color: #8b2d1c;
        font-weight: 700;
    }
    .experimental-upload-status__action {
        padding: 1rem 1.1rem;
        border-radius: 20px;
        border: 1px solid rgba(196, 109, 49, 0.28);
        background: linear-gradient(180deg, rgba(255, 248, 240, 0.98) 0%, rgba(255, 237, 219, 0.94) 100%);
        color: #7a431d;
        font-weight: 800;
        line-height: 1.55;
        box-shadow: 0 12px 28px rgba(122, 67, 29, 0.08);
    }
    .experimental-upload-status__block {
        padding: 0.9rem 1rem;
        border-radius: 18px;
        border: 1px solid rgba(127, 151, 176, 0.24);
        background: rgba(255, 255, 255, 0.72);
    }
    div[data-baseweb="input"] > div,
    div[data-baseweb="select"] > div,
    div[data-baseweb="popover"] > div {
        border-radius: 16px;
        border: 1.5px solid #2d5675 !important;
        background: linear-gradient(180deg, rgba(255,255,255,0.98) 0%, rgba(232,241,249,0.98) 100%) !important;
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.92), 0 8px 18px rgba(20, 53, 82, 0.08) !important;
    }
    div[data-baseweb="input"]:focus-within > div,
    div[data-baseweb="select"]:focus-within > div,
    div[data-baseweb="popover"]:focus-within > div {
        border-color: #c46d31 !important;
        box-shadow: 0 0 0 3px rgba(196, 109, 49, 0.22), 0 10px 22px rgba(20, 53, 82, 0.12) !important;
    }
    div[data-baseweb="input"] input,
    div[data-baseweb="select"] input,
    div[data-baseweb="select"] span,
    div[data-baseweb="popover"] input {
        color: #10253d !important;
        font-weight: 600 !important;
    }
    label[data-testid="stWidgetLabel"] p {
        color: #153754 !important;
        font-weight: 700 !important;
    }
    [data-testid="stSlider"] {
        padding-top: 0.35rem;
    }
    [data-testid="stExpander"] {
        border-radius: 22px;
        border: 1px solid rgba(127, 151, 176, 0.26);
        background: rgba(255, 255, 255, 0.74);
    }
    [data-testid="stDataFrame"] {
        border-radius: 22px;
        overflow: hidden;
        border: 1px solid rgba(127, 151, 176, 0.22);
        box-shadow: 0 14px 30px rgba(16, 37, 61, 0.04);
    }
    [data-testid="stTabs"] [data-baseweb="tab-list"] {
        gap: 0.45rem;
        margin-bottom: 0.95rem;
    }
    [data-testid="stTabs"] [data-baseweb="tab"] {
        height: 3rem;
        padding: 0 1rem;
        border-radius: 999px;
        border: 1px solid rgba(43, 77, 105, 0.18);
        background: linear-gradient(180deg, rgba(255,255,255,0.95) 0%, rgba(242,247,251,0.92) 100%);
        color: #173650;
        font-weight: 700;
        box-shadow: 0 12px 26px rgba(16, 37, 61, 0.04);
    }
    [data-testid="stTabs"] [aria-selected="true"] {
        border-color: #1a5a86;
        background: linear-gradient(135deg, rgba(23, 76, 115, 0.96) 0%, rgba(30, 103, 141, 0.96) 100%);
        color: #f8fbff;
        box-shadow: 0 16px 32px rgba(23, 76, 115, 0.18);
    }
    .hero-banner {
        position: relative;
        overflow: hidden;
        padding: 2rem;
        border-radius: 34px;
        background:
            linear-gradient(135deg, rgba(12, 41, 68, 0.96) 0%, rgba(23, 76, 115, 0.93) 56%, rgba(184, 106, 56, 0.88) 100%);
        color: #f6f8fb;
        box-shadow: 0 30px 80px rgba(16, 37, 61, 0.22);
        margin-bottom: 1.2rem;
    }
    .hero-banner::before {
        content: "";
        position: absolute;
        inset: auto -6% -32% 42%;
        height: 320px;
        background: radial-gradient(circle, rgba(255,255,255,0.24) 0%, rgba(255,255,255,0.02) 62%, transparent 72%);
        transform: rotate(-8deg);
    }
    .hero-banner__grid {
        position: relative;
        display: grid;
        grid-template-columns: minmax(0, 1.55fr) minmax(260px, 0.95fr);
        gap: 1.2rem;
        align-items: stretch;
    }
    .hero-banner__eyebrow {
        color: rgba(231, 241, 250, 0.82);
        font-size: 0.78rem;
        font-weight: 700;
        letter-spacing: 0.16em;
        text-transform: uppercase;
    }
    .hero-banner__title {
        margin: 0.55rem 0 0;
        color: #ffffff;
        font-size: clamp(2rem, 4vw, 3.35rem);
        line-height: 1.02;
    }
    .hero-banner__copy {
        margin: 0.85rem 0 0;
        max-width: 62ch;
        color: rgba(239, 245, 250, 0.92);
        font-size: 1.02rem;
        line-height: 1.65;
    }
    .hero-banner__chips {
        display: flex;
        flex-wrap: wrap;
        gap: 0.7rem;
        margin: 1.25rem 0 0;
    }
    .hero-banner__chip {
        padding: 0.72rem 1rem;
        border-radius: 999px;
        background: rgba(255, 255, 255, 0.12);
        border: 1px solid rgba(255, 255, 255, 0.18);
        color: #f8fbff;
        font-size: 0.92rem;
        font-weight: 700;
        backdrop-filter: blur(8px);
    }
    .hero-banner__authors {
        margin-top: 1rem;
        padding: 0.95rem 1rem;
        border-radius: 22px;
        background: rgba(255, 255, 255, 0.12);
        border: 1px solid rgba(255, 255, 255, 0.18);
        backdrop-filter: blur(10px);
    }
    .hero-banner__authors-title {
        color: rgba(231, 241, 250, 0.82);
        font-size: 0.76rem;
        font-weight: 700;
        letter-spacing: 0.14em;
        text-transform: uppercase;
    }
    .hero-banner__author-list {
        display: grid;
        gap: 0.7rem;
        margin-top: 0.75rem;
    }
    .hero-banner__author {
        display: grid;
        gap: 0.08rem;
    }
    .hero-banner__author-name {
        color: #ffffff;
        font-size: 1rem;
        font-weight: 700;
        line-height: 1.2;
    }
    .hero-banner__author-role {
        color: rgba(239, 245, 250, 0.9);
        font-size: 0.88rem;
        line-height: 1.45;
    }
    .hero-banner__panel {
        position: relative;
        padding: 1.2rem;
        border-radius: 24px;
        background: linear-gradient(180deg, rgba(245, 249, 252, 0.94) 0%, rgba(228, 238, 245, 0.9) 100%);
        border: 1px solid rgba(255, 255, 255, 0.26);
        color: #123047;
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.45);
    }
    .hero-banner__panel-title {
        margin: 0;
        color: #173650;
        font-size: 1.1rem;
        font-weight: 700;
    }
    .hero-banner__panel-copy {
        margin: 0.45rem 0 0;
        color: #385168;
        font-size: 0.94rem;
        line-height: 1.55;
    }
    .hero-banner__panel-list {
        margin: 0.95rem 0 0;
        padding: 0;
        list-style: none;
        display: grid;
        gap: 0.75rem;
    }
    .hero-banner__panel-item {
        padding: 0.75rem 0.85rem;
        border-radius: 16px;
        background: rgba(255, 255, 255, 0.78);
        border: 1px solid rgba(127, 151, 176, 0.24);
    }
    .hero-banner__panel-label {
        color: #678097;
        font-size: 0.76rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
    }
    .hero-banner__panel-value {
        margin-top: 0.2rem;
        color: #16324d;
        font-size: 0.95rem;
        font-weight: 600;
        line-height: 1.45;
    }
    .section-lead {
        margin: 0.35rem 0 0.8rem;
        padding-left: 0.2rem;
    }
    .section-lead__eyebrow {
        color: #8c5a3a;
        font-size: 0.76rem;
        font-weight: 700;
        letter-spacing: 0.16em;
        text-transform: uppercase;
    }
    .section-lead__title {
        margin: 0.32rem 0 0;
        color: #10253d;
        font-size: 1.55rem;
        line-height: 1.1;
    }
    .section-lead__copy {
        margin: 0.4rem 0 0;
        max-width: 70ch;
        color: #52697f;
        font-size: 0.98rem;
        line-height: 1.55;
    }
    .shared-state-panel {
        margin-bottom: 1rem;
        padding: 1rem 1.05rem 0.15rem;
        border-radius: 24px;
        background: linear-gradient(160deg, rgba(250,252,255,0.99) 0%, rgba(238,244,249,0.98) 100%);
        border: 1px solid #d5e0ea;
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.88);
    }
    .shared-state-panel__eyebrow {
        color: #8c5a3a;
        font-size: 0.76rem;
        font-weight: 700;
        letter-spacing: 0.14em;
        text-transform: uppercase;
    }
    .shared-state-panel__title {
        margin: 0.28rem 0 0;
        color: #10253d;
        font-size: 1.35rem;
        line-height: 1.15;
    }
    .shared-state-panel__copy {
        margin: 0.45rem 0 0;
        max-width: 72ch;
        color: #556b80;
        font-size: 0.95rem;
        line-height: 1.5;
    }
    .shared-state-panel__meta {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
        gap: 0.75rem;
        margin: 0.95rem 0 0.8rem;
    }
    .shared-state-panel__chip {
        padding: 0.8rem 0.9rem;
        border-radius: 18px;
        background: rgba(255, 255, 255, 0.96);
        border: 1px solid #d6e0ea;
    }
    .shared-state-panel__chip-label {
        color: #617588;
        font-size: 0.78rem;
        font-weight: 700;
        letter-spacing: 0.05em;
        text-transform: uppercase;
    }
    .shared-state-panel__chip-value {
        margin-top: 0.22rem;
        color: #10253d;
        font-size: 1rem;
        font-weight: 700;
        line-height: 1.3;
    }
    .drawing-showcase {
        padding: 1.25rem 1.25rem 1.15rem;
        border-radius: 30px;
        background: linear-gradient(160deg, rgba(250,252,255,0.98) 0%, rgba(236,243,249,0.98) 100%);
        border: 1px solid #d2dfeb;
        box-shadow: 0 24px 56px rgba(16, 37, 61, 0.07);
    }
    .drawing-showcase__eyebrow {
        color: #8c5a3a;
        font-size: 0.82rem;
        font-weight: 700;
        letter-spacing: 0.1em;
        text-transform: uppercase;
    }
    .drawing-showcase__title {
        margin: 0.3rem 0 0;
        color: #0f172a;
        font-size: 1.6rem;
        font-weight: 700;
        line-height: 1.15;
    }
    .drawing-showcase__copy {
        margin: 0.55rem 0 0;
        max-width: 64ch;
        color: #52697f;
        font-size: 0.98rem;
        line-height: 1.55;
    }
    .drawing-showcase__meta {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
        gap: 0.75rem;
        margin: 1rem 0 1.1rem;
    }
    .drawing-showcase__chip {
        padding: 0.8rem 0.9rem;
        border-radius: 18px;
        background: rgba(255, 255, 255, 0.95);
        border: 1px solid #d7e0e9;
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.85);
    }
    .drawing-showcase__chip-label {
        margin-bottom: 0.25rem;
        color: #64788d;
        font-size: 0.78rem;
        font-weight: 700;
        letter-spacing: 0.05em;
        text-transform: uppercase;
    }
    .drawing-showcase__chip-value {
        color: #0f172a;
        font-size: 1rem;
        font-weight: 600;
        line-height: 1.25;
    }
    .serviceability-scheme-showcase {
        margin: 1.15rem 0 0.35rem;
        padding: 1.25rem 1.25rem 1.2rem;
        border-radius: 30px;
        background: linear-gradient(165deg, rgba(251,252,254,0.98) 0%, rgba(236,242,247,0.98) 100%);
        border: 1px solid #d2dde8;
        box-shadow: 0 24px 56px rgba(16, 37, 61, 0.07);
    }
    .serviceability-scheme-showcase__eyebrow {
        color: #8c5a3a;
        font-size: 0.82rem;
        font-weight: 700;
        letter-spacing: 0.1em;
        text-transform: uppercase;
    }
    .serviceability-scheme-showcase__title {
        margin: 0.3rem 0 0;
        color: #0f172a;
        font-size: 1.6rem;
        font-weight: 700;
        line-height: 1.15;
    }
    .serviceability-scheme-showcase__copy {
        margin: 0.55rem 0 0;
        max-width: 68ch;
        color: #52697f;
        font-size: 0.98rem;
        line-height: 1.55;
    }
    .serviceability-scheme-showcase__meta {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        gap: 0.75rem;
        margin: 1rem 0 1.1rem;
    }
    .serviceability-scheme-showcase__chip {
        padding: 0.8rem 0.9rem;
        border-radius: 18px;
        background: rgba(255, 255, 255, 0.96);
        border: 1px solid #d7e0e9;
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.85);
    }
    .serviceability-scheme-showcase__chip-label {
        margin-bottom: 0.25rem;
        color: #64788d;
        font-size: 0.78rem;
        font-weight: 700;
        letter-spacing: 0.05em;
        text-transform: uppercase;
    }
    .serviceability-scheme-showcase__chip-value {
        color: #0f172a;
        font-size: 0.98rem;
        font-weight: 600;
        line-height: 1.32;
    }
    .serviceability-scheme-shell {
        margin-top: 0;
    }
    .serviceability-scheme-stage svg {
        width: min(100%, 980px);
        min-width: 680px;
    }
    .cad-shell {
        margin-top: 0;
        padding: 1rem;
        border-radius: 26px;
        background: linear-gradient(180deg, rgba(255,255,255,0.96) 0%, rgba(242,247,252,0.98) 100%);
        border: 1px solid #d7e2ed;
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.85);
    }
    .cad-stage {
        overflow-x: auto;
        padding: 1.1rem;
        border-radius: 22px;
        background:
            linear-gradient(180deg, rgba(250,252,255,0.99) 0%, rgba(236,242,248,0.99) 100%);
        border: 1px solid #d8e2ec;
    }
    .cad-stage svg {
        display: block;
        margin: 0 auto;
        width: min(100%, 1340px);
        min-width: 1040px;
        max-width: none;
        height: auto;
    }
    .serviceability-scheme-stage svg {
        width: min(100%, 980px);
        min-width: 680px;
    }
    .point-chip-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
        gap: 0.8rem;
        margin: 0.75rem 0 1rem;
    }
    .point-chip {
        padding: 0.9rem 1rem;
        border-radius: 18px;
        background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);
        border: 1px solid #d5dfe8;
        box-shadow: 0 12px 30px rgba(16, 37, 61, 0.05);
    }
    .point-chip__label {
        margin-bottom: 0.35rem;
        color: #627487;
        font-size: 0.82rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }
    .point-chip__value {
        color: #0f172a;
        font-size: 2rem;
        font-weight: 700;
        line-height: 1.05;
    }
    .chart-explanation-card {
        margin-top: 0.95rem;
        padding: 1rem 1.05rem;
        border-radius: 22px;
        background: linear-gradient(180deg, rgba(255,255,255,0.98) 0%, rgba(247,250,253,0.98) 100%);
        border: 1px solid rgba(126, 152, 177, 0.2);
        box-shadow: 0 16px 30px rgba(16, 37, 61, 0.06);
    }
    .chart-explanation-card__eyebrow {
        color: #8c5a3a;
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
    }
    .chart-explanation-card__title {
        margin-top: 0.3rem;
        color: #10253d;
        font-size: 1.05rem;
        font-weight: 700;
        line-height: 1.3;
    }
    .chart-explanation-card__meta {
        margin-top: 0.35rem;
        color: #60758a;
        font-size: 0.88rem;
        line-height: 1.5;
    }
    .chart-explanation-card__copy {
        margin: 0.65rem 0 0;
        color: #31465b;
        font-size: 0.94rem;
        line-height: 1.45;
    }
    .chart-explanation-card__value {
        margin-top: 0.35rem;
        color: #12283d;
        font-size: 1rem;
        font-weight: 700;
    }
    .chart-explanation-card__status {
        margin-top: 0.35rem;
        color: #425a71;
        font-size: 0.9rem;
        line-height: 1.45;
    }
    .chart-explanation-card__note {
        margin-top: 0.35rem;
        color: #60758a;
        font-size: 0.84rem;
        line-height: 1.45;
    }
    .chart-note {
        margin: 0.55rem 0 0.15rem;
        color: #60758a;
        font-size: 0.9rem;
        line-height: 1.5;
    }
    .termination-panel {
        margin-top: 0.95rem;
        padding: 1.1rem 1.15rem;
        border-radius: 24px;
        background: linear-gradient(165deg, rgba(250,252,255,0.98) 0%, rgba(237,243,248,0.98) 100%);
        border: 1px solid #d4e0ea;
        box-shadow: 0 18px 40px rgba(16, 37, 61, 0.06);
    }
    .termination-panel__eyebrow {
        color: #8c5a3a;
        font-size: 0.76rem;
        font-weight: 700;
        letter-spacing: 0.12em;
        text-transform: uppercase;
    }
    .termination-panel__title {
        margin: 0.35rem 0 0;
        color: #10253d;
        font-size: 1.35rem;
        line-height: 1.15;
    }
    .termination-panel__help-note {
        margin: 0.55rem 0 0;
        color: #5f7286;
        font-size: 0.9rem;
        line-height: 1.5;
    }
    .termination-panel__grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        gap: 0.75rem;
        margin-top: 0.9rem;
    }
    .termination-panel__card {
        padding: 0.85rem 0.95rem;
        border-radius: 18px;
        background: rgba(255, 255, 255, 0.94);
        border: 1px solid #d7e2ec;
    }
    .termination-panel__label {
        color: #64788d;
        font-size: 0.78rem;
        font-weight: 700;
        letter-spacing: 0.04em;
        text-transform: uppercase;
    }
    .termination-panel__value {
        margin-top: 0.3rem;
        color: #10253d;
        font-size: 0.98rem;
        font-weight: 600;
        line-height: 1.45;
    }
    .termination-panel__narrative {
        margin: 0.9rem 0 0;
        color: #4b6177;
        font-size: 0.95rem;
        line-height: 1.55;
    }
    .force-card-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 0.85rem;
        margin-top: 0.6rem;
    }
    .force-card {
        padding: 0.95rem 1rem;
        border-radius: 18px;
        background: rgba(255, 255, 255, 0.95);
        border: 1px solid #d5dfe8;
        box-shadow: 0 14px 28px rgba(16, 37, 61, 0.04);
    }
    .force-card--concrete {
        border-left: 5px solid #2d7ab7;
    }
    .force-card--steel {
        border-left: 5px solid #c06b37;
    }
    .force-card__title {
        margin-bottom: 0.7rem;
        color: #0f172a;
        font-size: 1.08rem;
        font-weight: 700;
    }
    .force-card__meta {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 0.5rem;
    }
    .force-card__meta-label {
        margin-bottom: 0.15rem;
        color: #64748b;
        font-size: 0.76rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .force-card__meta-value {
        color: #0f172a;
        font-size: 1rem;
        font-weight: 600;
    }
    .force-strip-caption {
        margin-top: 0.35rem;
        color: #52697f;
        font-size: 0.92rem;
    }
    .author-section {
        margin-top: 1.8rem;
        padding: 1.5rem;
        border-radius: 30px;
        background: linear-gradient(150deg, rgba(255,255,255,0.94) 0%, rgba(241,246,250,0.94) 100%);
        border: 1px solid rgba(126, 152, 177, 0.28);
        box-shadow: 0 26px 56px rgba(16, 37, 61, 0.08);
    }
    .author-section__eyebrow {
        color: #8c5a3a;
        font-size: 0.78rem;
        font-weight: 700;
        letter-spacing: 0.16em;
        text-transform: uppercase;
    }
    .author-section__title {
        margin: 0.35rem 0 0;
        color: #10253d;
        font-size: 1.8rem;
        line-height: 1.1;
    }
    .author-section__copy {
        margin: 0.5rem 0 0;
        max-width: 68ch;
        color: #52697f;
        line-height: 1.6;
    }
    .author-card-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
        gap: 0.9rem;
        margin-top: 1.2rem;
    }
    .author-card {
        padding: 1.15rem 1.1rem;
        border-radius: 22px;
        background: linear-gradient(180deg, rgba(255,255,255,0.98) 0%, rgba(248,251,254,0.98) 100%);
        border: 1px solid rgba(127, 151, 176, 0.24);
        box-shadow: 0 16px 36px rgba(16, 37, 61, 0.05);
    }
    .author-card__role {
        color: #8c5a3a;
        font-size: 0.78rem;
        font-weight: 700;
        letter-spacing: 0.12em;
        text-transform: uppercase;
    }
    .author-card__name {
        margin: 0.45rem 0 0;
        color: #10253d;
        font-size: 1.4rem;
        line-height: 1.15;
    }
    .author-card__description {
        margin: 0.55rem 0 0;
        color: #53697e;
        line-height: 1.6;
    }
    .app-footer {
        margin-top: 1rem;
        padding: 0.75rem 0.25rem 0;
        color: #61788c;
        font-size: 0.9rem;
        text-align: center;
    }
    .app-footer__line {
        margin: 0;
    }
    @media (max-width: 900px) {
        .hero-banner {
            padding: 1.55rem;
        }
        .hero-banner__grid {
            grid-template-columns: 1fr;
        }
        .hero-banner__title {
            font-size: 2.2rem;
        }
        .section-lead__title {
            font-size: 1.35rem;
        }
        .cad-stage svg {
            min-width: 920px;
        }
        .serviceability-scheme-stage svg {
            width: min(100%, 980px);
            min-width: 640px;
        }
    }
    @media (max-width: 640px) {
        [data-testid="block-container"] {
            padding-top: 1.2rem;
        }
        .serviceability-scheme-showcase {
            padding: 1rem 0.85rem 0.95rem;
        }
        .serviceability-scheme-showcase__title {
            font-size: 1.3rem;
        }
        .serviceability-scheme-showcase__copy {
            font-size: 0.92rem;
        }
        .serviceability-scheme-shell.cad-shell {
            padding: 0.75rem;
        }
        .serviceability-scheme-stage {
            padding: 0.75rem;
            border-radius: 18px;
        }
        .serviceability-scheme-stage svg {
            min-width: 440px;
        }
        .hero-banner {
            border-radius: 26px;
            padding: 1.35rem;
        }
        .hero-banner__copy {
            font-size: 0.95rem;
        }
        .author-section {
            padding: 1.15rem;
        }
    }
    </style>
    """


def _build_hero_banner_html() -> str:
    chips = ["Двошаровий бетон", "Експорт в Excel", "Верифікація результатів"]
    panel_rows = [
        ("Нормативна база", "ДСТУ Б В.2.6-156:2010 та ДБН В.2.6-98:2009"),
        ("Призначення", "Оцінка M_Rd, кривизни та деформацій прямокутного залізобетонного перерізу."),
        ("Формат роботи", "Інтерактивне введення параметрів, креслення та експорт розрахункових результатів."),
    ]
    fragments = [
        '<section class="hero-banner" data-role="hero-banner">',
        '<div class="hero-banner__grid">',
        "<div>",
        '<div class="hero-banner__eyebrow">ДСТУ / ДБН</div>',
        '<h1 class="hero-banner__title">Розрахунок згину залізобетонного перерізу</h1>',
        (
            '<p class="hero-banner__copy">Інженерний застосунок для аналізу двошарового прямокутного '
            "перерізу з двома шарами арматури: від геометрії та підбору матеріалів до кривизни, "
            "несучої здатності та наочних результатів для перевірки й презентації.</p>"
        ),
        '<div class="hero-banner__chips">',
    ]
    for chip in chips:
        fragments.append(f'<div class="hero-banner__chip" data-role="hero-chip">{escape(chip)}</div>')
    fragments.extend(
        [
            "</div>",
            '<section class="hero-banner__authors" data-role="hero-authors">',
            '<div class="hero-banner__authors-title">Автори</div>',
            '<div class="hero-banner__author-list" data-role="hero-author-list">',
        ]
    )
    for profile in AUTHOR_PROFILES:
        fragments.extend(
            [
                '<article class="hero-banner__author" data-role="hero-author-item">',
                f'<div class="hero-banner__author-name">{escape(profile["name"])}</div>',
                f'<div class="hero-banner__author-role">{escape(profile["role"])}</div>',
                "</article>",
            ]
        )
    fragments.extend(
        [
            "</div>",
            "</section>",
            "</div>",
            '<aside class="hero-banner__panel">',
            '<h2 class="hero-banner__panel-title">Коротко про робочу зону</h2>',
            '<p class="hero-banner__panel-copy">Сторінка поєднує нормативний розрахунок, графічну інтерпретацію перерізу та аналітичні таблиці без зміни розрахункової схеми.</p>',
            '<div class="hero-banner__panel-list">',
        ]
    )
    for label, value in panel_rows:
        fragments.extend(
            [
                '<div class="hero-banner__panel-item">',
                f'<div class="hero-banner__panel-label">{escape(label)}</div>',
                f'<div class="hero-banner__panel-value">{escape(value)}</div>',
                "</div>",
            ]
        )
    fragments.extend(["</div>", "</aside>", "</div>", "</section>"])
    return "".join(fragments)


def _build_section_lead_html(*, eyebrow: str, title: str, copy: str, data_role: str) -> str:
    return "".join(
        [
            f'<section class="section-lead" data-role="{escape(data_role)}">',
            f'<div class="section-lead__eyebrow">{escape(eyebrow)}</div>',
            f'<h2 class="section-lead__title">{escape(title)}</h2>',
            f'<p class="section-lead__copy">{escape(copy)}</p>',
            "</section>",
        ]
    )


def _build_shared_state_panel_html(
    selected_point,
    *,
    section_is_dirty: bool,
    serviceability_is_dirty: bool,
) -> str:
    if section_is_dirty:
        note = "Показано останній застосований стан перерізу; нові геометричні зміни ще не перераховані."
    elif serviceability_is_dirty:
        note = "II ГГС та експеримент спираються на останній застосований сервісний набір до натискання `Оновити перевірку`."
    else:
        note = "Активна точка кривої використовується у вкладках `II ГГС` та `Експеримент`, тому змінюйте її тут."

    chips = [
        ("Активний крок", str(selected_point.step_index)),
        ("M активної точки", f"{selected_point.moment_kNm:.2f} кН·м"),
        ("x нейтральної осі", f"{selected_point.neutral_axis_mm:.1f} мм"),
    ]

    fragments = [
        '<section class="shared-state-panel" data-role="shared-state-panel">',
        '<div class="shared-state-panel__eyebrow">Спільний контекст</div>',
        '<h3 class="shared-state-panel__title">Одна активна точка для всіх перевірок</h3>',
        f'<p class="shared-state-panel__copy">{escape(note)}</p>',
        '<div class="shared-state-panel__meta" data-role="shared-state-meta">',
    ]
    for label, value in chips:
        fragments.extend(
            [
                '<article class="shared-state-panel__chip" data-role="shared-state-chip">',
                f'<div class="shared-state-panel__chip-label">{escape(label)}</div>',
                f'<div class="shared-state-panel__chip-value">{escape(value)}</div>',
                "</article>",
            ]
        )
    fragments.extend(["</div>", "</section>"])
    return "".join(fragments)


def _build_drawing_stage_html(drawing_svg: str) -> str:
    return f'<div class="cad-shell" data-role="cad-shell"><div class="cad-stage" data-role="cad-stage">{drawing_svg}</div></div>'


def _build_serviceability_scheme_stage_html(drawing_svg: str) -> str:
    return (
        '<div class="cad-shell serviceability-scheme-shell" data-role="serviceability-scheme-shell">'
        f'<div class="cad-stage serviceability-scheme-stage" data-role="serviceability-scheme-stage">{drawing_svg}</div>'
        "</div>"
    )


def _build_drawing_showcase_html(
    derived: dict[str, object],
    drawing_svg: str,
    *,
    selected_point=None,
    note: str,
) -> str:
    concrete_rows = list(derived["concrete_rows"])
    chips = [
        ("Геометрія", f'{float(derived["section_width_mm"]):.1f} x {float(derived["section_height_mm"]):.1f} мм'),
        ("Шари бетону", f'{concrete_rows[0]["concrete_class"]} / {concrete_rows[1]["concrete_class"]}'),
    ]
    if selected_point is not None:
        chips.append(("Нейтральна вісь", f"x = {selected_point.neutral_axis_mm:.1f} мм"))
        chips.append(("Поточний крок", str(selected_point.step_index)))
    else:
        chips.append(("Стан візуалізації", "Поточна геометрія без активних оверлеїв"))

    fragments = [
        '<section class="drawing-showcase" data-role="drawing-showcase">',
        '<div class="drawing-showcase__eyebrow">Креслення перерізу</div>',
        '<h3 class="drawing-showcase__title">Переріз та епюри форм рівноваги</h3>',
        f'<p class="drawing-showcase__copy">{escape(note)}</p>',
        '<div class="drawing-showcase__meta" data-role="drawing-showcase-meta">',
    ]
    for label, value in chips:
        fragments.extend(
            [
                '<article class="drawing-showcase__chip" data-role="drawing-showcase-chip">',
                f'<div class="drawing-showcase__chip-label">{escape(label)}</div>',
                f'<div class="drawing-showcase__chip-value">{escape(value)}</div>',
                "</article>",
            ]
        )
    fragments.extend(
        [
            "</div>",
            _build_drawing_stage_html(drawing_svg),
            "</section>",
        ]
    )
    return "".join(fragments)


def _build_serviceability_scheme_showcase_html(
    drawing_svg: str,
    report,
    *,
    note: str,
) -> str:
    service_input = report.input
    chips = [
        ("Схема", SUPPORT_SCHEME_LABELS[service_input.support_scheme]),
        ("φ_creep", f"{service_input.phi_creep:.2f}"),
        ("Профіль", DEFLECTION_LIMIT_PROFILE_LABELS[service_input.deflection_limit_profile]),
        ("w_lim", f"{service_input.w_limit_mm:.3f} мм"),
        ("Тривалість", LOAD_DURATION_LABELS[service_input.load_duration]),
        ("Активна точка", f'крок {report.snapshot.step_index}, M = {report.snapshot.moment_kNm:.2f} кН·м'),
    ]
    if service_input.deflection_limit_profile == "partition_gap" and service_input.available_gap_mm is not None:
        chips.append(("Допустимий зазор", f"{service_input.available_gap_mm:.1f} мм"))

    fragments = [
        '<section class="serviceability-scheme-showcase" data-role="serviceability-scheme-showcase">',
        '<div class="serviceability-scheme-showcase__eyebrow">Сервісна схема</div>',
        '<h3 class="serviceability-scheme-showcase__title">Опори, навантаження та робота елемента</h3>',
        f'<p class="serviceability-scheme-showcase__copy">{escape(note)}</p>',
        '<div class="serviceability-scheme-showcase__meta" data-role="serviceability-scheme-meta">',
    ]
    for label, value in chips:
        fragments.extend(
            [
                '<article class="serviceability-scheme-showcase__chip" data-role="serviceability-scheme-chip">',
                f'<div class="serviceability-scheme-showcase__chip-label">{escape(label)}</div>',
                f'<div class="serviceability-scheme-showcase__chip-value">{escape(value)}</div>',
                "</article>",
            ]
        )
    fragments.extend(
        [
            "</div>",
            _build_serviceability_scheme_stage_html(drawing_svg),
            "</section>",
        ]
    )
    return "".join(fragments)


def _build_current_point_cards_html(selected_point) -> str:
    cards = [
        ("Крок", str(selected_point.step_index), "step"),
        ("M, кН·м", f"{selected_point.moment_kNm:.2f}", "moment"),
        ("κ, 1/м", f"{selected_point.curvature_1_per_m:.4f}", "curvature"),
        ("x, мм", f"{selected_point.neutral_axis_mm:.1f}", "neutral-axis"),
        ("ΣN, кН", f"{selected_point.axial_residual_kN:.4f}", "residual"),
    ]
    fragments = ['<div class="point-chip-grid" data-role="point-chip-grid">']
    for label, value, role in cards:
        fragments.append(
            "".join(
                [
                    '<article class="point-chip" data-role="point-chip">',
                    f'<div class="point-chip__label">{escape(label)}</div>',
                    f'<div class="point-chip__value" data-role="point-value-{role}">{escape(value)}</div>',
                    "</article>",
                ]
            )
        )
    fragments.append("</div>")
    return "".join(fragments)


def _build_force_cards_html(layer_force_rows: list[dict[str, float | int | str]]) -> str:
    fragments = ['<div class="force-card-grid" data-role="force-card-grid">']
    for row in layer_force_rows:
        layer_name = f"{'B' if row['kind'] == 'concrete' else 'A'}{row['index']}"
        accent_class = "force-card--concrete" if row["kind"] == "concrete" else "force-card--steel"
        fragments.extend(
            [
                f'<article class="force-card {accent_class}" data-role="force-card">',
                f'<div class="force-card__title">{escape(layer_name)}</div>',
                '<div class="force-card__meta">',
                '<div><div class="force-card__meta-label">N, кН</div>'
                f'<div class="force-card__meta-value">{float(row["force_kN"]):.2f}</div></div>',
                '<div><div class="force-card__meta-label">ε, ‰</div>'
                f'<div class="force-card__meta-value">{_to_promille(float(row["strain"])):.3f}</div></div>',
                '<div><div class="force-card__meta-label">σ, МПа</div>'
                f'<div class="force-card__meta-value">{float(row["stress_mpa"]):.2f}</div></div>',
                "</div>",
                "</article>",
            ]
        )
    fragments.append("</div>")
    return "".join(fragments)


def _build_author_cards_html() -> str:
    fragments = [
        '<section class="author-section" data-role="author-section">',
        '<div class="author-section__eyebrow">Команда</div>',
        '<h2 class="author-section__title">Автори проєкту</h2>',
        (
            '<p class="author-section__copy">Короткий авторський блок для презентаційного подання '
            "розрахункового застосунку та його інженерної інтерпретації.</p>"
        ),
        '<div class="author-card-grid">',
    ]
    for profile in AUTHOR_PROFILES:
        fragments.extend(
            [
                '<article class="author-card" data-role="author-card">',
                f'<div class="author-card__role">{escape(profile["role"])}</div>',
                f'<h3 class="author-card__name">{escape(profile["name"])}</h3>',
                f'<p class="author-card__description">{escape(profile["description"])}</p>',
                "</article>",
            ]
        )
    fragments.extend(["</div>", "</section>"])
    return "".join(fragments)


def _build_footer_html() -> str:
    return (
        '<footer class="app-footer" data-role="app-footer">'
        '<p class="app-footer__line">Презентаційний інтерфейс для нормативного аналізу згину '
        "залізобетонного перерізу з візуалізацією, таблицями та експортом у XLSX.</p>"
        "</footer>"
    )


def _get_select_index(options: list[object], current: object) -> int:
    try:
        return options.index(current)
    except ValueError:
        return 0


def _uses_parameter_a(support_scheme: str) -> bool:
    return support_scheme in {"cantilever_point_at_a", "simply_supported_two_point_symmetric"}


def _build_serviceability_theory_markdown() -> str:
    return """
### Прогини та тріщиностійкість

Сервісна перевірка виконується для вже обраної точки основного розрахунку. Момент, кривизна, положення нейтральної осі, деформації та геометрія беруться з поточної побудованої кривої `M-κ`. Джерело методики: ДСТУ Б В.2.6-156:2010, `5.3.4` і `5.4.1`-`5.4.3`.

Для тріщиностійкості сайт оцінює ширину розкриття тріщин у розтягнутій зоні та порівнює її з заданим граничним значенням `w_lim`. У підсумку показуються ключові робочі величини, нормативний ліміт і статус `OK/Не OK`.

Для прогину автоматично перевіряються вертикальні граничні прогини згинальних елементів. Нормативні профілі та межі беруться з ДСТУ Б В.1.2-3:2006: естетико-психологічні, конструктивні для перегородок, конструктивні для елементів, що розтріскуються, а також для перемичок і ригелів скління.

Довідково на сторінці також наведено горизонтальні переміщення з ДСТУ Б В.1.2-3:2006, але вони потребують уже повної розрахункової схеми будівлі, а не лише одного перерізу. Окремо враховано вимогу, що для елементів покриттів має забезпечуватись ухил покрівлі не менш як 1/200.
"""


def _build_active_state(active_inputs: dict[str, object], catalog) -> tuple[object, object]:
    section = build_section_input_from_draft(active_inputs, catalog)
    result = solve_bending_capacity(section, catalog, outer_steps=int(active_inputs.get("outer_steps", 40)))
    return section, result


def _render_section_input_tab(
    *,
    catalog,
    draft_inputs: dict[str, object],
    active_inputs: dict[str, object],
) -> tuple[dict[str, object], dict[str, object], list[str], bool]:
    st.markdown(
        _build_section_lead_html(
            eyebrow="Робоча область",
            title="Параметри перерізу та армування",
            copy="Задайте геометрію, класи бетону й арматури та перевірте, як зміна параметрів впливає на розрахунковий стан.",
            data_role="input-section-lead",
        ),
        unsafe_allow_html=True,
    )
    with st.container(border=True):
        st.subheader("Введення геометрії та армування")
        general_col, concrete_col = st.columns(2)

        with general_col:
            draft_inputs["section_height_mm"] = st.number_input(
                "Висота перерізу h, мм",
                min_value=100.0,
                value=float(draft_inputs["section_height_mm"]),
                step=10.0,
                key="draft_section_height_mm",
            )
            draft_inputs["section_width_mm"] = st.number_input(
                "Ширина перерізу b, мм",
                min_value=0.0,
                value=float(draft_inputs["section_width_mm"]),
                step=10.0,
                key="draft_section_width_mm",
            )
            draft_inputs["outer_steps"] = st.number_input(
                "Кількість кроків розрахунку",
                min_value=2,
                max_value=200,
                value=int(draft_inputs["outer_steps"]),
                step=1,
                key="draft_outer_steps",
            )

        with concrete_col:
            concrete_classes = list(catalog.concrete.keys())
            top_concrete = draft_inputs["concrete_layers"][0]
            bottom_concrete = draft_inputs["concrete_layers"][1]

            top_concrete["concrete_class"] = st.selectbox(
                "Клас бетону верхнього шару",
                concrete_classes,
                index=_get_select_index(concrete_classes, top_concrete["concrete_class"]),
                key="draft_top_concrete_class",
            )
            bottom_concrete["concrete_class"] = st.selectbox(
                "Клас бетону нижнього шару",
                concrete_classes,
                index=_get_select_index(concrete_classes, bottom_concrete["concrete_class"]),
                key="draft_bottom_concrete_class",
            )
            top_concrete["height_mm"] = st.number_input(
                "Товщина верхнього шару бетону h1, мм",
                min_value=0.0,
                value=float(top_concrete["height_mm"]),
                step=10.0,
                key="draft_top_concrete_height_mm",
            )

            concrete_derived = derive_draft_geometry(draft_inputs)
            st.metric(
                "Похідна товщина нижнього шару бетону h2, мм",
                f"{float(concrete_derived['concrete_rows'][1]['height_mm']):.1f}",
            )
            st.caption("Бі-бетонний прямокутний елемент: ширина перерізу b є сталою для обох шарів бетону.")

        st.subheader("Шари арматури")
        st.caption("Для нормативного сценарію передбачено рівно два шари арматури: верхній і нижній.")

        steel_classes = list(catalog.steel.keys())
        diameters = list(catalog.rebar_area_mm2.keys())
        for index, row in enumerate(draft_inputs["rebar_layers"]):
            row_id = str(row.get("id", f"rebar_{index + 1}"))
            row_cols = st.columns([1.0, 1.0, 0.8, 0.8, 1.0, 1.1])

            row["face"] = row_cols[0].selectbox(
                f"Грань шару арматури {index + 1}",
                [TOP_FACE, BOTTOM_FACE],
                index=_get_select_index([TOP_FACE, BOTTOM_FACE], row["face"]),
                key=f"draft_rebar_face_{row_id}",
            )
            row["distance_mm"] = row_cols[1].number_input(
                f"Відстань a{index + 1}, мм",
                min_value=0.0,
                value=float(row["distance_mm"]),
                step=5.0,
                key=f"draft_rebar_distance_{row_id}",
            )
            row["bar_count"] = row_cols[2].number_input(
                f"Кількість n{index + 1}, шт.",
                min_value=1,
                value=int(row["bar_count"]),
                step=1,
                key=f"draft_rebar_count_{row_id}",
            )
            row["diameter_mm"] = row_cols[3].selectbox(
                f"Діаметр d{index + 1}, мм",
                diameters,
                index=_get_select_index(diameters, int(row["diameter_mm"])),
                key=f"draft_rebar_diameter_{row_id}",
            )
            row["steel_class"] = row_cols[4].selectbox(
                f"Клас арматури {index + 1}",
                steel_classes,
                index=_get_select_index(steel_classes, row["steel_class"]),
                key=f"draft_rebar_class_{row_id}",
            )

            z_mm = float(row["distance_mm"]) if row["face"] == TOP_FACE else float(draft_inputs["section_height_mm"]) - float(row["distance_mm"])
            formula = "z = a" if row["face"] == TOP_FACE else "z = h - a"
            row_cols[5].markdown(f"**{formula}**\n\n`z = {z_mm:.1f} мм`")

        draft_derived = derive_draft_geometry(draft_inputs)
        validation_errors = validate_draft_inputs(draft_inputs, catalog)
        draft_changed = draft_inputs != active_inputs

        preview_col, status_col = st.columns([1.6, 1.0])
        with preview_col:
            st.subheader("Попередній перегляд геометрії")
            st.dataframe(_build_concrete_preview_df(draft_derived), width="stretch", hide_index=True)
            st.dataframe(_build_rebar_preview_df(draft_derived), width="stretch", hide_index=True)

        with status_col:
            st.subheader("Стан чернетки")
            recalculate_clicked = st.button("Перерахувати", disabled=bool(validation_errors), key="apply_draft")

            if recalculate_clicked and not validation_errors:
                st.session_state.active_inputs = copy_draft_inputs(draft_inputs)
                active_inputs = st.session_state.active_inputs
                draft_changed = False

            if validation_errors:
                st.error("Перевірте вхідні дані:\n" + "\n".join(f"- {message}" for message in validation_errors))
            elif draft_changed:
                st.warning("Є незастосовані зміни. Натисніть `Перерахувати`.")
            else:
                st.success("Показано актуальний застосований розрахунок.")

            if validation_errors or draft_changed:
                st.info("Зараз показано результати для останнього застосованого набору даних.")

        with st.expander("Ресурси для зовнішньої верифікації"):
            st.markdown(
                "- [EurocodeApplied ULS rectangular RC section](https://eurocodeapplied.com/design/en1992/uls-design-rectangular-section)\n"
                "- [CivilCalc reinforced concrete rectangular section](https://civilcalc.com/reinforced-concrete)\n"
                "- [CivilEng nonlinear deformation model](https://civileng.ru/check/rc/ndm-custom)"
            )

    return active_inputs, draft_derived, validation_errors, draft_changed


def _render_section_results_tab(
    *,
    draft_derived: dict[str, object],
    validation_errors: list[str],
    draft_changed: bool,
    show_active_overlays: bool,
    drawing_svg: str,
    selected_step: int,
    selected_point,
    section,
    catalog,
    result,
    chart_label_offsets: dict[str, dict[str, dict[str, int]]],
    curve_chart_df: pd.DataFrame,
    concrete_moment_df: pd.DataFrame,
    top_rebar_df: pd.DataFrame,
    bottom_rebar_df: pd.DataFrame,
    analytics_summary_df: pd.DataFrame,
    concrete_limit_annotation: ChartLimitAnnotation,
    top_rebar_limit_annotation: ChartLimitAnnotation,
    bottom_rebar_limit_annotation: ChartLimitAnnotation,
    concrete_last_point_annotation: ChartLimitAnnotation,
    top_rebar_last_point_annotation: ChartLimitAnnotation,
    bottom_rebar_last_point_annotation: ChartLimitAnnotation,
    top_rebar,
    bottom_rebar,
) -> None:
    layer_force_rows = build_layer_force_table(section, catalog, selected_point)

    st.markdown(
        _build_section_lead_html(
            eyebrow="Переріз",
            title="Креслення, графіки та пояснення",
            copy="Тут зібрано весь базовий нелінійний розрахунок перерізу без сервісної перевірки та без експериментальних накладень.",
            data_role="results-section-lead",
        ),
        unsafe_allow_html=True,
    )

    with st.container(border=True):
        if validation_errors:
            drawing_note = "Масштабні епюри та розрахункові підписи з'являться після виправлення геометрії та перерахунку."
        elif draft_changed:
            drawing_note = "Епюри доступних форм показуються лише для останнього застосованого стану після `Перерахувати`."
        else:
            drawing_note = "Креслення показує геометрію перерізу та доступні епюри форм рівноваги для обраної точки."
        st.markdown(
            _build_drawing_showcase_html(
                draft_derived,
                drawing_svg,
                selected_point=selected_point if show_active_overlays else None,
                note=drawing_note,
            ),
            unsafe_allow_html=True,
        )

    with st.container(border=True):
        st.subheader("Поточна розрахункова точка")
        if show_active_overlays:
            st.markdown(_build_current_point_cards_html(selected_point), unsafe_allow_html=True)
            st.markdown('<div class="force-strip-caption">Робочі зусилля за шарами для обраної точки.</div>', unsafe_allow_html=True)
            st.markdown(_build_force_cards_html(layer_force_rows), unsafe_allow_html=True)
        elif validation_errors:
            st.caption("Блок поточної точки стане доступним після виправлення геометрії.")
        else:
            st.caption("Блок поточної точки з'явиться після застосування змін кнопкою `Перерахувати`.")

    st.markdown(
        _build_section_lead_html(
            eyebrow="Аналітика",
            title="Графіки, деформації та таблиці",
            copy="Основні графіки M-κ і момент-деформація для бетону та арматури зі зведеною таблицею по кроках.",
            data_role="analytics-section-lead",
        ),
        unsafe_allow_html=True,
    )
    st.subheader("Діаграма M-κ")
    curve_chart = (
        alt.Chart(curve_chart_df)
        .mark_line(point=True)
        .encode(
            x=alt.X("κ, 1/м:Q", title="κ, 1/м"),
            y=alt.Y("M, кН·м:Q", title="M, кН·м"),
            tooltip=["Крок", "κ, 1/м", "M, кН·м", "ε_c,top, 10^-5", "ε_c,bot, 10^-5"],
        )
        .properties(height=320)
    )
    selected_curve_chart = (
        alt.Chart(curve_chart_df[curve_chart_df["Крок"] == selected_step])
        .mark_point(color="#c2410c", filled=True, size=180)
        .encode(
            x=alt.X("κ, 1/м:Q"),
            y=alt.Y("M, кН·м:Q"),
            tooltip=["Крок", "κ, 1/м", "M, кН·м", "ε_c,top, 10^-5", "ε_c,bot, 10^-5"],
        )
    )
    st.altair_chart(alt.layer(curve_chart, selected_curve_chart), width="stretch")
    st.markdown(
        (
            '<div class="chart-note" data-role="chart-caption-curvature">'
            "κ показує кривизну перерізу: що більше κ, то сильніше викривляється переріз при згині."
            "</div>"
        ),
        unsafe_allow_html=True,
    )

    with st.container(border=True):
        st.subheader("Момент-деформація бетону")
        st.caption(f"Клас бетону {section.concrete_layers[0].concrete_class}, верхня грань перерізу.")
        with st.expander("Коригування підписів графіка", expanded=False):
            concrete_label_offsets = _render_chart_label_offset_controls(
                chart_label_offsets,
                chart_id="concrete_moment_strain",
            )
        st.altair_chart(
            _build_moment_strain_chart(
                concrete_moment_df,
                x_field="ε_c,top, 10^-5",
                selected_step=selected_step,
                tooltip_fields=["Крок", "ε_c,top, 10^-5", "M, кН·м"],
                annotations=[
                    ChartAnnotationOverlay(
                        concrete_limit_annotation,
                        "#8c5a3a",
                        text_mode="symbol",
                        label_text=_build_annotation_callout_text(concrete_limit_annotation),
                        manual_dx=concrete_label_offsets["limit"]["dx"],
                        manual_dy=concrete_label_offsets["limit"]["dy"],
                    ),
                    ChartAnnotationOverlay(
                        concrete_last_point_annotation,
                        "#334155",
                        text_mode="symbol",
                        label_position="below",
                        label_text=_build_annotation_callout_text(concrete_last_point_annotation),
                        manual_dx=concrete_label_offsets["max"]["dx"],
                        manual_dy=concrete_label_offsets["max"]["dy"],
                    ),
                ],
            ),
            width="stretch",
        )
        st.markdown(
            _build_concrete_chart_explanation_html(
                chart_title="Момент-деформація бетону",
                concrete_class=section.concrete_layers[0].concrete_class,
                limit_annotation=concrete_limit_annotation,
                max_annotation=concrete_last_point_annotation,
            ),
            unsafe_allow_html=True,
        )

    with st.container(border=True):
        st.subheader("Момент-деформація верхньої арматури")
        st.caption(f"A{top_rebar[0]}, {top_rebar[1].steel_class}, z = {top_rebar[1].z_mm:.1f} мм")
        with st.expander("Коригування підписів графіка", expanded=False):
            top_rebar_label_offsets = _render_chart_label_offset_controls(
                chart_label_offsets,
                chart_id="top_rebar_moment_strain",
            )
        st.altair_chart(
            _build_moment_strain_chart(
                top_rebar_df,
                x_field="ε_s, 10^-5",
                selected_step=selected_step,
                tooltip_fields=["Крок", "ε_s, 10^-5", "M, кН·м"],
                annotations=[
                    ChartAnnotationOverlay(
                        top_rebar_limit_annotation,
                        "#8c5a3a",
                        text_mode="symbol",
                        label_text=_build_annotation_callout_text(top_rebar_limit_annotation),
                        manual_dx=top_rebar_label_offsets["limit"]["dx"],
                        manual_dy=top_rebar_label_offsets["limit"]["dy"],
                    ),
                    ChartAnnotationOverlay(
                        top_rebar_last_point_annotation,
                        "#334155",
                        text_mode="symbol",
                        label_position="below",
                        label_text=_build_annotation_callout_text(top_rebar_last_point_annotation),
                        manual_dx=top_rebar_label_offsets["max"]["dx"],
                        manual_dy=top_rebar_label_offsets["max"]["dy"],
                    ),
                ],
            ),
            width="stretch",
        )
        st.markdown(
            _build_rebar_chart_explanation_html(
                chart_title="Момент-деформація верхньої арматури",
                rebar_label=f"A{top_rebar[0]}",
                steel_class=top_rebar[1].steel_class,
                z_mm=top_rebar[1].z_mm,
                limit_annotation=top_rebar_limit_annotation,
                max_annotation=top_rebar_last_point_annotation,
            ),
            unsafe_allow_html=True,
        )

    with st.container(border=True):
        st.subheader("Момент-деформація нижньої арматури")
        st.caption(f"A{bottom_rebar[0]}, {bottom_rebar[1].steel_class}, z = {bottom_rebar[1].z_mm:.1f} мм")
        with st.expander("Коригування підписів графіка", expanded=False):
            bottom_rebar_label_offsets = _render_chart_label_offset_controls(
                chart_label_offsets,
                chart_id="bottom_rebar_moment_strain",
            )
        st.altair_chart(
            _build_moment_strain_chart(
                bottom_rebar_df,
                x_field="ε_s, 10^-5",
                selected_step=selected_step,
                tooltip_fields=["Крок", "ε_s, 10^-5", "M, кН·м"],
                annotations=[
                    ChartAnnotationOverlay(
                        bottom_rebar_limit_annotation,
                        "#8c5a3a",
                        text_mode="symbol",
                        label_text=_build_annotation_callout_text(bottom_rebar_limit_annotation),
                        manual_dx=bottom_rebar_label_offsets["limit"]["dx"],
                        manual_dy=bottom_rebar_label_offsets["limit"]["dy"],
                    ),
                    ChartAnnotationOverlay(
                        bottom_rebar_last_point_annotation,
                        "#334155",
                        text_mode="symbol",
                        label_position="below",
                        label_text=_build_annotation_callout_text(bottom_rebar_last_point_annotation),
                        manual_dx=bottom_rebar_label_offsets["max"]["dx"],
                        manual_dy=bottom_rebar_label_offsets["max"]["dy"],
                    ),
                ],
            ),
            width="stretch",
        )
        st.markdown(
            _build_rebar_chart_explanation_html(
                chart_title="Момент-деформація нижньої арматури",
                rebar_label=f"A{bottom_rebar[0]}",
                steel_class=bottom_rebar[1].steel_class,
                z_mm=bottom_rebar[1].z_mm,
                limit_annotation=bottom_rebar_limit_annotation,
                max_annotation=bottom_rebar_last_point_annotation,
            ),
            unsafe_allow_html=True,
        )

    st.caption("Зведена таблиця по всіх кроках розрахунку.")
    st.dataframe(analytics_summary_df, width="stretch")
    st.markdown(_build_termination_summary_html(result), unsafe_allow_html=True)


def _render_serviceability_tab(
    *,
    section,
    active_inputs: dict[str, object],
    selected_step: int,
    selected_point,
    catalog,
    result,
    chart_label_offsets: dict[str, dict[str, dict[str, int]]],
    serviceability_draft_inputs: dict[str, object],
    serviceability_active_inputs: dict[str, object],
) -> tuple[dict[str, object], list[str], bool, object, pd.DataFrame]:
    support_scheme_labels = list(SUPPORT_SCHEME_LABELS.values())
    support_scheme_by_label = {label: code for code, label in SUPPORT_SCHEME_LABELS.items()}
    deflection_profile_labels = list(DEFLECTION_LIMIT_PROFILE_LABELS.values())
    deflection_profile_by_label = {label: code for code, label in DEFLECTION_LIMIT_PROFILE_LABELS.items()}
    load_duration_labels = list(LOAD_DURATION_LABELS.values())
    load_duration_by_label = {label: code for code, label in LOAD_DURATION_LABELS.items()}

    st.markdown(
        _build_section_lead_html(
            eyebrow="II ГГС",
            title="Прогини та тріщиностійкість",
            copy="Після основного розрахунку перерізу задайте параметри сервісної перевірки та оновіть лише блок II групи граничних станів.",
            data_role="serviceability-section-lead",
        ),
        unsafe_allow_html=True,
    )

    with st.container(border=True):
        st.subheader("Перевірка тріщин та прогинів")
        st.caption(
            "Блок використовує поточну вибрану точку основної кривої. "
            "Зміна параметрів нижче не запускає повторно базовий нелінійний розрахунок перерізу."
        )

        service_left, service_mid, service_right = st.columns(3)
        serviceability_draft_inputs["span_mm"] = service_left.number_input(
            "Розрахунковий проліт l, мм",
            min_value=1.0,
            value=float(serviceability_draft_inputs["span_mm"]),
            step=100.0,
            key="draft_serviceability_span_mm",
        )
        selected_support_label = service_left.selectbox(
            "Розрахункова схема для прогину",
            support_scheme_labels,
            index=_get_select_index(
                support_scheme_labels,
                SUPPORT_SCHEME_LABELS.get(str(serviceability_draft_inputs["support_scheme"]), support_scheme_labels[0]),
            ),
            key="draft_serviceability_support_scheme",
        )
        serviceability_draft_inputs["support_scheme"] = support_scheme_by_label[selected_support_label]
        serviceability_draft_inputs["phi_creep"] = service_left.number_input(
            "Коефіцієнт повзучості φ_creep",
            min_value=0.0,
            value=float(serviceability_draft_inputs["phi_creep"]),
            step=0.1,
            key="draft_serviceability_phi_creep",
        )

        selected_profile_label = service_mid.selectbox(
            "Нормативний профіль обмеження прогину",
            deflection_profile_labels,
            index=_get_select_index(
                deflection_profile_labels,
                DEFLECTION_LIMIT_PROFILE_LABELS.get(
                    str(serviceability_draft_inputs["deflection_limit_profile"]),
                    deflection_profile_labels[0],
                ),
            ),
            key="draft_serviceability_deflection_limit_profile",
        )
        serviceability_draft_inputs["deflection_limit_profile"] = deflection_profile_by_label[selected_profile_label]
        if _uses_parameter_a(str(serviceability_draft_inputs["support_scheme"])):
            max_a_mm = max(1.0, float(serviceability_draft_inputs["span_mm"]) - 1.0)
            current_a_mm = serviceability_draft_inputs.get("a_mm")
            default_a_mm = float(current_a_mm) if current_a_mm not in {None, ""} else min(1000.0, max_a_mm)
            serviceability_draft_inputs["a_mm"] = service_mid.number_input(
                "Відстань a, мм",
                min_value=1.0,
                max_value=max_a_mm,
                value=min(default_a_mm, max_a_mm),
                step=50.0,
                key="draft_serviceability_a_mm",
            )
        else:
            serviceability_draft_inputs["a_mm"] = None
            service_mid.caption("Для обраної схеми параметр `a` не застосовується.")

        if str(serviceability_draft_inputs["deflection_limit_profile"]) == "partition_gap":
            current_gap_mm = serviceability_draft_inputs.get("available_gap_mm")
            serviceability_draft_inputs["available_gap_mm"] = service_mid.number_input(
                "Допустимий зазор, мм",
                min_value=0.0,
                value=40.0 if current_gap_mm in {None, ""} else float(current_gap_mm),
                step=1.0,
                key="draft_serviceability_available_gap_mm",
            )
        else:
            serviceability_draft_inputs["available_gap_mm"] = None
            service_mid.caption("Для інших профілів межа визначається автоматично від прольоту.")

        serviceability_draft_inputs["w_limit_mm"] = service_right.number_input(
            "Гранична ширина розкриття тріщин w_lim, мм",
            min_value=0.05,
            value=float(serviceability_draft_inputs["w_limit_mm"]),
            step=0.05,
            key="draft_serviceability_w_limit_mm",
        )
        selected_load_duration_label = service_right.selectbox(
            "Тривалість навантаження для тріщин",
            load_duration_labels,
            index=_get_select_index(
                load_duration_labels,
                LOAD_DURATION_LABELS.get(str(serviceability_draft_inputs["load_duration"]), load_duration_labels[0]),
            ),
            key="draft_serviceability_load_duration",
        )
        serviceability_draft_inputs["load_duration"] = load_duration_by_label[selected_load_duration_label]
        service_right.caption("Для тріщин використовується короткочасний або довготривалий режим навантаження.")

        serviceability_validation_errors = validate_serviceability_inputs(serviceability_draft_inputs)
        serviceability_draft_changed = serviceability_draft_inputs != serviceability_active_inputs
        apply_serviceability_clicked = st.button(
            "Оновити перевірку",
            disabled=bool(serviceability_validation_errors),
            key="apply_serviceability",
        )

        if apply_serviceability_clicked and not serviceability_validation_errors:
            st.session_state.serviceability_active_inputs = copy_draft_inputs(serviceability_draft_inputs)
            serviceability_active_inputs = st.session_state.serviceability_active_inputs
            serviceability_draft_changed = False

        if serviceability_validation_errors:
            st.error("Перевірте параметри II ГГС:\n" + "\n".join(f"- {message}" for message in serviceability_validation_errors))
        elif serviceability_draft_changed:
            st.warning("Є незастосовані зміни для перевірки прогинів і тріщиностійкості. Натисніть `Оновити перевірку`.")
        else:
            st.success("Показано актуальні результати перевірки II групи граничних станів.")

        active_service_input = build_serviceability_input(serviceability_active_inputs)
        serviceability_report = build_serviceability_report(
            section,
            active_inputs,
            selected_point,
            catalog,
            service_input=active_service_input,
        )
        deflection_curve_df = _build_deflection_curve_df(result, active_service_input)
        deflection_limit_annotation = _build_limit_annotation(
            result.curve_points,
            x_values=deflection_curve_df["f, мм"].tolist(),
            target_strain=serviceability_report.deflection.limit.limit_mm,
            label="f_u",
        )
        serviceability_scheme_svg = build_serviceability_scheme_svg(serviceability_report)
        if serviceability_validation_errors:
            serviceability_scheme_note = (
                "Схема та графічні індикатори показують останній коректно застосований набір II ГГС, "
                "доки нові параметри не будуть виправлені й застосовані."
            )
        elif serviceability_draft_changed:
            serviceability_scheme_note = (
                "Схема відповідає останньому застосованому набору параметрів II ГГС. "
                "Після `Оновити перевірку` креслення й індикатори синхронізуються з чернеткою."
            )
        else:
            serviceability_scheme_note = (
                "Креслення показує активну розрахункову схему, умовну деформовану вісь та ступінь "
                "використання лімітів прогину і тріщиностійкості."
            )
        st.markdown(
            _build_serviceability_scheme_showcase_html(
                serviceability_scheme_svg,
                serviceability_report,
                note=serviceability_scheme_note,
            ),
            unsafe_allow_html=True,
        )

        st.subheader("Діаграма M-f")
        with st.expander("Коригування підписів графіка", expanded=False):
            deflection_label_offsets = _render_chart_label_offset_controls(
                chart_label_offsets,
                chart_id="deflection_mf",
            )
        st.altair_chart(
            _build_moment_strain_chart(
                deflection_curve_df,
                x_field="f, мм",
                selected_step=selected_step,
                tooltip_fields=["Крок", "f, мм", "M, кН·м"],
                annotations=[
                    ChartAnnotationOverlay(
                        deflection_limit_annotation,
                        "#8c5a3a",
                        text_mode="symbol",
                        label_text=_build_deflection_annotation_callout_text(deflection_limit_annotation),
                        manual_dx=deflection_label_offsets["limit"]["dx"],
                        manual_dy=deflection_label_offsets["limit"]["dy"],
                    ),
                ],
            ),
            width="stretch",
        )
        st.markdown(
            (
                '<div class="chart-note" data-role="chart-caption-deflection">'
                "Графік показує, як змінюється прогин f для всіх уже побудованих точок основної кривої, і де розташована нормативна межа f_u."
                "</div>"
            ),
            unsafe_allow_html=True,
        )

        service_input = serviceability_report.input
        crack_width = serviceability_report.crack_width
        deflection = serviceability_report.deflection
        crack_col, deflection_col = st.columns(2)

        with crack_col:
            st.markdown("#### Ширина розкриття тріщин")
            st.metric("Розрахункова ширина тріщини w_k, мм", f"{crack_width.w_k_mm:.3f}")
            st.metric("Гранична ширина w_lim, мм", f"{crack_width.w_limit_mm:.3f}")
            st.metric("Статус за тріщинами", "OK" if crack_width.is_within_limit else "Не OK")
            st.markdown(
                "\n".join(
                    [
                        "ДСТУ Б В.2.6-156:2010, 5.3.4.",
                        f"- Поточна точка: крок {serviceability_report.snapshot.step_index}, M = {serviceability_report.snapshot.moment_kNm:.2f} кН·м.",
                        f"- `σ_s = {_format_optional_number(crack_width.sigma_s_mpa, digits=2)} МПа`.",
                        f"- `ρ_p,eff = {_format_optional_number(crack_width.rho_p_eff, digits=4)}`.",
                        f"- `s_r,max = {_format_optional_number(crack_width.crack_spacing_mm, digits=2)} мм`.",
                        f"- Режим навантаження: `{LOAD_DURATION_LABELS[service_input.load_duration]}`.",
                    ]
                )
            )
            if crack_width.note:
                st.info(crack_width.note)

        with deflection_col:
            st.markdown("#### Перевірка прогину")
            st.metric("Розрахунковий прогин f, мм", f"{deflection.deflection_mm:.3f}")
            st.metric("Граничний прогин f_u, мм", f"{deflection.limit.limit_mm:.3f}")
            st.metric("Статус за прогином", "OK" if deflection.is_within_limit else "Не OK")
            st.markdown(
                "\n".join(
                    [
                        "ДСТУ Б В.2.6-156:2010, 5.4.3; ДСТУ Б В.1.2-3:2006.",
                        f"- Схема: `{SUPPORT_SCHEME_LABELS[service_input.support_scheme]}`.",
                        f"- Профіль: `{DEFLECTION_LIMIT_PROFILE_LABELS[service_input.deflection_limit_profile]}`.",
                        f"- `k_m = {deflection.k_m:.5f}`.",
                        f"- `κ_eff = {deflection.effective_curvature_1_per_m:.6f} 1/м`.",
                        f"- Правило ліміту: {deflection.limit.rule_text}",
                    ]
                )
            )
            if deflection.limit.requires_additional_data or deflection.note:
                st.warning(deflection.note or deflection.limit.warning_message or "Для цього профілю потрібні додаткові конструктивні дані.")

        st.markdown(_build_serviceability_theory_markdown())

    return (
        serviceability_active_inputs,
        serviceability_validation_errors,
        serviceability_draft_changed,
        serviceability_report,
        deflection_curve_df,
    )


def _render_experimental_tab(
    *,
    experimental_dataset: ExperimentalDataset | None,
    experimental_error: str | None,
    experimental_file_name: str | None,
    serviceability_report,
    deflection_curve_df: pd.DataFrame,
    concrete_moment_df: pd.DataFrame,
    top_rebar_df: pd.DataFrame,
    bottom_rebar_df: pd.DataFrame,
    concrete_limit_annotation: ChartLimitAnnotation,
    top_rebar_limit_annotation: ChartLimitAnnotation,
    bottom_rebar_limit_annotation: ChartLimitAnnotation,
    concrete_last_point_annotation: ChartLimitAnnotation,
    top_rebar_last_point_annotation: ChartLimitAnnotation,
    bottom_rebar_last_point_annotation: ChartLimitAnnotation,
) -> tuple[ExperimentalDataset | None, str | None, str | None]:
    pending_inspection, pending_file_name = _load_pending_experimental_inspection_from_session()
    st.markdown(
        _build_section_lead_html(
            eyebrow="Експеримент",
            title="Порівняння теорії та експерименту",
            copy="Тут завантажується Excel з експериментальними кривими, а теорія накладається лише за потреби окремим прапорцем.",
            data_role="experimental-section-lead",
        ),
        unsafe_allow_html=True,
    )
    with st.container(border=True):
        st.subheader("Експериментальні дані для порівняння")
        st.caption(
            "Завантажте або канонічний шаблон Excel з аркушами M_f / M_eps_c / M_eps_s_top / M_eps_s_bot, "
            "або сирий лабораторний Excel з 4 таблицями на одному аркуші. Для сирого файлу система спочатку "
            "покаже знайдені блоки й попросить підтвердження."
        )
        upload_col, template_col, confirm_col, clear_col = st.columns([1.4, 1.0, 1.0, 0.9])
        uploaded_workbook = upload_col.file_uploader(
            "Файл експериментальних кривих (.xlsx)",
            type=["xlsx"],
            key="experimental_workbook_upload",
        )
        template_col.download_button(
            "Завантажити шаблон Excel",
            data=build_experimental_template_workbook_bytes(),
            file_name="experimental_curves_template.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        clear_clicked = clear_col.button(
            "Очистити експериментальні дані",
            disabled=(
                st.session_state.get("experimental_workbook_bytes") is None
                and st.session_state.get("experimental_pending_workbook_bytes") is None
            ),
            key="clear_experimental_workbook",
        )

        if clear_clicked:
            _clear_experimental_dataset_state()
            st.rerun()

        if uploaded_workbook is not None:
            uploaded_bytes = uploaded_workbook.getvalue()
            stored_bytes = st.session_state.get("experimental_pending_workbook_bytes")
            if stored_bytes is None:
                stored_bytes = st.session_state.get("experimental_workbook_bytes")
            stored_name = st.session_state.get("experimental_pending_workbook_name")
            if stored_name is None:
                stored_name = st.session_state.get("experimental_workbook_name")
            if uploaded_bytes != stored_bytes or uploaded_workbook.name != stored_name:
                experimental_error = _apply_uploaded_experimental_workbook(
                    st.session_state,
                    workbook_bytes=uploaded_bytes,
                    file_name=uploaded_workbook.name,
                )
                pending_inspection, pending_file_name = _load_pending_experimental_inspection_from_session()
                experimental_dataset, confirmed_error = _load_experimental_dataset_from_session()
                experimental_error = experimental_error or confirmed_error
                experimental_file_name = (
                    str(st.session_state.get("experimental_workbook_name"))
                    if st.session_state.get("experimental_workbook_name")
                    else None
                )

        confirm_clicked = confirm_col.button(
            "Підтвердити та показати графіки",
            disabled=not (
                pending_inspection is not None
                and pending_inspection.status == "ready"
                and pending_inspection.dataset is not None
            ),
            key="confirm_experimental_workbook",
        )

        if confirm_clicked:
            experimental_error = _confirm_pending_experimental_workbook(st.session_state)
            if experimental_error is None:
                st.rerun()

        if experimental_dataset is None and experimental_error is None and pending_inspection is None:
            experimental_file_name = None
        elif experimental_file_name is None and st.session_state.get("experimental_workbook_name"):
            experimental_file_name = str(st.session_state.get("experimental_workbook_name"))

        st.markdown(
            _build_experimental_upload_status_html(
                experimental_dataset,
                file_name=experimental_file_name,
                error_message=experimental_error,
                pending_inspection=pending_inspection,
                pending_file_name=pending_file_name,
            ),
            unsafe_allow_html=True,
        )

    show_theory = st.checkbox("Показати теорію", value=bool(st.session_state.experimental_show_theory), key="experimental_show_theory")
    st.caption("Помаранчева лінія показує експеримент. Синя пунктирна теоретична крива додається лише коли прапорець увімкнено.")

    target_deflection_mm = float(serviceability_report.deflection.limit.limit_mm)
    theoretical_reference_df = _build_theoretical_deflection_reference_df(
        deflection_curve_df,
        concrete_moment_df,
        top_rebar_df,
        bottom_rebar_df,
    )
    theoretical_state = _build_theoretical_state_at_deflection(
        theoretical_reference_df,
        target_deflection_mm=target_deflection_mm,
    )
    experimental_deflection_annotation = _build_experimental_deflection_annotation(
        _experimental_chart_df(experimental_dataset, chart_id="deflection_mf"),
        target_deflection_mm=target_deflection_mm,
    )
    summary_config = {
        "deflection_mf": {
            "limit_annotation": ChartLimitAnnotation(label="f_u", target_strain=target_deflection_mm, moment_kNm=None, within_chart_range=True),
            "max_annotation": ChartLimitAnnotation(label="f_u", target_strain=target_deflection_mm, moment_kNm=None, within_chart_range=True),
        },
        "concrete_moment_strain": {
            "limit_annotation": concrete_limit_annotation,
            "max_annotation": concrete_last_point_annotation,
        },
        "top_rebar_moment_strain": {
            "limit_annotation": top_rebar_limit_annotation,
            "max_annotation": top_rebar_last_point_annotation,
        },
        "bottom_rebar_moment_strain": {
            "limit_annotation": bottom_rebar_limit_annotation,
            "max_annotation": bottom_rebar_last_point_annotation,
        },
    }

    experimental_panels = [
        ("M-f", "Діаграма M-f", "deflection_mf", "f, мм", _experimental_chart_df(experimental_dataset, chart_id="deflection_mf"), deflection_curve_df),
        ("M-εc", "Момент-деформація бетону", "concrete_moment_strain", "ε_c,top, 10^-5", _experimental_chart_df(experimental_dataset, chart_id="concrete_moment_strain"), concrete_moment_df),
        ("M-εs(top)", "Момент-деформація верхньої арматури", "top_rebar_moment_strain", "ε_s, 10^-5", _experimental_chart_df(experimental_dataset, chart_id="top_rebar_moment_strain"), top_rebar_df),
        ("M-εs(bot)", "Момент-деформація нижньої арматури", "bottom_rebar_moment_strain", "ε_s, 10^-5", _experimental_chart_df(experimental_dataset, chart_id="bottom_rebar_moment_strain"), bottom_rebar_df),
    ]
    experimental_tabs = st.tabs([item[0] for item in experimental_panels])
    for tab, panel in zip(experimental_tabs, experimental_panels, strict=True):
        _, title, chart_id, x_field, panel_experimental_df, panel_theory_df = panel
        with tab:
            st.subheader(title)
            chart_annotations: list[ChartAnnotationOverlay] = []
            if chart_id == "deflection_mf":
                if show_theory and theoretical_state.moment_kNm is not None:
                    chart_annotations.append(
                        ChartAnnotationOverlay(
                            _build_theory_deflection_annotation(theoretical_state),
                            THEORY_OVERLAY_COLOR,
                            label_text="Theory @ f_u",
                        )
                    )
                if experimental_deflection_annotation.moment_kNm is not None:
                    chart_annotations.append(
                        ChartAnnotationOverlay(
                            experimental_deflection_annotation,
                            EXPERIMENTAL_OVERLAY_COLOR,
                            label_position="below",
                            label_text="Exp @ f_u",
                        )
                    )
            elif show_theory:
                theory_material_annotation = _build_theory_material_annotation(theoretical_state, chart_id=chart_id)
                if theory_material_annotation.within_chart_range and theory_material_annotation.moment_kNm is not None:
                    chart_annotations.append(
                        ChartAnnotationOverlay(
                            theory_material_annotation,
                            THEORY_OVERLAY_COLOR,
                            label_text="Theory @ f_u",
                        )
                    )
                limit_annotation = summary_config[chart_id]["limit_annotation"]
                max_annotation = summary_config[chart_id]["max_annotation"]
                chart_annotations.extend(
                    [
                        ChartAnnotationOverlay(
                            limit_annotation,
                            "#8c5a3a",
                            label_text=limit_annotation.label,
                        ),
                        ChartAnnotationOverlay(
                            max_annotation,
                            "#334155",
                            label_position="below",
                            label_text=max_annotation.label,
                        ),
                    ]
                )
            if panel_experimental_df is None and (panel_theory_df is None or panel_theory_df.empty or not show_theory):
                st.info("Експериментальні дані для цього графіка не завантажені.")
            else:
                if panel_experimental_df is None:
                    st.info("Експериментальні дані для цього графіка не завантажені. Показано лише теоретичну криву.")
                st.altair_chart(
                    _build_experimental_primary_chart(
                        x_field=x_field,
                        experimental_df=panel_experimental_df,
                        theory_df=panel_theory_df,
                        show_theory=show_theory,
                        annotations=chart_annotations,
                    ),
                    width="stretch",
                )
            st.markdown(
                _build_experimental_reference_summary_html(
                    chart_id=chart_id,
                    target_deflection_mm=target_deflection_mm,
                    theoretical_state=theoretical_state,
                    experimental_annotation=experimental_deflection_annotation if chart_id == "deflection_mf" else None,
                    limit_annotation=summary_config[chart_id]["limit_annotation"],
                    max_annotation=summary_config[chart_id]["max_annotation"],
                ),
                unsafe_allow_html=True,
            )
            with st.expander("Таблиця відхилень та допоміжні дані", expanded=False):
                _render_experimental_comparison(
                    panel_theory_df,
                    dataset=experimental_dataset,
                    chart_id=chart_id,
                )

    return experimental_dataset, experimental_error, experimental_file_name


def _render_shared_summary(
    *,
    result,
    selected_step: int,
    selected_point,
    validation_errors: list[str],
    draft_changed: bool,
    serviceability_validation_errors: list[str],
    serviceability_draft_changed: bool,
    workbook_bytes: bytes,
) -> None:
    st.markdown(
        _build_section_lead_html(
            eyebrow="Спільний стан",
            title="Активний контекст розрахунку",
            copy="Обрана точка кривої використовується одночасно у вкладках `Переріз`, `II ГГС` і `Експеримент`, а експорт збирає всі актуальні результати.",
            data_role="shared-state-lead",
        ),
        unsafe_allow_html=True,
    )
    with st.container(border=True):
        st.markdown(
            _build_shared_state_panel_html(
                selected_point,
                section_is_dirty=bool(validation_errors or draft_changed),
                serviceability_is_dirty=bool(serviceability_validation_errors or serviceability_draft_changed),
            ),
            unsafe_allow_html=True,
        )
        metric_left, metric_mid, export_col = st.columns([1.0, 1.0, 0.9])
        with metric_left:
            st.metric("Несуча здатність M_Rd, кН·м", f"{result.peak_moment_kNm:.2f}")
        with metric_mid:
            st.metric("Кривизна κ_peak, 1/м", f"{result.peak_point.curvature_1_per_m:.4f}")
        with export_col:
            st.metric("Момент активної точки M, кН·м", f"{selected_point.moment_kNm:.2f}")
            st.download_button(
                "Завантажити результати у XLSX",
                data=workbook_bytes,
                file_name="bending_results.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        st.slider(
            "Розрахункова точка",
            min_value=1,
            max_value=len(result.curve_points),
            value=selected_step,
            key="selected_curve_step",
        )
        st.caption("Зміна кроку оновлює активну точку для перерізу, II ГГС та експериментального накладання.")


def _legacy_main_pre_tabs() -> None:
    st.set_page_config(page_title="Розрахунок згину ЗБ перерізу", layout="wide")
    st.markdown(_build_custom_css(), unsafe_allow_html=True)
    st.markdown(_build_hero_banner_html(), unsafe_allow_html=True)

    catalog = load_material_catalog()
    draft_inputs, active_inputs, serviceability_draft_inputs, serviceability_active_inputs = _load_state()
    chart_label_offsets = _load_chart_label_offsets()
    experimental_dataset, experimental_error = _load_experimental_dataset_from_session()
    experimental_file_name = (
        str(st.session_state.get("experimental_workbook_name"))
        if experimental_dataset is not None and st.session_state.get("experimental_workbook_name")
        else None
    )

    if validate_draft_inputs(active_inputs, catalog):
        active_inputs = copy_draft_inputs(default_draft_inputs())
        st.session_state.active_inputs = active_inputs
    if validate_serviceability_inputs(serviceability_active_inputs):
        serviceability_active_inputs = copy_draft_inputs(default_serviceability_inputs())
        st.session_state.serviceability_active_inputs = serviceability_active_inputs

    st.markdown(
        _build_section_lead_html(
            eyebrow="Робоча область",
            title="Параметри перерізу та армування",
            copy="Задайте геометрію, класи бетону й арматури та перевірте, як зміна параметрів впливає на розрахунковий стан.",
            data_role="input-section-lead",
        ),
        unsafe_allow_html=True,
    )
    with st.container(border=True):
        st.subheader("Введення геометрії та армування")
        general_col, concrete_col = st.columns(2)

        with general_col:
            draft_inputs["section_height_mm"] = st.number_input(
                "Висота перерізу h, мм",
                min_value=100.0,
                value=float(draft_inputs["section_height_mm"]),
                step=10.0,
                key="draft_section_height_mm",
            )
            draft_inputs["section_width_mm"] = st.number_input(
                "Ширина перерізу b, мм",
                min_value=0.0,
                value=float(draft_inputs["section_width_mm"]),
                step=10.0,
                key="draft_section_width_mm",
            )
            draft_inputs["outer_steps"] = st.number_input(
                "Кількість кроків розрахунку",
                min_value=2,
                max_value=200,
                value=int(draft_inputs["outer_steps"]),
                step=1,
                key="draft_outer_steps",
            )

        with concrete_col:
            concrete_classes = list(catalog.concrete.keys())
            top_concrete = draft_inputs["concrete_layers"][0]
            bottom_concrete = draft_inputs["concrete_layers"][1]

            top_concrete["concrete_class"] = st.selectbox(
                "Клас бетону верхнього шару",
                concrete_classes,
                index=_get_select_index(concrete_classes, top_concrete["concrete_class"]),
                key="draft_top_concrete_class",
            )
            bottom_concrete["concrete_class"] = st.selectbox(
                "Клас бетону нижнього шару",
                concrete_classes,
                index=_get_select_index(concrete_classes, bottom_concrete["concrete_class"]),
                key="draft_bottom_concrete_class",
            )
            top_concrete["height_mm"] = st.number_input(
                "Товщина верхнього шару бетону h1, мм",
                min_value=0.0,
                value=float(top_concrete["height_mm"]),
                step=10.0,
                key="draft_top_concrete_height_mm",
            )

            concrete_derived = derive_draft_geometry(draft_inputs)
            st.metric(
                "Похідна товщина нижнього шару бетону h2, мм",
                f"{float(concrete_derived['concrete_rows'][1]['height_mm']):.1f}",
            )
            st.caption("Бі-бетонний прямокутний елемент: ширина перерізу b є сталою для обох шарів бетону.")

        st.subheader("Шари арматури")
        st.caption("Для нормативного сценарію передбачено рівно два шари арматури: верхній і нижній.")

        steel_classes = list(catalog.steel.keys())
        diameters = list(catalog.rebar_area_mm2.keys())
        for index, row in enumerate(draft_inputs["rebar_layers"]):
            row_id = str(row.get("id", f"rebar_{index + 1}"))
            row_cols = st.columns([1.0, 1.0, 0.8, 0.8, 1.0, 1.1])

            row["face"] = row_cols[0].selectbox(
                f"Грань шару арматури {index + 1}",
                [TOP_FACE, BOTTOM_FACE],
                index=_get_select_index([TOP_FACE, BOTTOM_FACE], row["face"]),
                key=f"draft_rebar_face_{row_id}",
            )
            row["distance_mm"] = row_cols[1].number_input(
                f"Відстань a{index + 1}, мм",
                min_value=0.0,
                value=float(row["distance_mm"]),
                step=5.0,
                key=f"draft_rebar_distance_{row_id}",
            )
            row["bar_count"] = row_cols[2].number_input(
                f"Кількість n{index + 1}, шт.",
                min_value=1,
                value=int(row["bar_count"]),
                step=1,
                key=f"draft_rebar_count_{row_id}",
            )
            row["diameter_mm"] = row_cols[3].selectbox(
                f"Діаметр d{index + 1}, мм",
                diameters,
                index=_get_select_index(diameters, int(row["diameter_mm"])),
                key=f"draft_rebar_diameter_{row_id}",
            )
            row["steel_class"] = row_cols[4].selectbox(
                f"Клас арматури {index + 1}",
                steel_classes,
                index=_get_select_index(steel_classes, row["steel_class"]),
                key=f"draft_rebar_class_{row_id}",
            )

            z_mm = float(row["distance_mm"]) if row["face"] == TOP_FACE else float(draft_inputs["section_height_mm"]) - float(row["distance_mm"])
            formula = "z = a" if row["face"] == TOP_FACE else "z = h - a"
            row_cols[5].markdown(f"**{formula}**\n\n`z = {z_mm:.1f} мм`")

        draft_derived = derive_draft_geometry(draft_inputs)
        validation_errors = validate_draft_inputs(draft_inputs, catalog)
        draft_changed = draft_inputs != active_inputs

        preview_col, status_col = st.columns([1.6, 1.0])
        with preview_col:
            st.subheader("Попередній перегляд геометрії")
            st.dataframe(_build_concrete_preview_df(draft_derived), width="stretch", hide_index=True)
            st.dataframe(_build_rebar_preview_df(draft_derived), width="stretch", hide_index=True)

        with status_col:
            st.subheader("Стан чернетки")
            recalculate_clicked = st.button("Перерахувати", disabled=bool(validation_errors), key="apply_draft")

            if recalculate_clicked and not validation_errors:
                st.session_state.active_inputs = copy_draft_inputs(draft_inputs)
                active_inputs = st.session_state.active_inputs
                draft_changed = False

            if validation_errors:
                st.error("Перевірте вхідні дані:\n" + "\n".join(f"- {message}" for message in validation_errors))
            elif draft_changed:
                st.warning("Є незастосовані зміни. Натисніть `Перерахувати`.")
            else:
                st.success("Показано актуальний застосований розрахунок.")

            if validation_errors or draft_changed:
                st.info("Зараз показано результати для останнього застосованого набору даних.")

        with st.expander("Ресурси для зовнішньої верифікації"):
            st.markdown(
                "- [EurocodeApplied ULS rectangular RC section](https://eurocodeapplied.com/design/en1992/uls-design-rectangular-section)\n"
                "- [CivilCalc reinforced concrete rectangular section](https://civilcalc.com/reinforced-concrete)\n"
                "- [CivilEng nonlinear deformation model](https://civileng.ru/check/rc/ndm-custom)"
            )

    try:
        section, result = _build_active_state(active_inputs, catalog)
    except ValueError as error:
        st.error(str(error))
        return

    selected_step = _resolve_selected_step(result)
    selected_point = next(point for point in result.curve_points if point.step_index == selected_step)
    show_active_overlays = not validation_errors and not draft_changed
    drawing_svg = build_section_drawing_svg(
        draft_derived,
        selected_point=selected_point if show_active_overlays else None,
        section=section if show_active_overlays else None,
        materials=catalog if show_active_overlays else None,
        result=result if show_active_overlays else None,
    )

    st.markdown(
        _build_section_lead_html(
            eyebrow="Результати",
            title="Ключові показники та активна точка кривої",
            copy="Після застосування змін система оновлює несучу здатність, кривизну та візуалізацію поточного стану перерізу.",
            data_role="results-section-lead",
        ),
        unsafe_allow_html=True,
    )
    summary_left, summary_right = st.columns(2)
    with summary_left:
        st.metric("Несуча здатність M_Rd, кН·м", f"{result.peak_moment_kNm:.2f}")
    with summary_right:
        st.metric("Кривизна κ_peak, 1/м", f"{result.peak_point.curvature_1_per_m:.4f}")

    with st.container(border=True):
        if validation_errors:
            drawing_note = "Масштабні епюри та розрахункові підписи з'являться після виправлення геометрії та перерахунку."
        elif draft_changed:
            drawing_note = "Епюри доступних форм показуються лише для останнього застосованого стану після `Перерахувати`."
        else:
            drawing_note = "Креслення показує геометрію перерізу та доступні епюри форм рівноваги для обраної точки."
        st.markdown(
            _build_drawing_showcase_html(
                draft_derived,
                drawing_svg,
                selected_point=selected_point if show_active_overlays else None,
                note=drawing_note,
            ),
            unsafe_allow_html=True,
        )

    selected_step = st.slider(
        "Розрахункова точка",
        min_value=1,
        max_value=len(result.curve_points),
        value=selected_step,
        key="selected_curve_step",
    )
    selected_point = next(point for point in result.curve_points if point.step_index == selected_step)
    layer_force_rows = build_layer_force_table(section, catalog, selected_point)

    with st.container(border=True):
        st.subheader("Поточна розрахункова точка")
        if show_active_overlays:
            st.markdown(_build_current_point_cards_html(selected_point), unsafe_allow_html=True)
            st.markdown('<div class="force-strip-caption">Робочі зусилля за шарами для обраної точки.</div>', unsafe_allow_html=True)
            st.markdown(_build_force_cards_html(layer_force_rows), unsafe_allow_html=True)
        elif validation_errors:
            st.caption("Блок поточної точки стане доступним після виправлення геометрії.")
        else:
            st.caption("Блок поточної точки з'явиться після застосування змін кнопкою `Перерахувати`.")

    with st.container(border=True):
        st.subheader("Експериментальні дані для порівняння")
        st.caption(
            "Завантажте одну Excel-книгу з аркушами M_f, M_eps_c, M_eps_s_top та/або M_eps_s_bot, "
            "щоб накласти експериментальні криві на теоретичні графіки."
        )
        upload_col, template_col, clear_col = st.columns([1.4, 1.0, 0.9])
        uploaded_workbook = upload_col.file_uploader(
            "Файл експериментальних кривих (.xlsx)",
            type=["xlsx"],
            key="experimental_workbook_upload",
        )
        template_col.download_button(
            "Завантажити шаблон Excel",
            data=build_experimental_template_workbook_bytes(),
            file_name="experimental_curves_template.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        clear_clicked = clear_col.button(
            "Очистити експериментальні дані",
            disabled=st.session_state.get("experimental_workbook_bytes") is None,
            key="clear_experimental_workbook",
        )

        if clear_clicked:
            _clear_experimental_dataset_state()
            st.rerun()

        if uploaded_workbook is not None:
            uploaded_bytes = uploaded_workbook.getvalue()
            stored_bytes = st.session_state.get("experimental_workbook_bytes")
            stored_name = st.session_state.get("experimental_workbook_name")
            if uploaded_bytes != stored_bytes or uploaded_workbook.name != stored_name:
                try:
                    parsed_experimental_dataset = load_experimental_dataset(uploaded_bytes)
                except ValueError as error:
                    experimental_error = str(error)
                else:
                    st.session_state.experimental_workbook_bytes = uploaded_bytes
                    st.session_state.experimental_workbook_name = uploaded_workbook.name
                    experimental_dataset = parsed_experimental_dataset
                    experimental_error = None
                    experimental_file_name = uploaded_workbook.name
        if experimental_dataset is None and experimental_error is None:
            experimental_file_name = None
        elif experimental_file_name is None and st.session_state.get("experimental_workbook_name"):
            experimental_file_name = str(st.session_state.get("experimental_workbook_name"))

        st.markdown(
            _build_experimental_upload_status_html(
                experimental_dataset,
                file_name=experimental_file_name,
                error_message=experimental_error,
            ),
            unsafe_allow_html=True,
        )

    curve_chart_df = _build_curve_chart_df(result)
    concrete_moment_df = _build_concrete_moment_strain_df(result)
    top_rebar, bottom_rebar = _pick_extreme_rebar_layers(section)
    top_rebar_df = _build_rebar_moment_strain_df(section, result, rebar_index=top_rebar[0])
    bottom_rebar_df = _build_rebar_moment_strain_df(section, result, rebar_index=bottom_rebar[0])
    experimental_concrete_df = _experimental_chart_df(experimental_dataset, chart_id="concrete_moment_strain")
    experimental_top_rebar_df = _experimental_chart_df(experimental_dataset, chart_id="top_rebar_moment_strain")
    experimental_bottom_rebar_df = _experimental_chart_df(experimental_dataset, chart_id="bottom_rebar_moment_strain")
    analytics_summary_df = _build_analytics_summary_df(section, result)
    concrete_limit_annotation = _build_concrete_limit_annotation(section, catalog, result)
    top_rebar_limit_annotation = _build_rebar_limit_annotation(section, catalog, result, rebar_index=top_rebar[0])
    bottom_rebar_limit_annotation = _build_rebar_limit_annotation(section, catalog, result, rebar_index=bottom_rebar[0])
    concrete_last_point_annotation = _build_concrete_last_point_annotation(result)
    top_rebar_last_point_annotation = _build_rebar_last_point_annotation(section, result, rebar_index=top_rebar[0])
    bottom_rebar_last_point_annotation = _build_rebar_last_point_annotation(section, result, rebar_index=bottom_rebar[0])

    st.markdown(
        _build_section_lead_html(
            eyebrow="Аналітика",
            title="Графіки, деформації та таблиці",
            copy="Основні графіки M-κ і момент-деформація для бетону та арматури зі зведеною таблицею по кроках.",
            data_role="analytics-section-lead",
        ),
        unsafe_allow_html=True,
    )
    st.subheader("Діаграма M-κ")
    curve_chart = (
        alt.Chart(curve_chart_df)
        .mark_line(point=True)
        .encode(
            x=alt.X("κ, 1/м:Q", title="κ, 1/м"),
            y=alt.Y("M, кН·м:Q", title="M, кН·м"),
            tooltip=["Крок", "κ, 1/м", "M, кН·м", "ε_c,top, 10^-5", "ε_c,bot, 10^-5"],
        )
        .properties(height=320)
    )
    selected_curve_chart = (
        alt.Chart(curve_chart_df[curve_chart_df["Крок"] == selected_step])
        .mark_point(color="#c2410c", filled=True, size=180)
        .encode(
            x=alt.X("κ, 1/м:Q"),
            y=alt.Y("M, кН·м:Q"),
            tooltip=["Крок", "κ, 1/м", "M, кН·м", "ε_c,top, 10^-5", "ε_c,bot, 10^-5"],
        )
    )
    st.altair_chart(alt.layer(curve_chart, selected_curve_chart), width="stretch")
    st.markdown(
        (
            '<div class="chart-note" data-role="chart-caption-curvature">'
            "κ показує кривизну перерізу: що більше κ, то сильніше викривляється переріз при згині."
            "</div>"
        ),
        unsafe_allow_html=True,
    )

    with st.container(border=True):
        st.subheader("Момент-деформація бетону")
        st.caption(f"Клас бетону {section.concrete_layers[0].concrete_class}, верхня грань перерізу.")
        concrete_label_offsets = _render_chart_label_offset_controls(
            chart_label_offsets,
            chart_id="concrete_moment_strain",
        )
        st.altair_chart(
            _build_moment_strain_chart(
                concrete_moment_df,
                x_field="ε_c,top, 10^-5",
                selected_step=selected_step,
                tooltip_fields=["Крок", "ε_c,top, 10^-5", "M, кН·м"],
                experimental_df=experimental_concrete_df,
                annotations=[
                    ChartAnnotationOverlay(
                        concrete_limit_annotation,
                        "#8c5a3a",
                        text_mode="symbol",
                        label_text=_build_annotation_callout_text(concrete_limit_annotation),
                        manual_dx=concrete_label_offsets["limit"]["dx"],
                        manual_dy=concrete_label_offsets["limit"]["dy"],
                    ),
                    ChartAnnotationOverlay(
                        concrete_last_point_annotation,
                        "#334155",
                        text_mode="symbol",
                        label_position="below",
                        label_text=_build_annotation_callout_text(concrete_last_point_annotation),
                        manual_dx=concrete_label_offsets["max"]["dx"],
                        manual_dy=concrete_label_offsets["max"]["dy"],
                    ),
                ],
            ),
            width="stretch",
        )
        st.markdown(
            _build_concrete_chart_explanation_html(
                chart_title="Момент-деформація бетону",
                concrete_class=section.concrete_layers[0].concrete_class,
                limit_annotation=concrete_limit_annotation,
                max_annotation=concrete_last_point_annotation,
            ),
            unsafe_allow_html=True,
        )
        _render_experimental_comparison(
            concrete_moment_df,
            dataset=experimental_dataset,
            chart_id="concrete_moment_strain",
        )
    with st.container(border=True):
        st.subheader("Момент-деформація верхньої арматури")
        st.caption(f"A{top_rebar[0]}, {top_rebar[1].steel_class}, z = {top_rebar[1].z_mm:.1f} мм")
        top_rebar_label_offsets = _render_chart_label_offset_controls(
            chart_label_offsets,
            chart_id="top_rebar_moment_strain",
        )
        st.altair_chart(
            _build_moment_strain_chart(
                top_rebar_df,
                x_field="ε_s, 10^-5",
                selected_step=selected_step,
                tooltip_fields=["Крок", "ε_s, 10^-5", "M, кН·м"],
                experimental_df=experimental_top_rebar_df,
                annotations=[
                    ChartAnnotationOverlay(
                        top_rebar_limit_annotation,
                        "#8c5a3a",
                        text_mode="symbol",
                        label_text=_build_annotation_callout_text(top_rebar_limit_annotation),
                        manual_dx=top_rebar_label_offsets["limit"]["dx"],
                        manual_dy=top_rebar_label_offsets["limit"]["dy"],
                    ),
                    ChartAnnotationOverlay(
                        top_rebar_last_point_annotation,
                        "#334155",
                        text_mode="symbol",
                        label_position="below",
                        label_text=_build_annotation_callout_text(top_rebar_last_point_annotation),
                        manual_dx=top_rebar_label_offsets["max"]["dx"],
                        manual_dy=top_rebar_label_offsets["max"]["dy"],
                    ),
                ],
            ),
            width="stretch",
        )
        st.markdown(
            _build_rebar_chart_explanation_html(
                chart_title="Момент-деформація верхньої арматури",
                rebar_label=f"A{top_rebar[0]}",
                steel_class=top_rebar[1].steel_class,
                z_mm=top_rebar[1].z_mm,
                limit_annotation=top_rebar_limit_annotation,
                max_annotation=top_rebar_last_point_annotation,
            ),
            unsafe_allow_html=True,
        )
        _render_experimental_comparison(
            top_rebar_df,
            dataset=experimental_dataset,
            chart_id="top_rebar_moment_strain",
        )
    with st.container(border=True):
        st.subheader("Момент-деформація нижньої арматури")
        st.caption(f"A{bottom_rebar[0]}, {bottom_rebar[1].steel_class}, z = {bottom_rebar[1].z_mm:.1f} мм")
        bottom_rebar_label_offsets = _render_chart_label_offset_controls(
            chart_label_offsets,
            chart_id="bottom_rebar_moment_strain",
        )
        st.altair_chart(
            _build_moment_strain_chart(
                bottom_rebar_df,
                x_field="ε_s, 10^-5",
                selected_step=selected_step,
                tooltip_fields=["Крок", "ε_s, 10^-5", "M, кН·м"],
                experimental_df=experimental_bottom_rebar_df,
                annotations=[
                    ChartAnnotationOverlay(
                        bottom_rebar_limit_annotation,
                        "#8c5a3a",
                        text_mode="symbol",
                        label_text=_build_annotation_callout_text(bottom_rebar_limit_annotation),
                        manual_dx=bottom_rebar_label_offsets["limit"]["dx"],
                        manual_dy=bottom_rebar_label_offsets["limit"]["dy"],
                    ),
                    ChartAnnotationOverlay(
                        bottom_rebar_last_point_annotation,
                        "#334155",
                        text_mode="symbol",
                        label_position="below",
                        label_text=_build_annotation_callout_text(bottom_rebar_last_point_annotation),
                        manual_dx=bottom_rebar_label_offsets["max"]["dx"],
                        manual_dy=bottom_rebar_label_offsets["max"]["dy"],
                    ),
                ],
            ),
            width="stretch",
        )
        st.markdown(
            _build_rebar_chart_explanation_html(
                chart_title="Момент-деформація нижньої арматури",
                rebar_label=f"A{bottom_rebar[0]}",
                steel_class=bottom_rebar[1].steel_class,
                z_mm=bottom_rebar[1].z_mm,
                limit_annotation=bottom_rebar_limit_annotation,
                max_annotation=bottom_rebar_last_point_annotation,
            ),
            unsafe_allow_html=True,
        )
        _render_experimental_comparison(
            bottom_rebar_df,
            dataset=experimental_dataset,
            chart_id="bottom_rebar_moment_strain",
        )

    st.caption("Зведена таблиця по всіх кроках розрахунку.")
    st.dataframe(analytics_summary_df, width="stretch")
    st.markdown(_build_termination_summary_html(result), unsafe_allow_html=True)

    st.markdown(
        _build_section_lead_html(
            eyebrow="II ГГС",
            title="Прогини та тріщиностійкість",
            copy="Після основного розрахунку перерізу задайте параметри сервісної перевірки та оновіть лише блок II групи граничних станів.",
            data_role="serviceability-section-lead",
        ),
        unsafe_allow_html=True,
    )

    with st.container(border=True):
        support_scheme_labels = list(SUPPORT_SCHEME_LABELS.values())
        support_scheme_by_label = {label: code for code, label in SUPPORT_SCHEME_LABELS.items()}
        deflection_profile_labels = list(DEFLECTION_LIMIT_PROFILE_LABELS.values())
        deflection_profile_by_label = {label: code for code, label in DEFLECTION_LIMIT_PROFILE_LABELS.items()}
        load_duration_labels = list(LOAD_DURATION_LABELS.values())
        load_duration_by_label = {label: code for code, label in LOAD_DURATION_LABELS.items()}

        st.subheader("Перевірка тріщин та прогинів")
        st.caption(
            "Блок використовує поточну вибрану точку основної кривої. "
            "Зміна параметрів нижче не запускає повторно базовий нелінійний розрахунок перерізу."
        )

        service_left, service_mid, service_right = st.columns(3)
        serviceability_draft_inputs["span_mm"] = service_left.number_input(
            "Розрахунковий проліт l, мм",
            min_value=1.0,
            value=float(serviceability_draft_inputs["span_mm"]),
            step=100.0,
            key="draft_serviceability_span_mm",
        )
        selected_support_label = service_left.selectbox(
            "Розрахункова схема для прогину",
            support_scheme_labels,
            index=_get_select_index(
                support_scheme_labels,
                SUPPORT_SCHEME_LABELS.get(str(serviceability_draft_inputs["support_scheme"]), support_scheme_labels[0]),
            ),
            key="draft_serviceability_support_scheme",
        )
        serviceability_draft_inputs["support_scheme"] = support_scheme_by_label[selected_support_label]
        serviceability_draft_inputs["phi_creep"] = service_left.number_input(
            "Коефіцієнт повзучості φ_creep",
            min_value=0.0,
            value=float(serviceability_draft_inputs["phi_creep"]),
            step=0.1,
            key="draft_serviceability_phi_creep",
        )

        selected_profile_label = service_mid.selectbox(
            "Нормативний профіль обмеження прогину",
            deflection_profile_labels,
            index=_get_select_index(
                deflection_profile_labels,
                DEFLECTION_LIMIT_PROFILE_LABELS.get(
                    str(serviceability_draft_inputs["deflection_limit_profile"]),
                    deflection_profile_labels[0],
                ),
            ),
            key="draft_serviceability_deflection_limit_profile",
        )
        serviceability_draft_inputs["deflection_limit_profile"] = deflection_profile_by_label[selected_profile_label]
        if _uses_parameter_a(str(serviceability_draft_inputs["support_scheme"])):
            max_a_mm = max(1.0, float(serviceability_draft_inputs["span_mm"]) - 1.0)
            current_a_mm = serviceability_draft_inputs.get("a_mm")
            default_a_mm = float(current_a_mm) if current_a_mm not in {None, ""} else min(1000.0, max_a_mm)
            serviceability_draft_inputs["a_mm"] = service_mid.number_input(
                "Відстань a, мм",
                min_value=1.0,
                max_value=max_a_mm,
                value=min(default_a_mm, max_a_mm),
                step=50.0,
                key="draft_serviceability_a_mm",
            )
        else:
            serviceability_draft_inputs["a_mm"] = None
            service_mid.caption("Для обраної схеми параметр `a` не застосовується.")

        if str(serviceability_draft_inputs["deflection_limit_profile"]) == "partition_gap":
            current_gap_mm = serviceability_draft_inputs.get("available_gap_mm")
            serviceability_draft_inputs["available_gap_mm"] = service_mid.number_input(
                "Допустимий зазор, мм",
                min_value=0.0,
                value=40.0 if current_gap_mm in {None, ""} else float(current_gap_mm),
                step=1.0,
                key="draft_serviceability_available_gap_mm",
            )
        else:
            serviceability_draft_inputs["available_gap_mm"] = None
            service_mid.caption("Для інших профілів межа визначається автоматично від прольоту.")

        serviceability_draft_inputs["w_limit_mm"] = service_right.number_input(
            "Гранична ширина розкриття тріщин w_lim, мм",
            min_value=0.05,
            value=float(serviceability_draft_inputs["w_limit_mm"]),
            step=0.05,
            key="draft_serviceability_w_limit_mm",
        )
        selected_load_duration_label = service_right.selectbox(
            "Тривалість навантаження для тріщин",
            load_duration_labels,
            index=_get_select_index(
                load_duration_labels,
                LOAD_DURATION_LABELS.get(str(serviceability_draft_inputs["load_duration"]), load_duration_labels[0]),
            ),
            key="draft_serviceability_load_duration",
        )
        serviceability_draft_inputs["load_duration"] = load_duration_by_label[selected_load_duration_label]
        service_right.caption("Для тріщин використовується короткочасний або довготривалий режим навантаження.")

        serviceability_validation_errors = validate_serviceability_inputs(serviceability_draft_inputs)
        serviceability_draft_changed = serviceability_draft_inputs != serviceability_active_inputs
        apply_serviceability_clicked = st.button(
            "Оновити перевірку",
            disabled=bool(serviceability_validation_errors),
            key="apply_serviceability",
        )

        if apply_serviceability_clicked and not serviceability_validation_errors:
            st.session_state.serviceability_active_inputs = copy_draft_inputs(serviceability_draft_inputs)
            serviceability_active_inputs = st.session_state.serviceability_active_inputs
            serviceability_draft_changed = False

        if serviceability_validation_errors:
            st.error("Перевірте параметри II ГГС:\n" + "\n".join(f"- {message}" for message in serviceability_validation_errors))
        elif serviceability_draft_changed:
            st.warning("Є незастосовані зміни для перевірки прогинів і тріщиностійкості. Натисніть `Оновити перевірку`.")
        else:
            st.success("Показано актуальні результати перевірки II групи граничних станів.")

        active_service_input = build_serviceability_input(serviceability_active_inputs)
        serviceability_report = build_serviceability_report(
            section,
            active_inputs,
            selected_point,
            catalog,
            service_input=active_service_input,
        )
        deflection_curve_df = _build_deflection_curve_df(result, active_service_input)
        experimental_deflection_df = _experimental_chart_df(experimental_dataset, chart_id="deflection_mf")
        deflection_limit_annotation = _build_limit_annotation(
            result.curve_points,
            x_values=deflection_curve_df["f, мм"].tolist(),
            target_strain=serviceability_report.deflection.limit.limit_mm,
            label="f_u",
        )
        serviceability_scheme_svg = build_serviceability_scheme_svg(serviceability_report)
        if serviceability_validation_errors:
            serviceability_scheme_note = (
                "Схема та графічні індикатори показують останній коректно застосований набір II ГГС, "
                "доки нові параметри не будуть виправлені й застосовані."
            )
        elif serviceability_draft_changed:
            serviceability_scheme_note = (
                "Схема відповідає останньому застосованому набору параметрів II ГГС. "
                "Після `Оновити перевірку` креслення й індикатори синхронізуються з чернеткою."
            )
        else:
            serviceability_scheme_note = (
                "Креслення показує активну розрахункову схему, умовну деформовану вісь та ступінь "
                "використання лімітів прогину і тріщиностійкості."
            )
        st.markdown(
            _build_serviceability_scheme_showcase_html(
                serviceability_scheme_svg,
                serviceability_report,
                note=serviceability_scheme_note,
            ),
            unsafe_allow_html=True,
        )

        st.subheader("Діаграма M-f")
        deflection_label_offsets = _render_chart_label_offset_controls(
            chart_label_offsets,
            chart_id="deflection_mf",
        )
        st.altair_chart(
            _build_moment_strain_chart(
                deflection_curve_df,
                x_field="f, мм",
                selected_step=selected_step,
                tooltip_fields=["Крок", "f, мм", "M, кН·м"],
                experimental_df=experimental_deflection_df,
                annotations=[
                    ChartAnnotationOverlay(
                        deflection_limit_annotation,
                        "#8c5a3a",
                        text_mode="symbol",
                        label_text=_build_deflection_annotation_callout_text(deflection_limit_annotation),
                        manual_dx=deflection_label_offsets["limit"]["dx"],
                        manual_dy=deflection_label_offsets["limit"]["dy"],
                    ),
                ],
            ),
            width="stretch",
        )
        st.markdown(
            (
                '<div class="chart-note" data-role="chart-caption-deflection">'
                "Графік показує, як змінюється прогин f для всіх уже побудованих точок основної кривої, і де розташована нормативна межа f_u."
                "</div>"
            ),
            unsafe_allow_html=True,
        )
        _render_experimental_comparison(
            deflection_curve_df,
            dataset=experimental_dataset,
            chart_id="deflection_mf",
        )

        service_input = serviceability_report.input
        crack_width = serviceability_report.crack_width
        deflection = serviceability_report.deflection
        crack_col, deflection_col = st.columns(2)

        with crack_col:
            st.markdown("#### Ширина розкриття тріщин")
            st.metric("Розрахункова ширина тріщини w_k, мм", f"{crack_width.w_k_mm:.3f}")
            st.metric("Гранична ширина w_lim, мм", f"{crack_width.w_limit_mm:.3f}")
            st.metric("Статус за тріщинами", "OK" if crack_width.is_within_limit else "Не OK")
            st.markdown(
                "\n".join(
                    [
                        "ДСТУ Б В.2.6-156:2010, 5.3.4.",
                        f"- Поточна точка: крок {serviceability_report.snapshot.step_index}, M = {serviceability_report.snapshot.moment_kNm:.2f} кН·м.",
                        f"- `σ_s = {_format_optional_number(crack_width.sigma_s_mpa, digits=2)} МПа`.",
                        f"- `ρ_p,eff = {_format_optional_number(crack_width.rho_p_eff, digits=4)}`.",
                        f"- `s_r,max = {_format_optional_number(crack_width.crack_spacing_mm, digits=2)} мм`.",
                        f"- Режим навантаження: `{LOAD_DURATION_LABELS[service_input.load_duration]}`.",
                    ]
                )
            )
            if crack_width.note:
                st.info(crack_width.note)

        with deflection_col:
            st.markdown("#### Перевірка прогину")
            st.metric("Розрахунковий прогин f, мм", f"{deflection.deflection_mm:.3f}")
            st.metric("Граничний прогин f_u, мм", f"{deflection.limit.limit_mm:.3f}")
            st.metric("Статус за прогином", "OK" if deflection.is_within_limit else "Не OK")
            st.markdown(
                "\n".join(
                    [
                        "ДСТУ Б В.2.6-156:2010, 5.4.3; ДСТУ Б В.1.2-3:2006.",
                        f"- Схема: `{SUPPORT_SCHEME_LABELS[service_input.support_scheme]}`.",
                        f"- Профіль: `{DEFLECTION_LIMIT_PROFILE_LABELS[service_input.deflection_limit_profile]}`.",
                        f"- `k_m = {deflection.k_m:.5f}`.",
                        f"- `κ_eff = {deflection.effective_curvature_1_per_m:.6f} 1/м`.",
                        f"- Правило ліміту: {deflection.limit.rule_text}",
                    ]
                )
            )
            if deflection.limit.requires_additional_data or deflection.note:
                st.warning(deflection.note or deflection.limit.warning_message or "Для цього профілю потрібні додаткові конструктивні дані.")

        st.markdown(_build_serviceability_theory_markdown())

    workbook_bytes = build_results_workbook_bytes(
        section,
        catalog,
        result,
        selected_point=selected_point,
        serviceability_report=serviceability_report,
    )

    st.download_button(
        "Завантажити результати у XLSX",
        data=workbook_bytes,
        file_name="bending_results.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    st.markdown(_build_footer_html(), unsafe_allow_html=True)


def main() -> None:
    st.set_page_config(page_title="Розрахунок згину ЗБ перерізу", layout="wide")
    st.markdown(_build_custom_css(), unsafe_allow_html=True)
    st.markdown(_build_hero_banner_html(), unsafe_allow_html=True)

    catalog = load_material_catalog()
    draft_inputs, active_inputs, serviceability_draft_inputs, serviceability_active_inputs = _load_state()
    automation_request = _load_automation_request()
    draft_inputs, active_inputs, serviceability_draft_inputs, serviceability_active_inputs = _apply_automation_request(
        automation_request,
        catalog=catalog,
        draft_inputs=draft_inputs,
        active_inputs=active_inputs,
        serviceability_draft_inputs=serviceability_draft_inputs,
        serviceability_active_inputs=serviceability_active_inputs,
    )
    chart_label_offsets = _load_chart_label_offsets()
    experimental_dataset, experimental_error = _load_experimental_dataset_from_session()
    experimental_file_name = (
        str(st.session_state.get("experimental_workbook_name"))
        if experimental_dataset is not None and st.session_state.get("experimental_workbook_name")
        else None
    )
    if "experimental_show_theory" not in st.session_state:
        st.session_state.experimental_show_theory = True

    if validate_draft_inputs(active_inputs, catalog):
        active_inputs = copy_draft_inputs(default_draft_inputs())
        st.session_state.active_inputs = active_inputs
    if validate_serviceability_inputs(serviceability_active_inputs):
        serviceability_active_inputs = copy_draft_inputs(default_serviceability_inputs())
        st.session_state.serviceability_active_inputs = serviceability_active_inputs

    summary_placeholder = st.container()
    section_tab, serviceability_tab, experimental_tab = st.tabs(["1. Переріз", "2. II ГГС", "3. Експеримент"])

    with section_tab:
        active_inputs, draft_derived, validation_errors, draft_changed = _render_section_input_tab(
            catalog=catalog,
            draft_inputs=draft_inputs,
            active_inputs=active_inputs,
        )

    try:
        section, result = _build_active_state(active_inputs, catalog)
    except ValueError as error:
        st.error(str(error))
        return

    selected_step = _resolve_selected_step(result)
    selected_point = next(point for point in result.curve_points if point.step_index == selected_step)
    show_active_overlays = not validation_errors and not draft_changed
    drawing_svg = build_section_drawing_svg(
        draft_derived,
        selected_point=selected_point if show_active_overlays else None,
        section=section if show_active_overlays else None,
        materials=catalog if show_active_overlays else None,
        result=result if show_active_overlays else None,
    )
    curve_chart_df = _build_curve_chart_df(result)
    concrete_moment_df = _build_concrete_moment_strain_df(result)
    top_rebar, bottom_rebar = _pick_extreme_rebar_layers(section)
    top_rebar_df = _build_rebar_moment_strain_df(section, result, rebar_index=top_rebar[0])
    bottom_rebar_df = _build_rebar_moment_strain_df(section, result, rebar_index=bottom_rebar[0])
    analytics_summary_df = _build_analytics_summary_df(section, result)
    concrete_limit_annotation = _build_concrete_limit_annotation(section, catalog, result)
    top_rebar_limit_annotation = _build_rebar_limit_annotation(section, catalog, result, rebar_index=top_rebar[0])
    bottom_rebar_limit_annotation = _build_rebar_limit_annotation(section, catalog, result, rebar_index=bottom_rebar[0])
    concrete_last_point_annotation = _build_concrete_last_point_annotation(result)
    top_rebar_last_point_annotation = _build_rebar_last_point_annotation(section, result, rebar_index=top_rebar[0])
    bottom_rebar_last_point_annotation = _build_rebar_last_point_annotation(section, result, rebar_index=bottom_rebar[0])

    with section_tab:
        _render_section_results_tab(
            draft_derived=draft_derived,
            validation_errors=validation_errors,
            draft_changed=draft_changed,
            show_active_overlays=show_active_overlays,
            drawing_svg=drawing_svg,
            selected_step=selected_step,
            selected_point=selected_point,
            section=section,
            catalog=catalog,
            result=result,
            chart_label_offsets=chart_label_offsets,
            curve_chart_df=curve_chart_df,
            concrete_moment_df=concrete_moment_df,
            top_rebar_df=top_rebar_df,
            bottom_rebar_df=bottom_rebar_df,
            analytics_summary_df=analytics_summary_df,
            concrete_limit_annotation=concrete_limit_annotation,
            top_rebar_limit_annotation=top_rebar_limit_annotation,
            bottom_rebar_limit_annotation=bottom_rebar_limit_annotation,
            concrete_last_point_annotation=concrete_last_point_annotation,
            top_rebar_last_point_annotation=top_rebar_last_point_annotation,
            bottom_rebar_last_point_annotation=bottom_rebar_last_point_annotation,
            top_rebar=top_rebar,
            bottom_rebar=bottom_rebar,
        )

    with serviceability_tab:
        (
            serviceability_active_inputs,
            serviceability_validation_errors,
            serviceability_draft_changed,
            serviceability_report,
            deflection_curve_df,
        ) = _render_serviceability_tab(
            section=section,
            active_inputs=active_inputs,
            selected_step=selected_step,
            selected_point=selected_point,
            catalog=catalog,
            result=result,
            chart_label_offsets=chart_label_offsets,
            serviceability_draft_inputs=serviceability_draft_inputs,
            serviceability_active_inputs=serviceability_active_inputs,
        )

    with experimental_tab:
        experimental_dataset, experimental_error, experimental_file_name = _render_experimental_tab(
            experimental_dataset=experimental_dataset,
            experimental_error=experimental_error,
            experimental_file_name=experimental_file_name,
            serviceability_report=serviceability_report,
            deflection_curve_df=deflection_curve_df,
            concrete_moment_df=concrete_moment_df,
            top_rebar_df=top_rebar_df,
            bottom_rebar_df=bottom_rebar_df,
            concrete_limit_annotation=concrete_limit_annotation,
            top_rebar_limit_annotation=top_rebar_limit_annotation,
            bottom_rebar_limit_annotation=bottom_rebar_limit_annotation,
            concrete_last_point_annotation=concrete_last_point_annotation,
            top_rebar_last_point_annotation=top_rebar_last_point_annotation,
            bottom_rebar_last_point_annotation=bottom_rebar_last_point_annotation,
        )

    workbook_bytes = build_results_workbook_bytes(
        section,
        catalog,
        result,
        selected_point=selected_point,
        serviceability_report=serviceability_report,
    )

    with summary_placeholder:
        _render_shared_summary(
            result=result,
            selected_step=selected_step,
            selected_point=selected_point,
            validation_errors=validation_errors,
            draft_changed=draft_changed,
            serviceability_validation_errors=serviceability_validation_errors,
            serviceability_draft_changed=serviceability_draft_changed,
            workbook_bytes=workbook_bytes,
        )

    if _automation_mode_enabled():
        _render_hidden_automation_payload(
            "automation-enabled",
            {"enabled": True},
        )
        _render_hidden_automation_payload(
            "automation-section-payload",
            _build_section_automation_payload(result, selected_point),
        )
        _render_hidden_automation_payload(
            "automation-serviceability-payload",
            _build_serviceability_automation_payload(result, selected_point, serviceability_report),
        )
        _render_hidden_automation_payload(
            "automation-experimental-payload",
            _build_experimental_automation_payload(
                experimental_dataset=experimental_dataset,
                experimental_error=experimental_error,
                experimental_file_name=experimental_file_name,
            ),
        )

    st.markdown(_build_footer_html(), unsafe_allow_html=True)


if __name__ == "__main__":
    main()
