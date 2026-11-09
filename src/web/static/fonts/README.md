# Bundled fonts

`Roboto-Regular.ttf` (400), `Roboto-Medium.ttf` (500) and
`Roboto-Bold.ttf` (700) are the interface weights. Source:
https://fonts.google.com/specimen/Roboto. Roboto is Copyright 2011 Google
Inc. and is redistributed under the Apache License, Version 2.0. The full
license text is in `LICENSE.txt` next to this file.

`Literata-Variable.ttf` is the display face used for book titles, card
headings and the queue's figures. Source:
https://fonts.google.com/specimen/Literata. Literata is Copyright 2018 The
Literata Project Authors and is redistributed under the SIL Open Font
License, Version 1.1. The full license text is in `Literata-OFL.txt`.

The files are served by Flask from `/static/fonts/`. Roboto is referenced by
the `@font-face` blocks at the top of `src/web/static/style.css`; Literata by
the block at the top of `src/web/static/literary-theme.css`.
