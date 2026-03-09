# `tests` Folder

This folder stores automated tests for the bending-calculator implementation.

## Contents
- `fixtures/` - static parser and regression fixtures used by the external-validation test suite.
- `test_materials.py` - verifies the material catalog shape, key DBN/DSTU values, and input validation rules before solver implementation exists.
- `test_solver.py` - checks the pure-bending fiber solver for axial equilibrium, homogeneous-layer reduction, and expected layered-concrete trends.
- `test_export_and_ui.py` - verifies Excel export structure, lightweight UI state helpers, and a Streamlit smoke render.
- `test_external_validation.py` - verifies the canonical external-validation case, EurocodeApplied mapping/parsing, tolerance comparison logic, workbook export, and MCP profile process filtering.
