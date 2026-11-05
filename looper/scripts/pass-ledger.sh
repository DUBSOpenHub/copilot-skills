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
    fail 64 'usage: pass-ledger.sh STATE init|status|verdict|criteria [COUNT]|reserve {work|final} TARGET|run NN [--ac AC01,AC02] [--label NAME] [--timeout SECONDS] [--baseline|--snapshot] -- COMMAND...|repair NN|close NN {passed|failed|blocked|interrupted}; pass-ledger.sh PROJECT_ROOT loops'
}

[[ $# -ge 2 ]] || usage
self=${BASH_SOURCE[0]}
state=$1
action=$2
shift 2
marker='ralph-loop-pass-ledger-v1'
id_pattern='^(0[1-9]|1[0-9]|20)$'
ac_pattern='^AC[0-9]{2,3}(,AC[0-9]{2,3})*$'
label_pattern='^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'
loop_pattern='^[a-z0-9][a-z0-9-]{0,39}$'

case "$action" in
    init|status|verdict|loops) [[ $# -eq 0 ]] || usage ;;
    reserve|close) [[ $# -eq 2 ]] || usage ;;
    criteria) [[ $# -le 1 ]] || usage ;;
    repair) [[ $# -eq 1 ]] || usage ;;
    run) [[ $# -ge 3 ]] || usage ;;
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
if [[ "$action" == loops ]]; then
    [[ -d "$state" ]] || fail 5 'project root missing'
else
    [[ -d "$state" ]] || fail 5 'state directory missing; do not recreate a lost ledger'
fi
state=$(cd "$state" && pwd -P)

# Read-only overview of every loop in a project: .ralph-loop is "default" and
# .ralph-loop-NAME is an independent named loop with its own 20-pass budget.
list_loops() {
    local entry name summary code complete found=0 errors=0
    for entry in "$state/.ralph-loop" "$state"/.ralph-loop-*; do
        [[ -e "$entry" || -L "$entry" ]] || continue
        name=${entry##*/}
        if [[ "$name" == .ralph-loop ]]; then
            name=default
        else
            name=${name#.ralph-loop-}
            [[ "$name" =~ $loop_pattern && "$name" != default ]] || continue
        fi
        found=1
        if [[ -L "$entry" || ! -d "$entry" ]]; then
            printf 'loop=%s error=unsafe state=%s\n' "$name" "$entry"
            errors=1
            continue
        fi
        if ! summary=$("${BASH:-bash}" "$self" "$entry" status 2>/dev/null); then
            printf 'loop=%s error=invalid state=%s\n' "$name" "$entry"
            errors=1
            continue
        fi
        code=0
        "${BASH:-bash}" "$self" "$entry" verdict > /dev/null 2>&1 || code=$?
        case "$code" in
            0) complete=yes ;;
            6) complete=no ;;
            *) printf 'loop=%s error=invalid state=%s\n' "$name" "$entry"; errors=1; continue ;;
        esac
        printf 'loop=%s %s complete=%s state=%s\n' "$name" "$summary" "$complete" "$entry"
    done
    [[ "$found" == 1 ]] || printf 'loops=none\n'
    [[ "$errors" == 0 ]] || exit 5
}

if [[ "$action" == loops ]]; then
    list_loops
    exit 0
fi

lock="$state/.lock"
owns_lock=0
owner_record=''
child=''
watcher=''
run_dir=''

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

release_lock() {
    [[ "$owns_lock" == 1 ]] || return 0
    owns_lock=0
    if [[ -d "$lock" && ! -L "$lock" &&
          -f "$lock/owner" && ! -L "$lock/owner" ]] &&
       cmp -s "$lock/owner" <(printf '%s\n' "$owner_record"); then
        if ! rm "$lock/owner" || ! rmdir "$lock"; then
            printf 'looper: owned lock cleanup failed\n' >&2
            return 1
        fi
    else
        printf 'looper: lock ownership uncertain; leaving lock intact\n' >&2
        return 1
    fi
}

# An interrupted command is recorded as a failed run, never as missing evidence.
stop_child() {
    local status=$1 tries=0 finished
    if [[ -n "$watcher" ]]; then
        kill -KILL -- "-$watcher" 2>/dev/null || :
    fi
    [[ -n "$child" ]] || return 0
    kill -TERM -- "-$child" 2>/dev/null || kill -TERM "$child" 2>/dev/null || :
    while (( tries < 20 )) && kill -0 -- "-$child" 2>/dev/null; do
        sleep 0.1
        tries=$((tries + 1))
    done
    kill -KILL -- "-$child" 2>/dev/null || :
    (set -o noclobber; printf 'interrupted\n' > "$run_dir/reason") 2>/dev/null || :
    finished=$(date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null) || finished=unknown
    (set -o noclobber; printf '%s\n' "$finished" > "$run_dir/finished-at") 2>/dev/null || :
    (set -o noclobber; printf '%s\n' "$status" > "$run_dir/exit") 2>/dev/null || :
}

cleanup() {
    local status=$?
    trap - EXIT
    stop_child "$status"
    if ! release_lock; then
        if [[ "$status" -eq 0 ]]; then status=1; fi
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
    # Some mkdir implementations report success when a concurrent caller created
    # the directory first, so the exclusive create of owner decides the winner.
    # A loser reports "locked" and never claims, or cleans up, the winner's lock.
    if ! (set -o noclobber; printf '%s\n' "$owner_record" > "$lock/owner") 2>/dev/null; then
        if [[ -e "$lock/owner" || -L "$lock/owner" || ! -d "$lock" ]]; then
            fail 4 "ledger locked; inspect $lock/owner, never steal a live lock"
        fi
        owns_lock=1
        fail 1 "cannot stage: $lock/owner"
    fi
    owns_lock=1
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
case "$action" in
    status|verdict) ;;
    criteria) if [[ $# -eq 1 ]]; then acquire; fi ;;
    *) acquire ;;
esac

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
optional_file "$state/criteria"
optional_file "$state/criteria.new"

valid_target() {
    [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]
}

res_mode=''
validate_reservation() {
    local mode_line='' target_line='' started_line='' extra='' mode target
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
    res_mode=$mode
}

crit_value=0
read_criteria() {
    local value=''
    crit_value=0
    [[ -f "$1" ]] || return 0
    value=$(< "$1")
    [[ "$value" =~ ^[1-9][0-9]{0,2}$ ]] || fail 5 "malformed criteria count: $1"
    cmp -s "$1" <(printf '%s\n' "$value") || fail 5 "malformed criteria count: $1"
    crit_value=$value
}

# Runs are numbered evidence records: passes/NN/runs/001, 002, ... with no gaps.
runs_count=0
check_runs() {
    local runs=$1/runs entry name expect=1 file
    runs_count=0
    [[ -e "$runs" || -L "$runs" ]] || return 0
    [[ -d "$runs" && ! -L "$runs" ]] || fail 5 "unsafe runs directory: $runs"
    for entry in "$runs"/* "$runs"/.[!.]* "$runs"/..?*; do
        [[ -e "$entry" || -L "$entry" ]] || continue
        name=${entry##*/}
        [[ "$name" =~ ^[0-9]{3}$ ]] || fail 5 "unexpected run entry: $entry"
        [[ -d "$entry" && ! -L "$entry" ]] || fail 5 "unsafe run: $entry"
        [[ "$((10#$name))" -eq "$expect" ]] || fail 5 "gapped runs: $runs"
        expect=$((expect + 1))
        for file in meta meta.new command command.new cwd cwd.new output exit finished-at reason; do
            optional_file "$entry/$file"
        done
        runs_count=$((runs_count + 1))
    done
}

r_complete=0
r_kind=''
r_phase=''
r_ac=''
r_exit=''
r_key=''
load_run() {
    local dir=$1 kind='' phase='' label='' ac='' limit='' started='' extra='' value=''
    r_complete=0 r_kind='' r_phase='' r_ac='' r_exit='' r_key=''
    # No published meta: allocated but never started, so it is not evidence.
    [[ -f "$dir/meta" ]] || return 0
    [[ -f "$dir/command" && -f "$dir/cwd" ]] || fail 5 "malformed run record: $dir"
    {
        IFS= read -r kind && IFS= read -r phase && IFS= read -r label &&
        IFS= read -r ac && IFS= read -r limit && IFS= read -r started &&
        ! IFS= read -r extra && [[ -z "$extra" ]]
    } < "$dir/meta" || fail 5 "malformed run record: $dir"
    cmp -s "$dir/meta" <(printf '%s\n' "$kind" "$phase" "$label" "$ac" "$limit" "$started") ||
        fail 5 "malformed run record: $dir"
    case "$kind" in kind=check|kind=snapshot) ;; *) fail 5 "malformed run record: $dir" ;; esac
    case "$phase" in
        phase=baseline|phase=initial|phase=revalidate|phase=final) ;;
        *) fail 5 "malformed run record: $dir" ;;
    esac
    [[ "$label" == label=* && "$ac" == ac=* && "$limit" =~ ^timeout=[1-9][0-9]*$ &&
       "$started" == started=?* ]] || fail 5 "malformed run record: $dir"
    r_kind=${kind#kind=}
    r_phase=${phase#phase=}
    r_ac=${ac#ac=}
    [[ -z "$r_ac" || "$r_ac" =~ $ac_pattern ]] || fail 5 "malformed run record: $dir"
    r_key="$(< "$dir/command")|$(< "$dir/cwd")"
    if [[ -f "$dir/exit" ]]; then
        value=$(< "$dir/exit")
        if [[ ! "$value" =~ ^[0-9]{1,3}$ ]] || ! cmp -s "$dir/exit" <(printf '%s\n' "$value"); then
            fail 5 "malformed exit status: $dir"
        fi
        r_exit=$value
        r_complete=1
    fi
}

# A work pass may close passed only when every check in its deciding phase
# (initial, or revalidate after the single repair) ran to completion and passed.
gate_work() {
    local pass=$1 entry want=initial seen=0 failed_keys='' key found
    if [[ -e "$pass/repair" ]]; then want=revalidate; fi
    for entry in "$pass/runs"/[0-9][0-9][0-9]; do
        [[ -d "$entry" ]] || continue
        load_run "$entry"
        [[ -n "$r_phase" && "$r_complete" == 1 ]] ||
            fail 6 "run ${entry##*/} has no recorded exit; it is inconclusive, so close this pass failed or interrupted"
        if [[ "$r_phase" == initial && "$r_exit" != 0 ]]; then
            failed_keys=$failed_keys$r_key$'\n'
        fi
        [[ "$r_phase" == "$want" ]] || continue
        seen=$((seen + 1))
        [[ "$r_exit" == 0 ]] ||
            fail 6 "run ${entry##*/} ($want) exited $r_exit; a failing check cannot close passed"
    done
    [[ "$seen" -gt 0 ]] ||
        fail 6 "no $want validation run recorded; record checks with: run NN -- COMMAND"
    [[ "$want" == revalidate ]] || return 0
    while IFS= read -r key; do
        [[ -n "$key" ]] || continue
        found=0
        for entry in "$pass/runs"/[0-9][0-9][0-9]; do
            load_run "$entry"
            if [[ "$r_phase" == revalidate && "$r_key" == "$key" ]]; then found=1; fi
        done
        [[ "$found" == 1 ]] ||
            fail 6 "a check that failed before the repair was not rerun: ${key%|*}"
    done <<< "$failed_keys"
}

# A final pass needs matching before/after snapshots, every run green, and
# every acceptance criterion AC01..ACnn covered by a passing check.
gate_final() {
    local pass=$1 count=$2 entry total=0 first='' first_key='' last='' last_key='' last_kind=''
    local covered=',' number ac
    [[ "$count" -ge 1 ]] || fail 6 'no acceptance-criteria count recorded; run: criteria COUNT'
    for entry in "$pass/runs"/[0-9][0-9][0-9]; do
        [[ -d "$entry" ]] || continue
        load_run "$entry"
        [[ -n "$r_phase" && "$r_complete" == 1 ]] ||
            fail 6 "run ${entry##*/} has no recorded exit; inconclusive checks are not passes"
        [[ "$r_phase" == final ]] || fail 5 "non-final run in final pass: $entry"
        [[ "$r_exit" == 0 ]] ||
            fail 6 "run ${entry##*/} exited $r_exit; any failure fails the final gate"
        total=$((total + 1))
        if [[ -z "$first" ]]; then
            [[ "$r_kind" == snapshot ]] ||
                fail 6 'the first final run must be the deliverable snapshot (--snapshot)'
            first=$entry
            first_key=$r_key
        fi
        last=$entry
        last_key=$r_key
        last_kind=$r_kind
        if [[ "$r_kind" == check ]]; then covered=$covered$r_ac,; fi
    done
    [[ "$total" -ge 3 && "$last_kind" == snapshot ]] ||
        fail 6 'the final pass needs a snapshot, the full checks, then the same snapshot again'
    [[ "$first_key" == "$last_key" ]] ||
        fail 6 'the closing snapshot must repeat the opening snapshot command in the same directory'
    [[ -s "$first/output" ]] || fail 6 'the snapshot produced no output; fingerprint the deliverables'
    cmp -s "$first/output" "$last/output" ||
        fail 6 'deliverables changed during the final gate; snapshots differ'
    number=1
    while [[ "$number" -le "$count" ]]; do
        printf -v ac 'AC%02d' "$number"
        [[ "$covered" == *",$ac,"* ]] ||
            fail 6 "no passing final check covers $ac; tag checks with --ac"
        number=$((number + 1))
    done
}

used=0
count=0
open=''

scan() {
    local entry id number outcome name
    for entry in "$state/passes"/* "$state/passes"/.[!.]* "$state/passes"/..?*; do
        [[ -e "$entry" || -L "$entry" ]] || continue
        id=${entry##*/}
        [[ "$id" =~ $id_pattern ]] || fail 5 "unexpected ledger entry: $id"
        [[ -d "$entry" && ! -L "$entry" ]] || fail 5 "unsafe reservation: $id"
        number=$((10#$id))
        count=$((count + 1))
        if (( number > used )); then used=$number; fi
        for name in reservation reservation.new result result.new finished-at finished-at.new \
                    repair criteria criteria.new; do
            optional_file "$entry/$name"
        done
        check_runs "$entry"
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
read_criteria "$state/criteria"

# Shared preconditions for commands that add evidence to the open pass.
open_pass() {
    [[ "$1" =~ $id_pattern ]] || usage
    pass="$state/passes/$1"
    [[ -d "$pass" && "$open" == "$1" ]] || fail 3 'pass is absent or already closed; results are immutable'
    [[ -f "$pass/reservation" ]] || fail 5 'incomplete reservation can only close as interrupted'
    validate_reservation "$pass/reservation"
}

verdict_no() {
    printf 'complete=no reason=%s\n' "$1"
    exit 6
}

case "$action" in
    init|status)
        printf 'used=%s limit=20 remaining=%s open=%s\n' "$used" "$((20 - used))" "${open:-none}"
        ;;
    criteria)
        if [[ $# -eq 1 ]]; then
            [[ "$1" =~ ^[1-9][0-9]{0,2}$ ]] || fail 64 'criteria COUNT must be 1-999'
            if [[ -n "$open" && -f "$state/passes/$open/reservation" ]]; then
                validate_reservation "$state/passes/$open/reservation"
                [[ "$res_mode" != final ]] ||
                    fail 3 "final pass $open is open; criteria are frozen during the final gate"
            fi
            [[ "$1" -ge "$crit_value" ]] ||
                fail 6 "criteria can only grow ($crit_value recorded); never remove or renumber criteria"
            if [[ "$1" -gt "$crit_value" ]]; then
                write_new "$state/criteria.new" '%s\n' "$1"
                publish "$state/criteria.new" "$state/criteria"
                crit_value=$1
            fi
        fi
        printf 'criteria=%s\n' "$crit_value"
        ;;
    verdict)
        [[ "$used" -gt 0 ]] || verdict_no no-passes
        [[ -z "$open" ]] || verdict_no pass-open
        printf -v id '%02d' "$used"
        pass="$state/passes/$id"
        [[ -f "$pass/reservation" ]] || verdict_no last-pass-not-final
        validate_reservation "$pass/reservation"
        [[ "$res_mode" == final ]] || verdict_no last-pass-not-final
        [[ "$(< "$pass/result")" == passed ]] || verdict_no final-not-passed
        [[ -f "$pass/criteria" ]] || verdict_no final-without-evidence
        recorded=$crit_value
        read_criteria "$pass/criteria"
        [[ "$crit_value" == "$recorded" ]] || verdict_no criteria-changed
        code=0
        (gate_final "$pass" "$crit_value") || code=$?
        case "$code" in
            0) ;;
            6) verdict_no evidence ;;
            *) exit "$code" ;;
        esac
        printf 'complete=yes final=%s criteria=%s\n' "$id" "$crit_value"
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
        if [[ "$mode" == final && "$crit_value" -lt 1 ]]; then
            fail 6 'record the acceptance-criteria count before a final pass: criteria COUNT'
        fi
        printf -v id '%02d' "$((used + 1))"
        pass="$state/passes/$id"
        mkdir "$pass"
        timestamp
        write_new "$pass/reservation.new" 'mode=%s\ntarget=%s\nstarted=%s\n' "$mode" "$target" "$now"
        publish "$pass/reservation.new" "$pass/reservation"
        printf '%s\n' "$id"
        ;;
    run)
        id=$1
        shift
        open_pass "$id"
        ac='' label='' limit=1800 kind=check baseline=0
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --ac) [[ $# -ge 2 && "$2" =~ $ac_pattern ]] || fail 64 '--ac takes AC01,AC02,...'; ac=$2; shift 2 ;;
                --label) [[ $# -ge 2 && "$2" =~ $label_pattern ]] || fail 64 '--label takes a short name'; label=$2; shift 2 ;;
                --timeout)
                    [[ $# -ge 2 && "$2" =~ ^[1-9][0-9]{0,4}$ ]] || fail 64 '--timeout takes 1-86400 seconds'
                    [[ "$2" -le 86400 ]] || fail 64 '--timeout takes 1-86400 seconds'
                    limit=$2
                    shift 2
                    ;;
                --baseline) baseline=1; shift ;;
                --snapshot) kind=snapshot; shift ;;
                --) shift; break ;;
                *) usage ;;
            esac
        done
        [[ $# -ge 1 ]] || usage
        if [[ "$kind" == snapshot && ( "$baseline" == 1 || -n "$ac" ) ]]; then
            fail 64 '--snapshot cannot be combined with --baseline or --ac'
        fi
        [[ "$PWD" != *$'\n'* ]] || fail 64 'working directory must not contain a newline'
        if [[ -n "$ac" ]]; then
            for item in ${ac//,/ }; do
                [[ "$((10#${item#AC}))" -le "$crit_value" ]] ||
                    fail 6 "$item exceeds the recorded criteria count ($crit_value); run: criteria COUNT"
            done
        fi
        printf -v quoted '%q ' "$@"
        key="$quoted|$PWD"
        if [[ "$res_mode" == final ]]; then
            [[ "$baseline" == 0 ]] || fail 6 'baseline runs belong to work passes'
            phase=final
        else
            [[ "$kind" == check ]] || fail 6 'snapshots belong to final passes'
            if [[ -e "$pass/repair" ]]; then
                [[ "$baseline" == 0 ]] || fail 6 'baseline runs must precede validation and repair'
                phase=revalidate
            elif [[ "$baseline" == 1 ]]; then
                phase=baseline
            else
                phase=initial
            fi
        fi
        executions=0
        for entry in "$pass/runs"/[0-9][0-9][0-9]; do
            [[ -d "$entry" ]] || continue
            load_run "$entry"
            if [[ "$phase" == baseline && -n "$r_phase" && "$r_phase" != baseline ]]; then
                fail 6 'baseline runs must precede validation runs in this pass'
            fi
            if [[ "$r_phase" == "$phase" && "$r_key" == "$key" ]]; then
                executions=$((executions + 1))
            fi
        done
        [[ "$executions" -lt 3 ]] ||
            fail 6 "this check already ran 3 times in the $phase phase; diagnose instead of retrying"
        (( runs_count < 999 )) || fail 6 'run limit reached for this pass'
        printf -v number '%03d' "$((runs_count + 1))"
        if [[ ! -d "$pass/runs" ]]; then mkdir "$pass/runs"; fi
        run_dir="$pass/runs/$number"
        mkdir "$run_dir"
        timestamp
        write_new "$run_dir/command.new" '%s\n' "$quoted"
        publish "$run_dir/command.new" "$run_dir/command"
        write_new "$run_dir/cwd.new" '%s\n' "$PWD"
        publish "$run_dir/cwd.new" "$run_dir/cwd"
        write_new "$run_dir/output" '%s' ''
        write_new "$run_dir/meta.new" 'kind=%s\nphase=%s\nlabel=%s\nac=%s\ntimeout=%s\nstarted=%s\n' \
            "$kind" "$phase" "$label" "$ac" "$limit" "$now"
        publish "$run_dir/meta.new" "$run_dir/meta"
        # Long commands must not hold the ledger lock.
        release_lock || fail 1 'cannot release ledger lock before running the command'
        # Job control gives the command and its watcher their own process groups,
        # so a timeout or interruption stops grandchildren too.
        set -m
        "$@" < /dev/null >> "$run_dir/output" 2>&1 &
        child=$!
        (
            sleep "$limit" || exit 0
            kill -0 -- "-$child" 2>/dev/null || exit 0
            (set -o noclobber; printf 'timeout\n' > "$run_dir/reason") 2>/dev/null || :
            kill -TERM -- "-$child" 2>/dev/null || kill -TERM "$child" 2>/dev/null || :
            sleep 5 || :
            kill -KILL -- "-$child" 2>/dev/null || :
        ) > /dev/null 2>&1 &
        watcher=$!
        set +m
        if wait "$child" 2>/dev/null; then code=0; else code=$?; fi
        child=''
        # SIGKILL cannot be caught, so the watcher cannot record a late timeout.
        kill -KILL -- "-$watcher" 2>/dev/null || :
        wait "$watcher" 2>/dev/null || :
        watcher=''
        # A command that outlives its time limit never counts as passing.
        if [[ "$code" == 0 && -f "$run_dir/reason" ]]; then code=124; fi
        timestamp
        write_new "$run_dir/finished-at" '%s\n' "$now"
        write_new "$run_dir/exit" '%s\n' "$code"
        tail -n 200 "$run_dir/output" || :
        reason=''
        if [[ -f "$run_dir/reason" ]]; then reason=" reason=$(< "$run_dir/reason")"; fi
        printf 'run=%s/%s phase=%s exit=%s%s output=%s\n' "$id" "$number" "$phase" "$code" "$reason" "$run_dir/output"
        [[ "$code" == 0 ]] || exit 7
        ;;
    repair)
        id=$1
        open_pass "$id"
        [[ "$res_mode" == work ]] || fail 6 'final passes are read-only; close failed and repair in a work pass'
        [[ ! -e "$pass/repair" ]] ||
            fail 6 'this pass already used its one repair batch; close it and reserve a new pass'
        failed=0
        for entry in "$pass/runs"/[0-9][0-9][0-9]; do
            [[ -d "$entry" ]] || continue
            load_run "$entry"
            [[ -z "$r_phase" || "$r_complete" == 1 ]] ||
                fail 6 "run ${entry##*/} is still in flight or inconclusive"
            if [[ "$r_phase" == initial && "$r_exit" != 0 ]]; then failed=1; fi
        done
        [[ "$failed" == 1 ]] || fail 6 'repair needs a failed initial validation run as evidence'
        timestamp
        write_new "$pass/repair" 'started=%s\n' "$now"
        printf 'repair=%s\n' "$id"
        ;;
    close)
        id=$1
        outcome=$2
        [[ "$id" =~ $id_pattern ]] || usage
        case "$outcome" in passed|failed|blocked|interrupted) ;; *) usage ;; esac
        pass="$state/passes/$id"
        [[ -d "$pass" && "$open" == "$id" ]] || fail 3 'pass is absent or already closed; results are immutable'
        if [[ ! -f "$pass/reservation" ]]; then
            [[ "$outcome" == interrupted ]] || fail 5 'incomplete reservation can only close as interrupted'
        fi
        # Preflight both candidates before leaving any new partial-close evidence.
        [[ ! -e "$pass/result.new" && ! -e "$pass/finished-at.new" && ! -e "$pass/criteria.new" ]] ||
            fail 5 'staging checkpoint exists; preserve and reconcile'
        res_mode=''
        if [[ "$outcome" == passed ]]; then
            validate_reservation "$pass/reservation"
            if [[ "$res_mode" == final ]]; then
                gate_final "$pass" "$crit_value"
            else
                gate_work "$pass"
            fi
        fi
        timestamp
        write_new "$pass/result.new" '%s\n' "$outcome"
        write_new "$pass/finished-at.new" '%s\n' "$now"
        if [[ "$outcome" == passed && "$res_mode" == final ]]; then
            write_new "$pass/criteria.new" '%s\n' "$crit_value"
            publish "$pass/criteria.new" "$pass/criteria"
        fi
        publish "$pass/finished-at.new" "$pass/finished-at"
        publish "$pass/result.new" "$pass/result"
        printf 'closed=%s outcome=%s\n' "$id" "$outcome"
        ;;
esac
