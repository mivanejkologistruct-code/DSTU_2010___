# `нормативи` Folder

This folder stores the regulatory documents, methodological extracts, and supporting figures used as source material for reinforced-concrete calculations.

## Contents
- `DodatokA_DSTU_B_V.2.6-156-2010.md` - Markdown transcription of Appendix A to `DSTU B V.2.6-156:2010`. It explains the deformation-method algorithm for solving the nonlinear equilibrium equations of a reinforced-concrete design section, lists the required input parameters, and walks through the iterative search for the section state diagram and bearing capacity.
- `DSTU_B_V.2.6-156-2010_DodatokA_scan.pdf` - three-page scan of the same Appendix A pages from the DSTU standard. It is useful for checking the Markdown transcription against the original printed layout and formulas.
- `dstu_методика.md` - Markdown transcription of the Section 4 methodology extract from `DSTU B V.2.6-156:2010`. It reproduces the narrative assumptions, formulas `4.1` to `4.12`, and figure references for the rectangular-section deformation-method equations.
- `dsty_b_v.2.6-156-2010.pdf` - full `DSTU B V.2.6-156:2010` standard, "Concrete and reinforced concrete structures made of heavy concrete. Design rules". This is the primary design-rule source referenced by the extracted materials in this folder.
- `ДБН В.2.6-982009.pdf` - official `DBN V.2.6-98:2009` document, "Concrete and reinforced concrete structures. Basic provisions". It contains the baseline concrete and reinforcement parameters that are referenced by the appendix algorithm and the calculation workbook.
- `Методика розрахунку ДСТУ.pdf` - five-page methodological extract from Section 4 of the DSTU standard. It covers the assumptions for first-group limit-state design, formulas `4.1` to `4.12`, and Figures `4.1` and `4.2` for rectangular section analysis.
- `рисунок 4.1.jpg` - image export of Figure `4.1`, showing the rectangular section, the stress diagrams, the strain diagrams, and the two equilibrium forms used in the deformation-method formulation.
- `рисунок 4.2.jpg` - image export of Figure `4.2`, showing stress and strain diagrams for a rectangular section under the first equilibrium form.

## Notes
- In this project, `DBN V.2.6-98:2009` is treated as the source of baseline material parameters, while `DSTU B V.2.6-156:2010` is treated as the source of the nonlinear section-analysis algorithm and Section 4 equations.
- If a figure or formula number appears in both documents, it must be interpreted in the context of the specific source document rather than by number alone.
