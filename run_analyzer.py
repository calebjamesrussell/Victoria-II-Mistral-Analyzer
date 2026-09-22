#!/usr/bin/env python3
"""Entry point for the Victoria II Mistral Analyzer."""

import sys


def main() -> int:
    try:
        from vic2analyzer.gui import main as gui_main
    except ImportError as exc:
        print(f"Missing dependency: {exc}", file=sys.stderr)
        print("Install with: pip install pillow matplotlib", file=sys.stderr)
        return 1
    return gui_main()


if __name__ == "__main__":
    sys.exit(main())
