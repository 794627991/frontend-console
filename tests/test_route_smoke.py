# -*- coding: utf-8 -*-
"""全路由健康冒烟:按 url_map 实际规则逐方法打(空 body),500/HTML 即 FAIL。"""
import sys
sys.path.insert(0, '.')
from src.server import app

c = app.test_client()
rules = []
for r in app.url_map.iter_rules():
    p = str(r)
    if 'harness' not in p or p == '/api/harness/':
        continue
    ms = sorted(r.methods - {'HEAD', 'OPTIONS'})
    rules.append((p.replace('/api/harness', '') or '/', ms))

# v3.2.17（用户实锤「多出了一大堆的新会话」）：POST /connect 空 body 会在
# 共享元数据（~/.serialconsole_pro/claude_harness.json）里真建一条空「新会
# 话」——每跑一轮冒烟就往用户会话列表塞一条垃圾。带状态副作用的入口改打
# 安全形态：/connect 只 GET 探测存在性（405 也算健康，不是 500/HTML）
SKIP_POST = {'/connect'}

bad = []
n = 0
for path, ms in rules:
    for m in ms:
        if m == 'POST' and path in SKIP_POST:
            continue
        n += 1
        fn = c.post if m == 'POST' else (c.delete if m == 'DELETE' else c.get)
        r = fn('/api/harness' + path, json={} if m == 'POST' else None)
        ct = r.content_type or ''
        if r.status_code >= 500 or 'html' in ct:
            bad.append((m, path, r.status_code, ct[:24]))
print('总路由:', len(rules), '总方法:', n)
print('BAD:', bad if bad else '无 — 全部健康(JSON/4xx)')
