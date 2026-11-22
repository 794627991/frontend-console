# -*- coding: utf-8 -*-
"""离线资源状态 / 安装 API（v4.1）。

前端启动后 GET /api/resources/status 拿统一检测结果：
- 换壳 P4 起全部资源均为可选（Node/Git/Claude/OnlyOffice/pydeps 等）——
  hard_missing 恒为空，保留字段只为前端旧结构兼容
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
          "cancel": False, "total": 0, "done_bytes": 0, "cur": "",
          "cancelled": False, "log_seq": 0}

# 包预检缓存：FcpkReader 要跑 PBKDF2 30 万轮（0.1~0.3s），设置页每次
# 选包/重检测都会问一次，按 (path, mtime, size) 缓存
_pkg_cache = {}


def _deps_err():
    """源码模式缺 pycryptodome（Crypto）时的人话降级。fcpk/res_install 靠它
    做包解密；exe 版 PyInstaller 已打包永不进这里。源码分发按 deps_bootstrap
    a356 定调不进自举表（非命脉库——内网无外网机不能卡首启页），缺了在调用
    点给人话，而不是裸 500 让前端 r.json() 炸天书 SyntaxError（用户实锤）。"""
    return jsonify({"ok": False,
                    "err": "本机 Python 缺 pycryptodome 模块，资源包功能不可用。"
                           "请在工具所用 Python 环境执行：pip install pycryptodome"
                           "（装完无需重启，直接重试）"}), 503


def _log(msg):
    # a325R（第2轮对抗审 P2）：原来只截到 400 条，前端用**数组下标**做游标
    # （`for (; seen < lg.length; seen++)`）——一旦超过 400 行，数组长度恒为
    # 400，`seen` 已 ≥ 400 就永不投递，最需要看的尾部（pip 输出、claude
    # --version 失败原因）全部消失，面板像卡死。改为每条带单调 seq，前端按
    # seq 增量投递，绕开"数组被裁剪导致下标失效"。
    _state["log_seq"] = _state.get("log_seq", 0) + 1
    _state["log"].append({"t": time.time(), "seq": _state["log_seq"],
                          "msg": str(msg)})
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
    # 保留硬资源不可忽略的防线（换壳 P4 后 _HARD 为空，规则对空集无操作）
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
    try:
        from src import fcpk
    except ImportError:
        return _deps_err()
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
    """后台装资源包。body: {path, kinds?, force?, mode?: 'online'}

    a322 批2：mode='online' 走在线安装（有网直接装，不要求 path/离线包）；
    在线安装不碰 .fcpk——a595 起它不要求 pycryptodome（res_install 已把
    fcpk 改惰性导入），缺 Crypto 的源码机器靠这条路径装 pydeps 自愈。
    默认（无 mode 或 'offline'）维持原离线包流程不变。两者共用同一任务槽
    与 poll 通道——正在跑时任一模式再点都 409。
    """
    d = request.get_json(force=True, silent=True) or {}
    path = str(d.get("path") or "").strip()
    online = str(d.get("mode") or "offline") == "online"
    try:
        if online:
            from src import res_install
        else:
            from src import fcpk, res_install
    except ImportError:
        return _deps_err()
    # 全审 N4：kinds 的语义必须区分「没传/传 null」和「传了空数组」。
    # `d.get("kinds") or None` 会把 [] 归成 None → 装全部六项，任何误传
    # 空数组的调用方都会得到「全量覆盖」这个最重后果。
    # 注意判定必须是 `is not None` 而不是 `"kinds" in d`：
    # 红条/安装弹窗（resources.js 的 startInstall）恒带 `kinds: null` 表示「全装」，
    # 用 in 判定会把这条并列主路径整个打成 400（复审实打复现）。
    kinds = d.get("kinds")
    if kinds is not None:
        from src.res_install import ORDER as _ORDER
        if not isinstance(kinds, list) or not kinds:
            return jsonify({"ok": False, "err": "未选择任何资源"}), 400
        # 未知 kind 安静滤掉会让用户「点了安装、日志说完成、什么都没装」
        bad = [k for k in kinds if k not in _ORDER]
        if bad:
            return jsonify({"ok": False,
                            "err": "未知资源：%s" % ",".join(map(str, bad))}), 400
    elif online:
        # 在线模式没有「全装」默认（各 kind 网络可用性不一）——必须显式勾选
        return jsonify({"ok": False, "err": "在线安装必须指定 kinds"}), 400
    force = bool(d.get("force"))
    if not online:
        if not path or not fcpk.is_fcpk(path):
            return jsonify({"ok": False, "err": "请选择 .fcpk 资源包"}), 400
        info = fcpk.inspect(path)
        if not info.get("ok"):
            return jsonify({"ok": False, "err": info.get("err") or "资源包无法读取"}), 400
        total0 = info.get("plain_len") or 0
    else:
        total0 = len(kinds)
    with _lock:
        if _state["running"]:
            return jsonify({"ok": False, "err": "已有安装任务在运行"}), 409
        _state.update(running=True, phase="准备", log=[], done=False, ok=False,
                      err="", ts=time.time(), result=None, cancel=False,
                      total=total0, done_bytes=0, cur="",
                      indeterminate=False,
                      cancelled=False, log_seq=0, note="")

    def should_cancel():
        return bool(_state.get("cancel"))

    def on_prog(done_b, total_b, label):
        # a355R（第21轮）：done_b=None 表示不确定进度（跑外部安装器/复制
        # 上万小文件）——百分比没意义，前端按 indeterminate 渲染。
        indet = done_b is None
        _state.update(done_bytes=(0 if indet else int(done_b or 0)),
                      total=(0 if indet else int(total_b or _state["total"] or 0)),
                      cur=label or "",
                      indeterminate=indet,
                      # R8-4：完成态不走「安装 %s」模板（否则显示「安装 完成」）
                      phase=(label if label == "完成" else "安装 %s" % (label or "")))

    def work():
        try:
            if online:
                _state["phase"] = "在线安装"
                res = res_install.install_online(
                    kinds, log=_log, progress=on_prog,
                    should_cancel=should_cancel, force=force)
            else:
                _state["phase"] = "解包安装"
                res = res_install.install_from(
                    path, kinds=kinds, log=_log, progress=on_prog,
                    should_cancel=should_cancel, force=force)
            errs = dict(res.get("errors") or {})
            # a332R（第3轮对抗审 P2-1）：absent 只接进了启动闸门（res_boot），
            # 设置页这条路径没接——选了子集包时 hard 项缺失、errors 为空，
            # 界面照弹"资源包安装完成"，红条刷新后仍在，用户以为装好了。
            # a333R（第4轮 P2-1）：判据从「只看 hard」放宽为「本次请求的项」——
            # 原来只勾 pydeps/node 而两者都 absent 时仍报"完成"；红条全装路径
            # 也会漏掉 soft 项。现在按 MANIFEST 里被请求的 kind 求交集，
            # 文案区分硬/软（硬=装不全不能用，软=相关功能不可用）。
            # a328（第5轮 P1-1，实锤盲区）：全集必须用 res_install.ORDER 而不是
            # MANIFEST——bili 在 ORDER 里但不在 MANIFEST 里（红条也不探测它），
            # 只按 MANIFEST 求交集会把 bili 缺失彻底静默，恰好是本条要修的
            # "一句完成盖过去"。MANIFEST 只用来取中文名，缺名的用 kind 兜底。
            try:
                from src.res_boot import MANIFEST as _MF
                from src.res_install import ORDER as _ORDER
                _absent = set(res.get("absent") or [])
                _name = {m.get("kind"): (m.get("name") or m.get("kind"))
                         for m in _MF}
                _hard = {m.get("kind") for m in _MF if m.get("hard")}
                _absent_all = [k for k in _ORDER if k in _absent]
                _hard_absent = [_name.get(k, k) for k in _absent_all
                                if k in _hard]
                _soft = "、".join(_name.get(k, k) for k in _absent_all
                                  if k not in _hard)
                if _hard_absent:
                    # a335R（第6轮 P2-1）：hard 与 soft 同时缺失时原来只报 hard，
                    # 用户换包后仍不知道 bili/node 等也没进包。软项信息一并带上。
                    _msg = ("所选资源包不含以下必需资源：%s。请换完整的"
                            "「前端控制台-资源包.fcpk」（子集包装不全）"
                            % "、".join(_hard_absent))
                    if _soft:
                        _msg += "；另外也缺（相关功能将不可用）：%s" % _soft
                    errs["资源包不完整"] = _msg
                    _log(_msg)
                elif _soft:
                    # 软项缺失不判失败（非必需，用户可能只想装其中几项），
                    # 但必须如实告知，不能一句"完成"盖过去
                    _state["note"] = "以下资源包内没有，相关功能不可用：%s" % _soft
                    _log(_state["note"])
            except Exception:
                pass
            _state.update(done=True, ok=not errs, result=res,
                          err="; ".join("%s: %s" % kv for kv in errs.items()),
                          phase="完成" if not errs else "部分失败")
        except res_install.InstallCancelled:
            _state.update(done=True, ok=False, err="已取消安装", phase="已取消",
                          cancelled=True)
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


@res_bp.route("/api/resources/net_check")
def res_net_check():
    """a322 批2：在线安装预检——前端禁用态依据。缓存 60s。

    a595R（审计 #4）：镜像感知后探测面变宽（6 kind × 候选首尾），全断
    网络最坏 ~2 分钟——不能再在 Flask handler 里同步跑。改 singleflight：
    首个请求起后台线程探测，并发请求等同一轮（≤25s）；没跑完回 pending
    空表（autoInstall 据此跳过本次、下次打开再试）。世代号防旧档结果
    覆盖改档后的缓存（mirror POST 递增）。
    """
    import time as _t
    with _lock:
        cached = _state.get("net_check")
        if cached and _t.time() - cached[0] < 60:
            return jsonify({"ok": True, "net": cached[1], "cached": True})
        th = _state.get("net_check_th")
        if not (th and th.is_alive()):
            th = threading.Thread(target=_net_check_worker, daemon=True)
            _state["net_check_th"] = th
            th.start()
    th.join(timeout=25)
    with _lock:
        cached = _state.get("net_check")
    if cached:
        return jsonify({"ok": True, "net": cached[1], "cached": False})
    return jsonify({"ok": True, "net": {}, "pending": True, "cached": False})


def _net_check_worker():
    """后台探测一轮 net_check（singleflight 专用）。世代号不匹配（探测
    途中镜像档被改）则丢弃结果，防旧档口径污染新档缓存。"""
    import time as _t
    try:
        from src.res_install import net_check as _nc
    except ImportError:
        return
    with _lock:
        gen = _state.get("net_check_gen", 0)
    net = _nc()
    with _lock:
        if _state.get("net_check_gen", 0) == gen:
            _state["net_check"] = (_t.time(), net)


@res_bp.route("/api/resources/mirror", methods=["GET"])
def res_mirror_get():
    """当前镜像档位 + 可选清单（设置页「镜像加速」下拉的数据源）。"""
    from src import mirrors
    return jsonify({"ok": True, "mode": mirrors.mode(),
                    "desc": mirrors.describe(), "options": mirrors.options()})


@res_bp.route("/api/resources/mirror", methods=["POST"])
def res_mirror_set():
    """切换镜像档位（用户自选镜像加速）。body: {mode}
    保存进 config.json 的 online_mirror 键，在线安装/net_check 下一次调用
    即按新档解析（无需重启）；net_check 的 60s 缓存当场作废。"""
    from src import mirrors
    from src.app_state import _load_config, _save_config
    d = request.get_json(force=True, silent=True) or {}
    m = str(d.get("mode") or "").strip()
    if m not in mirrors.mode_ids():
        return jsonify({"ok": False,
                        "err": "未知镜像档位：%s" % (m or "(空)")}), 400
    try:
        _save_config({**_load_config(), "online_mirror": m})
    except Exception as e:
        return jsonify({"ok": False, "err": "保存配置失败：%s" % e}), 500
    with _lock:
        _state.pop("net_check", None)
        # 世代号递增：在跑的旧档探测线程收尾时自检不匹配 → 丢弃结果
        _state["net_check_gen"] = _state.get("net_check_gen", 0) + 1
    return jsonify({"ok": True, "mode": m, "desc": mirrors.describe()})


@res_bp.route("/api/resources/latest")
def res_latest():
    """a322 批3：claude 在线升级检查。npm registry JSON 直查（不依赖 npm
    命令，秒回）；current 零进程开销读本机 package.json（d05df34 同款）。
    upgradable = latest 严格大于 current（semver 分段数字比较）。"""
    kind = request.args.get("kind", "claude")
    if kind != "claude":
        return jsonify({"ok": False, "err": "暂只支持 claude 的在线升级检查"}), 400
    from src.claude_setup import _pkg_version, _claude_pkg_dir
    import os as _os
    import subprocess as _sp
    # R8-3（实锤：current 读到打包镜像）：_claude_pkg_dir 优先 offline_assets
    # 离线镜像——升级判断必须以「本机 npm 实装」为基准（实装已新仍弹升级/
    # 实装落后却显示已是最新，双向误判）。镜像只在实装缺失时兜底
    current = ""
    for c in (_os.path.join(_os.environ.get("APPDATA", ""), "npm",
                            "node_modules", "@anthropic-ai", "claude-code"),):
        v = _pkg_version(c)
        if v:
            current = v
            break
    if not current:
        try:   # npm prefix 自定义过的机器
            out = _sp.check_output(["npm", "root", "-g"], text=True,
                                   stderr=_sp.DEVNULL, timeout=15).strip()
            if out:
                v = _pkg_version(_os.path.join(out, "@anthropic-ai",
                                               "claude-code"))
                if v:
                    current = v
        except Exception:
            pass
    if not current:
        current = _pkg_version(_claude_pkg_dir())
    latest, err = "", ""
    try:
        import json as _json
        import urllib.request
        req = urllib.request.Request(
            "https://registry.npmjs.org/@anthropic-ai/claude-code/latest",
            headers={"User-Agent": "fc-upgrade-check"})
        with urllib.request.urlopen(req, timeout=10) as r:
            latest = (_json.load(r) or {}).get("version") or ""
    except Exception as e:
        err = "查询 npm registry 失败（%s）——无网/被拦时请用离线包升级" % str(e)[:100]

    def _vt(v):
        try:
            return tuple(int(x) for x in v.split(".") if x.isdigit())
        except Exception:
            return ()

    upgradable = bool(latest and current and _vt(latest) > _vt(current))
    return jsonify({"ok": not err, "kind": kind, "current": current,
                    "latest": latest, "upgradable": upgradable, "err": err})


@res_bp.route("/api/resources/poll")
def res_poll():
    return jsonify({"ok": True,
                    "running": _state["running"], "phase": _state["phase"],
                    "log": _state["log"], "done": _state["done"],
                    "ok_done": _state["ok"], "err": _state["err"],
                    "result": _state["result"],
                    "total": _state["total"], "bytes": _state["done_bytes"],
                    "indeterminate": bool(_state.get("indeterminate")),
                    "cur": _state["cur"], "cancelling": _state["cancel"],
                    "cancelled": _state["cancelled"],
                    "log_seq": _state.get("log_seq", 0),
                    "note": _state.get("note", "")})
