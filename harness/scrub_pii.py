#!/usr/bin/env python3
"""scrub_pii.py —— 把训练产物里的真实邮箱换成 `solver@sandbox.local`。

背景：S3 冒烟时沙箱没预置 git 身份，solver 的收尾 commit 报 `Author identity unknown`，
于是它自己跑了 `git config user.email "<宿主用户真实邮箱>"` —— 这条命令连同邮箱进了 4 条训练轨迹。
`make_sandbox.py` 已经预置假身份堵住源头，这个脚本只负责洗已经落盘的产物。

用法:
    python3 scrub_pii.py <file|dir> [...] [--apply] [--replacement solver@sandbox.local]

默认 **dry-run**，只报「哪个文件、第几行、原文是什么」；加 `--apply` 才真写。
只扫 `results/` 这类我们自己产的文件；`~/.claude/` 下的原始 transcript **不动**。

白名单（不算真实邮箱，不替换）:
  * `you@example.com` / `you@example.org` —— git 自己 `Author identity unknown` 提示里的占位符
  * 以 `@example.com` / `@example.org` / `@sandbox.local` / `@localhost` 结尾的
  * 明显是误匹配的（`@pytest.mark.xxx`、`@property` 这种装饰器紧跟在换行后）
"""

import argparse
import json
import os
import re
import sys

DEFAULT_REPL = "solver@sandbox.local"
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# 装饰器误匹配：`\n@pytest.mark.usefixtures` 之类（jsonl 里 \n 是字面两个字符）
DECORATOR_RE = re.compile(r"@(pytest|property|staticmethod|classmethod|mock|patch|"
                          r"functools|dataclass|abstractmethod|contextmanager)\b")
SAFE_DOMAINS = ("@example.com", "@example.org", "@example.net",
                "@sandbox.local", "@localhost", "@invalid")
SCAN_SUFFIXES = (".jsonl", ".json", ".md", ".txt", ".diff", ".patch")


def is_real_email(m: str) -> bool:
    if DECORATOR_RE.search(m):
        return False
    if m.lower().endswith(SAFE_DOMAINS):
        return False
    return True


def scrub_text(text: str, repl: str):
    """-> (new_text, [(occurrence, count)])"""
    found = {}

    def sub(m):
        s = m.group(0)
        if not is_real_email(s):
            return s
        found[s] = found.get(s, 0) + 1
        return repl

    return EMAIL_RE.sub(sub, text), found


def iter_files(targets):
    for t in targets:
        t = os.path.abspath(t)
        if os.path.isfile(t):
            yield t
        elif os.path.isdir(t):
            for root, _, files in os.walk(t):
                for fn in sorted(files):
                    if fn.endswith(SCAN_SUFFIXES):
                        yield os.path.join(root, fn)
        else:
            print(f"[skip] not found: {t}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("targets", nargs="+")
    ap.add_argument("--apply", action="store_true", help="真的写盘（默认只 dry-run）")
    ap.add_argument("--replacement", default=DEFAULT_REPL)
    ap.add_argument("--out", default=None, help="把清单写成 json")
    args = ap.parse_args()

    for t in args.targets:
        if os.path.abspath(t).startswith(os.path.expanduser("~/.claude")):
            sys.exit(f"REFUSE: {t} 在 ~/.claude 下，原始 transcript 不许改")

    report, n_files, n_hits = [], 0, 0
    for path in iter_files(args.targets):
        try:
            text = open(path, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError):
            continue
        new, found = scrub_text(text, args.replacement)
        if not found:
            continue
        n_files += 1
        n_hits += sum(found.values())
        lines = [i for i, ln in enumerate(text.splitlines(), 1)
                 if any(e in ln for e in found)]
        report.append({"file": path, "matches": found, "lines": lines})
        if args.apply:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new)

    out = {"mode": "apply" if args.apply else "dry-run",
           "replacement": args.replacement,
           "n_files_changed": n_files, "n_occurrences": n_hits,
           "details": report}
    txt = json.dumps(out, indent=1, ensure_ascii=False)
    print(txt)
    if args.out:
        open(args.out, "w", encoding="utf-8").write(txt + "\n")


if __name__ == "__main__":
    main()
