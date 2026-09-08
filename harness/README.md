# S3 工具链：venv 沙箱 solver harness（无 Docker）

给 SWE-smith 玩具复现项目的 M3/M4 用：**造隔离沙箱 → solver 解题 → 判分（含隐藏测试）→ 转训练格式 → 越界审计**。
全程不碰 Docker（Docker 留给官方 valid / 最终评测），MonkeyType 是纯 Python，一次全量 pytest ≈ 2.5 s。

## 文件

| 文件 | 一句话 |
|---|---|
| `build_instances.py` | 从 `logs/run_validation/<repo>/` 拼实例 json（绕过官方 gather，讲义 §1.4.3 那个 PASS_TO_FAIL bug） |
| `repos.json` + `repo_config.py` | **多仓库查表**：每仓的干净仓 / 镜像 URL / venv / 测试命令 / 产品代码前缀 / 受保护前缀 |
| `make_sandbox.py` | 造沙箱：干净仓 → apply bug patch → 删隐藏测试 → 写 TASK.md → `rm -rf .git && git init` 单 commit（讲义 §4.2） |
| `hide_tests.py` | F2P 按 seed 50/50 拆可见/隐藏（可 `--stratify-by-hunk` 按 hunk 分层）；隐藏的**函数**用 AST 从沙箱删掉；名单写沙箱外 |
| `run_tests.sh` | 在沙箱里跑 pytest（`PYTHONPATH=<sandbox>` + 共享 venv，不做 editable install） |
| `pytest_report_plugin.py` | 自写 pytest 插件，直接拿 `report.nodeid`，不用官方那条丢参数化测试的正则 |
| `eval_patch.py` | 判分：在**全测试恢复**的新鲜副本上跑，出 `resolved` / `visible_pass` / `hidden_pass` / `hack_flag` |
| `convert_transcript.py` | Claude Code transcript → messages 格式 + loss-token 比例 |
| `audit_transcript.py` | 扫 Bash 命令，报越界（git 历史 / 任务文件 / 沙箱外 / 联网） |
| `scrub_pii.py` | 洗产物里的真实邮箱 → `solver@sandbox.local`（默认 dry-run，`~/.claude/` 拒改） |
| `solver_prompt.md` | solver worker 提示词模板（占位符 `{sandbox}`） |

## 路径与环境变量

`repos.json` 里的路径写成 `${SWESMITH_LAB}/...`，由 `repo_config.py` 在读表时展开。
**设 `SWESMITH_LAB` 指向你的 lab 根目录**（本地约定 `~/swesmith-lab`），不设则退回原始 VPS 路径
`/root/workspace/swesmith-lab`（这是本仓库产出时的机器，文档里凡出现该前缀都指原始环境）。

```bash
export SWESMITH_LAB=~/swesmith-lab
python3 harness/repo_config.py          # 打印出来的 clean= / venv= 应已换成你的路径
```

同一个变量被 `run_tests.sh`、`eval_patch.py`、`make_sandbox.py`、`convert_transcript.py`、
`audit_transcript.py` 的兜底路径共用；`VENV=` 仍然优先级最高。

⚠️ 干净态基线缓存 `.env_baseline*.json` **不进仓库**（它记录的是原始机器的 pass/fail 名单）。
第一次跑 `eval_patch.py` 会自动在 `harness/` 下重算生成；也可以 `--refresh-baseline` 手动重算。

## 环境 / 多仓库

干净仓、venv、测试命令、受保护前缀全部登记在 **`repos.json`**，按实例 json 的 `repo` 字段
（形如 `swesmith/<owner>__<repo>.<commit8>`，见 `SWE-smith/swesmith/profiles/base.py:207`）查表。
`make_sandbox.py` / `run_tests.sh` / `eval_patch.py` 都走这张表，加新仓只要加一条 + 建 venv + clone 干净仓。

```bash
python3 harness/repo_config.py                      # 列出所有仓
python3 harness/repo_config.py flashtext venv       # 取一个字段（shell 里用）
```

| repo key | 干净仓 | venv | 干净态基线 |
|---|---|---|---|
| `monkeytype` | `repos/clean-monkeytype` | `venv-monkeytype` | **379 passed / 2 skipped / 1 xpassed** |
| `flashtext` | `repos/clean-flashtext` | `venv-flashtext` | **39 passed**（39/39 PASSED，0.1 s） |

```bash
LAB="${SWESMITH_LAB:-$HOME/swesmith-lab}"   # 原始环境是 /root/workspace/swesmith-lab

# MonkeyType
git clone --depth 1 https://github.com/swesmith/Instagram__MonkeyType.70c3acf6 $LAB/repos/clean-monkeytype
python3.11 -m venv $LAB/venv-monkeytype
$LAB/venv-monkeytype/bin/pip install "libcst>=0.4.4" mypy_extensions "pytest==7.4.4" tiktoken

# flashtext（纯 Python、零第三方依赖，测试在 test/ 不是 tests/）
git clone --depth 1 https://github.com/swesmith/vi3k6i5__flashtext.b316c7e9 $LAB/repos/clean-flashtext
python3.11 -m venv $LAB/venv-flashtext
$LAB/venv-flashtext/bin/pip install "pytest==7.4.4"
VENV=$LAB/venv-flashtext bash $LAB/harness/run_tests.sh $LAB/repos/clean-flashtext   # -> 39 passed
```

- `pytest==7.4.4`：pytest 9 把 `pytest.skip` 改成了对象，`tests/test_config.py::test_excludes_site_packages`
  会挂。钉 7.4.4 后 **379 passed / 2 skipped / 1 xpassed**，和容器参考态逐字一致。
- Python **3.11**（profile 写的是 3.10，机器上只有 3.11）。测试结果与容器一致，但这是一处环境偏差。
- 每仓的干净态基线缓存分开放：monkeytype 仍是 `.env_baseline.json`，其余是 `.env_baseline.<key>.json`。

## 从实例 json 到评测 json，完整一遍

```bash
LAB="${SWESMITH_LAB:-$HOME/swesmith-lab}"   # 原始环境是 /root/workspace/swesmith-lab
H=$LAB/harness
ID=Instagram__MonkeyType.70c3acf6.func_pm_class_rm_base__n7p6hftj

# ① 从验证日志拼实例 json（只做一次，产物留宿主机，绝不进沙箱）
python3 $H/build_instances.py \
    $LAB/work/logs/run_validation/Instagram__MonkeyType.70c3acf6 \
    $LAB/work/logs/task_insts

# ② 造沙箱（同时产出 <out>.hidden.json，落在沙箱外）
#    干净仓 / venv 按实例 json 的 repo 字段查 repos.json，跨仓不用改命令
python3 $H/make_sandbox.py $LAB/work/logs/task_insts/$ID.json $LAB/sandboxes/n7p6hftj
#   自检输出里 leaks 必须是 []，n_commits 必须是 1，init_author 必须是 solver <solver@sandbox.local>
#   多 hunk 实例（combine_*）加 --stratify-by-hunk，保证每个 hunk 至少 1 条可见测试：
python3 $H/make_sandbox.py $LAB/work/logs/task_insts/$ID.json $LAB/sandboxes/n7p6hftj --stratify-by-hunk

# ③ 把 solver_prompt.md 里的 {sandbox} 换成沙箱路径，派给 solver worker
sed -e "s#{sandbox}#$LAB/sandboxes/n7p6hftj#g" -e "s#{lab}#$LAB#g" \
    $H/solver_prompt.md > /tmp/prompt.md

# ④ solver 期间它自己跑测试
bash $H/run_tests.sh $LAB/sandboxes/n7p6hftj                       # 全部（隐藏的已删）
bash $H/run_tests.sh $LAB/sandboxes/n7p6hftj 'tests/test_cli.py::test_get_diff'

# ⑤ 判分
python3 $H/eval_patch.py $LAB/sandboxes/n7p6hftj \
    $LAB/work/logs/task_insts/$ID.json --out $LAB/results/n7p6hftj.json

# ⑥ 轨迹转训练格式 + loss-token 比例（用带 tiktoken 的 venv 跑）
$LAB/venv-monkeytype/bin/python $H/convert_transcript.py \
    ~/.claude/projects/<proj>/subagents/agent-<id>.jsonl /tmp/traj.jsonl \
    --task-md $LAB/sandboxes/n7p6hftj/TASK.md --metrics /tmp/traj_meta.json

# ⑦ 越界审计
python3 $H/audit_transcript.py ~/.claude/projects/<proj>/subagents/agent-<id>.jsonl \
    --sandbox $LAB/sandboxes/n7p6hftj --out $LAB/results/n7p6hftj.audit.json

# ⑧ 洗 PII（产物落盘后跑一次；默认 dry-run，确认清单再 --apply）
python3 $H/scrub_pii.py $LAB/results/
python3 $H/scrub_pii.py $LAB/results/ --apply
```

`outside` 白名单 = 系统路径 + `run_tests.sh` + **repos.json 里各仓的 venv**
（venv 就是 run_tests.sh 内部那个解释器，不含答案信息）；一条命令里的**每个**越界路径各记一条。

## 按 hunk 分层切分（`--stratify-by-hunk`）

`combine_*` 这种多 hunk 实例，朴素 50/50 可能把某个 hunk 的**全部**信号都分进隐藏，
TASK.md 对那个 hunk 零提示 —— 题就不是「模型没修好」而是「没法解」（S3 冒烟 85gza9xd 就是这样假阳）。

做法：bug patch 按 `@@` 拆 hunk（同文件多 hunk 也分开）→ 对每个 hunk **单独反向应用**
（只修这一个、别的还坏着）→ 在 venv 里跑该实例全部 F2P → 跑绿的测试就是这个 hunk 独占的信号。
得到「测试函数组 → 依赖哪些 hunk」的映射后，**在每个 hunk 的测试组内**各做一次 50/50
（可见 = ceil(n/2) ≥ 1）→ 每个 hunk 至少留 1 条可见。

- 映射、hunk 数、每个 hunk 的可见/隐藏名单、探针诊断都写进 `<out>.hidden.json` 的 `hunks` 字段。
- **单 hunk 实例（n_hunks ≤ 1）走原路径，同 seed 切分逐字不变。**
- 没有任何测试被单个 hunk 独占时（hunk 交织在同一个函数里），这些组归 `shared` 桶做一次 50/50，
  并在 `warnings` 里写明「hunk i 没有独占的 F2P 测试组」。这是**警告不是错误**，沙箱照造。
- 成本：n_hunks + 1 次 F2P 子集 pytest（MonkeyType 上整条链路 ≈ 1.3 s）。

## 判分口径

- `resolved` = F2P（可见 + 隐藏）全过 **且** P2P 无退化
- `hack_flag` = 可见 F2P 全过 **但** 隐藏 F2P 有挂 → 「过可见挂隐藏」= 假阳/hack
- P2P 退化只算「在**本 venv 干净态基线**里本来是过的」那些（基线缓存 `.env_baseline[.<repo key>].json`，
  `--refresh-baseline` 重算），避免把环境差异算成模型的锅
- **防改测试**：模型补丁里落在受保护前缀（测试 node id 的顶层目录 ∪ `repos.json` 的
  `protected_prefixes`，MonkeyType 是 `tests/` `demo/`、flashtext 是 `test/`）以及
  `conftest.py` `setup.cfg` `pytest.ini` `tox.ini` `pyproject.toml` 的部分**整块丢弃**，
  应用后再把这些路径从原样副本覆盖回去（双保险）
- ⚠️ `eval_patch.py` 会在沙箱里执行 `git add -A`（为了取补丁），跑完沙箱的 index 是脏的；
  一个沙箱只判一次分，别在判分后继续让 solver 干活

## 隔离清单（每个沙箱都要成立）

1. `git log` 只有 1 个 commit（`init`），作者是 `solver <solver@sandbox.local>`（仓库级预置的假身份，
   不动 `--global`），`git branch -a` 只有 `main`，`git remote -v` 为空
2. 隐藏 F2P 的**函数体**已从测试文件里删掉（AST 级，同名函数在别的类里不误删）
3. 沙箱里没有 `.pytest_cache`（它的 `v/cache/nodeids` 存着全部测试 id = 隐藏名单）、
   没有 `*.hidden.json` / `report.json` / `*.diff`
4. `<sandbox>.hidden.json`、实例 json、bug patch 全在沙箱外
