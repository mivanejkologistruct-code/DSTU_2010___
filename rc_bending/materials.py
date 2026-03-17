from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
MATERIALS_DIR = BASE_DIR / "materials"


@dataclass(frozen=True)
class ConcreteMaterial:
    concrete_class: str
    f_cd_mpa: float
    e_cd_gpa: float
    epsilon_c1: float
    epsilon_cu1: float
    a: tuple[float, float, float, float, float]
    f_ck_mpa: float
    f_ctm_mpa: float
    e_cm_gpa: float
    epsilon_ctu: float


@dataclass(frozen=True)
class SteelMaterial:
    steel_class: str
    f_yk_mpa: float
    gamma_s: float
    e_s_mpa: float
    epsilon_ud: float

    @property
    def f_yd_mpa(self) -> float:
        return self.f_yk_mpa / self.gamma_s


@dataclass(frozen=True)
class ConcreteDisplayLimit:
    concrete_class: str
    label: str
    strain_e5: float


@dataclass(frozen=True)
class SteelDisplayLimit:
    steel_class: str
    label: str
    strain_e5: float


@dataclass(frozen=True)
class DisplayLimitCatalog:
    concrete: dict[str, ConcreteDisplayLimit]
    steel: dict[str, SteelDisplayLimit]


@dataclass(frozen=True)
class MaterialCatalog:
    concrete: dict[str, ConcreteMaterial]
    steel: dict[str, SteelMaterial]
    rebar_area_mm2: dict[int, float]
    display_limits: DisplayLimitCatalog


def _load_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def _parse_fck_from_concrete_class(concrete_class: str) -> float:
    try:
        prefix, _ = concrete_class.split("/", 1)
        return float(prefix.removeprefix("C"))
    except (TypeError, ValueError):
        raise ValueError(f"Unsupported concrete class format: {concrete_class!r}")


def _build_serviceability_concrete_properties(concrete_class: str) -> tuple[float, float, float, float]:
    f_ck_mpa = _parse_fck_from_concrete_class(concrete_class)
    f_cm_mpa = f_ck_mpa + 8.0
    f_ctm_mpa = 0.3 * (f_ck_mpa ** (2.0 / 3.0))
    e_cm_gpa = 22.0 * ((f_cm_mpa / 10.0) ** 0.3)
    epsilon_ctu = 2.0 * f_ctm_mpa / (e_cm_gpa * 1000.0)
    return f_ck_mpa, f_ctm_mpa, e_cm_gpa, epsilon_ctu


def load_material_catalog() -> MaterialCatalog:
    concrete_data = _load_json(MATERIALS_DIR / "concrete_dbn.json")
    steel_data = _load_json(MATERIALS_DIR / "steel_catalog.json")
    area_data = _load_json(MATERIALS_DIR / "rebar_area_mm2.json")
    display_limit_data = _load_json(MATERIALS_DIR / "display_limits.json")

    concrete = {
        item["concrete_class"]: ConcreteMaterial(
            concrete_class=item["concrete_class"],
            f_cd_mpa=item["f_cd_mpa"],
            e_cd_gpa=item["e_cd_gpa"],
            epsilon_c1=item["epsilon_c1"],
            epsilon_cu1=item["epsilon_cu1"],
            a=tuple(item["a"]),
            f_ck_mpa=_build_serviceability_concrete_properties(item["concrete_class"])[0],
            f_ctm_mpa=_build_serviceability_concrete_properties(item["concrete_class"])[1],
            e_cm_gpa=_build_serviceability_concrete_properties(item["concrete_class"])[2],
            epsilon_ctu=_build_serviceability_concrete_properties(item["concrete_class"])[3],
        )
        for item in concrete_data
    }
    steel = {
        item["steel_class"]: SteelMaterial(
            steel_class=item["steel_class"],
            f_yk_mpa=item["f_yk_mpa"],
            gamma_s=item["gamma_s"],
            e_s_mpa=item["e_s_mpa"],
            epsilon_ud=item["epsilon_ud"],
        )
        for item in steel_data
    }
    rebar_area_mm2 = {int(key): float(value) for key, value in area_data.items()}
    concrete_display_limits = {
        concrete_class: ConcreteDisplayLimit(
            concrete_class=concrete_class,
            label=item["label"],
            strain_e5=float(item["strain_e5"]),
        )
        for concrete_class, item in display_limit_data["concrete"].items()
    }
    steel_display_limits = {
        steel_class: SteelDisplayLimit(
            steel_class=steel_class,
            label=item["label"],
            strain_e5=float(item["strain_e5"]),
        )
        for steel_class, item in display_limit_data["steel"].items()
    }

    return MaterialCatalog(
        concrete=concrete,
        steel=steel,
        rebar_area_mm2=rebar_area_mm2,
        display_limits=DisplayLimitCatalog(
            concrete=concrete_display_limits,
            steel=steel_display_limits,
        ),
    )
