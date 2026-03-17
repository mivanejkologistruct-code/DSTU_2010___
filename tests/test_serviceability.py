import pytest

from rc_bending.materials import load_material_catalog
from rc_bending.models import CurrentPointSnapshot, ServiceabilityInput
from rc_bending.serviceability import (
    build_current_point_snapshot,
    build_serviceability_report,
    calculate_crack_width_from_design_values,
    calculate_deflection_limit,
    calculate_deflection_mm,
)
from rc_bending.solver import solve_bending_capacity
from rc_bending.ui_helpers import build_section_input_from_draft, default_draft_inputs


def _make_default_case():
    catalog = load_material_catalog()
    draft = default_draft_inputs()
    section = build_section_input_from_draft(draft, catalog)
    result = solve_bending_capacity(section, catalog, outer_steps=int(draft["outer_steps"]))
    return catalog, draft, section, result


def test_build_current_point_snapshot_reuses_selected_point_moment_and_curvature():
    catalog, draft, section, result = _make_default_case()
    selected_point = result.curve_points[-1]

    snapshot = build_current_point_snapshot(section, draft, selected_point, catalog)

    assert snapshot.step_index == selected_point.step_index
    assert snapshot.moment_kNm == pytest.approx(selected_point.moment_kNm)
    assert snapshot.curvature_1_per_m == pytest.approx(selected_point.curvature_1_per_m)
    assert snapshot.neutral_axis_mm == pytest.approx(selected_point.neutral_axis_mm)


def test_calculate_deflection_limit_interpolates_aesthetic_profile_by_span():
    limit = calculate_deflection_limit(
        profile="aesthetic_open_view",
        span_mm=15000.0,
        is_cantilever=False,
        available_gap_mm=None,
    )

    assert limit.limit_mm == pytest.approx(15000.0 / 225.0)
    assert "l/225.00" in limit.rule_text
    assert limit.profile == "aesthetic_open_view"


def test_calculate_deflection_limit_uses_available_gap_for_partition_profile():
    limit = calculate_deflection_limit(
        profile="partition_gap",
        span_mm=6000.0,
        is_cantilever=False,
        available_gap_mm=18.0,
    )

    assert limit.limit_mm == pytest.approx(18.0)
    assert "18.00 мм" in limit.rule_text
    assert limit.requires_additional_data is False


def test_calculate_deflection_limit_uses_double_reach_for_cantilever_aesthetic_profile():
    limit = calculate_deflection_limit(
        profile="aesthetic_open_view",
        span_mm=3000.0,
        is_cantilever=True,
        available_gap_mm=None,
    )

    assert limit.limit_mm == pytest.approx(30.0)
    assert "2a/200.00" in limit.rule_text


def test_calculate_deflection_limit_uses_1_over_75_for_unspecified_cantilever():
    limit = calculate_deflection_limit(
        profile="fallback_unspecified",
        span_mm=3000.0,
        is_cantilever=True,
        available_gap_mm=None,
    )

    assert limit.limit_mm == pytest.approx(40.0)
    assert "1/75" in limit.rule_text


def test_calculate_deflection_mm_uses_current_curvature_and_table_5_5_scheme():
    snapshot = CurrentPointSnapshot(
        step_index=5,
        moment_kNm=12.5,
        curvature_1_per_m=0.0002,
        neutral_axis_mm=50.0,
        top_strain=0.0001,
        bottom_strain=-0.0001,
        section_height_mm=120.0,
        section_width_mm=500.0,
        tension_face="bottom",
        tension_zone_height_mm=70.0,
        effective_tension_height_mm=20.0,
        effective_tension_area_mm2=10000.0,
        tension_rebar_index=2,
        tension_rebar_area_mm2=201.0,
        tension_rebar_bar_count=4,
        tension_rebar_diameter_mm=8.0,
        tension_rebar_spacing_mm=150.0,
        tension_rebar_cover_mm=16.0,
        tension_rebar_depth_from_top_mm=100.0,
        tension_steel_class="A500C",
        tension_steel_stress_mpa=100.0,
        alpha_e=6.9,
    )

    deflection_mm = calculate_deflection_mm(
        snapshot=snapshot,
        span_mm=6000.0,
        support_scheme="simply_supported_uniform",
        a_mm=None,
        phi_creep=0.0,
    )

    assert deflection_mm == pytest.approx(0.75)


def test_calculate_crack_width_matches_jrc_worked_example_internal_support():
    result = calculate_crack_width_from_design_values(
        sigma_s_mpa=190.2,
        f_ct_eff_mpa=2.6,
        rho_p_eff=0.0251,
        alpha_e=7.0,
        e_s_mpa=200000.0,
        k_t=0.4,
        cover_mm=19.0,
        bar_diameter_mm=20.0,
        bar_spacing_mm=None,
        neutral_axis_depth_mm=None,
        section_height_mm=50.0,
        k_1=0.8,
        k_2=1.0,
        k_3=3.4,
        k_4=0.425,
        w_limit_mm=0.30,
    )

    assert result.crack_spacing_mm == pytest.approx(335.3, abs=0.3)
    assert result.strain_difference == pytest.approx(0.71e-3, abs=0.02e-3)
    assert result.w_k_mm == pytest.approx(0.24, abs=0.02)
    assert result.is_within_limit is True


def test_build_serviceability_report_uses_selected_point_snapshot_in_results():
    catalog, draft, section, result = _make_default_case()
    selected_point = result.curve_points[-1]
    service_input = ServiceabilityInput(
        span_mm=6000.0,
        support_scheme="simply_supported_uniform",
        a_mm=None,
        phi_creep=0.0,
        deflection_limit_profile="aesthetic_open_view",
        available_gap_mm=None,
        w_limit_mm=0.3,
        load_duration="long_term",
    )

    report = build_serviceability_report(section, draft, selected_point, catalog, service_input=service_input)

    assert report.snapshot.step_index == selected_point.step_index
    assert report.snapshot.moment_kNm == pytest.approx(selected_point.moment_kNm)
    assert report.snapshot.curvature_1_per_m == pytest.approx(selected_point.curvature_1_per_m)
    assert report.deflection.curvature_1_per_m == pytest.approx(selected_point.curvature_1_per_m)
