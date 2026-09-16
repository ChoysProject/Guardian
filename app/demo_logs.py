from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.config import ROOT, settings
from app.metrics import wall_now

CATALOG = (
    "java",
    "springboot",
    "python",
    "nginx",
    "apache",
    "tomcat",
    "jeus",
    "weblogic",
    "mysql",
    "postgres",
    "oracle",
    "kafka",
    "rabbitmq",
    "redis",
    "systemd",
)


def extra_lines_for(plugin: str, stamp: str, syslog: str, host: str) -> list[str]:
    """1단계 플러그인이 잡을 시연용 줄."""
    name = (plugin or "").strip().lower()
    lines = {
        "java": [
            f"{stamp} ERROR [jvm] java.lang.OutOfMemoryError: Java heap space",
            f"{stamp} ERROR [jvm] java.lang.NullPointerException",
            f"{stamp} ERROR [jvm] Exception in thread \"http-nio-8080-exec-1\" java.lang.IllegalStateException: already started",
            f"{stamp} ERROR [jvm] Too many open files",
        ],
        "springboot": [
            f"{stamp} ERROR org.springframework.boot.SpringApplication APPLICATION FAILED TO START",
            f"{stamp} ERROR com.zaxxer.hikari.pool.HikariPool Connection is not available, request timed out after 30000ms",
            f"{stamp} ERROR org.springframework.web.servlet.DispatcherServlet Exception",
            f"{stamp} ERROR org.springframework.beans.factory.BeanCreationException: Error creating bean 'orderService'",
            f"{stamp} ERROR org.springframework.web.HttpRequestMethodNotSupportedException",
        ],
        "python": [
            f"{stamp} ERROR Traceback (most recent call last):",
            f"{stamp} ERROR ModuleNotFoundError: No module named 'psycopg2'",
            f"{stamp} ERROR ValueError: invalid literal for int()",
            f"{stamp} ERROR TimeoutError: timed out",
        ],
        "nginx": [
            f"{stamp} ERROR nginx: upstream timed out (110: Connection timed out) while connecting to upstream",
            f"{stamp} ERROR nginx: connect() failed (111: Connection refused) while connecting to upstream",
            f"{stamp} emerg nginx: worker process 2211 exited on signal 9",
        ],
        "apache": [
            f"{stamp} ERROR AH00484: server reached MaxRequestWorkers setting",
            f"{stamp} ERROR child pid 4411 exit signal Segmentation fault (11)",
            f"{stamp} WARN server reached MaxClients, consider raising the MaxClients setting",
        ],
        "tomcat": [
            f"{stamp} SEVERE org.apache.catalina.startup.ContextConfig Failed to start component",
            f"{stamp} SEVERE ProtocolHandler [http-nio-8080] failed",
            f"{stamp} ERROR java.lang.OutOfMemoryError: Java heap space",
            f"{stamp} WARN Session ABC123 expired",
            f"{stamp} WARN Session DEF456 expired",
        ],
        "jeus": [
            f"{stamp} ERROR [JEUS] JEUS-1234 deploy failed",
            f"{stamp} ERROR [JEUS] 애플리케이션 배포 실패 order-app",
            f"{stamp} ERROR [JEUS] license expired",
            f"{stamp} ERROR [JEUS] java.lang.OutOfMemoryError: Java heap space",
        ],
        "weblogic": [
            f"{stamp} ERROR BEA-000337 server failed to boot",
            f"{stamp} ERROR Failed to start WebLogic Server",
            f"{stamp} ERROR JDBC connection pool orderDS exhausted",
        ],
        "mysql": [
            f"{stamp} ERROR mysqld got signal 11",
            f"{stamp} ERROR Too many connections",
            f"{stamp} ERROR Table './shop/orders' is marked as crashed",
            f"{stamp} WARN Aborted connection 1024 to db: 'shop' user: 'app'",
            f"{stamp} WARN Aborted connection 1025 to db: 'shop' user: 'app'",
            f"{stamp} WARN Aborted connection 1026 to db: 'shop' user: 'app'",
        ],
        "postgres": [
            f"{stamp} PANIC:  could not write to file \"pg_wal/000000010000000000000001\"",
            f"{stamp} FATAL:  remaining connection slots are reserved",
            f"{stamp} ERROR:  deadlock detected",
            f"{stamp} FATAL:  too many connections for role \"app\"",
        ],
        "oracle": [
            f"{stamp} ERROR ORA-01555: snapshot too old",
            f"{stamp} ERROR TNS-12541: TNS:no listener",
            f"{stamp} ERROR ORA-00257: archive error, archive stuck",
        ],
        "kafka": [
            f"{stamp} ERROR kafka.controller UnderReplicatedPartitions=3",
            f"{stamp} ERROR NOT_LEADER_OR_FOLLOWER for topic orders-0",
            f"{stamp} ERROR kafka.log Disk error: No space left on device",
            f"{stamp} WARN ISR shrink for orders-0",
        ],
        "rabbitmq": [
            f"{stamp} ERROR memory alarm on node rabbit@mq-01",
            f"{stamp} ERROR connection_closed_abruptly from 10.0.0.8",
            f"{stamp} ERROR connection_closed_abruptly from 10.0.0.9",
            f"{stamp} ERROR queue orders crashed",
        ],
        "redis": [
            f"{stamp} ERROR OOM command not allowed when used memory > 'maxmemory'",
            f"{stamp} ERROR MISCONF Redis is configured to save RDB snapshots",
            f"{stamp} ERROR Connection with replica 10.0.0.9 lost",
        ],
        "systemd": [
            f"{syslog} {host} systemd[1]: Failed to start nginx.service",
            f"{syslog} {host} systemd[1]: nginx.service: Main process exited, code=exited, status=1/FAILURE",
            f"{syslog} {host} systemd[1]: Watchdog timeout",
            f"{syslog} {host} kernel: nginx[2211]: segfault at 0 ip 00007f",
        ],
        "auth_failures": [
            f"{syslog} {host} sshd[4412]: Failed password for root from 192.168.10.5 port 55122 ssh2",
            f"{syslog} {host} sshd[4413]: Failed password for root from 192.168.10.5 port 55123 ssh2",
            f"{syslog} {host} sshd[4414]: Failed password for invalid user oracle from 192.168.10.5 port 55124 ssh2",
            f"{syslog} {host} sshd[4415]: Failed password for invalid user oracle from 192.168.10.5 port 55125 ssh2",
            f"{syslog} {host} sshd[4416]: Failed password for admin from 192.168.10.5 port 55126 ssh2",
        ],
        "disk_full": [
            f"{stamp} WARN [disk] No space left on device /var",
            f"{stamp} ERROR [disk] No space left on device /var",
            f"{stamp} ERROR [disk] Disk quota exceeded",
        ],
    }
    return list(lines.get(name, []))


def _stamp_parts(when: datetime | None = None) -> tuple[str, str, str]:
    tz = ZoneInfo(settings.app.timezone)
    now = when or wall_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    stamp = now.strftime("%Y-%m-%d %H:%M:%S")
    months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
    syslog = f"{months[now.month - 1]} {now.day:2d} {now.strftime('%H:%M:%S')}"
    return stamp, syslog, now.strftime("%Y-%m-%d")


def common_lines(host: str, stamp: str, syslog: str) -> list[str]:
    lines = [
        f"{stamp} INFO [api] Guardian demo log started",
        f"{stamp} INFO [api] health check ok",
    ]
    for idx in range(8):
        lines.append(f"{stamp} ERROR [worker] Connection refused to 10.0.0.12:5432 try={idx}")
    lines.extend(extra_lines_for("auth_failures", stamp, syslog, host))
    lines.extend(extra_lines_for("disk_full", stamp, syslog, host))
    lines.append(f"{stamp} INFO [batch] guardian demo log finished")
    return lines


def write_demo_logs(base: Path | None = None, when: datetime | None = None) -> list[Path]:
    """시연용 샘플 로그를 sample_logs/ 에 만듭니다."""
    root = Path(base or (ROOT / "sample_logs"))
    root.mkdir(parents=True, exist_ok=True)
    stamp, syslog, day = _stamp_parts(when)
    written: list[Path] = []

    def dump(path: Path, lines: list[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        written.append(path)

    all_lines = common_lines("demo-local", stamp, syslog)
    for name in CATALOG:
        extra = extra_lines_for(name, stamp, syslog, name)
        dump(root / "catalog" / f"{name}.log", extra)
        all_lines.extend(extra)
    dump(root / "all-plugins.log", all_lines)
    dump(root / "demo.log", common_lines("demo-local", stamp, syslog))
    dump(root / "README.txt", [
        "Guardian 시연용 샘플 로그",
        f"만든 날짜: {day}",
        "",
        "all-plugins.log  모든 1단계 플러그인이 잡는 줄을 한 파일에 모았습니다.",
        "catalog/*.log    플러그인별 파일입니다. 서버 등록 때 경로로 넣으면 됩니다.",
        "demo.log         공통(ERROR 몰림, SSH 실패, 디스크 가득)만 있습니다.",
        "web/ db/ auth/   날짜·시간별 더미 로그입니다. 대시보드 추이 시연용입니다.",
        "",
        "시연 한 방에 보려면 로그 수집 대상 서버를 local 로 등록하고",
        "로그 경로에 sample_logs/all-plugins.log 를 넣은 뒤",
        "1단계 공통 플러그인을 모두 고르고 수집하면 됩니다.",
    ])
    if root.resolve() == (ROOT / "sample_logs").resolve():
        from app.seed import _write_dummy_logs

        _write_dummy_logs(force=True)
    return written
