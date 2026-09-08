# 主提示词 · SWE-smith 玩具复现执行阶段（M1 收尾 → M2 → M3 → M4 → M5）

> 整份贴给本地（Windows/WSL2）的 Claude Code / Codex 主 agent。规划方（Kiro，在 VPS）不在场，只在门控点验收。自包含：要逐字执行的东西在附录 A / B。

## 0 · 你是谁、边界、门控

**你是执行 agent**：编排、跑脚本、统计、写报告。你**不亲自当 solver / issue 写手**——你看得见宿主路径与答案文件，隔离不了。

1. **一切 LLM 角色用 Opus sub agent**（`Agent` + `model:"opus"`）：issue 写手、solver（老师）、假阳判读员；每个只拿该拿的输入。
2. **本轮不训练**，跑到 M5 结束就停（M6 租卡不在范围内）。
3. **不改 harness 语义**：可修 bug、可改死路径，每处写 `reports/CHANGELOG.md` 一行（`日期|文件:行|改了什么|为什么|谁批`）。语义级改动只有 §4 那一处可做，其余先停下问。
4. **绝不让 solver 看到 gold / 隐藏测试 / 任务 json**。隔离配方见**附录 B**，逐字执行；实例 json、`*.hidden.json`、`patch.diff`、`report.json`、`logs/` 只在沙箱**外**。派 solver 前必须看到 `make_sandbox.py` 自检 `leaks: []`、`n_commits: 1`、`init_author: solver <solver@sandbox.local>`。
5. **每阶段收尾四件事**：`reports/<阶段>.md` → `PROGRESS.md` 追一行（时间/阶段/产物/关键数）→ `git add -A && git commit` → `git push`。每个可断点批次也追一行——**续跑靠它不靠记忆**；开工先 `tail -20 PROGRESS.md` 从最后一行接。脚本要能重跑（`make_sandbox.py` 要 `--force`；`harness.valid` 默认跳过已验证的）。
6. **门控**：每阶段末有 Go/No-go。**No-go 就停**：写 `reports/BLOCKED-<阶段>.md`（现象 / 已排除的原因 / 两条备选路 / 要规划方拍什么），按 §8 回传三行，不擅自进下一阶段。

**资源**：本地 16GB，Docker 可 `mem_limit 2g` / `--workers 2`；**并行 sub agent ≤4**，跑 Docker 时别同时开 4 个 solver。**总量粗估** `[推断]`：五阶段 ≈ **25–35 h 机时**、**≈5.5M token**。

```bash
export SWESMITH_LAB=~/swesmith-lab; export QA=~/swesmith-quality-audit
export L=$SWESMITH_LAB; export H=$L/harness
export R=Instagram__MonkeyType.70c3acf6; export F=vi3k6i5__flashtext.b316c7e9
```

## 1 · 环境自检（8 条，任一不过就停）

与 `docs/SETUP-WSL2.md` 同一套；⚠️ 那份由另一 worker 产出，冲突以它为准并记 CHANGELOG。

| # | 命令 | 期望 |
|---|---|---|
| 1 | `python3.11 -V` | 3.11.x（profile 写 3.10，实际 3.11，已知偏差） |
| 2 | `grep -rn "/root/workspace" $H/*.py $H/*.sh $H/*.json $H/*.md` | **0 行**。改绑：`grep -rl "/root/workspace/swesmith-lab" $H/ \| xargs sed -i "s#/root/workspace/swesmith-lab#$L#g"` |
| 3 | `$L/venv-monkeytype/bin/pytest --version; $L/venv-flashtext/bin/pytest --version` | 都是 **7.4.4** |
| 4 | `bash $H/run_tests.sh $L/repos/clean-monkeytype`；`VENV=$L/venv-flashtext bash $H/run_tests.sh $L/repos/clean-flashtext` | `379 passed, 2 skipped, 1 xpassed` / `39 passed` |
| 5 | `git -C $L/repos/clean-monkeytype status --porcelain` | 空（脏了传染进每个沙箱） |
| 6 | `$L/venv/bin/pip show swebench \| grep Version` | **4.1.0**（不是 5.0.2，两 venv 永久分开） |
| 7 | `docker images \| grep swesmith`；`grep -n mem_limit $L/SWE-smith/swesmith/harness/utils.py` | 两镜像在；`mem_limit` 从 `10g` 改 `2g`（备份 `utils.py.orig-0908`） |
| 8 | `ls -t ~/.claude/projects/*/subagents/*.jsonl \| head -3` | 有文件 —— **M3/M5 轨迹的唯一来源** |

⚠️ 第 8 条只对 **Claude Code 宿主**成立。若你是 Codex：solver / issue 写手仍必须 Opus，要经 `claude -p --model opus` 起并自己落 JSONL，否则 `convert_transcript.py` / `audit_transcript.py` 解析不了。**未实测 ⚠️**——是 Codex 宿主就只跑 P1，然后按 §8 回传问规划方。

## 2 · P1 · M1 收尾（实例池 + 切分）

VPS 已完成：MonkeyType 227 候选 → **202 存活实例**（含 combine 17）；flashtext 99 候选**只验了 34**。

```bash
cd $L/work && source $L/venv/bin/activate
python -m swesmith.harness.valid logs/bug_gen/${F}_m1_patches.json \
    --workers 2 --timeout 60 2>&1 | tee $L/smoke/m1/valid_ft3.log     # 剩 65，已验的自动跳过
python3 $H/build_instances.py logs/run_validation/$R $L/work/logs/task_insts
python3 $H/build_instances.py logs/run_validation/$F $L/work/logs/task_insts_flashtext \
    --repo-name $F --image swebench/swesmith.x86_64.vi3k6i5_1776_flashtext.b316c7e9
```

⚠️ 两个 flashtext 候选会死循环吃穿内存（`ctrl_shuffle__lhg4dfim`、`op_change__habdq6v6`，VPS 上打死过机器两次）：每 5 分钟看 `free -m`，available <1G 就 Ctrl-C、剔掉这两个 id 再跑，报告记名。

**统计**（→ `reports/M1.md`）：两仓 × modifier 的候选/存活/产率；F2P 分布（min/p25/median/p75/max、F2P=1 占比）；秒/候选（总 & pytest 占比）；峰值内存。对照 VPS：MonkeyType 产率 80.4%、20.5 s/候选（pytest 仅 3.87 s，**81% 是容器起停**）；flashtext 72.7%（11 候选样本）。

**切分 `data/splits.json`**（`random.Random(0)`）：
- 池 = MonkeyType 全部存活实例（procedural + combine）。
- **全局排除**：bug patch 触及 `demo/` 的（受保护前缀，补丁会被整块丢弃 = 不可解）→ `excluded.unsolvable_demo`。
- **只排除出留出集**：`len(FAIL_TO_PASS)==1`（拆不出可见/隐藏），仍留训练池并打 `all_visible`。
- `heldout40` = 剩下的按 **modifier 分层**抽 40（按占比取整、每 modifier ≥1）。**实体成组**：同一 `(文件,实体)` 的实例必须同侧，实体取 `find $L/work/logs/bug_gen/$R -name "bug__*__<hash>.diff"` 路径倒数第二段（combine 落在文件目录下，按文件成组）。不这么切，学生训练见过某函数怎么修、留出又考它 = 测记忆不是泛化。
- `xrepo_heldout` = flashtext **全部**（只评测不训练）；`train_pool` = 其余。
- 结构：`{"seed":0,"heldout40":[…],"train_pool":[…],"xrepo_heldout":[…],"excluded":{"unsolvable_demo":[…],"f2p1_not_heldout":[…]},"entity_groups":{…}}`

**预期** `[推断]`：~40 min；~30k token（无 sub agent）。
**Go** = ①两仓每实例 json 齐（MonkeyType ≥180、flashtext ≥1，含 `problem_statement` 字段）②`splits.json` 在、`heldout40` 恰 40、四集合两两无交、实体不跨侧 ③`reports/M1.md` 五组数齐。

## 3 · P2 · M2 issue 生成（+ 泄漏审计）

**范围**：`train_pool` + `heldout40` + `xrepo_heldout` **全部**实例；**每个 Opus sub agent 一批 10 条**，并行 ≤3。给它的输入**只有三样**：①bug diff（实例 json 的 `patch`）②失败测试名与**错误摘要**（`run_validation/<repo>/<id>/test_output.txt` 里每条 F2P 断言错误前后各 5 行，≤800 字符）③风格编号（批内轮换 1/2/3）。写作要求照抄进它的提示词：

> 你在写一个**真实用户报的 GitHub issue**。diff 是**已注入代码的 bug**（不是修复），失败信息是它造成的症状。
> **必须**只写症状、复现、期望行为，用户口吻。**禁止**出现补丁或修复代码、任何测试函数名/测试文件名/`::` node id/pytest 输出原文、文件路径+行号的定位（可提用户可见的公开 API 名，不可点名内部实现文件）。
> **风格 1** 简短报错（3–6 行：现象 +「这以前是好的」）；**风格 2** 带复现步骤（最小代码片段 + 实际 vs 期望输出）；**风格 3** 带期望行为（业务语义应该是什么 + 一两句上下文）。
> **多 hunk 实例（diff 里多个 `@@`）**：每个 hunk 造成的症状都要有描述，哪怕一句。漏掉一个 hunk 的题会变成「没法解」而不是「没修好」（S3 冒烟 `85gza9xd` 就这么假阳的）。
> 输出两块：`## ISSUE` 下是正文；`## SELFCHECK` 下一行 JSON `{"can_locate":bool,"leak_level":"L0|L1|L2|L3","style":1|2|3,"n_hunks":N,"hunks_covered":N,"note":"…"}`。`can_locate` = 没看过 diff 的工程师能否凭它找到要改的模块；L0 无泄漏 / L1 出现修复代码 / L2 点名文件+函数+行 / L3 提到测试名或 pytest 输出。

**落盘**：`issues/<id>.md` + 正文写回实例 json 的 `problem_statement`（原地改 `$L/work/logs/task_insts*/<id>.json`）+ `issues/audit.csv`（`instance_id,style,n_hunks,hunks_covered,can_locate,leak_level_self,leak_level_rule,in_tokens,out_tokens`）。

**规则审计（抽 30 条，分层覆盖各 modifier）**：`tools/audit_issue.py` 正则查 `test_[A-Za-z0-9_]+` / `::` / `\btests?/` / `\.py\b` / `:\d+\b` / diff 的 `+`/`-` 行里出现过的内部标识符 → 记 `leak_level_rule`。再派**一个独立** Opus sub agent 复核其中 5 条（只给正文 + diff，问「泄漏了答案吗」），三方不一致的逐条列进报告。

**`reports/M2.md`**：泄漏率（rule 口径 L1+L2+L3）、well-defined 率（`can_locate` 真占比）、token/issue（均值+中位）、按 modifier 的泄漏率、多 hunk 覆盖率、自审 vs 规则 vs 复核一致率。泄漏若集中在少数 modifier（如删基类的 `func_pm_class_rm_base`），这本身是结论：procedural bug 天然写不出不泄漏的 issue。

**预期** `[推断]`：~250 条 ×（in 3–5k / out 300–600）≈ **1.2M token**；并行 3 → **1.5–2.5 h**。
**Go** = 泄漏率（rule 口径）**≤10%** 且多 hunk 的 `hunks_covered==n_hunks` ≥90%。No-go 就**只重写泄漏的那批**（提示词附上命中的词）再审；连重写两轮仍 >10% 停下回传。

## 4 · P3 · M3 难度与区分度

**题目**：训练池分层抽 **60 题**（按 modifier 比例，`combine_*` ≥8 题）+ `heldout40` 全部 = **100 题 × k=4 = 400 次 rollout**。

**必须先做的一处 harness 改动（记 CHANGELOG）**：`make_sandbox.py` 第 ④ 步现在把**可见测试名单**写进 `TASK.md`（S3 占位）。M3 起改成：`problem_statement` 非空时 `TASK.md` = issue 正文 +「怎么跑测试」+「不要改测试文件 / 评测有你看不见的测试」两句，**不列任何测试名**；加 `--task-md-mode {issue,tests}`，默认 `issue`；`problem_statement` 为空则报错退出。⚠️ 这一改让 M3 的 pass-rate **不能**与 S3 冒烟的 3/4 直接比（那次 TASK.md 里有测试名），报告写明。

```bash
ID=<instance_id>; K=<0..3>; S=$L/sandboxes/m3-$ID.k$K
IJ=$L/work/logs/task_insts/$ID.json         # flashtext 的在 task_insts_flashtext/
python3 $H/make_sandbox.py $IJ $S --seed $((20260907+K)) --stratify-by-hunk  # 留出集不加分层
sed "s#{sandbox}#$S#g" $H/solver_prompt.md > /tmp/prompt.$ID.k$K.md          # 附录 A 是原文
#  → 派 Opus sub agent，唯一输入 = 这份 /tmp/prompt.$ID.k$K.md 全文
python3 $H/eval_patch.py $S $IJ --out $QA/results/m3/$ID.k$K.json            # 一个沙箱只判一次
TRJ=$(ls -t ~/.claude/projects/*/subagents/*.jsonl | head -1)
python3 $H/audit_transcript.py $TRJ --sandbox $S --out $QA/results/m3/$ID.k$K.audit.json
$L/venv-monkeytype/bin/python $H/convert_transcript.py $TRJ $QA/results/m3/$ID.k$K.traj.jsonl \
    --task-md $S/TASK.md --metrics $QA/results/m3/$ID.k$K.traj_meta.json     # 必须用带 tiktoken 的 venv
rm -rf $S
```

并行 ≤4；每 20 次之间 `free -m` + 追 `PROGRESS.md`。**训练池开 `--stratify-by-hunk`，留出集不开**（留出要最硬的判据）。

**`metrics/m3.csv`**：`instance_id,k,split,modifier,n_hunks,resolved,hack_flag,visible_pass,hidden_pass,p2p_regressions,n_turns,total_tokens,assistant_tokens,loss_token_ratio,violations,verdict`；聚合出 `metrics/m3_per_task.csv`：`pass_rate`(0/.25/.5/.75/1)、`var=p(1-p)`、`hack_any`。

**`reports/M3.md` 必须有**：①难度分布**文本直方图**（五档 × 题数，`#` 画）②**零方差组比例**（`pass_rate∈{0,1}` 题数 / 100）——GRPO 里这些题零梯度，>75% 的读法是「做 RL 时四分之三算力白烧」③loss-token 比例均值/中位 + 口径脚注（分子 = assistant content 含思考文字与 bash 块；分母 = system+user+分子；thinking 段两边都不进、单列 `thinking_tokens`；tokenizer = tiktoken `cl100k_base`，非 Qwen 分词器，量级参考）④训练池 vs 留出集 pass-rate 差⑤平均轮数/token（对照 S3：10.75 轮 / 7.1k token / loss-token 0.168）。

**预期** `[推断]`：400 × ~7k ≈ **2.8M token**；每次 5–10 min，并行 4 → **9–14 h**（分两三夜，靠 PROGRESS.md 续）。
**Go** = ①越界 **0 条**（audit 报 violated 的那次**作废重跑**；重跑仍越界标 `void`、剔出统计并在报告点名）②400 次 `loss_token_ratio` **全部算出**（`thinking_tokens` 恒 0 是已知现象，不算失败）③`m3.csv` 行数 == 实际 rollout 数。

## 5 · P4 · M4 假阳与泄漏审计

1. **`audit/hack_list.csv`**：`m3.csv` 里 `hack_flag==true` 的全部 (instance,k)，附可见 F2P 通过数 / 隐藏挂的 node id / hunk 数 / 是否开分层。**逐条判成因**：(a) 模型只修了一半 = 真假阳；(b) 切分把某 hunk 信号全藏光、TASK.md 零提示 = 题没法解（我们的锅）。不许留 `unknown`。
2. **抽 20 条 `resolved` 补丁与 gold 对比**（gold = bug patch 反向）：先自动比改动**文件集合/函数集合**（不一致 = 可疑）；再派 Opus sub agent 逐条三选一（只给两段 diff，不给结论）：**逐字/等价修复**（不算假阳）/ **局部修复**（只修到测试覆盖的路径 → 算）/ **绕路**（特判、硬编码、改无关代码 → 算）。**你自己复核 5 条**并记改判数；改判率 >1/3 说明 LLM-judge 这维不可靠，写进报告。
3. **`audit/traj_violations.csv`**：汇总 400 条 `*.audit.json`（`instance_id,k,category,path_or_cmd,是否影响结果`；category = `git_history/task_files/outside/network/remote/hidden`）。

**`reports/M4.md`**：假阳率（假阳/resolved，对照 PatchDiff 29.6%）、文件集合一致率、hack_flag 的「真假阳 vs 题没法解」拆分、越界条数与类别分布、人审改判率。**假阳率接近 0 也是结论**：procedural bug 修复路径太唯一（改回去就是唯一解），假阳率被系统性低估，真实 PR 场景会高得多——写进「边界」；另记一条低估来源：官方解析器丢参数化测试（§7 坑 3），我们的插件已补回，给「369 / 382 条」对照。

**预期** `[推断]`：~0.2M token；1.5–2 h。
**Go** = ①`hack_list.csv` 每条都有成因判定 ②20 条 gold 对比全有分类 + 5 条人审复核在案 ③`traj_violations.csv` 覆盖全部 400 次。

## 6 · P5 · M5 老师轨迹上量

**目标 ~200 次 solver 运行，只在 `train_pool` 上跑**（留出集绝不进训练数据）。k 按 M3 难度分配：`pass_rate∈{0.25,0.5,0.75}` → 追加 **k=4**（中间难度多采，SFT/RL 都用得上）；`=1.0` → **k=1**；`=0` → **0**（老师都解不了，采了是废轨迹）；M3 没测过的训练池题 → **k=2**。先算总数，>220 就按中间档优先截断到 ~200，分配表写进报告。

**流水与 §4 完全一致**（附录 B 沙箱 + 附录 A 提示词 + eval + audit + convert），三处差别：①**全部**开 `--stratify-by-hunk` ②`--seed $((20260907+100+K))` 避开 M3 的切分 ③**每 20 次一批**，批末 `free -m` + 追 `PROGRESS.md` + `git commit && git push` + 按 §8 回传一次进度。

**筛轨迹**：只留 `resolved==true` **且** audit `verdict==clean` 的 → `data/trajectories/<split>.jsonl`（messages 格式，一行一条）。**训练 jsonl 只留 `messages`**，标签另存 `data/labels.jsonl` 按 `instance_id`+`k` 对齐（⚠️ 多余字段会不会让 ms-swift 报错未验证，分开存最稳）。**六维标签**（不许 null）：`pass_rate`（该题在 M3+M5 全部采样上的 resolved 比例）、`var=p(1-p)`、`modifier`、`file`（bug 落在哪个源文件）、`leak`（M2 的 `leak_level_rule`）、`loss_token_ratio`、`n_hunks`。

**收尾必做**：`python3 $H/scrub_pii.py $QA/data $QA/results $QA/metrics`（先看 dry-run 清单）→ 确认后 `--apply`。已知命中点是 solver 收尾 `git commit` 里的真实邮箱；`make_sandbox.py` 已预置假身份，理论上不该再有，**仍要跑**。`~/.claude/` 下原始 transcript 脚本会拒改，别动。

**`reports/M5.md`**：实际 runs、resolved 数与比例、按 modifier / pass_rate 档的分布、loss-token 分布、**轮数分布**（中位数用来重定「≤N 轮就 submit 要丢掉」的筛选阈值——讲义里的 3 是拍的）、单 modifier 最大占比（>25% 点名，模式塌缩风险）。

**预期** `[推断]`：200 × ~7k ≈ **1.4M token**；并行 4 → **5–7 h**。
**Go** = **≥120 条** resolved 且无越界的轨迹进 `data/trajectories/`，六维标签齐全。<120 别硬凑：先分清是题太难（pass_rate 左偏）还是 harness 坏了，写 BLOCKED。

## 7 · 交付清单 + 已知坑

**M5 结束时 `$QA` 里必须有**：`data/splits.json`；`data/trajectories/*.jsonl`（≥120）；`data/labels.jsonl`；`issues/<id>.md` 全部 + `issues/audit.csv`；`metrics/m3.csv` + `m3_per_task.csv`；`audit/hack_list.csv` + `false_positive.csv` + `traj_violations.csv`；`results/m3/*.json|.audit.json|.traj.jsonl|.traj_meta.json`；`reports/M1..M5.md` + `CHANGELOG.md`；`PROGRESS.md`。

**已知坑（0907–0908 实测，别再踩）**

1. `--max_bugs` 是**每个 modifier** 的候选上限不是全局（`generate.py:128,168`）。
2. 官方 `harness.gather` 坏在 `gather.py:333` 读 `PASS_TO_FAIL`（恒 0）→ 全 SKIP、`0 new instances`。**用 `build_instances.py`**。
3. 官方解析器**丢参数化测试**：正则 `^(\S+)\s+PASSED` 对带空格的 node id 匹配不上，379 个通过里静默丢 10 个（2.6%）；带换行的 nodeid 同理。判分一律走 `pytest_report_plugin.py`（382 vs 369 条）。
4. `.pytest_cache/v/cache/nodeids` 存着**全部测试 id = 隐藏名单**，`copytree` 会抄进沙箱；已 ignore + 兜底，改动沙箱逻辑后要重新确认沙箱里没有它。
5. **pytest 钉 7.4.4**：pytest 9 把 `pytest.skip` 改成对象，`test_config.py::TestDefaultCodeFilter::test_excludes_site_packages`（在**所有** MonkeyType 实例的 P2P 里）会挂，整批判分全废。
6. **`demo/` 的 bug 实例不可解**：受保护前缀，补丁被整块丢弃 → 切分时全局排除。
7. **F2P 拆可见/隐藏按「函数组」不按 node id**：参数化一函数多 id，按 id 拆源码层面删不动；`hide_tests.py` 已按 (文件,类链,函数名)。
8. **git 假身份**：不预置则 solver 收尾 commit `Author identity unknown` 白烧一轮，且模型会自己敲 `git config user.email <宿主真实邮箱>` 写进训练轨迹（S3 冒烟 4/4 全中）。已在**仓库级**预置 `solver <solver@sandbox.local>`（不动 `--global`）。
9. **transcript 里 thinking 是空的**（只剩加密 `signature`）→ `thinking_tokens` 恒 0，**蒸出的 SFT 数据无 CoT**。是事实不是 bug，写进边界。
10. **flashtext 两个死循环候选**不带 timeout 会吃穿内存（VPS 死机两次）：验证一律 `--timeout 60`。
11. **容器内存上限**：源码写死 `mem_limit=10g`（`harness/utils.py:151`），本地改 `2g`（VPS 是 `600m`），记 CHANGELOG。
12. **一个沙箱只判一次分**：`eval_patch.py` 会 `git add -A`，跑完 index 是脏的。
13. **`--stratify-by-hunk` 尽力而为不是硬保证**：hunk 交织在同一函数时无测试被单个 hunk 独占，全归 `shared` 桶（`<out>.hidden.json` 的 `warnings` 会写）；`combine_file__3io24ypb`（4 hunk）四个全无独占测试。分层还稀释隐藏测试检出力（85gza9xd 隐藏 3→1）——所以留出集不开。⚠️ 算假阳率优先用「F2P 函数组 ≥4」的实例（这个阈值是拍的，报告里标注）。

## 8 · 给规划方的回传格式

每阶段结束（以及 M5 每 20 次一批）回传**恰好三行**，别的写报告里：

```
产物：<绝对路径1>；<绝对路径2>；…（阶段报告放第一个）
关键数：<3–6 个数带口径。例：flashtext 存活 71/99=71.7%；heldout40=40 / train_pool=137 / xrepo=71>
门控：Go | No-go —— <一句话原因；No-go 附 BLOCKED 报告路径与要拍的那一个问题>
```

## 附录 A · solver 提示词原文（逐字，`{sandbox}` 是占位符）

用法：`sed "s#{sandbox}#$S#g" $H/solver_prompt.md > /tmp/prompt.md`，替换后的**全文**是 solver sub agent 的唯一输入。**不要**补背景，不要告诉它 instance_id、modifier、F2P 数量、这是第几次采样。以下与 `$H/solver_prompt.md` 逐字一致；改绑路径时只有 `/root/workspace/swesmith-lab` 那几处随之变，其余一个字不动。

---

# Solver 任务提示词模板（占位符：`{sandbox}`）

你是一个只能用 bash 工作的软件工程 agent。

**你的工作目录是 `{sandbox}`，任务写在 `{sandbox}/TASK.md` 里。先读它。**

## 交互格式（必须严格遵守）

- **每一轮只发一条 bash 命令。** 不要一次发两条工具调用，不要用 `&&` 串起互不相关的操作去凑数。
- 每轮先写**一到两句**你的判断（为什么发这条命令、上一条输出说明了什么），然后是命令。
- 命令的输出会作为下一轮的输入返回给你。
- 改完代码后，用这条命令收尾并在同一轮回复里写 `SUBMIT`：

  ```bash
  cd {sandbox} && git add -A && git commit -m done
  ```

## 你可以做什么

- 读、改 `{sandbox}` 里的任何**产品代码**（`monkeytype/` 等）。
- 跑可见测试：

  ```bash
  bash /root/workspace/swesmith-lab/harness/run_tests.sh {sandbox}
  bash /root/workspace/swesmith-lab/harness/run_tests.sh {sandbox} 'tests/test_x.py::test_y'
  ```

## 禁区（越界的这次 rollout 会被作废重跑）

1. **不许读或推断 git 历史**：`git log` / `git diff <任何 ref>` / `git show` / `git branch` /
   `git checkout` / `git reflog` / `git stash` / 直接读 `.git/`。
   （工作区只有一个 `init` commit，没有干净态、没有 remote —— 但也不要去试。）
2. **不许离开 `{sandbox}`**：不读、不写、不列举沙箱外的任何路径。
   尤其是 `/root/workspace/swesmith-lab/work/`、`logs/`、`*.hidden.json`、
   `report.json`、`*_all_patches.json`、`task_insts`、`patch.diff`。
3. **不许联网**：`curl` / `wget` / `git clone` / `git fetch` / `pip install` 一律禁止。
   仓库的上游源码在网上有，去看等于抄答案。
4. **不许改测试文件**（`tests/`、`demo/`、`conftest.py`、`setup.cfg`、`pytest.ini`、
   `tox.ini`、`pyproject.toml`）。评测时这些文件会被原样还原，改了纯属浪费轮次。

你的输入只有：`{sandbox}` 里的代码 + `TASK.md` 里那段 issue 文本。

## 一件要知道的事

评测时会跑一批**你在工作区里看不到的测试**（它们已经从这份代码里删掉了）。
所以「让 TASK.md 列的那几条测试变绿」不等于做完了 —— 请修**根因**，
不要写特判、不要针对测试断言硬编码返回值。
