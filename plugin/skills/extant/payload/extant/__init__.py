"""The extant package.

Deliberately holds a version and nothing else. Every sibling module imports
from siblings; if this file imported any of them, every one of those imports
would become a cycle through the package root.
"""
from __future__ import annotations

__version__ = "0.24.1"
