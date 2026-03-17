from __future__ import annotations

from collections.abc import Mapping, Sequence

from rc_bending.materials import load_material_catalog
from rc_bending.serviceability import (
    DEFLECTION_LIMIT_PROFILE_LABELS,
    LOAD_DURATION_LABELS,
    SUPPORT_SCHEME_LABELS,
)
from rc_bending.ui_helpers import BOTTOM_FACE, TOP_FACE, default_draft_inputs, default_serviceability_inputs


FACE_TO_UI = {
    "top": TOP_FACE,
    "bottom": BOTTOM_FACE,
}


def build_draft_inputs(section_input: Mapping[str, object]) -> dict[str, object]:
    concrete_layers = list(_require_sequence(section_input.get("concrete_layers"), "concrete_layers"))
    rebar_layers = list(_require_sequence(section_input.get("rebar_layers"), "rebar_layers"))
    if len(concrete_layers) != 2:
        raise ValueError("Exactly two concrete layers are required.")
    if len(rebar_layers) != 2:
        raise ValueError("Exactly two rebar layers are required.")

    defaults = default_draft_inputs()
    top_concrete = _require_mapping(concrete_layers[0], "concrete_layers[0]")
    bottom_concrete = _require_mapping(concrete_layers[1], "concrete_layers[1]")
    return {
        "section_height_mm": float(section_input["section_height_mm"]),
        "section_width_mm": float(section_input["section_width_mm"]),
        "outer_steps": int(section_input.get("outer_steps", defaults["outer_steps"])),
        "concrete_layers": [
            {
                "height_mm": float(top_concrete["height_mm"]),
                "concrete_class": str(top_concrete["concrete_class"]),
            },
            {
                "height_mm": float(bottom_concrete["height_mm"]),
                "concrete_class": str(bottom_concrete["concrete_class"]),
            },
        ],
        "rebar_layers": [
            _build_rebar_row(index, _require_mapping(rebar_layer, f"rebar_layers[{index}]"))
            for index, rebar_layer in enumerate(rebar_layers, start=1)
        ],
        "serviceability": default_serviceability_inputs(),
    }


def build_serviceability_draft_inputs(serviceability_input: Mapping[str, object] | None) -> dict[str, object]:
    defaults = default_serviceability_inputs()
    if serviceability_input is None:
        return defaults
    return {
        "span_mm": float(serviceability_input.get("span_mm", defaults["span_mm"])),
        "support_scheme": str(serviceability_input.get("support_scheme", defaults["support_scheme"])),
        "a_mm": _optional_float(serviceability_input.get("a_mm", defaults["a_mm"])),
        "phi_creep": float(serviceability_input.get("phi_creep", defaults["phi_creep"])),
        "deflection_limit_profile": str(
            serviceability_input.get("deflection_limit_profile", defaults["deflection_limit_profile"])
        ),
        "available_gap_mm": _optional_float(serviceability_input.get("available_gap_mm", defaults["available_gap_mm"])),
        "w_limit_mm": float(serviceability_input.get("w_limit_mm", defaults["w_limit_mm"])),
        "load_duration": str(serviceability_input.get("load_duration", defaults["load_duration"])),
    }


def build_catalog_payload() -> dict[str, object]:
    catalog = load_material_catalog()
    return {
        "concrete_classes": sorted(catalog.concrete.keys()),
        "steel_classes": sorted(catalog.steel.keys()),
        "rebar_diameters_mm": sorted(catalog.rebar_area_mm2.keys()),
        "support_schemes": sorted(SUPPORT_SCHEME_LABELS.keys()),
        "deflection_limit_profiles": sorted(DEFLECTION_LIMIT_PROFILE_LABELS.keys()),
        "load_durations": sorted(LOAD_DURATION_LABELS.keys()),
    }


def _build_rebar_row(index: int, rebar_layer: Mapping[str, object]) -> dict[str, object]:
    face = str(rebar_layer["face"]).strip().lower()
    if face not in FACE_TO_UI:
        raise ValueError(f"Unsupported rebar face: {face}")
    return {
        "id": f"rebar_{index}",
        "face": FACE_TO_UI[face],
        "distance_mm": float(rebar_layer["distance_mm"]),
        "bar_count": int(rebar_layer["bar_count"]),
        "diameter_mm": int(rebar_layer["diameter_mm"]),
        "steel_class": str(rebar_layer["steel_class"]),
    }


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object.")
    return value


def _require_sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{label} must be an array.")
    return value


def _optional_float(value: object) -> float | None:
    if value in {None, ""}:
        return None
    return float(value)
