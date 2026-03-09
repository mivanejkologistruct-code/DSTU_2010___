from __future__ import annotations

import argparse
from pathlib import Path
import sys

from rc_bending.external_validation import (
    build_validation_workbook_bytes,
    ensure_output_directories,
    run_default_validation,
)
from rc_bending.materials import load_material_catalog


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the strict external validation benchmark.")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to the generated XLSX report. Defaults to output/spreadsheet/external_validation_report.xlsx.",
    )
    parser.add_argument(
        "--evidence",
        action="append",
        default=[],
        help="Optional evidence artifact path to record in the workbook. Repeat for multiple files.",
    )
    parser.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Skip MCP profile cleanup before the live validation request.",
    )
    args = parser.parse_args(argv)

    base_dir = Path(__file__).resolve().parent.parent
    spreadsheet_dir, _ = ensure_output_directories(base_dir)
    output_path = args.output or (spreadsheet_dir / "external_validation_report.xlsx")

    catalog = load_material_catalog()
    run_result, _ = run_default_validation(
        base_dir,
        catalog,
        evidence_paths=tuple(args.evidence),
        execute_preflight=not args.skip_preflight,
    )
    workbook_bytes = build_validation_workbook_bytes(run_result)
    output_path.write_bytes(workbook_bytes)

    print(f"Report written to {output_path}")
    print(f"Status: {run_result.status}")
    print(run_result.message)
    if run_result.comparison is not None:
        for key, metric in run_result.comparison.metrics.items():
            print(
                f"{key}: local={metric.local_value:.6f}, external={metric.external_value:.6f}, "
                f"relative_error={metric.relative_error_ratio:.6%}, passed={metric.passed}"
            )
    return 0 if run_result.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
