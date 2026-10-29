# -*- coding: utf-8 -*-
"""离线资源状态 / 安装 API（v4.1）。

前端启动后 GET /api/resources/status 拿统一检测结果：
- hard_missing 非空 → 理论上此时界面根本起不来（启动闸门已拦），
  能走到这里说明是旁路启动，仍按红条提示
- soft_missing 非空 → 常驻红条「缺少 X —— 相关功能不可用 [安装资源包]」

安装走后台线程 + 轮询（与 claude_setup 的任务状态机同款形态，但状态
对象独立——两套安装互不阻塞）。
"""
import threading
import time

from flask import Blueprint, jsonify, request

res_bp = Blueprint("resources", __name__)

_lock = threading.Lock()
_state = {"running": False, "phase": "", "log": [], "done": False,
          "ok": False, "err": "", "ts": 0.0, "result": None}


def _log(msg):
    _state["log"].append({"t": time.time(), "msg": str(msg)})
    if len(_state["log"]) > 400:
        del _state["log"][:-400]


@res_bp.route("/api/resources/status")
def res_status():
    """统一资源检测（60s 缓存，不会每次轮询都起子进程）。"""
    from src.res_boot import probe_all, MANIFEST, _read_state
    d = probe_all(use_cache=True)
    st = _read_state()
    d["ignored"] = st.get("res_ignore") or []
    d["installed_at"] = st.get("installed_at") or ""
    d["manifest"] = MANIFEST
    return jsonify({"ok": True, **d})


@res_bp.route("/api/resources/ignore", methods=["POST"])
def res_ignore():
    """用户点「忽略」后不再提示这些软资源。body: {kinds: [...]}"""
    from src.res_boot import _read_state, _write_state
    d = request.get_json(force=True, silent=True) or {}
    kinds = [str(k) for k in (d.get("kinds") or []) if k]
    cur = _read_state().get("res_ignore") or []
    _write_state({"res_ignore": sorted(set(cur) | set(kinds))})
    return jsonify({"ok": True, "ignored": sorted(set(cur) | set(kinds))})


@res_bp.route("/api/resources/install", methods=["POST"])
def res_install_api():
    """后台装资源包。body: {path, kinds?}"""
    from src import fcpk, res_install
    d = request.get_json(force=True, silent=True) or {}
    path = str(d.get("path") or "").strip()
    kinds = d.get("kinds") or None
    if not path or not fcpk.is_fcpk(path):
        return jsonify({"ok": False, "err": "请选择 .fcpk 资源包"}), 400
    info = fcpk.inspect(path)
    if not info.get("ok"):
        return jsonify({"ok": False, "err": info.get("err") or "资源包无法读取"}), 400
    with _lock:
        if _state["running"]:
            return jsonify({"ok": False, "err": "已有安装任务在运行"}), 409
        _state.update(running=True, phase="准备", log=[], done=False, ok=False,
                      err="", ts=time.time(), result=None)

    def work():
        try:
            _state["phase"] = "解包安装"
            res = res_install.install_from(
                path, kinds=kinds, log=_log,
                progress=lambda d_, t_, l_: _state.update(
                    phase="安装 %s" % (l_ or "")))
            errs = res.get("errors") or {}
            _state.update(done=True, ok=not errs, result=res,
                          err="; ".join("%s: %s" % kv for kv in errs.items()),
                          phase="完成" if not errs else "部分失败")
        except Exception as e:
            _state.update(done=True, ok=False, err=str(e)[:400], phase="失败")
            _log("失败：%s" % e)
        finally:
            _state["running"] = False
            # 装完清探测缓存——下一次 status 立刻反映真实状态
            try:
                from src import res_boot
                cur = res_boot._read_state()
                cur.pop("last_probe", None)
                p = res_boot._state_file()
                import json as _json, os as _os
                _os.makedirs(_os.path.dirname(p), exist_ok=True)
                with open(p, "w", encoding="utf-8") as f:
                    _json.dump(cur, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

    threading.Thread(target=work, daemon=True).start()
    return jsonify({"ok": True})


@res_bp.route("/api/resources/poll")
def res_poll():
    return jsonify({"ok": True,
                    "running": _state["running"], "phase": _state["phase"],
                    "log": _state["log"], "done": _state["done"],
                    "ok_done": _state["ok"], "err": _state["err"],
                    "result": _state["result"]})
