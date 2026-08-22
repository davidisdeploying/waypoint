# Waypoint mark

Variant A, "Fix, tightened." Diamond ring with a solid core, mitered joins.

## Files

| File | Use |
|---|---|
| `waypoint-mark.svg` | The mark. Ring inherits `currentColor`, core is fixed `#e5331c`. |
| `waypoint-mark-mono.svg` | Single color. Everything inherits `currentColor`. |
| `waypoint-mark-cut.svg` | Knockout version. One path, center cut through. For icons and anywhere the mark sits on a solid fill. |
| `waypoint-lockup.svg` | Horizontal lockup, 209 x 40. Text is outlined, so no font loading needed. |
| `waypoint-lockup-mono.svg` | Same lockup, single `currentColor`. |
| `favicon.svg` | Two color, swaps ink to white under `prefers-color-scheme: dark`. |
| `favicon-16.png` `favicon-32.png` `favicon-48.png` | Fallback. Solid `#e5331c` so they hold on light and dark tab chrome. |
| `apple-touch-icon.png` | 180 square, red field, white knockout. Full bleed, iOS applies its own corner mask. |
| `icon-192.png` `icon-512.png` | Web app manifest. |

## Head snippet

```html
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="icon" href="/favicon-32.png" sizes="32x32">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="manifest" href="/site.webmanifest">
```

## Spec

- viewBox `0 0 100 100`. Ring vertices at 9 and 91, stroke 8, `stroke-linejoin: miter`. Core vertices at 32 and 68.
- Ink `#111111`, accent `#e5331c`.
- Clear space on all sides equals the core's half width, 18 units.
- Minimum size 16px. Below that use the cut version.

The PNG favicons are drawn with the stroke thickened inward at 16 and 32 so the ring does not wash out to grey. Outer silhouette is identical across all sizes.

## Notes

- The mark reads correctly in one color. If you need a single ink version, use the mono files rather than dropping the core.
- Do not round the joins. The four sharp points are the whole idea.
- Do not put the outline version in red at large sizes against white. It starts to read as a road warning sign. Use the cut version if you want an all red mark.
