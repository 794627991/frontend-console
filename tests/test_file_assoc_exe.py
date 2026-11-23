# -*- coding: utf-8 -*-
"""文件关联启动命令的源码形态兜底（src/file_assoc.py::_app_exe）。

注册表里 shell\\open\\command 写的是「谁来了就拉起壳」。正常链路由壳 spawn
后端时注入 FC_SHELL_EXE / FC_SHELL_APP，这里测的是 env 缺失时的兜底：
  · 打包形态：<install>\\前端控制台.exe（由 resources\\backend\\<后端 exe> 上溯三级）
  · 源码形态：与 run.bat 同序——项目内 node_modules 的 electron.exe →
    上一级的离线运行时（资源包装出）→ 都没有仍写首选路径（装好即生效）

2026-11-23 总审计 a683-A7：源码兜底原只认 node_modules 那一个位置，离线
形态旁路启动（没有 FC_SHELL_EXE）时往注册表里写的是不存在的路径。

全程不碰注册表：只调 _app_exe（纯字符串拼接 + isfile 探测）。
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src import file_assoc as fa   # noqa: E402

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(fa.__file__)))
ELECTRON_DIR = os.path.join(PROJECT, "electron")
LOCAL = os.path.join(ELECTRON_DIR, "node_modules", "electron", "dist",
                     "electron.exe")
OFFLINE = os.path.join(os.path.dirname(PROJECT), "offline_runtime", "electron",
                       "electron.exe")


@pytest.fixture
def exe_env(monkeypatch):
    """清掉 env 注入、让两个候选路径的存在性完全由用例决定。

    只对这两个候选路径接管 isfile——开发机上 node_modules 里的 electron.exe
    往往真实存在，若对它透传真实文件系统，「本地没装」的场景就模拟不出来；
    其余路径照常透传。
    """
    monkeypatch.delenv("FC_SHELL_EXE", raising=False)
    monkeypatch.delenv("FC_SHELL_APP", raising=False)
    assert not getattr(sys, "frozen", False), "本用例只在非打包的源码形态下有意义"
    real = os.path.isfile
    cands = {os.path.normcase(LOCAL), os.path.normcase(OFFLINE)}

    def install(*existing):
        have = {os.path.normcase(p) for p in existing}
        monkeypatch.setattr(os.path, "isfile",
                            lambda p: (os.path.normcase(p) in have)
                            if os.path.normcase(p) in cands else real(p))
    return install


def test_env_injection_wins(monkeypatch):
    monkeypatch.setenv("FC_SHELL_EXE", r"C:\Apps\Shell.exe")
    monkeypatch.setenv("FC_SHELL_APP", r"C:\Apps\resources\app")
    assert fa._app_exe() == '"C:\\Apps\\Shell.exe" "C:\\Apps\\resources\\app"'
    monkeypatch.delenv("FC_SHELL_APP")
    assert fa._app_exe() == '"C:\\Apps\\Shell.exe"'


def test_source_fallback_prefers_project_local_runtime(exe_env):
    exe_env(LOCAL, OFFLINE)
    assert fa._app_exe() == '"%s" "%s"' % (LOCAL, ELECTRON_DIR)


def test_source_fallback_uses_offline_runtime_when_local_missing(exe_env):
    """离线形态（资源包装出，没跑过 npm install）：必须指到离线运行时。"""
    exe_env(OFFLINE)                       # node_modules 里没有
    assert fa._app_exe() == '"%s" "%s"' % (OFFLINE, ELECTRON_DIR), \
        "旧实现返回不存在的 node_modules 路径"


def test_source_fallback_when_nothing_installed_still_names_shell(exe_env):
    exe_env()                              # 两处都没有
    got = fa._app_exe()
    assert got == '"%s" "%s"' % (LOCAL, ELECTRON_DIR)
    # 绝不能退回后端自身的解释器/exe（那是无 UI 的 sidecar）
    assert "python" not in got.lower() and sys.executable not in got


def test_open_command_appends_open_file_flag(exe_env):
    exe_env(LOCAL)
    cmd = fa._open_command()
    assert cmd.startswith('"' + LOCAL + '" "' + ELECTRON_DIR + '"')
    assert cmd.endswith(' --open-file "%1"')


def test_offline_runtime_path_matches_run_bat():
    """兜底顺序与路径必须和 run.bat 的三级兜底同口径（两处各写一份，
    改一处要一起改）。"""
    with open(os.path.join(ROOT, "run.bat"), "rb") as f:
        raw = f.read()
    for enc in ("utf-8", "gbk"):
        try:
            bat = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    assert '"..\\offline_runtime\\electron\\electron.exe"' in bat, \
        "run.bat 的离线运行时相对路径变了——同步 _app_exe"
    assert "offline_runtime" + os.sep + "electron" in OFFLINE


if __name__ == "__main__":
    import pytest as _pt
    sys.exit(_pt.main([__file__, "-q"]))
