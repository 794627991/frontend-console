# -*- coding: utf-8 -*-
"""代码跳转索引 API（a333 批1）。蓝图 nav_bp——就近注册（server.py）。

任务槽复刻 res_api 形态（状态独立、单任务、poll 轮询、协作式取消、
seq 日志）；查询端点无状态直答。门卫：索引根必须在文件树登记根内
（_under_roots + _under_roots_real，与 tree 系 API 同源）。"""
import json
import os
import re
import threading
import time
import uuid

from flask import Blueprint, jsonify, request

nav_bp = Blueprint("nav", __name__)

_lock = threading.Lock()
_state = {"running": False, "phase": "", "log": [], "done": False,
          "ok": False, "err": "", "ts": 0.0, "result": None, "cancel": False,
          "percent": 0, "cur": "", "cancelled": False, "log_seq": 0,
          "root": "", "importing": False, "reason": "", "scope_saved": None}

# ---- a570：推荐器任务槽（独立于建库，可同时进行）------------------------
_rec_lock = threading.Lock()
# a570 对抗审计（P1·第十六轮）：推荐槽硬上界。recommend_scope 内部每个顶层
# 目录 300s 超时、逐个判定，正常最坏也就是「目录数×300s」——这里按全局
# 上界兜底，防止单次 scandir 卡死把槽永久占住（cancel 后 30s 也放行）。
_REC_GUARD = 1800.0
_REC_CANCEL_GRACE = 30.0
_REC_GUARD_TICK = 5.0        # 守护线程巡检间隔（测试可调小以快速触发）
_rec_state = {"running": False, "phase": "", "done": False, "ok": False,
              "err": "", "root": "", "root_key": "", "cancel": False,
              "percent": 0, "cur": "", "total": 0, "result": None,
              "ts": 0.0, "run_id": ""}


def _scope_fingerprint(sc):
    """范围配置的语义指纹（用于判断「是否真的覆盖了旧配置」）。
    a570 对抗审计（P2·第十七轮）：mode/arch 也要 lower——`MANUAL` 与
    `manual` 是同一个配置，原来会误判成「被覆盖」并白写备份。"""
    sc = sc or {}
    return (str(sc.get("mode") or "manual").strip().lower(),
            str(sc.get("arch") or "auto").strip().lower(),
            tuple(sorted((str(k).lower(), str(v).lower())
                         for k, v in (sc.get("dirs") or {}).items())),
            tuple(sorted(str(x).lower()
                         for x in (sc.get("artifact_roots") or []))),
            tuple(sorted(str(x).lower()
                         for x in (sc.get("exclude_names") or []))))


def _backup_scope_if_overwrite(root, scope):
    """a570 对抗审计（P1·第十六轮）：前端「全量/白名单」档直接发 scope 载荷，
    同样会覆盖工程根已有三态配置。覆盖前把原有配置备份到 `.prev.bak`
    （已有备份不覆盖，保住用户最初那份）。返回要写进日志的提示；无覆盖返回 ""。

    a570 对抗审计（P2·第十七轮）：判据必须覆盖**全部**语义字段——原来只比
    mode+dirs，于是「三态树确认」把 artifact_roots/exclude_names 清空时
    既不备份也不告警（实测）。
    """
    import shutil as _sh
    from src import nav_index
    try:
        _sp = os.path.join(root, nav_index.SCOPE_FILE)
        if scope is None or not os.path.isfile(_sp):
            return ""
        _old_sc, _old_src = nav_index.load_scope(root)
        if _old_src != "project":
            return ""
        _old_sc = _old_sc or {}
        if not ((_old_sc.get("dirs") or {}) or (_old_sc.get("artifact_roots") or [])
                or (_old_sc.get("exclude_names") or [])
                or _old_sc.get("mode") in ("whitelist", "full")):
            return ""
        # 语义等价不算覆盖——避免每次重建都白写备份
        if _scope_fingerprint(_old_sc) == _scope_fingerprint(scope):
            return ""
        _bak = _sp + ".prev.bak"
        if os.path.isfile(_bak):
            return ""
        _sh.copy2(_sp, _bak)
        return ("⚠ 已有三态配置被新范围覆盖，旧配置备份在 %s.prev.bak"
                % nav_index.SCOPE_FILE)
    except Exception:
        return ""


def _log(msg):
    """a424（用户令：同类日志不许刷屏，只占同一行）：按「进度行键」合并。

    进度类消息用 `\\r` 前缀标记为可覆盖行——同键的后续消息**原地替换**
    最后一条，而不是追加。前端按 seq 变化就地更新那一行。
    键 = 去掉末尾数字/百分比后的稳定前缀（如「产物源扫描中」「递归 include」）。
    非进度消息（阶段头、告警、完成）照常追加。"""
    msg = str(msg)
    with _lock:
        _state["log_seq"] += 1
        _seq = _state["log_seq"]
        _key = _progress_key(msg)
        _lg = _state["log"]
        if _key:
            _last = _state.get("_prog_row") or {}
            _idx = _last.get(_key)
            if _idx is not None and 0 <= _idx < len(_lg) \
                    and _lg[_idx].get("key") == _key:
                _lg[_idx] = {"t": time.time(), "msg": msg,
                             "seq": _seq, "key": _key}
                # 原地替换 + 后端给旧位置换新 seq，前端写盘时要把它搬到末尾，
                # 让日志按 seq 递增（与后端数组顺序一致）——否则 poll 响应里
                # 数组顺序是后端顺序、seq 却乱序，任何「seq > 上次」的增量
                # 遍历都会跳过该行之后的全部新条目。
                _row = _lg.pop(_idx)
                _lg.append(_row)
                for _k, _i2 in list(_state.get("_prog_row", {}).items()):
                    if _i2 > _idx:
                        _state["_prog_row"][_k] = _i2 - 1
                _state["_prog_row"][_key] = len(_lg) - 1
                return
        _lg.append({"t": time.time(), "msg": msg, "seq": _seq, "key": _key})
        if _key:
            _state.setdefault("_prog_row", {})[_key] = len(_lg) - 1
        # 裁剪会移动下标——重置进度行索引（下一次退化为追加，可接受）。
        # a434：记录被裁掉的最后一条 seq——前端据此判断自己是否漏了日志
        # （进度行原地替换也会消耗 seq，只比对 log_seq 会把合并误判成丢失）
        if len(_lg) > 400:
            _cut = len(_lg) - 400
            _state["log_dropped"] = _lg[_cut - 1]["seq"]
            del _lg[:_cut]
            _state["_prog_row"] = {}


# 进度行识别：这些前缀的消息视为「同一行刷新」
_PROG_PREFIXES = (
    "产物源扫描中", "扫描中：", "单元推导", "编译参数提取", "递归 include",
    "同目录头文件补收", "写文件清单", "指纹扫描中", "白名单映射",
    "读符号表", "sqlite 导入", "扫描等待",
)
_PROG_NUM_RE = re.compile(r"\d[\d.,:/%]*")


def _progress_key(msg):
    """进度行键：把数字统一替换成 #，同类进度得到稳定键（原地刷新）。
    「单元推导 ① … 100/4425」与「单元推导 ① … 200/4425」同键；
    ①/②/③ 因文案不同而分键。"""
    s = msg.strip()
    if not any(s.startswith(p) for p in _PROG_PREFIXES):
        return ""
    return _PROG_NUM_RE.sub("#", s)[:48]


def _guard(path):
    """索引/管理目标必须在文件树登记根内（防任意目录索引）。

    a570 对抗审计：相对/盘符相对形态（`C:foo`）不加 isabs 前置检查会经
    `_under_roots` 里的 abspath 按 CWD 补全后落到登记根内，对用户没指定的
    目录做状态探测/建图/删除。这里统一先拒非绝对路径。
    """
    if not isinstance(path, str) or not path.strip():
        return False
    if not os.path.isabs(path):
        return False
    from src.file_tree import _under_roots, _under_roots_real
    return _under_roots(path) and _under_roots_real(path)


@nav_bp.route("/api/nav/scope_tree")
def nav_scope_tree():
    """a398：收录范围手选目录树（懒加载一层）。?root=&rel=
    返回 {ok, dirs:[{name, rel, sub}], files}——sub=是否有子目录（展开箭头）。
    跳过 _SKIP_DIRS/点目录（与建库 walk 同规则——所见即所收）。
    a398（审计#27）：盘符根边界（root=C:\\ 时 normpath 无尾_sep 导致全
    越界）、尾斜杠归一、realpath 防根内符号链接逃逸、条目上限、rel isabs"""
    import os
    from src import nav_index
    root = (request.args.get("root") or "").strip()
    rel = (request.args.get("rel") or "").strip().replace("\\", "/").strip("/")
    if not root:
        return jsonify({"ok": False, "err": "缺 root"}), 400
    if not _guard(root):
        return jsonify({"ok": False, "err": "目录不在文件树登记根内"}), 400
    if rel and (".." in rel.split("/") or rel.startswith("/")
                or ntpath_isabs(rel)):
        return jsonify({"ok": False, "err": "非法子目录"}), 400
    base = os.path.normpath(os.path.join(root, rel.replace("/", os.sep))) \
        if rel else os.path.normpath(root)
    _rn = os.path.normpath(root)
    _rn_p = _rn if _rn.endswith(("\\", "/")) else _rn + os.sep
    if os.path.normpath(base) != _rn and \
            not os.path.normpath(base).startswith(_rn_p):
        return jsonify({"ok": False, "err": "越界"}), 400
    try:
        if os.path.realpath(base).lower() != base.lower() and \
                not os.path.realpath(base).lower().startswith(
                    os.path.realpath(root).rstrip("\\/") .lower() + os.sep) and \
                os.path.realpath(base).lower() != os.path.realpath(root).lower():
            return jsonify({"ok": False, "err": "越界（符号链接）"}), 400
    except OSError:
        pass
    try:
        with os.scandir(base) as it:
            ents = list(it)
    except OSError as e:
        return jsonify({"ok": False, "err": "读取失败：%s" % e}), 400
    dirs, files, _trunc = [], 0, False
    _skip_l = {s.lower() for s in nav_index._SKIP_DIRS}
    # a570 对抗审计（P2·第十八轮）：tmp 类在 walk 里是**无条件硬剪**的，
    # 面板若照常展示、后端还接受显式配置，用户勾了「全」却零文件（实测）。
    # 与 walk 同口径：不展示。
    _tmp_l = {s.lower() for s in nav_index._TMP_NAMES}
    for e in ents:
        try:
            if e.is_dir():
                if e.name.lower() in _skip_l or e.name.lower() in _tmp_l \
                        or e.name.startswith("."):
                    continue
                if len(dirs) >= 800:   # 巨目录封顶（浏览器渲染保护）
                    _trunc = True      # a684-A7：以「确有目录被截」为准
                    continue
                sub = False
                try:
                    with os.scandir(e.path) as it2:
                        # a570 对抗审计（P2·第十九轮）：与展示同口径，
                        # tmp 类也不算「有子目录」——否则展开箭头点了空白。
                        sub = any(x.is_dir() and x.name.lower() not in _skip_l
                                  and x.name.lower() not in _tmp_l
                                  and not x.name.startswith(".") for x in it2)
                except OSError:
                    pass
                dirs.append({"name": e.name,
                             "rel": (rel + "/" + e.name) if rel else e.name,
                             "sub": sub})
            else:
                files += 1
        except OSError:
            continue
    dirs.sort(key=lambda x: x["name"].lower())
    return jsonify({"ok": True, "rel": rel, "dirs": dirs, "files": files,
                    "truncated": _trunc})


def ntpath_isabs(p):
    import ntpath
    return ntpath.isabs(p)


@nav_bp.route("/api/nav/scope_export", methods=["POST"])
def nav_scope_export():
    """导出当前范围配置。

    为什么必须走后端：壳内渲染层 `<a download>` 永远拿不到文件——init.js 在
    捕获阶段对所有 a[href] preventDefault（防就地导航）。另外 status 下发的
    是摘要（无 dirs/arch/exclude_names、artifact_roots 截断 8 条），拿它导出
    会丢配置。这里读工程根真实配置原样写出。

    body {root, path?}：path 是用户在 Electron 壳保存框（fc:save-as）里选定的
    绝对路径，经 app_state.export_target_err 校验（只拦「覆盖工具自身的
    config/凭据/日志」）后按选定路径原样写。不带 path（无壳：浏览器/自动化）
    回落：桌面 → 用户目录，O_EXCL 抢名。
    （2026-11-23 评审修正：此前去找 pywebview 时代的 main._save_file_dialog
    弹保存框，那个函数已随 P4 删除——保存框从未弹出，每次导出都静默落桌面
    并按序号堆文件。）
    不写工程根——那是运行时配置位，导出是给用户备份用的副本。
    """
    import os
    from src import nav_index
    from src import app_state as _st
    d = request.get_json(force=True, silent=True) or {}
    root = str(d.get("root") or "").strip()
    if not root or not os.path.isabs(root):
        return jsonify({"ok": False, "err": "root 须为绝对路径"}), 400
    if not _guard(root):
        return jsonify({"ok": False, "err": "目录不在文件树登记根内"}), 400
    sc, src = nav_index.load_scope(root)
    if not sc:
        return jsonify({"ok": False,
                        "err": "工程根没有可导出的范围配置（%s）——先用三态树"
                               "确认一次并建库，或导入 JSON" % (src or "未配置")}), 400
    body = json.dumps({k: sc.get(k) for k in
                       ("version", "name", "mode", "arch", "dirs",
                        "artifact_roots", "exclude_names")},
                      ensure_ascii=False, indent=2)
    fn = "fcpk-scope-%s.json" % (os.path.basename(root.rstrip("\\/")) or
                                 "project")
    path = str(d.get("path") or "").strip()
    if path:
        _perr = _st.export_target_err(path)
        if _perr:
            return jsonify({"ok": False, "err": _perr}), 400
        _picked = True
    else:
        _picked = False
        # 回落：桌面 → 用户目录
        try:
            home = os.path.expanduser("~")
            desk = os.path.join(home, "Desktop")
            base = desk if os.path.isdir(desk) else home
        except Exception:
            base = os.getcwd()
        path = os.path.join(base, fn)
    try:
        if _picked:
            # 用户已在保存框里确认过位置（含覆盖已有文件）
            with open(path, "w", encoding="utf-8") as f:
                f.write(body)
        else:
            # 自动路径：O_EXCL 抢名，避免并发导出相互覆盖
            stem, ext = os.path.splitext(path)
            cur = path
            for i in range(200):
                try:
                    with open(cur, "x", encoding="utf-8") as f:
                        f.write(body)
                    break
                except FileExistsError:
                    cur = "%s-%d%s" % (stem, i + 1, ext)
            else:
                raise OSError("同名文件过多")
            path = cur
    except OSError as e:
        return jsonify({"ok": False, "err": "写入失败：%s" % e}), 500
    return jsonify({"ok": True, "path": path,
                    "bytes": len(body.encode("utf-8"))})


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
    backend = str(d.get("backend") or "auto").strip().lower()   # a369 三档
    # a393（用户令：不允许全量方案）：memory 显式拒绝给明确反馈
    if backend == "memory":
        return jsonify({"ok": False, "err": "全量内存模式已下线"
                        "（600 万符号 ≈8GB 常驻实锤），请用 readtags 或 sqlite"}), 400
    if backend not in ("auto", "readtags", "sqlite"):
        backend = "auto"
    if not os.path.isabs(root):   # D-5（P4）：类型混淆/相对形态以 CWD 解析落登记根——垃圾任务真实启动
        return jsonify({"ok": False, "err": "root 须为绝对路径"}), 400
    if not root:
        return jsonify({"ok": False, "err": "缺 root"}), 400
    if not _guard(root):
        return jsonify({"ok": False, "err": "目录不在文件树登记根内"}), 400
    if not os.path.isdir(root):   # FD-2 终审（P4）：D-5 只落了 isabs 半截——不存在的绝对路径仍真启动任务
        return jsonify({"ok": False, "err": "目录不存在：%s" % root[:120]}), 400
    # a390：显式点 sql 档但环境无 sqlite3（旧版 exe 打包缺件）——早拒说人话，
    # 不让任务跑到阶段 4 才"构建失败"吓人（auto 由 build 内部自动降 readtags）
    if backend == "sqlite" and not nav_index.sqlite_capable():
        return jsonify({"ok": False, "err": "本程序未内置 sqlite3 模块"
                        "（旧版打包缺件，升级新版修复；readtags 模式查询速度相近）"}), 400
    # a398：收录范围（档B）。a398（审计#11）：校验/互斥全过之后再处理
    # scope 三参数（原 409 拒绝时 scope.json 已被删）。scope=dict 内联配置
    # （UI 导入 JSON/手选目录）建库成功后落独立存储位（复用）；scope_tier=
    # 用已发现配置强制档位；scope_clear=清已存范围（回全量）
    # a415R2 BUG-E2：scope 传了但不是对象=显式 400（原静默当没传=整根全量）
    if d.get("scope") is not None and not isinstance(d.get("scope"), dict):
        return jsonify({"ok": False, "err": "scope 必须是 JSON 对象"}), 400
    scope = d.get("scope") if isinstance(d.get("scope"), dict) else None
    # a570 对抗审计（P1·第十九轮）：任务占用必须在**任何写操作之前**判一次。
    # 原顺序虽是「先判 → 备份 → 再判」，但中间那段写操作（备份/clear）与
    # 第二处锁的窗口里，别的请求可以抢到槽——于是被拒的请求已经写下了
    # `.prev.bak`（用户真正覆盖时拿不到告警）甚至删掉了配置。这里先做一次
    # 纯读预检，锁内那次保留作最终裁决。
    with _lock:
        if _state["running"]:
            return jsonify({"ok": False,
                            "err": "已有索引任务在运行（%s）" % _state["root"]}), 409
        if _state["importing"]:
            return jsonify({"ok": False, "err": "nm 清单导入进行中，稍后再建"}), 409
    # a570 对抗审计（P0·第四轮）：档位展开与配置备份**必须在 _lock 之外**做。
    # 原实现在 `with _lock:` 内调 `_log`（它自己又 `with _lock:`）——
    # `threading.Lock` 不可重入 ⇒ 请求线程自锁并永久持有 _lock，此后所有
    # nav 端点（poll/status/cancel/delete/tier）全部阻塞，功能整体瘫痪。
    # 顺带把磁盘 I/O（load_scope/copy2/detect_scope 多次 scandir）也移出
    # 锁——SMB 工程根上可达秒级。
    _prev_bak_msg = ""
    # a570 对抗审计（P1·第十六轮）：备份不能只挂在 scope_tier 分支上。
    # 前端「全量/白名单」档是直接发 scope 载荷的（nav.js _scopeSel），
    # 同样会覆盖工程根已有的精细三态配置，却既无备份也无告警。
    if scope is None and d.get("scope_tier") in ("whitelist", "full"):
        # a570：v2 的档位就是 mode。scope_tier 只用于「一键档位」入口。
        # 这会**覆盖**工程根已有的精细三态配置并落盘（save_scope 对 v2→v2
        # 不备份），用户原有 dirs 不可恢复。覆盖前先备份到 `.prev.bak`。
        # a570 对抗审计（P1·第十八轮）：判据必须复用 _backup_scope_if_overwrite
        # 的完整指纹——原来只认 `dirs`，含 artifact_roots/exclude_names 的
        # 有效配置（detect_scope 产出的 mode=whitelist 形态）被静默覆盖。
        _sc_d = {"version": 2,
                 "name": "%s 档" % ("白名单" if d["scope_tier"] == "whitelist"
                                    else "全量"),
                 "mode": d["scope_tier"], "arch": "auto",
                 "dirs": {}, "artifact_roots": [], "exclude_names": []}
        if d["scope_tier"] == "whitelist":
            # 白名单档需要产物源（sbuilder 等），走一次形态检测
            try:
                _det, _dk = nav_index.detect_scope(root)
                if _det:
                    _sc_d["artifact_roots"] = _det.get("artifact_roots") or []
                    # a570 对抗审计（P1·第四轮）：detect_scope 现在还会给
                    # dirs（sbuilder/output=off）。原实现只复制 artifact_roots
                    # 就丢弃了它 —— sbuilder/output/host 的 3.9 万源文件整棵
                    # 进索引，且这份 scope 会被落盘成「合法」的长期配置。
                    _sc_d["dirs"] = dict(_det.get("dirs") or {})
                    # mode=whitelist 时全树统一，带 dirs 会被 _norm_scope_v2
                    # 拒绝 → 改用 manual（语义等价：根默认 white + 显式 off）
                    if _sc_d["dirs"]:
                        _sc_d["mode"] = "manual"
                    _sc_d["name"] = _det.get("name") or _sc_d["name"]
            except Exception:
                pass
        scope = _sc_d
    # a570 对抗审计（P1·第十九轮）：**先占槽，再做任何写操作**。
    # 备份与 clear 原先排在两处 409 检查之间——被拒的请求已经写出
    # `.prev.bak`（用户真正覆盖时拿不到告警），甚至删掉了工程根配置。
    _cleared_only = False
    with _lock:
        if _state["running"]:
            return jsonify({"ok": False,
                            "err": "已有索引任务在运行（%s）" % _state["root"]}), 409
        if _state["importing"]:
            return jsonify({"ok": False, "err": "nm 清单导入进行中，稍后再建"}), 409
        if d.get("scope_clear") and scope is None:
            # a570 对抗审计（P2·第二十轮）：清除也必须占槽——否则它与并发
            # build 无互斥：用户被告知「已清除」，实际被随后落盘的配置覆盖。
            _cleared_only = True
            # 2026-11-23 总审计 a684-A9：轻量 reset 也清「上一次任务的结论」
            # ——留着 result/reason 时，终态 poll 会带着旧建库结果返回，全靠
            # 前端分支碰巧先判 cleared 才不串台。
            _state.update(running=True, phase="清除范围", root=root,
                          done=False, ok=False, err="", cancel=False,
                          result=None, reason="", cancelled=False,
                          scope_saved=None)
        else:
            _state.update(running=True, phase="准备", log=[], _prog_row={}, ask_tier=None, log_dropped=0, done=False, ok=False,
                          err="", ts=time.time(), result=None, cancel=False,
                          percent=0, cur="", cancelled=False, log_seq=0, root=root,
                          reason="", scope_saved=None)
    # a570 对抗审计（P2·第十六轮）：`scope_clear` 的 isfile/remove 是 SMB
    # 往返，原在 `_lock` 内做——并发 poll 被阻塞近 2 秒（实测）。
    # a570 对抗审计（P2·第十七轮）：删除同样要先备份——`.prev.bak` 机制
    # 原来只接「覆盖」不接「清除」，用户点红字按钮后精细三态配置不可恢复。
    _clr_err = ""
    if d.get("scope_clear"):
        try:
            _sp = os.path.join(root, nav_index.SCOPE_FILE)
            if os.path.isfile(_sp):
                import shutil as _sh
                _bak = _sp + ".prev.bak"
                if not os.path.isfile(_bak):
                    _sh.copy2(_sp, _bak)
                os.remove(_sp)
        except OSError as _e:
            # 2026-11-23 复核 a684-A9 时发现：原为 `except OSError: pass`——
            # 文件被占用（编辑器开着 .fcpk-scope.json）时删除失败，仍返回
            # ok/cleared，用户看到「已清除」而工程根配置还在。如实上报。
            _clr_err = "已存范围删除失败（%s）" % _e
        if _cleared_only:
            with _lock:
                _state.update(running=False, done=True, ok=not _clr_err,
                              phase="已完成" if not _clr_err else "清除失败",
                              err=_clr_err)
            if _clr_err:
                return jsonify({"ok": False, "err": _clr_err}), 500
            return jsonify({"ok": True, "cleared": True})
    # 备份必须用最终载荷（scope_tier 分支可能补出 detect 的 artifact_roots）
    if scope is not None:
        _prev_bak_msg = _backup_scope_if_overwrite(root, scope)
    # a570 对抗审计（P1·第四轮）：备份提示必须在 reset 之后写——否则会被
    # 上面那句 `log=[]` / `log_seq=0` 清掉，用户永远看不到。
    if _prev_bak_msg:
        _log(_prev_bak_msg)

    def should_cancel():
        return bool(_state.get("cancel"))

    def on_prog(pct, total, label):
        _state.update(percent=int(pct), cur=label or "",
                      phase=str(label or "处理中"))

    def ask_tier(info):
        """a431→a570：白名单覆盖率偏低时暂停，等用户在弹窗里选建库方式。
        返回 "full" | "whitelist" | "reconfigure" | "cancel"。

        a570（定稿 §九）：新增 reconfigure——用户在树上重新配置。它复用
        取消路径（Cancelled(reason="reconfigure")），前端据 reason 不显示
        「已取消」而直接打开三态树。

        a432：不能用裸 evt.wait()——用户点「取消」或关掉面板时没有任何
        路径能唤醒它，建库线程会永久挂起（running 状态卡死，下次建库被拒）。
        改分片轮询：0.2s 一轮，同时检查 should_cancel；超时兜底 10 分钟。"""
        _ask = {"evt": threading.Event(), "choice": None, "info": info}
        with _lock:
            _state["ask_tier"] = _ask
        _state.update(phase="等待选择建库方式")
        _t0 = time.time()
        try:
            while not _ask["evt"].wait(0.2):
                if should_cancel():
                    break
                if time.time() - _t0 > 600:      # 10 分钟无人应答 → 按全量继续
                    _log("等待建库方式选择超时（10 分钟），按全量收源码继续")
                    break
        finally:
            # a452（审计 P2）：清空必须走 finally——等待期间线程被异常打断
            # 时若不执行，ask_tier 会残留非空，poll 持续下发数据、/api/nav/tier
            # 持续返回 200，前端弹窗反复出现，直到下一次建库才被 reset。
            with _lock:
                _state["ask_tier"] = None
        if should_cancel():
            return "cancel"
        _c = _ask["choice"] or "full"
        if _c not in ("full", "whitelist", "reconfigure", "cancel"):
            _c = "full"
        return _c

    def work():
        try:
            nav_index._close_tagdb()   # S37-2（P2）：与 reindex 对齐——查询过的库
                                       # 持有 tags.db 连接，阶段 4 os.replace 撞
                                       # WinError 5 → 静默降级 readtags + tmp 残留
            # a570（定稿 §九）：ask_tier 只在**首次建库**触发——已有配置
            # 时零单元/低覆盖一律自动降级 + 汇总告警，不重复打扰。
            # a570 对抗审计：判据必须是「有**可用的 v2** 配置」，不能只判
            # 文件存在——工程根挂着 v1 旧配置时 build 会当无配置重新生成，
            # 但这里会误判成「非首次」而丢掉四选一，用户从旧版升级后静默
            # 全量收录。
            _sc_cur, _sc_src = nav_index.load_scope(root)
            # a570 对抗审计：`bad:*`（配置损坏）不能算「首次」——否则每次
            # 建库都弹四选一。首次的语义是「从未配置过」：空源 或 v1 旧格式。
            # a570 对抗审计（P1·第四轮）：本次显式给了 scope（三态树/导入）
            # 时绝不能再弹四选一——用户刚确认过范围，再问一次「要不要全量」
            # 并可能推翻他的配置。也避免 bad:* 时静默按 full 收（用户刚手改
            # 坏配置，正是最该给选择权的时候）。
            _is_first = (scope is None) and (
                _sc_src in ("", "v1-deprecated") or _sc_src.startswith("bad:"))
            res = nav_index.build(root, log=_log, progress=on_prog,
                                  should_cancel=should_cancel,
                                  backend=backend, scope=scope,
                                  ask_tier=(ask_tier if _is_first else None))
            # 建库**成功后**才落盘范围，且只写工程根（方案 A）。写失败不抛
            # ——工程根只读时不能因此让建库算失败。
            # a570 对抗审计：写失败要明确告诉用户「配置没保存」，否则下次
            # 建库又回到首次询问且配置丢失，用户毫无感知。
            _sc_saved = None          # None = 本次没指定范围（读了已有配置）
            if scope is not None:
                # a570 对抗审计（P0·第十六轮）：必须落盘 **build 实际用的** 范围。
                # build 内部零产物/低覆盖会降级（sc["mode"]="full"），原实现
                # 却拿调用方原始的 boost scope 落盘 → 磁盘仍是 whitelist，
                # 下次建库静默把范围收窄（实测 50 文件缩到 2 个）。
                _eff = res.get("scope") if isinstance(res, dict) else None
                _eff = ({k: _eff.get(k) for k in
                         ("version", "name", "mode", "arch", "dirs",
                          "artifact_roots", "exclude_names")}
                        if isinstance(_eff, dict) else scope)
                _ok_sc, _sc_n = nav_index._norm_scope(_eff, root)
                _sc_saved = False
                if _ok_sc:
                    # a570 对抗审计（P1·第十七轮）：判据必须两边都归一后再比。
                    # 原来拿**未归一**的原始 scope（磁盘真实大小写 `Kernel`）
                    # 比归一后的 `_sc_n`（`kernel`），同配置也误报「被调整」。
                    _ok0, _sc0 = nav_index._norm_scope(scope, root)
                    _changed = (not _ok0) or (
                        _scope_fingerprint(_sc0) != _scope_fingerprint(_sc_n))
                    if _changed:
                        _log("· 本次收录范围在建库中被调整（%s）——已按实际范围落盘"
                             % _sc_n.get("name"))
                    _w_ok, _w_err = nav_index.save_scope(root, _sc_n)
                    if not _w_ok:
                        _log("⚠ 收录范围未能写入工程根（%s）——本次建库已生效，"
                             "但下次建库需重新配置" % _w_err)
                    else:
                        _sc_saved = True
            _state.update(done=True, ok=True, result=res, phase="完成",
                          scope_saved=_sc_saved)
        except nav_index.Cancelled as _ce:
            # a570：区分「真取消」与「用户要重新配置」——后者前端直接开三态树
            _rc = getattr(_ce, "reason", "") or ""
            if _rc == "reconfigure":
                _state.update(done=True, ok=False, err="需要重新配置收录范围",
                              phase="重新配置", cancelled=True,
                              reason="reconfigure")
                _log("用户选择重新配置收录范围")
            else:
                _state.update(done=True, ok=False, err="已取消", phase="已取消",
                              cancelled=True, reason=_rc)
                _log("用户取消索引")
        except Exception as e:
            _state.update(done=True, ok=False, err=str(e)[:400], phase="失败")
            _log("失败：%s" % e)
        finally:
            _state["running"] = False
            _state["cancel"] = False

    # a570 对抗审计（P1·第二十轮）：线程启动失败（线程耗尽）时 `work()` 永不
    # 执行，`running` 会永久 True——此后所有 nav 端点都只拿到 409。这里回滚。
    try:
        threading.Thread(target=work, daemon=True).start()
    except Exception as e:
        with _lock:
            _state.update(running=False, done=True, ok=False,
                          err="任务启动失败：%s" % str(e)[:200], phase="失败")
        return jsonify({"ok": False, "err": "任务启动失败：%s" % str(e)[:200]}), 500
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
                        # a570：区分「真取消」与「需要重新配置收录范围」
                        "reason": _state.get("reason") or "",
                        "log_seq": _state["log_seq"], "root": _state["root"],
                        # a426：任务启动时刻（前端独立计时器基准——关面板
                        # 重开后仍能显示真实已用时间，而非从 0 重数）
                        "started": _state.get("ts") or 0,
                        # a431：等待用户选择建库方式时的数据（无则 null）
                        "ask_tier": (_state.get("ask_tier") or {}).get("info"),
                        # a434：已被裁剪的日志最大 seq——前端据此提示省略
                        "log_dropped": _state.get("log_dropped") or 0,
                        # a570：范围是否已落盘（None=本次没指定；False=写失败）
                        "scope_saved": _state.get("scope_saved")})


@nav_bp.route("/api/nav/tier", methods=["POST"])
def nav_tier():
    """a431→a570：用户对「白名单覆盖率偏低」弹窗的选择。body {choice}：
    full=全量收源码 / whitelist=只收白名单 / reconfigure=返回树上重新配置
    （复用取消路径，前端据 Cancelled.reason 区分）/ cancel=放弃建库。"""
    d = request.get_json(force=True, silent=True) or {}
    choice = str(d.get("choice") or "").strip().lower()
    if choice not in ("full", "whitelist", "reconfigure", "cancel"):
        return jsonify({"ok": False, "err": "choice 必须是 "
                        "full / whitelist / reconfigure / cancel"}), 400
    with _lock:
        _ask = _state.get("ask_tier")
        if not _ask:
            return jsonify({"ok": False, "err": "当前没有待选择的建库任务"}), 409
        _ask["choice"] = choice
        if choice == "cancel":
            _state["cancel"] = True
    _ask["evt"].set()
    return jsonify({"ok": True})


@nav_bp.route("/api/nav/scope_recommend", methods=["POST"])
def nav_scope_recommend():
    """a570：推荐器（异步）。body {root, force?}。

    **完整递归统计**（定稿 §11.1），六平台实测 18~48 秒，必须给进度。
    任务槽独立于建库槽——用户可以在建库进行时先看推荐结果。

    轮询 `/api/nav/scope_recommend_poll`；取消 `/api/nav/scope_recommend_cancel`。

    a570 对抗审计：槽是全局单槽，必须让调用方能**区分「我的任务」与
    「别人的任务」**——否则在 A 工程点开后切到 B 工程，B 会拿到 A 的
    dirs 当自己的建库范围（跨工程污染，静默剪错目录）。
    """
    d = request.get_json(force=True, silent=True) or {}
    root = (d.get("root") or "").strip()
    if not root:
        return jsonify({"ok": False, "err": "缺 root"}), 400
    if not _guard(root):
        return jsonify({"ok": False, "err": "目录不在文件树登记根内"}), 400
    from src import nav_index
    _rk = os.path.normcase(os.path.abspath(root))
    # a570 对抗审计（P2·第十六轮）：force 原本前端发、后端从不读——「重新推荐」
    # 与首次推荐请求完全一样。这里落实语义：force 且槽被**同一工程**占用时
    # 取消旧任务并等它退出，再起新任务；别的工程占用仍返回 409。
    _force = bool(d.get("force"))
    if _force:
        # a570 对抗审计（P2·第十七轮）：等待上界必须不小于取消宽限
        # （_REC_CANCEL_GRACE=30s）——原 10s 会在旧任务硬卡时**必然**先失败
        # 一次，用户得点两遍「重新推荐」。
        _deadline = time.time() + (_REC_CANCEL_GRACE + 10)
        while True:
            with _rec_lock:
                if not _rec_state["running"]:
                    break
                if _rec_state.get("root_key") == _rk:
                    _rec_state["cancel"] = True
                    _i_own = True
                else:
                    _i_own = False
                _busy_root = _rec_state.get("root") or ""
            if not _i_own:
                return jsonify({"ok": False, "busy": True, "same": False,
                                "root": _busy_root,
                                "run_id": _rec_state.get("run_id") or "",
                                "err": "推荐任务进行中（%s）" % _busy_root}), 409
            if time.time() > _deadline:
                return jsonify({"ok": False, "busy": True, "same": True,
                                "root": _busy_root,
                                "err": "旧推荐任务未能及时退出，请稍后重试"}), 409
            time.sleep(0.05)
    with _rec_lock:
        if _rec_state["running"]:
            _busy_root = _rec_state["root"]
            same = os.path.normcase(os.path.abspath(_busy_root)) == _rk
            return jsonify({"ok": False, "busy": True, "same": same,
                            "root": _busy_root,
                            # a570 对抗审计（P2·第十八轮）：前端要据此判断
                            # 这个在途任务是否已被本会话取消过
                            "run_id": _rec_state.get("run_id") or "",
                            "err": "推荐任务进行中（%s）" % _busy_root}), 409
        _rec_state.update(running=True, phase="准备", done=False, ok=False,
                          err="", root=root, root_key=_rk, cancel=False,
                          percent=0, cur="", total=0, result=None,
                          ts=time.time(), run_id=uuid.uuid4().hex)

    with _rec_lock:
        _run_id = _rec_state.get("run_id")

    def should_cancel():
        """本次任务是否该停：显式 cancel，**或本次 run_id 已被作废**（守护
        线程强制释放槽 / 被新任务顶替）。
        （2026-11-23 总审计 P0-2）此前只看 cancel 标志：守护线程强制释放槽时
        没置 cancel，被作废的线程要等自然结束才停——每 top 上限 300s、剩十几个
        top 就是白扫一小时；用户立刻点「重新推荐」时新旧线程并发扫同一棵树。
        只在守护线程里补 cancel=True 还不够：新任务启动会把 cancel 重置，
        旧线程下一个检查点又活了——所以同时比对 run_id。
        必须在**不持 _rec_lock** 时调用（recommend_scope 的工作线程）；持锁处
        直接读字段，否则重入死锁。"""
        with _rec_lock:
            return bool(_rec_state.get("cancel")) or \
                _rec_state.get("run_id") != _run_id

    def on_prog(i, n, label):
        # a570 对抗审计（P1·第十七轮）：进度写回也要校验 run_id——旧任务被
        # 守护线程释放后仍在循环里调 on_prog，会把**新任务**的 cur/phase/
        # percent 改写成旧任务的进度，前端看到的是错的扫描位点。
        with _rec_lock:
            if _rec_state.get("run_id") != _run_id:
                return
            _rec_state.update(percent=int(100.0 * i / max(1, n)),
                              cur=label or "", phase=label or "扫描中",
                              total=n)

    def work():
        # a570 对抗审计（P1·第十六轮）：单次 scandir 卡死在 SMB 上时，
        # 循环头里的 cancel/deadline 检查进不去，`finally` 也永远不执行 →
        # 全局推荐槽 `running` 恒 True，之后任何工程都只能拿到 409。
        # 加一个守护线程：槽被占超过 _REC_GUARD 就强制释放（工作线程
        # 苏醒后会发现自己已不是槽主，结果直接丢弃）。
        _t_start = time.time()

        def _guard_slot():
            _t_cancel = None
            while True:
                time.sleep(_REC_GUARD_TICK)
                with _rec_lock:
                    if not _rec_state.get("running") \
                            or _rec_state.get("run_id") != _run_id:
                        return          # 正常退出（或结果已落地）
                    if _rec_state.get("cancel"):
                        if _t_cancel is None:
                            _t_cancel = time.time()
                        if time.time() - _t_cancel < _REC_CANCEL_GRACE:
                            continue
                    elif time.time() - _t_start < _REC_GUARD:
                        continue
                    _rec_state.update(
                        running=False, done=True, ok=False,
                        err="推荐任务超时（扫描卡住）——已释放任务槽，可重试",
                        phase="失败",
                        # a570 对抗审计（P1·第十七轮）：必须作废本次任务的
                        # run_id——否则旧线程苏醒后 `run_id` 仍相等，会把槽
                        # 改写成「ok=True + 超时错误」的自相矛盾状态。
                        run_id=uuid.uuid4().hex,
                        # 2026-11-23 总审计 P0-2：同时置 cancel——让被作废的
                        # 工作线程在 recommend_scope 的下一个检查点自行退出，
                        # 不再白扫到自然结束。
                        cancel=True)

        threading.Thread(target=_guard_slot, daemon=True).start()
        try:
            res = nav_index.recommend_scope(
                root, progress=on_prog, should_cancel=should_cancel)
            with _rec_lock:
                if _rec_state.get("run_id") != _run_id:
                    return          # 已被守护线程释放，结果作废
                if _rec_state.get("cancel"):     # 持锁中：直接读字段，不调 should_cancel
                    _rec_state.update(done=True, ok=False, err="已取消",
                                      phase="已取消")
                elif not res.get("ok"):
                    _rec_state.update(done=True, ok=False,
                                      err=res.get("err") or "推荐失败",
                                      phase="失败")
                else:
                    _rec_state.update(done=True, ok=True, result=res,
                                      phase="完成", percent=100)
        except nav_index.Cancelled:
            with _rec_lock:
                if _rec_state.get("run_id") == _run_id:
                    _rec_state.update(done=True, ok=False, err="已取消",
                                      phase="已取消")
        except Exception as e:
            with _rec_lock:
                if _rec_state.get("run_id") == _run_id:
                    _rec_state.update(done=True, ok=False,
                                      err=str(e)[:400], phase="失败")
        finally:
            with _rec_lock:
                if _rec_state.get("run_id") == _run_id:
                    _rec_state["running"] = False

    try:
        threading.Thread(target=work, daemon=True).start()
    except Exception as e:
        with _rec_lock:
            _rec_state.update(running=False, done=True, ok=False,
                              err="任务启动失败：%s" % str(e)[:200], phase="失败")
        return jsonify({"ok": False, "err": "任务启动失败：%s"
                        % str(e)[:200]}), 500
    with _rec_lock:
        _new_run = _rec_state.get("run_id") or ""
    return jsonify({"ok": True, "run_id": _new_run, "root": root})


@nav_bp.route("/api/nav/scope_recommend_poll")
def nav_scope_recommend_poll():
    """?root= —— a570 对抗审计：带上 root 才能判断结果是否属于调用方。
    调用方比对 `root` 字段；不一致就丢弃（跨工程污染防护）。"""
    _want = (request.args.get("root") or "").strip()
    _want_k = os.path.normcase(os.path.abspath(_want)) if _want else ""
    with _rec_lock:
        # a570 对抗审计：不传 root 必须判「不属于我」——原 `not _want_k or …`
        # 让任意不带参数的调用方都能读到当前槽里任意工程的结果，隔离失效。
        _mine = bool(_want_k) and _rec_state.get("root_key") == _want_k
        _res = _rec_state["result"] if _mine else None
        return jsonify({"ok": True,
                        "running": _rec_state["running"],
                        "done": _rec_state["done"],
                        "ok_done": _rec_state["ok"] if _mine else False,
                        "err": (_rec_state["err"] if _mine else
                                "推荐任务属于其他工程（%s）" % _rec_state["root"]),
                        "phase": _rec_state["phase"],
                        "percent": _rec_state["percent"],
                        "cur": _rec_state["cur"],
                        "total": _rec_state["total"],
                        "root": _rec_state["root"],
                        "mine": _mine,
                        "result": _res,
                        "run_id": _rec_state.get("run_id") if _mine else "",
                        "started": _rec_state.get("ts") or 0})


@nav_bp.route("/api/nav/scope_recommend_cancel", methods=["POST"])
def nav_scope_recommend_cancel():
    """取消推荐任务。body {root?}。

    a570 对抗审计（P1·第三轮）：槽是全局单槽，不带 root 时会把**别的工程**
    正在跑的推荐取消掉（A 关闭弹层 → B 的扫描白费）。传了 root 就必须
    匹配；不传保持旧行为（兼容脚本/测试）。
    """
    d = request.get_json(force=True, silent=True) or {}
    root = str(d.get("root") or "").strip()
    # a570 对抗审计（P2·第十六轮）：同工程快速关-开弹层时，旧弹层的 cancel
    # 会晚于新任务启动到达（root 相同故校验通过），把新任务误杀。带上
    # run_id（启动时下发）后只取消**它自己那一次**任务。
    _want_run = str(d.get("run_id") or "").strip()
    with _rec_lock:
        if not _rec_state["running"]:
            return jsonify({"ok": False, "err": "没有运行中的推荐任务"}), 409
        # a570 对抗审计（P2·第十七轮）：空 run_id **不能**放行。前端在启动
        # POST 返回前关弹层时会带空串发 cancel，若原样放行，同工程刚启动的
        # 新任务会被误杀（实测 200 且 R2 被取消）。
        if not _want_run:
            return jsonify({"ok": False, "same": False,
                            "err": "缺 run_id——只有持有本次任务凭证的调用方"
                                   "才能取消（防误杀同工程新任务）"}), 400
        if _rec_state.get("run_id") != _want_run:
            return jsonify({"ok": False, "same": False,
                            "err": "运行中的推荐任务不是该次启动的任务"}), 409
        if root:
            _rk = os.path.normcase(os.path.abspath(root))
            if _rec_state.get("root_key") != _rk:
                return jsonify({"ok": False, "same": False,
                                "err": "运行中的推荐任务属于其他工程（%s）"
                                % _rec_state["root"]}), 409
        _rec_state["cancel"] = True
    return jsonify({"ok": True})


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
    if not os.path.isabs(root):   # D-5（P4）：类型混淆/相对形态以 CWD 解析落登记根——垃圾任务真实启动
        return jsonify({"ok": False, "err": "root 须为绝对路径"}), 400
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
    # P-13 干跑补 api 层：文件被外部占用时 rmtree 抛 OSError——不捕获则
    # 500 HTML（原为静默 ok:true 残留，两个极端都不对）
    try:
        return jsonify({"ok": nav_index.delete_lib(root)})
    except OSError as e:
        return jsonify({"ok": False, "err": "部分删除失败（%s）——文件被占用，"
                        "关闭占用程序后重试" % str(e)[:80]}), 500


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
    try:
        ok, msg = nav_index.rebind(old_root, new_root)
        if ok:
            return jsonify({"ok": True, "err": "", "msg": msg})
        return jsonify({"ok": False, "err": msg, "msg": msg}), 400
    except OSError as e:
        # FA-3 终审：rebind 内部有目录改名——文件被占用时抛 OSError 不捕获
        # 则 500 HTML+半迁移孤儿（P-13 delete 同款防御）
        return jsonify({"ok": False, "err": "重关联失败（%s）——文件被占用" % str(e)[:80]}), 500


@nav_bp.route("/api/nav/reindex", methods=["POST"])
def nav_reindex():
    """a369：已建库切换查询后端（不重建 tags）。body {root, backend}"""
    import os
    from src import nav_index
    d = request.get_json(force=True, silent=True) or {}
    root = str(d.get("root") or "").strip()
    backend = str(d.get("backend") or "").strip().lower()
    # a393（用户令：不允许全量方案）：memory 显式拒绝
    if backend == "memory":
        return jsonify({"ok": False, "err": "全量内存模式已下线"
                        "（600 万符号 ≈8GB 常驻实锤），请用 readtags 或 sqlite"}), 400
    if backend not in ("readtags", "sqlite"):
        return jsonify({"ok": False, "err": "backend 须为 readtags/sqlite"}), 400
    # a390：同 build——sqlite 无能力早拒（切换任务同样不该跑到一半失败）
    if backend == "sqlite" and not nav_index.sqlite_capable():
        return jsonify({"ok": False, "err": "本程序未内置 sqlite3 模块"
                        "（旧版打包缺件，升级新版修复；readtags 模式查询速度相近）"}), 400
    if not os.path.isabs(root):   # D-5（P4）：类型混淆/相对形态以 CWD 解析落登记根——垃圾任务真实启动
        return jsonify({"ok": False, "err": "root 须为绝对路径"}), 400
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
        _state.update(running=True, phase="切档", log=[], _prog_row={}, ask_tier=None, log_dropped=0, done=False, ok=False,
                      err="", ts=time.time(), result=None, cancel=False,
                      percent=0, cur="", cancelled=False, log_seq=0, root=root,
                      reason="", scope_saved=None)   # a570 对抗审计：漏 reason 会把上一轮的
                                   # "reconfigure" 残留给无关任务

    def work():
        try:
            # R35 复验终修（S35-2）+FD-1 终审（P1）：定向关目标库（非全量）——
            # 全量关闭与 20 并发线程重建交叠触发 sqlite3 C 层竞态杀进程 3/3。
            # 定向关+busy 让路：其他库不受干扰、目标库窗口内不再建 sqlite 连接
            nav_index._close_tagdb(ld)
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
            # S37-9（P4）：切档后 sizes.db 同步（sqlite 加项/其他档删项）——
            # 面板尺寸双方向失真（虚高 95MB+/虚低 1.2GB）
            _sz = meta.get("sizes") or {}
            _sz.pop("db", None)
            if backend == "sqlite" and os.path.isfile(db):
                _sz["db"] = os.path.getsize(db)
            meta["sizes"] = _sz
            nav_index._write_json(os.path.join(ld, "meta.json"), meta)
            nav_index._invalidate_cache()
            _state.update(done=True, ok=True, phase="完成",
                          result={"kind": "reindex", "backend": backend})
        except Exception as e:
            _state.update(done=True, ok=False, err=str(e)[:400], phase="失败")
            _log("失败：%s" % e)
        finally:
            nav_index._unbusy_tagdb(ld)   # FD-1：解除 busy，恢复 sqlite 查询
            _state["running"] = False
            _state["cancel"] = False

    try:
        threading.Thread(target=work, daemon=True).start()
    except Exception as e:
        with _lock:
            _state.update(running=False, done=True, ok=False,
                          err="任务启动失败：%s" % str(e)[:200], phase="失败")
        return jsonify({"ok": False, "err": "任务启动失败：%s"
                        % str(e)[:200]}), 500
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
        _state.update(running=True, phase="codegraph", log=[], _prog_row={}, ask_tier=None, log_dropped=0, done=False, ok=False,
                      err="", ts=time.time(), result=None, cancel=False,
                      percent=0, cur="", cancelled=False, log_seq=0, root=root,
                      reason="", scope_saved=None)   # a570 对抗审计：同 reindex——防残留

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

    try:
        threading.Thread(target=work, daemon=True).start()
    except Exception as e:
        with _lock:
            _state.update(running=False, done=True, ok=False,
                          err="任务启动失败：%s" % str(e)[:200], phase="失败")
        return jsonify({"ok": False, "err": "任务启动失败：%s"
                        % str(e)[:200]}), 500
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
