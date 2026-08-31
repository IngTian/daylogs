"""PyInstaller entry point.

`python -m daylogs` and the `day` console script both route through
daylogs.__main__:main. PyInstaller wants a plain script, so this is that
script and nothing more.
"""

from daylogs.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
