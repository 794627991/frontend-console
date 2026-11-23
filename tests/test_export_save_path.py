# -*- coding: utf-8 -*-
"""导出类接口的「用户自选保存路径」回归锚（2026-11-23 评审修复 C）。

背景：P4 删掉了 pywebview 的 main._save_file_dialog 却没补 Electron 等价物
——后端日志导出、代码索引范围配置导出都弹不出保存框，静默落桌面。现在
前端先经壳的 fc:save-as 弹保存框、把路径回传后端，于是后端多了一个
「按调用方给的路径写文件」的入口。本文件锁住：

  1. app_state.export_target_err 的规则：只拦「覆盖工具自身的文件」
     （config 的家 / 数据目录 / 锚点之内已存在的目标），新建文件放哪都行
  2. 两处导出路由：带 path → 按选定路径原样写（含覆盖已有文件）；
     path 落在受保护目录 → 400 且原文件一字不动
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import src.app_state as st
import src.backend_log as BL
import src.nav_api as NA
import src.server as S


@pytest.fixture
def homes(tmp_path, monkeypatch):
    tool = tmp_path / "tool" / "data"          # config 的家 = 数据目录
    anchor = tmp_path / "anchor"               # 锚点（endpoint / 取证日志）
    out = tmp_path / "exports"
    tool.mkdir(parents=True)
    anchor.mkdir()
    out.mkdir()
    (tool / "config.json").write_text('{"theme": "dark"}', encoding="utf-8")
    (tool / "cmdlib.json").write_text('[{"name": "a", "cmd": "ls"}]', encoding="utf-8")
    (anchor / "endpoint.json").write_text('{"port": 1}', encoding="utf-8")
    (out / "old.txt").write_text("old", encoding="utf-8")
    monkeypatch.setattr(st, "TOOL_DATA_DIR", str(tool))
    monkeypatch.setattr(st, "DATA_DIR", str(tool))
    monkeypatch.setattr(st, "HOME_DIR", str(anchor))
    return {"tool": tool, "anchor": anchor, "out": out}


@pytest.fixture
def migrated(tmp_path, monkeypatch):
    """数据目录迁移之后：config 的家（工具目录 data）与数据目录是**两个**
    不同的目录。上面的 homes 把两者钉成同一个，测不到「各自独立拦截」
    （2026-11-23 总审计 W-8）。"""
    tool = tmp_path / "tool" / "data"          # config 的家（不随迁）
    data = tmp_path / "migrated-data"          # 数据目录（config.data_dir）
    anchor = tmp_path / "anchor"
    for d in (tool, data, anchor):
        d.mkdir(parents=True)
    (tool / "config.json").write_text('{"theme": "dark"}', encoding="utf-8")
    (tool / "config.json.bak").write_text('{"theme": "light"}', encoding="utf-8")
    (tool / "data_backup").mkdir()
    (tool / "data_backup" / "config.json").write_text(
        '{"theme": "light"}', encoding="utf-8")
    (data / "cmdlib.json").write_text('[{"name": "a", "cmd": "ls"}]', encoding="utf-8")
    (data / "files").mkdir()
    (data / "files" / "note.md").write_text("note", encoding="utf-8")
    (anchor / "endpoint.json").write_text('{"port": 1}', encoding="utf-8")
    monkeypatch.setattr(st, "TOOL_DATA_DIR", str(tool))
    monkeypatch.setattr(st, "DATA_DIR", str(data))
    monkeypatch.setattr(st, "HOME_DIR", str(anchor))
    return {"tool": tool, "data": data, "anchor": anchor}


# ---------------- 校验规则 ----------------

def test_target_err_new_file_anywhere_is_fine(homes):
    assert st.export_target_err(str(homes["out"] / "new.txt")) is None
    assert st.export_target_err(str(homes["out"] / "sub" / "deeper.json")) is None


def test_target_err_existing_outside_protected_dirs_is_fine(homes):
    assert st.export_target_err(str(homes["out"] / "old.txt")) is None


@pytest.mark.parametrize("rel", ["config.json", "cmdlib.json",
                                 os.path.join("nested", "x.log")])
def test_target_err_rejects_overwrite_inside_data_dir(homes, rel):
    p = homes["tool"] / rel
    if rel.endswith(".log"):
        p.parent.mkdir()
        p.write_text("log", encoding="utf-8")
    assert st.export_target_err(str(p)) is not None


def test_target_err_rejects_overwrite_inside_anchor(homes):
    assert st.export_target_err(str(homes["anchor"] / "endpoint.json")) is not None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 路径语义")
def test_target_err_rejects_bad_shapes(homes):
    assert st.export_target_err("") is not None
    assert st.export_target_err("relative.txt") is not None
    assert st.export_target_err(r"\\server\share\x.txt") is not None
    assert st.export_target_err(str(homes["out"] / "CON.txt")) is not None


# ---------------- 迁移后：config 的家 与 数据目录 分离 ----------------

def test_migrated_fixture_really_has_two_dirs(migrated):
    assert str(migrated["tool"]) != str(migrated["data"])
    assert str(st.TOOL_DATA_DIR) == str(migrated["tool"])
    assert str(st.DATA_DIR) == str(migrated["data"])


@pytest.mark.parametrize("rel", ["config.json", "config.json.bak",
                                 os.path.join("data_backup", "config.json")])
def test_migrated_config_home_files_rejected(migrated, rel):
    # 这些文件只存在于 config 的家；数据目录里没有它们
    assert (migrated["tool"] / rel).is_file()
    assert not (migrated["data"] / rel).exists()
    assert st.export_target_err(str(migrated["tool"] / rel)) is not None


@pytest.mark.parametrize("rel", ["cmdlib.json", os.path.join("files", "note.md")])
def test_migrated_data_dir_files_rejected(migrated, rel):
    assert (migrated["data"] / rel).is_file()
    assert not (migrated["tool"] / rel).exists()
    assert st.export_target_err(str(migrated["data"] / rel)) is not None


def test_each_dir_is_guarded_on_its_own(migrated, tmp_path, monkeypatch):
    """把另一个目录指到不相干的地方，本目录的文件照样拦——不是靠某一
    个目录碰巧把另一个包含住。"""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    cfg = str(migrated["tool"] / "config.json")
    cmd = str(migrated["data"] / "cmdlib.json")
    monkeypatch.setattr(st, "DATA_DIR", str(elsewhere))
    assert st.export_target_err(cfg) is not None, "只靠 TOOL_DATA_DIR 拦不住"
    monkeypatch.setattr(st, "DATA_DIR", str(migrated["data"]))
    monkeypatch.setattr(st, "TOOL_DATA_DIR", str(elsewhere))
    assert st.export_target_err(cmd) is not None, "只靠 DATA_DIR 拦不住"


def test_migrated_log_export_refuses_config_backup(migrated):
    bak = migrated["tool"] / "config.json.bak"
    before = bak.read_bytes()
    rv = _log_client().post("/api/backend_log/save", json={"path": str(bak)})
    assert rv.status_code == 400
    assert bak.read_bytes() == before


def test_migrated_log_export_refuses_data_dir_file(migrated):
    cmd = migrated["data"] / "cmdlib.json"
    before = cmd.read_bytes()
    rv = _log_client().post("/api/backend_log/save", json={"path": str(cmd)})
    assert rv.status_code == 400
    assert cmd.read_bytes() == before


# ---------------- 日志导出路由 ----------------

def _log_client():
    BL.install()
    BL.clear()
    BL.log("x", "导出探针-ABC")
    return S.app.test_client()


def test_log_export_writes_chosen_path(homes):
    target = homes["out"] / "new.txt"
    j = _log_client().post("/api/backend_log/save",
                           json={"path": str(target)}).get_json()
    assert j["ok"] is True and j["path"] == str(target)
    assert "导出探针-ABC" in target.read_text(encoding="utf-8")


def test_log_export_overwrites_user_confirmed_existing_file(homes):
    target = homes["out"] / "old.txt"
    j = _log_client().post("/api/backend_log/save",
                           json={"path": str(target)}).get_json()
    assert j["ok"] is True
    assert target.read_text(encoding="utf-8") != "old"


def test_log_export_refuses_to_clobber_config(homes):
    cfg = homes["tool"] / "config.json"
    before = cfg.read_bytes()
    rv = _log_client().post("/api/backend_log/save", json={"path": str(cfg)})
    assert rv.status_code == 400
    assert cfg.read_bytes() == before            # 一字不动


def test_log_export_refuses_relative_path(homes):
    rv = _log_client().post("/api/backend_log/save", json={"path": "relative.txt"})
    assert rv.status_code == 400


# ---------------- 范围配置导出路由 ----------------

@pytest.fixture
def scope(homes, monkeypatch):
    # 登记根校验与范围配置读取各有自己的测试；这里只验「写到你选的路径」
    monkeypatch.setattr(NA, "_guard", lambda _p: True)
    import src.nav_index as NI
    monkeypatch.setattr(NI, "load_scope",
                        lambda _r: ({"version": 1, "name": "demo",
                                     "dirs": ["src"], "exclude_names": []}, "ok"))
    return homes["tool"]


def test_scope_export_writes_chosen_path(scope, homes):
    target = homes["out"] / "scope.json"
    j = S.app.test_client().post("/api/nav/scope_export",
                                 json={"root": str(scope), "path": str(target)}).get_json()
    assert j["ok"] is True and j["path"] == str(target), j
    assert json.loads(target.read_text(encoding="utf-8"))["dirs"] == ["src"]


def test_scope_export_refuses_to_clobber_config(scope, homes):
    cfg = homes["tool"] / "config.json"
    before = cfg.read_bytes()
    rv = S.app.test_client().post("/api/nav/scope_export",
                                  json={"root": str(scope), "path": str(cfg)})
    assert rv.status_code == 400
    assert cfg.read_bytes() == before


if __name__ == "__main__":
    import pytest as _pt
    sys.exit(_pt.main([__file__, "-q"]))
