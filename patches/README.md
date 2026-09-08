# patches/

## `swesmith-utils-memlimit.patch`

作用于 SWE-smith 源码树 `swesmith/harness/utils.py`（`run_patch_in_container`）。

**为什么要打**：SWE-smith 官方给验证容器的 `mem_limit="10g"`。原始环境是一台 **2GB 内存的 VPS**，
一旦某个候选 bug 造出死循环（M1 阶段 flashtext 的 `ctrl_shuffle__lhg4dfim`、`op_change__habdq6v6`
就是），容器会一路吃到宿主 swap 抖动、内核不触发 OOM-kill，整机失去响应（0907/0908 两次死机）。
把上限压到 600m 并禁 swap 后，失控容器 2 秒内 `exit 137`，宿主 swap 仅 +70MB。

**本机 16GB 怎么调**：把补丁里的 `600m` 改成 `2g`（`mem_limit` 与 `memswap_limit` 两处都改），
`pids_limit=256` 保留。改法见 `docs/SETUP-WSL2.md` 第 4 步。

## 版本钉死（原始环境实测通过的组合）

| 项 | 值 | 说明 |
|---|---|---|
| SWE-smith commit | `9b74ac0` | "Add PHP language support (#233)"；本补丁按这个 commit 的行号生成 |
| `swebench` | `4.1.0` | 5.x 与 SWE-smith 的 harness 接口不兼容 |
| `fastcore` | `1.7.29` | 1.8+ 改了 `patch` 装饰器行为 |
| `pytest` | `7.4.4` | harness 侧 venv 用；pytest 9 把 `pytest.skip` 改成对象，MonkeyType 的 `test_excludes_site_packages` 会挂 |
| Python | 3.11 | SWE-smith profile 写的是 3.10，原始环境只有 3.11；测试结果与容器逐字一致，但这是一处已知环境偏差 |

PyPI 上的 `swe-smith` 包是空壳，**必须源码安装**（`pip install -e '.[generate]'`）。

## 打法

```bash
cd ~/swesmith-lab/SWE-smith
git apply ~/swesmith-quality-audit/patches/swesmith-utils-memlimit.patch
git diff --stat        # 应为 swesmith/harness/utils.py | 4 +++-
```
