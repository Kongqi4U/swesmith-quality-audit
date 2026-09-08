# 本地启动提示词（在 WSL2 Ubuntu 里起 Claude Code 后整段粘贴）

> 前置（人工）：WSL2 Ubuntu 24.04、Docker Desktop（WSL integration 开）、Ubuntu 内可用的 Claude Code（能派 Opus sub agent）。

```
你是本项目的本地执行 agent。项目：SWE-smith 合成管线的玩具复现与七维数据质量审计。规划方在另一台机器上，只验收，不在场；你按门控自主推进，No-go 就停。

第一步 · 取仓库并装环境
1. git clone https://github.com/Kongqi4U/swesmith-quality-audit ~/swesmith-quality-audit
2. 通读 docs/SETUP-WSL2.md，逐条执行第 3 步起的所有命令（WSL2 与 Docker Desktop 我已装好，跳过 1–2）。SWE-smith 固定 commit 9b74ac0，补丁 patches/ 下那份必须打上；本机 16GB，容器内存上限可改 2g。
3. 跑文档末尾的 8 条自检，逐条把命令和输出贴给我。任一条不过：修到过为止，修不了就停下报告，不要绕过。
4. 环境变量 SWESMITH_LAB 写进 ~/.bashrc。

第二步 · 执行
自检全绿后，读 tasks/MASTER-PROMPT.md，从 §1 起按阶段执行。硬规则：
- 所有 LLM 角色（issue 写手、solver/老师）用 Opus sub agent，并行 ≤4；solver 只能用 Bash 工具、一轮一条命令，提示词用附录 A 原文，隔离配方用附录 B 原文，一字不改。
- 每阶段末尾：写 reports/<阶段>.md，PROGRESS.md 追加一行，git commit 并 push 到 origin main。
- 每阶段末尾按 §8 格式给我三行（产物路径 / 关键数 / Go-No-go 与原因），然后停下等我说「继续」再进下一阶段。
- 修 harness 的 bug 可以，但要记进 reports/CHANGELOG.md；不改语义。
- 绝不让 solver 看到 gold patch、隐藏测试名单、data/ 下的任务 json；越界的 rollout 作废重跑。
- 不读、不动本仓库以外的任何目录；不用 ~/.claude 之外的凭据。
- 内存或磁盘异常、Docker 卡死、连续 3 次同类报错：停下报告。

现在从第一步开始。
```
