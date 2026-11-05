# -*- coding: utf-8 -*-
"""文本 / 二进制判定回归网（a356R）。

为什么要有：`_looks_binary` 原先只看「前 8KB 有没有 NUL」，把串口采集的
BSP 启动日志判成二进制——用户双击打开被强行切到十六进制查看器（实锤：
121KB 日志里 661 个 NUL、0.54%，其余全是可读文本）。

判据改成两道：已知二进制后缀直接拒 + 可读字符占比 <90% 才判二进制。
这里把两道的边界钉死，防止下次「修 A 坏 B」。

直接 `python tests/test_editor_binary.py`。
"""
import os
import shutil
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.editor_files import _looks_binary, _safe_ext_path, _text_kind

_PASS, _FAIL = [], []


def check(name, cond, detail=""):
    (_PASS if cond else _FAIL).append(name)
    print(("  [ok] " if cond else "  [FAIL] ") + name
          + ("" if cond else "  " + str(detail)))


def _mk(d, name, data):
    p = os.path.join(d, name)
    with open(p, "wb") as f:
        f.write(data)
    return p


def main():
    d = tempfile.mkdtemp(prefix="edbin_")
    try:
        # ---- 必须判成文本（用户真实场景：串口日志里的零星 NUL）----
        check("零星 NUL 的启动日志是文本",
              not _looks_binary(_mk(d, "bsp.log",
                                    (b"[boot] ok\x00 next line\r\n") * 300)))
        check("正常 UTF-8 文本",
              not _looks_binary(_mk(d, "a.txt", "hello 中文\n".encode() * 500)))
        check("GBK 日志",
              not _looks_binary(_mk(d, "b.log",
                                    "[2026] 启动成功\r\n".encode("gb18030") * 500)))
        check("空文件按文本",
              not _looks_binary(_mk(d, "empty.txt", b"")))
        check("CRLF + 高位字节混合",
              not _looks_binary(_mk(d, "c.log",
                                    b"[11:33:01] \xd6\xd0\xce\xc4 ok\r\n" * 400)))

        # ---- 必须判成二进制 ----
        check("高密度 NUL",
              _looks_binary(_mk(d, "f.bin", b"ab\x00\x00\x00" * 3000)))
        check("PNG 头",
              _looks_binary(_mk(d, "d.png",
                                b"\x89PNG\r\n\x1a\n" + b"\x00" * 2000)))
        z = os.path.join(d, "c.zip")
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("a.txt", "x" * 2000)
        check("短 zip（内容接近纯文本也必须拒）", _looks_binary(z))
        check("后缀是 .exe 但内容像文本 → 仍判二进制",
              _looks_binary(_mk(d, "g.exe", b"hello world\n" * 100)))

        # ---- 三档分级（a357R：选择权交给用户）----
        check("纯文本 → text",
              _text_kind(_mk(d, "k1.log", b"hello\n" * 500)) == "text")
        check("半数不可读 → mixed",
              _text_kind(_mk(d, "k2.unk", b"abc\x00\x01\x02" * 400)) == "mixed")
        check("几乎全不可读 → binary",
              _text_kind(_mk(d, "k3.unk",
                             b"\x00\x01\x02\x03\x04" * 2000 + b"x" * 100))
              == "binary")
        check("mixed 不是 binary", not _looks_binary(
            _mk(d, "k4.unk", b"abc\x00\x01\x02" * 400)))

        # ---- 放行规则：用户明确选编辑器时，非结构文件都放行 ----
        mixed_p = _mk(d, "k5.unk", b"abc\x00\x01\x02" * 400)
        check("mixed 默认不放行", not _safe_ext_path(mixed_p))
        check("mixed 用户选了编辑器 → 放行",
              bool(_safe_ext_path(mixed_p, force=True)))
        bin_p = _mk(d, "k6.unk", b"\x00\x01\x02\x03\x04" * 2000 + b"x" * 100)
        check("内容像二进制 用户选了编辑器 → 放行",
              bool(_safe_ext_path(bin_p, force=True)))
        # 结构文件即使 force 也拒：编辑器写成文本 = 毁文件
        check("exe 即使 force 也拒",
              not _safe_ext_path(_mk(d, "k7.exe", b"hello\n" * 500), force=True))
        check("zip 即使 force 也拒",
              not _safe_ext_path(_mk(d, "k8.zip", b"PK\x03\x04" + b"\x00" * 500),
                                 force=True))

        # ---- 真实二进制样本（仓库自带）----
        for rel in ("vendor/rg.exe", "vendor/ctags/ctags.exe"):
            p = os.path.join(ROOT, rel)
            if os.path.isfile(p):
                check("真二进制 %s" % rel, _looks_binary(p))

        # ---- 用户实锤场景的完整复现（a356R）----
        # 121KB 启动日志、661 个 NUL（0.54%）、其余为带时间戳的可读行。
        # 判据必须放行，且 _read_text 能解出内容。
        import random
        random.seed(20261105)
        lines, nul_left = [], 661
        for i in range(900):
            line = "[2026-11-05 11:34:%02d.%03d]  boot step %d ok\r\n" % (
                i % 60, i % 1000, i)
            if nul_left > 0:
                pos = random.randint(10, len(line) - 5)
                line = line[:pos] + "\x00" + line[pos + 1:]
                nul_left -= 1
            lines.append(line)
        # 剩下的一次性塞进结尾几行（真实日志里 NUL 分布本来就不均匀）
        while nul_left > 0:
            lines.append("[2026-11-05 12:00:00.000]  tail\x00end\r\n")
            nul_left -= 1
        real = _mk(d, "real.log", "".join(lines).encode("utf-8"))
        size = os.path.getsize(real)
        check("实锤样本是文本", not _looks_binary(real),
              "size=%d" % size)
        check("实锤样本能被打开", bool(_safe_ext_path(real)))
        from src.editor_files import _read_text
        txt, err, used, _bom = _read_text(real)
        check("实锤样本可解码", err is None and bool(txt), err)
        check("实锤样本保留原文（NUL 不被吞）",
              txt is not None and txt.count("\x00") == 661,
              txt.count("\x00") if txt else "None")

        # ---- 打开路径整体放行（用户要的是"能打开"）----
        p = _mk(d, "open.log", (b"[boot] ok\x00 next line\r\n") * 300)
        check("safe_ext_path 放行", bool(_safe_ext_path(p)))
        check("safe_ext_path(force) 放行", bool(_safe_ext_path(p, force=True)))
        # 目录当文件传进来必须拒（_looks_binary 对目录 open 会 OSError）
        check("目录不放行", not _safe_ext_path(d))
    finally:
        shutil.rmtree(d, ignore_errors=True)

    print("\n%d passed, %d failed" % (len(_PASS), len(_FAIL)))
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
