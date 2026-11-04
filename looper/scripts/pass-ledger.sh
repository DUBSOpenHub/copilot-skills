#!/usr/bin/env bash
set -euo pipefail

# Directory creation is the reservation commit; partial reservations still count.
fail() {
    local code=$1
    shift
    printf 'looper: %s\n' "$*" >&2
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

# Check the supplied spelling before resolving it: link/.. and link/ are links too.
[[ -n "$state" ]] || fail 5 'state directory missing'
case "$state" in
    /*) remaining=$state ;;
    *) remaining=$PWD/$state ;;
esac
prefix=''
while [[ -n "$remaining" ]]; do
    component=${remaining%%/*}
    if [[ "$remaining" == */* ]]; then
        remaining=${remaining#*/}
    else
        remaining=''
    fi
    [[ -n "$component" ]] || continue
    prefix=$prefix/$component
    [[ ! -L "$prefix" ]] || fail 5 'state path must not contain symlinks'
done
state=${prefix:-/}
if [[ "$action" == init && ! -e "$state" ]]; then
    mkdir "$state"
fi
[[ -d "$state" ]] || fail 5 'state directory missing; do not recreate a lost ledger'
state=$(cd "$state" && pwd -P)
lock="$state/.lock"
owns_lock=0
owner_record=''

optional_file() {
    [[ ! -L "$1" ]] || fail 5 "unsafe file: $1"
    if [[ -e "$1" ]]; then
        [[ -f "$1" ]] || fail 5 "nonregular file: $1"
    fi
}

write_new() {
    local path=$1
    shift
    optional_file "$path"
    [[ ! -e "$path" ]] || fail 5 "staging file exists; preserve and reconcile: $path"
    # Callers supply literal formats; record values are separate printf arguments.
    # shellcheck disable=SC2059
    (set -o noclobber; printf "$@" > "$path") || fail 1 "cannot stage: $path"
}

publish() {
    optional_file "$1"
    [[ -f "$1" ]] || fail 5 "missing staged file: $1"
    optional_file "$2"
    mv "$1" "$2" || fail 1 "cannot publish: $2"
}

timestamp() {
    now=$(date -u '+%Y-%m-%dT%H:%M:%SZ') || fail 1 'cannot obtain timestamp'
    [[ -n "$now" ]] || fail 1 'empty timestamp'
}

cleanup() {
    local status=$?
    trap - EXIT
    if [[ "$owns_lock" == 1 ]]; then
        if [[ -d "$lock" && ! -L "$lock" &&
              -f "$lock/owner" && ! -L "$lock/owner" ]] &&
           cmp -s "$lock/owner" <(printf '%s\n' "$owner_record"); then
            if ! rm "$lock/owner" || ! rmdir "$lock"; then
                printf 'looper: owned lock cleanup failed\n' >&2
                if [[ "$status" -eq 0 ]]; then status=1; fi
            fi
        else
            printf 'looper: lock ownership uncertain; leaving lock intact\n' >&2
            if [[ "$status" -eq 0 ]]; then status=1; fi
        fi
    fi
    exit "$status"
}

acquire() {
    local host
    host=$(hostname) || fail 1 'cannot obtain lock host'
    timestamp
    printf -v owner_record 'pid=%s\nhost=%s\nstarted=%s' "$$" "$host" "$now"
    if ! mkdir "$lock"; then
        fail 4 "ledger locked; inspect $lock/owner, never steal a live lock"
    fi
    owns_lock=1
    write_new "$lock/owner" '%s\n' "$owner_record"
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
if [[ "$action" != status ]]; then
    acquire
fi

optional_file "$state/format"
optional_file "$state/format.new"
if [[ "$action" == init && ! -e "$state/format" ]]; then
    for entry in "$state"/* "$state"/.[!.]* "$state"/..?*; do
        [[ -e "$entry" || -L "$entry" ]] || continue
        [[ "$entry" == "$lock" ]] || fail 5 'refusing to initialize a nonempty unrecognized state directory'
    done
    mkdir "$state/passes"
    write_new "$state/format.new" '%s\n' "$marker"
    publish "$state/format.new" "$state/format"
fi

[[ -f "$state/format" && ! -L "$state/format" ]] || fail 5 'missing/unsafe format marker'
cmp -s "$state/format" <(printf '%s\n' "$marker") || fail 5 'unknown ledger format'
[[ -d "$state/passes" && ! -L "$state/passes" ]] || fail 5 'missing/unsafe pass ledger'

valid_target() {
    [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]
}

validate_reservation() {
    local mode_line target_line started_line extra mode target
    {
        IFS= read -r mode_line &&
        IFS= read -r target_line &&
        IFS= read -r started_line &&
        ! IFS= read -r extra && [[ -z "$extra" ]]
    } < "$1" || fail 5 "malformed reservation: $1"
    # Compare bytes as well: shell reads must not silently accept binary data.
    cmp -s "$1" <(printf '%s\n' "$mode_line" "$target_line" "$started_line") ||
        fail 5 "malformed reservation: $1"
    case "$mode_line" in mode=work|mode=final) ;; *) fail 5 "invalid mode: $1" ;; esac
    [[ "$target_line" == target=* && "$started_line" == started=?* ]] ||
        fail 5 "invalid reservation fields: $1"
    mode=${mode_line#mode=}
    target=${target_line#target=}
    valid_target "$target" || fail 5 "invalid target: $1"
    [[ "$mode" != final || "$target" == ALL ]] || fail 5 "invalid final target: $1"
}

used=0
count=0
open=''

scan() {
    local entry id number outcome name
    for entry in "$state/passes"/* "$state/passes"/.[!.]* "$state/passes"/..?*; do
        [[ -e "$entry" || -L "$entry" ]] || continue
        id=${entry##*/}
        [[ "$id" =~ ^(0[1-9]|1[0-9]|20)$ ]] || fail 5 "unexpected ledger entry: $id"
        [[ -d "$entry" && ! -L "$entry" ]] || fail 5 "unsafe reservation: $id"
        number=$((10#$id))
        count=$((count + 1))
        if (( number > used )); then used=$number; fi
        for name in reservation reservation.new result result.new finished-at finished-at.new; do
            optional_file "$entry/$name"
        done
        if [[ -f "$entry/reservation" ]]; then
            validate_reservation "$entry/reservation"
        fi
        if [[ -f "$entry/result" ]]; then
            outcome=$(< "$entry/result")
            case "$outcome" in
                passed|failed|blocked|interrupted) ;;
                *) fail 5 "invalid result: $id" ;;
            esac
            cmp -s "$entry/result" <(printf '%s\n' "$outcome") ||
                fail 5 "malformed result: $id"
            [[ -f "$entry/reservation" || "$outcome" == interrupted ]] ||
                fail 5 "missing reservation for non-interrupted result: $id"
        else
            [[ -z "$open" ]] || fail 5 'multiple open reservations; reconcile before continuing'
            open=$id
        fi
    done
    [[ "$count" -eq "$used" ]] || fail 5 'gapped ledger; never reconstruct or refund reservations'
    [[ -z "$open" || "$((10#$open))" -eq "$used" ]] ||
        fail 5 'open reservation is not last; reconcile history'
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
        valid_target "$target" || fail 64 'target must be a step ID or ALL'
        if [[ "$mode" == final && "$target" != ALL ]]; then
            fail 64 'a final pass must target ALL'
        fi
        (( used < 20 )) || fail 2 '20 passes reserved: exhausted; no pass 21'
        [[ -z "$open" ]] || fail 3 "pass $open is open; reconcile and close it first"
        printf -v id '%02d' "$((used + 1))"
        pass="$state/passes/$id"
        mkdir "$pass"
        timestamp
        write_new "$pass/reservation.new" 'mode=%s\ntarget=%s\nstarted=%s\n' "$mode" "$target" "$now"
        publish "$pass/reservation.new" "$pass/reservation"
        printf '%s\n' "$id"
        ;;
    close)
        id=$1
        outcome=$2
        [[ "$id" =~ ^(0[1-9]|1[0-9]|20)$ ]] || usage
        case "$outcome" in passed|failed|blocked|interrupted) ;; *) usage ;; esac
        pass="$state/passes/$id"
        [[ -d "$pass" && "$open" == "$id" ]] || fail 3 'pass is absent or already closed; results are immutable'
        if [[ ! -f "$pass/reservation" ]]; then
            [[ "$outcome" == interrupted ]] || fail 5 'incomplete reservation can only close as interrupted'
        fi
        # Preflight both candidates before leaving any new partial-close evidence.
        [[ ! -e "$pass/result.new" && ! -e "$pass/finished-at.new" ]] ||
            fail 5 'staging checkpoint exists; preserve and reconcile'
        timestamp
        write_new "$pass/result.new" '%s\n' "$outcome"
        write_new "$pass/finished-at.new" '%s\n' "$now"
        publish "$pass/finished-at.new" "$pass/finished-at"
        publish "$pass/result.new" "$pass/result"
        printf 'closed=%s outcome=%s\n' "$id" "$outcome"
        ;;
esac
