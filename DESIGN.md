---
# gstack: design-md-format=spec
name: OpsBridge AI
description: Flight recorder on a light table. A ruled, square, ink-and-paper operator console where the one orange row is the human's job.
colors:
  ground: "#E9ECEF"
  surface: "#F6F7F8"
  ink: "#14181C"
  on-ink: "#F6F7F8"
  rule: "#C3C9CF"
  text-muted: "#5A646D"
  needs-you: "#FF5B14"
  executed: "#0F7B4F"
  failed: "#C21F3A"
  rejected: "#5B3A8C"
  pending: "#7A848E"
  confidence: "#FFE14D"
typography:
  display:
    fontFamily: Barlow Condensed
    fontWeight: 700
    fontSize: 1.75rem
    letterSpacing: 0.04em
  body:
    fontFamily: Instrument Sans
    fontSize: 0.875rem
    lineHeight: 1.5
  label:
    fontFamily: Barlow Condensed
    fontWeight: 700
    fontSize: 0.75rem
    letterSpacing: 0.08em
  mono:
    fontFamily: JetBrains Mono
    fontFeature: tnum
rounded:
  none: 0px
spacing:
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 24px
  2xl: 32px
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.on-ink}"
    rounded: "{rounded.none}"
  button:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
  table-row-attention:
    backgroundColor: "{colors.needs-you}"
---

# OpsBridge AI

## Overview

**Creative North Star:** A flight recorder on a light table: precise, ruled, accountable. Engineering craft shows in alignment, numerals and restraint, not effects.
**Product context:** Internal operator console for an AI triage agent (GitHub Issues events). Operators approve, edit or reject risky actions; engineers inspect traces and eval results. Next.js + Tailwind. Also shown to hiring managers as a portfolio piece.
**Mode per surface:** Operate (queue, approvals, trace inspector, eval dashboard).
**Reference sites:** langfuse.com, linear.app, sentry.io (visual reference only; their dark or purple looks are deliberately avoided).
**Key characteristics:**
- Light ground, 1px ink rules, square corners.
- Orange appears only on rows that need a human.
- Every status has a shape as well as a color.
- Data in tabular mono; decisions as stamped verdicts.

## Colors

**Strategy:** Restrained. Ink and paper neutrals plus status colors; orange is rare and meaningful.
**Light or dark:** Light, from the use scene (office, daytime, long sessions, screenshots and projectors). A dark theme exists as a secondary toggle with lifted status colors (`#3DC98A`, `#FF6B82`, `#B79AE8`).
`needs-you` marks AWAITING_APPROVAL only. `confidence` is a highlighter bar behind the score. Shapes: filled square (awaiting, executed), X (failed), slash in square (rejected), hollow square (pending). Do not rely on color alone.

## Typography

Instrument Sans for UI and body (fine as body on an Operate surface). Barlow Condensed 700, uppercase, letterspaced for headings and status labels. JetBrains Mono for IDs, JSON, traces and numbers with `font-variant-numeric: tabular-nums slashed-zero`. All load from Google Fonts (OFL 1.1).
**Unconfirmed:** the exact Instrument Sans weight range (sources disagree; 400 to 700 is safe) and JetBrains Mono tabular-figure support (verify in the font's feature list). Load only the weights you use.

## Layout

Grid-disciplined, dense. Content max width 1040px. Table rows are 32px. Ticket detail is a vertical trace "tape": step numbers in a left gutter, latency in a right gutter, citations as footnote superscripts that expand inline. No cards inside cards.

## Elevation & Depth

Depth comes from 1px ink borders and a 2px offset hard shadow on keys (`2px 2px 0 ink`). No blur, no glow.

## Shapes

Radius is 0 everywhere. Hierarchy comes from rule weight and offset shadows.

## Components

- **Button:** square, 1px ink border, 2px offset shadow; hover moves 1px and shrinks the shadow; focus-visible is a 2px orange outline. Primary is solid ink.
- **Status badge:** Barlow Condensed uppercase plus shape plus color.
- **Queue row:** 32px, 1px rule below; attention rows get a light orange tint.
- **Stamp:** verdict word with operator initials and timestamp on the trace header after approve or reject.
- **Empty, loading, error states:** designed with ink text and a rule border; errors name the failure and offer retry.
- Keyboard: A approve, E edit, R reject.

## Do's and Don'ts

- Do keep orange exclusive to AWAITING_APPROVAL.
- Do pair every status color with a shape and a text label.
- Do use tabular mono for every number that is compared or scanned.
- Do keep keyboard shortcuts for approve, edit and reject.
- Don't add rounded corners, blur shadows or glows.
- Don't nest cards; use rules and indentation.
- Don't use purple gradients or the Linear/Sentry look.
- Don't use stat tiles with big numbers and tiny labels for the eval dashboard; use a ruled table.

## Motion

- **Approach:** minimal-functional
- **Easing:** enter(ease-out) exit(ease-out) move(ease-in-out)
- **Duration:** micro(50-100ms) short(150-250ms) medium(250-400ms) long(400-700ms)
- **The one authored moment:** on approve or reject the verdict stamps onto the trace header, then the row leaves the queue.

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-11-16 | Initial design system created | Created by /design-consultation from the PRD, a brief visual pass over three reference sites and one independent Claude proposal (Codex unavailable). Tokens come from the approved HTML preview. |
