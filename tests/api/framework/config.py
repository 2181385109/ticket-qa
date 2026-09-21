"""
环境配置。选择顺序:真实环境变量 > tests/api/config/<env>.env 文件 > 代码默认值。
环境名由 TICKETQA_ENV 决定(local / ci),默认 local。

为什么不用 YAML:多一个依赖换不来任何表达力——配置就是十来个 key=value。
为什么环境变量优先:CI 里 MySQL / WireMock 的端口和口令由 workflow 注入,不改文件。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def _load_env_file(name: str) -> dict[str, str]:
    path = _CONFIG_DIR / f"{name}.env"
    if not path.exists():
        raise FileNotFoundError(f"环境配置文件不存在: {path}(可选 local / ci)")
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


@dataclass(frozen=True)
class Config:
    env: str
    base_url: str
    request_timeout: float
    mysql_host: str
    mysql_port: int
    mysql_db: str
    mysql_user: str
    mysql_password: str
    wiremock_url: str
    rabbitmq_mgmt_url: str
    rabbitmq_user: str
    rabbitmq_password: str
    attachment_dir: Path | None
    # 故障注入:docker compose 命令模板(空 = 本环境不做故障注入,fault 用例 skip);服务文件日志路径(空 = 不断言日志)
    docker_compose_cmd: str = ""
    service_log_path: Path | None = None
    # 熔断相关:与 service/application.yml 的 llm.* 保持一致,用例按它算等待时间
    llm_timeout_ms: int = 3000
    circuit_failure_threshold: int = 5
    circuit_open_seconds: int = 60
    sla_minutes: dict[str, int] = field(default_factory=lambda: {"P0": 15, "P1": 60, "P2": 240})
    sla_scan_batch_size: int = 100
    hikari_max_pool_size: int = 20
    # 故障恢复时长的 SLO(ADR-020):依赖恢复后服务多久回到正常延迟。Redis 实测 23.6 s(Lettuce 重连退避),RabbitMQ 实测 11 s
    redis_recovery_slo_seconds: int = 45
    rabbit_recovery_slo_seconds: int = 45

    @property
    def mysql_dsn(self) -> dict:
        return dict(host=self.mysql_host, port=self.mysql_port, user=self.mysql_user,
                    password=self.mysql_password, database=self.mysql_db, charset="utf8mb4")


def load_config() -> Config:
    env = os.environ.get("TICKETQA_ENV", "local")
    file_values = _load_env_file(env)

    def pick(key: str, default: str | None = None) -> str:
        value = os.environ.get(key, file_values.get(key, default))
        if value is None:
            raise KeyError(f"缺少配置项 {key}(环境 {env})")
        return value

    attachment_dir = pick("ATTACHMENT_DIR", "")
    service_log = pick("SERVICE_LOG_PATH", "")

    def resolve(p: str) -> Path | None:
        if not p:
            return None
        return Path(p) if Path(p).is_absolute() else (_CONFIG_DIR.parent / p).resolve()

    return Config(
        env=env,
        base_url=pick("BASE_URL", "http://localhost:8080").rstrip("/"),
        request_timeout=float(pick("REQUEST_TIMEOUT", "15")),
        mysql_host=pick("MYSQL_HOST", "127.0.0.1"),
        mysql_port=int(pick("MYSQL_PORT", "3306")),
        mysql_db=pick("MYSQL_DATABASE", "ticket_qa"),
        mysql_user=pick("MYSQL_USER", "ticketqa"),
        mysql_password=pick("MYSQL_PASSWORD", "ticketqa123"),
        wiremock_url=pick("WIREMOCK_URL", "http://localhost:8089").rstrip("/"),
        rabbitmq_mgmt_url=pick("RABBITMQ_MGMT_URL", "http://localhost:15672").rstrip("/"),
        rabbitmq_user=pick("RABBITMQ_USER", "ticketqa"),
        rabbitmq_password=pick("RABBITMQ_PASSWORD", "rabbit123"),
        attachment_dir=resolve(attachment_dir),
        docker_compose_cmd=pick("DOCKER_COMPOSE_CMD", ""),
        service_log_path=resolve(service_log),
    )
