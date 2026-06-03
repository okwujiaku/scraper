"""Launcher when Render root directory is the repo root (not bot/).

Prefer setting Root Directory to bot/ on Render. See README.md.
"""
import os
import runpy

_ROOT = os.path.dirname(os.path.abspath(__file__))
runpy.run_path(os.path.join(_ROOT, "bot", "bot.py"), run_name="__main__")
