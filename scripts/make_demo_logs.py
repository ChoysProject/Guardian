"""시연용 샘플 로그를 sample_logs/ 에 다시 만듭니다."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.demo_logs import write_demo_logs  # noqa: E402


def main() -> None:
    paths = write_demo_logs()
    print(f"{len(paths)}개 파일을 만들었습니다.")
    for path in paths:
        print(f"  {path}")


if __name__ == "__main__":
    main()
