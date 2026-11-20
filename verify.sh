#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
image="${1:-princeamd/phpmyadmin:5.2.3-php8.4.28-r0}"
mkdir -p reports
docker build --pull --no-cache --progress=plain -t "$image" .
docker run --rm -v "$PWD/tests:/tests:ro" "$image" php /tests/templates.php
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
    -v mp-deployer-trivy-cache:/root/.cache/trivy -v "$PWD/reports:/reports" \
    aquasec/trivy:0.75.0 image --scanners vuln --timeout 20m \
    --format json --output /reports/after.json "$image"
python3 tests/check-scan.py reports/after.json > reports/summary.json
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
    -v mp-deployer-trivy-cache:/root/.cache/trivy -v "$PWD/reports:/reports" \
    aquasec/trivy:0.75.0 image --severity CRITICAL,HIGH --scanners vuln \
    --skip-db-update --format table --output /reports/critical-high.txt "$image"
echo 'Build, template compilation and scan gate passed. Run integration and upstream tests before publishing.'
