# -*- coding: utf-8 -*-
"""文本编辑器后端（Flask Blueprint 路由 /api/ed/*）。
管理工具目录下 files/ 中的文本文件：新建/读取/保存/另存为/重命名/删除。
设计取舍（调研 CodeMirror/Monaco/Notepad++ 后）：
- 引擎零依赖：纯文本编辑用 textarea + 原生 undo 足够，不引重型编辑器引擎
- 脏状态在前端（* 标记），后端只管文件 I/O；UTF-8 统一编码
- 路径安全：只允许访问 files/ 目录内（防 ../ 穿越）
"""
import os, re, time
from flask import Blueprint, request, jsonify

from src.app_state import BASE_DIR

edit_bp = Blueprint("editor", __name__)

# 编辑器文件根目录：工具所在目录/files（源码运行=项目根，exe=exe 所在目录）
FILES_DIR = os.path.join(BASE_DIR, "files")

# 文件名合法规则：禁路径分隔符与控制字符（目录切换交给未来的文件夹功能）
_NAME_RE = re.compile(r'^[^\\/:*?"<>|\x00-\x1f]{1,120}$')


def _ensure_dir():
    os.makedirs(FILES_DIR, exist_ok=True)


def _safe_path(name):
    """把文件名解析为 files/ 内的绝对路径。非法名或穿越尝试返回 None。
    允许外部绝对路径（打开 files 外的文件）由调用方单独校验，这里只管站内。"""
    if not _NAME_RE.match(name or ""):
        return None
    p = os.path.normpath(os.path.join(FILES_DIR, name))
    if not os.path.realpath(p).startswith(os.path.realpath(FILES_DIR) + os.sep):
        return None  # 穿越尝试（. 不会被 _NAME_RE 放行，双保险）
    return p


def _unique_name(base="新建文本"):
    """生成不冲突的默认文件名：新建文本.txt / 新建文本2.txt / ..."""
    _ensure_dir()
    candidate = base + ".txt"
    n = 2
    while os.path.exists(os.path.join(FILES_DIR, candidate)):
        candidate = f"{base}{n}.txt"
        n += 1
    return candidate


def _read_text(path, max_bytes=20 * 1024 * 1024):
    """读文本文件。超限拒绝（20MB——textarea 渲染 2000 万字符必卡）。
    用 utf-8 读，带 BOM 容错；失败时回退 utf-8 errors=replace 再试（保内容不保格式）。"""
    size = os.path.getsize(path)
    if size > max_bytes:
        return None, f"文件过大（{size/1024/1024:.1f}MB > 20MB 上限）"
    with open(path, "r", encoding="utf-8-sig") as f:
        try:
            return f.read(), None
        except UnicodeDecodeError:
            with open(path, "r", encoding="utf-8", errors="replace") as f2:
                return f2.read(), None


@edit_bp.route("/api/ed/new", methods=["POST"])
def ed_new():
    """新建文件：创建空文件（默认 .txt），返回文件名。"""
    _ensure_dir()
    name = _unique_name()
    with open(os.path.join(FILES_DIR, name), "w", encoding="utf-8") as f:
        f.write("")
    return jsonify({"ok": True, "name": name})


@edit_bp.route("/api/ed/list")
def ed_list():
    """列出 files/ 下可编辑文本文件（按修改时间倒序）。"""
    _ensure_dir()
    items = []
    for fn in os.listdir(FILES_DIR):
        p = os.path.join(FILES_DIR, fn)
        if not os.path.isfile(p):
            continue
        st = os.stat(p)
        items.append({"name": fn, "size": st.st_size, "mtime": int(st.st_mtime)})
    items.sort(key=lambda x: -x["mtime"])
    return jsonify({"ok": True, "files": items, "dir": FILES_DIR})


@edit_bp.route("/api/ed/open")
def ed_open():
    """读文件内容：name=files/ 内文件名。"""
    name = request.args.get("name", "")
    p = _safe_path(name)
    if not p or not os.path.isfile(p):
        return jsonify({"ok": False, "err": "文件不存在"}), 404
    text, err = _read_text(p)
    if err:
        return jsonify({"ok": False, "err": err}), 400
    return jsonify({"ok": True, "name": name, "text": text})


@edit_bp.route("/api/ed/save", methods=["POST"])
def ed_save():
    """覆盖保存：{name, text}。前端在关闭前保证已确认脏状态。"""
    data = request.get_json(force=True, silent=True) or {}
    p = _safe_path(data.get("name", ""))
    if not p:
        return jsonify({"ok": False, "err": "非法文件名"}), 400
    text = data.get("text", "")
    # 先写临时文件再原子替换：保存中途崩溃/断电不留半个文件
    tmp = p + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(tmp, p)
    except Exception as e:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return jsonify({"ok": False, "err": str(e)}), 500
    return jsonify({"ok": True, "name": data.get("name")})


@edit_bp.route("/api/ed/save_as", methods=["POST"])
def ed_save_as():
    """另存为：{new_name, text}。new_name 冲突时返回 err（前端提示后可改用覆盖保存）。"""
    data = request.get_json(force=True, silent=True) or {}
    name = data.get("new_name", "").strip()
    p = _safe_path(name)
    if not p:
        return jsonify({"ok": False, "err": "非法文件名（不含 \\ / : * ? \" < > |）"}), 400
    if os.path.exists(p):
        return jsonify({"ok": False, "err": "同名文件已存在"}), 409
    text = data.get("text", "")
    tmp = p + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(tmp, p)
    except Exception as e:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return jsonify({"ok": False, "err": str(e)}), 500
    return jsonify({"ok": True, "name": name})


@edit_bp.route("/api/ed/rename", methods=["POST"])
def ed_rename():
    """重命名：{old, new}。同 files/ 内改名，新名冲突返回 err。"""
    data = request.get_json(force=True, silent=True) or {}
    po = _safe_path(data.get("old", ""))
    pn = _safe_path(data.get("new", "").strip())
    if not po or not pn or not os.path.isfile(po):
        return jsonify({"ok": False, "err": "原文件不存在"}), 404
    if os.path.exists(pn):
        return jsonify({"ok": False, "err": "同名文件已存在"}), 409
    try:
        os.replace(po, pn)
    except Exception as e:
        return jsonify({"ok": False, "err": str(e)}), 500
    return jsonify({"ok": True, "name": data.get("new").strip()})


@edit_bp.route("/api/ed/delete", methods=["POST"])
def ed_delete():
    """删除文件：{name}。前端已做确认。"""
    data = request.get_json(force=True, silent=True) or {}
    p = _safe_path(data.get("name", ""))
    if not p or not os.path.isfile(p):
        return jsonify({"ok": False, "err": "文件不存在"}), 404
    try:
        os.remove(p)
    except Exception as e:
        return jsonify({"ok": False, "err": str(e)}), 500
    return jsonify({"ok": True})


@edit_bp.route("/api/ed/open_dir", methods=["POST"])
def ed_open_dir():
    """在资源管理器中打开 files/ 目录。"""
    _ensure_dir()
    try:
        if os.name == "nt":
            os.startfile(FILES_DIR)  # noqa: startfile 仅 Windows
        else:
            import subprocess
            subprocess.Popen(["xdg-open", FILES_DIR])
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "err": str(e)}), 500
