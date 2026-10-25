# syntax=docker/dockerfile:1
FROM phpmyadmin:5.2.3-apache@sha256:62a50b1419fe55b9b4c3cd6f5aed03a18f8f5b4a236f24735d76400bea75a5ff AS upstream
FROM composer:2@sha256:b6dcd72ca98fa19d0e5b8476de179859704891fad06dd9e0b96833d4c430a5fc AS composer

FROM princeamd/php84-fpm:8.4.27-r2@sha256:7c8e805b922a9ff34a3865719b25b7b4b06094f7fd8e6a0e042722568b643ff6 AS php
USER root
# No NodeSource packages are needed; use signed Debian stable/security updates.
RUN rm -f /etc/apt/sources.list.d/nodesource.* \
    && install-php-extensions mysqli bz2

FROM php AS dependencies
COPY --from=composer /usr/bin/composer /usr/local/bin/composer
WORKDIR /var/www/html
COPY --from=upstream /var/www/html/ /var/www/html/
COPY composer.json composer.lock ./
ENV COMPOSER_ALLOW_SUPERUSER=1
# Reinstall from the reviewed lock, preserving bundled PDF and 2FA features.
RUN rm -rf vendor \
    && rm libraries/classes/Plugins/Import/ImportXml.php libraries/classes/Plugins/Import/ImportOds.php \
    && composer install --no-dev --prefer-dist --no-interaction --no-plugins --no-scripts --optimize-autoloader \
    && composer check-platform-reqs --no-dev

FROM php AS runtime
ARG VERSION=5.2.3-php8.4.27-r3
LABEL org.opencontainers.image.title="phpMyAdmin on princeamd PHP 8.4" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.vendor="princeamd" \
      org.opencontainers.image.source="https://github.com/deonthomasgy/docker-phpmyadmin" \
      org.opencontainers.image.licenses="GPL-2.0-only" \
      org.opencontainers.image.description="phpMyAdmin 5.2.3 with patched dependencies, Apache and PHP 8.4 FPM"
COPY docker/runtime-security.sh /usr/local/bin/phpmyadmin-runtime-security
RUN sh /usr/local/bin/phpmyadmin-runtime-security
WORKDIR /var/www/html
COPY --from=dependencies /var/www/html/ /var/www/html/
COPY --from=upstream /etc/phpmyadmin/ /etc/phpmyadmin/
COPY --from=upstream /docker-entrypoint.sh /usr/local/bin/phpmyadmin-upstream-entrypoint
COPY docker/apache.conf /etc/apache2/sites-available/000-default.conf
COPY docker/phpmyadmin.ini /usr/local/etc/php/conf.d/zzzz-phpmyadmin.ini
COPY docker/fpm.conf /usr/local/etc/php-fpm.d/zz-phpmyadmin.conf
COPY docker/import-policy.php /usr/local/lib/phpmyadmin/import-policy.php
COPY --chmod=755 docker/start.sh /usr/local/bin/phpmyadmin-start
ENV PMA_SSL_DIR=/etc/phpmyadmin/ssl \
    MAX_EXECUTION_TIME=600 MEMORY_LIMIT=512M UPLOAD_LIMIT=2048K TZ=UTC \
    SESSION_SAVE_PATH=/sessions APACHE_PORT=80 \
    PHP_MEMORY_LIMIT=512M PHP_MAX_EXECUTION_TIME=600
RUN mkdir -p /sessions /etc/phpmyadmin/ssl /var/www/html/tmp \
    && ln -s /usr/local/bin/phpmyadmin-start /usr/local/bin/apache2ctl-pma \
    && chmod 1777 /sessions \
    && chown -R www-data:www-data /etc/phpmyadmin /var/www/html/tmp \
    && a2enmod proxy proxy_fcgi setenvif remoteip \
    && a2dismod -f autoindex status \
    && printf 'ServerName localhost\nServerTokens Prod\nServerSignature Off\n' > /etc/apache2/conf-enabled/security-local.conf \
    && printf 'Listen ${APACHE_PORT}\n' > /etc/apache2/ports.conf \
    && ln -sf /proc/self/fd/1 /var/log/apache2/access.log \
    && ln -sf /proc/self/fd/2 /var/log/apache2/error.log \
    && php-fpm -t && apache2ctl configtest
EXPOSE 80
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl --fail --silent --max-time 4 "http://127.0.0.1:${APACHE_PORT}/index.php" > /dev/null || exit 1
ENTRYPOINT ["/usr/local/bin/phpmyadmin-start"]
CMD ["serve"]
