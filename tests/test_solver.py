from dataclasses import replace

import pytest

from rc_bending.materials import load_material_catalog
from rc_bending.models import BendingResult, ConcreteLayerInput, CurvePoint, RebarLayerInput, SectionInput
from rc_bending.solver import (
    build_layer_force_table,
    build_section_diagram_state,
    build_strain_profile_for_point,
    classify_equilibrium_form,
    find_comparison_curve_point,
    solve_bending_capacity,
)

TERMINATION_STUB = object()


def make_case_a() -> SectionInput:
    return SectionInput(
        section_height_mm=500.0,
        concrete_layers=(
            ConcreteLayerInput(width_mm=500.0, height_mm=250.0, concrete_class="C25/30"),
            ConcreteLayerInput(width_mm=500.0, height_mm=250.0, concrete_class="C25/30"),
        ),
        rebar_layers=(
            RebarLayerInput(z_mm=30.0, area_mm2=7 * 615.8, steel_class="A400C"),
            RebarLayerInput(z_mm=470.0, area_mm2=7 * 615.8, steel_class="A400C"),
        ),
    )


def test_solver_returns_nonempty_curve_and_small_axial_residual():
    result = solve_bending_capacity(make_case_a(), load_material_catalog())

    assert result.peak_moment_kNm > 0.0
    assert len(result.curve_points) >= 10
    assert abs(result.peak_point.axial_residual_kN) <= 0.5
    assert result.peak_point.curvature_1_per_m > 0.0
    assert result.strain_profile[0].z_mm == pytest.approx(0.0)
    assert result.strain_profile[-1].z_mm == pytest.approx(500.0)


def test_solver_starts_curve_from_zero_strain_and_zero_moment():
    result = solve_bending_capacity(make_case_a(), load_material_catalog())
    first_point = result.curve_points[0]

    assert first_point.step_index == 1
    assert first_point.top_strain == pytest.approx(0.0)
    assert first_point.bottom_strain == pytest.approx(0.0)
    assert first_point.curvature_1_per_m == pytest.approx(0.0)
    assert first_point.moment_kNm == pytest.approx(0.0)
    assert first_point.axial_residual_kN == pytest.approx(0.0)


def test_solver_respects_requested_outer_steps_until_early_stop():
    result = solve_bending_capacity(make_case_a(), load_material_catalog(), outer_steps=12)

    assert len(result.curve_points) <= 12
    assert result.curve_points[-1].step_index == len(result.curve_points)


def test_solver_reports_early_stop_when_next_step_loses_tension_equilibrium():
    catalog = load_material_catalog()
    section = make_case_a()
    expected_limit = catalog.display_limits.concrete[section.concrete_layers[0].concrete_class].strain_e5 * 1e-5

    result = solve_bending_capacity(section, catalog, outer_steps=12)
    termination = result.termination

    assert termination.reason_code == "no_tension_equilibrium_at_steel_limit"
    assert termination.last_step == result.curve_points[-1].step_index
    assert termination.last_moment_kNm == pytest.approx(result.curve_points[-1].moment_kNm)
    assert termination.previous_step == result.curve_points[-2].step_index
    assert termination.previous_moment_kNm == pytest.approx(result.curve_points[-2].moment_kNm)
    assert termination.attempted_step == result.curve_points[-1].step_index + 1
    expected_attempted_strain = expected_limit * (termination.attempted_step - 1) / (12 - 1)
    assert termination.attempted_top_strain == pytest.approx(expected_attempted_strain)
    assert termination.attempted_top_strain < expected_limit
    assert termination.attempted_lower_force_kN > 0.0
    assert termination.attempted_upper_force_kN > 0.0
    assert termination.residual_kN == pytest.approx(result.curve_points[-1].axial_residual_kN)


def test_solver_reports_completion_when_curve_reaches_concrete_limit():
    catalog = load_material_catalog()
    section = SectionInput(
        section_height_mm=120.0,
        concrete_layers=(
            ConcreteLayerInput(width_mm=500.0, height_mm=60.0, concrete_class="C20/25"),
            ConcreteLayerInput(width_mm=500.0, height_mm=60.0, concrete_class="C20/25"),
        ),
        rebar_layers=(
            RebarLayerInput(z_mm=12.0, area_mm2=615.8, steel_class="A400C"),
            RebarLayerInput(z_mm=108.0, area_mm2=615.8, steel_class="A400C"),
        ),
    )

    result = solve_bending_capacity(section, catalog, outer_steps=12)
    termination = result.termination
    expected_limit = catalog.display_limits.concrete[section.concrete_layers[0].concrete_class].strain_e5 * 1e-5

    assert len(result.curve_points) == 12
    assert termination.reason_code == "completed_at_concrete_limit"
    assert termination.last_step == 12
    assert termination.last_moment_kNm == pytest.approx(result.curve_points[-1].moment_kNm)
    assert result.curve_points[-1].top_strain == pytest.approx(expected_limit)
    assert termination.previous_step == 11
    assert termination.previous_moment_kNm == pytest.approx(result.curve_points[-2].moment_kNm)
    assert termination.attempted_step is None
    assert termination.attempted_top_strain is None
    assert termination.attempted_lower_force_kN is None
    assert termination.attempted_upper_force_kN is None
    assert termination.residual_kN == pytest.approx(result.curve_points[-1].axial_residual_kN)


def test_same_material_partition_is_invariant():
    base = make_case_a()
    repartitioned = replace(
        base,
        concrete_layers=(
            ConcreteLayerInput(width_mm=500.0, height_mm=200.0, concrete_class="C25/30"),
            ConcreteLayerInput(width_mm=500.0, height_mm=300.0, concrete_class="C25/30"),
        ),
    )

    result_a = solve_bending_capacity(base, load_material_catalog())
    result_b = solve_bending_capacity(repartitioned, load_material_catalog())

    assert result_a.peak_moment_kNm == pytest.approx(result_b.peak_moment_kNm, rel=1e-3)


def test_zero_height_second_layer_reduces_to_single_material_case():
    uniform = make_case_a()
    reduced = replace(
        uniform,
        concrete_layers=(
            ConcreteLayerInput(width_mm=500.0, height_mm=500.0, concrete_class="C25/30"),
            ConcreteLayerInput(width_mm=500.0, height_mm=0.0, concrete_class="C25/30"),
        ),
    )

    result_uniform = solve_bending_capacity(uniform, load_material_catalog())
    result_reduced = solve_bending_capacity(reduced, load_material_catalog())

    assert result_uniform.peak_moment_kNm == pytest.approx(result_reduced.peak_moment_kNm, rel=1e-3)


def test_stronger_top_layer_does_not_reduce_capacity():
    weaker = make_case_a()
    stronger = replace(
        weaker,
        concrete_layers=(
            ConcreteLayerInput(width_mm=500.0, height_mm=200.0, concrete_class="C30/35"),
            ConcreteLayerInput(width_mm=500.0, height_mm=300.0, concrete_class="C20/25"),
        ),
    )

    weak_result = solve_bending_capacity(weaker, load_material_catalog())
    strong_result = solve_bending_capacity(stronger, load_material_catalog())

    assert strong_result.peak_moment_kNm >= weak_result.peak_moment_kNm


def test_strain_profile_can_be_built_for_any_curve_point():
    section = make_case_a()
    result = solve_bending_capacity(section, load_material_catalog())

    early_point = result.curve_points[0]
    early_profile = build_strain_profile_for_point(section, early_point)
    peak_profile = build_strain_profile_for_point(section, result.peak_point)

    assert early_profile[0].z_mm == pytest.approx(0.0)
    assert early_profile[-1].z_mm == pytest.approx(500.0)
    assert early_profile[0].strain != pytest.approx(peak_profile[0].strain)


@pytest.mark.parametrize(
    ("section_height_mm", "top_height_mm", "bottom_height_mm", "top_class", "bottom_class"),
    [
        (100.0, 40.0, 60.0, "C25/30", "C25/30"),
        (100.0, 1.0, 99.0, "C30/35", "C20/25"),
        (100.0, 99.0, 1.0, "C30/35", "C20/25"),
        (120.0, 48.0, 72.0, "C25/30", "C25/30"),
        (200.0, 80.0, 120.0, "C30/35", "C20/25"),
        (300.0, 120.0, 180.0, "C30/35", "C20/25"),
    ],
)
def test_solver_handles_small_and_thin_sections(
    section_height_mm: float,
    top_height_mm: float,
    bottom_height_mm: float,
    top_class: str,
    bottom_class: str,
):
    section = SectionInput(
        section_height_mm=section_height_mm,
        concrete_layers=(
            ConcreteLayerInput(width_mm=500.0, height_mm=top_height_mm, concrete_class=top_class),
            ConcreteLayerInput(width_mm=500.0, height_mm=bottom_height_mm, concrete_class=bottom_class),
        ),
        rebar_layers=(
            RebarLayerInput(z_mm=section_height_mm * 0.1, area_mm2=7 * 615.8, steel_class="A400C"),
            RebarLayerInput(z_mm=section_height_mm * 0.9, area_mm2=7 * 615.8, steel_class="A400C"),
        ),
    )

    result = solve_bending_capacity(section, load_material_catalog())

    assert result.peak_moment_kNm > 0.0
    assert len(result.curve_points) >= 10
    assert max(abs(point.axial_residual_kN) for point in result.curve_points) <= 0.5


def test_solver_accepts_boundary_rebar_positions():
    section = SectionInput(
        section_height_mm=100.0,
        concrete_layers=(
            ConcreteLayerInput(width_mm=500.0, height_mm=50.0, concrete_class="C25/30"),
            ConcreteLayerInput(width_mm=500.0, height_mm=50.0, concrete_class="C25/30"),
        ),
        rebar_layers=(
            RebarLayerInput(z_mm=0.0, area_mm2=7 * 615.8, steel_class="A400C"),
            RebarLayerInput(z_mm=100.0, area_mm2=7 * 615.8, steel_class="A400C"),
        ),
    )

    result = solve_bending_capacity(section, load_material_catalog())

    assert result.peak_moment_kNm > 0.0
    assert abs(result.peak_point.axial_residual_kN) <= 0.5


def test_classify_equilibrium_form_distinguishes_first_and_second_forms():
    first_form_point = CurvePoint(
        step_index=1,
        top_strain=0.002,
        bottom_strain=0.0003,
        curvature_1_per_m=3.4,
        neutral_axis_mm=620.0,
        axial_residual_kN=0.0,
        moment_kNm=100.0,
        state_label="whole_compression",
    )
    second_form_point = replace(first_form_point, bottom_strain=-0.0003, state_label="bending_with_tension")

    assert classify_equilibrium_form(first_form_point) == "first"
    assert classify_equilibrium_form(second_form_point) == "second"


def test_find_comparison_curve_point_prefers_closest_step_then_curvature():
    active_point = CurvePoint(
        step_index=10,
        top_strain=0.002,
        bottom_strain=-0.001,
        curvature_1_per_m=4.0,
        neutral_axis_mm=150.0,
        axial_residual_kN=0.0,
        moment_kNm=200.0,
        state_label="bending_with_tension",
    )
    close_first = replace(
        active_point,
        step_index=8,
        bottom_strain=0.0002,
        curvature_1_per_m=3.8,
        state_label="whole_compression",
    )
    tied_first = replace(
        active_point,
        step_index=12,
        bottom_strain=0.0002,
        curvature_1_per_m=4.7,
        state_label="whole_compression",
    )
    farther_first = replace(
        active_point,
        step_index=15,
        bottom_strain=0.0004,
        curvature_1_per_m=4.1,
        state_label="whole_compression",
    )
    result = BendingResult(
        curve_points=(active_point, farther_first, tied_first, close_first),
        peak_point=active_point,
        peak_moment_kNm=active_point.moment_kNm,
        strain_profile=(),
        inner_iterations=(),
        termination=TERMINATION_STUB,
    )

    assert find_comparison_curve_point(result, active_point) == close_first


def test_find_comparison_curve_point_returns_none_when_other_form_is_missing():
    result = solve_bending_capacity(make_case_a(), load_material_catalog())

    assert find_comparison_curve_point(result, result.peak_point) is None


def test_build_section_diagram_state_zeroes_concrete_tension_for_second_form():
    section = make_case_a()
    catalog = load_material_catalog()
    result = solve_bending_capacity(section, catalog)

    state = build_section_diagram_state(section, catalog, result.peak_point)

    assert state.form == "second"
    assert any(point.stress_mpa > 0.0 for point in state.concrete_profile if point.z_mm < result.peak_point.neutral_axis_mm)
    assert all(
        point.stress_mpa == pytest.approx(0.0)
        for point in state.concrete_profile
        if point.z_mm > result.peak_point.neutral_axis_mm
    )


def test_build_section_diagram_state_matches_rebar_forces_from_layer_force_table():
    section = make_case_a()
    catalog = load_material_catalog()
    result = solve_bending_capacity(section, catalog)
    layer_force_rows = build_layer_force_table(section, catalog, result.peak_point)

    state = build_section_diagram_state(section, catalog, result.peak_point)
    rebar_rows = [row for row in layer_force_rows if row["kind"] == "rebar"]

    assert len(state.rebar_states) == len(rebar_rows)
    for rebar_state, row in zip(state.rebar_states, rebar_rows):
        assert rebar_state.index == row["index"]
        assert rebar_state.z_mm == pytest.approx(float(row["z_mm"]))
        assert rebar_state.stress_mpa == pytest.approx(float(row["stress_mpa"]))
        assert rebar_state.force_kN == pytest.approx(float(row["force_kN"]))
