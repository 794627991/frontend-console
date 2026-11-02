# -*- coding: utf-8 -*-
"""文件树工作区 API（Flask Blueprint）——类 VSCode 资源管理器的后端。

安全模型（根目录登记制）：
/api/tree/* 只允许枚举 config.json `tree_roots` 已登记根的子树内路径。
不开放任意绝对路径枚举——枚举目录等于把整个磁盘变成可浏览列表
（config/密码文件路径结构全暴露给任何能 POST 到 127.0.0.1 的页面）。
文件打开不走本模块：树节点点击走 openFileSmart → /api/file_info →
/api/ed/open 既有链路，权限沿用原通道，零新增攻击面。

流畅度（项目第一守则）：
- 单层扫描（os.scandir，不递归）——展开才拉一层，懒加载由前端驱动
- 不 stat size/mtime——树只展示结构，几千条目的 stat 才是 IO 大头
- 单层超 LIST_CAP 截断 + truncated 计数，防万级目录撑爆前端 DOM
"""
import os
from flask import Blueprint, request, jsonify

from src.app_state import _load_config, _save_config

tree_bp = Blueprint("filetree", __name__)

LIST_CAP = 2000   # 单层条目上限（防万级目录卡前端；超限截断并告知）


def _tree_roots():
    """已登记根目录列表（abspath 归一 + 过滤已不存在的目录）。"""
    roots = _load_config().get("tree_roots") or []
    out = []
    for r in roots:
        p = os.path.abspath(r)
        if os.path.isdir(p) and p not in out:
            out.append(p)
    return out


def _save_tree_roots(roots):
    """保存根列表（保序去重）。"""
    _save_config({**_load_config(), "tree_roots": list(dict.fromkeys(roots))})


def _project_roots():
    """已打开的 Claude 会话工程目录（v4.0.1）。

    用户拍板「已打开的工程，不用必须在文件树打开，只要打开了就可以显示
    git」——版本面板/工作区能看到的工程，不止文件树登记的根。数据源取
    会话元数据里出现过的 cwd（老会话也认，切走过的不丢）。
    仍与 _tree_roots 同口径：过滤不存在的目录、abspath 归一。"""
    out = []
    try:
        from .harness import meta as _m
        _m._meta_load()
        for v in list(_m._meta.values()):
            c = str((v or {}).get("cwd") or "").strip()
            if not c:
                continue
            p = os.path.abspath(c)
            if p not in out and os.path.isdir(p):
                out.append(p)
    except Exception:
        pass
    return out


def _under_roots(path):
    """安全门卫：path 必须在某登记根或其子树内，返回归一化路径，否则 None。"""
    if not path:
        return None
    p = os.path.abspath(str(path).strip().strip('"').strip("'"))
    for root in _tree_roots():
        if p == root or p.startswith(root + os.sep):
            return p
    return None


def _under_roots_or_projects(path):
    """版本面板专用门卫：文件树登记根 **或** 已打开会话工程目录。
    与 _under_roots 分开——文件树枚举仍只认登记根（枚举目录 = 把磁盘变
    可浏览列表，不能因为开过会话就放开）；git/svn 只读查看工程目录本身
    是用户已明确打开的路径，不会扩大枚举面。"""
    p = _under_roots(path)
    if p:
        return p
    if not path:
        return None
    p = os.path.abspath(str(path).strip().strip('"').strip("'"))
    for root in _project_roots():
        if p == root or p.startswith(root + os.sep):
            return p
    return None


def _list_dir(path, show_hidden=False):
    """单层扫描：os.scandir 一次拿 entry.is_dir()（不 follow symlink，
    不 stat size/mtime）。目录在前 + 字母序不区分大小写（资源管理器习惯）。
    隐藏（. 开头）默认滤除；超上限截断，返回 (entries, truncated_remaining)。
    truncated 只数【可见】条目——隐藏文件不参与截断提示（开关关着时
    不该冒出"还有 N 项"去诱导用户点开）。"""
    entries = []
    n = 0
    try:
        with os.scandir(path) as it:
            for e in it:
                if not show_hidden and e.name.startswith("."):
                    continue          # 隐藏文件在计数前滤除——不计入 n 也不计入 truncated
                n += 1
                if n > LIST_CAP:     # 只多扫 1 个就知道还有剩余
                    continue
                try:
                    is_dir = e.is_dir(follow_symlinks=False)
                except OSError:
                    continue         # 权限/重解析点异常的条目跳过，单条不炸整体
                entries.append({"name": e.name, "path": e.path, "dir": is_dir})
    except OSError as ex:
        return None, str(ex)
    entries.sort(key=lambda x: (not x["dir"], x["name"].lower()))
    truncated = max(0, n - len(entries))
    return entries[:LIST_CAP], truncated


@tree_bp.route("/api/tree/roots")
def tree_roots():
    """已登记的根目录列表（前端启动时拉取渲染）。"""
    return jsonify({"ok": True, "roots": _tree_roots()})


@tree_bp.route("/api/tree/add_root", methods=["POST"])
def tree_add_root():
    """登记一个根目录（多根工作区）。body: {path}。只登记不删磁盘。"""
    data = request.get_json(force=True, silent=True) or {}
    p = os.path.abspath(str(data.get("path") or "").strip().strip('"').strip("'"))
    if not os.path.isdir(p):
        return jsonify({"ok": False, "err": "目录不存在"}), 400
    # a234 黑盒穿透修复：系统目录/盘根/UNC 管理共享拒登记——曾可加
    # System32 后 search 全盘读文件内容、加 c$ 后 touch 全盘写
    _wl = os.environ.get("WINDIR", r"C:\Windows").lower()
    _pl = p.lower()
    _danger = (
        p.startswith("\\\\")                                    # UNC 一律拒（本地工具无网络目录需求）
        or _pl == "c:\\" or _pl == "d:\\" or _pl.endswith(":\\")  # 盘根
        or _pl.startswith(_wl)                                      # Windows 目录及子树
        or _pl.startswith("c:\program files")                   # Program Files
        or _pl.startswith("c:\programdata"))
    if _danger:
        return jsonify({"ok": False, "err":
            "系统/网络/盘根路径不允许登记为工作区根（安全限制）"}), 400
    roots = _tree_roots()
    # 对抗审 a206C P3：嵌套根拒绝——D:\work 与 D:\work\sub 同时登记会使
    # 同一 path 双行渲染（open/cache/idx 按 path 共享，两处同开同拉、
    # 对焦恒跳靠后行）。精确重复上面已挡，这里挡父子包含（双向）
    def _nested(a, b):
        try:
            return os.path.commonpath([a, b]) in (a, b) and a != b
        except ValueError:
            return False   # 跨盘符 commonpath 抛错——不可能嵌套
    for r in roots:
        if _nested(p, r):
            inside = (r in p and p != r)
            msg = "嵌套根：%s %s已登记根 %s——请先移除旧根再添加，或添加未覆盖的兄弟目录" % (
                p, "位于" if inside else "覆盖了", r)
            return jsonify({"ok": False, "err": msg}), 400
    if p not in roots:
        roots.append(p)
        _save_tree_roots(roots)
    return jsonify({"ok": True, "roots": roots})


@tree_bp.route("/api/tree/remove_root", methods=["POST"])
def tree_remove_root():
    """取消登记一个根（原样对照 config 列表；归一后比对）。"""
    data = request.get_json(force=True, silent=True) or {}
    _raw = str(data.get("path") or "").strip().strip('"').strip("'")
    if not _raw:
        return jsonify({"ok": False, "err": "缺少 path 参数"}), 400   # a234: 空 body 曾误删主根
    p = os.path.abspath(_raw)
    roots = [r for r in _tree_roots() if r != p]
    _save_tree_roots(roots)
    return jsonify({"ok": True, "roots": roots})


@tree_bp.route("/api/tree/list", methods=["POST"])
def tree_list():
    """单层列目录（懒加载：前端展开某目录才调）。body: {path, hidden?}。
    path 必须在已登记根的子树内（_under_roots 门卫）。"""
    data = request.get_json(force=True, silent=True) or {}
    p = _under_roots(data.get("path"))
    if not p:
        return jsonify({"ok": False, "err": "路径不在文件树根目录内"}), 400
    if not os.path.isdir(p):
        return jsonify({"ok": False, "err": "目录不存在或已移除"}), 400
    if not _under_roots(os.path.realpath(p)):   # a234: junction 指根外拒
        return jsonify({"ok": False, "err": "路径包含指向根外的链接"}), 400
    entries, err = _list_dir(p, bool(data.get("hidden")))
    if entries is None:
        return jsonify({"ok": False, "err": f"读取失败：{err}"}), 400
    return jsonify({"ok": True, "path": p, "entries": entries,
                    "truncated": err if isinstance(err, int) else 0})


# ============================================================
# a209批2：文件操作（对标 VSCode Explorer 右键全家桶）
# 单端点多操作，全部过 _under_roots 门卫（白名单语义不变）；
# delete 走系统回收站（SHFileOperationW + FOF_ALLOWUNDO，可恢复，
# 零新依赖纯 ctypes）；根目录本体不可删（只可 remove_root）。
# ============================================================
def _recycle_to_trash(path):
    """移入系统回收站。返回 (ok, err)。纯 ctypes，Windows only。"""
    import ctypes
    from ctypes import wintypes

    class _SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", ctypes.c_uint),
                    ("pFrom", ctypes.c_wchar_p), ("pTo", ctypes.c_wchar_p),
                    ("fFlags", ctypes.c_ushort),
                    ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p),
                    ("lpszProgressTitle", ctypes.c_wchar_p)]

    op = _SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = 3                    # FO_DELETE
    op.pFrom = str(path) + "\0\0"  # pFrom 需双 NUL 结尾（ctypes c_wchar_p 只补一个）
    op.fFlags = 0x40 | 0x10 | 0x4 | 0x400   # ALLOWUNDO|NOCONFIRMATION|SILENT|NOERRORUI（a213 审计 P3：失败不弹系统框阻塞请求线程）
    try:
        rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    except Exception as e:
        return False, str(e)
    if rc != 0:
        return False, "系统回收站操作失败（code=%d）" % rc
    if op.fAnyOperationsAborted:
        return False, "操作被系统中止"
    return True, ""


def _is_reparse(path):
    """junction/符号链接检测（a234 黑盒穿透修复）：根内 junction 指向根外时，
    fileops 全部 op 曾能穿过它读/写/删根外文件（mklink /J 实测穿透）。"""
    try:
        import ctypes
        from ctypes import wintypes
        FILE_ATTRIBUTE_REPARSE_POINT = 0x400
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        return attrs != -1 and (attrs & FILE_ATTRIBUTE_REPARSE_POINT) != 0
    except Exception:
        return False


def _resolve_real(path):
    """解析到最终真实路径（穿透 junction 链）——fileops 守卫须验真实路径。"""
    try:
        return os.path.realpath(str(path))
    except Exception:
        return str(path)


def _guard_ops_path(path):
    """fileops 统一守卫：根白名单 + 真实路径也须在根内（堵 junction 逃逸）+
    NUL 字节/超长拒绝。返回 (guarded_path, err)。"""
    p = str(path or "")
    if "\x00" in p or len(p) > 1024:
        return None, "参数无效"
    fp = _under_roots(p)
    if not fp:
        return None, None   # 白名单拒绝——由调用方返回 404/400
    real = _resolve_real(fp)
    # 真实路径也必须在根内（junction 指根外→real 在根外→拒）
    if not _under_roots(real):
        return None, "路径包含指向根外的链接（junction/symlink），禁止操作"
    return fp, None


def _parent_dir(path):
    return os.path.dirname(os.path.abspath(path))


@tree_bp.route("/api/tree/fileops", methods=["POST"])
def tree_fileops():
    """文件操作：{op: mkdir|touch|rename|copy|delete, ...}。
    - mkdir  {dir}                新建目录
    - touch  {dir, name}          新建空文件
    - rename {path, name}         同目录改名（name 禁含路径分隔符）
    - copy   {path, dir}          复制文件/目录到目标目录
    - delete {path}               移入系统回收站（可恢复）
    响应 {ok, parent}（parent=受影响目录，前端 treeInvalidate 用）。"""
    data = request.get_json(force=True, silent=True) or {}
    op = str(data.get("op") or "").strip()
    try:
        if op == "mkdir":
            d, gerr = _guard_ops_path(data.get("dir"))
            if gerr: return jsonify({"ok": False, "err": gerr}), 400
            if not d:
                return jsonify({"ok": False, "err": "目录不在已登记根内"}), 400
            if os.path.exists(d):
                return jsonify({"ok": False, "err": "已存在同名目录"}), 400
            os.makedirs(d)
            return jsonify({"ok": True, "parent": _parent_dir(d)})
        if op == "touch":
            base, gerr = _guard_ops_path(data.get("dir"))
            if gerr: return jsonify({"ok": False, "err": gerr}), 400
            if not base:
                return jsonify({"ok": False, "err": "目录不在已登记根内"}), 400
            name = str(data.get("name") or "").strip()
            # a213 审计 P3：冒号一并拒——'d:foo' 会被 os.path.join 丢弃 base
            # 跨盘建文件（实测穿越白名单）
            if not base or not name or "/" in name or os.sep in name or ":" in name:
                return jsonify({"ok": False, "err": "参数无效（名字禁含分隔符/冒号）"}), 400
            fp = os.path.join(base, name)
            if os.path.exists(fp):
                return jsonify({"ok": False, "err": "已存在同名文件"}), 400
            with open(fp, "w", encoding="utf-8") as f:
                f.write("")
            return jsonify({"ok": True, "parent": base})
        if op == "rename":
            fp, gerr = _guard_ops_path(data.get("path"))
            if gerr: return jsonify({"ok": False, "err": gerr}), 400
            if not fp:
                return jsonify({"ok": False, "err": "路径不在已登记根内"}), 404
            name = str(data.get("name") or "").strip()
            if not fp or not name or "/" in name or os.sep in name or ":" in name or name in (".", ".."):
                return jsonify({"ok": False, "err": "参数无效"}), 400
            roots = _tree_roots()
            if fp in roots:
                return jsonify({"ok": False, "err": "根目录请用「移除根」（不可改名）"}), 400
            if not os.path.exists(fp):
                return jsonify({"ok": False, "err": "原路径不存在"}), 404
            tp = os.path.join(os.path.dirname(fp), name)
            if os.path.exists(tp):
                return jsonify({"ok": False, "err": "目标名已存在"}), 400
            os.rename(fp, tp)
            return jsonify({"ok": True, "parent": os.path.dirname(fp),
                            "old": fp, "new": tp})
        if op == "copy":
            fp, gerr = _guard_ops_path(data.get("path"))
            if gerr: return jsonify({"ok": False, "err": gerr}), 400
            d, gerr2 = _guard_ops_path(data.get("dir"))
            if gerr2: return jsonify({"ok": False, "err": gerr2}), 400
            if not fp or not d or not os.path.exists(fp):
                return jsonify({"ok": False, "err": "参数无效或原路径不存在"}), 400
            # a213 审计 P2：自嵌递归防护（src 是 dst 祖先 → copytree 自我
            # 递归炸 500 + 493 层垃圾——实测复现）
            try:
                if os.path.commonpath([fp, d]) == os.path.abspath(fp):
                    return jsonify({"ok": False, "err": "不能把目录复制到自身内部"}), 400
            except ValueError:
                pass
            import shutil
            tp = os.path.join(d, os.path.basename(fp))
            if os.path.exists(tp):
                return jsonify({"ok": False, "err": "目标已存在同名项"}), 400
            if os.path.isdir(fp):
                shutil.copytree(fp, tp)
            else:
                shutil.copy2(fp, tp)
            return jsonify({"ok": True, "parent": d})
        if op == "delete":
            fp, gerr = _guard_ops_path(data.get("path"))
            if gerr: return jsonify({"ok": False, "err": gerr}), 400
            if not fp:
                return jsonify({"ok": False, "err": "路径不存在"}), 404
            if not os.path.exists(fp):
                return jsonify({"ok": False, "err": "路径不存在"}), 404
            # a231 审计 P2：SHFileOperation+ALLOWUNDO 对网络路径（UNC/映射盘）
            # 不经回收站直接永久删且返回成功——前端承诺「可恢复」静默失效。
            # 网络根上一律拒绝，引导资源管理器操作
            try:
                import ctypes as _ct
                _drive = fp[:3] if fp[1:2] == ":" else None   # 'X:' 形式；UNC 走前缀判定
                if fp.startswith("\\\\") or (_drive and _ct.windll.kernel32.GetDriveTypeW(_drive) == 4):
                    return jsonify({"ok": False, "err":
                        "网络路径的删除不经回收站（不可恢复），请在资源管理器中操作"}), 400
            except Exception:
                pass
            if fp in _tree_roots():
                return jsonify({"ok": False, "err": "根目录请用「移除根」（不删磁盘文件）"}), 400
            ok, err = _recycle_to_trash(fp)
            if not ok:
                return jsonify({"ok": False, "err": err}), 500
            return jsonify({"ok": True, "parent": _parent_dir(fp), "deleted": fp})
        return jsonify({"ok": False, "err": "未知操作 %r" % op}), 400
    except (OSError, RecursionError, ValueError) as e:   # a235: 4096 段路径 makedirs 递归爆（原只捕 OSError→HTML 500）
        return jsonify({"ok": False, "err": str(e)}), 500


@tree_bp.route("/api/tree/reveal", methods=["POST"])
def tree_reveal():
    """在系统资源管理器中打开并定位到该条目（文件=选中它，目录=打开它）。
    path 必须在已登记根的子树内（同 list 门卫——explorer /select 是任意路径
    都能打的洞，不能裸放）。"""
    import subprocess, sys
    data = request.get_json(force=True, silent=True) or {}
    p = _under_roots(data.get("path"))
    if not p or not os.path.exists(p):
        return jsonify({"ok": False, "err": "路径不在文件树根目录内或不存在"}), 400
    try:
        if sys.platform.startswith("win"):
            # /select, 定位到文件（目录则直接打开该目录）
            subprocess.Popen(["explorer.exe", "/select,", p], close_fds=True)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", p])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(p)])
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "err": str(e)}), 500
