"""
故障注入的最小封装:docker compose stop / start 某个中间件,以及读服务日志文件。

注入手段限定为 `docker compose stop/start`(CLAUDE.md §3 不引入 ChaosBlade),命令模板来自配置
DOCKER_COMPOSE_CMD——Docker 在 WSL2 里时是 `wsl.exe -d Ubuntu-24.04 -u root -- docker compose --project-directory ../ops`,
CI 里是 `docker compose --project-directory ../ops`(相对 tests/,pytest 的工作目录)。配置为空时,fault 标记的用例整体 skip 并说明原因。

stop / start 都是同步阻塞到容器状态改变;"服务感知到故障 / 恢复"另有时延(Lettuce 重连退避、
RabbitMQ 监听容器重连),用例里用 wait_until 等,并把等到的秒数记进 Allure——那是 KI-015 要的数据。
"""
from __future__ import annotations

import gzip
import shlex
import subprocess
import time
from pathlib import Path

import allure


class ComposeFaults:
    def __init__(self, compose_cmd: str, timeout: float = 90.0):
        self.enabled = bool(compose_cmd.strip())
        self.argv = shlex.split(compose_cmd, posix=False) if self.enabled else []
        self.timeout = timeout

    def _run(self, *args: str) -> str:
        cmd = [*self.argv, *args]
        t0 = time.monotonic()
        proc = subprocess.run(cmd, capture_output=True, timeout=self.timeout)
        out = (proc.stdout + proc.stderr).decode("utf-8", errors="replace").replace("\x00", "")
        allure.attach(f"$ {' '.join(cmd)}\n[{time.monotonic() - t0:.1f}s exit={proc.returncode}]\n{out}",
                      name=f"docker compose {' '.join(args)}", attachment_type=allure.attachment_type.TEXT)
        if proc.returncode != 0:
            raise RuntimeError(f"docker compose {' '.join(args)} 失败 exit={proc.returncode}: {out[-500:]}")
        return out

    def stop(self, service: str) -> None:
        with allure.step(f"故障注入:docker compose stop {service}"):
            self._run("stop", service)

    def start(self, service: str) -> None:
        with allure.step(f"故障恢复:docker compose start {service}"):
            self._run("start", service)

    def ps(self) -> str:
        return self._run("ps")


class ServiceLog:
    """按行读服务的文件日志。用 offset 而不是整文件比较:压测后的日志有几百 MB。"""

    def __init__(self, path: Path | None):
        self.path = path

    @property
    def available(self) -> bool:
        return self.path is not None and self.path.exists()

    def size(self) -> int:
        return self.path.stat().st_size if self.available else 0

    def read_since(self, offset: int) -> str:
        """offset 之后写入的全部内容。

        文件可能在 offset 之后被滚动(Spring Boot 默认 10MB 一滚:活动文件改名压缩成 <name>.<日期>.<N>.gz,
        再开一个新文件;mapper 层 DEBUG 日志让全量接口用例跑一遍就能写 ~20MB)。滚动后当前文件比 offset 还小,
        直接 seek 会读到空——offset 之后、滚动之前那一段在最新的归档里,拼上当前文件全文才是"offset 之后的全部"。
        只处理一次滚动:两次滚动之间至少 10MB,单个用例的观察窗口写不了这么多。
        """
        if not self.available:
            return ""
        if self.path.stat().st_size < offset:
            return self._latest_archive_since(offset) + self._read(0)
        return self._read(offset)

    def _read(self, offset: int) -> str:
        with self.path.open("rb") as f:
            f.seek(offset)
            return f.read().decode("utf-8", errors="replace")

    def _latest_archive_since(self, offset: int) -> str:
        archives = sorted(self.path.parent.glob(self.path.name + ".*"), key=lambda a: a.stat().st_mtime)
        if not archives:
            return ""
        latest = archives[-1]
        raw = gzip.decompress(latest.read_bytes()) if latest.suffix == ".gz" else latest.read_bytes()
        return raw[offset:].decode("utf-8", errors="replace")

    def lines_since(self, offset: int, containing: str) -> list[str]:
        return [ln for ln in self.read_since(offset).splitlines() if containing in ln]
