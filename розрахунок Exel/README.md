# `розрахунок Exel` Folder

This folder stores the Excel-based calculation model.

## Contents
- `ДБН_11_.xlsx` - the main working workbook for reinforced-concrete checks. The workbook contains:
  - an input sheet for geometry, material classes, safety factors, and reinforcement layout;
  - a normal-section sheet for section-level calculations;
  - an oblique-section sheet for additional design checks;
  - embedded reference tables for reinforcement properties and concrete parameters from DSTU/DBN sources;
  - a large nonlinear equation solver sheet that iterates the deformation-method equilibrium equations;
  - unit-conversion and settings sheets;
  - a diagram sheet that assembles the calculated section-state points.

## Notes
- The workbook was reviewed against the local DBN/DSTU source set and includes corrected formulas for the `C30/35` polynomial coefficient in the concrete table and for the second reinforcement lever arm in the nonlinear solver.
- A remaining review note is kept open for the `C50/60` coefficient `a_5` in the concrete table: the current workbook value looks unusual, but the repository does not yet contain a directly readable source table that would allow it to be corrected with confidence.
