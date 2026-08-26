import os
import tempfile
from pathlib import Path

os.environ["GUARDIAN_TESTING"] = "1"

ROOT = Path(__file__).resolve().parent.parent
_tmp = Path(tempfile.mkdtemp(prefix="guardian-test-"))
_config = _tmp / "config.yaml"
_db = _tmp / "guardian.db"
_config.write_text(
    f"""
app:
  name: Guardian
  host: 127.0.0.1
  port: 8080
  data_dir: {_tmp.as_posix()}
  timezone: Asia/Seoul
  seed_demo: true
database:
  url: sqlite:///{_db.as_posix()}
auth:
  enabled: false
dify:
  enabled: false
plugins:
  dir: {(ROOT / "plugins").as_posix()}
scheduler:
  daily_report_time: "18:00"
""",
    encoding="utf-8",
)
os.environ["GUARDIAN_CONFIG"] = str(_config)
