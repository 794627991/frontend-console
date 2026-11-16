# -*- coding: utf-8 -*-
"""a588 回归：本地终端的代码页行为与 cwd 校验。

钉两个「不报错但结果错」的缺陷，都是我在 a581 引入的：

1. `chcp 65001` 写进 argv：cmd 在 65001 下 `type` 既有 GBK 日志输出
   `����־`，`python x.py > out.txt` 后 `type out.txt` 同样乱码；默认 936
   下这两类都正确。ConPTY 已负责把子进程输出转成 UTF-8，不该改代码页。
2. `PYTHONIOENCODING=utf-8` 注入 env：后果同 1（写出的字节变了）。
3. 后端没校验 cwd 是绝对路径：相对路径按 Flask 进程 cwd 解析。

测试靠断言 argv/env 的**内容**，不真 spawn（spawn 在 CI 上无 ConPTY）。
真 spawn 的验证见 a588 提交说明里的实测记录。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import shell_conn as S          # noqa: E402


# ---- 1/2. 代码页与编码变量 -------------------------------------------
def test_no_chcp_in_any_shell_argv():
    """任何 shell 的 argv 都不许出现 chcp / 65001。"""
    for key, (name, argv) in S.SHELLS.items():
        blob = " ".join(argv).lower()
        assert "chcp" not in blob, "%s 的 argv 仍带 chcp：%r" % (key, argv)
        assert "65001" not in blob, "%s 的 argv 仍带 65001：%r" % (key, argv)


def test_cmd_argv_keeps_k_flag():
    """cmd 必须带 /K（常驻），且没有第三条参数。"""
    name, argv = S.SHELLS["cmd"]
    assert argv[0] == "cmd.exe"
    assert argv[1] == "/K"
    assert len(argv) == 2, argv


def test_powershell_argv_has_no_command_param():
    name, argv = S.SHELLS["powershell"]
    assert "-NoExit" in argv
    assert "-Command" not in argv, argv


def _captured_env(monkeypatch_argv="cmd"):
    """走 _io_open 但把 spawn 换成记录器，返回它收到的 env。"""
    got = {}

    class _FakeProc:
        def isalive(self): return False
        def read(self, n): raise EOFError
        def write(self, s): pass
        def terminate(self, force=False): pass

    class _FakePP:
        class PtyProcess:
            @staticmethod
            def spawn(argv, cwd=None, env=None, dimensions=None):
                got["argv"] = argv
                got["cwd"] = cwd
                got["env"] = env
                return _FakeProc()

    orig = S._get_pty
    S._get_pty = lambda: _FakePP
    try:
        c = S.ShellConnection.__new__(S.ShellConnection)
        import threading as _t
        c.port_id = "shell:test:1"
        c.lock = _t.Lock()
        c.shell_key, c.shell_name, c._argv = S._resolve_shell(monkeypatch_argv)
        c.cwd = os.getcwd()
        c._cols, c._rows = 120, 30
        c._proc = None
        c._io_open()
    finally:
        S._get_pty = orig
    return got


def test_env_does_not_force_python_encoding():
    got = _captured_env()
    env = got["env"]
    assert "PYTHONIOENCODING" not in env, "不该注入 PYTHONIOENCODING：%r" % env.get("PYTHONIOENCODING")
    # TERM/COLORTERM 用 setdefault：CI/宿主可能已有值，这里只要求「有值」
    assert env.get("TERM")
    assert env.get("COLORTERM")
    assert got["argv"] == ["cmd.exe", "/K"]


# ---- 3. cwd 必须是绝对路径 --------------------------------------------
def test_validate_cwd_rejects_relative():
    """相对路径必须拒——它存在且是目录，但会被 Flask 进程 cwd 解析。"""
    import tempfile
    cwd = os.getcwd()
    path = tempfile.mkdtemp(dir=cwd)
    try:
        name = os.path.basename(path)
        assert not os.path.isabs(name)
        assert os.path.isdir(name)                     # 相对名确实指向真实目录
        err = S.validate_cwd(name)
        assert err and "绝对路径" in err, err
    finally:
        os.rmdir(path)


def test_validate_cwd_accepts_and_rejects():
    assert S.validate_cwd("") is None            # 空 = 主目录
    assert S.validate_cwd(os.getcwd()) is None   # 绝对且存在
    assert "绝对路径" in S.validate_cwd("docs")   # 相对
    missing = os.path.join(os.getcwd(), "__no_such_dir_a588__")
    assert "不存在" in S.validate_cwd(missing)


def test_connection_constructor_uses_same_judgement():
    """ShellConnection 与 API 层共用 validate_cwd（不再各写一半）。"""
    try:
        S.ShellConnection(shell="cmd", cwd="docs", port_id="shell:test:rel")
        raise AssertionError("相对路径应当构造失败")
    except ValueError as e:
        assert "绝对路径" in str(e), e


def test_resolve_shell_falls_back_to_cmd():
    key, name, argv = S._resolve_shell("not-a-shell")
    assert key == "cmd"
    assert argv == S.SHELLS["cmd"][1]
