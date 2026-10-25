#!/bin/sh
set -eu
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get upgrade -y --no-install-recommends --no-remove
apt-get install -y --no-install-recommends apache2 tini

# phpMyAdmin uses GD, not Imagick, and connects through mysqli/mysqlnd.
rm -f /usr/local/etc/php/conf.d/*imagick* /usr/local/lib/php/extensions/*/imagick.so
packages=$(dpkg-query -W -f='${binary:Package} ${db:Status-Status}\n' | awk '
 $2 == "installed" {
   n=$1; sub(/:.*/, "", n)
   if (n ~ /-dev$/ || n ~ /^(autoconf|automake|m4|make|patch|rpcsvc-proto|re2c|pkg-config|pkgconf|pkgconf-bin|dpkg-dev|linux-libc-dev|libc-dev-bin|nodejs|npm|openssh-client|git|git-man|gnupg|gnupg-l10n|gpg|gpg-agent|gpgsm|gpgconf|dirmngr|pinentry-curses|python3.*|libpython3.*|mariadb-.*|libmariadb3|pdftk.*|default-jre.*|openjdk-.*|java-common|ca-certificates-java|ghostscript|imagemagick.*)$/ || n ~ /-java$/ || n ~ /^(cpp|gcc|g\+\+)(-[0-9]+)?(-x86-64-linux-gnu)?$/ || n ~ /^(binutils.*|libasan[0-9]+|liblsan[0-9]+|libtsan[0-9]+|libubsan[0-9]+|libhwasan[0-9]+|libcc1-0|libgprofng0|libctf.*|libsframe[0-9]+)$/) print $1
 }')
apt-get purge -y $packages
libraries=$(dpkg-query -W -f='${binary:Package} ${db:Status-Status}\n' | awk '$2 == "installed" && $1 ~ /^lib/ { print $1 }')
apt-mark auto $libraries >/dev/null
# PHP and its extensions live outside dpkg: protect their shared libraries.
ldd /usr/local/bin/php /usr/local/sbin/php-fpm /usr/local/lib/php/extensions/*/*.so \
  | awk '/=> \/.* / {print $3} $1 ~ /^\// && $2 ~ /^\(/ {print $1}' | sort -u \
  | while read -r lib; do dpkg-query -S "$(readlink -f "$lib")" | sed 's/: \/.*//' | head -1; done > /tmp/php-runtime-packages
apt-mark manual $(sort -u /tmp/php-runtime-packages) >/dev/null
apt-get autoremove -y --purge
apt-get clean
rm -rf /var/lib/apt/lists/* /usr/lib/node_modules /usr/local/lib/node_modules \
  /root/.npm /root/.cache /root/.composer /tmp/pear /usr/src/php \
  /usr/local/include/php /usr/local/lib/php/build
rm -f /tmp/php-runtime-packages /usr/bin/composer /usr/local/bin/composer /usr/local/bin/phpize /usr/local/bin/php-config
php -r 'foreach (["mysqli", "mysqlnd", "bz2", "gd", "mbstring", "zip", "openssl", "sodium"] as $e) {if (!extension_loaded($e)) {throw new RuntimeException("Missing extension: $e");}}'
for package in apache2 apache2-bin apache2-data apache2-utils; do
  dpkg --compare-versions "$(dpkg-query -W -f='${Version}' "$package")" ge '2.4.69-1~deb13u1'
done
dpkg --compare-versions "$(dpkg-query -W -f='${Version}' libssl3t64)" ge '3.5.5-1~deb13u2'
dpkg --compare-versions "$(dpkg-query -W -f='${Version}' libpcre2-8-0)" ge '10.46-1~deb13u2'
if dpkg-query -W -f='${binary:Package} ${db:Status-Status}\n' | grep -E '^(linux-libc-dev|mariadb-.*|libmariadb3|libcups2t64|libopenexr.*|libxrender1|openjdk-.*|nodejs)(:[^ ]+)? installed$'; then
  echo 'Unexpected unnecessary vulnerable runtime package' >&2; exit 1
fi
