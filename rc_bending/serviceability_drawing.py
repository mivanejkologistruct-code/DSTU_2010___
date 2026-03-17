from __future__ import annotations

from html import escape

from rc_bending.models import ServiceabilityReport
from rc_bending.serviceability import SUPPORT_SCHEME_LABELS

CANVAS_WIDTH = 960.0
CANVAS_HEIGHT = 340.0
BEAM_X1 = 72.0
BEAM_X2 = 578.0
BEAM_Y = 172.0
PANEL_X = 640.0
PANEL_WIDTH = 244.0


def _text(
    x: float,
    y: float,
    value: str,
    *,
    css_class: str = "",
    anchor: str = "start",
    fill: str = "",
) -> str:
    class_attr = f' class="{css_class}"' if css_class else ""
    fill_attr = f' fill="{fill}"' if fill else ""
    return f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}"{class_attr}{fill_attr}>{escape(value)}</text>'


def _line(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    css_class: str = "",
    role: str = "",
    marker_end: str = "",
    marker_start: str = "",
) -> str:
    class_attr = f' class="{css_class}"' if css_class else ""
    role_attr = f' data-role="{role}"' if role else ""
    marker_end_attr = f' marker-end="url(#{marker_end})"' if marker_end else ""
    marker_start_attr = f' marker-start="url(#{marker_start})"' if marker_start else ""
    return (
        f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"'
        f"{class_attr}{role_attr}{marker_end_attr}{marker_start_attr} />"
    )


def _rect(
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    css_class: str = "",
    role: str = "",
    rx: float = 0.0,
    fill: str = "",
) -> str:
    class_attr = f' class="{css_class}"' if css_class else ""
    role_attr = f' data-role="{role}"' if role else ""
    rx_attr = f' rx="{rx:.1f}"' if rx else ""
    fill_attr = f' fill="{fill}"' if fill else ""
    return (
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" height="{height:.1f}"'
        f"{class_attr}{role_attr}{rx_attr}{fill_attr} />"
    )


def _circle(x: float, y: float, radius: float, *, css_class: str = "") -> str:
    class_attr = f' class="{css_class}"' if css_class else ""
    return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}"{class_attr} />'


def _polygon(points: list[tuple[float, float]], *, css_class: str = "") -> str:
    class_attr = f' class="{css_class}"' if css_class else ""
    serialized = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    return f'<polygon points="{serialized}"{class_attr} />'


def _polyline(points: list[tuple[float, float]], *, css_class: str = "", role: str = "") -> str:
    class_attr = f' class="{css_class}"' if css_class else ""
    role_attr = f' data-role="{role}"' if role else ""
    serialized = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    return f'<polyline points="{serialized}"{class_attr}{role_attr} />'


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _dimension_line(x1: float, x2: float, y: float, label: str, *, role: str) -> str:
    mid_x = (x1 + x2) / 2.0
    return "".join(
        [
            _line(x1, BEAM_Y + 14.0, x1, y - 16.0, css_class="dimension-extension"),
            _line(x2, BEAM_Y + 14.0, x2, y - 16.0, css_class="dimension-extension"),
            _line(
                x1,
                y,
                x2,
                y,
                css_class="dimension-line",
                role=role,
                marker_start="dimension-arrow",
                marker_end="dimension-arrow",
            ),
            _rect(mid_x - 52.0, y - 24.0, 104.0, 22.0, css_class="dimension-chip", rx=11.0),
            _text(mid_x, y - 8.0, label, css_class="dimension-chip-text", anchor="middle"),
        ]
    )


def _draw_pin_support(x: float, *, role: str) -> str:
    return "".join(
        [
            f'<g data-role="{role}">',
            _polygon([(x, BEAM_Y), (x - 26.0, BEAM_Y + 36.0), (x + 26.0, BEAM_Y + 36.0)], css_class="support-shape"),
            _line(x - 42.0, BEAM_Y + 44.0, x + 42.0, BEAM_Y + 44.0, css_class="ground-line"),
            "</g>",
        ]
    )


def _draw_roller_support(x: float, *, role: str) -> str:
    return "".join(
        [
            f'<g data-role="{role}">',
            _polygon([(x, BEAM_Y), (x - 24.0, BEAM_Y + 28.0), (x + 24.0, BEAM_Y + 28.0)], css_class="support-shape"),
            _circle(x - 12.0, BEAM_Y + 35.0, 6.0, css_class="support-wheel"),
            _circle(x + 12.0, BEAM_Y + 35.0, 6.0, css_class="support-wheel"),
            _line(x - 40.0, BEAM_Y + 44.0, x + 40.0, BEAM_Y + 44.0, css_class="ground-line"),
            "</g>",
        ]
    )


def _draw_fixity(x: float) -> str:
    hatch_lines = "".join(
        _line(x - 22.0, BEAM_Y - 30.0 + offset, x, BEAM_Y - 48.0 + offset, css_class="fixity-hatch")
        for offset in range(0, 88, 12)
    )
    return "".join(
        [
            '<g data-role="serviceability-fixity">',
            _rect(x - 18.0, BEAM_Y - 50.0, 18.0, 88.0, css_class="fixity-block"),
            hatch_lines,
            "</g>",
        ]
    )


def _draw_distributed_load(x1: float, x2: float) -> str:
    arrow_count = 8
    spacing = (x2 - x1) / (arrow_count - 1)
    arrows = []
    for index in range(arrow_count):
        x = x1 + spacing * index
        arrows.append(_line(x, BEAM_Y - 48.0, x, BEAM_Y - 10.0, css_class="load-line", marker_end="load-arrow"))
    return "".join(
        [
            '<g data-role="serviceability-load-distributed">',
            _line(x1, BEAM_Y - 48.0, x2, BEAM_Y - 48.0, css_class="load-guide"),
            "".join(arrows),
            _text((x1 + x2) / 2.0, BEAM_Y - 58.0, "q", css_class="load-label", anchor="middle"),
            "</g>",
        ]
    )


def _draw_point_load(x: float, *, label: str = "P") -> str:
    return "".join(
        [
            '<g data-role="serviceability-load-point">',
            _line(x, BEAM_Y - 58.0, x, BEAM_Y - 10.0, css_class="load-line", marker_end="load-arrow"),
            _text(x, BEAM_Y - 68.0, label, css_class="load-label", anchor="middle"),
            "</g>",
        ]
    )


def _sample_deformed_axis(report: ServiceabilityReport, *, amplitude: float) -> list[tuple[float, float]]:
    scheme = report.input.support_scheme
    a_ratio = 0.25
    if report.input.a_mm is not None and report.input.span_mm > 0.0:
        a_ratio = _clamp(report.input.a_mm / report.input.span_mm, 0.08, 0.45)

    points: list[tuple[float, float]] = []
    for index in range(13):
        t = index / 12.0
        x = BEAM_X1 + (BEAM_X2 - BEAM_X1) * t
        if scheme.startswith("cantilever"):
            shape = t * t * (3.0 - 2.0 * t)
            if scheme == "cantilever_point_at_a":
                shape *= 0.88 + 0.12 * (1.0 if t >= a_ratio else max(a_ratio, 0.12))
        elif scheme == "simply_supported_center_point":
            shape = 1.0 - abs(2.0 * t - 1.0)
        elif scheme == "simply_supported_two_point_symmetric":
            left_peak = max(0.0, 1.0 - abs(t - a_ratio) / max(a_ratio, 0.12))
            right_peak = max(0.0, 1.0 - abs(t - (1.0 - a_ratio)) / max(a_ratio, 0.12))
            shape = min(1.0, 0.55 * (left_peak + right_peak))
        else:
            shape = 4.0 * t * (1.0 - t)
        points.append((x, BEAM_Y + 48.0 + amplitude * shape))
    return points


def _utilization_fill_width(ratio: float) -> float:
    return 182.0 * _clamp(ratio / 1.25, 0.0, 1.0)


def _utilization_color(ratio: float) -> str:
    if ratio <= 0.85:
        return "#2f7d4a"
    if ratio <= 1.0:
        return "#b5771f"
    return "#c44a3d"


def _draw_utilization_row(
    *,
    x: float,
    y: float,
    label: str,
    ratio: float,
    actual_text: str,
    limit_text: str,
    role: str,
) -> str:
    fill_width = _utilization_fill_width(ratio)
    color = _utilization_color(ratio)
    return "".join(
        [
            _text(x, y, label, css_class="utilization-label"),
            _rect(x, y + 10.0, 182.0, 14.0, css_class="utilization-track", rx=7.0),
            _rect(x, y + 10.0, fill_width, 16.0, role=role, rx=8.0, fill=color),
            _text(
                x + min(fill_width + 8.0, 182.0),
                y + 22.0,
                f"{ratio:.2f}",
                css_class="utilization-ratio",
                fill=color,
            ),
            _text(x, y + 44.0, f"{actual_text} / {limit_text}", css_class="utilization-meta"),
        ]
    )


def _load_positions(report: ServiceabilityReport) -> list[float]:
    scheme = report.input.support_scheme
    span_mm = max(report.input.span_mm, 1.0)
    beam_length = BEAM_X2 - BEAM_X1
    if scheme == "simply_supported_center_point":
        return [BEAM_X1 + beam_length / 2.0]
    if scheme == "cantilever_tip_point":
        return [BEAM_X2]
    if scheme == "cantilever_point_at_a":
        a_mm = report.input.a_mm if report.input.a_mm is not None else span_mm * 0.3
        return [BEAM_X1 + beam_length * _clamp(a_mm / span_mm, 0.08, 0.95)]
    if scheme == "simply_supported_two_point_symmetric":
        a_mm = report.input.a_mm if report.input.a_mm is not None else span_mm * 0.25
        ratio = _clamp(a_mm / span_mm, 0.08, 0.45)
        return [BEAM_X1 + beam_length * ratio, BEAM_X2 - beam_length * ratio]
    return []


def build_serviceability_scheme_svg(report: ServiceabilityReport) -> str:
    scheme = report.input.support_scheme
    scheme_label = SUPPORT_SCHEME_LABELS.get(scheme, scheme)
    span_label = f"l = {report.input.span_mm:.1f} мм"
    deflection_ratio = (
        report.deflection.deflection_mm / report.deflection.limit.limit_mm
        if report.deflection.limit.limit_mm > 0.0
        else 0.0
    )
    crack_ratio = (
        report.crack_width.w_k_mm / report.crack_width.w_limit_mm
        if report.crack_width.w_limit_mm > 0.0
        else 0.0
    )
    deformed_scale = _clamp(deflection_ratio, 0.0, 1.25)
    deformed_axis = _sample_deformed_axis(report, amplitude=34.0 * deformed_scale)
    load_positions = _load_positions(report)

    fragments = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {CANVAS_WIDTH:.0f} {CANVAS_HEIGHT:.0f}" data-role="serviceability-scheme-svg">',
        "<defs>",
        '<marker id="load-arrow" markerWidth="12" markerHeight="12" refX="6" refY="6" orient="auto" markerUnits="strokeWidth">',
        '<path d="M 0 0 L 12 6 L 0 12 z" fill="#3f5368" />',
        "</marker>",
        '<marker id="dimension-arrow" markerWidth="10" markerHeight="10" refX="5" refY="5" orient="auto" markerUnits="strokeWidth">',
        '<path d="M 0 5 L 10 0 L 10 10 z" fill="#6b7c8d" />',
        "</marker>",
        "<style>",
        ".scheme-title{fill:#10253d;font:700 20px 'Segoe UI',sans-serif;}",
        ".scheme-subtitle{fill:#617689;font:600 12px 'Segoe UI',sans-serif;letter-spacing:.04em;text-transform:uppercase;}",
        ".scheme-note{fill:#5d7389;font:500 12px 'Segoe UI',sans-serif;}",
        ".beam-line{stroke:#1f3448;stroke-width:6;stroke-linecap:round;}",
        ".support-shape{fill:#d5dee8;stroke:#385169;stroke-width:2;}",
        ".support-wheel{fill:#ffffff;stroke:#385169;stroke-width:2;}",
        ".ground-line{stroke:#51677d;stroke-width:2.2;stroke-linecap:round;}",
        ".fixity-block{fill:#d8e3ed;stroke:#3b546b;stroke-width:1.6;}",
        ".fixity-hatch{stroke:#7991a7;stroke-width:1.4;}",
        ".load-guide{stroke:#6f7f8f;stroke-width:2;}",
        ".load-line{stroke:#3f5368;stroke-width:2.4;}",
        ".load-label{fill:#8c5a3a;font:700 14px 'Segoe UI',sans-serif;}",
        ".dimension-line{stroke:#6b7c8d;stroke-width:1.8;}",
        ".dimension-extension{stroke:#c0ccd7;stroke-width:1.5;}",
        ".dimension-chip{fill:#ffffff;stroke:#d5dfe8;stroke-width:1.2;}",
        ".dimension-chip-text{fill:#30465b;font:600 11px 'Segoe UI',sans-serif;}",
        ".deformed-axis{fill:none;stroke:#b65d3c;stroke-width:3;stroke-linecap:round;stroke-linejoin:round;}",
        ".deformed-baseline{stroke:#d7e0e8;stroke-width:2;stroke-dasharray:7 6;}",
        ".panel-shell{fill:#f9fbfd;stroke:#d8e1eb;stroke-width:1.4;}",
        ".panel-title{fill:#10253d;font:700 15px 'Segoe UI',sans-serif;}",
        ".utilization-label{fill:#495f75;font:600 12px 'Segoe UI',sans-serif;}",
        ".utilization-track{fill:#e7edf3;}",
        ".utilization-ratio{font:700 12px 'Segoe UI',sans-serif;}",
        ".utilization-meta{fill:#60758b;font:500 10px 'Segoe UI',sans-serif;}",
        ".status-chip{fill:#ffffff;stroke:#d5e0ea;stroke-width:1.2;}",
        ".status-label{fill:#6b7f92;font:600 11px 'Segoe UI',sans-serif;text-transform:uppercase;letter-spacing:.05em;}",
        ".status-value{fill:#0f172a;font:700 13px 'Segoe UI',sans-serif;}",
        "</style>",
        "</defs>",
        _text(40.0, 40.0, "Схема II ГГС", css_class="scheme-subtitle"),
        _text(40.0, 68.0, scheme_label, css_class="scheme-title"),
        _line(BEAM_X1, BEAM_Y, BEAM_X2, BEAM_Y, css_class="beam-line", role="serviceability-beam"),
    ]

    if scheme.startswith("cantilever"):
        fragments.append(_draw_fixity(BEAM_X1))
    else:
        fragments.append(_draw_pin_support(BEAM_X1, role="serviceability-support-left"))
        fragments.append(_draw_roller_support(BEAM_X2, role="serviceability-support-right"))

    if scheme.endswith("uniform"):
        fragments.append(_draw_distributed_load(BEAM_X1 + 28.0, BEAM_X2 - 28.0))
    else:
        fragments.extend(_draw_point_load(x) for x in load_positions)

    fragments.append(_dimension_line(BEAM_X1, BEAM_X2, 284.0, span_label, role="serviceability-dimension-span"))
    if scheme in {"cantilever_point_at_a", "simply_supported_two_point_symmetric"} and load_positions:
        fragments.append(
            _dimension_line(
                BEAM_X1,
                load_positions[0],
                112.0,
                f"a = {report.input.a_mm:.1f} мм",
                role="serviceability-dimension-a",
            )
        )

    fragments.extend(
        [
            _line(BEAM_X1, BEAM_Y + 48.0, BEAM_X2, BEAM_Y + 48.0, css_class="deformed-baseline"),
            _polyline(deformed_axis, css_class="deformed-axis", role="serviceability-deformed-axis"),
            _text(
                BEAM_X1,
                308.0,
                "Умовна деформована вісь показує масштаб роботи елемента, а не точний розподіл w(x).",
                css_class="scheme-note",
            ),
            _rect(PANEL_X, 78.0, PANEL_WIDTH, 196.0, css_class="panel-shell", rx=20.0),
            _text(PANEL_X + 18.0, 106.0, "Використання лімітів", css_class="panel-title"),
            _draw_utilization_row(
                x=PANEL_X + 18.0,
                y=130.0,
                label="Прогин f / f_u",
                ratio=deflection_ratio,
                actual_text=f"f = {report.deflection.deflection_mm:.2f} мм",
                limit_text=f"f_u = {report.deflection.limit.limit_mm:.2f} мм",
                role="serviceability-utilization-deflection",
            ),
            _draw_utilization_row(
                x=PANEL_X + 18.0,
                y=194.0,
                label="Тріщини w_k / w_lim",
                ratio=crack_ratio,
                actual_text=f"w_k = {report.crack_width.w_k_mm:.3f} мм",
                limit_text=f"w_lim = {report.crack_width.w_limit_mm:.3f} мм",
                role="serviceability-utilization-crack",
            ),
            _rect(PANEL_X + 18.0, 238.0, 106.0, 26.0, css_class="status-chip", rx=13.0),
            _text(PANEL_X + 34.0, 255.0, "κ_eff", css_class="status-label"),
            _text(
                PANEL_X + 126.0,
                256.0,
                f"{report.deflection.effective_curvature_1_per_m:.6f} 1/м",
                css_class="status-value",
                anchor="start",
            ),
        ]
    )

    fragments.append("</svg>")
    return "".join(fragments)
