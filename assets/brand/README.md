# Waypoint brand assets

Finalized 2026-07-29 from David's `waypoint.zip`.

- `source-package/` preserves all 13 files from the original ZIP byte-for-byte,
  including its README and every SVG/PNG deliverable.
- Original ZIP SHA-256:
  `5d1c0ed0249a6e20af9344a234dfc11c45063e3e367c96c59541ff26ba87d0e0`.
- `waypoint-lockup.svg` is the production masthead lockup.
- `waypoint-mark.svg` is the two-color standalone mark.
- `waypoint-mark-mono.svg` and `waypoint-lockup-mono.svg` inherit `currentColor`.
- `waypoint-mark-cut.svg` is the knockout mark for solid fills and very small uses.
- `waypoint-app-icon-dark.svg` is the production dark-appearance app icon
  source. It preserves the mark geometry while changing the ring to white on
  an opaque `#111111` field.

The sharp mitered diamond ring and red core are intentional. Do not round the
joins, recolor the large outline red on white, or recreate the outlined lockup
with a web font.
