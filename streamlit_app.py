from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st
import altair as alt

from rc_bending.export import build_results_workbook_bytes
from rc_bending.materials import load_material_catalog
from rc_bending.section_drawing import build_section_drawing_svg
from rc_bending.solver import build_layer_force_table, solve_bending_capacity
from rc_bending.ui_helpers import (
    BOTTOM_FACE,
    TOP_FACE,
    build_section_input_from_draft,
    copy_draft_inputs,
    default_draft_inputs,
    derive_draft_geometry,
    validate_draft_inputs,
)

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


def _to_promille(value: float) -> float:
    return value * 1000.0


def _to_strain_e5(value: float) -> float:
    return value * 100000.0


def _strain_at_depth(top_strain: float, bottom_strain: float, z_mm: float, section_height_mm: float) -> float:
    if section_height_mm == 0.0:
        return 0.0
    return top_strain + (bottom_strain - top_strain) * z_mm / section_height_mm


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


def _build_concrete_moment_strain_df(result) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Крок": [point.step_index for point in result.curve_points],
            "M, кН·м": [point.moment_kNm for point in result.curve_points],
            "ε_c,top, 10^-5": [_to_strain_e5(point.top_strain) for point in result.curve_points],
        }
    )


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


def _build_rebar_moment_strain_df(section, result, *, rebar_index: int) -> pd.DataFrame:
    rebar = section.rebar_layers[rebar_index - 1]
    return pd.DataFrame(
        {
            "Крок": [point.step_index for point in result.curve_points],
            "M, кН·м": [point.moment_kNm for point in result.curve_points],
            "ε_s, 10^-5": [
                _to_strain_e5(
                    _strain_at_depth(
                        point.top_strain,
                        point.bottom_strain,
                        rebar.z_mm,
                        section.section_height_mm,
                    )
                )
                for point in result.curve_points
            ],
        }
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


def _load_state() -> tuple[dict[str, object], dict[str, object]]:
    defaults = default_draft_inputs()

    if not _is_draft_shape(st.session_state.get("draft_inputs")):
        st.session_state.draft_inputs = copy_draft_inputs(defaults)
    if not _is_draft_shape(st.session_state.get("active_inputs")):
        st.session_state.active_inputs = copy_draft_inputs(defaults)

    return st.session_state.draft_inputs, st.session_state.active_inputs


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
    div[data-baseweb="input"] > div,
    div[data-baseweb="select"] > div,
    div[data-baseweb="popover"] > div {
        border-radius: 16px;
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
    }
    @media (max-width: 640px) {
        [data-testid="block-container"] {
            padding-top: 1.2rem;
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


def _build_drawing_stage_html(drawing_svg: str) -> str:
    return f'<div class="cad-shell" data-role="cad-shell"><div class="cad-stage" data-role="cad-stage">{drawing_svg}</div></div>'


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


def _build_active_state(active_inputs: dict[str, object], catalog) -> tuple[object, object]:
    section = build_section_input_from_draft(active_inputs, catalog)
    result = solve_bending_capacity(section, catalog, outer_steps=int(active_inputs.get("outer_steps", 40)))
    return section, result


def main() -> None:
    st.set_page_config(page_title="Розрахунок згину ЗБ перерізу", layout="wide")
    st.markdown(_build_custom_css(), unsafe_allow_html=True)
    st.markdown(_build_hero_banner_html(), unsafe_allow_html=True)

    catalog = load_material_catalog()
    draft_inputs, active_inputs = _load_state()

    if validate_draft_inputs(active_inputs, catalog):
        active_inputs = copy_draft_inputs(default_draft_inputs())
        st.session_state.active_inputs = active_inputs

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

    selected_step = st.slider("Розрахункова точка", min_value=1, max_value=len(result.curve_points), value=result.peak_point.step_index)
    selected_point = next(point for point in result.curve_points if point.step_index == selected_step)
    layer_force_rows = build_layer_force_table(section, catalog, selected_point)
    workbook_bytes = build_results_workbook_bytes(section, catalog, result, selected_point=selected_point)
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

        st.subheader("Поточна розрахункова точка")
        if show_active_overlays:
            st.markdown(_build_current_point_cards_html(selected_point), unsafe_allow_html=True)
            st.markdown('<div class="force-strip-caption">Робочі зусилля за шарами для обраної точки.</div>', unsafe_allow_html=True)
            st.markdown(_build_force_cards_html(layer_force_rows), unsafe_allow_html=True)
        elif validation_errors:
            st.caption("Блок поточної точки стане доступним після виправлення геометрії.")
        else:
            st.caption("Блок поточної точки з'явиться після застосування змін кнопкою `Перерахувати`.")

    curve_chart_df = _build_curve_chart_df(result)
    concrete_moment_df = _build_concrete_moment_strain_df(result)
    top_rebar, bottom_rebar = _pick_extreme_rebar_layers(section)
    top_rebar_df = _build_rebar_moment_strain_df(section, result, rebar_index=top_rebar[0])
    bottom_rebar_df = _build_rebar_moment_strain_df(section, result, rebar_index=bottom_rebar[0])
    analytics_summary_df = _build_analytics_summary_df(section, result)

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

    chart_left, chart_center, chart_right = st.columns(3)
    with chart_left:
        st.subheader("Момент-деформація бетону")
        concrete_moment_chart = (
            alt.Chart(concrete_moment_df)
            .mark_line(point=True)
            .encode(
                x=alt.X("ε_c,top, 10^-5:Q", title="ε_c,top, 10^-5"),
                y=alt.Y("M, кН·м:Q", title="M, кН·м"),
                tooltip=["Крок", "ε_c,top, 10^-5", "M, кН·м"],
            )
            .properties(height=320)
        )
        selected_concrete_moment_chart = (
            alt.Chart(concrete_moment_df[concrete_moment_df["Крок"] == selected_step])
            .mark_point(color="#c2410c", filled=True, size=180)
            .encode(
                x=alt.X("ε_c,top, 10^-5:Q"),
                y=alt.Y("M, кН·м:Q"),
                tooltip=["Крок", "ε_c,top, 10^-5", "M, кН·м"],
            )
        )
        st.altair_chart(alt.layer(concrete_moment_chart, selected_concrete_moment_chart), width="stretch")
    with chart_center:
        st.subheader("Момент-деформація верхньої арматури")
        st.caption(f"A{top_rebar[0]}, z = {top_rebar[1].z_mm:.1f} мм")
        top_rebar_chart = (
            alt.Chart(top_rebar_df)
            .mark_line(point=True)
            .encode(
                x=alt.X("ε_s, 10^-5:Q", title="ε_s, 10^-5"),
                y=alt.Y("M, кН·м:Q", title="M, кН·м"),
                tooltip=["Крок", "ε_s, 10^-5", "M, кН·м"],
            )
            .properties(height=320)
        )
        selected_top_rebar_chart = (
            alt.Chart(top_rebar_df[top_rebar_df["Крок"] == selected_step])
            .mark_point(color="#c2410c", filled=True, size=180)
            .encode(
                x=alt.X("ε_s, 10^-5:Q"),
                y=alt.Y("M, кН·м:Q"),
                tooltip=["Крок", "ε_s, 10^-5", "M, кН·м"],
            )
        )
        st.altair_chart(alt.layer(top_rebar_chart, selected_top_rebar_chart), width="stretch")
    with chart_right:
        st.subheader("Момент-деформація нижньої арматури")
        st.caption(f"A{bottom_rebar[0]}, z = {bottom_rebar[1].z_mm:.1f} мм")
        bottom_rebar_chart = (
            alt.Chart(bottom_rebar_df)
            .mark_line(point=True)
            .encode(
                x=alt.X("ε_s, 10^-5:Q", title="ε_s, 10^-5"),
                y=alt.Y("M, кН·м:Q", title="M, кН·м"),
                tooltip=["Крок", "ε_s, 10^-5", "M, кН·м"],
            )
            .properties(height=320)
        )
        selected_bottom_rebar_chart = (
            alt.Chart(bottom_rebar_df[bottom_rebar_df["Крок"] == selected_step])
            .mark_point(color="#c2410c", filled=True, size=180)
            .encode(
                x=alt.X("ε_s, 10^-5:Q"),
                y=alt.Y("M, кН·м:Q"),
                tooltip=["Крок", "ε_s, 10^-5", "M, кН·м"],
        )
        )
        st.altair_chart(alt.layer(bottom_rebar_chart, selected_bottom_rebar_chart), width="stretch")

    st.caption("Зведена таблиця по всіх кроках розрахунку.")
    st.dataframe(analytics_summary_df, width="stretch")

    st.download_button(
        "Завантажити результати у XLSX",
        data=workbook_bytes,
        file_name="bending_results.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    st.markdown(_build_footer_html(), unsafe_allow_html=True)


if __name__ == "__main__":
    main()
