"""把一次测试执行的结果汇总成质量数据平台的导入格式(POST /api/runs),可选直接 POST。

输入是标准产物,不依赖 Allure:
    --junit   一个或多个 JUnit XML(pytest --junitxml=…;Maven surefire-reports/TEST-*.xml 可用 glob)
    --jacoco  service/target/site/jacoco/jacoco.xml(行 / 分支覆盖率,coverageSource=jacoco)
    --coverage-xml  tests/coverage.xml(coverage.py,只有行覆盖率,coverageSource=coverage.py)

用法(在 tests/ 下):
    python -m pytest --junitxml=junit.xml
    python tools/publish_run.py --suite api --junit junit.xml --coverage-xml coverage.xml --post
    python tools/publish_run.py --suite unit --junit "../service/target/surefire-reports/TEST-*.xml" --jacoco ../service/target/site/jacoco/jacoco.xml --post
批次号默认:环境变量 GITHUB_RUN_ID(CI)或本地时间戳;提交号默认 GITHUB_SHA 或 git rev-parse。
xfail 的判定:pytest 的 junit 里 xfail 是 <skipped type="pytest.xfail">,和普通 skipped 分开算,通过率的分母两者都不含。
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime


def parse_junit(paths):
    total = passed = failed = skipped = xfailed = 0
    duration = 0.0
    started = None
    for path in paths:
        root = ET.parse(path).getroot()
        suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
        for s in suites:
            ts = s.get("timestamp")
            if ts:
                try:
                    t = datetime.fromisoformat(ts.replace("Z", ""))
                    started = t if started is None or t < started else started
                except ValueError:
                    pass
            duration += float(s.get("time") or 0)
            for case in s.findall("testcase"):
                total += 1
                sk = case.find("skipped")
                if sk is not None:
                    if (sk.get("type") or "").endswith("xfail"):
                        xfailed += 1
                    else:
                        skipped += 1
                elif case.find("failure") is not None or case.find("error") is not None:
                    failed += 1
                else:
                    passed += 1
    return dict(total=total, passed=passed, failed=failed, skipped=skipped, xfailed=xfailed,
                durationMs=int(duration * 1000), startedAt=started)


def parse_jacoco(path):
    root = ET.parse(path).getroot()
    out = {}
    for c in root.findall("counter"):
        covered, missed = int(c.get("covered")), int(c.get("missed"))
        if c.get("type") == "LINE":
            out["lineCoverage"] = round(covered * 100 / max(covered + missed, 1), 2)
        if c.get("type") == "BRANCH":
            out["branchCoverage"] = round(covered * 100 / max(covered + missed, 1), 2)
    out["coverageSource"] = "jacoco"
    return out


def parse_coverage_py(path):
    root = ET.parse(path).getroot()
    rate = root.get("line-rate")
    out = {"coverageSource": "coverage.py"}
    if rate is not None:
        out["lineCoverage"] = round(float(rate) * 100, 2)
    branch = root.get("branch-rate")
    if branch is not None and root.get("branches-valid") not in (None, "0"):
        out["branchCoverage"] = round(float(branch) * 100, 2)
    return out


def git_sha():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL).decode().strip()
    except Exception:  # noqa: BLE001
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--suite", required=True, help="unit / api / security / all")
    ap.add_argument("--junit", required=True, nargs="+", help="JUnit XML 路径或 glob")
    ap.add_argument("--jacoco")
    ap.add_argument("--coverage-xml")
    ap.add_argument("--batch", default=os.environ.get("GITHUB_RUN_ID") or datetime.now().strftime("local-%Y%m%d%H%M%S"))
    ap.add_argument("--source", default="ci" if os.environ.get("GITHUB_ACTIONS") else "local")
    ap.add_argument("--branch", default=os.environ.get("GITHUB_REF_NAME", ""))
    ap.add_argument("--note", default="")
    ap.add_argument("--post", action="store_true")
    ap.add_argument("--url", default=os.environ.get("PLATFORM_URL", "http://localhost:8081"))
    args = ap.parse_args()

    files = [p for pat in args.junit for p in sorted(glob.glob(pat))]
    if not files:
        raise SystemExit(f"没有匹配的 JUnit XML: {args.junit}")
    payload = parse_junit(files)
    payload["startedAt"] = (payload["startedAt"] or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    payload.update(batchNo=args.batch, suite=args.suite, source=args.source, branch=args.branch or None,
                   commitSha=os.environ.get("GITHUB_SHA") or git_sha(), note=args.note or None)
    if args.jacoco:
        payload.update(parse_jacoco(args.jacoco))
    elif args.coverage_xml:
        payload.update(parse_coverage_py(args.coverage_xml))

    body = json.dumps(payload, ensure_ascii=False, indent=1)
    if not args.post:
        print(body)
        return 0
    req = urllib.request.Request(f"{args.url}/api/runs", data=body.encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=15) as r:
        resp = json.loads(r.read().decode("utf-8"))
    print(f"batch {args.batch}: HTTP {r.status} code={resp.get('code')} id={resp.get('data', {}).get('id')} passRate={resp.get('data', {}).get('passRate')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
