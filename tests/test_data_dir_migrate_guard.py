# -*- coding: utf-8 -*-
"""数据目录迁移回归锚（2026-11-23 评审修复）。

迁移函数此前没有任何 pytest 用例（对面的验证都是一次性沙箱脚本），
而它是全仓唯一会**删除用户数据目录**的代码。本文件锁住三件事：

  1. 设置保存失败 → 迁移中止，不切换、不删旧目录、不碰 worker
     （旧实现 _save_config 返回值被丢：保存失败也照删旧目录并报成功，
     config.data_dir 仍是旧目录——下次启动回到被删空的旧目录。）
  2. 首次迁移（旧数据目录就是 工具目录\\data，最常见形态）：config 与
     data_backup 留在工具目录，数据搬去新目录；data_backup 里的 config
     镜像副本**不随迁**（拷过去就是一份从此不再更新的过期副本）。
  3. worker 重启发生在「config 已落盘」之后、「旧目录被删」之前——
     worker 的新进程读到的必须是新 data_dir，且退出时旧目录还在
     （没有句柄占着、不再往旧目录写）。

pytest 下 CLAUDE_INLINE=1（conftest），manage_restart 被替换成探针，
不碰任何真实进程。
"""
import importlib
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import src.app_state as st
import src.server as S


def _pin_mod(monkeypatch, dotted, *names):
    """把迁移函数会改写的模块属性预先登记给 monkeypatch，用例结束后复原。

    2026-11-23 总审计 W-9：原对导入失败/属性缺失静默跳过——模块名或属性名
    写错（模块改名后最容易）会让被迁移改写的全局无人复原、泄漏给后面的
    用例，而测试照过。夹具宁可当场失败。
    """
    try:
        m = importlib.import_module(dotted)
    except Exception as e:
        pytest.fail("迁移夹具导入 %s 失败（模块改名后请同步夹具；否则迁移"
                    "改写的全局无人复原）：%r" % (dotted, e))
    for n in names:
        if not hasattr(m, n):
            pytest.fail("迁移夹具：%s 里没有属性 %s（改名后请同步夹具，否则"
                        "迁移对它的改写无人复原）" % (dotted, n))
        monkeypatch.setattr(m, n, getattr(m, n))


@pytest.fixture
def mig(tmp_path, monkeypatch):
    """形态②现场：旧数据目录 == 工具目录\\data（config 的家）。"""
    tool = tmp_path / "tool" / "data"
    new = tmp_path / "newdata"
    (tool / "data_backup").mkdir(parents=True)
    (tool / "harness_uploads").mkdir()
    (tool / "harness_uploads" / "a.png").write_bytes(b"img")
    (tool / "files").mkdir()
    (tool / "files" / "n.md").write_text("note", encoding="utf-8")
    (tool / "cmdlib.json").write_text('[{"name": "a", "cmd": "ls"}]', encoding="utf-8")
    (tool / "claude_harness.json").write_text('{"x": 1}', encoding="utf-8")
    (tool / "config.json").write_text('{"theme": "dark", "close_to_tray": true}',
                                      encoding="utf-8")
    (tool / "data_backup" / "config.json").write_text('{"theme": "dark"}',
                                                      encoding="utf-8")
    (tool / "data_backup" / "cred.json").write_text('{"c": 1}', encoding="utf-8")

    # 迁移函数读写的入口全局
    for mod, name, val in (
            (S, "DATA_DIR", str(tool)), (S, "STATE_DIR", str(tool)),
            (S, "CMD_LIB_FILE", str(tool / "cmdlib.json")),
            (S, "LOG_DIR", str(tool / "logs")),
            (st, "DATA_DIR", str(tool)), (st, "STATE_DIR", str(tool)),
            (st, "LOG_DIR", str(tool / "logs")),
            (st, "CMD_LIB_FILE", str(tool / "cmdlib.json")),
            (st, "TOOL_DATA_DIR", str(tool)),
            (st, "CONFIG_FILE", str(tool / "config.json")),
            (st, "CONFIG_BACKUP_FILE", str(tool / "data_backup" / "config.json"))):
        monkeypatch.setattr(mod, name, val)
    # 迁移函数会补绑的模块（值不变，只为用例后复原）
    _pin_mod(monkeypatch, "src.editor_files", "FILES_DIR", "IMAGES_DIR")
    _pin_mod(monkeypatch, "src.skills_repo", "DATA_DIR", "_CACHE_DIR", "_ZH_DIR",
             "_EXPORT_DIR", "_META_FILE")
    _pin_mod(monkeypatch, "src.proxy", "DATA_DIR", "PROXY_STATE_PATH")
    _pin_mod(monkeypatch, "src.lanzi.state", "CRED_PATH", "MARKS_PATH")
    _pin_mod(monkeypatch, "src.lanzi.bot", "DATA_DIR", "SESSION_PATH")
    _pin_mod(monkeypatch, "src.proxy_usage", "DATA_DIR", "USAGE_PATH")
    _pin_mod(monkeypatch, "src.harness.meta", "_META_FILE")
    _pin_mod(monkeypatch, "src.harness.routes", "_UPLOAD_DIR", "_SKILL_ZH_FILE")
    _pin_mod(monkeypatch, "src.harness.consts", "_META_FILE", "_UPLOAD_DIR",
             "_SKILL_ZH_FILE")
    _pin_mod(monkeypatch, "src.eventlog.store", "_WSEQ_DIR")
    _pin_mod(monkeypatch, "src.cred_mirror", "BACKUP_DIR")

    # worker 重启探针：记录调用时刻的三件事，不碰真实进程
    calls = []

    def fake_restart():
        cfg_p = tool / "config.json"
        calls.append({
            "cfg_data_dir": (json.loads(cfg_p.read_text(encoding="utf-8"))
                             .get("data_dir") if cfg_p.exists() else None),
            "old_uploads_still_there": (tool / "harness_uploads" / "a.png").exists(),
            "runtime_switched": st.DATA_DIR != str(tool),
        })
        return "restarted"

    import src.worker_app as wa
    monkeypatch.setattr(wa, "manage_restart", fake_restart)
    return {"tool": tool, "new": new, "calls": calls}


def _migrate(new):
    """走真实路由（带应用上下文，连带目标预检与迁移互斥锁）。"""
    rv = S.app.test_client().post("/api/data_dir/migrate", json={"dir": str(new)})
    return rv.status_code, rv.get_json()


def test_save_failure_aborts_before_touching_anything(mig, monkeypatch):
    tool, new = mig["tool"], mig["new"]
    monkeypatch.setattr(st, "cfg_commit", lambda _m: (False, "模拟：config.json 暂时不可读"))
    code, body = _migrate(new)
    assert code == 500
    assert body["ok"] is False and "设置保存失败" in body["err"]
    # 未切换、旧目录原封不动、没碰 worker
    assert st.DATA_DIR == str(tool) and S.DATA_DIR == str(tool)
    assert (tool / "harness_uploads" / "a.png").exists()
    assert (tool / "files" / "n.md").exists()
    assert json.loads((tool / "config.json").read_text(encoding="utf-8")) \
        == {"theme": "dark", "close_to_tray": True}    # data_dir 没被写进去
    assert mig["calls"] == []


def test_first_migration_moves_data_keeps_config_home(mig):
    tool, new = mig["tool"], mig["new"]
    code, body = _migrate(new)
    assert code == 200 and body["ok"] is True, body
    # config 的家不动，且记下了新目录
    cfg = json.loads((tool / "config.json").read_text(encoding="utf-8"))
    assert cfg["data_dir"] == str(new)
    assert cfg["close_to_tray"] is True                 # 其余设置原样
    assert (tool / "data_backup").is_dir()
    assert (tool / "config.json.bak").exists()
    # 数据搬走了，旧目录里对应项已删
    assert (new / "harness_uploads" / "a.png").read_bytes() == b"img"
    assert (new / "files" / "n.md").exists()
    assert (new / "cmdlib.json").exists()
    assert not (tool / "harness_uploads").exists()
    assert not (tool / "files").exists()
    # data_backup 随迁，但 config 镜像副本不随迁（它只写工具目录那一份）
    assert (new / "data_backup" / "cred.json").exists()
    assert not (new / "data_backup" / "config.json").exists()
    assert st.DATA_DIR == str(new)
    assert body["worker_restart"] == "restarted"


def test_worker_restart_is_ordered_after_save_before_delete(mig):
    new = mig["new"]
    code, body = _migrate(new)
    assert code == 200 and body["ok"] is True, body
    assert len(mig["calls"]) == 1
    seen = mig["calls"][0]
    assert seen["cfg_data_dir"] == str(new)             # 新进程能读到新目录
    assert seen["old_uploads_still_there"] is True      # 退出时旧目录还在
    assert seen["runtime_switched"] is False            # 运行时尚未切换


def test_keystore_copy_failure_in_subdir_aborts_migration(mig, monkeypatch):
    """子目录里的证书/私钥拷失败不能当「尽力复制」跳过——旧目录随后会被删，
    那等于私钥静默丢失。（2026-11-23 总审计 F3：根级补了严格校验，子目录没补）"""
    tool, new = mig["tool"], mig["new"]
    (tool / "certs").mkdir()
    (tool / "certs" / "web_h2_key.pem").write_text("KEY", encoding="utf-8")
    (tool / "certs" / "notes.txt").write_text("x", encoding="utf-8")     # 对照：普通文件
    real_copy = S._mig_copy_atomic

    def flaky_copy(sf, df):
        if str(sf).endswith(".pem"):
            raise PermissionError("模拟：杀软占用")
        return real_copy(sf, df)

    monkeypatch.setattr(S, "_mig_copy_atomic", flaky_copy)
    code, body = _migrate(new)
    assert code == 500 and body["ok"] is False
    assert (tool / "certs" / "web_h2_key.pem").read_text(encoding="utf-8") == "KEY"
    assert st.DATA_DIR == str(tool)                    # 未切换


def test_ordinary_file_copy_failure_in_subdir_is_tolerated(mig, monkeypatch):
    """对照：子目录里的普通文件拷失败仍是尽力复制，不中止。"""
    tool, new = mig["tool"], mig["new"]
    (tool / "misc").mkdir()
    (tool / "misc" / "cache.bin").write_text("c", encoding="utf-8")
    real_copy = S._mig_copy_atomic

    def flaky_copy(sf, df):
        if str(sf).endswith(".bin"):
            raise PermissionError("模拟：占用")
        return real_copy(sf, df)

    monkeypatch.setattr(S, "_mig_copy_atomic", flaky_copy)
    code, body = _migrate(new)
    assert code == 200 and body["ok"] is True, body
    assert any(c.get("name") == "misc" and c.get("skipped") for c in body["copied"])


def test_pin_mod_fails_loudly_instead_of_skipping(monkeypatch):
    """W-9 守卫自检：模块名/属性名写错必须当场失败，不能静默跳过。
    （pytest.fail 抛的 Failed 不是 BaseException 的 Exception 子类公开名，
    这里按基类接。）"""
    with pytest.raises(BaseException, match="导入 src.no_such_module_xyz 失败"):
        _pin_mod(monkeypatch, "src.no_such_module_xyz", "DATA_DIR")
    with pytest.raises(BaseException, match="里没有属性 NO_SUCH_ATTR"):
        _pin_mod(monkeypatch, "src.proxy", "NO_SUCH_ATTR")


if __name__ == "__main__":
    import pytest as _pt
    sys.exit(_pt.main([__file__, "-q"]))
