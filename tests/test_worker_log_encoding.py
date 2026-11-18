# -*- coding: utf-8 -*-
"""worker 日志中文乱码修复（a643）。

用户实锤：后端日志里 worker 的中文全是方块（`Lanz ��¼�ɹ�`）。

根因：worker 子进程 stdout 中文按系统默认编码（中文 Windows = GBK）写出，
而父进程 `decode("utf-8", "replace")` → 每个中文字节都变成 U+FFFD。

本测钉住：
1. _spawn_cmd 给子进程注入 UTF-8 输出编码（两端对齐）
2. _decode_worker_line 对 UTF-8 / GBK 都能正确解出中文（升级残留的旧
   worker 仍可能按 GBK 写）
"""
import sys

sys.path.insert(0, '.')

import src.worker_app as wa

TXT = "蓝奏登录成功：gaoyi13"


def test_spawn_cmd_forces_utf8_output():
    """子进程必须被要求按 UTF-8 输出，否则父进程按 UTF-8 解必乱码。"""
    cmd, env, cwd = wa._spawn_cmd(12345)
    assert env.get("PYTHONIOENCODING", "").lower().startswith("utf-8")
    assert env.get("PYTHONUTF8") == "1"


def test_decode_utf8_and_gbk():
    """两种编码写出的中文都能正确解出（不再产生替代符）。"""
    assert wa._decode_worker_line(TXT.encode("utf-8")) == TXT
    assert wa._decode_worker_line(TXT.encode("gbk")) == TXT


def test_decode_never_raises_on_garbage():
    """真正的坏字节仍要走 replace，不能抛异常打断日志泵。"""
    out = wa._decode_worker_line(b"\xff\xfe\xff")
    assert isinstance(out, str)


def test_decode_preserves_ascii_and_newlines():
    """ASCII 行（含 ANSI 转义）原样返回——werkzeug 那些行不能被动。"""
    raw = b" * Running on http://127.0.0.1:58870\r\n"
    assert wa._decode_worker_line(raw).rstrip() == \
        " * Running on http://127.0.0.1:58870"
