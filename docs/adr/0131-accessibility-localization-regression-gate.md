# ADR 0131: Accessibility and localization regression gate

- Status: Accepted
- Date: 2026-07-28

## Context

P2-008 requires keyboard, screen-reader semantics, RTL, contrast, reduced
motion, masking, and critical E2E evidence. A single Arabic screenshot and
preference persistence test cannot detect invalid ARIA, contrast regressions,
lost keyboard focus, or sensitive presentation drift across new routes.

## Decision

Use the pinned Playwright-compatible axe-core package to evaluate WCAG 2 A/AA
and WCAG 2.1 A/AA rules across every native English and Arabic/RTL route plus
mobile landmarks in both directions. Keep
separate behavioral tests for skip links, modal focus wrapping/restoration,
high contrast, color-safe colors, reduced motion, focus indicators, and source-
path masking. Correct invalid chart semantics and raise default/color-safe
tokens to pass the automated AA contrast gate.
Mobile controls retain explicit accessible names when visual labels collapse,
and the active dock token must meet the same contrast gate.

The strong-focus preference may change emphasis but never remove the baseline
`:focus-visible` outline. Arabic tests assert both document language and
direction rather than relying on translated text alone.

## Consequences

- Semantic and contrast regressions now fail Chromium E2E instead of depending
  on screenshots or visual judgment.
- Axe-core is a locked development dependency and does not enter the production
  application bundle.
- Automated checks cannot replace manual screen-reader, voice-control,
  cognitive, zoom/reflow, or independent conformance assessment.
- Rollback can remove the test dependency and gate; no data migration exists.
