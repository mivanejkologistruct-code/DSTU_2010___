# `rc_bending` Folder

This folder stores the Python package for the two-layer concrete bending calculator.

## Contents
- `__init__.py` - package marker.
- `experimental_data.py` - legacy-template loader plus one-sheet workbook inspection helpers for experimental curve imports and theory-vs-experiment comparison tables.
- `external_validation.py` - canonical external-validation case definition, EurocodeApplied submission/parsing logic, tolerance comparison, workbook generation, and live run helpers.
- `external_validation_runner.py` - command-line entrypoint that runs the strict EurocodeApplied validation benchmark and writes the Excel report.
- `export.py` - builds the Excel workbook with result tables and native charts.
- `materials.py` - loads the machine-readable DBN/DSTU material catalog.
- `models.py` - validated input dataclasses used by the solver, export, and UI layers.
- `section_drawing.py` - SVG section-drawing builder for the active point, layer dimensions, and equilibrium-form overlays in the Streamlit UI.
- `serviceability.py` - crack-width and deflection checks, code-based limit profiles, and derived serviceability report assembly.
- `serviceability_drawing.py` - serviceability-scheme SVG renderer for the II GGS tab.
- `solver.py` - computes the pure-bending moment-curvature response for a layered reinforced-concrete section.
- `ui_helpers.py` - lightweight helpers for Streamlit session-state row management and input conversion.
