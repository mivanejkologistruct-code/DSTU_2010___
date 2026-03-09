from __future__ import annotations

from dataclasses import dataclass

from rc_bending.materials import ConcreteMaterial, MaterialCatalog, SteelMaterial
from rc_bending.models import (
    BendingResult,
    ConcreteDiagramPoint,
    ConcreteLayerInput,
    CurvePoint,
    DiagramResultant,
    DiagramScaleLimits,
    InnerIterationRow,
    RebarDiagramState,
    SectionDiagramState,
    SectionInput,
    StrainProfilePoint,
)


@dataclass(frozen=True)
class _ConcreteFiber:
    z_mm: float
    area_mm2: float
    material: ConcreteMaterial


def _concrete_stress_mpa(strain: float, material: ConcreteMaterial) -> float:
    if strain <= 0.0:
        return 0.0
    eta = strain / material.epsilon_c1
    stress_ratio = 0.0
    for power, coefficient in enumerate(material.a, start=1):
        stress_ratio += coefficient * (eta**power)
    return max(0.0, material.f_cd_mpa * stress_ratio)


def _steel_stress_mpa(strain: float, material: SteelMaterial) -> float:
    if abs(strain) >= material.epsilon_ud:
        return 0.0
    elastic = material.e_s_mpa * strain
    if elastic > material.f_yd_mpa:
        return material.f_yd_mpa
    if elastic < -material.f_yd_mpa:
        return -material.f_yd_mpa
    return elastic


def _strain_at_depth(top_strain: float, bottom_strain: float, z_mm: float, section_height_mm: float) -> float:
    if section_height_mm == 0:
        return 0.0
    ratio = z_mm / section_height_mm
    return top_strain + (bottom_strain - top_strain) * ratio


def _build_fibers(
    layers: tuple[ConcreteLayerInput, ConcreteLayerInput],
    materials: MaterialCatalog,
    section_height_mm: float,
    fibers_per_section: int,
) -> tuple[_ConcreteFiber, ...]:
    fibers: list[_ConcreteFiber] = []
    current_top = 0.0
    for layer in layers:
        if layer.height_mm == 0:
            continue
        layer_material = materials.concrete[layer.concrete_class]
        share = layer.height_mm / section_height_mm
        fiber_count = max(1, int(round(fibers_per_section * share)))
        dz = layer.height_mm / fiber_count
        for index in range(fiber_count):
            z_mm = current_top + (index + 0.5) * dz
            fibers.append(
                _ConcreteFiber(
                    z_mm=z_mm,
                    area_mm2=layer.width_mm * dz,
                    material=layer_material,
                )
            )
        current_top += layer.height_mm
    return tuple(fibers)


def _concrete_material_at_depth(
    section: SectionInput,
    materials: MaterialCatalog,
    z_mm: float,
) -> ConcreteMaterial:
    top_layer = section.concrete_layers[0]
    bottom_layer = section.concrete_layers[1]
    boundary_mm = top_layer.height_mm
    if bottom_layer.height_mm == 0.0 or z_mm <= boundary_mm:
        return materials.concrete[top_layer.concrete_class]
    return materials.concrete[bottom_layer.concrete_class]


def _section_response(
    section: SectionInput,
    materials: MaterialCatalog,
    fibers: tuple[_ConcreteFiber, ...],
    top_strain: float,
    bottom_strain: float,
) -> tuple[float, float]:
    centroid_mm = section.section_centroid_mm
    axial_force_kN = 0.0
    moment_kNm = 0.0

    for fiber in fibers:
        strain = _strain_at_depth(top_strain, bottom_strain, fiber.z_mm, section.section_height_mm)
        stress_mpa = _concrete_stress_mpa(strain, fiber.material)
        force_kN = stress_mpa * fiber.area_mm2 / 1000.0
        axial_force_kN += force_kN
        moment_kNm += force_kN * (centroid_mm - fiber.z_mm) / 1000.0

    for rebar in section.rebar_layers:
        material = materials.steel[rebar.steel_class]
        strain = _strain_at_depth(top_strain, bottom_strain, rebar.z_mm, section.section_height_mm)
        stress_mpa = _steel_stress_mpa(strain, material)
        force_kN = stress_mpa * rebar.area_mm2 / 1000.0
        axial_force_kN += force_kN
        moment_kNm += force_kN * (centroid_mm - rebar.z_mm) / 1000.0

    return axial_force_kN, abs(moment_kNm)


def build_layer_force_table(
    section: SectionInput,
    materials: MaterialCatalog,
    point: CurvePoint,
    *,
    fibers_per_section: int = 120,
) -> tuple[dict[str, float | int | str], ...]:
    fibers = _build_fibers(section.concrete_layers, materials, section.section_height_mm, fibers_per_section)
    rows: list[dict[str, float | int | str]] = []
    concrete_totals = {1: 0.0, 2: 0.0}
    concrete_stress_sums = {1: 0.0, 2: 0.0}
    concrete_area_sums = {1: 0.0, 2: 0.0}
    boundary = section.concrete_layers[0].height_mm

    for fiber in fibers:
        strain = _strain_at_depth(point.top_strain, point.bottom_strain, fiber.z_mm, section.section_height_mm)
        stress_mpa = _concrete_stress_mpa(strain, fiber.material)
        force_kN = stress_mpa * fiber.area_mm2 / 1000.0
        layer_index = 1 if fiber.z_mm <= boundary or section.concrete_layers[1].height_mm == 0 else 2
        concrete_totals[layer_index] += force_kN
        concrete_stress_sums[layer_index] += stress_mpa * fiber.area_mm2
        concrete_area_sums[layer_index] += fiber.area_mm2

    start_z = 0.0
    for index, layer in enumerate(section.concrete_layers, start=1):
        if layer.height_mm == 0:
            rows.append(
                {
                    "kind": "concrete",
                    "index": index,
                    "class": layer.concrete_class,
                    "z_mm": start_z,
                    "area_mm2": 0.0,
                    "strain": 0.0,
                    "stress_mpa": 0.0,
                    "force_kN": 0.0,
                }
            )
            continue
        z_mid = start_z + layer.height_mm / 2.0
        avg_stress = (
            concrete_stress_sums[index] / concrete_area_sums[index]
            if concrete_area_sums[index] > 0
            else 0.0
        )
        rows.append(
            {
                "kind": "concrete",
                "index": index,
                "class": layer.concrete_class,
                "z_mm": z_mid,
                "area_mm2": layer.width_mm * layer.height_mm,
                "strain": _strain_at_depth(point.top_strain, point.bottom_strain, z_mid, section.section_height_mm),
                "stress_mpa": avg_stress,
                "force_kN": concrete_totals[index],
            }
        )
        start_z += layer.height_mm

    for index, rebar in enumerate(section.rebar_layers, start=1):
        material = materials.steel[rebar.steel_class]
        strain = _strain_at_depth(point.top_strain, point.bottom_strain, rebar.z_mm, section.section_height_mm)
        stress_mpa = _steel_stress_mpa(strain, material)
        rows.append(
            {
                "kind": "rebar",
                "index": index,
                "class": rebar.steel_class,
                "z_mm": rebar.z_mm,
                "area_mm2": rebar.area_mm2,
                "strain": strain,
                "stress_mpa": stress_mpa,
                "force_kN": stress_mpa * rebar.area_mm2 / 1000.0,
            }
        )
    return tuple(rows)


def classify_equilibrium_form(point: CurvePoint) -> str:
    return "first" if point.bottom_strain >= 0.0 else "second"


def find_comparison_curve_point(result: BendingResult, active_point: CurvePoint) -> CurvePoint | None:
    active_form = classify_equilibrium_form(active_point)
    opposite_form = "second" if active_form == "first" else "first"
    candidates = [
        point
        for point in result.curve_points
        if point.step_index != active_point.step_index and classify_equilibrium_form(point) == opposite_form
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda point: (
            abs(point.step_index - active_point.step_index),
            abs(point.curvature_1_per_m - active_point.curvature_1_per_m),
            point.step_index,
        ),
    )


def build_section_diagram_state(
    section: SectionInput,
    materials: MaterialCatalog,
    point: CurvePoint,
    *,
    sample_count: int = 61,
    fibers_per_section: int = 120,
    is_active: bool = True,
) -> SectionDiagramState:
    if sample_count < 2:
        sample_count = 2

    concrete_profile: list[ConcreteDiagramPoint] = []
    max_abs_strain = max(abs(point.top_strain), abs(point.bottom_strain))
    max_abs_stress = 0.0
    for index in range(sample_count):
        z_mm = section.section_height_mm * index / (sample_count - 1)
        material = _concrete_material_at_depth(section, materials, z_mm)
        strain = _strain_at_depth(point.top_strain, point.bottom_strain, z_mm, section.section_height_mm)
        stress_mpa = _concrete_stress_mpa(strain, material)
        concrete_profile.append(ConcreteDiagramPoint(z_mm=z_mm, strain=strain, stress_mpa=stress_mpa))
        max_abs_strain = max(max_abs_strain, abs(strain))
        max_abs_stress = max(max_abs_stress, abs(stress_mpa))

    rebar_states: list[RebarDiagramState] = []
    for index, rebar in enumerate(section.rebar_layers, start=1):
        material = materials.steel[rebar.steel_class]
        strain = _strain_at_depth(point.top_strain, point.bottom_strain, rebar.z_mm, section.section_height_mm)
        stress_mpa = _steel_stress_mpa(strain, material)
        force_kN = stress_mpa * rebar.area_mm2 / 1000.0
        rebar_states.append(
            RebarDiagramState(
                index=index,
                z_mm=rebar.z_mm,
                area_mm2=rebar.area_mm2,
                strain=strain,
                stress_mpa=stress_mpa,
                force_kN=force_kN,
                label=f"A{index}",
            )
        )
        max_abs_strain = max(max_abs_strain, abs(strain))
        max_abs_stress = max(max_abs_stress, abs(stress_mpa))

    fibers = _build_fibers(section.concrete_layers, materials, section.section_height_mm, fibers_per_section)
    concrete_force_kN = 0.0
    concrete_force_moment = 0.0
    for fiber in fibers:
        strain = _strain_at_depth(point.top_strain, point.bottom_strain, fiber.z_mm, section.section_height_mm)
        stress_mpa = _concrete_stress_mpa(strain, fiber.material)
        force_kN = stress_mpa * fiber.area_mm2 / 1000.0
        concrete_force_kN += force_kN
        concrete_force_moment += force_kN * fiber.z_mm

    concrete_resultant = (
        DiagramResultant(force_kN=concrete_force_kN, z_mm=concrete_force_moment / concrete_force_kN)
        if concrete_force_kN > 0.0
        else None
    )

    tension_rebars = [state for state in rebar_states if state.force_kN < 0.0]
    if concrete_resultant is not None and tension_rebars:
        tension_force_kN = sum(-state.force_kN for state in tension_rebars)
        tension_centroid_mm = sum((-state.force_kN) * state.z_mm for state in tension_rebars) / tension_force_kN
        lever_arm_mm: float | None = abs(tension_centroid_mm - concrete_resultant.z_mm)
    else:
        lever_arm_mm = None

    return SectionDiagramState(
        form=classify_equilibrium_form(point),
        point=point,
        is_active=is_active,
        concrete_profile=tuple(concrete_profile),
        rebar_states=tuple(rebar_states),
        concrete_resultant=concrete_resultant,
        lever_arm_mm=lever_arm_mm,
        scale_limits=DiagramScaleLimits(
            strain_abs_max=max(max_abs_strain, 1e-9),
            stress_abs_max_mpa=max(max_abs_stress, 1e-9),
        ),
    )


def _solve_bottom_strain(
    section: SectionInput,
    materials: MaterialCatalog,
    fibers: tuple[_ConcreteFiber, ...],
    top_strain: float,
    axial_tolerance_kN: float,
    max_inner_iterations: int,
    max_bottom_strain: float,
) -> tuple[float, float, tuple[InnerIterationRow, ...]]:
    lower = -max_bottom_strain
    upper = top_strain
    lower_force, _ = _section_response(section, materials, fibers, top_strain, lower)
    upper_force, _ = _section_response(section, materials, fibers, top_strain, upper)

    if lower_force > 0.0:
        raise ValueError("Lower strain bound did not produce tension-dominated equilibrium.")
    if upper_force < 0.0:
        raise ValueError("Upper strain bound did not produce compression-dominated equilibrium.")

    iterations: list[InnerIterationRow] = []
    trial = lower
    force = lower_force
    for iteration in range(1, max_inner_iterations + 1):
        trial = 0.5 * (lower + upper)
        force, _ = _section_response(section, materials, fibers, top_strain, trial)
        iterations.append(
            InnerIterationRow(
                outer_step=0,
                iteration=iteration,
                lower_bottom_strain=lower,
                upper_bottom_strain=upper,
                trial_bottom_strain=trial,
                axial_residual_kN=force,
            )
        )
        if abs(force) <= axial_tolerance_kN:
            break
        if force > 0.0:
            upper = trial
        else:
            lower = trial

    return trial, force, tuple(iterations)


def _build_strain_profile(section: SectionInput, point: CurvePoint, sample_count: int = 51) -> tuple[StrainProfilePoint, ...]:
    profile: list[StrainProfilePoint] = []
    if sample_count < 2:
        sample_count = 2
    for index in range(sample_count):
        z_mm = section.section_height_mm * index / (sample_count - 1)
        strain = _strain_at_depth(point.top_strain, point.bottom_strain, z_mm, section.section_height_mm)
        profile.append(StrainProfilePoint(z_mm=z_mm, strain=strain))
    return tuple(profile)


def build_strain_profile_for_point(
    section: SectionInput,
    point: CurvePoint,
    *,
    sample_count: int = 51,
) -> tuple[StrainProfilePoint, ...]:
    return _build_strain_profile(section, point, sample_count=sample_count)


def solve_bending_capacity(
    section: SectionInput,
    materials: MaterialCatalog,
    *,
    outer_steps: int = 40,
    fibers_per_section: int = 120,
    axial_tolerance_kN: float = 0.5,
    max_inner_iterations: int = 80,
) -> BendingResult:
    section.validate()
    fibers = _build_fibers(section.concrete_layers, materials, section.section_height_mm, fibers_per_section)
    max_top_strain = materials.concrete[section.concrete_layers[0].concrete_class].epsilon_cu1
    max_bottom_strain = max(materials.steel[layer.steel_class].epsilon_ud for layer in section.rebar_layers) * 0.99

    curve_points: list[CurvePoint] = []
    all_inner_iterations: list[InnerIterationRow] = []

    for step_index in range(1, outer_steps + 1):
        top_strain = max_top_strain * step_index / outer_steps
        try:
            bottom_strain, residual, iterations = _solve_bottom_strain(
                section,
                materials,
                fibers,
                top_strain,
                axial_tolerance_kN,
                max_inner_iterations,
                max_bottom_strain,
            )
        except ValueError:
            if curve_points:
                break
            raise
        axial_force_kN, moment_kNm = _section_response(section, materials, fibers, top_strain, bottom_strain)
        curvature_1_per_m = (top_strain - bottom_strain) / (section.section_height_mm / 1000.0)
        neutral_axis_mm = (
            section.section_height_mm
            if curvature_1_per_m == 0
            else top_strain / (top_strain - bottom_strain) * section.section_height_mm
        )
        point = CurvePoint(
            step_index=step_index,
            top_strain=top_strain,
            bottom_strain=bottom_strain,
            curvature_1_per_m=curvature_1_per_m,
            neutral_axis_mm=neutral_axis_mm,
            axial_residual_kN=axial_force_kN,
            moment_kNm=moment_kNm,
            state_label="whole_compression" if bottom_strain >= 0 else "bending_with_tension",
        )
        curve_points.append(point)
        all_inner_iterations.extend(
            InnerIterationRow(
                outer_step=step_index,
                iteration=row.iteration,
                lower_bottom_strain=row.lower_bottom_strain,
                upper_bottom_strain=row.upper_bottom_strain,
                trial_bottom_strain=row.trial_bottom_strain,
                axial_residual_kN=row.axial_residual_kN,
            )
            for row in iterations
        )
        if abs(residual) > axial_tolerance_kN * 10:
            break

    peak_point = max(curve_points, key=lambda point: point.moment_kNm)
    return BendingResult(
        curve_points=tuple(curve_points),
        peak_point=peak_point,
        peak_moment_kNm=peak_point.moment_kNm,
        strain_profile=_build_strain_profile(section, peak_point),
        inner_iterations=tuple(all_inner_iterations),
    )
