#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 2 ]]; then
  printf 'usage: initialize_gitea_main.sh REMOTE_URL EXPECTED_NEW_SHA\n' >&2
  exit 2
fi

remote_url="$1"
expected_new_sha="$2"
expected_old_sha="052251b1a133a3aef9506b864c30d96c628c45be"
readonly backup_tag="pre-github-sync-20260920-052251b1"

if [[ ! "$expected_new_sha" =~ ^[0-9a-f]{40}$ ]]; then
  printf 'EXPECTED_NEW_SHA must be a full lowercase commit SHA\n' >&2
  exit 2
fi

askpass=""
temporary_tag=""
git_cleanup_enabled=false
readonly initialization_ref="refs/gitea-initialize/main"
cleanup() {
  if [[ "$git_cleanup_enabled" == true ]]; then
    if [[ -n "$temporary_tag" ]]; then
      git tag -d "$temporary_tag" >/dev/null 2>&1 || true
    fi
    git update-ref -d "$initialization_ref" >/dev/null 2>&1 || true
  fi
  if [[ -n "$askpass" ]]; then
    rm -f "$askpass"
  fi
}
trap cleanup EXIT

case "$remote_url" in
  file://*)
    expected_old_sha="${GITEA_INITIALIZE_TEST_OLD_SHA:-$expected_old_sha}"
    ;;
  https://*)
    if [[ -n "${GITEA_INITIALIZE_TEST_OLD_SHA:-}" ]]; then
      printf 'test old SHA override is forbidden for HTTPS\n' >&2
      exit 7
    fi
    if [[ -z "${TRADING_AGENTS_WEB_GITEA_SYNC_TOKEN:-}" ]]; then
      printf 'TRADING_AGENTS_WEB_GITEA_SYNC_TOKEN is required for HTTPS initialization\n' >&2
      exit 4
    fi
    askpass="$(mktemp)"
    chmod 0700 "$askpass"
    cat >"$askpass" <<'ASKPASS'
#!/usr/bin/env bash
case "$1" in
  *Username*) printf '%s\n' 'git' ;;
  *Password*) printf '%s\n' "$TRADING_AGENTS_WEB_GITEA_SYNC_TOKEN" ;;
  *) exit 1 ;;
esac
ASKPASS
    export GIT_ASKPASS="$askpass"
    export GIT_TERMINAL_PROMPT=0
    ;;
  *)
    printf 'REMOTE_URL must use https:// (production) or file:// (tests)\n' >&2
    exit 5
    ;;
esac
readonly expected_old_sha

git_cleanup_enabled=true
if [[ "$(git rev-parse HEAD)" != "$expected_new_sha" ]]; then
  printf 'checked out SHA does not match EXPECTED_NEW_SHA\n' >&2
  exit 3
fi

git fetch --no-tags "$remote_url" \
  refs/heads/main:"$initialization_ref"
observed_old_sha="$(git rev-parse "$initialization_ref")"
test "$observed_old_sha" = "$expected_old_sha"
test "$(git rev-list --parents -n 1 "$observed_old_sha" | wc -w)" -eq 1
test "$(git ls-tree -r --name-only "$observed_old_sha")" = "README.md"
test "$(git cat-file -s "${observed_old_sha}:README.md")" -eq 0

temporary_tag="gitea-initialize-$$"
git -c user.name='Trading Agents Sync' \
  -c user.email='sync@invalid.local' \
  tag -a "$temporary_tag" "$observed_old_sha" \
  -m "Backup Gitea main before GitHub synchronization"
remote_tag_sha="$(
  git ls-remote "$remote_url" "refs/tags/${backup_tag}^{}" |
    awk 'NR == 1 { print $1 }'
)"
if [[ -z "$remote_tag_sha" ]]; then
  git push --no-follow-tags "$remote_url" \
    "refs/tags/${temporary_tag}:refs/tags/${backup_tag}"
else
  test "$remote_tag_sha" = "$expected_old_sha"
fi
test "$(
  git ls-remote "$remote_url" "refs/tags/${backup_tag}^{}" |
    awk 'NR == 1 { print $1 }'
)" = "$expected_old_sha"

git push --no-follow-tags --force-with-lease="refs/heads/main:${expected_old_sha}" \
  "$remote_url" HEAD:refs/heads/main
test "$(
  git ls-remote "$remote_url" refs/heads/main |
    awk 'NR == 1 { print $1 }'
)" = "$expected_new_sha"
printf 'Gitea main initialized at %s\n' "$expected_new_sha"
