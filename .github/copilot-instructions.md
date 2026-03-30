# Copilot Instructions — Inbox AI

## Project Overview

Inbox AI is an AI-powered email client with a Python (FastAPI) backend and a
vanilla HTML/CSS/JS frontend using Material Design 3 web components.

## Tech Stack

- **Backend:** Python, FastAPI, Jinja2 templates, SQLite
- **Frontend:** Vanilla HTML/CSS/JS, Material Web (`@material/web`), esbuild
- **Design System:** Material Design 3 with CSS custom properties (design tokens)
- **Fonts:** Roboto (body), Material Icons + Material Symbols Outlined
- **Themes:** Multiple themes via `data-theme` attribute and CSS variables

## Frontend Design Rules

When creating or modifying frontend code, follow these principles.

### Composition Over Components

- Start with composition, not components. Treat each viewport as a poster.
- Each section gets one job, one dominant visual idea, and one primary action.
- Default to cardless layouts — use sections, columns, dividers, lists, and
  media blocks. Use cards only when the card itself is the interaction.
- If removing a border, shadow, background, or radius does not hurt interaction
  or understanding, it should not be a card.

### Visual Hierarchy

- Keep the brand ("InboxAI") the loudest signal in the header.
- No headline should overpower the brand.
- Use whitespace, alignment, scale, and contrast before adding chrome.
- Reduce clutter: avoid pill clusters, stat strips, icon rows, and multiple
  competing text blocks.

### Design Token Discipline

- All colors must use existing `--theme-*` CSS custom properties. Never
  hard-code colors.
- Respect the token layers: `surface`, `surface-container`,
  `surface-container-high`, `on-surface`, `on-surface-variant`, `primary`,
  `outline`, `outline-variant`, `error`.
- Limit typefaces to existing Roboto weights (300, 400, 500, 700). Do not
  introduce new font families without discussion.
- One accent color (`--theme-primary`) by default. Use `--theme-tertiary` only
  for a distinct semantic purpose (e.g., warnings, categories).

### App UI — Not Marketing

This is a productivity dashboard, not a landing page. Apply utility-UI rules:

- Prioritize orientation, status, and action over promise, mood, or brand voice.
- Section headings should say what the area is or what the user can do there
  (e.g., "Unread emails", "Follow-ups due", "Draft replies").
- Supporting text should explain scope, behavior, or freshness in one sentence.
- If a sentence could appear in a homepage hero or ad, rewrite it until it
  sounds like product UI.
- If a section does not help someone operate, monitor, or decide, remove it.

### Layout

- Ensure all pages load properly on both desktop and mobile.
- Keep fixed or floating UI elements from overlapping text, buttons, or other
  key content across screen sizes.
- When using viewport-height heroes or panels, subtract persistent UI chrome.
- Dense but readable information — Linear-style restraint: calm surface
  hierarchy, strong typography, few colors, minimal chrome.

### Motion

- Use motion to create presence and hierarchy, not noise.
- Prefer CSS transitions and animations (no framework dependency).
- Motion must be smooth on mobile, fast, restrained, and consistent.
- Remove motion if it is purely ornamental.

### Accessibility

- All interactive elements must have visible focus indicators.
- Maintain WCAG AA contrast ratios for text over any surface.
- All text over imagery must maintain strong contrast and clear tap targets.
- Use semantic HTML and ARIA attributes where appropriate.

### Hard Rules

- No new cards by default.
- No more than one dominant idea per section.
- No filler copy or placeholder lorem ipsum in committed code.
- No hard-coded colors — use CSS custom properties.
- No new font families without explicit approval.
- No inline styles — use CSS classes.
- All Material Web components must be imported in `material.js` before use.

### Litmus Checks Before Submitting Frontend Changes

- Is the brand unmistakable in the header?
- Can the page be understood by scanning headings only?
- Does each section have one job?
- Are cards actually necessary?
- Does motion improve hierarchy or is it just decoration?
- Would the design still feel clean if all decorative shadows were removed?

## Code Conventions

- Files must end with exactly one trailing newline.
- No trailing whitespace.
- Python code follows the project's existing patterns (dependency injection via
  `container.py`, repository pattern for storage). See
  `.github/instructions/backend.instructions.md` for detailed backend rules.
- JavaScript uses vanilla ES modules — no React, no framework.
