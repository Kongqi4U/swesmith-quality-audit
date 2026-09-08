"""pytest plugin: dump exact node-id -> status map to JSON.

用法（不直接调用，由 run_tests.sh / eval_patch.py 注入）:
    PYTHONPATH=<sandbox>:<harness> SWESMITH_REPORT_JSON=/path/out.json \
        <venv>/bin/python -m pytest -p pytest_report_plugin ...

为什么自己写而不是复用官方 log_parser：官方 `^(\\S+)\\s+PASSED` 正则会把
参数化测试 id 里带空格的那些（MonkeyType 上是 10 个）静默丢掉（讲义 §1.3.5）。
这里直接拿 pytest 内部的 report.nodeid，零解析、零丢失。
"""

import json
import os

_results = {}


def pytest_runtest_logreport(report):
    nid = report.nodeid
    if report.when == "call":
        if report.passed:
            _results[nid] = "XPASS" if hasattr(report, "wasxfail") else "PASSED"
        elif report.failed:
            _results[nid] = "FAILED"
        else:  # skipped
            _results[nid] = "XFAIL" if hasattr(report, "wasxfail") else "SKIPPED"
    elif report.when in ("setup", "teardown"):
        if report.failed:
            _results[nid] = "ERROR"
        elif report.skipped and nid not in _results:
            _results[nid] = "XFAIL" if hasattr(report, "wasxfail") else "SKIPPED"


def pytest_collectreport(report):
    if report.failed:
        _results[report.nodeid] = "COLLECT_ERROR"


def pytest_sessionfinish(session, exitstatus):
    path = os.environ.get("SWESMITH_REPORT_JSON")
    if not path:
        return
    with open(path, "w") as f:
        json.dump({"results": _results, "exitstatus": int(exitstatus)}, f)
