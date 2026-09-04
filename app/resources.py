"""Filesystem resource paths (assets shipped with the application)."""

from __future__ import annotations

import os

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
LOGO = os.path.join(ASSETS_DIR, "logo.png")
