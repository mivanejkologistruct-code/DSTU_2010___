from __future__ import annotations

from rc_bending.materials import MaterialCatalog
from rc_bending.models import (
    CrackWidthResult,
    CurrentPointSnapshot,
    CurvePoint,
    DeflectionLimitResult,
    DeflectionResult,
    SectionInput,
    ServiceabilityInput,
    ServiceabilityReport,
)
from rc_bending.ui_helpers import default_serviceability_inputs, derive_draft_geometry


SUPPORT_SCHEME_LABELS = {
    "cantilever_uniform": "Консольна балка з рівномірно розподіленим навантаженням",
    "simply_supported_uniform": "Балка на двох опорах з рівномірно розподіленим навантаженням",
    "cantilever_tip_point": "Консольна балка з зосередженою силою на вільному кінці",
    "simply_supported_center_point": "Балка на двох опорах з зосередженою силою посередині прольоту",
    "cantilever_point_at_a": "Консольна балка з зосередженою силою на відстані a від защемлення",
    "simply_supported_two_point_symmetric": "Балка на двох опорах з двома однаковими зосередженими силами",
}

DEFLECTION_LIMIT_PROFILE_LABELS = {
    "aesthetic_open_view": "Естетико-психологічні",
    "partition_gap": "Конструктивні при наявності перегородок",
    "cracking_sensitive_finish": "Конструктивні при наявності елементів, що розтріскуються",
    "lintel_or_glazing_beam": "Перемички / ригелі скління",
    "fallback_unspecified": "Fallback за 4.6",
    "cantilever_fallback": "Fallback для консолі за 4.6",
}

LOAD_DURATION_LABELS = {
    "short_term": "Короткочасне",
    "long_term": "Довготривале",
}

DEFAULT_SERVICEABILITY_INPUTS = default_serviceability_inputs()


def _strain_at_depth(top_strain: float, bottom_strain: float, z_mm: float, section_height_mm: float) -> float:
    if section_height_mm == 0.0:
        return 0.0
    return top_strain + (bottom_strain - top_strain) * z_mm / section_height_mm


def _steel_stress_mpa(strain: float, material) -> float:
    if abs(strain) >= material.epsilon_ud:
        return 0.0
    elastic = material.e_s_mpa * strain
    if elastic > material.f_yd_mpa:
        return material.f_yd_mpa
    if elastic < -material.f_yd_mpa:
        return -material.f_yd_mpa
    return elastic


def _resolve_tension_face(point: CurvePoint) -> str | None:
    top_tension = point.top_strain < 0.0
    bottom_tension = point.bottom_strain < 0.0
    if not top_tension and not bottom_tension:
        return None
    if top_tension and not bottom_tension:
        return "top"
    if bottom_tension and not top_tension:
        return "bottom"
    return "top" if abs(point.top_strain) >= abs(point.bottom_strain) else "bottom"


def _derive_bar_spacing_mm(section_width_mm: float, cover_mm: float, diameter_mm: float, bar_count: float | None) -> float | None:
    if bar_count is None or bar_count <= 1:
        return None
    center_cover_mm = cover_mm + diameter_mm / 2.0
    free_width_mm = max(0.0, section_width_mm - 2.0 * center_cover_mm)
    if free_width_mm <= 0.0:
        return diameter_mm
    return free_width_mm / (bar_count - 1)


def build_serviceability_input(draft_inputs: dict[str, object]) -> ServiceabilityInput:
    raw = dict(DEFAULT_SERVICEABILITY_INPUTS)
    serviceability_block = draft_inputs.get("serviceability")
    if isinstance(serviceability_block, dict):
        raw.update(serviceability_block)
    else:
        raw.update(draft_inputs)
    return ServiceabilityInput(
        span_mm=float(raw["span_mm"]),
        support_scheme=str(raw["support_scheme"]),
        a_mm=None if raw.get("a_mm") in {None, ""} else float(raw["a_mm"]),
        phi_creep=max(0.0, float(raw["phi_creep"])),
        deflection_limit_profile=str(raw["deflection_limit_profile"]),
        available_gap_mm=None if raw.get("available_gap_mm") in {None, ""} else float(raw["available_gap_mm"]),
        w_limit_mm=float(raw["w_limit_mm"]),
        load_duration=str(raw["load_duration"]),
    )


def validate_serviceability_inputs(serviceability_inputs: dict[str, object]) -> list[str]:
    errors: list[str] = []
    raw = dict(DEFAULT_SERVICEABILITY_INPUTS)
    raw.update(serviceability_inputs)

    def add_error(message: str) -> None:
        if message not in errors:
            errors.append(message)

    try:
        span_mm = float(raw["span_mm"])
    except (TypeError, ValueError):
        add_error("Розрахунковий проліт l має бути додатним числом.")
        span_mm = None
    else:
        if span_mm <= 0.0:
            add_error("Розрахунковий проліт l має бути додатним числом.")

    support_scheme = str(raw["support_scheme"])
    if support_scheme not in SUPPORT_SCHEME_LABELS:
        add_error("Розрахункова схема для прогину задана некоректно.")

    try:
        phi_creep = float(raw["phi_creep"])
    except (TypeError, ValueError):
        add_error("Коефіцієнт повзучості φ_creep має бути невід'ємним числом.")
    else:
        if phi_creep < 0.0:
            add_error("Коефіцієнт повзучості φ_creep має бути невід'ємним числом.")

    profile = str(raw["deflection_limit_profile"])
    if profile not in DEFLECTION_LIMIT_PROFILE_LABELS:
        add_error("Нормативний профіль обмеження прогину задано некоректно.")

    if profile == "partition_gap" and raw.get("available_gap_mm") not in {None, ""}:
        try:
            available_gap_mm = float(raw["available_gap_mm"])
        except (TypeError, ValueError):
            add_error("Допустимий зазор має бути невід'ємним числом.")
        else:
            if available_gap_mm < 0.0:
                add_error("Допустимий зазор має бути невід'ємним числом.")

    try:
        w_limit_mm = float(raw["w_limit_mm"])
    except (TypeError, ValueError):
        add_error("Гранична ширина тріщини w_lim має бути додатним числом.")
    else:
        if w_limit_mm <= 0.0:
            add_error("Гранична ширина тріщини w_lim має бути додатним числом.")

    load_duration = str(raw["load_duration"])
    if load_duration not in LOAD_DURATION_LABELS:
        add_error("Режим тривалості навантаження для тріщин задано некоректно.")

    if support_scheme in {"cantilever_point_at_a", "simply_supported_two_point_symmetric"}:
        try:
            a_mm = float(raw["a_mm"])
        except (TypeError, ValueError):
            add_error("Параметр a для обраної схеми має бути додатним числом.")
        else:
            if a_mm <= 0.0:
                add_error("Параметр a для обраної схеми має бути додатним числом.")
            elif span_mm is not None and a_mm >= span_mm:
                add_error("Параметр a для обраної схеми має бути меншим за проліт l.")

    return errors


def build_current_point_snapshot(
    section: SectionInput,
    draft_inputs: dict[str, object],
    selected_point: CurvePoint,
    catalog: MaterialCatalog,
) -> CurrentPointSnapshot:
    derived = derive_draft_geometry(draft_inputs)
    section_height_mm = float(derived["section_height_mm"])
    section_width_mm = float(derived["section_width_mm"])
    tension_face = _resolve_tension_face(selected_point)
    rebar_rows = list(derived["rebar_rows"])

    tension_index: int | None = None
    tension_row: dict[str, object] | None = None
    min_strain = 0.0
    for index, row in enumerate(rebar_rows, start=1):
        strain = _strain_at_depth(
            selected_point.top_strain,
            selected_point.bottom_strain,
            float(row["z_mm"]),
            section_height_mm,
        )
        if strain < min_strain:
            min_strain = strain
            tension_index = index
            tension_row = row

    if tension_face == "top":
        tension_zone_height_mm = max(0.0, min(selected_point.neutral_axis_mm, section_height_mm))
    elif tension_face == "bottom":
        tension_zone_height_mm = max(0.0, section_height_mm - selected_point.neutral_axis_mm)
    else:
        tension_zone_height_mm = None

    if tension_row is None or tension_face is None:
        return CurrentPointSnapshot(
            step_index=selected_point.step_index,
            moment_kNm=selected_point.moment_kNm,
            curvature_1_per_m=selected_point.curvature_1_per_m,
            neutral_axis_mm=selected_point.neutral_axis_mm,
            top_strain=selected_point.top_strain,
            bottom_strain=selected_point.bottom_strain,
            section_height_mm=section_height_mm,
            section_width_mm=section_width_mm,
            tension_face=tension_face,
            tension_zone_height_mm=tension_zone_height_mm,
            effective_tension_height_mm=None,
            effective_tension_area_mm2=None,
            tension_rebar_index=None,
            tension_rebar_area_mm2=None,
            tension_rebar_bar_count=None,
            tension_rebar_diameter_mm=None,
            tension_rebar_spacing_mm=None,
            tension_rebar_cover_mm=None,
            tension_rebar_depth_from_top_mm=None,
            tension_steel_class=None,
            tension_steel_stress_mpa=None,
            alpha_e=None,
        )

    z_mm = float(tension_row["z_mm"])
    diameter_mm = float(tension_row["diameter_mm"])
    bar_count = float(tension_row["bar_count"])
    area_mm2 = bar_count * catalog.rebar_area_mm2[int(tension_row["diameter_mm"])]
    cover_to_surface_mm = max(0.0, z_mm - diameter_mm / 2.0) if tension_face == "top" else max(
        0.0,
        section_height_mm - z_mm - diameter_mm / 2.0,
    )
    cover_to_centroid_mm = z_mm if tension_face == "top" else section_height_mm - z_mm
    effective_tension_height_mm = min(
        2.5 * cover_to_centroid_mm,
        (tension_zone_height_mm or 0.0) / 3.0 if tension_zone_height_mm else 0.0,
        section_height_mm / 2.0,
    )
    effective_tension_area_mm2 = section_width_mm * effective_tension_height_mm
    steel_class = str(tension_row["steel_class"])
    steel_material = catalog.steel[steel_class]
    strain = _strain_at_depth(
        selected_point.top_strain,
        selected_point.bottom_strain,
        z_mm,
        section_height_mm,
    )
    stress_mpa = abs(_steel_stress_mpa(strain, steel_material))
    tension_concrete_class = (
        section.concrete_layers[0].concrete_class if tension_face == "top" else section.concrete_layers[-1].concrete_class
    )
    tension_concrete = catalog.concrete[tension_concrete_class]
    bar_spacing_mm = _derive_bar_spacing_mm(section_width_mm, cover_to_surface_mm, diameter_mm, bar_count)
    alpha_e = steel_material.e_s_mpa / (tension_concrete.e_cm_gpa * 1000.0)

    return CurrentPointSnapshot(
        step_index=selected_point.step_index,
        moment_kNm=selected_point.moment_kNm,
        curvature_1_per_m=selected_point.curvature_1_per_m,
        neutral_axis_mm=selected_point.neutral_axis_mm,
        top_strain=selected_point.top_strain,
        bottom_strain=selected_point.bottom_strain,
        section_height_mm=section_height_mm,
        section_width_mm=section_width_mm,
        tension_face=tension_face,
        tension_zone_height_mm=tension_zone_height_mm,
        effective_tension_height_mm=effective_tension_height_mm,
        effective_tension_area_mm2=effective_tension_area_mm2,
        tension_rebar_index=tension_index,
        tension_rebar_area_mm2=area_mm2,
        tension_rebar_bar_count=bar_count,
        tension_rebar_diameter_mm=diameter_mm,
        tension_rebar_spacing_mm=bar_spacing_mm,
        tension_rebar_cover_mm=cover_to_surface_mm,
        tension_rebar_depth_from_top_mm=z_mm,
        tension_steel_class=steel_class,
        tension_steel_stress_mpa=stress_mpa,
        alpha_e=alpha_e,
    )


def _interpolate_aesthetic_divisor(span_mm: float) -> float:
    points = [
        (1000.0, 120.0),
        (3000.0, 150.0),
        (6000.0, 200.0),
        (24000.0, 250.0),
        (36000.0, 300.0),
    ]
    if span_mm <= points[0][0]:
        return points[0][1]
    if span_mm >= points[-1][0]:
        return points[-1][1]
    for (left_span, left_divisor), (right_span, right_divisor) in zip(points, points[1:], strict=True):
        if left_span <= span_mm <= right_span:
            ratio = (span_mm - left_span) / (right_span - left_span)
            return left_divisor + ratio * (right_divisor - left_divisor)
    return points[-1][1]


def calculate_deflection_limit(
    *,
    profile: str,
    span_mm: float,
    is_cantilever: bool,
    available_gap_mm: float | None,
) -> DeflectionLimitResult:
    effective_span_mm = span_mm * 2.0 if is_cantilever else span_mm
    if profile == "partition_gap":
        gap_mm = 40.0 if available_gap_mm is None else available_gap_mm
        return DeflectionLimitResult(
            profile=profile,
            limit_mm=gap_mm,
            rule_text=f"Граничний прогин визначено через фактичний зазор {gap_mm:.2f} мм.",
            requires_additional_data=available_gap_mm is None,
            warning_message="За замовчуванням використано типовий зазор 40 мм." if available_gap_mm is None else None,
        )
    if profile == "cracking_sensitive_finish":
        return DeflectionLimitResult(
            profile=profile,
            limit_mm=effective_span_mm / 150.0,
            rule_text=(
                "Граничний прогин = l/150 для елементів із шарами, що розтріскуються."
                if not is_cantilever
                else "Для консолі прийнято подвоєний виліт: граничний прогин = 2a/150."
            ),
            requires_additional_data=False,
        )
    if profile == "lintel_or_glazing_beam":
        return DeflectionLimitResult(
            profile=profile,
            limit_mm=effective_span_mm / 200.0,
            rule_text=(
                "Граничний прогин = l/200 для перемичок і ригелів скління."
                if not is_cantilever
                else "Для консолі прийнято подвоєний виліт: граничний прогин = 2a/200."
            ),
            requires_additional_data=False,
        )
    if profile == "cantilever_fallback":
        return DeflectionLimitResult(
            profile=profile,
            limit_mm=span_mm / 75.0,
            rule_text="Fallback за 4.6: 1/75 вильоту консолі.",
            requires_additional_data=False,
        )
    if profile == "fallback_unspecified":
        return DeflectionLimitResult(
            profile=profile,
            limit_mm=span_mm / 75.0 if is_cantilever else span_mm / 150.0,
            rule_text="Fallback за 4.6: 1/75 вильоту консолі." if is_cantilever else "Fallback за 4.6: 1/150 прольоту.",
            requires_additional_data=False,
        )

    divisor = _interpolate_aesthetic_divisor(effective_span_mm)
    return DeflectionLimitResult(
        profile=profile,
        limit_mm=effective_span_mm / divisor,
        rule_text=(
            f"Граничний прогин = l/{divisor:.2f} за естетико-психологічним профілем."
            if not is_cantilever
            else f"Для консолі прийнято подвоєний виліт: граничний прогин = 2a/{divisor:.2f}."
        ),
        requires_additional_data=False,
    )


def _resolve_k_m(support_scheme: str, span_mm: float, a_mm: float | None) -> float:
    span = span_mm / 1000.0
    a = None if a_mm is None else a_mm / 1000.0
    if support_scheme == "cantilever_uniform":
        return 1.0 / 4.0
    if support_scheme == "simply_supported_uniform":
        return 5.0 / 48.0
    if support_scheme == "cantilever_tip_point":
        return 1.0 / 3.0
    if support_scheme == "simply_supported_center_point":
        return 1.0 / 12.0
    if support_scheme == "cantilever_point_at_a" and a is not None and span > 0.0:
        return a / (6.0 * span) * (3.0 - a / span)
    if support_scheme == "simply_supported_two_point_symmetric" and a is not None and span > 0.0:
        return 1.0 / 8.0 - (a * a) / (6.0 * span * span)
    return 5.0 / 48.0


def calculate_deflection_mm(
    *,
    snapshot: CurrentPointSnapshot,
    span_mm: float,
    support_scheme: str,
    a_mm: float | None,
    phi_creep: float,
) -> float:
    return calculate_deflection_mm_from_curvature(
        curvature_1_per_m=snapshot.curvature_1_per_m,
        span_mm=span_mm,
        support_scheme=support_scheme,
        a_mm=a_mm,
        phi_creep=phi_creep,
    )


def calculate_deflection_mm_from_curvature(
    *,
    curvature_1_per_m: float,
    span_mm: float,
    support_scheme: str,
    a_mm: float | None,
    phi_creep: float,
) -> float:
    span_m = span_mm / 1000.0
    k_m = _resolve_k_m(support_scheme, span_mm, a_mm)
    effective_curvature = abs(curvature_1_per_m) * (1.0 + max(0.0, phi_creep))
    return effective_curvature * k_m * (span_m**2) * 1000.0


def calculate_crack_width_from_design_values(
    *,
    sigma_s_mpa: float,
    f_ct_eff_mpa: float,
    rho_p_eff: float,
    alpha_e: float,
    e_s_mpa: float,
    k_t: float,
    cover_mm: float,
    bar_diameter_mm: float,
    bar_spacing_mm: float | None,
    neutral_axis_depth_mm: float | None,
    section_height_mm: float,
    k_1: float,
    k_2: float,
    k_3: float,
    k_4: float,
    w_limit_mm: float,
) -> CrackWidthResult:
    if sigma_s_mpa <= 0.0 or rho_p_eff <= 0.0 or e_s_mpa <= 0.0:
        return CrackWidthResult(
            sigma_s_mpa=None,
            rho_p_eff=None,
            crack_spacing_mm=None,
            strain_difference=None,
            w_k_mm=0.0,
            w_limit_mm=w_limit_mm,
            is_within_limit=True,
            note="Напруження розтягу для розрахунку тріщин відсутнє.",
        )

    threshold_spacing = 5.0 * (cover_mm + bar_diameter_mm / 2.0)
    use_upper_bound = (
        neutral_axis_depth_mm is not None
        and bar_spacing_mm is not None
        and bar_spacing_mm > threshold_spacing
    )
    if use_upper_bound:
        crack_spacing_mm = 1.3 * max(0.0, section_height_mm - neutral_axis_depth_mm)
    else:
        crack_spacing_mm = k_3 * cover_mm + k_1 * k_2 * k_4 * bar_diameter_mm / rho_p_eff

    strain_difference = max(
        (sigma_s_mpa - k_t * f_ct_eff_mpa / rho_p_eff * (1.0 + alpha_e * rho_p_eff)) / e_s_mpa,
        0.6 * sigma_s_mpa / e_s_mpa,
    )
    w_k_mm = crack_spacing_mm * strain_difference
    return CrackWidthResult(
        sigma_s_mpa=sigma_s_mpa,
        rho_p_eff=rho_p_eff,
        crack_spacing_mm=crack_spacing_mm,
        strain_difference=strain_difference,
        w_k_mm=w_k_mm,
        w_limit_mm=w_limit_mm,
        is_within_limit=w_k_mm <= w_limit_mm,
        derived_bar_spacing_mm=bar_spacing_mm,
    )


def calculate_deflection_result(snapshot: CurrentPointSnapshot, service_input: ServiceabilityInput) -> DeflectionResult:
    is_cantilever = service_input.support_scheme.startswith("cantilever")
    limit = calculate_deflection_limit(
        profile=service_input.deflection_limit_profile,
        span_mm=service_input.span_mm,
        is_cantilever=is_cantilever,
        available_gap_mm=service_input.available_gap_mm,
    )
    k_m = _resolve_k_m(service_input.support_scheme, service_input.span_mm, service_input.a_mm)
    effective_curvature = abs(snapshot.curvature_1_per_m) * (1.0 + max(0.0, service_input.phi_creep))
    deflection_mm = calculate_deflection_mm(
        snapshot=snapshot,
        span_mm=service_input.span_mm,
        support_scheme=service_input.support_scheme,
        a_mm=service_input.a_mm,
        phi_creep=service_input.phi_creep,
    )
    return DeflectionResult(
        curvature_1_per_m=snapshot.curvature_1_per_m,
        effective_curvature_1_per_m=effective_curvature,
        support_scheme=service_input.support_scheme,
        k_m=k_m,
        span_mm=service_input.span_mm,
        a_mm=service_input.a_mm,
        deflection_mm=deflection_mm,
        limit=limit,
        is_within_limit=deflection_mm <= limit.limit_mm,
        note=limit.warning_message,
    )


def calculate_crack_width_result(
    snapshot: CurrentPointSnapshot,
    service_input: ServiceabilityInput,
    section: SectionInput,
    catalog: MaterialCatalog,
) -> CrackWidthResult:
    if (
        snapshot.tension_rebar_area_mm2 is None
        or snapshot.effective_tension_area_mm2 is None
        or snapshot.effective_tension_area_mm2 <= 0.0
        or snapshot.tension_steel_stress_mpa is None
        or snapshot.tension_rebar_diameter_mm is None
        or snapshot.tension_rebar_cover_mm is None
        or snapshot.alpha_e is None
        or snapshot.tension_face is None
    ):
        return CrackWidthResult(
            sigma_s_mpa=None,
            rho_p_eff=None,
            crack_spacing_mm=None,
            strain_difference=None,
            w_k_mm=0.0,
            w_limit_mm=service_input.w_limit_mm,
            is_within_limit=True,
            note="У вибраній точці не визначено розтягнуту арматуру для оцінки тріщин.",
        )

    concrete_class = (
        section.concrete_layers[0].concrete_class if snapshot.tension_face == "top" else section.concrete_layers[-1].concrete_class
    )
    concrete = catalog.concrete[concrete_class]
    rho_p_eff = snapshot.tension_rebar_area_mm2 / snapshot.effective_tension_area_mm2
    k_t = 0.6 if service_input.load_duration == "short_term" else 0.4
    return calculate_crack_width_from_design_values(
        sigma_s_mpa=snapshot.tension_steel_stress_mpa,
        f_ct_eff_mpa=concrete.f_ctm_mpa,
        rho_p_eff=rho_p_eff,
        alpha_e=snapshot.alpha_e,
        e_s_mpa=catalog.steel[snapshot.tension_steel_class].e_s_mpa if snapshot.tension_steel_class else 200000.0,
        k_t=k_t,
        cover_mm=snapshot.tension_rebar_cover_mm,
        bar_diameter_mm=snapshot.tension_rebar_diameter_mm,
        bar_spacing_mm=snapshot.tension_rebar_spacing_mm,
        neutral_axis_depth_mm=(
            snapshot.neutral_axis_mm if snapshot.tension_face == "bottom" else snapshot.section_height_mm - snapshot.neutral_axis_mm
        ),
        section_height_mm=snapshot.section_height_mm,
        k_1=0.8,
        k_2=0.5,
        k_3=3.4,
        k_4=0.425,
        w_limit_mm=service_input.w_limit_mm,
    )


def build_serviceability_report(
    section: SectionInput,
    draft_inputs: dict[str, object],
    selected_point: CurvePoint,
    catalog: MaterialCatalog,
    *,
    service_input: ServiceabilityInput | None = None,
) -> ServiceabilityReport:
    resolved_input = service_input or build_serviceability_input(draft_inputs)
    snapshot = build_current_point_snapshot(section, draft_inputs, selected_point, catalog)
    return ServiceabilityReport(
        input=resolved_input,
        snapshot=snapshot,
        crack_width=calculate_crack_width_result(snapshot, resolved_input, section, catalog),
        deflection=calculate_deflection_result(snapshot, resolved_input),
    )
