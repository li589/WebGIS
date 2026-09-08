"""Quick E2E test"""
import json, time, urllib.request, urllib.error, http.cookiejar

BASE_URL = 'http://127.0.0.1:8000'
cookie_jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))

def api(path, method='GET', payload=None):
    data = json.dumps(payload).encode() if payload else None
    req = urllib.request.Request(f'{BASE_URL}{path}', data=data,
                                 headers={'Content-Type': 'application/json'}, method=method)
    try:
        with opener.open(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, body
    except Exception as e:
        return -1, str(e)

# Login
code, data = api('/auth/login', 'POST', {'username': 'admin', 'password': 'cgda-dev-admin'})
print(f'Login: {code}')

# Trigger seed sync
code, data = api('/workflow-definitions')
if isinstance(data, dict):
    count = len(data.get('items', []))
elif isinstance(data, list):
    count = len(data)
else:
    count = -1
print(f'Sync: {code} definitions={count}')

# Submit FY workflow
code, data = api('/workflow-runs', 'POST', {
    'command_type': 'analysis',
    'layer_id': 'ref-fy-tb-202512-mwri',
    'time_range': {'start_at': '2025-06-01T00:00:00', 'end_at': '2025-06-02T00:00:00', 'granularity': 'day'},
    'algorithm_request': {'workflow_name': 'fy_tb_online_read'},
})
run_id = data.get('run_id') if isinstance(data, dict) else None
print(f'Submit: {code} run_id={run_id}')

if run_id:
    time.sleep(10)
    code2, data2 = api(f'/workflow-runs/{run_id}')
    status = data2.get('status') if isinstance(data2, dict) else str(data2)[:100]
    print(f'Status: {code2} => {status}')
    if isinstance(data2, dict) and status in ('failed', 'cancelled'):
        print(f'Detail: {str(data2.get("message", data2.get("error", "")))[:300]}')
