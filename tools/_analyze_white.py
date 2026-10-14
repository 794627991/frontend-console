# 白屏分析：新 trace 的 transcript 拉取、长任务、清场-换入时序
import gzip, json, sys

raw = gzip.open(r'C:\Users\gaoyi13\.serialconsole_pro\harness_uploads\fa175fee_2.json.gz', 'rb').read()
d = json.loads(raw.decode('utf-8', 'replace'))
ev = d.get('traceEvents', [])

# 1) 全量大响应（transcript 类）
fin = []
for e in ev:
    if e.get('name') == 'ResourceFinish':
        dd = e.get('args', {}).get('data', {}) if isinstance(e.get('args'), dict) else {}
        kb = (dd.get('encodedDataLength', 0) or 0) / 1024
        if kb > 200:
            fin.append((e.get('ts', 0), kb))
fin.sort()
t0 = fin[0][0] if fin else 0
print('=== 大响应（>200KB）===')
for ts, kb in fin:
    print('  +%.0fms  %.0fKB' % ((ts - t0) / 1000, kb))

# 2) 长任务
tasks = sorted([e for e in ev if e.get('name') == 'RunTask'
                and e.get('ph') == 'X' and e.get('dur', 0) > 100000],
               key=lambda x: x['ts'])
print('=== RunTask>100ms 共 %d ===' % len(tasks))
for t in tasks[:20]:
    print('  +%.0fms  %.0fms' % ((t['ts'] - t0) / 1000, t['dur'] / 1000))

# 3) layout/updateLayoutTree（渲染期）
layouts = sorted([e for e in ev if e.get('name') in ('Layout', 'UpdateLayoutTree')
                  and e.get('ph') == 'X' and e.get('dur', 0) > 30000],
                 key=lambda x: x['ts'])
print('=== Layout>30ms 共 %d ===' % len(layouts))
for t in layouts[:12]:
    print('  +%.0fms  %.0fms %s' % ((t['ts'] - t0) / 1000, t['dur'] / 1000, t['name']))

# 4) 主线程关键脚本函数（FunctionCall 大块）
fc = sorted([e for e in ev if e.get('name') == 'FunctionCall'
             and e.get('ph') == 'X' and e.get('dur', 0) > 80000],
            key=lambda x: x['ts'])
print('=== FunctionCall>80ms 共 %d ===' % len(fc))
for t in fc[:15]:
    dd = t.get('args', {}).get('data', {})
    print('  +%.0fms  %.0fms  %s' % ((t['ts'] - t0) / 1000, t['dur'] / 1000,
                                     str(dd.get('functionName', ''))[:50]))
