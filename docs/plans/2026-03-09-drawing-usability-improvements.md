# Drawing Usability Improvements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Improve the section drawing presentation and remove the empty first-form epure when the active state is second-form and no first-form comparison exists.

**Architecture:** Keep the existing SVG renderer in `rc_bending/section_drawing.py` as the single source of drawing layout. Update panel selection/layout there, then keep Streamlit wrapper copy in `streamlit_app.py` aligned with the new behavior and verify through focused tests plus rendered artifacts.

**Tech Stack:** Python, Streamlit, pytest, Streamlit AppTest, SVG rendering

---

### Task 1: Lock the missing-first-form behavior in tests

**Files:**
- Modify: `tests/test_section_drawing.py`
- Modify: `tests/test_export_and_ui.py`

**Step 1: Write the failing test**

Add a drawing test for the default peak-point scenario asserting that:
- the second-form panel is present
- the first-form title is absent
- no placeholder is rendered for the missing first form

Add a Streamlit test asserting that the rendered SVG for the default state does not include the first-form placeholder/title when only the second form is available.

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_section_drawing.py tests/test_export_and_ui.py -k "missing_comparison_form or renders_without_exception" -v`

Expected: FAIL because the current SVG always renders both panels and keeps the first-form placeholder.

**Step 3: Write minimal implementation**

Update panel selection/layout logic in `rc_bending/section_drawing.py` so only relevant panels are rendered for the current state, with the second-form panel promoted when first-form data is unavailable.

**Step 4: Run test to verify it passes**

Run the same pytest command and confirm both new assertions pass.

**Step 5: Commit**

Skip unless the user asks for a commit.

### Task 2: Improve drawing readability without breaking current structure

**Files:**
- Modify: `rc_bending/section_drawing.py`
- Modify: `tests/test_section_drawing.py`
- Modify: `tests/test_export_and_ui.py`

**Step 1: Write the failing test**

Add assertions that capture the updated layout contract, such as:
- compact single-panel canvas width/height bounds
- presence of a dedicated panel-layout role for visible panels
- preserved legends/annotations for the active panel

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_section_drawing.py tests/test_export_and_ui.py -k "compact_canvas or layout" -v`

Expected: FAIL until the SVG layout metrics are updated.

**Step 3: Write minimal implementation**

Tighten the SVG canvas and improve label readability by:
- computing visible panels dynamically
- resizing/repositioning section, callouts, and panels for the visible set
- slightly increasing panel/callout readability where space allows

**Step 4: Run test to verify it passes**

Run the focused pytest command again and confirm PASS.

**Step 5: Commit**

Skip unless the user asks for a commit.

### Task 3: Verify rendered output and summarize UX findings

**Files:**
- Modify: `streamlit_app.py`

**Step 1: Verify wrapper copy stays accurate**

Adjust the explanatory note in `streamlit_app.py` so it no longer promises both equilibrium forms when only one is actually available.

**Step 2: Run tests**

Run: `pytest tests/test_section_drawing.py tests/test_export_and_ui.py -v`

Expected: PASS.

**Step 3: Generate visual artifacts**

Render the updated SVG to `tmp/current_drawing.png` and `tmp/current_drawing_both.png` using headless Chrome for a visual check.

**Step 4: Summarize usability analysis**

Report concrete UX findings on:
- drawing density / empty space
- label readability
- consistency between UI copy and actual rendering
- mobile/overflow risk in the drawing stage
