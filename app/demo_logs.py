from __future__ import annotations

from datetime import datetime, timedelta
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


def healthy_lines_for(plugin: str, stamp: str, syslog: str, host: str) -> list[str]:
    """플러그인 규칙에 안 걸리는 정상 INFO/DEBUG 줄."""
    name = (plugin or "").strip().lower()
    lines = {
        "java": [
            f"{stamp} INFO [jvm] JVM started heap=2g",
            f"{stamp} INFO [jvm] GC young collection 12ms",
            f"{stamp} INFO [http] GET /orders/1201 200 18ms",
            f"{stamp} INFO [http] GET /orders/1202 200 21ms",
            f"{stamp} DEBUG [http] request completed path=/health",
        ],
        "springboot": [
            f"{stamp} INFO org.springframework.boot.StartupInfoLogger Started DemoApplication in 2.1 seconds",
            f"{stamp} INFO org.apache.catalina.core.StandardService Tomcat started on port 8080",
            f"{stamp} INFO org.springframework.web.servlet.DispatcherServlet Initializing Servlet 'dispatcherServlet'",
            f"{stamp} INFO [order] GET /orders/8801 200 16ms",
            f"{stamp} INFO [order] POST /orders 201 44ms",
            f"{stamp} DEBUG [order] health UP",
        ],
        "python": [
            f"{stamp} INFO [uvicorn] Application startup complete",
            f"{stamp} INFO [app] GET /batch/jobs 200",
            f"{stamp} INFO [app] job daily-settle finished rows=120",
            f"{stamp} DEBUG [app] cache hit key=job:daily-settle",
        ],
        "nginx": [
            f'{stamp} INFO nginx: worker process 2211 started',
            f'{stamp} 10.20.0.8 - - "GET /health HTTP/1.1" 200 12',
            f'{stamp} 10.20.0.8 - - "GET /orders/8801 HTTP/1.1" 200 512',
            f'{stamp} 10.20.0.9 - - "POST /orders HTTP/1.1" 201 88',
        ],
        "apache": [
            f'{stamp} INFO apache: configured -- resuming normal operations',
            f'{stamp} 10.20.0.8 - - "GET /health HTTP/1.1" 200 12',
            f'{stamp} 10.20.0.8 - - "GET /static/app.js HTTP/1.1" 200 4096',
        ],
        "tomcat": [
            f"{stamp} INFO org.apache.catalina.startup.Catalina Server startup in [2103] milliseconds",
            f"{stamp} INFO org.apache.coyote.http11.Http11NioProtocol Starting ProtocolHandler [http-nio-8080]",
            f"{stamp} INFO [http] GET /orders/8801 200",
        ],
        "jeus": [
            f"{stamp} INFO tmax domain started engine=8",
            f"{stamp} INFO deploy order-app success",
            f"{stamp} INFO http listener 8080 ready",
        ],
        "weblogic": [
            f"{stamp} INFO WebLogic Server started in RUNNING mode",
            f"{stamp} INFO data source orderDS connected",
            f"{stamp} INFO [http] GET /orders/8801 200",
        ],
        "mysql": [
            f"{stamp} INFO mysqld ready for connections version=8.0",
            f"{stamp} INFO InnoDB buffer pool ready",
            f"{stamp} INFO [sql] SELECT orders id=8801 ok 2ms",
        ],
        "postgres": [
            f"{stamp} INFO:  database system is ready to accept connections",
            f"{stamp} INFO:  checkpoint complete",
            f"{stamp} INFO:  autovacuum launcher started",
            f"{stamp} DEBUG:  connection authorized: user=app database=shop",
        ],
        "oracle": [
            f"{stamp} INFO database shop opened",
            f"{stamp} INFO listener LISTENER on port 1521 ready",
            f"{stamp} INFO [sql] SELECT orders id=8801 ok",
        ],
        "kafka": [
            f"{stamp} INFO kafka.server KafkaServer started (kafka.server.KafkaServer)",
            f"{stamp} INFO kafka.log [Log partition=orders-0, dir=/data] Loading producer state",
            f"{stamp} INFO kafka.cluster Partition orders-0 leader is 1",
        ],
        "rabbitmq": [
            f"{stamp} INFO Server startup complete; 3 plugins started",
            f"{stamp} INFO accepting AMQP connection 10.20.0.21",
            f"{stamp} INFO queue orders declared",
        ],
        "redis": [
            f"{stamp} INFO Redis version=7.2.4 64 bit",
            f"{stamp} INFO Ready to accept connections tcp=6379",
            f"{stamp} INFO replica 10.20.0.9 sync ok",
        ],
        "systemd": [
            f"{syslog} {host} systemd[1]: Started nginx.service",
            f"{syslog} {host} systemd[1]: Started ssh.service",
            f"{syslog} {host} systemd[1]: Reached target Multi-User System",
        ],
        "auth_failures": [
            f"{syslog} {host} sshd[2201]: Accepted publickey for deploy from 10.0.1.8 port 51022 ssh2",
            f"{syslog} {host} sshd[2202]: Accepted publickey for ops from 10.0.1.9 port 51023 ssh2",
        ],
        "disk_full": [
            f"{stamp} INFO [disk] /var usage=41% inodes=12%",
            f"{stamp} INFO [disk] /data usage=58% inodes=9%",
        ],
    }
    return list(lines.get(name, []))


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


def write_healthy_dated_logs(base: Path | None = None, days: int = 7, when: datetime | None = None) -> list[Path]:
    """여유 시연용으로 날짜별 정상 로그를 채운다."""
    root = Path(base or (ROOT / "sample_logs" / "healthy"))
    now = when or wall_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=ZoneInfo(settings.app.timezone))
    now = now.replace(minute=0, second=0, microsecond=0)
    plugins = ("springboot", "python", "postgres", "redis", "mysql", "nginx")
    written: list[Path] = []
    for name in plugins:
        for day_offset in range(days - 1, -1, -1):
            day = (now - timedelta(days=day_offset)).date()
            path = root / name / f"{day.isoformat()}.log"
            lines: list[str] = []
            last_hour = now.hour if day_offset == 0 else 23
            last_stamp = ""
            for hour in range(last_hour + 1):
                stamp_dt = datetime(day.year, day.month, day.day, hour, tzinfo=now.tzinfo)
                stamp, syslog, _day = _stamp_parts(stamp_dt)
                last_stamp = stamp
                lines.extend(healthy_lines_for(name, stamp, syslog, name))
            if last_stamp:
                lines.extend([f"{last_stamp} INFO [health] check ok"] * 24)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            written.append(path)
    return written


def _stamp_parts(when: datetime | None = None) -> tuple[str, str, str]:
    tz = ZoneInfo(settings.app.timezone)
    now = when or wall_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    stamp = now.strftime("%Y-%m-%d %H:%M:%S")
    months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
    syslog = f"{months[now.month - 1]} {now.day:2d} {now.strftime('%H:%M:%S')}"
    return stamp, syslog, now.strftime("%Y-%m-%d")


def _mix(healthy: list[str], extra: list[str]) -> list[str]:
    if not healthy:
        return list(extra)
    mid = max(1, len(healthy) // 2)
    return healthy[:mid] + extra + healthy[mid:]


def catalog_lines_for(plugin: str, stamp: str, syslog: str, host: str) -> list[str]:
    """정상 줄 사이에 이상 줄을 섞습니다."""
    return _mix(
        healthy_lines_for(plugin, stamp, syslog, host),
        extra_lines_for(plugin, stamp, syslog, host),
    )


def common_lines(host: str, stamp: str, syslog: str) -> list[str]:
    """대부분 정상이고, 공통 규칙이 잡을 이상만 조금 넣습니다."""
    lines = [
        f"{stamp} INFO [api] Guardian demo log started",
        f"{stamp} INFO [api] health check ok",
    ]
    for idx in range(12):
        lines.append(f"{stamp} INFO [api] request accepted path=/orders/{8800 + idx} status=200")
    lines.append(f"{stamp} DEBUG [cache] hit key=session:demo")
    lines.append(f"{stamp} WARN [api] slow response 820ms path=/orders/summary")
    for idx in range(2):
        lines.append(f"{stamp} ERROR [worker] Connection refused to 10.0.0.12:5432 try={idx}")
    lines.extend(extra_lines_for("auth_failures", stamp, syslog, host)[:3])
    lines.extend(extra_lines_for("disk_full", stamp, syslog, host)[:1])
    lines.append(f"{stamp} INFO [batch] guardian demo log finished")
    return lines


def healthy_common_lines(host: str, stamp: str, syslog: str) -> list[str]:
    lines = [
        f"{stamp} INFO [api] Guardian healthy log started",
        f"{stamp} INFO [api] health check ok",
    ]
    for idx in range(12):
        lines.append(f"{stamp} INFO [api] request accepted path=/orders/{8900 + idx} status=200")
    lines.extend(healthy_lines_for("auth_failures", stamp, syslog, host))
    lines.extend(healthy_lines_for("disk_full", stamp, syslog, host))
    lines.append(f"{stamp} DEBUG [cache] hit key=session:healthy")
    lines.append(f"{stamp} INFO [batch] guardian healthy log finished")
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
    healthy_all = healthy_common_lines("healthy-local", stamp, syslog)
    for name in CATALOG:
        mixed = catalog_lines_for(name, stamp, syslog, name)
        healthy = healthy_lines_for(name, stamp, syslog, name)
        dump(root / "catalog" / f"{name}.log", mixed)
        dump(root / "healthy" / f"{name}.log", healthy)
        all_lines.extend(mixed)
        healthy_all.extend(healthy)
    dump(root / "all-plugins.log", all_lines)
    dump(root / "demo.log", common_lines("demo-local", stamp, syslog))
    dump(root / "healthy.log", healthy_all)
    dump(root / "README.txt", [
        "Guardian 시연용 샘플 로그",
        f"만든 날짜: {day}",
        "",
        "healthy.log / healthy/*.log  정상 INFO·DEBUG 만 있습니다. 여유 서버 시연용입니다.",
        "catalog/*.log               정상 줄 사이에 이상 줄을 섞었습니다.",
        "all-plugins.log             정상+이상. 모든 1단계 플러그인이 잡는 줄이 들어 있습니다.",
        "demo.log                    공통 정상 트래픽 + ERROR/WARN 일부입니다.",
        "web/ db/ auth/              날짜·시간별 더미(정상 많음, 일부 시간대 이상).",
        "healthy/web|db|auth/        날짜·시간별 정상 더미입니다.",
        "",
        "이상 시연: catalog 또는 all-plugins.log 경로 + 1단계 플러그인 선택 후 수집.",
        "정상 시연: healthy.log 또는 healthy/*.log 경로로 서버를 따로 등록 후 수집.",
    ])
    if root.resolve() == (ROOT / "sample_logs").resolve():
        from app.seed import _write_dummy_logs, _write_healthy_dummy_logs

        _write_dummy_logs(force=True)
        _write_healthy_dummy_logs(force=True)
    return written
