#!/usr/bin/env python3
"""Run on an authorized Docker host. Change one Compose service; retain rollback."""
import copy
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

image, name = sys.argv[1:3]
assert '@sha256:' in image and image.startswith('princeamd/phpmyadmin:')

def run(args, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, **kwargs)
    if result.returncode:
        # Do not dump Compose environment/configuration or database credentials.
        raise RuntimeError(f'{args[0]} {args[1]} failed ({result.returncode}): {result.stderr[-1500:]}')
    return result.stdout

def inspect(container):
    return json.loads(run(['docker', 'inspect', container]))[0]

original = inspect(name)
labels = original['Config']['Labels']
files = labels['com.docker.compose.project.config_files'].split(',')
assert len(files) == 1, 'Multiple Compose files require an explicit review'
path = Path(files[0])
service = labels['com.docker.compose.service']
project = labels['com.docker.compose.project']
directory = labels['com.docker.compose.project.working_dir']
os.chdir(directory)
compose = ['docker', 'compose', '-p', project, '-f', str(path)]
before_config = json.loads(run(compose + ['config', '--format', 'json']))
assert service in before_config['services']
assert 'phpmyadmin' in before_config['services'][service]['image']
before = path.read_text()
stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
backup_dir = Path.home() / 'phpmyadmin-security-backups' / stamp
backup_dir.mkdir(parents=True, mode=0o700)
os.chmod(backup_dir, 0o700)
backup = backup_dir / path.name
backup.write_text(before)
os.chmod(backup, 0o600)
snapshot = backup_dir / 'container.json'
snapshot.write_text(json.dumps(original, indent=2))
os.chmod(snapshot, 0o600)

# Support both JSON and ordinary block-style YAML without rewriting other services.
try:
    document = json.loads(before)
except json.JSONDecodeError:
    document = None
if document is not None:
    old_image = document['services'][service]['image']
    needle = json.dumps(old_image)
    lines = before.splitlines(keepends=True)
    candidates = [i for i, line in enumerate(lines) if re.match(r'\s*"image"\s*:', line) and needle in line]
    assert len(candidates) == 1, 'Ambiguous JSON image pin'
    index = candidates[0]
    lines[index] = lines[index].replace(needle, json.dumps(image), 1)
    after = ''.join(lines)
else:
    lines = before.splitlines(keepends=True)
    found = False
    changed = 0
    indent = None
    for index, line in enumerate(lines):
        match = re.match(r'^(\s*)' + re.escape(service) + r':\s*(?:#.*)?$', line.rstrip('\n'))
        if match:
            found, indent = True, len(match[1])
            continue
        if found and line.strip() and not line.lstrip().startswith('#'):
            if len(line) - len(line.lstrip()) <= indent:
                found = False
            elif re.match(r'^\s+image\s*:', line):
                spacing = line[:len(line) - len(line.lstrip())]
                lines[index] = f'{spacing}image: {image}\n'
                changed += 1
    assert changed == 1, 'Could not isolate service image line'
    after = ''.join(lines)

run(['docker', 'pull', image], timeout=300)
target = inspect(image)['Id']
assert path.read_text() == before, 'Compose file changed during preflight'
mode = path.stat().st_mode & 0o777

def write_config(content):
    temporary = path.with_name(path.name + '.pma-security-tmp')
    temporary.write_text(content)
    os.chmod(temporary, mode)
    temporary.replace(path)

deployment_started = False
try:
    write_config(after)
    after_config = json.loads(run(compose + ['config', '--format', 'json']))
    expected = copy.deepcopy(before_config)
    expected['services'][service]['image'] = image
    assert after_config == expected, 'Unexpected configuration change'
    deployment_started = True
    if original['State']['Running']:
        run(compose + ['up', '-d', '--no-deps', '--no-build', '--force-recreate', service], timeout=180)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            current = inspect(name)
            if current['Image'] == target and current['State'].get('Health', {}).get('Status') == 'healthy':
                break
            if not current['State']['Running']:
                raise RuntimeError('Replacement exited')
            time.sleep(3)
        else:
            raise RuntimeError('Replacement did not become healthy')
        assert current['HostConfig']['PortBindings'] == original['HostConfig']['PortBindings']
        assert sorted((m['Source'], m['Destination']) for m in current['Mounts']) == sorted((m['Source'], m['Destination']) for m in original['Mounts'])
        bindings = current['HostConfig']['PortBindings']['80/tcp']
        address = bindings[0]['HostIp']
        if address in ('', '0.0.0.0'):
            address = '127.0.0.1'
        base = f'http://{address}:{bindings[0]["HostPort"]}'
        client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        page = client.open(base + '/index.php', timeout=15).read()
        assert b'phpMyAdmin' in page and b'Fatal error' not in page
        for fmt in ('xml', 'ods'):
            try:
                client.open(base + '/index.php?route=/import', urllib.parse.urlencode({'format': fmt}).encode(), timeout=10)
                raise AssertionError('Disabled import was accepted')
            except urllib.error.HTTPError as error:
                assert error.code == 403 and b'XML and ODS imports are disabled' in error.read()
        result = 'healthy; HTTP 200; XML/ODS HTTP 403'
    else:
        run(compose + ['up', '--no-start', '--no-deps', '--no-build', '--force-recreate', service], timeout=180)
        current = inspect(name)
        assert not current['State']['Running'] and current['Image'] == target
        result = 'updated; preserved stopped state'
except Exception:
    # Restore the configuration only if nobody else edited it in the meantime.
    if path.read_text() == after:
        rollback = before.replace(before_config['services'][service]['image'], original['Image'], 1)
        write_config(rollback)
        try:
            command = ['up', '-d', '--no-deps', '--no-build', '--force-recreate', service] if original['State']['Running'] else ['up', '--no-start', '--no-deps', '--no-build', '--force-recreate', service]
            if deployment_started:
                run(compose + command, timeout=180)
        finally:
            write_config(before)
    raise

print(json.dumps({'container': name, 'service': service, 'file': str(path), 'image': image, 'image_id': target,
    'result': result, 'backup': str(backup), 'before_sha256': hashlib.sha256(before.encode()).hexdigest(),
    'after_sha256': hashlib.sha256(after.encode()).hexdigest()}))
