# Codex Thread Provider Card

在 Windows 版 Codex 的聊天右栏旁显示一张独立的「会话提供方」卡片。展开后可以给当前聊天指定 Responses API 地址和 API Key，点「恢复默认」即可回到共享配置。这个社区配件与 OpenAI 没有隶属关系。

## 安装和使用

1. 使用 Windows x64 和 Microsoft Store 版 Codex。先在共享 `config.toml` 配好一个具名的 Responses API 提供方，使用 `env_key` 或 `experimental_bearer_token`。只有 ChatGPT 账号登录、企业 OAuth、带 query 参数的接口和远程环境目前均未适配。配件包含自己的 Python 运行时。
2. 解压 Windows 发行包。若 Windows 给下载的 ZIP 标记了互联网来源，请在核对来源和校验值后用文件属性中的「解除锁定」再解压。双击 `Install.cmd`，完成后完整退出并重开 Codex。安装面向当前 Windows 用户，无需管理员权限。已有其他 `CODEX_CLI_PATH` 启动器时，安装程序会提示冲突并保留原设置。该环境变量也可能被使用它的其它程序读取。
3. 打开已有的本地聊天，展开 App 右栏的「输出内容」或「来源」所在区域。首次新建的聊天先发一条消息，使会话进入本地索引。点卡片的「＋」，输入地址与 Key，保存后从下一次请求起生效。同名聊天需要选择会话 ID。提供方按请求中的会话 ID 选择，与请求来自 Codex App、VS Code 或 CLI 无关；保存完成后，下一次请求立即读取新设置，不需要重启。默认模型、推理强度、Fast 档位及 Codex 的重试次数由原配置决定。自定义服务必须支持该模型和 Responses API。切换提供方后，后续请求会将该聊天需要的上下文发送给所选提供方。

Key 使用 Windows 凭据管理器保存。不同服务域名之间不会转发原提供方的自定义凭据头。传输使用回环 HTTP 和上游 HTTPS，可对本机开发服务使用 HTTP。中继按原样转发请求与响应，透传 429 和 Retry-After。若既有聊天带有某家提供方专属的加密历史、响应 ID 或压缩上下文，新提供方可能拒绝继续该历史。此时可恢复默认或开一个新的聊天。WebSocket 传输在此启动过程中切换为 HTTP/SSE。

## 这次更新（v0.1.1）

本版补充了来自 Codex App、VS Code 和 CLI 的会话 ID 路由测试，并覆盖手动上下文压缩与同一会话切换提供方。 路由依据会话 ID，不依据 `originator` 字段；因此同一会话从不同客户端继续时仍保持专属提供方。已有旧版用户可直接运行 `Repair.cmd`；如果旧转发器仍在使用，请等待当前请求结束，修复程序会在空闲边界更新它。

## Codex 更新以后

配件安装在 `%LOCALAPPDATA%\CodexThreadProviderCard`。每次启动都会查询当前注册的 Codex 包，API Key 保存在独立的用户凭据库中。文件损坏或启动入口丢失时，完整退出 Codex 并运行解压目录里的 `Repair.cmd`。该命令校验发行文件并恢复当前用户的入口。如果显示检查通过但卡片仍未出现，先打开一个已有聊天和右栏；如果新版本改变了右栏结构、会话索引或后端协议，需要新版配件。面板目前识别中英文右栏。

完整退出 Codex 后双击 `Uninstall.cmd`。它删除本配件的安装文件，释放属于它的启动入口。要清除单个聊天的凭据可以先点击「恢复默认」，也可在 Windows 凭据管理器中删除 `ThreadProviderCard/Bindings/v1/` 项。

## 从源码构建

在 Windows x64 上使用 Python 3.11 或更新版本运行 `python build.py`。构建使用 Windows .NET Framework 4.x 的 C# 编译器和 WPF UI Automation 程序集，从 python.org 获取并校验固定版本的 Windows 嵌入式运行时。输出位于 `out/`。仅项目本身的源码按 MIT 许可发布，发行包中的 Python 运行时适用 `payload/runtime/LICENSE.txt`。构建不读取用户聊天、凭据或个人配置。

运行 `python tests/smoke.py` 可以用临时目录、本机测试端点和随机会话凭据检查安装、实际 app-server 请求及卸载。需要已安装 Windows 版 Codex。测试跳过真实 App 窗口交互。
