# -*- coding: utf-8 -*-
"""Cython 源码保护编译器（v2.3.2，用户定调「治本」）：自有 .py → .pyd 机器码。

威胁模型：防「本机翻文件」——pyc 反编译工具成熟，但 .pyd 是原生机器码，
逆向=IDA 级；磁盘上不存在明文/可反编译形态，无需加密无密钥（web 前端源码
仍走 AES：JS 不是 Python，Cython 管不到——见 encrypt_pkg.py）。

产物：build/_cython/src/<name>.cp314-win_amd64.pyd（包结构平铺，含 __init__），
encrypt_pkg 负责摆到 _internal/src/。main.py 不编译（PyInstaller 入口脚本）。

编译链：cython --3 → cl /O2（vcvars64 环境）→ python314.lib 链接。
增量：源 mtime <= 产物 mtime 跳过（日常打包只重编译改动过的模块）。
"""
import os, sys, subprocess, glob

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, "src")
OUT = os.path.join(BASE, "build", "_cython", "src")
_TAG = "cp%d%d-win_amd64" % sys.version_info[:2]

# 发布机专用模块不进同事包（用户定调「服务分发不要随打包」）：
#   update_server——升级分发门户（8765）：同事机不需要，带着还多一个可被
#     利用的假门户面；updater（升级客户端）保留。
#   build——打包脚本，只在发布机跑。
#   secure_boot——加密器（tools/encrypt_pkg）在 dev 引用；exe 的自举解密
#     逻辑已内联在 main.py 顶部，同事包不需要它。
_EXCLUDE = {"update_server.py", "build.py", "secure_boot.py"}


def _find_vcvars():
    for pat in (r"C:\Program Files (x86)\Microsoft Visual Studio\*\BuildTools\VC\Auxiliary\Build\vcvars64.bat",
                r"C:\Program Files\Microsoft Visual Studio\*\BuildTools\VC\Auxiliary\Build\vcvars64.bat",
                r"C:\Program Files (x86)\Microsoft Visual Studio\*\Community\VC\Auxiliary\Build\vcvars64.bat",
                r"C:\Program Files\Microsoft Visual Studio\*\Community\VC\Auxiliary\Build\vcvars64.bat"):
        hit = sorted(glob.glob(pat))
        if hit:
            return hit[-1]      # 最高版本
    return None


def _msvc_env():
    """v2.3.3 绕过 vcvars64（本机 VsDevCmd 深处报「找不到网络路径」，SDK 装了
    也起不来）——直接枚举 MSVC/Windows SDK 目录手工构造 INCLUDE/LIB/PATH。
    返回 (env_dict, cl_path) 或 (None, None)。"""
    msvc_root = None
    for pat in (r"C:\Program Files (x86)\Microsoft Visual Studio\*\BuildTools\VC\Tools\MSVC\*",
                r"C:\Program Files\Microsoft Visual Studio\*\BuildTools\VC\Tools\MSVC\*",
                r"C:\Program Files (x86)\Microsoft Visual Studio\*\Community\VC\Tools\MSVC\*",
                r"C:\Program Files\Microsoft Visual Studio\*\Community\VC\Tools\MSVC\*"):
        hit = sorted(glob.glob(pat))
        if hit:
            msvc_root = hit[-1]
            break
    sdk_inc = sorted(glob.glob(r"C:\Program Files (x86)\Windows Kits\10\Include\*"))
    sdk_lib = sorted(glob.glob(r"C:\Program Files (x86)\Windows Kits\10\Lib\*"))
    if not (msvc_root and sdk_inc and sdk_lib):
        return None, None
    sdk_ver_inc, sdk_ver_lib = sdk_inc[-1], sdk_lib[-1]
    inc = [os.path.join(msvc_root, "include"),
           os.path.join(sdk_ver_inc, "ucrt"),
           os.path.join(sdk_ver_inc, "um"),
           os.path.join(sdk_ver_inc, "shared")]
    lib = [os.path.join(msvc_root, "lib", "x64"),
           os.path.join(sdk_ver_lib, "ucrt", "x64"),
           os.path.join(sdk_ver_lib, "um", "x64")]
    env = dict(os.environ)
    env["INCLUDE"] = ";".join(inc)
    env["LIB"] = ";".join(lib)
    cl = os.path.join(msvc_root, "bin", "Hostx64", "x64", "cl.exe")
    if not os.path.isfile(cl):
        return None, None
    env["PATH"] = os.path.dirname(cl) + os.pathsep + env.get("PATH", "")
    return env, cl


def build_all(force=False):
    """编译 src/*.py（main.py 除外）→ OUT/*.pyd。返回 (成功数, 失败列表)。"""
    env, cl = _msvc_env()
    if not cl:
        raise RuntimeError("未找到 MSVC/SDK 组合（cl.exe 或 Windows Kits）")
    py_inc = sysconfig_include()
    os.makedirs(OUT, exist_ok=True)
    mods = [f for f in os.listdir(SRC)
            if f.endswith(".py") and f != "main.py" and f not in _EXCLUDE]
    ok, fails = 0, []
    for i, f in enumerate(mods):
        stem = os.path.splitext(f)[0]
        pyd = os.path.abspath(os.path.join(OUT, "%s.%s.pyd" % (stem, _TAG)))
        cfile = os.path.abspath(os.path.join(OUT, stem + ".c"))
        if not force and os.path.isfile(pyd) and \
                os.path.getmtime(pyd) >= os.path.getmtime(os.path.abspath(os.path.join(SRC, f))):
            ok += 1
            continue
        # cython：纯编译（不自动调编译器，我们自己用 cl 控制 flag）
        r = subprocess.run([sys.executable, "-m", "cython", "--3", "-o", cfile,
                            os.path.abspath(os.path.join(SRC, f))],
                           capture_output=True, text=True)
        if r.returncode != 0:
            fails.append((f, "cython: " + (r.stderr or r.stdout)[-200:]))
            continue
        # cl：手工 env（INCLUDE/LIB 注入，绕过本机起不来的 vcvars64）。
        # /Fo 把 .obj 中间产物收进 build/_cython/obj——默认落在 cwd（项目根），
        # 每次编译在根目录拉 35 个 .obj 垃圾（用户实锤）。
        objdir = os.path.join(os.path.dirname(OUT), "obj")
        os.makedirs(objdir, exist_ok=True)
        r = subprocess.run(
            [cl, "/nologo", "/O2", "/LD", "/DWIN32", "/D_WINDOWS",
             "/I" + py_inc, cfile,
             "/Fo:" + objdir + os.sep,
             "/Fe:" + pyd,
             "/link", "/LIBPATH:" + os.path.join(os.path.dirname(sys.executable), "libs"),
             "python%d%d.lib" % sys.version_info[:2]],
            capture_output=True, text=True, encoding="gbk", errors="replace",
            env=env)
        if r.returncode != 0 or not os.path.isfile(pyd):
            fails.append((f, "cl: " + ((r.stderr or "") + (r.stdout or ""))[-300:]))
            continue
        ok += 1
        print("  ✓ %s.pyd" % stem)
    return ok, fails


def sysconfig_include():
    import sysconfig
    return sysconfig.get_paths()["include"]


def staged_pyd_paths():
    """编译产物清单（encrypt_pkg 摆包用）：OUT 下全部 .pyd 绝对路径。"""
    return glob.glob(os.path.join(OUT, "*.pyd"))


if __name__ == "__main__":
    n, fails = build_all(force="--force" in sys.argv)
    print("\n编译完成: %d/%d" % (n, len([f for f in os.listdir(SRC)
          if f.endswith(".py") and f != "main.py"])))
    for f, why in fails:
        print("  ✗ %s: %s" % (f, why))
    sys.exit(1 if fails else 0)
