#!/usr/bin/env python3
"""build_instances.py —— 从验证日志目录拼出「实例 json」（绕过官方 gather，讲义 §1.4.3：
HEAD 上 gather 读的是 PASS_TO_FAIL，会把所有实例判成 no-validatable-bug 而全跳过）。

用法:
    python3 build_instances.py <run_validation/<repo>/ 目录> <out_dir> [--repo-name Instagram__MonkeyType.70c3acf6]

每个存活实例（F2P>=1 且 P2P>=1）写一个 <out_dir>/<instance_id>.json，字段照讲义 §1.4.1：
    instance_id / patch / FAIL_TO_PASS / PASS_TO_PASS / repo / image_name / problem_statement(空)
⚠️ 这些 json 是**答案的一半**（F2P 名单 = 判分表），必须留在宿主机、绝不进沙箱。
"""

import argparse
import json
import os

IMAGE = "swebench/swesmith.x86_64.instagram_1776_monkeytype.70c3acf6"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("valid_dir")
    ap.add_argument("out_dir")
    ap.add_argument("--repo-name", default="Instagram__MonkeyType.70c3acf6")
    ap.add_argument("--image", default=IMAGE)
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    n_total = n_ok = 0
    for name in sorted(os.listdir(args.valid_dir)):
        d = os.path.join(args.valid_dir, name)
        rep, pat = os.path.join(d, "report.json"), os.path.join(d, "patch.diff")
        if not (os.path.isfile(rep) and os.path.isfile(pat)):
            continue
        n_total += 1
        r = json.load(open(rep))
        f2p, p2p = r.get("FAIL_TO_PASS", []), r.get("PASS_TO_PASS", [])
        if not f2p or not p2p:
            print(f"skip {name}: F2P={len(f2p)} P2P={len(p2p)}")
            continue
        inst = {
            "instance_id": name,
            "patch": open(pat).read(),
            "FAIL_TO_PASS": f2p,
            "PASS_TO_PASS": p2p,
            "repo": f"swesmith/{args.repo_name}",
            "image_name": args.image,
            "problem_statement": "",
        }
        with open(os.path.join(args.out_dir, name + ".json"), "w") as f:
            json.dump(inst, f, indent=1, ensure_ascii=False)
        n_ok += 1
        print(f"ok   {name}: F2P={len(f2p)} P2P={len(p2p)}")
    print(f"\n存活 {n_ok}/{n_total}  ->  {args.out_dir}")


if __name__ == "__main__":
    main()
