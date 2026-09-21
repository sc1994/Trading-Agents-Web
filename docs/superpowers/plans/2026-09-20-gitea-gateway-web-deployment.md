# Gitea 网关 Web 自动部署实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 建立从 GitHub `main` 安全同步到 Gitea，再由网关 Runner 自动构建、验证并部署空白 Web 页面的完整链路。

**架构：** GitHub `main` 仍是唯一权威源；独立的一次性初始化脚本只负责备份并替换当前 Gitea 独立根提交，现有同步脚本继续只执行普通快进推送。Gitea 中带 `gateway` 标签的 Runner 构建提交 SHA 镜像，先检查隔离候选容器，再通过固定 Compose 项目切换 `127.0.0.1:7681` 服务，失败时恢复旧镜像。

**技术栈：** Bash、Python 3.10-3.13 标准库、pytest、PyYAML、Docker Engine、Docker Compose、GitHub Actions、Gitea Actions。

**规格：** `docs/superpowers/specs/2026-09-20-gitea-gateway-web-deployment-design.md`

## 全局约束

- GitHub `sc1994/Trading-Agents-Web` 的 `main` 是唯一权威代码源。
- Gitea 目标固定为 `suncheng/Trading-Agents-Web` 的 `main`。
- Gitea 当前旧提交固定为 `052251b1a133a3aef9506b864c30d96c628c45be`；初始化备份标签固定为 `pre-github-sync-20260920-052251b1`。
- 一次性初始化只能对上述旧 SHA 使用精确 `force-with-lease`；日常同步继续只允许普通 `HEAD:refs/heads/main` 推送。
- Web 容器固定监听容器端口 `8080`，宿主机只绑定 `127.0.0.1:7681`。
- Compose 项目名固定为 `trading-agents-web`，服务名固定为 `web`，镜像名固定为 `trading-agents-web-ui:<40 位小写提交 SHA>`。
- 镜像和容器都必须包含 `org.opencontainers.image.revision=<SHA>`。
- Web 服务只提供 `/`、`/index.html`、`/healthz` 和 404；空白页不得出现可见产品内容。
- Web 容器不读取 `.env`、LLM/行情 API 密钥、TradingAgents 数据目录或 Docker socket。
- Gitea 部署工作流只使用 `gateway` Runner 标签，权限为 `contents: read`，不读取同步 token 或应用密钥。
- 构建或候选检查失败不得修改运行服务；切换后检查失败时恢复旧镜像，首次部署失败时停止失败服务。
- 不清理历史镜像，不修改 Nginx Proxy Manager，不启动或删除历史 Dockge Stack，不修改无关容器。
- 网关、Runner 和 Gitea 的实际变更只能在仓库代码通过审查、进入 GitHub `main` 后执行。

---

## 文件职责映射

- `scripts/initialize_gitea_main.sh`：一次性校验 Gitea 旧根提交、创建带说明的备份标签，并用精确租约替换 `main`。
- `tests/infra/test_initialize_gitea.py`：用临时 Git 仓库覆盖初始化成功、前置条件变化和租约竞态。
- `web/server.py`：仅用 Python 标准库提供空白页与健康检查。
- `web/index.html`：无可见内容的最小 HTML 文档。
- `web/Dockerfile`：构建非 root、无业务依赖的 Web 镜像。
- `tests/infra/test_gateway_web.py`：验证 HTTP 字节、HEAD、404、端口校验和 Dockerfile 安全属性。
- `docker-compose.gateway-web.yml`：声明固定回环端口、健康检查和容器安全配置。
- `scripts/deploy_gateway_web.sh`：构建候选镜像、候选检查、Compose 切换、上线检查和失败回退。
- `tests/infra/test_gateway_web_deployment.py`：通过伪 Docker/Compose/Curl 命令验证部署顺序、失败保护、回退和静态配置。
- `.gitea/workflows/deploy-gateway-web.yml`：只在目标 Gitea 仓库的 `main` 上向 `gateway` Runner 派发部署。
- `.github/workflows/ci.yml`：在现有 pytest/ruff 之外增加 Web 镜像构建检查。
- `docs/operations/gateway-web-deployment.md`：记录 Runner 标签、首次同步和上线验收的人工操作边界。
- `tests/infra/test_gateway_web_operations.py`：验证运维手册包含必要保护条件，且没有危险的宽泛操作。

---

### Task 1：实现受保护的一次性 Gitea 初始化

**Files:**
- Create: `scripts/initialize_gitea_main.sh`
- Create: `tests/infra/test_initialize_gitea.py`

**Interfaces:**
- Consumes: 当前 checkout 的 GitHub 提交、`REMOTE_URL`、`EXPECTED_NEW_SHA`；HTTPS 时从 `TRADING_AGENTS_WEB_GITEA_SYNC_TOKEN` 读取凭据。
- Produces: `bash scripts/initialize_gitea_main.sh REMOTE_URL EXPECTED_NEW_SHA`；成功后远端备份标签 peel 到固定旧 SHA，远端 `main` 等于 `EXPECTED_NEW_SHA`。

- [ ] **Step 1：先写初始化成功的集成测试**

在测试中创建两个无共同历史的仓库：source 含新 `main`，bare target 的旧 `main` 只有空 `README.md`。调用脚本后验证备份标签和新 `main`：

```python
BACKUP_TAG = "pre-github-sync-20260920-052251b1"


def test_initialization_backs_up_old_root_and_replaces_main(tmp_path: Path) -> None:
    source, target, new_sha = make_initialization_fixture(tmp_path)
    old_sha = git(source, "--git-dir", str(target), "rev-parse", "refs/heads/main")
    result = run(
        "bash",
        str(SCRIPT),
        target.resolve().as_uri(),
        new_sha,
        cwd=source,
        env={**os.environ, "GITEA_INITIALIZE_TEST_OLD_SHA": old_sha},
    )
    assert "initialized" in result.stdout
    assert remote_sha(source, target, "refs/heads/main") == new_sha
    assert remote_sha(source, target, f"refs/tags/{BACKUP_TAG}^{{}}") == old_sha
```

`GITEA_INITIALIZE_TEST_OLD_SHA` 是严格限制在 `file://` 远端的测试注入点。脚本处理
`https://` 时如果发现该变量非空必须立即拒绝；生产路径始终使用设计中固定的旧 SHA，
命令行也不提供覆盖旧 SHA 的参数。

- [ ] **Step 2：运行测试并确认因脚本不存在而失败**

Run: `pytest -q tests/infra/test_initialize_gitea.py::test_initialization_backs_up_old_root_and_replaces_main`

Expected: FAIL，错误包含 `scripts/initialize_gitea_main.sh` 不存在。

- [ ] **Step 3：实现最小初始化脚本**

脚本沿用 `scripts/sync_gitea_main.sh` 的 HTTPS askpass 方式，但把初始化能力隔离在单独入口。核心检查与写入顺序固定如下：

```bash
expected_old_sha="052251b1a133a3aef9506b864c30d96c628c45be"
readonly backup_tag="pre-github-sync-20260920-052251b1"

if [[ "$remote_url" == file://* ]]; then
  expected_old_sha="${GITEA_INITIALIZE_TEST_OLD_SHA:-$expected_old_sha}"
elif [[ -n "${GITEA_INITIALIZE_TEST_OLD_SHA:-}" ]]; then
  printf 'test old SHA override is forbidden for HTTPS\n' >&2
  exit 7
fi
readonly expected_old_sha

test "$(git rev-parse HEAD)" = "$expected_new_sha"
git fetch --no-tags "$remote_url" \
  refs/heads/main:refs/gitea-initialize/main
observed_old_sha="$(git rev-parse refs/gitea-initialize/main)"
test "$observed_old_sha" = "$expected_old_sha"
test "$(git rev-list --parents -n 1 "$observed_old_sha" | wc -w)" -eq 1
test "$(git ls-tree -r --name-only "$observed_old_sha")" = "README.md"
test -z "$(git show "${observed_old_sha}:README.md")"

temporary_tag="gitea-initialize-$$"
git -c user.name='Trading Agents Sync' \
    -c user.email='sync@invalid.local' \
    tag -a "$temporary_tag" "$observed_old_sha" \
    -m "Backup Gitea main before GitHub synchronization"
remote_tag_sha="$(git ls-remote "$remote_url" "refs/tags/${backup_tag}^{}" | awk 'NR == 1 {print $1}')"
if [[ -z "$remote_tag_sha" ]]; then
  git push "$remote_url" \
    "refs/tags/${temporary_tag}:refs/tags/${backup_tag}"
else
  test "$remote_tag_sha" = "$expected_old_sha"
fi
test "$(git ls-remote "$remote_url" "refs/tags/${backup_tag}^{}" | awk 'NR == 1 {print $1}')" = \
  "$expected_old_sha"
git push --force-with-lease="refs/heads/main:${expected_old_sha}" \
  "$remote_url" HEAD:refs/heads/main
test "$(git ls-remote "$remote_url" refs/heads/main | awk 'NR == 1 {print $1}')" = \
  "$expected_new_sha"
```

用 `trap` 删除临时本地引用、askpass 文件和 `refs/gitea-initialize/main`。生产只允许 `https://`，测试只额外允许 `file://`；拒绝短 SHA、非当前 HEAD 和其他 URL scheme。

- [ ] **Step 4：补齐所有拒绝与竞态测试**

增加以下独立测试，每个测试都断言脚本非零退出，并检查远端 `main` 未被脚本覆盖：

- `test_rejects_changed_old_main_without_creating_tag`：目标 `main` 指向另一个根提交，断言备份 tag 不存在。
- `test_rejects_old_commit_with_parent`：测试旧 SHA 指向有父提交的 commit，断言无远端引用变化。
- `test_rejects_old_tree_with_extra_file`：旧提交树增加 `extra.txt`，断言无远端引用变化。
- `test_rejects_nonempty_readme`：旧树仍只有 `README.md`，但 blob 非空，断言无远端引用变化。
- `test_rejects_arbitrary_expected_old_sha_argument`：传入第三个位置参数，断言 usage 错误且未执行 fetch/push。
- `test_rejects_test_old_sha_override_for_https`：使用 HTTPS URL 和测试覆盖变量，断言在调用 Git 前退出。
- `test_reuses_existing_backup_tag_only_when_it_peels_to_old_sha`：预建指向旧 SHA 的 annotated tag，断言初始化成功且没有重写 tag object。
- `test_rejects_conflicting_existing_backup_tag`：预建指向其他 commit 的同名 tag，断言 `main` 不变。
- `test_exact_lease_rejects_main_race_after_backup_tag`：在备份 tag 创建后通过 Git hook 推进 target `main`，断言竞态提交仍是 `main`。
- `test_script_contains_no_mirror_wildcard_or_delete`：读取脚本文本，拒绝 `--mirror`、`--delete`、通配 refspec 和不带租约的 force。
- `test_https_requires_sync_token_before_git`：清除 token 后使用 HTTPS URL，断言 stderr 包含 token 缺失说明。

租约竞态允许已经安全创建的备份 tag 保留；脚本再次执行时必须验证该 tag peel 到固定旧 SHA，绝不能删除或改写已有 tag。

- [ ] **Step 5：运行初始化测试和现有日常同步回归**

Run: `pytest -q tests/infra/test_initialize_gitea.py tests/infra/test_sync_gitea.py`

Expected: PASS；现有 `scripts/sync_gitea_main.sh` 仍不包含 `--force`、`--mirror` 或 `--delete`。

- [ ] **Step 6：提交初始化实现**

```bash
git add scripts/initialize_gitea_main.sh tests/infra/test_initialize_gitea.py
git commit -m "feat: guard initial gitea main synchronization"
```

---

### Task 2：实现空白 Web 服务和安全镜像

**Files:**
- Create: `web/server.py`
- Create: `web/index.html`
- Create: `web/Dockerfile`
- Create: `tests/infra/test_gateway_web.py`

**Interfaces:**
- Consumes: `WEB_HOST`，默认 `0.0.0.0`；`WEB_PORT`，默认 `8080`。
- Produces: `create_server(host: str | None = None, port: int | None = None) -> ThreadingHTTPServer`；`GET/HEAD /`、`GET/HEAD /index.html`、`GET/HEAD /healthz`。

- [ ] **Step 1：写 HTTP 行为和端口校验测试**

测试启动真实本地临时端口，逐项断言：

```python
def test_root_and_index_return_exact_checked_in_bytes(running_server: str) -> None:
    for path in ("/", "/index.html"):
        with urlopen(f"{running_server}{path}", timeout=2) as response:
            assert response.status == 200
            assert response.read() == INDEX.read_bytes()


def test_healthz_returns_exact_body(running_server: str) -> None:
    with urlopen(f"{running_server}/healthz", timeout=2) as response:
        assert response.read() == b"ok\n"


def test_head_returns_headers_without_body(running_server: str) -> None:
    request = Request(f"{running_server}/", method="HEAD")
    with urlopen(request, timeout=2) as response:
        assert response.status == 200
        assert response.headers["Content-Length"] == str(len(INDEX.read_bytes()))
        assert response.read() == b""


def test_unknown_path_returns_404(running_server: str) -> None:
    with pytest.raises(HTTPError) as error:
        urlopen(f"{running_server}/missing", timeout=2)
    assert error.value.code == 404


@pytest.mark.parametrize("value", ["zero", "0", "65536", "-1"])
def test_invalid_environment_ports_are_rejected(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("WEB_PORT", value)
    with pytest.raises(ValueError, match="WEB_PORT"):
        server_module.create_server()
```

- [ ] **Step 2：运行测试并确认因 Web 文件不存在而失败**

Run: `pytest -q tests/infra/test_gateway_web.py`

Expected: FAIL，导入或启动 `web/server.py` 失败。

- [ ] **Step 3：实现最小标准库服务器和空白页面**

`web/index.html` 使用没有可见正文的有效文档：

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title></title>
</head>
<body></body>
</html>
```

`web/server.py` 缓存 `index.html` 原始字节；用 `urlsplit(self.path).path` 匹配路径；所有响应设置精确 `Content-Length`、`Cache-Control: no-store` 和 `X-Content-Type-Options: nosniff`。`HEAD` 复用 GET 路由但不写 body，端口必须在 `1..65535`，测试显式传 `port=0` 时允许操作系统分配临时端口。

- [ ] **Step 4：增加 Dockerfile 静态契约测试并观察失败**

```python
def test_dockerfile_runs_as_non_root_python_312_alpine() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert text.startswith("FROM python:3.12-alpine\n")
    assert "USER web" in text
    assert 'CMD ["python", "server.py"]' in text
    assert "COPY --chown=web:web web/server.py web/index.html ./" in text
```

Run: `pytest -q tests/infra/test_gateway_web.py::test_dockerfile_runs_as_non_root_python_312_alpine`

Expected: FAIL，因为 `web/Dockerfile` 尚不存在。

- [ ] **Step 5：实现非 root Web 镜像并运行本任务测试**

```dockerfile
FROM python:3.12-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WEB_HOST=0.0.0.0 \
    WEB_PORT=8080

WORKDIR /app
RUN addgroup -S web && adduser -S -G web web
COPY --chown=web:web web/server.py web/index.html ./
USER web
EXPOSE 8080
CMD ["python", "server.py"]
```

Run: `pytest -q tests/infra/test_gateway_web.py && ruff check web/server.py tests/infra/test_gateway_web.py`

Expected: PASS。

- [ ] **Step 6：提交 Web 服务**

```bash
git add web tests/infra/test_gateway_web.py
git commit -m "feat: add blank gateway web service"
```

---

### Task 3：实现 Compose 契约和可回退部署脚本

**Files:**
- Create: `docker-compose.gateway-web.yml`
- Create: `scripts/deploy_gateway_web.sh`
- Create: `tests/infra/test_gateway_web_deployment.py`

**Interfaces:**
- Consumes: 唯一位置参数 `FULL_SHA`；Docker、Docker Compose、curl；固定文件 `web/index.html`。
- Produces: 固定 Compose 项目 `trading-agents-web` 的 `web` 服务；成功镜像 `trading-agents-web-ui:<FULL_SHA>`；失败时非零退出并保持或恢复先前状态。

- [ ] **Step 1：写 Compose 安全与追溯契约测试**

```python
def test_compose_binds_only_fixed_loopback_port_and_has_no_secrets() -> None:
    service = load_yaml(COMPOSE)["services"]["web"]
    assert service["image"] == "${TRADINGAGENTS_WEB_IMAGE:?required}"
    assert service["ports"] == ["127.0.0.1:7681:8080"]
    assert service["restart"] == "unless-stopped"
    assert service["read_only"] == "true"
    assert service["cap_drop"] == ["ALL"]
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert "env_file" not in service
    assert "volumes" not in service
    assert "/healthz" in " ".join(service["healthcheck"]["test"])


def test_compose_sets_revision_label_from_required_sha() -> None:
    service = load_yaml(COMPOSE)["services"]["web"]
    assert service["labels"] == {
        "org.opencontainers.image.revision": "${TRADINGAGENTS_WEB_REVISION:?required}"
    }
```

- [ ] **Step 2：运行 Compose 测试并确认文件不存在**

Run: `pytest -q tests/infra/test_gateway_web_deployment.py -k compose`

Expected: FAIL，因为 `docker-compose.gateway-web.yml` 不存在。

- [ ] **Step 3：实现固定 Compose 定义**

Compose 只引用外部已构建镜像，不在切换阶段重新 build：

```yaml
services:
  web:
    image: ${TRADINGAGENTS_WEB_IMAGE:?required}
    labels:
      org.opencontainers.image.revision: ${TRADINGAGENTS_WEB_REVISION:?required}
    ports:
      - "127.0.0.1:7681:8080"
    restart: unless-stopped
    read_only: true
    cap_drop: [ALL]
    security_opt:
      - no-new-privileges:true
    tmpfs:
      - /tmp:rw,noexec,nosuid,size=16m
    healthcheck:
      test: [CMD, python, -c, 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8080/healthz", timeout=2).read()']
      interval: 5s
      timeout: 3s
      retries: 6
      start_period: 2s
```

- [ ] **Step 4：写伪命令部署测试并确认脚本不存在**

测试把 `docker`、`docker-compose` 和 `curl` fake 放到临时 `PATH`，所有调用逐行
追加到日志。fake Docker 根据 `FAKE_EXISTING_IMAGE`、`FAKE_CANDIDATE_HEALTH`、
`FAKE_LIVE_HEALTH` 和 `FAKE_PORT_OWNER` 返回确定结果；fake curl 根据 URL 写出
`ok\n`、`web/index.html` 原始字节或指定失败码。覆盖：

- `test_candidate_is_verified_before_compose_cutover`：健康候选和空闲端口，断言 build、候选 run、两次 curl、候选 rm 全部早于第一次 Compose up。
- `test_candidate_failure_never_calls_compose_up`：候选 `/healthz` 失败，断言非零退出、候选被删除、日志没有 Compose up/stop。
- `test_port_conflict_fails_before_build`：端口属于非本项目容器，断言 stderr 报告 owner，日志没有 build。
- `test_post_cutover_failure_restores_previous_image`：预置旧镜像且 live 检查失败，断言第二次 Compose up 使用旧镜像和旧 revision，最终仍非零退出。
- `test_failed_first_deployment_stops_service`：无旧容器且 live 检查失败，断言调用 Compose stop 且没有伪造旧镜像。
- `test_rejects_short_or_uppercase_sha_before_docker`：分别传 `abc` 和 40 位大写 SHA，断言 Docker 日志为空。
- `test_script_never_prunes_images_or_changes_proxy`：读取脚本文本，断言不存在 `prune`、NPM API、`docker image rm` 或历史 Stack 名称。

关键顺序断言：

```python
calls = fake_commands.calls()
assert calls.index(f"docker build --label org.opencontainers.image.revision={SHA}") \
    < calls.index("docker run candidate") \
    < calls.index("compose up web")
```

Run: `pytest -q tests/infra/test_gateway_web_deployment.py -k 'not compose'`

Expected: FAIL，因为 `scripts/deploy_gateway_web.sh` 不存在。

- [ ] **Step 5：实现候选优先、失败回退的部署脚本**

脚本固定这些值，禁止环境覆盖端口、项目名和镜像库：

```bash
readonly project_name="trading-agents-web"
readonly image_repository="trading-agents-web-ui"
readonly host_port="7681"
readonly image_ref="${image_repository}:${sha}"
readonly candidate_name="trading-agents-web-candidate-${sha}-$$"
```

实现顺序：

1. 校验 SHA、Docker、Compose、curl，并确认 `127.0.0.1:7681` 未被非本项目容器/进程占用。
2. `docker build --label "org.opencontainers.image.revision=$sha" --tag "$image_ref" --file web/Dockerfile .`。
3. `docker image inspect` 验证 revision label 精确匹配。
4. 用 `docker run --detach --rm --read-only --cap-drop ALL --security-opt no-new-privileges --tmpfs /tmp:rw,noexec,nosuid,size=16m --publish 127.0.0.1::8080 "$image_ref"` 启动候选，读取随机宿主端口，逐字节检查 `/healthz` 和 `/`，并通过 trap 删除候选。
5. 从现有 Compose 容器 label 读取旧镜像引用；设置 `TRADINGAGENTS_WEB_IMAGE` 和 `TRADINGAGENTS_WEB_REVISION` 后执行 `compose up --detach --no-build web`。
6. 等待 Docker health 为 `healthy`，再检查固定回环 URL 和空白页字节。
7. 上线检查失败且有旧镜像时，从旧镜像读取 revision、重新 `compose up` 并验证恢复；没有旧镜像时执行 `compose stop web`。最后保留原始失败状态码。

页面比较不能使用 shell command substitution，因为它会剥离尾部换行；必须把 curl 结果和 `web/index.html` 写入临时文件后用 `cmp -s` 比较。

- [ ] **Step 6：运行部署脚本测试和 Compose 渲染检查**

Run:

```bash
pytest -q tests/infra/test_gateway_web_deployment.py
TRADINGAGENTS_WEB_IMAGE="trading-agents-web-ui:$(printf 'a%.0s' {1..40})" \
TRADINGAGENTS_WEB_REVISION="$(printf 'a%.0s' {1..40})" \
docker compose --project-name trading-agents-web \
  --file docker-compose.gateway-web.yml config --quiet
```

Expected: pytest PASS；Compose 配置退出 0。若开发机没有 Docker Compose，只报告该环境限制，伪命令测试仍必须通过，不能声称已完成真实渲染验证。

- [ ] **Step 7：提交部署实现**

```bash
git add docker-compose.gateway-web.yml scripts/deploy_gateway_web.sh \
  tests/infra/test_gateway_web_deployment.py
git commit -m "feat: deploy gateway web with rollback"
```

---

### Task 4：添加受保护的 Gitea 工作流和 GitHub CI

**Files:**
- Create: `.gitea/workflows/deploy-gateway-web.yml`
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/infra/test_gateway_web_deployment.py`

**Interfaces:**
- Consumes: Gitea push/manual dispatch 上下文，checkout 得到的完整提交 SHA。
- Produces: 仅在指定 Gitea 地址、仓库和 `refs/heads/main` 上运行的 `gateway` 部署任务。

- [ ] **Step 1：写工作流结构测试并观察失败**

```python
def test_gitea_workflow_is_restricted_to_gateway_main() -> None:
    workflow = load_yaml(GITEA_WORKFLOW)
    assert workflow["on"]["push"]["branches"] == ["main"]
    assert "workflow_dispatch" in workflow["on"]
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"] == {
        "group": "trading-agents-web-gateway-deploy",
        "cancel-in-progress": "false",
    }
    job = workflow["jobs"]["deploy"]
    assert job["runs-on"] == "gateway"
    assert "github.repository == 'suncheng/Trading-Agents-Web'" in job["if"]
    assert "github.ref == 'refs/heads/main'" in job["if"]


def test_gitea_workflow_pins_actions_and_exposes_no_secrets() -> None:
    workflow = load_yaml(GITEA_WORKFLOW)
    checkout = workflow["jobs"]["deploy"]["steps"][0]
    assert PINNED_ACTION.fullmatch(checkout["uses"])
    assert checkout["with"]["persist-credentials"] == "false"
    text = GITEA_WORKFLOW.read_text(encoding="utf-8")
    for forbidden in ("TRADING_AGENTS_WEB_GITEA_SYNC_TOKEN", "OPENAI_API_KEY", "ALPHA_VANTAGE_API_KEY"):
        assert forbidden not in text
```

Run: `pytest -q tests/infra/test_gateway_web_deployment.py -k workflow`

Expected: FAIL，因为 Gitea 工作流不存在。

- [ ] **Step 2：实现 Gitea 部署工作流**

工作流使用固定 checkout action SHA `11bd71901bbe5b1630ceea73d27597364c9af683`，并在 shell 中再次校验完整 SHA：

```yaml
name: Deploy gateway blank web page

on:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: trading-agents-web-gateway-deploy
  cancel-in-progress: false

jobs:
  deploy:
    if: >-
      ${{ (github.server_url == 'http://suncheng.online:14200' ||
      github.server_url == 'http://192.168.31.2:14200') &&
      github.repository == 'suncheng/Trading-Agents-Web' &&
      github.ref == 'refs/heads/main' }}
    runs-on: gateway
    steps:
      - name: Check out the synchronized commit
        uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683
        with:
          ref: ${{ github.sha }}
          fetch-depth: 1
          persist-credentials: false
      - name: Build, deploy, and verify
        env:
          DEPLOY_SHA: ${{ github.sha }}
        run: |
          case "$DEPLOY_SHA" in
            *[!0-9a-f]*|'') exit 2 ;;
          esac
          test "${#DEPLOY_SHA}" -eq 40
          test "$(git rev-parse HEAD)" = "$DEPLOY_SHA"
          bash scripts/deploy_gateway_web.sh "$DEPLOY_SHA"
```

服务地址守卫必须以实施时从 Gitea event 中核实的实际 `github.server_url` 为准；如果当前两种已知值都不匹配，先更新测试和设计记录，再运行部署，不能删除地址守卫。

- [ ] **Step 3：先写 GitHub CI 镜像构建测试，再修改 CI**

```python
def test_github_ci_builds_gateway_web_image_without_running_it_privileged() -> None:
    workflow = load_yaml(CI_WORKFLOW)
    job = workflow["jobs"]["gateway-web-image"]
    runs = "\n".join(step.get("run", "") for step in job["steps"])
    assert "docker build" in runs
    assert "web/Dockerfile" in runs
    assert "org.opencontainers.image.revision=${GITHUB_SHA}" in runs
    assert "--privileged" not in runs
```

Run: `pytest -q tests/infra/test_gateway_web_deployment.py::test_github_ci_builds_gateway_web_image_without_running_it_privileged`

Expected: FAIL，因为 `gateway-web-image` job 尚不存在。

向 `.github/workflows/ci.yml` 增加独立 `gateway-web-image` job，在 `ubuntu-latest` 上 checkout 后执行：

```bash
docker build \
  --label "org.opencontainers.image.revision=${GITHUB_SHA}" \
  --tag "trading-agents-web-ui:${GITHUB_SHA}" \
  --file web/Dockerfile .
docker image inspect \
  --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' \
  "trading-agents-web-ui:${GITHUB_SHA}" | grep -Fx "$GITHUB_SHA"
```

- [ ] **Step 4：运行工作流、基础设施和全量测试**

Run:

```bash
pytest -q tests/infra/test_gateway_web.py \
  tests/infra/test_gateway_web_deployment.py \
  tests/infra/test_initialize_gitea.py \
  tests/infra/test_sync_gitea.py
pytest -q
ruff check .
```

Expected: 全部 PASS，ruff 无错误。

- [ ] **Step 5：提交工作流与 CI**

```bash
git add .gitea/workflows/deploy-gateway-web.yml .github/workflows/ci.yml \
  tests/infra/test_gateway_web_deployment.py
git commit -m "ci: deploy gateway web from gitea main"
```

---

### Task 5：编写并测试网关上线运维手册

**Files:**
- Create: `docs/operations/gateway-web-deployment.md`
- Create: `tests/infra/test_gateway_web_operations.py`

**Interfaces:**
- Consumes: 已审查并进入 GitHub `main` 的 Task 1-4 产物，以及网关现有 Runner、Nginx Proxy Manager 和 Gitea 仓库。
- Produces: 可审计的上线前检查、Runner 标签变更、一次性同步、自动部署观察和验收步骤。

- [ ] **Step 1：写运维手册契约测试并观察失败**

```python
def test_runbook_contains_fixed_identity_and_preflight_checks() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    for required in (
        "gitea-runner-gatway",
        "gateway",
        "127.0.0.1:7681",
        "trading.suncheng.online",
        "pre-github-sync-20260920-052251b1",
        "052251b1a133a3aef9506b864c30d96c628c45be",
    ):
        assert required in text


def test_runbook_forbids_broad_or_destructive_operations() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    for forbidden in ("git push --mirror", "git push --force ", "docker system prune"):
        assert forbidden not in text
    assert "不得删除历史 Dockge Stack" in text
    assert "不得修改 Nginx Proxy Manager" in text
```

Run: `pytest -q tests/infra/test_gateway_web_operations.py`

Expected: FAIL，因为运维手册不存在。

- [ ] **Step 2：编写分阶段运维手册**

手册明确以下阶段和停止条件：

1. 记录 GitHub `main` 完整 SHA，确认 Task 1-4 的 CI 全绿。
2. 只为 `gitea-runner-gatway` 增加 `gateway` 标签，保留 `ubuntu-latest,emailbill`；如配置机制要求，只重启该 Runner。
3. 验证 Runner 带 `gateway` 在线、Docker/Compose 可用、`7681` 无监听、历史 `tradingagents` Stack 停止、NPM 路由未变。
4. 使用 Task 1 脚本执行一次性初始化。运行前再次读取旧 SHA；任意差异立即停止并联系 Multica 小队，不自行改写。
5. 验证备份 tag peel、两端 `main` SHA 和首次 Gitea workflow 目标 SHA。
6. 检查容器健康、镜像 revision、本机 `/healthz`、本机空白页和公网空白页。
7. 记录 workflow URL、部署 SHA、容器 ID、镜像 ID和验收时间。

手册中的命令使用占位变量前必须立即从只读命令解析并人工核对，不能硬编码 token，也不能把 token 放进 URL 或日志。

- [ ] **Step 3：运行手册测试和文档占位符扫描**

Run:

```bash
pytest -q tests/infra/test_gateway_web_operations.py
! rg -n -i 'TB[D]|TO[D]O|implement[[:space:]]+later|fill[[:space:]]+in' \
  docs/operations/gateway-web-deployment.md
```

Expected: PASS，搜索无输出。

- [ ] **Step 4：提交运维手册**

```bash
git add docs/operations/gateway-web-deployment.md \
  tests/infra/test_gateway_web_operations.py
git commit -m "docs: add gateway web deployment runbook"
```

---

### Task 6：合并后准备 Runner、初始化 Gitea 并验收首次部署

**Files:**
- No repository file changes.
- Operational evidence recorded in the Gitea/GitHub change record selected by the operator.

**Interfaces:**
- Consumes: 已进入 GitHub `main` 的精确提交 SHA，以及 Task 5 运维手册。
- Produces: 在线的 `gateway` Runner、已备份并对齐的 Gitea `main`、健康的 `trading-agents-web` Compose 服务和公开空白页。

- [ ] **Step 1：确认代码已合并且部署前状态没有漂移**

Run the read-only preflight commands from `docs/operations/gateway-web-deployment.md`。

Expected: GitHub `main` 是已审查 SHA；Gitea `main` 仍为固定旧 SHA；端口 `7681` 无监听；历史 Stack 仍停止。任何一项不匹配都停止，不进入下一步。

- [ ] **Step 2：为现有 Runner 增加专用标签**

按 Runner 当前实际配置机制，在保留 `ubuntu-latest,emailbill` 的同时增加 `gateway`，仅在必要时重启 `gitea-runner-gatway`。

Expected: Gitea 管理界面显示该 Runner 在线且包含 `gateway`；其他 Runner 和容器没有变化。

- [ ] **Step 3：执行一次性 Gitea 初始化**

从干净的 GitHub `main` checkout 运行：

```bash
bash scripts/initialize_gitea_main.sh \
  https://gitea.suncheng.online:81/suncheng/Trading-Agents-Web.git \
  "$(git rev-parse HEAD)"
```

`TRADING_AGENTS_WEB_GITEA_SYNC_TOKEN` 仅注入当前受控 shell 环境，不写入命令历史、仓库文件或远程 URL。

Expected: 脚本退出 0；备份标签 peel 到固定旧 SHA；Gitea `main` 等于 GitHub `main`。

- [ ] **Step 4：观察首次 Gitea 构建部署**

Expected: workflow 由 `gateway` Runner 接收；候选检查先成功，随后 Compose 服务切换；运行镜像的 tag 与 revision 都等于同步 SHA。失败时按手册收集日志，不手工复活历史 Stack，也不绕过部署脚本直接覆盖服务。

- [ ] **Step 5：完成本机和公网验收**

Run on the gateway:

```bash
curl --fail --silent --show-error http://127.0.0.1:7681/healthz
curl --fail --silent --show-error http://127.0.0.1:7681/ | cmp - web/index.html
curl --fail --silent --show-error https://trading.suncheng.online/ | cmp - web/index.html
docker compose --project-name trading-agents-web \
  --file docker-compose.gateway-web.yml ps
```

Expected: `/healthz` 精确输出 `ok` 加换行；两次页面比较退出 0；只有一个 `web` 服务健康；镜像 SHA 与 Gitea/GitHub `main` 一致。

- [ ] **Step 6：验证后续同步恢复普通推送**

下一次经过审查的 GitHub `main` 更新触发 `.github/workflows/sync-gitea.yml`。

Expected: `scripts/sync_gitea_main.sh` 通过普通非强制推送更新 Gitea；新的 Gitea 部署串行运行；若 Gitea 被独立推进，同步失败且不覆盖分歧。

---

## 最终验收命令

仓库实现合并前执行：

```bash
pytest -q
ruff check .
git diff --check
```

具备 Docker 的环境额外执行：

```bash
sha="$(git rev-parse HEAD)"
docker build \
  --label "org.opencontainers.image.revision=$sha" \
  --tag "trading-agents-web-ui:$sha" \
  --file web/Dockerfile .
test "$(docker image inspect --format '{{ index .Config.Labels \"org.opencontainers.image.revision\" }}' "trading-agents-web-ui:$sha")" = "$sha"
TRADINGAGENTS_WEB_IMAGE="trading-agents-web-ui:$sha" \
TRADINGAGENTS_WEB_REVISION="$sha" \
docker compose --project-name trading-agents-web \
  --file docker-compose.gateway-web.yml config --quiet
```

只有上述检查、代码审查和 GitHub `main` 合并全部完成后，才执行 Task 6 的生产操作。
