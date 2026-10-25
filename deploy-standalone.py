#!/usr/bin/env python3
"""Replace one standalone phpMyAdmin container, preserving its Docker configuration."""
import copy
import datetime
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

image, name = sys.argv[1:3]
assert image.startswith('princeamd/phpmyadmin:') and '@sha256:' in image

def inspect(ref):
    return json.loads(subprocess.check_output(['docker', 'inspect', ref]))[0]

class DockerConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect('/var/run/docker.sock')

def api(method, path, body=None):
    connection = DockerConnection('localhost', timeout=60)
    connection.request(method, path, body=None if body is None else json.dumps(body), headers={'Content-Type': 'application/json'})
    response = connection.getresponse()
    data = response.read()
    connection.close()
    if response.status >= 300:
        raise RuntimeError(f'Docker {method} {path}: HTTP {response.status}: {data.decode()[:300]}')
    return json.loads(data) if data else {}

old = inspect(name)
assert old['State']['Running']
assert not any(k.startswith('com.docker.compose.') or k.startswith('com.docker.swarm.') for k in old['Config'].get('Labels', {}))
subprocess.run(['docker', 'pull', image], check=True, stdout=subprocess.DEVNULL)
base_old = inspect(old['Image'])['Config']
new_image = inspect(image)
new_config = copy.deepcopy(new_image['Config'])
fields = ['Hostname', 'Domainname', 'User', 'ExposedPorts', 'Tty', 'OpenStdin', 'StdinOnce',
    'Cmd', 'Healthcheck', 'Volumes', 'WorkingDir', 'Entrypoint', 'StopTimeout']
for key in fields:
    if old['Config'].get(key) != base_old.get(key):
        new_config[key] = copy.deepcopy(old['Config'].get(key))
env = dict(item.split('=', 1) for item in new_config.get('Env', []))
base_env = dict(item.split('=', 1) for item in base_old.get('Env', []))
for item in old['Config'].get('Env', []):
    key, value = item.split('=', 1)
    if base_env.get(key) != value:
        env[key] = value
new_config['Env'] = [f'{key}={value}' for key, value in env.items()]
for key, value in old['Config'].get('Labels', {}).items():
    if base_old.get('Labels', {}).get(key) != value:
        new_config.setdefault('Labels', {})[key] = value
new_config['Image'] = image
new_config['HostConfig'] = copy.deepcopy(old['HostConfig'])
endpoints = {}
for network, endpoint in old['NetworkSettings']['Networks'].items():
    endpoints[network] = {key: endpoint[key] for key in ['IPAMConfig', 'Aliases', 'Links', 'DriverOpts'] if endpoint.get(key) is not None}
    if 'Aliases' in endpoints[network]:
        endpoints[network]['Aliases'] = [a for a in endpoints[network]['Aliases'] if a not in (old['Id'], old['Id'][:12])]
new_config['NetworkingConfig'] = {'EndpointsConfig': endpoints}
stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
backup_dir = Path.home() / 'phpmyadmin-security-backups' / stamp
backup_dir.mkdir(parents=True, mode=0o700)
os.chmod(backup_dir, 0o700)
backup = backup_dir / 'container.json'
backup.write_text(json.dumps(old, indent=2))
os.chmod(backup, 0o600)
old_name = name + '-rollback-' + stamp
renamed = False
created = False
try:
    api('POST', f'/containers/{old["Id"]}/stop?t=30')
    api('POST', f'/containers/{old["Id"]}/rename?name={old_name}')
    renamed = True
    new = api('POST', f'/containers/create?name={name}', new_config)
    created = True
    api('POST', f'/containers/{new["Id"]}/start')
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        current = inspect(name)
        if current['Image'] == new_image['Id'] and current['State'].get('Health', {}).get('Status') == 'healthy':
            break
        if not current['State']['Running']:
            raise RuntimeError('Replacement exited')
        time.sleep(3)
    else:
        raise RuntimeError('Replacement did not become healthy')
    assert current['HostConfig']['PortBindings'] == old['HostConfig']['PortBindings']
    assert current['HostConfig']['RestartPolicy'] == old['HostConfig']['RestartPolicy']
    assert sorted((m['Source'], m['Destination']) for m in current['Mounts']) == sorted((m['Source'], m['Destination']) for m in old['Mounts'])
    bind = current['HostConfig']['PortBindings']['80/tcp'][0]
    host = bind['HostIp'] if bind['HostIp'] not in ('', '0.0.0.0') else '127.0.0.1'
    url = f'http://{host}:{bind["HostPort"]}/index.php'
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    page = client.open(url, timeout=15).read()
    assert b'phpMyAdmin' in page and b'Fatal error' not in page
    for fmt in ('xml', 'ods'):
        try:
            client.open(url+'?route=/import', urllib.parse.urlencode({'format': fmt}).encode(), timeout=10)
            raise AssertionError('Disabled import accepted')
        except urllib.error.HTTPError as error:
            assert error.code == 403 and b'XML and ODS imports are disabled' in error.read()
except Exception:
    if created:
        api('DELETE', f'/containers/{name}?force=true')
    if renamed:
        api('POST', f'/containers/{old["Id"]}/rename?name={name}')
    api('POST', f'/containers/{old["Id"]}/start')
    raise

# Persist the replacement specification privately on the host for future use.
spec = Path.home() / 'phpmyadmin' / 'container-spec.json'
spec.write_text(json.dumps({'name': name, 'create': new_config}, indent=2))
os.chmod(spec, 0o600)
api('DELETE', f'/containers/{old["Id"]}')
print(json.dumps({'container': name, 'image': image, 'image_id': new_image['Id'],
    'result': 'healthy; HTTP 200; XML/ODS HTTP 403; custom configuration retained',
    'backup': str(backup), 'specification': str(spec)}))
