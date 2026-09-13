from __future__ import annotations

from app.collectors.local import LocalTailCollector
from app.collectors.ssh import SshTailCollector
from app.models import Server


def collector_for(server: Server, ssh_timeout: int = 20):
    if server.collector_type == "local":
        return LocalTailCollector()
    return SshTailCollector(server, timeout=ssh_timeout)
