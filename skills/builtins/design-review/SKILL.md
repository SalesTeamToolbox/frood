---
name: design-review
description: UI/UX review, accessibility checks, brand consistency, and design system patterns.
always: false
task_types: [design]
---

# Design Review Skill

Evaluate and improve design work for usability, accessibility, brand consistency, and visual quality.

## Review Framework

### 1. Visual Hierarchy
- **Eye flow:** Does the layout guide the eye from most to least important?
- **Contrast:** Is there sufficient contrast between headings, body, and background?
- **Whitespace:** Is there enough breathing room? Dense layouts overwhelm users.
- **Size & weight:** Are heading sizes consistent? Do important elements stand out?

### 2. Accessibility (WCAG 2.1)
- **Color contrast:** 4.5:1 minimum for normal text, 3:1 for large text (18px+).
- **Color independence:** Never convey info by color alone — use icons, labels, patterns.
- **Focus states:** All interactive elements must have visible focus indicators.
- **Touch targets:** 44x44px minimum for mobile interactive elements.
- **Alt text:** All images need descriptive alternatives.
- **Keyboard navigation:** All functionality must be reachable without a mouse.

### 3. Brand Consistency
- **Color palette:** Are colors from the approved palette?
- **Typography:** Are fonts, weights, and sizes from the design system?
- **Spacing:** Does spacing follow the grid/scale system?
- **Tone:** Does the visual language match the brand personality?
- **Logo usage:** Is the logo used correctly (clear space, minimum size)?

### 4. User Experience
- **Clarity:** Can users understand what to do within 5 seconds?
- **Feedback:** Do interactive elements provide clear feedback?
- **Error states:** Are errors helpful and actionable?
- **Loading states:** Is there feedback during async operations?
- **Mobile:** Does the design work on small screens?

## Design Principles

- **Consistency over creativity.** A coherent experience beats one clever element.
- **Reduce cognitive load.** If users have to think, simplify.
- **Progressive disclosure.** Show only what's needed at each step.
- **Familiar patterns.** Use conventions users already know.
- **Design for edge cases.** Long names, empty states, error states, overflow.

## Feedback Format

When reviewing designs, structure feedback as:

1. **What works well** — Acknowledge good decisions (builds trust).
2. **Critical issues** — Must-fix problems (accessibility, usability blockers).
3. **Improvements** — Suggestions that would enhance quality.
4. **Minor polish** — Nice-to-haves for final refinement.

Always be specific: "Increase button contrast from 2.8:1 to 4.5:1" not "fix contrast."
