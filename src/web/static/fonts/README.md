# Bundled fonts

`ZillaSlab-Regular.ttf` (400), `ZillaSlab-Medium.ttf` (500) and
`ZillaSlab-SemiBold.ttf` (600) are the display face used for book titles,
card headings and the queue's figures. Source:
https://fonts.google.com/specimen/Zilla+Slab. Zilla Slab is Copyright 2017
Mozilla and is redistributed under the SIL Open Font License, Version 1.1.
The full license text is in `ZillaSlab-OFL.txt`.

`IBMPlexSans-Variable.ttf` is the interface face (weights 100–700). Source:
https://fonts.google.com/specimen/IBM+Plex+Sans. IBM Plex Sans is Copyright
2017 IBM Corp. and is redistributed under the SIL Open Font License, Version
1.1. The full license text is in `IBMPlexSans-OFL.txt`.

`Roboto-Regular.ttf` (400), `Roboto-Medium.ttf` (500) and `Roboto-Bold.ttf`
(700) remain in `style.css` as the legacy/fallback interface stack. Roboto is
Copyright 2011 Google Inc. and is redistributed under the Apache License,
Version 2.0; the full text is in `LICENSE.txt`.

`Literata-Variable.ttf` and `Literata-OFL.txt` are the previous display face.
The current theme does not load them; they remain in the folder only as an
archived option.

The files are served by Flask from `/static/fonts/`. Zilla Slab and IBM Plex
Sans are referenced by the `@font-face` blocks at the top of
`src/web/static/literary-theme.css`.
