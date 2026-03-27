# `експерементальні дослідження` Folder

This folder stores experimental datasets prepared for overlaying measured curves on the theoretical bending-response charts shown in the app.

## Contents
- `60+60 непідсилена/` - the current experimental dataset package for the unstrengthened `60+60` specimen configuration.
- `60+60 непідсилена/experimental_curves_template(1).xlsx` - the Excel workbook that stores the experimental curve points in the canonical four-sheet layout used by the `Експеримент` tab:
  - `M_f` for the moment-deflection curve;
  - `M_eps_c` for the moment-concrete-strain curve;
  - `M_eps_s_top` for the moment-top-reinforcement-strain curve;
  - `M_eps_s_bot` for the moment-bottom-reinforcement-strain curve.

## Notes
- The workbook is kept in the same multi-sheet structure as the app's downloadable experimental template.
- Each supported sheet is expected to contain a canonical header row followed only by numeric curve points so the current Excel importer can load the dataset without manual cleanup.
