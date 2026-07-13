# Third-Party Licenses

RetroVault is distributed under its own license (see the repository root). Packaged
builds (the PyInstaller one-folder bundle and the Inno Setup installer) redistribute
third-party components. This document records the notices for the components that are
bundled as native/binary artifacts in those packaged builds.

## pygame-ce

RetroVault uses [pygame-ce](https://github.com/pygame-community/pygame-ce) for
controller input. pygame-ce is licensed under the **GNU LGPL version 2.1**.

- Project: https://github.com/pygame-community/pygame-ce
- License text: https://github.com/pygame-community/pygame-ce/blob/main/docs/LGPL.txt

Because pygame-ce is LGPL-2.1, its source code is available at the project link above,
and the library is used unmodified. Users retain the LGPL rights to obtain the source
and to relink RetroVault against a modified version of pygame-ce.

## SDL2

pygame-ce dynamically links the **Simple DirectMedia Layer 2 (SDL2)** libraries, which
are bundled inside the pygame-ce wheels (for example `SDL2.dll` on Windows) and are
therefore redistributed inside RetroVault's packaged builds.

SDL2 is licensed under the **zlib license**.

- Project: https://www.libsdl.org/
- License text: https://github.com/libsdl-org/SDL/blob/main/LICENSE.txt

The zlib license permits redistribution of the SDL2 binaries in both source and binary
form with minimal conditions and no requirement to relink.

## LGPL relinking note

SDL2 is **dynamically linked** by pygame-ce (it is shipped as a standalone shared
library rather than statically compiled in). This preserves the LGPL relinking right:
a user may replace the bundled SDL2 shared library in an installed RetroVault build
with a compatible build of their own, and may likewise obtain the pygame-ce source and
relink it. The corresponding source for both pygame-ce and SDL2 is available at the
project links above.
