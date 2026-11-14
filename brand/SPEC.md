# etl-craft mark: geometry spec

Master canvas 512 x 512, transparent, one `<path fill-rule="evenodd">` per file (no raster, no effects, no live text).

- Stroke weight t = 10, channel c = 10 (outer band width 30), weave gap g = 10: one value each, everywhere.
- Angles: all diagonals 30 degrees from horizontal. Mitered joins, flat square ends.
- Layers: hollow rhombus (half-width 150 on centreline) / vertical stem / two nested downward chevrons, tip spacing 86.
- Weave: rhombus over stem, stem over chevron 1, chevron 2 over stem.
- Colour: #1B7694 on light, #5BBFDF on dark (#0D1115). Mono: #000 / #fff.
- Wordmark: Inter Medium, outlined to paths, scaled so the stem of "l" = 30 (the mark's band width), baseline set so the ascender box is centred on the mark.
- favicon-16/32: solid shapes on the pixel grid, diagonals at 1:2 (26.6 deg) so edges land on pixel corners; embed a prefers-color-scheme swap.
- banner/etl-craft-flat*.svg: solid shapes only, 30 degrees, band 44, gap 14.
