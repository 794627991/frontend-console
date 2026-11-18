# -*- coding: utf-8 -*-
"""命令库防洗库护栏（a645 真实事故）。

事故：用户的命令库（10 条手写命令：nfs 挂载/uboot ip/内核 mac…）被覆盖成
一条 `{"name":"a","cmd":"echo 1"}`，全盘找不到任何副本——`/api/cmd_lib`
是全量覆盖语义，`_save_cmd_lib` 又从来不 backup。

本测钉住两道防线：
1. 写前滚动留底：cmdlib.json.bak + cmdlib.json.snap/ 最近 N 份
2. 接口护栏：清空需 allow_empty、大幅删减需 allow_shrink
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, '.')

import pytest


@pytest.fixture
def cmdlib_env(monkeypatch):
    """把 CMD_LIB_FILE 指到临时目录，避免碰真实命令库。"""
    import src.app_state as st
    root = tempfile.mkdtemp(prefix="fc_cmdlib_")
    monkeypatch.setattr(st, "CMD_LIB_FILE", os.path.join(root, "cmdlib.json"))
    monkeypatch.setattr(st, "CMD_LIB_BAK",
                        os.path.join(root, "cmdlib.json.bak"))
    monkeypatch.setattr(st, "CMD_LIB_SNAP_DIR",
                        os.path.join(root, "cmdlib.json.snap"))
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


TEN = [{"name": "cmd%d" % i, "cmd": "echo %d" % i} for i in range(10)]


def test_save_creates_bak(cmdlib_env):
    """写前把上一版留到 .bak。"""
    import src.app_state as st
    assert st._save_cmd_lib(TEN)
    assert st._save_cmd_lib([{"name": "x", "cmd": "new"}])
    with open(st.CMD_LIB_BAK, encoding="utf-8") as f:
        bak = json.load(f)
    assert len(bak) == 10            # 上一版（10 条）完整留底
    with open(st.CMD_LIB_FILE, encoding="utf-8") as f:
        assert len(json.load(f)) == 1


def test_snapshot_rotation_keeps_last_n(cmdlib_env):
    """连续多次保存 → 快照最多留 CMD_LIB_SNAP_KEEP 份。"""
    import src.app_state as st
    for i in range(8):
        st._save_cmd_lib(TEN + [{"name": "n%d" % i, "cmd": "c%d" % i}])
        # 快照按秒命名，同秒内只生成一份。把已有快照改名成不同秒，
        # 模拟跨秒保存（避免用 sleep 拖慢测试）。
        if not os.path.isdir(st.CMD_LIB_SNAP_DIR):
            continue        # 首次保存（此前无旧文件）不产生快照
        for old in os.listdir(st.CMD_LIB_SNAP_DIR):
            srcp = os.path.join(st.CMD_LIB_SNAP_DIR, old)
            dstp = os.path.join(st.CMD_LIB_SNAP_DIR,
                                "cmdlib-2026010%d-000000.json" % (i + 1))
            if srcp != dstp and not os.path.exists(dstp):
                os.rename(srcp, dstp)
                break
    snaps = os.listdir(st.CMD_LIB_SNAP_DIR)
    assert len(snaps) <= st.CMD_LIB_SNAP_KEEP
    assert len(snaps) >= 1


def test_backup_failure_does_not_block_save(cmdlib_env, monkeypatch):
    """留底失败绝不能挡住正常保存（备份是尽力而为）。"""
    import src.app_state as st

    def boom(*_a, **_k):
        raise OSError("模拟备份失败")

    monkeypatch.setattr(shutil, "copy2", boom)
    assert st._save_cmd_lib(TEN) is True
    with open(st.CMD_LIB_FILE, encoding="utf-8") as f:
        assert len(json.load(f)) == 10


# ---------- 接口护栏 ----------

@pytest.fixture
def client(monkeypatch):
    """Flask 测试客户端；CMD_LIB_FILE 指向临时目录。"""
    import src.app_state as st
    root = tempfile.mkdtemp(prefix="fc_cmdapi_")
    monkeypatch.setattr(st, "CMD_LIB_FILE", os.path.join(root, "cmdlib.json"))
    monkeypatch.setattr(st, "CMD_LIB_BAK",
                        os.path.join(root, "cmdlib.json.bak"))
    monkeypatch.setattr(st, "CMD_LIB_SNAP_DIR",
                        os.path.join(root, "cmdlib.json.snap"))
    from src.server import app
    try:
        yield app.test_client(), st
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_api_rejects_wiping_nonempty_lib(client):
    """原库非空、提交空数组 → 409（这是本次事故的形态）。"""
    c, st = client
    st._save_cmd_lib(TEN)
    r = c.post("/api/cmd_lib", json={"lib": []})
    assert r.status_code == 409
    assert "拒绝清空" in r.get_json()["err"]
    with open(st.CMD_LIB_FILE, encoding="utf-8") as f:
        assert len(json.load(f)) == 10          # 磁盘未被改动


def test_api_allows_empty_with_explicit_flag(client):
    """带 allow_empty 才允许清空。"""
    c, st = client
    st._save_cmd_lib(TEN)
    r = c.post("/api/cmd_lib", json={"lib": [], "allow_empty": True})
    assert r.status_code == 200
    with open(st.CMD_LIB_FILE, encoding="utf-8") as f:
        assert json.load(f) == []


def test_api_rejects_mass_shrink(client):
    """10 条变 1 条 → 409（正是事故的真实形态：只剩 echo 1）。"""
    c, st = client
    st._save_cmd_lib(TEN)
    r = c.post("/api/cmd_lib", json={"lib": [{"name": "a", "cmd": "echo 1"}]})
    assert r.status_code == 409
    assert "大幅删减" in r.get_json()["err"]
    with open(st.CMD_LIB_FILE, encoding="utf-8") as f:
        assert len(json.load(f)) == 10


def test_api_allows_shrink_with_flag(client):
    c, st = client
    st._save_cmd_lib(TEN)
    r = c.post("/api/cmd_lib", json={
        "lib": [{"name": "a", "cmd": "echo 1"}], "allow_shrink": True})
    assert r.status_code == 200
    with open(st.CMD_LIB_FILE, encoding="utf-8") as f:
        assert len(json.load(f)) == 1


def test_api_small_edit_unaffected(client):
    """正常增删（10 → 6，超过一半）不受护栏影响。"""
    c, st = client
    st._save_cmd_lib(TEN)
    r = c.post("/api/cmd_lib", json={"lib": TEN[:6]})
    assert r.status_code == 200
    with open(st.CMD_LIB_FILE, encoding="utf-8") as f:
        assert len(json.load(f)) == 6


def test_api_small_library_not_gated(client):
    """原来只有 2 条时，删到 1 条不该触发骤降保护（避免过度拦截）。"""
    c, st = client
    st._save_cmd_lib(TEN[:2])
    r = c.post("/api/cmd_lib", json={"lib": TEN[:1]})
    assert r.status_code == 200
