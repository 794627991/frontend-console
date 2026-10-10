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
SKIP_POST = {'/connect',
             # v3.5.102（用户实锤「识图配置自己关闭」）：空 body 探测会让
             # harness_set_vision 落默认值 enabled=False 写进真实 config
             # （v3.5.101 起还会同步进真实方案快照，用户开启的配置被探测
             # 打回关闭态）。后端已加空 body 400 防御，此处一并改打安全形
             # 态——GET 探测存在性即可。
             '/vision'}

# v3.5.109（designer 方案 §2.4 SAFE_POST）：写端点「合法形态」探测——空 body
# 永远到不了参数层（sid→404 前置），order 被 400 拦死 3 年的那类参数层断裂
# 对空 body 探测结构性不可见，只有真实形态才能探到。桩会话注入（不碰真实
# 注册表/meta），断言真实形态 200 且 j.ok，另钉 now/del 缺 id 仍 400。
import threading as _th
from src.harness.session import HarnessSession as _HS
from src.harness import routes as _hroutes


def _stub_session():
    s = _HS.__new__(_HS)          # 绕过 __init__：不起进程不碰真实注册表
    s._inbox = []
    s._inbox_lock = _th.Lock()
    s._gen = 0
    s._closed = False
    s._pump_timer = None
    s.busy = False
    s.sid = 'smoke'
    s.hidden = False
    s.emit = lambda ev: None
    s.sync_meta = lambda: None
    return s


SAFE_POST = {'/queue_act': ({"sid": "smoke", "act": "order", "ids": []}, 200)}

bad = []
n = 0
for path, ms in rules:
    for m in ms:
        if m == 'POST' and path in SKIP_POST:
            continue
        if m == 'POST' and path in SAFE_POST:
            body, want = SAFE_POST[path]
            n += 1
            stub = _stub_session()
            _orig = _hroutes._get_or_create
            _hroutes._get_or_create = lambda sid, _s=stub: _s
            try:
                r = c.post('/api/harness' + path, json=body)
            finally:
                _hroutes._get_or_create = _orig
            ct = r.content_type or ''
            j = {}
            try:
                j = r.get_json() or {}
            except Exception:
                pass
            if r.status_code != want or not j.get('ok') or 'html' in ct:
                bad.append(('POST*', path, r.status_code, ct[:24]))
            if path == '/queue_act':
                # 防矫枉过正：now/del 缺 id 的 400 校验仍在（v3.5.106 口径）
                n += 1
                _hroutes._get_or_create = lambda sid, _s=stub: _s
                try:
                    r2 = c.post('/api/harness' + path, json={"sid": "smoke", "act": "now"})
                finally:
                    _hroutes._get_or_create = _orig
                if r2.status_code != 400:
                    bad.append(('POST*', path + '#now-noid', r2.status_code, ''))
            continue
        n += 1
        fn = c.post if m == 'POST' else (c.delete if m == 'DELETE' else c.get)
        r = fn('/api/harness' + path, json={} if m == 'POST' else None)
        ct = r.content_type or ''
        if r.status_code >= 500 or 'html' in ct:
            bad.append((m, path, r.status_code, ct[:24]))
print('总路由:', len(rules), '总方法:', n)
print('BAD:', bad if bad else '无 — 全部健康(JSON/4xx)')
