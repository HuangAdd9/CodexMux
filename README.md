# CodexMux

轻量级 Codex CLI 多账号隔离与会话同步封装（Linux）。  
A lightweight Linux wrapper for Codex CLI account isolation and session synchronization.

> [!IMPORTANT]
> **支持范围 / Scope**
> - **当前仅支持 Linux**（依赖 `/proc/locks`、Unix socket、`SO_PEERCRED`）。
> - 需要你**单独安装 Codex CLI**（可执行名 `codex`）。
> - CodexMux **不提供模型访问**、**不配置代理**、**不替代 Codex 身份验证**。
> - macOS、原生 Windows 当前不支持；WSL 未验证。
>
> **Linux-only snapshot.** You must install Codex CLI separately. CodexMux does not provide model access, proxy setup, or authentication replacement. macOS and native Windows are unsupported in this snapshot; WSL is unverified.

## 目录 / Table of Contents

- [1. 项目功能概览 / Feature Overview](#1-项目功能概览--feature-overview)
- [2. 仓库结构与脚本职责 / Layout and Script Roles](#2-仓库结构与脚本职责--layout-and-script-roles)
- [3. 安装前提 / Prerequisites](#3-安装前提--prerequisites)
- [4. 安装方式（非 Python 包）/ Installation (Not a Python Package)](#4-安装方式非-python-包-installation-not-a-python-package)
- [5. 快速开始 / Quick Start](#5-快速开始--quick-start)
- [6. 创建账号 vs 登录账号 / Create Account vs Login](#6-创建账号-vs-登录账号--create-account-vs-login)
- [7. 数据目录与安全提示 / Data Directories and Safety Notes](#7-数据目录与安全提示--data-directories-and-safety-notes)
- [8. 按 SESSION_ID 恢复会话 / Resume by SESSION_ID](#8-按-session_id-恢复会话--resume-by-session_id)
- [9. 可选：启用普通 `codex` 路由 / Optional Plain `codex` Routing](#9-可选启用普通-codex-路由--optional-plain-codex-routing)
- [10. 环境变量配置 / Environment Variables](#10-环境变量配置--environment-variables)
- [11. 安全边界 / Safety Boundaries](#11-安全边界--safety-boundaries)
- [12. 测试 / Tests](#12-测试--tests)
- [13. 常见问题与故障排查 / Troubleshooting](#13-常见问题与故障排查--troubleshooting)
- [14. 卸载与数据清理 / Uninstall and Data Cleanup](#14-卸载与数据清理--uninstall-and-data-cleanup)
- [15. 许可证 / License](#15-许可证--license)

## 1. 项目功能概览 / Feature Overview

### 中文
- 创建独立账号目录（`CODEX_HOME` 隔离），但不自动登录。
- 支持同账号多会话并发、不同账号并发。
- 支持显式 UUID 的 `resume` / `fork` 跨目录查找与导入。
- 会导入所需 `history_base` 祖先链，避免缺失父历史。
- 检测历史分叉（divergent history）并保守失败，不自动合并。
- 仅在同机协作 wrapper 间进行锁协调；不提供跨主机分布式锁。

### English
- Creates isolated account homes (`CODEX_HOME`) without auto-login.
- Supports concurrent sessions across different accounts or within one account.
- Supports explicit-UUID `resume` / `fork` synchronization across local homes.
- Imports required `history_base` lineage for safe resume/fork.
- Fails closed on divergent history; does not auto-merge branches.
- Coordination locks are local to the machine, not distributed across hosts.

## 2. 仓库结构与脚本职责 / Layout and Script Roles

```text
bin/codex-account       账号入口：创建账号、列账号、在账号 CODEX_HOME 下启动 codex
bin/codex-session-sync  会话同步器：显式 UUID 同步、lineage 校验、锁与保守失败策略
bin/codex               可选路由器：让普通 codex resume/fork 也走同步逻辑
tests/                  回归测试与 mock
```

- `bin/codex-account` 常用形式：
  - `codex-account --add <account>`
  - `codex-account --list`
  - `codex-account <account> [codex arguments...]`
- `bin/codex-session-sync` 由 wrapper 调用（通常不需要手动调用），核心参数：
  - `--lock-home`
  - `--log-prefix`
  - `--session-action {resume|fork}`
- `bin/codex` 是可选组件；不启用也不影响 `codex-account` 主流程。

## 3. 安装前提 / Prerequisites

### 中文
必须具备：
- Linux
- `bash`
- `python3`（3.10+）
- `codex`（单独安装）
- `flock`（util-linux）

建议先检查：

```bash
python3 --version
codex --version
flock --version
```

### English
Required:
- Linux
- `bash`
- `python3` (3.10+)
- `codex` (installed separately)
- `flock` (util-linux)

Sanity checks:

```bash
python3 --version
codex --version
flock --version
```

## 4. 安装方式（非 Python 包）/ Installation (Not a Python Package)

### 中文
这不是 `pip install` 的 Python 包。推荐方式是 clone 后直接运行 `bin/` 脚本：

```bash
git clone https://github.com/HuangAdd9/CodexMux.git
cd CodexMux
```

若执行权限丢失（例如压缩包拷贝后）：

```bash
chmod +x bin/codex bin/codex-account bin/codex-session-sync
```

### English
This is **not** a Python package install flow. Clone and run scripts directly from `bin/`:

```bash
git clone https://github.com/HuangAdd9/CodexMux.git
cd CodexMux
```

If executable bits are missing:

```bash
chmod +x bin/codex bin/codex-account bin/codex-session-sync
```

## 5. 快速开始 / Quick Start

### 中文（可复制执行）

```bash
# 1) 在当前仓库中指定同步器路径
export CODEX_SESSION_SYNC_BIN="$PWD/bin/codex-session-sync"

# 2) 创建隔离账号目录（不会自动登录）
./bin/codex-account --add personal

# 3) 触发登录（示例：设备码登录）
./bin/codex-account personal login --device-auth

# 4) 查看登录状态
./bin/codex-account personal login status

# 5) 启动该账号下的 Codex
./bin/codex-account personal
```

### English (copy/paste)

```bash
# 1) Point to the sync helper in this repo
export CODEX_SESSION_SYNC_BIN="$PWD/bin/codex-session-sync"

# 2) Create an isolated account directory (no login yet)
./bin/codex-account --add personal

# 3) Log in (example: device auth)
./bin/codex-account personal login --device-auth

# 4) Check login status
./bin/codex-account personal login status

# 5) Start Codex in that account home
./bin/codex-account personal
```

## 6. 创建账号 vs 登录账号 / Create Account vs Login

### 中文
- `--add` 只创建目录：`~/.codex-accounts/<account>`。
- 登录是独立动作，需要显式执行 `login ...`。
- `--list` 只列出检测到 `auth.json` 的账号，不代表在线校验。

### English
- `--add` only creates `~/.codex-accounts/<account>`.
- Login is separate and explicit (`login ...`).
- `--list` lists accounts with `auth.json`; it is not a live auth check.

## 7. 数据目录与安全提示 / Data Directories and Safety Notes

默认目录（可由环境变量覆盖）：

```text
~/.codex-accounts              # 隔离账号目录根
~/.codex                       # 普通 Codex 共享主目录（历史搜索源）
~/.cache/codex-account/locks   # 本机 wrapper 协调锁目录
```

- 请勿误删 `~/.codex`，除非你明确要删除普通 Codex CLI 的数据。
- CodexMux 只隔离 Codex 状态目录，不提供 OS 级权限隔离。

## 8. 按 SESSION_ID 恢复会话 / Resume by SESSION_ID

### 中文
使用显式 UUID：

```bash
export CODEX_SESSION_SYNC_BIN="$PWD/bin/codex-session-sync"
./bin/codex-account --list
./bin/codex-account personal resume SESSION_ID
```

将 `SESSION_ID` 替换为你的真实 UUID（例如 `11111111-1111-4111-8111-111111111111`）。

行为说明：
- wrapper 会在 `~/.codex` 与各账号 home 中搜索兼容 rollout。
- 会按 `history_base` 导入所需祖先链（lineage）。
- 若发现历史分叉（不是前缀关系），会保守失败并拒绝自动合并。

### English
Use an explicit UUID:

```bash
export CODEX_SESSION_SYNC_BIN="$PWD/bin/codex-session-sync"
./bin/codex-account --list
./bin/codex-account personal resume SESSION_ID
```

Replace `SESSION_ID` with your real UUID (for example `11111111-1111-4111-8111-111111111111`).

Behavior:
- Searches `~/.codex` plus account homes for compatible rollouts.
- Imports required `history_base` lineage.
- Fails closed on divergence (non-prefix histories); no auto-merge.

## 9. 可选：启用普通 `codex` 路由 / Optional Plain `codex` Routing

`bin/codex` 是可选路由器，用于让普通 `codex resume/fork <UUID>` 也走同步逻辑。

**安全示例：请先在 subshell 测试，不污染当前 shell。**

```bash
(
  export CODEX_REAL_BIN="$(command -v codex)"
  export CODEX_SESSION_SYNC_BIN="$PWD/bin/codex-session-sync"
  export PATH="$PWD/bin:$PATH"
  codex resume SESSION_ID
)
```

关键限制：
- `CODEX_REAL_BIN` 必须指向真实 Codex 可执行文件（或官方 launcher）。
- **不要**把 `CODEX_REAL_BIN` 指向另一个路由 wrapper，避免递归/错误链路。
- 退出 subshell 后，`PATH` 自动恢复。

## 10. 环境变量配置 / Environment Variables

| 变量 / Variable | 默认值 / Default | 用途 / Purpose |
| --- | --- | --- |
| `CODEX_SHARED_HOME` | `~/.codex` | 共享历史搜索 home |
| `CODEX_ACCOUNTS_HOME` | `~/.codex-accounts` | 账号 home 根目录 |
| `CODEX_ACCOUNT_LOCK_HOME` | `~/.cache/codex-account/locks` | 本机协调锁目录 |
| `CODEX_SESSION_SYNC_BIN` | `~/bin/codex-session-sync` | 会话同步脚本路径 |
| `CODEX_REAL_BIN` | auto detect | `bin/codex` 路由时指定真实 codex |

## 11. 安全边界 / Safety Boundaries

- 不自动合并分叉历史；冲突时失败并提示人工备份与选择。
- 不盲删锁；遇到 active writer 要先确认任务状态。
- 不会为了切换会话去杀用户任务。
- 协调范围是本机，不是跨主机分布式锁。
- provider 覆盖只在支持路径内校验；失败时拒绝继续，避免静默错配。

更多安全与隐私注意事项见 [`SECURITY.md`](SECURITY.md)。

## 12. 测试 / Tests

```bash
bash -n bin/codex bin/codex-account
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py' -q
```

测试使用本地临时目录与 mock 服务，不依赖真实账号或模型访问。

## 13. 常见问题与故障排查 / Troubleshooting

### 1) 找不到 `codex`
- 检查：`command -v codex`
- 先安装 Codex CLI，并确保当前 shell 可找到该命令。

### 2) 脚本无执行权限 / Permission denied
- 运行：`chmod +x bin/codex bin/codex-account bin/codex-session-sync`

### 3) 登录状态不确定
- 运行：`./bin/codex-account <account> login status`
- 若未登录，执行：`./bin/codex-account <account> login --device-auth`

### 4) 找不到 SESSION_ID
- 先尝试：`./bin/codex-account --list`
- 确认 UUID 格式：`8-4-4-4-12` 的十六进制字符串。
- 非显式 UUID 的 picker 只能看到当前 home 的可见会话，不等于全量历史。

### 5) 历史冲突 / divergent history
- 表示多个副本不是前缀关系，工具会拒绝自动合并。
- 先备份两支历史，再人工确定保留分支。

### 6) 锁冲突 / active writer
- 可能有本地 app-server 或其它 wrapper 正在写入同一会话。
- 不要直接删锁文件；先确认相关任务/进程已停止。

### 7) provider 验证失败
- 可能是会话处于活动状态，无法在当前时机切换 provider。
- 按错误提示先结束/停止当前 turn，再重试。

### 8) 如何恢复原始 PATH（使用了 `bin/codex` 路由后）
- 推荐始终在 subshell 中测试路由；退出 subshell 自动恢复。
- 如果你在当前 shell 手动改了 PATH，移除仓库 `bin` 前缀即可。

## 14. 卸载与数据清理 / Uninstall and Data Cleanup

### 中文
CodexMux 无系统级安装。删除仓库即可移除脚本：

```bash
cd ..
rm -rf CodexMux
```

如需清理隔离账号与锁：

```bash
rm -rf ~/.codex-accounts
rm -rf ~/.cache/codex-account
```

⚠️ `~/.codex` 是普通 Codex 数据目录，不要误删。

### English
CodexMux has no system-wide install. Remove the cloned repository to remove scripts:

```bash
cd ..
rm -rf CodexMux
```

To remove isolated account data and lock cache:

```bash
rm -rf ~/.codex-accounts
rm -rf ~/.cache/codex-account
```

⚠️ `~/.codex` is normal Codex CLI data. Do not delete it unintentionally.

## 15. 许可证 / License

Apache License 2.0. See [`LICENSE`](LICENSE).
