from dataclasses import replace

import pytest

from rc_bending.materials import load_material_catalog
from rc_bending.models import ConcreteLayerInput, RebarLayerInput, SectionInput
from rc_bending.ui_helpers import (
    build_section_input_from_draft,
    default_draft_inputs,
    derive_draft_geometry,
    validate_draft_inputs,
    validate_section_form_inputs,
)


def make_section() -> SectionInput:
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


def test_material_catalog_contains_expected_reference_values():
    catalog = load_material_catalog()

    concrete = catalog.concrete["C25/30"]
    steel = catalog.steel["A400C"]

    assert concrete.f_cd_mpa == pytest.approx(17.0)
    assert concrete.epsilon_c1 == pytest.approx(1.69e-3)
    assert concrete.epsilon_cu1 == pytest.approx(3.28e-3)
    assert concrete.a[0] == pytest.approx(2.7404)
    assert steel.f_yk_mpa == pytest.approx(400.0)
    assert steel.gamma_s == pytest.approx(1.1)
    assert steel.epsilon_ud == pytest.approx(0.025)
    assert catalog.rebar_area_mm2[28] == pytest.approx(615.8)


def test_section_input_validates_total_height_and_rebar_position():
    section = make_section()

    assert section.total_concrete_height_mm == pytest.approx(500.0)
    assert section.section_centroid_mm == pytest.approx(250.0)

    invalid_height = replace(
        section,
        concrete_layers=(
            ConcreteLayerInput(width_mm=500.0, height_mm=150.0, concrete_class="C30/35"),
            ConcreteLayerInput(width_mm=500.0, height_mm=300.0, concrete_class="C20/25"),
        ),
    )
    with pytest.raises(ValueError, match="sum of concrete layer heights"):
        invalid_height.validate()

    invalid_rebar = replace(
        section,
        rebar_layers=(
            RebarLayerInput(z_mm=520.0, area_mm2=615.8, steel_class="A400C"),
        ),
    )
    with pytest.raises(ValueError, match="inside the section height"):
        invalid_rebar.validate()


def test_zero_height_second_layer_is_allowed_for_single_concrete_reduction():
    section = SectionInput(
        section_height_mm=500.0,
        concrete_layers=(
            ConcreteLayerInput(width_mm=500.0, height_mm=500.0, concrete_class="C25/30"),
            ConcreteLayerInput(width_mm=500.0, height_mm=0.0, concrete_class="C25/30"),
        ),
        rebar_layers=(
            RebarLayerInput(z_mm=30.0, area_mm2=615.8, steel_class="A400C"),
        ),
    )

    section.validate()


def test_validate_section_form_inputs_reports_multiple_errors():
    errors = validate_section_form_inputs(
        section_height_mm=400.0,
        concrete_rows=[
            {"width_mm": 500.0, "height_mm": 200.0, "concrete_class": "C25/30"},
            {"width_mm": 500.0, "height_mm": 300.0, "concrete_class": "C25/30"},
        ],
        rebar_rows=[
            {"z_mm": 30.0, "bar_count": 7, "diameter_mm": 28, "steel_class": "A400C"},
            {"z_mm": 470.0, "bar_count": 7, "diameter_mm": 28, "steel_class": "A400C"},
        ],
    )

    assert "The sum of concrete layer heights must equal the section height." in errors
    assert "Each rebar layer must stay inside the section height." in errors


def test_derive_draft_geometry_builds_expected_bottom_height_and_rebar_z():
    draft = default_draft_inputs()
    derived = derive_draft_geometry(draft)

    assert "use_layer_widths" not in draft
    assert draft["outer_steps"] == 12
    assert derived["concrete_rows"][0]["height_mm"] == pytest.approx(60.0)
    assert derived["concrete_rows"][0]["width_mm"] == pytest.approx(500.0)
    assert derived["concrete_rows"][1]["height_mm"] == pytest.approx(60.0)
    assert derived["concrete_rows"][1]["width_mm"] == pytest.approx(500.0)
    assert derived["concrete_rows"][0]["concrete_class"] == "C40/50"
    assert derived["concrete_rows"][1]["concrete_class"] == "C40/50"
    assert derived["rebar_rows"][0]["z_mm"] == pytest.approx(40.0)
    assert derived["rebar_rows"][1]["z_mm"] == pytest.approx(100.0)
    assert derived["rebar_rows"][0]["steel_class"] == "A500C"
    assert derived["rebar_rows"][1]["steel_class"] == "A500C"


def test_validate_draft_inputs_reports_invalid_top_height_and_cover():
    catalog = load_material_catalog()
    draft = default_draft_inputs()
    draft["concrete_layers"][0]["height_mm"] = 520.0
    draft["rebar_layers"][1]["distance_mm"] = 520.0

    errors = validate_draft_inputs(draft, catalog)

    assert any("h1" in message for message in errors)
    assert any("a2" in message for message in errors)


def test_build_section_input_from_draft_matches_expected_section():
    catalog = load_material_catalog()
    draft = default_draft_inputs()

    section = build_section_input_from_draft(draft, catalog)

    assert section.section_height_mm == pytest.approx(120.0)
    assert section.concrete_layers[0].width_mm == pytest.approx(500.0)
    assert section.concrete_layers[0].height_mm == pytest.approx(60.0)
    assert section.concrete_layers[1].height_mm == pytest.approx(60.0)
    assert section.concrete_layers[0].concrete_class == "C40/50"
    assert section.concrete_layers[1].concrete_class == "C40/50"
    assert section.rebar_layers[0].z_mm == pytest.approx(40.0)
    assert section.rebar_layers[1].z_mm == pytest.approx(100.0)
    assert section.rebar_layers[0].steel_class == "A500C"
    assert section.rebar_layers[1].steel_class == "A500C"
