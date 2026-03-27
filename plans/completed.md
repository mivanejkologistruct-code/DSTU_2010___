# Completed Work

## Entry Format
- Completion date: `YYYY-MM-DD`
- Task title
- Result
- Status: `done`

## Finished Items
- Completion date: 2026-03-25
  Title: Верхня арматура і таблиця `f_u` в блоці Експеримент
  Result: Повернуто інженерний напрям осі `0 -> від'ємні значення` для графіка верхньої арматури в теоретичному та experimental overlay режимах, додано спільну таблицю `Граничний момент при досягненні граничного прогину` під графіками блоку `Експеримент`, а також оновлено UI-регресії для осі, таблиці, порядку рендерингу та reference mode без колонки DIC.
  Status: `done`

- Completion date: 2026-03-17
  Title: Add MCP server for automated Streamlit calculations
  Result: Added the `rc_bending_mcp` package with stdio MCP tool registration, machine-input adapters, direct Python handlers, a Playwright Streamlit UI runner, structured artifact output, automation-mode payload hooks in the Streamlit app, new MCP unit/live tests, and dependency updates for the MCP SDK plus Playwright.
  Status: `done`

- Completion date: 2026-03-12
  Title: Autodetect experimental Excel workbooks
  Result: Added rule-based inspection for one-sheet laboratory `.xlsx` files with four graph tables, preserved backward-compatible import for the legacy multi-sheet template, introduced pending-preview and confirm flow in the experimental Streamlit tab, added anonymized workbook fixtures, and extended parser/UI regression coverage for ready, incomplete, conflict, and confirmation scenarios.
  Status: `done`

- Completion date: 2026-03-11
  Title: Refine chart annotations and per-graph explanations
  Result: Restacked the three `M-ε` charts into full-width sections, replaced long overlapping Altair labels with short in-chart limit symbols, moved material-specific explanations directly under each graph, added a curvature caption for `M-κ`, refreshed the chart card styling for readability, and updated the UI/rendering tests to cover the new layout and explanation blocks.
  Status: `done`

- Completion date: 2026-03-09
  Title: Strict external validation via EurocodeApplied
  Result: Added a standalone EurocodeApplied validation module and CLI runner, mapped a canonical homogeneous benchmark case to the external calculator, generated a strict comparison workbook with evidence links, created output folders with inventories, captured live screenshot/HTML evidence, and covered the new flow with parser, comparison, workbook, process-filter, and opt-in live smoke tests.
  Status: `done`

- Completion date: 2026-03-07
  Title: Normalize chart set without moment-deflection
  Result: Removed the non-normative moment-deflection graph and span input from the Streamlit UI, retained DSTU/DBN-based moment-curvature and strain charts with `10^-5` strain scaling on graphs, and locked the normative UI workflow to exactly two rebar layers with matching validation and tests.
  Status: `done`

- Completion date: 2026-03-07
  Title: Add deflection and rebar strain charts
  Result: Added a span-based moment-deflection chart, separate moment-strain charts for the extreme top and bottom rebar layers, introduced `10^-5` strain scaling for plotted strain values, and covered the new chart data/UI behavior with automated tests.
  Status: `done`

- Completion date: 2026-03-06
  Title: Two-layer concrete bending calculator
  Result: Implemented a Streamlit calculator for pure bending with two concrete layers and arbitrary rebar layers, added machine-readable material catalogs, a fiber-section solver, intermediate-iteration and layer-force views, Excel export with native charts, online-validation notes, and automated tests for materials, solver behavior, export, and UI smoke rendering.
  Status: `done`

- Completion date: 2026-03-06
  Title: DBN/DSTU theory correction and workbook formula fix
  Result: Corrected the DBN appendix reference in the Appendix A Markdown file, updated the methodology transcription and folder descriptions to distinguish DBN material properties from DSTU calculation rules, fixed the confirmed workbook formula errors in the concrete table and nonlinear solver, and documented the still-unconfirmed `C50/60` coefficient review note in the workbook README.
  Status: `done`

- Completion date: 2026-03-06
  Title: English documentation update and file inventory refinement
  Result: Added the new `dstu_методика.md` file to the project inventory, translated the project descriptions into English, and expanded the file descriptions so they reflect the actual content of the Markdown, PDF, image, and Excel files.
  Status: `done`

- Completion date: 2026-03-05
  Title: Project index and folder descriptions
  Result: Created `agent.md` with the project structure and instructions, and added `README.md` files to the `нормативи` and `розрахунок Exel` folders.
  Status: `done`

- Completion date: 2026-03-05
  Title: Planning journal setup
  Result: Created the `plans` folder with `planned.md`, `completed.md`, and `README.md`, then updated `agent.md` with the mandatory planning rules.
  Status: `done`
