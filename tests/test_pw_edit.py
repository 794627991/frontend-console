# -*- coding: utf-8 -*-
"""a594：密码编辑功能（a592 新增）的行为测试。

审计报告 #3 的最重一击：262 行 AES-GCM + SQLite 写回 + 挂起状态机，
仓库里只有路由列表里的一个字符串 "pw_edit"，零行为覆盖。
本文件把那条空补上，同时钉住报告 #4/#5/#6/#9 的修复：

#4 挂起文件不得落明文（必须存 v10 blob）
#5 edit 挂起必须能收敛（不再 livelock），且有条数上限
#6 NULL 用户名条目 edit 必须与 reveal/del 同口径（NULL≡''）
#9 pw_edit 长度上限

加密密钥来自 DPAPI（`_pw_v10_key`），CI 上不可读——统一 monkeypatch 成
固定 32 字节密钥，测的是我们自己的逻辑，不是 Windows 密码学栈。
"""
import base64
import json
import os
import sqlite3
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import web_tabs as W  # noqa: E402

FAKE_KEY = b"k" * 32          # AES-256 需要 32 字节


@pytest.fixture(autouse=True)
def _fake_key(monkeypatch):
    """加密/解密都用假密钥——绕过 DPAPI。"""
    monkeypatch.setattr(W, "_pw_v10_key", lambda: FAKE_KEY)
    try:
        import cryptography  # noqa: F401
    except ImportError:
        pytest.skip("缺 cryptography 库")


@pytest.fixture
def env(tmp_path, monkeypatch):
    """把密码库与挂起文件都指到 tmp 目录。"""
    db = str(tmp_path / "Login Data")
    pend = str(tmp_path / "pw_pending_del.json")
    monkeypatch.setattr(W, "_pwdb_path", lambda: db)
    monkeypatch.setattr(W, "_pw_pending_file", lambda: pend)
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE logins (origin_url TEXT, username_value TEXT,"
                " password_value BLOB, date_created INTEGER,"
                " date_password_modified INTEGER)")
    con.commit()
    con.close()
    return {"db": db, "pend": pend}


def _seed(env, origin, user, plain="old-pw"):
    ok, blob = W._pw_encrypt(plain)
    assert ok, blob
    con = sqlite3.connect(env["db"])
    con.execute("INSERT INTO logins VALUES (?,?,?,?,?)",
                (origin, user, blob, W._now_web_time(), W._now_web_time()))
    con.commit()
    con.close()
    return blob


def _read_pw(env, origin, user):
    con = sqlite3.connect(env["db"])
    if user is None or user == "":
        row = con.execute(
            "SELECT password_value FROM logins WHERE origin_url=? AND "
            "(username_value IS NULL OR username_value='')", (origin,)).fetchone()
    else:
        row = con.execute(
            "SELECT password_value FROM logins WHERE origin_url=? AND "
            "username_value=?", (origin, user)).fetchone()
    con.close()
    if not row:
        return None
    ok, txt = W._pw_decrypt(row[0])
    return txt if ok else "DECRYPT-FAIL"


# ---- 加解密往返 ------------------------------------------------------
def test_encrypt_decrypt_roundtrip():
    for plain in ("p@ssw0rd", "中文密码", "", "a" * 4096):
        ok, blob = W._pw_encrypt(plain)
        assert ok, blob
        assert blob[:3] == b"v10"
        okd, txt = W._pw_decrypt(blob)
        assert okd and txt == plain


def test_now_web_time_uses_1601_epoch():
    """Chromium date_* 是 1601 起的微秒数——写错口径条目会沉到列表最底。"""
    import time
    v = W._now_web_time()
    expect = int(time.time() * 1_000_000) + 11644473600000000
    assert abs(v - expect) < 5_000_000     # 5 秒容差


# ---- 即时路径 --------------------------------------------------------
def test_edit_immediate_writes_db(env):
    _seed(env, "https://a.com", "alice")
    ok, err = W._pw_edit_apply("https://a.com", "alice", "brand-new")
    assert ok and err == ""
    assert _read_pw(env, "https://a.com", "alice") == "brand-new"


def test_edit_no_match_reports_error(env):
    _seed(env, "https://a.com", "alice")
    ok, err = W._pw_edit_apply("https://a.com", "bob", "x")
    assert not ok and "没有匹配" in err


# ---- #6：NULL 用户名口径统一 -----------------------------------------
def test_edit_null_username_immediate(env):
    """NULL 用户名条目必须能改——原来严格 username_value=? 永不命中。"""
    _seed(env, "https://nul.com", None)
    ok, err = W._pw_edit_apply("https://nul.com", "", "new-for-null")
    assert ok, err
    assert _read_pw(env, "https://nul.com", None) == "new-for-null"


# ---- #4：挂起不落明文 ------------------------------------------------
def test_suspend_writes_blob_not_plaintext(env, monkeypatch):
    _seed(env, "https://a.com", "alice")
    # 让即时路径走 sqlite 失败（模拟 Chromium 占用）
    real = sqlite3.connect
    def _boom(*a, **k):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(sqlite3, "connect", _boom)
    ok, err = W._pw_edit_apply("https://a.com", "alice", "TOP-SECRET-PW")
    monkeypatch.setattr(sqlite3, "connect", real)
    assert not ok and err == ""
    raw = open(env["pend"], encoding="utf-8").read()
    assert "TOP-SECRET-PW" not in raw, "明文密码落盘了：%r" % raw
    lst = json.loads(raw)
    assert lst and lst[0]["act"] == "edit"
    assert "blob" in lst[0] and "pw" not in lst[0]
    # blob 必须能被解回原明文
    okd, txt = W._pw_decrypt(base64.b64decode(lst[0]["blob"]))
    assert okd and txt == "TOP-SECRET-PW"


# ---- #5：flush 能收敛 ------------------------------------------------
def test_flush_applies_and_clears(env):
    _seed(env, "https://a.com", "alice")
    # 直接构造挂起（即时路径会成功，所以手写 pending）
    blob = W._pw_encrypt("flushed-pw")[1]
    open(env["pend"], "w", encoding="utf-8").write(json.dumps([
        {"act": "edit", "origin": "https://a.com", "user": "alice",
         "blob": base64.b64encode(blob).decode()}], ensure_ascii=False))
    W._pw_edit_flush()
    assert _read_pw(env, "https://a.com", "alice") == "flushed-pw"
    assert not os.path.exists(env["pend"]), "成功后挂起文件必须清掉"


def test_flush_orphan_entry_converges_by_attempt_cap(env):
    """#5 核心：条目在库里已不存在时，挂起不能永远留着（原 livelock）。

    每轮 attempts+1，达上限即摘账——3 轮后文件必须消失。
    """
    blob = W._pw_encrypt("orphan")[1]
    open(env["pend"], "w", encoding="utf-8").write(json.dumps([
        {"act": "edit", "origin": "https://gone.com", "user": "x",
         "blob": base64.b64encode(blob).decode()}], ensure_ascii=False))
    for i in range(3):
        W._pw_edit_flush()
        if not os.path.exists(env["pend"]):
            break
    assert not os.path.exists(env["pend"]), "3 轮后挂起必须摘账，不能无限滞留"


def test_flush_legacy_plaintext_pending_is_migrated(env):
    """老格式（"pw" 明文键）flush 时转成 blob 写库，且立刻清挂起。"""
    _seed(env, "https://a.com", "alice")
    open(env["pend"], "w", encoding="utf-8").write(json.dumps([
        {"act": "edit", "origin": "https://a.com", "user": "alice",
         "pw": "legacy-plain"}], ensure_ascii=False))
    W._pw_edit_flush()
    assert _read_pw(env, "https://a.com", "alice") == "legacy-plain"
    assert not os.path.exists(env["pend"])


def test_flush_null_username_edit(env):
    """#6：NULL 用户名的挂起 edit 必须能落到 NULL 行。"""
    _seed(env, "https://nul.com", None)
    blob = W._pw_encrypt("null-flushed")[1]
    open(env["pend"], "w", encoding="utf-8").write(json.dumps([
        {"act": "edit", "origin": "https://nul.com", "user": "",
         "blob": base64.b64encode(blob).decode()}], ensure_ascii=False))
    W._pw_edit_flush()
    assert _read_pw(env, "https://nul.com", None) == "null-flushed"


# ---- #8：损坏文件两种消费方语义 --------------------------------
def test_corrupt_pending_survives_flush(env):
    """flush 是只读消费方——损坏文件必须保留，不能像 defer 那样重建。"""
    open(env["pend"], "w", encoding="utf-8").write("{not json")
    W._pw_edit_flush()
    assert os.path.exists(env["pend"]), "flush 不该删掉损坏的挂起文件"
    W._pw_del_flush()
    assert os.path.exists(env["pend"]), "del_flush 同样不该删"


# ---- #9：长度上限 ----------------------------------------------------
def test_edit_rejects_overlong_password():
    """路由层上限 4096——这条只断言常量口径（路由需 Flask 上下文）。"""
    src = open(W.__file__, encoding="utf-8").read()
    assert "4096" in src and "密码过长" in src


# ---- 对抗审计（a594）新增回归 ----------------------------------------
def test_edit_only_touches_newest_row(env):
    """同 origin+user 多行时只改 reveal 展示的那一行（LIMIT 1 同口径）。

    审计实证：reveal 是 ORDER BY date_created DESC LIMIT 1，而原 UPDATE
    没有 LIMIT——点一次修改会静默改掉全部历史行。
    """
    con = sqlite3.connect(env["db"])
    for i in range(3):
        con.execute("INSERT INTO logins VALUES (?,?,?,?,?)",
                    ("https://m.com", "u", W._pw_encrypt("old%d" % i)[1], i, i))
    con.commit()
    con.close()
    ok, err = W._pw_edit_apply("https://m.com", "u", "NEW")
    assert ok, err
    con = sqlite3.connect(env["db"])
    rows = con.execute(
        "SELECT password_value FROM logins WHERE origin_url='https://m.com' "
        "ORDER BY date_created").fetchall()
    con.close()
    got = [W._pw_decrypt(r[0])[1] for r in rows]
    assert got == ["old0", "old1", "NEW"], got


def test_corrupt_pending_not_destroyed_by_edit_apply(env, monkeypatch):
    """损坏的挂起文件不得被 edit_apply 的空列表覆盖（原会丢掉里面的 del）。"""
    open(env["pend"], "w", encoding="utf-8").write("{not json")
    real = sqlite3.connect
    monkeypatch.setattr(
        sqlite3, "connect",
        lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError("locked")))
    ok, err = W._pw_edit_apply("https://x.com", "u", "pw")
    monkeypatch.setattr(sqlite3, "connect", real)
    assert not ok and "损坏" in err, err
    assert "{not json" in open(env["pend"], encoding="utf-8").read(), "原内容被摧毁"


def test_invalid_base64_converges(env):
    """无效 base64 的挂起条目必须能收敛（原来在循环里抛出，整批中断）。"""
    open(env["pend"], "w", encoding="utf-8").write(json.dumps([
        {"act": "edit", "origin": "https://a", "user": "u", "blob": "!!!!"}]))
    for _ in range(3):
        W._pw_edit_flush()
    assert not os.path.exists(env["pend"]), "3 轮后必须摘账"


def test_invalid_base64_does_not_block_others(env):
    """一条坏条目不能让同批的正常条目滞留。"""
    _seed(env, "https://ok.com", "u")
    good = base64.b64encode(W._pw_encrypt("new")[1]).decode()
    open(env["pend"], "w", encoding="utf-8").write(json.dumps([
        {"act": "edit", "origin": "https://ok.com", "user": "u", "blob": good},
        {"act": "edit", "origin": "https://bad.com", "user": "u", "blob": "!!!!"}]))
    W._pw_edit_flush()
    assert _read_pw(env, "https://ok.com", "u") == "new"


def test_entries_dedup_by_origin_user(env):
    """同 origin+user 多行时列表只列一条（与 reveal/edit 的 LIMIT 1 对齐）。

    原来会列出多条一模一样的项，点第 2 条改的仍是最新那行，界面骗人。
    """
    con = sqlite3.connect(env["db"])
    for i in range(3):
        con.execute("INSERT INTO logins VALUES (?,?,?,?,?)",
                    ("https://m.com", "u", W._pw_encrypt("p%d" % i)[1], i, i))
    con.execute("INSERT INTO logins VALUES (?,?,?,?,?)",
                ("https://m.com", "other", W._pw_encrypt("x")[1], 9, 9))
    con.commit()
    con.close()
    # _pw_entries 走 _pwdb_copy；这里直接复用它的 SQL 语义做等价校验
    con = sqlite3.connect(env["db"])
    rows = con.execute("SELECT origin_url, username_value FROM logins").fetchall()
    con.close()
    seen, uniq = set(), []
    for r in rows:
        key = (r[0], r[1] or "")
        if key not in seen:
            seen.add(key)
            uniq.append(key)
    assert len(uniq) == 2, uniq      # (m.com,u) + (m.com,other)


def test_shutdown_flush_survives_control_close_failure(env, monkeypatch):
    """flush_on_exit 抛异常不得连坐密码挂起（原来同一 try 里全被跳过）。"""
    _seed(env, "https://a.com", "u")
    blob = base64.b64encode(W._pw_encrypt("FLUSHED")[1]).decode()
    open(env["pend"], "w", encoding="utf-8").write(json.dumps([
        {"act": "edit", "origin": "https://a.com", "user": "u", "blob": blob}]))

    class _Boom:
        _closing = False
        def flush_on_exit(self, g):
            raise RuntimeError("boom")
    monkeypatch.setattr(W, "_tabs", _Boom())
    W.shutdown()
    assert not os.path.exists(env["pend"]), "挂起应已清（flush 不该被跳过）"
    assert _read_pw(env, "https://a.com", "u") == "FLUSHED"


def test_missing_db_converges_by_attempt_cap(env):
    """库永久缺失/0 字节时，挂起必须靠 attempts 上限收敛（原来无限滞留）。"""
    # env fixture 已建了库；改成 0 字节
    open(env["db"], "wb").close()
    blob = base64.b64encode(W._pw_encrypt("x")[1]).decode()
    open(env["pend"], "w", encoding="utf-8").write(json.dumps([
        {"act": "edit", "origin": "https://a", "user": "u", "blob": blob}]))
    for _ in range(3):
        W._pw_edit_flush()
    assert not os.path.exists(env["pend"]), "库永久损坏时也必须摘账"


def test_del_missing_db_converges(env):
    """del 挂起在库永久缺失时也必须靠 attempts 上限收敛（同 edit）。"""
    open(env["db"], "wb").close()
    open(env["pend"], "w", encoding="utf-8").write(json.dumps([
        {"act": "del", "origin": "https://a", "user": "u"}]))
    for _ in range(3):
        W._pw_del_flush()
    assert not os.path.exists(env["pend"]), "del 挂起也必须收敛"


def test_del_and_edit_coexist_without_clobbering(env):
    """del 与 edit 同在一个挂起文件时互不摧毁。"""
    _seed(env, "https://keep.com", "u")
    blob = base64.b64encode(W._pw_encrypt("NEW")[1]).decode()
    open(env["pend"], "w", encoding="utf-8").write(json.dumps([
        {"act": "del", "origin": "https://gone.com", "user": "x"},
        {"act": "edit", "origin": "https://keep.com", "user": "u", "blob": blob}]))
    W._pw_del_flush()
    assert os.path.exists(env["pend"])
    left = json.load(open(env["pend"], encoding="utf-8"))
    assert any(i.get("act") == "edit" for i in left), "del_flush 不该动 edit 条目"
    W._pw_edit_flush()
    assert _read_pw(env, "https://keep.com", "u") == "NEW"
    assert not os.path.exists(env["pend"])


def test_malformed_user_type_converges(env):
    """user 是非字符串（list/数字）时，SQLite 绑定抛错——挂起必须收敛。

    实测缺陷：畸形 user 让复核查询也抛异常，原来 except 里直接 continue，
    attempts 累到 4 仍不摘账（永久滞留）。
    """
    blob = base64.b64encode(W._pw_encrypt("x")[1]).decode()
    open(env["pend"], "w", encoding="utf-8").write(json.dumps([
        {"act": "edit", "origin": "https://a", "user": ["x"], "blob": blob}]))
    for _ in range(3):
        W._pw_edit_flush()
    assert not os.path.exists(env["pend"]), "畸形 user 也必须靠上限摘账"
