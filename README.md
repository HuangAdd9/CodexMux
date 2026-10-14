# CodexMux

给 Codex CLI 增加多账号管理。主账号和其他账号共用 Codex 程序，各自保存登录态和会话。

## 安装

目前支持 Linux。需要 Git、Bash、Python 3.10+ 和 `flock`；通过 npm 安装 Codex 时还需要 Node.js 和 npm。

### 1. 安装官方 Codex CLI

已经安装的可以跳过：

```bash
npm install -g @openai/codex
codex --version
```

### 2. 下载并安装 CodexMux

```bash
git clone https://github.com/HuangAdd9/CodexMux.git
cd CodexMux
mkdir -p "$HOME/bin"
install -m 755 bin/codex bin/codex-account bin/codex-session-sync bin/codex-account-limits "$HOME/bin/"
export PATH="$HOME/bin:$PATH"
hash -r
codex --version
codex-account --help
```

这会把四个 wrapper 文件装到 `~/bin`，官方 Codex 程序仍保留在原安装位置。

使用 Bash 时，把下面这一行加入 `~/.bashrc`，保证新终端也能找到 wrapper。只需添加一次，并放在其他 PATH 设置之后：

```bash
export PATH="$HOME/bin:$PATH"
```

添加后执行 `source ~/.bashrc`，或重新打开终端。

## 创建和登录账号

以下用 `work` 作为账号名，你可以换成自己的名字。账号名允许字母、数字、点、下划线和连字符。

```bash
codex-account --add work
codex-account work login
codex-account work login status
```

第一条只创建目录，不会登录或复制其他账号的登录态。第二条按终端提示在浏览器完成登录，第三条检查登录状态。

- 主账号：使用 `codex`，数据放在 `~/.codex`。
- 其他账号：使用 `codex-account 账号名`，数据放在 `~/.codex-accounts/账号名`。

主账号登录可以执行 `codex login`。

## 命令速查

| 命令                                                     | 用途                                          |
| -------------------------------------------------------- | --------------------------------------------- |
| `codex-account --help`                                 | 显示帮助                                      |
| `codex-account --add work`                             | 新建账号目录，不登录                          |
| `codex-account --list`                                 | 列出有登录文件的账号，不实时核验登录是否有效  |
| `codex-account --lslimit`                              | 查询所有账号的额度、重置时间和可用重置次数      |
| `codex-account work login`                             | 登录或重新登录 work                           |
| `codex-account work login status`                      | 检查 work 的登录状态                          |
| `codex-account work logout`                            | 退出 work 的登录，保留账号目录                |
| `codex-account work`                                   | 用 work 启动交互会话                          |
| `codex-account work resume SESSION_ID`                 | 用 work 继续指定会话                          |
| `codex-account work fork SESSION_ID`                   | 从指定会话创建新分支                          |
| `codex-account work exec "任务内容"`                   | 非交互执行任务                                |
| `codex-account work exec resume SESSION_ID "继续任务"` | 非交互继续指定会话                            |
| `codex-account work --version`                         | 查看 work 实际使用的 Codex 版本               |
| `codex-account work update`                            | 更新共享 Codex 程序，所有账号下次启动共用新版 |

`SESSION_ID` 替换成真实的会话 UUID，不要直接输入这个占位符。

`--lslimit` 显示额度使用比例、剩余比例、重置时间和可用重置次数（`RESETS`）；时间使用东八区 `Asia/Shanghai`。`RESETS` 为账号级次数，不是各窗口分别拥有的次数；`0` 表示没有可用次数，`-` 表示接口未提供有效数据。账号显示 `need login again` 时，重新执行该账号的登录命令。

在交互会话内可以输入 `/status` 查看状态，输入 `/exit` 退出。

## 切换账号继续会话

例如先用 work 创建会话，之后改用 personal：

```bash
codex-account work
codex-account --add personal
codex-account personal login
codex-account personal resume SESSION_ID
```

先退出 work 的目标会话，再执行最后一条命令。显式指定会话 ID 时，wrapper 会搜索主账号和所有账号目录，导入兼容的历史。

也可以用主账号继续：

```bash
codex resume SESSION_ID
```

不带 ID 的 `resume` 选择器只显示当前账号目录中的会话。历史导入发生在指定 ID 的操作时，不是每条消息实时同步；遇到 `divergent copies` 表示不能自动确定兼容历史，需要先检查并备份各份记录，再选择保留的分支。

同一账号可以并发运行不同会话。同一会话在当前机器上被其他 wrapper 或原生进程占用时，不能再启动另一个写入者。

## 模型和 provider

账号名后面可以继续传官方 Codex 参数：

```bash
codex-account work -m MODEL_NAME
codex-account work resume SESSION_ID -c 'model_reasoning_effort="high"'
codex resume SESSION_ID -c 'model_provider="openai"'
```

`MODEL_NAME` 替换成要使用的模型。`codex-account` 默认使用 `openai` provider；切换 provider 不会切换账号。自定义 provider 需要在对应账号的 `config.toml` 中配置。

## 升级

所有账号共用程序，执行一次即可；需要支持 `update` 命令的 Codex CLI：

```bash
codex update
```

也可以执行 `codex-account work update`，它同样更新主安装目录。升级后重开会话，再检查版本：

```bash
hash -r
codex --version
codex-account work --version
```

更新 CodexMux 自身则在仓库目录运行：

```bash
git pull --ff-only
install -m 755 bin/codex bin/codex-account bin/codex-session-sync bin/codex-account-limits "$HOME/bin/"
```

如果 Codex 的安装器重新设置了 `~/.local/bin/codex`，确认 `~/bin` 仍排在 PATH 最前面。

许可证见 [LICENSE](LICENSE)。
