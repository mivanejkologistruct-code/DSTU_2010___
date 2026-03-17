# `tests` Folder

This folder stores automated tests for the bending-calculator implementation.

## Contents
- `fixtures/` - static parser and regression fixtures used by the external-validation and experimental-workbook test suites.
- `test_experimental_data.py` - experimental workbook template generation, one-sheet detection, interpolation, and comparison-table regression tests.
- `test_materials.py` - verifies the material catalog shape, key DBN/DSTU values, and input validation rules before solver implementation exists.
- `test_export_and_ui.py` - verifies Excel export structure, lightweight UI state helpers, and a Streamlit smoke render.
- `test_external_validation.py` - verifies the canonical external-validation case, EurocodeApplied mapping/parsing, tolerance comparison logic, workbook export, and MCP profile process filtering.
- `test_mcp_live.py` - opt-in live MCP smoke tests that drive the local Streamlit app through the Playwright UI runner for section, serviceability, experimental, and template workflows.
- `test_mcp_server.py` - verifies the MCP adapters, tool-response envelopes, artifact writing, and fake-UI comparison paths for the local stdio server handlers.
- `test_section_drawing.py` - validates the SVG section-drawing layout, annotation content, and active-overlay rendering rules.
- `test_serviceability.py` - checks crack-width and deflection calculations, serviceability report assembly, and limit-profile behavior.
- `test_serviceability_scheme.py` - regression-tests the II GGS Streamlit layout and the serviceability-scheme explanatory content.
- `test_solver.py` - checks the pure-bending fiber solver for axial equilibrium, homogeneous-layer reduction, and expected layered-concrete trends.
