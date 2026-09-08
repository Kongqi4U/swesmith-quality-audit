# 项目说明 · SWE-smith 玩具规模复现 + 合成数据 scaling 实验

> 本文由项目笔记的「0907 v2 立项」与「0908 事故与硬约束」两节整理而成。
> 文中「作者」= 项目执行者，「规划方」= 出任务书与验收标准的规划角色。

## 定位

数据合成 scale 这条线的**主项目**（不是文档）。目标：

1. 跑通一条成熟的环境/任务合成管线（[SWE-smith](https://github.com/SWE-bench/SWE-smith)），量出每个环节的产率与成本；
2. 加一个它没有的环节 —— **验证器假阳审计**（测试过了但补丁语义错）；
3. 在合成实例上真训一个小模型，画**合成数据的 scaling 曲线**，回答「哪一维质量预测训练收益」。

---

## 一、七维质量口径

七维（数据质量的一种常见拆法）中 **6 维不需要训练就能量**：

| 维度 | 怎么量 | 在哪个里程碑 |
|---|---|---|
| 难度 | API 模型在该题上的 pass-rate（k 次采样） | M3 |
| 区分度 | 同题多次采样的方差 | M3 |
| 多样性 | bug 策略 / 文件 / 仓库分布 | M1、M2 |
| 成本 | 秒/任务、$/任务、**loss-token 比例** | M1、M3 |
| 垃圾率 | 抽样人审 + flaky 检测 | M1 |
| 正确性 | 验证器假阳审计（= M4）；issue 是否泄漏答案（well-defined 审计） | M2、M4 |
| **泛化性** | **唯一必须靠训练才能卡的一维** | M6、M7 |

终产物 = 一份「管线 × 七维」质量报告 + 一条 scaling 曲线。

---

## 二、v2 主线（0907 立项）

**一句话**：在 SWE-smith 合成的实例上，量出「不训练就能量」的六维质量，然后真训 ——
画合成数据的 scaling 曲线，看**质量筛选能不能移动曲线**，回答「哪一维预测训练收益」。

### 贴前沿的五处设计（每处有出处）

1. **隐藏测试（gold test overlay）**
   每个实例的 F2P 测试拆成可见 / 隐藏两份，隐藏那份从工作区**物理删掉**，评测时再叠回
   （Intern-S2-Preview, arXiv 2608.13505）。
   由此「**过可见测试但挂隐藏测试**」= 可直接量的 hack / 假阳率，评测口径比官方 `valid` 更硬。

2. **难度 = rollout 方差**
   k=4 的 pass-rate 当难度、方差当区分度（RODS, arXiv 2606.19047；GRPO 里零方差组无梯度）。
   SFT 筛法与 RL 筛法分开：**SFT 留老师能解的，RL 留 0 < p < 1 的**。

3. **老师轨迹 = bash-only 单命令格式**
   与 mini-SWE-agent 同构；只在 assistant token 上算 loss，并报 **loss-token 比例**
   （Intern-S2 的口径最细）。学生评测同样走 mini-SWE-agent + vLLM，保证训练/评测格式一致。

4. **等预算多样性对照**（TDScaling：多样性 > 数量）
   同样的 N，1 个仓库 vs 2 个仓库。⚠️ 可选，受原始环境内存限制。

5. **两枚扩展**
   - RLVR 单轮 patch GRPO，奖励 = **容器里真跑测试**（SWE-RL, arXiv 2502.18449 用的是相似度奖励，执行奖励更硬），ms-swift 跑；
   - 一轮自训练（学生拒绝采样再训）vs 老师蒸馏，等 N 对照。

### 资源事实

原始环境是一台 **2GB 内存 / 2 核的 VPS**，Docker 只能串行（`--workers 1` 是唯一安全档）。因此：

- **老师轨迹阶段用 venv 沙箱**：每个 worker 一份 `cp -a` 干净副本 + `rm -rf .git && git init`。
  ⚠️ **不能用 `git worktree`** —— worktree 的 `.git` 是指向主仓的文件，gold 的 `main` 分支仍然可达，答案会泄漏。
- **Docker 只用于官方 `valid` 与最终评测**。
- 训练/评测阶段租卡（A100 / 4090 档，约 8–10 小时）。

---

## 三、里程碑 v2

| # | 内容 | 产物 / 看什么数 | 状态 |
|---|---|---|---|
| M1 | procedural + combine 造 ~300 实例，**每实例做可见/隐藏测试拆分**；留出 40 题 | 实例 jsonl；候选→存活产率、秒/候选 | 冒烟 0907 通过：51→41 存活（80%）+ combine 17/17；MonkeyType repo 级 task_insts 202 条 |
| M2 | LLM 写 issue（官方模板）；well-defined / 答案泄漏审计 | issue 字段；泄漏率、token/issue、modifier 与文件分布 | 待开 |
| M3 | k=4 跑 60 题（含留出 40）：难度、区分度、loss-token 比例 | 每题 pass-rate / 方差 | 冒烟 0907 通过：4 题 3 解、loss-token 0.168、0 越界 |
| M4 | 假阳（过可见挂隐藏）+ 轨迹越界审计 | 假阳率、越界数 | 待开 |
| M5 | 老师轨迹上量：**池子必须显著大于最大 N**，否则「筛选」退化成「全取」 | 轨迹集 + 每条的六维标签 | 待开 |
| M6 | 租卡 LoRA SFT：base / N30 / N100 / N300-随机 / N300-筛选 | 5 组权重 | 待开 |
| M7 | 留出集评测（mini-SWE-agent，pass@4，隐藏测试叠回）+ 报告 | scaling 曲线；筛选 vs 随机；六维 × 收益相关表 | 待开 |
| M8 | 扩展：RLVR 单轮 patch GRPO（执行奖励） | RL 之后曲线还能动多少 | 可选 |
| M9 | 扩展：一轮自训练 vs 蒸馏 | 等 N 对照 | 可选 |

### M3 冒烟后的三处修订（已进 harness）

1. **多 hunk 实例按 hunk 分层切分**（`make_sandbox.py --stratify-by-hunk`）——
   朴素 50/50 可能把某个 hunk 的全部信号都分进隐藏，那道题就不是「模型没修好」而是「没法解」（假阳）。
2. **沙箱预置 git 假身份** `solver <solver@sandbox.local>`（仓库级，不动 `--global`）。
3. **越界审计白名单加上各仓 venv** —— venv 就是 `run_tests.sh` 内部那个解释器，不含答案信息。

---

## 四、学生模型选型

- 学生 = **Qwen3.5-9B 非思考模式**；备选 Qwen3.8-27B（QLoRA，成本 ×3）；
  「coder 特化」备选 Devstral-Small-2-24B；兜底 Qwen2.5-Coder-7B-Instruct
  （当基线在留出 20 题 k=1 的 F2P 均值 < 0.05 时切换）。
- **必做**：训练与评测两端都关思考 —— SFT 数据不带 `<think>`、模板 `enable_thinking=False`
  （ms-swift 的 Qwen3 模板开关 ⚠️ 待核）、vLLM 请求传 `chat_template_kwargs.enable_thinking=false`
  （mini-SWE-agent 配置里可以塞）。**两端不一致 = 训练/评测分布错开**。
- 排除 Qwen3-Coder-30B-A3B：MoE 的 LoRA 训练复杂度不值这个玩具规模。
- 排除 ≤3B：SWE 类任务基线约等于 0，曲线会贴地。
- 选型背景（2026-09 直查 HF）：小尺寸**专用 coder** 模型没有 2026 新品 ——
  Qwen 的 Coder 线已转大 MoE（Qwen3-Coder-30B-A3B 2025-07、Qwen3-Coder-Next 80B-A3B 2026-01），
  Mistral 最新专用是 Devstral-Small-2-24B（2025-11），Qwen2.5-Coder-7B/14B 仍是 2024 款。
  → 「最新 + 可训尺寸」= **Qwen3.5-9B**。
- 租卡当天必核：`qwen3_5` 模板的思考开关、ms-swift 的 LoRA 对 `Qwen3_5ForConditionalGeneration` 的支持、vLLM 起服务。

---

## 五、0908 事故与硬约束

> 原则：「**一定要保证不能死机；先小步走，稳定了再考虑上量**」

### 事故

原始 VPS 两次死机（09-07 17:51 UTC、09-08 04:50 UTC），**都在 flashtext 的验证阶段**。

根因 = SWE-smith 给验证容器的 `mem_limit="10g"`（`swesmith/harness/utils.py:151`，而机器只有 2GB）
+ flashtext 两个**死循环候选**（`ctrl_shuffle__lhg4dfim`、`op_change__habdq6v6`）吃穿内存进 swap 抖动；
内核没有触发 OOM-kill，**整机失去响应**。基线本来就占 1.3–1.4GB（编辑器 server ≈900MB、agent 进程 400MB+）。

第二次死机的直接原因是**未诊断即续跑**，责任在规划方。

### 三道保险（0908 已装）

1. **容器内存硬限**：`mem_limit=600m` + `memswap_limit=600m` + `pids_limit=256`
   （lab 内 SWE-smith 副本改一处源码，见 `patches/swesmith-utils-memlimit.patch`）。
   受控测试：失控分配的容器 2 秒内 `exit 137`，宿主 swap 只 +70MB。
2. **`earlyoom`**：`-m 6 -s 90`，prefer `pytest`/`python`，avoid `claude`/`node`/`sshd`/`tmux`/`docker`。
3. **停用高频后台定时任务**（原本每 5 分钟起一个 agent 进程）。

### 运行规则（硬约束）

- **Docker 任务不与任何其它 worker 并行**。
- 派 Docker 任务前先看 `free -m`，available **≥ 700MB** 才派。
- 验证一律带 `--timeout 60`。
- **小批量**：≤10 个候选跑完就看 `free -m` 和 `journalctl -u earlyoom`，确认没有被杀再下一批。
- 上量必须显式拍板。

> 本机 16GB 的话，这些限制可以放松：容器上限调到 `2g`、验证批量可以放大到几十个候选、
> `--workers` 仍建议保持 1（SWE-smith 的并行验证是每 worker 一个容器）。

---

## 六、已知环境偏差（复现时注意）

| 项 | 原始环境 | 说明 |
|---|---|---|
| Python | 3.11 | SWE-smith profile 写的是 3.10；测试结果与容器逐字一致，但这是一处偏差 |
| pytest | 7.4.4（钉死） | pytest 9 把 `pytest.skip` 改成对象，MonkeyType 的 `test_excludes_site_packages` 会挂 |
| tokenizer | tiktoken `cl100k_base` | ⚠️ **不是 Qwen 分词器**，loss-token 比例只作量级参考 |
| `thinking` 字段 | 观察到为空串（只留加密 signature） | 若真实轨迹也这样，`thinking_tokens` 恒为 0 |
| 干净仓 HEAD | `810d9de`（MonkeyType 镜像） | = 容器里那个 `Initial commit`，公开可 clone 已证实 |
