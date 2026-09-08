# harness 修订（0908）：四处修复 + 多仓库支持

对象 `/root/workspace/swesmith-lab/harness/`。venv 自测，**没碰 Docker**、没 push，`sandboxes/s3-*`
与 `results/` 已有文件除 scrub 外未改。问题来源见「冒烟-S3-solver结果-0907」。

## 改动清单

1. **git 假身份** `make_sandbox.py`：`git init` 后加**仓库级**（非 `--global`）`user.name solver` /
   `user.email solver@sandbox.local`，init commit 用它；自检新增 `init_author` 断言（不符进 `leaks`）。
   `solver_prompt.md` 收尾命令未动。
2. **audit 白名单与 break** `audit_transcript.py`：`ALLOW_ABS_PREFIXES` 改为从 `repos.json` 动态取
   **所有仓的 venv**（加新仓自动生效）；`outside` 去掉 `break`，一条命令报**全部**去重越界路径。
3. **按 hunk 分层切分** `hide_tests.py --stratify-by-hunk`（`make_sandbox.py` 透传）：patch 按 `@@`
   拆 hunk（同文件多 hunk 也分，兼容无 `diff --git` 头的 patch）→ 每个 hunk 单独 `git apply -R` →
   venv 跑全部 F2P → 跑绿的即该 hunk 独占信号 → 得「测试组 → 依赖哪些 hunk」映射 →
   **在每个 hunk 的组内**各做 50/50（可见 = ceil(n/2) ≥ 1）。映射 / hunk 数 / 每 hunk 名单 / 探针
   诊断写进 `<out>.hidden.json` 的 `hunks`；无独占测试的 hunk 进 `warnings`。**单 hunk 走原路径。**
4. **scrub 邮箱** 新增 `scrub_pii.py`（默认 dry-run，`~/.claude/` 拒改），已对 `results/` `--apply`。
5. **多仓库** 新增 `repos.json` + `repo_config.py`（查表接受 `swesmith/<owner>__<repo>.<c8>` / 仓名 /
   短 key 三种写法）；`make_sandbox.py`、`run_tests.sh`、`eval_patch.py` 按实例 json 的 `repo` 字段查表
   取干净仓 / venv / 受保护前缀 / 产品代码前缀；基线缓存按仓分文件（monkeytype 沿用老
   `.env_baseline.json`）。建了 `repos/clean-flashtext` + `venv-flashtext`（py3.11 + pytest==7.4.4）。
   README 已更新（新选项 / repos.json / 多仓用法 / 洗 PII ⑧）。

## 自测：**全过**

- `s3b-85gza9xd`（`--stratify-by-hunk`）：**n_hunks = 2**；hunk0 可见1/隐藏0、hunk1 可见2/隐藏1 →
  **每 hunk ≥1 可见**；`leaks == []`；commit 数 1；作者 `solver <solver@sandbox.local>`。
- 分层前后：旧 可见5/隐藏3，`TestRewriteLargeUnion`（hunk0 的**全部**信号）整组进隐藏 → 假阳；
  新 可见7/隐藏1，该组进可见，TASK.md 里有了 hunk0 提示。
- `s3b-0mdq6eqw`（单 hunk，同 seed）：`visible`/`hidden`/`*_funcs`/`n_funcs_deleted` 与
  `s3-0mdq6eqw.hidden.json` **逐字相同**；不带 `--stratify` 的 85gza9xd 也与旧 hidden.json 逐字相同。
- audit 重跑 `agent-a59d1b84a95645ba4.jsonl`：11 tool calls，**0 violations / clean**（原 1 条误报）；
  合成用例「1 条命令 4 个越界路径」4 条全报、重复去重。
- hunk 拆分器全量 54 个实例 json：`@@` 计数 == hunk 数、路径全解析；分布 1×37 / 2×13 / 3×3 / 4×1。
- `eval_patch.py` 端到端（gold 反向）：`379 passed, 2 skipped, 1 xpassed`、`resolved=True`、
  `p2p_regressions=0`；flashtext 侧 `run_tests.sh` + `env_baseline` 跑通。
- 85gza9xd 整条造沙箱链路（含 3 次 F2P 子集 pytest）**1.3 s**，内存无明显变化。

## scrub 清单

`<作者真实邮箱>` → `solver@sandbox.local`，**4 个文件各 1 处，共 4 处**：
`results/s3-{0mdq6eqw,0pr4euv6,85gza9xd,k0voxhym}.traj.jsonl`（都在 solver 那条
`git config user.email ...` 命令里）。替换后仍是合法 JSONL。`*.traj_meta.json` / `*.audit.json` /
判分 `*.json` **零命中**。`you@example.com` 保留 —— git `Author identity unknown` 提示自带的占位符。
`~/.claude/` 下原始 transcript **一字节没动**。

## flashtext 干净仓基线

`repos/clean-flashtext` + `venv-flashtext`（py3.11 / pytest 7.4.4）：**39 passed，0.07~0.14 s**，
逐条 `PASSED` 39/39，0 skipped / 0 xfail，与 S1S2「39 test def」一致。测试目录是 **`test/`**（不是
`tests/`），已写进 `repos.json`。实例 json 尚未产出，只做到「干净仓 + venv + 条目 + 基线」。

## 两处没把握

1. **hunk 归属只能识别「被单个 hunk 独占」的测试。** 抽测 `combine_file__3io24ypb`（cli.py 4 hunk），
   **4 个 hunk 全无独占测试组**——单独修任何一个都没测试变绿，13 个 F2P 组全进 `shared` 桶做一次性
   50/50，等于退回老口径（有 warning、不报错）。更强的归属要跑 2^k 个子集或按覆盖率归因，判断
   不划算；所以「每个 hunk 至少 1 条可见」是**尽力而为**，不是硬保证。
2. **分层会稀释隐藏测试的检出力。** 85gza9xd 隐藏从 3 条降到 1 条（每桶 ceil(n/2) 可见，桶内只有
   1 组时全可见）。函数组少、hunk 多的实例，`hack_flag` 抓假阳的能力会下降。「是否对所有
   `combine_*` 默认开」是 policy，没擅自改默认值——**默认仍是关的**。

另：`results/s3-k0voxhym.audit.json` 那条误报**没覆盖**（按要求不动 results 已有文件）。
