#!/usr/bin/env bash
# run_tests.sh —— 在 venv 沙箱里跑测试（不做 editable install，多沙箱共用一个 venv）
#
# 用法:
#     bash run_tests.sh <sandbox>                       # 整套
#     bash run_tests.sh <sandbox> tests/test_cli.py::test_x [more node ids...]
#
# venv 的选取顺序（多仓库支持）:
#     1. 环境变量 VENV
#     2. <sandbox>.hidden.json 里的 "venv"（make_sandbox.py 按 repos.json 写进去的）
#     3. harness/repos.json 里 monkeytype 那条（老行为）
#
# 环境变量:
#     SWESMITH_REPORT_JSON=/path/out.json   同时把 {nodeid: status} 精确名单落盘
#                                           （自写 plugin，不用官方那条丢参数化测试的正则）
#     VENV=$SWESMITH_LAB/venv-<repo>
#     SWESMITH_LAB=~/swesmith-lab                lab 根目录（默认 /root/workspace/swesmith-lab）
set -uo pipefail

SANDBOX="${1:?usage: run_tests.sh <sandbox> [node_ids...]}"
shift || true
HARNESS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SANDBOX="$(cd "$SANDBOX" && pwd)"

if [[ -z "${VENV:-}" && -f "${SANDBOX}.hidden.json" ]]; then
  # 只取 venv 一个字段；读失败就静默退回默认，绝不把 json 里别的内容打出来
  VENV="$(python3 -c 'import json,sys
try: print(json.load(open(sys.argv[1])).get("venv") or "")
except Exception: print("")' "${SANDBOX}.hidden.json" 2>/dev/null)"
fi
if [[ -z "${VENV:-}" ]]; then
  VENV="$(python3 "$HARNESS/repo_config.py" monkeytype venv 2>/dev/null)"
fi
VENV="${VENV:-${SWESMITH_LAB:-/root/workspace/swesmith-lab}/venv-monkeytype}"

PLUGIN_ARGS=()
if [[ -n "${SWESMITH_REPORT_JSON:-}" ]]; then
  PLUGIN_ARGS=(-p pytest_report_plugin)
fi

cd "$SANDBOX"
PYTHONPATH="$SANDBOX:$HARNESS" \
  "$VENV/bin/python" -m pytest \
  "${PLUGIN_ARGS[@]}" \
  --disable-warnings --color=no --tb=short -q -p no:cacheprovider \
  "$@"
exit $?
