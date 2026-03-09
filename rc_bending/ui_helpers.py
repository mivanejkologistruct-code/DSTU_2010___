from __future__ import annotations

from copy import deepcopy

from rc_bending.materials import MaterialCatalog
from rc_bending.models import ConcreteLayerInput, RebarLayerInput, SectionInput

TOP_FACE = "Верхня"
BOTTOM_FACE = "Нижня"


def _next_rebar_id(rows: list[dict[str, object]]) -> str:
    next_index = 1
    for row in rows:
        raw_id = str(row.get("id", ""))
        if raw_id.startswith("rebar_"):
            suffix = raw_id.split("_", 1)[1]
            if suffix.isdigit():
                next_index = max(next_index, int(suffix) + 1)
    return f"rebar_{next_index}"


def _is_draft_rebar_row(row: dict[str, object]) -> bool:
    return "distance_mm" in row or "face" in row


def default_rebar_rows() -> list[dict[str, object]]:
    return [
        {"z_mm": 40.0, "bar_count": 4, "diameter_mm": 8, "steel_class": "A500C"},
        {"z_mm": 100.0, "bar_count": 4, "diameter_mm": 8, "steel_class": "A500C"},
    ]


def default_draft_inputs() -> dict[str, object]:
    return {
        "section_height_mm": 120.0,
        "section_width_mm": 500.0,
        "outer_steps": 12,
        "concrete_layers": [
            {"height_mm": 60.0, "concrete_class": "C40/50"},
            {"concrete_class": "C40/50"},
        ],
        "rebar_layers": [
            {
                "id": "rebar_1",
                "face": TOP_FACE,
                "distance_mm": 40.0,
                "bar_count": 4,
                "diameter_mm": 8,
                "steel_class": "A500C",
            },
            {
                "id": "rebar_2",
                "face": BOTTOM_FACE,
                "distance_mm": 20.0,
                "bar_count": 4,
                "diameter_mm": 8,
                "steel_class": "A500C",
            },
        ],
    }


def copy_draft_inputs(draft_inputs: dict[str, object]) -> dict[str, object]:
    return deepcopy(draft_inputs)


def add_rebar_layer(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    new_rows = [dict(row) for row in rows]

    if new_rows and _is_draft_rebar_row(new_rows[0]):
        distance_values = [float(row["distance_mm"]) for row in new_rows] or [30.0]
        new_rows.append(
            {
                "id": _next_rebar_id(new_rows),
                "face": TOP_FACE,
                "distance_mm": sum(distance_values) / len(distance_values),
                "bar_count": 1,
                "diameter_mm": 12,
                "steel_class": "A400C",
            }
        )
        return new_rows

    z_values = [float(row["z_mm"]) for row in new_rows] or [250.0]
    new_rows.append(
        {
            "z_mm": sum(z_values) / len(z_values),
            "bar_count": 1,
            "diameter_mm": 12,
            "steel_class": "A400C",
        }
    )
    return new_rows


def remove_rebar_layer(rows: list[dict[str, object]], index: int) -> list[dict[str, object]]:
    if len(rows) <= 1:
        return [dict(row) for row in rows]
    return [dict(row) for current, row in enumerate(rows) if current != index]


def derive_draft_geometry(draft_inputs: dict[str, object]) -> dict[str, object]:
    section_height_mm = float(draft_inputs["section_height_mm"])
    section_width_mm = float(draft_inputs["section_width_mm"])

    concrete_layers = copy_draft_inputs({"rows": draft_inputs["concrete_layers"]})["rows"]
    top_height_mm = float(concrete_layers[0]["height_mm"])
    bottom_height_mm = section_height_mm - top_height_mm

    concrete_rows = [
        {
            "layer": "B1",
            "width_mm": section_width_mm,
            "height_mm": top_height_mm,
            "concrete_class": str(concrete_layers[0]["concrete_class"]),
            "status": "OK" if top_height_mm >= 0 else "Помилка",
        },
        {
            "layer": "B2",
            "width_mm": section_width_mm,
            "height_mm": bottom_height_mm,
            "concrete_class": str(concrete_layers[1]["concrete_class"]),
            "status": "OK" if bottom_height_mm >= 0 else "Помилка",
        },
    ]

    rebar_rows = []
    for index, row in enumerate(list(draft_inputs["rebar_layers"]), start=1):
        face = str(row["face"])
        distance_mm = float(row["distance_mm"])
        z_mm = distance_mm if face == TOP_FACE else section_height_mm - distance_mm
        formula = f"z = a{index}" if face == TOP_FACE else f"z = h - a{index}"
        rebar_rows.append(
            {
                "layer": f"A{index}",
                "face": face,
                "distance_mm": distance_mm,
                "z_mm": z_mm,
                "bar_count": int(row["bar_count"]),
                "diameter_mm": int(row["diameter_mm"]),
                "steel_class": str(row["steel_class"]),
                "formula": formula,
                "status": "OK" if 0.0 <= z_mm <= section_height_mm else "Помилка",
            }
        )

    return {
        "section_height_mm": section_height_mm,
        "section_width_mm": section_width_mm,
        "concrete_rows": concrete_rows,
        "rebar_rows": rebar_rows,
    }


def validate_draft_inputs(draft_inputs: dict[str, object], catalog: MaterialCatalog | None = None) -> list[str]:
    errors: list[str] = []

    def add_error(message: str) -> None:
        if message not in errors:
            errors.append(message)

    derived = derive_draft_geometry(draft_inputs)
    section_height_mm = float(derived["section_height_mm"])
    section_width_mm = float(derived["section_width_mm"])
    concrete_rows = list(derived["concrete_rows"])
    rebar_rows = list(derived["rebar_rows"])
    outer_steps_raw = draft_inputs.get("outer_steps", 40)

    if section_height_mm <= 0:
        add_error("Висота перерізу h має бути додатною.")
    if section_width_mm <= 0:
        add_error("Ширина перерізу b має бути додатною.")
    if isinstance(outer_steps_raw, bool):
        add_error("Кількість кроків розрахунку має бути цілим числом у межах від 2 до 200.")
    else:
        try:
            outer_steps = float(outer_steps_raw)
        except (TypeError, ValueError):
            add_error("Кількість кроків розрахунку має бути цілим числом у межах від 2 до 200.")
        else:
            if not outer_steps.is_integer() or not (2 <= int(outer_steps) <= 200):
                add_error("Кількість кроків розрахунку має бути цілим числом у межах від 2 до 200.")

    if concrete_rows[0]["height_mm"] < 0 or concrete_rows[0]["height_mm"] > section_height_mm:
        add_error("Товщина верхнього шару бетону h1 має бути в межах від 0 до h.")
    if concrete_rows[1]["height_mm"] < 0:
        add_error("Похідна товщина нижнього шару бетону h2 не може бути від'ємною.")

    for index, row in enumerate(concrete_rows, start=1):
        if not str(row["concrete_class"]):
            add_error(f"Клас бетону шару {index} обов'язковий.")

    if len(rebar_rows) != 2:
        add_error("Рівно два шари арматури є обов'язковими для нормативного сценарію: верхній і нижній.")

    for index, row in enumerate(rebar_rows, start=1):
        face = str(row["face"])
        distance_mm = float(row["distance_mm"])
        bar_count = int(row["bar_count"])
        diameter_mm = int(row["diameter_mm"])
        steel_class = str(row["steel_class"])

        if face not in {TOP_FACE, BOTTOM_FACE}:
            add_error(f"Положення грані для шару арматури {index} задано некоректно.")
        if distance_mm < 0 or distance_mm > section_height_mm:
            add_error(f"Відстань a{index} має бути в межах від 0 до h.")
        if not (0.0 <= float(row["z_mm"]) <= section_height_mm):
            add_error(f"Похідна координата z{index} виходить за межі перерізу.")
        if bar_count <= 0:
            add_error(f"Площа шару арматури {index} має бути додатною.")
        if diameter_mm <= 0:
            add_error(f"Діаметр d{index} має бути додатним.")
        if not steel_class:
            add_error(f"Клас арматури шару {index} обов'язковий.")

        if catalog is None:
            continue

        if diameter_mm not in catalog.rebar_area_mm2:
            add_error(f"Діаметр d{index} відсутній у довіднику.")
            continue

        if bar_count * catalog.rebar_area_mm2[diameter_mm] <= 0:
            add_error(f"Площа шару арматури {index} має бути додатною.")

    return errors


def validate_section_form_inputs(
    section_height_mm: float,
    concrete_rows: list[dict[str, object]],
    rebar_rows: list[dict[str, object]],
    catalog: MaterialCatalog | None = None,
) -> list[str]:
    errors: list[str] = []

    def add_error(message: str) -> None:
        if message not in errors:
            errors.append(message)

    if section_height_mm <= 0:
        add_error("Section height must be positive.")

    if len(concrete_rows) != 2:
        add_error("Exactly two concrete layers are required.")

    concrete_height_sum = 0.0
    for row in concrete_rows:
        width_mm = float(row["width_mm"])
        height_mm = float(row["height_mm"])
        concrete_class = str(row["concrete_class"])

        if width_mm <= 0:
            add_error("Concrete layer width must be positive.")
        if height_mm < 0:
            add_error("Concrete layer height must be non-negative.")
        if not concrete_class:
            add_error("Concrete layer class is required.")

        concrete_height_sum += height_mm

    if concrete_rows and abs(concrete_height_sum - section_height_mm) > 1e-9:
        add_error("The sum of concrete layer heights must equal the section height.")

    if len(rebar_rows) != 2:
        add_error("Exactly two rebar layers are required.")

    for row in rebar_rows:
        z_mm = float(row["z_mm"])
        bar_count = float(row["bar_count"])
        diameter_mm = int(row["diameter_mm"])
        steel_class = str(row["steel_class"])

        if not (0.0 <= z_mm <= section_height_mm):
            add_error("Each rebar layer must stay inside the section height.")
        if bar_count <= 0:
            add_error("Rebar layer area must be positive.")
        if not steel_class:
            add_error("Rebar layer class is required.")

        if catalog is None:
            if diameter_mm <= 0:
                add_error("Rebar layer area must be positive.")
            continue

        if diameter_mm not in catalog.rebar_area_mm2:
            add_error("Rebar layer area must be positive.")
            continue

        if bar_count * catalog.rebar_area_mm2[diameter_mm] <= 0:
            add_error("Rebar layer area must be positive.")

    return errors


def build_section_input(
    section_height_mm: float,
    concrete_rows: list[dict[str, object]],
    rebar_rows: list[dict[str, object]],
    catalog: MaterialCatalog,
) -> SectionInput:
    errors = validate_section_form_inputs(section_height_mm, concrete_rows, rebar_rows, catalog)
    if errors:
        raise ValueError(errors[0])

    concrete_layers = tuple(
        ConcreteLayerInput(
            width_mm=float(row["width_mm"]),
            height_mm=float(row["height_mm"]),
            concrete_class=str(row["concrete_class"]),
        )
        for row in concrete_rows
    )
    rebar_layers = []
    for row in rebar_rows:
        diameter = int(row["diameter_mm"])
        count = float(row["bar_count"])
        rebar_layers.append(
            RebarLayerInput(
                z_mm=float(row["z_mm"]),
                area_mm2=count * catalog.rebar_area_mm2[diameter],
                steel_class=str(row["steel_class"]),
            )
        )
    section = SectionInput(
        section_height_mm=section_height_mm,
        concrete_layers=concrete_layers,  # type: ignore[arg-type]
        rebar_layers=tuple(rebar_layers),
    )
    section.validate()
    return section


def build_section_input_from_draft(draft_inputs: dict[str, object], catalog: MaterialCatalog) -> SectionInput:
    derived = derive_draft_geometry(draft_inputs)
    concrete_rows = [
        {
            "width_mm": row["width_mm"],
            "height_mm": row["height_mm"],
            "concrete_class": row["concrete_class"],
        }
        for row in derived["concrete_rows"]
    ]
    rebar_rows = [
        {
            "z_mm": row["z_mm"],
            "bar_count": row["bar_count"],
            "diameter_mm": row["diameter_mm"],
            "steel_class": row["steel_class"],
        }
        for row in derived["rebar_rows"]
    ]
    return build_section_input(float(derived["section_height_mm"]), concrete_rows, rebar_rows, catalog)
