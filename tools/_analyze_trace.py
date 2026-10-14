# 通用 trace 分析器 v2：吃命令行参数；自动找长任务窗口；不硬编码
import gzip, json, sys, collections

path = sys.argv[1]
raw = gzip.open(path, 'rb').read()
data = json.loads(raw.decode('utf-8', 'replace'))
ev = data.get('traceEvents') or []
print('事件总数:', len(ev))

ts_all = sorted(e.get('ts', 0) for e in ev if e.get('ts'))
if not ts_all:
    print('无时间戳事件'); sys.exit(0)
T0, T1 = ts_all[0], ts_all[-1]
print('录制时长: %.1fs（%d ~ %d）' % ((T1 - T0) / 1e6, T0, T1))

# 1) 全程 RunTask 长任务分布（>100ms）
tasks = sorted((e for e in ev if e.get('name') == 'RunTask' and e.get('ph') == 'X'
                and e.get('dur', 0) > 100000), key=lambda x: x['ts'])
print('=== RunTask>100ms 共 %d 个 ===' % len(tasks))
for t in tasks[:25]:
    print('  +%.1fs  %.0fms' % ((t['ts'] - T0) / 1e6, t['dur'] / 1000))

# 2) 自动深挖最大的 3 个窗口（各 ±50ms）事件聚合
def top_windows(n=3):
    wins = []
    for t in tasks:
        c = t['ts']; w0, w1 = c - 50000, c + t['dur'] + 50000
        agg = collections.Counter(); dur = collections.Counter()
        for e in ev:
            ts = e.get('ts', 0)
            if ts < w0 or ts > w1: continue
            if e.get('cat', '') in ('disabled-by-default-devtools.timeline', 'devtools.timeline'):
                agg[e['name']] += 1
                dur[e['name']] += e.get('dur', 0)
        wins.append((t['dur'], (t['ts'] - T0) / 1e6, agg, dur))
    return sorted(wins, key=lambda x: -x[0])[:n]

for wd, at, agg, dur in top_windows():
    print('=== 窗口 @+%.1fs（核心长任务 %.0fms）===' % (at, wd / 1000))
    for name, n in agg.most_common(12):
        print('  %5d x  self=%8.1fms  %s' % (n, dur[name] / 1000, name))
    print()

# 3) 网络：慢请求 top
res = []
for e in ev:
    if e.get('name') in ('ResourceSendRequest', 'ResourceFinish', 'ResourceReceiveResponse'):
        a = (e.get('args') or {}).get('data', {})
        res.append((e.get('name'), e.get('ts', 0), a))
by_req = collections.defaultdict(dict)
for name, ts, a in res:
    rid = a.get('requestId', a.get('id', '?'))
    by_req[rid][name] = (ts, a)
rows = []
for rid, m in by_req.items():
    if 'ResourceFinish' in m and 'ResourceSendRequest' in m:
        ts0, a0 = m['ResourceSendRequest']
        ts1, a1 = m['ResourceFinish']
        rows.append((ts1 - ts0, a1.get('encodedDataLength', a1.get('decodedBodyLength', 0)),
                     a0.get('url', '?')[:80]))
rows.sort(reverse=True)
print('=== 最慢请求 top8 ===')
for d, sz, u in rows[:8]:
    print('  %8.1fms  %7.1fKB  %s' % (d / 1000, sz / 1024, u))

# 4) 大响应（流量）
big = sorted(rows, key=lambda x: -x[1])[:5]
print('=== 最大响应 top5 ===')
for d, sz, u in big:
    print('  %7.1fKB  %.1fs  %s' % (sz / 1024, d / 1e6, u))
