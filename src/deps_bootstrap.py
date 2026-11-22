# -*- coding: utf-8 -*-
"""首次启动依赖自检（Electron 壳形态）。

安装包（PyInstaller + Electron）内所有 Python 依赖已打包，自检恒通过；
源码开发形态缺必需库时打印 pip 指引并让后端退出（壳弹「后端启动失败」，
stdout/stderr 进 electron-shell.log）。不再有 pywebview 安装引导窗——
pywebview/pythonnet/WebView2 已随换壳 P4 整体退役。

a356 铁律：只有**必需库**缺失才阻断；可选库（paramiko/pywinpty）缺失只
提示，绝不阻断启动（pyelftools 内网事故的根因就是可选库算进引导页）。
"""
import os
import sys
import importlib
import importlib.util
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# 依赖清单：pip 名 → (import 名, 是否必需, 中文用途说明)
DEPS = [
    ("flask",     ("flask",    True,  "HTTP 后端服务")),
    ("pyserial",  ("serial",   True,  "串口连接")),
    ("paramiko",  ("paramiko", False, "SSH 远程连接")),
    ("pywinpty",  ("winpty",   False, "内嵌 Claude 终端（ConPTY）")),
    # a356 紧急回撤（用户实锤：内网机打不开工具）：pyelftools 曾列入本表——
    # 但本闸门对可选库缺失同样阻断启动（missing=req+opt 全进引导页），
    # 内网无外网 pip 装不上 → 工具永远卡在首启安装页。跳转索引（nav_index）
    # 对缺库本就自动降级（符号层跳过、白名单照常）——预装毫无必要；
    # 需要时随 .fcpk 资源包的 pydeps 离线装。严禁再把非命脉库加进本表
]

def check_deps():
    """逐库探测。返回 (missing_required, missing_optional)——元素是 (pip名, 用途)。

    a668：先用 importlib.util.find_spec 判存在性，**存在就不再真 import**。
    原实现为每个库各跑一遍 importlib.import_module，实测冷态合计 577ms
    （flask 437 / paramiko 507 / winpty 115 / serial 84，大头是各自子依赖
    树）——而这些库启动后几秒内本来就会全部被真正 import，这里多花的一次
    纯属白等。find_spec 只做路径解析，全部库共 ~5ms。

    代价（明确的取舍）：find_spec 只看「装上没有」，看不出「装了但坏」
    （二进制 DLL 缺失、.pyd 架构不符）。这类机器会在后续真正 import 时
    报错——比原实现晚，但错误信息更具体。只有**找不到**时才真 import
    一次兜底：sys.path 运行时变动、命名空间包等场景下 find_spec 可能失手。
    """
    miss_req, miss_opt = [], []
    for pip_name, (mod_name, required, desc) in DEPS:
        try:
            if importlib.util.find_spec(mod_name) is not None:
                continue
        except (ImportError, ValueError, AttributeError):
            pass
        # find_spec 说不存在：再真 import 一次（父包已导入/元路径钩子等
        # 会让 find_spec 与 import 结论不一致）
        try:
            importlib.import_module(mod_name)
            continue
        except ImportError:
            pass
        except Exception:
            pass
        (miss_req if required else miss_opt).append((pip_name, desc))
    return miss_req, miss_opt


# ---- 启动自检（每机一次）：config 标记 deps_selftest_ok ----
def _selftest_flag_path():
    """标记文件与 config.json 同目录（app_state.HOME_DIR）——源码/打包两态同一路径。"""
    try:
        from src.app_state import HOME_DIR
        return os.path.join(HOME_DIR, "deps_selftest.json")
    except Exception:
        # app_state 依赖 flask 之外的纯标准库，但保险起见给独立回退
        return os.path.join(os.path.expanduser("~"), ".serialconsole_pro",
                            "deps_selftest.json")


def selftest_once():
    """启动早期调用（main.py，在 bootstrap_if_needed 之后）：
    探测一轮依赖，全通过 → 写标记，此后启动不再测（用户要求：只一次）。
    有缺失 → 返回缺失清单给调用方弹提醒（每启动都提醒，除非用户用离线包补装）。
    返回 (ok, miss_req, miss_opt, skipped)。"""
    flag = _selftest_flag_path()
    # 标记存在且值 ok → 不再测
    try:
        import json
        with open(flag, "r", encoding="utf-8") as f:
            d = json.load(f)
        if d.get("ok"):
            return True, [], [], True   # skipped：之前测过，直接放行
    except Exception:
        pass
    miss_req, miss_opt = check_deps()
    if not (miss_req or miss_opt):
        try:
            import json
            os.makedirs(os.path.dirname(flag), exist_ok=True)
            with open(flag, "w", encoding="utf-8") as f:
                json.dump({"ok": True, "ts": time.time()}, f)
        except Exception:
            pass
        return True, [], [], False
    return False, miss_req, miss_opt, False


def mark_selftest_ok():
    """离线包补装依赖成功后调用：写标记，后续启动不再弹提醒。"""
    try:
        import json
        flag = _selftest_flag_path()
        os.makedirs(os.path.dirname(flag), exist_ok=True)
        with open(flag, "w", encoding="utf-8") as f:
            json.dump({"ok": True, "ts": time.time()}, f)
    except Exception:
        pass


def _message_box(text):
    """pythonw 下唯一可见的原生 UI（无任何第三方依赖，仅 Win32）。"""
    try:
        import ctypes
        # MB_ICONWARNING | MB_SETFOREGROUND | MB_TOPMOST
        ctypes.windll.user32.MessageBoxW(0, text, "前端控制台 · 依赖安装", 0x50040)
    except Exception:
        pass


def bootstrap_if_needed():
    """main.py 启动早期调用。缺必需库 → 打印 pip 指引并让调用方退出。

    Electron 壳形态不再有 pywebview 引导窗：安装包内依赖已全部打包；源码
    开发缺库时按下面的命令装完重启即可（壳错误框 + stderr 都有指引）。
    a356 铁律：可选库缺失只提示，绝不阻断启动。
    """
    miss_req, miss_opt = check_deps()
    if miss_opt:
        print("[deps] 可选库缺失（不阻断，需要时用离线资源包补装）：%s"
              % ", ".join(p for p, _ in miss_opt))
    if not miss_req:
        return True
    pip_cmd = "pip install " + " ".join(p for p, _ in miss_req)
    text = ("缺少工具本体依赖：%s\n\n请在工具所用 Python 环境执行：\n\n    %s"
            % (", ".join(p for p, _ in miss_req), pip_cmd))
    print("=" * 56)
    print(text)
    print("=" * 56)
    _message_box(text)
    return False
