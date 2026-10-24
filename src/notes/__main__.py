"""允许 `python -m src.notes ...` 直接用。"""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
