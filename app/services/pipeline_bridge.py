"""Load modules from pipeline/ by their bare names.

Pipeline scripts run directly and import each other as `import enrich`, so the
crawler and scorer need pipeline/ on sys.path when the API calls into them.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType

_PIPELINE_DIR = str(Path(__file__).resolve().parents[2] / "pipeline")


def load(name: str) -> ModuleType:
    if _PIPELINE_DIR not in sys.path:
        sys.path.append(_PIPELINE_DIR)
    return importlib.import_module(name)
