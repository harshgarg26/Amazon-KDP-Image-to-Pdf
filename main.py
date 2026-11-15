"""KDP Builder entry point.

    python main.py            start the desktop application
    python main.py --cli ...  run headless (see `python main.py --cli --help`)
"""

from __future__ import annotations

import sys


def main() -> int:
    if "--cli" in sys.argv:
        from kdpbuilder.cli import run_cli

        argv = [a for a in sys.argv[1:] if a != "--cli"]
        return run_cli(argv)
    try:
        from kdpbuilder.gui.app import main as gui_main
    except ImportError as exc:  # missing customtkinter / tkinter
        print(f"Cannot start the GUI: {exc}\nInstall dependencies with:  pip install -r requirements.txt")
        return 1
    gui_main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
