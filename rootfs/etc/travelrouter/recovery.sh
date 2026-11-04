#!/bin/sh
# Shared by the early initramfs and an independent OpenRC health guard.
set -eu

read_state() {
    IFS=' ' read -r format kind phase version digest extra < "$medium/.travelrouter-update" || return 1
    [ "$format" = v1 ] && [ -z "${extra:-}" ] || return 1
    case "$kind:$phase" in
        application:prepared|application:ready|application:trial)
            printf '%s\n' "$version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' || return 1
            case "$digest" in *[!0-9a-f]*|'') return 1 ;; esac
            [ "${#digest}" -eq 64 ] || return 1 ;;
        packages:prepared|packages:ready|packages:trial)
            [ "$version" = - ] && [ "$digest" = - ] || return 1 ;;
        *) return 1 ;;
    esac
}

write_state() {
    printf 'v1 %s %s %s %s\n' "$kind" "$1" "$version" "$digest" > "$medium/.travelrouter-update.new"
    sync
    mv -f "$medium/.travelrouter-update.new" "$medium/.travelrouter-update"
    sync
}

finish_rollback() {
    printf '%s\n' "$kind update rolled back after an interrupted or failed boot" > "$backup/result"
    sync
    rm -f "$medium/.travelrouter-update" "$backup/watchdog.pid"
    sync
    printf '%s\n' rolled-back
}

restore_application() {
    [ -f "$backup/overlay.gz" ] || return 1
    actual=$(sha256sum "$backup/overlay.gz")
    [ "${actual%% *}" = "$digest" ] || return 1
    gzip -t "$backup/overlay.gz" || return 1
    cp "$backup/overlay.gz" "$medium/.travelrouter-overlay.restore"
    sync
    actual=$(sha256sum "$medium/.travelrouter-overlay.restore")
    [ "${actual%% *}" = "$digest" ] || return 1
    mv -f "$medium/.travelrouter-overlay.restore" "$medium/travelrouter.apkovl.tar.gz"
    sync
    finish_rollback
}

restore_packages() {
    if [ -d "$backup/repositories" ]; then
        if [ -e "$medium/repositories" ]; then
            [ ! -e "$backup/failed" ] || return 1
            mv "$medium/repositories" "$backup/failed"
            sync
        fi
        mv "$backup/repositories" "$medium/repositories"
        sync
    else
        # Before the first rename, the active repository is still the old one.
        # After an interrupted rollback, the old one is active and failed exists.
        [ -d "$medium/repositories" ] || return 1
        if [ "$phase" = trial ]; then [ -d "$backup/failed" ] || return 1; fi
    fi
    finish_rollback
}

transition() {
    [ -f "$medium/.travelrouter-update" ] || { printf '%s\n' none; return 0; }
    read_state || { echo 'Invalid update recovery state' >&2; return 1; }
    [ -d "$backup" ] || return 1
    if [ "$phase" = trial ] || [ "$phase" = prepared ]; then
        case "$kind" in application) restore_application ;; packages) restore_packages ;; esac
        return
    fi
    if [ "$kind" = application ]; then
        [ -f "$backup/overlay.gz" ] || return 1
        actual=$(sha256sum "$backup/overlay.gz")
        [ "${actual%% *}" = "$digest" ] && gzip -t "$backup/overlay.gz" || return 1
    else
        if [ ! -d "$backup/repositories" ] || [ ! -d "$medium/repositories" ]; then
            restore_packages
            return
        fi
    fi
    write_state trial
    printf '%s\n' trial
}

find_medium() {
    medium=
    for marker in "${1:-}"/media/*/.travelrouter; do
        [ -f "$marker" ] || continue
        [ -z "$medium" ] || { echo 'Multiple router boot media found' >&2; return 2; }
        medium=${marker%/.travelrouter}
    done
    [ -n "$medium" ]
    backup="$medium/.travelrouter-recovery"
}

early() {
    find_medium "${1:-}" || { result=$?; [ "$result" -eq 1 ] && return 0; return "$result"; }
    [ -f "$medium/.travelrouter-update" ] || return 0
    mount -o remount,rw "$medium" || return 1
    outcome=$(transition) || { mount -o remount,ro "$medium" || :; return 1; }
    if [ "$outcome" = trial ]; then
        # A trial is never attempted without an active watchdog in initramfs.
        if [ -c /dev/watchdog ] && [ "$(cat /sys/class/watchdog/watchdog0/nowayout 2>/dev/null || :)" = 0 ]; then
            /bin/busybox timeout -s KILL 900 /bin/busybox watchdog -F -T 15 -t 5 /dev/watchdog >/dev/null 2>&1 &
            watchdog=$!
            sleep 1
        else
            watchdog=
        fi
        if [ -n "$watchdog" ] && kill -0 "$watchdog" 2>/dev/null && \
           [ "$(cat /sys/class/watchdog/watchdog0/state 2>/dev/null || :)" = active ]; then
            printf '%s\n' "$watchdog" > "$backup/watchdog.pid"
            sync
        else
            [ -z "$watchdog" ] || kill -TERM "$watchdog" 2>/dev/null || :
            outcome=$(transition) || { mount -o remount,ro "$medium" || :; return 1; }
        fi
    fi
    if [ "$outcome" = rolled-back ] && [ -d "$medium/repositories" ]; then
        printf '%s\n' "$medium/repositories/main" "$medium/repositories/community" > "${1:-}/tmp/repositories"
    fi
    mount -o remount,ro "$medium"
}

failure() {
    find_medium "${1:-}" || { result=$?; [ "$result" -eq 1 ] && return 0; return "$result"; }
    [ -f "$medium/.travelrouter-update" ] || return 0
    read_state || return 1
    [ "$phase" = trial ] || return 1
    mount -o remount,rw "$medium" || return 1
    outcome=$(transition) || { mount -o remount,ro "$medium" || :; return 1; }
    [ "$outcome" = rolled-back ] || return 1
    mount -o remount,ro "$medium" || return 1
    sync
    reboot -f
    return 1
}

healthy() {
    for service in hostapd dnsmasq unbound travelrouter; do
        rc-service "$service" status >/dev/null 2>&1 || return 1
    done
    developer=$(/usr/bin/python3 -c 'import json; print(json.load(open("/etc/travelrouter/config.json")).get("developer_enabled") is True)') || return 1
    if [ "$developer" = True ]; then
        rc-service travelrouter-ssh status >/dev/null 2>&1 || return 1
        /usr/sbin/sshd -t -f /etc/travelrouter/sshd_config >/dev/null 2>&1 || return 1
        read -r sshd_pid < /run/travelrouter-dev-sshd.pid || return 1
        case "$sshd_pid" in *[!0-9]*|'') return 1 ;; esac
        kill -0 "$sshd_pid" 2>/dev/null || return 1
    fi
    if [ "$kind" = application ]; then
        installed=$(PYTHONPATH=/opt/travelrouter /usr/bin/python3 -c 'from travelrouter import __version__; print(__version__)') || return 1
        [ "$installed" = "$version" ] || return 1
    fi
    wget -q -T 3 -O - http://10.42.0.1/api/status 2>/dev/null | grep -q '"setup_complete"'
}

guard() {
    find_medium '' || { result=$?; [ "$result" -eq 1 ] && return 0; return "$result"; }
    [ -f "$medium/.travelrouter-update" ] || return 0
    read_state || return 1
    [ "$phase" = trial ] || return 1
    consecutive=0
    attempts=0
    while [ "$attempts" -lt 36 ]; do
        if healthy; then consecutive=$((consecutive + 1)); else consecutive=0; fi
        if [ "$consecutive" -ge 3 ]; then
            read -r watchdog < "$backup/watchdog.pid" || return 1
            case "$watchdog" in *[!0-9]*|'') return 1 ;; esac
            tr '\000' ' ' < "/proc/$watchdog/cmdline" | grep -q 'watchdog -F' || return 1
            kill -TERM "$watchdog" || return 1
            mount -o remount,rw "$medium" || return 1
            printf '%s\n' "$kind update confirmed after local service checks" > "$backup/result"
            sync
            rm -f "$medium/.travelrouter-update" "$backup/watchdog.pid"
            sync
            mount -o remount,ro "$medium"
            return 0
        fi
        attempts=$((attempts + 1))
        sleep 5
    done
    # The preboot transaction handler restores the previous generation.
    reboot -f
    return 1
}

case "${1:-}" in
    transition) medium=$2; backup="$medium/.travelrouter-recovery"; transition ;;
    early) early "${2:-}" ;;
    guard) guard ;;
    failure) failure "${2:-}" ;;
    *) echo 'Expected transition, early, failure, or guard' >&2; exit 2 ;;
esac
