"""把被测服务的 HikariCP 连接池预热到上限,再跑接口自动化(KI-010:池大小是并发用例结果的隐藏变量)。

用法(在 tests/ 下):python tools/warm_pool.py            # 读 TICKETQA_ENV 对应的配置
退出码恒为 0:预热失败只打印警告,不阻断流水线——并发用例里的 warmed_pool fixture 会再试并断言
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

from framework.config import load_config      # noqa: E402
from framework.db import Db                   # noqa: E402
from framework.metrics import Metrics         # noqa: E402
from framework.pool import warm_pool          # noqa: E402


def main() -> int:
    config = load_config()
    metrics = Metrics(config.base_url)
    total, maximum = warm_pool(config.base_url, metrics, Db(config))
    print(f"hikaricp_connections={total:.0f} max={maximum:.0f} base_url={config.base_url}")
    if not maximum or total < maximum:
        print("WARNING: 连接池未撑到上限,并发用例的 warmed_pool fixture 会再试一次")
    return 0


if __name__ == "__main__":
    sys.exit(main())
