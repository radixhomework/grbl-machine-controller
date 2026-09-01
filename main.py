#!/usr/bin/env python
"""Packaging entry point (used by PyInstaller to build standalone binaries)."""

import sys

from app.main import main

if __name__ == "__main__":
    sys.exit(main())
