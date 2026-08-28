"""PyInstaller entry point.

`python -m daybook` and the `day` console script both route through
daybook.__main__:main. PyInstaller wants a plain script, so this is that
script and nothing more.
"""

from daybook.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
