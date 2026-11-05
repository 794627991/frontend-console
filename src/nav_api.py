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
    """手动建库（唯一入口——绝不自动触发）。body {root, backend?}"""
    from src import nav_index
    d = request.get_json(force=True, silent=True) or {}
    root = str(d.get("root") or "").strip()
    backend = str(d.get("backend") or "auto").strip().lower()   # a390 三档
    if backend not in ("auto", "memory", "readtags", "sqlite"):
        backend = "auto"
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
                                  should_cancel=should_cancel, backend=backend)
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
        # R18-1（实锤：delete 漏接 importing 互斥）：导入中删库 → 导入线程
        # makedirs 复活库目录写孤儿 symbols.json（不可见、无法 UI 清理）
        if _state["importing"]:
            return jsonify({"ok": False, "err": "nm 清单导入进行中，稍后再删"}), 409
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


@nav_bp.route("/api/nav/reindex", methods=["POST"])
def nav_reindex():
    """a390：已建库切换查询后端（不重建 tags）。body {root, backend}"""
    import os
    from src import nav_index
    d = request.get_json(force=True, silent=True) or {}
    root = str(d.get("root") or "").strip()
    backend = str(d.get("backend") or "").strip().lower()
    if backend not in ("memory", "readtags", "sqlite"):
        return jsonify({"ok": False, "err": "backend 须为 memory/readtags/sqlite"}), 400
    if not root:
        return jsonify({"ok": False, "err": "缺 root"}), 400
    if not _guard(root):
        return jsonify({"ok": False, "err": "目录不在文件树登记根内"}), 400
    ld = nav_index.lib_dir(root)
    if not os.path.isfile(os.path.join(ld, "meta.json")):
        return jsonify({"ok": False, "err": "该目录没有索引库"}), 400
    with _lock:
        if _state["running"]:
            return jsonify({"ok": False,
                            "err": "已有索引任务在运行（%s）" % _state["root"]}), 409
        _state.update(running=True, phase="切档", log=[], done=False, ok=False,
                      err="", ts=time.time(), result=None, cancel=False,
                      percent=0, cur="", cancelled=False, log_seq=0, root=root)

    def work():
        try:
            meta = nav_index._read_json(os.path.join(ld, "meta.json")) or {}
            db = os.path.join(ld, "tags.db")
            tags_p = os.path.join(ld, "tags")
            if backend == "sqlite":
                _log("切换 sqlite：构建 tags.db（%d 符号，一次性）…"
                     % (meta.get("code_files") or 0))
                n = nav_index._build_tag_db(
                    tags_p, db, say=_log,
                    prog=lambda pct, lab: _state.update(
                        percent=int(pct), cur=lab, phase=str(lab or "sqlite")))
                _log("✓ tags.db：%d 行" % n)
            else:
                if os.path.isfile(db):
                    os.remove(db)
                    _log("已删除 tags.db（%s 模式零额外文件）" % backend)
            meta["backend"] = backend
            meta["backend_auto"] = False
            nav_index._write_json(os.path.join(ld, "meta.json"), meta)
            nav_index._invalidate_cache()
            _state.update(done=True, ok=True, phase="完成",
                          result={"kind": "reindex", "backend": backend})
        except Exception as e:
            _state.update(done=True, ok=False, err=str(e)[:400], phase="失败")
            _log("失败：%s" % e)
        finally:
            _state["running"] = False
            _state["cancel"] = False

    threading.Thread(target=work, daemon=True).start()
    return jsonify({"ok": True})


@nav_bp.route("/api/nav/cg_status")
def nav_cg_status():
    """Claude 代码图（codegraph）状态。?root="""
    from src import nav_codegraph as cg
    root = (request.args.get("root") or "").strip()
    if not root:
        return jsonify({"ok": False, "err": "缺 root"}), 400
    if not _guard(root):
        return jsonify({"ok": False, "err": "目录不在文件树登记根内"}), 400
    return jsonify(cg.status(root))


@nav_bp.route("/api/nav/cg_build", methods=["POST"])
def nav_cg_build():
    """建/重建 Claude 代码图索引。body {root, mode: 'build'|'sync'}
    复用 nav 任务槽（与 ctags 建库互斥——同一时间只跑一种索引）。"""
    from src import nav_codegraph as cg
    d = request.get_json(force=True, silent=True) or {}
    root = str(d.get("root") or "").strip()
    mode = str(d.get("mode") or "build")
    if mode not in ("build", "sync"):
        return jsonify({"ok": False, "err": "mode 只认 build/sync"}), 400
    if not root:
        return jsonify({"ok": False, "err": "缺 root"}), 400
    if not _guard(root):
        return jsonify({"ok": False, "err": "目录不在文件树登记根内"}), 400
    with _lock:
        if _state["running"]:
            return jsonify({"ok": False, "err": "索引任务运行中（%s）" % _state["root"]}), 409
        _state.update(running=True, phase="codegraph", log=[], done=False, ok=False,
                      err="", ts=time.time(), result=None, cancel=False,
                      percent=0, cur="", cancelled=False, log_seq=0, root=root)

    def work():
        def should_cancel():
            return bool(_state.get("cancel"))
        try:
            _state["percent"] = 10
            fn = cg.sync if mode == "sync" else cg.build
            # R27-1（实锤：取消钮假动作）：should_cancel 透传——心跳每拍查，
            # 取消即杀 codegraph 子进程并走取消终态（旧版钮在动作假）
            ok, msg = fn(root, log=_log, should_cancel=should_cancel)
            _state.update(percent=100, done=True, ok=ok,
                          err="" if ok else msg[:400],
                          phase="完成" if ok else "失败",
                          result={"kind": "codegraph", "ok": ok, "msg": msg[:200],
                                  "files": (cg.status(root) or {}).get("files", 0)})
        except cg.CgCancelled:
            _state.update(done=True, ok=False, err="已取消", phase="已取消",
                          cancelled=True)
            _log("用户取消 codegraph")
        except Exception as e:
            _state.update(done=True, ok=False, err=str(e)[:400], phase="失败")
        finally:
            _state["running"] = False
            _state["cancel"] = False

    threading.Thread(target=work, daemon=True).start()
    return jsonify({"ok": True})


@nav_bp.route("/api/nav/cg_delete", methods=["POST"])
def nav_cg_delete():
    """删除工程的 codegraph 索引。body {root}
    R26-4（实锤：缺运行互斥）：build 运行中可删——uninit 与 index 并发
    操作同一 DB。对齐 nav_delete 的 R15-7 防护"""
    from src import nav_codegraph as cg
    d = request.get_json(force=True, silent=True) or {}
    root = str(d.get("root") or "").strip()
    if not root:
        return jsonify({"ok": False, "err": "缺 root"}), 400
    if not _guard(root):
        return jsonify({"ok": False, "err": "目录不在文件树登记根内"}), 400
    with _lock:
        if _state["running"]:
            return jsonify({"ok": False, "err": "索引任务运行中，稍后再删"}), 409
    ok, msg = cg.remove(root)
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
    scope = (request.args.get("scope") or "").strip()   # a383：file=文件内符号（Ctrl+Shift+O）
    if not f:
        return jsonify({"ok": False, "err": "缺 file"}), 400
    try:
        return jsonify(nav_index.symbols(f, q, limit if scope != "file" else 500, scope=scope))
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
