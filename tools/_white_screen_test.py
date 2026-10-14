# 白屏专项测试：快速连续切换会话，100ms 粒度采样 flow 空白段
import sys, json, time
sys.path.insert(0, '.')
sys.path.insert(0, 'src')
from src.devtools_cdp import find_cdp, find_page_target, CdpSession

port = find_cdp()
info = json.load(open(r'C:\Users\gaoyi13\.serialconsole_pro\endpoint.json', encoding='utf-8'))
origin = 'http://127.0.0.1:%s' % info.get('port', '')
tid = find_page_target(port, origin)['id']

SAMPLER = """(function(){
  if (window.__wsProbe) return 'alive';
  window.__wsLog = [];
  window.__wsProbe = setInterval(function(){
    try {
      var flow = document.querySelector('[data-hg-flow]');
      if (!flow) return;
      var n = flow.getElementsByTagName('*').length;
      var act = document.querySelector('.hg-item.active .hg-item-title');
      var L = window.__wsLog;
      var prev = L.length ? L[L.length-1] : null;
      var blank = n < 50;
      // 只记状态变化点+空白段全程（降日志量）
      if (blank || !prev || prev.blank !== blank || L[L.length-1].t < Date.now()-1000)
        L.push({t: Date.now(), n: n, act: act?act.textContent.trim().slice(0,14):'?', blank: blank});
      if (L.length > 300) L.shift();
    } catch(_){}
  }, 100);
  return 'ws-probe-on';
})()"""

CLICK_SID = """(function(){var rows=document.querySelectorAll('.hg-item[data-sid]');
for(var i=0;i<rows.length;i++){if(rows[i].dataset.sid==='%s'){rows[i].click();return 'ok';}}
return 'gone';})()"""

LIST = """JSON.stringify((function(){var rows=document.querySelectorAll('.hg-item[data-sid]');var a=[];
for(var i=0;i<rows.length;i++)a.push({sid:rows[i].dataset.sid,t:(rows[i].querySelector('.hg-item-title')||{}).textContent||'',busy:!!rows[i].querySelector('.hg-item-busy')});
return a;})())"""

with CdpSession(port, tid, timeout=30) as cs:
    res = cs.send('Runtime.evaluate', {'expression': LIST, 'returnByValue': True})
    sess = json.loads(res['result']['value'])
    print('会话数:', len(sess))
    for x in sess[:4]:
        print('  -', x['t'][:14], 'busy' if x['busy'] else '', x['sid'][-6:])
    if len(sess) < 2:
        sys.exit(0)
    busy = next((x for x in sess if x['busy']), sess[0])
    others = [x for x in sess if x['sid'] != busy['sid']]
    target = others[0] if others else sess[1]

    cs.send('Runtime.evaluate', {'expression': SAMPLER, 'returnByValue': True})
    time.sleep(0.5)

    # 快速来回切 3 轮（间隔 1s，模拟用户快速切换）
    for rnd in range(3):
        for sid in (target['sid'], busy['sid']):
            r = cs.send('Runtime.evaluate', {'expression': CLICK_SID % sid,
                                             'returnByValue': True})
            time.sleep(1.0)
    print('切换完成（3 轮×2 次点击，间隔 1s），等 2s 收尾…')
    time.sleep(2)
    r2 = cs.send('Runtime.evaluate', {'expression':
        "JSON.stringify({probe:!!window.__wsProbe,log:(window.__wsLog||[]).slice(-40)})",
        'returnByValue': True})
    if 'exceptionDetails' in r2:
        print('异常:', r2['exceptionDetails']['exception']['description'][:150])
        sys.exit(1)
    log = json.loads(r2['result']['value'])
    print('=== 状态变化时间线（n=节点数，blank=白屏）===')
    t_prev = None
    blank_total = 0
    blank_start = None
    for e in log:
        dt = ('+%ds' % ((e['t'] - t_prev) / 1000)) if t_prev else '0s'
        t_prev = e['t']
        print('  %s  act=%-14s n=%-6d %s' % (dt, e['act'], e['n'],
                                             '*** 白屏 ***' if e['blank'] else ''))
PYEOF