# phpMyAdmin on our PHP 8.4 image

Custom phpMyAdmin 5.2.3 image built from `princeamd/php84-fpm:8.4.27-r2`, with
Apache 2.4 forwarding PHP requests to FPM on loopback. Release:
`princeamd/phpmyadmin:5.2.3-php8.4.27-r3` (linux/amd64).

The application and upstream environment/secrets configuration come from the
Docker Official Image `phpmyadmin:5.2.3-apache`, pinned by digest. The older
`phpmyadmin/phpmyadmin:latest` namespace still serves its October 2025 build.
phpMyAdmin 5.2.3 remains the latest stable 5.x release as checked on 2026-10-25;
there is no newer stable upstream application tag that fixes the bundled Twig.

## Changes

- PHP 8.3.26 → our PHP 8.4.27, explicitly requested by the owner.
- Debian 13.1 → 13.7; signed stable/security updates run during the build.
- Twig 3.11.3 → 3.27.0; Symfony cache 5.4.46 → 5.4.52,
  expression-language 5.4.45 → 5.4.54, process 5.4.47 → 5.4.51;
  sodium_compat 1.23.0 → 1.24.2. Other runtime packages remain locked.
- Apache → 2.4.69-1~deb13u1, OpenSSL → 3.5.7-1~deb13u3,
  PCRE2 → 10.46-1~deb13u3. The build asserts minimum fixed versions.
- Remove development headers/compiler tools, Node/npm, Composer, Git/SSH/GnuPG,
  Java/pdftk, MariaDB client libraries and Imagick/Ghostscript. phpMyAdmin uses
  mysqli/mysqlnd, GD and TCPDF, so database access and PDF support remain.
- Keep the PHP base's `session.upload_progress.enabled=0` mitigation for
  CVE-2026-115560. Uploads work; upload-progress tracking is unavailable.
- Keep HTTP on port 80, `APACHE_PORT`, the upstream `PMA_*`/`*_FILE`/base64
  configuration, upload limits, sessions and custom configuration mounts.
  FPM listens only on loopback; do not publish the inherited metadata port 9000.
- Apache uses event MPM + proxy_fcgi instead of mod_php. Custom mod_php Apache
  directives would require migration. The inspected production deployment has
  only an `/etc/localtime` mount and uses the standard HTTP interface.
- Tini reaps children; either server failing stops the container. SIGTERM shuts
  down both servers. HTTP health checks exercise Apache, FPM and application rendering.

No phpMyAdmin or dependency major version upgrade is included. PHP 8.4 support
and deprecation fixes appear in the upstream 5.2.3 release notes. The upstream
test suite still emits non-failing PHP 8.4 and PHPUnit deprecation warnings.
Twig 3.27's future 4.0 sandbox strict mode is opt-in and is not enabled here.

## Build and verify

```sh
./verify.sh
```

This rebuilds without cached package updates, compiles every application Twig
template, saves the full unsuppressed Trivy JSON and CRITICAL/HIGH table, and
fails if any of the nine requested CVEs or any finding with a fixed version
remains. Scanner: `aquasec/trivy:0.75.0`; reports are local artifacts in `reports/`.
There is no Trivy ignore file or VEX suppression.

`tests/http-smoke.py URL` logs into a **disposable** test instance using the
test-only account `pma_test` / `pma-test-only`, creates and replaces a table named
`smoke` in database `pma_test`, exercises SQL import/browse/export, checks blocked
internal paths, and logs out. Never point it at production.

For upstream tests, use the `RELEASE_5_2_3` checkout of
https://github.com/phpmyadmin/phpmyadmin and PHPUnit 9.6.38 from
https://phar.phpunit.de/phpunit-9.phar. Mount its `test`, `examples` and
`templates/test` directories at the matching `/var/www/html/` paths, mount this
project's `tests` at `/tests`, and run:

```sh
php -d session.cookie_httponly=0 /tmp/phpunit -c /tests/upstream-phpunit.xml
```

The CLI-only cookie override matches the upstream test's expected PHP defaults;
production retains HttpOnly cookies. Network-group tests need outbound internet.
XML/ODS plugin tests are excluded because those classes are removed, and
`tests/upstream-disabled-imports.patch` adjusts the plugin count from six to four.
The tested suite had 3,119 tests, 12,441 assertions, zero failures/errors,
48 skips and 3 PHPUnit warnings. All 270 Twig templates and 16 HTTP checks passed.

Apache failure made the container exit with status 1. Sending SIGTERM to Tini
inside the container stopped both servers with status 0. This workstation's
Docker daemon reported `unable to signal init: permission denied` for its own
signal delivery, so `docker stop` timed out and forced a kill locally. Verify
Docker's host-side stop/recreate behavior during the approved production rollout.

Dependency maintenance: build the `dependencies` target, then use its Composer
to update selected packages with `--with-dependencies --minimal-changes`. Keep
the optional PDF and 2FA packages in `require`: upstream distribution packages
include these even though the upstream development manifest labels them dev
dependencies. Review the lock diff and repeat tests/scanning before publishing.

## Security results and remaining risk

The original image's full scan contained 28 critical / 1,023 high findings.
This image has 1 critical / 60 high, plus 105 medium, 185 low and 5 unknown.
All **22 requested package findings (9 unique CVEs)** are absent. All 6,923
original findings with an available fix are gone; the final scan has zero
findings with an available fix. Counts are package/advisory occurrences, not
distinct exploitable vulnerabilities. See `security-review.json` for retained
critical/high findings and package-specific rationale.

Unfixed does not mean harmless. In particular, Debian's `libxml2` is required
by PHP and remains vulnerable. Authenticated XML/ODS imports call SimpleXML on
uploaded content. This release removes `ImportXml.php` and `ImportOds.php` before generating
the autoloader. XML/ODS choices disappear from the UI, and a PHP prepend guard
returns HTTP 403 for direct XML/ODS import submissions before application parsing.
This blocks those import entry points, but is not proof that every libxml2 path
in PHP and optional libraries is unreachable. SQL and CSV imports and XML/ODS
exports remain available. A patched stable libxml2 or a tested
backport is still required. Do not mix Debian unstable packages into this image.

The remaining curl, ncurses, X11, util-linux, ACL, systemd-library and Perl
findings are documented separately. These have no fixed Debian 13 package in
the scanned database. The image is a remediation for the supplied RCE list,
not a claim of zero remaining vulnerabilities or an approval to accept all risk.

The `linux-libc-dev` ksmbd findings concern development headers from the kernel
source package, not a running kernel inside the image. Removing the headers
eliminates those image findings; host-kernel patching is a separate operation.

## Production deployment

Host: `mintage-host-9`; file: `/home/thomas/mysql/docker-compose.yml`, image currently at line 98;
Compose project: `mysql`; service: `phpmyadmin-9`; container:
`thomas-phpmyadmin-9`. Current image: `phpmyadmin/phpmyadmin:latest`. The deployment file changed from YAML to JSON during this work through an external change; the proposed patch was refreshed and dry-run checked against its current contents.
HTTP is bound to the host's Tailscale address on port 8080. Deployment is authorized for all discovered hosts. `deploy-compose.py` backs up
the original configuration on each host, changes only its phpMyAdmin image pin,
and preserves ports, mounts, other services and stopped instances.
`deployment-results.json` records the verified rollout.

`deployment.patch` contains the proposed immutable image pin. Preserve all other configuration, pull the pinned image,
and recreate only `phpmyadmin-9` with `docker compose up -d --no-deps phpmyadmin-9`.
Verify login, database browsing/import/export and health after replacement.
Rollback by restoring the previous image reference and recreating that service.
Releases r1 and r2 are superseded; use r3 with XML/ODS imports disabled.

## Sources

- https://www.phpmyadmin.net/downloads/
- https://github.com/phpmyadmin/phpmyadmin/blob/RELEASE_5_2_3/ChangeLog
- https://github.com/phpmyadmin/docker
- https://symfony.com/blog/twig-3-26-0-released
- https://symfony.com/blog/twig-3-27-0-released
- https://security-tracker.debian.org/tracker/CVE-2026-63292
- https://security-tracker.debian.org/tracker/CVE-2026-28387
- https://security-tracker.debian.org/tracker/CVE-2026-86138
- https://security-tracker.debian.org/tracker/CVE-2026-86140
- https://security-tracker.debian.org/tracker/CVE-2026-86142

Upstream phpMyAdmin is GPL-2.0-only. Its source/release, licenses, runtime
dependency versions and source references are retained in the distribution and
Composer lock. Local Docker build scripts are maintained in this directory.
