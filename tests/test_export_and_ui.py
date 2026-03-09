from pathlib import Path

from openpyxl import load_workbook
import pytest
from streamlit.testing.v1 import AppTest

from rc_bending.export import build_results_workbook_bytes
from rc_bending.materials import load_material_catalog
from rc_bending.models import ConcreteLayerInput, RebarLayerInput, SectionInput
from rc_bending.solver import build_layer_force_table, build_strain_profile_for_point, solve_bending_capacity
from rc_bending.ui_helpers import (
    add_rebar_layer,
    build_section_input_from_draft,
    default_draft_inputs,
    remove_rebar_layer,
    validate_draft_inputs,
)


def make_case() -> SectionInput:
    return SectionInput(
        section_height_mm=500.0,
        concrete_layers=(
            ConcreteLayerInput(width_mm=500.0, height_mm=200.0, concrete_class="C30/35"),
            ConcreteLayerInput(width_mm=500.0, height_mm=300.0, concrete_class="C20/25"),
        ),
        rebar_layers=(
            RebarLayerInput(z_mm=30.0, area_mm2=7 * 615.8, steel_class="A400C"),
            RebarLayerInput(z_mm=470.0, area_mm2=7 * 615.8, steel_class="A400C"),
        ),
    )


def _find_widget_by_label(elements, label: str):
    for element in elements:
        if getattr(element, "label", None) == label:
            return element
    raise AssertionError(f"Widget with label '{label}' was not found.")


def _find_metric(app: AppTest, label: str):
    return _find_widget_by_label(app.metric, label)


def _has_metric(app: AppTest, label: str) -> bool:
    return any(getattr(metric, "label", None) == label for metric in app.metric)


def _find_dataframe(app: AppTest, columns: list[str]):
    for dataframe in app.dataframe:
        if list(dataframe.value.columns) == columns:
            return dataframe.value
    raise AssertionError(f"DataFrame with columns {columns!r} was not found.")


def _has_dataframe(app: AppTest, columns: list[str]) -> bool:
    return any(list(dataframe.value.columns) == columns for dataframe in app.dataframe)


def _find_markdown_containing(app: AppTest, substring: str):
    for markdown in app.markdown:
        if substring in markdown.value:
            return markdown.value
    raise AssertionError(f"Markdown containing {substring!r} was not found.")


def _has_markdown_containing(app: AppTest, substring: str) -> bool:
    return any(substring in markdown.value for markdown in app.markdown)


def test_export_workbook_contains_required_sheets_and_charts(tmp_path):
    section = make_case()
    catalog = load_material_catalog()
    result = solve_bending_capacity(section, catalog)

    workbook_bytes = build_results_workbook_bytes(section, catalog, result)
    output_path = tmp_path / "result.xlsx"
    output_path.write_bytes(workbook_bytes)
    workbook = load_workbook(output_path)

    assert workbook.sheetnames == [
        "Inputs",
        "Materials",
        "MomentCurvature",
        "ConcreteStrainProfile",
        "IntermediateIterations",
        "LayerForces",
    ]
    assert workbook["MomentCurvature"]["A2"].value == 1
    assert workbook["MomentCurvature"]["D2"].value == 0
    assert workbook["MomentCurvature"]["D3"].value > 0
    assert workbook["ConcreteStrainProfile"]["A2"].value == 0
    assert workbook["IntermediateIterations"].max_row > 2
    assert workbook["LayerForces"].max_row > 2
    assert len(workbook["MomentCurvature"]._charts) == 1
    assert len(workbook["ConcreteStrainProfile"]._charts) == 1


def test_export_can_follow_a_selected_curve_point(tmp_path):
    section = make_case()
    catalog = load_material_catalog()
    result = solve_bending_capacity(section, catalog)
    selected_point = result.curve_points[0]
    expected_profile = build_strain_profile_for_point(section, selected_point)

    workbook_bytes = build_results_workbook_bytes(section, catalog, result, selected_point=selected_point)
    output_path = tmp_path / "selected_result.xlsx"
    output_path.write_bytes(workbook_bytes)
    workbook = load_workbook(output_path)

    assert workbook["ConcreteStrainProfile"]["B2"].value == expected_profile[0].strain


def test_ui_helpers_can_add_and_remove_rebar_rows():
    rows = [
        {"id": "rebar_1", "face": "top", "distance_mm": 30.0, "bar_count": 7, "diameter_mm": 28, "steel_class": "A400C"},
        {"id": "rebar_2", "face": "bottom", "distance_mm": 30.0, "bar_count": 7, "diameter_mm": 28, "steel_class": "A400C"},
    ]

    rows = add_rebar_layer(rows)
    assert len(rows) == 3
    assert rows[-1]["bar_count"] == 1
    assert rows[-1]["face"] == "Верхня"

    rows = remove_rebar_layer(rows, 1)
    assert len(rows) == 2
    assert rows[1]["id"] != "rebar_2"


def test_current_point_cards_html_contains_named_value_slots():
    from streamlit_app import _build_current_point_cards_html

    catalog = load_material_catalog()
    result = solve_bending_capacity(make_case(), catalog)

    html = _build_current_point_cards_html(result.peak_point)

    assert 'data-role="point-chip-grid"' in html
    assert html.count('data-role="point-chip"') == 5
    assert 'data-role="point-value-step"' in html
    assert 'data-role="point-value-moment"' in html
    assert 'data-role="point-value-curvature"' in html
    assert 'data-role="point-value-neutral-axis"' in html
    assert 'data-role="point-value-residual"' in html


def test_custom_css_uses_wider_content_width_for_drawing_readability():
    from streamlit_app import _build_custom_css

    css = _build_custom_css()

    assert "max-width: 1480px" in css


def test_force_cards_html_contains_one_card_per_layer():
    from streamlit_app import _build_force_cards_html

    catalog = load_material_catalog()
    section = make_case()
    result = solve_bending_capacity(section, catalog)
    layer_force_rows = build_layer_force_table(section, catalog, result.peak_point)

    html = _build_force_cards_html(layer_force_rows)

    assert 'data-role="force-card-grid"' in html
    assert html.count('data-role="force-card"') == len(layer_force_rows)
    assert "B1" in html
    assert "A2" in html
    assert "N, кН" in html
    assert "σ, МПа" in html


def test_drawing_showcase_html_wraps_svg_with_summary_chips():
    from streamlit_app import _build_drawing_showcase_html
    from rc_bending.section_drawing import build_section_drawing_svg
    from rc_bending.ui_helpers import default_draft_inputs, derive_draft_geometry

    catalog = load_material_catalog()
    draft = default_draft_inputs()
    derived = derive_draft_geometry(draft)
    section = build_section_input_from_draft(draft, catalog)
    result = solve_bending_capacity(section, catalog)

    html = _build_drawing_showcase_html(
        derived,
        build_section_drawing_svg(derived, selected_point=result.peak_point),
        selected_point=result.peak_point,
        note="Тестова примітка.",
    )

    assert 'data-role="drawing-showcase"' in html
    assert 'data-role="drawing-showcase-chip"' in html
    assert "Переріз та епюри форм рівноваги" in html
    assert "Тестова примітка." in html
    assert "120.0 мм" in html


def test_author_cards_html_renders_profiles():
    from streamlit_app import _build_hero_banner_html

    html = _build_hero_banner_html()

    assert 'data-role="hero-author-list"' in html
    assert html.count('data-role="hero-author-item"') == 2
    assert "Іванейко М.М." in html
    assert "Іванейко В.М." in html
    assert "Автор проєкту." in html


def test_draft_validation_requires_exactly_two_rebar_layers():
    catalog = load_material_catalog()
    one_layer_draft = default_draft_inputs()
    one_layer_draft["rebar_layers"] = one_layer_draft["rebar_layers"][:1]

    three_layer_draft = default_draft_inputs()
    three_layer_draft["rebar_layers"] = add_rebar_layer(list(three_layer_draft["rebar_layers"]))

    one_layer_errors = validate_draft_inputs(one_layer_draft, catalog)
    three_layer_errors = validate_draft_inputs(three_layer_draft, catalog)

    assert any("Рівно два шари арматури" in error for error in one_layer_errors)
    assert any("Рівно два шари арматури" in error for error in three_layer_errors)


def test_build_section_input_from_draft_rejects_non_normative_rebar_count():
    catalog = load_material_catalog()
    draft = default_draft_inputs()
    draft["rebar_layers"] = add_rebar_layer(list(draft["rebar_layers"]))

    with pytest.raises(ValueError, match="Exactly two rebar layers"):
        build_section_input_from_draft(draft, catalog)


def test_concrete_and_rebar_chart_data_use_1e5_strain_scale():
    from streamlit_app import (
        _build_concrete_moment_strain_df,
        _build_concrete_strain_chart_df,
        _build_rebar_moment_strain_df,
        _pick_extreme_rebar_layers,
    )

    catalog = load_material_catalog()
    section = make_case()
    result = solve_bending_capacity(section, catalog)
    top_rebar, bottom_rebar = _pick_extreme_rebar_layers(section)

    concrete_moment_df = _build_concrete_moment_strain_df(result)
    concrete_df = _build_concrete_strain_chart_df(build_strain_profile_for_point(section, result.peak_point))
    top_df = _build_rebar_moment_strain_df(section, result, rebar_index=top_rebar[0])
    bottom_df = _build_rebar_moment_strain_df(section, result, rebar_index=bottom_rebar[0])

    first_point = result.curve_points[0]
    top_expected = (
        first_point.top_strain
        + (first_point.bottom_strain - first_point.top_strain) * top_rebar[1].z_mm / section.section_height_mm
    ) * 100000.0
    bottom_expected = (
        first_point.top_strain
        + (first_point.bottom_strain - first_point.top_strain) * bottom_rebar[1].z_mm / section.section_height_mm
    ) * 100000.0

    assert list(concrete_moment_df.columns) == ["Крок", "M, кН·м", "ε_c,top, 10^-5"]
    assert list(concrete_df.columns) == ["z, мм", "ε_c, 10^-5"]
    assert list(top_df.columns) == ["Крок", "M, кН·м", "ε_s, 10^-5"]
    assert list(bottom_df.columns) == ["Крок", "M, кН·м", "ε_s, 10^-5"]
    assert concrete_moment_df.iloc[0]["ε_c,top, 10^-5"] == pytest.approx(first_point.top_strain * 100000.0)
    assert concrete_df.iloc[0]["ε_c, 10^-5"] == pytest.approx(result.peak_point.top_strain * 100000.0)
    assert top_df.iloc[0]["ε_s, 10^-5"] == pytest.approx(top_expected)
    assert bottom_df.iloc[0]["ε_s, 10^-5"] == pytest.approx(bottom_expected)


def test_analytics_summary_table_uses_curve_and_extreme_rebar_layers():
    from streamlit_app import _build_analytics_summary_df

    catalog = load_material_catalog()
    section = make_case()
    result = solve_bending_capacity(section, catalog)

    summary_df = _build_analytics_summary_df(section, result)
    first_point = result.curve_points[0]
    top_expected = first_point.top_strain + (
        (first_point.bottom_strain - first_point.top_strain) * section.rebar_layers[0].z_mm / section.section_height_mm
    )
    bottom_expected = first_point.top_strain + (
        (first_point.bottom_strain - first_point.top_strain) * section.rebar_layers[1].z_mm / section.section_height_mm
    )

    assert list(summary_df.columns) == [
        "Крок",
        "M, кН·м",
        "κ, 1/м",
        "ε_c,top, 10^-5",
        "ε_s,top, 10^-5",
        "ε_s,bot, 10^-5",
    ]
    assert len(summary_df) == len(result.curve_points)
    assert summary_df.iloc[0]["Крок"] == first_point.step_index
    assert summary_df.iloc[0]["M, кН·м"] == pytest.approx(first_point.moment_kNm)
    assert summary_df.iloc[0]["κ, 1/м"] == pytest.approx(first_point.curvature_1_per_m)
    assert summary_df.iloc[0]["ε_c,top, 10^-5"] == pytest.approx(first_point.top_strain * 100000.0)
    assert summary_df.iloc[0]["ε_s,top, 10^-5"] == pytest.approx(top_expected * 100000.0)
    assert summary_df.iloc[0]["ε_s,bot, 10^-5"] == pytest.approx(bottom_expected * 100000.0)


def test_draft_validation_requires_outer_steps_in_supported_range():
    catalog = load_material_catalog()
    too_small = default_draft_inputs()
    too_small["outer_steps"] = 1

    too_large = default_draft_inputs()
    too_large["outer_steps"] = 201

    not_integer = default_draft_inputs()
    not_integer["outer_steps"] = 12.5

    too_small_errors = validate_draft_inputs(too_small, catalog)
    too_large_errors = validate_draft_inputs(too_large, catalog)
    not_integer_errors = validate_draft_inputs(not_integer, catalog)

    assert any("Кількість кроків" in error for error in too_small_errors)
    assert any("Кількість кроків" in error for error in too_large_errors)
    assert any("Кількість кроків" in error for error in not_integer_errors)


def test_streamlit_app_renders_without_exception():
    app_path = Path("streamlit_app.py")
    assert app_path.exists(), "streamlit_app.py must exist"

    app = AppTest.from_file(str(app_path))
    app.run(timeout=10)

    assert len(app.exception) == 0
    hero = _find_markdown_containing(app, 'data-role="hero-banner"')
    assert "Розрахунок згину залізобетонного перерізу" in hero
    assert "ДСТУ / ДБН" in hero
    assert "Двошаровий бетон" in hero
    assert "Експорт в Excel" in hero
    assert "Верифікація результатів" in hero
    assert _find_widget_by_label(app.number_input, "Висота перерізу h, мм").value == 120.0
    assert _find_widget_by_label(app.number_input, "Ширина перерізу b, мм").value == 500.0
    assert _find_widget_by_label(app.number_input, "Кількість кроків розрахунку").value == 12
    assert all(getattr(number_input, "label", None) != "Розрахунковий проліт L, мм" for number_input in app.number_input)
    assert _find_widget_by_label(app.button, "Перерахувати").label == "Перерахувати"
    assert _find_metric(app, "Несуча здатність M_Rd, кН·м").label == "Несуча здатність M_Rd, кН·м"
    assert _find_metric(app, "Кривизна κ_peak, 1/м").label == "Кривизна κ_peak, 1/м"
    assert not _has_metric(app, "Нев'язка ΣN, кН")
    assert not any(getattr(subheader, "value", None) == "Діаграма M-f" for subheader in app.subheader)
    assert not any(getattr(button, "label", None) == "Додати шар арматури" for button in app.button)
    assert not any(getattr(button, "label", None) == "Видалити" for button in app.button)
    assert any(getattr(subheader, "value", None) == "Діаграма M-κ" for subheader in app.subheader)
    assert any(getattr(subheader, "value", None) == "Момент-деформація бетону" for subheader in app.subheader)
    assert any(getattr(subheader, "value", None) == "Момент-деформація верхньої арматури" for subheader in app.subheader)
    assert any(getattr(subheader, "value", None) == "Момент-деформація нижньої арматури" for subheader in app.subheader)
    assert not any(getattr(subheader, "value", None) == "Графік деформацій бетону" for subheader in app.subheader)
    assert not any(getattr(subheader, "value", None) == "Проміжні результати" for subheader in app.subheader)
    assert not any(getattr(subheader, "value", None) == "Зусилля в шарах для обраної точки" for subheader in app.subheader)
    point_panel = _find_markdown_containing(app, 'data-role="point-chip-grid"')
    force_panel = _find_markdown_containing(app, 'data-role="force-card-grid"')
    assert 'data-role="point-value-step"' in point_panel
    assert 'data-role="point-value-moment"' in point_panel
    assert 'data-role="point-value-curvature"' in point_panel
    assert 'data-role="point-value-neutral-axis"' in point_panel
    assert 'data-role="point-value-residual"' in point_panel
    assert 'data-role="force-card"' in force_panel
    concrete_preview = _find_dataframe(app, ["Шар", "b, мм", "h, мм", "Клас", "Статус"])
    rebar_preview = _find_dataframe(app, ["Шар", "Грань", "a, мм", "z, мм", "n, шт.", "d, мм", "Клас", "Статус"])
    assert concrete_preview.iloc[0]["h, мм"] == 60.0
    assert concrete_preview.iloc[1]["Клас"] == "C40/50"
    assert rebar_preview.iloc[0]["Клас"] == "A500C"
    assert rebar_preview.iloc[0]["n, шт."] == 4
    assert rebar_preview.iloc[0]["d, мм"] == 8
    assert rebar_preview.iloc[1]["z, мм"] == 100.0
    summary_table = _find_dataframe(app, [
        "Крок",
        "M, кН·м",
        "κ, 1/м",
        "ε_c,top, 10^-5",
        "ε_s,top, 10^-5",
        "ε_s,bot, 10^-5",
    ])
    assert list(summary_table.columns) == [
        "Крок",
        "M, кН·м",
        "κ, 1/м",
        "ε_c,top, 10^-5",
        "ε_s,top, 10^-5",
        "ε_s,bot, 10^-5",
    ]
    assert summary_table.iloc[0]["Крок"] == 1
    assert summary_table.iloc[0]["M, кН·м"] == pytest.approx(0.0)
    assert len(summary_table) <= 12
    assert not _has_dataframe(app, ["Крок", "M, кН·м", "κ, 1/м", "ε_c,top, ‰", "ε_c,bot, ‰"])
    assert not _has_dataframe(app, ["Крок", "M, кН·м", "ε_c,top, 10^-5"])
    assert not _has_dataframe(app, ["z, мм", "ε_c, ‰"])
    assert not _has_dataframe(app, ["Тип", "№", "Клас", "z, мм", "A, мм²", "ε, ‰", "σ, МПа", "N, кН"])
    drawing = _find_markdown_containing(app, "<svg")
    assert "Креслення перерізу" in drawing
    assert "2-га форма рівноваги" in drawing
    assert "Активна точка" in drawing
    assert "1-ша форма рівноваги" not in drawing
    assert "форма не реалізована для цього набору даних" not in drawing
    assert "A1: 4 x 8" in drawing
    assert "A500C" in drawing
    assert "N_A1 =" in drawing
    assert 'data-role="metric-legend"' in drawing
    assert 'data-role="metric-chip"' in drawing
    assert 'data-role="form-grid-line"' in drawing
    assert 'data-role="top-row-layout"' in drawing
    assert 'data-role="dimension-lane-left-h"' in drawing
    assert 'data-role="dimension-lane-left-z1"' in drawing
    assert 'data-role="dimension-lane-left-z2"' in drawing
    assert 'data-role="dimension-lane-right-h1"' in drawing
    assert 'data-role="dimension-lane-right-h2"' in drawing
    assert 'data-role="dimension-label-chip"' in drawing


def test_streamlit_app_hides_missing_first_form_panel_for_default_second_form_state():
    app = AppTest.from_file("streamlit_app.py")

    app.run(timeout=10)

    drawing = _find_markdown_containing(app, "<svg")

    assert len(app.exception) == 0
    assert "2-га форма рівноваги" in drawing
    assert "1-ша форма рівноваги" not in drawing
    assert "форма не реалізована для цього набору даних" not in drawing
    assert drawing.count('data-role="form-panel"') == 1
    hero = _find_markdown_containing(app, 'data-role="hero-banner"')
    assert 'data-role="hero-author-list"' in hero
    assert "Іванейко М.М." in hero
    assert "Іванейко В.М." in hero
    assert not _has_markdown_containing(app, 'data-role="author-section"')


def test_streamlit_app_keeps_last_active_result_until_recalculate():
    app = AppTest.from_file("streamlit_app.py")

    app.run(timeout=10)
    baseline = float(_find_metric(app, "Несуча здатність M_Rd, кН·м").value)
    _find_widget_by_label(app.number_input, "Висота перерізу h, мм").set_value(400.0)
    app.run(timeout=10)

    assert len(app.exception) == 0
    rebar_preview = _find_dataframe(app, ["Шар", "Грань", "a, мм", "z, мм", "n, шт.", "d, мм", "Клас", "Статус"])
    assert rebar_preview.iloc[1]["z, мм"] == 380.0
    assert float(_find_metric(app, "Несуча здатність M_Rd, кН·м").value) == baseline
    assert _find_widget_by_label(app.button, "Перерахувати").disabled is False
    assert any("останнього застосованого" in info.value for info in app.info)
    assert not _has_markdown_containing(app, 'data-role="point-chip-grid"')

    _find_widget_by_label(app.button, "Перерахувати").click()
    app.run(timeout=10)

    assert float(_find_metric(app, "Несуча здатність M_Rd, кН·м").value) != baseline
    assert _has_markdown_containing(app, 'data-role="point-chip-grid"')


def test_streamlit_app_updates_outer_steps_only_after_recalculate():
    app = AppTest.from_file("streamlit_app.py")

    app.run(timeout=10)
    baseline_curve_df = _find_dataframe(
        app,
        ["Крок", "M, кН·м", "κ, 1/м", "ε_c,top, 10^-5", "ε_s,top, 10^-5", "ε_s,bot, 10^-5"],
    )
    baseline_rows = len(baseline_curve_df)

    _find_widget_by_label(app.number_input, "Кількість кроків розрахунку").set_value(8)
    app.run(timeout=10)

    dirty_curve_df = _find_dataframe(
        app,
        ["Крок", "M, кН·м", "κ, 1/м", "ε_c,top, 10^-5", "ε_s,top, 10^-5", "ε_s,bot, 10^-5"],
    )
    assert len(app.exception) == 0
    assert len(dirty_curve_df) == baseline_rows
    assert _find_widget_by_label(app.button, "Перерахувати").disabled is False

    _find_widget_by_label(app.button, "Перерахувати").click()
    app.run(timeout=10)

    updated_curve_df = _find_dataframe(
        app,
        ["Крок", "M, кН·м", "κ, 1/м", "ε_c,top, 10^-5", "ε_s,top, 10^-5", "ε_s,bot, 10^-5"],
    )
    assert len(updated_curve_df) < baseline_rows
    assert len(updated_curve_df) <= 8


def test_streamlit_app_disables_recalculate_for_invalid_draft():
    app = AppTest.from_file("streamlit_app.py")

    app.run(timeout=10)
    baseline = float(_find_metric(app, "Несуча здатність M_Rd, кН·м").value)
    _find_widget_by_label(app.number_input, "Товщина верхнього шару бетону h1, мм").set_value(600.0)
    app.run(timeout=10)

    assert len(app.exception) == 0
    assert _find_widget_by_label(app.button, "Перерахувати").disabled is True
    assert any("h1" in error.value for error in app.error)
    assert float(_find_metric(app, "Несуча здатність M_Rd, кН·м").value) == baseline


def test_streamlit_app_updates_preview_when_rebar_face_changes():
    app = AppTest.from_file("streamlit_app.py")

    app.run(timeout=10)
    _find_widget_by_label(app.selectbox, "Грань шару арматури 2").set_value("Верхня")
    app.run(timeout=10)

    assert len(app.exception) == 0
    rebar_preview = _find_dataframe(app, ["Шар", "Грань", "a, мм", "z, мм", "n, шт.", "d, мм", "Клас", "Статус"])
    assert rebar_preview.iloc[1]["Грань"] == "Верхня"
    assert rebar_preview.iloc[1]["z, мм"] == 20.0
    drawing = _find_markdown_containing(app, "<svg")
    assert "z2 = 20.0 мм" in drawing


def test_streamlit_app_uses_constant_width_without_individual_layer_controls():
    app = AppTest.from_file("streamlit_app.py")

    app.run(timeout=10)

    labels = [widget.label for widget in app.number_input]
    checkbox_labels = [widget.label for widget in app.checkbox]
    assert len(app.exception) == 0
    assert "Окремі ширини шарів" not in checkbox_labels
    assert "Ширина верхнього шару бетону b1, мм" not in labels
    assert "Ширина нижнього шару бетону b2, мм" not in labels
    drawing = _find_markdown_containing(app, "<svg")
    assert "b = 500.0 мм" in drawing


def test_streamlit_app_updates_section_drawing_when_geometry_changes():
    app = AppTest.from_file("streamlit_app.py")

    app.run(timeout=10)
    initial_drawing = _find_markdown_containing(app, "<svg")
    _find_widget_by_label(app.number_input, "Товщина верхнього шару бетону h1, мм").set_value(50.0)
    app.run(timeout=10)

    updated_drawing = _find_markdown_containing(app, "<svg")

    assert len(app.exception) == 0
    assert "h1 = 60.0 мм" in initial_drawing
    assert "h1 = 50.0 мм" in updated_drawing
    assert "h2 = 70.0 мм" in updated_drawing


def test_streamlit_app_hides_result_overlays_for_dirty_draft_until_recalculate():
    app = AppTest.from_file("streamlit_app.py")

    app.run(timeout=10)
    _find_widget_by_label(app.number_input, "Висота перерізу h, мм").set_value(400.0)
    app.run(timeout=10)

    dirty_drawing = _find_markdown_containing(app, "<svg")

    assert "Активна точка" not in dirty_drawing
    assert "N_A1 =" not in dirty_drawing
    assert dirty_drawing.count('data-role="form-placeholder"') == 2
    assert "оверлеї" in dirty_drawing
    assert not _has_markdown_containing(app, 'data-role="point-chip-grid"')

    _find_widget_by_label(app.button, "Перерахувати").click()
    app.run(timeout=10)

    active_drawing = _find_markdown_containing(app, "<svg")

    assert "Активна точка" in active_drawing
    assert "N_A1 =" in active_drawing
    assert _has_markdown_containing(app, 'data-role="point-chip-grid"')


def test_streamlit_app_updates_current_point_panel_when_curve_point_changes():
    app = AppTest.from_file("streamlit_app.py")

    app.run(timeout=10)
    baseline_panel = _find_markdown_containing(app, 'data-role="point-chip-grid"')

    _find_widget_by_label(app.slider, "Розрахункова точка").set_value(1)
    app.run(timeout=10)

    assert len(app.exception) == 0
    updated_panel = _find_markdown_containing(app, 'data-role="point-chip-grid"')
    assert baseline_panel != updated_panel
    assert 'data-role="point-value-step">1<' in updated_panel
