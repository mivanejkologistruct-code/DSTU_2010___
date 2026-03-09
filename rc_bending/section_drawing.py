from __future__ import annotations

from rc_bending.materials import MaterialCatalog
from rc_bending.models import BendingResult, CurvePoint, SectionDiagramState, SectionInput
from rc_bending.solver import build_section_diagram_state, find_comparison_curve_point

FORM_TITLES = {
    "first": "1-ша форма рівноваги",
    "second": "2-га форма рівноваги",
}


def _escape_text(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;")


def _fmt_mm(value: float) -> str:
    return f"{value:.1f} мм"


def _fmt_force(value: float) -> str:
    return f"{value:.1f} кН"


def _fmt_stress(value: float) -> str:
    return f"{value:.1f} МПа"


def _fmt_strain_promille(value: float) -> str:
    return f"{value * 1000.0:.3f}‰"


def _text(
    x: float,
    y: float,
    value: str,
    *,
    css_class: str = "",
    anchor: str = "start",
    data_role: str = "",
) -> str:
    class_attr = f' class="{css_class}"' if css_class else ""
    role_attr = f' data-role="{data_role}"' if data_role else ""
    return f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}"{class_attr}{role_attr}>{_escape_text(value)}</text>'


def _line(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    css_class: str = "",
    marker_start: str = "",
    marker_end: str = "",
    data_role: str = "",
) -> str:
    class_attr = f' class="{css_class}"' if css_class else ""
    start_attr = f' marker-start="url(#{marker_start})"' if marker_start else ""
    end_attr = f' marker-end="url(#{marker_end})"' if marker_end else ""
    role_attr = f' data-role="{data_role}"' if data_role else ""
    return (
        f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"'
        f"{class_attr}{start_attr}{end_attr}{role_attr} />"
    )


def _polyline(
    points: list[tuple[float, float]],
    *,
    css_class: str = "",
    data_role: str = "",
) -> str:
    class_attr = f' class="{css_class}"' if css_class else ""
    role_attr = f' data-role="{data_role}"' if data_role else ""
    serialized = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    return f'<polyline points="{serialized}"{class_attr}{role_attr} />'


def _polygon(
    points: list[tuple[float, float]],
    *,
    css_class: str = "",
    data_role: str = "",
) -> str:
    class_attr = f' class="{css_class}"' if css_class else ""
    role_attr = f' data-role="{data_role}"' if data_role else ""
    serialized = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    return f'<polygon points="{serialized}"{class_attr}{role_attr} />'


def _rect(
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    css_class: str = "",
    fill: str | None = None,
    rx: float | None = None,
    ry: float | None = None,
    data_role: str = "",
) -> str:
    class_attr = f' class="{css_class}"' if css_class else ""
    fill_attr = f' fill="{fill}"' if fill is not None else ""
    rx_attr = f' rx="{rx:.1f}"' if rx is not None else ""
    ry_attr = f' ry="{ry:.1f}"' if ry is not None else ""
    role_attr = f' data-role="{data_role}"' if data_role else ""
    return (
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" height="{height:.1f}"'
        f"{class_attr}{fill_attr}{rx_attr}{ry_attr}{role_attr} />"
    )


def _circle(
    x: float,
    y: float,
    radius: float,
    *,
    css_class: str = "",
    data_role: str = "",
) -> str:
    class_attr = f' class="{css_class}"' if css_class else ""
    role_attr = f' data-role="{data_role}"' if data_role else ""
    return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}"{class_attr}{role_attr} />'


def _horizontal_dimension(x1: float, x2: float, y: float, text: str, *, data_role: str = "") -> str:
    mid_x = (x1 + x2) / 2.0
    return "".join(
        [
            _line(x1, y + 10.0, x1, y - 18.0, css_class="dim-extension"),
            _line(x2, y + 10.0, x2, y - 18.0, css_class="dim-extension"),
            _line(
                x1,
                y - 10.0,
                x2,
                y - 10.0,
                css_class="dim-line",
                marker_start="arrow-end",
                marker_end="arrow-end",
                data_role=data_role,
            ),
            _dimension_label_chip(mid_x, y - 16.0, text),
        ]
    )


def _dimension_label_chip(
    x: float,
    y: float,
    text: str,
    *,
    anchor: str = "middle",
    data_role: str = "dimension-label-chip",
) -> str:
    width = max(84.0, 24.0 + len(text) * 7.1)
    height = 24.0
    if anchor == "start":
        chip_x = x
    elif anchor == "end":
        chip_x = x - width
    else:
        chip_x = x - width / 2.0
    return "".join(
        [
            f'<g data-role="{data_role}">',
            _rect(chip_x, y - height / 2.0, width, height, css_class="dim-chip", rx=12.0, ry=12.0),
            _text(chip_x + width / 2.0, y + 4.0, text, css_class="dim-chip-text", anchor="middle"),
            "</g>",
        ]
    )


def _vertical_dimension(
    x: float,
    y1: float,
    y2: float,
    text: str,
    *,
    data_role: str = "",
    label_chip: bool = False,
    label_x: float | None = None,
    label_anchor: str = "end",
) -> str:
    mid_y = (y1 + y2) / 2.0
    return "".join(
        [
            _line(x + 22.0, y1, x - 8.0, y1, css_class="dim-extension"),
            _line(x + 22.0, y2, x - 8.0, y2, css_class="dim-extension"),
            _line(x, y1, x, y2, css_class="dim-line", marker_start="arrow-end", marker_end="arrow-end", data_role=data_role),
            (
                _dimension_label_chip(label_x if label_x is not None else x - 14.0, mid_y, text, anchor=label_anchor)
                if label_chip
                else _text(x - 14.0, mid_y, text, css_class="dim-text", anchor="end")
            ),
        ]
    )


def _vertical_dimension_lane(
    x: float,
    y1: float,
    y2: float,
    text: str,
    *,
    lane_role: str,
    line_role: str,
    label_x: float = -28.0,
) -> str:
    return "".join(
        [
            f'<g data-role="{lane_role}" transform="translate({x:.1f} 0)">',
            _vertical_dimension(
                0.0,
                y1,
                y2,
                text,
                data_role=line_role,
                label_chip=True,
                label_x=label_x,
                label_anchor="middle",
            ),
            "</g>",
        ]
    )


def _build_rebar_centers(x: float, width: float, count: int) -> list[float]:
    if count <= 1:
        return [x + width / 2.0]

    spacing = width / (count + 1)
    return [x + spacing * (index + 1) for index in range(count)]


def _estimate_chip_width(value: str, *, min_width: float = 112.0) -> float:
    return max(min_width, 28.0 + len(value) * 7.2)


def _chip(
    x: float,
    y: float,
    value: str,
    *,
    chip_class: str = "layer-chip",
    text_class: str = "chip-text",
    data_role: str = "",
) -> str:
    width = _estimate_chip_width(value)
    return "".join(
        [
            _rect(x, y - 18.0, width, 30.0, css_class=chip_class, rx=15.0, ry=15.0, data_role=data_role),
            _text(x + 14.0, y + 2.0, value, css_class=text_class),
        ]
    )


def _annotation_card(
    x: float,
    y: float,
    width: float,
    title: str,
    meta: str,
    *,
    card_class: str = "annotation-card",
    title_class: str = "annotation-title",
    meta_class: str = "annotation-meta",
) -> str:
    return "".join(
        [
            f'<g data-role="annotation-card" transform="translate({x:.1f} {y:.1f})">',
            _rect(0.0, 0.0, width, 36.0, css_class=card_class, rx=10.0, ry=10.0),
            _text(10.0, 14.0, title, css_class=title_class),
            _text(10.0, 28.0, meta, css_class=meta_class),
            "</g>",
        ]
    )


def _stack_callout_tops(targets: list[float], min_top: float, max_top: float, gap: float) -> list[float]:
    if not targets:
        return []

    indexed_targets = sorted(enumerate(targets), key=lambda item: item[1])
    placed_tops: list[float] = []
    current_top = min_top
    for _, target in indexed_targets:
        top = max(target, current_top)
        placed_tops.append(top)
        current_top = top + gap

    placed_tops[-1] = min(placed_tops[-1], max_top)
    for index in range(len(placed_tops) - 2, -1, -1):
        placed_tops[index] = min(placed_tops[index], placed_tops[index + 1] - gap)

    if placed_tops[0] < min_top:
        placed_tops[0] = min_top
        for index in range(1, len(placed_tops)):
            placed_tops[index] = max(placed_tops[index], placed_tops[index - 1] + gap)

    resolved = [0.0] * len(targets)
    for (original_index, _), top in zip(indexed_targets, placed_tops):
        resolved[original_index] = top
    return resolved


def _resolve_form_states(
    section: SectionInput | None,
    materials: MaterialCatalog | None,
    result: BendingResult | None,
    selected_point: CurvePoint | None,
) -> tuple[SectionDiagramState | None, SectionDiagramState | None]:
    if selected_point is None or section is None or materials is None:
        return None, None

    active_state = build_section_diagram_state(section, materials, selected_point, is_active=True)
    comparison_state = None
    if result is not None:
        comparison_point = find_comparison_curve_point(result, selected_point)
        if comparison_point is not None:
            comparison_state = build_section_diagram_state(section, materials, comparison_point, is_active=False)
    return active_state, comparison_state


def _build_panel_scale_limits(states: tuple[SectionDiagramState | None, SectionDiagramState | None]) -> tuple[float, float, float]:
    concrete_states = [state for state in states if state is not None]
    if not concrete_states:
        return 1.0, 1.0, 1.0

    concrete_stress_max = max(
        max((abs(point.stress_mpa) for point in state.concrete_profile), default=0.0) for state in concrete_states
    )
    steel_stress_max = max(
        max((abs(rebar.stress_mpa) for rebar in state.rebar_states), default=0.0) for state in concrete_states
    )
    strain_max = max(state.scale_limits.strain_abs_max for state in concrete_states)
    return max(concrete_stress_max, 1.0), max(steel_stress_max, 1.0), max(strain_max, 0.0001)


def _build_panel_entries(
    active_state: SectionDiagramState | None,
    comparison_state: SectionDiagramState | None,
) -> list[tuple[str, SectionDiagramState | None]]:
    if active_state is None and comparison_state is None:
        return [(FORM_TITLES["first"], None), (FORM_TITLES["second"], None)]

    if active_state is not None and active_state.form == "second" and comparison_state is None:
        return [(FORM_TITLES["second"], active_state)]

    states_by_form: dict[str, SectionDiagramState | None] = {"first": None, "second": None}
    for state in (active_state, comparison_state):
        if state is not None:
            states_by_form[state.form] = state
    return [(FORM_TITLES["first"], states_by_form["first"]), (FORM_TITLES["second"], states_by_form["second"])]


def _build_form_panel(
    title: str,
    state: SectionDiagramState | None,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    section_height_mm: float,
    layer_split_mm: float,
    concrete_stress_abs_max_mpa: float,
    steel_stress_abs_max_mpa: float,
    strain_abs_max: float,
) -> str:
    badge_map = {
        True: ("Активна точка", "panel-badge panel-badge--active"),
        False: ("Порівняння", "panel-badge panel-badge--comparison"),
    }
    fragments = [f'<g data-role="form-panel" transform="translate({x:.1f} {y:.1f})">']
    fragments.append(_rect(0.0, 0.0, width, height, css_class="panel-card", rx=22.0, ry=22.0))
    fragments.append(_text(22.0, 30.0, title, css_class="panel-title"))
    fragments.append(_line(22.0, 48.0, width - 22.0, 48.0, css_class="panel-divider", data_role="panel-divider"))

    if state is None:
        fragments.append(
            "".join(
                [
                    _rect(20.0, 56.0, width - 40.0, height - 92.0, css_class="placeholder-card", rx=18.0, ry=18.0, data_role="form-placeholder"),
                    _text(42.0, 110.0, "форма не реалізована для цього набору даних", css_class="placeholder-title"),
                    _text(42.0, 146.0, "Для цієї форми немає придатної точки на поточній кривій.", css_class="placeholder-copy"),
                    _text(42.0, 174.0, "Змініть геометрію або крок розрахунку, щоб побачити епюру.", css_class="placeholder-copy"),
                    _line(width - 166.0, 108.0, width - 166.0, 244.0, css_class="placeholder-axis"),
                    _line(width - 224.0, 236.0, width - 88.0, 236.0, css_class="placeholder-axis"),
                    _polyline(
                        [
                            (width - 166.0, 108.0),
                            (width - 134.0, 136.0),
                            (width - 122.0, 174.0),
                            (width - 96.0, 208.0),
                        ],
                        css_class="placeholder-curve",
                    ),
                    _polyline(
                        [
                            (width - 208.0, 208.0),
                            (width - 166.0, 182.0),
                            (width - 118.0, 144.0),
                        ],
                        css_class="placeholder-curve placeholder-curve--secondary",
                    ),
                ]
            )
        )
        fragments.append("</g>")
        return "".join(fragments)

    badge_label, badge_class = badge_map[state.is_active]
    badge_width = _estimate_chip_width(badge_label, min_width=126.0)
    fragments.append(_rect(width - badge_width - 22.0, 12.0, badge_width, 28.0, css_class=badge_class, rx=14.0, ry=14.0, data_role="form-panel-badge"))
    fragments.append(_text(width - badge_width + 6.0, 31.0, badge_label, css_class="panel-badge-text"))

    top_margin = 84.0
    bottom_margin = 88.0
    body_height = height - top_margin - bottom_margin
    scale_y = body_height / max(section_height_mm, 1.0)
    diagram_y = lambda z_mm: top_margin + z_mm * scale_y
    expanded_layout = width >= 760.0
    note_width = 126.0 if expanded_layout else 108.0
    left_note_x = 22.0
    right_note_x = width - note_width - 22.0
    stress_zone_left = left_note_x + note_width + 14.0
    stress_zone_right = stress_zone_left + (212.0 if expanded_layout else 176.0)
    concrete_zone_left = stress_zone_left + 6.0
    concrete_zone_width = 76.0 if expanded_layout else 66.0
    concrete_zone_right = concrete_zone_left + concrete_zone_width
    concrete_zero_x = concrete_zone_left + 4.0
    concrete_pos_width = concrete_zone_right - concrete_zero_x - 4.0
    stress_gap = 16.0 if expanded_layout else 14.0
    steel_zone_left = concrete_zone_right + stress_gap
    steel_zone_right = stress_zone_right - 6.0
    steel_half_width = max((steel_zone_right - steel_zone_left) / 2.0, 1.0)
    steel_zero_x = steel_zone_left + steel_half_width
    strain_zone_left = stress_zone_right + 22.0
    strain_zone_right = right_note_x - 10.0
    strain_zero_x = (strain_zone_left + strain_zone_right) / 2.0
    strain_half_width = max((strain_zone_right - strain_zone_left) / 2.0, 1.0)
    body_top = top_margin
    body_bottom = top_margin + body_height
    concrete_stress_scale = concrete_pos_width / max(concrete_stress_abs_max_mpa, 1.0)
    steel_stress_scale = steel_half_width / max(steel_stress_abs_max_mpa, 1.0)
    strain_scale = strain_half_width / max(strain_abs_max, 1e-9)

    level_rows = [("0", 0.0), ("h1", layer_split_mm), ("0.5h", section_height_mm * 0.5), ("h", section_height_mm)]
    if 0.0 <= state.point.neutral_axis_mm <= section_height_mm:
        level_rows.append(("x", state.point.neutral_axis_mm))
    unique_levels: list[tuple[str, float]] = []
    seen_levels: set[int] = set()
    for label, depth in level_rows:
        key = round(depth)
        if key in seen_levels:
            continue
        seen_levels.add(key)
        unique_levels.append((label, depth))

    fragments.extend(
        [
            _rect(stress_zone_left, body_top - 4.0, stress_zone_right - stress_zone_left, body_height + 8.0, css_class="plot-zone", rx=14.0, ry=14.0),
            _rect(concrete_zone_left, body_top, concrete_zone_width, body_height, css_class="material-plot-zone", rx=10.0, ry=10.0),
            _rect(steel_zone_left, body_top, steel_zone_right - steel_zone_left, body_height, css_class="material-plot-zone", rx=10.0, ry=10.0),
            _rect(strain_zone_left, body_top - 4.0, strain_zone_right - strain_zone_left, body_height + 8.0, css_class="plot-zone", rx=14.0, ry=14.0),
            _text((stress_zone_left + stress_zone_right) / 2.0, 66.0, "Епюра напружень σ", css_class="panel-subtitle", anchor="middle"),
            _text(strain_zero_x, 66.0, "Епюра деформацій ε", css_class="panel-subtitle", anchor="middle"),
            _text(concrete_zero_x + concrete_pos_width / 2.0, 82.0, "σc", css_class="material-scale-title", anchor="middle"),
            _text(steel_zero_x, 82.0, "σs", css_class="material-scale-title", anchor="middle"),
            _line(concrete_zero_x, body_top, concrete_zero_x, body_bottom, css_class="scale-axis"),
            _line(steel_zero_x, body_top, steel_zero_x, body_bottom, css_class="scale-axis"),
            _line(concrete_zone_right + stress_gap / 2.0, body_top + 2.0, concrete_zone_right + stress_gap / 2.0, body_bottom - 2.0, css_class="material-divider"),
            f'<g data-role="concrete-stress-scale">{_line(concrete_zero_x, body_bottom + 16.0, concrete_zero_x + concrete_pos_width, body_bottom + 16.0, css_class="scale-line")}{_line(concrete_zero_x, body_bottom + 10.0, concrete_zero_x, body_bottom + 22.0, css_class="scale-tick")}{_line(concrete_zero_x + concrete_pos_width, body_bottom + 10.0, concrete_zero_x + concrete_pos_width, body_bottom + 22.0, css_class="scale-tick")}{_text(concrete_zero_x, body_bottom + 38.0, "0", css_class="scale-label", anchor="middle")}{_text(concrete_zero_x + concrete_pos_width, body_bottom + 38.0, f"{concrete_stress_abs_max_mpa:.1f}", css_class="scale-label", anchor="middle")}</g>',
            f'<g data-role="steel-stress-scale">{_line(steel_zero_x - steel_half_width, body_bottom + 16.0, steel_zero_x + steel_half_width, body_bottom + 16.0, css_class="scale-line", data_role="stress-scale")}{_line(steel_zero_x - steel_half_width, body_bottom + 10.0, steel_zero_x - steel_half_width, body_bottom + 22.0, css_class="scale-tick")}{_line(steel_zero_x, body_bottom + 10.0, steel_zero_x, body_bottom + 22.0, css_class="scale-tick")}{_line(steel_zero_x + steel_half_width, body_bottom + 10.0, steel_zero_x + steel_half_width, body_bottom + 22.0, css_class="scale-tick")}{_text(steel_zero_x - steel_half_width, body_bottom + 38.0, f"-{steel_stress_abs_max_mpa:.0f}", css_class="scale-label", anchor="middle")}{_text(steel_zero_x, body_bottom + 38.0, "0", css_class="scale-label", anchor="middle")}{_text(steel_zero_x + steel_half_width, body_bottom + 38.0, f"+{steel_stress_abs_max_mpa:.0f}", css_class="scale-label", anchor="middle")}</g>',
            _text(steel_zone_right, body_bottom + 56.0, "МПа", css_class="scale-label", anchor="end"),
            _line(strain_zero_x, body_top, strain_zero_x, body_bottom, css_class="scale-axis"),
            _line(strain_zero_x - strain_half_width, body_bottom + 16.0, strain_zero_x + strain_half_width, body_bottom + 16.0, css_class="scale-line", data_role="strain-scale"),
            _line(strain_zero_x - strain_half_width, body_bottom + 10.0, strain_zero_x - strain_half_width, body_bottom + 22.0, css_class="scale-tick"),
            _line(strain_zero_x, body_bottom + 10.0, strain_zero_x, body_bottom + 22.0, css_class="scale-tick"),
            _line(strain_zero_x + strain_half_width, body_bottom + 10.0, strain_zero_x + strain_half_width, body_bottom + 22.0, css_class="scale-tick"),
            _text(strain_zero_x - strain_half_width, body_bottom + 38.0, f"{-strain_abs_max * 1000.0:.2f}", css_class="scale-label", anchor="middle"),
            _text(strain_zero_x, body_bottom + 38.0, "0", css_class="scale-label", anchor="middle"),
            _text(strain_zero_x + strain_half_width, body_bottom + 38.0, f"{strain_abs_max * 1000.0:.2f}", css_class="scale-label", anchor="middle"),
            _text(strain_zero_x + strain_half_width, body_bottom + 56.0, "‰", css_class="scale-label", anchor="end"),
        ]
    )

    for label, depth_mm in unique_levels:
        level_y = diagram_y(depth_mm)
        fragments.extend(
            [
                _line(stress_zone_left + 4.0, level_y, strain_zone_right - 4.0, level_y, css_class="grid-line", data_role="form-grid-line"),
                _text(stress_zone_left - 14.0, level_y - 4.0, label, css_class="grid-label", anchor="end", data_role="level-marker"),
            ]
        )

    concrete_polygon = [(concrete_zero_x, body_top)]
    for point in state.concrete_profile:
        concrete_polygon.append((concrete_zero_x + point.stress_mpa * concrete_stress_scale, diagram_y(point.z_mm)))
    concrete_polygon.append((concrete_zero_x, body_bottom))
    fragments.append(_polygon(concrete_polygon, css_class="concrete-stress-area", data_role="concrete-stress-area"))

    top_x = strain_zero_x + state.point.top_strain * strain_scale
    bottom_x = strain_zero_x + state.point.bottom_strain * strain_scale
    fragments.append(_line(top_x, body_top, bottom_x, body_bottom, css_class="strain-line"))
    fragments.append(_circle(top_x, body_top, 3.6, css_class="strain-node"))
    fragments.append(_circle(bottom_x, body_bottom, 3.6, css_class="strain-node"))

    if 0.0 <= state.point.neutral_axis_mm <= section_height_mm:
        neutral_axis_y = diagram_y(state.point.neutral_axis_mm)
        fragments.append(_line(left_note_x, neutral_axis_y, width - 18.0, neutral_axis_y, css_class="neutral-axis", data_role="neutral-axis"))
        fragments.append(_text(width - 20.0, neutral_axis_y - 6.0, f"x = {_fmt_mm(state.point.neutral_axis_mm)}", css_class="panel-note", anchor="end"))
    else:
        fragments.append(_text(width - 22.0, 66.0, f"x = {_fmt_mm(state.point.neutral_axis_mm)} > h", css_class="panel-note", anchor="end"))

    max_force = max(
        [abs(state.concrete_resultant.force_kN) if state.concrete_resultant is not None else 0.0]
        + [abs(rebar.force_kN) for rebar in state.rebar_states]
        + [1.0]
    )
    sorted_rebars = sorted(state.rebar_states, key=lambda rebar: rebar.z_mm)
    top_rebar = sorted_rebars[0] if sorted_rebars else None
    bottom_rebar = sorted_rebars[-1] if sorted_rebars else None

    if state.concrete_resultant is not None:
        concrete_peak_stress_mpa = max((point.stress_mpa for point in state.concrete_profile), default=0.0)
        concrete_force_x = concrete_zero_x + concrete_peak_stress_mpa * concrete_stress_scale
        concrete_force_y = diagram_y(state.concrete_resultant.z_mm)
        fragments.append(
            _line(
                concrete_zero_x,
                concrete_force_y,
                concrete_force_x,
                concrete_force_y,
                css_class="force-line force-line--concrete",
                marker_end="arrow-end",
                data_role="force-resultant",
            )
        )
        concrete_card_y = body_top + 8.0
        fragments.append(
            _polyline(
                [
                    (left_note_x + note_width, concrete_card_y + 18.0),
                    (stress_zone_left - 8.0, concrete_card_y + 18.0),
                    (stress_zone_left - 8.0, concrete_force_y),
                    (concrete_force_x, concrete_force_y),
                ],
                css_class="annotation-link annotation-link--concrete",
            )
        )
        fragments.append(
            _annotation_card(
                left_note_x,
                concrete_card_y,
                note_width,
                f"N_c = {_fmt_force(state.concrete_resultant.force_kN)}",
                f"z_c = {_fmt_mm(state.concrete_resultant.z_mm)}",
                card_class="annotation-card annotation-card--concrete",
            )
        )

    tension_rebars = [rebar for rebar in state.rebar_states if rebar.force_kN < 0.0]
    tension_centroid_mm: float | None = None
    if tension_rebars:
        tension_force = sum(-rebar.force_kN for rebar in tension_rebars)
        tension_centroid_mm = sum((-rebar.force_kN) * rebar.z_mm for rebar in tension_rebars) / tension_force

    for rebar in state.rebar_states:
        y_rebar = diagram_y(rebar.z_mm)
        stress_x = steel_zero_x + rebar.stress_mpa * steel_stress_scale
        block_x = min(steel_zero_x, stress_x)
        block_width = max(abs(stress_x - steel_zero_x), 1.6)
        block_height = 16.0
        fragments.append(
            _rect(
                block_x,
                y_rebar - block_height / 2.0,
                block_width,
                block_height,
                css_class="steel-stress-block",
                rx=4.0,
                ry=4.0,
                data_role="steel-stress-block",
            )
        )
        label_anchor = "start" if stress_x >= steel_zero_x else "end"
        label_x = stress_x + 8.0 if label_anchor == "start" else stress_x - 8.0
        if y_rebar < body_top + 28.0:
            force_label_y = y_rebar + 16.0
            force_meta_y = y_rebar + 31.0
            strain_label_y = y_rebar + 46.0
        elif y_rebar > body_bottom - 22.0:
            force_label_y = y_rebar - 26.0
            force_meta_y = y_rebar - 11.0
            strain_label_y = y_rebar - 41.0
        else:
            force_label_y = y_rebar - 5.0
            force_meta_y = y_rebar + 10.0
            strain_label_y = y_rebar - 5.0
        fragments.append(
            _line(
                steel_zero_x,
                y_rebar,
                stress_x,
                y_rebar,
                css_class="force-line force-line--steel",
                marker_end="arrow-end",
            )
        )

        strain_x = strain_zero_x + rebar.strain * strain_scale
        fragments.append(_circle(strain_x, y_rebar, 3.0, css_class="strain-node"))
        fragments.append(_line(strain_zero_x, y_rebar, strain_x, y_rebar, css_class="strain-guide"))

    if top_rebar is not None:
        top_force_y = body_top + 54.0
        top_force_target_x = steel_zero_x + top_rebar.stress_mpa * steel_stress_scale
        top_force_target_y = diagram_y(top_rebar.z_mm)
        fragments.append(
            _polyline(
                [
                    (left_note_x + note_width, top_force_y + 18.0),
                    (stress_zone_left - 8.0, top_force_y + 18.0),
                    (stress_zone_left - 8.0, top_force_target_y),
                    (top_force_target_x, top_force_target_y),
                ],
                css_class="annotation-link annotation-link--steel",
            )
        )
        fragments.append(
            _annotation_card(
                left_note_x,
                top_force_y,
                note_width,
                f"σs{top_rebar.index} = {_fmt_stress(top_rebar.stress_mpa)}",
                f"N_A{top_rebar.index} = {_fmt_force(top_rebar.force_kN)}",
                card_class="annotation-card annotation-card--steel",
            )
        )

    if bottom_rebar is not None and bottom_rebar is not top_rebar:
        bottom_force_y = body_bottom - 40.0
        bottom_force_target_x = steel_zero_x + bottom_rebar.stress_mpa * steel_stress_scale
        bottom_force_target_y = diagram_y(bottom_rebar.z_mm)
        fragments.append(
            _polyline(
                [
                    (left_note_x + note_width, bottom_force_y + 18.0),
                    (stress_zone_left - 8.0, bottom_force_y + 18.0),
                    (stress_zone_left - 8.0, bottom_force_target_y),
                    (bottom_force_target_x, bottom_force_target_y),
                ],
                css_class="annotation-link annotation-link--steel",
            )
        )
        fragments.append(
            _annotation_card(
                left_note_x,
                bottom_force_y,
                note_width,
                f"σs{bottom_rebar.index} = {_fmt_stress(bottom_rebar.stress_mpa)}",
                f"N_A{bottom_rebar.index} = {_fmt_force(bottom_rebar.force_kN)}",
                card_class="annotation-card annotation-card--steel",
            )
        )

    if top_rebar is not None:
        top_strain_y = body_top + 8.0
        top_strain_x = strain_zero_x + top_rebar.strain * strain_scale
        top_strain_target_y = diagram_y(top_rebar.z_mm)
        fragments.append(
            _polyline(
                [
                    (right_note_x, top_strain_y + 12.0),
                    (strain_zone_right + 8.0, top_strain_y + 12.0),
                    (strain_zone_right + 8.0, body_top),
                    (top_x, body_top),
                ],
                css_class="annotation-link annotation-link--strain",
            )
        )
        fragments.append(
            _polyline(
                [
                    (right_note_x, top_strain_y + 24.0),
                    (strain_zone_right + 8.0, top_strain_y + 24.0),
                    (strain_zone_right + 8.0, top_strain_target_y),
                    (top_strain_x, top_strain_target_y),
                ],
                css_class="annotation-link annotation-link--strain",
            )
        )
        fragments.append(
            _annotation_card(
                right_note_x,
                top_strain_y,
                note_width,
                f"εc(1) = {_fmt_strain_promille(state.point.top_strain)}",
                f"εs{top_rebar.index} = {_fmt_strain_promille(top_rebar.strain)}",
                card_class="annotation-card annotation-card--strain",
            )
        )

    if bottom_rebar is not None:
        bottom_strain_y = body_bottom - 40.0
        bottom_strain_x = strain_zero_x + bottom_rebar.strain * strain_scale
        bottom_strain_target_y = diagram_y(bottom_rebar.z_mm)
        fragments.append(
            _polyline(
                [
                    (right_note_x, bottom_strain_y + 12.0),
                    (strain_zone_right + 8.0, bottom_strain_y + 12.0),
                    (strain_zone_right + 8.0, bottom_strain_target_y),
                    (bottom_strain_x, bottom_strain_target_y),
                ],
                css_class="annotation-link annotation-link--strain",
            )
        )
        fragments.append(
            _polyline(
                [
                    (right_note_x, bottom_strain_y + 24.0),
                    (strain_zone_right + 8.0, bottom_strain_y + 24.0),
                    (strain_zone_right + 8.0, body_bottom),
                    (bottom_x, body_bottom),
                ],
                css_class="annotation-link annotation-link--strain",
            )
        )
        fragments.append(
            _annotation_card(
                right_note_x,
                bottom_strain_y,
                note_width,
                f"εs{bottom_rebar.index} = {_fmt_strain_promille(bottom_rebar.strain)}",
                f"εc(2) = {_fmt_strain_promille(state.point.bottom_strain)}",
                card_class="annotation-card annotation-card--strain",
            )
        )

    if state.concrete_resultant is not None and tension_centroid_mm is not None and state.lever_arm_mm is not None:
        fragments.append(
            _vertical_dimension(
                width - 26.0,
                diagram_y(state.concrete_resultant.z_mm),
                diagram_y(tension_centroid_mm),
                f"z = {_fmt_mm(state.lever_arm_mm)}",
                data_role="lever-arm",
            )
        )

    if state.is_active:
        legend_width = width - 40.0
        legend_x = 20.0
        legend_y = height - 54.0
        chip_gap = 10.0
        chip_width = (legend_width - chip_gap * 2.0) / 3.0
        metric_items = [
            ("M", f"{state.point.moment_kNm:.2f} кН·м"),
            ("κ", f"{state.point.curvature_1_per_m:.4f} 1/м"),
            ("ΣN", f"{state.point.axial_residual_kN:.3f} кН"),
        ]
        fragments.append(_rect(20.0, legend_y - 2.0, width - 40.0, 40.0, css_class="result-strip", rx=15.0, ry=15.0, data_role="result-strip"))
        fragments.append(f'<g data-role="metric-legend" transform="translate({legend_x:.1f} {legend_y:.1f})">')
        for index, (label, value) in enumerate(metric_items):
            chip_x = index * (chip_width + chip_gap)
            fragments.extend(
                [
                    f'<g data-role="metric-chip" transform="translate({chip_x:.1f} 0)">',
                    _rect(0.0, 0.0, chip_width, 36.0, css_class="metric-chip-card", rx=12.0, ry=12.0),
                    _text(14.0, 15.0, label, css_class="metric-chip-label"),
                    _text(14.0, 29.0, value, css_class="metric-chip-value"),
                    "</g>",
                ]
            )
        fragments.append("</g>")
    fragments.append("</g>")
    return "".join(fragments)


def build_section_drawing_svg(
    derived: dict[str, object],
    *,
    selected_point: CurvePoint | None = None,
    section: SectionInput | None = None,
    materials: MaterialCatalog | None = None,
    result: BendingResult | None = None,
) -> str:
    section_height_mm = float(derived["section_height_mm"])
    section_width_mm = float(derived["section_width_mm"])
    concrete_rows = list(derived["concrete_rows"])
    rebar_rows = list(derived["rebar_rows"])

    active_state, comparison_state = _resolve_form_states(section, materials, result, selected_point)
    panel_entries = _build_panel_entries(active_state, comparison_state)
    panel_states = tuple(state for _, state in panel_entries)
    concrete_stress_abs_max_mpa, steel_stress_abs_max_mpa, strain_abs_max = _build_panel_scale_limits(panel_states)

    single_panel_mode = len(panel_entries) == 1
    if single_panel_mode:
        canvas_width = 1220.0
        panel_x = 44.0
        panel_width = canvas_width - panel_x * 2.0
        panel_height = 348.0
        panel_gap = 0.0
        top_row_left = panel_x + 12.0
        top_row_right = canvas_width - panel_x - 12.0
        scale = min(540.0 / max(section_width_mm, 1.0), 156.0 / max(section_height_mm, 1.0))
        drawing_width = section_width_mm * scale
        drawing_height = section_height_mm * scale
        section_x = (top_row_left + top_row_right - drawing_width) / 2.0
        section_y = 146.0
        callout_width = 176.0
        callout_gap = 58.0
        callout_x = top_row_right - callout_width
        left_h_lane_x = section_x - 120.0
        left_z1_lane_x = section_x - 76.0
        left_z2_lane_x = section_x - 32.0
        axis_x = section_x - 10.0
        right_h1_lane_x = section_x + drawing_width + 40.0
        right_h2_lane_x = section_x + drawing_width + 84.0
        panel_y_values = [section_y + drawing_height + 28.0]
        bottom_margin = 36.0
        canvas_height = panel_y_values[-1] + panel_height + bottom_margin
    else:
        scale = min(388.0 / max(section_width_mm, 1.0), 420.0 / max(section_height_mm, 1.0))
        drawing_width = section_width_mm * scale
        drawing_height = section_height_mm * scale
        section_x = 190.0
        section_y = 146.0
        callout_width = 176.0
        callout_gap = 58.0
        callout_x = section_x + drawing_width + 124.0
        panel_x = callout_x + callout_width + 24.0
        panel_width = 602.0
        panel_height = 362.0
        panel_gap = 24.0
        left_h_lane_x = section_x - 116.0
        left_z1_lane_x = section_x - 74.0
        left_z2_lane_x = section_x - 32.0
        axis_x = section_x - 10.0
        right_h1_lane_x = section_x + drawing_width + 40.0
        right_h2_lane_x = section_x + drawing_width + 82.0
        top_row_left = left_h_lane_x - 20.0
        top_row_right = callout_x + callout_width
        panel_y_values = [104.0 + index * (panel_height + panel_gap) for index in range(len(panel_entries))]
        bottom_margin = 56.0
        canvas_width = panel_x + panel_width + 26.0
        canvas_height = max(section_y + drawing_height + 92.0, panel_y_values[-1] + panel_height + bottom_margin)

    top_layer_height_mm = float(concrete_rows[0]["height_mm"])
    bottom_layer_height_mm = float(concrete_rows[1]["height_mm"])
    top_layer_height = top_layer_height_mm * scale
    bottom_layer_y = section_y + top_layer_height

    fragments: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_width:.1f}" height="{canvas_height:.1f}" viewBox="0 0 {canvas_width:.1f} {canvas_height:.1f}" role="img" aria-label="Креслення перерізу" data-role="diagram-sheet">',
        "<defs>",
        '<marker id="arrow-end" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">',
        '<path d="M 0 0 L 10 5 L 0 10 z" fill="#475569" /></marker>',
        '<filter id="card-shadow" x="-20%" y="-20%" width="140%" height="140%">',
        '<feDropShadow dx="0" dy="10" stdDeviation="12" flood-color="#94a3b8" flood-opacity="0.20" />',
        "</filter>",
        '<pattern id="hatch-concrete-stress" patternUnits="userSpaceOnUse" width="10" height="10" patternTransform="rotate(45)">',
        '<rect x="0" y="0" width="10" height="10" fill="#f8e5c1" />',
        '<line x1="0" y1="0" x2="0" y2="10" stroke="#cc8632" stroke-width="1.4" />',
        "</pattern>",
        '<pattern id="hatch-steel-stress" patternUnits="userSpaceOnUse" width="8" height="8" patternTransform="rotate(-45)">',
        '<rect x="0" y="0" width="8" height="8" fill="#edf4ff" />',
        '<line x1="0" y1="0" x2="0" y2="8" stroke="#5c82ca" stroke-width="1.2" />',
        "</pattern>",
        "</defs>",
        "<style>",
        ".title{font:700 27px 'Palatino Linotype','Book Antiqua',serif;fill:#0f172a;letter-spacing:0.01em;}",
        ".subtitle{font:15px 'Trebuchet MS',Verdana,sans-serif;fill:#516275;}",
        ".label{font:600 15px 'Trebuchet MS',Verdana,sans-serif;fill:#0f172a;}",
        ".chip-text{font:600 13px 'Trebuchet MS',Verdana,sans-serif;fill:#0f172a;}",
        ".small{font:13px 'Trebuchet MS',Verdana,sans-serif;fill:#44566c;}",
        ".dim-text{font:600 13px 'Trebuchet MS',Verdana,sans-serif;fill:#516275;}",
        ".dim-chip{fill:#ffffff;stroke:#d6e0ea;stroke-width:1.0;}",
        ".dim-chip-text{font:700 12px 'Trebuchet MS',Verdana,sans-serif;fill:#40566f;}",
        ".dim-line{stroke:#64748b;stroke-width:1.5;}",
        ".dim-extension{stroke:#b2bfd0;stroke-width:1.2;}",
        ".outline{stroke:#0f172a;stroke-width:2.6;fill:none;}",
        ".stage-bg{fill:#fbfdff;stroke:#d8e4f0;stroke-width:1.2;}",
        ".stage-accent{stroke:#e6edf5;stroke-width:1.2;}",
        ".layer-split{stroke:#62748a;stroke-width:1.6;stroke-dasharray:7 5;}",
        ".neutral-axis{stroke:#d4551f;stroke-width:2.0;stroke-dasharray:8 5;}",
        ".axis{stroke:#0f172a;stroke-width:1.6;marker-end:url(#arrow-end);}",
        ".rebar{fill:#2f67d8;stroke:#1747a6;stroke-width:1.1;}",
        ".rebar-warning{fill:#fca5a5;stroke:#b91c1c;stroke-width:1.4;}",
        ".compression-zone{fill:#f59e0b;fill-opacity:0.16;}",
        ".layer-chip{fill:#ffffff;stroke:#d7e1eb;stroke-width:1.2;}",
        ".callout-card{fill:#ffffff;stroke:#9eb2c7;stroke-width:1.3;filter:url(#card-shadow);}",
        ".callout-title{font:600 13px 'Trebuchet MS',Verdana,sans-serif;fill:#0f172a;}",
        ".callout-meta{font:12px 'Trebuchet MS',Verdana,sans-serif;fill:#44566c;}",
        ".callout-leader{stroke:#64748b;stroke-width:1.6;fill:none;}",
        ".callout-anchor{fill:#64748b;}",
        ".layout-warning{font:700 12px 'Trebuchet MS',Verdana,sans-serif;fill:#b91c1c;}",
        ".panel-card{fill:#fffdf8;stroke:#d8e4f0;stroke-width:1.4;filter:url(#card-shadow);}",
        ".panel-title{font:700 18px 'Trebuchet MS',Verdana,sans-serif;fill:#0f172a;}",
        ".panel-divider{stroke:#e2ebf3;stroke-width:1.2;}",
        ".panel-subtitle{font:700 12px 'Trebuchet MS',Verdana,sans-serif;fill:#607489;letter-spacing:0.04em;text-transform:uppercase;}",
        ".panel-note{font:12px 'Trebuchet MS',Verdana,sans-serif;fill:#5a6c81;paint-order:stroke;stroke:#fffdf8;stroke-width:3.5;stroke-linejoin:round;}",
        ".plot-zone{fill:#ffffff;fill-opacity:0.72;stroke:#e8eef5;stroke-width:1;}",
        ".material-plot-zone{fill:#fbfdff;stroke:#edf2f7;stroke-width:0.9;}",
        ".material-scale-title{font:700 11px 'Trebuchet MS',Verdana,sans-serif;fill:#607489;letter-spacing:0.06em;}",
        ".material-divider{stroke:#d8e3ee;stroke-width:1.0;stroke-dasharray:3 4;}",
        ".panel-badge{stroke-width:1.2;}",
        ".panel-badge--active{fill:#fff3e7;stroke:#cf6f32;}",
        ".panel-badge--comparison{fill:#eef5ff;stroke:#4175be;}",
        ".panel-badge-text{font:700 12px 'Trebuchet MS',Verdana,sans-serif;fill:#123047;}",
        ".placeholder-card{fill:#f8fbff;stroke:#c9d8e8;stroke-dasharray:8 6;}",
        ".placeholder-title{font:700 16px 'Trebuchet MS',Verdana,sans-serif;fill:#38536f;}",
        ".placeholder-copy{font:13px 'Trebuchet MS',Verdana,sans-serif;fill:#61788c;}",
        ".placeholder-axis{stroke:#d7e1eb;stroke-width:1.2;}",
        ".placeholder-curve{stroke:#8da5bd;stroke-width:2.0;fill:none;stroke-dasharray:6 5;}",
        ".placeholder-curve--secondary{stroke:#c06b34;stroke-width:1.6;stroke-dasharray:3 5;}",
        ".scale-axis{stroke:#64748b;stroke-width:1.4;}",
        ".scale-line{stroke:#94a3b8;stroke-width:1.2;}",
        ".scale-tick{stroke:#94a3b8;stroke-width:1.2;}",
        ".scale-label{font:12px 'Trebuchet MS',Verdana,sans-serif;fill:#64748b;}",
        ".grid-line{stroke:#dbe5ef;stroke-width:0.9;stroke-dasharray:3 5;}",
        ".grid-label{font:11px 'Trebuchet MS',Verdana,sans-serif;fill:#8aa0b4;}",
        ".concrete-stress-area{fill:url(#hatch-concrete-stress);stroke:#b45309;stroke-width:1.8;}",
        ".strain-line{stroke:#1d4ed8;stroke-width:2.0;}",
        ".strain-node{fill:#1d4ed8;stroke:#ffffff;stroke-width:1.0;}",
        ".strain-guide{stroke:#a0b7d8;stroke-width:1.1;stroke-dasharray:4 4;}",
        ".steel-stress-block{fill:url(#hatch-steel-stress);stroke:#2e60c3;stroke-width:1.0;}",
        ".force-line{stroke-width:1.8;}",
        ".force-line--concrete{stroke:#b45309;}",
        ".force-line--steel{stroke:#1d4ed8;}",
        ".annotation-link{stroke:#b2bfd0;stroke-width:1.1;fill:none;}",
        ".annotation-link--concrete{stroke:#c57a3f;}",
        ".annotation-link--steel{stroke:#5d84c9;}",
        ".annotation-link--strain{stroke:#8fa9d2;}",
        ".annotation-card{fill:#ffffff;stroke:#d7e2ed;stroke-width:1.0;filter:url(#card-shadow);}",
        ".annotation-card--concrete{stroke:#d1a06b;}",
        ".annotation-card--steel{stroke:#7f9fda;}",
        ".annotation-card--strain{stroke:#b7c8e5;}",
        ".annotation-title{font:700 11px 'Trebuchet MS',Verdana,sans-serif;fill:#203247;}",
        ".annotation-meta{font:11px 'Trebuchet MS',Verdana,sans-serif;fill:#607489;}",
        ".force-label{font:700 12px 'Trebuchet MS',Verdana,sans-serif;fill:#0f172a;paint-order:stroke;stroke:#fffdf8;stroke-width:4;stroke-linejoin:round;}",
        ".result-strip{fill:#f4f8fc;stroke:#dde7f0;stroke-width:1.0;}",
        ".metric-chip-card{fill:#ffffff;stroke:#d7e2ed;stroke-width:1.0;}",
        ".metric-chip-label{font:700 10px 'Trebuchet MS',Verdana,sans-serif;fill:#71879c;letter-spacing:0.08em;}",
        ".metric-chip-value{font:700 12px 'Trebuchet MS',Verdana,sans-serif;fill:#0f172a;}",
        "</style>",
        _rect(18.0, 14.0, canvas_width - 36.0, canvas_height - 28.0, css_class="stage-bg", rx=30.0, ry=30.0, data_role="drawing-stage"),
        _text(72.0, 44.0, "Креслення перерізу", css_class="title"),
        _text(72.0, 70.0, "Переріз, епюри напружень бетону й арматури та контрольні параметри в масштабному креслярському аркуші.", css_class="subtitle"),
        _line(42.0, 96.0, canvas_width - 42.0, 96.0, css_class="stage-accent"),
    ]
    left_zone_fragments: list[str] = []
    section_zone_fragments: list[str] = []
    right_zone_fragments: list[str] = []

    if selected_point is not None:
        compression_depth_mm = max(0.0, min(section_height_mm, selected_point.neutral_axis_mm))
        if compression_depth_mm > 0.0:
            section_zone_fragments.append(
                _rect(
                    section_x,
                    section_y,
                    drawing_width,
                    compression_depth_mm * scale,
                    css_class="compression-zone",
                    data_role="compression-zone",
                )
            )

    section_zone_fragments.extend(
        [
            _horizontal_dimension(
                section_x,
                section_x + drawing_width,
                section_y - 38.0,
                f"b = {_fmt_mm(section_width_mm)}",
                data_role="section-width-dimension",
            ),
            _rect(section_x, section_y, drawing_width, top_layer_height, fill="#edf3fe"),
            _rect(section_x, bottom_layer_y, drawing_width, max(section_height_mm - top_layer_height_mm, 0.0) * scale, fill="#dde8f8"),
            _rect(section_x, section_y, drawing_width, drawing_height, css_class="outline", data_role="section-frame"),
            _line(section_x, bottom_layer_y, section_x + drawing_width, bottom_layer_y, css_class="layer-split"),
            _chip(section_x + 18.0, section_y + 26.0, f"B1: {concrete_rows[0]['concrete_class']}", data_role="layer-chip"),
            _chip(section_x + 18.0, bottom_layer_y + 26.0, f"B2: {concrete_rows[1]['concrete_class']}", data_role="layer-chip"),
        ]
    )

    left_zone_fragments.extend(
        [
            _vertical_dimension_lane(
                left_h_lane_x,
                section_y,
                section_y + drawing_height,
                f"h = {_fmt_mm(section_height_mm)}",
                lane_role="dimension-lane-left-h",
                line_role="section-height-dimension",
            ),
            _line(axis_x, section_y, axis_x, section_y + drawing_height, css_class="axis"),
            _text(axis_x - 8.0, section_y - 12.0, "z", css_class="label", anchor="middle"),
        ]
    )

    right_zone_fragments.extend(
        [
            _vertical_dimension_lane(
                right_h1_lane_x,
                section_y,
                bottom_layer_y,
                f"h1 = {_fmt_mm(top_layer_height_mm)}",
                lane_role="dimension-lane-right-h1",
                line_role="layer-height-dimension",
            ),
            _vertical_dimension_lane(
                right_h2_lane_x,
                bottom_layer_y,
                section_y + drawing_height,
                f"h2 = {_fmt_mm(bottom_layer_height_mm)}",
                lane_role="dimension-lane-right-h2",
                line_role="layer-height-dimension",
            ),
        ]
    )

    callout_targets = [section_y + float(row["z_mm"]) * scale - 28.0 for row in rebar_rows]
    callout_min_top = section_y + 10.0
    callout_max_top = section_y + drawing_height - 64.0
    callout_tops = _stack_callout_tops(callout_targets, callout_min_top, callout_max_top, callout_gap)

    for row, callout_top in zip(rebar_rows, callout_tops):
        index = int(str(row["layer"])[1:])
        count = int(row["bar_count"])
        diameter_mm = int(row["diameter_mm"])
        z_mm = float(row["z_mm"])
        actual_y = section_y + z_mm * scale
        radius = max(diameter_mm * scale / 2.0, 4.0)
        layout_warning = count * diameter_mm > section_width_mm
        box_height = 78.0 if layout_warning else 60.0
        rebar_class = "rebar-warning" if layout_warning else "rebar"

        for center_x in _build_rebar_centers(section_x, drawing_width, count):
            section_zone_fragments.append(_circle(center_x, actual_y, radius, css_class=rebar_class))

        leader_mid_x = section_x + drawing_width + 18.0
        callout_mid_y = callout_top + 26.0
        right_zone_fragments.extend(
            [
                _polyline(
                    [
                        (section_x + drawing_width + 8.0, actual_y),
                        (leader_mid_x, actual_y),
                        (leader_mid_x, callout_mid_y),
                        (callout_x, callout_mid_y),
                    ],
                    css_class="callout-leader",
                ),
                _circle(section_x + drawing_width + 8.0, actual_y, 3.2, css_class="callout-anchor"),
                f'<g class="rebar-callout" data-role="rebar-callout" transform="translate({callout_x:.1f} {callout_top:.1f})">',
                _rect(0.0, 0.0, callout_width, box_height, css_class="callout-card", rx=12.0, ry=12.0),
                _text(16.0, 24.0, f"A{index}: {count} x {diameter_mm}, {row['steel_class']}", css_class="callout-title"),
                _text(16.0, 46.0, f"a{index} = {_fmt_mm(float(row['distance_mm']))}; z{index} = {_fmt_mm(z_mm)}", css_class="callout-meta"),
            ]
        )
        if layout_warning:
            right_zone_fragments.append(_text(16.0, 64.0, f"A{index}: n*d > b", css_class="layout-warning", data_role="layout-warning"))
        right_zone_fragments.append("</g>")

    top_rebar_row = min(rebar_rows, key=lambda row: float(row["z_mm"])) if rebar_rows else None
    bottom_rebar_row = max(rebar_rows, key=lambda row: float(row["z_mm"])) if rebar_rows else None
    if top_rebar_row is not None:
        top_z_mm = float(top_rebar_row["z_mm"])
        top_z_y = section_y + top_z_mm * scale
        left_zone_fragments.append(
            _vertical_dimension_lane(
                left_z1_lane_x,
                section_y,
                top_z_y,
                f"z1 = {_fmt_mm(top_z_mm)}",
                lane_role="dimension-lane-left-z1",
                line_role="rebar-depth-dimension",
            )
        )
    if bottom_rebar_row is not None:
        bottom_z_mm = float(bottom_rebar_row["z_mm"])
        bottom_z_y = section_y + bottom_z_mm * scale
        left_zone_fragments.append(
            _vertical_dimension_lane(
                left_z2_lane_x,
                section_y,
                bottom_z_y,
                f"z2 = {_fmt_mm(bottom_z_mm)}",
                lane_role="dimension-lane-left-z2",
                line_role="rebar-depth-dimension",
            )
        )

    fragments.extend(
        [
            '<g data-role="top-row-layout">',
            '<g data-role="left-dimension-zone">',
            *left_zone_fragments,
            "</g>",
            '<g data-role="section-zone">',
            *section_zone_fragments,
            "</g>",
            '<g data-role="right-detail-zone">',
            *right_zone_fragments,
            "</g>",
            "</g>",
        ]
    )

    for panel_index, (panel_title, panel_state) in enumerate(panel_entries):
        fragments.append(
            _build_form_panel(
                panel_title,
                panel_state,
                x=panel_x,
                y=panel_y_values[panel_index],
                width=panel_width,
                height=panel_height,
                section_height_mm=section_height_mm,
                layer_split_mm=top_layer_height_mm,
                concrete_stress_abs_max_mpa=concrete_stress_abs_max_mpa,
                steel_stress_abs_max_mpa=steel_stress_abs_max_mpa,
                strain_abs_max=strain_abs_max,
            )
        )

    fragments.append("</svg>")
    return "".join(fragments)
