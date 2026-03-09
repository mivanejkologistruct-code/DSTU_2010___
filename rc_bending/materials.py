from __future__ import annotations

import json
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
class MaterialCatalog:
    concrete: dict[str, ConcreteMaterial]
    steel: dict[str, SteelMaterial]
    rebar_area_mm2: dict[int, float]


def _load_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_material_catalog() -> MaterialCatalog:
    concrete_data = _load_json(MATERIALS_DIR / "concrete_dbn.json")
    steel_data = _load_json(MATERIALS_DIR / "steel_catalog.json")
    area_data = _load_json(MATERIALS_DIR / "rebar_area_mm2.json")

    concrete = {
        item["concrete_class"]: ConcreteMaterial(
            concrete_class=item["concrete_class"],
            f_cd_mpa=item["f_cd_mpa"],
            e_cd_gpa=item["e_cd_gpa"],
            epsilon_c1=item["epsilon_c1"],
            epsilon_cu1=item["epsilon_cu1"],
            a=tuple(item["a"]),
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

    return MaterialCatalog(concrete=concrete, steel=steel, rebar_area_mm2=rebar_area_mm2)
