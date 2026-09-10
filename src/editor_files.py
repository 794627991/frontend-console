# -*- coding: utf-8 -*-
"""文本编辑器后端（Flask Blueprint 路由 /api/ed/*）。
管理工具目录下 files/ 中的文件：新建/读取/保存/另存为/重命名/删除。
文件类型：.note（Editor.js 块笔记，JSON）与 .txt（纯文本）统一走同一套
I/O——后端不解析内容，格式由前端负责；图片上传存 files/images/。
设计取舍（调研 Editor.js/Monaco/Notepad++ 后）：
- 引擎：.note 用 Editor.js（块式编辑，可贴图/表格/清单，类 OneNote），
  纯文本用 textarea + 原生 undo，均零构建 vendor 化接入
- 脏状态在前端（* 标记），后端只管文件 I/O；UTF-8 统一编码
- 路径安全：只允许访问 files/ 目录内（防 ../ 穿越）
"""
import os, re, time, binascii, shutil
from flask import Blueprint, request, jsonify

from src.app_state import BASE_DIR, DATA_DIR

edit_bp = Blueprint("editor", __name__)

# 编辑器文件根目录：数据目录/files（默认 D:\前端控制台\files，随数据目录迁移走）
FILES_DIR = os.path.join(DATA_DIR, "files")
# 图片目录：files/images（.note 粘贴/上传的图片落这里，笔记里存相对路径 images/xxx.png）
IMAGES_DIR = os.path.join(FILES_DIR, "images")

# 文件名合法规则：禁路径分隔符与控制字符（目录切换交给未来的文件夹功能）
_NAME_RE = re.compile(r'^[^\\/:*?"<>|\x00-\x1f]{1,120}$')

# 允许的图片扩展名（粘贴上传只收这几类，Content 校验防止伪装脚本）
_IMG_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp"}


# 旧版本笔记在 BASE_DIR/files（工具目录）——启动时自动搬进数据目录 files/，
# 搬完在原位置留一个「已迁移.txt」指路，绝不静默丢。防「迁移了就找不到了」。
def _migrate_legacy_files():
    legacy = os.path.join(BASE_DIR, "files")
    if os.path.normpath(legacy) == os.path.normpath(FILES_DIR) or not os.path.isdir(legacy):
        return
    try:
        os.makedirs(FILES_DIR, exist_ok=True)
        moved = 0
        for fn in os.listdir(legacy):
            src = os.path.join(legacy, fn)
            dst = os.path.join(FILES_DIR, fn)
            if os.path.exists(dst):
                continue   # 新位置已有同名文件（用户已手动处理过）不覆盖
            if os.path.isfile(src):
                shutil.copy2(src, dst)
                moved += 1
            elif os.path.isdir(src):   # images/ 子目录
                shutil.copytree(src, dst, dirs_exist_ok=True)
                moved += 1
        if moved:
            shutil.rmtree(legacy, ignore_errors=True)
    except Exception:
        pass    # 迁移失败不阻塞启动，旧位置数据仍在

_migrate_legacy_files()


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


def _unique_name(base="新建笔记", ext=".note"):
    """生成不冲突的默认文件名：新建笔记.note / 新建笔记2.note / ...
    （供另存为/保存默认名提示用；新建草稿本身不落盘）"""
    _ensure_dir()
    candidate = base + ext
    n = 2
    while os.path.exists(os.path.join(FILES_DIR, candidate)):
        candidate = f"{base}{n}{ext}"
        n += 1
    return candidate


@edit_bp.route("/api/ed/default_name")
def ed_default_name():
    """生成一个不冲突的默认文件名（草稿首次保存/另存为时的输入框预填值）。
    ext 参数可选 .note/.txt，默认 .note（块笔记）。"""
    ext = request.args.get("ext", ".note")
    if ext not in (".note", ".txt"):
        ext = ".note"
    return jsonify({"ok": True, "name": _unique_name(ext=ext)})


def _read_text(path, max_bytes=30 * 1024 * 1024, enc=None):
    """读文本文件。超限拒绝（30MB 上限——前端 >30MB 已强制走阅读器，
    20~30MB 用户在弹窗里明确选了编辑器才到这里，Monaco 还能扛）。
    enc 指定编码（编辑器编码下拉手动切）时直接用之——用户说了算，不探测。
    自动探测：utf-8-sig → GB18030 回退（Windows ANSI 中文主流，BSP 常见，
    GBK 超集，能完整解码无 FFRD 才采纳）→ errors=replace 保底。
    返回 (text, err, used_enc)。"""
    size = os.path.getsize(path)
    if size > max_bytes:
        return None, f"文件过大（{size/1024/1024:.1f}MB > 30MB 上限）", None
    if enc:
        try:
            # GB2312 在 Python 无独立 codec（gb2312 即 gbk 别名子集），统一升 gb18030 兼容最广
            real = "gb18030" if enc.lower() in ("gb2312", "gbk", "gb18030") else enc.lower()
            with open(path, "r", encoding=real, errors="replace") as f:
                return f.read(), None, real
        except (LookupError, OSError) as e:
            return None, f"编码无效：{e}", None
    with open(path, "r", encoding="utf-8-sig") as f:
        try:
            return f.read(), None, "utf-8-sig"
        except UnicodeDecodeError:
            pass
    # GB18030 回退：能完整解码（无替换符）才信任——GBK 误读 utf-8 文件
    # 也会"成功"但出乱码，FFPD 无是采纳的必要条件
    try:
        with open(path, "r", encoding="gb18030", errors="strict") as f:
            t = f.read()
        if "�" not in t:
            return t, None, "gb18030"
    except (UnicodeDecodeError, ValueError):
        pass
    with open(path, "r", encoding="utf-8", errors="replace") as f2:
        return f2.read(), None, "utf-8(replace)"


# ---- 外部文件（拖入的任意文本文件）可编辑支持 ----
# 仅放行文本类后缀（白名单），防止把 exe/zip 等二进制灌进编辑器。
_EXT_TEXT = {
    ".txt", ".note", ".md", ".json", ".log", ".csv", ".ini", ".cfg", ".conf", ".yaml", ".yml",
    ".c", ".h", ".cpp", ".hpp", ".py", ".bat", ".cmd", ".sh", ".ps1", ".js", ".ts",
    ".html", ".css", ".xml", ".sql", ".dts", ".dtsi", ".mak", ".mk", ".makefile",
    ".s", ".lds", ".ko", ".rul", ".te", ".fc", "readme", "makefile",
    # 补齐常见文本后缀（曾经漏 .pyw 等——白名单是手列的，不是有意排除）
    ".pyw", ".pyi", ".cc", ".cxx", ".hh", ".hxx", ".java", ".kt", ".kts", ".rs", ".go",
    ".rb", ".php", ".pl", ".lua", ".tcl", ".awk", ".r", ".jl", ".nim", ".zig",
    ".m", ".mm", ".cs", ".vb", ".fs", ".fsx", ".scala", ".groovy", ".swift", ".dart",
    ".v", ".sv", ".svh", ".vhd", ".vhdl", ".asm", ".sln", ".props", ".targets",
    ".gradle", ".properties", ".toml", ".proto", ".tf", ".tfvars",
    ".graphql", ".gql", ".ipynb", ".nix",
    ".editorconfig", ".gitignore", ".gitattributes", ".npmrc",
    ".bashrc", ".zshrc", ".profile", "dockerfile", ".dockerignore",
}
def _ext_of(p):
    # 特殊无后缀文件名（makefile/readme 等）整名匹配
    low = os.path.basename(p).lower()
    dot = low.rfind(".")
    ext = low[dot:] if dot > 0 else low
    return ext

def _safe_ext_path(path, force=False):
    """校验外部绝对路径：必须是文本后缀白名单内的已存在文件。通过返回绝对路径。
    force=True（用户在打开方式弹窗明确选了编辑器）：后缀不在白名单时做 NUL 字节探测，
    开头 8KB 含 NUL 判二进制仍拒，否则按文本放行（去后缀的 json 等曾在此被拒）。"""
    if not path or len(path) < 3 or ":" not in path and not path.startswith("\\\\"):
        return None
    if _ext_of(path) not in _EXT_TEXT:
        if not force:
            return None
        p = os.path.abspath(path)
        if not os.path.isfile(p) or _looks_binary(p):
            return None
        return p
    p = os.path.abspath(path)
    if not os.path.isfile(p):
        return None
    return p


def _looks_binary(path, probe=8192):
    """NUL 字节探测（git 同款判法）：开头 probe 字节含 \\x00 判二进制。"""
    try:
        with open(path, "rb") as f:
            return b"\x00" in f.read(probe)
    except OSError:
        return True


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
    """读文件内容：name=files/ 内文件名；path=外部绝对路径（拖入文件，白名单后缀）。
    enc=编码（编码切换下拉传入：utf-8/gb2312/gbk/gb18030/big5/latin-1…，
    不传走自动探测）。回显 used_enc 供前端显示"当前编码"。"""
    enc = (request.args.get("enc") or "").strip() or None
    # 外部绝对路径分支（拖入的任意文本文件）
    ext_path = request.args.get("path", "")
    force = request.args.get("force") == "1"   # 用户明确选编辑器：无后缀/未知类型按内容探测放行
    if ext_path:
        p = _safe_ext_path(ext_path, force)
        if not p:
            return jsonify({"ok": False, "err": "不支持的文件类型或文件不存在"}), 400
        text, err, used = _read_text(p, enc=enc)
        if err:
            return jsonify({"ok": False, "err": err}), 400
        return jsonify({"ok": True, "name": os.path.basename(p), "path": p,
                        "text": text, "used_enc": used,
                        "mtime": os.path.getmtime(p), "size": os.path.getsize(p)})
    name = request.args.get("name", "")
    p = _safe_path(name)
    if not p or not os.path.isfile(p):
        return jsonify({"ok": False, "err": "文件不存在"}), 404
    text, err, used = _read_text(p, enc=enc)
    if err:
        return jsonify({"ok": False, "err": err}), 400
    return jsonify({"ok": True, "name": name, "text": text, "used_enc": used,
                    "mtime": os.path.getmtime(p), "size": os.path.getsize(p)})


@edit_bp.route("/api/ed/stat")
def ed_stat():
    """轻量查文件状态（mtime+size）：前端编辑器 tab 检测后台进程改动磁盘用。
    name=files/ 内文件名；path=外部绝对路径。文件不存在 err（被外部删除的场景，
    前端也该知道）。"""
    ext_path = (request.args.get("path", "") or "").strip()
    if ext_path:
        try:
            st = os.stat(ext_path)
            return jsonify({"ok": True, "mtime": st.st_mtime, "size": st.st_size})
        except OSError as e:
            return jsonify({"ok": False, "err": "文件不存在或不可访问: %s" % e}), 404
    name = request.args.get("name", "")
    p = _safe_path(name)
    if not p or not os.path.isfile(p):
        return jsonify({"ok": False, "err": "文件不存在"}), 404
    st = os.stat(p)
    return jsonify({"ok": True, "mtime": st.st_mtime, "size": st.st_size})


@edit_bp.route("/api/ed/save", methods=["POST"])
def ed_save():
    """覆盖保存：{name, text}（files/ 内）或 {path, text}（外部绝对路径，拖入文件）。
    前端在关闭前保证已确认脏状态。"""
    data = request.get_json(force=True, silent=True) or {}
    text = data.get("text", "")
    # 外部绝对路径分支：写回原文件（白名单后缀 + 原子替换）
    ext_path = (data.get("path") or "").strip()
    if ext_path:
        # 打开时按内容探测放行过的文件（无后缀文本），保存也放行（同一文件，内容已在前端展示过）
        if _ext_of(ext_path) not in _EXT_TEXT and _looks_binary(os.path.abspath(ext_path)):
            return jsonify({"ok": False, "err": "不支持的文件类型"}), 400
        p = os.path.abspath(ext_path)
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
        return jsonify({"ok": True, "path": p})
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


@edit_bp.route("/api/ed/upload_img", methods=["POST"])
def ed_upload_img():
    """上传图片（.note 编辑器粘贴/选图）：multipart 字段 file。
    落盘 files/images/img_<时间戳>_<随机>.<ext>，返回 files/ 内相对路径
    （如 images/img_...png），前端存进 .note 数据，渲染时走静态路由。"""
    import uuid
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"ok": False, "err": "未收到文件"}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in _IMG_EXT:
        return jsonify({"ok": False, "err": f"不支持的图片类型 {ext or '(无后缀)'}"}), 400
    os.makedirs(IMAGES_DIR, exist_ok=True)
    # 魔数校验：防伪装成图片的脚本文件（png/jpg/gif/bmp/webp 各取头部特征）
    head = f.stream.read(12)
    f.stream.seek(0)
    if not _is_image_head(head, ext):
        return jsonify({"ok": False, "err": "文件内容与图片后缀不符"}), 400
    # 大小上限 10MB（截图粘贴足够；超大图拖垮 WebView 渲染）
    f.stream.seek(0, 2)
    size = f.stream.tell()
    f.stream.seek(0)
    if size > 10 * 1024 * 1024:
        return jsonify({"ok": False, "err": "图片超过 10MB 上限"}), 400
    name = f"img_{int(time.time())}_{uuid.uuid4().hex[:8]}{ext}"
    path = os.path.join(IMAGES_DIR, name)
    f.save(path)
    return jsonify({"ok": True, "url": "images/" + name})


def _is_image_head(head, ext):
    """按扩展名校验文件头魔数（防上传伪装脚本）。"""
    try:
        if ext == ".png":
            return head[:8] == b"\x89PNG\r\n\x1a\n"
        if ext in (".jpg", ".jpeg"):
            return head[:2] == b"\xff\xd8"
        if ext == ".gif":
            return head[:6] in (b"GIF87a", b"GIF89a")
        if ext == ".bmp":
            return head[:2] == b"BM"
        if ext == ".webp":
            return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    except Exception:
        return False
    return False


@edit_bp.route("/api/ed/img/<path:fn>")
def ed_img(fn):
    """静态出图：files/images/<fn>。.note 渲染时 <img src> 指到这里。
    防穿越：规范化后必须在 images/ 内，且扩展名白名单。"""
    p = os.path.normpath(os.path.join(IMAGES_DIR, fn))
    if not os.path.realpath(p).startswith(os.path.realpath(IMAGES_DIR) + os.sep):
        return jsonify({"ok": False, "err": "非法路径"}), 400
    ext = os.path.splitext(fn)[1].lower()
    if ext not in _IMG_EXT:
        return jsonify({"ok": False, "err": "非法类型"}), 400
    if not os.path.isfile(p):
        return jsonify({"ok": False, "err": "图片不存在"}), 404
    from flask import send_file
    return send_file(p, mimetype=_IMG_EXT[ext])


@edit_bp.route("/api/ed/proxy_img", methods=["POST"])
def ed_proxy_img():
    """外部磁盘图片读取中转：{path: 绝对路径} → 复制进 files/images/，返回相对 url。
    .note 拖图插入用——WebView2 页面内 fetch('file:///…') 被安全策略拦截，
    直传 multipart 又拿不到原始 File 对象，只能由后端读文件代劳。
    校验复用 upload_img 同款：后缀白名单 + 魔数 + 10MB 上限。"""
    import uuid
    data = request.get_json(force=True, silent=True) or {}
    path = data.get("path") or ""
    ext = os.path.splitext(path)[1].lower()
    if ext not in _IMG_EXT:
        return jsonify({"ok": False, "err": f"不支持的图片类型 {ext or '(无后缀)'}"}), 400
    p = os.path.abspath(path)
    if not os.path.isfile(p):
        return jsonify({"ok": False, "err": "文件不存在"}), 404
    try:
        with open(p, "rb") as f:
            head = f.read(12)
            if not _is_image_head(head, ext):
                return jsonify({"ok": False, "err": "文件内容与图片后缀不符"}), 400
            f.seek(0, 2)
            if f.tell() > 10 * 1024 * 1024:
                return jsonify({"ok": False, "err": "图片超过 10MB 上限"}), 400
    except OSError as e:
        return jsonify({"ok": False, "err": f"读取失败: {e}"}), 400
    os.makedirs(IMAGES_DIR, exist_ok=True)
    name = f"img_{int(time.time())}_{uuid.uuid4().hex[:8]}{ext}"
    try:
        shutil.copyfile(p, os.path.join(IMAGES_DIR, name))
    except OSError as e:
        return jsonify({"ok": False, "err": f"复制失败: {e}"}), 400
    return jsonify({"ok": True, "url": "images/" + name})
