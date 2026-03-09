# `rc_bending` Folder

This folder stores the Python package for the two-layer concrete bending calculator.

## Contents
- `__init__.py` - package marker.
- `external_validation.py` - canonical external-validation case definition, EurocodeApplied submission/parsing logic, tolerance comparison, workbook generation, and live run helpers.
- `external_validation_runner.py` - command-line entrypoint that runs the strict EurocodeApplied validation benchmark and writes the Excel report.
- `export.py` - builds the Excel workbook with result tables and native charts.
- `materials.py` - loads the machine-readable DBN/DSTU material catalog.
- `models.py` - validated input dataclasses used by the solver, export, and UI layers.
- `solver.py` - computes the pure-bending moment-curvature response for a layered reinforced-concrete section.
- `ui_helpers.py` - lightweight helpers for Streamlit session-state row management and input conversion.
