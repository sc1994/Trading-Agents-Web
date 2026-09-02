# Trading-Agents-Web 仓库初始化、Gitea 同步与本地镜像发布 Design Spec

- 规格版本：v1.0.0
- 日期：2026-09-01
- 需求确认 Issue：CODI-37
- 父 Issue：CODI-36

## 问题与用户

`sc1994/Trading-Agents-Web` 当前为空仓库，后续计划基于 `TauricResearch/TradingAgents` 二次开发，但本期只建立可审计、可持续维护的代码与发布基线，不开发 Web 功能。用户已经在 Gitea 创建私有目标仓库 `https://gitea.suncheng.online:81/suncheng/Trading-Agents-Web.git`，希望 GitHub 保持唯一权威源，代码单向同步到 Gitea，并由现有本地 Gitea Runner 产出可追溯、可回退的 Docker 镜像。

本规格面向项目维护者和本机运维人员。维护者需要明确上游来源、同步状态和发布结果；运维人员需要在不暴露凭据、不运行真实分析、不破坏现有镜像或业务数据的前提下管理本地发布产物。

上游初始化基线固定为已验证签名的 `TauricResearch/TradingAgents v0.4.0` 标签，其标签对象为 `c5e62b8bb88bc308e84ea351044356f99da1213e`，解析后的提交为 `2448d0a12576f9b2ddcd5980a0630833423d1e1b`。

## 目标和非目标

### 目标

- 以 TradingAgents `v0.4.0` 的精确提交初始化 GitHub `main`，保留许可证、版权、来源和可供后续人工同步的上游关系。
- 将 GitHub `main` 作为唯一权威源，以普通非强制推送单向同步到 Gitea `main`。
- 复用工作区现有同步实践，通过 GitHub Actions 在 `main` 更新或人工触发时同步 Gitea，并把凭据限制在最小权限和正确的 Secret 边界内。
- 在 Gitea `main` 收到同步提交后，复用现有 `gitea-runner-ai` 完成上游等价质量门禁、Docker 构建和离线 CLI smoke test。
- 生成以完整提交 SHA 标识的本地不可变镜像，在验证成功后提升稳定别名，保留最近三个成功版本并支持人工回退。
- 让同步、构建、提升、清理和失败结果可由 GitHub/Gitea 任务状态与脱敏日志审计。

### 非目标

- 不开发 Web 页面、Web API、用户系统或任何产品功能。
- 不自动合并未来上游更新；后续更新必须由人工获取、审查并通过 GitHub 变更流程进入 `main`。
- 不进行 GitHub/Gitea 双向同步，不从 Gitea 反向覆盖 GitHub。
- 不镜像其他分支或标签，不强制更新或删除 Gitea 引用。
- 不启动常驻应用容器，不配置端口、域名、反向代理或服务管理。
- 不执行真实 TradingAgents 分析，不注入 LLM、行情、云平台或券商 API 凭据，不产生模型费用。
- 不创建、挂载、迁移或修改 `~/.tradingagents` memory/checkpoint 数据。
- 不引入远程镜像仓库、主机 Python 虚拟环境发布、Kubernetes 或蓝绿部署。

## 范围

- 上游 `v0.4.0` 基线的身份、来源、许可证和历史可追溯性。
- GitHub 与 Gitea 的权威关系、目标仓库、分支、触发方式和 SHA 一致性。
- GitHub 到 Gitea 的同步凭据、最小权限、Secret 存储位置、缺失或泄露时的安全行为。
- GitHub 与 Gitea 工作流的执行平台隔离，防止镜像后的工作流在错误平台重复执行。
- Gitea Runner、Docker socket、受信任分支、并发和宿主机权限边界。
- Python 测试矩阵、clean-install/import、静态检查、Docker 构建和离线 CLI smoke 质量门禁。
- 本地镜像的不可变 SHA 标识、稳定别名、最近三版保留、失败保护和人工回退。
- 同步与发布结果的日志脱敏、可审计状态和验收方式。

## 约束

- GitHub 仓库固定为 `sc1994/Trading-Agents-Web`，Gitea 仓库固定为私有的 `suncheng/Trading-Agents-Web`；两者生产分支均为 `main`。
- 初始化来源固定为上游 `v0.4.0` 对应提交 `2448d0a12576f9b2ddcd5980a0630833423d1e1b`。仓库必须保留上游许可证、版权和来源说明，并记录足以重新验证基线的 tag、tag object 和 commit SHA。
- 后续上游更新只允许人工评审后进入 GitHub `main`；不得自动跟随上游 `main` 或自动合并新 tag。
- GitHub 到 Gitea 只推送 `HEAD:main`。同步不得使用强制推送、精确镜像或引用删除；目标非快进、分叉或已有冲突内容时必须失败并由人工处理。
- GitHub 同步任务只需读取 GitHub 仓库内容。Gitea 写入凭据使用 GitHub 仓库 Secret `GITEA_MIRROR_SYNC_TOKEN`，不得出现在仓库、命令输出、远程 URL、任务摘要或普通变量中。
- Gitea 写入 token 由专用自动化账号持有；该账号只对目标 Gitea 仓库拥有代码写入能力，不授予实例管理、组织管理、用户管理、Actions Secret 管理或其他仓库访问权限。若 Gitea 版本无法提供足够细的 token scope，则通过专用账号的仓库成员权限限制实际影响范围。
- 同步代码只在 `github.com` 的 GitHub Actions 环境执行；Gitea 本地发布只在目标 Gitea 环境执行。任一工作流被同步到另一平台后必须因平台身份保护而跳过错误侧任务。
- 本地发布 Runner 固定复用 `gitea-runner-ai`、标签 `ubuntu-latest`、Docker 执行器和宿主机 Docker socket。Docker socket 是宿主机 root 等价控制面，只能暴露给受保护 `main` 的发布任务，不能暴露给 PR、其他分支或不受信任的外部代码。
- Gitea `main` 更新自动发布，并允许对明确属于 `main` 历史的提交 SHA 手动重跑；PR、其他分支和标签不得自动取得发布权限。
- 发布按仓库串行。尚未开始的过期发布可被更新提交替代；已经进入稳定别名提升或镜像清理阶段的任务必须完成并记录结果后，下一提交才能继续。
- 发布过程不读取运行时 `.env`，不注入任何应用 API 密钥，不访问真实分析服务，也不操作 TradingAgents 持久化数据。
- 本地镜像名固定为 `trading-agents-web`。成功版本使用完整提交 SHA 作为不可变标签，稳定别名为 `local-stable`。

## 外部行为

### 初始化与上游关系

- GitHub `main` 的初始代码可验证为来自上游 `v0.4.0` 精确提交，且保留原许可证、版权和来源信息。
- 项目维护说明记录上游仓库 URL、基线 tag、tag object、commit SHA 和人工更新原则。后续维护者无需依赖某台机器的本地 Git remote 配置即可重建上游关系。
- 仓库初始化不会引入本期之外的 Web 功能或隐式产品变更。

### GitHub 到 Gitea 同步

- GitHub `main` 每次更新后自动触发同步；授权维护者也可手动重跑同一同步动作。
- 同步任务以 GitHub 只读权限检出完整提交，再使用 `GITEA_MIRROR_SYNC_TOKEN` 通过 HTTPS 普通推送更新 Gitea `main`。
- 成功时，GitHub 与 Gitea `main` 指向同一完整提交 SHA；日志展示非敏感仓库目标、源 SHA 和目标 SHA，但不展示 token 或带凭据 URL。
- token 缺失、无权、失效，Gitea 不可达，目标非快进或 SHA 不一致时，同步失败并保持 GitHub 权威源不变；不得改用强制覆盖恢复。
- 同步只处理 `main`，不创建、更新或删除其他 Gitea 分支和标签。

### Gitea 本地发布

- Gitea `main` 收到同步提交后自动触发发布；授权用户可对明确的 `main` 提交 SHA 手动重跑。
- 发布先执行与上游当前 CI 等价的门禁：Python 3.10、3.11、3.12、3.13 分别运行完整 `pytest -q`；Python 3.12 执行无开发依赖的 clean-install/import smoke；全仓执行 `ruff check .`。
- 全部门禁通过后才允许构建 `trading-agents-web:<完整提交 SHA>`，并在无任何应用 API 密钥的条件下执行离线 CLI smoke test。
- 构建和 smoke 全部成功后，才把同一镜像提升为 `trading-agents-web:local-stable`。Gitea 任务结果和日志明确展示候选 SHA、被提升 SHA、失败阶段和脱敏错误。
- 本期发布结束后不启动常驻容器，不修改端口、代理、运行时 `.env` 或 TradingAgents 数据目录。

### 失败、保留与回退

- 测试、静态检查、构建或 smoke 任一失败时，任务失败，`local-stable` 保持原指向，旧成功镜像不被删除。
- 只有成功提升后才执行清理；本机保留当前成功 SHA 及之前两个成功 SHA，共最近三个成功版本。
- 清理前必须确认候选镜像不是三个保留版本之一，且没有任何容器正在使用；不满足条件时跳过删除并在日志中说明。
- 人工回退只允许把 `local-stable` 重新指向一个仍保留的完整 SHA 镜像，不重新构建、不运行真实分析，也不改动持久化数据。
- Runner、Docker 或 Gitea 暂时不可用时允许有限重试；最终失败保持已有稳定镜像和数据不变，并通过任务状态与脱敏日志呈现。

### 用户准备事项

- 用户创建或选用专用 Gitea 自动化账号，只授予 `suncheng/Trading-Agents-Web` 代码写入能力。
- 用户在该账号下创建最小权限 token，并把值写入 GitHub 仓库 Actions Secret `GITEA_MIRROR_SYNC_TOKEN`；不得把真实值粘贴到 Issue、提交、普通变量或日志。
- 若 token 疑似泄露，用户立即撤销并轮换 Secret。轮换不需要改写 Git 历史，也不得通过放宽权限绕过同步失败。
- 本期不要求用户准备任何 LLM、行情、云平台或券商 API token。

## 方案取舍

### 稳定发布标签导入（采用）

采用已签名的上游 `v0.4.0` 精确提交，获得可验证、可复现的初始化基线，同时保留未来人工同步上游的能力。直接跟随上游 `main` 更新更及时，但会把未发布变更和不可预测兼容性带入空仓初始化；一次性快照则会削弱历史追溯和后续更新能力，因此均不采用。

### GitHub Actions 普通推送到 Gitea（采用）

该方式与 Multica 中现有 P2V 仓库实践一致，可在 GitHub `main` 更新后立即同步，并复用 GitHub Secret 和 Gitea HTTPS 可达性。Gitea 拉取镜像可减少 GitHub 侧写凭据，但触发和部署衔接依赖轮询或额外配置；局域网桥接 Runner 增加主机维护与隔离成本，因此本期不采用。

### 本机 Docker 镜像发布（采用）

上游已经提供 Docker 构建入口，现有 Gitea Runner 具备宿主机 Docker 能力。仅构建、验证和保留镜像，不常驻启动容器，可满足本期“发布到本地”并避免提前决定 Web 服务、端口、运行密钥和数据目录。宿主机虚拟环境发布会增加 Python 与路径漂移；只做 CI 验证则不会留下可运行产物，因此不采用。

### 不可变 SHA 标签加稳定别名（采用）

完整 SHA 标签提供审计和精确回退，`local-stable` 提供稳定人工入口，最近三版在恢复能力与磁盘占用间取得平衡。只保留 SHA 会降低日常使用便利；只保留 `latest` 会失去来源和可靠回退能力，因此不采用。

## 高层设计

1. **来源层**：以已验证签名的 `v0.4.0` tag 解析到的精确提交建立 GitHub `main`，保留上游历史可追溯性、许可证与来源记录；未来上游更新通过人工审查进入权威分支。
2. **同步层**：GitHub 侧在 `main` 更新或人工重跑时，以只读 GitHub 权限获取源提交，再使用独立 Gitea 凭据执行单分支普通推送；完成后校验两端 `main` SHA 一致。
3. **平台隔离层**：GitHub 同步任务与 Gitea 发布任务分别验证当前服务身份。工作流文件随代码镜像后，错误平台上的任务安全跳过，不形成同步循环或重复发布。
4. **资格验证层**：Gitea 对受信任 `main` 提交运行上游等价测试矩阵、clean-install/import 和全仓静态检查；验证阶段不接触应用密钥或真实分析服务。
5. **镜像构建层**：资格验证通过后，在受控 Docker socket 边界内构建完整 SHA 镜像并执行离线 CLI smoke。构建产物在提升前不影响稳定别名。
6. **提升与互斥层**：同一仓库的发布串行执行；成功 smoke 后才更新 `local-stable`。候选 SHA、提升前后状态和任务结果进入脱敏日志。
7. **保留与回退层**：成功提升后保留最近三个成功 SHA 镜像，跳过被容器使用的镜像；失败保持旧稳定别名。人工回退只重指稳定别名，不触碰运行数据。
8. **凭据边界**：GitHub 只持有目标仓库写入所需的 Gitea Secret；Gitea 发布不持有同步 token 或应用运行密钥。Docker socket 权限仅限受保护发布任务。

## 风险

- **Docker socket 权限过大**：受信任 `main` 中的恶意或误提交可能控制宿主机。通过分支保护、平台身份保护、来源限制、串行发布和不向 PR 暴露 socket 降低风险，但无法消除 root 等价属性。
- **Gitea token 泄露**：泄露可能允许篡改目标镜像仓库代码。通过专用账号、单仓库写权限、GitHub Secret、日志脱敏和快速轮换限制影响范围。
- **目标仓库意外分叉**：Gitea 上的直接提交会使后续普通推送非快进。设计选择失败关闭并人工处理，避免自动覆盖，但会暂时中断同步和发布。
- **跨平台工作流误执行**：同一工作流文件同时存在于 GitHub 与 Gitea，若缺少平台保护可能形成重复同步或在错误环境访问 Docker。平台身份保护是强制验收项。
- **上游基线漂移**：只记录 tag 名可能无法证明初始化内容。规格同时固定签名 tag object 和解析后的 commit SHA，并要求保留来源记录。
- **测试矩阵耗时**：四个 Python 版本加完整测试会延长发布时间，但它与上游兼容性承诺一致，用户已选择质量优先。
- **Runner 或 Gitea 可用性波动**：同步或发布可能暂时失败。有限重试后保持 GitHub 权威源和旧稳定镜像，不通过强制推送或跳过门禁恢复。
- **镜像占用磁盘**：构建缓存和失败层可能持续增长。成功后按三版策略清理可识别的旧成功镜像；任何额外缓存治理必须保证不删除被使用镜像。
- **稳定别名竞态**：并发任务可能让较旧提交覆盖新提交。通过仓库级串行化和提升阶段不可异步终止避免竞态。
- **未来运行边界未设计**：本期镜像不等于生产服务。端口、凭据、数据卷、费用、安全和实际分析验收必须在未来运行需求中重新确认。

## 开放问题

当前没有阻塞本规格批准的开放设计问题。实施前置条件是用户已创建的 Gitea 目标仓库保持为空或可快进，并由用户在 GitHub 配置符合本规格权限边界的 `GITEA_MIRROR_SYNC_TOKEN`。任何要求启动常驻容器、执行真实分析、增加 Web 功能、同步更多引用或允许强制覆盖的变化，都属于需求变更，必须重新确认安全与发布边界。

## 验收标准

1. GitHub `main` 的初始化来源可验证为上游签名 tag `v0.4.0`、tag object `c5e62b8bb88bc308e84ea351044356f99da1213e` 和 commit `2448d0a12576f9b2ddcd5980a0630833423d1e1b`；原许可证、版权和来源信息完整保留。
2. 仓库中存在可供新维护者重建上游关系的来源记录，且未来上游更新明确要求人工审查后进入 GitHub `main`。
3. GitHub `main` 更新和授权手动触发均能启动单向同步；同步任务的 GitHub 权限仅为读取仓库内容。
4. 用户仅需准备专用 Gitea 写入 token，并将其配置为 GitHub Actions Secret `GITEA_MIRROR_SYNC_TOKEN`；仓库、普通变量、任务输出和远程 URL 中均不出现真实值。
5. token 缺失、失效或权限不足时，同步在不泄露凭据的情况下失败，GitHub 内容不受影响，流程不尝试放宽权限或强制覆盖。
6. 同步成功后，GitHub `main` 与 `https://gitea.suncheng.online:81/suncheng/Trading-Agents-Web.git` 的 `main` 指向相同完整 SHA。
7. 同步仅执行普通 `HEAD:main` 推送；验证未强制更新、未精确镜像、未创建或删除其他分支/标签。目标非快进或分叉时任务失败并保留两端现状。
8. GitHub 同步任务只在 GitHub 环境执行，Gitea 发布任务只在目标 Gitea 环境执行；镜像后的错误侧任务被平台身份保护安全跳过。
9. Gitea `main` 更新自动触发发布，授权用户可对明确属于 `main` 历史的 SHA 手动重跑；PR、其他分支和标签不能取得发布权限或 Docker socket。
10. `gitea-runner-ai` 对候选 SHA 完成 Python 3.10–3.13 的完整 `pytest -q`、Python 3.12 clean-install/import smoke 和全仓 `ruff check .`；任一失败时不构建或提升稳定发布。
11. 全部质量门禁通过后，系统构建 `trading-agents-web:<完整提交 SHA>` 并在不注入任何应用 API 密钥的情况下完成离线 CLI smoke test。
12. 只有构建和 smoke 成功时，`trading-agents-web:local-stable` 才指向候选 SHA；Gitea 状态和脱敏日志可从稳定别名追溯到完整提交。
13. 测试、构建或 smoke 人为失败时，任务标记失败，原 `local-stable` 指向与既有成功镜像保持不变，旧镜像不被清理。
14. 成功提升后，本机保留当前及之前两个成功 SHA 镜像；清理不会删除三个保留版本或任何正在被容器使用的镜像。
15. 人工回退可将 `local-stable` 重新指向任一保留 SHA，且不重新构建、不启动真实分析、不读取应用密钥、不修改 TradingAgents 数据。
16. 发布任务按仓库串行；旧提交不能在新提交之后覆盖稳定别名，已进入提升或清理阶段的任务不会被异步终止。
17. 完整流程不启动常驻容器，不配置端口或代理，不创建或修改运行时 `.env`，不触碰 `~/.tradingagents` memory/checkpoint 数据。
18. GitHub/Gitea 任务日志只包含必要的非敏感仓库、SHA、阶段和错误信息；不输出 token、完整环境变量、运行时凭据或带凭据 URL。
