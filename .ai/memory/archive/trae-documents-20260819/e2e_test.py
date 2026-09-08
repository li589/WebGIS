"""E2E 测试：在线数据拉取功能验证（修正版）"""
import json
import time
import urllib.request
import urllib.error
import http.cookiejar

BASE_URL = 'http://127.0.0.1:8000'

cookie_jar = http.cookiejar.CookieJar()
cookie_handler = urllib.request.HTTPCookieProcessor(cookie_jar)
opener = urllib.request.build_opener(cookie_handler)

def api_request(path, method='GET', payload=None):
    url = f'{BASE_URL}{path}'
    headers = {'Content-Type': 'application/json'}
    data = json.dumps(payload).encode() if payload else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with opener.open(req, timeout=30) as resp:
            body = resp.read().decode()
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, body
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:400] if e.fp else ''
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, body
    except Exception as e:
        return -1, str(e)

print('=' * 55)
print('  E2E 在线数据拉取功能测试')
print('=' * 55)

# ── 0. 登录 ──
print('\n[0] 登录 admin')
code, data = api_request('/auth/login', 'POST', {
    'username': 'admin',
    'password': 'cgda-dev-admin'
})
if code == 200:
    print(f'  [OK] Login success - role={data.get("role")}')
else:
    print(f'  [FAIL] Login HTTP {code}: {str(data)[:200]}')
    exit(1)

# ── 1. 触发种子同步：GET /workflow-definitions ──
print('\n[1] 触发种子同步 (GET /workflow-definitions)')
code, data = api_request('/workflow-definitions')
if code == 200:
    if isinstance(data, dict) and 'items' in data:
        defs = data['items']
    elif isinstance(data, list):
        defs = data
    else:
        defs = []
    print(f'  [OK] {len(defs)} definitions loaded')
    # 检查新种子是否在列表中
    def_names = [d.get('name', d.get('workflow_name', '')) for d in defs]
    for wf in ['fy_tb_online_read', 'ndvi_online_read', 'ndvi_gee_read',
               'fy_tb_nas_read', 'fy_tb_nsmc_online']:
        exists = wf in def_names
        print(f'    {"✓" if exists else "✗"} {wf}')
else:
    print(f'  [FAIL] HTTP {code}: {str(data)[:200]}')

# ── 2. 逐个检查工作流定义 ──
print('\n[2] 逐个检查工作流定义')
workflows = ['fy_tb_online_read', 'ndvi_online_read', 'ndvi_gee_read',
             'fy_tb_nas_read', 'fy_tb_nsmc_online']
for wf in workflows:
    code, data = api_request(f'/workflow-definitions/{wf}')
    if code == 200:
        node_count = len(data.get('nodes', []))
        print(f'  [OK]   {wf} - {node_count} nodes')
    else:
        print(f'  [FAIL] {wf} - HTTP {code}: {str(data)[:100]}')

# ── 3. 检查图层目录 ──
print('\n[3] 检查图层目录 (GET /layers)')
code, data = api_request('/layers')
if code == 200:
    items = data.get('items', data) if isinstance(data, dict) else data
    print(f'  Total layers: {len(items)}')
    for layer in items:
        lid = layer.get('layer_id', '')
        if lid in ('ref-fy-tb-202512-mwri', 'ndvi'):
            ot = layer.get('online_temporal', {})
            wf_online = layer.get('workflow_online_name', '')
            aliases = layer.get('workflow_aliases', [])
            print(f'  [{lid}]')
            print(f'    online_temporal.enabled = {ot.get("enabled")}')
            print(f'    workflow_online_name = {wf_online}')
            print(f'    workflow_aliases = {aliases}')
else:
    print(f'  [FAIL] HTTP {code}: {str(data)[:200]}')

# ── 4. 检查 online-temporal 端点 ──
print('\n[4] 检查图层 online-temporal 端点')
for layer_id in ['ref-fy-tb-202512-mwri', 'ndvi']:
    code, data = api_request(f'/layers/{layer_id}/online-temporal')
    if code == 200:
        print(f'  [OK]   {layer_id} - {json.dumps(data, ensure_ascii=False)[:200]}')
    else:
        print(f'  [FAIL] {layer_id} - HTTP {code}: {str(data)[:100]}')

# ── 5. 提交 FY 在线工作流 ──
print('\n[5] 提交 FY 在线工作流 (fy_tb_online_read)')
fy_payload = {
    'command_type': 'analysis',
    'layer_id': 'ref-fy-tb-202512-mwri',
    'time_range': {
        'start_at': '2025-06-01T00:00:00',
        'end_at': '2025-06-02T00:00:00',
        'granularity': 'day',
    },
    'algorithm_request': {
        'workflow_name': 'fy_tb_online_read',
    },
}
code, data = api_request('/workflow-runs', 'POST', fy_payload)
fy_run_id = None
if code in (200, 201, 202):
    fy_run_id = data.get('run_id')
    print(f'  [OK] Run ID: {fy_run_id}  Status: {data.get("status")}')
else:
    print(f'  [FAIL] HTTP {code}: {str(data)[:300]}')

# ── 6. 提交 NDVI Earthdata 在线工作流 ──
print('\n[6] 提交 NDVI Earthdata 在线工作流 (ndvi_online_read)')
ndvi_payload = {
    'command_type': 'analysis',
    'layer_id': 'ndvi',
    'time_range': {
        'start_at': '2025-06-01T00:00:00',
        'end_at': '2025-06-02T00:00:00',
        'granularity': 'day',
    },
    'algorithm_request': {
        'workflow_name': 'ndvi_online_read',
    },
}
code, data = api_request('/workflow-runs', 'POST', ndvi_payload)
ndvi_run_id = None
if code in (200, 201, 202):
    ndvi_run_id = data.get('run_id')
    print(f'  [OK] Run ID: {ndvi_run_id}  Status: {data.get("status")}')
else:
    print(f'  [FAIL] HTTP {code}: {str(data)[:300]}')

# ── 7. 轮询工作流状态（90秒）──
print('\n[7] 轮询工作流状态 (90s)')
run_ids = []
if fy_run_id:
    run_ids.append(('FY', fy_run_id))
if ndvi_run_id:
    run_ids.append(('NDVI', ndvi_run_id))

if not run_ids:
    print('  无可轮询的工作流运行')
else:
    deadline = time.time() + 90
    while time.time() < deadline and run_ids:
        time.sleep(5)
        remaining = []
        for name, rid in run_ids:
            code, data = api_request(f'/workflow-runs/{rid}')
            if code == 200:
                status = data.get('status', 'unknown')
                progress = data.get('progress', '')
                msg = data.get('message', data.get('error', ''))
                print(f'  [{name}] {rid} => {status} {progress}')
                if msg and status in ('failed', 'cancelled'):
                    print(f'         detail: {str(msg)[:300]}')
                if status in ('succeeded', 'failed', 'cancelled'):
                    continue
            else:
                print(f'  [{name}] {rid} => poll error HTTP {code}')
            remaining.append((name, rid))
        run_ids = remaining

print('\n' + '=' * 55)
print('  E2E 测试完成')
print('=' * 55)
