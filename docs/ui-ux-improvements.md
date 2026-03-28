# UI/UX Improvements — Feedback Capture

> **Date:** 2026-03-28
> **Branch:** `ui-ux-improvements`
> **Status:** Draft

---

## Goals

- Keep the interface simple and minimalist.
- Maintain a modern and clean look.
- Ensure the experience is mobile friendly.

---

## Current UI Direction

The dashboard already has a strong foundation:

- clear two-pane list/detail structure on desktop
- compact top app bar
- restrained Material-style controls
- responsive behavior for smaller screens

The main opportunity is not adding more UI, but reducing visual weight,
clarifying hierarchy, and improving mobile ergonomics.

---

## Recommended Improvements

### 1. Simplify the Filter Experience

**Why:** The current left filter rail takes a large amount of visual space for
secondary controls.

**Recommendation:**

- convert the desktop filter rail into a lighter, compact filter bar
- use a slide-over panel or bottom sheet for filters on mobile
- keep only the most-used filters visible by default

**Benefit:** Less chrome, more focus on inbox content, better mobile fit.

---

### 2. Reduce Email List Density

**Why:** List rows currently carry a lot of metadata and state.

**Recommendation:**

- keep subject as the strongest signal
- show sender and one supporting line only
- move less critical state into the detail view or reveal it only when needed

**Benefit:** Cleaner scanning and a more modern minimalist feel.

---

### 3. Make Mobile Detail View Feel More Native

**Why:** On mobile, detail content should feel like entering a dedicated screen,
not exposing a compressed desktop panel.

**Recommendation:**

- treat the selected email view as a full reading state on mobile
- keep the back affordance obvious and sticky
- avoid overcrowding the top portion of the detail view

**Benefit:** Better readability and easier navigation on phones.

---

### 4. Separate Primary and Secondary Actions

**Why:** Draft and follow-up sections currently contain several actions with
similar visual weight.

**Recommendation:**

- keep one or two primary actions prominent
- downgrade secondary utilities like regenerate, delete, and feedback
- avoid too many tonal buttons in the same row

**Benefit:** Cleaner hierarchy and lower cognitive load.

---

### 5. Quiet Decorative Backgrounds on Data-Heavy Screens

**Why:** Organic background shapes add personality, but the dashboard is a
productivity surface, not a marketing page.

**Recommendation:**

- reduce the visual intensity of the background once inbox content is present
- keep decorative treatment subtle behind dense information areas

**Benefit:** Stronger focus on actual work and a calmer interface.

---

### 6. Standardize Active and Selected States

**Why:** Selected rows, chips, buttons, and feedback controls should feel like
they belong to one coherent system.

**Recommendation:**

- use a consistent selected-state treatment across list rows and action controls
- avoid mixing too many active-state colors and weights

**Benefit:** More polished and modern visual consistency.

---

### 7. Use Progressive Disclosure on Mobile

**Why:** Mobile layouts benefit from showing less by default.

**Recommendation:**

- surface search and one quick filter first
- hide advanced filters behind “More filters”
- collapse categories or metadata when they are not critical

**Benefit:** Faster use on small screens without losing functionality.

---

### 8. Improve Readability Through Spacing, Not More Containers

**Why:** Minimalist design works best when whitespace and rhythm create the
structure.

**Recommendation:**

- give key sections more breathing room
- reduce cramped action clusters
- rely on spacing and typography before adding extra cards or dividers

**Benefit:** Cleaner visual hierarchy without additional UI complexity.

---

## Priority Order

Recommended implementation order:

1. Simplify the filter experience.
2. Reduce email list density.
3. Improve the mobile detail view.
4. Separate primary and secondary actions.
5. Quiet decorative backgrounds.
6. Standardize active and selected states.

---

## Notes

- Keep changes evolutionary, not a redesign from scratch.
- Preserve the existing calm Material-based design language.
- Prefer removing or simplifying UI before adding new interface elements.
- Mobile friendliness should be treated as a first-class layout goal, not a
  later cleanup pass.
