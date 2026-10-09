"""每日一瓜 · 小瓜桌宠 — the 梅花易数 cast, the 黄历, the evidence gate, and 小瓜 on your desktop.

Data lives next to the code (engines/, checks/, evidence/, protocols/, references/,
voice/) and every module resolves it relative to this directory. Importing this
package puts engines/ and checks/ on `sys.path`, so those modules work both as
standalone scripts and as importable units.
"""

from __future__ import annotations

import sys
from pathlib import Path

__version__ = "1.0.0"

ROOT = Path(__file__).resolve().parent
ENGINES = ROOT / "engines"
CHECKS = ROOT / "checks"

for _directory in (ENGINES, CHECKS):
    _path = str(_directory)
    if _path not in sys.path:
        sys.path.insert(0, _path)


def data_path(*parts: str) -> Path:
    """Resolve a bundled knowledge-base file, e.g. data_path('evidence', 'meihua.md')."""
    return ROOT.joinpath(*parts)


__all__ = ["ROOT", "ENGINES", "CHECKS", "data_path", "__version__"]
