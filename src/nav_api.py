# -*- coding: utf-8 -*-
"""代码跳转索引 API（a333 批1）。蓝图 nav_bp——就近注册（server.py）。

任务槽复刻 res_api 形态（状态独立、单任务、poll 轮询、协作式取消、
seq 日志）；查询端点无状态直答。门卫：索引根必须在文件树登记根内
（_under_roots + _under_roots_real，与 tree 系 API 同源）。"""
import os
import threading
import time

from flask import Blueprint, jsonify, request

nav_bp = Blueprint("nav", __name__)

_lock = threading.Lock()
_state = {"running": False, "phase": "", "log": [], "done": False,
          "ok": False, "err": "", "ts": 0.0, "result": None, "cancel": False,
          "percent": 0, "cur": "", "cancelled": False, "log_seq": 0,
          "root": "", "importing": False}


def _log(msg):
    with _lock:
        _state["log_seq"] += 1
        _state["log"].append({"t": time.time(), "msg": str(msg),
                              "seq": _state["log_seq"]})
        if len(_state["log"]) > 400:
            del _state["log"][:-400]


def _guard(path):
    """索引/管理目标必须在文件树登记根内（防任意目录索引）。"""
    from src.file_tree import _under_roots, _under_roots_real
    return _under_roots(path) and _under_roots_real(path)


@nav_bp.route("/api/nav/status")
def nav_status():
    """右键三态 + 跳转前探测。?root= 目录（浅探测秒级）。"""
    from src import nav_index
    root = (request.args.get("root") or "").strip()
    if not root:
        return jsonify({"ok": False, "err": "缺 root"}), 400
    if not _guard(root):
        return jsonify({"ok": False, "err": "目录不在文件树登记根内"}), 400
    return jsonify({"ok": True, **nav_index.status(root)})


@nav_bp.route("/api/nav/libs")
def nav_libs():
    """全部索引库概览（管理/存储感知联动）。"""
    from src import nav_index
    return jsonify({"ok": True, "libs": nav_index.list_libs(),
                    "total": os_dir_size_safe(nav_index._nav_root())})


def os_dir_size_safe(p):
    import os
    if not os.path.isdir(p):
        return 0
    total = 0
    for r, _, fs in os.walk(p):
        for f in fs:
            try:
                total += os.path.getsize(os.path.join(r, f))
            except OSError:
                pass
    return total


@nav_bp.route("/api/nav/build", methods=["POST"])
def nav_build():
    """手动建库（唯一入口——绝不自动触发）。body {root}"""
    from src import nav_index
    d = request.get_json(force=True, silent=True) or {}
    root = str(d.get("root") or "").strip()
    if not root:
        return jsonify({"ok": False, "err": "缺 root"}), 400
    if not _guard(root):
        return jsonify({"ok": False, "err": "目录不在文件树登记根内"}), 400
    with _lock:
        # R17-2（实锤：互斥只挡单向）：导入进行中（大清单秒级窗口）启动
        # build 会非确定互覆 symbols/meta——双向互斥
        if _state["running"]:
            return jsonify({"ok": False,
                            "err": "已有索引任务在运行（%s）" % _state["root"]}), 409
        if _state["importing"]:
            return jsonify({"ok": False, "err": "nm 清单导入进行中，稍后再建"}), 409
        _state.update(running=True, phase="准备", log=[], done=False, ok=False,
                      err="", ts=time.time(), result=None, cancel=False,
                      percent=0, cur="", cancelled=False, log_seq=0, root=root)

    def should_cancel():
        return bool(_state.get("cancel"))

    def on_prog(pct, total, label):
        _state.update(percent=int(pct), cur=label or "",
                      phase=str(label or "处理中"))

    def work():
        try:
            res = nav_index.build(root, log=_log, progress=on_prog,
                                  should_cancel=should_cancel)
            _state.update(done=True, ok=True, result=res, phase="完成")
        except nav_index.Cancelled:
            _state.update(done=True, ok=False, err="已取消", phase="已取消",
                          cancelled=True)
            _log("用户取消索引")
        except Exception as e:
            _state.update(done=True, ok=False, err=str(e)[:400], phase="失败")
            _log("失败：%s" % e)
        finally:
            _state["running"] = False
            _state["cancel"] = False

    threading.Thread(target=work, daemon=True).start()
    return jsonify({"ok": True})


@nav_bp.route("/api/nav/poll")
def nav_poll():
    with _lock:
        return jsonify({"ok": True, "running": _state["running"],
                        "phase": _state["phase"], "log": _state["log"],
                        "done": _state["done"], "ok_done": _state["ok"],
                        "err": _state["err"], "result": _state["result"],
                        "percent": _state["percent"], "cur": _state["cur"],
                        "cancelling": _state["cancel"],
                        "cancelled": _state["cancelled"],
                        "log_seq": _state["log_seq"], "root": _state["root"]})


@nav_bp.route("/api/nav/cancel", methods=["POST"])
def nav_cancel():
    with _lock:
        if not _state["running"]:
            return jsonify({"ok": False, "err": "没有运行中的索引任务"}), 409
        _state["cancel"] = True
    return jsonify({"ok": True})


@nav_bp.route("/api/nav/delete", methods=["POST"])
def nav_delete():
    """删除某根的索引库。body {root}
    R15-7：运行中建库拒删（build 线程正在写库目录，删=竞态崩溃）。
    R15-5：工程路径已不可达（换盘/移动）时门卫必拒——但库删除本身不依赖
    路径有效性：库存在即允许删（否则孤儿库永远删不掉）。"""
    from src import nav_index
    d = request.get_json(force=True, silent=True) or {}
    root = str(d.get("root") or "").strip()
    if not root:
        return jsonify({"ok": False, "err": "缺 root"}), 400
    with _lock:
        if _state["running"]:
            return jsonify({"ok": False, "err": "索引任务运行中，稍后再删"}), 409
    has_lib = any(l["root"].lower() == os.path.normcase(os.path.abspath(root))
                  for l in nav_index.list_libs())
    if not has_lib and not _guard(root):
        return jsonify({"ok": False, "err": "目录不在文件树登记根内且无对应索引库"}), 400
    return jsonify({"ok": nav_index.delete_lib(root)})


@nav_bp.route("/api/nav/rebind", methods=["POST"])
def nav_rebind():
    """工程移动/换盘后重关联。body {old_root, new_root}"""
    from src import nav_index
    d = request.get_json(force=True, silent=True) or {}
    old_root = str(d.get("old_root") or "").strip()
    new_root = str(d.get("new_root") or "").strip()
    if not old_root or not new_root:
        return jsonify({"ok": False, "err": "缺 old_root/new_root"}), 400
    if not _guard(new_root):
        return jsonify({"ok": False, "err": "新目录不在文件树登记根内"}), 400
    ok, msg = nav_index.rebind(old_root, new_root)
    return jsonify({"ok": ok, "err": "" if ok else msg, "msg": msg})


@nav_bp.route("/api/nav/definition")
def nav_definition():
    """跳转查询。?file=（发起跳转的文件，组件上下文+库反查）&symbol="""
    from src import nav_index
    f = (request.args.get("file") or "").strip()
    sym = (request.args.get("symbol") or "").strip()
    if not f or not sym:
        return jsonify({"ok": False, "err": "缺 file/symbol"}), 400
    try:
        res = nav_index.definition(f, sym)
        return jsonify({"ok": True, **res})
    except Exception as e:
        return jsonify({"ok": False, "err": str(e)[:200]}), 200


@nav_bp.route("/api/nav/symbols")
def nav_symbols():
    """工作区符号面板（Ctrl+T）。?file=&q=&limit="""
    from src import nav_index
    f = (request.args.get("file") or "").strip()
    q = (request.args.get("q") or "").strip()
    try:
        limit = min(100, max(10, int(request.args.get("limit") or 50)))
    except ValueError:
        limit = 50
    if not f:
        return jsonify({"ok": False, "err": "缺 file"}), 400
    try:
        return jsonify(nav_index.symbols(f, q, limit))
    except Exception as e:
        return jsonify({"ok": False, "err": str(e)[:200]}), 200


@nav_bp.route("/api/nav/references")
def nav_references():
    """引用查找（Shift+F12）。?file=&symbol="""
    from src import nav_index
    f = (request.args.get("file") or "").strip()
    sym = (request.args.get("symbol") or "").strip()
    if not f or not sym:
        return jsonify({"ok": False, "err": "缺 file/symbol"}), 400
    try:
        return jsonify(nav_index.references(f, sym))
    except Exception as e:
        return jsonify({"ok": False, "err": str(e)[:200]}), 200


@nav_bp.route("/api/nav/import_nm", methods=["POST"])
def nav_import_nm():
    """批3：Linux 侧 nm -A 清单导入（可选增强）。body {root, file}
    R16-6：与 build 互斥（并发写 symbols.json 交错丢数据）。
    R16-7：库/meta 异常统一 200 人话（不留 500）。
    R16-8：清单文件存在性+大小上限（防巨文件/不存在路径 500）。"""
    from src import nav_index
    d = request.get_json(force=True, silent=True) or {}
    root = str(d.get("root") or "").strip()
    nmf = str(d.get("file") or "").strip()
    if not root or not nmf:
        return jsonify({"ok": False, "err": "缺 root/file"}), 400
    if not _guard(root):
        return jsonify({"ok": False, "err": "目录不在文件树登记根内"}), 400
    with _lock:
        if _state["running"]:
            return jsonify({"ok": False, "err": "索引任务运行中，稍后再导入"}), 409
        if _state["importing"]:
            return jsonify({"ok": False, "err": "已有导入进行中"}), 409
        _state["importing"] = True
    try:
        if not os.path.isfile(nmf):
            return jsonify({"ok": False, "err": "清单文件不存在"}), 400
        try:
            if os.path.getsize(nmf) > 100 * 1048576:
                return jsonify({"ok": False, "err": "清单过大（>100MB）"}), 400
        except OSError:
            return jsonify({"ok": False, "err": "清单不可读"}), 400
        try:
            ok, msg = nav_index.import_nm_list(root, nmf)
        except Exception as e:
            return jsonify({"ok": False, "err": "导入失败：%s" % str(e)[:150]}), 200
        return jsonify({"ok": ok, "err": "" if ok else msg, "msg": msg})
    finally:
        with _lock:
            _state["importing"] = False
