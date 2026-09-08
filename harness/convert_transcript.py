#!/usr/bin/env python3
"""convert_transcript.py —— 把 Claude Code sub-agent 的 transcript（JSONL）转成训练用 messages 格式，
并算 loss-token 比例。

用法（用装了 tiktoken 的那个 venv 跑最好）:
    $SWESMITH_LAB/venv-monkeytype/bin/python convert_transcript.py \
        <agent_output.jsonl> <out.jsonl> [--task-md TASK.md] [--system-file solver_prompt.md] \
        [--metrics out_metrics.json]

输入结构（实测 `~/.claude/projects/<proj>/subagents/agent-*.jsonl`）:
    每行一个事件；`type` ∈ {user, assistant, attachment, ...}
    assistant 行的 message.content 是 block 列表：{type: thinking|text|tool_use}
    tool_result 以 `type: user` 行回来，message.content = [{type: tool_result, content: ...}]
    同一次 API 调用的多个 block 分散在多行，靠 message.id 归组

输出（out.jsonl，一行一条对话）:
    {"messages":[{"role":"system",...},{"role":"user",...},{"role":"assistant",...},...],
     "thinking":[...], "meta":{...}}

loss-token 口径（规划方定）:
    loss_token_ratio = assistant 生成 token / 全部 token
      分子 = assistant 消息的 content（思考文字 + bash 命令），**不含 thinking 段**
      分母 = system + user(TASK/命令输出) + 上面那个分子，**thinking 也不进分母**
             —— 因为 thinking 根本不会进 SFT 数据集，进分母会人为压低比例
    另出一列 thinking_tokens 与 ratio_if_thinking_counted 供对照。
    ⚠️ tokenizer 是 tiktoken cl100k_base（**不是 Qwen 分词器**），只作量级参考；
       装不上 tiktoken 时退化为字符数比例，输出里 tokenizer 字段会写 "chars".
"""

import argparse
import json
import os
import sys

os.environ.setdefault("TIKTOKEN_CACHE_DIR", os.path.join(
    os.environ.get("SWESMITH_LAB", "/root/workspace/swesmith-lab"), ".tiktoken_cache"))

try:
    import tiktoken

    _ENC = tiktoken.get_encoding("cl100k_base")
    TOKENIZER = "tiktoken:cl100k_base (⚠️ 非 Qwen 分词器，量级参考)"

    def ntok(s):
        return len(_ENC.encode(s, disallowed_special=()))
except Exception:  # pragma: no cover
    _ENC = None
    TOKENIZER = "chars (tiktoken 不可用，下面所有 token 数其实是字符数)"

    def ntok(s):
        return len(s)


def flatten(content):
    """tool_result 的 content 可能是 str，也可能是 block 列表"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for b in content:
            if isinstance(b, str):
                out.append(b)
            elif isinstance(b, dict):
                if b.get("type") == "text":
                    out.append(b.get("text", ""))
                elif b.get("type") == "tool_result":
                    out.append(flatten(b.get("content")))
                elif b.get("type") == "image":
                    out.append("[image]")
        return "\n".join(x for x in out if x)
    return str(content)


def fmt_tool_use(block):
    """把一次工具调用渲染成 bash-only 单命令格式（与 mini-SWE-agent 同构）"""
    name, inp = block.get("name", "?"), block.get("input", {}) or {}
    if name == "Bash":
        return "```bash\n" + (inp.get("command", "") or "") + "\n```"
    # 非 Bash 工具：渲染成等价 bash，训练时格式统一
    if name == "Read" and inp.get("file_path"):
        return "```bash\ncat " + inp["file_path"] + "\n```"
    if name in ("Grep", "Glob"):
        return "```bash\n# " + name + " " + json.dumps(inp, ensure_ascii=False) + "\n```"
    return "```bash\n# tool:" + name + " " + json.dumps(inp, ensure_ascii=False) + "\n```"


def convert(path, system_text, first_user_text=None):
    events = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    messages = [{"role": "system", "content": system_text}]
    thinking_segs = []
    pending = {}  # message.id -> {"text": [...], "cmds": [...]}
    order = []
    n_turns = 0
    first_user_done = False

    def flush(mid):
        nonlocal n_turns
        if mid not in pending:
            return
        buf = pending.pop(mid)
        order.remove(mid)
        parts = [t for t in buf["text"] if t.strip()] + buf["cmds"]
        if parts:
            messages.append({"role": "assistant", "content": "\n\n".join(parts)})
            n_turns += 1

    for ev in events:
        typ = ev.get("type")
        msg = ev.get("message") or {}
        if typ == "user":
            content = msg.get("content")
            if isinstance(content, str):
                # 第一条纯文本 user = 任务提示（真实 rollout 里就是 TASK.md）
                text = first_user_text if (not first_user_done and first_user_text) else content
                messages.append({"role": "user", "content": text})
                first_user_done = True
                continue
            # tool_result：先把还挂着的 assistant 消息落地
            for mid in list(order):
                flush(mid)
            txt = flatten(content)
            if txt.strip():
                messages.append({"role": "user", "content": txt})
        elif typ == "assistant":
            mid = msg.get("id") or ev.get("uuid")
            if mid not in pending:
                pending[mid] = {"text": [], "cmds": []}
                order.append(mid)
            for b in msg.get("content") or []:
                if not isinstance(b, dict):
                    continue
                t = b.get("type")
                if t == "thinking":
                    thinking_segs.append(b.get("thinking", "") or "")
                elif t == "text":
                    pending[mid]["text"].append(b.get("text", ""))
                elif t == "tool_use":
                    pending[mid]["cmds"].append(fmt_tool_use(b))
    for mid in list(order):
        flush(mid)

    # 合并相邻同 role（tool_result 连发时）
    merged = []
    for m in messages:
        if merged and merged[-1]["role"] == m["role"] and m["role"] != "system":
            merged[-1]["content"] += "\n\n" + m["content"]
        else:
            merged.append(dict(m))

    a_tok = sum(ntok(m["content"]) for m in merged if m["role"] == "assistant")
    u_tok = sum(ntok(m["content"]) for m in merged if m["role"] == "user")
    s_tok = sum(ntok(m["content"]) for m in merged if m["role"] == "system")
    t_tok = sum(ntok(s) for s in thinking_segs)
    total = a_tok + u_tok + s_tok

    meta = {
        "source": os.path.abspath(path),
        "tokenizer": TOKENIZER,
        "n_messages": len(merged),
        "n_assistant_turns": sum(1 for m in merged if m["role"] == "assistant"),
        "system_tokens": s_tok,
        "user_tokens": u_tok,
        "assistant_tokens": a_tok,
        "thinking_tokens": t_tok,
        "total_tokens_excl_thinking": total,
        "loss_token_ratio": round(a_tok / total, 4) if total else None,
        "ratio_if_thinking_counted": round(a_tok / (total + t_tok), 4) if total + t_tok else None,
    }
    return {"messages": merged, "thinking": thinking_segs, "meta": meta}, meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("agent_output")
    ap.add_argument("out")
    ap.add_argument("--task-md", default=None, help="用 TASK.md 内容替换第一条 user 消息")
    ap.add_argument("--system-file", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "solver_prompt.md"))
    ap.add_argument("--metrics", default=None)
    args = ap.parse_args()

    system_text = ""
    if args.system_file and os.path.exists(args.system_file):
        system_text = open(args.system_file, encoding="utf-8").read()
    task_text = open(args.task_md, encoding="utf-8").read() if args.task_md else None

    rec, meta = convert(args.agent_output, system_text, task_text)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    txt = json.dumps(meta, indent=1, ensure_ascii=False)
    print(txt)
    if args.metrics:
        open(args.metrics, "w").write(txt + "\n")


if __name__ == "__main__":
    main()
