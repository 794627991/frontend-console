# busy 态切回综合验证（v3.5.191+ 新代码）：Profiler 剖面 + 就绪时序 + DOM 终态 + 秒表时间线
import sys, json, time
sys.path.insert(0, '.')
sys.path.insert(0, 'src')
from src.devtools_cdp import find_cdp, find_page_target, CdpSession

port = find_cdp()
info = json.load(open(r'C:\Users\gaoyi13\.serialconsole_pro\endpoint.json', encoding='utf-8'))
origin = 'http://127.0.0.1:%s' % info.get('port', '')
tid = find_page_target(port, origin)['id']

PROBE_BUSY = """JSON.stringify((function(){
  var rows=document.querySelectorAll('.hg-item[data-sid]');
  var b=null,o=null,bt='';
  for(var i=0;i<rows.length;i++){
    if(rows[i].querySelector('.hg-item-busy')){
      if(!b){b=rows[i].dataset.sid;bt=(rows[i].querySelector('.hg-item-title')||{}).textContent||'';}
    } else if(!o){o=rows[i].dataset.sid;}
  }
  return {b:b,o:o,bt:bt};
})())"""

SW_AWAY = """(function(){var rows=document.querySelectorAll('.hg-item[data-sid]');
var cur=null,other=null;
for(var i=0;i<rows.length;i++){
  if(rows[i].classList.contains('active'))cur=rows[i];
  else if(!other)other=rows[i];
}
if(!cur||!other)return 'bad';
window.__swOrig=cur.dataset.sid;other.click();return 'away';})()"""

SW_BACK = """(function(){var rows=document.querySelectorAll('.hg-item[data-sid]');
var o=window.__swOrig;
for(var i=0;i<rows.length;i++){if(rows[i].dataset.sid===o){rows[i].click();return 'back';}}
return 'gone';})()"""

with CdpSession(port, tid, timeout=30) as cs:
    res = cs.send('Runtime.evaluate', {'expression': PROBE_BUSY, 'returnByValue': True})
    d = json.loads(res['result']['value'])
    print('busy 会话:', d['bt'] or '无！')
    if not d['b']:
        sys.exit(0)
    # longtask 观察器
    cs.send('Runtime.evaluate', {'expression':
        "(function(){window.__lt=[];try{new PerformanceObserver(function(l){l.getEntries().forEach(function(e){window.__lt.push({t:Math.round(e.startTime),d:Math.round(e.duration)});});}).observe({entryTypes:['longtask']});}catch(_){}})()",
        'returnByValue': True})
    cs.send('Profiler.enable')
    cs.send('Profiler.setSamplingInterval', {'interval': 100})
    cs.send('Profiler.start')
    # 切走
    r1 = cs.send('Runtime.evaluate', {'expression': SW_AWAY, 'returnByValue': True})
    print(r1['result'].get('value'))
    time.sleep(2.5)
    # longtask 清零（只记切回后的）
    cs.send('Runtime.evaluate', {'expression': 'window.__lt=[]', 'returnByValue': True})
    # 切回 + 就绪时序采样
    r2 = cs.send('Runtime.evaluate', {'expression': SW_BACK, 'returnByValue': True})
    print(r2['result'].get('value'))
    t0 = time.time()
    first_ready = None
    for i in range(25):
        time.sleep(0.2)
        res = cs.send('Runtime.evaluate', {'expression':
            '''JSON.stringify((function(){
  var flow=document.querySelector('[data-hg-flow]');
  var hEnd=0;
  flow.querySelectorAll('[data-h-end]').forEach(function(el){hEnd=Math.max(hEnd,+(el.dataset.hEnd||0));});
  return {t: Math.round(performance.now()),
          hEnd:hEnd, grps:flow.querySelectorAll('.h-grp').length,
          nodes:flow.getElementsByTagName('*').length};
})())''', 'returnByValue': True})
        d2 = json.loads(res['result']['value'])
        if i % 3 == 0 or i < 5:
            print('%5dms  hEnd=%s grps=%s nodes=%s' % (d2['t'], d2['hEnd'], d2['grps'], d2['nodes']))
    time.sleep(1)
    res = cs.send('Profiler.stop', timeout=60)
    res2 = cs.send('Runtime.evaluate', {'expression':
        '''JSON.stringify({lt: (window.__lt||[]).slice(-8),
  ltTotal: (window.__lt||[]).reduce(function(a,e){return a+e.d;},0),
  head: (function(){var g=document.querySelectorAll('.h-grp');var l=g[g.length-1];
    var h=l?(l.querySelector('.h-turn-head .h-turn-label')||l.querySelector('[class*=turn-label]')):null;
    return h?h.textContent.trim().slice(0,24):null;})(),
  railTicks: (function(){var r=document.querySelector('.hg-rail');return r?r.querySelectorAll('.hg-rail-t').length:0;})(),
  arch: (function(){var h=document.querySelector('[data-hg-flow] .h-archive-hint');return h?h.textContent.trim():null;})()})''',
        'returnByValue': True})
    d3 = json.loads(res2['result']['value'])
    print('切回后长任务:', d3['lt'], '| 冻结总计 %dms' % d3['ltTotal'])
    print('当前回合头:', d3['head'])
    print('轨刻度数:', d3['railTicks'], '| 归档条:', d3['arch'])
