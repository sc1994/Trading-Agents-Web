# 网关 Web 研究工作台运维手册

## 研究工作台当前发布与访问边界

当前版本包含研究任务与服务器端凭据，工作台**没有登录或访问控制**。
GitHub `main` 经批准的同步流程推送至 Gitea `suncheng/Trading-Agents-Web` 的
`main` 时，Gitea 工作流在 `gateway` Runner 上自动发布该 push 的完整 SHA；无需手动
触发或填写发布/入口核验 SHA。工作流仍核验仓库、服务地址、分支、检出 commit、完整
SHA 和镜像 revision，并保留候选验证及自动回退保护。

Compose 仅绑定 `127.0.0.1:7681:8080`，但回环绑定**不是隐私保证**：既有反向代理、
隧道或转发端口仍可能将无登录的工作台公开。是否开放公开代理入口是单独的运维决策，
须由获授权的维护者独立评估访问边界；自动发布不表示已审核或更改代理配置。
自动发布不修改代理配置或公开入口。

### gateway Runner 执行环境

现有 `gitea-runner-gatway` 继续承担 `ubuntu-latest` 和 `emailbill`，仅新增完整规格
`gateway:docker://local/trading-agents-gateway-runner:20260923`。从
`infra/gateway-runner.Dockerfile` 构建该本机镜像；它提供 Node、Git、Bash、curl、
Docker CLI、Buildx、Compose 和 `ss`。在激活标签前，必须先核对网关身份、Runner
Compose 服务及配置挂载、镜像内命令和 `127.0.0.1:7681` 占用状态。现有注册文件
`/data/.runner` 不得读取、删除或重新注册；配置文件 `runner.labels` 必须填写
`ubuntu-latest:docker://docker-cli:latest`、`emailbill:docker://docker-cli:latest`
及上述 `gateway` 完整规格，再只重启 Runner 服务。修改前备份配置并保留权限；
重启后确认原 Runner 身份和原有两个标签均不变。回退时从备份恢复配置，仅重启
Runner 服务，保留工作台的服务和数据卷。

本机预置顺序（仅在更新后的脚本已进入 Gitea `main` 时执行）：

1. 用运维清单的 SSH 配置解析 `billsys`，在连接内核对 `hostname=billsys`、
   `id -un=root`、`pwd=/root`；确认 `code/gitea-runner` 正在运行，实际挂载为
   `/wd/apps/vols/gitea/runner/config.yaml:/config.yaml` 和 Runner 数据目录，
   Docker 监听者及宿主机 `ss` 均显示 `7681` 未被无关进程占用。
2. 从已经合并的 GitHub `main` 取得 `infra/gateway-runner.Dockerfile`，经受控
   `scp -F /home/ai/.ssh/paseo-ops/config` 复制到网关单独创建的临时目录。网关
   使用 `docker build --pull=false -f <临时目录>/Dockerfile -t
   local/trading-agents-gateway-runner:20260923 <临时目录>` 构建；记录镜像 ID。
   执行 `docker image inspect` 核对该 tag，并从只挂 Docker socket 的隔离容器
   验证 `docker buildx version`、`docker compose version`、`git --version` 和
   宿主网络辅助容器内的 `ss -H -ltn 'sport = :7681'`。Runner 和 Docker CLI
   必须访问同一宿主 Docker daemon，不能在其他机器只构建相同名字的镜像。
3. 核对配置文件当前仅包含已确认的 Runner 设置，备份
   `/wd/apps/vols/gitea/runner/config.yaml` 并保留权限。使用 YAML 解析器
   在原配置添加完整 `runner.labels` 三项，不修改 `container.valid_volumes`、
   Compose 其他服务或 `.runner` 注册文件。运行
   `docker compose -f /wd/apps/docker/dockge/code/compose.yaml -p code restart
   gitea-runner`，只重启这一服务。单纯运行 `up -d` 不会因挂载的配置文件变化
   而重启容器，也就不会重新声明标签。
4. 确认原 Runner ID 在线、`ubuntu-latest` 和 `emailbill` 保留、`gateway`
   指向已核对的本机镜像；再确认等待任务及本服务容器、镜像 revision 和
   `127.0.0.1:7681/healthz`。任一步异常都停止扩大变更，依据备份恢复配置并
   仅重启 Runner 服务，不手动启动或覆盖工作台服务。

Runner 任务容器保持现有隔离网络。部署脚本只对宿主机端口监听和回环 HTTP 校验
启动短生命周期 `--network host` 探测容器；该容器只读、丢弃 capabilities、没有
卷挂载，且禁止拉取未知镜像。响应由标准输出回传任务容器供逐字节比对。任务容器
内的 `127.0.0.1` 不是网关宿主机，不能直接用于正式服务健康检查。必须在更新的
部署脚本进入 Gitea `main` 后才激活 `gateway` 标签，否则已有排队任务会执行旧
脚本并错误访问任务容器自己的回环地址。

Web 暂不支持 `openai_compatible`：界面不提供该选项，任务、默认设置和连接测试
均拒绝它，浏览器不能提供任意后端 URL。CLI 的现有能力不受影响。
浏览器仍以用户本地日历日填写今天；服务端最大接受 UTC 日期加一天，以覆盖包括
亚洲午夜和 UTC+14 在内的全球本地今天，不依赖浏览器提供的时区。超过此界限仍拒绝。
运行中历史查询会立即显示恢复暂不可用，执行器空闲后重新查询可恢复状态；真正恢复前
仍在执行锁内重新验证检查点和原凭据归属。

镜像是 Node 22 构建 React + Python 3.12 运行时，缺少构建后的 `dist/index.html`
会导致构建失败。只启动一个 Uvicorn worker，UID/GID 固定为 `10001:10001`，
不可扩为多个 worker/副本。Compose 保留只读根目录、cap-drop、no-new-privileges、
16 MiB `/tmp` 与 `127.0.0.1:7681:8080`。构建和健康检查不读取模型密钥；
生产凭据在私有入口的设置页配置，不加入构建参数、CI 环境或镜像。

中文股票名称检索需要独立的标的目录刷新。经数据使用条款和运维授权后，在包含
`docker-compose.gateway-web.yml` 的已核实仓库目录执行一次
`timeout 180s docker compose -p trading-agents-web -f docker-compose.gateway-web.yml exec -T web python -m web.catalog`，
并由宿主调度器每天执行同一命令。刷新在容器的持久卷写入 `assets.json`，失败时
退出非零且保留旧文件；应监控退出码及文件更新时间，不要把第三方接口故障当成
工作台健康检查故障。港股名单优先从东方财富获取，失败后尝试新浪；两者均失效时
不发布不完整数据。升级前备份该文件，回退时它可被旧版本忽略。

### 持久卷、属主与首次迁移

Compose 项目 `trading-agents-web` 的逻辑卷 `web-data` 默认命名为
`trading-agents-web_web-data`，挂载 `/var/lib/tradingagents-web`（读写）。
`TRADINGAGENTS_WEB_DATA_DIR` 在镜像中固定为该路径。先用 Compose 配置与容器 Mounts
核对实际卷名，不能以目录或工作树名称猜测。新空卷由 Docker 从镜像目录初始化，
应继承 `10001:10001` 与 `0700`；已有卷不会自动修正属主。

完整备份范围包括 `web.db` 及其 SQLite sidecar、`reports/`、`cache/`（含
`cache/checkpoints/*.db`）、`memory/`，以及 `private/checkpoint-bindings/`
中的签名密钥和任务归属记录。遗漏 `private/` 会使原检查点无法安全恢复。
这些目录可能在首次运行后才创建。运行时可创建文件，不能写镜像根目录。

从旧空白页升级没有 Web 任务数据可迁移；先创建并核验新卷即可。
若需从开发目录或其他版本导入已有工作台数据：在独立维护授权下停止本服务写入，
先备份原数据，再将完整内容恢复到**新建的专用卷**，仅对该已确认的卷内目录修正
属主为 `10001:10001`，根目录权限为 `0700`。不要更改宿主机宽泛目录、其他服务卷，
也不要让应用长期以 root 运行。确认所有 SQLite 文件和报告/记忆/检查点目录均可由
UID 10001 读写后，再安排切换；原卷保留用于恢复。

### 一致备份与恢复演练

以下为维护流程，**需要独立的维护窗口授权，不在本次打包任务中执行**：

1. 记录当前不可变镜像 SHA/ID、实际卷名、备份时间与权限。停止本服务并确认没有
   worker/副本写入；不要仅复制运行中的 `web.db`，以免遗漏 WAL 或与检查点不一致。
2. 用该镜像的 UID 10001，将已确认卷只读挂载到隔离容器，运行
   `tar -C /var/lib/tradingagents-web -czf - .`，将标准输出保存到权限 `0600`
   的受控备份文件（先设 `umask 077`）。备份包含所有隐藏文件和上述完整目录。
   备份与密钥同等敏感，限制访问并在存储/传输层加密，不打印内容到日志。
3. 校验归档与校验和，恢复演练只使用新建的空白专用卷。以 UID 10001 解压可信归档
   （`tar --no-same-owner -xzf ...`），不覆盖当前卷。检查根目录 UID/GID/权限，
   并对 `web.db` 与每个 `cache/checkpoints/*.db` 执行 SQLite
   `PRAGMA integrity_check`，结果必须为 `ok`；核对 reports、memory、private 和
   checkpoint 文件清单/校验和与备份一致。
4. 用相同镜像 SHA、恢复卷和独立回环端口验证健康、历史、报告正文/导出、设置掩码
   与可恢复任务归属。恢复的排队任务会自动执行，必须在阻断外网的隔离环境演练，
   或使用无排队任务的预备演练快照；不得让演练触发付费模型/真实数据请求。
5. 清理的仅是本次明确命名的演练容器/卷。保留原卷与备份，记录恢复耗时与结果。

### 升级与回退

升级前备份整个卷，确认磁盘空间、UID/GID 和访问入口，检查版本是否包含数据库迁移。
当前存储初始化使用兼容的建表逻辑，不自动转换旧 CLI 数据。Gitea `main` push
会自动发布对应完整 SHA；候选使用独立临时卷，绝不挂载生产卷，
删除候选时同时删除临时卷。
部署脚本从候选镜像提取编译后的 HTML 做逐字节校验，并保留旧容器 HTML 供回退验证，
兼容旧空白页路径。CI 另验证包导入、非 root、数据目录可写、SQLite 完整性和无密钥 API。

脚本的自动回退只恢复镜像，不恢复或删除持久卷。若将来升级包含不向后兼容的数据迁移，
不得依赖自动镜像回退：需单独审核迁移方案，停写后将升级前完整备份恢复到新卷，
使用对应旧 SHA 验证后再安排切换。禁止 `docker compose down --volumes` 和全局 prune。
健康检查不证明真实模型/行情连接可用；连接测试须由用户在设置页显式触发。

## 已废弃的首次上线记录（不得执行）

以下所有阶段是旧版首次上线记录，**不得作为当前发布或 Runner 配置操作指令执行**。
包括下文总则的授权/停止条件和阶段 2 的 UI 标签操作均已失效；以本页上面的
“gateway Runner 执行环境”与当前用户授权为准。备份与回退说明见上文。

本手册原先记录 `Trading-Agents-Web` 网关 Web 的首次上线边界。GitHub
`sc1994/Trading-Agents-Web` 的 `main` 是唯一权威源；Gitea
`suncheng/Trading-Agents-Web` 的 `main` 只能由批准的同步流程更新。

固定身份如下：

- 现有 Runner：`gitea-runner-gatway`
- Runner 新标签：`gateway`；保留现有 `ubuntu-latest,emailbill`
- 旧 Gitea 根提交：`052251b1a133a3aef9506b864c30d96c628c45be`
- 备份标签：`pre-github-sync-20260920-052251b1`
- Compose 项目和服务：`trading-agents-web` / `web`
- 服务回环地址：`127.0.0.1:7681`
- 公开地址：`https://trading.suncheng.online/`

## 总则与停止条件

1. 在所有实现通过审查并已进入 GitHub `main` 前，**不得**操作网关、Runner、Gitea、Docker 或 Nginx Proxy Manager。合并前只执行仓库 CI。
2. 本手册只授权读取状态、为指定 Runner 增加一个标签、执行一次固定初始化脚本，以及观察由 Gitea 工作流完成的部署。不得自行扩大权限。
3. 任何命令失败、输出与本手册的预期不同、目标机器身份不明、现场配置机制不明，或无法确认任一状态时，立即停止并联系 Multica 小队成员。
4. 不得修改 Nginx Proxy Manager。不得删除历史 Dockge Stack。不得启动、停止、删除历史 `tradingagents` Stack、历史镜像或无关容器。
5. 不得手工运行 Compose 切换、手工覆盖 `7681` 服务、手工重跑部署脚本，或用 Git 宽泛覆盖方式处理同步失败。首次部署和后续部署均由已审查的 Gitea 工作流执行。
6. 命令中绝不启用 shell tracing；不要把 token 写入 URL、仓库文件、终端历史、截图、日志或变更记录。

每个代码块都完整包在独立的 `( ... )` 子 shell 中；连同括号一起执行，变量、
readonly 声明、shell 选项和 trap 均只在该块内有效。不要拆开括号或把变量预先定义到
父 shell。每个代码块均以非零退出作为停止条件，不要在失败后跳到下一阶段。

## 阶段 0：合并后才开始

在干净的 GitHub `main` checkout 中执行。下面的变量均由紧邻的只读命令解析；先人工查看打印值，再继续。此阶段不修改远端或网关。

```bash
(
set -euo pipefail

readonly GITHUB_REMOTE='https://github.com/sc1994/Trading-Agents-Web.git'
readonly GITEA_REMOTE='https://gitea.suncheng.online:81/suncheng/Trading-Agents-Web.git'
readonly EXPECTED_OLD_SHA='052251b1a133a3aef9506b864c30d96c628c45be'
readonly BACKUP_TAG='pre-github-sync-20260920-052251b1'

test -z "$(git status --porcelain)"
LOCAL_SHA="$(git rev-parse HEAD)"
GITHUB_MAIN_SHA="$(git ls-remote "$GITHUB_REMOTE" refs/heads/main | awk 'NR == 1 { print $1 }')"
GITEA_MAIN_SHA="$(git ls-remote "$GITEA_REMOTE" refs/heads/main | awk 'NR == 1 { print $1 }')"
printf 'local=%s\ngithub-main=%s\ngitea-main=%s\n' \
  "$LOCAL_SHA" "$GITHUB_MAIN_SHA" "$GITEA_MAIN_SHA"

test "$LOCAL_SHA" = "$GITHUB_MAIN_SHA"
test "$GITEA_MAIN_SHA" = "$EXPECTED_OLD_SHA"
if [[ ! "$LOCAL_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  printf 'invalid GitHub main SHA\n' >&2
  exit 1
fi

DEPLOY_SHA="$LOCAL_SHA"
printf 'approved deployment SHA=%s\n' "$DEPLOY_SHA"
)
```

人工在 GitHub 的目标提交页面确认 Task 1 至 Task 4 的必需 CI 均为绿色，且该提交已在受保护的 `main`。无法读取或确认 CI 结论时，停止并联系 Multica 小队成员。

## 阶段 1：只读网关预检

在网关上、使用现有 Runner 所在的受控账户执行。以下命令不改变 Docker、端口或代理配置。输出仅供人工核对，不要据此清理任何对象。

```bash
(
set -euo pipefail

command -v docker
if command -v docker-compose >/dev/null 2>&1; then
  docker-compose version
else
  docker compose version
fi
command -v curl
command -v ss

printf '%s\n' 'listeners on 7681:'
ss -H -ltn 'sport = :7681'

printf '%s\n' 'containers publishing 7681 (ID/name/image/status/compose project/service):'
docker ps --filter 'publish=7681' \
  --format '{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Label "com.docker.compose.project"}}\t{{.Label "com.docker.compose.service"}}'
)
```

首次上线的预期是：Docker 和 Compose 可用，`7681` 没有监听者，且历史 Dockge
`tradingagents` Stack 仍停止。Docker 查询只列出发布 `7681` 的容器及必要字段；
历史 Stack 的停止状态仅从既有 Dockge 界面的该 Stack 页面只读确认，不扩展容器查询。
若 `ss` 或该 Docker 查询有输出、历史 Stack 状态无法确认，或 Docker/Compose 不可用，
停止并联系 Multica 小队成员；不要释放端口、修改 Stack 或调整 Docker 权限。

在既有 Nginx Proxy Manager 管理界面中以只读方式确认
`trading.suncheng.online` 仍转发到 `127.0.0.1:7681`。此检查不是修改代理的授权。
如果没有已获授权的只读查看方式，或当前路由与该目标不一致，停止并联系 Multica 小队成员。

### Actions 兼容性硬门禁：首次同步前必须通过

在激活任何部署工作流前，从现有管理界面或已确认的只读版本查询取得**实际运行的
Gitea 完整版本/构建标识**及 `gitea-runner-gatway` 的 **act_runner 完整版本/构建标识**，
并记录来源和时间。镜像的 `latest` 标签、仓库 YAML 被接受或 Runner 在线均不能证明兼容。

将这两个实际版本与对应版本的 Gitea Actions / act_runner 官方支持说明逐项核对，
并取得与现场版本、配置一致的隔离环境验证记录，或 Multica 已有的等效行为证据：

- `concurrency`：固定 group `trading-agents-web-gateway-deploy` 在各次人工触发之间
  均生效，同组部署不会同时执行；`cancel-in-progress: false` 不取消正在执行的部署。
  证据需包括工作流定义、运行 ID、排队/开始/结束时间及最终执行顺序，确认不会让旧部署
  在新部署之后覆盖运行版本。
- `permissions`：`contents: read` 实际限制工作流 token 的仓库权限，未声明权限不会
  隐式赋予写入能力。证据需证明 checkout 可读且写入被拒绝，记录权限结论而非 token。
  不得只凭 YAML 字段存在、checkout 的 `persist-credentials: false` 或文档的笼统兼容声明放行。

**任何一项不支持、被忽略、版本不明，或缺少可核验的实际行为证据，都必须停止并联系
Multica 小队成员；不得进入阶段 3，不得执行初始化或普通同步来激活部署 workflow。**
不得先同步再试验。此手册仅允许读取已有证据，不授权在真实网关或目标仓库创建验证任务、
升级组件、改权限或用其他锁替代该门禁。需要新的隔离验证时，由 Multica 安排。

## 阶段 2：为现有 Runner 增加专用标签

在 Gitea 管理界面找到名称精确为 `gitea-runner-gatway` 的现有 Runner。仅在保留
`ubuntu-latest,emailbill` 的前提下增加 `gateway` 标签。不要移除、替换或借用
`emailbill` 作为部署标签。

Runner 的注册方式、配置文件路径及服务管理器不在仓库中定义。若管理界面不能完成该标签变更，或变更需要使用不确定的配置文件、服务名、提权方式或重启命令，停止并联系 Multica 小队成员。不得猜测命令、修改其他 Runner，或重启任何其他服务。

若现有、已确认的 Runner 配置机制明确要求重启，才只重启这一个 Runner。随后在
Gitea 管理界面确认它处于在线状态，标签集合仍包含
`ubuntu-latest,emailbill,gateway`。任一条件不满足时，停止并联系 Multica 小队成员。

## 阶段 3：一次性初始化 Gitea `main`

只在阶段 0 至阶段 2 均完成，且上述 Actions 兼容性硬门禁的版本与行为证据均已记录并
核验通过后执行；证据缺失即停止，不能运行下面的代码块。以下单一受控子 shell 在远端写入前 fresh fetch
GitHub `main`，重新读取 GitHub 与 Gitea，固定唯一的 `DEPLOY_SHA`，并再次验证 Gitea
仍是固定旧根。它不会沿用任何前一代码块中的变量。若 checkout 或任一远端在此期间漂移，
命令会在读取 token 或写入前失败。

```bash
(
  set -Eeuo pipefail
  readonly GITHUB_REMOTE='https://github.com/sc1994/Trading-Agents-Web.git'
  readonly GITEA_REMOTE='https://gitea.suncheng.online:81/suncheng/Trading-Agents-Web.git'
  readonly EXPECTED_OLD_SHA='052251b1a133a3aef9506b864c30d96c628c45be'
  readonly FRESH_MAIN_REF="refs/gateway-web-preflight/main-$$"

  cleanup() {
    git update-ref -d "$FRESH_MAIN_REF" >/dev/null 2>&1 || true
    unset TRADING_AGENTS_WEB_GITEA_SYNC_TOKEN
  }
  trap cleanup EXIT INT TERM

  test -z "$(git status --porcelain)"
  git fetch --no-tags "$GITHUB_REMOTE" refs/heads/main:"$FRESH_MAIN_REF"
  DEPLOY_SHA="$(git rev-parse HEAD)"
  readonly DEPLOY_SHA
  FETCHED_GITHUB_MAIN_SHA="$(git rev-parse "$FRESH_MAIN_REF")"
  GITHUB_MAIN_SHA="$(git ls-remote "$GITHUB_REMOTE" refs/heads/main | awk 'NR == 1 { print $1 }')"
  GITEA_MAIN_SHA="$(git ls-remote "$GITEA_REMOTE" refs/heads/main | awk 'NR == 1 { print $1 }')"
  printf 'local=%s\ngithub-main-fetched=%s\ngithub-main-remote=%s\ngitea-main-before-init=%s\n' \
    "$DEPLOY_SHA" "$FETCHED_GITHUB_MAIN_SHA" "$GITHUB_MAIN_SHA" "$GITEA_MAIN_SHA"

  test "$DEPLOY_SHA" = "$FETCHED_GITHUB_MAIN_SHA"
  test "$DEPLOY_SHA" = "$GITHUB_MAIN_SHA"
  test "$GITEA_MAIN_SHA" = "$EXPECTED_OLD_SHA"

  test -z "${TRADING_AGENTS_WEB_GITEA_SYNC_TOKEN:-}"
  IFS= read -r -s -p 'Gitea sync token: ' TRADING_AGENTS_WEB_GITEA_SYNC_TOKEN
  printf '\n'
  test -n "$TRADING_AGENTS_WEB_GITEA_SYNC_TOKEN"
  export TRADING_AGENTS_WEB_GITEA_SYNC_TOKEN

  bash scripts/initialize_gitea_main.sh "$GITEA_REMOTE" "$DEPLOY_SHA"
)
```

子 shell 非零退出即停止并联系 Multica 小队成员。输入不会回显，token 只存在于该子
shell 和初始化脚本的临时 askpass 环境中；不要使用预先导出的 token，也不要把 token
传给命令行参数。不要打印环境、打开 shell tracing、复制终端回滚内容，或以其他方式重试写入。

## 阶段 4：验证初始化结果和首次工作流

初始化成功后，使用只读 Git 查询验证备份标签和两端 `main`。先读取并显示，再由命令执行精确比较。

```bash
(
set -euo pipefail

readonly GITHUB_REMOTE='https://github.com/sc1994/Trading-Agents-Web.git'
readonly GITEA_REMOTE='https://gitea.suncheng.online:81/suncheng/Trading-Agents-Web.git'
readonly EXPECTED_OLD_SHA='052251b1a133a3aef9506b864c30d96c628c45be'
readonly BACKUP_TAG='pre-github-sync-20260920-052251b1'

DEPLOY_SHA="$(git rev-parse HEAD)"
BACKUP_PEELED_SHA="$(git ls-remote "$GITEA_REMOTE" "refs/tags/${BACKUP_TAG}^{}" | awk 'NR == 1 { print $1 }')"
GITHUB_MAIN_SHA="$(git ls-remote "$GITHUB_REMOTE" refs/heads/main | awk 'NR == 1 { print $1 }')"
GITEA_MAIN_SHA="$(git ls-remote "$GITEA_REMOTE" refs/heads/main | awk 'NR == 1 { print $1 }')"
printf 'backup-peeled=%s\ngithub-main=%s\ngitea-main=%s\ndeployment=%s\n' \
  "$BACKUP_PEELED_SHA" "$GITHUB_MAIN_SHA" "$GITEA_MAIN_SHA" "$DEPLOY_SHA"

test "$BACKUP_PEELED_SHA" = "$EXPECTED_OLD_SHA"
test "$GITHUB_MAIN_SHA" = "$DEPLOY_SHA"
test "$GITEA_MAIN_SHA" = "$DEPLOY_SHA"
)
```

在 Gitea 的 `suncheng/Trading-Agents-Web` Actions 页面找到本次 `main` 推送生成的首次工作流。确认：

- 工作流目标提交精确等于 `DEPLOY_SHA`；
- 执行 Runner 是 `gitea-runner-gatway`，并具有 `gateway` 标签；
- 对该 `DEPLOY_SHA` 已审版本的 `scripts/deploy_gateway_web.sh` 核对固定顺序：端口
  所有者检查、候选镜像和 revision 检查、隔离候选容器的精确健康/页面检查、候选删除，
  然后才是 Compose 切换和本机回环检查；切换后失败由脚本恢复旧镜像，首次失败则停止服务；
- 工作流成功，证明上述 fail-fast 脚本检查全部通过；不要要求工作流日志输出不存在的
  “候选先于切换”阶段标记；
- 工作流没有读取同步 token 或应用密钥。

若工作流排队未被该 Runner 接收、失败、目标 SHA 不同，或无法确认任一项，停止并联系 Multica 小队成员。失败调查仅收集该工作流和本服务的只读证据；不得手工启动历史 Stack、修改 Nginx Proxy Manager、删除镜像或操作无关容器。

## 阶段 5：Docker 与回环验收

仅在首次工作流显示成功后，于网关 checkout 中执行。此代码块只读取 Docker 状态和发起 HTTP GET；临时目录在退出时移除。

```bash
(
set -euo pipefail

DEPLOY_SHA="$(git rev-parse HEAD)"
if [[ ! "$DEPLOY_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  printf 'invalid deployment SHA\n' >&2
  exit 1
fi

WEB_CONTAINER_IDS="$(docker ps \
  --filter 'label=com.docker.compose.project=trading-agents-web' \
  --filter 'label=com.docker.compose.service=web' \
  --format '{{.ID}}')"
WEB_CONTAINER_COUNT="$(printf '%s\n' "$WEB_CONTAINER_IDS" | awk 'NF { count++ } END { print count + 0 }')"
printf 'web-container-count=%s\n%s\n' "$WEB_CONTAINER_COUNT" "$WEB_CONTAINER_IDS"
test "$WEB_CONTAINER_COUNT" -eq 1
WEB_CONTAINER_ID="$(printf '%s\n' "$WEB_CONTAINER_IDS" | awk 'NF { print; exit }')"

RUNNING_IMAGE="$(docker inspect --format '{{.Config.Image}}' "$WEB_CONTAINER_ID")"
RUNNING_IMAGE_ID="$(docker inspect --format '{{.Image}}' "$WEB_CONTAINER_ID")"
CONTAINER_REVISION="$(docker inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$WEB_CONTAINER_ID")"
IMAGE_REVISION="$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$RUNNING_IMAGE_ID")"
HEALTH_STATUS="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$WEB_CONTAINER_ID")"
printf 'container=%s\nimage=%s\nimage-id=%s\ncontainer-revision=%s\nimage-revision=%s\nhealth=%s\n' \
  "$WEB_CONTAINER_ID" "$RUNNING_IMAGE" "$RUNNING_IMAGE_ID" "$CONTAINER_REVISION" "$IMAGE_REVISION" "$HEALTH_STATUS"

test "$RUNNING_IMAGE" = "trading-agents-web-ui:${DEPLOY_SHA}"
test "$CONTAINER_REVISION" = "$DEPLOY_SHA"
test "$IMAGE_REVISION" = "$DEPLOY_SHA"
test "$HEALTH_STATUS" = healthy

RESULT_DIR="$(mktemp -d)"
trap 'rm -rf -- "$RESULT_DIR"' EXIT
docker cp "${WEB_CONTAINER_ID}:/app/web/client/dist/index.html" "$RESULT_DIR/image-index.html"
curl --fail --silent --show-error --connect-timeout 2 --max-time 5 \
  --output "$RESULT_DIR/local-health" http://127.0.0.1:7681/healthz
printf 'ok\n' | cmp -s - "$RESULT_DIR/local-health"
curl --fail --silent --show-error --connect-timeout 2 --max-time 5 \
  --output "$RESULT_DIR/local-page" http://127.0.0.1:7681/
cmp -s "$RESULT_DIR/local-page" "$RESULT_DIR/image-index.html"
)
```

成功条件是恰有一个健康的 `trading-agents-web` / `web` 容器，其镜像名、容器
revision 和镜像 revision 都等于 `DEPLOY_SHA`；本机 `/healthz` 精确为 `ok` 加换行，
本机根页面与运行镜像中的 `web/client/dist/index.html` 字节相同。
私有网络入口另由获授权维护者验证，不能复用旧空白页的公开入口验收。

自动回退仅发生在 workflow 内部署脚本的切换或切换后验证失败时：存在旧镜像则尝试
恢复旧镜像，首次失败则尝试停止失败服务，具体结果以该次失败工作流的证据为准。
阶段 5 在 workflow 已成功结束后独立执行，此时的 Docker 或回环验收失败**不会触发
自动回退，也不能据此声称已尝试回退**。应停止并联系 Multica 小队成员，保留当前状态，
仅收集本服务的只读证据进行人工调查；不要在现场切换或清理。
若本机通过但私有入口页面失败，保留健康回环服务，停止并联系 Multica 小队成员，将其作为
代理入口问题处理；不得修改 Nginx Proxy Manager。

## 阶段 6：证据记录与后续普通同步

在变更记录中保存以下非敏感证据。不要保存 token、环境变量转储或含凭据的 URL。

- GitHub `main` 完整 SHA 与 Gitea `main` 完整 SHA
- 备份标签 `pre-github-sync-20260920-052251b1` 的 peeled SHA
- 实际 Gitea / act_runner 版本、查询来源与时间、对应版本的支持说明，以及
  `concurrency` / `permissions` 行为验证证据和门禁核验结论
- 首次 Gitea workflow URL、运行 ID、结果、目标 SHA 和 Runner 名称
- 容器 ID、镜像 ID、镜像名、两个 revision 值、健康状态
- 本机 `/healthz`、本机页面和私有入口页面的验收时间与结果
- 执行人、变更单号，以及任何停止条件的原始非敏感输出

首次初始化完成后，后续只允许 GitHub `main` 通过
`.github/workflows/sync-gitea.yml` 的普通同步到达 Gitea，再由 Gitea 部署工作流串行发布。不要再次运行初始化脚本，不要手工同步 token，也不要手工部署。

后续提交的只读同步核对可使用：

```bash
(
set -euo pipefail

readonly GITHUB_REMOTE='https://github.com/sc1994/Trading-Agents-Web.git'
readonly GITEA_REMOTE='https://gitea.suncheng.online:81/suncheng/Trading-Agents-Web.git'
GITHUB_MAIN_SHA="$(git ls-remote "$GITHUB_REMOTE" refs/heads/main | awk 'NR == 1 { print $1 }')"
GITEA_MAIN_SHA="$(git ls-remote "$GITEA_REMOTE" refs/heads/main | awk 'NR == 1 { print $1 }')"
printf 'github-main=%s\ngitea-main=%s\n' "$GITHUB_MAIN_SHA" "$GITEA_MAIN_SHA"
test "$GITHUB_MAIN_SHA" = "$GITEA_MAIN_SHA"
)
```

若常规同步因非快进、漂移或权限问题失败，保持 GitHub 为权威源并停止并联系 Multica 小队成员；不得覆盖 Gitea 分歧。

## 文档自审

提交前可执行以下只读扫描。它只用于检查本手册，不是自动化测试。

```bash
(
set -euo pipefail
! rg -n -i 'TB[D]|TO[D]O|implement[[:space:]]+later|fill[[:space:]]+in' \
  docs/operations/gateway-web-deployment.md
)
```
