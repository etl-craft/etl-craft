# etl-craft branding

The etl-craft name, logo and wordmark are the project owner's marks. The owner retains
ownership; the artwork is distributed under the repository's [Apache-2.0 licence](../LICENSE).
That licence does not grant trademark rights (section 6). Use these assets to identify
etl-craft without suggesting that the owner endorses another product.

## Backgrounds and size

Use the supplied SVG lockups (mark and wordmark together):

| Background | Lockup in `lockup/` |
| --- | --- |
| Light or white | `etl-craft-lockup.svg` (transparent) or `etl-craft-lockup-on-white.svg` |
| Dark or navy | `etl-craft-lockup-dark.svg` (transparent) or `etl-craft-lockup-on-navy.svg` |
| Light, monochrome | `etl-craft-lockup-black.svg` |
| Dark, monochrome | `etl-craft-lockup-white.svg` |

Keep the lockup at least 160 CSS pixels wide and a standalone mark at least 32 CSS pixels
wide. For browser icons at 16 or 32 pixels, use the dedicated files in `favicon/` instead
of shrinking the full mark. Preserve the aspect ratio and choose a background that keeps
every part legible. Give informative images the alternative text “etl-craft”.

Do not recolour, stretch, redraw, crop or rearrange the mark and wordmark. Use the supplied
monochrome variants when colour is unavailable. [SPEC.md](SPEC.md) defines the geometry and
colours; it remains the source for those details.

## CLI banner

A bare `etl-craft` invocation displays the product banner and installed version on an
interactive terminal before the usage line. `etl-craft about` displays the banner with
installation and session facts. Ordinary commands and help do not prepend it.

Set `ETL_CRAFT_NO_BANNER` (any value) to suppress the artwork; on a bare invocation this
suppresses the entire banner, while `about` still prints its plain information rows.
Narrow terminals, non-interactive output and `TERM=dumb` use no artwork. `NO_COLOR` (any
value) suppresses colour. JSON and piped output never contain the graphical banner;
`about --format json` returns its structured result, and piped text `about` retains plain rows.
Library imports, agents and task children do not display a startup banner.
