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


def _under_roots(path):
    """安全门卫：path 必须在某登记根或其子树内，返回归一化路径，否则 None。"""
    if not path:
        return None
    p = os.path.abspath(str(path).strip().strip('"').strip("'"))
    for root in _tree_roots():
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
    roots = _tree_roots()
    if p not in roots:
        roots.append(p)
        _save_tree_roots(roots)
    return jsonify({"ok": True, "roots": roots})


@tree_bp.route("/api/tree/remove_root", methods=["POST"])
def tree_remove_root():
    """取消登记一个根（原样对照 config 列表；归一后比对）。"""
    data = request.get_json(force=True, silent=True) or {}
    p = os.path.abspath(str(data.get("path") or "").strip().strip('"').strip("'"))
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
    entries, err = _list_dir(p, bool(data.get("hidden")))
    if entries is None:
        return jsonify({"ok": False, "err": f"读取失败：{err}"}), 400
    return jsonify({"ok": True, "path": p, "entries": entries,
                    "truncated": err if isinstance(err, int) else 0})
