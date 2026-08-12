# Thumb-Specific Super Finger Axis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Select a mirrored primary rotation axis for automatic thumb chains while preserving the existing marker normalization used by ordinary fingers.

**Architecture:** Keep axis selection inside the existing `FingerAxisPlan`; automatic index/ring chains retain `-X`, while `Thumb_*_L` uses `Z` and `Thumb_*_R` uses `-Z`. Manual Rigify axis settings remain untouched. The Blender MCP regression check will generate a temporary rig, connect the source armature, scale both thumb master controls, and inspect source-bone motion without saving the blend.

**Tech Stack:** Python, unittest, Blender 5.2 MCP, Rigify `limbs.super_finger`.

## Global Constraints

- Do not change the already committed `ad05838` behavior for non-thumb fingers.
- Keep terminal marker collinearity before Rigify generation.
- Do not persist temporary Blender test objects or save the user blend.

---

### Task 1: Add failing axis-selection regression tests

**Files:**
- Modify: `tests/test_compatibility.py`

- [ ] Add assertions that automatic `Thumb_01_L` plans select `Z` and automatic `Thumb_01_R` plans select `-Z`.
- [ ] Run the focused tests and confirm they fail because the current implementation returns `-X` for every chain.

### Task 2: Implement mirrored thumb axis selection

**Files:**
- Modify: `re_rigify/compatibility.py:61-100`

- [ ] Select `Z` for a detected automatic chain whose root ends in `_L` and starts with `Thumb_`.
- [ ] Select `-Z` for the matching `_R` chain.
- [ ] Keep `-X` as the default for all other detected automatic super-finger chains.
- [ ] Continue applying marker collinearity and the selected axis through `apply_compatibility_plan`.

### Task 3: Verify source-driven Blender behavior

**Files:**
- No persistent Blender file changes.

- [ ] Run all Python unit tests, byte-compilation, and `git diff --check`.
- [ ] Through Blender MCP, generate temporary left/right variants, connect source-to-rig, scale `Thumb_01_master_L/R` to `Y=1.25`, and verify both source thumb tips move toward the hand with no temporary objects remaining.
- [ ] Regenerate the open user rig with the new code, restore all test scales to `(1, 1, 1)`, and leave the blend unsaved.

