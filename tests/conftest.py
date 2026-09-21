"""
tests/ 根 conftest:api/ 和 security/ 共用。

fixture 分三层(ADR-012):
  session  只建一次、只读或无状态:配置、各身份的 ApiClient、DB / WireMock / RabbitMQ / 指标 客户端、服务就绪检查
  module   一个测试文件共用、只读的数据:module_ticket(供只读用例反复 GET,省造数)
  function 每个用例独占、会被改动的数据:tickets(TicketFactory,结束后硬删)、metrics_before(指标快照)

排序钩子:带 circuit 标记的用例排到最后——它们会把熔断器打开 60 秒,放中间会污染后面所有 LLM 用例;
带 fault 标记的(docker compose stop 中间件)排在 circuit 之后、整个会话的最末尾。
"""
from __future__ import annotations

import sys
from pathlib import Path

import allure
import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent / "api"))   # security/ 也能 import framework

from framework.client import ApiClient            # noqa: E402
from framework.config import Config, load_config  # noqa: E402
from framework.db import Db                       # noqa: E402
from framework.factory import TicketFactory       # noqa: E402
from framework.faults import ComposeFaults, ServiceLog  # noqa: E402
from framework.metrics import Metrics             # noqa: E402
from framework.mq import RabbitMgmt               # noqa: E402
from framework.pool import warm_pool              # noqa: E402
from framework.users import Users                 # noqa: E402
from framework.waits import wait_until            # noqa: E402
from framework.wiremock import WireMock           # noqa: E402


# ---------------------------------------------------------------------- 收集阶段

def pytest_collection_modifyitems(config, items):
    """circuit 用例排到后面、fault 用例排到最后;security 目录自动打 security 标记"""
    fault, circuit, rest = [], [], []
    for item in items:
        if "security" in Path(str(item.fspath)).parts:
            item.add_marker(pytest.mark.security)
        if item.get_closest_marker("fault"):
            fault.append(item)
        elif item.get_closest_marker("circuit"):
            circuit.append(item)
        else:
            rest.append(item)
    items[:] = rest + circuit + fault


# ---------------------------------------------------------------------- session 层

@pytest.fixture(scope="session")
def config() -> Config:
    return load_config()


@pytest.fixture(scope="session")
def api(config) -> ApiClient:
    """默认 ADMIN 身份;换身份用 api.as_user(Users.AGENT_A)"""
    return ApiClient(config.base_url, Users.ADMIN, config.request_timeout)


@pytest.fixture(scope="session")
def anon(api) -> ApiClient:
    return api.as_user(None)


@pytest.fixture(scope="session")
def db(config) -> Db:
    return Db(config)


@pytest.fixture(scope="session")
def wiremock(config) -> WireMock:
    return WireMock(config.wiremock_url)


@pytest.fixture(scope="session")
def rabbit(config) -> RabbitMgmt:
    return RabbitMgmt(config.rabbitmq_mgmt_url, config.rabbitmq_user, config.rabbitmq_password)


@pytest.fixture(scope="session")
def metrics(config) -> Metrics:
    return Metrics(config.base_url)


@pytest.fixture(scope="session")
def faults(config) -> ComposeFaults:
    """docker compose stop/start;配置里没给命令模板就 skip 整个用例"""
    f = ComposeFaults(config.docker_compose_cmd)
    if not f.enabled:
        pytest.skip("DOCKER_COMPOSE_CMD 未配置,本环境不做故障注入")
    return f


@pytest.fixture(scope="session")
def service_log(config) -> ServiceLog:
    return ServiceLog(config.service_log_path)


@pytest.fixture(scope="session", autouse=True)
def service_ready(config, api, db, wiremock):
    """整个会话开始前确认三件事:服务健康、MySQL 可连、WireMock 可连。任一不满足直接失败,不让几十个用例逐个报连接错误。"""
    try:
        health = wait_until(lambda: api.health(), lambda r: r.status == 200 and r.path("status") == "UP",
                            timeout=30, interval=2, what=f"{config.base_url}/actuator/health = UP")
    except (AssertionError, requests.RequestException) as e:
        pytest.exit(f"被测服务未就绪: {e}", returncode=3)
    components = health.path("components") or {}
    for name in ("db", "redis", "rabbit"):
        if components.get(name, {}).get("status") != "UP":
            pytest.exit(f"服务健康检查 {name} 不是 UP: {components.get(name)}", returncode=3)
    if db.scalar("SELECT COUNT(*) AS c FROM agent") != 6:
        pytest.exit("agent 表不是 6 个种子坐席,请先 docker compose down -v && up -d", returncode=3)
    if not wiremock.healthy():
        pytest.exit(f"WireMock 未就绪: {config.wiremock_url}", returncode=3)
    allure.attach(f"env={config.env} base_url={config.base_url}\nhealth={health.json}", name="environment",
                  attachment_type=allure.attachment_type.TEXT)
    yield


# ---------------------------------------------------------------------- module 层

@pytest.fixture(scope="module")
def module_factory(api, db) -> TicketFactory:
    """module 级工厂:造只读共享数据,模块结束统一清理"""
    f = TicketFactory(api, db)
    yield f
    f.cleanup()


@pytest.fixture(scope="module")
def module_ticket(module_factory) -> dict:
    """一张 agent_a 名下 ASSIGNED 的只读工单,供同一文件里的读接口用例反复使用"""
    return module_factory.assigned(Users.AGENT_A)


# ---------------------------------------------------------------------- function 层

@pytest.fixture
def tickets(api, db) -> TicketFactory:
    """用例级工厂:用例结束硬删所有它造过的工单"""
    f = TicketFactory(api, db)
    yield f
    f.cleanup()


@pytest.fixture
def metrics_before(metrics):
    """用例开始时的指标快照,用 metrics.delta(metrics_before, ...) 断差值"""
    return metrics.snapshot()


@pytest.fixture
def warmed_pool(config, metrics, db):
    """并发用例前把 HikariCP 撑到上限(KI-010):CI 和本地在同一起点上跑,结果才可比。返回 (total, max)"""
    total, maximum = warm_pool(config.base_url, metrics, db)
    allure.attach(f"hikaricp_connections={total} max={maximum}", name="连接池预热", attachment_type=allure.attachment_type.TEXT)
    assert maximum == 0 or total >= maximum, f"连接池未撑满: total={total} max={maximum}"
    return total, maximum


@pytest.fixture
def clean_wiremock_requests(wiremock):
    """清空挡板请求日志,让本用例只看到自己触发的请求"""
    wiremock.reset_requests()
    yield wiremock
