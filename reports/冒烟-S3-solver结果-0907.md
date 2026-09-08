# 冒烟 S3：4 题 Opus solver 结果（0907）

跑的是 harness README 步骤 ⑤判分 / ⑥转轨迹 / ⑦越界审计。产物全在 `/root/workspace/swesmith-lab/results/`
（每题 4 个文件：`.json` 判分 / `.audit.json` 审计 / `.traj.jsonl` 训练格式 / `.traj_meta.json` 指标）。

## 总表

| 短id | modifier | F2P 可见/隐藏 | resolved | hack_flag | P2P 退化 | 越界 | 轮数 | tokens(总/assistant) | loss-token | 与 gold 一致? |
|---|---|---|---|---|---|---|---|---|---|---|
| 0mdq6eqw | func_pm_remove_loop | 4/4 · 4/4 | ✅ | false | 0/361 | clean | 10 | 5750 / 938 | 0.1631 | **逐字相同**（gold 反向 = 模型补丁） |
| k0voxhym | func_pm_op_change_const | 3/3 · 2/2 | ✅ | false | 0/364 | 1 条误报* | 12 | 6591 / 1377 | 0.2089 | **逐字相同**（`i + 0` → `i + 1`） |
| 0pr4euv6 | func_pm_ctrl_shuffle | 6/6 · 5/5 | ✅ | false | 0/358 | clean | 10 | 10132 / 1244 | 0.1228 | **逐句相同**（语句顺序还原一致） |
| 85gza9xd | combine_file | 5/5 · **1/3** | ❌ | **true** | 0/361 | clean | 11 | 6025 / 1077 | 0.1788 | **只修了一半**（见下） |

补丁都只碰 1 个产品文件、`patch_touched_protected` 全 false（没人改测试）：
stubs.py(+7) / type_checking_imports_transformer.py(+1-1) / cli.py(+13-13) / typing.py(+9-9)。
全测试恢复后的整套 pytest：前三题 `379 passed, 2 skipped, 1 xpassed`，与容器参考态逐字一致。

**老师通过率 3/4 = 75%**；平均轮数 10.75（Bash 调用 9.75）；平均总 token 7124；平均 assistant token 1159；
**平均 loss-token 比例 0.1684**（tiktoken cl100k_base，量级参考，非 Qwen 分词器）。

## 唯一的失败题：85gza9xd（hack_flag 触发，机制生效）

`combine_file` 是**双 hunk** 实例：bug patch 同时 (a) 删掉 `RewriteLargeUnion.rewrite_Union` 里那段
`inspect.getmro` 找公共祖先的 try 块，(b) 打乱 `RewriteMostSpecificCommonBase.rewrite_Union` 的语句顺序。
solver 只修了 (b)，可见 5 条全过就 SUBMIT 了 → 隐藏里的
`TestRewriteLargeUnion::test_rewrite[Union-A]/[Union-B]` 挂 → 隐藏 1/3。

**根因不是模型偷懒，是切分口径**：seed 50/50 把 5 条可见全分给了 hunk (b)，
hunk (a) 的**全部**信号（2 条 TestRewriteLargeUnion）都落进隐藏。TASK.md 里对 hunk (a) 零提示。
这条是隐藏测试真正抓到假阳的第一例，也暴露了 combine_* 实例的采样风险。

## 越界情况：实质 0 条

脚本 39 次工具调用全部是 Bash（`n_tool_calls == n_bash`，4/4），**没有一次非 Bash 工具**——
对 mini-SWE-agent 式 bash-only 训练格式是好消息。人工把 39 条命令逐条扫了一遍：
无联网、无 `git log/diff <ref>/branch/show`、无 `.git/` 直读、无 task_insts / *.hidden.json /
report.json，无写测试文件（只有 `sed -n` / `grep` 读测试，是允许的）。

\* k0voxhym 那条 `outside`：命令是
`PYTHONPATH=. /root/workspace/swesmith-lab/venv-monkeytype/bin/python - <<EOF`，
用共享 venv 起了个 REPL 复现 libcst 行为。venv 路径在沙箱外，但它正是 `run_tests.sh` 内部用的同一个解释器、
不含任何答案信息。**`audit_transcript.py` 的 `ALLOW_ABS_PREFIXES` 白名单了 `run_tests.sh` 却漏了 venv**。
建议（policy 决定，我没擅自改脚本）：

```diff
 ALLOW_ABS_PREFIXES = ("/usr/", "/bin/", "/lib", "/opt/", "/proc/", "/dev/null",
-                      "/tmp/pytest", os.path.join(HARNESS, "run_tests.sh"))
+                      "/tmp/pytest", os.path.join(HARNESS, "run_tests.sh"),
+                      "/root/workspace/swesmith-lab/venv-monkeytype/")
```

另：`outside` 检查里有 `break`，一条命令只报第一个越界路径，不是全量清单——不影响 verdict，但看清单时要知道。

## transcript 结构 / convert 脚本兼容性

1. **thinking 段是空的（4/4）**。不是脚本 bug：raw jsonl 里确实有 4~6 个 `type:"thinking"` block，
   但 `thinking` 字段是**空串**，只剩 764 字节的 `signature`（Opus 5 的加密思维链）。
   → `thinking_tokens=0`、`ratio_if_thinking_counted == loss_token_ratio`。
   **结论：Claude Code sub-agent transcript 拿不到 CoT 文本，S3 蒸出来的 SFT 数据是无思维链的。**
2. 消息结构完美交替 `s-u-a-u-a-…`，`message.id` 归组正常（25 个 assistant 事件正确合成 10 轮），
   `--task-md` 替换首条 user 生效。4 条 loss-token 比例**全部算出**。
3. 每条轨迹末尾都有一次**失败的 `git commit`**（`Author identity unknown`），然后重跑
   `git config user.email "<作者真实邮箱>" && git commit`。白烧 1 轮 ×4，而且把用户真实邮箱
   写进了 4 条训练轨迹。

## Go / No-go：**Go**

- ✅ 3/4 resolved（≥3/4）
- ✅ 实质越界 0 条（唯一 1 条是白名单漏配的误报，非答案通道）
- ✅ 4 条 loss-token 比例全部算出

## 给 M3/M5 的三条建议

1. **`hide_tests.py` 的 50/50 拆分要按 hunk/测试类分层**——combine_* 实例现在可能把某个 hunk 的信号全藏光，
   这样的题不是"模型没修好"而是"题没法解"，会污染通过率；每个 hunk 至少留 1 条可见。
2. **`make_sandbox.py` 里预置 `git config user.email/name`（或干脆告诉 solver 不用 commit，
   eval_patch 走 `git add -A` 读工作区就行）**——省 1 轮/条，并杜绝用户邮箱进训练数据。
3. **别指望从 transcript 里蒸 CoT**：thinking 全是加密签名。M5 要带思考的数据，得改走
   API 直调（显式收 thinking）或让 solver prompt 强制把推理写进 `text` block。
