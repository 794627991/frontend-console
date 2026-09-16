# -*- coding: utf-8 -*-
"""代理用量统计积木（v2.26）——独立插件，不侵入 proxy.py / proxy_core.py。

搭积木原则：本文件是独立一块，对宿主的全部接入只有两根插头：
1. server.py 挂载本蓝图（一行 register_blueprint，工程插件惯例）
2. monkeypatch proxy_core.Stats.req_success / req_failed 包一层采集
   （宿主零改动；补丁仅在进程内生效）

功能：按 日×小时×模型 聚合转发用量（请求数/输入/输出 tokens），
60s 后台落盘 + atexit flush，滚动保留 180 天。
查询：GET /api/usage/summary?range=hour|7d|30d
"""
import atexit
import json
import logging
import os
import threading
import time

from flask import Blueprint, jsonify, request

from src import proxy_core
from src.app_state import DATA_DIR

log = logging.getLogger("proxy_usage")

USAGE_PATH = os.path.join(DATA_DIR, "proxy_usage.json")
USAGE_KEEP_DAYS = 180

usage_bp = Blueprint("proxy_usage", __name__)


class UsageRecorder:
    """转发用量聚合器。存储结构
    {"days": {"2026-09-15": {"14": {"模型": [req, in, out]}}}}。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._days = {}      # {date_str: {hour_int: {model: [req,in,out]}}}
        self._dirty = False
        self._load()

    @staticmethod
    def _cutoff(now=None):
        now = now or time.time()
        return time.strftime("%Y-%m-%d", time.localtime(now - USAGE_KEEP_DAYS * 86400))

    def _load(self):
        try:
            with open(USAGE_PATH, encoding="utf-8") as f:
                days = (json.load(f) or {}).get("days") or {}
        except (ValueError, OSError):
            return
        cutoff = self._cutoff()
        for d, hours in days.items():
            if not isinstance(hours, dict) or d < cutoff:
                continue
            hh = {}
            for h, models in hours.items():
                try:
                    hh[int(h)] = {m: list(v) for m, v in (models or {}).items()
                                  if isinstance(v, (list, tuple)) and len(v) == 3}
                except (ValueError, TypeError):
                    continue
            if hh:
                self._days[d] = hh

    def record(self, model, in_tok, out_tok):
        if not model:
            return
        lt = time.localtime()
        day = time.strftime("%Y-%m-%d", lt)
        with self._lock:
            hours = self._days.setdefault(day, {})
            cell = hours.setdefault(lt.tm_hour, {}).setdefault(model, [0, 0, 0])
            cell[0] += 1
            cell[1] += in_tok or 0
            cell[2] += out_tok or 0
            self._dirty = True

    def _save(self):
        cutoff = self._cutoff()
        self._days = {d: h for d, h in self._days.items() if d >= cutoff}
        tmp = USAGE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"days": {d: {str(h): m for h, m in hh.items()}
                                for d, hh in self._days.items()}},
                      f, ensure_ascii=False)
        os.replace(tmp, USAGE_PATH)
        self._dirty = False

    def _loop(self):
        while True:
            time.sleep(60)
            try:
                with self._lock:
                    if self._dirty:
                        self._save()
            except Exception:
                log.exception("用量落盘失败")

    def flush(self):
        try:
            with self._lock:
                if self._dirty:
                    self._save()
        except Exception:
            log.exception("用量退出落盘失败")

    def query(self, rng):
        """rng: hour=当日按小时；7d/30d=近 N 日按日。统一结构供柱状图。"""
        with self._lock:
            snap = {d: {h: {m: list(v) for m, v in hh.items()} for h, hh in days.items()}
                    for d, days in self._days.items()}
        # 历史「?」占位（无模型名请求）从查询侧一并滤掉——写入侧已停记，
        # 落盘 json 里存量条目在这里统一出清（用户定调排除）
        for days in snap.values():
            for hh in days.values():
                hh.pop("?", None)
        now = time.localtime()
        items = []
        if rng == "hour":
            day = time.strftime("%Y-%m-%d", now)
            hours = snap.get(day, {})
            for h in range(24):
                models = hours.get(h, {})
                if models or h <= now.tm_hour:
                    items.append({"key": "%02d" % h, "label": "%02d时" % h,
                                  "models": models})
        else:
            n = 7 if rng == "7d" else 30
            for i in range(n - 1, -1, -1):
                t = time.localtime(time.time() - i * 86400)
                d = time.strftime("%Y-%m-%d", t)
                models = {}
                for hh in (snap.get(d) or {}).values():
                    for m, v in hh.items():
                        cell = models.setdefault(m, [0, 0, 0])
                        cell[0] += v[0]
                        cell[1] += v[1]
                        cell[2] += v[2]
                items.append({"key": d, "label": "%d/%d" % (t.tm_mon, t.tm_mday),
                              "models": models})
        total = {}
        for it in items:
            for m, v in it["models"].items():
                c = total.setdefault(m, [0, 0, 0])
                c[0] += v[0]
                c[1] += v[1]
                c[2] += v[2]
        return {"ok": True, "range": rng, "items": items, "total": total,
                "keep_days": USAGE_KEEP_DAYS}


_recorder = UsageRecorder()


def _record_success(self, model, in_tok, out_tok, elapsed, **kw):
    _orig_req_success(self, model, in_tok, out_tok, elapsed, **kw)
    # 无模型名的请求（CLI 内部整理/探测等）不进用量统计——此前记成「?」
    # 在图表上变成一根 0 token 的假柱 + 一行无意义明细（用户定调排除）
    if model:
        _recorder.record(model, in_tok or 0, out_tok or 0)


def _record_failed(self, reason, path, attempt, status=None, elapsed=None,
                   in_tok=0, out_tok=0, **kw):
    _orig_req_failed(self, reason, path, attempt, status=status, elapsed=elapsed,
                     in_tok=in_tok, out_tok=out_tok, **kw)
    # 失败但已消耗 token（流中断等）也算真实用量；零消耗不计。
    # 模型名拿不到（brief 缺失）的失败请求同样不计——没法归类的用量没有意义
    if (in_tok or out_tok):
        brief = kw.get("brief")
        m = brief[2] if brief else None
        if m:
            _recorder.record(m, in_tok or 0, out_tok or 0)


# ---- monkeypatch 接入（宿主零改动）：包原方法，只在本积木被导入时生效 ----
_orig_req_success = proxy_core.Stats.req_success
_orig_req_failed = proxy_core.Stats.req_failed
proxy_core.Stats.req_success = _record_success
proxy_core.Stats.req_failed = _record_failed

threading.Thread(target=_recorder._loop, daemon=True, name="proxy-usage-flush").start()
atexit.register(_recorder.flush)


@usage_bp.route("/api/usage/summary")
def usage_summary():
    """用量统计：range=hour（当日按小时）| 7d | 30d，前端柱状图数据源。"""
    rng = request.args.get("range", "hour")
    if rng not in ("hour", "7d", "30d"):
        rng = "hour"
    return jsonify(_recorder.query(rng))
