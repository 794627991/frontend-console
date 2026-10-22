/* v4store —— 前端投影 store（ZCode 归一管线，批C）。
 *
 * 对照 ZCode conversationProjectionStore.ts 的四条铁律（原生 JS 版）：
 *   1. snapshot → 整体替换，绝不 merge；
 *   2. deltas 帧仅在区间衔接（fromSeq === 本地 seq）时 apply，断档不猜、
 *      不缓存补偿——携水位重订阅，由服务端裁决 resume/snapshot；
 *   3. 连接与状态同生共死——断档时状态未被污染，重订阅即可恢复；
 *   4. 除 overlay（pending 命令对账登记，不渲染任何气泡）外，本 store
 *      不产生任何会话事实。DOM 永远是投影的纯函数。
 *
 * 依赖：v4proto.js（V4P，applyDeltas 唯一状态推进器）。
 * 挂载：window.V4Store（构造器）。渲染层 subscribe 监听两种通知：
 *   {kind:'status'} / {kind:'snapshot'} / {kind:'deltas', deltas, snap}
 */
(function (root) {
  'use strict';

  var ACK_MS = 15000;         // 连接建立后未收到首帧的判死窗
  var SILENT_MS = 20000;      // 无帧判死（心跳 5s 兜底）
  var WATCHDOG_MS = 2000;     // 命令 ACK 后投影静默的自愈窗
  var OVERLAY_TTL = 20000;    // overlay 对账放弃窗
  var RETRY_MS = 1000;        // 断线重连退避

  function V4Store(sid, topic) {
    this.sid = sid;
    this.topic = topic || 'main';
    this.status = 'idle';     // idle|connecting|live|reconnecting|closed
    this.epoch = '';
    this.seq = 0;
    this.snap = root.V4P.newSnapshot('');
    this.overlay = [];        // [{cmdId, at}] 只喂 watchdog，不渲染
    this._es = null;
    this._listeners = [];
    this._forceSnapshot = false;
    this._lastFrameAt = 0;
    this._ackTimer = null;
    this._silentTimer = null;
    this._retryTimer = null;
    this._closed = false;
  }

  V4Store.prototype.subscribe = function (fn) {
    var self = this;
    this._listeners.push(fn);
    return function () {
      var i = self._listeners.indexOf(fn);
      if (i >= 0) self._listeners.splice(i, 1);
    };
  };

  V4Store.prototype._notify = function (ev) {
    for (var i = 0; i < this._listeners.length; i++) {
      try { this._listeners[i](ev || { kind: 'status' }); }
      catch (e) { /* 渲染层异常不伤数据层 */ }
    }
  };

  // ---- 连接管理 ----------------------------------------------------------

  V4Store.prototype.connect = function () {
    if (this._closed) return;
    var self = this;
    this._teardown();
    this.status = this.seq > 0 && !this._forceSnapshot
      ? 'reconnecting' : 'connecting';
    // a60R（用户实测 reload 后主窗只剩 live 行，数秒空窗）：冷连接先垫显
    // 本地持久快照（上一会话期的权威快照，可能过期）——服务端 hydration
    // 需数秒构建 21 回合窗，空窗期用户看到「只剩当前回合」；垫片立现旧内
    // 容，权威 snapshot 到达按规则 1 整体覆盖（垫片永不与增量混写）
    if (!this.seq && this.topic === 'main') {
      try {
        var _c = JSON.parse(localStorage.getItem(
          'hg_v4snap:' + this.sid + ':main') || 'null');
        if (_c && _c.snapshot && (_c.snapshot.rows || []).length) {
          this.snap = _c.snapshot;
          this.seq = _c.toSeq || 0;
          this._notify({ kind: 'snapshot', snap: this.snap });
        }
      } catch (e) { /* 垫片损坏按无处理 */ }
    }
    this._notify();
    var qs = 'sid=' + encodeURIComponent(this.sid) +
      '&topic=' + encodeURIComponent(this.topic);
    if (this.epoch && this.seq > 0 && !this._forceSnapshot) {
      qs += '&epoch=' + encodeURIComponent(this.epoch) + '&seq=' + this.seq;
    }
    var es = this._es = new EventSource('/api/harness/v4/stream?' + qs);
    this._lastFrameAt = Date.now();
    es.addEventListener('ack', function (e) {
      self._lastFrameAt = Date.now();
      try {
        var a = JSON.parse(e.data);
        if (a.epoch) self.epoch = a.epoch;
        if (a.mode === 'snapshot') self._forceSnapshot = false;
        // a92：resume 零帧（安静 feed 续传）也算连上——否则 status 停在
        // connecting，15s ACK 判死窗反复重连（服务端 a92 起安静 feed 只
        // ack 不发帧）
        if (a.mode === 'resume' && self.status !== 'live') {
          self.status = 'live';
          self._notify();
        }
      } catch (err) { /* ack 损坏：等 frame 或判死 */ }
    });
    es.addEventListener('frame', function (e) {
      var f = null;
      try { f = JSON.parse(e.data); } catch (err) { return; }
      self._onFrame(f);
    });
    es.addEventListener('ka', function () { self._lastFrameAt = Date.now(); });
    es.onerror = function () { self._scheduleReconnect(); };
    // 判死双保险：连上却无首帧 / 长期静默（心跳丢失）
    this._ackTimer = setTimeout(function () {
      if (self.status !== 'live') self._scheduleReconnect();
    }, ACK_MS);
    this._silentTimer = setInterval(function () {
      if (Date.now() - self._lastFrameAt > SILENT_MS) self._scheduleReconnect();
    }, 5000);
  };

  V4Store.prototype._scheduleReconnect = function () {
    var self = this;
    if (this._closed || this._retryTimer) return;
    this._teardown();
    this.status = 'reconnecting';
    this._notify();
    this._retryTimer = setTimeout(function () {
      self._retryTimer = null;
      self.connect();
    }, RETRY_MS);
  };

  V4Store.prototype._teardown = function () {
    if (this._es) { try { this._es.close(); } catch (e) {} this._es = null; }
    if (this._ackTimer) { clearTimeout(this._ackTimer); this._ackTimer = null; }
    if (this._silentTimer) { clearInterval(this._silentTimer); this._silentTimer = null; }
  };

  V4Store.prototype.close = function () {
    this._closed = true;
    this._teardown();
    if (this._retryTimer) { clearTimeout(this._retryTimer); this._retryTimer = null; }
    this.status = 'closed';
    this._notify();
  };

  // ---- 帧处理（唯一状态推进路径） ----------------------------------------

  V4Store.prototype._onFrame = function (f) {
    this._lastFrameAt = Date.now();
    if (f.kind === 'snapshot') {
      // 规则 1：整体替换，绝不 merge
      this.snap = f.snapshot;
      this.epoch = f.snapshot.epoch || this.epoch;
      this.seq = f.toSeq;
      this.status = 'live';
      this._forceSnapshot = false;
      this._reconcile();
      // a60R：持久化权威快照（下一轮冷连接的垫片；main topic 限定防超限）
      if (this.topic === 'main') {
        try { localStorage.setItem('hg_v4snap:' + this.sid + ':main',
          JSON.stringify({ snapshot: f.snapshot, toSeq: f.toSeq })); } catch (e) {}
      }
      this._notify({ kind: 'snapshot', snap: this.snap });
      return;
    }
    if (f.kind === 'deltas') {
      if (this.status !== 'live' && this.status !== 'reconnecting') {
        // resume 首帧：ack(mode=resume) 已到但 status 仍非 live——
        // 本地 snap 即权威延续，直接进入应用
        if (this.status !== 'connecting') return;
        this.status = 'live';
        this._forceSnapshot = false;
      }
      if (f.fromSeq !== this.seq) {
        // 规则 2：断档不猜——重订阅让服务端裁决
        this._forceSnapshot = true;
        this._scheduleReconnect();
        return;
      }
      root.V4P.applyDeltas(this.snap, f.deltas);
      this.seq = f.toSeq;
      this._reconcile();
      this._notify({ kind: 'deltas', deltas: f.deltas, snap: this.snap });
    }
  };

  // ---- overlay 对账（发送链路红线：绝不伪造消息行） -----------------------

  V4Store.prototype.markPending = function (cmdId) {
    var self = this;
    this.overlay.push({ cmdId: cmdId, at: Date.now() });
    setTimeout(function () {
      var still = self.overlay.some(function (o) { return o.cmdId === cmdId; });
      if (!still) return;
      // ACK 后投影静默超窗：不重放不伪造，携水位重订阅恢复权威投影
      self._forceSnapshot = true;
      if (self.status === 'live') self._scheduleReconnect();
    }, WATCHDOG_MS);
  };

  V4Store.prototype._reconcile = function () {
    if (!this.overlay.length) return;
    var rows = this.snap.rows;
    var now = Date.now();
    this.overlay = this.overlay.filter(function (o) {
      if (now - o.at > OVERLAY_TTL) return false;      // 放弃对账
      for (var i = 0; i < rows.length; i++) {
        var r = rows[i];
        if (r.kind === 'user_input' && r.cmd === o.cmdId) return false;
      }
      return true;
    });
  };

  root.V4Store = V4Store;
})(window);
