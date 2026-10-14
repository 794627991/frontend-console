# 切换压力测试矩阵：白屏/头/秒表/内容串台/长任务 全指标
import sys, json, time
sys.path.insert(0, '.')
sys.path.insert(0, 'src')
from src.devtools_cdp import find_cdp, find_page_target, CdpSession

port = find_cdp()
info = json.load(open(r'C:\Users\gaoyi13\.serialconsole_pro\endpoint.json', encoding='utf-8'))
origin = 'http://127.0.0.1:%s' % info.get('port', '')
tid = find_page_target(port, origin)['id']

# 探针：50ms 采样 flow（节点数/首行指纹/活组头）+ longtask
SETUP = """(function(){
  window.__stLog = [];
  window.__stLt = [];
  setInterval(function(){
    try {
      var flow = document.querySelector('[data-hg-flow]');
      if (!flow) return;
      var act = document.querySelector('.hg-item.active .hg-item-title');
      var u = flow.querySelector('.h-msg.user');
      var live=[].slice.call(flow.querySelectorAll('.h-grp:not([data-finalized])')).pop();
      var h = live ? live.querySelector('.h-turn-head') : null;
      window.__stLog.push({t: Date.now(),
        act: act ? act.textContent.trim().slice(0,6) : '?',
        n: flow.getElementsByTagName('*').length,
        first: u ? u.textContent.replace(/\\s+/g,'').slice(0,8) : '',
        headOk: live ? (!!h && h.style.display !== 'none') : null,
        lbl: h ? ((h.querySelector('.h-turn-label')||{textContent:''}).textContent.trim().slice(0,16)) : ''});
      if (window.__stLog.length > 600) window.__stLog.shift();
    } catch(_){}
  }, 50);
  try { new PerformanceObserver(function(l){
    l.getEntries().forEach(function(e){ window.__stLt.push({t:Math.round(e.startTime),d:Math.round(e.duration)}); });
  }).observe({entryTypes:['longtask']}); } catch(_){}
  return 'stress-probe-on';
})()"""

CLICK = """(function(){var rows=document.querySelectorAll('.hg-item[data-sid]');
for(var i=0;i<rows.length;i++){if(rows[i].dataset.sid==='%s'){rows[i].click();return 1;}}return 0;})()"""

LIST = """JSON.stringify((function(){var rows=document.querySelectorAll('.hg-item[data-sid]');var a=[];
for(var i=0;i<rows.length;i++)a.push({sid:rows[i].dataset.sid,
  t:(rows[i].querySelector('.hg-item-title')||{textContent:''}).textContent.slice(0,6),
  busy:!!rows[i].querySelector('.hg-item-busy')});
return a;})())"""

DUMP = """JSON.stringify({
  logN: (window.__stLog||[]).length,
  blanks: (window.__stLog||[]).filter(function(e){return e.n < 50;}).length,
  ltN: (window.__stLt||[]).length,
  ltMax: (window.__stLt||[]).reduce(function(m,e){return Math.max(m,e.d);},0),
  ltRecent: (window.__stLt||[]).slice(-8),
  tail: (window.__stLog||[]).slice(-30)
})"""


def run():
    with CdpSession(port, tid, timeout=30) as cs:
        cs.send('Runtime.evaluate', {'expression': SETUP, 'returnByValue': True})
        res = cs.send('Runtime.evaluate', {'expression': LIST, 'returnByValue': True})
        sess = json.loads(res['result']['value'])
        print('会话:', [(x['t'] + ('*' if x['busy'] else '')) for x in sess])
        if len(sess) < 2:
            print('会话不足'); return
        b = next((x for x in sess if x['busy']), sess[0])
        others = [x for x in sess if x['sid'] != b['sid']]

        # 场景1：busy↔idle 快切 8 轮（0.5s 间隔——比渲染稳定更快，制造竞态）
        print('--- 场景1: busy↔idle 0.5s 快切 ×8 ---')
        for i in range(8):
            for x in (others[0], b):
                cs.send('Runtime.evaluate', {'expression': CLICK % x['sid'], 'returnByValue': True})
                time.sleep(0.5)
        # 场景2：三会话轮转 4 轮（0.8s）
        print('--- 场景2: 三会话轮转 0.8s ×4 ---')
        if len(others) >= 2:
            for i in range(4):
                for x in (others[0], others[1], b):
                    cs.send('Runtime.evaluate', {'expression': CLICK % x['sid'], 'returnByValue': True})
                    time.sleep(0.8)
        # 场景3：极快连击（0.25s ×6，纯竞态压力）
        print('--- 场景3: 极快连击 0.25s ×12 ---')
        for i in range(12):
            x = (others[0], b)[i % 2]
            cs.send('Runtime.evaluate', {'expression': CLICK % x['sid'], 'returnByValue': True})
            time.sleep(0.25)
        time.sleep(2.5)
        # 回到 busy 会话收尾
        cs.send('Runtime.evaluate', {'expression': CLICK % b['sid'], 'returnByValue': True})
        time.sleep(2)
        r = cs.send('Runtime.evaluate', {'expression': DUMP, 'returnByValue': True})
        return json.loads(r['result']['value']), b, others


d, b, others = run()
print()
print('====== 压测结果 ======')
print('白屏采样点: %d / %d' % (d['blanks'], d['logN']))
print('长任务: %d 个, 最大 %dms' % (d['ltN'], d['ltMax']))
print('最近长任务:', d['ltRecent'])
# 头检查：切回 busy 会话后的头状态序列
tail = [e for e in d['tail'] if isinstance(e, dict)]
t_prev = None
bad_head = 0
for e in tail:
    if e.get('act') == b['t'][:6] and e.get('headOk') is False:
        bad_head += 1
print('尾窗 busy 会话头异常采样: %d / %d' % (bad_head, len([e for e in tail if e.get('act')==b['t'][:6]])))
for e in tail[-12:]:
    print('  %d act=%-6s n=%-5s headOk=%-5s %s' % (e['t'] % 100000, e['act'], e['n'],
          e.get('headOk'), e.get('lbl', '')))
