// 一次性:对象简写键误改名反向检查(用法: node _shorthand_check.js <dir>)
'use strict';
const fs = require('fs'), path = require('path');
const DIR = process.argv[2];
const NEW = ['_hgConn','_hgQ','_hgWrap','_hgFlow','_hgInput','_hgScrollBottom','_hgStateEl',
  '_hgCostEl','_hgSendBtn','_hgTitleEl','_hgCwdEl','_hgAttsEl','_hgListEl','_hgSearchEl',
  '_hgFileEl','_hgOverlayEl','_hgMentionEl','_hgActEl','_hgFmtDur'];
const re = new RegExp('([{,][ \\t]*)(' + NEW.join('|') + ')[ \\t]*(?=[,}])');
let bad = 0;
for (const f of fs.readdirSync(DIR).filter(x => x.endsWith('.js')).sort()) {
  const src = fs.readFileSync(path.join(DIR, f), 'utf8');
  let m;
  const r = new RegExp(re.source, 'g');
  while ((m = r.exec(src))) {
    const line = src.slice(0, m.index).split('\n').length;
    console.log(f + ' line ' + line + ' 简写键: ' + m[0].trim() + ' | ' + src.split('\n')[line - 1].trim().slice(0, 90));
    bad++;
  }
}
console.log(bad ? ('HITS=' + bad) : 'CLEAN: 无简写键误改名');
