# Chat + 本地 MCP 方案调研

核查日期：2026-09-15。输入材料：仓库根目录的 `Chat用法.md`。三组子代理分别研究 WebCodex、DevSpace、codex-with-chatgpt 与 Mac Developer Bridge；主代理核对 OpenAI 文档并综合判断。

边界：本次是文档、发布记录和关键源码审查，未安装这些项目，未使用账号凭证或 Tunnel key，未执行真实 ChatGPT MCP 调用，也未进行长期稳定性压测。下文的选型是工程判断，不是实测排名。没有修改生产 wrapper。

## 结论

目标若是“在 ChatGPT 网页的 Chat 中直接修改 Linux 上的代码、执行命令，并尽量省去自行拼接隧道的工作”，优先隔离试用 **WebCodex 常规 Server + Runner + Secure Tunnel**，不是 Mac Desktop 安装路线。

目标若是“少量工具、短任务、愿意自己维护 Node/OAuth/隧道集成”，DevSpace 是备选。只把规划和复查交给 Chat、执行仍保留 Codex，可以考虑 codex-with-chatgpt。Mac Developer Bridge 不适合作为现有 Linux 多账号主机的首选。

不能直接宣布某个方案“最稳”。至少需在目标网络下验证工具调用、鉴权刷新、响应丢失和不同进程重启的行为，再决定是否长期使用。

## 先纠正文中的几个前提

1. **不是 Codex Cloud，也不是把 Codex CLI 界面搬进浏览器。** Chat 模型通过 MCP 调用另一套本地执行工具；不会自动继承我们的 `codex-account` 登录选择、UUID 锁、分页历史、权限配置或恢复语义。
2. **官方确实支持 Secure MCP Tunnel。** 客户端从私网主动发出 HTTPS 请求，再转交给 stdio/HTTP MCP；不需要给 MCP 直接开放公网入口。需要正确的组织/workspace 关联及 Tunnel 权限。Tunnel runtime key 用于隧道认证；模型调用仍遵循所用产品的计量规则。[官方隧道文档](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
3. **“无限 token”不能成立为采购或生产承诺。** 官方明确区分 Chat 与 Work/Codex 的用量；Thinking 有按套餐变化的限额和回退行为，文本聊天不限量的表述也不能扩大成所有模型、推理等级和工具调用无限。[Chat 用量](https://help.openai.com/en/articles/20001354-gpt-56-in-chatgpt)、[Work/Codex 共用额度](https://learn.chatgpt.com/docs/pricing)
4. **Chat 版 Sol 不能仅凭名字视为 Codex 版的等价替代。** OpenAI 说明其日常 Chat 优化版本只用于 Chat，Work/Codex 版本不随该更新改变。接上工具不代表获得同样的执行控制和长任务保障；本次没有做模型能力对照实验。[官方更新说明](https://openai.com/index/improving-gpt-5-6-sol-in-chatgpt/)
5. **套餐权限需实际核对。** 开发文档列出 Plus/Pro 等可用完整读写 MCP，但另一篇帮助文档仍将完整 MCP 限于组织套餐，两者存在表述冲突。不能凭文章保证每个个人账号均已开放；以目标账号能否启用 Developer mode、发现工具及完成确认后的写操作为验收点。[开发文档](https://developers.openai.com/api/docs/guides/developer-mode)、[帮助文档](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt)
6. **本地进程继续运行，不等于 Chat 会一直自主推理。** 官方 `/goal` 入口及 Web Work 长任务是独立的产品机制，不能由 MCP 的后台进程能力推导出来。[长任务说明](https://learn.chatgpt.com/docs/long-running-work)

## 项目与版本

| 项目 | 核查版本 | 适合的角色 | 主要保留意见 |
| --- | --- | --- | --- |
| [WebCodex](https://github.com/yyjeqhc/webcodex) | 正式版 v0.4.1，发布于 09-10 | Linux 多项目、网页直接执行、集成官方 Tunnel | 组件较多，默认执行权限较宽；恢复能力有生命周期限制 |
| [DevSpace](https://github.com/Waishnav/devspace) | 稳定 1.0.8；重点源码为 1.1.0-beta.3 | 简洁工具集、Linux 短任务 | OAuth/隧道需要整合；普通进程会话不持久化 |
| [codex-with-chatgpt](https://github.com/XiaoDuoYa/codex-with-chatgpt) | 稳定 v0.1.3；源码 9663b887 | Chat 规划与复查、Codex 执行 | 不消除 Codex 用量；完整自动化依赖浏览器协作 |
| [Mac Developer Bridge](https://github.com/alexanderradahl/mac-developer-bridge) | 稳定 v0.2.0；源码 fea70d1a | Mac 整机工具桥 | 非完整 Linux 产品，用户级权限过宽 |

这些都是社区项目；版本号、功能数或星标数不等于长期稳定性认证。

## WebCodex：首选试验对象

- 正式包包含 Linux x64/arm64，常规 Server、Runner、CLI 不要求桌面。正式版集成了 Linux tunnel-client 下载与校验，核查版本固定使用 0.0.12；不能假设与官方最新客户端完全等价。[部署](https://github.com/yyjeqhc/webcodex/blob/v0.4.1/docs/DEPLOYMENT.md)、[Tunnel 实现](https://github.com/yyjeqhc/webcodex/blob/v0.4.1/src/project_entry_openai_tunnel.rs)
- 网络断开或 Server 重启时，仍活着的同一个 Runner 可重新上报任务；Runner 重启后普通 job 不能无缝接管。显式 detached process 有独立 supervisor 和磁盘状态，恢复仍要求 supervisor 存活，并不跨机器重启保证续跑。[Runner 契约](https://github.com/yyjeqhc/webcodex/blob/v0.4.1/docs/RUNNER.md)、[detached 实现](https://github.com/yyjeqhc/webcodex/blob/v0.4.1/crates/webcodex-runner/src/webcodex_runner/detached_job.rs)
- 常规 Server 的集成 Tunnel 路径注入 bootstrap Bearer，该身份的 scope 判断直接放行。因此网页端选择 No Auth 不代表后端匿名，更不代表每个网页账号有独立最小权限。[凭证注入](https://github.com/yyjeqhc/webcodex/blob/v0.4.1/src/project_entry_regular_tunnel.rs)、[scope 逻辑](https://github.com/yyjeqhc/webcodex/blob/v0.4.1/src/auth/context.rs)
- 默认 `trusted_agent` 并非逐命令人工审批；`restricted` 会拒绝相关执行工具。环境变量隔离不是文件系统沙箱。[权限策略](https://github.com/yyjeqhc/webcodex/blob/v0.4.1/src/tool_runtime/permissions/policy.rs)、[进程启动](https://github.com/yyjeqhc/webcodex/blob/v0.4.1/crates/webcodex-process/src/unix.rs)
- 有发布及 CI，但安全策略页仍存在旧支持版本信息，需按实际 tag 审核，不能把 main 的变更当成正式版能力。[v0.4.1](https://github.com/yyjeqhc/webcodex/releases/tag/v0.4.1)、[安全策略快照](https://github.com/yyjeqhc/webcodex/blob/e11cb3e4c96b8b4fa9f84ca59fa072ca0bb0b2ae/SECURITY.md)

判断：完整的官方 Tunnel 集成与较细的任务恢复机制，使其更适合作为本次常驻方案的第一试验对象；不是承诺它更少崩溃。

## DevSpace：轻量备选，但别忽略集成成本

- 是 `Waishnav/devspace`，不是同名 Kubernetes 工具。Node HTTP 服务支持 headless；核查 beta 要求 Node `>=22.19 <27`，含 SQLite 原生依赖和可选 PTY。当前会话默认 Node 为 20.20.2，不满足该要求；若试用应独立配置运行时，不直接改全机默认 Node。[依赖](https://github.com/Waishnav/devspace/blob/v1.1.0-beta.3/package.json)
- 六个核心工具是真实的，但少量工具不等于低权限；普通 `exec_command` 使用宿主进程环境和权限。默认 cwd 检查不是操作系统沙箱。[执行实现](https://github.com/Waishnav/devspace/blob/v1.1.0-beta.3/src/process-sessions.ts)
- 可以接官方 Tunnel，不必天然依赖公网反代。但 `/mcp` 有 OAuth，授权页面可达性、resource URL 与卡片静态资源都要处理。resource 别名支持进入 beta.2，不能套用于稳定 1.0.8。[PR #298](https://github.com/Waishnav/devspace/pull/298)、[服务端](https://github.com/Waishnav/devspace/blob/v1.1.0-beta.3/src/server.ts)
- 上游有通过本地认证代理配合 Tunnel 的成功报告，但这是额外集成，不是我们实测，更不能把代理持有的 Owner 权限当成每用户隔离。[上游报告](https://github.com/Waishnav/devspace/issues/182#issuecomment-5326258733)
- 普通进程句柄保存在内存，服务重启不能恢复；响应丢失后可能已经执行却丢了句柄，盲目重试有重复副作用。上游仍有对应的恢复问题与改进讨论；需核对最终合入版本。[问题 #334](https://github.com/Waishnav/devspace/issues/334)
- Worktree 可以分开代码，但不是账号权限隔离。核查 beta 有过期 worktree 清理及恢复逻辑；不要把被 Git 忽略的实验产物当成有恢复保证的数据。[worktree 管理](https://github.com/Waishnav/devspace/blob/v1.1.0-beta.3/src/git-worktrees.ts)

判断：适合短任务；若目标是省掉隧道/OAuth运维和稳妥保留长进程，它不是明显优于 WebCodex 的选择。

## 另外两个方案

### codex-with-chatgpt

对外 MCP 确实是九个只读工具。测试状态工具读取上报记录，不独立重跑测试，因此不能把其复查当成独立执行验证。[工具实现](https://github.com/XiaoDuoYa/codex-with-chatgpt/blob/9663b88753e35c76796c5bce000293e0bd22cd9e/src/mcp/server.ts)

Codex 仍实施任务，Skill 还包含通过 `iab` 浏览器与 ChatGPT 协作的流程；所以不是完全替代 Codex，也不是零 Codex 用量。服务端 Linux 路径支持不等于整个浏览器闭环在 headless 主机开箱即用。[Skill](https://github.com/XiaoDuoYa/codex-with-chatgpt/blob/9663b88753e35c76796c5bce000293e0bd22cd9e/skill/SKILL.md)

有 workspace 绑定和 OAuth，但状态不默认跟随 `CODEX_HOME` 分离，敏感文件规则也不全面覆盖 Codex 认证目录。若试用，独立配置 `C2C_STATE_DIR`，只开放无凭证源码目录，先单账号单任务。[状态存储](https://github.com/XiaoDuoYa/codex-with-chatgpt/blob/9663b88753e35c76796c5bce000293e0bd22cd9e/src/session/state.ts)、[拒绝清单](https://github.com/XiaoDuoYa/codex-with-chatgpt/blob/9663b88753e35c76796c5bce000293e0bd22cd9e/src/workspace/ignore.ts)

### Mac Developer Bridge

安装器面向 Darwin，依赖 macOS 运维机制；部分核心 Node 服务有 Linux 回退，但桌面、浏览器、PTY 和安装链不能认定完整支持 Linux。[安装器](https://github.com/alexanderradahl/mac-developer-bridge/blob/fea70d1a3c5524164f2159f6063ba685fef91324/install.sh)

普通 MCP 执行功能不需要 Codex 推理，但具备当前系统用户的 Shell/文件权限。当前项目另含实验性的浏览器模型转接路径，文章“本身不调用模型”只能限定到普通执行工具，不能概括所有功能。[安全说明](https://github.com/alexanderradahl/mac-developer-bridge/blob/fea70d1a3c5524164f2159f6063ba685fef91324/SECURITY.md)、[HTTP 路由](https://github.com/alexanderradahl/mac-developer-bridge/blob/fea70d1a3c5524164f2159f6063ba685fef91324/mcp-http.mjs)

判断：不纳入当前 Linux 常驻方案首轮试验。

## 对现有多账号环境的底线

以下是基于执行代码的安全推论，并未实际尝试读取敏感目录：若 MCP Runner 与日常 Codex 使用同一 Unix 用户，且 Shell 没有 OS 级隔离，就可能访问该用户的 `~/.codex`、`~/.codex-accounts`、SSH 文件和环境秘密。Tunnel、OAuth、workspace roots、worktree 都不能单独解决这个问题。

建议专用低权限 OS 用户或隔离容器/VM，只挂载测试仓库；不挂载真实账号目录、SSH agent socket、Docker socket或整个 HOME。只把 Server 容器化、Runner 留在原用户下，不满足这个隔离要求。避免两个 Agent 同时修改同一 checkout；即使我们的 session 锁正常，也不协调 MCP 文件写入。

## 建议的首轮验收，不自动执行

1. 在目标网页账号确认 Developer mode、Tunnel 关联和所需工具权限；先用官方 stub 或无副作用的只读工具打通链路。[官方客户端](https://github.com/openai/tunnel-client)
2. 专用隔离环境内固定 WebCodex 正式 tag，启动常规 Server、Runner 与 Tunnel；不申请整机文件访问。
3. 用无秘密的小测试仓库，验证读取、修改一个文件、执行测试、显示 diff；逐步确认工具结果与本地文件一致。
4. 人为断开网络、重启 Server、重启 Runner，分别记录普通任务与 detached 任务的结果、句柄和日志，不混淆三个故障场景。
5. 测试一次“命令已启动但响应丢失”的恢复流程，确认不会盲目重复执行写操作。
6. 使用合成的不可访问哨兵文件验证 OS 权限边界，不用真实认证文件做测试。
7. 开两个独立 worktree，检查不会串目录、串状态；保持生产账号和生产任务不变。
8. 对同类短编码任务记录成功率、重连次数、用时、人工干预和网页实际用量变化。通过后再考虑更长任务；不要将其直接接入持续批量生产。

本次只创建这份调研汇总，未安装服务或发起上述试验。
