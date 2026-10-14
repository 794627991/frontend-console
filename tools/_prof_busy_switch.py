# DevTools 剖面：busy 大会话切走→切回，Profiler 同连接全流程 + 稳健分析
import sys, json, time
sys.path.insert(0, '.')
sys.path.insert(0, 'src')
from src.devtools_cdp import find_cdp, find_page_target, CdpSession

port = find_cdp()
info = json.load(open(r'C:\Users\gaoyi13\.serialconsole_pro\endpoint.json', encoding='utf-8'))
origin = 'http://127.0.0.1:%s' % info.get('port', '')
tid = find_page_target(port, origin)['id']

OUT = r'D:\AI\串口控制台Pro\tools\_prof_snapshot.json'

with CdpSession(port, tid, timeout=30) as cs:
    cs.send('Profiler.enable')
    cs.send('Profiler.setSamplingInterval', {'interval': 100})
    cs.send('Profiler.start')
    r1 = cs.send('Runtime.evaluate', {'expression':
        "(function(){var rows=document.querySelectorAll('.hg-item[data-sid]');"
        "var cur=null,other=null;"
        "for(var i=0;i<rows.length;i++){if(rows[i].classList.contains('active'))cur=rows[i];else if(!other)other=rows[i];}"
        "if(!cur||!other)return 'bad-state';"
        "window.__swOrig=cur.dataset.sid;other.click();"
        "return 'away-from-'+window.__swOrig.slice(-6);})()",
        "returnByValue": True})
    print(r1)
    time.sleep(2.5)
    r2 = cs.send('Runtime.evaluate', {'expression':
        "(function(){var t=document.querySelector('.hg-item[data-sid="'+window.__swOrig+'"]');"
        "if(!t)return 'orig-gone';t.click();return 'back-to-'+window.__swOrig.slice(-6);})()",
        "returnByValue": True})
    print(r2)
    time.sleep(6)
    res = cs.send('Profiler.stop', timeout=60)

prof = (res or {}).get('profile', {})
with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(prof, f)
print('profile 已存盘:', OUT)

nodes_raw = prof.get('nodes', [])
nodes = {}
for n in nodes_raw:
    if isinstance(n, dict):
        nodes[n.get('id')] = n
    elif isinstance(n, list) and len(n) > 1:
        nodes[n[0]] = n[1]
agg = {}
for s in prof.get('samples', []):
    if isinstance(s, dict):
        sid_ = s.get('nodeId')
    else:
        sid_ = s
    n = nodes.get(sid_)
    if not n:
        continue
    cf = n.get('callFrame', n) if isinstance(n, dict) else {}
    key = '%s @%s' % (cf.get('functionName') or '(anon)',
                      (cf.get('url') or '').split('/')[-1][:20])
    agg[key] = agg.get(key, 0) + 1
total = sum(agg.values()) or 1
print('采样:', total, '≈%.1fs' % (total * 0.0001))
for k, v in sorted(agg.items(), key=lambda x: -x[1])[:24]:
    print('%7.1fms  %s' % (v * 0.1, k))
