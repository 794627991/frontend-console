# -*- coding: utf-8 -*-
"""二进制文件十六进制查看/编辑 API（Flask Blueprint）。

bin/hex/ihx 等二进制文件以前只能走阅读器（文本形式乱码）。现在：
- /api/hex/meta：大小 + Intel HEX 标记（.hex/.ihx 是 ASCII 文本但语义是二进制镜像）
- /api/hex/read：分块读原始字节（base64）——大文件窗口式加载，不整读进内存
- /api/hex/save：整文件字节写回（base64）
安全：仅绝对路径 + 已存在文件；不做站内 files/ 名映射（二进制不在笔记白名单）。
"""
import os, base64
from flask import Blueprint, request, jsonify

hex_bp = Blueprint("hexfiles", __name__)

# 十六进制查看常用二进制后缀（不在文本白名单的都允许——is_text 探测已分流）
READ_CHUNK = 512 * 1024   # 单次读取上限 512KB（大文件分块窗口加载）

def _real_path(path):
    p = os.path.abspath((path or "").strip().strip('"').strip("'"))
    if not os.path.isfile(p):
        return None
    return p

@hex_bp.route("/api/hex/meta", methods=["POST"])
def hex_meta():
    """文件元信息：大小 + 是否 Intel HEX（.hex/.ihx 文本格式但内容是二进制镜像）。"""
    data = request.get_json(force=True, silent=True) or {}
    p = _real_path(data.get("path"))
    if not p:
        return jsonify({"ok": False, "err": "文件不存在"}), 400
    low = p.lower()
    is_ihex = low.endswith((".hex", ".ihx"))
    try:
        size = os.path.getsize(p)
    except OSError as e:
        return jsonify({"ok": False, "err": str(e)}), 400
    return jsonify({"ok": True, "path": p, "size": size, "ihex": is_ihex})

@hex_bp.route("/api/hex/read", methods=["POST"])
def hex_read():
    """分块读字节。body: {path, offset, length} → {data: base64, size, offset}"""
    data = request.get_json(force=True, silent=True) or {}
    p = _real_path(data.get("path"))
    if not p:
        return jsonify({"ok": False, "err": "文件不存在"}), 400
    try:
        offset = max(0, int(data.get("offset") or 0))
        length = min(int(data.get("length") or READ_CHUNK), READ_CHUNK)
        size = os.path.getsize(p)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "err": "参数无效"}), 400
    if offset >= size:
        return jsonify({"ok": True, "data": "", "size": size, "offset": offset})
    length = min(length, size - offset)
    with open(p, "rb") as f:
        f.seek(offset)
        chunk = f.read(length)
    return jsonify({"ok": True, "data": base64.b64encode(chunk).decode("ascii"),
                    "size": size, "offset": offset})

@hex_bp.route("/api/hex/save", methods=["POST"])
def hex_save():
    """整文件写回（查看器内存中已有完整镜像，尺寸通常受 READ_CHUNK 窗口约束）。
    body: {path, data: base64}。原子替换：写 .part 再 os.replace。"""
    data = request.get_json(force=True, silent=True) or {}
    p = _real_path(data.get("path"))
    if not p:
        return jsonify({"ok": False, "err": "文件不存在"}), 400
    try:
        raw = base64.b64decode(data.get("data") or "")
    except Exception:
        return jsonify({"ok": False, "err": "base64 无效"}), 400
    tmp = p + ".hexpart"
    try:
        with open(tmp, "wb") as f:
            f.write(raw)
        os.replace(tmp, p)
    except OSError as e:
        try: os.remove(tmp)
        except OSError: pass
        return jsonify({"ok": False, "err": str(e)}), 400
    return jsonify({"ok": True, "size": len(raw)})
