from dataclasses import replace
import re
import xml.etree.ElementTree as ET

from rc_bending.materials import load_material_catalog
from rc_bending.models import BendingResult
from rc_bending.solver import solve_bending_capacity
from rc_bending.ui_helpers import build_section_input_from_draft, default_draft_inputs, derive_draft_geometry

TERMINATION_STUB = object()
SVG_NS = "{http://www.w3.org/2000/svg}"


def _extract_viewbox(svg: str) -> tuple[float, float]:
    match = re.search(r'viewBox="0 0 ([0-9.]+) ([0-9.]+)"', svg)
    assert match is not None
    return float(match.group(1)), float(match.group(2))


def _extract_section_frame(svg: str) -> tuple[float, float, float, float]:
    match = re.search(
        r'<rect x="([0-9.]+)" y="([0-9.]+)" width="([0-9.]+)" height="([0-9.]+)" class="outline"[^>]*data-role="section-frame"',
        svg,
    )
    assert match is not None
    return tuple(float(value) for value in match.groups())


def _extract_group_translate_x(svg: str, role: str) -> float:
    match = re.search(rf'<g data-role="{re.escape(role)}" transform="translate\(([0-9.]+) 0\)">', svg)
    assert match is not None
    return float(match.group(1))


def _parse_svg(svg: str) -> ET.Element:
    return ET.fromstring(svg)


def _extract_group_translate_xy(root: ET.Element, role: str) -> list[tuple[float, float]]:
    positions: list[tuple[float, float]] = []
    for group in root.iter(f"{SVG_NS}g"):
        if group.attrib.get("data-role") != role:
            continue
        transform = group.attrib.get("transform", "")
        match = re.search(r"translate\(([0-9.]+) ([0-9.]+)\)", transform)
        assert match is not None
        positions.append((float(match.group(1)), float(match.group(2))))
    return positions


def _extract_rect_by_role(root: ET.Element, role: str) -> ET.Element:
    for rect in root.iter(f"{SVG_NS}rect"):
        if rect.attrib.get("data-role") == role:
            return rect
    raise AssertionError(f"Rect with role {role} not found")


def _extract_callout_boxes(root: ET.Element) -> list[tuple[float, float, float, float]]:
    boxes: list[tuple[float, float, float, float]] = []
    for group in root.iter(f"{SVG_NS}g"):
        if group.attrib.get("data-role") != "rebar-callout":
            continue
        transform = group.attrib.get("transform", "")
        match = re.search(r"translate\(([0-9.]+) ([0-9.]+)\)", transform)
        assert match is not None
        callout_rect = next(
            child for child in group if child.tag == f"{SVG_NS}rect" and child.attrib.get("class") == "callout-card"
        )
        boxes.append(
            (
                float(match.group(1)),
                float(match.group(2)),
                float(callout_rect.attrib["width"]),
                float(callout_rect.attrib["height"]),
            )
        )
    return boxes


def _extract_text_y(root: ET.Element, value: str) -> float:
    for text in root.iter(f"{SVG_NS}text"):
        if (text.text or "").strip() == value:
            return float(text.attrib["y"])
    raise AssertionError(f"Text {value} not found")


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
        termination=TERMINATION_STUB,
    )


def test_build_section_drawing_svg_contains_geometry_dimensions_and_callouts():
    from rc_bending.section_drawing import build_section_drawing_svg

    draft = default_draft_inputs()
    derived = derive_draft_geometry(draft)

    svg = build_section_drawing_svg(derived)

    assert "<svg" in svg
    assert "Креслення перерізу" in svg
    assert "b = 500.0 мм" in svg
    assert "h = 120.0 мм" in svg
    assert "h1 = 60.0 мм" in svg
    assert "h2 = 60.0 мм" in svg
    assert "B1: C40/50" in svg
    assert "B2: C40/50" in svg
    assert "A1: 4 x 8" in svg
    assert "a1 = 40.0 мм" in svg
    assert "z1 = 40.0 мм" in svg
    assert "A2: 4 x 8" in svg
    assert "a2 = 20.0 мм" in svg
    assert "z2 = 100.0 мм" in svg
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


def test_build_section_drawing_svg_hides_zero_height_placeholder_layer_for_reference_slab():
    from rc_bending.section_drawing import build_section_drawing_svg

    draft = default_draft_inputs()
    draft["has_strengthening_layer"] = False
    draft["concrete_layers"][0]["height_mm"] = 20.0
    draft["concrete_layers"][0]["concrete_class"] = "C40/50"
    draft["concrete_layers"][1]["concrete_class"] = "C25/30"

    svg = build_section_drawing_svg(derive_draft_geometry(draft))

    assert "B1: C25/30" in svg
    assert "B2:" not in svg
    assert "h2 =" not in svg
    assert 'class="layer-split"' not in svg
    assert svg.count('data-role="layer-height-dimension"') == 0


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


def test_build_section_drawing_svg_hides_missing_first_form_when_active_point_is_second_form():
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
    assert "1-ша форма рівноваги" not in svg
    assert "форма не реалізована для цього набору даних" not in svg
    assert svg.count('data-role="form-placeholder"') == 0
    assert svg.count('data-role="form-panel"') == 1


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
    viewbox_width, viewbox_height = _extract_viewbox(svg)
    _, _, frame_width, _ = _extract_section_frame(svg)

    assert frame_width >= 500.0
    assert viewbox_width <= 1280.0
    assert viewbox_height <= 760.0


def test_build_section_drawing_svg_balances_single_panel_section_and_exposes_dimension_lanes():
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

    viewbox_width, _ = _extract_viewbox(svg)
    frame_x, _, frame_width, _ = _extract_section_frame(svg)
    frame_center_x = frame_x + frame_width / 2.0

    left_h_x = _extract_group_translate_x(svg, "dimension-lane-left-h")
    left_z1_x = _extract_group_translate_x(svg, "dimension-lane-left-z1")
    left_z2_x = _extract_group_translate_x(svg, "dimension-lane-left-z2")
    right_h1_x = _extract_group_translate_x(svg, "dimension-lane-right-h1")
    right_h2_x = _extract_group_translate_x(svg, "dimension-lane-right-h2")

    assert 'data-role="top-row-layout"' in svg
    assert 'data-role="left-dimension-zone"' in svg
    assert 'data-role="section-zone"' in svg
    assert 'data-role="right-detail-zone"' in svg
    assert svg.count('data-role="dimension-label-chip"') >= 5
    assert svg.count('data-role="dimension-label-chip" transform="rotate(-90') >= 5
    assert viewbox_width * 0.40 <= frame_center_x <= viewbox_width * 0.50
    assert left_h_x < left_z1_x < left_z2_x < frame_x
    assert frame_x + frame_width < right_h1_x < right_h2_x


def test_build_section_drawing_svg_separates_single_panel_dimension_lanes_and_callout_column():
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
    root = _parse_svg(svg)

    left_h_x = _extract_group_translate_x(svg, "dimension-lane-left-h")
    left_z1_x = _extract_group_translate_x(svg, "dimension-lane-left-z1")
    left_z2_x = _extract_group_translate_x(svg, "dimension-lane-left-z2")
    right_h1_x = _extract_group_translate_x(svg, "dimension-lane-right-h1")
    right_h2_x = _extract_group_translate_x(svg, "dimension-lane-right-h2")
    callout_positions = _extract_group_translate_xy(root, "rebar-callout")

    assert left_z1_x - left_h_x >= 64.0
    assert left_z2_x - left_z1_x >= 64.0
    assert right_h2_x - right_h1_x >= 64.0
    assert min(callout_x for callout_x, _ in callout_positions) - right_h2_x >= 52.0


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


def test_build_section_drawing_svg_keeps_scale_labels_above_result_strip():
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
    root = _parse_svg(svg)
    result_strip = _extract_rect_by_role(root, "result-strip")
    result_strip_y = float(result_strip.attrib["y"])

    assert _extract_text_y(root, "МПа") <= result_strip_y - 12.0
    assert _extract_text_y(root, "‰") <= result_strip_y - 12.0


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


def test_build_section_drawing_svg_stacks_callout_boxes_with_positive_gap():
    from rc_bending.section_drawing import build_section_drawing_svg

    draft = default_draft_inputs()
    draft["rebar_layers"] = [
        {"id": "rebar_1", "face": "Верхня", "distance_mm": 30.0, "bar_count": 4, "diameter_mm": 20, "steel_class": "A400C"},
        {"id": "rebar_2", "face": "Верхня", "distance_mm": 45.0, "bar_count": 3, "diameter_mm": 18, "steel_class": "A400C"},
        {"id": "rebar_3", "face": "Нижня", "distance_mm": 50.0, "bar_count": 3, "diameter_mm": 18, "steel_class": "A500C"},
        {"id": "rebar_4", "face": "Нижня", "distance_mm": 30.0, "bar_count": 4, "diameter_mm": 20, "steel_class": "A500C"},
    ]

    svg = build_section_drawing_svg(derive_draft_geometry(draft))
    root = _parse_svg(svg)
    callout_boxes = sorted(_extract_callout_boxes(root), key=lambda item: item[1])

    assert len(callout_boxes) == 4
    for previous, current in zip(callout_boxes, callout_boxes[1:]):
        _, previous_top, _, previous_height = previous
        _, current_top, _, _ = current
        assert current_top - (previous_top + previous_height) >= 8.0


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
