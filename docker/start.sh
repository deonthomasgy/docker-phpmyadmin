#!/bin/bash
set -euo pipefail
if [[ "${1:-}" != serve ]]; then
    exec /usr/local/bin/phpmyadmin-upstream-entrypoint "$@"
fi
if [[ "${PMA_UNDER_TINI:-}" != 1 ]]; then
    export PMA_UNDER_TINI=1
    exec /usr/bin/tini -- "$0" serve
fi
case "$APACHE_PORT" in ''|*[!0-9]*) echo 'APACHE_PORT must be numeric' >&2; exit 1;; esac
if (( APACHE_PORT < 1 || APACHE_PORT > 65535 )); then exit 1; fi
# Initialize upstream secrets, configuration and *_FILE environment variables
# in the same process environment before starting either server.
if [[ "${PMA_CONFIG_READY:-}" != 1 ]]; then
    export PMA_CONFIG_READY=1
    exec /usr/local/bin/phpmyadmin-upstream-entrypoint apache2ctl-pma serve
fi
mkdir -p "$SESSION_SAVE_PATH" /var/www/html/tmp /run/apache2
chown www-data:www-data "$SESSION_SAVE_PATH" /var/www/html/tmp
php-fpm -t
apache2ctl configtest
php-fpm -F &
fpm_pid=$!
apache2ctl -D FOREGROUND &
apache_pid=$!
stop() {
    kill -TERM "$fpm_pid" "$apache_pid" 2>/dev/null || true
    apache2ctl -k stop 2>/dev/null || true
    wait "$fpm_pid" "$apache_pid" 2>/dev/null || true
}
trap 'stop; exit 0' TERM INT QUIT
set +e
wait -n "$fpm_pid" "$apache_pid"
status=$?
stop
# A server exiting, even with zero, must not leave a half-working container.
(( status == 0 )) && status=1
exit "$status"
