# 网关 Web 首次上线运维手册

本手册是 `Trading-Agents-Web` 网关 Web 的首次上线边界。GitHub
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

每个代码块均以非零退出作为停止条件。不要在失败后跳到下一阶段。

## 阶段 0：合并后才开始

在干净的 GitHub `main` checkout 中执行。下面的变量均由紧邻的只读命令解析；先人工查看打印值，再继续。此阶段不修改远端或网关。

```bash
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
case "$LOCAL_SHA" in [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
  *) printf 'invalid GitHub main SHA\n' >&2; exit 1 ;;
esac

DEPLOY_SHA="$LOCAL_SHA"
printf 'approved deployment SHA=%s\n' "$DEPLOY_SHA"
```

人工在 GitHub 的目标提交页面确认 Task 1 至 Task 4 的必需 CI 均为绿色，且该提交已在受保护的 `main`。无法读取或确认 CI 结论时，停止并联系 Multica 小队成员。

## 阶段 1：只读网关预检

在网关上、使用现有 Runner 所在的受控账户执行。以下命令不改变 Docker、端口或代理配置。输出仅供人工核对，不要据此清理任何对象。

```bash
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

printf '%s\n' 'running containers mentioning TradingAgents:'
docker ps --format '{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Labels}}'

printf '%s\n' 'existing gateway web project containers:'
docker ps --all \
  --filter 'label=com.docker.compose.project=trading-agents-web' \
  --filter 'label=com.docker.compose.service=web' \
  --format '{{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Labels}}'
```

首次上线的预期是：Docker 和 Compose 可用，`7681` 没有监听者，且历史 Dockge
`tradingagents` Stack 仍停止。若 `ss` 有输出、历史 Stack 状态无法从既有 Dockge
界面与容器列表确认，或 Docker/Compose 不可用，停止并联系 Multica 小队成员；不要释放端口、修改 Stack 或调整 Docker 权限。

在既有 Nginx Proxy Manager 管理界面中以只读方式确认
`trading.suncheng.online` 仍转发到 `127.0.0.1:7681`。此检查不是修改代理的授权。
如果没有已获授权的只读查看方式，或当前路由与该目标不一致，停止并联系 Multica 小队成员。

## 阶段 2：为现有 Runner 增加专用标签

在 Gitea 管理界面找到名称精确为 `gitea-runner-gatway` 的现有 Runner。仅在保留
`ubuntu-latest,emailbill` 的前提下增加 `gateway` 标签。不要移除、替换或借用
`emailbill` 作为部署标签。

Runner 的注册方式、配置文件路径及服务管理器不在仓库中定义。若管理界面不能完成该标签变更，或变更需要使用不确定的配置文件、服务名、提权方式或重启命令，停止并联系 Multica 小队成员。不得猜测命令、修改其他 Runner，或重启任何其他服务。

若现有、已确认的 Runner 配置机制明确要求重启，才只重启这一个 Runner。随后在
Gitea 管理界面确认它处于在线状态，标签集合仍包含
`ubuntu-latest,emailbill,gateway`。任一条件不满足时，停止并联系 Multica 小队成员。

## 阶段 3：一次性初始化 Gitea `main`

只在阶段 0 至阶段 2 均完成后执行。以下单一受控子 shell 在远端写入前 fresh fetch
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
    unset GITEA_MIRROR_SYNC_TOKEN
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

  test -z "${GITEA_MIRROR_SYNC_TOKEN:-}"
  IFS= read -r -s -p 'Gitea sync token: ' GITEA_MIRROR_SYNC_TOKEN
  printf '\n'
  test -n "$GITEA_MIRROR_SYNC_TOKEN"
  export GITEA_MIRROR_SYNC_TOKEN

  bash scripts/initialize_gitea_main.sh "$GITEA_REMOTE" "$DEPLOY_SHA"
)
```

子 shell 非零退出即停止并联系 Multica 小队成员。输入不会回显，token 只存在于该子
shell 和初始化脚本的临时 askpass 环境中；不要使用预先导出的 token，也不要把 token
传给命令行参数。不要打印环境、打开 shell tracing、复制终端回滚内容，或以其他方式重试写入。

## 阶段 4：验证初始化结果和首次工作流

初始化成功后，使用只读 Git 查询验证备份标签和两端 `main`。先读取并显示，再由命令执行精确比较。

```bash
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

## 阶段 5：Docker、回环与公开入口验收

仅在首次工作流显示成功后，于网关 checkout 中执行。此代码块只读取 Docker 状态和发起 HTTP GET；临时目录在退出时移除。

```bash
set -euo pipefail

DEPLOY_SHA="$(git rev-parse HEAD)"
case "$DEPLOY_SHA" in
  [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
  *) printf 'invalid deployment SHA\n' >&2; exit 1 ;;
esac

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
curl --fail --silent --show-error --connect-timeout 2 --max-time 5 \
  --output "$RESULT_DIR/local-health" http://127.0.0.1:7681/healthz
printf 'ok\n' | cmp -s - "$RESULT_DIR/local-health"
curl --fail --silent --show-error --connect-timeout 2 --max-time 5 \
  --output "$RESULT_DIR/local-page" http://127.0.0.1:7681/
cmp -s "$RESULT_DIR/local-page" web/index.html
curl --fail --silent --show-error --connect-timeout 2 --max-time 10 \
  --output "$RESULT_DIR/public-page" https://trading.suncheng.online/
cmp -s "$RESULT_DIR/public-page" web/index.html
```

成功条件是恰有一个健康的 `trading-agents-web` / `web` 容器，其镜像名、容器
revision 和镜像 revision 都等于 `DEPLOY_SHA`；本机 `/healthz` 精确为 `ok` 加换行，
本机和公开根页面均与 `web/index.html` 字节相同。

若本机回环验收失败，停止并联系 Multica 小队成员。工作流已按脚本契约尝试恢复旧镜像；不要在现场再切换或清理。若本机通过但公开页面失败，保留健康回环服务，停止并联系 Multica 小队成员，将其作为代理入口问题处理；不得修改 Nginx Proxy Manager。

## 阶段 6：证据记录与后续普通同步

在变更记录中保存以下非敏感证据。不要保存 token、环境变量转储或含凭据的 URL。

- GitHub `main` 完整 SHA 与 Gitea `main` 完整 SHA
- 备份标签 `pre-github-sync-20260920-052251b1` 的 peeled SHA
- 首次 Gitea workflow URL、运行 ID、结果、目标 SHA 和 Runner 名称
- 容器 ID、镜像 ID、镜像名、两个 revision 值、健康状态
- 本机 `/healthz`、本机页面和公开页面的验收时间与结果
- 执行人、变更单号，以及任何停止条件的原始非敏感输出

首次初始化完成后，后续只允许 GitHub `main` 通过
`.github/workflows/sync-gitea.yml` 的普通同步到达 Gitea，再由 Gitea 部署工作流串行发布。不要再次运行初始化脚本，不要手工同步 token，也不要手工部署。

后续提交的只读同步核对可使用：

```bash
set -euo pipefail

readonly GITHUB_REMOTE='https://github.com/sc1994/Trading-Agents-Web.git'
readonly GITEA_REMOTE='https://gitea.suncheng.online:81/suncheng/Trading-Agents-Web.git'
GITHUB_MAIN_SHA="$(git ls-remote "$GITHUB_REMOTE" refs/heads/main | awk 'NR == 1 { print $1 }')"
GITEA_MAIN_SHA="$(git ls-remote "$GITEA_REMOTE" refs/heads/main | awk 'NR == 1 { print $1 }')"
printf 'github-main=%s\ngitea-main=%s\n' "$GITHUB_MAIN_SHA" "$GITEA_MAIN_SHA"
test "$GITHUB_MAIN_SHA" = "$GITEA_MAIN_SHA"
```

若常规同步因非快进、漂移或权限问题失败，保持 GitHub 为权威源并停止并联系 Multica 小队成员；不得覆盖 Gitea 分歧。

## 文档自审

提交前可执行以下只读扫描。它只用于检查本手册，不是自动化测试。

```bash
set -euo pipefail
! rg -n -i 'TB[D]|TO[D]O|implement[[:space:]]+later|fill[[:space:]]+in' \
  docs/operations/gateway-web-deployment.md
```
