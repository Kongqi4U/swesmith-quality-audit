#!/usr/bin/env python3
"""hide_tests.py —— 把实例的 F2P 测试按固定种子 50/50 拆成「可见 / 隐藏」，
并把隐藏的那些**测试函数**从沙箱里 AST 级删掉（删函数，不删整个文件）。

用法:
    python3 hide_tests.py <sandbox_dir> <instance_json> <hidden_json_out> [--seed 20260907] [--dry-run]
        [--stratify-by-hunk [--venv DIR] [--hunk-base DIR] [--hunk-timeout 600]]

规则:
  * 参数化测试按**函数**处理：`test_x[a]`/`test_x[b]` 属同一个函数，同进同出。
  * 拆分粒度 = 函数组。按 sha256(seed|函数全名) 排序后取前一半隐藏（比 random.shuffle
    在 n 很小时分布更均匀）；同一个 seed + 同一个实例永远得到同一份拆分。
  * 只有 1 个 F2P 函数组的实例：全部可见、隐藏为空，输出里 `all_visible: true` 打标记。
  * 隐藏名单写到沙箱**外**的 <hidden_json_out>（绝不能落在 sandbox 里）。
  * 删函数后若某个 class 体被清空，自动补一行 `pass`，保证文件仍可 import。

`--stratify-by-hunk`（多 hunk 实例专用，见「冒烟-S3-solver结果-0907」§85gza9xd）:
  bug patch 拆成 hunk（按 diff 的 `@@` 段，同文件多 hunk 也算多个）。对每个 hunk **单独反向
  应用**（= 只修这一个 hunk、别的 hunk 还坏着）后在 venv 里跑该实例全部 F2P 测试，
  「跑绿了的测试」就是这个 hunk 独自控制的信号 → 得到「测试函数组 → 依赖哪些 hunk」的映射。
  然后在**每个 hunk 的测试组内**各做一次 50/50（组内只有 1 个函数时归可见），
  可见数 = ceil(n/2) ≥ 1 → **每个 hunk 至少留 1 条可见**，不会出现「某个 hunk 零提示」的死题。
  单 hunk 实例（n_hunks <= 1）直接走老路径，切分逐字不变。
"""

import argparse
import ast
import json
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
JUNK_DIRS = {".pytest_cache", "__pycache__", ".tox", ".mypy_cache", "htmlcov", ".hypothesis", ".git"}
PASS_STATUS = {"PASSED", "XPASS"}


# ---------- test id 解析 ----------
def parse_nodeid(nodeid: str):
    """'tests/a.py::C::test_f[p 1]' -> ('tests/a.py', ('C',), 'test_f')"""
    parts = nodeid.split("::")
    path = parts[0]
    if len(parts) == 1:
        raise ValueError(f"not a function-level node id: {nodeid}")
    func = parts[-1]
    if "[" in func:
        func = func[: func.index("[")]
    classes = tuple(parts[1:-1])
    return path, classes, func


def group_key(nodeid: str):
    p, c, f = parse_nodeid(nodeid)
    return (p, c, f)


# ---------- AST 级删函数 ----------
def _walk_funcs(tree):
    """yield (classes_tuple, node) for every function def, incl. nested in classes."""

    def rec(body, classes):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield classes, node
            elif isinstance(node, ast.ClassDef):
                yield from rec(node.body, classes + (node.name,))

    yield from rec(tree.body, ())


def _node_span(node):
    start = node.lineno
    for d in getattr(node, "decorator_list", []):
        start = min(start, d.lineno)
    return start, node.end_lineno


def delete_functions(src_path: str, targets: set, dry_run=False):
    """targets: set of (classes_tuple, funcname). Returns (n_deleted, missing set)."""
    with open(src_path, "r", encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src, filename=src_path)
    lines = src.splitlines(keepends=True)

    found = {}
    for classes, node in _walk_funcs(tree):
        key = (classes, node.name)
        if key in targets:
            found[key] = node

    missing = targets - set(found)
    if not found:
        return 0, missing

    kill = set()
    for node in found.values():
        s, e = _node_span(node)
        kill.update(range(s, e + 1))  # 1-based

    # class 体被清空 -> 补 pass
    inserts = {}  # lineno(1-based) -> text to put before deletion block

    def scan_classes(body, classes):
        for node in body:
            if isinstance(node, ast.ClassDef):
                child_keys = [
                    (classes + (node.name,), c.name)
                    for c in node.body
                    if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                n_stmts = len(node.body)
                n_killed = sum(1 for k in child_keys if k in found)
                if n_stmts > 0 and n_killed == n_stmts:
                    indent = " " * node.body[0].col_offset
                    inserts[node.body[0].lineno] = indent + "pass\n"
                scan_classes(node.body, classes + (node.name,))

    scan_classes(tree.body, ())

    out = []
    for i, line in enumerate(lines, start=1):
        if i in inserts:
            out.append(inserts[i])
        if i not in kill:
            out.append(line)
    new_src = "".join(out)
    ast.parse(new_src, filename=src_path)  # 语法自检，坏了就抛
    if not dry_run:
        with open(src_path, "w", encoding="utf-8") as f:
            f.write(new_src)
    return len(found), missing


# ---------- hunk 切分 ----------
def split_hunks(patch_text: str):
    """把一个 unified diff 拆成一个个 hunk。

    返回 [{index, file, hunk_header, text}]，`text` = 该文件的 diff 头 + 这一个 @@ 段，
    是一份可以单独 `git apply -R` 的最小补丁。同一个文件的多个 @@ 段会拆成多条。
    """
    lines = patch_text.splitlines(keepends=True)
    n = len(lines)

    def starts_file(i):
        """i 处是不是一个新文件段的开头。

        SWE-smith 的 bug patch 两种格式都有：带 `diff --git` 头的，和直接 `--- a/x` 开头的
        （func_pm_remove_loop__0mdq6eqw 就是后者）。
        """
        if lines[i].startswith("diff --git "):
            return True
        return lines[i].startswith("--- ") and i + 1 < n and lines[i + 1].startswith("+++ ")

    out, header, path = [], None, None
    i = 0
    while i < n:
        if starts_file(i):
            hdr = []
            while i < n and not lines[i].startswith("@@"):
                hdr.append(lines[i])
                i += 1
                if i < n and starts_file(i):
                    break
            header = "".join(hdr)
            path = None
            for h in hdr:
                if h.startswith("+++ "):
                    path = h[4:].strip()
                    if path.startswith("b/"):
                        path = path[2:]
                    break
                if h.startswith("diff --git ") and " b/" in h:
                    path = h.split(" b/", 1)[-1].strip()
            continue
        if lines[i].startswith("@@"):
            hh = lines[i].rstrip("\n")
            body = [lines[i]]
            i += 1
            # hunk 体里的内容行都带 ' ' / '+' / '-' 前缀，顶格的 @@ / 文件头只可能是下一段
            while i < n and not lines[i].startswith("@@") and not starts_file(i):
                body.append(lines[i])
                i += 1
            out.append({
                "index": len(out),
                "file": path,
                "hunk_header": hh,
                "text": (header or "") + "".join(body),
            })
            continue
        i += 1
    return out


def _copy_base(src, dst):
    shutil.copytree(src, dst, symlinks=True,
                    ignore=shutil.ignore_patterns(*JUNK_DIRS, "*.pyc", ".coverage"))
    for root, dirs, _ in os.walk(dst, topdown=True):
        for d in list(dirs):
            if d in JUNK_DIRS:
                shutil.rmtree(os.path.join(root, d), ignore_errors=True)
                dirs.remove(d)


def _reverse_apply(workdir, patch_text):
    f = os.path.join(workdir, ".hunk.diff")
    with open(f, "w", encoding="utf-8") as fh:
        fh.write(patch_text if patch_text.endswith("\n") else patch_text + "\n")
    for cmd in (["git", "apply", "-R", f],
                ["git", "apply", "-R", "--recount", f],
                ["patch", "--batch", "--fuzz=5", "-R", "-p1", "-i", f]):
        p = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True)
        if p.returncode == 0:
            os.remove(f)
            subprocess.run(f"find {workdir} -name '*.orig' -o -name '*.rej' -delete",
                           shell=True, capture_output=True)
            return " ".join(cmd[:3])
    os.remove(f)
    return None


def _run_f2p(workdir, node_ids, venv, timeout=600):
    """在 workdir 里只跑这些 node id，返回 {nodeid: status}。"""
    fd, rep = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    env = dict(os.environ)
    env["PYTHONPATH"] = workdir + os.pathsep + HERE
    env["SWESMITH_REPORT_JSON"] = rep
    try:
        subprocess.run(
            [os.path.join(venv, "bin", "python"), "-m", "pytest",
             "-p", "pytest_report_plugin", "--disable-warnings", "--color=no",
             "--tb=no", "-q", "-p", "no:cacheprovider"] + list(node_ids),
            cwd=workdir, env=env, capture_output=True, text=True, timeout=timeout)
        try:
            data = json.load(open(rep))["results"]
        except Exception:
            data = {}
    finally:
        if os.path.exists(rep):
            os.unlink(rep)
    return data


def _groups_passing(results, groups):
    """一个函数组算「过」= 它名下的 node id 全部过（且都跑到了）。"""
    ok = set()
    for k, ids in groups.items():
        st = [results.get(i, "MISSING") for i in ids]
        if st and all(s in PASS_STATUS for s in st):
            ok.add(k)
    return ok


def analyze_hunks(base_dir, patch_text, groups, venv, timeout=600, keep=False):
    """对每个 hunk 单独反向应用后跑 F2P，返回 (hunks, group->[hunk idx], 诊断 dict)。"""
    hunks = split_hunks(patch_text)
    f2p_ids = sorted(i for ids in groups.values() for i in ids)
    work = tempfile.mkdtemp(prefix="hunkprobe-")
    diag = {"hunk_apply": [], "base_passing_groups": []}
    fixed_by = {k: [] for k in groups}
    try:
        # 基线：bug patch 全在（= base_dir 原样），F2P 应当全挂
        wd = os.path.join(work, "base")
        _copy_base(base_dir, wd)
        base_res = _run_f2p(wd, f2p_ids, venv, timeout)
        base_ok = _groups_passing(base_res, groups)
        diag["base_passing_groups"] = sorted("::".join((k[0],) + k[1] + (k[2],)) for k in base_ok)
        shutil.rmtree(wd, ignore_errors=True)

        for h in hunks:
            wd = os.path.join(work, f"h{h['index']}")
            _copy_base(base_dir, wd)
            how = _reverse_apply(wd, h["text"])
            if how is None:
                diag["hunk_apply"].append({"index": h["index"], "applied": None})
                shutil.rmtree(wd, ignore_errors=True)
                continue
            res = _run_f2p(wd, f2p_ids, venv, timeout)
            ok = _groups_passing(res, groups) - base_ok
            diag["hunk_apply"].append({"index": h["index"], "applied": how, "n_groups_fixed": len(ok)})
            for k in ok:
                fixed_by[k].append(h["index"])
            shutil.rmtree(wd, ignore_errors=True)
    finally:
        if keep:
            print(f"[hunk workdir kept] {work}", file=sys.stderr)
        else:
            shutil.rmtree(work, ignore_errors=True)
    return hunks, fixed_by, diag


def _split_bucket(keys, seed):
    """桶内 50/50：隐藏 len//2 条，可见 ceil(n/2) 条 —— n>=1 时可见必 >= 1。"""
    if len(keys) <= 1:
        return sorted(keys), []
    order = sorted(keys, key=lambda k: hashlib.sha256(
        f"{seed}|{'::'.join((k[0],) + k[1] + (k[2],))}".encode()).hexdigest())
    n_hidden = len(order) // 2
    return sorted(order[n_hidden:]), sorted(order[:n_hidden])


def split_f2p_by_hunk(groups, hunks, fixed_by, seed):
    """按 hunk 分层：每个组归到 min(它依赖的 hunk)，桶内各做一次 50/50。"""
    buckets = {h["index"]: [] for h in hunks}
    shared = []
    for k, idxs in fixed_by.items():
        (buckets[min(idxs)] if idxs else shared).append(k)
    visible, hidden, per_hunk = [], [], []
    for h in hunks:
        vis, hid = _split_bucket(buckets[h["index"]], seed)
        visible += vis
        hidden += hid
        per_hunk.append({
            "index": h["index"], "file": h["file"], "hunk_header": h["hunk_header"],
            "n_groups": len(buckets[h["index"]]),
            "visible_funcs": [_fk(k) for k in vis],
            "hidden_funcs": [_fk(k) for k in hid],
        })
    vis, hid = _split_bucket(shared, seed)
    visible += vis
    hidden += hid
    meta = {
        "n_hunks": len(hunks),
        "per_hunk": per_hunk,
        "hunk_map": {_fk(k): sorted(v) for k, v in sorted(fixed_by.items())},
        "shared_groups": [_fk(k) for k in sorted(shared)],
        "shared_visible_funcs": [_fk(k) for k in vis],
        "shared_hidden_funcs": [_fk(k) for k in hid],
        "hunks_without_own_tests": [h["index"] for h in hunks if not buckets[h["index"]]],
    }
    return sorted(visible), sorted(hidden), meta


def _fk(k):
    return "::".join((k[0],) + k[1] + (k[2],))


# ---------- 主流程 ----------
def split_f2p(f2p: list, seed: int):
    groups = {}
    for nid in f2p:
        groups.setdefault(group_key(nid), []).append(nid)
    keys = sorted(groups)
    if len(keys) <= 1:
        return keys, [], groups, True
    # 用 sha256(seed|key) 排序而不是 random.shuffle：n 很小时 shuffle 的取值分布很粗
    order = sorted(keys, key=lambda k: hashlib.sha256(
        f"{seed}|{'::'.join((k[0],) + k[1] + (k[2],))}".encode()).hexdigest())
    n_hidden = len(order) // 2  # 50/50，奇数时可见多一个
    hidden = sorted(order[:n_hidden])
    visible = sorted(order[n_hidden:])
    return visible, hidden, groups, False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sandbox")
    ap.add_argument("instance_json")
    ap.add_argument("hidden_json_out")
    ap.add_argument("--seed", type=int, default=20260907)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--stratify-by-hunk", action="store_true",
                    help="多 hunk 实例：按 hunk 分层做 50/50，保证每个 hunk 至少 1 条可见")
    ap.add_argument("--venv", default=None, help="跑 hunk 探针用的 venv（默认按 repos.json 查表）")
    ap.add_argument("--hunk-base", default=None,
                    help="hunk 探针的底本目录，默认 = sandbox（此时它应当是「干净仓 + 完整 bug patch + 全部测试」）")
    ap.add_argument("--hunk-timeout", type=int, default=600)
    ap.add_argument("--keep-hunk-workdir", action="store_true")
    args = ap.parse_args()

    inst = json.load(open(args.instance_json))
    f2p = inst["FAIL_TO_PASS"]
    vis_keys, hid_keys, groups, all_visible = split_f2p(f2p, args.seed)

    hunk_meta = None
    if args.stratify_by_hunk and not all_visible:
        hunks = split_hunks(inst["patch"])
        if len(hunks) <= 1:
            hunk_meta = {"n_hunks": len(hunks), "applied": False,
                         "reason": "single-hunk instance: 走原 50/50，行为不变"}
        else:
            venv = args.venv
            if not venv:
                sys.path.insert(0, HERE)
                import repo_config
                venv = repo_config.get_or_default(inst.get("repo", "")).get("venv")
            base = os.path.abspath(args.hunk_base or args.sandbox)
            hs, fixed_by, diag = analyze_hunks(base, inst["patch"], groups, venv,
                                               timeout=args.hunk_timeout,
                                               keep=args.keep_hunk_workdir)
            vis_keys, hid_keys, hunk_meta = split_f2p_by_hunk(groups, hs, fixed_by, args.seed)
            hunk_meta.update({"applied": True, "venv": venv, "hunk_base": base, "probe": diag})
    elif args.stratify_by_hunk:
        hunk_meta = {"applied": False, "reason": "all_visible 实例（只有 1 个 F2P 函数组）"}

    # 分层的「软问题」不该让 make_sandbox 挂掉，单独放 warnings（problems 才是致命的）
    warnings = []
    if hunk_meta and hunk_meta.get("applied"):
        for i in hunk_meta.get("hunks_without_own_tests") or []:
            warnings.append(f"hunk {i} 没有独占的 F2P 测试组 → 它拿不到可见提示")
        for bad in [d for d in hunk_meta["probe"]["hunk_apply"] if d.get("applied") is None]:
            warnings.append(f"hunk {bad['index']} 反向应用失败，未纳入分层")
        if hunk_meta["probe"]["base_passing_groups"]:
            warnings.append("这些 F2P 在完整 bug patch 下就已经过了："
                            + ", ".join(hunk_meta["probe"]["base_passing_groups"][:5]))

    visible_ids = sorted(i for k in vis_keys for i in groups[k])
    hidden_ids = sorted(i for k in hid_keys for i in groups[k])

    # 按文件聚合要删的函数
    by_file = {}
    for path, classes, func in hid_keys:
        by_file.setdefault(path, set()).add((classes, func))

    deleted, problems = 0, []
    for rel, targets in sorted(by_file.items()):
        abspath = os.path.join(args.sandbox, rel)
        if not os.path.exists(abspath):
            problems.append(f"missing file: {rel}")
            continue
        n, missing = delete_functions(abspath, targets, dry_run=args.dry_run)
        deleted += n
        for c, f in sorted(missing):
            problems.append(f"func not found in {rel}: {'::'.join(c + (f,))}")

    out = {
        "instance_id": inst.get("instance_id"),
        "seed": args.seed,
        "all_visible": all_visible,
        "n_f2p_ids": len(f2p),
        "n_f2p_funcs": len(groups),
        "visible": visible_ids,
        "hidden": hidden_ids,
        "hidden_funcs": ["::".join((p,) + c + (f,)) for p, c, f in sorted(hid_keys)],
        "visible_funcs": ["::".join((p,) + c + (f,)) for p, c, f in sorted(vis_keys)],
        "n_funcs_deleted": deleted,
        "problems": problems,
        "stratify_by_hunk": bool(hunk_meta and hunk_meta.get("applied")),
        "hunks": hunk_meta,
        "warnings": warnings,
        "PASS_TO_PASS": inst.get("PASS_TO_PASS", []),
    }
    hj = os.path.abspath(args.hidden_json_out)
    sb = os.path.abspath(args.sandbox)
    if hj.startswith(sb + os.sep):
        sys.exit(f"REFUSE: hidden json {hj} would land inside the sandbox {sb}")
    if not args.dry_run:
        with open(hj, "w") as f:
            json.dump(out, f, indent=1, ensure_ascii=False)
    brief = {k: v for k, v in out.items()
             if k not in ("visible", "hidden", "PASS_TO_PASS", "hunks")}
    if hunk_meta:
        brief["n_hunks"] = hunk_meta.get("n_hunks")
        brief["hunk_visible_hidden"] = [
            {"hunk": h["index"], "file": h["file"],
             "visible": len(h["visible_funcs"]), "hidden": len(h["hidden_funcs"])}
            for h in hunk_meta.get("per_hunk", [])]
    print(json.dumps(brief, indent=1, ensure_ascii=False))
    if problems:
        sys.exit(2)


if __name__ == "__main__":
    main()
