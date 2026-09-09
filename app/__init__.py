"""Guardian application package."""

from pathlib import Path
import sys

# 반입본: 바깥에서 풀어 넣은 lib/ 를 pip 없이 쓴다.
_root = Path(__file__).resolve().parent.parent
_lib = _root / "lib"
if _lib.is_dir():
    _lib_s = str(_lib)
    if _lib_s not in sys.path:
        sys.path.insert(0, _lib_s)

__version__ = "0.1.0"
