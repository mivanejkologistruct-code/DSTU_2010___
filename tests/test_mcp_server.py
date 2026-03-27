import importlib
import json
from pathlib import Path

from openpyxl import Workbook
import pytest


def _import_module(name: str):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as error:
        pytest.fail(f"Expected module {name!r} to exist: {error}")


def _make_section_payload() -> dict[str, object]:
    return {
        "section_height_mm": 500.0,
        "section_width_mm": 300.0,
        "outer_steps": 12,
        "concrete_layers": [
            {"height_mm": 250.0, "concrete_class": "C25/30"},
            {"height_mm": 250.0, "concrete_class": "C25/30"},
        ],
        "rebar_layers": [
            {"face": "top", "distance_mm": 40.0, "bar_count": 2, "diameter_mm": 20, "steel_class": "B500"},
            {"face": "bottom", "distance_mm": 40.0, "bar_count": 2, "diameter_mm": 20, "steel_class": "B500"},
        ],
    }


def _make_serviceability_payload() -> dict[str, object]:
    return {
        "span_mm": 6000.0,
        "support_scheme": "simply_supported_uniform",
        "a_mm": 1000.0,
        "phi_creep": 0.0,
        "deflection_limit_profile": "aesthetic_open_view",
        "available_gap_mm": 40.0,
        "w_limit_mm": 0.3,
        "load_duration": "long_term",
    }


def _build_experimental_workbook(path: Path) -> Path:
    workbook = Workbook()
    sheet_specs = {
        "M_f": ("f, мм", [(0.0, 0.0), (4.0, 12.0), (8.0, 20.0)]),
        "M_eps_c": ("ε_c,top, 10^-5", [(0.0, 0.0), (120.0, 12.0), (240.0, 20.0)]),
        "M_eps_s_top": ("ε_s, 10^-5", [(0.0, 0.0), (-120.0, 12.0), (-260.0, 20.0)]),
        "M_eps_s_bot": ("ε_s, 10^-5", [(0.0, 0.0), (180.0, 12.0), (360.0, 20.0)]),
    }
    first_sheet = workbook.active
    for index, (sheet_name, (x_field, rows)) in enumerate(sheet_specs.items()):
        sheet = first_sheet if index == 0 else workbook.create_sheet(sheet_name)
        sheet.title = sheet_name
        sheet.append([x_field, "M, кН·м"])
        for x_value, moment in rows:
            sheet.append([x_value, moment])
    workbook.save(path)
    return path


def test_build_draft_inputs_maps_machine_faces_to_ui_labels():
    adapters = _import_module("rc_bending_mcp.adapters")

    draft_inputs = adapters.build_draft_inputs(_make_section_payload())

    assert draft_inputs["section_height_mm"] == pytest.approx(500.0)
    assert draft_inputs["section_width_mm"] == pytest.approx(300.0)
    assert draft_inputs["rebar_layers"][0]["face"] == "Верхня"
    assert draft_inputs["rebar_layers"][1]["face"] == "Нижня"


def test_build_draft_inputs_marks_normalized_single_layer_payload_as_reference_mode():
    adapters = _import_module("rc_bending_mcp.adapters")
    payload = _make_section_payload()
    payload["concrete_layers"] = [
        {"height_mm": 500.0, "concrete_class": "C25/30"},
        {"height_mm": 0.0, "concrete_class": "C25/30"},
    ]
    payload["rebar_layers"] = [payload["rebar_layers"][1]]

    draft_inputs = adapters.build_draft_inputs(payload)

    assert draft_inputs["has_strengthening_layer"] is False
    assert len(draft_inputs["rebar_layers"]) == 1
    assert draft_inputs["rebar_layers"][0]["face"] == "Нижня"


def test_extract_section_machine_input_normalizes_reference_mode_to_two_layers():
    ui_helpers = _import_module("rc_bending.ui_helpers")
    ui_runner = _import_module("rc_bending_mcp.ui_runner")
    draft_inputs = ui_helpers.default_draft_inputs()
    draft_inputs["section_height_mm"] = 500.0
    draft_inputs["has_strengthening_layer"] = False
    draft_inputs["concrete_layers"][0]["height_mm"] = 30.0
    draft_inputs["concrete_layers"][0]["concrete_class"] = "C40/50"
    draft_inputs["concrete_layers"][1]["concrete_class"] = "C25/30"
    draft_inputs["rebar_layers"] = [draft_inputs["rebar_layers"][1]]

    payload = ui_runner._extract_section_machine_input(draft_inputs)

    assert payload["concrete_layers"] == [
        {"height_mm": 500.0, "concrete_class": "C25/30"},
        {"height_mm": 0.0, "concrete_class": "C25/30"},
    ]
    assert payload["rebar_layers"] == [
        {"face": "bottom", "distance_mm": 20.0, "bar_count": 4, "diameter_mm": 8, "steel_class": "A500C"}
    ]


def test_get_catalogs_returns_machine_ids_and_choices():
    handlers = _import_module("rc_bending_mcp.handlers")

    response = handlers.execute_get_catalogs()

    assert response["status"] == "ok"
    assert "messages" in response
    assert "python_result" in response
    assert response["ui_result"] is None
    assert response["comparison"] is None
    assert "C25/30" in response["python_result"]["concrete_classes"]
    assert "B500" in response["python_result"]["steel_classes"]
    assert "simply_supported_uniform" in response["python_result"]["support_schemes"]


def test_execute_calculate_section_returns_ok_envelope_and_artifacts(tmp_path):
    handlers = _import_module("rc_bending_mcp.handlers")

    class MatchingUIRunner:
        def run_section(self, **kwargs):
            expected = kwargs["expected_python_result"]
            return {
                "peak_moment_kNm": expected["peak_moment_kNm"],
                "selected_step": expected["selected_step"],
                "neutral_axis_mm": expected["neutral_axis_mm"],
                "top_strain": expected["top_strain"],
                "bottom_strain": expected["bottom_strain"],
            }

    response = handlers.execute_calculate_section(
        _make_section_payload(),
        output_dir=tmp_path,
        ui_runner=MatchingUIRunner(),
    )

    artifact_names = {Path(item["path"]).name for item in response["artifacts"]}
    summary_path = tmp_path / "summary.json"

    assert response["status"] == "ok"
    assert response["python_result"]["peak_moment_kNm"] > 0.0
    assert response["ui_result"]["peak_moment_kNm"] == pytest.approx(response["python_result"]["peak_moment_kNm"])
    assert response["comparison"]["mismatches"] == []
    assert "summary.json" in artifact_names
    assert "bending_results.xlsx" in artifact_names
    assert summary_path.exists()
    assert json.loads(summary_path.read_text(encoding="utf-8"))["status"] == "ok"


def test_execute_calculate_section_returns_invalid_input_without_ui(tmp_path):
    handlers = _import_module("rc_bending_mcp.handlers")
    payload = _make_section_payload()
    payload["rebar_layers"][0]["face"] = "middle"

    class FailingUIRunner:
        def run_section(self, **kwargs):
            raise AssertionError("UI runner must not be called for invalid input.")

    response = handlers.execute_calculate_section(
        payload,
        output_dir=tmp_path,
        ui_runner=FailingUIRunner(),
    )

    assert response["status"] == "invalid_input"
    assert response["ui_result"] is None
    assert response["comparison"] is None
    assert response["artifacts"] == []
    assert response["messages"]


def test_reference_section_theory_tables_use_single_bottom_rebar_series():
    domain = _import_module("rc_bending_mcp.domain")
    payload = _make_section_payload()
    payload["concrete_layers"] = [
        {"height_mm": 500.0, "concrete_class": "C25/30"},
        {"height_mm": 0.0, "concrete_class": "C25/30"},
    ]
    payload["rebar_layers"] = [payload["rebar_layers"][1]]

    result = domain.calculate_serviceability_python(payload, _make_serviceability_payload())

    assert "M_eps_s_bot" in result["theory_tables"]
    assert "M_eps_s_top" not in result["theory_tables"]
    assert float(result["theory_tables"]["M_eps_s_bot"].iloc[0]["ε_s, 10^-5"]) == pytest.approx(0.0)
    assert float(result["theory_tables"]["M_eps_s_bot"].iloc[-1]["ε_s, 10^-5"]) > 0.0


def test_execute_calculate_serviceability_returns_ok_envelope(tmp_path):
    handlers = _import_module("rc_bending_mcp.handlers")

    class MatchingUIRunner:
        def run_serviceability(self, **kwargs):
            expected = kwargs["expected_python_result"]
            return {
                "selected_step": expected["selected_step"],
                "peak_moment_kNm": expected["peak_moment_kNm"],
                "w_k_mm": expected["w_k_mm"],
                "deflection_mm": expected["deflection_mm"],
            }

    response = handlers.execute_calculate_serviceability(
        _make_section_payload(),
        _make_serviceability_payload(),
        output_dir=tmp_path,
        ui_runner=MatchingUIRunner(),
    )

    assert response["status"] == "ok"
    assert response["python_result"]["deflection_mm"] >= 0.0
    assert response["ui_result"]["w_k_mm"] == pytest.approx(response["python_result"]["w_k_mm"])
    assert response["comparison"]["mismatches"] == []


def test_execute_analyze_experimental_workbook_returns_ok_envelope(tmp_path):
    handlers = _import_module("rc_bending_mcp.handlers")
    workbook_path = _build_experimental_workbook(tmp_path / "experimental_curves.xlsx")

    class MatchingUIRunner:
        def run_experimental(self, **kwargs):
            expected = kwargs["expected_python_result"]
            return {
                "inspection_status": expected["inspection_status"],
                "loaded_sheet_names": expected["loaded_sheet_names"],
            }

    response = handlers.execute_analyze_experimental_workbook(
        str(workbook_path),
        _make_section_payload(),
        _make_serviceability_payload(),
        output_dir=tmp_path,
        ui_runner=MatchingUIRunner(),
    )

    assert response["status"] == "ok"
    assert response["python_result"]["inspection_status"] == "ready"
    assert sorted(response["python_result"]["loaded_sheet_names"]) == ["M_eps_c", "M_eps_s_bot", "M_eps_s_top", "M_f"]
    assert response["comparison"]["mismatches"] == []


def test_execute_build_experimental_template_writes_xlsx(tmp_path):
    handlers = _import_module("rc_bending_mcp.handlers")

    response = handlers.execute_build_experimental_template(output_dir=tmp_path)

    artifact_names = {Path(item["path"]).name for item in response["artifacts"]}

    assert response["status"] == "ok"
    assert response["python_result"]["template_path"].endswith("experimental_curves_template.xlsx")
    assert "experimental_curves_template.xlsx" in artifact_names
    assert "summary.json" in artifact_names
