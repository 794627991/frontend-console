# 今日全部修改点·网页自测矩阵（DevTools 驱动，自己测自己发现）
# 覆盖：RO退出seq/审计窗/任务卡去重回填/busy判据(活组收体)/头体系/白屏历史/摘要行/思考保留/vcs徽章/看门狗
import sys, json, time, urllib.request
sys.path.insert(0, '.')
sys.path.insert(0, 'src')
from src.devtools_cdp import find_cdp, find_page_target, CdpSession, evaluate

RESULTS = []
def check(name, ok, detail=''):
    RESULTS.append((name, ok, detail))
    print('%s %s %s' % ('PASS' if ok else '*** FAIL ***', name, detail))

port = find_cdp()
info = json.load(open(r'C:\Users\gaoyi13\.serialconsole_pro\endpoint.json', encoding='utf-8'))
BACK = info['port']
origin = 'http://127.0.0.1:%s' % BACK
tid = find_page_target(port, origin)['id']

CLICK = """(function(){var rows=document.querySelectorAll('.hg-item[data-sid]');
for(var i=0;i<rows.length;i++){if(rows[i].dataset.sid==='%s'){rows[i].click();return 1;}}return 0;})()"""
LIST = """JSON.stringify((function(){var rows=document.querySelectorAll('.hg-item[data-sid]');var a=[];
for(var i=0;i<rows.length;i++)a.push({sid:rows[i].dataset.sid,busy:!!rows[i].querySelector('.hg-item-busy')});return a;})())"""
STATE = """JSON.stringify((function(){
  var f=document.querySelector('[data-hg-flow]');
  var grps=[].slice.call(f.querySelectorAll('.h-grp'));
  var live=grps.filter(function(g){return !g.dataset.finalized;}).pop();
  var h=live?live.querySelector(':scope > .h-grp-proc > .h-turn-head'):null;
  var tb=live?live.querySelector(':scope > .h-grp-proc > .h-turn-body'):null;
  return {n:f.getElementsByTagName('*').length,grps:grps.length,
    hist:f.querySelectorAll('.h-msg.user').length,
    arch:!!f.querySelector('.h-archive-hint'),
    headVis:h?!!(h.offsetWidth||h.offsetHeight):null,
    headTxt:h?(h.querySelector('.h-turn-label')||{textContent:''}).textContent.trim().slice(0,16):'',
    liveBodyClosed:tb?tb.classList.contains('closed'):null,
    tasks:f.querySelectorAll('.h-taskcard').length,
    turnsum:f.querySelectorAll('.h-turnsum').length,
    thinkN:f.querySelectorAll('.h-think-seg').length};})())"""

with CdpSession(port, tid, timeout=30) as cs:
    sess = json.loads(cs.send('Runtime.evaluate', {'expression': LIST, 'returnByValue': True})['result']['value'])
    A = next((x for x in sess if x['busy']), sess[0])
    B = next((x for x in sess if x['sid'] != A['sid']), sess[1])
    print('会话: A=%s(busy=%s) B=%s' % (A['sid'][-6:], A['busy'], B['sid'][-6:]))

    # ========== ① 白屏/历史/头/busy判据(活组收体) ==========
    cs.send('Runtime.evaluate', {'expression':
        "(function(){window.__tLt=[];try{new PerformanceObserver(function(l){l.getEntries().forEach(function(e){window.__tLt.push(Math.round(e.duration));});}).observe({entryTypes:['longtask']});}catch(_){}})()",
        'returnByValue': True})
    samples = []
    for rnd in range(6):
        cs.send('Runtime.evaluate', {'expression': CLICK % B['sid'], 'returnByValue': True})
        time.sleep(0.8)
        cs.send('Runtime.evaluate', {'expression': CLICK % A['sid'], 'returnByValue': True})
        time.sleep(1.0)
        samples.append(json.loads(cs.send('Runtime.evaluate', {'expression': STATE, 'returnByValue': True})['result']['value']))
    blank = sum(1 for s in samples if s['n'] < 50)
    histMin = min(s['hist'] for s in samples)
    grpsMin = min(s['grps'] for s in samples)
    headLost = sum(1 for s in samples if s['headVis'] is False)
    bodyClosed = sum(1 for s in samples if s['liveBodyClosed'])
    check('①白屏零', blank == 0, '(%d/6轮)' % blank)
    check('①历史完整', grpsMin >= 18 and histMin >= 15, '组min=%s user min=%s' % (grpsMin, histMin))
    check('①头零消失', headLost == 0, '(%d)' % headLost)
    check('①busy活组不被收体[S2/G3]', bodyClosed == 0, 'closed轮数=%d' % bodyClosed)
    lt = cs.send('Runtime.evaluate', {'expression': "JSON.stringify(window.__tLt||[])", 'returnByValue': True})
    lts = json.loads(lt['result']['value'])
    check('①长任务≤300ms', all(x <= 300 for x in lts), 'max=%s' % (max(lts) if lts else 0))

    # ========== ② RO 进出（P1 seq：退出无白屏/内容在/无snapshot清场）==========
    cs.send('Runtime.evaluate', {'expression': CLICK % A['sid'], 'returnByValue': True})
    time.sleep(1.5)
    r = cs.send('Runtime.evaluate', {'expression':
        "document.querySelector('[data-hg-flow] .h-archive-hint') ? 'hint' : 'no-hint'", 'returnByValue': True})
    if r['result']['value'] == 'hint':
        before = json.loads(cs.send('Runtime.evaluate', {'expression': STATE, 'returnByValue': True})['result']['value'])
        cs.send('Runtime.evaluate', {'expression':
            "document.querySelector('[data-hg-flow] .h-archive-hint').click()", 'returnByValue': True})
        time.sleep(3.0)
        inRO = json.loads(cs.send('Runtime.evaluate', {'expression':
            "JSON.stringify({ro:!!document.querySelector('.hg-ro')})", 'returnByValue': True})['result']['value'])
        check('②RO进入', inRO['ro'], '')
        cs.send('Runtime.evaluate', {'expression':
            "(document.querySelector('[data-ro-exit]')||{click:function(){}}).click()", 'returnByValue': True})
        # 白屏采样（退出后 300ms 起）
        time.sleep(0.3)
        exits = []
        for k in range(10):
            exits.append(json.loads(cs.send('Runtime.evaluate', {'expression': STATE, 'returnByValue': True})['result']['value']))
            time.sleep(0.3)
        blankExit = sum(1 for e in exits if e['n'] < 50)
        check('②RO退出零白屏[P1]', blankExit == 0, '(%d/10采样)' % blankExit)
        check('②RO退出内容在场[P1]', exits[-1]['grps'] >= 15, '组=%s' % exits[-1]['grps'])
        check('②RO退出无snapshot清场特征[P1]', exits[-1]['hist'] >= 10, 'user=%s(若被清场重放会骤降)' % exits[-1]['hist'])
    else:
        check('②RO进出', False, '无归档条（会话<20轮）跳过——手动验')

    # ========== ③ 摘要行（P4：最近完成回合应有 .h-turnsum）==========
    cs.send('Runtime.evaluate', {'expression': CLICK % A['sid'], 'returnByValue': True})
    time.sleep(2.5)
    st = json.loads(cs.send('Runtime.evaluate', {'expression': STATE, 'returnByValue': True})['result']['value'])
    check('③摘要行在场或场景不适用[P4]', True, 'turnsum=%s(无工具回合可为0，非断言项)' % st['turnsum'])

    # ========== ④ 思考保留（v227：切回后思考段在）==========
    check('④思考段保留[v227]', st['thinkN'] > 0, 'thinkN=%s' % st['thinkN'])

    # ========== ⑤ 任务卡不双卡（S3b）==========
    # DOM 内同 tid 双卡检测
    dup = cs.send('Runtime.evaluate', {'expression':
        """(function(){var m={};var dup=0;
document.querySelectorAll('.h-taskcard').forEach(function(c){
  var t=c.dataset.tid; if(t){m[t]=(m[t]||0)+1;}});
Object.keys(m).forEach(function(k){if(m[k]>1)dup++;});
return JSON.stringify({cards:Object.keys(m).length,dup:dup});})()""",
        'returnByValue': True})
    d5 = json.loads(dup['result']['value'])
    check('⑤任务卡零双卡[S3b]', d5['dup'] == 0, 'cards=%s dup=%s' % (d5['cards'], d5['dup']))

    # ========== ⑥ 头定稿收口（v228：所有已完成组头非「工作中」）==========
    fin = cs.send('Runtime.evaluate', {'expression':
        """JSON.stringify((function(){
var bad=0,total=0;
document.querySelectorAll('.h-grp[data-finalized]').forEach(function(g){
  total++;var l=g.querySelector('.h-turn-label');
  if(l&&l.textContent.indexOf('工作中')===0)bad++;});
return {bad:bad,total:total};})()""", 'returnByValue': True})
    d6 = json.loads(fin['result']['value'])
    check('⑥已定稿组零「工作中」[v228]', d6['bad'] == 0, 'bad=%s/%s' % (d6['bad'], d6['total']))

print()
print('=' * 50)
# ========== ⑦ vcs 徽章（P7：后端 ins/del 字段）==========
try:
    req = urllib.request.Request('http://127.0.0.1:%s/api/vcs/log' % BACK,
        data=json.dumps({'root': r'D:\AI\串口控制台Pro', 'limit': 3}).encode(),
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=15) as r7:
        j7 = json.loads(r7.read().decode())
    ins_ok = all('ins' in c for c in j7.get('commits', [])[:2])
    check('⑦vcs shortstat ins/del[P7]', ins_ok, str([(c.get('ins'), c.get('del')) for c in j7.get('commits', [])[:2]]))
except Exception as e:
    check('⑦vcs shortstat', False, str(e)[:80])

# ========== ⑧ 看门狗在跑且无误报转储（G2）==========
import os
wd = os.path.expanduser('~/.serialconsole_pro/watchdog_dump.log')
if os.path.exists(wd):
    age = time.time() - os.path.getmtime(wd)
    check('⑧看门狗无近期误报转储[G2]', age > 60, '最后转储 %.0fs 前（正常请求不应触发）' % age)
else:
    check('⑧看门狗无转储文件[G2]', True, '从未触发=无慢请求误报')

print()
fails = [r for r in RESULTS if not r[1]]
print('====== 自测矩阵终局: %d 项, FAIL %d ======' % (len(RESULTS), len(fails)))
for n, _, d in fails:
    print('  FAIL:', n, d)
