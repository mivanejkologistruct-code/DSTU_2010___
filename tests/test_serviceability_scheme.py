from __future__ import annotations

import importlib
import re

import pytest
from streamlit.testing.v1 import AppTest

from rc_bending.materials import load_material_catalog
from rc_bending.models import ChartLimitAnnotation
from rc_bending.serviceability import build_serviceability_report
from rc_bending.solver import solve_bending_capacity
from rc_bending.ui_helpers import build_section_input_from_draft, default_draft_inputs


def _make_serviceability_report(**serviceability_updates):
    catalog = load_material_catalog()
    draft = default_draft_inputs()
    draft["serviceability"].update(serviceability_updates)
    section = build_section_input_from_draft(draft, catalog)
    result = solve_bending_capacity(section, catalog, outer_steps=int(draft["outer_steps"]))
    selected_point = result.curve_points[-1]
    report = build_serviceability_report(section, draft, selected_point, catalog)
    return draft, result, report


def _load_serviceability_scheme_renderer():
    try:
        module = importlib.import_module("rc_bending.serviceability_drawing")
    except ModuleNotFoundError as error:
        pytest.fail(f"Expected rc_bending.serviceability_drawing module: {error}")
    renderer = getattr(module, "build_serviceability_scheme_svg", None)
    assert callable(renderer), "Expected build_serviceability_scheme_svg(report) renderer."
    return renderer


def _load_showcase_builder():
    import streamlit_app

    builder = getattr(streamlit_app, "_build_serviceability_scheme_showcase_html", None)
    assert callable(builder), "Expected _build_serviceability_scheme_showcase_html helper in streamlit_app.py."
    return builder


def _find_markdown_containing(app: AppTest, substring: str):
    for markdown in app.markdown:
        if substring in markdown.value:
            return markdown.value
    raise AssertionError(f"Markdown containing {substring!r} was not found.")


def _find_tab(app: AppTest, label: str):
    for tab in app.tabs:
        if getattr(tab, "label", None) == label:
            return tab
    raise AssertionError(f"Tab with label {label!r} was not found.")


def _block_and_child_index_with_markdown(app: AppTest, substring: str) -> tuple[int, int]:
    for index, element in app.main.children.items():
        if type(element).__name__ != "Block":
            continue
        for child_index, child in element.children.items():
            if type(child).__name__ == "Markdown" and substring in child.value:
                return index, child_index
    raise AssertionError(f"Block markdown containing {substring!r} was not found.")


def _block_and_child_index_with_subheader(app: AppTest, title: str) -> tuple[int, int]:
    for index, element in app.main.children.items():
        if type(element).__name__ != "Block":
            continue
        for child_index, child in element.children.items():
            if getattr(child, "type", None) == "subheader" and getattr(child, "value", None) == title:
                return index, child_index
    raise AssertionError(f"Block subheader {title!r} was not found.")


def _block_and_child_index_with_markdown_in_node(node, substring: str) -> tuple[int, int]:
    for index, element in node.children.items():
        if type(element).__name__ != "Block":
            continue
        for child_index, child in element.children.items():
            if type(child).__name__ == "Markdown" and substring in child.value:
                return index, child_index
    raise AssertionError(f"Block markdown containing {substring!r} was not found in node.")


def _block_and_child_index_with_subheader_in_node(node, title: str) -> tuple[int, int]:
    for index, element in node.children.items():
        if type(element).__name__ != "Block":
            continue
        for child_index, child in element.children.items():
            if getattr(child, "type", None) == "subheader" and getattr(child, "value", None) == title:
                return index, child_index
    raise AssertionError(f"Block subheader {title!r} was not found in node.")


def _find_widget_by_label(elements, label: str):
    for element in elements:
        if getattr(element, "label", None) == label:
            return element
    raise AssertionError(f"Widget with label {label!r} was not found.")


def _extract_viewbox(svg: str) -> tuple[float, float]:
    match = re.search(r'viewBox="0 0 ([0-9.]+) ([0-9.]+)"', svg)
    assert match is not None
    return float(match.group(1)), float(match.group(2))


def test_build_serviceability_scheme_svg_renders_default_simply_supported_scheme():
    _, _, report = _make_serviceability_report()

    svg = _load_serviceability_scheme_renderer()(report)

    assert "<svg" in svg
    assert 'data-role="serviceability-scheme-svg"' in svg
    assert 'data-role="serviceability-support-left"' in svg
    assert 'data-role="serviceability-support-right"' in svg
    assert 'data-role="serviceability-load-distributed"' in svg
    assert 'data-role="serviceability-dimension-span"' in svg
    assert 'data-role="serviceability-deformed-axis"' in svg
    assert 'data-role="serviceability-utilization-deflection"' in svg
    assert 'data-role="serviceability-utilization-crack"' in svg
    assert "Балка на двох опорах" in svg
    assert "l = 6000.0 мм" in svg
    assert 'data-role="serviceability-dimension-a"' not in svg


def test_build_serviceability_scheme_svg_uses_compact_canvas_and_header():
    _, _, report = _make_serviceability_report()

    svg = _load_serviceability_scheme_renderer()(report)
    viewbox_width, viewbox_height = _extract_viewbox(svg)

    assert viewbox_width <= 980.0
    assert viewbox_height <= 360.0
    assert "Активна точка:" not in svg


def test_build_serviceability_scheme_svg_renders_cantilever_point_load_with_parameter_a():
    _, _, report = _make_serviceability_report(
        support_scheme="cantilever_point_at_a",
        span_mm=4500.0,
        a_mm=1500.0,
    )

    svg = _load_serviceability_scheme_renderer()(report)

    assert 'data-role="serviceability-fixity"' in svg
    assert svg.count('data-role="serviceability-load-point"') == 1
    assert 'data-role="serviceability-dimension-a"' in svg
    assert "a = 1500.0 мм" in svg
    assert 'data-role="serviceability-support-right"' not in svg


def test_build_serviceability_scheme_svg_renders_two_symmetric_point_loads():
    _, _, report = _make_serviceability_report(
        support_scheme="simply_supported_two_point_symmetric",
        span_mm=6000.0,
        a_mm=1800.0,
    )

    svg = _load_serviceability_scheme_renderer()(report)

    assert svg.count('data-role="serviceability-load-point"') == 2
    assert 'data-role="serviceability-support-left"' in svg
    assert 'data-role="serviceability-support-right"' in svg
    assert 'data-role="serviceability-dimension-a"' in svg


def test_serviceability_scheme_showcase_html_renders_gap_chip_only_for_partition_profile():
    _, _, partition_report = _make_serviceability_report(
        deflection_limit_profile="partition_gap",
        available_gap_mm=18.0,
        phi_creep=2.1,
    )
    _, _, default_report = _make_serviceability_report()

    renderer = _load_serviceability_scheme_renderer()
    showcase_builder = _load_showcase_builder()

    partition_html = showcase_builder(renderer(partition_report), partition_report, note="Перевірка")
    default_html = showcase_builder(renderer(default_report), default_report, note="Перевірка")

    assert 'data-role="serviceability-scheme-showcase"' in partition_html
    assert "Допустимий зазор" in partition_html
    assert "18.0 мм" in partition_html
    assert "φ_creep" in partition_html
    assert "Допустимий зазор" not in default_html


def test_custom_css_uses_compact_serviceability_scheme_scaling():
    import streamlit_app

    css = streamlit_app._build_custom_css()

    assert ".serviceability-scheme-stage svg" in css
    assert "width: min(100%, 980px);" in css
    assert "min-width: 680px;" in css


def test_custom_css_keeps_serviceability_override_after_generic_cad_rule():
    import streamlit_app

    css = streamlit_app._build_custom_css()
    generic_pos = css.rfind(".cad-stage svg {")
    serviceability_pos = css.rfind(".serviceability-scheme-stage svg {")

    assert generic_pos != -1
    assert serviceability_pos != -1
    assert serviceability_pos > generic_pos


def test_custom_css_uses_tighter_mobile_serviceability_scaling():
    import streamlit_app

    css = streamlit_app._build_custom_css()

    assert "@media (max-width: 640px)" in css
    assert ".serviceability-scheme-stage svg" in css
    assert "min-width: 440px;" in css
    assert ".serviceability-scheme-shell.cad-shell" in css
    assert "padding: 0.75rem;" in css


def test_chart_callout_texts_use_compact_labels_for_readability():
    import streamlit_app

    in_range = ChartLimitAnnotation(label="εmax", target_strain=257.0, moment_kNm=11.01, within_chart_range=True)
    out_of_range = ChartLimitAnnotation(label="ε_cu1,ck", target_strain=263.0, moment_kNm=None, within_chart_range=False)
    deflection = ChartLimitAnnotation(label="f_u", target_strain=30.0, moment_kNm=2.51, within_chart_range=True)

    assert streamlit_app._build_annotation_callout_text(in_range) == "εmax"
    assert streamlit_app._build_annotation_callout_text(out_of_range) == "ε_cu1,ck"
    assert streamlit_app._build_deflection_annotation_callout_text(deflection) == "f_u"


def test_streamlit_app_places_serviceability_scheme_before_mf_chart():
    app = AppTest.from_file("streamlit_app.py")

    app.run(timeout=10)

    serviceability_tab = _find_tab(app, "2. II ГГС")
    scheme_index, scheme_child_index = _block_and_child_index_with_markdown_in_node(serviceability_tab, 'data-role="serviceability-scheme-showcase"')
    chart_index, chart_child_index = _block_and_child_index_with_subheader_in_node(serviceability_tab, "Діаграма M-f")

    assert len(app.exception) == 0
    assert scheme_index == chart_index
    assert scheme_child_index < chart_child_index


def test_streamlit_app_serviceability_scheme_uses_active_inputs_until_refresh():
    app = AppTest.from_file("streamlit_app.py")

    app.run(timeout=10)

    baseline_scheme = _find_markdown_containing(app, 'data-role="serviceability-scheme-showcase"')

    _find_widget_by_label(app.number_input, "Розрахунковий проліт l, мм").set_value(9000.0)
    app.run(timeout=10)
    dirty_scheme = _find_markdown_containing(app, 'data-role="serviceability-scheme-showcase"')

    _find_widget_by_label(app.button, "Оновити перевірку").click()
    app.run(timeout=10)
    updated_scheme = _find_markdown_containing(app, 'data-role="serviceability-scheme-showcase"')

    assert "6000.0 мм" in baseline_scheme
    assert "6000.0 мм" in dirty_scheme
    assert "9000.0 мм" not in dirty_scheme
    assert "9000.0 мм" in updated_scheme


def test_streamlit_app_serviceability_scheme_shows_partition_gap_after_refresh():
    app = AppTest.from_file("streamlit_app.py")

    app.run(timeout=10)
    _find_widget_by_label(app.selectbox, "Нормативний профіль обмеження прогину").select(
        "Конструктивні при наявності перегородок"
    )
    app.run(timeout=10)
    _find_widget_by_label(app.number_input, "Допустимий зазор, мм").set_value(18.0)
    _find_widget_by_label(app.button, "Оновити перевірку").click()
    app.run(timeout=10)

    scheme = _find_markdown_containing(app, 'data-role="serviceability-scheme-showcase"')

    assert len(app.exception) == 0
    assert "Допустимий зазор" in scheme
    assert "18.0 мм" in scheme
