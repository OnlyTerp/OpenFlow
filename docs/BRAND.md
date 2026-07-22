# OpenFlow brand guidelines

OpenFlow's identity signals **many sources, one stream**: several speech memberships flowing
through one calm, local control panel. It is technical and trustworthy — an instrument panel,
not a consumer lifestyle app.

## Name & wordmark

- Name: **OpenFlow** (one word, capital O and F).
- Wordmark: `Open` in the primary text color, `Flow` in ember, 650 weight, −0.02em tracking.
- Tagline (mono, uppercase, letterspaced): `LOCAL DICTATION CONTROL`.
  Occasional variant: `MANY SOURCES · ONE STREAM`.
- Never write "Open Flow", "openflow" in prose headings, or "OpenFlow AI". Never append
  another vendor's name to ours ("OpenFlow for Wispr" — prohibited).

## The mark

An **open ring** (a circle with a gap at the upper right — the "open") with **three signal
bars** inside (the stream / waveform). Geometry on a 32×32 grid:

- Ring: r = 11.5, stroke 2.4, round caps, ~65° gap rotated to the upper right
  (`stroke-dasharray="59 13.3"`, `rotate(-38)`).
- Bars: width 2.6, radius 1.3, heights 7 / 14 / 9, horizontally centered at x = 10.7 / 16 / 21.3.
- Gradient: `#FFB25C → #FF6B2C`, diagonal top-left → bottom-right.

Usage:

- Always render the mark on dark warm neutrals or transparent; the ember gradient is the
  brand's primary signal.
- Clearspace: at least the ring stroke width (2.4 units) on all sides.
- Minimum size: 16 px (favicon) — below that use the ring alone.
- **Don't** close the ring, add a play triangle, mirror the bars, recolor to a provider's
  brand color, or place it on busy imagery.
- The mark is an original asset. Do not redraw it to resemble any vendor's logo; do not
  combine it with third-party marks in one lockup.

## Color

"Ember console" — a warm dark system. One mode, owned fully (no half-hearted light theme).

| Token | Hex | Role |
|-------|-----|------|
| `--of-bg-0` | `#100E0C` | app background |
| `--of-bg-1` | `#16130F` | surface |
| `--of-bg-2` | `#1D1915` | raised surface |
| `--of-bg-3` | `#26211A` | hover |
| `--of-line` / `--of-line-2` | `rgba(255,188,138,.10/.20)` | warm hairlines |
| `--of-text` | `#F2EDE6` | primary text |
| `--of-text-2` | `#B3AA9E` | secondary |
| `--of-text-3` | `#7D756A` | muted |
| `--of-ember` | `#FF6B2C` | accent (configurable) |
| `--of-ember-2` | `#FFB25C` | accent highlight |
| `--of-ok` | `#57D98D` | ready / success |
| `--of-warn` | `#FFC24B` | needs login / limited |
| `--of-err` | `#FF6E66` | error |

Provider identity hues — used **only** for dots/chips that label an engine, never as UI
chrome: Grok `#FF6B2C`, ChatGPT `#E9B949`, Claude `#C97E5A`. These are OpenFlow-assigned
identifiers, not the vendors' official brand colors; do not import vendor palettes or logos.

The accent is user-configurable (`config.ui.accent`): presets Ember `#FF6B2C`, Amber
`#FFA41B`, Flare `#FF5C6C`, Signal `#E9B949`. Marketing/screenshots use Ember.

## Typography

Two voices:

- **UI sans** — system stack (`Inter` → `Segoe UI Variable` → `system-ui`). Titles 680
  weight, −0.025em tracking; body 400–550.
- **Data mono** — `ui-monospace` → `Cascadia Code` → `JetBrains Mono`. Used for kickers
  (uppercase, 0.14–0.18em tracking, 10–11px), endpoints, file paths, timings, counters —
  the "instrument" feel. Numbers in mono are `tabular-nums`.

Do not license or embed a display font for v1; the system's restraint is the identity.

## Voice & copy

- Calm, precise, honest. Short sentences. Technical nouns allowed: *shim, engine, endpoint,
  latency, session*.
- Say what is true: an engine that can't be reached says so. Status pills are
  **ready / needs login / limited / offline** — never "OK!" for a degraded state.
- Providers are "engines" you connect; OpenFlow is the "control center" / "controller".
- Avoid vendor slogans, "AI magic", exclamation marks, and any phrasing that implies
  endorsement by xAI, OpenAI, Anthropic, or Wispr.
- Legal line for about pages/store listings: *OpenFlow is not affiliated with or endorsed by
  xAI, OpenAI, Anthropic, or Wispr.*

## Differentiation rules (hard requirements)

1. No third-party trademarks, logos, screenshots, or marketing phrases in the repo or UI.
2. No layout traced from another dictation app's screens; design from these tokens and the
   product requirements in [DESIGN.md](DESIGN.md).
3. Provider names appear only nominatively ("send audio to ChatGPT"), never as decoration.
4. The words "Wispr" or "Flow" as a product name appear only where required for compatibility,
   historical context, or legal clarity.
5. Do not publish screenshots of the third-party desktop shell. Until OpenFlow has a
   standalone shell, documentation may use only screenshots of OpenFlow-authored local UI and
   must label that UI accurately.
