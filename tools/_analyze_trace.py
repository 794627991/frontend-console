# 深挖两个长任务窗口：窗口内事件聚合 + 网络资源 + Profile 格式探测
import gzip, json, sys, collections

path = r"C:\Users\gaoyi13\.serialconsole_pro\harness_uploads\e13c8db2_Trace-20261013T142132.json.gz"
with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
    data = json.load(f)
ev = data.get("traceEvents") or []

wins = [(104399784866, 104399784866 + 1490300, "任务A"),
        (104403014889, 104403014889 + 1570500, "任务B")]

for w0, w1, tag in wins:
    agg = collections.Counter()
    dur_agg = collections.Counter()
    for e in ev:
        ts, d = e.get("ts", 0), e.get("dur", 0)
        if ts < w0 or ts > w1:
            continue
        name = e.get("name", "")
        cat = e.get("cat", "")
        if cat in ("disabled-by-default-devtools.timeline", "devtools.timeline"):
            agg[name] += 1
            dur_agg[name] += d
    print("== %s 窗口事件（%s ~ %s）==" % (tag, w0, w1))
    for name, n in agg.most_common(18):
        print("  %4d x  self=%8.1fms  %s" % (n, dur_agg[name] / 1000, name))
    print()

# 网络资源：transcript 拉取
print("== 网络资源 top（transferred/receive）==")
res = []
for e in ev:
    if e.get("name") in ("ResourceSendRequest", "ResourceFinish", "ResourceReceiveResponse"):
        a = (e.get("args") or {}).get("data", {})
        res.append((e.get("name"), e.get("ts", 0), a))
by_req = collections.defaultdict(dict)
for name, ts, a in res:
    rid = a.get("requestId", "?")
    by_req[rid][name] = (ts, a)
rows = []
for rid, m in by_req.items():
    if "ResourceFinish" in m:
        ts0, a0 = m.get("ResourceSendRequest", (0, {}))
        ts1, a1 = m["ResourceFinish"]
        rows.append((ts1 - ts0, a1.get("decodedBodyLength", 0),
                     a0.get("url", "")[:90]))
rows.sort(reverse=True)
for dur, size, url in rows[:8]:
    print("  %8.1fms  %9.1f KB  %s" % (dur / 1000, size / 1024, url))

# Profile 事件样例（格式探测）
for e in ev:
    if "Profile" in e.get("name", ""):
        a = e.get("args", {})
        print("\nProfile 事件样例:", e.get("name"), "keys:", list((a.get("data") or {}).keys())[:8])
        break
