# swesmith-quality-audit

> **SWE-smith 合成管线的玩具规模复现 + 七维数据质量审计 + 合成数据 scaling 实验。**

在 [SWE-smith](https://github.com/SWE-bench/SWE-smith) 合成的 SWE 任务实例上，
先量出「**不训练就能量**」的六维数据质量，再真训一个小模型画 scaling 曲线，
回答一个对照表里普遍空白的问题：**哪一维质量真的预测训练收益？**

比官方管线多做的两件事：

1. **隐藏测试**（gold test overlay）—— 每个实例的 F2P 测试拆成可见 / 隐藏两份，
   隐藏那份从工作区物理删掉、评测时叠回。由此「过可见测试但挂隐藏测试」= **可直接量的假阳 / hack 率**。
2. **验证器假阳审计 + 轨迹越界审计** —— 官方 `valid` 只看测试红绿，这里还看补丁语义和 solver 有没有作弊。

---

## 七维质量口径

| 维度 | 怎么量 | 需要训练？ |
|---|---|---|
| 难度 | API 模型在该题上的 pass-rate（k 次采样） | 否 |
| 区分度 | 同题多次采样的方差 | 否 |
| 多样性 | bug 策略 / 文件 / 仓库分布 | 否 |
| 成本 | 秒/任务、$/任务、loss-token 比例 | 否 |
| 垃圾率 | 抽样人审 + flaky 检测 | 否 |
| 正确性 | 验证器假阳审计 + issue 泄漏审计 | 否 |
| **泛化性** | **训了能不能提点** | **是** ← 整个项目要卡的就是这一维 |

细节见 [`docs/PROJECT.md`](docs/PROJECT.md)。

---

## 里程碑 v2

| # | 内容 | 状态 |
|---|---|---|
| M1 | procedural + combine 造 ~300 实例，每实例做可见/隐藏测试拆分；留出 40 题 | 冒烟通过（数据已在本仓库 `data/`） |
| M2 | LLM 写 issue（官方模板）+ well-defined / 答案泄漏审计 | 待开 |
| M3 | k=4 跑 60 题：难度、区分度、loss-token 比例 | 冒烟通过（4 题 3 解、loss-token 0.168、0 越界，见 `results/`） |
| M4 | 假阳（过可见挂隐藏）+ 轨迹越界审计 | 待开 |
| M5 | 老师轨迹上量（池子必须显著大于最大 N，否则「筛选」退化成「全取」） | 待开 |
| M6 | 租卡 LoRA SFT：base / N30 / N100 / N300-随机 / N300-筛选 | 待开 |
| M7 | 留出集评测（mini-SWE-agent，pass@4，隐藏测试叠回）+ 报告 | 待开 |
| M8 / M9 | 扩展：RLVR 单轮 patch GRPO；一轮自训练 vs 蒸馏 | 可选 |

---

## 仓库结构

| 目录 | 内容 |
|---|---|
| `harness/` | **核心工具链**：造沙箱 / 拆隐藏测试 / 跑测试 / 判分 / 轨迹转训练格式 / 越界审计 / 洗 PII。全程不碰 Docker。见 [`harness/README.md`](harness/README.md) |
| `patches/` | 打给 SWE-smith 源码的补丁（容器内存硬限）+ 版本钉死清单 |
| `data/task_insts/` | M1 产出的任务实例 json（55 个文件，含一个 202 条的 repo 级汇总；约 7.8MB） |
| `data/validation_reports/` | 官方 `run_validation` 的 `report.json`，按 `<repo>/<instance>/` 组织（330 份：MonkeyType 286 / flashtext 34 / dominate 10） |
| `data/bug_gen/` | bug 生成阶段的 `*_patches.json` 汇总（12 份，约 3.2MB） |
| `reports/` | 各阶段冒烟报告（中文，含数与结论） |
| `results/` | M3 冒烟 4 道题的判分 / 越界审计 / 老师轨迹（已 scrub PII） |
| `docs/` | [`PROJECT.md`](docs/PROJECT.md)（项目说明）、[`SETUP-WSL2.md`](docs/SETUP-WSL2.md)（本地环境从零搭建） |
| `tasks/` | 执行用的主提示词 |

---

## 本地怎么跑

**完整步骤看 [`docs/SETUP-WSL2.md`](docs/SETUP-WSL2.md)**（Windows 11 + WSL2 + Docker Desktop，从零，含 8 条验证清单）。

一分钟版：

```bash
# 1) 环境变量：harness 的所有路径都从它读
export SWESMITH_LAB=$HOME/swesmith-lab

# 2) SWE-smith 源码装 + 打内存补丁（PyPI 上的 swe-smith 是空壳）
git clone https://github.com/SWE-bench/SWE-smith $SWESMITH_LAB/SWE-smith
cd $SWESMITH_LAB/SWE-smith && git checkout 9b74ac0
python3.11 -m venv venv && ./venv/bin/pip install -e '.[generate]'
./venv/bin/pip install swebench==4.1.0 fastcore==1.7.29
git apply ~/swesmith-quality-audit/patches/swesmith-utils-memlimit.patch

# 3) harness 侧：干净仓 + venv（pytest 钉 7.4.4）
#    见 harness/README.md「环境 / 多仓库」

# 4) 确认查表已指向本地
python3 ~/swesmith-quality-audit/harness/repo_config.py   # 不应再出现 /root/workspace
```

### 路径约定

`harness/repos.json` 里的路径写成 `${SWESMITH_LAB}/...`，由 `harness/repo_config.py` 在读表时展开；
`run_tests.sh` / `eval_patch.py` / `make_sandbox.py` / `convert_transcript.py` / `audit_transcript.py`
的兜底路径共用同一个变量（`VENV=` 仍然优先级最高）。

> ⚠️ 仓库和报告里出现的 **`/root/workspace/swesmith-lab`** 是**原始环境**（一台 2GB 内存的 VPS）的路径，
> 保留下来是为了让报告里的日志/命令可追溯，**不需要在本地复现它**。
> 不设 `SWESMITH_LAB` 时 harness 会退回这个默认值 —— 所以第一件事就是 export 它。

---

## 硬约束（从两次死机来的）

原始环境两次整机失去响应，都在验证阶段：SWE-smith 给容器的 `mem_limit="10g"`（机器只有 2GB）
撞上合成出来的**死循环 bug**，内存吃穿进 swap 抖动、内核不触发 OOM-kill。

- 容器必须有内存硬限（`mem_limit` + `memswap_limit` + `pids_limit`）。本机 16GB 可放宽到 `2g`。
- Docker 验证任务不与其它重进程并行；验证一律带 `--timeout 60`。
- **小批量**（≤10 候选）跑完看内存无异常再下一批。

详见 [`docs/PROJECT.md`](docs/PROJECT.md) §五、[`patches/README.md`](patches/README.md)。

---

## 已知环境偏差

| 项 | 值 | 说明 |
|---|---|---|
| SWE-smith | commit `9b74ac0` | 补丁按这个 commit 的行号生成 |
| `swebench` / `fastcore` | `4.1.0` / `1.7.29` | 版本敏感，`pip install -e` 之后必须再钉一次 |
| `pytest` | `7.4.4` | pytest 9 把 `pytest.skip` 改成对象，MonkeyType 的 `test_excludes_site_packages` 会挂 |
| Python | 3.11 | SWE-smith profile 写的是 3.10；测试结果与容器逐字一致，但这是一处偏差 |
| tokenizer | tiktoken `cl100k_base` | **不是 Qwen 分词器**，loss-token 比例只作量级参考 |

---

## 参考

- SWE-smith（合成管线）：<https://github.com/SWE-bench/SWE-smith>，论文 arXiv 2504.21798
- 隐藏测试叠回：Intern-S2-Preview，arXiv 2608.13505
- rollout 方差当区分度：RODS，arXiv 2606.19047
- 执行奖励的 RL：SWE-RL，arXiv 2502.18449

## License

[MIT](LICENSE)
