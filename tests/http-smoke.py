#!/usr/bin/env python3
"""Exercise an isolated phpMyAdmin + disposable MySQL instance; never production."""
import html
import http.cookiejar
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

base = sys.argv[1].rstrip('/')
cookies = http.cookiejar.CookieJar()
client = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(cookies))
checks = []

def request(path, data=None):
    response = client.open(base + path, None if data is None else urllib.parse.urlencode(data).encode(), timeout=30)
    body = response.read().decode('utf-8', errors='replace')
    assert 'Fatal error' not in body and 'Uncaught ' not in body, body[-1500:]
    return body

def hidden(body, name):
    match = re.search(r'name="' + re.escape(name) + r'"[^>]*value="([^"]*)"', body)
    assert match, f'Missing {name}'
    return html.unescape(match[1])

login = request('/index.php')
assert 'id="login_form"' in login
checks.append('unauthenticated login page and Twig rendering')
page = request('/index.php?route=/', {
    'token': hidden(login, 'token'), 'set_session': hidden(login, 'set_session'),
    'pma_username': 'pma_test', 'pma_password': 'pma-test-only', 'server': '1', 'lang': 'en',
})
assert 'id="login_form"' not in page and 'pma_test' in page, page[-2000:]
assert any(c.name.startswith('pmaAuth') for c in cookies)
checks.append('cookie login against MySQL 8.4')
token = hidden(page, 'token')
imports = request('/index.php?route=/database/import&server=1&db=pma_test')
assert not re.search(r'<option[^>]+value="(?:xml|ods)"', imports, re.I)
checks.append('XML and ODS are absent from import choices')
for disabled in ['xml', 'ods', 'XML', 'ODS']:
    try:
        request('/index.php?route=/import', {
            'token': token, 'server': '1', 'db': 'pma_test',
            'format': disabled, 'import_type': 'database', 'import_text': '<test/>',
        })
        raise AssertionError(f'Disabled format accepted: {disabled}')
    except urllib.error.HTTPError as e:
        assert e.code == 403 and b'XML and ODS imports are disabled' in e.read()
checks.append('direct XML/ODS import submissions are rejected with HTTP 403')
sql = "DROP TABLE IF EXISTS smoke; CREATE TABLE smoke (id INT PRIMARY KEY, message VARCHAR(255)); INSERT INTO smoke VALUES (1, 'php84_security_smoke');"
request('/index.php?route=/import', {
    'token': token, 'server': '1', 'db': 'pma_test', 'sql_query': sql,
    'import_type': 'database', 'format': 'sql',
})
page = request('/index.php?' + urllib.parse.urlencode({
    'route': '/sql', 'server': '1', 'db': 'pma_test', 'table': 'smoke', 'sql_query': 'SELECT * FROM smoke',
}))
assert 'php84_security_smoke' in page, page[-2000:]
checks.append('SQL import/create/insert and table browse')
for route in ['/database/structure', '/database/sql', '/database/import', '/database/export', '/table/structure', '/table/search', '/table/change', '/table/export']:
    body = request('/index.php?' + urllib.parse.urlencode({'route': route, 'server': 1, 'db': 'pma_test', 'table': 'smoke'}))
    assert 'id="login_form"' not in body
    checks.append(route)
export = request('/index.php?route=/export', {
    'token': hidden(page, 'token'), 'server': '1', 'db': 'pma_test', 'table': 'smoke',
    'export_type': 'table', 'export_method': 'quick', 'quick_or_custom': 'quick', 'what': 'sql',
    'sql_structure_or_data': 'structure_and_data', 'sql_data': 'something',
    'sql_structure': 'something', 'sql_type': 'INSERT', 'sql_insert_syntax': 'both',
    'asfile': 'sendit', 'filename_template': '@TABLE@', 'charset_of_file': 'utf-8', 'compression': 'none',
})
assert 'php84_security_smoke' in export and 'INSERT INTO' in export, export[-2000:]
checks.append('SQL export contains inserted data')
for path in ['/composer.lock', '/vendor/autoload.php', '/templates/login/form.twig', '/tmp/', '/setup/']:
    try:
        request(path)
        raise AssertionError(f'Sensitive path exposed: {path}')
    except urllib.error.HTTPError as e:
        assert e.code in (403, 404), e.code
checks.append('sensitive files and setup inaccessible over HTTP')
request('/index.php?route=/logout', {'server': '1', 'token': hidden(page, 'token')})
assert 'id="login_form"' in request('/index.php')
checks.append('logout invalidates authentication')
print(json.dumps({'passed': len(checks), 'checks': checks}, indent=2))
