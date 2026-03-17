from pathlib import Path
import os

from openpyxl import Workbook
import pytest

from rc_bending_mcp.handlers import (
    execute_analyze_experimental_workbook,
    execute_build_experimental_template,
    execute_calculate_section,
    execute_calculate_serviceability,
)


LIVE_UI_ENABLED = os.getenv("LIVE_MCP_UI") == "1"


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
    specs = {
        "M_f": ("f, мм", [(0.0, 0.0), (4.0, 12.0)]),
        "M_eps_c": ("ε_c,top, 10^-5", [(0.0, 0.0), (120.0, 12.0)]),
        "M_eps_s_top": ("ε_s, 10^-5", [(0.0, 0.0), (-120.0, 12.0)]),
        "M_eps_s_bot": ("ε_s, 10^-5", [(0.0, 0.0), (180.0, 12.0)]),
    }
    first_sheet = workbook.active
    for index, (sheet_name, (x_field, rows)) in enumerate(specs.items()):
        sheet = first_sheet if index == 0 else workbook.create_sheet(sheet_name)
        sheet.title = sheet_name
        sheet.append([x_field, "M, кН·м"])
        for x_value, moment in rows:
            sheet.append([x_value, moment])
    workbook.save(path)
    return path


@pytest.mark.skipif(not LIVE_UI_ENABLED, reason="Set LIVE_MCP_UI=1 to run live MCP UI automation checks.")
def test_live_calculate_section(tmp_path):
    response = execute_calculate_section(_make_section_payload(), output_dir=tmp_path / "section")

    assert response["status"] == "ok"
    assert response["comparison"]["mismatches"] == []


@pytest.mark.skipif(not LIVE_UI_ENABLED, reason="Set LIVE_MCP_UI=1 to run live MCP UI automation checks.")
def test_live_calculate_serviceability(tmp_path):
    response = execute_calculate_serviceability(
        _make_section_payload(),
        _make_serviceability_payload(),
        output_dir=tmp_path / "serviceability",
    )

    assert response["status"] == "ok"
    assert response["comparison"]["mismatches"] == []


@pytest.mark.skipif(not LIVE_UI_ENABLED, reason="Set LIVE_MCP_UI=1 to run live MCP UI automation checks.")
def test_live_analyze_experimental_workbook(tmp_path):
    workbook_path = _build_experimental_workbook(tmp_path / "experimental.xlsx")

    response = execute_analyze_experimental_workbook(
        str(workbook_path),
        _make_section_payload(),
        _make_serviceability_payload(),
        output_dir=tmp_path / "experimental",
    )

    assert response["status"] == "ok"
    assert response["comparison"]["mismatches"] == []


@pytest.mark.skipif(not LIVE_UI_ENABLED, reason="Set LIVE_MCP_UI=1 to run live MCP UI automation checks.")
def test_live_build_experimental_template(tmp_path):
    response = execute_build_experimental_template(output_dir=tmp_path / "template")

    assert response["status"] == "ok"
    assert response["python_result"]["template_path"].endswith("experimental_curves_template.xlsx")
