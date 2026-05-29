# Cycle 3 Design Notes — Servarr-Dark + Emerald

## Aesthetic
Servarr (Sonarr/Radarr) -style dark admin dashboard: dense data tables, subtle borders, left-sidebar layout. Emerald/teal accent on a dark slate surface. Geometric-sans typography.

## Palette

| Token      | Hex       | Usage                        |
|------------|-----------|------------------------------|
| bg         | #1a1d24   | Page/app background          |
| surface    | #20242c   | Cards, panels                |
| elevated   | #161920   | Inputs, depressed elements   |
| border     | #2c313a   | All dividers/borders         |
| fg         | #e8eaed   | Primary text                 |
| muted      | #9aa0aa   | Secondary/placeholder text   |
| accent     | #10b981   | Primary CTA, running state   |
| accent-hover | #0ea371 | Hover on accent             |
| accent-fg  | #04140d   | Text on accent background    |

## State Colors

| State     | Hex     |
|-----------|---------|
| queued    | #64748b |
| running   | #10b981 |
| done      | #16a34a |
| failed    | #ef4444 |
| skipped   | #f59e0b |
| cancelled | #71717a |

## Typography
- **Headings**: Space Grotesk (500/600/700) — `font-display`
- **Body**: Inter (400/500/600) — `font-sans`
- **Numbers/IDs/sizes/%**: JetBrains Mono (400/500) — `font-mono`

## State → Badge Mapping
| Job state       | Badge variant |
|-----------------|---------------|
| queued          | queued        |
| running         | running       |
| done            | done          |
| failed          | failed        |
| skipped_larger  | skipped       |
| cancelled       | cancelled     |

## Eligibility → Badge Mapping
| Eligibility    | Badge variant |
|----------------|---------------|
| needs_transcode | accent       |
| already_h265   | neutral       |
| below_1080p    | queued        |
| excluded       | skipped       |
