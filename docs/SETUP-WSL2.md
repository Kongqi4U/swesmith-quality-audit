# 本地环境搭建 · Windows 11 + WSL2（从零，照着敲）

目标机型：**Windows 11 / 16GB 内存 / RTX 3060 laptop**。
全程约 40–60 分钟（大头是 Docker 拉镜像）。

本文的路径约定：

| 名字 | 路径 | 是什么 |
|---|---|---|
| 本仓库 | `~/swesmith-quality-audit` | 你现在读的这个仓库（harness + 数据 + 报告） |
| lab | `~/swesmith-lab` | 工作目录：SWE-smith 源码、干净仓、venv、沙箱、产物 |

> 仓库和报告里出现的 `/root/workspace/swesmith-lab` 是**原始环境（一台 2GB VPS）**的路径，
> 不需要在本地复现它 —— harness 已经改成从环境变量 `SWESMITH_LAB` 读，见第 6 步。

---

## 1. 启用 WSL2 + Ubuntu 24.04

**管理员 PowerShell**：

```powershell
wsl --install -d Ubuntu-24.04
```

装完重启，第一次进 Ubuntu 会让你设用户名/密码。然后确认是 WSL2：

```powershell
wsl -l -v
#   NAME            STATE           VERSION
#   Ubuntu-24.04    Running         2        <- VERSION 必须是 2
```

### 把 WSL 内存上限设成 12GB

WSL2 默认会吃掉宿主一半以上内存，Docker 一跑就和 Windows 抢。
在 **Windows 侧**新建/编辑 `%USERPROFILE%\.wslconfig`（就是 `C:\Users\<你>\.wslconfig`）：

```ini
[wsl2]
memory=12GB
processors=6
swap=8GB
# 关掉 WSL 自动回收前的页面缓存膨胀
pageReporting=true
```

保存后在 PowerShell 里重启 WSL 生效：

```powershell
wsl --shutdown
```

再进 Ubuntu 验证：

```bash
free -g          # total 应约为 11–12
nproc            # 应为 6
```

---

## 2. Docker Desktop + WSL integration

1. 装 [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/)（选 WSL2 backend）。
2. Settings → **Resources → WSL Integration** → 打开 `Ubuntu-24.04` 的开关 → Apply & Restart。
3. 在 **Ubuntu 里**验证（不是在 PowerShell 里）：

```bash
docker version          # Client 和 Server 都要有输出
docker run --rm hello-world
# -> Hello from Docker!
```

如果 `docker` 提示 permission denied：

```bash
sudo usermod -aG docker $USER
# 然后退出 Ubuntu 再进（wsl --shutdown 最保险）
```

---

## 3. Ubuntu 里的基础工具

```bash
sudo apt update
sudo apt install -y git jq curl build-essential software-properties-common

# Python 3.11（Ubuntu 24.04 自带的是 3.12，SWE-smith 与 harness 都按 3.11 验证过）
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3.11-dev

python3.11 --version     # -> Python 3.11.x
```

> 也可以用 [uv](https://docs.astral.sh/uv/)：`curl -LsSf https://astral.sh/uv/install.sh | sh`
> 然后 `uv python install 3.11`，后面所有 `python3.11 -m venv X` 换成 `uv venv --python 3.11 X`。

### clone 本仓库

```bash
cd ~
git clone https://github.com/Kongqi4U/swesmith-quality-audit.git
cd ~/swesmith-quality-audit && ls
```

---

## 4. SWE-smith 源码安装（钉死版本）

⚠️ **PyPI 上的 `swe-smith` 包是空壳，必须源码装。**

```bash
mkdir -p ~/swesmith-lab && cd ~/swesmith-lab

git clone https://github.com/SWE-bench/SWE-smith
cd SWE-smith
git checkout 9b74ac0                 # 本项目全程钉在这个 commit

python3.11 -m venv venv
source venv/bin/activate
pip install -U pip
pip install -e '.[generate]'

# 这两个必须在 -e 之后再钉一次（-e 会拉最新版）
pip install swebench==4.1.0 fastcore==1.7.29

python -c "import swebench, fastcore; print(swebench.__version__, fastcore.__version__)"
# -> 4.1.0 1.7.29
```

### 打内存限制补丁

```bash
cd ~/swesmith-lab/SWE-smith
git apply ~/swesmith-quality-audit/patches/swesmith-utils-memlimit.patch
git diff --stat
#  swesmith/harness/utils.py | 4 +++-
```

补丁把验证容器的 `mem_limit` 从 `10g` 压到 `600m`（原始环境只有 2GB）。
**你有 16GB，把它放宽到 2g**：

```bash
sed -i 's/mem_limit="600m"/mem_limit="2g"/; s/memswap_limit="600m"/memswap_limit="2g"/' \
    ~/swesmith-lab/SWE-smith/swesmith/harness/utils.py

grep -n 'mem_limit\|memswap_limit\|pids_limit' ~/swesmith-lab/SWE-smith/swesmith/harness/utils.py
#  mem_limit="2g",
#  memswap_limit="2g",
#  pids_limit=256,
```

`pids_limit=256` 保留 —— 它挡的是 fork 炸弹式的候选 bug，和内存大小无关。

> 保留内存硬限的理由：合成出来的 bug 里**真的会有死循环**（原始环境两次死机都是这么来的）。
> 有上限时容器 2 秒内 `exit 137`，没上限时宿主一路进 swap 抖动、内核不 OOM-kill、整机失去响应。

---

## 5. 拉两个验证镜像

串行拉，一个约 1–2GB：

```bash
docker pull swebench/swesmith.x86_64.instagram_1776_monkeytype.70c3acf6
docker pull swebench/swesmith.x86_64.vi3k6i5_1776_flashtext.b316c7e9

docker images | grep swesmith
```

> 镜像名里的 `_1776_` 是 SWE-bench 对 `__` 的转义，不是笔误。

---

## 6. harness 环境（venv 沙箱，不碰 Docker）

harness 的所有路径都从 `SWESMITH_LAB` 读。**先把它写进 shell 配置**：

```bash
echo 'export SWESMITH_LAB=$HOME/swesmith-lab' >> ~/.bashrc
source ~/.bashrc
echo $SWESMITH_LAB          # -> /home/<你>/swesmith-lab
```

### 建干净仓 + venv（两个仓库）

```bash
LAB=$SWESMITH_LAB
H=~/swesmith-quality-audit/harness
mkdir -p $LAB/repos $LAB/sandboxes $LAB/results

# ---- MonkeyType ----
git clone --depth 1 https://github.com/swesmith/Instagram__MonkeyType.70c3acf6 $LAB/repos/clean-monkeytype
python3.11 -m venv $LAB/venv-monkeytype
$LAB/venv-monkeytype/bin/pip install -q "libcst>=0.4.4" mypy_extensions "pytest==7.4.4" tiktoken

# ---- flashtext ----（纯 Python、零第三方依赖，测试目录是 test/ 不是 tests/）
git clone --depth 1 https://github.com/swesmith/vi3k6i5__flashtext.b316c7e9 $LAB/repos/clean-flashtext
python3.11 -m venv $LAB/venv-flashtext
$LAB/venv-flashtext/bin/pip install -q "pytest==7.4.4"
```

### 确认查表已指向本地

```bash
python3 $H/repo_config.py
# clean= 和 venv= 两行都应该是 /home/<你>/swesmith-lab/... 而不是 /root/workspace/...
```

如果还是 `/root/workspace/...`，说明 `SWESMITH_LAB` 没导出，回上面重来。

### 干净态基线

```bash
VENV=$LAB/venv-monkeytype bash $H/run_tests.sh $LAB/repos/clean-monkeytype
# -> 379 passed, 2 skipped, 1 xpassed

VENV=$LAB/venv-flashtext  bash $H/run_tests.sh $LAB/repos/clean-flashtext
# -> 39 passed
```

> ⚠️ 基线缓存 `harness/.env_baseline*.json` **不在仓库里**（那是原始机器的名单）。
> 第一次跑 `eval_patch.py` 会自动重算生成，之后想手动刷新用 `--refresh-baseline`。

### 自测一遍：造沙箱 → 打完美补丁 → 判分应为 `resolved=true`

```bash
LAB=$SWESMITH_LAB
H=~/swesmith-quality-audit/harness
D=~/swesmith-quality-audit/data/task_insts
ID=Instagram__MonkeyType.70c3acf6.func_pm_class_rm_base__n7p6hftj

# ① 造沙箱（隐藏名单落在沙箱外的 <out>.hidden.json）
python3 $H/make_sandbox.py $D/$ID.json $LAB/sandboxes/selftest
#   自检输出里 leaks 必须是 []、n_commits 必须是 1、
#   init_author 必须是 solver <solver@sandbox.local>

# ② 打「完美补丁」= gold patch 的反向（把 bug 改回去）
python3 - <<'PY'
import json, os, subprocess, sys
inst = json.load(open(os.path.expanduser(
    "~/swesmith-quality-audit/data/task_insts/"
    "Instagram__MonkeyType.70c3acf6.func_pm_class_rm_base__n7p6hftj.json")))
sb = os.path.join(os.environ["SWESMITH_LAB"], "sandboxes", "selftest")
p = subprocess.run(["git", "apply", "-R", "-"], cwd=sb,
                   input=inst["patch"], text=True, capture_output=True)
print("apply rc:", p.returncode, p.stderr)
PY

# ③ 判分
python3 $H/eval_patch.py $LAB/sandboxes/selftest $D/$ID.json \
    --out $LAB/results/selftest.json
jq '{resolved, visible_pass, hidden_pass, hack_flag}' $LAB/results/selftest.json
# -> resolved 必须是 true，hack_flag 必须是 false
```

> `eval_patch.py` 会在沙箱里跑 `git add -A`，跑完沙箱 index 是脏的。
> **一个沙箱只判一次分**，判完就删：`rm -rf $LAB/sandboxes/selftest $LAB/sandboxes/selftest.hidden.json`

---

## 7. 本地执行 agent 的要求

老师轨迹（M3/M5）需要一个能**派 sub agent** 的执行端：

- 模型档位：**Opus** 级（冒烟阶段 4 题 3 解就是这个档位的数）。
- 每道题派一个 sub agent 当 solver，提示词模板 = `harness/solver_prompt.md`，
  两个占位符 `{sandbox}` 和 `{lab}` 都要替换：

  ```bash
  sed -e "s#{sandbox}#$SWESMITH_LAB/sandboxes/selftest#g" \
      -e "s#{lab}#$SWESMITH_LAB#g" \
      $H/solver_prompt.md > /tmp/prompt.md
  ```

- **transcript（轨迹）路径**：Claude Code 把每个 sub agent 的对话写在

  ```
  ~/.claude/projects/<项目目录名>/subagents/agent-<id>.jsonl
  ```

  `<项目目录名>` = 你启动 agent 时的工作目录，把 `/` 换成 `-`。
  比如在 `~/swesmith-lab` 里启动，目录名就是 `-home-<你>-swesmith-lab`。找最新一条：

  ```bash
  ls -t ~/.claude/projects/*/subagents/agent-*.jsonl | head -3
  ```

- 轨迹转训练格式 + loss-token 比例（用带 tiktoken 的那个 venv 跑）：

  ```bash
  $SWESMITH_LAB/venv-monkeytype/bin/python $H/convert_transcript.py \
      <上面那个 agent-*.jsonl> /tmp/traj.jsonl \
      --task-md $SWESMITH_LAB/sandboxes/selftest/TASK.md \
      --metrics /tmp/traj_meta.json
  ```

- 越界审计：

  ```bash
  python3 $H/audit_transcript.py <agent-*.jsonl> \
      --sandbox $SWESMITH_LAB/sandboxes/selftest --out /tmp/audit.json
  ```

- 产物落盘后洗一次 PII（默认 dry-run，看清单没问题再 `--apply`）：

  ```bash
  python3 $H/scrub_pii.py $SWESMITH_LAB/results/
  python3 $H/scrub_pii.py $SWESMITH_LAB/results/ --apply
  ```

> 换别的执行 agent 也行，硬要求只有两条：
> ① 能把 solver 关在沙箱目录里（提示词约束 + 事后 `audit_transcript.py` 兜底）；
> ② 能拿到结构化的对话轨迹 JSONL（否则 `convert_transcript.py` 没输入）。

---

## 8. 验证清单（8 条，全过才算环境就绪）

一条一条敲，每条都要看到 ✅ 那行描述的结果：

```bash
# ✅ 1  WSL2 + 内存上限
free -g | awk '/Mem:/{print "mem_total_GB="$2}'          # 期望 11–12

# ✅ 2  Docker 通
docker run --rm hello-world | grep -q "Hello from Docker" && echo OK-docker

# ✅ 3  Python 3.11
python3.11 --version                                      # Python 3.11.x

# ✅ 4  SWE-smith 版本钉死
cd ~/swesmith-lab/SWE-smith && git rev-parse --short HEAD  # 9b74ac0
./venv/bin/python -c "import swebench,fastcore;print(swebench.__version__,fastcore.__version__)"
                                                          # 4.1.0 1.7.29

# ✅ 5  内存补丁已打
grep -c 'pids_limit=256' ~/swesmith-lab/SWE-smith/swesmith/harness/utils.py   # 1

# ✅ 6  两个镜像都在
docker images --format '{{.Repository}}' | grep -c swesmith                   # 2

# ✅ 7  两个仓的干净态基线对得上
VENV=$SWESMITH_LAB/venv-monkeytype bash ~/swesmith-quality-audit/harness/run_tests.sh \
     $SWESMITH_LAB/repos/clean-monkeytype | tail -1     # 379 passed, 2 skipped, 1 xpassed
VENV=$SWESMITH_LAB/venv-flashtext  bash ~/swesmith-quality-audit/harness/run_tests.sh \
     $SWESMITH_LAB/repos/clean-flashtext  | tail -1     # 39 passed

# ✅ 8  harness 查表指向本地（不含 /root/workspace）
python3 ~/swesmith-quality-audit/harness/repo_config.py | grep -c '/root/workspace'   # 0
```

第 6 步的「完美补丁 → `resolved=true`」自测通过，就可以开 M2 了。

---

## 附：出问题时先看这里

| 症状 | 多半是 |
|---|---|
| `repo_config.py` 打出来还是 `/root/workspace/...` | `SWESMITH_LAB` 没 export（新开的 shell 要 `source ~/.bashrc`） |
| `run_tests.sh` 报 `No module named pytest` | `VENV` 指错了，或者那个 venv 没装 `pytest==7.4.4` |
| MonkeyType 基线是 378 passed / 1 failed | pytest 版本不是 7.4.4（`test_excludes_site_packages` 在 pytest 9 上挂） |
| `docker` 在 Ubuntu 里找不到 | Docker Desktop 的 WSL Integration 没给 `Ubuntu-24.04` 打开 |
| 验证阶段 WSL 卡死 | 内存补丁没打，或者 `.wslconfig` 的 `memory=` 没生效（要 `wsl --shutdown`） |
| `pip install -e '.[generate]'` 装完 swebench 是 5.x | 忘了后面那句 `pip install swebench==4.1.0 fastcore==1.7.29` |
