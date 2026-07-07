#!/usr/bin/env bash
# Manual smoke test for textaccounts shallow-clone + ephemeral lifecycle.
#
# Runs Tier 1 (basic create/list/dry-run/destroy/audit) and Tier 3 (orchestrator
# simulation: 5 ephemerals + orphan + permanent, gc by owner). Tier 2 (running
# claude inside a clone) is manual — see docs/SMOKETESTS.yaml.
#
# Usage:
#   scripts/manual-smoke.sh [--parent NAME]
#
# Defaults: --parent personal
#
# The script cleans up after itself on success and via a trap on failure.
# Names are prefixed with a per-run id so reruns can't collide with each other.

set -euo pipefail

PARENT="personal"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --parent) PARENT="$2"; shift 2 ;;
        -h|--help)
            grep '^#' "$0" | head -20
            exit 0
            ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done

RUN_ID="smoke-$(date +%s)"
OWNER="$RUN_ID"
PREFIX="$RUN_ID"
PASS=0
FAIL=0
FAIL_NAMES=()

cleanup() {
    # Best-effort: destroy any ephemerals we created. `gc --owner` is the
    # cheapest way; --max-age 0d catches them regardless of age.
    textaccounts gc --max-age 0d --owner "$OWNER" >/dev/null 2>&1 || true
    # Also nuke the test "permanent" profile we made on purpose.
    if textaccounts repos 2>/dev/null | awk '$1=="REPO"{print $2}' | grep -qx "$PREFIX-permanent"; then
        # Permanent profiles can't be `destroy`ed — drop the dir + edit
        # profiles.yaml manually. We use python because sed across platforms
        # is annoying.
        local perm_path="$HOME/.textaccounts/profiles/$PREFIX-permanent"
        rm -rf "$perm_path" 2>/dev/null || true
        python3 - "$PREFIX-permanent" <<'PY' 2>/dev/null || true
import sys, yaml, pathlib
p = pathlib.Path.home() / ".textaccounts" / "profiles.yaml"
data = yaml.safe_load(p.read_text())
name = sys.argv[1]
if (data.get("profiles") or {}).pop(name, None):
    p.write_text(yaml.safe_dump(data, sort_keys=False))
PY
    fi
}
trap cleanup EXIT

step() {
    local name="$1"; shift
    printf "  %-45s " "$name"
    if "$@"; then
        echo "PASS"
        PASS=$((PASS + 1))
    else
        echo "FAIL"
        FAIL=$((FAIL + 1))
        FAIL_NAMES+=("$name")
    fi
}

# Sanity: parent must exist (use `repos` — parseable, no Rich box-drawing)
if ! textaccounts repos 2>/dev/null | awk '$1=="REPO"{print $2}' | grep -qx "$PARENT"; then
    echo "ERROR: parent profile '$PARENT' not found in registry" >&2
    echo "Available profiles:" >&2
    textaccounts repos >&2
    exit 1
fi

# Helper: does a profile name exist in the registry?
ta_has_profile() {
    textaccounts repos 2>/dev/null | awk '$1=="REPO"{print $2}' | grep -qx "$1"
}
export -f ta_has_profile

echo "Run ID: $RUN_ID  (parent: $PARENT)"
echo

# ---------------------------------------------------------------------------
# Tier 1 — basic create / dry-run / destroy / audit
# ---------------------------------------------------------------------------
echo "Tier 1 — basic shallow-clone + destroy"

BOT="$PREFIX-tier1"

step "create --shallow --owner" \
    bash -c "textaccounts create $BOT --shallow --from $PARENT --owner $OWNER >/dev/null"

step "manifest has shallow: true" \
    bash -c "grep -A8 \"^  $BOT:\" ~/.textaccounts/profiles.yaml | grep -q 'shallow: true'"

step "manifest has ephemeral: true" \
    bash -c "grep -A8 \"^  $BOT:\" ~/.textaccounts/profiles.yaml | grep -q 'ephemeral: true'"

step "manifest has owner=$OWNER" \
    bash -c "grep -A8 \"^  $BOT:\" ~/.textaccounts/profiles.yaml | grep -q \"owner: $OWNER\""

step "dir contains only .claude.json + settings.json" \
    bash -c '
        d=~/.textaccounts/profiles/'"$BOT"'
        [ -f "$d/.claude.json" ] && [ -f "$d/settings.json" ] &&
        [ "$(/bin/ls -A "$d" | wc -l | tr -d " ")" -eq 2 ]
    '

step "profile registered (visible to repos cmd)" \
    bash -c "textaccounts repos | awk '\$1==\"REPO\"{print \$2}' | grep -qx $BOT"

step "gc --dry-run reports without removing" \
    bash -c "
        out=\$(textaccounts gc --max-age 0d --owner $OWNER --dry-run)
        echo \"\$out\" | grep -q 'Would remove' &&
        echo \"\$out\" | grep -q $BOT &&
        ta_has_profile $BOT
    "

step "destroy removes profile" \
    bash -c "textaccounts destroy $BOT >/dev/null && ! ta_has_profile $BOT"

step "destroy removed dir from disk" \
    bash -c "[ ! -d ~/.textaccounts/profiles/$BOT ]"

echo

# ---------------------------------------------------------------------------
# Tier 3 — orchestrator simulation (5 batch + 1 orphan + 1 permanent)
# ---------------------------------------------------------------------------
echo "Tier 3 — gc by owner with mixed profiles"

BATCH_PREFIX="$PREFIX-batch"
ORPHAN="$PREFIX-orphan"
ORPHAN_OWNER="$RUN_ID-orphan"
PERMANENT="$PREFIX-permanent"

# 5 ephemerals under the same run-id
for i in 1 2 3 4 5; do
    textaccounts create "$BATCH_PREFIX-$i" --shallow --from "$PARENT" --owner "$OWNER" >/dev/null
done

# 1 ephemeral under a different owner — should NOT be swept by --owner $OWNER
textaccounts create "$ORPHAN" --shallow --from "$PARENT" --owner "$ORPHAN_OWNER" >/dev/null

# 1 permanent — should NEVER be swept
textaccounts create "$PERMANENT" --shallow --from "$PARENT" >/dev/null

step "all 7 profiles registered" \
    bash -c "
        names=\$(textaccounts repos | awk '\$1==\"REPO\"{print \$2}')
        n=\$(echo \"\$names\" | grep -cE \"^($BATCH_PREFIX-[0-9]+|$ORPHAN|$PERMANENT)\$\" || true)
        [ \"\$n\" -eq 7 ]
    "

# gc with owner filter — should remove the 5 batch-bots only
step "gc --owner $OWNER removes 5 batch-bots" \
    bash -c "
        out=\$(textaccounts gc --max-age 0d --owner $OWNER)
        n=\$(echo \"\$out\" | grep -c 'Removed' || true)
        [ \"\$n\" -eq 5 ]
    "

step "orphan + permanent survive owner-scoped gc" \
    bash -c "ta_has_profile $ORPHAN && ta_has_profile $PERMANENT"

step "destroy refuses non-ephemeral" \
    bash -c "
        textaccounts destroy $PERMANENT >/tmp/smoke-destroy.out 2>&1 && exit 1
        grep -q 'not ephemeral' /tmp/smoke-destroy.out
    "

step "wide gc sweeps remaining ephemerals (orphan), spares permanent" \
    bash -c "
        textaccounts gc --max-age 0d >/dev/null
        ! ta_has_profile $ORPHAN &&
        ta_has_profile $PERMANENT
    "

step "audit log has new entries from this run" \
    bash -c "
        log=~/.local/state/textaccounts/gc.log
        [ -f \"\$log\" ] &&
        grep -q $OWNER \"\$log\"
    "

echo
# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo "Result: $PASS passed, $FAIL failed"
if [ "$FAIL" -gt 0 ]; then
    echo "Failed steps:"
    for n in "${FAIL_NAMES[@]}"; do echo "  - $n"; done
    exit 1
fi
echo "All smoke tests passed."
