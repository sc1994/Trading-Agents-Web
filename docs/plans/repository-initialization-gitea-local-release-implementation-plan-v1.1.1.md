# 仓库初始化、Gitea 同步与本地镜像发布 Implementation Plan

- 计划版本：v1.1.1
- 日期：2026-09-02
- 实施方案 Issue：CODI-38
- 父 Issue：CODI-36

> 本计划必须先通过当前实施方案新周期的独立设计审查；审查通过且新设计 PR 合并前不得恢复 Task 3，也不得启动 Task 4-5。已合并的 Task 1-2 只作为审计基线，不重复实施。

**目标：** 在不开发 Web 功能的前提下，把 `sc1994/Trading-Agents-Web` 建立在 TradingAgents `v0.4.0` 精确历史之上，完成 GitHub `main` 到私有 Gitea `main` 的单向安全同步，并由现有 Gitea Runner 生成、验证、提升、保留和回滚本地 Docker 镜像。

**架构：** GitHub `main` 已完成上游历史导入和到 Gitea 的单向同步实现，本轮设计包从该真实 head 建立且只增加批准的 v1.1.0 spec 与版本化 plan。剩余实现由可单元测试的发布控制器、受保护且仓库级串行的 Gitea 发布/失败验收 workflow 和运维 runbook 构成：控制器在顺序执行及可观察冲突下复用或拒绝完整 SHA 标签、离线 smoke 后才提升 stable，并明确接受最终检查到 tag 写入之间的同 SHA 跨进程窄竞态；常规发布/回滚只能走 workflow，直接 CLI 的受控例外仍不构成宿主机全局锁。

**技术栈：** Git/GitHub CLI、GitHub Actions、Gitea Actions/`gitea-runner-ai`、Bash、Python 3.10-3.13、pytest、PyYAML、ruff、Docker Engine。

**规格：** `docs/design/Trading-Agents-Web-repository-initialization-gitea-local-release-design-spec-v1.1.0.md`，规格版本 `v1.1.0`，SHA-256 `971e8fb990cb911f11160107d887a531b2eed6d955ea156a70ad4cbaf3197754`；替代 v1.0.0。

## 全局约束

- 本期不开发 Web 页面、Web API、用户系统或其他产品功能。
- 上游固定为 `https://github.com/TauricResearch/TradingAgents.git`；签名 tag `v0.4.0` 的 tag object 固定为 `c5e62b8bb88bc308e84ea351044356f99da1213e`，解析提交固定为 `2448d0a12576f9b2ddcd5980a0630833423d1e1b`。
- 保留上游完整可达历史、原始 `LICENSE`、版权与来源说明；未来上游更新只能人工获取、审查并通过 GitHub 变更流程进入 `main`。
- README 冲突默认完整保留用户 bootstrap README 与上游 README 的所有有效内容，并新增 lineage；若实现者判断任一侧任何有效内容必须舍弃，必须停止 merge、保持远端不变并取得用户明确确认，不得自行删减。
- GitHub `sc1994/Trading-Agents-Web` 的 `main` 是唯一权威源；Gitea 目标固定为私有仓库 `https://gitea.suncheng.online:81/suncheng/Trading-Agents-Web.git` 的 `main`。
- 同步只允许普通 `HEAD:main` 推送；禁止 force、mirror、引用删除、其他分支或 tag 同步。非快进、分叉或冲突必须失败。
- Gitea 写入凭据只使用 GitHub Actions Secret `GITEA_MIRROR_SYNC_TOKEN`；不得写入仓库、远程 URL、普通变量、日志或任务摘要。
- 本地发布固定使用 `gitea-runner-ai` 的 `ubuntu-latest` 标签、Docker 执行器和宿主机 Docker socket；PR、其他分支和 tag 不得获得发布权限。
- 门禁固定为 Python 3.10、3.11、3.12、3.13 的 `pytest -q`，Python 3.12 clean-install/import，`ruff check .`，Docker build 和无网络 CLI smoke。
- 镜像仓库名固定为 `trading-agents-web`；成功提交使用完整 40 位提交 SHA tag，稳定别名固定为 `local-stable`；保留集合总数为三个成功 SHA，必须包含 stable 当前指向的 SHA。
- 完整 SHA 标签在顺序执行和可观察冲突下不得主动覆盖：匹配 managed/revision 元数据时复用并重新 smoke，已观察到元数据或 image ID 冲突时失败。唯一豁免是两个发布进程对同一完整 SHA 并发并在最终检查与实际 tag 写入之间交错时，后写入者可能改指该 SHA tag；不要求跨进程锁、原子 claim 或该窄窗口的绝对不可变证明。
- Gitea workflow 必须用固定仓库级 concurrency group 和 `cancel-in-progress: false` 串行受控运行，但不得把该属性描述为直接 CLI、其他 workflow 或宿主机外部进程的全局互斥。
- 常规 publish 和 rollback 必须只经受控 Gitea workflow。直接 CLI 仅限受控恢复或验收；开始前必须确认没有任何其他 active/queued 发布、回滚或失败验收 workflow，也没有其他直接 publish/rollback，并在单一维护窗口串行执行。该人工/审计前置条件不是宿主机全局锁，不能扩大同 SHA 窄竞态豁免。
- 构建或 smoke 失败的进程不得改变 `local-stable` 或清理旧成功镜像；回滚只重指稳定别名，不重新构建。同 SHA 竞态豁免不得用于放宽 stable、失败保护、保留、容器占用保护或回滚。
- workflow 不读取运行时 `.env`，不注入模型、行情、云平台或券商 API 密钥，不启动常驻容器，不挂载或修改 `~/.tradingagents`。

---

## 已核对的仓库事实

- 2026-09-02 本轮 fresh-fetch 后 `origin/main` 为 merge commit `15969d15e0f1491d9f3c9c26c4635c004f380ed2`，tree 为 `76346578540234d6dd39cd719c39e999b30a77e2`。旧设计 PR #1 已合并为 `98e76321f9d8fc8b32e2cfbc322afac2d390a137`，只作上一周期历史记录，不能完成本轮设计门禁。
- Task 1 已由 PR #2 合并为 `7dd23562296d87caa4a12e1e4adf4bec42b08abd`：用户 root `76fc9e407842970e8e6fdfdf32a2f9b7ef86be13` 与上游 commit `2448d0a12576f9b2ddcd5980a0630833423d1e1b` 均为 `main` 祖先，README/lineage、`UPSTREAM.md`、原始 `LICENSE` 和来源测试已在仓库中。
- Task 2 已由 PR #3 合并为当前 `main`：`.github/workflows/sync-gitea.yml`、`scripts/sync_gitea_main.sh`、`tests/infra/test_sync_gitea.py` 和 `PyYAML` dev 依赖已存在；CODI-60 已完成，不受 v1.1.0 风险豁免影响。
- v1.1.0 plan head `64f74dc1934b8a97fd416a4d5ab61a6aa280b2a6` 已在固定 base 上通过来源、投影和结构验证，但独立设计审查因 Task 5 的直接 CLI 并发边界及不可达失败验收返回“受阻”；v1.1.1 只修订该版本化计划，不改批准 spec 或生产文件。
- CODI-61 报告的待复审实现 head 为 `245e48c112880157a39665b3e525ba4acd1f90d1`，原审查只因旧计划要求的检查后写入竞态绝对不可变而返回“计划缺口”；该对象未进入 `origin/main` 且当前设计 checkout 不含该对象。本轮设计 PR 合并后由父流程从 CODI-61 原 checkout/来源恢复限定复审，不在本计划阶段复制、重写或假定其代码内容。
- 原 README bootstrap root 的 tree 为 `4fc3b335cf19a02aed5caffb6eb22962832189ef`，只含 `README.md`；README blob 为 `f28ff51c7392b770bbd7ac16024c7fb4d8b67dc2`，精确内容为 `# Trading-Agents-Web\n`，现仍可从 `main` 追溯。
- 上游 `v0.4.0` 同时存在同名 branch；只使用 `refs/tags/v0.4.0`，不得使用 `git clone --branch v0.4.0` 来选择基线。
- 上游 `v0.4.0` README blob 为 `505b69df46ce78e6bb0b22088a5b9c380cbc7a39`，与用户 README 是同路径独立添加；Task 1 当时已显式解决唯一的 add/add 冲突，没有选择 `--ours`、`--theirs` 或静默覆盖。
- `git ls-remote` 已核对 tag object 和 peeled commit 分别为 `c5e62b8bb88bc308e84ea351044356f99da1213e`、`2448d0a12576f9b2ddcd5980a0630833423d1e1b`；GitHub tag API 的 `verification.verified` 为 `true`、`reason` 为 `valid`。
- 上游提交包含 273 个可达提交、Apache-2.0 `LICENSE`、`pyproject.toml`、`Dockerfile`、`.dockerignore`、`.github/workflows/ci.yml`、CLI、包代码和 pytest 测试；没有现成 `docs/` 或 `.gitea/` 目录。
- 上游 `LICENSE` 的 SHA-256 为 `c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4`。
- 上游 `.github/workflows/ci.yml` 已固定四版本 pytest、Python 3.12 clean install/import 和全仓 ruff；本计划在 Gitea 侧保持这些命令等价。
- 上游 `Dockerfile` 使用 Python 3.12、多阶段构建、非 root `appuser`，入口为 `tradingagents`；`.dockerignore` 已排除 `.env`，因此构建上下文不会带入运行时 Secret。

## 本轮真实 base、设计复审与 PR 门禁

本轮新设计包只接受以下 fresh-fetch 基线；它已经包含旧设计、Task 1 上游导入和 Task 2 同步实现：

```text
BASE_REF=refs/heads/main
BASE_SHA=15969d15e0f1491d9f3c9c26c4635c004f380ed2
BASE_TREE=76346578540234d6dd39cd719c39e999b30a77e2
PREVIOUS_DESIGN_MERGE=98e76321f9d8fc8b32e2cfbc322afac2d390a137
TASK1_MERGE=7dd23562296d87caa4a12e1e4adf4bec42b08abd
TASK2_HEAD=3a0e3ae9520075711f3107cbed1d7dab81729d2e
```

每次创建 source、设计复审或创建 PR 前都 fresh-fetch 并执行：

```bash
set -euo pipefail
BASE_SHA="15969d15e0f1491d9f3c9c26c4635c004f380ed2"
git fetch --no-tags origin refs/heads/main:refs/remotes/origin/main --prune
test "$(git rev-parse refs/remotes/origin/main)" = "$BASE_SHA"
test "$(git rev-parse "${BASE_SHA}^{tree}")" = \
  "76346578540234d6dd39cd719c39e999b30a77e2"
git merge-base --is-ancestor \
  76fc9e407842970e8e6fdfdf32a2f9b7ef86be13 "$BASE_SHA"
git merge-base --is-ancestor \
  2448d0a12576f9b2ddcd5980a0630833423d1e1b "$BASE_SHA"
git merge-base --is-ancestor \
  3a0e3ae9520075711f3107cbed1d7dab81729d2e "$BASE_SHA"
test "$(git rev-parse "${BASE_SHA}:README.md")" != \
  "f28ff51c7392b770bbd7ac16024c7fb4d8b67dc2"
test "$(git rev-parse "${BASE_SHA}:LICENSE")" = \
  "$(git rev-parse 2448d0a12576f9b2ddcd5980a0630833423d1e1b:LICENSE)"
for path in \
  UPSTREAM.md \
  scripts/compose_import_readme.py \
  tests/infra/test_repository_provenance.py \
  .github/workflows/sync-gitea.yml \
  scripts/sync_gitea_main.sh \
  tests/infra/test_sync_gitea.py; do
  git cat-file -e "${BASE_SHA}:${path}"
done
```

Expected: 当前 `main` SHA/tree 与本轮 base 完全一致，上游和 Task 2 head 均可达，组合 README 已替代原始单行 blob，LICENSE 与上游相同，Task 1/2 产物全部存在。任何 base 前进或历史/文件差异都停止，重新核对真实仓库并重新设计审查；不得 reset、force 或删除已合并内容来适配本计划。

本轮 source 的首个提交从该 base 新建并加入批准 spec 与 v1.1.0 plan；v1.1.1 修订提交必须以已审查但受阻的 `64f74dc1934b8a97fd416a4d5ab61a6aa280b2a6` 为唯一 parent，旧 plan 文件保持不变。不改生产文件，不恢复 CODI-61 head，不创建 PR：

```bash
set -euo pipefail
BASE_SHA="15969d15e0f1491d9f3c9c26c4635c004f380ed2"
REVISION_PARENT="64f74dc1934b8a97fd416a4d5ab61a6aa280b2a6"
test "$(git rev-parse "${REVISION_PARENT}^")" = "$BASE_SHA"
git switch -c design/codi-38-plan-v1.1.1 "$REVISION_PARENT"
cp docs/plans/repository-initialization-gitea-local-release-implementation-plan-v1.1.0.md \
  docs/plans/repository-initialization-gitea-local-release-implementation-plan-v1.1.1.md
```

修订提交后，独立设计复审必须验证 revision parent、完整设计 diff、旧 plan 未改和批准规格摘要：

```bash
set -euo pipefail
BASE_SHA="15969d15e0f1491d9f3c9c26c4635c004f380ed2"
REVISION_PARENT="64f74dc1934b8a97fd416a4d5ab61a6aa280b2a6"
PLAN_HEAD="$(git rev-parse HEAD)"
test "$(git rev-parse "${PLAN_HEAD}^")" = "$REVISION_PARENT"
test "$(git rev-parse "${REVISION_PARENT}^")" = "$BASE_SHA"
test "$(git rev-list --count "${BASE_SHA}..${PLAN_HEAD}")" = "2"
test "$(git diff --name-only "$REVISION_PARENT" "$PLAN_HEAD")" = \
  "docs/plans/repository-initialization-gitea-local-release-implementation-plan-v1.1.1.md"
test "$(git diff --name-only "$BASE_SHA" "$PLAN_HEAD" | sort)" = \
  "$(printf '%s\n' \
    docs/design/Trading-Agents-Web-repository-initialization-gitea-local-release-design-spec-v1.1.0.md \
    docs/plans/repository-initialization-gitea-local-release-implementation-plan-v1.1.0.md \
    docs/plans/repository-initialization-gitea-local-release-implementation-plan-v1.1.1.md | sort)"
test "$(git show "${PLAN_HEAD}:docs/plans/repository-initialization-gitea-local-release-implementation-plan-v1.1.0.md" | sha256sum | awk '{print $1}')" = \
  "acdcca2cceefa7f757ed4ded57a4261b2bb7f38a439884ada77993e35d6611ca"
test "$(sha256sum \
  docs/design/Trading-Agents-Web-repository-initialization-gitea-local-release-design-spec-v1.1.0.md | awk '{print $1}')" = \
  "971e8fb990cb911f11160107d887a531b2eed6d955ea156a70ad4cbaf3197754"
git diff --exit-code "$BASE_SHA" "$PLAN_HEAD" -- \
  README.md LICENSE UPSTREAM.md pyproject.toml scripts/ tests/infra/ \
  .github/workflows/sync-gitea.yml
```

设计与 PR 门禁顺序固定为：

1. 独立设计复审 fresh-fetch 后返回已审查 `PLAN_HEAD`、目标分支 `main` 和目标版本 `15969d15e0f1491d9f3c9c26c4635c004f380ed2`。
2. 只有审查三元组与当前 head/base 完全一致时，后续 PR 阶段才普通推送已审查 head 到独立 source branch；禁止 rebase、force-push 或修改已审查 commit。
3. 新设计 PR 标题同时包含 `CODI-36`、`CODI-38`，正文只写 `Closes CODI-38`；provider head/base 必须匹配审查快照，diff 只能包含 v1.1.0 spec 与 v1.1.0/v1.1.1 plan。旧 PR #1 的 merged 状态和受阻 head `64f74dc...` 都不能作为本轮成功锚点。
4. 新设计 PR 合并后，父流程才以本轮来源评论恢复 CODI-61 的限定代码复审；不新建重复 Task 3 Issue。CODI-59、CODI-58 在 Task 3 通过并合并前继续 parked。
5. 任一 head/base/diff/provider 状态漂移都停止并重新审查；本计划编写阶段不 push、不做专业审查、不创建 PR。

## 文件职责映射

- `UPSTREAM.md`：版本化保存上游 URL、tag object、commit、签名核验、许可证和人工同步命令。
- `README.md`：Task 1 已显式组合并完整保留用户 bootstrap README、`Repository lineage` 和上游 `v0.4.0` README，没有静默选择任一冲突侧。
- `scripts/compose_import_readme.py`：只在 README add/add 冲突期间，从两个已核验 ref 读取原始字节并按固定顺序无损组合。
- `pyproject.toml`：在 dev extra 中增加测试 workflow YAML 所需的 `PyYAML>=6.0.2`。
- `.github/workflows/sync-gitea.yml`：GitHub 环境中的单分支普通推送；不承担测试或发布。
- `scripts/sync_gitea_main.sh`：实现可在本地 bare repo 上集成测试的 push/远端 SHA 校验协议；生产 HTTPS 模式通过 askpass 读取 Secret。
- `.gitea/workflows/local-release.yml`：Gitea 环境中的目标 SHA 解析、测试矩阵、clean install、ruff、构建发布与回滚编排。
- `.gitea/workflows/local-release-failure-acceptance.yml`：仅允许受保护 `main` 人工触发，在与生产发布相同的 concurrency group 中以唯一测试 SHA/镜像 namespace 验证 smoke 失败保护并清理临时产物。
- `scripts/resolve_release_target.py`：只从 job env 读取事件和人工输入，使用 checkout 已有的完整本地历史校验目标，不执行远端 fetch。
- `scripts/local_image_release.py`：唯一 Docker 镜像生命周期入口；在顺序/可观察场景复用或拒绝完整 SHA，执行 `publish`、`rollback`、stable 感知保留和使用中镜像保护；不实现跨进程锁或原子 claim。
- `docs/operations/repository-sync-and-local-release.md`：用户配置、受控 workflow 触发、active/queued 与直接进程前置核对、审计、同 SHA 并发残余风险、受控 CLI 例外、回滚和安全清理 runbook。
- `tests/infra/test_repository_provenance.py`：验证 README 两侧字节完整保留、独立根 fixture、上游提交可达、许可证字节未改和来源常量完整。
- `tests/infra/test_sync_gitea.py`：解析 GitHub workflow，并用临时 bare repo 验证普通推送成功和非快进失败。
- `tests/infra/test_local_image_release.py`：用 fake Docker runner 验证失败保护、顺序复用、预先存在/最终检查可观察冲突拒绝、stable 感知保留、使用中镜像和回滚；不注入最终检查后的竞态。
- `tests/infra/test_release_target.py`：验证私有仓库在 checkout 凭据移除后仅靠本地完整历史解析 SHA，并拒绝带引号或换行的恶意输入。
- `tests/infra/test_gitea_release_workflow.py`：结构化解析 Gitea workflow，验证触发、矩阵、依赖、平台 guard、env 输入边界、权限和发布命令。
- `tests/infra/test_operations_runbook.py`：验证 runbook 与隔离失败验收 workflow 包含常规 workflow-only 操作、无 active/queued 前置条件、唯一 namespace、生产状态不变和临时产物清理，且不含任何 Secret 值。

## 接口契约

### GitHub 到 Gitea 同步脚本

```text
scripts/sync_gitea_main.sh REMOTE_URL EXPECTED_SHA
```

- `REMOTE_URL`：生产仅传固定 HTTPS URL；测试允许 `file://` 临时 bare repo。
- `EXPECTED_SHA`：必须为当前 `HEAD` 的完整 40 位小写 SHA。
- HTTPS 模式只从环境变量 `GITEA_MIRROR_SYNC_TOKEN` 读取 token，并通过临时 `GIT_ASKPASS` 返回；脚本退出时删除 askpass。
- 成功条件是普通 `git push REMOTE_URL HEAD:refs/heads/main` 成功，随后 `git ls-remote` 返回的 `main` SHA 与 `EXPECTED_SHA` 完全一致。
- 任一步失败返回非零，不执行 force、mirror、delete 或其他 refspec。

### 本地镜像控制器

以下 CLI 是受控 workflow 的内部接口，不是常规运维入口：

```text
python scripts/local_image_release.py publish --sha FULL_SHA \
  --image trading-agents-web --keep 3 --context .
python scripts/local_image_release.py rollback --sha FULL_SHA \
  --image trading-agents-web
```

- 常规 publish/rollback 只通过 `.gitea/workflows/local-release.yml` 自动触发或 `workflow_dispatch` 执行。直接调用上述 CLI 仅用于文档定义的受控恢复/验收，并须先证明没有其他 active/queued workflow 或直接发布/回滚。

- `publish` 首先检查完整 SHA tag：不存在时才构建 candidate；存在且 managed/revision 标签匹配时直接复用并重新离线 smoke；已观察到元数据不匹配时失败且不执行 Docker 变更。
- 新 candidate 通过 smoke 后再次检查完整 SHA tag：若此时观察到匹配元数据但不同 image ID，则失败且不提升/清理；若仍不存在则执行 candidate→完整 SHA tag。该检查与实际 tag 写入之间不加跨进程锁或原子 claim，两个同 SHA 发布进程在此窄窗口交错时允许后写入者改指完整 SHA tag。
- 上述豁免不改变顺序行为，也不允许删除第二次检查；实现和测试不得声称完整 SHA 在所有宿主机进程下绝对不可变。
- smoke 对 candidate 或复用的完整 SHA 镜像执行 `--network none`、只读根文件系统、无宿主机 env/volume 的 `tradingagents --help`。
- smoke 成功后才允许当前成功进程更新 `local-stable`；此前不触碰稳定别名。构建/smoke 失败或第二次检查已观察到冲突的进程不得提升 stable 或清理旧成功镜像。
- 清理先验证 `local-stable` 指向 managed 镜像且存在匹配的完整 SHA tag，把 stable SHA 计入三个保留槽位，再按 `Created` 倒序补足其余槽位。
- 清理前收集所有容器的不可变 image ID；stable 当前 SHA、保留集合内其余 SHA 以及任何被运行中或停止容器引用的镜像都不删除。
- `rollback` 只接受存在且 managed/revision 标签匹配的完整 SHA 镜像，然后执行一次 Docker tag 更新稳定别名；常规回滚必须由受控 Gitea `workflow_dispatch` 调用。

## Stage 与依赖

| 状态 | 工作项 | 依赖/恢复入口 | 独立审查产物 |
|---|---|---|---|
| 已完成 | 原 Task 1：精确上游历史与来源证明（CODI-62，PR #2） | 旧设计 PR #1 | 双 parent 历史、README/lineage、来源与许可证回归；不重复实施 |
| 已完成 | 原 Task 2：GitHub→Gitea 同步（CODI-60，PR #3） | 原 Task 1 | bare-repo 快进/分叉、最小凭据与同步 workflow；不受豁免影响 |
| Stage 1 | Task 3：恢复 CODI-61 的本地镜像控制器限定复审 | 新 v1.1.1 plan 设计 PR 已合并；从 CODI-61 原来源恢复，不建重复 Issue | 顺序复用、可观察冲突拒绝、失败保护、stable 感知保留和回滚 fake-Docker 测试 |
| Stage 2 | Task 4：Gitea 门禁与发布编排（CODI-59） | Task 3 代码 PR 已合并；此前保持 parked | 平台隔离、私有 checkout、恶意输入拒绝、四版本门禁、workflow 级串行与人工回滚 |
| Stage 3 | Task 5：runbook、隔离失败验收 workflow 与端到端证据（CODI-58） | Task 4 代码 PR 已合并，用户已配置 token、分支保护和 Runner；此前保持 parked | workflow-only 常规操作、无其他活动前置证明、唯一 namespace、生产状态不变/临时清理、失败保护和回滚记录 |

## 迁移与兼容性

- 仓库初始化和单向同步实现已经完成，不再是空仓；没有数据库、API、配置格式或 TradingAgents 运行数据迁移。本轮只修订设计契约，设计 PR 不改生产文件。
- README bootstrap root、旧设计 merge、上游无关历史 merge 与 Task 2 merge 均保留在当前 `main`；不得重写、squash、回退或重复创建对应实现 Issue。
- v1.1.0 spec 仅改变同一完整 SHA 跨进程并发在最终检查至实际 tag 写入窄窗口的验收保证；控制器 CLI 参数、生产镜像名、标签名、保留数、常规 workflow 输入、同步接口和凭据边界不变。v1.1.1 plan 新增同 concurrency group 的隔离失败验收 workflow，不迁移生产数据或配置，也不允许把测试 namespace 用作常规发布入口。
- 新设计 PR 合并后，CODI-61 先在原 Issue 恢复限定代码复审：旧“计划缺口”不能直接视为通过，但也不得继续要求跨进程互斥、原子 claim 或检查后写入竞态绝对不可变测试。CODI-59/58 依赖顺序不变。
- Gitea 目标必须继续能从 GitHub `main` 快进。发现 Gitea 已有独立提交时停止，不重置、不 force-push。
- 后续人工同步上游时先 fetch，再在功能分支合并或 cherry-pick，经 GitHub PR 审查进入 `main`；Gitea 仍只接收 GitHub `main` 的普通推送。

---

### 已完成基线 A：TradingAgents v0.4.0 精确历史与来源证明

**状态：** 已由 CODI-62 / GitHub PR #2 合并；本节保留原执行证据供审计，不再创建或执行 Task 1。

**Files：**
- Create: `UPSTREAM.md`
- Create: `scripts/compose_import_readme.py`
- Modify: `README.md`（完整用户 README + 固定 lineage + 完整上游 README）
- Create: `tests/infra/test_repository_provenance.py`
- Preserve byte-for-byte: `LICENSE`
- Preserve history: user root `76fc9e407842970e8e6fdfdf32a2f9b7ef86be13`; upstream commit `2448d0a12576f9b2ddcd5980a0630833423d1e1b` and all ancestors

**Interfaces：**
- Consumes: 已合并 spec/plan 的 GitHub `main`，其中用户 README root 可达且 README blob 仍为 `f28ff51c7392b770bbd7ac16024c7fb4d8b67dc2`；`origin` 指向 `sc1994/Trading-Agents-Web`。
- Produces: `scripts/compose_import_readme.py --repository PATH --base REF --upstream REF`；最终 README 完整包含两侧原始字节与 lineage；当前分支包含两个独立 root 及上游完整历史；`UPSTREAM.md` 提供后续人工同步契约。

以下已勾选步骤是 v1.0.3 周期的历史执行记录，只用于证明当前 base；实现者不得重跑 merge、重写 README 或新建重复 Issue。

- [x] **Step 1：确认设计 PR 合并结果仍完整保留已核验 README root**

Run:

```bash
set -euo pipefail
BASE_SHA="76fc9e407842970e8e6fdfdf32a2f9b7ef86be13"
git fetch origin refs/heads/main:refs/remotes/origin/main --prune
git merge-base --is-ancestor "$BASE_SHA" refs/remotes/origin/main
test "$(git rev-parse "${BASE_SHA}:README.md")" = \
  "f28ff51c7392b770bbd7ac16024c7fb4d8b67dc2"
test "$(git rev-parse refs/remotes/origin/main:README.md)" = \
  "f28ff51c7392b770bbd7ac16024c7fb4d8b67dc2"
test "$(git diff --name-only "$BASE_SHA" refs/remotes/origin/main | sort)" = \
  "$(printf '%s\n' \
    docs/design/Trading-Agents-Web-repository-initialization-gitea-local-release-design-spec-v1.0.0.md \
    docs/plans/repository-initialization-gitea-local-release-implementation-plan-v1.0.3.md | sort)"
git switch -c codi-38/import-upstream-v0.4.0 refs/remotes/origin/main
```

Expected: base 仍是 `main` 祖先；设计 PR 只增加批准 spec 与 v1.0.3 plan；工作树包含原始 `README.md` 和两份设计文档。任何其他文件或 README blob 差异都停止并回到 CODI-38 复审，不静默接受。

- [x] **Step 2：精确 fetch 同名 tag，而不是同名 branch，并验证 GitHub 签名状态**

Run:

```bash
git remote add upstream https://github.com/TauricResearch/TradingAgents.git
git fetch upstream refs/tags/v0.4.0:refs/tags/upstream-v0.4.0

test "$(git rev-parse refs/tags/upstream-v0.4.0)" = \
  "c5e62b8bb88bc308e84ea351044356f99da1213e"
test "$(git rev-parse refs/tags/upstream-v0.4.0^{commit})" = \
  "2448d0a12576f9b2ddcd5980a0630833423d1e1b"
test "$(gh api repos/TauricResearch/TradingAgents/git/tags/c5e62b8bb88bc308e84ea351044356f99da1213e \
  --jq '.verification.verified and (.verification.reason == "valid") and (.object.sha == "2448d0a12576f9b2ddcd5980a0630833423d1e1b")')" = "true"
```

Expected: 三个 `test` 均退出 0；fetch 输出明确是 `refs/tags/v0.4.0`。

- [x] **Step 3：先写来源保护测试并观察失败**

Create `tests/infra/test_repository_provenance.py`:

```python
import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSER = ROOT / "scripts/compose_import_readme.py"
BASE_COMMIT = "76fc9e407842970e8e6fdfdf32a2f9b7ef86be13"
BASE_README_BLOB = "f28ff51c7392b770bbd7ac16024c7fb4d8b67dc2"
UPSTREAM_COMMIT = "2448d0a12576f9b2ddcd5980a0630833423d1e1b"
UPSTREAM_README_BLOB = "505b69df46ce78e6bb0b22088a5b9c380cbc7a39"
TAG_OBJECT = "c5e62b8bb88bc308e84ea351044356f99da1213e"
LICENSE_SHA256 = "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4"


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=check,
        text=True,
        capture_output=True,
    )


def git_bytes(*args: str, cwd: Path = ROOT) -> bytes:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True
    ).stdout


def fixture_git(
    repo: Path, *args: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, check=check, text=True, capture_output=True
    )


def fixture_commit(repo: Path, message: str) -> str:
    fixture_git(repo, "add", "README.md")
    fixture_git(repo, "commit", "-m", message)
    return fixture_git(repo, "rev-parse", "HEAD").stdout.strip()


def test_upstream_commit_is_the_imported_parent_or_an_ancestor() -> None:
    merge_head = git("rev-parse", "-q", "--verify", "MERGE_HEAD", check=False)
    if merge_head.returncode == 0:
        assert merge_head.stdout.strip() == UPSTREAM_COMMIT
    else:
        result = git("merge-base", "--is-ancestor", UPSTREAM_COMMIT, "HEAD", check=False)
        assert result.returncode == 0


def test_upstream_license_is_preserved_byte_for_byte() -> None:
    current = (ROOT / "LICENSE").read_bytes()
    original = git_bytes("show", f"{UPSTREAM_COMMIT}:LICENSE")
    assert current == original
    assert hashlib.sha256(current).hexdigest() == LICENSE_SHA256


def test_source_record_contains_reproducible_identity() -> None:
    source = (ROOT / "UPSTREAM.md").read_text(encoding="utf-8")
    assert "https://github.com/TauricResearch/TradingAgents.git" in source
    assert "v0.4.0" in source
    assert TAG_OBJECT in source
    assert UPSTREAM_COMMIT in source
    assert "manual review" in source.lower()


def test_both_readmes_are_preserved_around_lineage() -> None:
    assert git("rev-parse", f"{BASE_COMMIT}:README.md").stdout.strip() == BASE_README_BLOB
    assert (
        git("rev-parse", f"{UPSTREAM_COMMIT}:README.md").stdout.strip()
        == UPSTREAM_README_BLOB
    )
    user_readme = git_bytes("show", f"{BASE_COMMIT}:README.md")
    upstream_readme = git_bytes("show", f"{UPSTREAM_COMMIT}:README.md")
    current = (ROOT / "README.md").read_bytes()
    assert current.startswith(user_readme + b"\n## Repository lineage\n")
    assert current.endswith(upstream_readme)
    assert b"<<<<<<<" not in current
    assert b"=======" not in current
    assert b">>>>>>>" not in current
    assert git("ls-files", "-u", "--", "README.md").stdout == ""


def test_composer_resolves_independent_root_readmes_without_data_loss(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "fixture"
    repo.mkdir()
    fixture_git(repo, "init", "-b", "main")
    fixture_git(repo, "config", "user.name", "README Merge Test")
    fixture_git(repo, "config", "user.email", "readme-merge@example.invalid")
    user_readme = b"# User repository\n\nOwner bootstrap text.\n"
    upstream_readme = b"# Upstream project\n\nInstall and usage text.\n"
    (repo / "README.md").write_bytes(user_readme)
    base = fixture_commit(repo, "user root")

    fixture_git(repo, "switch", "--orphan", "upstream-root")
    fixture_git(repo, "rm", "-rf", ".", check=False)
    (repo / "README.md").write_bytes(upstream_readme)
    upstream = fixture_commit(repo, "upstream root")
    fixture_git(repo, "switch", "main")
    merge = fixture_git(
        repo,
        "merge",
        "--allow-unrelated-histories",
        "--no-ff",
        "--no-commit",
        upstream,
        check=False,
    )
    assert merge.returncode != 0
    assert fixture_git(
        repo, "diff", "--name-only", "--diff-filter=U"
    ).stdout.strip() == "README.md"

    subprocess.run(
        [
            sys.executable,
            str(COMPOSER),
            "--repository",
            str(repo),
            "--base",
            base,
            "--upstream",
            upstream,
        ],
        check=True,
    )
    fixture_git(repo, "add", "README.md")
    assert fixture_git(repo, "ls-files", "-u").stdout == ""
    combined = (repo / "README.md").read_bytes()
    assert combined.startswith(user_readme + b"\n## Repository lineage\n")
    assert combined.endswith(upstream_readme)

    fixture_git(repo, "commit", "-m", "merge roots")
    parents = fixture_git(repo, "rev-list", "--parents", "-n", "1", "HEAD").stdout.split()
    assert parents[1:] == [base, upstream]
```

Run:

```bash
python -m pytest tests/infra/test_repository_provenance.py -q
```

Expected: FAIL；`LICENSE`、`UPSTREAM.md` 和上游历史尚未导入，README 组合器也尚不存在。

- [x] **Step 4：实现只在 add/add 冲突期间工作的 README 无损组合器**

Create executable `scripts/compose_import_readme.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

LINEAGE = b"""## Repository lineage

This repository retains the repository owner's Trading-Agents-Web bootstrap content above and the complete TauricResearch/TradingAgents v0.4.0 README below. See [UPSTREAM.md](UPSTREAM.md) for the imported release identity, Apache-2.0 license, and manual upstream review process.
"""


def git_bytes(repository: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", *args], cwd=repository, check=True, capture_output=True
    ).stdout


def compose(repository: Path, base_ref: str, upstream_ref: str) -> bytes:
    unmerged = git_bytes(
        repository, "diff", "--name-only", "--diff-filter=U"
    ).decode("utf-8").splitlines()
    if unmerged != ["README.md"]:
        raise RuntimeError("README.md must be the only unmerged path")
    user_readme = git_bytes(repository, "show", f"{base_ref}:README.md")
    upstream_readme = git_bytes(repository, "show", f"{upstream_ref}:README.md")
    if not user_readme or not upstream_readme:
        raise RuntimeError("both README inputs must be non-empty")
    separator = b"" if user_readme.endswith(b"\n\n") else b"\n"
    return user_readme + separator + LINEAGE + b"\n---\n\n" + upstream_readme


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, default=Path("."))
    parser.add_argument("--base", required=True)
    parser.add_argument("--upstream", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repository = args.repository.resolve()
    combined = compose(repository, args.base, args.upstream)
    (repository / "README.md").write_bytes(combined)


if __name__ == "__main__":
    main()
```

Run:

```bash
chmod 0755 scripts/compose_import_readme.py
python -m pytest \
  tests/infra/test_repository_provenance.py::test_composer_resolves_independent_root_readmes_without_data_loss -q
ruff check scripts/compose_import_readme.py tests/infra/test_repository_provenance.py
```

Expected: 独立根 fixture PASS；合并前存在且仅存在 README add/add 冲突，组合后用户字节保持前缀、上游字节保持后缀，merge commit 有两个预期 parent；ruff 退出 0。

- [x] **Step 5：开始无关历史 merge，显式解决 README 并添加来源记录**

Run:

```bash
set -euo pipefail
BASE_SHA="76fc9e407842970e8e6fdfdf32a2f9b7ef86be13"
UPSTREAM_SHA="2448d0a12576f9b2ddcd5980a0630833423d1e1b"
if git merge --allow-unrelated-histories --no-ff --no-commit "$UPSTREAM_SHA"; then
  printf 'expected README add/add conflict was absent\n' >&2
  git merge --abort
  exit 1
fi
test "$(git diff --name-only --diff-filter=U)" = "README.md"
python scripts/compose_import_readme.py \
  --repository . \
  --base "$BASE_SHA" \
  --upstream "$UPSTREAM_SHA"
git add README.md
test -z "$(git ls-files -u)"
test "$(git rev-parse "${BASE_SHA}:README.md")" = \
  "f28ff51c7392b770bbd7ac16024c7fb4d8b67dc2"
test "$(git rev-parse "${UPSTREAM_SHA}:README.md")" = \
  "505b69df46ce78e6bb0b22088a5b9c380cbc7a39"
```

Expected: merge 非零只因为 `README.md` add/add；组合器后 index 不再有未合并路径。禁止使用 `git checkout --ours`、`--theirs` 或复制任一整文件覆盖另一侧；如果精确 blob 或唯一冲突断言失败，立即 `git merge --abort` 并回到 CODI-38。若任何实现或编辑理由要求舍弃任一侧有效内容，必须停止并请求用户明确确认，不得自行删减或提交。

Create `UPSTREAM.md`:

````markdown
# Upstream source

This repository is derived from [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents).

- Upstream remote: `https://github.com/TauricResearch/TradingAgents.git`
- Imported release: `v0.4.0`
- Annotated tag object: `c5e62b8bb88bc308e84ea351044356f99da1213e`
- Peeled commit: `2448d0a12576f9b2ddcd5980a0630833423d1e1b`
- License: Apache License 2.0 in `LICENSE`

The import preserves upstream history and attribution. Future upstream changes are never merged automatically. A maintainer must fetch the upstream repository, verify the selected tag or commit, inspect the complete diff, and submit the result through the GitHub pull-request process for manual review.

Recreate the local upstream relationship with:

```bash
git remote add upstream https://github.com/TauricResearch/TradingAgents.git
git fetch upstream --tags
git log --oneline --decorate --graph main upstream/main
```

Before proposing an update, record the selected upstream ref and full commit SHA in the pull request and run the repository's complete CI and local-release qualification suite.
````

README 已由组合器生成；在继续前核对两侧原始字节与 lineage 的相对位置：

```bash
python -m pytest \
  tests/infra/test_repository_provenance.py::test_both_readmes_are_preserved_around_lineage -q
```

Expected: PASS；用户 README 是最终文件的完整前缀，上游 README 是完整后缀，lineage 位于两者之间，且没有冲突标记或未合并 index entry。

- [x] **Step 6：运行来源测试，确认 merge tree 满足约束**

Run:

```bash
python -m pytest tests/infra/test_repository_provenance.py -q
git diff --exit-code 2448d0a12576f9b2ddcd5980a0630833423d1e1b -- LICENSE
git rev-list --count 2448d0a12576f9b2ddcd5980a0630833423d1e1b
```

Expected: 5 tests PASS；用户/上游 README 原始字节与 lineage 组合、独立根 merge fixture、LICENSE、来源记录和可达历史均通过；`LICENSE` diff 为空；上游可达提交数为 `273`。

- [x] **Step 7：提交完整的来源 merge，并复验历史**

Run:

```bash
git add LICENSE README.md UPSTREAM.md scripts/compose_import_readme.py \
  tests/infra/test_repository_provenance.py
git commit -m "chore: import TradingAgents v0.4.0 baseline"
git merge-base --is-ancestor \
  76fc9e407842970e8e6fdfdf32a2f9b7ef86be13 HEAD
git merge-base --is-ancestor \
  2448d0a12576f9b2ddcd5980a0630833423d1e1b HEAD
python -m pytest tests/infra/test_repository_provenance.py -q
```

Expected: merge commit 有两个 parent，分别承载用户 README root/设计文档历史与精确上游历史；5 tests PASS；最终 README 完整保留两侧内容。

---

### 已完成基线 B：GitHub main 到 Gitea main 的失败关闭同步

**状态：** 已由 CODI-60 / GitHub PR #3 合并；本节保留原执行证据供审计，不再创建或执行 Task 2。

**Files：**
- Modify: `pyproject.toml`
- Create: `scripts/sync_gitea_main.sh`
- Create: `.github/workflows/sync-gitea.yml`
- Create: `tests/infra/test_sync_gitea.py`

**Interfaces：**
- Consumes: Task 1 的 GitHub `main` 历史；用户配置的 `GITEA_MIRROR_SYNC_TOKEN`。
- Produces: `scripts/sync_gitea_main.sh REMOTE_URL EXPECTED_SHA`；Task 4 只依赖同步后 Gitea `main` 得到同一 SHA，不读取该 Secret。

以下已勾选步骤是 v1.0.3 周期的历史执行记录；本轮只运行基线回归，不修改已合并同步接口，不重开 CODI-60。

- [x] **Step 1：添加结构化 workflow 测试依赖和失败测试**

Modify `pyproject.toml` 的 `dev` 列表，加入：

```toml
    "PyYAML>=6.0.2",
```

Create `tests/infra/test_sync_gitea.py`:

```python
import os
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/sync-gitea.yml"
SCRIPT = ROOT / "scripts/sync_gitea_main.sh"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def run(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, check=check, text=True, capture_output=True)


def git(cwd: Path, *args: str) -> str:
    return run("git", *args, cwd=cwd).stdout.strip()


def commit(repo: Path, message: str, content: str) -> str:
    (repo / "payload.txt").write_text(content, encoding="utf-8")
    git(repo, "add", "payload.txt")
    git(repo, "commit", "-m", message)
    sha = git(repo, "rev-parse", "HEAD")
    assert SHA_RE.fullmatch(sha)
    return sha


def test_workflow_has_read_only_single_branch_contract() -> None:
    document = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert document["on"]["push"]["branches"] == ["main"]
    assert "workflow_dispatch" in document["on"]
    assert document["permissions"] == {"contents": "read"}
    job = document["jobs"]["sync-main"]
    assert "github.server_url == 'https://github.com'" in job["if"]
    assert "github.ref == 'refs/heads/main'" in job["if"]
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "GITEA_MIRROR_SYNC_TOKEN" in text
    assert "HEAD:refs/heads/main" not in text
    assert all(flag not in text for flag in ("--force", "--mirror", "--delete"))


def test_script_pushes_main_and_rejects_non_fast_forward(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target.git"
    other = tmp_path / "other"
    source.mkdir()
    git(source, "init", "-b", "main")
    git(source, "config", "user.name", "Infra Test")
    git(source, "config", "user.email", "infra-test@example.invalid")
    first = commit(source, "first", "first")
    run("git", "init", "--bare", str(target), cwd=tmp_path)
    remote = target.resolve().as_uri()

    run("bash", str(SCRIPT), remote, first, cwd=source)
    assert git(source, "ls-remote", remote, "refs/heads/main").split()[0] == first

    run("git", "clone", "--branch", "main", remote, str(other), cwd=tmp_path)
    git(other, "config", "user.name", "Infra Test")
    git(other, "config", "user.email", "infra-test@example.invalid")
    divergent = commit(other, "target divergence", "target")
    git(other, "push", "origin", "HEAD:main")

    second = commit(source, "source divergence", "source")
    result = run("bash", str(SCRIPT), remote, second, cwd=source, check=False)
    assert result.returncode != 0
    assert git(source, "ls-remote", remote, "refs/heads/main").split()[0] == divergent


def test_https_mode_fails_before_git_when_token_is_missing(tmp_path: Path) -> None:
    env = os.environ.copy()
    env.pop("GITEA_MIRROR_SYNC_TOKEN", None)
    result = subprocess.run(
        ["bash", str(SCRIPT), "https://gitea.example.invalid/owner/repo.git", "a" * 40],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "GITEA_MIRROR_SYNC_TOKEN is required" in result.stderr
```

Run:

```bash
python -m pip install -e ".[dev]"
python -m pytest tests/infra/test_sync_gitea.py -q
```

Expected: FAIL，因为脚本和 workflow 尚不存在。

- [x] **Step 2：实现只推送一个 refspec 的同步脚本**

Create executable `scripts/sync_gitea_main.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

remote_url="${1:?usage: sync_gitea_main.sh REMOTE_URL EXPECTED_SHA}"
expected_sha="${2:?usage: sync_gitea_main.sh REMOTE_URL EXPECTED_SHA}"

if [[ ! "$expected_sha" =~ ^[0-9a-f]{40}$ ]]; then
  printf 'EXPECTED_SHA must be a full lowercase commit SHA\n' >&2
  exit 2
fi

askpass=""
cleanup() {
  if [[ -n "$askpass" ]]; then
    rm -f "$askpass"
  fi
}
trap cleanup EXIT

case "$remote_url" in
  https://*)
    if [[ -z "${GITEA_MIRROR_SYNC_TOKEN:-}" ]]; then
      printf 'GITEA_MIRROR_SYNC_TOKEN is required for HTTPS sync\n' >&2
      exit 4
    fi
    askpass="$(mktemp)"
    chmod 0700 "$askpass"
    cat >"$askpass" <<'ASKPASS'
#!/usr/bin/env bash
case "$1" in
  *Username*) printf '%s\n' 'git' ;;
  *Password*) printf '%s\n' "$GITEA_MIRROR_SYNC_TOKEN" ;;
  *) exit 1 ;;
esac
ASKPASS
    export GIT_ASKPASS="$askpass"
    export GIT_TERMINAL_PROMPT=0
    ;;
  file://*)
    ;;
  *)
    printf 'REMOTE_URL must use https:// (production) or file:// (tests)\n' >&2
    exit 5
    ;;
esac

actual_sha="$(git rev-parse HEAD)"
if [[ "$actual_sha" != "$expected_sha" ]]; then
  printf 'checked out SHA does not match EXPECTED_SHA\n' >&2
  exit 3
fi

git push --porcelain "$remote_url" HEAD:refs/heads/main
remote_sha="$(git ls-remote "$remote_url" refs/heads/main | awk 'NR == 1 { print $1 }')"
if [[ "$remote_sha" != "$expected_sha" ]]; then
  printf 'remote main SHA mismatch after push\n' >&2
  exit 6
fi
printf 'Gitea main synchronized at %s\n' "$expected_sha"
```

Run:

```bash
chmod 0755 scripts/sync_gitea_main.sh
python -m pytest tests/infra/test_sync_gitea.py::test_script_pushes_main_and_rejects_non_fast_forward -q
python -m pytest tests/infra/test_sync_gitea.py::test_https_mode_fails_before_git_when_token_is_missing -q
```

Expected: 两项 PASS；非快进测试返回非零并保持目标分叉 SHA。

- [x] **Step 3：添加 GitHub 平台 guard、最小权限和 Secret 边界**

Create `.github/workflows/sync-gitea.yml`:

```yaml
name: Sync main to Gitea

on:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: sync-gitea-main
  cancel-in-progress: false

jobs:
  sync-main:
    if: ${{ github.server_url == 'https://github.com' && github.repository == 'sc1994/Trading-Agents-Web' && github.ref == 'refs/heads/main' }}
    runs-on: ubuntu-latest
    steps:
      - name: Check out the authoritative commit
        uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
        with:
          fetch-depth: 0
          persist-credentials: false
      - name: Push only HEAD to Gitea main and verify the SHA
        env:
          GITEA_MIRROR_SYNC_TOKEN: ${{ secrets.GITEA_MIRROR_SYNC_TOKEN }}
        run: >-
          bash scripts/sync_gitea_main.sh
          https://gitea.suncheng.online:81/suncheng/Trading-Agents-Web.git
          "${GITHUB_SHA}"
```

Update the test assertion from `assert "HEAD:refs/heads/main" not in text` to these structured checks:

```python
    run_command = job["steps"][1]["run"]
    assert "scripts/sync_gitea_main.sh" in run_command
    assert "https://gitea.suncheng.online:81/suncheng/Trading-Agents-Web.git" in run_command
    assert job["steps"][1]["env"] == {
        "GITEA_MIRROR_SYNC_TOKEN": "${{ secrets.GITEA_MIRROR_SYNC_TOKEN }}"
    }
    script = SCRIPT.read_text(encoding="utf-8")
    assert "HEAD:refs/heads/main" in script
    assert all(flag not in script for flag in ("--force", "--mirror", "--delete"))
```

- [x] **Step 4：运行同步专项测试和静态检查**

Run:

```bash
python -m pytest tests/infra/test_sync_gitea.py -q
ruff check scripts tests/infra/test_sync_gitea.py
bash -n scripts/sync_gitea_main.sh
git diff --check
```

Expected: 所有测试 PASS；ruff、`bash -n`、`git diff --check` 退出 0。

- [x] **Step 5：提交同步边界**

Run:

```bash
git add pyproject.toml scripts/sync_gitea_main.sh \
  .github/workflows/sync-gitea.yml tests/infra/test_sync_gitea.py
git commit -m "ci: sync GitHub main to Gitea safely"
```

Expected: commit 只包含 GitHub→Gitea 同步及其测试，不包含 Gitea Docker 发布。

---

### Task 3：恢复 CODI-61 的本地镜像发布与回滚控制器并限定复审

**Stage：** 1（新设计 PR 合并后恢复；Task 1/2 已完成）

**Files：**
- Create: `scripts/local_image_release.py`
- Create: `tests/infra/test_local_image_release.py`

**Interfaces：**
- Consumes: Task 1 的上游 `Dockerfile`、`.dockerignore` 和 `tradingagents` ENTRYPOINT；本机 Docker Engine。
- Produces: Task 4 调用的 `publish`/`rollback` CLI；不读取 workflow Secret 或 TradingAgents 应用配置；不提供跨进程锁、原子 claim 或宿主机全局互斥保证。

**本轮恢复门禁：** CODI-61 原开发回执记录 head `245e48c112880157a39665b3e525ba4acd1f90d1`，原代码审查基于 `origin/main@7dd23562296d87caa4a12e1e4adf4bec42b08abd` 验证定向 10 tests、ruff、编译和 CLI 后，只因现已豁免的检查后写入竞态返回“计划缺口”。新设计 PR 合并后，父流程必须在原 CODI-61 中恢复工作，不建替代 Issue；先取回该原 checkout/head 并 fresh-fetch 当时最新 `origin/main`。若原 head 不可取回则返回受阻，不根据评论重造未知代码；若 head 可取回，只允许在 CODI-61 内做本计划要求的测试命名/说明调整并重新走独立代码审查，旧“计划缺口”不得直接改写为“通过”。

- [ ] **Step 1：核对失败保护、顺序复用、可观察冲突、stable 感知保留和回滚测试**

Create `tests/infra/test_local_image_release.py`:

```python
import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/local_image_release.py"
SPEC = importlib.util.spec_from_file_location("local_image_release", MODULE_PATH)
assert SPEC and SPEC.loader
release = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = release
SPEC.loader.exec_module(release)

SHA = "1" * 40
OLD_1 = "2" * 40
OLD_2 = "3" * 40
OLD_3 = "4" * 40


def completed(stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["docker"], 0, stdout=stdout, stderr="")


def test_smoke_failure_never_tags_full_sha_or_stable() -> None:
    docker = Mock()
    docker.inspect.return_value = release.ImageInfo(
        id="sha256:candidate",
        created="2026-09-01T00:00:00Z",
        revision=SHA,
        managed=True,
    )
    docker.exists.side_effect = [False, True]
    docker.call.side_effect = [
        completed(),
        subprocess.CalledProcessError(1, ["docker", "run"]),
        completed(),
    ]
    with pytest.raises(subprocess.CalledProcessError):
        release.publish(docker, SHA, "trading-agents-web", 3, Path("."), pid=7)
    calls = [call.args[0] for call in docker.call.call_args_list]
    assert not any(args[:2] == ["image", "tag"] for args in calls)
    assert ["image", "rm", f"trading-agents-web:candidate-{SHA}-7"] in calls
    docker.list_managed_sha_images.assert_not_called()
    docker.remove_image.assert_not_called()


def test_publish_smokes_offline_before_updating_stable() -> None:
    docker = Mock()
    candidate = release.ImageInfo(
        id="sha256:candidate",
        created="2026-09-01T00:00:00Z",
        revision=SHA,
        managed=True,
    )
    docker.inspect.return_value = candidate
    docker.exists.side_effect = [False, False, True, False]
    docker.call.return_value = completed()
    docker.list_managed_sha_images.return_value = [candidate]
    docker.used_image_ids.return_value = set()
    release.publish(docker, SHA, "trading-agents-web", 3, Path("."), pid=7)
    calls = [call.args[0] for call in docker.call.call_args_list]
    smoke_index = next(i for i, args in enumerate(calls) if args[0] == "run")
    stable_index = calls.index(
        ["image", "tag", f"trading-agents-web:{SHA}", "trading-agents-web:local-stable"]
    )
    assert smoke_index < stable_index
    smoke = calls[smoke_index]
    assert ["--network", "none"] == smoke[smoke.index("--network") : smoke.index("--network") + 2]
    assert "--read-only" in smoke
    assert "--help" == smoke[-1]


def test_matching_immutable_sha_is_reused_without_build_or_overwrite() -> None:
    docker = Mock()
    existing = release.ImageInfo(
        id="sha256:existing",
        created="2026-09-01T00:00:00Z",
        revision=SHA,
        managed=True,
    )
    docker.exists.side_effect = [True, True]
    docker.inspect.return_value = existing
    docker.list_managed_sha_images.return_value = [existing]
    docker.used_image_ids.return_value = set()
    docker.call.return_value = completed()

    release.publish(docker, SHA, "trading-agents-web", 3, Path("."), pid=7)

    calls = [call.args[0] for call in docker.call.call_args_list]
    assert not any(args[0] == "build" for args in calls)
    assert ["image", "tag", f"trading-agents-web:{SHA}", "trading-agents-web:local-stable"] in calls
    assert not any(
        args[:3] == ["image", "tag", f"trading-agents-web:candidate-{SHA}-7"]
        for args in calls
    )


def test_conflicting_immutable_sha_is_rejected_before_docker_mutation() -> None:
    docker = Mock()
    docker.exists.return_value = True
    docker.inspect.return_value = release.ImageInfo(
        id="sha256:foreign",
        created="2026-09-01T00:00:00Z",
        revision=SHA,
        managed=False,
    )
    with pytest.raises(RuntimeError, match="immutable SHA tag conflicts"):
        release.publish(docker, SHA, "trading-agents-web", 3, Path("."), pid=7)
    assert docker.call.call_count == 0


def test_observed_different_image_at_final_check_is_rejected() -> None:
    docker = Mock()
    candidate = release.ImageInfo(
        id="sha256:candidate",
        created="2026-09-01T00:00:00Z",
        revision=SHA,
        managed=True,
    )
    existing = release.ImageInfo(
        id="sha256:other",
        created="2026-09-01T00:00:01Z",
        revision=SHA,
        managed=True,
    )
    docker.exists.side_effect = [False, True, True]
    docker.inspect.side_effect = [candidate, existing]
    docker.call.return_value = completed()
    with pytest.raises(RuntimeError, match="different image ID"):
        release.publish(docker, SHA, "trading-agents-web", 3, Path("."), pid=7)
    calls = [call.args[0] for call in docker.call.call_args_list]
    assert not any(
        args == ["image", "tag", f"trading-agents-web:candidate-{SHA}-7", f"trading-agents-web:{SHA}"]
        for args in calls
    )
    assert not any(args[-1:] == ["trading-agents-web:local-stable"] for args in calls)
    assert ["image", "rm", f"trading-agents-web:candidate-{SHA}-7"] in calls
    docker.list_managed_sha_images.assert_not_called()
    docker.remove_image.assert_not_called()


def test_cleanup_counts_rolled_back_stable_among_three_and_skips_in_use() -> None:
    docker = Mock()
    stable = release.ImageInfo("id-stable", "2026-09-01T00:00:00Z", OLD_3, True)
    docker.exists.return_value = True
    docker.inspect.return_value = stable
    docker.list_managed_sha_images.return_value = [
        release.ImageInfo("id-new", "2026-09-05T00:00:00Z", SHA, True),
        release.ImageInfo("id-2", "2026-09-04T00:00:00Z", OLD_1, True),
        release.ImageInfo("id-used", "2026-09-03T00:00:00Z", OLD_2, True),
        stable,
        release.ImageInfo("id-old", "2026-08-31T00:00:00Z", "5" * 40, True),
    ]
    docker.used_image_ids.return_value = {"id-used"}
    release.cleanup(docker, "trading-agents-web", keep=3)
    docker.remove_image.assert_called_once_with(f"trading-agents-web:{'5' * 40}")
    assert all(OLD_3 not in str(call) for call in docker.remove_image.call_args_list)


def test_cleanup_refuses_stable_without_matching_full_sha_tag() -> None:
    docker = Mock()
    docker.exists.return_value = True
    docker.inspect.return_value = release.ImageInfo(
        "id-stable", "2026-09-01T00:00:00Z", OLD_3, True
    )
    docker.list_managed_sha_images.return_value = [
        release.ImageInfo("id-new", "2026-09-05T00:00:00Z", SHA, True)
    ]
    with pytest.raises(RuntimeError, match="matching immutable SHA tag"):
        release.cleanup(docker, "trading-agents-web", keep=3)
    docker.remove_image.assert_not_called()


def test_rollback_requires_matching_managed_revision() -> None:
    docker = Mock()
    docker.inspect.return_value = release.ImageInfo(
        id="sha256:kept",
        created="2026-09-01T00:00:00Z",
        revision=SHA,
        managed=True,
    )
    release.rollback(docker, SHA, "trading-agents-web")
    docker.call.assert_called_once_with(
        ["image", "tag", f"trading-agents-web:{SHA}", "trading-agents-web:local-stable"]
    )
```

Run:

```bash
python -m pytest tests/infra/test_local_image_release.py -q
```

Expected: clean `main` reconstruction 因模块尚不存在而 FAIL；恢复的 CODI-61 head 则应运行到 10 tests PASS。该测试只覆盖第二次 `exists` 已观察到不同 image ID 后拒绝写入，不覆盖、模拟或声称“第二次检查返回不存在之后、实际 tag 之前”的竞争写入绝不会改指标签。

- [ ] **Step 2：实现 DockerClient、镜像元数据校验与安全清理**

Create executable `scripts/local_image_release.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
REVISION_LABEL = "org.opencontainers.image.revision"
MANAGED_LABEL = "io.trading-agents-web.managed"


@dataclass(frozen=True)
class ImageInfo:
    id: str
    created: str
    revision: str
    managed: bool


class DockerClient:
    def call(
        self,
        args: Sequence[str],
        *,
        check: bool = True,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["docker", *args],
            check=check,
            text=True,
            capture_output=capture_output,
        )

    def inspect(self, ref: str) -> ImageInfo:
        result = self.call(
            ["image", "inspect", "--format", "{{json .}}", ref],
            capture_output=True,
        )
        payload = json.loads(result.stdout)
        labels = payload.get("Config", {}).get("Labels") or {}
        return ImageInfo(
            id=payload["Id"],
            created=payload["Created"],
            revision=labels.get(REVISION_LABEL, ""),
            managed=labels.get(MANAGED_LABEL) == "true",
        )

    def exists(self, ref: str) -> bool:
        result = self.call(["image", "inspect", ref], check=False, capture_output=True)
        return result.returncode == 0

    def list_managed_sha_images(self, image: str) -> list[ImageInfo]:
        result = self.call(
            ["image", "ls", "--format", "{{.Repository}}\t{{.Tag}}", image],
            capture_output=True,
        )
        images: list[ImageInfo] = []
        for line in result.stdout.splitlines():
            repository, tag = line.split("\t", maxsplit=1)
            if repository != image or not FULL_SHA.fullmatch(tag):
                continue
            info = self.inspect(f"{image}:{tag}")
            if info.managed and info.revision == tag:
                images.append(info)
        return images

    def used_image_ids(self) -> set[str]:
        ids = self.call(
            ["container", "ls", "--all", "--quiet"], capture_output=True
        ).stdout.split()
        if not ids:
            return set()
        output = self.call(
            ["container", "inspect", "--format", "{{.Image}}", *ids],
            capture_output=True,
        ).stdout
        return set(output.split())

    def remove_image(self, ref: str) -> None:
        self.call(["image", "rm", ref])


def validate_sha(value: str) -> str:
    if not FULL_SHA.fullmatch(value):
        raise ValueError("SHA must be 40 lowercase hexadecimal characters")
    return value


def require_immutable(info: ImageInfo, sha: str) -> ImageInfo:
    if not info.managed or info.revision != sha:
        raise RuntimeError("immutable SHA tag conflicts with managed release metadata")
    return info


def smoke(docker: DockerClient, ref: str) -> None:
    docker.call(
        [
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            ref,
            "--help",
        ]
    )


def cleanup(docker: DockerClient, image: str, keep: int) -> None:
    if keep < 1:
        raise ValueError("keep must be at least 1")
    images = sorted(
        docker.list_managed_sha_images(image),
        key=lambda item: (item.created, item.revision),
        reverse=True,
    )
    stable_ref = f"{image}:local-stable"
    if not docker.exists(stable_ref):
        raise RuntimeError("local-stable is missing; refusing cleanup")
    stable = docker.inspect(stable_ref)
    if not stable.managed or not FULL_SHA.fullmatch(stable.revision):
        raise RuntimeError("local-stable is not a managed SHA image; refusing cleanup")
    if not any(
        item.id == stable.id and item.revision == stable.revision for item in images
    ):
        raise RuntimeError("local-stable has no matching immutable SHA tag")

    retained = {stable.revision}
    for info in images:
        if len(retained) >= keep:
            break
        retained.add(info.revision)

    used = docker.used_image_ids()
    for info in images:
        ref = f"{image}:{info.revision}"
        if info.revision in retained:
            continue
        if info.id in used:
            print(f"skip in-use image {ref}")
            continue
        docker.remove_image(ref)
        print(f"removed expired successful image {ref}")


def publish(
    docker: DockerClient,
    sha: str,
    image: str,
    keep: int,
    context: Path,
    *,
    pid: int | None = None,
) -> None:
    sha = validate_sha(sha)
    pid = os.getpid() if pid is None else pid
    candidate = f"{image}:candidate-{sha}-{pid}"
    immutable = f"{image}:{sha}"
    stable = f"{image}:local-stable"

    if docker.exists(immutable):
        require_immutable(docker.inspect(immutable), sha)
        smoke(docker, immutable)
        docker.call(["image", "tag", immutable, stable])
        print(f"reused {immutable} and promoted it to {stable}")
        cleanup(docker, image, keep)
        return

    candidate_created = False
    try:
        docker.call(
            [
                "build",
                "--label",
                f"{REVISION_LABEL}={sha}",
                "--label",
                f"{MANAGED_LABEL}=true",
                "--tag",
                candidate,
                str(context),
            ]
        )
        candidate_created = True
        candidate_info = require_immutable(docker.inspect(candidate), sha)
        smoke(docker, candidate)

        if docker.exists(immutable):
            existing = require_immutable(docker.inspect(immutable), sha)
            if existing.id != candidate_info.id:
                raise RuntimeError(
                    "immutable SHA tag appeared with a different image ID; refusing overwrite"
                )
        else:
            # v1.1.0 accepts the same-SHA cross-process race after this check.
            docker.call(["image", "tag", candidate, immutable])

        docker.call(["image", "tag", immutable, stable])
        print(f"promoted {immutable} to {stable}")
        cleanup(docker, image, keep)
    finally:
        if candidate_created and docker.exists(candidate):
            docker.call(["image", "rm", candidate], check=False)


def rollback(docker: DockerClient, sha: str, image: str) -> None:
    sha = validate_sha(sha)
    immutable = f"{image}:{sha}"
    info = docker.inspect(immutable)
    if not info.managed or info.revision != sha:
        raise RuntimeError("rollback image is not a managed successful SHA image")
    docker.call(["image", "tag", immutable, f"{image}:local-stable"])
    print(f"rolled local-stable back to {immutable}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    publish_parser = subparsers.add_parser("publish")
    publish_parser.add_argument("--sha", required=True)
    publish_parser.add_argument("--image", default="trading-agents-web")
    publish_parser.add_argument("--keep", type=int, default=3)
    publish_parser.add_argument("--context", type=Path, default=Path("."))
    rollback_parser = subparsers.add_parser("rollback")
    rollback_parser.add_argument("--sha", required=True)
    rollback_parser.add_argument("--image", default="trading-agents-web")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    docker = DockerClient()
    if args.command == "publish":
        publish(docker, args.sha, args.image, args.keep, args.context)
    else:
        rollback(docker, args.sha, args.image)


if __name__ == "__main__":
    main()
```

该最小实现必须保留第二次可观察检查和失败分支，但不得增加 `flock`、文件锁、分布式锁、原子 claim 服务或检查后竞态注入 hook。注释明确窄窗口已由 v1.1.0 接受，不代表允许顺序覆盖、删除检查或放宽后续 stable/cleanup 门禁。

- [ ] **Step 3：运行单元测试并补充两个失败边界**

Add tests that call `validate_sha("abc")` and `rollback` with `managed=False`:

```python
def test_short_sha_is_rejected_before_docker_is_called() -> None:
    docker = Mock()
    with pytest.raises(ValueError, match="40 lowercase"):
        release.publish(docker, "abc", "trading-agents-web", 3, Path("."))
    assert docker.method_calls == []


def test_rollback_rejects_unmanaged_image() -> None:
    docker = Mock()
    docker.inspect.return_value = release.ImageInfo(
        id="sha256:foreign",
        created="2026-09-01T00:00:00Z",
        revision=SHA,
        managed=False,
    )
    with pytest.raises(RuntimeError, match="not a managed successful"):
        release.rollback(docker, SHA, "trading-agents-web")
    docker.call.assert_not_called()
```

Run:

```bash
chmod 0755 scripts/local_image_release.py
python -m pytest tests/infra/test_local_image_release.py -q
ruff check scripts/local_image_release.py tests/infra/test_local_image_release.py
```

Expected: 10 tests PASS；其中顺序既有 SHA 复用、预先存在冲突、最终检查可观察冲突拒绝、失败保护、旧 SHA 回滚后清理和 stable traceability 回归均通过；不要求最终检查后写入竞态绝对不可变测试；ruff 退出 0。

- [ ] **Step 4：用真实上游 Dockerfile 做本地候选 smoke，不提升项目稳定 tag**

Run in a disposable Docker namespace:

```bash
SOURCE_SHA="$(git rev-parse HEAD)"
docker build \
  --label "org.opencontainers.image.revision=${SOURCE_SHA}" \
  --label "io.trading-agents-web.managed=true" \
  --tag "trading-agents-web-plan-check:${SOURCE_SHA}" .
docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  "trading-agents-web-plan-check:${SOURCE_SHA}" --help
docker image rm "trading-agents-web-plan-check:${SOURCE_SHA}"
```

Expected: build 成功；CLI 显示帮助并退出 0；没有容器残留；不创建 `trading-agents-web:local-stable`。若执行环境没有 Docker，记录该项由 Task 4 的受控 Runner 首次验证，不声称本地通过。

- [ ] **Step 5：提交或续提交 CODI-61 的控制器范围调整**

Run:

```bash
git add scripts/local_image_release.py tests/infra/test_local_image_release.py
git commit -m "test: align local release race acceptance"
```

Expected: 在 CODI-61 原实现历史上追加可审查提交；diff 仍只包含控制器与其测试，不包含 workflow、Secret 或宿主机状态文件。若恢复 head 已准确使用新测试名和 v1.1.0 注释且无需文件修改，不创建空 commit，直接用原 head 进入新的独立代码审查。

---

### Task 4：编排 Gitea main 质量门禁、串行发布和人工回滚

**Stage：** 2（CODI-59 在 Task 3 代码 PR 合并前保持 parked）

**Files：**
- Create: `scripts/resolve_release_target.py`
- Create: `.gitea/workflows/local-release.yml`
- Create: `tests/infra/test_release_target.py`
- Create: `tests/infra/test_gitea_release_workflow.py`

**Interfaces：**
- Consumes: Task 2 同步到 Gitea 的完整 SHA；Task 3 的 `local_image_release.py`；Runner 标签 `ubuntu-latest`；checkout action 临时使用的私有仓库 read credential。
- Produces: `resolve_release_target.py` 只基于完整本地 checkout 输出已校验的 `target_sha`/`operation`；`push(main)` 自动 publish；`workflow_dispatch(operation=publish|rollback,target_sha=<40hex>)` 人工重跑/回滚；固定 concurrency 只串行本 workflow 管理的运行，不是宿主机全局锁。

- [ ] **Step 1：写 workflow 结构失败测试**

Create `tests/infra/test_gitea_release_workflow.py`:

```python
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".gitea/workflows/local-release.yml"
PINNED_ACTION = re.compile(r"^[^@]+@[0-9a-f]{40}$")


def load() -> dict:
    return yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_only_main_push_and_manual_dispatch_can_enter() -> None:
    document = load()
    assert document["on"]["push"]["branches"] == ["main"]
    assert "pull_request" not in document["on"]
    assert "workflow_dispatch" in document["on"]
    assert document["permissions"] == {"contents": "read"}
    assert document["concurrency"] == {
        "group": "trading-agents-web-local-release",
        "cancel-in-progress": "false",
    }


def test_quality_matrix_and_dependency_gate_match_upstream_ci() -> None:
    jobs = load()["jobs"]
    assert jobs["test"]["strategy"]["matrix"]["python-version"] == [
        "3.10", "3.11", "3.12", "3.13"
    ]
    assert set(jobs["publish"]["needs"]) == {"resolve", "test", "clean-install", "lint"}
    all_runs = "\n".join(
        step.get("run", "")
        for job in jobs.values()
        for step in job.get("steps", [])
    )
    assert "pytest -q" in all_runs
    assert "import tradingagents, cli.main" in all_runs
    assert "ruff check ." in all_runs
    assert "local_image_release.py publish" in all_runs
    assert "local_image_release.py rollback" in all_runs


def test_every_job_is_gitea_guarded_and_actions_are_commit_pinned() -> None:
    jobs = load()["jobs"]
    for job in jobs.values():
        assert "github.server_url == 'https://gitea.suncheng.online:81'" in job["if"]
        for step in job.get("steps", []):
            if "uses" in step:
                assert PINNED_ACTION.fullmatch(step["uses"])
```

Run:

```bash
python -m pytest tests/infra/test_gitea_release_workflow.py -q
```

Expected: FAIL，因为 Gitea workflow 尚不存在。

- [ ] **Step 2：写私有 checkout 与恶意人工输入回归测试**

Create `tests/infra/test_release_target.py`:

```python
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/resolve_release_target.py"
SPEC = importlib.util.spec_from_file_location("resolve_release_target", MODULE_PATH)
assert SPEC and SPEC.loader
resolver = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = resolver
SPEC.loader.exec_module(resolver)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, text=True, capture_output=True
    ).stdout.strip()


def make_history(repo: Path) -> tuple[str, str]:
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Release Resolver Test")
    git(repo, "config", "user.email", "resolver@example.invalid")
    (repo / "data.txt").write_text("first", encoding="utf-8")
    git(repo, "add", "data.txt")
    git(repo, "commit", "-m", "first")
    first = git(repo, "rev-parse", "HEAD")
    (repo / "data.txt").write_text("second", encoding="utf-8")
    git(repo, "commit", "-am", "second")
    return first, git(repo, "rev-parse", "HEAD")


def run_resolver(repo: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    merged.update(env)
    merged["GIT_TERMINAL_PROMPT"] = "0"
    return subprocess.run(
        [sys.executable, str(MODULE_PATH)],
        cwd=repo,
        env=merged,
        text=True,
        capture_output=True,
    )


def test_private_checkout_needs_no_persisted_credentials_or_remote_fetch(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    first, head = make_history(repo)
    git(repo, "remote", "add", "origin", "https://private.invalid/owner/repo.git")
    output = tmp_path / "github-output"
    result = run_resolver(
        repo,
        {
            "RELEASE_EVENT_NAME": "workflow_dispatch",
            "RELEASE_PUSH_SHA": head,
            "RELEASE_INPUT_SHA": first,
            "RELEASE_INPUT_OPERATION": "publish",
            "GITHUB_OUTPUT": str(output),
        },
    )
    assert result.returncode == 0, result.stderr
    assert output.read_text(encoding="utf-8") == (
        f"target_sha={first}\noperation=publish\n"
    )


@pytest.mark.parametrize(
    ("target_suffix", "operation"),
    [
        ('"\ntouch injected', "publish"),
        ("$(touch injected)", "publish"),
        ("", 'publish"\ntouch injected'),
    ],
)
def test_quotes_newlines_and_substitutions_are_rejected_as_data(
    tmp_path: Path, target_suffix: str, operation: str
) -> None:
    repo = tmp_path / "repo"
    _, head = make_history(repo)
    result = run_resolver(
        repo,
        {
            "RELEASE_EVENT_NAME": "workflow_dispatch",
            "RELEASE_PUSH_SHA": head,
            "RELEASE_INPUT_SHA": head + target_suffix,
            "RELEASE_INPUT_OPERATION": operation,
            "GITHUB_OUTPUT": str(tmp_path / "github-output"),
        },
    )
    assert result.returncode == 2
    assert not (repo / "injected").exists()


def test_push_sha_must_equal_the_checked_out_head(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    first, _ = make_history(repo)
    result = run_resolver(
        repo,
        {
            "RELEASE_EVENT_NAME": "push",
            "RELEASE_PUSH_SHA": first,
            "RELEASE_INPUT_SHA": "",
            "RELEASE_INPUT_OPERATION": "",
            "GITHUB_OUTPUT": str(tmp_path / "github-output"),
        },
    )
    assert result.returncode == 2
```

Run:

```bash
python -m pytest tests/infra/test_release_target.py -q
```

Expected: FAIL，因为 resolver 尚不存在。

- [ ] **Step 3：实现只读取 env 与本地完整历史的 resolver**

Create executable `scripts/resolve_release_target.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
OPERATIONS = {"publish", "rollback"}
EVENTS = {"push", "workflow_dispatch"}


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], check=False, text=True, capture_output=True
    )


def resolve(env: Mapping[str, str]) -> tuple[str, str]:
    event = env.get("RELEASE_EVENT_NAME", "")
    if event not in EVENTS:
        raise ValueError("unsupported release event")
    if event == "push":
        target_sha = env.get("RELEASE_PUSH_SHA", "")
        operation = "publish"
    else:
        target_sha = env.get("RELEASE_INPUT_SHA", "")
        operation = env.get("RELEASE_INPUT_OPERATION", "")

    if not FULL_SHA.fullmatch(target_sha):
        raise ValueError("target SHA must be 40 lowercase hexadecimal characters")
    if operation not in OPERATIONS:
        raise ValueError("operation must be publish or rollback")

    head = git("rev-parse", "HEAD")
    if head.returncode != 0:
        raise ValueError("checkout HEAD is unavailable")
    if event == "push" and target_sha != head.stdout.strip():
        raise ValueError("push SHA does not equal checked out HEAD")
    if git("cat-file", "-e", f"{target_sha}^{{commit}}").returncode != 0:
        raise ValueError("target commit is absent from the local checkout")
    if git("merge-base", "--is-ancestor", target_sha, "HEAD").returncode != 0:
        raise ValueError("target commit is not in protected main history")
    return target_sha, operation


def main() -> None:
    try:
        target_sha, operation = resolve(os.environ)
        output_path = Path(os.environ["GITHUB_OUTPUT"])
    except (KeyError, ValueError):
        print("release target rejected", file=sys.stderr)
        raise SystemExit(2) from None
    with output_path.open("a", encoding="utf-8") as output:
        output.write(f"target_sha={target_sha}\n")
        output.write(f"operation={operation}\n")


if __name__ == "__main__":
    main()
```

Run:

```bash
chmod 0755 scripts/resolve_release_target.py
python -m pytest tests/infra/test_release_target.py -q
ruff check scripts/resolve_release_target.py tests/infra/test_release_target.py
```

Expected: 5 tests PASS；测试中的 `origin` 不可达且没有凭据，但祖先 SHA 仍只靠本地 checkout 通过；三组恶意输入都作为数据返回 2，未创建 sentinel 文件。

- [ ] **Step 4：添加安全目标 SHA 解析和上游等价门禁**

Create `.gitea/workflows/local-release.yml`:

```yaml
name: Qualify and publish local image

on:
  push:
    branches: [main]
  workflow_dispatch:
    inputs:
      operation:
        description: Publish a main commit or roll local-stable back
        required: true
        type: choice
        default: publish
        options: [publish, rollback]
      target_sha:
        description: Full 40-character SHA from main history
        required: true
        type: string

permissions:
  contents: read

concurrency:
  group: trading-agents-web-local-release
  cancel-in-progress: false

jobs:
  resolve:
    if: ${{ github.server_url == 'https://gitea.suncheng.online:81' && github.repository == 'suncheng/Trading-Agents-Web' && github.ref == 'refs/heads/main' }}
    runs-on: ubuntu-latest
    outputs:
      target_sha: ${{ steps.target.outputs.target_sha }}
      operation: ${{ steps.target.outputs.operation }}
    steps:
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683
        with:
          ref: ${{ github.event_name == 'push' && github.sha || 'main' }}
          fetch-depth: 0
          persist-credentials: false
      - id: target
        name: Resolve and authorize the target SHA from local history
        env:
          RELEASE_EVENT_NAME: ${{ github.event_name }}
          RELEASE_PUSH_SHA: ${{ github.sha }}
          RELEASE_INPUT_SHA: ${{ inputs.target_sha }}
          RELEASE_INPUT_OPERATION: ${{ inputs.operation }}
        run: python scripts/resolve_release_target.py

  test:
    if: ${{ github.server_url == 'https://gitea.suncheng.online:81' && needs.resolve.outputs.operation == 'publish' }}
    needs: [resolve]
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.10", "3.11", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683
        with:
          ref: ${{ needs.resolve.outputs.target_sha }}
          persist-credentials: false
      - uses: actions/setup-python@42375524e23c412d93fb67b49958b491fce71c38
        with:
          python-version: ${{ matrix.python-version }}
      - run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev]"
          pytest -q

  clean-install:
    if: ${{ github.server_url == 'https://gitea.suncheng.online:81' && needs.resolve.outputs.operation == 'publish' }}
    needs: [resolve]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683
        with:
          ref: ${{ needs.resolve.outputs.target_sha }}
          persist-credentials: false
      - uses: actions/setup-python@42375524e23c412d93fb67b49958b491fce71c38
        with:
          python-version: "3.12"
      - run: |
          python -m pip install --upgrade pip
          pip install .
          python -c "import tradingagents, cli.main; print('clean-install import OK')"

  lint:
    if: ${{ github.server_url == 'https://gitea.suncheng.online:81' && needs.resolve.outputs.operation == 'publish' }}
    needs: [resolve]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683
        with:
          ref: ${{ needs.resolve.outputs.target_sha }}
          persist-credentials: false
      - uses: actions/setup-python@42375524e23c412d93fb67b49958b491fce71c38
        with:
          python-version: "3.12"
      - run: |
          pip install "ruff>=0.15"
          ruff check .
```

该 concurrency group 只约束该仓库中由此 Gitea workflow 调度的运行。实现、测试、日志和 runbook 都不得把它描述为对宿主机直接 CLI、其他 workflow 或外部进程的互斥；不在 Task 4 添加 `flock` 或任何全局锁。

- [ ] **Step 5：添加通过门禁后的 publish 和独立 rollback job**

Append under `jobs` in the same workflow:

```yaml
  publish:
    if: ${{ github.server_url == 'https://gitea.suncheng.online:81' && needs.resolve.outputs.operation == 'publish' }}
    needs: [resolve, test, clean-install, lint]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683
        with:
          ref: ${{ needs.resolve.outputs.target_sha }}
          persist-credentials: false
      - name: Build, smoke, promote, and clean managed images
        env:
          RELEASE_TARGET_SHA: ${{ needs.resolve.outputs.target_sha }}
        run: |
          set -euo pipefail
          test "$(git rev-parse HEAD)" = "$RELEASE_TARGET_SHA"
          python scripts/local_image_release.py publish \
            --sha "$RELEASE_TARGET_SHA" \
            --image trading-agents-web \
            --keep 3 \
            --context .

  rollback:
    if: ${{ github.server_url == 'https://gitea.suncheng.online:81' && github.event_name == 'workflow_dispatch' && needs.resolve.outputs.operation == 'rollback' }}
    needs: [resolve]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683
        with:
          ref: ${{ needs.resolve.outputs.target_sha }}
          persist-credentials: false
      - name: Point local-stable at an existing retained SHA image
        env:
          RELEASE_TARGET_SHA: ${{ needs.resolve.outputs.target_sha }}
        run: >-
          python scripts/local_image_release.py rollback
          --sha "$RELEASE_TARGET_SHA"
          --image trading-agents-web
```

- [ ] **Step 6：强化 workflow 测试的凭据、输入、socket、Secret 和触发边界**

Add to `tests/infra/test_gitea_release_workflow.py`:

```python
def test_resolver_uses_local_history_and_env_data_boundary() -> None:
    document = load()
    resolve = document["jobs"]["resolve"]
    checkout = resolve["steps"][0]["with"]
    assert checkout["fetch-depth"] == "0"
    assert checkout["persist-credentials"] == "false"
    assert "github.sha" in checkout["ref"]
    target = resolve["steps"][1]
    assert target["run"] == "python scripts/resolve_release_target.py"
    assert "${{ inputs." not in target["run"]
    assert target["env"] == {
        "RELEASE_EVENT_NAME": "${{ github.event_name }}",
        "RELEASE_PUSH_SHA": "${{ github.sha }}",
        "RELEASE_INPUT_SHA": "${{ inputs.target_sha }}",
        "RELEASE_INPUT_OPERATION": "${{ inputs.operation }}",
    }
    all_runs = "\n".join(
        step.get("run", "")
        for job in document["jobs"].values()
        for step in job.get("steps", [])
    )
    assert "git fetch" not in all_runs


def test_release_workflow_has_no_application_or_sync_secrets() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    forbidden = (
        "GITEA_MIRROR_SYNC_TOKEN",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "ALPHA_VANTAGE_API_KEY",
        "docker compose up",
        "pull_request",
    )
    assert all(value not in text for value in forbidden)
    assert "--keep 3" in text
    assert "fetch-depth: 0" in text
    assert "scripts/resolve_release_target.py" in text
```

Run:

```bash
python -m pytest tests/infra/test_release_target.py -q
python -m pytest tests/infra/test_gitea_release_workflow.py -q
python -m pytest tests/infra/test_local_image_release.py -q
ruff check .
git diff --check
```

Expected: resolver 5 tests、workflow 5 tests和控制器 10 tests 全部 PASS；私有仓库无持久凭据、本地祖先校验、恶意输入、顺序复用、可观察冲突与 stable 保护回归均通过；workflow 测试证明固定 group 和 `cancel-in-progress: false`，但不声称宿主机全局互斥；ruff 与 diff check 退出 0。

- [ ] **Step 7：在 Runner 管理侧核对权限前置条件，不改仓库外状态**

由 Gitea 管理员在 UI 中核对并留存截图或审计记录：

```text
Runner: gitea-runner-ai
Required label: ubuntu-latest
Scope: suncheng/Trading-Agents-Web or a trusted scope that excludes untrusted repositories
Executor: Docker
Docker socket: available to this protected main release workflow
Gitea main: protected; direct unreviewed changes disallowed
PR/other branch/tag workflows: cannot invoke this workflow or obtain release permission
```

Expected: 每项均被现有配置证明；任何一项不满足时，Task 4 保持未交付，且不通过扩大 token 权限绕过。

- [ ] **Step 8：提交 Gitea 发布编排**

Run:

```bash
git add scripts/resolve_release_target.py \
  .gitea/workflows/local-release.yml \
  tests/infra/test_release_target.py \
  tests/infra/test_gitea_release_workflow.py
git commit -m "ci: qualify and publish local images on Gitea"
```

Expected: commit 不包含应用密钥、`.env`、Compose 启动或常驻服务配置。

---

### Task 5：交付运维 runbook、隔离失败验收 workflow 与端到端证据

**Stage：** 3（CODI-58 在 Task 4 代码 PR 合并及外部配置就绪前保持 parked）

**Files：**
- Create: `docs/operations/repository-sync-and-local-release.md`
- Create: `.gitea/workflows/local-release-failure-acceptance.yml`
- Create: `tests/infra/test_operations_runbook.py`

**Interfaces：**
- Consumes: Tasks 1-4 的 workflow 与脚本；用户在平台 Secret/Runner/分支保护中完成的外部配置。
- Produces: 常规 publish/rollback 仅走受控 Gitea workflow 的运维流程；同一 concurrency group 下、唯一 SHA/镜像 namespace 的失败验收；直接 CLI 受控例外的零 active/queued/直接进程前置证明；生产 stable/旧成功镜像不变及临时产物清理证据。

- [ ] **Step 1：写 workflow-only 运维与隔离失败验收的失败测试**

Create `tests/infra/test_operations_runbook.py`:

```python
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
RUNBOOK = ROOT / "docs/operations/repository-sync-and-local-release.md"
RELEASE_WORKFLOW = ROOT / ".gitea/workflows/local-release.yml"
FAILURE_WORKFLOW = ROOT / ".gitea/workflows/local-release-failure-acceptance.yml"


def load_workflow(path: Path) -> dict:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_runbook_covers_serial_operations_and_recovery_without_secrets() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    required = (
        "GITEA_MIRROR_SYNC_TOKEN",
        "Contents: Read-only",
        "code write",
        "gh workflow run sync-gitea.yml --ref main",
        "workflow_dispatch",
        "local-stable",
        "docker image inspect",
        "docker container inspect",
        "rollback",
        "revoke",
        "~/.tradingagents",
        "last three",
        "Same-SHA concurrency residual risk",
        "not a host-wide lock",
        "serialized publish rerun",
        "Routine publish and rollback use only the controlled Gitea workflow",
        "Direct CLI is limited to controlled recovery or acceptance",
        "no active or queued",
        "no other direct publish or rollback",
    )
    assert all(value in text for value in required)
    assert "pgrep -af '[l]ocal_image_release.py (publish|rollback)'" in text
    routine = text.split("## Automatic local publication", 1)[1].split(
        "## Controlled direct CLI exception", 1
    )[0]
    controlled = text.split("## Controlled direct CLI exception", 1)[1]
    assert "python scripts/local_image_release.py" not in routine
    assert "python scripts/local_image_release.py rollback" in controlled
    assert "gh secret set GITEA_MIRROR_SYNC_TOKEN" in text
    assert "token=" not in text.lower()
    assert "--force" not in text
    assert "--mirror" not in text


def test_failure_acceptance_is_isolated_and_uses_the_release_group() -> None:
    document = load_workflow(FAILURE_WORKFLOW)
    release = load_workflow(RELEASE_WORKFLOW)
    assert set(document["on"]) == {"workflow_dispatch"}
    assert document["permissions"] == {"contents": "read"}
    assert document["concurrency"] == release["concurrency"] == {
        "group": "trading-agents-web-local-release",
        "cancel-in-progress": "false",
    }
    job = document["jobs"]["smoke-failure-acceptance"]
    assert job["runs-on"] == "ubuntu-latest"
    assert "github.server_url == 'https://gitea.suncheng.online:81'" in job["if"]
    assert "github.repository == 'suncheng/Trading-Agents-Web'" in job["if"]
    assert "github.ref == 'refs/heads/main'" in job["if"]
    checkout = job["steps"][0]
    assert checkout["uses"] == "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683"
    assert checkout["with"]["persist-credentials"] == "false"
    script = job["steps"][1]["run"]
    subprocess.run(["bash", "-n"], input=script, text=True, check=True)
    text = FAILURE_WORKFLOW.read_text(encoding="utf-8")
    required = (
        'TEST_IMAGE="trading-agents-web-acceptance-${ACCEPTANCE_RUN_ID}-${ACCEPTANCE_PROCESS_ID}"',
        'TEST_SHA="$(printf',
        "PROD_STABLE_BEFORE",
        "PROD_IMAGES_BEFORE",
        "local_image_release.py publish",
        '--image "$TEST_IMAGE"',
        "FAILURE_STATUS",
        "cleanup_acceptance",
        "docker image rm",
    )
    assert all(value in text for value in required)
    assert "trading-agents-web:local-stable" in text
    assert "GITEA_MIRROR_SYNC_TOKEN" not in text
    assert "local_image_release.py rollback" not in text
```

Run:

```bash
python -m pytest tests/infra/test_operations_runbook.py -q
```

Expected: 2 tests FAIL，因为 runbook 和隔离失败验收 workflow 尚不存在。

- [ ] **Step 2：编写 workflow-only 常规操作、受控 CLI 例外、失败验收和审计流程**

Create `docs/operations/repository-sync-and-local-release.md` with these exact operational sections and commands:

````markdown
# Repository sync and local release operations

## Security boundaries

GitHub `sc1994/Trading-Agents-Web` `main` is authoritative. Gitea `suncheng/Trading-Agents-Web` is a private, one-way target. Never resolve divergence with force, mirror, ref deletion, or a reverse push. The release does not start an application container, read runtime `.env` values, or access `~/.tradingagents`. Routine publish and rollback use only the controlled Gitea workflow; neither a shell session nor another workflow is a routine release entry point.

## One-time user configuration

1. Create a dedicated Gitea automation account. Grant only code write access to `suncheng/Trading-Agents-Web`; do not grant instance, organization, user, Actions Secret, or other repository access.
2. Create the narrowest token supported by the installed Gitea version. Keep the token out of issues, commits, shell arguments, remote URLs, logs, and ordinary variables.
3. From an authenticated interactive terminal, run `gh secret set GITEA_MIRROR_SYNC_TOKEN --repo sc1994/Trading-Agents-Web` and enter the token only at the protected prompt.
4. Keep GitHub workflow permissions at `Contents: Read-only`. Protect GitHub and Gitea `main`; do not develop directly on Gitea.
5. Confirm `gitea-runner-ai` exposes label `ubuntu-latest`, uses the Docker executor, is scoped to trusted repositories, and makes the host Docker socket available only to the protected local-release path. Docker socket access is host-root equivalent.

## Trigger and verify synchronization

A GitHub `main` push starts synchronization automatically. An authorized maintainer can rerun it with:

```bash
gh workflow run sync-gitea.yml --ref main --repo sc1994/Trading-Agents-Web
gh run list --workflow sync-gitea.yml --repo sc1994/Trading-Agents-Web --limit 5
```

The job log may show the target repository and full source/target SHA. It must not show a token or credential-bearing URL. Verify the authoritative SHA with:

```bash
GITHUB_SHA="$(git ls-remote git@github.com:sc1994/Trading-Agents-Web.git refs/heads/main | awk '{print $1}')"
printf 'GitHub main: %s\n' "$GITHUB_SHA"
```

Use an authenticated Gitea Git client to read `refs/heads/main`, store it as `GITEA_SHA`, and require `test "$GITHUB_SHA" = "$GITEA_SHA"`. Do not put a token in that URL.

The resolve job's checkout action uses the private repository read credential only while fetching full history, then removes it with `persist-credentials: false`. Target validation performs no later `git fetch`: push SHA and manual inputs enter the resolver only through job `env`, and the resolver checks the local commit object and `merge-base --is-ancestor <sha> HEAD`. Quotes, newlines, substitutions, short SHAs, unknown commits, non-ancestors and unsupported operations fail before any Docker job can start.

## Publication serialization and direct CLI restrictions

Routine publish and rollback use only the controlled Gitea workflow `Qualify and publish local image`. Automatic publish and its `workflow_dispatch` publish/rollback operations share `trading-agents-web-local-release` with `cancel-in-progress: false`. The dedicated failure-acceptance workflow uses that same group. The group serializes these managed runs, but it is not a host-wide lock.

Direct CLI is limited to controlled recovery or acceptance. Before dispatching the failure-acceptance workflow or starting any direct `local_image_release.py publish|rollback`, the operator must:

1. Open the Gitea Actions run lists for `Qualify and publish local image` and `Local release smoke-failure acceptance`; filter waiting, pending, queued and running states, and record that there is no active or queued pre-existing run. If state cannot be proven, do not start the operation.
2. On the Runner host, require that there is no other direct publish or rollback process:

```bash
if pgrep -af '[l]ocal_image_release.py (publish|rollback)'; then
  printf 'another direct publish or rollback is active; stop\n' >&2
  exit 1
fi
```

3. Reserve one maintenance window and operator. Start no second direct command and enqueue no other release/rollback/acceptance workflow until the current operation finishes and its cleanup/state evidence is recorded.

These are explicit operational and audit prerequisites, not a cross-process mutex. They do not turn workflow concurrency into a host-wide lock and do not widen the approved same-SHA post-check/pre-write residual risk to different SHA ordering, `local-stable`, cleanup, retention or rollback.

## Automatic local publication

A synchronized Gitea `main` push starts `Qualify and publish local image`. The workflow must show all four `pytest -q` matrix jobs, clean-install/import, and ruff passing before the publish job starts. The publish log must show the full candidate SHA and `local-stable` promotion, without application API keys or complete environment dumps.

Inspect the stable image and its source revision on the Runner host:

```bash
docker image inspect trading-agents-web:local-stable \
  --format '{{.Id}} {{index .Config.Labels "org.opencontainers.image.revision"}}'
docker image ls trading-agents-web --format '{{.Repository}}:{{.Tag}} {{.ID}} {{.CreatedAt}}'
docker container ls --all --filter ancestor=trading-agents-web:local-stable
```

The revision label must equal Gitea `main`. The final command must not show a container started by the release workflow.

## Manual publish rerun

Open the Gitea Actions `Qualify and publish local image` workflow on `main`, choose `workflow_dispatch`, set operation to `publish`, and enter a full 40-character commit SHA already contained in Gitea `main` history. The resolve job rejects short, unknown, or non-ancestor values. Do not invoke the controller directly for a routine rerun; if another managed run is active, let the fixed group queue and serialize this run without cancellation.

## Failure behavior

A missing, revoked, expired, or underprivileged `GITEA_MIRROR_SYNC_TOKEN` makes GitHub synchronization fail without changing GitHub or forcing Gitea. Rotate by revoking the old Gitea token, creating another least-privilege token, and rerunning `gh secret set GITEA_MIRROR_SYNC_TOKEN --repo sc1994/Trading-Agents-Web`.

A test, lint, clean-install, Docker build, or offline CLI smoke failure prevents promotion. Capture the failed job URL and stage, then verify that `docker image inspect trading-agents-web:local-stable --format '{{.Id}}'` is unchanged. The workflow does not clean old successful images on these failures.

A Gitea non-fast-forward failure is resolved by identifying and reviewing the Gitea-only commit. Do not run a force or mirror command. Restore a fast-forward relationship through an explicitly reviewed repository recovery procedure before rerunning synchronization.

## Same-SHA concurrency residual risk

The fixed Gitea concurrency group serializes both release workflows managed by this repository; it is not a host-wide lock for direct CLI invocations, unrelated workflows, or external processes. All routine publish and rollback operations stay inside the controlled workflow. The accepted residual window exists only when two publishing processes target the same full SHA and a competing tag write lands after another process's final absence check but before its `docker image tag` write. In that window the later writer may redirect the full-SHA tag to a different image ID; no cross-process lock or atomic claim is provided.

This exception does not authorize smoke-before-promotion bypasses, failed-process stable updates, cleanup after failure, retention violations, deleting in-use images, unsafe rollback, force/mirror Git recovery, or broader credentials. Every process that updates `local-stable` must first complete offline smoke successfully; a failed process must not update stable or run successful-release cleanup.

If logs or image inspection indicate the accepted race:

1. Stop starting additional direct or workflow publications and let an already active controlled promotion/cleanup stage finish and record its result.
2. Set `TARGET_SHA` to the affected full SHA and inspect both tags without changing them:

```bash
read -r TARGET_SHA
docker image inspect "trading-agents-web:${TARGET_SHA}" \
  --format '{{.Id}} {{index .Config.Labels "io.trading-agents-web.managed"}} {{index .Config.Labels "org.opencontainers.image.revision"}}'
docker image inspect trading-agents-web:local-stable \
  --format '{{.Id}} {{index .Config.Labels "io.trading-agents-web.managed"}} {{index .Config.Labels "org.opencontainers.image.revision"}}'
```

3. Record only image IDs, managed/revision labels, SHA, stage and sanitized logs. Do not expose environment dumps or credentials.
4. Re-run the publication with the Gitea `workflow_dispatch` `publish` operation for the same authorized main-history SHA as a serialized publish rerun. Before dispatch, apply the run-list/direct-process preflight above; then let the workflow re-smoke the observed managed SHA tag and only afterward promote/clean. If metadata does not match, keep the workflow failed and escalate for reviewed image recovery; do not overwrite manually or widen Git/token permissions.

Acceptance does not actively manufacture this race in the shared `trading-agents-web` namespace and does not claim the full-SHA tag can never be redirected in that window. Unit tests continue to cover sequential reuse, pre-existing conflicts and conflicts observable at the final check.

## Manual rollback

List retained full SHA tags and inspect managed/revision labels without changing them:

```bash
docker image ls trading-agents-web --format '{{.Repository}}:{{.Tag}} {{.CreatedAt}}'
read -r TARGET_SHA
case "$TARGET_SHA" in
  (*[!0-9a-f]*|'') printf 'full lowercase SHA required\n' >&2; exit 2 ;;
esac
test "${#TARGET_SHA}" -eq 40
docker image inspect "trading-agents-web:${TARGET_SHA}" \
  --format '{{.Id}} {{index .Config.Labels "io.trading-agents-web.managed"}} {{index .Config.Labels "org.opencontainers.image.revision"}}'
```

For a routine rollback, open `Qualify and publish local image` on Gitea `main`, choose `workflow_dispatch`, set operation to `rollback`, enter the retained full main-history SHA, and wait for that managed run to finish before starting another operation. Rollback retags an existing image; it does not build, run an analysis, read application keys, or modify TradingAgents data.

## Controlled direct CLI exception

Direct CLI is limited to controlled recovery or acceptance and is never the routine rollback or publish path. A human-approved recovery may call the controller only after the Gitea run-list and Runner process preflight above proves no active or queued managed run and no other direct publish or rollback; if proof is unavailable, stop. Keep the maintenance window exclusive until the command and state verification finish. Example after those gates:

```bash
python scripts/local_image_release.py rollback \
  --sha "$TARGET_SHA" --image trading-agents-web
docker image inspect trading-agents-web:local-stable \
  --format '{{index .Config.Labels "org.opencontainers.image.revision"}}'
```

The dedicated `Local release smoke-failure acceptance` workflow is the controlled acceptance use of the CLI. It shares the production release concurrency group but writes only a unique test SHA/image namespace and verifies the production namespace did not change.

## Retention and safe cleanup

After a successful promotion, the controller keeps the last three managed full-SHA images in total. The SHA currently referenced by `local-stable` consumes one retention slot even after a rollback; the remaining slots are filled by newest `Created` values. Before removing any other tag it compares immutable image IDs against all running and stopped containers from `docker container inspect`; an in-use image is skipped and logged. In sequential execution, matching managed metadata is reused and re-smoked while pre-existing or final-check-observable conflicts abort publication. The accepted same-SHA post-check/pre-write race remains documented above; it does not relax retention, in-use protection, stable ordering or failure cleanup. `local-stable`, candidate tags, unmanaged images, and any image used by a container are never selected as expired successful SHA images.

## Acceptance evidence

Retain the GitHub sync run URL, Gitea release run URL, common main SHA, tag verification result, four pytest results, clean-install/import result, ruff result, candidate/stable revision label, retained full-SHA list, failed-promotion stable ID comparison, rollback before/after revision, residual-risk inspection/serialized-recovery record, and confirmation that no release container or `~/.tradingagents` change was produced. For each direct recovery/acceptance exception, also retain the preflight timestamp/operator, zero active/queued pre-existing run evidence, zero other direct-process evidence, unique test SHA/image namespace, production stable/full-SHA snapshot before and after, failed job URL/status, and temporary-artifact cleanup result. Evidence contains job URLs, SHAs, image IDs, stage names and sanitized errors only; never attach tokens, credential URLs, complete environment dumps or application secrets. Do not create acceptance evidence by racing two publishers in the shared namespace.
````

Create `.gitea/workflows/local-release-failure-acceptance.yml` as the controlled smoke-failure acceptance path:

```yaml
name: Local release smoke-failure acceptance

on:
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: trading-agents-web-local-release
  cancel-in-progress: false

jobs:
  smoke-failure-acceptance:
    if: ${{ github.server_url == 'https://gitea.suncheng.online:81' && github.repository == 'suncheng/Trading-Agents-Web' && github.ref == 'refs/heads/main' }}
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683
        with:
          ref: ${{ github.sha }}
          persist-credentials: false
      - name: Prove isolated smoke failure preserves production images
        env:
          ACCEPTANCE_SOURCE_SHA: ${{ github.sha }}
          ACCEPTANCE_RUN_ID: ${{ github.run_id }}
        run: |
          set -euo pipefail
          case "$ACCEPTANCE_RUN_ID" in
            (*[!0-9]*|'')
              printf 'numeric run id required\n' >&2
              exit 2
              ;;
          esac
          ACCEPTANCE_PROCESS_ID="$$"
          if pgrep -af '[l]ocal_image_release.py (publish|rollback)'; then
            printf 'another direct publish or rollback is active\n' >&2
            exit 1
          fi

          TEST_IMAGE="trading-agents-web-acceptance-${ACCEPTANCE_RUN_ID}-${ACCEPTANCE_PROCESS_ID}"
          TEST_SHA="$(printf '%s\n' \
            "${ACCEPTANCE_SOURCE_SHA}:${ACCEPTANCE_RUN_ID}:${ACCEPTANCE_PROCESS_ID}" |
            sha256sum | cut -c1-40)"
          case "$TEST_SHA" in
            (*[!0-9a-f]*|'') exit 2 ;;
          esac
          test "${#TEST_SHA}" -eq 40
          printf 'acceptance test image=%s sha=%s\n' "$TEST_IMAGE" "$TEST_SHA"

          snapshot_production_success_images() {
            docker image ls trading-agents-web --no-trunc \
              --format '{{.Tag}} {{.ID}}' |
              awk '$1 ~ /^[0-9a-f]{40}$/ {print}' |
              LC_ALL=C sort
          }

          PROD_STABLE_BEFORE="$(docker image inspect \
            trading-agents-web:local-stable --format '{{.Id}}')"
          PROD_IMAGES_BEFORE="$(snapshot_production_success_images)"
          test -z "$(docker image ls --all --quiet \
            --filter "reference=${TEST_IMAGE}:*")"
          test -z "$(docker image ls --all --quiet \
            --filter "label=org.opencontainers.image.revision=${TEST_SHA}")"

          FAILURE_CONTEXT="$(mktemp -d ./release-failure-acceptance.XXXXXX)"
          cleanup_acceptance() {
            rm -rf "$FAILURE_CONTEXT"
            mapfile -t test_refs < <(
              docker image ls "$TEST_IMAGE" \
                --format '{{.Repository}}:{{.Tag}}' |
                awk '$1 !~ /:<none>$/ {print}'
            )
            if (( ${#test_refs[@]} )); then
              docker image rm "${test_refs[@]}"
            fi
            mapfile -t test_ids < <(
              docker image ls --all --quiet \
                --filter "label=org.opencontainers.image.revision=${TEST_SHA}" |
                sort -u
            )
            if (( ${#test_ids[@]} )); then
              docker image rm "${test_ids[@]}"
            fi
          }
          trap cleanup_acceptance EXIT
          cat >"$FAILURE_CONTEXT/Dockerfile" <<'DOCKERFILE'
          FROM trading-agents-web:local-stable
          ENTRYPOINT ["/bin/false"]
          DOCKERFILE

          set +e
          python scripts/local_image_release.py publish \
            --sha "$TEST_SHA" \
            --image "$TEST_IMAGE" \
            --keep 3 \
            --context "$FAILURE_CONTEXT"
          FAILURE_STATUS=$?
          set -e
          test "$FAILURE_STATUS" -ne 0
          printf 'expected isolated publish failure status=%s\n' "$FAILURE_STATUS"

          test "$(docker image inspect trading-agents-web:local-stable \
            --format '{{.Id}}')" = "$PROD_STABLE_BEFORE"
          PROD_IMAGES_AFTER="$(snapshot_production_success_images)"
          test "$PROD_IMAGES_AFTER" = "$PROD_IMAGES_BEFORE"
          test -z "$(docker image ls --all --quiet \
            --filter "reference=${TEST_IMAGE}:*")"

          cleanup_acceptance
          trap - EXIT
          test -z "$(docker image ls --all --quiet \
            --filter "reference=${TEST_IMAGE}:*")"
          test -z "$(docker image ls --all --quiet \
            --filter "label=org.opencontainers.image.revision=${TEST_SHA}")"
          printf 'production stable preserved id=%s\n' "$PROD_STABLE_BEFORE"
          printf 'production successful SHA images preserved:\n%s\n' \
            "$PROD_IMAGES_AFTER"
          printf 'isolated failure artifacts cleaned for image=%s sha=%s\n' \
            "$TEST_IMAGE" "$TEST_SHA"
```

The operator dispatches this workflow only after the run-list/direct-process preflight in the runbook records no pre-existing active/queued workflow and no direct release process. The workflow's own run is then the sole active managed acceptance operation; the shared group prevents overlap with the regular release workflow, while the host-wide non-lock boundary remains explicit.

- [ ] **Step 3：运行全部仓库级验证**

Run:

```bash
python -m pytest tests/infra/test_operations_runbook.py -q
python -m pytest -q
ruff check .
bash -n scripts/sync_gitea_main.sh
python scripts/local_image_release.py --help
git diff --check
git status --short
```

Expected: runbook/隔离 workflow 2 tests PASS，全量 pytest 0 failures；验收 workflow 内嵌 Bash 通过 `bash -n`；ruff、同步脚本 parse、CLI help、diff check 均退出 0；status 只包含 Task 5 runbook、失败验收 workflow 和测试。

- [ ] **Step 4：提交 runbook 与隔离失败验收 workflow**

Run:

```bash
git add docs/operations/repository-sync-and-local-release.md \
  .gitea/workflows/local-release-failure-acceptance.yml \
  tests/infra/test_operations_runbook.py
git commit -m "docs: add serialized local release operations"
```

Expected: workflow/docs/test commit 可独立审查；两个 Gitea workflow 使用同一固定 concurrency group；不包含凭据值、截图中的敏感信息、生产镜像变更或运行时数据。

- [ ] **Step 5：在用户完成 Secret 与 Runner 配置后收集常规 workflow 端到端证据**

先在 Gitea Actions 中记录两个发布 workflow 没有重叠运行，并在 Runner 主机确认没有直接控制器进程；整个常规验收只触发受控 workflow，不调用本地控制器 CLI。Run and record sanitized results:

```bash
if pgrep -af '[l]ocal_image_release.py (publish|rollback)'; then
  printf 'unexpected direct release process\n' >&2
  exit 1
fi
gh workflow run sync-gitea.yml --ref main --repo sc1994/Trading-Agents-Web
gh run list --workflow sync-gitea.yml --repo sc1994/Trading-Agents-Web --limit 1
GITHUB_SHA="$(git ls-remote git@github.com:sc1994/Trading-Agents-Web.git refs/heads/main | awk '{print $1}')"
printf 'authoritative sha=%s\n' "$GITHUB_SHA"
docker image inspect trading-agents-web:local-stable \
  --format '{{.Id}} {{index .Config.Labels "org.opencontainers.image.revision"}}'
docker image ls trading-agents-web --format '{{.Repository}}:{{.Tag}} {{.ID}} {{.CreatedAt}}'
docker container ls --all --filter ancestor=trading-agents-web:local-stable
```

Expected: GitHub sync success；Gitea `main` 与 `GITHUB_SHA` 相同；Gitea 门禁全部通过；stable revision 与同一 SHA 相同；保留集合总数为三个并包含 stable SHA，若还有集合外旧 SHA 则日志和容器检查证明其因正在被容器使用而跳过；另有 `local-stable` alias；无发布 workflow 启动的容器。证据证明 publish 由 `Qualify and publish local image` 完成、没有直接 CLI 进程，两个同 group workflow 没有重叠；同时记录“这不是宿主机全局锁”的边界，不在共享 namespace 并发启动 publisher。

- [ ] **Step 6：由共享 concurrency group 管理隔离 smoke 失败与 workflow rollback 验收**

先在 Gitea Actions 中打开 `Qualify and publish local image` 与 `Local release smoke-failure acceptance` 的 run list。记录 waiting/pending/queued/running 均为零；若不能证明零 active/queued pre-existing run，则不触发验收。在 Runner 主机执行只读前置快照并确认没有直接控制器进程；保持该 shell 会话打开，供 workflow 完成后的只读对比使用：

```bash
set -euo pipefail
if pgrep -af '[l]ocal_image_release.py (publish|rollback)'; then
  printf 'another direct publish or rollback is active\n' >&2
  exit 1
fi
PROD_STABLE_BEFORE="$(docker image inspect \
  trading-agents-web:local-stable --format '{{.Id}}')"
PROD_IMAGES_BEFORE="$(
  docker image ls trading-agents-web --no-trunc --format '{{.Tag}} {{.ID}}' |
    awk '$1 ~ /^[0-9a-f]{40}$/ {print}' |
    LC_ALL=C sort
)"
printf 'production stable before=%s\n' "$PROD_STABLE_BEFORE"
printf 'production SHA images before:\n%s\n' "$PROD_IMAGES_BEFORE"
```

在 Gitea `main` 上人工 dispatch `Local release smoke-failure acceptance`。不要直接运行控制器，不要在该 run 排队或运行期间启动任何 publish/rollback/其他失败验收。等待 workflow 成功结束；workflow 成功表示其中隔离 publish 如预期返回非零，且所有保护断言与清理通过。记录 job URL、唯一 `TEST_IMAGE`/`TEST_SHA`、嵌套 `FAILURE_STATUS`、生产 stable ID/完整 SHA 快照和 cleanup 行。然后从脱敏日志输入唯一标识并在 Runner 主机复核：

```bash
set -euo pipefail
read -r TEST_IMAGE
read -r TEST_SHA
[[ "$TEST_IMAGE" =~ ^trading-agents-web-acceptance-[0-9]+-[0-9]+$ ]]
[[ "$TEST_SHA" =~ ^[0-9a-f]{40}$ ]]
PROD_STABLE_AFTER="$(docker image inspect \
  trading-agents-web:local-stable --format '{{.Id}}')"
PROD_IMAGES_AFTER="$(
  docker image ls trading-agents-web --no-trunc --format '{{.Tag}} {{.ID}}' |
    awk '$1 ~ /^[0-9a-f]{40}$/ {print}' |
    LC_ALL=C sort
)"
test "$PROD_STABLE_AFTER" = "$PROD_STABLE_BEFORE"
test "$PROD_IMAGES_AFTER" = "$PROD_IMAGES_BEFORE"
test -z "$(docker image ls --all --quiet \
  --filter "reference=${TEST_IMAGE}:*")"
test -z "$(docker image ls --all --quiet \
  --filter "label=org.opencontainers.image.revision=${TEST_SHA}")"
```

Expected: 验收 workflow 与生产 workflow 使用同一 `trading-agents-web-local-release` group 且未重叠；它在全新测试 SHA/镜像 namespace 中从无 immutable tag 分支构建，离线 smoke 确定失败，嵌套 publish 非零；生产 `local-stable` ID 和全部既有成功 SHA tag 前后逐字一致；测试 immutable/stable/candidate/tagged/dangling 镜像及临时 context 均被删除。没有在共享生产 namespace 制造同 SHA 竞态，也不声称 concurrency group 是宿主机全局锁。

当至少存在两个保留成功 SHA 时，只通过常规 Gitea `workflow_dispatch` 验收回滚。选择一个非当前 SHA，先 dispatch `rollback` 并等待成功，再对原当前 SHA dispatch 第二个 `rollback` 并等待成功；两个 run 之间不得重叠，也不得直接运行 CLI：

```bash
set -euo pipefail
CURRENT_SHA="$(docker image inspect trading-agents-web:local-stable \
  --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')"
mapfile -t RETAINED_SHAS < <(
  docker image ls trading-agents-web --format '{{.Tag}}' |
    awk '/^[0-9a-f]{40}$/'
)
if (( ${#RETAINED_SHAS[@]} < 2 )); then
  printf 'live rollback requires at least two retained successful SHA images\n' >&2
  exit 75
fi
ROLLBACK_SHA=""
for retained_sha in "${RETAINED_SHAS[@]}"; do
  if [[ "$retained_sha" != "$CURRENT_SHA" ]]; then
    ROLLBACK_SHA="$retained_sha"
    break
  fi
done
test -n "$ROLLBACK_SHA"
printf 'dispatch rollback to %s, wait, then dispatch rollback to %s\n' \
  "$ROLLBACK_SHA" "$CURRENT_SHA"
```

Expected: Gitea resolver accepts both retained SHAs as `main` history；第一个受控 workflow run 使 stable 指向旧 SHA，第二个在前一 run 完成后无需重建地恢复当前 SHA；run URL/开始结束时间证明串行，Runner 上无其他直接进程。过程中没有启动分析容器、读取应用密钥、清理旧成功镜像或修改 `~/.tradingagents`。若只有一个成功 SHA，在第二个成功发布后再收集 live rollback 证据；自动测试继续覆盖回滚标签校验。

---

## 最终验收映射

| Spec 验收项 | 实现任务 | 自动证据 | 平台/人工证据 |
|---|---|---|---|
| 1-2 来源、README、许可证、人工 upstream | 已完成基线 A | README 双侧字节/独立根 fixture、merge ancestry、LICENSE hash | 已合并 PR #2 parents、`UPSTREAM.md`；本轮只回归 |
| 3-7 单向同步、最小权限、失败关闭 | 已完成基线 B | YAML 结构测试、bare repo 快进/分叉测试、缺失 token 测试 | 已合并 PR #3；GitHub workflow 权限页、Secret 名、两端 main SHA |
| 8 平台隔离 | 已完成基线 B、Tasks 4-5 | GitHub 同步与两个 Gitea workflow 的 `github.server_url`/repository/ref guard 测试 | 错误平台/非 main job 为 skipped |
| 9-10 触发与质量矩阵 | Task 4 | 私有 checkout 本地历史、恶意输入、workflow trigger/matrix/dependency 测试 | Gitea 四版本 pytest、clean import、ruff job 状态 |
| 11-12 build、离线 smoke、稳定提升 | Tasks 3、4 | publish 顺序、匹配 SHA 复用、可观察冲突拒绝和 `--network none` 测试 | 候选/stable revision label 与 job log |
| 13 失败不改变稳定版本 | Tasks 3、5 | build/smoke failure、最终检查可观察冲突、隔离验收 workflow 结构/脚本测试 | 唯一测试 namespace 的嵌套 publish 非零；生产 stable/完整 SHA 快照不变；临时产物清空 |
| 14 最近三版和使用中保护 | Task 3 | rolled-back stable 占保留槽、缺失完整 SHA 拒绝、used-image 测试 | Runner 主机镜像/容器清单 |
| 15 人工回滚 | Tasks 3-5 | managed revision 回滚与常规 workflow 命令测试 | 两次 Gitea `workflow_dispatch` 串行回滚及前后 revision；无直接 CLI |
| 16 workflow 串行与过期 pending | Tasks 4-5 | 两个 Gitea workflow 使用相同 group、`cancel-in-progress: false`，验收 Bash 语法测试 | Gitea run 时间不重叠；触发前零 active/queued 与零直接进程证据；不声称宿主机全局锁 |
| 17 不启动/不读密钥/不碰数据 | Tasks 3-5 | workflow forbidden-string 测试、无 volume/env 的 smoke 命令 | 无新增容器、无 `~/.tradingagents` 变更 |
| 18 脱敏审计 | 已完成基线 B、Task 5 | askpass、runbook Secret 值、失败验收 workflow forbidden-string 检查 | workflow/job URL、唯一测试标识、生产快照与脱敏日志抽查 |
| 19 有限同 SHA 竞态豁免 | Tasks 3-5 | 顺序复用、预存冲突、最终检查可观察冲突；不注入检查后竞态 | 常规操作 workflow-only；直接例外零活动前置；风险条件/核对/串行重跑；不扩大至 stable/不同 SHA |

## 计划自检

执行以下命令检查版本、批准规格原文、占位符、路径和任务依赖：

```bash
set -euo pipefail
BASE_SHA="15969d15e0f1491d9f3c9c26c4635c004f380ed2"
REVISION_PARENT="64f74dc1934b8a97fd416a4d5ab61a6aa280b2a6"
SPEC="docs/design/Trading-Agents-Web-repository-initialization-gitea-local-release-design-spec-v1.1.0.md"
OLD_PLAN="docs/plans/repository-initialization-gitea-local-release-implementation-plan-v1.1.0.md"
PLAN="docs/plans/repository-initialization-gitea-local-release-implementation-plan-v1.1.1.md"
test "$(sha256sum "$SPEC" | awk '{print $1}')" = \
  "971e8fb990cb911f11160107d887a531b2eed6d955ea156a70ad4cbaf3197754"
test "$(sha256sum "$OLD_PLAN" | awk '{print $1}')" = \
  "acdcca2cceefa7f757ed4ded57a4261b2bb7f38a439884ada77993e35d6611ca"
test "$(git rev-parse HEAD^)" = "$REVISION_PARENT"
test "$(git rev-parse "${REVISION_PARENT}^")" = "$BASE_SHA"
test "$(git rev-list --count "${BASE_SHA}..HEAD")" = "2"
test "$(git diff --name-only "$REVISION_PARENT" HEAD)" = "$PLAN"
test "$(git diff --name-only "$BASE_SHA" HEAD | sort)" = \
  "$(printf '%s\n' "$SPEC" "$OLD_PLAN" "$PLAN" | sort)"
if rg -n 'TB''D|TO''DO|implement ''later|fill in ''details|Similar to ''Task' "$PLAN"; then
  exit 1
fi
test "$(rg -c '^### 已完成基线' "$PLAN")" = "2"
test "$(rg -c '^### Task [345]' "$PLAN")" = "3"
test "$(rg -c '^- \[x\] \*\*Step' "$PLAN")" = "12"
test "$(rg -c '^- \[ \] \*\*Step' "$PLAN")" = "19"
rg -n 'v1\.1\.1|Routine publish and rollback use only|Direct CLI is limited|no active or queued|local-release-failure-acceptance|TEST_IMAGE|PROD_IMAGES_BEFORE|not a host-wide lock|CODI-61|PR #3' "$PLAN"
git diff --check "$BASE_SHA" HEAD
git status --short
```

Expected: spec SHA-256 仍精确为 `971e8fb990cb911f11160107d887a531b2eed6d955ea156a70ad4cbaf3197754`，v1.1.0 plan hash 未改；source head 是受阻回执 `64f74dc...` 的单 commit 后继，固定 base 至 head 共两个 commit，总 diff 只含批准 spec 与 v1.1.0/v1.1.1 plans，revision diff 只新增 v1.1.1 plan；两个历史基线不重跑；Task 3-5 依赖和 TDD 步骤完整；常规 workflow-only、直接 CLI 零活动前置、共享 concurrency group、唯一测试 namespace、生产快照不变、临时清理和非全局锁边界均可检索；占位符扫描无命中；diff check 退出 0，worktree clean。
