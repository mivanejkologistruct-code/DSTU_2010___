# Project Index

## Structure
- `.playwright-cli/` - transient Playwright CLI logs and YAML snapshots created during manual browser automation.
  - `README.md` - inventory of the transient Playwright CLI artifacts.
  - `console-2026-03-09T08-54-56-766Z.log` - console log captured from the live EurocodeApplied browser session.
  - `page-2026-03-09T08-54-57-627Z.yml` - initial page snapshot from the live EurocodeApplied browser session.
  - `page-2026-03-09T08-55-04-383Z.yml` - page snapshot after opening the EurocodeApplied form.
  - `page-2026-03-09T08-55-42-464Z.yml` - page snapshot after accepting cookies.
  - `page-2026-03-09T08-55-49-491Z.yml` - page snapshot after initial input edits.
  - `page-2026-03-09T08-56-12-353Z.yml` - page snapshot after switching the calculation to `MRd`.
  - `page-2026-03-09T08-56-23-658Z.yml` - page snapshot after updating Nationally Defined Parameters.
  - `page-2026-03-09T08-56-26-998Z.yml` - page snapshot immediately after clicking `Calculate`.
  - `page-2026-03-09T08-56-33-634Z.yml` - intermediate page snapshot during result capture.
  - `page-2026-03-09T08-56-48-121Z.yml` - final page snapshot containing the rendered result cards and details.
- `external_validation.md` - notes the selected online calculators for independent checks, their URLs, and the scope limits of online validation for the homogeneous-versus-two-layer use cases.
- `output/` - generated deliverables and evidence artifacts created by validation workflows.
  - `README.md` - description of the generated-output folders and their purposes.
  - `playwright/` - browser evidence captured during live external validation runs.
    - `README.md` - description of the browser-artifact output folder.
    - `eurocodeapplied_live.png` - full-page screenshot of the live EurocodeApplied benchmark run.
    - `eurocodeapplied_response.html` - saved HTML response from the EurocodeApplied live validation request.
  - `spreadsheet/` - generated spreadsheet deliverables.
    - `README.md` - description of the spreadsheet-output folder and the strict validation report name.
    - `external_validation_report.xlsx` - strict external validation report comparing the canonical benchmark case against EurocodeApplied with evidence links.
- `requirements.txt` - Python dependency list for running the Streamlit app, the local MCP server, Playwright UI automation, and automated tests.
- `streamlit_app.py` - Streamlit entrypoint for the pure-bending calculator UI with layered-concrete inputs, result charts, intermediate tables, export, external-validation links, and hidden automation payloads for browser-driven MCP runs.
- `нормативи/` - regulatory and methodological source materials used for reinforced concrete design checks.
  - `README.md` - English inventory of the folder with content-based descriptions of each source file.
  - `DodatokA_DSTU_B_V.2.6-156-2010.md` - Markdown transcription of Appendix A to `DSTU B V.2.6-156:2010`; describes the required input data, the three problem statements, and the 15-step iterative algorithm for solving the nonlinear equilibrium equations of a reinforced-concrete section by the deformation method.
  - `dstu-b-v-1-2-3-2006-progini-perem-shchennya.pdf` - `DSTU B V.1.2-3:2006` source document on allowable deflections and displacements used for the II GGS deflection-limit rules.
  - `DSTU_B_V.2.6-156-2010_DodatokA_scan.pdf` - three-page scan of Appendix A (the same algorithm as the Markdown transcription) for checking the transcription against the original standard pages.
  - `dstu_методика.md` - Markdown transcription of the Section 4 methodology extract from `DSTU B V.2.6-156:2010`; records the assumptions of the deformation method, formulas `4.1` to `4.12`, and the figure references used for rectangular-section analysis.
  - `dsty_b_v.2.6-156-2010.pdf` - full 123-page national standard `DSTU B V.2.6-156:2010`, "Concrete and reinforced concrete structures made of heavy concrete. Design rules".
  - `rozdil_5_dstu_fragment.md` - Markdown notes for the Section 5 serviceability provisions referenced by the crack-width and deflection explanations in the UI.
  - `ДБН В.2.6-982009.pdf` - 68-page DBN standard `DBN V.2.6-98:2009`, "Concrete and reinforced concrete structures. Basic provisions"; used as the source for material properties and design references.
  - `Методика розрахунку ДСТУ 2 ГГСpdf.pdf` - methodological extract focused on second-group limit-state checks and serviceability interpretation.
  - `Методика розрахунку ДСТУ.pdf` - five-page methodological extract from Section 4 of the DSTU standard with formulas `4.1` to `4.12` and Figures `4.1` and `4.2` for rectangular section analysis.
  - `рисунок 4.1.jpg` - figure showing the stress-strain state of a rectangular reinforced-concrete section and the two equilibrium forms used by the deformation method.
  - `рисунок 4.2.jpg` - figure showing the stress and strain diagrams for a rectangular section in the first equilibrium form.

- `розрахунок Exel/` - spreadsheet-based calculation files.
  - `README.md` - English description of the workbook and its calculation sheets.
  - `ДБН_11_.xlsx` - main calculation workbook with input data, normal-section checks, oblique-section checks, reference tables from DBN/DSTU, a nonlinear equation solver, unit settings, and a state-diagram sheet; the workbook has been reviewed for the known polynomial-table and solver-formula issues documented in the folder README.

- `plans/` - project planning journal.
  - `README.md` - English description of the planning folder and the journal maintenance rules.
  - `planned.md` - list of tasks that are planned or currently in progress.
  - `completed.md` - history of completed tasks with completion dates and outcomes.

- `materials/` - machine-readable DBN/DSTU-derived material datasets used by the calculator.
  - `README.md` - inventory of the material catalog files.
  - `concrete_dbn.json` - concrete strength classes, deformation parameters, and polynomial coefficients for the fiber solver.
  - `display_limits.json` - chart-display defaults and label-position presets consumed by the Streamlit visualization layer.
  - `steel_catalog.json` - reinforcement strength, modulus, ductility, and safety-factor data.
  - `rebar_area_mm2.json` - nominal rebar diameters and areas used to convert `count x diameter` into layer area.

- `rc_bending/` - Python package implementing the bending-calculator domain logic.
  - `README.md` - inventory of the package modules.
  - `__init__.py` - package marker.
  - `experimental_data.py` - legacy-template loader plus one-sheet workbook inspection helpers for experimental curve imports and theory-vs-experiment comparison tables.
  - `external_validation.py` - canonical EurocodeApplied validation case definition, live submission/parsing helpers, tolerance comparison, and workbook-report generation.
  - `external_validation_runner.py` - command-line entrypoint for the strict external validation benchmark.
  - `export.py` - Excel workbook export builder with native charts.
  - `materials.py` - material catalog loader.
  - `models.py` - validated input and result dataclasses.
  - `section_drawing.py` - SVG section-drawing builder for the active point, layer dimensions, and equilibrium-form overlays.
  - `serviceability.py` - crack-width and deflection checks, code-based limit profiles, and serviceability report assembly.
  - `serviceability_drawing.py` - II GGS scheme-drawing builder for the Streamlit serviceability tab.
  - `solver.py` - layered fiber-section pure-bending solver and section-state helpers.
  - `ui_helpers.py` - session-state helpers and input conversion utilities for Streamlit.

- `rc_bending_mcp/` - Python package implementing the local stdio MCP server and Streamlit automation bridge.
  - `README.md` - inventory of the MCP package modules.
  - `__init__.py` - package marker for the MCP server package.
  - `__main__.py` - module entrypoint so the MCP server can be launched with `python -m rc_bending_mcp`.
  - `adapters.py` - machine-input adapters that map MCP payloads to the existing Streamlit and domain draft formats.
  - `artifacts.py` - artifact-path resolution and JSON/XLSX/log writing helpers for MCP tool runs.
  - `domain.py` - direct Python execution layer for section, serviceability, experimental, and template workflows.
  - `handlers.py` - high-level MCP tool handlers that build response envelopes, invoke the UI runner, compare results, and record artifacts.
  - `server.py` - MCP tool registration for the public `get_catalogs`, `calculate_section`, `calculate_serviceability`, `analyze_experimental_workbook`, and `build_experimental_template` tools.
  - `ui_runner.py` - Playwright-based Streamlit UI runner that starts the local app, injects automation requests, and reads hidden JSON payloads from the page.

- `tests/` - automated tests for the calculator.
  - `README.md` - inventory of the test suite.
  - `fixtures/` - static parser and regression fixtures used by external-validation and experimental-workbook tests.
    - `README.md` - inventory of the test-fixture folder.
    - `experimental_workbooks/` - anonymized `.xlsx` fixtures for one-sheet experimental-workbook detection.
      - `README.md` - inventory of the experimental workbook fixtures.
      - `lab_one_sheet_primary.xlsx` - baseline one-sheet laboratory workbook with four labeled graph tables and nearby notes.
      - `lab_one_sheet_shifted.xlsx` - one-sheet workbook with the same four graph tables shifted to different positions and reordered across the sheet.
    - `eurocodeapplied_mrd_response.html` - minimal EurocodeApplied result-table fixture used to regression-test HTML parsing.
  - `test_experimental_data.py` - experimental workbook template generation, one-sheet detection, interpolation, and comparison-table regression tests.
  - `test_materials.py` - material-catalog and input-validation tests.
  - `test_export_and_ui.py` - Excel export, UI helper, and Streamlit smoke tests.
  - `test_external_validation.py` - tests for the strict external-validation case definition, mapping/parsing helpers, comparison logic, workbook export, and MCP profile filtering.
  - `test_mcp_live.py` - opt-in live MCP smoke tests that execute the local Streamlit app through the Playwright UI runner.
  - `test_mcp_server.py` - MCP adapter, handler, envelope, artifact, and fake-UI comparison tests for the local stdio server package.
  - `test_section_drawing.py` - SVG section-drawing layout and overlay regression tests.
  - `test_serviceability.py` - crack-width and deflection calculation tests.
  - `test_serviceability_scheme.py` - Streamlit II GGS layout and explanatory-content regression tests.
  - `test_solver.py` - solver behavior and reduction tests.

## Mandatory Instructions For The Agent
1. After any change to the project structure (adding, deleting, or renaming files or folders), always update `agent.md`.
2. Every project folder must contain a `README.md` file with a short purpose statement and an up-to-date list of its contents.
3. If a new folder is created, create its `README.md` immediately and add that folder to `agent.md`.
4. If a file or folder is deleted or renamed, update or remove the corresponding entries both in the local `README.md` and in `agent.md`.
5. Before finishing any task, verify that `agent.md` and all `README.md` files match the actual state of the project.
6. Every new initiative or task must be added to `plans/planned.md` with a short description and a date before implementation starts.
7. After the task is completed, move the entry from `plans/planned.md` to `plans/completed.md` and add the completion date and the result.
8. Entries in `plans/planned.md` and `plans/completed.md` must stay current after every change related to planning or execution.

These rules are mandatory for every future project update.
