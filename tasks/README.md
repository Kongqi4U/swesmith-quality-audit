# tasks/ —— 给本地执行 agent 的东西

1. **怎么用**：把 `MASTER-PROMPT.md` **整份**贴给本地（WSL2）的 Claude Code / Codex 主 agent，它会按 P1(M1收尾)→P2(M2)→P3(M3)→P4(M4)→P5(M5) 顺序跑，所有 LLM 角色派 Opus sub agent；断点续跑看仓库根的 `PROGRESS.md`，先跑 §1 环境自检 8 条（任一不过就停）。
2. **门控在哪**：每个阶段（§2–§6）末尾的「Go/No-go」那一行；No-go 就写 `reports/BLOCKED-<阶段>.md` 并停下等规划方，不进下一阶段。
3. **完成后交什么**：`reports/M1..M5.md` + `CHANGELOG.md`、`data/splits.json`、`data/trajectories/*.jsonl`(≥120) + `data/labels.jsonl`、`issues/` + `metrics/` + `audit/` + `results/m3/`（清单见主提示词 §7），并按 §8 的三行格式（产物 / 关键数 / Go-No-go）回传规划方。
