from dataclasses import replace
import re

from rc_bending.materials import load_material_catalog
from rc_bending.models import BendingResult
from rc_bending.solver import solve_bending_capacity
from rc_bending.ui_helpers import build_section_input_from_draft, default_draft_inputs, derive_draft_geometry


def _with_first_form_comparison(result) -> BendingResult:
    template = result.curve_points[max(0, len(result.curve_points) // 3)]
    comparison_point = replace(
        template,
        step_index=max(point.step_index for point in result.curve_points) + 1,
        bottom_strain=max(abs(template.bottom_strain) * 0.25, 1e-5),
        neutral_axis_mm=template.neutral_axis_mm + 420.0,
        state_label="whole_compression",
    )
    return BendingResult(
        curve_points=tuple(result.curve_points) + (comparison_point,),
        peak_point=result.peak_point,
        peak_moment_kNm=result.peak_moment_kNm,
        strain_profile=result.strain_profile,
        inner_iterations=result.inner_iterations,
    )


def test_build_section_drawing_svg_contains_geometry_dimensions_and_callouts():
    from rc_bending.section_drawing import build_section_drawing_svg

    draft = default_draft_inputs()
    derived = derive_draft_geometry(draft)

    svg = build_section_drawing_svg(derived)

    assert "<svg" in svg
    assert "Креслення перерізу" in svg
    assert "b = 500.0 мм" in svg
    assert "h = 500.0 мм" in svg
    assert "h1 = 200.0 мм" in svg
    assert "h2 = 300.0 мм" in svg
    assert "B1: C30/35" in svg
    assert "B2: C20/25" in svg
    assert "A1: 7 x 28" in svg
    assert "a1 = 30.0 мм" in svg
    assert "z1 = 30.0 мм" in svg
    assert "A2: 7 x 28" in svg
    assert "a2 = 30.0 мм" in svg
    assert "z2 = 470.0 мм" in svg
    assert 'data-role="section-width-dimension"' in svg
    assert svg.count('data-role="layer-height-dimension"') == 2
    assert svg.count('data-role="rebar-depth-dimension"') == 2
    assert 'data-role="rebar-callout"' in svg
    assert "1-ша форма рівноваги" in svg
    assert "2-га форма рівноваги" in svg
    assert 'data-role="diagram-sheet"' in svg


def test_build_section_drawing_svg_renders_placeholders_without_active_point():
    from rc_bending.section_drawing import build_section_drawing_svg

    svg = build_section_drawing_svg(derive_draft_geometry(default_draft_inputs()))

    assert "форма не реалізована для цього набору даних" in svg
    assert svg.count('data-role="form-placeholder"') == 2
    assert "Активна точка" not in svg
    assert "Порівняння" not in svg
    assert "N_c =" not in svg
    assert "N_A1 =" not in svg
    assert 'data-role="neutral-axis"' not in svg


def test_build_section_drawing_svg_renders_active_and_comparison_forms_when_available():
    from rc_bending.section_drawing import build_section_drawing_svg

    catalog = load_material_catalog()
    draft = default_draft_inputs()
    derived = derive_draft_geometry(draft)
    section = build_section_input_from_draft(draft, catalog)
    result = solve_bending_capacity(section, catalog)
    result_with_comparison = _with_first_form_comparison(result)

    svg = build_section_drawing_svg(
        derived,
        selected_point=result.peak_point,
        section=section,
        materials=catalog,
        result=result_with_comparison,
    )

    assert "Активна точка" in svg
    assert "Порівняння" in svg
    assert "1-ша форма рівноваги" in svg
    assert "2-га форма рівноваги" in svg
    assert "N_c =" in svg
    assert "N_A1 =" in svg
    assert "N_A2 =" in svg
    assert 'data-role="metric-legend"' in svg
    assert 'data-role="metric-chip"' in svg
    assert 'data-role="neutral-axis"' in svg
    assert 'data-role="lever-arm"' in svg
    assert 'data-role="form-panel-badge"' in svg


def test_build_section_drawing_svg_renders_placeholder_for_missing_comparison_form():
    from rc_bending.section_drawing import build_section_drawing_svg

    catalog = load_material_catalog()
    draft = default_draft_inputs()
    derived = derive_draft_geometry(draft)
    section = build_section_input_from_draft(draft, catalog)
    result = solve_bending_capacity(section, catalog)

    svg = build_section_drawing_svg(
        derived,
        selected_point=result.peak_point,
        section=section,
        materials=catalog,
        result=result,
    )

    assert "Активна точка" in svg
    assert "2-га форма рівноваги" in svg
    assert "1-ша форма рівноваги" in svg
    assert "форма не реалізована для цього набору даних" in svg
    assert svg.count('data-role="form-placeholder"') == 1


def test_build_section_drawing_svg_marks_rebar_layout_warning_when_bars_do_not_fit():
    from rc_bending.section_drawing import build_section_drawing_svg

    draft = default_draft_inputs()
    draft["rebar_layers"][0]["bar_count"] = 30
    draft["rebar_layers"][0]["diameter_mm"] = 28

    svg = build_section_drawing_svg(derive_draft_geometry(draft))

    assert "A1: n*d > b" in svg
    assert 'data-role="layout-warning"' in svg


def test_build_section_drawing_svg_stacks_rebar_callouts_without_overlaps():
    from rc_bending.section_drawing import build_section_drawing_svg

    draft = default_draft_inputs()
    draft["rebar_layers"] = [
        {"id": "rebar_1", "face": "Верхня", "distance_mm": 30.0, "bar_count": 4, "diameter_mm": 20, "steel_class": "A400C"},
        {"id": "rebar_2", "face": "Верхня", "distance_mm": 45.0, "bar_count": 3, "diameter_mm": 18, "steel_class": "A400C"},
        {"id": "rebar_3", "face": "Нижня", "distance_mm": 50.0, "bar_count": 3, "diameter_mm": 18, "steel_class": "A500C"},
        {"id": "rebar_4", "face": "Нижня", "distance_mm": 30.0, "bar_count": 4, "diameter_mm": 20, "steel_class": "A500C"},
    ]

    svg = build_section_drawing_svg(derive_draft_geometry(draft))
    callout_positions = re.findall(r'data-role="rebar-callout"[^>]*transform="translate\([0-9.]+ ([0-9.]+)\)"', svg)

    assert len(callout_positions) == 4
    assert len(set(callout_positions)) == 4


def test_build_section_drawing_svg_exposes_readable_visual_groups():
    from rc_bending.section_drawing import build_section_drawing_svg

    catalog = load_material_catalog()
    draft = default_draft_inputs()
    derived = derive_draft_geometry(draft)
    section = build_section_input_from_draft(draft, catalog)
    result = solve_bending_capacity(section, catalog)

    svg = build_section_drawing_svg(
        derived,
        selected_point=result.peak_point,
        section=section,
        materials=catalog,
        result=_with_first_form_comparison(result),
    )

    assert 'data-role="diagram-sheet"' in svg
    assert 'data-role="drawing-stage"' in svg
    assert 'data-role="section-frame"' in svg
    assert svg.count('data-role="layer-chip"') == 2
    assert svg.count('data-role="form-panel"') == 2
    assert svg.count('data-role="panel-divider"') == 2
    assert svg.count('data-role="stress-scale"') == 2
    assert svg.count('data-role="strain-scale"') == 2
    assert svg.count('data-role="metric-legend"') == 1
    assert svg.count('data-role="result-strip"') == 1
    assert svg.count('data-role="annotation-card"') >= 4
    assert svg.count('data-role="form-grid-line"') >= 6
    assert svg.count('data-role="level-marker"') >= 4


def test_build_section_drawing_svg_uses_compact_canvas_for_readability():
    from rc_bending.section_drawing import build_section_drawing_svg

    catalog = load_material_catalog()
    draft = default_draft_inputs()
    derived = derive_draft_geometry(draft)
    section = build_section_input_from_draft(draft, catalog)
    result = solve_bending_capacity(section, catalog)

    svg = build_section_drawing_svg(
        derived,
        selected_point=result.peak_point,
        section=section,
        materials=catalog,
        result=result,
    )
    match = re.search(r'viewBox="0 0 ([0-9.]+) ([0-9.]+)"', svg)

    assert match is not None
    assert float(match.group(1)) <= 1450.0


def test_build_section_drawing_svg_moves_metrics_into_legend_block():
    from rc_bending.section_drawing import build_section_drawing_svg

    catalog = load_material_catalog()
    draft = default_draft_inputs()
    derived = derive_draft_geometry(draft)
    section = build_section_input_from_draft(draft, catalog)
    result = solve_bending_capacity(section, catalog)

    svg = build_section_drawing_svg(
        derived,
        selected_point=result.peak_point,
        section=section,
        materials=catalog,
        result=result,
    )

    assert 'data-role="metric-legend"' in svg
    assert svg.count('data-role="metric-chip"') >= 3


def test_build_section_drawing_svg_uses_scaled_hatching_for_stress_epures():
    from rc_bending.section_drawing import build_section_drawing_svg

    catalog = load_material_catalog()
    draft = default_draft_inputs()
    derived = derive_draft_geometry(draft)
    section = build_section_input_from_draft(draft, catalog)
    result = solve_bending_capacity(section, catalog)

    svg = build_section_drawing_svg(
        derived,
        selected_point=result.peak_point,
        section=section,
        materials=catalog,
        result=result,
    )

    assert 'id="hatch-concrete-stress"' in svg
    assert 'id="hatch-steel-stress"' in svg
    assert svg.count('patternUnits="userSpaceOnUse"') >= 2
    assert 'data-role="concrete-stress-area"' in svg
    assert svg.count('data-role="steel-stress-block"') == len(section.rebar_layers)


def test_build_section_drawing_svg_uses_separate_scales_for_concrete_and_steel_stress():
    from rc_bending.section_drawing import build_section_drawing_svg

    catalog = load_material_catalog()
    draft = default_draft_inputs()
    derived = derive_draft_geometry(draft)
    section = build_section_input_from_draft(draft, catalog)
    result = solve_bending_capacity(section, catalog)

    svg = build_section_drawing_svg(
        derived,
        selected_point=result.peak_point,
        section=section,
        materials=catalog,
        result=result,
    )

    assert 'data-role="concrete-stress-scale"' in svg
    assert 'data-role="steel-stress-scale"' in svg
    assert "σc" in svg
    assert "σs" in svg
