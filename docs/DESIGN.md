# OpenFlow design system — "ember console"

> **Scope.** These tokens style the shim debug UI under `openflow/static/openflow/` and define
> a future standalone desktop-overlay specification. The current preview does not publish or
> inject vendor UI assets.

Implementation: `openflow/static/openflow/app.css` (tokens + components),
`overlay.html` (HUD). No framework, no build step; every rule below maps to a CSS custom
property or component class. Brand rationale lives in [BRAND.md](BRAND.md).

## Foundations

- **Surfaces** — four warm graphite levels (`--of-bg-0..3`). Page background adds a faint
  ember radial at the top-right. Cards use a vertical gradient of bg-2 → bg-1.
- **Borders** — 1px warm hairlines (`--of-line`, `--of-line-2`); no cold grays anywhere.
- **Radius** — 8 controls / 12 tiles & rows / 16 cards / 999 pills & HUD.
- **Elevation** — warm soft shadow (`--of-shadow`); active/brand surfaces glow
  (`--of-glow`: ember ring + bloom), used sparingly (active engine, chosen rows).
- **Motion** — 160 ms `cubic-bezier(.2,.7,.3,1)` micro-transitions; waveform keyframes for
  listening; shimmer skeletons while loading; `prefers-reduced-motion` collapses all of it.
- **Type** — UI sans for prose, data mono for kickers/labels/values (see BRAND.md §Type).

## Components

| Class | Notes |
|-------|-------|
| `.of-card` (+`--active`, `--off`) | container; `--active` = ember ring glow; `--off` = dimmed (disabled engine) |
| `.of-pill` (+`--ok/--warn/--err/--ember/--mute`) | status: ready / needs login / limited / offline. Always paired with `.of-dot` |
| `.of-pdot` (+`--grok/--chatgpt/--claude`) | 10px rounded-square engine identifier |
| `.of-stat` | mono value + uppercase mono label tile |
| `.of-btn` (+`--primary`, `--ghost`, `--sm`, `--rec`) | primary = ember gradient with dark text; `--rec` = hold-to-talk pill with live state |
| `.of-switch` | accessible checkbox switch (focus-visible ring) |
| `.of-seg` | segmented control — the engine quick switch |
| `.of-wave` | 7-bar waveform; `.of-live` animates (staggered bounce) |
| `.of-kv` | definition grid: mono uppercase dt, dd values, `overflow-wrap:anywhere` for paths |
| `.of-table` | activity tables: mono headers, hairline rows |
| `.of-toast` | bottom-center confirmations; `--err` variant |
| `.of-notice` (+`--warn/--err`) | inline callouts, ember/status left rail |
| `.of-ob*` | onboarding modal: backdrop blur, step bar, `.of-ob-row` connect rows |
| `.of-chip` | mono inline token (endpoints, timings) |
| `.of-hotkey kbd` | keycap style with 2px bottom border |

## Layout language

Left rail (236px, sticky): brand lockup (mark + wordmark + mono tagline), primary nav with
CSS-only glyphs (signal-bar motif), footer with the **shim chip** (live dot + `online /
offline` + `:18765`) and Setup guide button. Content column max 980px: mono kicker → title →
lede → sections introduced by `.of-section-label` (uppercase mono + hairline rule).
Responsive <860px collapses the rail to a top bar.

## Screens

1. **Home** — active-engine card (name, vendor, live detail, transport chip, last latency,
   status pill) with quick-switch segmented control; shim stat tiles (uptime, dictations,
   last latency, last engine); **test bench** card (hold-to-talk, format-pass toggle, test
   tone, result panel with raw/final transcripts + timing chips + paste-stub button); last
   engine error callout when present.
2. **Speech engine** — one card per provider: identity dot, name, vendor/plan, status pill,
   kv rows (engine id, transport, auth file, session, status detail, error), actions
   (enabled switch, fallback switch when eligible, make-active button disabled when not
   usable). Honest-status notice under the grid. Claude must be able to say *limited*.
3. **Activity** — metric tiles (requests, succeeded, failed, avg total, avg asr, lexicon
   rules); per-engine table (status, ok, fail, last latency); last-error callout; bench
   history table persisted in localStorage (max 50) with clear button.
4. **Settings** — local shim kv (endpoint, config file, STT route, cleanup); appearance
   (accent presets saved to `config.ui.accent`); dictation hotkey (keycaps, capture,
   overlay preview, explicit stub copy); about (mark, one-paragraph promise, legal line).
5. **Onboarding** — modal, 5 steps: welcome → connect engines (live status rows + refresh)
   → choose engine (disabled when unusable) → hotkey (capture + overlay preview + stub
   copy) → test dictation (inline bench) → finish. Step bar reflects progress; skippable;
   `of_onboarded_v1` localStorage flag.
6. **Overlay HUD** (`overlay.html`) — transparent page, capsule 250px+: mark, live dot,
   7-bar waveform, state label, mono engine/timer lines. States: `listening` (bouncing
   bars, breathing ember dot, running timer), `processing` (pulsing bars), `done` (green
   ring), `error` (red ring). `?demo=1` cycles; `?state=`/`?engine=` pin. Esc closes.
   This page is the pixel spec the desktop shell renders as an always-on-top window.

## Interaction rules

- Every control that mutates config round-trips through `PUT /v1/config` and re-reads
  `/health`; a switch that "didn't stick" is a toast error, never silent.
- Destructive-ish actions (clear history) are local-only and reversible by re-testing.
- Poll cadence: `/health` every 5 s; `/metrics` only on the Activity route. Re-render is
  suppressed while recording so the bench never clobbers itself.
- All dynamic text passes through `esc()`; provider `detail`/`error` strings are untrusted.
- Contrast: text tokens on their surface tokens meet WCAG AA (verify when adding colors);
  status is never color-only — pills always carry a text label.

## What this system deliberately avoids

Light themes as an afterthought, blue-gray "SaaS" neutrals, card-in-card nesting, vendor
brand colors as chrome, emoji icons, and any asset or layout lifted from another dictation
product. New screens must be composable from the tokens above — if a needed primitive is
missing, add it here first.
