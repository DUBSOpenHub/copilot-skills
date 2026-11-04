#!/usr/bin/env bash
set -euo pipefail

# Directory creation is the reservation commit; partial reservations still count.
fail() {
    local code=$1
    shift
    printf 'ralph-loop: %s\n' "$*" >&2
    exit "$code"
}

usage() {
    fail 64 'usage: pass-ledger.sh STATE init|status|reserve {work|final} TARGET|close NN {passed|failed|blocked|interrupted}'
}

[[ $# -ge 2 ]] || usage
state=$1
action=$2
shift 2
marker='ralph-loop-pass-ledger-v1'

case "$action" in
    init|status) [[ $# -eq 0 ]] || usage ;;
    reserve|close) [[ $# -eq 2 ]] || usage ;;
    *) usage ;;
esac

[[ ! -L "$state" ]] || fail 5 'state must not be a symlink'
if [[ "$action" == init && ! -e "$state" ]]; then
    mkdir "$state"
fi
[[ -d "$state" ]] || fail 5 'state directory missing; do not recreate a lost ledger'
state=$(cd "$state" && pwd -P)
lock="$state/.lock"
owns_lock=0

cleanup() {
    if [[ "$owns_lock" == 1 ]]; then
        rm "$lock/owner"
        rmdir "$lock"
    fi
}

acquire() {
    if ! mkdir "$lock"; then
        fail 4 "ledger locked; inspect $lock/owner, never steal a live lock"
    fi
    owns_lock=1
    trap cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM HUP
    printf 'pid=%s\nhost=%s\nstarted=%s\n' "$$" "$(hostname)" \
        "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" > "$lock/owner"
}

if [[ "$action" != status ]]; then
    acquire
fi

if [[ "$action" == init && ! -e "$state/format" ]]; then
    for entry in "$state"/* "$state"/.[!.]* "$state"/..?*; do
        [[ -e "$entry" || -L "$entry" ]] || continue
        [[ "$entry" == "$lock" ]] || fail 5 'refusing to initialize a nonempty unrecognized state directory'
    done
    mkdir "$state/passes"
    printf '%s\n' "$marker" > "$state/format.new"
    mv "$state/format.new" "$state/format"
fi

[[ -f "$state/format" && ! -L "$state/format" ]] || fail 5 'missing/unsafe format marker'
[[ "$(< "$state/format")" == "$marker" ]] || fail 5 'unknown ledger format'
[[ -d "$state/passes" && ! -L "$state/passes" ]] || fail 5 'missing/unsafe pass ledger'

used=0
count=0
open=''

scan() {
    local entry id number outcome
    for entry in "$state/passes"/* "$state/passes"/.[!.]* "$state/passes"/..?*; do
        [[ -e "$entry" || -L "$entry" ]] || continue
        id=${entry##*/}
        [[ "$id" =~ ^(0[1-9]|1[0-9]|20)$ ]] || fail 5 "unexpected ledger entry: $id"
        [[ -d "$entry" && ! -L "$entry" ]] || fail 5 "unsafe reservation: $id"
        number=$((10#$id))
        count=$((count + 1))
        if (( number > used )); then used=$number; fi
        if [[ -e "$entry/result" || -L "$entry/result" ]]; then
            [[ -f "$entry/result" && ! -L "$entry/result" ]] || fail 5 "unsafe result: $id"
            outcome=$(< "$entry/result")
            case "$outcome" in
                passed|failed|blocked|interrupted) ;;
                *) fail 5 "invalid result: $id" ;;
            esac
        else
            [[ -z "$open" ]] || fail 5 'multiple open reservations; reconcile before continuing'
            open=$id
        fi
    done
    [[ "$count" -eq "$used" ]] || fail 5 'gapped ledger; never reconstruct or refund reservations'
}

scan

case "$action" in
    init|status)
        printf 'used=%s limit=20 remaining=%s open=%s\n' "$used" "$((20 - used))" "${open:-none}"
        ;;
    reserve)
        mode=$1
        target=$2
        case "$mode" in work|final) ;; *) usage ;; esac
        [[ "$target" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || fail 64 'target must be a step ID or ALL'
        if [[ "$mode" == final && "$target" != ALL ]]; then
            fail 64 'a final pass must target ALL'
        fi
        (( used < 20 )) || fail 2 '20 passes reserved: exhausted; no pass 21'
        [[ -z "$open" ]] || fail 3 "pass $open is open; reconcile and close it first"
        printf -v id '%02d' "$((used + 1))"
        pass="$state/passes/$id"
        mkdir "$pass"
        printf 'mode=%s\ntarget=%s\nstarted=%s\n' "$mode" "$target" \
            "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" > "$pass/reservation.new"
        mv "$pass/reservation.new" "$pass/reservation"
        printf '%s\n' "$id"
        ;;
    close)
        id=$1
        outcome=$2
        [[ "$id" =~ ^(0[1-9]|1[0-9]|20)$ ]] || usage
        case "$outcome" in passed|failed|blocked|interrupted) ;; *) usage ;; esac
        pass="$state/passes/$id"
        [[ -d "$pass" && "$open" == "$id" ]] || fail 3 'pass is absent or already closed; results are immutable'
        if [[ ! -f "$pass/reservation" || -L "$pass/reservation" ]]; then
            [[ "$outcome" == interrupted ]] || fail 5 'incomplete reservation can only close as interrupted'
        fi
        [[ ! -L "$pass/result.new" && ! -L "$pass/finished-at" ]] || fail 5 'unsafe checkpoint path'
        printf '%s\n' "$outcome" > "$pass/result.new"
        date -u '+%Y-%m-%dT%H:%M:%SZ' > "$pass/finished-at"
        mv "$pass/result.new" "$pass/result"
        printf 'closed=%s outcome=%s\n' "$id" "$outcome"
        ;;
esac
