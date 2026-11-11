# -*- coding: utf-8 -*-
"""全路由健康冒烟:按 url_map 实际规则逐方法打(空 body),500/HTML 即 FAIL。"""
import sys
sys.path.insert(0, '.')
from src.server import app as _main_app


def _harness_rule_count(a):
    return sum(1 for r in a.url_map.iter_rules()
               if 'harness' in str(r) and str(r) != '/api/harness/')


# a46x（审计实锤：全量 pytest 直接 INTERNALERROR）——默认 offload 形态下
# harness 路由已迁到 worker 进程，主进程只剩 /<path:sub> 落点。原实现拿主
# 进程 app 跑，rules<=2 时走 sys.exit(1)，而 sys.exit 在 pytest 收集阶段
# 是 INTERNALERROR，**整个测试套件一条都跑不起来**（不是「冒烟失败」，是
# 全量归零）。改成：offload 形态自动换 worker_app.build_app() 跑同一份
# 规则表——两边注册的是同一批蓝图，覆盖面等价。
app = _main_app
if _harness_rule_count(_main_app) <= 2:
    from src.worker_app import build_app as _build_worker_app
    app = _build_worker_app()

# a116 二十三次全审：v4 流的 wseq 高水位与 BOOT 计数器会**真写 HOME**
# （`_save_wseq` 同步落盘 + `_next_boot` 落盘）。本冒烟会真打 `/v4/stream`
# 与写端点，实测跑一轮就在用户 `~/.serialconsole_pro/v4wseq` 留下 BOOT。
# 与 test_v4feed 的 `_use_temp_wseq_dir()` 同理，这里在**任何请求前**重定向。
import os as _os
import tempfile as _tempfile
_TMP_WSEQ = _tempfile.mkdtemp(prefix="wseq_smoke_")
import src.eventlog.store as _S
from src.harness import v4feed as _F
_S._WSEQ_DIR = _TMP_WSEQ
# a452（第二轮审计 P1）：冒烟改用 worker_app 后路由数从 2 变 42，写盘端点
# 真正打到——harness 元数据文件的路径也要重定向，否则任何漏网的写端点
# （历史上 /delete 就不校验空 sid，直接 _meta_save 原子重写真实文件）会把
# 用户的 ~/.serialconsole_pro/claude_harness.json 改掉。与上面的 wseq 同理。
import src.harness.meta as _M
_M._META_FILE = _os.path.join(_TMP_WSEQ, "claude_harness.json")
_F.V4Feed._boot_path = staticmethod(
    lambda: _os.path.join(_TMP_WSEQ, "BOOT"))
_F.V4Feed._boot = None

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
             '/vision',
             # a452（第二轮审计 P1）：/delete 空 body 会真写
             # ~/.serialconsole_pro/claude_harness.json——routes.py 对空 sid
             # 不校验，直接 _meta_load → _meta.pop("") → _meta_save()（原子
             # 重写真实文件）。冒烟改用 worker_app 后路由数从 2 变 42，这条
             # 副作用首次暴露。实测单跑一轮就把文件的 mtime 改掉。
             '/delete'}

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
# P1-6 修复（a116）：原脚本只 print 不置退出码——offload 形态下 10 条 BAD
# 仍 EXIT=0，CI/人工都误判绿。另外 offload 形态（默认 CLAUDE_OFFLOAD=True）
# 下主进程只剩 /<path:sub> 落点，46 条 harness 路由的冒烟覆盖被静默清零
# （实测 总路由=2 vs inline 46）——此情形必须显式失败而不是假装通过。
if len(rules) <= 2:
    print('FAIL: 主进程与 worker_app 两处都只拿到 %d 条 harness 路由'
          '——蓝图注册已断，冒烟覆盖为零' % len(rules))
    sys.exit(1)
if bad:
    sys.exit(1)
