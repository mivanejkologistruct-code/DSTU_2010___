# External Validation References

This note lists the online calculators selected for independent cross-checks of the pure-bending solver.

## Primary reference
- EurocodeApplied ULS rectangular RC section
  - URL: https://eurocodeapplied.com/design/en1992/uls-design-rectangular-section
  - Use for homogeneous single-concrete `N = 0` comparison.
  - Compare moment resistance, neutral-axis depth, and the strain regime after aligning material assumptions as closely as possible.

## Secondary reference
- CivilCalc reinforced concrete rectangular section
  - URL: https://civilcalc.com/reinforced-concrete
  - Use as a quick nominal-moment and strain-diagram sanity check for the same homogeneous case.

## Qualitative deformation-method reference
- CivilEng nonlinear deformation model
  - URL: https://civileng.ru/check/rc/ndm-custom
  - Use only as a qualitative secondary check because it is alpha and based on SP 63, not DSTU/DBN.

## Scope note
- No clearly documented browser calculator was identified that explicitly supports a two-concrete-layer rectangular section with DSTU/DBN material data.
- The online cross-check workflow is therefore limited to the homogeneous-concrete subset.
