# -*- coding: utf-8 -*-
"""vcs_remote 纯函数回归（a457 三路对抗审计收编）。

覆盖三路审计修过的行为面，全部不依赖 SSH/网络：
- _allowed 白名单（rev-list 补录 / git -c 真子命令校验 / 危险子命令拒绝）
- _enc/_dec 加密往返、nonce 唯一、篡改必败
- _quote 注入转义
- to_remote 切片对齐（尾反斜杠/大小写漂移回归）
- _map_argv 只翻工程根下路径（提交说明绝对路径形态不改写回归）
- _match_or_add_profile 对非数字 port 的健壮性
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import vcs_remote as vr   # noqa: E402


def test_allowed_legit():
    ok = [
        ["svn", "status", "--xml"],
        ["svn", "info", "--xml"],
        ["svn", "cat", "-r", "BASE", "W:\\x\\a.c"],
        ["svn", "diff", "--summarize", "-c", "123", "."],
        ["svn", "add", "--", "a"],
        ["svn", "commit", "-m", "msg"],
        ["svn", "update"],
        ["svn", "log", "-l", "30"],
        ["git", "status", "--porcelain"],
        ["git", "log", "-5"],
        ["git", "show", "HEAD:a/b"],
        ["git", "diff"],
        ["git", "add", "."],
        ["git", "commit", "-m", "m"],
        ["git", "pull"],
        ["git", "rev-parse", "--short", "HEAD"],
        ["git", "rev-list", "--count", "HEAD"],           # G2：log 首页必发
        ["git", "-c", "core.quotepath=false", "status", "--porcelain=v1", "-z", "--branch"],
        ["git", "-c", "core.quotepath=false", "show", "HEAD:x"],
        ["git", "-c", "core.quotepath=false", "-c", "x=y", "rev-parse", "HEAD"],
    ]
    for argv in ok:
        assert vr._allowed(argv), argv


def test_allowed_reject():
    bad = [
        ["git", "-c", "core.quotepath=false", "push", "--force"],   # F5：-c 后任意子命令
        ["git", "-c", "a=b", "-c", "c=d", "-C", "/x", "-c", "e=f",
         "-c", "g=h", "push"],                                      # 8 位窗口外仍校验到
        ["git", "clone", "http://x"],
        ["git", "push"],
        ["git", "fetch"],
        ["svn", "revert", "-R", "."],                               # F11：能力边界外
        ["rm", "-rf", "/"],
        ["sh", "-c", "x"],
        ["bash", "-c", "x"],
        ["svn"],
        ["git"],
        [],
    ]
    for argv in bad:
        assert not vr._allowed(argv), argv


def test_enc_dec_roundtrip():
    for pwd in ("p@ss 'quote\" 中文", "x" * 300, "a"):
        assert vr._dec(vr._enc(pwd)) == pwd


def test_enc_nonce_and_tamper():
    blob = vr._enc("secret1")
    assert blob != vr._enc("secret1")            # 随机 nonce，两次密文不同
    assert vr._dec(blob[:-4] + "AAAA") == ""     # 篡改必败 → 当未配置
    assert vr._dec("") == ""
    assert vr._dec("not-base64!!!") == ""


def test_quote_injection():
    assert vr._quote("abc-123_x.y") == "abc-123_x.y"
    # POSIX 逃生四连 = ' \ ' '（引号-反斜杠-引号-引号），用 chr 显式拼杜绝
    # 测试自身的转义歧义（本串在审计过程中写错三次，教训立此存照）
    s = "a'; rm -rf /; '"
    esc = chr(39) + chr(92) + chr(39) + chr(39)
    assert vr._quote(s) == chr(39) + "a" + esc + "; rm -rf /; " + esc + chr(39)
    assert vr._quote("$(id)") == "'$(id)'"


def test_to_remote_alignment():
    e = {"local_root": r"W:\work\g10", "remote_root": "/data1/g10"}
    assert vr.to_remote(e, r"W:\work\g10") == "/data1/g10"
    assert vr.to_remote(e, r"W:\work\g10\src\a.c") == "/data1/g10/src/a.c"
    # G1 回归：保存的 local_root 带尾反斜杠 → 旧实现 tail 从名字中截断
    # （raw 串不能以反斜杠收尾，这里用转义串）
    e2 = {"local_root": "W:\\work\\g10\\", "remote_root": "/data1/g10"}
    assert vr.to_remote(e2, r"W:\work\g10\kernel\x.c") == "/data1/g10/kernel/x.c"
    # G1 回归：大小写漂移（normcase 匹配命中、长度按 normpath 对齐）
    e3 = {"local_root": r"w:\WORK\g10", "remote_root": "/data1/g10"}
    assert vr.to_remote(e3, r"W:\work\g10\A.c") == "/data1/g10/A.c"
    # 根自身（带尾反斜杠形态）
    assert vr.to_remote(e2, "W:\\work\\g10\\") == "/data1/g10"


def test_map_argv_scope():
    e = {"local_root": r"W:\work\g10", "remote_root": "/data1/g10"}
    # 工程根下：翻译
    assert vr._map_argv(e, ["svn", "cat", "-r", "BASE",
                            r"W:\work\g10\src\a.c"], r"W:\work\g10") == \
        ["svn", "cat", "-r", "BASE", "/data1/g10/src/a.c"]
    # G4 回归：-m 的自由文本长得像绝对路径 → 绝不改写（旧实现会被永久写进版本库）
    msg = r"W:\work\g10 修了编译错"
    assert vr._map_argv(e, ["git", "commit", "-m", msg], r"W:\work\g10") == \
        ["git", "commit", "-m", msg]
    # 工程外绝对路径：原样（不翻译不斜杠化）
    assert vr._map_argv(e, ["git", "log", "--grep", r"C:\other"], "x") == \
        ["git", "log", "--grep", r"C:\other"]
    # 相对路径：原样
    assert vr._map_argv(e, ["svn", "add", "--", "sub/a.c"], "x") == \
        ["svn", "add", "--", "sub/a.c"]


def test_migrate_port_robustness():
    # L2 回归：旧格式 port 非数字不再炸穿 load() 路径
    d = {"profiles": [{"id": 1, "host": "h", "port": "abc",
                       "user": "u", "auth": "password"}],
         "remotes": []}
    prof = vr._match_or_add_profile(d, {"host": "h", "port": 22,
                                        "user": "u", "auth": "password",
                                        "secret_enc": "", "key_path": ""})
    assert prof["id"] == 1         # 命中同档案（异常 port 按 22 兜底）
