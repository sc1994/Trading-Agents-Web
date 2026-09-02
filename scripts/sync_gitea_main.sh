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
