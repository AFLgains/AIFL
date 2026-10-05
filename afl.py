"""The entry point: python afl.py <command> ...   (python afl.py --help for the list)

Runs straight from a checkout, with nothing installed. After `pip install -e .` the same CLI is the `afl` command.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
for _s in (sys.stdout, sys.stderr):                                        # Windows consoles and redirected logs default to cp1252
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from aflsim.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
