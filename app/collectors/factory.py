from __future__ import annotations

from app.collectors.local import LocalTailCollector
from app.collectors.ssh import SshTailCollector
from app.models import Server


def collector_for(server: Server, ssh_timeout: int = 20):
    if server.collector_type == "local":
        return LocalTailCollector()
    return SshTailCollector(
        host=server.host,
        port=server.port,
        username=server.username,
        key_path=server.key_path,
        timeout=ssh_timeout,
    )
