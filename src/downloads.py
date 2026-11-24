# -*- coding: utf-8 -*-
"""下载中心（2026-11-24 用户令）。

背景：壳此前完全不管下载——Electron 对没接管的下载弹系统保存框，存哪、存没
存成只有用户自己知道。工具内的 AI 点完下载只能照页面文案说「浏览器下载列表
可见」；用户自己在网页标签页里下载，更是点了保存就没下文。

用户令三条：
  ① 普通网页标签页的下载也对接到同一套：不再弹保存框，直接存进下载目录；
  ② 要有进度显示、下载完成提示；
  ③ 下载目录可配置：默认跟随数据目录（数据目录\\download），用户可手动另行指定。

链路：壳在 AI 浏览器分区与网页标签页分区的 session 上监听 will-download →
setSavePath 到下载目录（同名加序号、不覆盖；文件名清洗）→ 每个阶段 POST
/api/downloads/report → 这里登记，并经 SSE（kind="download"）推给顶栏的下载
面板（web/js/downloads.js：进度条、完成提示、打开 / 取消）。AI 用
browser_downloads 拿真实路径与状态。

边界：
  · 「完成」必须自己到磁盘核实文件在下载目录里才给路径——AI 会照着它去读文件；
  · 记录只在内存（后端重启即清）；文件本身这里永远不动——删除的唯一入口在
    设置→数据目录→可清理项（data_hygiene.manual_clean），且只对默认目录开放；
  · 用户手动指定的下载目录：工具只往里存，不清理。
"""
import logging
import os
import re
import subprocess
import threading
import time
from collections import OrderedDict

from flask import Blueprint, jsonify, request

from src import app_state as _st
from src.app_state import _broadcast_to_ai

log = logging.getLogger(__name__)

downloads_bp = Blueprint("downloads", __name__)

WAIT_MAX = 60.0                 # 列表接口等「进行中的下载」结束的上限（秒）
_RECORD_MAX = 50                # 记录条数上限
_DONE = ("completed", "cancelled", "interrupted")
_ID_RE = re.compile(r"[^A-Za-z0-9_-]+")
_SOURCES = ("ai_browser", "webtab")

_lock = threading.Lock()
_records = OrderedDict()        # id → 记录；最新在后
_hooks = []                     # 事件订阅者 fn(记录, 事件名)——AI 浏览器的状态条等


def subscribe(fn):
    """订阅下载事件（started / updated / done）。AI 浏览器用它把下载显示到状态条。"""
    _hooks.append(fn)


def _int(v):
    """字节入参：非数、负数、nan、inf 一律当 0；夹到 2**53 以内（防离谱数值）。"""
    try:
        n = int(float(v))
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(0, min(n, 2 ** 53))


def _fmt_bytes(n):
    n = _int(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%d %s" % (n, unit) if unit == "B" else "%.2f %s" % (n, unit)
        n /= 1024.0


def _name(v):
    """文件名入参（壳已清洗过一遍，这里再兜底）：去控制字符、截断 255。"""
    s = re.sub(r"[\u0000-\u001f\u007f]", "", str(v or ""))
    return s.strip()[:255] or "download"


def _verified(path):
    """completed 不能只信壳说的话：文件得真在下载目录里。AI 会照着这个路径去读
    文件，路径必须是自己核实过的。返回 (字节数, 不通过的原因)。"""
    ddir = _st.download_dir()
    try:
        base = os.path.normcase(os.path.realpath(ddir)) + os.sep if ddir else ""
        real = os.path.normcase(os.path.realpath(str(path or "")))
        if not base or not real.startswith(base):
            return 0, "文件不在下载目录里"
        if not os.path.isfile(real):
            return 0, "文件不在磁盘上"
        return os.path.getsize(real), None
    except Exception as e:
        return 0, "核实文件失败：%s" % e


def _public(r):
    return {k: r[k] for k in ("id", "filename", "state", "received", "total",
                              "path", "error", "ts", "source")}


def _trim():
    """记录条数封顶：先淘汰最早已结束的；全在进行中（不现实）才动最旧的。"""
    while len(_records) > _RECORD_MAX:
        for k, r in _records.items():
            if r["state"] != "in_progress":
                del _records[k]
                break
        else:
            _records.pop(next(iter(_records)))


def _emit(rec, event):
    """每个阶段都推给下载面板（SSE，kind="download"），并通知订阅者。"""
    try:
        _broadcast_to_ai(dict(rec, kind="download", event=event))
    except Exception:
        pass
    for fn in list(_hooks):
        try:
            fn(dict(rec), event)
        except Exception:
            log.exception("下载事件的订阅者抛出了异常")


@downloads_bp.route("/api/downloads/report", methods=["POST"])
def report():
    """壳调用（session 的 will-download）：{event: started|updated|done, id,
    filename, source, received, total, state, path, error}。"""
    d = request.get_json(force=True, silent=True)
    if not isinstance(d, dict):
        d = {}
    did = _ID_RE.sub("", str(d.get("id") or ""))[:80]
    ev = str(d.get("event") or "")
    if not did:
        return jsonify({"ok": False, "err": "缺少下载标识 id"})
    if ev not in ("started", "updated", "done"):
        return jsonify({"ok": False, "err": "event 只能是 started / updated / done"})
    src = str(d.get("source") or "")
    src = src if src in _SOURCES else "webtab"
    with _lock:
        rec = _records.get(did)
        if ev == "started":
            if rec is None:
                rec = {"id": did, "filename": _name(d.get("filename")), "source": src,
                       "state": "in_progress", "received": 0, "total": 0,
                       "path": None, "error": None, "ts": time.time()}
                _records[did] = rec
            rec["total"] = _int(d.get("total")) or rec["total"]
            _trim()
            out = dict(rec)
        elif rec is None:
            # 后端重启过而壳还在报旧下载：没有起点记录，无从登记——如实告知
            return jsonify({"ok": True, "unknown": True})
        elif ev == "updated":
            rec["received"] = _int(d.get("received"))
            rec["total"] = _int(d.get("total")) or rec["total"]
            out = dict(rec)
        else:
            state = str(d.get("state") or "")
            rec["received"] = _int(d.get("received"))
            rec["total"] = _int(d.get("total")) or rec["total"]
            if state not in _DONE:
                rec["error"] = "未知的结束状态：%s" % (state or "（空）")   # 先留原值再改写
                state = "interrupted"
            elif state == "completed":
                size, why = _verified(d.get("path"))
                if why:
                    # 壳说存好了、磁盘上却对不上：不能记成完成（AI 会去读一个不存在
                    # 的路径），按失败处理并说明原因
                    state, rec["error"] = "interrupted", why
                else:
                    rec["path"], rec["received"] = d.get("path"), size
            elif state == "interrupted":
                rec["error"] = str(d.get("error") or "")[:200] or "下载被中断"
            rec["state"] = state
            _records.move_to_end(did)
            _trim()
            out = dict(rec)
    _emit(out, ev)
    if ev == "done":
        try:
            from src import data_hygiene as _dh
            _dh.invalidate_usage_cache()     # 设置页的「存储占用」要跟上
        except Exception:
            pass
    return jsonify({"ok": True})


def _wait(wait_s):
    """等所有进行中的下载结束，最多 wait_s 秒（上限 WAIT_MAX）。
    返回 True = 都结束了。轮询而不建条件变量：简单可靠。"""
    deadline = time.time() + min(WAIT_MAX, max(0.0, wait_s))
    while True:
        with _lock:
            busy = any(r["state"] == "in_progress" for r in _records.values())
        if not busy or time.time() >= deadline:
            return not busy
        time.sleep(0.2)


def _text(items):
    ddir = _st.download_dir()
    if not items:
        return "还没有下载记录。下载不弹保存窗口，文件自动存到：%s" % ddir
    lines = ["下载目录：" + ddir]
    for r in reversed(items):            # 最新的在前
        name, st = r["filename"], r["state"]
        if st == "completed":
            lines.append("[完成] %s  %s  → %s" % (name, _fmt_bytes(r["received"]), r["path"]))
        elif st == "cancelled":
            lines.append("[已取消] %s" % name)
        elif st == "interrupted":
            lines.append("[失败] %s（%s）" % (name, r["error"] or "原因未知"))
        else:
            pct = ("（%d%%）" % int(100.0 * r["received"] / r["total"])) if r["total"] else ""
            lines.append("[进行中] %s  已收 %s%s" % (name, _fmt_bytes(r["received"]), pct))
    return "\n".join(lines)


@downloads_bp.route("/api/downloads/list", methods=["POST"])
def list_downloads():
    """{wait} → {ok, dir, custom, text, downloads}。AI 的 browser_downloads 用 text；
    下载面板用 downloads。wait>0 时若有进行中的下载，等它们结束或超时。"""
    d = request.get_json(force=True, silent=True)
    if not isinstance(d, dict):
        d = {}
    try:
        wait_s = float(d.get("wait") or 0)
    except (TypeError, ValueError):
        wait_s = 0.0
    if wait_s != wait_s:                  # nan
        wait_s = 0.0
    _wait(wait_s)
    with _lock:
        items = [_public(r) for r in _records.values()]
    return jsonify({"ok": True, "dir": _st.download_dir(),
                    "custom": not _st.download_dir_is_default(),
                    "text": _text(items), "downloads": items})


@downloads_bp.route("/api/downloads/forget", methods=["POST"])
def forget():
    """把已结束的记录从列表里移除（**不动文件**）：{id} 或 {all: true}。
    进行中的不能移除——面板还要靠它显示进度。"""
    d = request.get_json(force=True, silent=True)
    if not isinstance(d, dict):
        d = {}
    with _lock:
        if d.get("all"):
            for k in [k for k, r in _records.items() if r["state"] != "in_progress"]:
                del _records[k]
        else:
            did = _ID_RE.sub("", str(d.get("id") or ""))[:80]
            r = _records.get(did)
            if r is not None and r["state"] != "in_progress":
                del _records[did]
    return jsonify({"ok": True})


# ---- 下载目录的配置（用户令 2026-11-24：默认跟随数据目录，可手动另行指定）----

def _same(a, b):
    try:
        return bool(a) and bool(b) and os.path.normcase(os.path.abspath(a)) \
            == os.path.normcase(os.path.abspath(b))
    except Exception:
        return False


def _dir_state():
    """下载目录的现状（给设置页 / 壳）：当前目录、是否用户指定、能不能用。"""
    custom = not _st.download_dir_is_default()
    d = _st.download_dir(create=True)
    reason = None
    if d is None:
        d = _st.download_custom_dir() or _st.download_default_dir()
        reason = "目录用不了（路径无效、建不出来或没有写入权限）——下载会退回弹保存框"
    return {"dir": d, "custom": custom, "default_dir": _st.download_default_dir(),
            "usable": reason is None, "reason": reason}


def _check_custom_dir(raw):
    """校验用户手动指定的下载目录。返回 (绝对路径, None) 或 (None, 原因)。
    会顺手建目录并做一次写探针——用户点「应用」就是要用它。"""
    if not os.path.isabs(raw) or "~" in raw:
        return None, "请填写完整路径（如 D:\\下载）"
    p = os.path.abspath(raw)
    if os.path.dirname(p) == p:
        return None, "不能把磁盘根目录当下载目录"
    for bad, why in ((_st.DATA_DIR, "数据目录本身"), (_st.APP_DIR, "工具目录本身"),
                     (_st.HOME_DIR, "锚点目录本身"),
                     (os.path.expanduser("~"), "用户主目录本身")):
        if _same(p, bad):
            return None, "不能设成" + why
    for bad in (os.environ.get("SystemRoot"), os.environ.get("ProgramFiles")):
        if not bad:
            continue
        if any(_same(q, bad) for q in (p, os.path.dirname(p), os.path.dirname(os.path.dirname(p)))):
            return None, "不能设在系统目录里"
    try:
        os.makedirs(p, exist_ok=True)
        probe = os.path.join(p, ".fc_dl_probe_%d" % os.getpid())
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
    except Exception as e:
        return None, "目录用不了（建不出来或没有写入权限）：%s" % e
    if not os.path.isdir(p):
        return None, "那个位置是个文件，不是文件夹"
    return p, None


def _save_dir(p):
    cfg = dict(_st._load_config())
    cfg["download_dir"] = p
    _st._save_config(cfg)
    try:
        from src import data_hygiene as _dh
        _dh.invalidate_usage_cache()     # 设置页的占用要按新目录重算
    except Exception:
        pass


@downloads_bp.route("/api/downloads/config", methods=["GET", "POST"])
def config():
    """GET → 下载目录的现状。POST {dir}: 空串 = 恢复默认（跟随数据目录）；
    否则校验后保存。校验不过回 400 并说明原因，不动现有配置。"""
    if request.method == "GET":
        return jsonify(dict(_dir_state(), ok=True))
    d = request.get_json(force=True, silent=True)
    if not isinstance(d, dict):
        return jsonify({"ok": False, "err": "参数必须是 JSON 对象"}), 400
    raw = str(d.get("dir") or "").strip()
    if not raw:
        _save_dir("")
        return jsonify(dict(_dir_state(), ok=True))
    p, why = _check_custom_dir(raw)
    if why:
        return jsonify({"ok": False, "err": why}), 400
    _save_dir(p)
    return jsonify(dict(_dir_state(), ok=True))


@downloads_bp.route("/api/downloads/open", methods=["POST"])
def open_path():
    """打开下载的文件 / 下载目录，或在资源管理器里定位文件（reveal=true）。
    只认**下载目录本身**和它**第一层**里现存的条目——不接受任意路径。"""
    d = request.get_json(force=True, silent=True)
    if not isinstance(d, dict):
        d = {}
    base = _st.download_dir()
    p = str(d.get("path") or "").strip()
    if not base or not p:
        return jsonify({"ok": False, "err": "缺少路径"}), 400
    real = os.path.normcase(os.path.realpath(p))
    real_base = os.path.normcase(os.path.realpath(base))
    if real != real_base and os.path.dirname(real) != real_base:
        return jsonify({"ok": False, "err": "只能打开下载目录里的东西"}), 403
    if not os.path.exists(real):
        return jsonify({"ok": False, "err": "文件已经不在磁盘上（可能被移走或删除了）"}), 404
    try:
        target = os.path.normpath(p)
        if d.get("reveal") and real != real_base:
            # 在资源管理器里定位文件：/select, 与路径之间不能有空格
            subprocess.Popen('explorer.exe /select,"%s"' % target, close_fds=True)
        elif os.path.isdir(real):
            # os.startfile 偶发静默失败（无控制台形态错误不可见），explorer.exe 更可靠
            subprocess.Popen(["explorer.exe", target], close_fds=True)
        else:
            os.startfile(real)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "err": str(e)}), 400
