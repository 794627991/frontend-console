/* v4 投影协议纯函数（JS 端）：与 src/harness/v4proto.py 同语义。
 *
 * 对照 ZCode packages/shared/src/zcode-protocol-v4/{rows,delta,apply,coalesce}.ts：
 * 操作集封闭（appended/upserted/removed/delta/state.updated），表达不了的
 * 结构变化一律服务端 snapshot resync；apply 与 coalesce 语义保持由
 * tests/v4_golden/golden.json 双端跑绿保证（Python/JS 各自实现同一夹具）。
 *
 * 浏览器：挂 window.V4P（script 标签按序加载，无模块系统）。
 * Node（黄金夹具校验）：node v4proto.js --golden <golden.json>。
 */
(function (root) {
  'use strict';

  var ROW_KINDS = ['turn_header', 'user_input', 'assistant_text', 'reasoning',
    'tool_call', 'subagent', 'vision', 'peer_notify', 'marker'];
  var TOOL_STATUS = ['streaming_input', 'running', 'success', 'error', 'cancelled'];
  // 契约白名单：必须是**自有属性**判断。用对象当集合时 'constructor' /
  // 'toString' 等原型链名字会命中真值（实测把字符串拼进行字段），而后端
  // v4proto.py 用 tuple 成员判断会拒绝——双端不一致。改用数组 + indexOf。
  var STREAM_PATH_LIST = ['text', 'inputText', 'summary'];
  function _isStreamPath(p) { return STREAM_PATH_LIST.indexOf(p) >= 0; }

  function newSnapshot(epoch) {
    return { seq: 0, epoch: epoch || '', state: {}, rows: [], total: 0 };
  }

  function mkRow(rowId, turnId, kind, at, atSeq, fields) {
    var row = { rowId: rowId, turnId: turnId, kind: kind, at: at, atSeq: atSeq };
    if (fields) for (var k in fields) row[k] = fields[k];
    return row;
  }

  // ---- apply（协议规范实现；前端 store 唯一状态推进器）----

  function applyDelta(snap, d) {
    var op = d.op, i, r;
    if (op === 'row.appended') {
      var row = d.row;
      for (i = 0; i < snap.rows.length; i++)
        if (snap.rows[i].rowId === row.rowId) return snap;   // 幂等 no-op
      snap.rows.push(Object.assign({}, row));                // 拷贝入账，不共享引用
      snap.total += 1;
      return snap;
    }
    if (op === 'row.upserted') {
      var up = d.row;
      for (i = 0; i < snap.rows.length; i++)
        if (snap.rows[i].rowId === up.rowId) {
          snap.rows[i] = Object.assign({}, up); return snap;
        }
      snap.rows.push(Object.assign({}, up));                 // 未加载：等价 appended
      snap.total += 1;
      return snap;
    }
    if (op === 'row.removed') {
      var keep = [];
      for (i = 0; i < snap.rows.length; i++)
        if (snap.rows[i].rowId < d.fromRowId) keep.push(snap.rows[i]);
      snap.total = Math.max(0, snap.total - (snap.rows.length - keep.length));
      snap.rows = keep;
      return snap;
    }
    if (op === 'row.delta') {
      if (!_isStreamPath(d.path) || !d.append) return snap;
      for (i = 0; i < snap.rows.length; i++) {
        r = snap.rows[i];
        if (r.rowId === d.rowId) {
          r[d.path] = (r[d.path] || '') + d.append;
          break;                                             // 窗口外：no-op 不猜
        }
      }
      return snap;
    }
    if (op === 'state.updated') {
      var p = d.patch;
      for (var key in p) snap.state[key] = p[key];           // 键级整体替换
      return snap;
    }
    return snap;                                             // 未知 op：no-op
  }

  function applyDeltas(snap, deltas) {
    for (var i = 0; i < deltas.length; i++) applyDelta(snap, deltas[i]);
    return snap;
  }

  // ---- coalesce（语义保持：apply(s, coalesce(ds)) ≡ apply(s, ds)）----

  function coalesce(deltas) {
    var out = [], i, d, prev;
    for (i = 0; i < deltas.length; i++) {
      d = deltas[i];
      prev = out.length ? out[out.length - 1] : null;
      if (d.op === 'row.delta') {
        if (prev && prev.op === 'row.delta' && prev.rowId === d.rowId
            && prev.path === d.path) prev.append += d.append;
        else out.push({ op: 'row.delta', rowId: d.rowId, path: d.path, append: d.append });
      } else if (d.op === 'state.updated') {
        if (prev && prev.op === 'state.updated') {
          for (var k in d.patch) prev.patch[k] = d.patch[k];
        } else {
          var patch = {};
          for (var k2 in d.patch) patch[k2] = d.patch[k2];
          out.push({ op: 'state.updated', patch: patch });
        }
      } else if (d.op === 'row.upserted') {
        var rid = d.row.rowId;
        out = out.filter(function (x) {
          return !(x.op === 'row.delta' && x.rowId === rid);
        });
        out.push({ op: 'row.upserted', row: d.row });
      } else if (d.op === 'row.removed') {
        var frid = d.fromRowId;
        out = out.filter(function (x) {
          if (x.op === 'row.delta') return x.rowId < frid;
          if (x.op === 'row.appended' || x.op === 'row.upserted') return x.row.rowId < frid;
          return true;
        });
        out.push({ op: 'row.removed', fromRowId: frid });
      } else {
        out.push(d);
      }
    }
    return out;
  }

  var V4P = {
    ROW_KINDS: ROW_KINDS, TOOL_STATUS: TOOL_STATUS,
    STREAM_PATHS: { text: 1, inputText: 1, summary: 1 },   // 兼容导出（判据用 _isStreamPath）
    newSnapshot: newSnapshot, mkRow: mkRow,
    applyDelta: applyDelta, applyDeltas: applyDeltas, coalesce: coalesce
  };

  // ---- Node 黄金夹具校验入口 ----
  if (typeof module !== 'undefined' && module.exports && typeof process !== 'undefined'
      && process.argv && process.argv.indexOf('--golden') >= 0) {
    var fs = require('fs');
    var path = process.argv[process.argv.indexOf('--golden') + 1];
    var cases = JSON.parse(fs.readFileSync(path, 'utf8'));
    var fails = 0;
    cases.forEach(function (c) {
      try {
        var snap = newSnapshot('');
        if (c.snapshot0) snap = JSON.parse(JSON.stringify(c.snapshot0));
        applyDeltas(snap, c.deltas);
        var got = JSON.parse(JSON.stringify(snap));
        var want = JSON.parse(JSON.stringify(c.expect));
        if (JSON.stringify(got) !== JSON.stringify(want)) {
          fails++;
          console.error('FAIL[apply] ' + c.name + '\n  got:  ' + JSON.stringify(got) +
            '\n  want: ' + JSON.stringify(want));
        }
        if (c.expect_coalesced) {
          var co = coalesce(c.deltas);
          if (JSON.stringify(co) !== JSON.stringify(c.expect_coalesced)) {
            fails++;
            console.error('FAIL[coalesce] ' + c.name + '\n  got:  ' + JSON.stringify(co) +
              '\n  want: ' + JSON.stringify(c.expect_coalesced));
          }
          // 语义保持校验：coalesce 前后 apply 结果一致
          var s2 = JSON.parse(JSON.stringify(c.snapshot0 || newSnapshot('')));
          applyDeltas(s2, co);
          if (JSON.stringify(s2) !== JSON.stringify(got)) {
            fails++;
            console.error('FAIL[equiv] ' + c.name + '：apply(coalesce) ≠ apply(raw)');
          }
        }
      } catch (e) {
        fails++;
        console.error('FAIL[throw] ' + c.name + '：' + (e && e.message));
      }
    });
    console.log(fails ? 'GOLDEN FAIL ' + fails : 'GOLDEN OK ' + cases.length);
    process.exit(fails ? 1 : 0);
  }

  root.V4P = V4P;
  if (typeof module !== 'undefined' && module.exports) module.exports = V4P;
})(typeof window !== 'undefined' ? window : globalThis);
