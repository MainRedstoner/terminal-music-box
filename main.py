#!/usr/bin/env python3
"""Convenience launcher: python main.py [args]  (same as python -m tmb)."""
from tmb.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())