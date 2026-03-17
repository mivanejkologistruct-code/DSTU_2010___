from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConcreteLayerInput:
    width_mm: float
    height_mm: float
    concrete_class: str

    def validate(self) -> None:
        if self.width_mm <= 0:
            raise ValueError("Concrete layer width must be positive.")
        if self.height_mm < 0:
            raise ValueError("Concrete layer height must be non-negative.")
        if not self.concrete_class:
            raise ValueError("Concrete layer class is required.")


@dataclass(frozen=True)
class RebarLayerInput:
    z_mm: float
    area_mm2: float
    steel_class: str
    bar_count: float | None = None
    diameter_mm: float | None = None
    face: str | None = None
    distance_mm: float | None = None

    def validate(self) -> None:
        if self.area_mm2 <= 0:
            raise ValueError("Rebar layer area must be positive.")
        if not self.steel_class:
            raise ValueError("Rebar layer class is required.")
        if self.bar_count is not None and self.bar_count <= 0:
            raise ValueError("Rebar layer bar count must be positive when provided.")
        if self.diameter_mm is not None and self.diameter_mm <= 0:
            raise ValueError("Rebar layer diameter must be positive when provided.")


@dataclass(frozen=True)
class SectionInput:
    section_height_mm: float
    concrete_layers: tuple[ConcreteLayerInput, ConcreteLayerInput]
    rebar_layers: tuple[RebarLayerInput, ...]

    @property
    def total_concrete_height_mm(self) -> float:
        return sum(layer.height_mm for layer in self.concrete_layers)

    @property
    def section_centroid_mm(self) -> float:
        return self.section_height_mm / 2.0

    def validate(self) -> None:
        if self.section_height_mm <= 0:
            raise ValueError("Section height must be positive.")
        if len(self.concrete_layers) != 2:
            raise ValueError("Exactly two concrete layers are required.")
        if not self.rebar_layers:
            raise ValueError("At least one rebar layer is required.")

        for layer in self.concrete_layers:
            layer.validate()
        for layer in self.rebar_layers:
            layer.validate()

        if abs(self.total_concrete_height_mm - self.section_height_mm) > 1e-9:
            raise ValueError("The sum of concrete layer heights must equal the section height.")

        for layer in self.rebar_layers:
            if not (0.0 <= layer.z_mm <= self.section_height_mm):
                raise ValueError("Each rebar layer must stay inside the section height.")


@dataclass(frozen=True)
class CurvePoint:
    step_index: int
    top_strain: float
    bottom_strain: float
    curvature_1_per_m: float
    neutral_axis_mm: float
    axial_residual_kN: float
    moment_kNm: float
    state_label: str


@dataclass(frozen=True)
class StrainProfilePoint:
    z_mm: float
    strain: float


@dataclass(frozen=True)
class InnerIterationRow:
    outer_step: int
    iteration: int
    lower_bottom_strain: float
    upper_bottom_strain: float
    trial_bottom_strain: float
    axial_residual_kN: float


@dataclass(frozen=True)
class CalculationTermination:
    reason_code: str
    last_step: int
    last_moment_kNm: float
    previous_step: int | None
    previous_moment_kNm: float | None
    attempted_step: int | None
    attempted_top_strain: float | None
    attempted_lower_force_kN: float | None
    attempted_upper_force_kN: float | None
    residual_kN: float


@dataclass(frozen=True)
class BendingResult:
    curve_points: tuple[CurvePoint, ...]
    peak_point: CurvePoint
    peak_moment_kNm: float
    strain_profile: tuple[StrainProfilePoint, ...]
    inner_iterations: tuple[InnerIterationRow, ...]
    termination: CalculationTermination


@dataclass(frozen=True)
class ChartLimitAnnotation:
    label: str
    target_strain: float
    moment_kNm: float | None
    within_chart_range: bool
    secondary_label: str | None = None
    secondary_strain: float | None = None


@dataclass(frozen=True)
class ConcreteDiagramPoint:
    z_mm: float
    strain: float
    stress_mpa: float


@dataclass(frozen=True)
class RebarDiagramState:
    index: int
    z_mm: float
    area_mm2: float
    strain: float
    stress_mpa: float
    force_kN: float
    label: str


@dataclass(frozen=True)
class DiagramResultant:
    force_kN: float
    z_mm: float


@dataclass(frozen=True)
class DiagramScaleLimits:
    strain_abs_max: float
    stress_abs_max_mpa: float


@dataclass(frozen=True)
class SectionDiagramState:
    form: str
    point: CurvePoint
    is_active: bool
    concrete_profile: tuple[ConcreteDiagramPoint, ...]
    rebar_states: tuple[RebarDiagramState, ...]
    concrete_resultant: DiagramResultant | None
    lever_arm_mm: float | None
    scale_limits: DiagramScaleLimits


@dataclass(frozen=True)
class ServiceabilityInput:
    span_mm: float
    support_scheme: str
    a_mm: float | None
    phi_creep: float
    deflection_limit_profile: str
    available_gap_mm: float | None
    w_limit_mm: float
    load_duration: str


@dataclass(frozen=True)
class CurrentPointSnapshot:
    step_index: int
    moment_kNm: float
    curvature_1_per_m: float
    neutral_axis_mm: float
    top_strain: float
    bottom_strain: float
    section_height_mm: float
    section_width_mm: float
    tension_face: str | None
    tension_zone_height_mm: float | None
    effective_tension_height_mm: float | None
    effective_tension_area_mm2: float | None
    tension_rebar_index: int | None
    tension_rebar_area_mm2: float | None
    tension_rebar_bar_count: float | None
    tension_rebar_diameter_mm: float | None
    tension_rebar_spacing_mm: float | None
    tension_rebar_cover_mm: float | None
    tension_rebar_depth_from_top_mm: float | None
    tension_steel_class: str | None
    tension_steel_stress_mpa: float | None
    alpha_e: float | None


@dataclass(frozen=True)
class DeflectionLimitResult:
    profile: str
    limit_mm: float
    rule_text: str
    requires_additional_data: bool
    warning_message: str | None = None


@dataclass(frozen=True)
class DeflectionResult:
    curvature_1_per_m: float
    effective_curvature_1_per_m: float
    support_scheme: str
    k_m: float
    span_mm: float
    a_mm: float | None
    deflection_mm: float
    limit: DeflectionLimitResult
    is_within_limit: bool
    note: str | None = None


@dataclass(frozen=True)
class CrackWidthResult:
    sigma_s_mpa: float | None
    rho_p_eff: float | None
    crack_spacing_mm: float | None
    strain_difference: float | None
    w_k_mm: float
    w_limit_mm: float
    is_within_limit: bool
    derived_bar_spacing_mm: float | None = None
    note: str | None = None


@dataclass(frozen=True)
class ServiceabilityReport:
    input: ServiceabilityInput
    snapshot: CurrentPointSnapshot
    crack_width: CrackWidthResult
    deflection: DeflectionResult
