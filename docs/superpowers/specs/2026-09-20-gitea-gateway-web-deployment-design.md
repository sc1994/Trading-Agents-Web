# Gitea 网关 Web 自动部署设计

## 背景

GitHub 上的 `sc1994/Trading-Agents-Web` 是唯一权威代码源。仓库目前是
CLI 应用，没有可长期运行的 HTTP 服务。第一版 Web 服务仅展示空白 HTML
页面，目的是在真正开发 Web 产品功能前，先建立一条经过测试、可以审计的
自动构建和部署链路。

网关机器是 `billsys`（`192.168.31.2`）。其 Gitea 仓库
`suncheng/Trading-Agents-Web` 当前只有一个与 GitHub 无共同历史的根提交
`052251b1a133a3aef9506b864c30d96c628c45be`，提交树中仅有一个空的
`README.md`。该仓库没有工作流，Actions 运行、任务和计划数量均为零。因此，
GitHub `main` 尚未同步到 Gitea。

网关上已有一台运行中的 Gitea Actions Runner，当前名称为
`gitea-runner-gatway`。Nginx Proxy Manager 已将
`trading.suncheng.online` 转发到 `127.0.0.1:7681`，该端口目前没有服务
监听。主机上还保留着历史 TradingAgents Dockge Stack 和镜像，但它们已经
停止，也不是当前仓库的构建产物。

本设计扩展并在必要处替代此前“只生成本地 CLI 镜像”的设计，但不会把
TradingAgents CLI 改造成 Web 应用。

## 目标

- 保持 GitHub `main` 为唯一权威代码源。
- 让 GitHub `main` 的常规更新通过非强制推送同步到 Gitea `main`。
- 使用网关专用的 Gitea Runner 标签构建并部署 Web 镜像。
- 通过 `trading.suncheng.online` 提供空白 HTML 页面。
- 提供不依赖业务组件的 `/healthz` 健康检查端点。
- 应用只绑定 `127.0.0.1:7681`，继续由 Nginx Proxy Manager 对外提供入口。
- 每个已部署镜像都能追溯到精确的 Gitea/GitHub 提交 SHA。
- 不影响现有运行密钥、TradingAgents 数据、历史 Stack 和无关容器。

## 非目标

- 不提供 TradingAgents 分析表单、HTTP API、身份认证或报告查看器。
- Web 容器和工作流不读取 LLM 或行情数据凭据。
- 不引入远程镜像仓库、Kubernetes、蓝绿部署平台或独立自动回滚服务。
- CI 不修改 Nginx Proxy Manager 配置。
- 不删除历史 TradingAgents 镜像、卷或 Dockge Stack。
- 不自动覆盖或修复未来出现的 Gitea 分支漂移。

## 方案比较

### 由仓库管理 Gitea 工作流并使用网关 Runner（采用）

仓库统一保存 Web 服务、Compose 配置、部署脚本、测试和 Gitea 工作流。
同步后的 Gitea `main` 收到推送时，只向带有 `gateway` 标签的 Runner 派发
部署任务。这样，运行内容与部署自动化可以一起版本化，并能直接从提交追踪到
运行实例。

### 使用 Dockge 手工维护 Stack

Dockge 符合网关现有运维方式，但仓库更新不能自然触发部署，主机配置也容易与
仓库中的部署契约发生漂移。Dockge 继续管理其他历史 Stack，但不负责本服务。

### 构建后推送镜像仓库，再由网关拉取

这种方式能隔离构建与运行权限，但当前服务只是单机上的无依赖空白页。为此增加
镜像仓库、凭据、保留策略和拉取编排，成本大于现阶段收益。

## 架构

### 代码同步

GitHub Actions 是唯一允许更新 Gitea `main` 的组件。完成初始化后，常规同步
只使用单一非强制 refspec `HEAD:refs/heads/main`，随后精确比较两端 SHA。

当前 Gitea 独立根提交会阻止首次快进推送。需要由运维人员执行一次受保护的
初始化操作：

1. 重新读取 Gitea `main`，要求它精确等于
   `052251b1a133a3aef9506b864c30d96c628c45be`。
2. 验证该提交没有父提交，且提交树中只有 `README.md`。
3. 在该提交上创建带说明的备份标签
   `pre-github-sync-20260920-052251b1`。
4. 验证备份标签能够解析回预期提交。
5. 使用绑定精确旧 SHA 的 `force-with-lease`，只替换
   `refs/heads/main`；禁止 mirror push、通配 refspec 和引用删除。
6. 验证 Gitea `main` 与本次检出的 GitHub `main` 完整 SHA 完全一致。

任何已观察 SHA 或提交树不匹配时，初始化立即停止且不修改 Gitea。初始化入口
不能接受任意旧 SHA。固定旧根提交离开 `main` 后，未来再出现分支漂移时只报告
异常，不自动覆盖。

### Web 服务

`web/server.py` 只使用 Python 标准库。它在 `/` 和 `/index.html` 返回
`web/index.html` 的精确内容，在 `/healthz` 返回 `ok\n`，其他路径返回
404。HTML 页面按需求保持无可见内容。

`web/Dockerfile` 使用 Python 3.12 Alpine，以非 root 用户运行，只包含服务器
和页面文件。Compose 服务满足以下约束：

- 将主机 `127.0.0.1:7681` 映射到容器 `8080` 端口；
- 使用 `restart: unless-stopped`；
- 通过 `/healthz` 执行 Docker 健康检查；
- 根文件系统只读，删除全部 Linux capabilities，启用
  `no-new-privileges`，并为 `/tmp` 提供小容量 `tmpfs`；
- 不使用 `env_file`，不读取应用密钥，不挂载宿主数据或 Docker socket。

Compose 项目名固定为 `trading-agents-web`。运行镜像命名为
`trading-agents-web-ui:<40 位提交 SHA>`，镜像与容器均携带
`org.opencontainers.image.revision=<SHA>` 元数据。

### 部署工作流

`.gitea/workflows/deploy-gateway-web.yml` 响应 `main` 推送和显式人工触发。
部署任务满足以下约束：

- 验证 Gitea 服务地址、仓库名、`refs/heads/main` 和 40 位小写提交 SHA；
- 使用 `runs-on: gateway`，不得使用通用 `ubuntu-latest` 标签；
- 仓库权限仅为 `contents: read`；
- 使用固定完整 SHA 的 checkout action，并在检出后禁用凭据保留；
- 将不可变的检出 SHA 传给 `scripts/deploy_gateway_web.sh`；
- 使用固定 concurrency group 和 `cancel-in-progress: false`，防止本工作流中的
  旧部署在新部署之后覆盖运行版本。

工作流不读取 GitHub 到 Gitea 的同步 token，也不读取任何应用 API 密钥。它会
使用 Runner 已有的宿主机 Docker 权限。该权限等同宿主机 root 控制面，实际约束
来自专用 Runner 标签和工作流身份守卫，而不是 Docker 自身隔离。

### 部署脚本

部署脚本验证提交 SHA 和固定端口，并选择 Docker Compose v2；如果环境只有兼容的
`docker-compose` 命令则使用该命令。执行顺序如下：

1. 构建带 revision 元数据的完整 SHA 候选镜像。
2. 在不挂载宿主数据、不注入密钥的条件下启动临时候选容器，同时验证
   `/healthz` 和空白页精确内容。
3. 删除临时候选容器。
4. 如果已有部署，记录当前镜像引用。
5. 使用候选镜像更新固定 Compose 项目。
6. 验证 Docker 健康状态、`http://127.0.0.1:7681/healthz` 和页面精确内容。
7. 切换后验证失败时，如果存在旧镜像则恢复旧镜像并报告失败；首次部署失败时，
   停止失败服务。

构建或候选检查失败不会影响当前运行服务。脚本不清理镜像，也不修改 Nginx Proxy
Manager。旧镜像暂时保留，供人工诊断和回退；只有镜像增长成为实际问题时才增加
自动保留策略。

## Runner 与网关准备

部署工作流同步到 Gitea 前，网关运维人员需要在保留已有标签的同时，为
`gitea-runner-gatway` 增加 `gateway` 标签。如果 Runner 的配置机制要求重启，
只重启这一台 Runner，并确认它带着新标签重新上线。本仓库不得借用含义错误的
`emailbill` 标签执行部署。

运维人员同时确认：

- 首次部署前，`127.0.0.1:7681` 仍未被占用；
- 历史 Dockge `tradingagents` Stack 继续保持停止；
- Nginx Proxy Manager 仍将 `trading.suncheng.online` 指向
  `127.0.0.1:7681`；
- 网关 Runner 可以使用 Docker 和 Compose。

这些是部署前检查，不授权删除或改写历史 Stack。

## 失败处理

- 初始化前置条件不匹配：不修改引用，报告新发现的 Gitea 状态。
- 常规同步遇到非快进：直接失败，不使用强制推送。
- Gitea 地址、仓库、分支或 Runner 不匹配：在修改 Docker 前跳过或失败。
- 构建或候选检查失败：保持当前服务不变。
- 端口冲突：切换前失败，并报告占用端口的进程或容器。
- 切换后健康检查失败：存在旧镜像时恢复旧镜像；首次部署则停止失败服务。
- Nginx Proxy Manager 入口失败：保留健康的本机回环服务，将代理异常作为独立
  运维问题报告。
- 除精确租约保护的一次性 `main` 替换外，任何失败路径都不得删除应用数据、
  历史 Stack、镜像或 Git 引用。

## 测试

实现前先编写测试，覆盖以下行为：

- 根页面精确字节、`/healthz`、HEAD 请求和 404 响应；
- 非法服务端口配置；
- 非 root 镜像和 Compose 安全配置；
- 精确的回环映射 `127.0.0.1:7681:8080`；
- 完整 SHA 镜像标签和 revision 元数据契约；
- 工作流的平台、仓库和 ref 守卫，`gateway` Runner 标签，固定 action SHA、
  权限、串行配置以及无密钥约束；
- 通过伪 Docker/Curl 命令环境验证部署脚本参数、候选先于切换、页面与健康检查、
  失败回退；
- 一次性初始化成功，以及旧 SHA 变化、提交树变化、租约竞态、任意旧 SHA、宽泛
  force、mirror、通配和删除操作的拒绝行为；
- 初始化后的常规快进同步，以及后续分支漂移的拒绝行为。

GitHub 仓库 CI 在 Pull Request 和 GitHub `main` 上运行 Web 与基础设施测试。
Gitea 部署工作流在网关上完成候选镜像和实际服务验证。

## 验收标准

1. Gitea 旧根提交可通过 `pre-github-sync-20260920-052251b1` 找回，Gitea 与
   GitHub `main` 解析到同一个完整 SHA。
2. 后续 GitHub `main` 提交能够通过常规非强制推送到达 Gitea。
3. Gitea 部署任务由带有 `gateway` 标签的 Runner 执行，并成功部署对应同步 SHA。
4. 只有一个 `trading-agents-web` Compose Web 容器处于健康状态；它使用
   `trading-agents-web-ui:<该 SHA>`，revision 元数据与提交一致。
5. `127.0.0.1:7681/healthz` 返回 `200` 和 `ok\n`，`/` 返回仓库中的空白页
   精确内容。
6. `trading.suncheng.online` 通过现有 Nginx Proxy Manager 入口返回相同页面。
7. 没有修改运行时或应用密钥、TradingAgents 数据目录、历史 Stack 或无关容器。
8. 测试中的无效候选镜像在切换前被拒绝，先前健康服务仍保持选中状态。

## 交付顺序

1. 实现并测试受保护的一次性 Gitea 初始化流程。
2. 实现并测试空白 Web 服务、镜像、Compose 契约和部署脚本。
3. 添加并测试 Gitea 部署工作流和 GitHub CI 覆盖。
4. 为网关 Runner 增加标签并确认 Runner 在线。
5. 执行一次性受保护 Gitea 同步。
6. 观察首次 Gitea 构建和部署，并验证回环地址与公开入口。

第 4 至第 6 步属于运维变更，只在仓库代码通过审查并进入 GitHub `main` 后执行。
