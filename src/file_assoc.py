# -*- coding: utf-8 -*-
r"""文件关联接管/还原（Flask Blueprint 路由 /api/assoc/*）。

背景（用户需求）：txt 等文本文件默认用记事本打开；「接管」后双击改用本工具
打开，「还原」恢复成记事本（或系统原默认）。

Windows 实现（ProgId 方案，同 VSCode/Notepad++ 的做法）：
- 接管：
  1. HKCU\Software\Classes\SerialConsolePro.Text  注册 ProgId
     defaulticon  → 工具 exe 图标（源码运行用 pythonw 的）
     shell\open\command → "<exe>" --open-file "%1"
  2. HKCU\...\Software\Classes\<.ext>\OpenWithProgids  加 ProgId 引用
  3. HKCU\...\Software\Classes\<.ext>\(Default) = ProgId ——老式关联链
     （Win10 资源管理器对无 UserChoice 的后缀按此解析；txt 默认正是
     走 HKCU\Software\Classes\.txt\(Default)=txtfile 链）。
     FileExts\UserChoice 受系统 hash 保护不可写；若系统已有 UserChoice
     优先级更高，资源管理器不生效——此时提示用户去系统「打开方式→
     选择另一应用→始终」选一次本工具（一次性，UserChoice 会由系统写）。
- 还原：恢复接管前备份的原 Default 值（config.json assoc_backup 键），
  删 OpenWithProgids 引用；全部还原后 ProgId 一并清理，注册表不留孤儿。
- 状态查询：各后缀 .ext\(Default) 是否指向本 ProgId。

只动 HKCU（无需管理员权限），不动 HKLM——干净、可完全还原。
docstring 加 r 前缀：\S \U 在普通字符串里是非法转义（unicodeescape 报错曾中招）。
"""
import os, sys, json
import winreg
from flask import Blueprint, request, jsonify

from src.app_state import _load_config, _save_config

assoc_bp = Blueprint("assoc", __name__)

PROG_ID = "SerialConsolePro.Text"
_CLASSES = r"Software\Classes"
# 后缀 → 图标 design 名（ico/ext/<design>.ico，tools/gen_ext_icons.py 生成）。
# 桌面/资源管理器图标按后缀区分（用户需求：手绘文件主体+像素机器人角标，
# 不同后缀不同形）——每后缀独立 ProgId（SerialConsolePro.Text.<design>），
# 各自 DefaultIcon 指向专属 ico；之前 19 个后缀共用一个 ProgId 一个图标，
# 桌面上 txt/log/c/h/json 全长一个样。
EXT_ICON_MAP = {
    ".txt": "txt", ".log": "log", ".md": "md",
    ".ini": "ini", ".cfg": "ini", ".conf": "ini",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml",
    ".c": "c", ".h": "h", ".cpp": "cpp", ".hpp": "cpp",
    ".py": "py", ".sh": "sh", ".bat": "sh", ".cmd": "sh", ".ps1": "sh",
    ".xml": "xml",
}
# 支持接管的后缀（与编辑器文本白名单对齐，挑常用）
ASSOC_EXTS = [".txt", ".log", ".md", ".ini", ".cfg", ".conf", ".json", ".yaml", ".yml",
              ".c", ".h", ".cpp", ".hpp", ".py", ".sh", ".bat", ".cmd", ".ps1", ".xml"]


def _prog_id(ext):
    """后缀专属 ProgId：SerialConsolePro.Text.<design>（各自独立图标）。"""
    return f"{PROG_ID}.{EXT_ICON_MAP.get(ext, 'txt')}"


def _app_exe():
    """工具可执行路径：exe 分发=本 exe；源码运行=pythonw + main.py。"""
    if getattr(sys, "frozen", False):
        return sys.executable
    # 源码运行：pythonw 跑 src/main.py（命令行形态与 exe --open-file 一致）
    main_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
    pyw = sys.executable.replace("python.exe", "pythonw.exe")
    return f'"{pyw}" "{main_py}"'


def _open_command():
    r"""shell\open\command 的值（%(1)s 占位文件路径）。"""
    return f'{_app_exe()} --open-file "%1"'


def _ext_default(ext):
    r"""读 HKCU\<.ext>\(Default)（老式关联链；无返回 ''）。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, f"{_CLASSES}\\{ext}") as k:
            v, _ = winreg.QueryValueEx(k, "")
            return v or ""
    except OSError:
        return ""


def _set_backup(ext, old_default):
    """接管前备份 .ext 原 Default 值（还原依据；_save_config 整份替换须先合并）。"""
    cfg = _load_config()
    backup = cfg.get("assoc_backup") or {}
    if ext not in backup:
        backup[ext] = {"default": old_default}
        cfg["assoc_backup"] = backup
        _save_config(cfg)


def _clear_backup(ext):
    """还原后清备份条目。"""
    cfg = _load_config()
    backup = cfg.get("assoc_backup") or {}
    if ext in backup:
        del backup[ext]
        cfg["assoc_backup"] = backup
        _save_config(cfg)


def _take_over_ext(ext):
    """接管单后缀：备份原值 → 指向后缀专属 ProgId → OpenWithProgids 加引用。"""
    pid = _prog_id(ext)
    _set_backup(ext, _ext_default(ext))
    # 1. .ext\(Default) = ProgId（老式链：双击打开方式）
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, f"{_CLASSES}\\{ext}") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, pid)
    # 2. OpenWithProgids：加入「打开方式」候选
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, f"{_CLASSES}\\{ext}\\OpenWithProgids") as k:
        winreg.SetValueEx(k, pid, 0, winreg.REG_SZ, "")
    # 3. 清老版本共用 ProgId 的残留引用（曾 19 后缀共用 SerialConsolePro.Text）
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, f"{_CLASSES}\\{ext}\\OpenWithProgids") as k:
            winreg.DeleteValue(k, PROG_ID)
    except OSError:
        pass
    return True


def _restore_ext(ext):
    """还原单后缀：恢复备份的原 Default（无备份→删除键值走系统默认）+ 删引用。"""
    pid = _prog_id(ext)
    backup = _load_config().get("assoc_backup") or {}
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, f"{_CLASSES}\\{ext}") as k:
        old = (backup.get(ext) or {}).get("default", "")
        if old:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, old)
        else:
            try:
                winreg.DeleteValue(k, "")
            except OSError:
                pass
    for ref in (pid, PROG_ID):  # 新专属 + 老共用，都清
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, f"{_CLASSES}\\{ext}\\OpenWithProgids") as k:
                winreg.DeleteValue(k, ref)
        except OSError:
            pass
    if ext in backup:
        _clear_backup(ext)
    return True


def _stable_icon_path(design):
    r"""后缀专属 ico 的稳定路径（注册表 DefaultIcon 要长期有效）。
    源码运行：项目根 ico/ext/。打包 exe：_MEIPASS 是 onefile 每次启动变的
    临时解压目录不能进注册表——首用到 %LOCALAPPDATA% 固定落盘。"""
    if not getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "ico", "ext", design + ".ico")
    base = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "SerialConsolePro", "ico", "ext")
    dst = os.path.join(base, design + ".ico")
    if not os.path.exists(dst):
        src = os.path.join(getattr(sys, "_MEIPASS", ""), "ico", "ext", design + ".ico")
        os.makedirs(base, exist_ok=True)
        if os.path.exists(src):
            import shutil
            shutil.copy2(src, dst)
    return dst


def _register_prog_id(design):
    """注册/刷新一个后缀专属 ProgId（命令 + 该后缀专属图标）。幂等。"""
    pid = f"{PROG_ID}.{design}"
    root = f"{_CLASSES}\\{pid}"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, root) as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, f"前端控制台 {design.upper()} 文件")
    # 图标：每后缀专属 ico（用户需求：桌面 txt/log/c/h/json 要能区分）。
    # exe 的内嵌图标只有 app.ico 一个——全指它就全同款了，不采用。
    icon = f'"{_stable_icon_path(design)}",0'
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, root + r"\DefaultIcon") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, icon)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, root + r"\shell\open\command") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, _open_command())


def _remove_prog_id():
    """删全部 ProgId（专属的逐 design + 老共用），还原全部后缀后清理。"""
    designs = set(EXT_ICON_MAP.values())
    for design in designs:
        pid = f"{PROG_ID}.{design}"
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, f"{_CLASSES}\\{pid}\\shell\\open\\command")
        except OSError:
            pass
        for sub in (r"\shell\open", r"\shell", r"\DefaultIcon"):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, f"{_CLASSES}\\{pid}{sub}")
            except OSError:
                pass
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, f"{_CLASSES}\\{pid}")
        except OSError:
            pass
    # 老版本共用 ProgId（可能仍被早期接管的后缀引用）
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, f"{_CLASSES}\\{PROG_ID}\\shell\\open\\command")
    except OSError:
        pass
    for sub in (r"\shell\open", r"\shell", r"\DefaultIcon"):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, f"{_CLASSES}\\{PROG_ID}{sub}")
        except OSError:
            pass
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, f"{_CLASSES}\\{PROG_ID}")
    except OSError:
        pass


@assoc_bp.route("/api/assoc/status")
def assoc_status():
    r"""各后缀接管状态：.ext\(Default) 是否指向本工具的 ProgId。"""
    items = []
    for ext in ASSOC_EXTS:
        items.append({"ext": ext, "taken": _ext_default(ext) in (_prog_id(ext), PROG_ID),
                      "design": EXT_ICON_MAP.get(ext, "txt")})
    return jsonify({"ok": True, "items": items,
                    "open_command": _open_command()})


@assoc_bp.route("/api/assoc/takeover", methods=["POST"])
def assoc_takeover():
    """接管：{exts: [".txt", ...]}。注册各后缀专属 ProgId + 指向。"""
    data = request.get_json(force=True, silent=True) or {}
    exts = data.get("exts") or []
    exts = [e for e in exts if e in ASSOC_EXTS]
    if not exts:
        return jsonify({"ok": False, "err": "未选择有效后缀"})
    try:
        for design in {EXT_ICON_MAP[e] for e in exts}:
            _register_prog_id(design)
        for ext in exts:
            _take_over_ext(ext)
    except OSError as e:
        return jsonify({"ok": False, "err": f"注册表写入失败：{e}"})
    return jsonify({"ok": True, "exts": exts})


@assoc_bp.route("/api/assoc/restore", methods=["POST"])
def assoc_restore():
    """还原：{exts: [".txt", ...]}。恢复备份原值；全部还原后删全部 ProgId。"""
    data = request.get_json(force=True, silent=True) or {}
    exts = data.get("exts") or []
    exts = [e for e in exts if e in ASSOC_EXTS]
    if not exts:
        return jsonify({"ok": False, "err": "未选择有效后缀"})
    try:
        for ext in exts:
            _restore_ext(ext)
        # 已无任何接管后缀 → ProgId 一并清理（注册表不留孤儿）
        remaining = [e for e in ASSOC_EXTS
                     if _ext_default(e) in (_prog_id(e), PROG_ID)]
        if not remaining:
            _remove_prog_id()
    except OSError as e:
        return jsonify({"ok": False, "err": f"注册表写入失败：{e}"})
    return jsonify({"ok": True, "exts": exts})
