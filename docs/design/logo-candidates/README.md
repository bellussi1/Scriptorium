# Scriptorium logo candidates

Three candidate logos for the Scriptorium name. None is wired into the UI:
`src/web/static/TBL-Logo.png`, `TBL-Logo-alpha.png` and `favicon.svg` are unchanged.
The owner picks one later.

| Candidate | Mark |
| --- | --- |
| `a-folio` | A manuscript page with ruled lines on a pine tile |
| `b-quill` | A pen nib with an ink drop |
| `c-monogram` | An `S` with a manuscript rule on an ink tile |

## Files

- `scriptorium-logo-<candidate>-<theme>.svg`: the source. `light` is for light
  surfaces, `dark` for dark surfaces. The wordmark is outlined from
  `src/web/static/fonts/Roboto-Medium.ttf`, so the SVG has no font dependency.
- `scriptorium-logo-<candidate>-<theme>-<px>.png`: transparent renders at 32, 128
  and 512 px. The number is the height of the full lockup (mark plus wordmark).

## Palette

Taken from the active literary theme (`src/web/static/literary-theme.css`):

- light: ink `#15191a`, accent `#0f5f56`, paper `#f2f4f2`
- dark: ink `#e6ece9`, accent `#7fc3b8`, paper `#0f1212`

## Notes

- The active theme sets Zilla Slab for display text and IBM Plex Sans for UI text.
  Roboto is the base layer from `style.css`. The wordmark uses Roboto Medium as
  the brief asked.
- The wordmark is set with glyph advances only, without kerning. Re-check the
  spacing if a candidate is chosen.
- Checked: 32 px renders are legible in a headless Chrome contact sheet on light
  and dark surfaces. Not checked: the logo in the running UI.
