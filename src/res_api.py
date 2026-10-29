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
          "ok": False, "err": "", "ts": 0.0, "result": None,
          "cancel": False, "total": 0, "done_bytes": 0, "cur": ""}

# 包预检缓存：FcpkReader 要跑 PBKDF2 30 万轮（0.1~0.3s），设置页每次
# 选包/重检测都会问一次，按 (path, mtime, size) 缓存
_pkg_cache = {}


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
    # 对抗审 P3：硬资源（webview2/dotnet）不许忽略——红条消失但下次启动
    # 闸门照拦，行为不一致还掩盖问题
    from src.res_boot import _HARD
    bad = [k for k in kinds if k in _HARD]
    if bad:
        return jsonify({"ok": False,
                        "err": "必需资源不能忽略：%s（下次启动仍会检测）"
                               % ",".join(bad)}), 400
    cur = _read_state().get("res_ignore") or []
    _write_state({"res_ignore": sorted(set(cur) | set(kinds))})
    return jsonify({"ok": True, "ignored": sorted(set(cur) | set(kinds))})


@res_bp.route("/api/resources/package")
def res_package():
    """包预检：告诉设置页这个 .fcpk 里有哪些资源、多大、何时打的。

    query: ?path=...
    返回 {ok, name, size, plain_len, created, kinds:{kind:文件数}, err}
    前端据此把包内没有的 kind 行置灰（选了也装不上）。
    """
    import os as _os
    from src import fcpk
    path = (request.args.get("path") or "").strip()
    if not path:
        return jsonify({"ok": False, "err": "缺少 path 参数"}), 400
    if not fcpk.is_fcpk(path):
        return jsonify({"ok": False, "err": "不是资源包（.fcpk）"}), 400
    try:
        st = _os.stat(path)
        key = "%s|%d|%d" % (path, int(st.st_mtime), st.st_size)
    except OSError:
        return jsonify({"ok": False, "err": "文件不存在或不可读"}), 400
    hit = _pkg_cache.get(key)
    if hit:
        return jsonify(hit)
    try:
        import collections
        r = fcpk.FcpkReader(path)
        try:
            entries = list(r.entries)
            kinds = collections.Counter(
                e.get("kind") or "" for e in entries if e.get("kind"))
            plain = sum(int(e.get("size") or 0) for e in entries)
            created = str(r.table.get("created") or "")
            declared = r.table.get("resources") or []
        finally:
            r.close()
        # 声明段优先（打包侧写入），缺失则退回按 entries 的 kind 统计
        if declared:
            kinds = {str(x.get("kind")): int(x.get("files") or 0)
                     for x in declared if x.get("kind")}
        out = {"ok": True, "name": _os.path.basename(path),
               "size": st.st_size, "plain_len": plain,
               "created": created, "entries": len(entries),
               "kinds": dict(kinds)}
        _pkg_cache.clear()          # 只留最近一个，别让缓存无限长
        _pkg_cache[key] = out
        return jsonify(out)
    except Exception as e:
        return jsonify({"ok": False, "err": str(e)[:200]}), 400


@res_bp.route("/api/resources/cancel", methods=["POST"])
def res_cancel():
    """请求取消当前安装。只做到 kind 边界——正在跑的 msiexec/Inno 中断不
    可靠（强杀留半成品），与 install_from 的 should_cancel 语义一致。"""
    with _lock:
        if not _state["running"]:
            return jsonify({"ok": False, "err": "没有正在运行的安装任务"}), 409
        _state["cancel"] = True
        _log("已请求取消，当前步骤结束后停止")
    return jsonify({"ok": True})


@res_bp.route("/api/resources/install", methods=["POST"])
def res_install_api():
    """后台装资源包。body: {path, kinds?, force?}"""
    from src import fcpk, res_install
    d = request.get_json(force=True, silent=True) or {}
    path = str(d.get("path") or "").strip()
    kinds = d.get("kinds") or None
    force = bool(d.get("force"))
    if not path or not fcpk.is_fcpk(path):
        return jsonify({"ok": False, "err": "请选择 .fcpk 资源包"}), 400
    info = fcpk.inspect(path)
    if not info.get("ok"):
        return jsonify({"ok": False, "err": info.get("err") or "资源包无法读取"}), 400
    with _lock:
        if _state["running"]:
            return jsonify({"ok": False, "err": "已有安装任务在运行"}), 409
        _state.update(running=True, phase="准备", log=[], done=False, ok=False,
                      err="", ts=time.time(), result=None, cancel=False,
                      total=info.get("plain_len") or 0, done_bytes=0, cur="")

    def should_cancel():
        return bool(_state.get("cancel"))

    def on_prog(done_b, total_b, label):
        _state.update(done_bytes=int(done_b or 0),
                      total=int(total_b or _state["total"] or 0),
                      cur=label or "",
                      phase="安装 %s" % (label or ""))

    def work():
        try:
            _state["phase"] = "解包安装"
            res = res_install.install_from(
                path, kinds=kinds, log=_log, progress=on_prog,
                should_cancel=should_cancel, force=force)
            errs = res.get("errors") or {}
            _state.update(done=True, ok=not errs, result=res,
                          err="; ".join("%s: %s" % kv for kv in errs.items()),
                          phase="完成" if not errs else "部分失败")
        except res_install.InstallCancelled:
            _state.update(done=True, ok=False, err="已取消安装", phase="已取消")
            _log("用户取消安装")
        except Exception as e:
            _state.update(done=True, ok=False, err=str(e)[:400], phase="失败")
            _log("失败：%s" % e)
        finally:
            _state["running"] = False
            _state["cancel"] = False
            # 装完清探测缓存——下一次 status 立刻反映真实状态。
            # 对抗审 P2：早前绕过 _write_state 整写文件，与并发 /status 的
            # read-modify-write 互相覆盖（陈旧 last_probe 复活、红条多挂 60s）
            try:
                from src import res_boot
                res_boot._pop_state("last_probe")
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
                    "result": _state["result"],
                    "total": _state["total"], "bytes": _state["done_bytes"],
                    "cur": _state["cur"], "cancelling": _state["cancel"]})
