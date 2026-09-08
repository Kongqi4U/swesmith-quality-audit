#!/usr/bin/env python3
"""make_sandbox.py —— 造一个 venv 用的 solver 沙箱（不用 Docker、不用 git worktree）。

用法:
    python3 make_sandbox.py <instance_json> <out_dir> [--clean-repo DIR] [--seed 20260907]
                            [--stratify-by-hunk]

配方（讲义 §4.2 逐字，只是把「容器里」换成「目录里」）:
  ① 从干净仓复制一份（干净仓/venv 按实例 json 的 repo 字段查 harness/repos.json，
     没有就 git clone --depth 1 该仓的官方镜像仓 main）
  ② git apply 该实例的 bug patch          -> 仓库变成坏版本
  ③ hide_tests.py 删掉隐藏的 F2P 测试函数  -> held-out 测试不在工作区
     （多 hunk 实例可加 --stratify-by-hunk：每个 hunk 至少留 1 条可见测试）
  ④ 写 TASK.md（S3 阶段：最简 issue 占位 + 可见测试名单）
  ⑤ rm -rf .git && git init && git config user.{name,email} && git add -A && git commit -m init
     -> 工作区里没有干净态、没有 bug 分支、没有 remote，`git diff main` 拿不到 gold
     -> 仓库级预置假身份 `solver <solver@sandbox.local>`：solver 收尾 commit 不会再失败，
        也不会把宿主用户的真实邮箱写进训练轨迹（见「冒烟-S3-solver结果-0907」§transcript 结构 3）

⚠️ 绝不用 `git worktree`：共享 .git 会把干净态整个泄漏给 solver。
⚠️ 隐藏名单落在沙箱**外**：<out_dir>.hidden.json
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import repo_config  # noqa: E402

DEFAULT_CLEAN = os.path.join(repo_config.LAB, "repos", "clean-monkeytype")
JUNK_DIRS = {".pytest_cache", "__pycache__", ".tox", ".mypy_cache", "htmlcov", ".hypothesis"}
JUNK = list(JUNK_DIRS) + ["*.pyc", ".coverage", "*.egg-info"]
GIT_USER = "solver"
GIT_EMAIL = "solver@sandbox.local"


def run(cmd, cwd=None, check=True, **kw):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, **kw)
    if check and p.returncode != 0:
        sys.exit(f"FAILED: {cmd}\nstdout:\n{p.stdout}\nstderr:\n{p.stderr}")
    return p


def ensure_clean_repo(path, mirror_url):
    if os.path.isdir(os.path.join(path, ".git")):
        return path
    if not mirror_url:
        sys.exit(f"{path} 不存在且没有 mirror_url 可 clone（检查 harness/repos.json）")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    print(f"[clone] {mirror_url} -> {path}")
    run(["git", "clone", "--depth", "1", mirror_url, path])
    return path


def apply_patch(sandbox, diff_path):
    for cmd in (
        ["git", "apply", "--verbose", diff_path],
        ["git", "apply", "--verbose", "--reject", diff_path],
        ["patch", "--batch", "--fuzz=5", "-p1", "-i", diff_path],
    ):
        p = run(cmd, cwd=sandbox, check=False)
        if p.returncode == 0:
            return " ".join(cmd[:2])
    sys.exit(f"could not apply {diff_path} in {sandbox}")


TASK_TMPL = """# 任务

仓库 `{repo}` 里有一处 bug：某个函数/类的行为被改坏了，导致下面这些测试失败。

**你的目标：让这些测试全部通过，同时不要弄坏其它任何测试。**

失败的测试（可见部分）：

```
{visible}
```

跑测试：

```bash
{test_hint}
```

注意：
- 只改产品代码（`{code}`），**不要改测试文件**——改了也没用，评测时测试会被还原。
- 评测时还会跑一批你在这里看不到的测试，所以请修根因，不要只让上面这几条过。
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance_json")
    ap.add_argument("out_dir")
    ap.add_argument("--clean-repo", default=None,
                    help="默认按实例 json 的 repo 字段查 harness/repos.json")
    ap.add_argument("--seed", type=int, default=20260907)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--stratify-by-hunk", action="store_true",
                    help="透传给 hide_tests.py：多 hunk 实例按 hunk 分层切分")
    args = ap.parse_args()

    inst = json.load(open(args.instance_json))
    cfg = repo_config.get_or_default(inst.get("repo", ""))
    out = os.path.abspath(args.out_dir)
    if os.path.exists(out):
        if not args.force:
            sys.exit(f"{out} exists (use --force)")
        shutil.rmtree(out)

    clean = ensure_clean_repo(os.path.abspath(args.clean_repo or cfg["clean_repo"]),
                              cfg.get("mirror_url"))
    dirty = run(["git", "status", "--porcelain"], cwd=clean).stdout.strip()
    if dirty and not args.force:
        sys.exit(f"clean repo {clean} is dirty, refusing to propagate:\n{dirty}")

    # ① 复制（含 .git，为了 git apply 好用；⑤ 里整个删掉）
    # ⚠️ 必须挡掉缓存类目录：.pytest_cache/v/cache/nodeids 里存着**全部测试 id**，
    #    照抄进沙箱等于把隐藏测试名单直接送给 solver（自测时真踩到过）。
    shutil.copytree(clean, out, symlinks=True, ignore=shutil.ignore_patterns(*JUNK))
    for root, dirs, _ in os.walk(out, topdown=True):
        for d in list(dirs):
            if d in JUNK_DIRS:
                shutil.rmtree(os.path.join(root, d), ignore_errors=True)
                dirs.remove(d)

    # ② bug patch
    diff = os.path.join(out, ".bug.diff")
    with open(diff, "w") as f:
        f.write(inst["patch"])
    how = apply_patch(out, diff)
    os.remove(diff)
    for junk in ("*.orig", "*.rej"):
        subprocess.run(f"find {out} -name '{junk}' -delete", shell=True)

    # ③ 隐藏测试
    hidden_json = out + ".hidden.json"
    hide_cmd = [sys.executable, os.path.join(HERE, "hide_tests.py"),
                out, os.path.abspath(args.instance_json), hidden_json,
                "--seed", str(args.seed)]
    if args.stratify_by_hunk:
        # 此刻 out = 干净仓 + 完整 bug patch + **全部**测试，正是 hunk 探针要的底本
        hide_cmd += ["--stratify-by-hunk", "--venv", cfg["venv"]]
    p = run(hide_cmd, check=False)
    print(p.stdout, p.stderr)
    if p.returncode != 0:
        sys.exit("hide_tests.py failed")
    hid = json.load(open(hidden_json))

    # ④ TASK.md
    _rt = os.path.join(HERE, "run_tests.sh")
    test_hint = (f"bash {_rt} "
                 f"{out}          # 全部可见测试\n"
                 f"bash {_rt} "
                 f"{out} <node_id> # 单条")
    code = "、".join(f"`{c}/`" for c in cfg.get("code_prefixes", [])) or "产品代码目录"
    with open(os.path.join(out, "TASK.md"), "w") as f:
        f.write(TASK_TMPL.format(repo=inst.get("repo", "?"),
                                 visible="\n".join(hid["visible"]),
                                 code=code,
                                 test_hint=test_hint))

    # ⑤ 重建 git：单 commit、无 remote、无干净态
    #    仓库级（不是 --global）预置假身份，solver 的收尾 commit 不会再 Author identity unknown
    shutil.rmtree(os.path.join(out, ".git"))
    run(["git", "init", "-q", "-b", "main"], cwd=out)
    run(["git", "config", "user.name", GIT_USER], cwd=out)
    run(["git", "config", "user.email", GIT_EMAIL], cwd=out)
    run(["git", "add", "-A"], cwd=out)
    run(["git", "commit", "-qm", "init"], cwd=out)
    sha = run(["git", "rev-parse", "HEAD"], cwd=out).stdout.strip()
    author = run(["git", "log", "-1", "--format=%an <%ae>"], cwd=out).stdout.strip()

    # 自检
    n_commits = int(run(["git", "rev-list", "--count", "HEAD"], cwd=out).stdout)
    branches = run(["git", "branch", "-a"], cwd=out).stdout.split()
    remotes = run(["git", "remote", "-v"], cwd=out).stdout.strip()
    leaks = []
    if n_commits != 1:
        leaks.append(f"commits={n_commits}")
    if remotes:
        leaks.append(f"remotes={remotes!r}")
    if author != f"{GIT_USER} <{GIT_EMAIL}>":
        leaks.append(f"unexpected commit author: {author!r}")
    # 隐藏函数是否真的没了：用 AST 按 (文件, 类链, 函数名) 精确核对
    # （不能光 grep 函数名 —— test_rewrite 这种名字别的类里也有，会误报）
    sys.path.insert(0, HERE)
    import ast as _ast
    from hide_tests import _walk_funcs
    for hf in hid["hidden_funcs"]:
        bits = hf.split("::")
        rel, classes, fn = bits[0], tuple(bits[1:-1]), bits[-1]
        fp = os.path.join(out, rel)
        if not os.path.exists(fp):
            leaks.append(f"hidden test file vanished entirely: {rel}")
            continue
        tree = _ast.parse(open(fp, encoding="utf-8").read(), filename=fp)
        if any(c == classes and n.name == fn for c, n in _walk_funcs(tree)):
            leaks.append(f"hidden func still present: {hf}")
    # 沙箱里不许出现任何任务/判分文件
    g = subprocess.run(
        f"find {out} -name '*.hidden.json' -o -name 'report.json' -o -name '*_all_patches.json' "
        f"-o -name '*.diff' -o -name '.pytest_cache' -o -name 'nodeids'",
        shell=True, capture_output=True, text=True)
    if g.stdout.strip():
        leaks.append("task/cache files inside sandbox:\n" + g.stdout.strip()[:400])

    hid["init_commit"] = sha
    hid["init_author"] = author
    hid["sandbox"] = out
    hid["instance_json"] = os.path.abspath(args.instance_json)
    hid["apply_method"] = how
    hid["repo_key"] = cfg.get("key")
    hid["venv"] = cfg.get("venv")
    hid["clean_repo"] = clean
    with open(hidden_json, "w") as f:
        json.dump(hid, f, indent=1, ensure_ascii=False)

    summary = {
        "sandbox": out, "hidden_json": hidden_json, "init_commit": sha,
        "init_author": author, "repo_key": cfg.get("key"), "venv": cfg.get("venv"),
        "n_commits": n_commits, "branches": branches,
        "n_visible": len(hid["visible"]), "n_hidden": len(hid["hidden"]),
        "all_visible": hid["all_visible"],
        "stratify_by_hunk": hid.get("stratify_by_hunk", False),
        "warnings": hid.get("warnings", []),
        "leaks": leaks,
    }
    if hid.get("stratify_by_hunk"):
        hm = hid["hunks"]
        summary["n_hunks"] = hm["n_hunks"]
        summary["per_hunk_visible_hidden"] = [
            {"hunk": h["index"], "file": h["file"],
             "visible": len(h["visible_funcs"]), "hidden": len(h["hidden_funcs"])}
            for h in hm["per_hunk"]]
    print(json.dumps(summary, indent=1, ensure_ascii=False))
    if leaks:
        sys.exit(3)


if __name__ == "__main__":
    main()
