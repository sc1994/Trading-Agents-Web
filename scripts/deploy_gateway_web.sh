#!/usr/bin/env bash
set -Eeuo pipefail

readonly project_name="trading-agents-web"
readonly image_repository="trading-agents-web-ui"
readonly host_port="7681"
readonly compose_file="docker-compose.gateway-web.yml"

if [[ $# -ne 1 ]]; then
    printf 'usage: %s FULL_SHA\n' "$0" >&2
    exit 2
fi

readonly sha="$1"
if [[ ! "$sha" =~ ^[0-9a-f]{40}$ ]]; then
    printf 'FULL_SHA must be exactly 40 lowercase hexadecimal characters\n' >&2
    exit 2
fi

readonly image_ref="${image_repository}:${sha}"
readonly candidate_name="trading-agents-web-candidate-${sha}-$$"

for dependency in docker curl ss cmp mktemp rm sleep; do
    if ! command -v "$dependency" >/dev/null 2>&1; then
        printf 'required command not found: %s\n' "$dependency" >&2
        exit 127
    fi
done

if command -v docker-compose >/dev/null 2>&1; then
    compose_command=(docker-compose)
elif docker compose version >/dev/null 2>&1; then
    compose_command=(docker compose)
else
    printf 'Docker Compose is required\n' >&2
    exit 127
fi
readonly -a compose_command

compose() {
    "${compose_command[@]}" \
        --project-name "$project_name" \
        --file "$compose_file" \
        "$@"
}

tmp_dir=""
candidate_running=false

cleanup() {
    local status=$?
    trap - EXIT INT TERM
    if [[ "$candidate_running" == true ]]; then
        docker rm --force "$candidate_name" >/dev/null 2>&1 || true
    fi
    if [[ -n "$tmp_dir" ]]; then
        rm -rf -- "$tmp_dir"
    fi
    exit "$status"
}
trap cleanup EXIT INT TERM

assert_deployment_port_available() {
    local owner_lines owner_id owner_project owner_service remainder
    local project_web_owns_port=false
    owner_lines=$(
        docker ps \
            --filter "publish=${host_port}" \
            --format '{{.ID}}|{{.Label "com.docker.compose.project"}}|{{.Label "com.docker.compose.service"}}'
    )

    while IFS='|' read -r owner_id owner_project owner_service remainder; do
        [[ -z "$owner_id" ]] && continue
        if [[ "$owner_project" == "$project_name" && "$owner_service" == "web" && -z "$remainder" ]]; then
            project_web_owns_port=true
            continue
        fi
        printf 'port %s is owned by container %s (%s/%s)\n' \
            "$host_port" "$owner_id" "$owner_project" "$owner_service" >&2
        return 1
    done <<< "$owner_lines"

    local listeners
    listeners=$(ss -H -ltn "sport = :${host_port}")
    if [[ -n "$listeners" && "$project_web_owns_port" != true ]]; then
        printf 'port %s is occupied by a non-project process\n' "$host_port" >&2
        return 1
    fi
}

fetch_exact() {
    local url="$1"
    local expected="$2"
    local output="$3"
    local status

    curl --fail --silent --show-error --output "$output" "$url" || {
        status=$?
        printf 'request failed: %s\n' "$url" >&2
        return "$status"
    }
    cmp -s "$output" "$expected" || {
        status=$?
        printf 'response body mismatch: %s\n' "$url" >&2
        return "$status"
    }
}

wait_for_live_container() {
    local container_id status attempt
    container_id=$(compose ps --quiet web) || return $?
    if [[ -z "$container_id" ]]; then
        printf 'Compose web container was not created\n' >&2
        return 1
    fi

    for ((attempt = 1; attempt <= 30; attempt++)); do
        if status=$(
            docker inspect \
                --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
                "$container_id"
        ); then
            case "$status" in
                healthy)
                    return 0
                    ;;
                unhealthy | exited | dead)
                    printf 'Compose web container entered state: %s\n' "$status" >&2
                    return 1
                    ;;
            esac
        fi
        sleep 1
    done

    printf 'timed out waiting for Compose web health\n' >&2
    return 1
}

verify_live_service() {
    wait_for_live_container || return $?
    fetch_exact \
        "http://127.0.0.1:${host_port}/healthz" \
        "$health_expected" \
        "$tmp_dir/live-health.response" || return $?
    fetch_exact \
        "http://127.0.0.1:${host_port}/" \
        "web/index.html" \
        "$tmp_dir/live-index.response"
}

assert_deployment_port_available

docker build \
    --label "org.opencontainers.image.revision=${sha}" \
    --tag "$image_ref" \
    --file web/Dockerfile \
    .

built_revision=$(
    docker image inspect \
        --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' \
        "$image_ref"
)
if [[ "$built_revision" != "$sha" ]]; then
    printf 'built image revision mismatch: expected %s, got %s\n' "$sha" "$built_revision" >&2
    exit 1
fi

tmp_dir=$(mktemp -d)
readonly tmp_dir
health_expected="$tmp_dir/health.expected"
printf 'ok\n' > "$health_expected"

docker run \
    --detach \
    --rm \
    --name "$candidate_name" \
    --read-only \
    --cap-drop ALL \
    --security-opt no-new-privileges \
    --tmpfs /tmp:rw,noexec,nosuid,size=16m \
    --publish 127.0.0.1::8080 \
    "$image_ref" >/dev/null
candidate_running=true

candidate_binding=$(docker port "$candidate_name" 8080/tcp)
if [[ ! "$candidate_binding" =~ ^127\.0\.0\.1:([0-9]{1,5})$ ]]; then
    printf 'candidate received an invalid loopback binding: %s\n' "$candidate_binding" >&2
    exit 1
fi
candidate_port="${BASH_REMATCH[1]}"
if ((candidate_port < 1 || candidate_port > 65535)); then
    printf 'candidate received an invalid port: %s\n' "$candidate_port" >&2
    exit 1
fi

fetch_exact \
    "http://127.0.0.1:${candidate_port}/healthz" \
    "$health_expected" \
    "$tmp_dir/candidate-health.response"
fetch_exact \
    "http://127.0.0.1:${candidate_port}/" \
    "web/index.html" \
    "$tmp_dir/candidate-index.response"

docker rm --force "$candidate_name" >/dev/null
candidate_running=false

old_container_id=""
existing_container_ids=$(
    docker ps \
        --all \
        --filter "label=com.docker.compose.project=${project_name}" \
        --filter "label=com.docker.compose.service=web" \
        --format '{{.ID}}'
)
while IFS= read -r container_id; do
    [[ -z "$container_id" ]] && continue
    if [[ -n "$old_container_id" ]]; then
        printf 'multiple Compose web containers found for project %s\n' "$project_name" >&2
        exit 1
    fi
    old_container_id="$container_id"
done <<< "$existing_container_ids"

old_image=""
old_revision=""
if [[ -n "$old_container_id" ]]; then
    old_image=$(docker inspect --format '{{.Config.Image}}' "$old_container_id")
    if [[ -z "$old_image" ]]; then
        printf 'existing Compose web container has no image reference\n' >&2
        exit 1
    fi
    old_revision=$(
        docker image inspect \
            --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' \
            "$old_image"
    )
    if [[ ! "$old_revision" =~ ^[0-9a-f]{40}$ ]]; then
        printf 'existing image has no valid revision label: %s\n' "$old_image" >&2
        exit 1
    fi
fi

restore_previous_state() {
    local rollback_failed=false
    if [[ -n "$old_image" ]]; then
        export TRADINGAGENTS_WEB_IMAGE="$old_image"
        export TRADINGAGENTS_WEB_REVISION="$old_revision"
        if ! compose up --detach --no-build web; then
            printf 'failed to restore previous Compose web image: %s\n' "$old_image" >&2
            rollback_failed=true
        elif ! verify_live_service; then
            printf 'previous Compose web image did not recover: %s\n' "$old_image" >&2
            rollback_failed=true
        fi
    elif ! compose stop web; then
        printf 'failed to stop unsuccessful first deployment\n' >&2
        rollback_failed=true
    fi

    [[ "$rollback_failed" == false ]]
}

export TRADINGAGENTS_WEB_IMAGE="$image_ref"
export TRADINGAGENTS_WEB_REVISION="$sha"

if compose up --detach --no-build web; then
    if verify_live_service; then
        printf 'deployed %s\n' "$image_ref"
        exit 0
    else
        deployment_status=$?
    fi
else
    deployment_status=$?
fi

restore_previous_state || true
exit "$deployment_status"
