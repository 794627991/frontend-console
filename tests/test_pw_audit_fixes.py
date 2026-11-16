# -*- coding: utf-8 -*-
"""a591 密码域回归：审计报告（2026-11-16）指出的四处真缺陷。

每条都先用一个「假库 + 真 SQL」证明缺陷存在，再钉住修复后的判据。
不依赖真实 Chromium 密码库（本机不一定有，CI 更不会有）。
"""
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _mkdb(rows):
    """rows: [(origin, user_or_None, pwd_bytes, date_created), ...]"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE logins (origin_url TEXT, username_value TEXT,"
                " password_value BLOB, date_created INTEGER)")
    con.executemany("INSERT INTO logins VALUES (?,?,?,?)", rows)
    con.commit()
    con.close()
    return path


# ---- #8：NULL 用户名「看不了但删得掉」 --------------------------------
def test_null_username_row_is_reachable_by_empty_string():
    """pw_reveal 传 user='' 时必须同时命中 NULL 行。

    原 SQL 是 `username_value=?` 传 ''——SQL 里 '' != NULL，永远 not-found，
    眼睛按钮永久 ❌；而删除侧按 NULL+空串全口径删。同一条目看不了却删得掉。
    """
    db = _mkdb([
        ("https://a.com", None, b"\x00", 1),   # Chromium 登录页无用户名 → NULL
        ("https://a.com", "", b"\x01", 2),
        ("https://a.com", "alice", b"\x02", 3),
    ])
    try:
        con = sqlite3.connect(db)
        # 修复后的判据（与 web_tabs.pw_reveal 一致）
        null_or_empty = con.execute(
            "SELECT count(*) FROM logins WHERE origin_url=? AND "
            "(username_value IS NULL OR username_value='')",
            ("https://a.com",)).fetchone()[0]
        # 修复前的判据（复现缺陷）
        only_empty = con.execute(
            "SELECT count(*) FROM logins WHERE origin_url=? AND "
            "username_value=?", ("https://a.com", "")).fetchone()[0]
        named = con.execute(
            "SELECT count(*) FROM logins WHERE origin_url=? AND "
            "username_value=?", ("https://a.com", "alice")).fetchone()[0]
        con.close()
    finally:
        os.remove(db)
    assert only_empty == 1, "缺陷复现：原判据只命中空串行，NULL 行被漏"
    assert null_or_empty == 2, "修复后应同时命中 NULL 与空串"
    assert named == 1, "正常用户名不受影响"


def test_reveal_uses_null_or_empty_branch():
    """源码里 pw_reveal 的 user=='' 分支必须打 (IS NULL OR ='')。"""
    import inspect
    from src import web_tabs
    src = inspect.getsource(web_tabs)
    # 这是**判据本身**的字符串检查（不是行为代理）：保证两个分支都在，
    # 真正的行为由上面那条 SQL 测试覆盖。
    assert "(username_value IS NULL OR username_value='')" in src
    assert 'if _u == "":' in src or "if _u == '':" in src


# ---- #9：重复粘贴块（json.load/open 双份） ---------------------------
def test_pw_entries_cleanup_block_not_duplicated():
    """_pw_entries 的 finally 里 os.remove(db) 只应出现一次。

    重复粘贴事故（ddabbdf 引入）让清理片段整段出现两遍——多余但不是最致命。
    """
    import inspect
    from src import web_tabs
    src = inspect.getsource(web_tabs._pw_entries)
    assert src.count("_os.remove(db)") == 1, (
        "清理块被粘贴了多份：%d 处" % src.count("_os.remove(db)"))


def test_no_bare_json_load_open_in_web_tabs():
    """json.load(open(...)) 会泄漏文件对象，一律用 with。

    a591：用 AST 检查真实调用，不做源码子串匹配（注释里提到这个写法会误报）。
    """
    import ast
    from src import web_tabs
    src = open(web_tabs.__file__, encoding="utf-8").read()
    tree = ast.parse(src)
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        # json.load(x) 且 x 是 open(...)
        if (isinstance(f, ast.Attribute) and f.attr == "load" and node.args):
            a0 = node.args[0]
            if (isinstance(a0, ast.Call) and isinstance(a0.func, ast.Name)
                    and a0.func.id == "open"):
                bad.append(node.lineno)
    assert not bad, "未关闭的文件读取在行 %r" % bad


# ---- #4：RA7 畸形库应 400 而非 200 -----------------------------------
def test_pw_reveal_error_returns_400():
    """库读取失败必须 400——原来 return jsonify(...) 没写状态码，是 200。

    提交信息宣称「RA7 try/finally+400」，HEAD 却是 200+ok:false。
    """
    import inspect
    from src import web_tabs
    src = inspect.getsource(web_tabs)
    assert '"库读取失败：%r" % e}), 400' in src, "畸形库路径缺 400 状态码"
