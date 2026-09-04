# Trading-Agents-Web 仓库初始化、Gitea 同步与本地镜像发布 Design Spec

- 规格版本：v1.2.0
- 日期：2026-09-04
- 需求确认 Issue：CODI-37
- 父 Issue：CODI-36

## 版本说明

本版本替代 `v1.1.0` 作为后续规划和未完成实现的需求依据。`v1.1.0` 及其批准记录继续保留为历史，不被覆盖。

`v1.2.0` 保留 `v1.1.0` 已批准的上游来源、单向同步、质量门禁、本地镜像、stable、保留、回滚和同一 SHA 并发发布风险边界，并根据用户最新决定作四项调整：

1. Gitea 当前 `main@052251b1a133a3aef9506b864c30d96c628c45be` 是仅含 `README.md` 的独立根提交。允许通过精确 compare-and-swap 机制一次性覆盖它，使 Gitea `main` 收敛到 GitHub 权威 `main` 的同一完整 SHA。
2. Gitea `main` 不要求分支保护。无状态检查、审批、禁止强推和可信 push 限制所带来的风险由用户接受，但必须如实记录，不能声称这些控制存在。
3. `gitea-runner-ai` 的 instance Runner 范围和读写 Docker socket 不再是本期验收门禁。它们仍是宿主机 root 等价风险，不能声称 Docker 能力只暴露给受保护发布路径。
4. Ruff 按项目声明的 `ruff>=0.15` 验收，记录实际版本并执行无忽略参数的全仓 `ruff check .`。旧版 `ruff 0.6.7` 的两个 `UP038` 告警不属于声明版本基线，不要求修改源码或增加忽略配置。

此前批准的唯一发布竞态豁免继续有效：两个发布进程对同一完整提交 SHA 并发，并在最终检查与实际标签写入之间交错时，后写入者可能将该完整 SHA 标签改指向不同 image ID。本规格不要求跨进程锁或原子 claim，但该豁免不得扩展到 stable 提升、失败清理、回滚、同步或凭据边界。

## 问题与目标

GitHub `sc1994/Trading-Agents-Web` 已从已验证的 `TauricResearch/TradingAgents v0.4.0` 初始化，并作为唯一权威源继续维护。Gitea 私有目标仓库 `https://gitea.suncheng.online:81/suncheng/Trading-Agents-Web.git` 已创建 `main`，但其 tip 是与 GitHub 历史无关的 README 独立根，现有普通推送会以 non-fast-forward 失败，阻断同步和后续本地发布。

本期需要在不授予通用破坏性能力的前提下完成一次性收敛，之后恢复普通非强制同步；同时按用户接受的 Gitea 分支和 Runner 风险边界完成质量门禁、本地镜像发布、保留与回滚设计。

本规格面向项目维护者和本机运维人员。维护者应能验证权威来源、初始化前像、同步 SHA 和发布结果；运维人员应能在不泄露凭据、不运行真实分析、不破坏已有稳定镜像或业务数据的前提下处理失败和回滚。

上游初始化基线继续固定为签名标签 `TauricResearch/TradingAgents v0.4.0`：tag object `c5e62b8bb88bc308e84ea351044356f99da1213e`，解析提交 `2448d0a12576f9b2ddcd5980a0630833423d1e1b`。

## 目标

- 保持 GitHub `main` 为唯一权威源，Gitea 只承接单向同步、质量验证和本地发布。
- 仅在 Gitea `main` 仍精确等于已审计 README 根提交时，允许一次性、人工触发、失败关闭的 compare-and-swap 覆盖。
- 初始化成功后，使 GitHub 与 Gitea `main` 指向同一完整 SHA，并恢复现有普通非强制同步。
- 保持专用 Gitea 自动化账号、单仓库代码写入权限、GitHub Secret 和日志脱敏边界；不因初始化例外增加实例管理或引用删除权限。
- 在 Gitea `main` 更新后通过现有 `gitea-runner-ai` 执行 Python 测试矩阵、clean-install/import、声明版本 Ruff、Docker 构建和离线 CLI smoke。
- 生成可追溯的完整 SHA 镜像，在 smoke 成功后提升 `local-stable`，保留最近三个成功版本并支持受控人工回滚。
- 准确记录无 Gitea 分支保护、instance Runner 读写 Docker socket 和同一 SHA 发布竞态的残余风险及恢复方式。
- 让一次性初始化、常规同步、质量门禁、镜像提升、清理和失败结果可通过任务状态与脱敏日志审计。

## 非目标

- 不开发 Web 页面、Web API、用户系统或其他产品功能。
- 不改变已导入的 TradingAgents `v0.4.0` 来源历史、许可证或版权记录。
- 不自动合并未来上游更新；后续更新必须人工审查后进入 GitHub `main`。
- 不允许 GitHub/Gitea 双向同步，不把 Gitea 独有提交反向合入 GitHub。
- 不提供通用 `--force`、`--mirror`、引用删除、任意旧 SHA 参数或对未知 Gitea 状态的覆盖能力。
- 不用删除仓库、删除分支或重建 Gitea 仓库替代精确 compare-and-swap 初始化。
- 不要求 Gitea `main` 分支保护，不把状态检查、审批、禁止强推或可信 push 限制描述为已存在。
- 不改造 Runner、Docker socket、宿主机或 Gitea 管理配置，不证明 instance Runner 只服务本仓库或受保护发布路径。
- 不启动常驻应用容器，不配置端口、域名、反向代理或服务管理。
- 不执行真实 TradingAgents 分析，不注入 LLM、行情、云平台或券商 API 凭据，不产生模型费用。
- 不创建、挂载、迁移或修改 `~/.tradingagents` memory/checkpoint 数据。
- 不引入远程镜像仓库、宿主机 Python 虚拟环境、Kubernetes、蓝绿部署、跨进程锁、分布式锁或原子 claim 服务。
- 不为未声明支持的 Ruff 旧版本修改业务源码，也不加入无效的 `UP038` 忽略配置。

## 范围与约束

### 仓库与来源

- GitHub 仓库固定为 `sc1994/Trading-Agents-Web`，Gitea 仓库固定为私有 `suncheng/Trading-Agents-Web`，两端生产分支均为 `main`。
- GitHub `main` 是唯一规范来源。Gitea 上任何未源自已验证 GitHub 同步的提交均为越界漂移，不获得反向同步资格。
- Gitea 无分支保护意味着该权威关系是流程规则而非平台强制保证。直接写入 Gitea `main` 可能造成漂移并触发高权限发布，属于用户已接受的残余风险。
- Gitea 初始化前像固定为 `refs/heads/main@052251b1a133a3aef9506b864c30d96c628c45be`。该 SHA 同时固定其无父历史和仅含 `README.md` 的树内容；初始化逻辑仍须显式复核这些事实并留下脱敏证据。
- 一次性初始化的目标 SHA 是人工触发当次、在 GitHub 官方环境中检出的权威 `main` 完整提交 SHA，不把某个可能漂移的观察值永久写成目标。

### 凭据与权限

- GitHub workflow 权限保持 `contents: read`。Gitea 写入凭据只从 GitHub Actions Secret `GITEA_MIRROR_SYNC_TOKEN` 读取。
- token 由专用自动化账号持有，实际影响范围仅限目标 Gitea 仓库的代码写入；不授予实例、组织、用户、Actions Secret 或其他仓库管理权限。
- 初始化模式复用同一 token，不新增管理员 token、密码、SSH 私钥或删除引用权限。若当前单仓库写权限不能执行精确 lease push，流程必须失败并回到需求确认，不得自动扩大权限。
- token 不得出现在仓库、Git remote、命令参数回显、任务摘要、普通变量或 Issue 中。HTTPS Git 认证继续使用受控临时 askpass，并保证权限收紧和退出清理。
- Gitea 发布 job 不读取 `GITEA_MIRROR_SYNC_TOKEN`，也不持有应用运行密钥。

### 平台与 Runner

- 同步和初始化只在 `github.com` 的 `sc1994/Trading-Agents-Web`、`refs/heads/main` 上运行；Gitea 发布只在目标 Gitea 仓库运行。错误平台上的镜像 workflow 必须由平台身份 guard 跳过。
- 本地发布复用 `gitea-runner-ai`、`ubuntu-latest` 标签、Docker executor 和读写宿主机 Docker socket。
- 当前 Runner 是 instance Runner，Docker socket 是宿主机 root 等价控制面。本期不要求仓库专属 Runner、socket proxy、DinD 或受保护分支隔离；验收必须记录实际边界，不能声称 PR、其他仓库或非受信任代码在基础设施层无法取得该能力。
- 仓库 workflow 仍须限制发布事件、仓库、ref、输入和 job 权限。这些应用层 guard 降低误触发概率，但不等同于 Gitea 分支保护或 Runner 基础设施隔离。
- Gitea 发布 workflow 使用固定仓库级 concurrency group 和 `cancel-in-progress: false`。它只串行本 workflow 管理的运行，不互斥直接 CLI、其他 workflow 或宿主机外部进程。

### 质量与发布

- 自动发布只响应目标 Gitea 仓库的 `main` push；人工 publish/rollback 必须使用完整 40 位 SHA，并验证提交存在且属于检出的 `main` 历史。
- publish 先运行 Python 3.10、3.11、3.12、3.13 的完整 `pytest -q`，再运行 Python 3.12 clean-install/import 和全仓 Ruff。
- Ruff 必须从满足项目声明 `ruff>=0.15` 的环境执行；任务日志或摘要记录 `ruff --version`，随后运行不带 `--ignore` 的 `ruff check .`。
- `ruff 0.15.0` 与当前解析版本 `0.16.6` 已在 GitHub `main@335d9e23e5505e9cc64d3c1971ca0f183773004f` 上通过全仓检查。`UP038` 在 `0.15.0` 已移除；旧版 `0.6.7` 的两个告警不构成基线失败。
- 全部门禁通过后才构建 `trading-agents-web:<完整提交 SHA>` 并执行不含应用密钥的离线 CLI smoke；smoke 成功后才可提升 `trading-agents-web:local-stable`。
- 完整 SHA 标签在顺序执行和可观察冲突下不得主动覆盖。仅保留 `v1.1.0` 已批准的同一 SHA 最终检查后并发竞态豁免。
- 构建或 smoke 失败的进程不得提升 stable 或执行成功后清理。成功提升后保留最近三个成功 SHA，且不得删除 stable 当前 SHA 或任何运行中、停止容器引用的镜像。
- 人工 rollback 只把 `local-stable` 指向已保留、元数据匹配的完整 SHA 镜像，不重建、不运行真实分析、不修改持久化数据。

## 外部行为

### 一次性初始化状态机

初始化模式只能人工触发，并按以下顺序执行；任一步失败都停止，且不得退化为普通 force、分支删除或仓库重建：

1. 验证当前平台为 GitHub 官方环境，仓库为 `sc1994/Trading-Agents-Web`，ref 为 `refs/heads/main`，检出提交是完整 40 位 `GITHUB_SHA`。
2. 通过无凭据回显的 Git 查询读取 Gitea `refs/heads/main`，要求结果唯一且精确等于 `052251b1a133a3aef9506b864c30d96c628c45be`。
3. 在隔离的临时 Git 状态中获取该目标提交，验证它无父提交，树中只有 `README.md`，并再次确认对象解析到预期完整 SHA。验证不写永久 remote 或工作树文件。
4. 仅执行等价于以下语义的单 ref push：

   `git push --porcelain --force-with-lease=refs/heads/main:052251b1a133a3aef9506b864c30d96c628c45be <受控 Gitea URL> HEAD:refs/heads/main`

5. push 不携带通用 `--force`、`--mirror`、`--delete`、tag refspec、通配 refspec 或用户可提供的任意旧 SHA。其他 Gitea 分支和标签保持不变。
6. push 后重新读取 Gitea `main`，要求其精确等于本次 GitHub `main` 的完整 SHA；不一致则任务失败并报告脱敏的源/目标 SHA。
7. 成功状态由远端 main 已不再等于初始化前像自然关闭。以后再次请求初始化时，步骤 2 必然失败；常规同步继续使用普通 `HEAD:refs/heads/main` 推送。

若 Gitea `main` 在步骤 2 到步骤 4 之间发生任何变化，`--force-with-lease` 必须拒绝写入。若未来有人故意把远端重置回同一前像，这本身是新的越界破坏性操作，不由本期初始化机制授权或恢复。

### 常规 GitHub 到 Gitea 同步

- GitHub `main` push 和授权人工重跑触发常规同步；初始化模式必须是显式、可区分的人工选择，不能由普通 push 自动进入。
- 常规同步只执行普通 `HEAD:refs/heads/main` 推送并在完成后校验两端完整 SHA 相等。
- token 缺失、权限不足、网络失败、Gitea 非快进、目标漂移或事后 SHA 不一致时失败关闭；不自动切换到初始化模式或任何 force 行为。
- 初始化例外只适用于固定 README 前像。此后出现的 Gitea 直接提交、分叉或未知状态必须单独调查和批准，不能复用本例外覆盖。
- 同步不创建、更新或删除其他 Gitea 分支和标签，日志不输出 token 或带凭据 URL。

### Gitea 质量门禁与本地发布

- Gitea `main` 更新自动触发 publish；授权用户可对检出 `main` 历史中的完整 SHA 手动 publish 或 rollback。
- 发布入口验证 Gitea 平台、目标仓库、事件、ref、operation 和 target SHA，并使用固定完整提交 SHA 的第三方 actions。
- publish 严格按测试矩阵、clean-install/import、`ruff --version`、全仓 `ruff check .`、Docker build、离线 smoke、stable 提升、成功后清理的顺序执行。
- 任一质量步骤失败即阻止构建或提升。旧 Ruff 的 `UP038` 告警不通过 `--ignore UP038` 绕过；正确做法是安装项目声明范围内的 Ruff 并留下版本证据。
- Gitea `main` 未受保护，因此直接 push 也可能触发该高权限 workflow。该行为不代表提交获得 GitHub 权威资格，是已接受但必须记录的安全风险。
- 本期发布不启动常驻容器，不读取运行时 `.env`，不访问真实分析服务，不触碰 `~/.tradingagents`。

### 同一 SHA 并发发布

- 正常 Gitea 发布入口继续按 workflow 串行，维护者不应绕过该入口并发启动同一 SHA 发布。
- 已存在且 managed/revision 元数据匹配的完整 SHA 标签应复用并重新 smoke；元数据或可观察 image ID 冲突必须拒绝。
- 两个进程在最终检查与实际 tag 写入之间交错时，允许后写入者把同一完整 SHA 标签改指向不同 image ID；本期不提供跨进程锁或原子 compare-and-set。
- 每个进入 stable 提升阶段的进程仍必须独立完成成功 smoke。失败进程不得提升 stable 或清理旧镜像。
- 发现竞态后应停止额外发布，核对标签元数据、image ID 和 `local-stable`，再通过受控串行 publish 恢复；不得用 Git force、引用删除或扩大凭据处理 Docker 标签竞态。

### 失败、保留与回滚

- 测试、Ruff、构建或 smoke 任一失败时，任务失败，`local-stable` 保持原指向，旧成功镜像不被删除。
- 只有成功提升后才清理；保留当前及之前两个成功 SHA，并跳过 stable 当前 SHA 和所有被运行中或停止容器引用的镜像。
- rollback 只重指 stable，不重新构建、不运行真实分析、不读取应用密钥、不修改数据。
- Runner、Docker 或 Gitea 不可用时允许有界重试；最终失败保持现状，并通过任务状态和脱敏日志呈现。

## 方案取舍

### 精确 compare-and-swap 初始化（采用）

采用固定前像 SHA、显式内容复核和 `--force-with-lease=<ref>:<精确旧 SHA>`，只覆盖用户已批准的 README 独立根。它能在并发变化时失败，且不授予任意旧 SHA、通用 force、mirror 或删除引用能力。

临时 workflow 成功后再删除也能缩短代码入口寿命，但增加额外变更和合并周期；把 Gitea README 历史合入 GitHub 会改变权威来源历史；删除分支或重建仓库会扩大破坏范围。因此均不采用。初始化入口可保留为状态守卫逻辑，因为远端离开固定前像后无法再次生效。

### GitHub Actions 单向同步（继续采用）

GitHub Actions 能在权威 `main` 更新后立即同步，并复用现有 Secret 与 HTTPS 可达性。初始化成功后的所有正常流量仍使用普通单分支 push。Gitea 拉取镜像会改变触发和凭据模型，双向同步会引入冲突，因此不采用。

### 不要求 Gitea 分支保护（风险接受）

用户选择以当前未保护 `main` 推进，减少 Gitea 管理侧前置配置，但平台不再阻止直接 push、force push 或未经状态检查/审批的提交。仓库 workflow guard 和 GitHub 权威规则只能降低误用并支持审计，不能替代分支保护。未来若需要恢复强制保护，应作为新的需求变更处理。

### 复用 instance Runner 与宿主机 Docker socket（风险接受）

复用现有 Runner 能直接产出本地镜像，但 instance 级调度和读写 Docker socket 扩大了可信边界。本期不引入专属 Runner、socket proxy 或 DinD，也不把其隔离作为验收门禁；runbook 和证据必须清楚说明 root 等价风险。

### 按声明 Ruff 版本验收（采用）

使用 `ruff>=0.15` 与项目依赖声明一致，最低版和当前解析版均已证明全仓通过。为未声明的 `0.6.7` 修改上游源码会扩大范围；新增 `UP038` ignore 则会形成对已移除规则的无效配置。因此两者均不采用。

### 完整 SHA 镜像、stable 与三版保留（继续采用）

完整 SHA 标签提供审计和精确回滚，`local-stable` 提供稳定人工入口，三版保留平衡恢复能力与磁盘占用。顺序执行和可观察冲突下仍拒绝覆盖，只保留已批准的同一 SHA 最终检查后竞态豁免。

## 高层设计

1. **权威来源层**：GitHub `main` 保留上游 `v0.4.0` 来源与后续人工审查历史，是唯一规范来源。
2. **初始化守卫层**：人工初始化读取并验证固定 Gitea 前像，以精确 lease 单 ref 替换 main，随后验证两端完整 SHA；任何漂移都失败关闭。
3. **常规同步层**：初始化后只允许 GitHub `main` 通过普通 push 更新 Gitea `main`，并校验 SHA 一致。Gitea 漂移不自动修复。
4. **平台隔离层**：GitHub 与 Gitea workflow 分别验证平台、仓库、事件与 ref，错误侧安全跳过。
5. **资格验证层**：Gitea publish 对候选提交运行测试矩阵、clean import 和声明版本 Ruff，不读取应用密钥。
6. **镜像构建层**：资格通过后使用现有 Docker socket 构建完整 SHA 镜像并离线 smoke。Runner/socket 事实进入风险记录，不宣称基础设施隔离。
7. **提升与串行层**：workflow 级 concurrency 串行受控运行，smoke 成功后才提升 stable；该串行性不覆盖外部进程。
8. **保留与回滚层**：成功后清理到三个可回退成功 SHA，同时保护 stable 和容器引用；失败保持旧稳定状态。
9. **审计层**：记录初始化前后 SHA、Ruff 实际版本、质量阶段、候选/稳定镜像、清理跳过和错误原因，统一脱敏。

## 对后续任务和验收的影响

### Task 2：GitHub 到 Gitea 同步

- Task 2 不再以“目标为空或可快进”为初始化前提，必须增加本规格定义的人工初始化状态机。
- 测试必须覆盖：精确 README 前像成功、前像 SHA 不同失败、目标在检查与 push 间变化导致 lease 失败、父/树验证失败、缺 token 失败、事后 SHA 不一致失败，以及初始化成功后的普通快进同步。
- 测试和静态检查必须证明不存在通用 `--force`、`--mirror`、`--delete`、其他 refspec 或可传入任意前像的接口。
- 现有常规 non-fast-forward 失败保护继续有效。初始化完成后，任何新的分叉都不得自动覆盖。
- 凭据仍为单仓库代码写入 token；不得为初始化增加管理或删除权限。

### Task 3：本地镜像控制器

- `v1.1.0` 的验收边界保持不变：顺序复用、元数据与可观察 image ID 冲突拒绝、smoke 前不得提升、失败保护、三版保留、stable/容器引用保护和受控回滚继续强制。
- 不要求跨进程互斥、原子 claim 或最终检查后竞态下绝对不可变；该豁免不受本轮 Gitea 风险决定扩大。

### Task 4：Gitea 质量门禁与发布 workflow

- 删除“Gitea `main` 已配置分支保护”和“Docker socket 只暴露给受保护发布路径”作为验收前置条件；不得声称这些事实成立。
- 保留平台/仓库/ref/input guard、只读仓库权限、完整 action SHA pin、完整 SHA/祖先验证、测试矩阵、clean import、workflow concurrency、smoke 后 publish 和 rollback 边界。
- Ruff 验收必须安装满足 `>=0.15` 的版本，记录版本并运行无 ignore 的全仓 `ruff check .`。旧版 `0.6.7` 的 `UP038` 不阻塞，也不通过源码修改或配置抑制处理。
- 审查必须把未保护 main 可直接触发 root 等价 Docker job、instance Runner 共享范围和 socket 读写挂载列为已接受残余风险。

### Task 5：runbook 与端到端证据

- runbook 必须提供一次性初始化的操作者条件、固定前像、精确 lease 语义、失败关闭行为、脱敏证据和初始化后的常规同步路径。
- 端到端证据必须展示初始化前 Gitea SHA、当次 GitHub 源 SHA、lease push 结果、初始化后两端同一完整 SHA，以及其他 refs 未被修改。
- 证据必须记录 Gitea `main` 无分支保护、Runner 为 instance scope、Docker executor 与读写宿主机 socket；这些是风险披露，不是要求整改或证明隔离。
- 证据必须记录 Ruff 实际版本满足声明、无 ignore 的全仓命令和结果；不得把旧 `0.6.7` 输出作为声明版本失败。
- 保留同步 token、平台隔离、质量门禁、stable、失败保护、三版保留、容器引用保护、回滚、竞态恢复和日志脱敏证据。
- Gitea 后续漂移时，runbook 只能指导停止发布、核对事实并重新进入审批；不得提供通用 force 修复指令。

## 风险

- **未保护 Gitea main（已接受）**：具备写权限的主体可直接 push 或 force push，绕过状态检查和审批，并可能触发发布。GitHub 权威规则不能在 Gitea 平台层阻止此行为。
- **instance Runner 与 Docker socket（已接受）**：能够调度到该 Runner 并执行 Docker 命令的 workflow 可能取得宿主机 root 等价控制。仓库级 guard 不是基础设施隔离。
- **一次性覆盖误用**：若覆盖条件可配置为任意 SHA，会演变为通用 force。通过固定前像、内容复核、精确 lease、人工触发和单 ref 限制降低风险。
- **检查后并发变化**：读取前像后他人可能更新 Gitea main。精确 `--force-with-lease` 必须使覆盖失败，避免丢失并发写入。
- **后续 Gitea 漂移**：初始化后直接提交会使普通同步失败，且可能已触发高权限发布。流程必须停止、审计并重新批准，不能复用初始化例外。
- **Gitea token 泄露**：泄露可能篡改目标仓库。通过专用账号、单仓库写权限、Secret、askpass 清理、日志脱敏和轮换限制影响。
- **跨平台误执行**：镜像后的 workflow 若缺少平台 guard，可能循环同步或在错误环境访问 Docker。平台身份校验继续是强制项。
- **Ruff 环境漂移**：使用系统旧版会产生与声明范围不一致的结果。通过安装项目声明范围、打印版本和全仓无 ignore 命令保证证据一致。
- **同一 SHA 镜像标签竞态（已接受）**：外部并发进程可能在最终检查后改指标签。工作流串行、操作约束、日志核对和串行重跑降低发生率与恢复成本，但本期不消除此风险。
- **stable 顺序竞态**：受控 workflow 若并发或被中途取消，旧提交可能覆盖新 stable。固定 concurrency 和 `cancel-in-progress: false` 继续防止该问题。
- **镜像磁盘占用**：构建缓存和失败层可能累积。只在成功后清理可识别旧成功镜像，并保护 stable 和容器引用。
- **未来运行边界未设计**：本期镜像不是生产服务。端口、凭据、数据卷、费用、安全和真实分析必须在未来需求中重新确认。

## 开放问题

当前没有阻塞本规格审批的开放设计问题。用户已批准精确 compare-and-swap 初始化和按 `ruff>=0.15` 验收；不要求 Gitea 分支保护及 Runner/socket 隔离也已明确作为风险接受。

本规格批准后，仅允许提交本 spec 相关变更并创建新的探索 PR。探索 PR 合并后，受影响的旧 plan 与 Task 2、Task 4、Task 5 未完成工作必须按 `v1.2.0` 重新规划；在新 spec 和后续 plan 的 provider 合并事实成立前，不得恢复 CODI-59 的实现审查或 PR。

任何增加 Web 功能、改变 GitHub 权威源、同步其他 refs、允许任意 force/删除、启动真实分析、扩大凭据、要求或取消更多安全控制的变化，都属于新的需求变更。

## 验收标准

1. 规格明确 GitHub `main` 是唯一权威源；Gitea 不获得反向同步或独立来源资格。
2. 上游来源仍可验证为 `v0.4.0`、tag object `c5e62b8bb88bc308e84ea351044356f99da1213e` 和 commit `2448d0a12576f9b2ddcd5980a0630833423d1e1b`，许可证、版权和来源信息完整保留。
3. 一次性初始化只允许人工触发，并验证 GitHub 平台、仓库、main ref 和完整源 SHA。
4. 初始化前必须验证 Gitea `main` 精确等于 `052251b1a133a3aef9506b864c30d96c628c45be`，该提交无父且树中仅有 `README.md`；任一不匹配均在 push 前失败。
5. 初始化只使用精确 `--force-with-lease=refs/heads/main:052251b1a133a3aef9506b864c30d96c628c45be` 的单 main ref 语义；不存在通用 force、mirror、delete、tag/通配 refspec 或任意前像参数。
6. Gitea `main` 在检查与 push 之间变化时 lease 拒绝写入，并保留变化后的远端状态。
7. 初始化成功后，两端 `main` 指向同一完整 SHA，其他 Gitea 分支和标签不被创建、更新或删除；再次初始化因前像不匹配而失败。
8. 初始化和常规同步复用单仓库代码写入 token `GITEA_MIRROR_SYNC_TOKEN`，不新增管理、删除或其他仓库权限；凭据不进入仓库、URL、日志或 Issue。
9. 初始化后的 GitHub `main` push 和授权人工重跑只执行普通 `HEAD:refs/heads/main` 同步；non-fast-forward、未知漂移或 SHA 不一致失败且不自动 force。
10. GitHub 同步只在 GitHub 官方环境执行，Gitea 发布只在目标 Gitea 环境执行，错误侧 workflow 由平台、仓库和 ref guard 安全跳过。
11. 验收如实记录 Gitea `main` 没有分支保护，不要求状态检查、审批或禁止强推证据，也不声称直接 push 在平台层被阻止。
12. 验收如实记录 `gitea-runner-ai` 的 instance scope、`ubuntu-latest`、Docker executor 和读写宿主机 Docker socket，不要求整改或声称只向受保护发布路径暴露。
13. 发布 workflow 仍只响应目标仓库 main push 或严格验证的人工 publish/rollback 输入，并使用完整 action SHA、只读仓库权限和完整 40 位目标 SHA。
14. publish 对候选 SHA 完成 Python 3.10-3.13 的完整 `pytest -q`、Python 3.12 clean-install/import，以及满足 `>=0.15` 的 Ruff 全仓检查。
15. Ruff 证据包含 `ruff --version` 和无 `--ignore` 的 `ruff check .` 成功结果；旧版 `0.6.7` 的两个 `UP038` 不阻塞，不修改对应源码，也不增加 `UP038` ignore。
16. 任一测试、clean import 或 Ruff 失败时不构建、不 smoke、不提升 stable、不执行成功后清理。
17. 质量门禁通过后构建 `trading-agents-web:<完整提交 SHA>` 并在不注入应用密钥的条件下完成离线 CLI smoke。
18. 只有 smoke 成功的进程可更新 `trading-agents-web:local-stable`；失败进程不能改变 stable 或清理旧成功镜像。
19. 成功后保留当前及之前两个成功 SHA；清理保护 stable 当前 SHA 及运行中、停止容器引用的镜像。
20. rollback 只把 stable 指向已保留且元数据匹配的完整 SHA，不重建、不运行真实分析、不读取应用密钥、不修改数据。
21. 受控 Gitea workflow 使用固定 concurrency 和 `cancel-in-progress: false`，旧提交不能在新提交后覆盖 stable；验收不把该属性表述为全局互斥。
22. 完整 SHA 标签在顺序执行和可观察冲突下不得主动覆盖；仅保留同一 SHA 最终检查后并发竞态豁免，且不放宽 stable、失败、清理或回滚要求。
23. 完整流程不启动常驻容器，不配置端口或代理，不创建或修改运行时 `.env`，不触碰 `~/.tradingagents`。
24. GitHub/Gitea 日志只包含必要的非敏感仓库、SHA、版本、阶段和错误信息，不输出 token、完整环境变量、运行时凭据或带凭据 URL。
25. runbook 记录一次性初始化、常规同步、Ruff 版本、无分支保护、Runner/socket、同一 SHA 竞态、失败处理、漂移升级、保留和回滚，并禁止用通用 force 处理后续未知状态。
26. 新探索 PR 只包含本版本 spec 相关文件，目标分支固定为 GitHub `main`，正文对 CODI-37 使用正确的关闭意图；旧探索 PR 仅作历史，不重复使用。
