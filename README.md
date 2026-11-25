# Codex Thread Provider Card

在 Windows 版 Codex 的聊天右栏旁显示一张独立的「会话提供方」卡片。可以为每个会话选择 Responses API 提供方和请求速度，两项可分别设置，也可跟随共享配置。这个社区配件与 OpenAI 没有隶属关系。

## 安装和使用

1. 使用 Windows x64 和 Microsoft Store 版 Codex。先在共享 `config.toml` 配好一个具名的 Responses API 提供方，使用 `env_key` 或 `experimental_bearer_token`。只有 ChatGPT 账号登录、企业 OAuth、带 query 参数的接口和远程环境目前均未适配。配件包含自己的 Python 运行时。
2. 解压 Windows 发行包。若 Windows 给下载的 ZIP 标记了互联网来源，请在核对来源和校验值后用文件属性中的「解除锁定」再解压。双击 `Install.cmd`，完成后完整退出并重开 Codex。安装面向当前 Windows 用户，无需管理员权限。已有其他 `CODEX_CLI_PATH` 启动器时，安装程序会提示冲突并保留原设置。该环境变量也可能被使用它的其它程序读取。
3. 打开已有的本地聊天，展开 App 右栏的「输出内容」或「来源」所在区域。首次新建的聊天先发一条消息，使会话进入本地索引。点卡片的「＋」填写地址与 Key；点卡片标题栏的闪电按钮选择速度，不必先设专属提供方。同名聊天需要选定会话 ID。两项设置均从该会话的下一次生成请求起生效，无需重启。模型、推理强度和重试次数仍由 Codex 决定。切换提供方后，后续请求会将该聊天需要的上下文发送给所选提供方。

Key 使用 Windows 凭据管理器保存，原生面板明文显示当前会话已保存的 Key。「恢复默认」只清除该会话的地址和 Key；要清除速度偏好，请在闪电菜单里选「跟随 config.toml」。不同服务域名之间不会转发原提供方的自定义凭据头。传输使用回环 HTTP 和上游 HTTPS，可对本机开发服务使用 HTTP。中继透传响应流、429 和 Retry-After。若既有聊天带有某家提供方专属的加密历史、响应 ID 或压缩上下文，新提供方可能拒绝继续该历史。此时可恢复默认或开一个新的聊天。WebSocket 传输在此启动过程中切换为 HTTP/SSE。

## 会话速度（v0.2.0）

- **跟随 config.toml**（默认）：每次读取当前配置的 `service_tier`，`fast` 会映射为 `priority`。未指定档位时保留客户端的请求值。
- **Fast（优先）**：只为当前会话的生成请求发送 `service_tier: "priority"`。
- **标准**：显式发送 `service_tier: "default"`，即使共享配置选择了 Fast。

展开卡片可查看上一次发出的档位和上游 HTTP 状态。它们不能证明提供方兑现了优先处理；实际支持、速度及计费由所选提供方决定。配件只调整 `POST /v1/responses` 的速度字段；专用压缩接口保持原样。速度偏好按会话保存到 `CODEX_HOME/thread-provider-card/speed.sqlite3`，并最多保留 256 个会话的最近请求状态，不记录 API Key、地址、提示词或响应内容。

**从旧版升级**：等当前任务结束，完整退出 Codex，从 [Releases](https://github.com/by0159/Select-provider-for-different-codex-app-sessions/releases) 下载并解压 Windows x64 发行包，运行新版的 `Repair.cmd`，再打开 Codex。已保存的提供方凭据会保留。日常切换速度或提供方无需重启。

## Codex 更新以后

配件安装在 `%LOCALAPPDATA%\CodexThreadProviderCard`。每次启动都会查询当前注册的 Codex 包，API Key 保存在独立的用户凭据库中。文件损坏或启动入口丢失时，完整退出 Codex 并运行解压目录里的 `Repair.cmd`。该命令校验发行文件并恢复当前用户的入口。如果显示检查通过但卡片仍未出现，先打开一个已有聊天和右栏；如果新版本改变了右栏结构、会话索引或后端协议，需要新版配件。面板目前识别中英文右栏。

完整退出 Codex 后双击 `Uninstall.cmd`。它删除本配件的安装文件，释放属于它的启动入口。要清除单个聊天的凭据可以先点击「恢复默认」，也可在 Windows 凭据管理器中删除 `ThreadProviderCard/Bindings/v1/` 项。

## 从源码构建

在 Windows x64 上使用 Python 3.11 或更新版本运行 `python build.py`。构建使用 Windows .NET Framework 4.x 的 C# 编译器和 WPF UI Automation 程序集，从 python.org 获取并校验固定版本的 Windows 嵌入式运行时。输出位于 `out/`。仅项目本身的源码按 MIT 许可发布，发行包中的 Python 运行时适用 `payload/runtime/LICENSE.txt`。构建不读取用户聊天、凭据或个人配置。

构建后运行 `python tests/smoke.py`，在临时目录中验证发行包的安装、修复、卸载、原生卡片和实际 app-server 跨会话切速。测试需要已安装 Windows 版 Codex，只连接本机测试端点。`python tests/test_route_identity.py` 检查会话路由，`python tests/test_speed.py` 检查请求档位、gzip、压缩接口及错误状态。
