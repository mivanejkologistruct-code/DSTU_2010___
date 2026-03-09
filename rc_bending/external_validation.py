from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from io import BytesIO, StringIO
from pathlib import Path
import http.cookiejar
import re
import subprocess
import urllib.parse
import urllib.request

from openpyxl import Workbook
from pandas import read_html

from rc_bending.materials import MaterialCatalog
from rc_bending.models import ConcreteLayerInput, RebarLayerInput, SectionInput
from rc_bending.solver import solve_bending_capacity


EUROCODEAPPLIED_URL = "https://eurocodeapplied.com/design/en1992/uls-design-rectangular-section"
DEFAULT_MCP_PROFILE_DIR = Path.home() / "AppData" / "Local" / "ms-playwright" / "mcp-chrome"


@dataclass(frozen=True)
class ValidationCase:
    name: str
    description: str
    section: SectionInput
    moment_tolerance_ratio: float
    secondary_tolerance_ratio: float
    concrete_class: str | None = None
    steel_class: str | None = None
    bar_count_per_layer: int | None = None
    bar_diameter_mm: int | None = None
    cover_mm: float | None = None


@dataclass(frozen=True)
class EurocodeAppliedSubmission:
    source_url: str
    fields: dict[str, str]


@dataclass(frozen=True)
class LocalValidationResult:
    moment_kNm: float
    neutral_axis_depth_mm: float
    top_concrete_strain: float
    bottom_concrete_strain: float
    axial_residual_kN: float


@dataclass(frozen=True)
class ExternalValidationResult:
    source_url: str
    moment_kNm: float
    neutral_axis_depth_mm: float
    top_concrete_strain: float
    bottom_concrete_strain: float
    raw_row_index: int


@dataclass(frozen=True)
class MetricComparison:
    label: str
    local_value: float
    external_value: float
    relative_error_ratio: float
    tolerance_ratio: float
    passed: bool


@dataclass(frozen=True)
class ValidationComparison:
    passed: bool
    metrics: dict[str, MetricComparison]


@dataclass(frozen=True)
class EvidenceArtifact:
    label: str
    path: str
    description: str


@dataclass(frozen=True)
class ValidationRunResult:
    case: ValidationCase
    local_result: LocalValidationResult
    external_result: ExternalValidationResult | None
    comparison: ValidationComparison | None
    evidence: tuple[EvidenceArtifact, ...]
    status: str
    message: str
    executed_at: str


def build_default_validation_case(catalog: MaterialCatalog) -> ValidationCase:
    bar_count = 2
    bar_diameter_mm = 20
    area_mm2 = bar_count * catalog.rebar_area_mm2[bar_diameter_mm]
    section = SectionInput(
        section_height_mm=500.0,
        concrete_layers=(
            ConcreteLayerInput(width_mm=300.0, height_mm=250.0, concrete_class="C25/30"),
            ConcreteLayerInput(width_mm=300.0, height_mm=250.0, concrete_class="C25/30"),
        ),
        rebar_layers=(
            RebarLayerInput(z_mm=40.0, area_mm2=area_mm2, steel_class="B500"),
            RebarLayerInput(z_mm=460.0, area_mm2=area_mm2, steel_class="B500"),
        ),
    )
    return ValidationCase(
        name="canonical_homogeneous_rectangular_section",
        description="Homogeneous rectangular section benchmark aligned to EurocodeApplied MRd workflow.",
        section=section,
        moment_tolerance_ratio=0.01,
        secondary_tolerance_ratio=0.10,
        concrete_class="C25/30",
        steel_class="B500",
        bar_count_per_layer=bar_count,
        bar_diameter_mm=bar_diameter_mm,
        cover_mm=40.0,
    )


def build_eurocodeapplied_submission(case: ValidationCase) -> EurocodeAppliedSubmission:
    if case.bar_count_per_layer is None or case.bar_diameter_mm is None or case.cover_mm is None:
        raise ValueError("Validation case is missing EurocodeApplied reinforcement metadata.")

    h_m = case.section.section_height_mm / 1000.0
    width_top = case.section.concrete_layers[0].width_mm
    width_bottom = case.section.concrete_layers[1].width_mm
    if abs(width_top - width_bottom) > 1e-9:
        raise ValueError("EurocodeApplied submission requires constant section width.")
    b_m = width_top / 1000.0
    cover_m = case.cover_mm / 1000.0

    fields = {
        "Calculation.AnalysisType": "1",
        "Calculation.fck": "25",
        "Calculation.fyk": "500",
        "Calculation.ReinforcementLaw": "0",
        "Calculation.epsilonuk": "12",
        "Calculation.h": _format_decimal(h_m),
        "Calculation.b": _format_decimal(b_m),
        "Calculation.nBars1": str(case.bar_count_per_layer),
        "Calculation.Phi1": str(case.bar_diameter_mm),
        "Calculation.cPrime1": _format_decimal(cover_m),
        "Calculation.nBars2": str(case.bar_count_per_layer),
        "Calculation.Phi2": str(case.bar_diameter_mm),
        "Calculation.cPrime2": _format_decimal(cover_m),
        "Calculation.nBars3": "0",
        "Calculation.Phi3": "12",
        "Calculation.MEd": "0",
        "Calculation.NEd": "0",
        "Calculation.VariableReinforcementLayers": "0",
        "Calculation.acc": "0.85",
        "Calculation.gammaC": "1.25",
        "Calculation.gammaS": "1.2",
        "Calculation.epsilonudRule": "6",
        "Calculation._gammaC": "Default",
        "Calculation._gammaS": "Default",
        "Calculation._epsilonudRule": "Default",
    }
    return EurocodeAppliedSubmission(source_url=EUROCODEAPPLIED_URL, fields=fields)


def build_local_validation_result(
    case: ValidationCase,
    catalog: MaterialCatalog,
    *,
    outer_steps: int = 200,
    fibers_per_section: int = 1000,
    axial_tolerance_kN: float = 0.05,
    max_inner_iterations: int = 120,
) -> LocalValidationResult:
    result = solve_bending_capacity(
        case.section,
        catalog,
        outer_steps=outer_steps,
        fibers_per_section=fibers_per_section,
        axial_tolerance_kN=axial_tolerance_kN,
        max_inner_iterations=max_inner_iterations,
    )
    peak = result.peak_point
    return LocalValidationResult(
        moment_kNm=result.peak_moment_kNm,
        neutral_axis_depth_mm=peak.neutral_axis_mm,
        top_concrete_strain=peak.top_strain,
        bottom_concrete_strain=peak.bottom_strain,
        axial_residual_kN=peak.axial_residual_kN,
    )


def fetch_eurocodeapplied_result(submission: EurocodeAppliedSubmission) -> tuple[ExternalValidationResult, str]:
    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    initial_response = opener.open(submission.source_url)
    initial_html = initial_response.read().decode("utf-8", errors="ignore")
    token_match = re.search(r'name="__RequestVerificationToken" type="hidden" value="([^"]+)"', initial_html)
    if token_match is None:
        raise ValueError("EurocodeApplied verification token was not found in the response.")

    payload = dict(submission.fields)
    payload["__RequestVerificationToken"] = token_match.group(1)
    body = urllib.parse.urlencode(payload).encode()
    request = urllib.request.Request(
        submission.source_url,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0",
        },
    )
    response_html = opener.open(request).read().decode("utf-8", errors="ignore")
    return parse_eurocodeapplied_response(response_html, source_url=submission.source_url), response_html


def parse_eurocodeapplied_response(html: str, *, source_url: str) -> ExternalValidationResult:
    tables = read_html(StringIO(html))
    target_row: tuple[int, object, list[str]] | None = None

    for table in tables:
        flattened_columns = [_flatten_column_name(column) for column in table.columns]
        row_index = _find_column_index(flattened_columns, "design bending moment resistance", "mrd")
        x_index = _find_column_index(flattened_columns, "depth of compressive zone", "x [m]")
        top_strain_index = _find_column_index(flattened_columns, "top concrete strain")
        bottom_strain_index = _find_column_index(flattened_columns, "bottom concrete strain")
        if None in {row_index, x_index, top_strain_index, bottom_strain_index}:
            continue

        positive_rows = table[table.iloc[:, row_index] > 0]
        if positive_rows.empty:
            continue

        selected_index = positive_rows.iloc[:, row_index].astype(float).idxmax()
        target_row = (selected_index, positive_rows.loc[selected_index], flattened_columns)
        break

    if target_row is None:
        raise ValueError("EurocodeApplied response did not contain a positive MRd result row.")

    raw_index, row, flattened_columns = target_row
    mr_d = float(row.iloc[_find_column_index(flattened_columns, "design bending moment resistance", "mrd")])
    x_m = float(row.iloc[_find_column_index(flattened_columns, "depth of compressive zone", "x [m]")])
    top_permille = float(row.iloc[_find_column_index(flattened_columns, "top concrete strain")])
    bottom_permille = float(row.iloc[_find_column_index(flattened_columns, "bottom concrete strain")])

    return ExternalValidationResult(
        source_url=source_url,
        moment_kNm=mr_d,
        neutral_axis_depth_mm=x_m * 1000.0,
        top_concrete_strain=abs(top_permille) / 1000.0,
        bottom_concrete_strain=-abs(bottom_permille) / 1000.0,
        raw_row_index=int(raw_index) + 1,
    )


def compare_validation_results(
    case: ValidationCase,
    local: LocalValidationResult,
    external: ExternalValidationResult,
) -> ValidationComparison:
    metrics = {
        "moment_kNm": _build_metric(
            "Moment resistance M_Rd [kNm]",
            local.moment_kNm,
            external.moment_kNm,
            case.moment_tolerance_ratio,
        ),
        "neutral_axis_depth_mm": _build_metric(
            "Neutral-axis depth x [mm]",
            local.neutral_axis_depth_mm,
            external.neutral_axis_depth_mm,
            case.secondary_tolerance_ratio,
        ),
        "top_concrete_strain": _build_metric(
            "Top concrete strain epsilon_c,top [-]",
            local.top_concrete_strain,
            external.top_concrete_strain,
            case.secondary_tolerance_ratio,
        ),
        "bottom_concrete_strain": _build_metric(
            "Bottom concrete strain epsilon_c,bot [-]",
            abs(local.bottom_concrete_strain),
            abs(external.bottom_concrete_strain),
            case.secondary_tolerance_ratio,
        ),
    }
    return ValidationComparison(
        passed=all(metric.passed for metric in metrics.values()),
        metrics=metrics,
    )


def build_validation_workbook_bytes(run_result: ValidationRunResult) -> bytes:
    workbook = Workbook()
    summary = workbook.active
    summary.title = "Summary"
    summary.append(["Field", "Value"])
    summary.append(["Status", run_result.status])
    summary.append(["Message", run_result.message])
    summary.append(["Executed At", run_result.executed_at])
    summary.append(["Case", run_result.case.name])
    summary.append(["Source URL", run_result.external_result.source_url if run_result.external_result else EUROCODEAPPLIED_URL])

    case_sheet = workbook.create_sheet("CaseInputs")
    case_sheet.append(["Field", "Value"])
    case_sheet.append(["name", run_result.case.name])
    case_sheet.append(["description", run_result.case.description])
    case_sheet.append(["section_height_mm", run_result.case.section.section_height_mm])
    for index, layer in enumerate(run_result.case.section.concrete_layers, start=1):
        case_sheet.append([f"concrete_{index}_class", layer.concrete_class])
        case_sheet.append([f"concrete_{index}_width_mm", layer.width_mm])
        case_sheet.append([f"concrete_{index}_height_mm", layer.height_mm])
    for index, layer in enumerate(run_result.case.section.rebar_layers, start=1):
        case_sheet.append([f"rebar_{index}_z_mm", layer.z_mm])
        case_sheet.append([f"rebar_{index}_area_mm2", layer.area_mm2])
        case_sheet.append([f"rebar_{index}_steel_class", layer.steel_class])

    local_sheet = workbook.create_sheet("LocalResults")
    local_sheet.append(["Metric", "Value"])
    local_sheet.append(["moment_kNm", run_result.local_result.moment_kNm])
    local_sheet.append(["neutral_axis_depth_mm", run_result.local_result.neutral_axis_depth_mm])
    local_sheet.append(["top_concrete_strain", run_result.local_result.top_concrete_strain])
    local_sheet.append(["bottom_concrete_strain", run_result.local_result.bottom_concrete_strain])
    local_sheet.append(["axial_residual_kN", run_result.local_result.axial_residual_kN])

    external_sheet = workbook.create_sheet("EurocodeAppliedResults")
    external_sheet.append(["Metric", "Value"])
    if run_result.external_result is not None:
        external_sheet.append(["source_url", run_result.external_result.source_url])
        external_sheet.append(["moment_kNm", run_result.external_result.moment_kNm])
        external_sheet.append(["neutral_axis_depth_mm", run_result.external_result.neutral_axis_depth_mm])
        external_sheet.append(["top_concrete_strain", run_result.external_result.top_concrete_strain])
        external_sheet.append(["bottom_concrete_strain", run_result.external_result.bottom_concrete_strain])
        external_sheet.append(["raw_row_index", run_result.external_result.raw_row_index])
    else:
        external_sheet.append(["status", "missing"])

    comparison_sheet = workbook.create_sheet("Comparison")
    comparison_sheet.append(["Metric", "Local", "External", "Relative Error", "Tolerance", "Passed"])
    if run_result.comparison is not None:
        for key, metric in run_result.comparison.metrics.items():
            comparison_sheet.append(
                [
                    key,
                    metric.local_value,
                    metric.external_value,
                    metric.relative_error_ratio,
                    metric.tolerance_ratio,
                    "yes" if metric.passed else "no",
                ]
            )
    else:
        comparison_sheet.append(["status", "", "", "", "", "missing"])

    evidence_sheet = workbook.create_sheet("Evidence")
    evidence_sheet.append(["Label", "Path", "Description"])
    for artifact in run_result.evidence:
        evidence_sheet.append([artifact.label, artifact.path, artifact.description])

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def select_mcp_profile_processes(rows: list[dict[str, object]], profile_dir: str | Path) -> list[dict[str, object]]:
    normalized_profile = str(profile_dir).lower()
    matches: list[dict[str, object]] = []
    for row in rows:
        name = str(row.get("Name", "")).lower()
        command_line = row.get("CommandLine")
        if name != "chrome.exe" or not isinstance(command_line, str):
            continue
        if normalized_profile in command_line.lower():
            matches.append(row)
    return matches


def list_windows_processes() -> list[dict[str, object]]:
    command = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -match 'chrome|msedge' } | "
        "Select-Object Name, ProcessId, CommandLine | ConvertTo-Json -Depth 2"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        check=True,
        capture_output=True,
        text=True,
    )
    raw_output = completed.stdout.strip()
    if not raw_output:
        return []
    import json

    parsed = json.loads(raw_output)
    if isinstance(parsed, dict):
        return [parsed]
    return list(parsed)


def stabilize_mcp_profile(profile_dir: Path = DEFAULT_MCP_PROFILE_DIR) -> list[str]:
    messages: list[str] = []
    try:
        processes = list_windows_processes()
    except subprocess.CalledProcessError as error:
        return [f"Failed to inspect browser processes: {error.stderr.strip() or error.stdout.strip()}"]

    matches = select_mcp_profile_processes(processes, profile_dir)
    for row in matches:
        process_id = int(row["ProcessId"])
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", f"Stop-Process -Id {process_id} -Force"],
            check=False,
            capture_output=True,
            text=True,
        )
        messages.append(f"Stopped chrome process {process_id} using MCP profile.")

    lockfile = profile_dir / "lockfile"
    if lockfile.exists():
        lockfile.unlink()
        messages.append(f"Removed stale lockfile at {lockfile}.")

    if not messages:
        messages.append("MCP profile directory was already clear.")
    return messages


def ensure_output_directories(base_dir: Path) -> tuple[Path, Path]:
    spreadsheet_dir = base_dir / "output" / "spreadsheet"
    playwright_dir = base_dir / "output" / "playwright"
    spreadsheet_dir.mkdir(parents=True, exist_ok=True)
    playwright_dir.mkdir(parents=True, exist_ok=True)
    return spreadsheet_dir, playwright_dir


def run_default_validation(
    base_dir: Path,
    catalog: MaterialCatalog,
    *,
    evidence_paths: tuple[str, ...] = (),
    execute_preflight: bool = True,
) -> tuple[ValidationRunResult, str]:
    if execute_preflight:
        stabilize_mcp_profile()

    case = build_default_validation_case(catalog)
    local_result = build_local_validation_result(case, catalog)
    submission = build_eurocodeapplied_submission(case)
    external_result, response_html = fetch_eurocodeapplied_result(submission)
    comparison = compare_validation_results(case, local_result, external_result)
    evidence = tuple(
        EvidenceArtifact(
            label=f"Evidence {index}",
            path=str(path),
            description="Browser artifact recorded during external validation.",
        )
        for index, path in enumerate(evidence_paths, start=1)
    )
    run_result = ValidationRunResult(
        case=case,
        local_result=local_result,
        external_result=external_result,
        comparison=comparison,
        evidence=evidence,
        status="passed" if comparison.passed else "failed",
        message="Validation completed." if comparison.passed else "Validation exceeded the configured tolerance profile.",
        executed_at=datetime.now().astimezone().isoformat(timespec="seconds"),
    )

    _, playwright_dir = ensure_output_directories(base_dir)
    response_path = playwright_dir / "eurocodeapplied_response.html"
    response_path.write_text(response_html, encoding="utf-8")
    if evidence_paths:
        return run_result, response_html

    run_result = ValidationRunResult(
        case=run_result.case,
        local_result=run_result.local_result,
        external_result=run_result.external_result,
        comparison=run_result.comparison,
        evidence=(
            EvidenceArtifact(
                label="EurocodeApplied HTML",
                path=str(response_path),
                description="Saved HTML response used for result extraction.",
            ),
        ),
        status=run_result.status,
        message=run_result.message,
        executed_at=run_result.executed_at,
    )
    return run_result, response_html


def _build_metric(label: str, local_value: float, external_value: float, tolerance_ratio: float) -> MetricComparison:
    relative_error_ratio = _relative_error_ratio(local_value, external_value)
    return MetricComparison(
        label=label,
        local_value=local_value,
        external_value=external_value,
        relative_error_ratio=relative_error_ratio,
        tolerance_ratio=tolerance_ratio,
        passed=relative_error_ratio <= tolerance_ratio,
    )


def _relative_error_ratio(local_value: float, external_value: float) -> float:
    denominator = max(abs(local_value), abs(external_value), 1e-9)
    return abs(local_value - external_value) / denominator


def _flatten_column_name(column: object) -> str:
    if isinstance(column, tuple):
        parts = [str(part).strip() for part in column if str(part).strip() and "unnamed" not in str(part).lower()]
        return " ".join(parts).lower()
    return str(column).strip().lower()


def _find_column_index(columns: list[str], *keywords: str) -> int | None:
    normalized_keywords = [keyword.lower() for keyword in keywords]
    for index, column in enumerate(columns):
        if all(keyword in column for keyword in normalized_keywords):
            return index
    return None


def _format_decimal(value: float) -> str:
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text if text else "0"
