#!/usr/bin/env python3
"""repo_config.py —— harness/repos.json 的查表器（多仓库支持）。

实例 json 的 `repo` 字段形如 `swesmith/Instagram__MonkeyType.70c3acf6`；
镜像仓命名规律 = `swesmith/<owner>__<repo>.<commit[:8]>`
（SWE-smith/swesmith/profiles/base.py:207 `repo_name`）。

查表接受三种写法，都能命中同一条：
    swesmith/Instagram__MonkeyType.70c3acf6   (实例 json 原样)
    Instagram__MonkeyType.70c3acf6            (去掉 org)
    monkeytype                                (短 key / alias)

命令行:
    python3 repo_config.py                # 列出所有仓
    python3 repo_config.py <repo> [field]  # 查一条 / 取一个字段（给 shell 用）
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPOS_JSON = os.path.join(HERE, "repos.json")

# lab 根目录（干净仓 / venv / 沙箱都挂在它下面）。repos.json 里写 ${SWESMITH_LAB}，
# 这里统一展开；不设环境变量时退回原始 VPS 路径，老脚本行为不变。
LAB = os.environ.get("SWESMITH_LAB", "/root/workspace/swesmith-lab").rstrip("/")

_CACHE = None


def load_repos():
    global _CACHE
    if _CACHE is None:
        with open(REPOS_JSON, encoding="utf-8") as f:
            raw = f.read().replace("${SWESMITH_LAB}", LAB)
        _CACHE = json.loads(raw)["repos"]
    return _CACHE


def _index():
    idx = {}
    for full, cfg in load_repos().items():
        keys = {full, full.split("/", 1)[-1], cfg.get("key", "")}
        keys.update(cfg.get("aliases", []))
        for k in keys:
            if k:
                idx[k.lower()] = cfg
    return idx


def get(repo, strict=True):
    """repo 可以是实例 json 的 repo 字段 / 仓名 / 短 key。找不到时 strict 则抛。"""
    if isinstance(repo, dict):  # 直接传实例 json 也行
        repo = repo.get("repo", "")
    cfg = _index().get(str(repo).lower())
    if cfg is None and strict:
        raise KeyError(
            f"repo {repo!r} 不在 {REPOS_JSON} 里；已知："
            + ", ".join(sorted(c.get("key", "?") for c in load_repos().values()))
        )
    return cfg


def get_or_default(repo, default_key="monkeytype"):
    """找不到就退回默认仓（老脚本行为不变）。"""
    return get(repo, strict=False) or get(default_key)


def all_venvs():
    return sorted({c["venv"] for c in load_repos().values() if c.get("venv")})


def all_clean_repos():
    return sorted({c["clean_repo"] for c in load_repos().values() if c.get("clean_repo")})


def main():
    if len(sys.argv) == 1:
        for full, cfg in load_repos().items():
            print(f"{cfg.get('key','?'):12s} {full}\n"
                  f"{'':12s}   clean={cfg.get('clean_repo')}\n"
                  f"{'':12s}   venv ={cfg.get('venv')}")
        return
    cfg = get(sys.argv[1], strict=False)
    if cfg is None:
        sys.exit(f"unknown repo: {sys.argv[1]}")
    if len(sys.argv) >= 3:
        v = cfg.get(sys.argv[2], "")
        print(v if not isinstance(v, (list, dict)) else json.dumps(v, ensure_ascii=False))
    else:
        print(json.dumps(cfg, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
