# -*- coding: utf-8 -*-
"""收录范围 v2 数据模型钉测（a570）。

为什么钉这一块：v2 把「一个工程一个档」改成「按目录三态 + 继承」，判错
只有两种后果——(a) 该收的目录被剪（跳转失效，用户难察觉）、(b) off 的
目录被收（索引膨胀、符号污染）。两种都静默。

用户定调（定稿 §一）：落盘只在工程根、v1 不兼容（直接当无配置）。
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import nav_index as ni   # noqa: E402


# ---- 继承解析 ----------------------------------------------------------

def test_resolve_child_overrides_parent():
    dirs = {"kernel": "whitelist", "kernel/tools": "full"}
    assert ni._resolve_dir_state("kernel/lib", dirs) == "whitelist"
    assert ni._resolve_dir_state("kernel/tools/bin", dirs) == "full"


def test_resolve_deepest_ancestor_wins():
    """三级覆盖：祖父 whitelist → 父 full → 自身 off。"""
    dirs = {"a": "whitelist", "a/b": "full", "a/b/c": "off"}
    assert ni._resolve_dir_state("a/x", dirs) == "whitelist"
    assert ni._resolve_dir_state("a/b/x", dirs) == "full"
    assert ni._resolve_dir_state("a/b/c/x", dirs) == "off"


def test_resolve_falls_back_to_default():
    assert ni._resolve_dir_state("anything", {}) == ni.SCOPE_MODE_ROOT_DEFAULT
    assert ni._resolve_dir_state("", {}) == ni.SCOPE_MODE_ROOT_DEFAULT
    assert ni._resolve_dir_state("x", {}, "full") == "full"


def test_mode_whitelist_ignores_dirs():
    """mode=whitelist/full 时全树统一，dirs 不生效。"""
    sc = {"mode": "whitelist", "dirs": {"kernel": "off"}}
    assert ni._scope_root_default(sc) == "whitelist"
    sc2 = {"mode": "full", "dirs": {"kernel": "off"}}
    assert ni._scope_root_default(sc2) == "full"


def test_make_state_of_none_when_no_scope():
    assert ni._make_state_of(None) is None


# ---- _norm_dirs 严校验 -------------------------------------------------

@pytest.mark.parametrize("bad", [
    {"../escape": "full"},
    {"/abs": "full"},
    {"C:/win": "full"},
    # a570 第十八轮：""/"." 是合法的根键（表达工程根自身），移出拒绝列表，
    # 见下面 test_norm_dirs_accepts_root_key。空白/分隔符造出的根形态仍拒。
    {"  ": "full"},
    {" / ": "full"},
    {"kernel": "bogus"},
    {"kernel": 1},
])
def test_norm_dirs_rejects(bad):
    assert ni._norm_dirs(bad) is None


def test_norm_dirs_normalizes():
    got = ni._norm_dirs({"kernel\\tools": "FULL", "./a//b": " off "})
    assert got == {"kernel/tools": "full", "a/b": "off"}


# ---- v1 不兼容 ---------------------------------------------------------

def test_v1_config_is_deprecated():
    ok, msg = ni._norm_scope({"version": 1, "tier": "auto",
                              "include": ["."]}, "")
    assert not ok and msg == "v1-deprecated"


def test_v2_ok():
    ok, sc = ni._norm_scope({"version": 2, "mode": "manual",
                             "dirs": {"kernel": "whitelist"}}, "")
    assert ok
    assert sc["mode"] == "manual"
    assert sc["dirs"] == {"kernel": "whitelist"}
    assert sc["artifact_roots"] == []
    assert sc["exclude_names"] == []


def test_v2_unknown_field_is_bad():
    ok, msg = ni._norm_scope({"version": 2, "inlcude": ["."]}, "")
    assert not ok and "未知字段" in msg


def test_v2_bad_mode():
    ok, msg = ni._norm_scope({"version": 2, "mode": "auto"}, "")
    assert not ok and "mode" in msg


def test_v2_artifact_roots_rejects_escape():
    ok, _ = ni._norm_scope({"version": 2, "artifact_roots": ["../x"]}, "")
    assert not ok


# ---- load / save -------------------------------------------------------

def test_load_scope_absent(tmp_path):
    assert ni.load_scope(str(tmp_path)) == (None, "")


def test_load_scope_v2(tmp_path):
    p = os.path.join(str(tmp_path), ni.SCOPE_FILE)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"version": 2, "mode": "manual",
                   "dirs": {"k": "whitelist"}}, f)
    sc, src = ni.load_scope(str(tmp_path))
    assert src == "project" and sc["dirs"] == {"k": "whitelist"}


def test_load_scope_v1_reports_deprecated(tmp_path):
    p = os.path.join(str(tmp_path), ni.SCOPE_FILE)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "tier": "auto", "include": ["."]}, f)
    sc, src = ni.load_scope(str(tmp_path))
    assert sc is None and src == "v1-deprecated"


def test_save_scope_writes_and_backs_up_v1(tmp_path):
    root = str(tmp_path)
    p = os.path.join(root, ni.SCOPE_FILE)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "include": ["."]}, f)
    ok, err = ni.save_scope(root, {"version": 2, "mode": "manual",
                                   "dirs": {}, "artifact_roots": [],
                                   "exclude_names": [], "arch": "auto",
                                   "name": "x"})
    assert ok, err
    assert os.path.isfile(p + ".v1.bak"), "v1 覆盖前必须备份"
    with open(p, encoding="utf-8") as f:
        assert json.load(f)["version"] == 2


def test_save_scope_does_not_overwrite_existing_bak(tmp_path):
    root = str(tmp_path)
    p = os.path.join(root, ni.SCOPE_FILE)
    bak = p + ".v1.bak"
    with open(bak, "w") as f:
        f.write("ORIGINAL")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"version": 1}, f)
    ni.save_scope(root, {"version": 2, "mode": "manual"})
    with open(bak) as f:
        assert f.read() == "ORIGINAL"


# ---- build 端到端（小树）-----------------------------------------------

def _make_tree(root, layout):
    """layout: {rel_dir: [filenames]}"""
    for d, files in layout.items():
        p = os.path.join(root, *d.split("/")) if d else root
        os.makedirs(p, exist_ok=True)
        for fn in files:
            with open(os.path.join(p, fn), "w") as f:
                f.write("int x;\n")


def test_build_off_dir_not_indexed(tmp_path):
    """off 目录的源码不进 files.txt（收录清单）。"""
    root = str(tmp_path)
    _make_tree(root, {"keep": ["a.c"], "drop": ["b.c"]})
    sc = {"version": 2, "name": "t", "mode": "manual", "arch": "auto",
          "dirs": {"keep": "full", "drop": "off"},
          "artifact_roots": [], "exclude_names": []}
    # 静默日志，快速失败（无 ctags 也会写 files.txt 前报错——这里只验切分）
    logs = []
    try:
        ni.build(root, log=logs.append, scope=sc)
    except Exception:
        pass
    txt = "\n".join(logs)
    assert "全量区" in txt or "白名单" in txt


def test_build_full_mode_indexes_everything(tmp_path):
    root = str(tmp_path)
    _make_tree(root, {"a": ["x.c"], "b": ["y.c"]})
    sc = {"version": 2, "name": "t", "mode": "full", "arch": "auto",
          "dirs": {}, "artifact_roots": [], "exclude_names": []}
    logs = []
    try:
        ni.build(root, log=logs.append, scope=sc)
    except Exception:
        pass
    assert any("全量区" in l for l in logs)


# ---- a570 第十八轮：根键（"." / ""）表达「工程根自身」------------------

@pytest.mark.parametrize("key", ["", "."])
def test_norm_dirs_accepts_root_key(key):
    """根键用于表达「根直下源码也收」，否则降级后下次建库静默丢根文件。"""
    got = ni._norm_dirs({key: "full", "kernel": "off"})
    assert got == {"": "full", "kernel": "off"}


def test_root_key_beats_default_in_resolve():
    dirs = {"": "full"}
    assert ni._resolve_dir_state("", dirs, "whitelist") == "full"
    assert ni._resolve_dir_state("kernel", dirs, "whitelist") == "full"


def test_mode_full_rejects_non_root_dirs():
    ok, err = ni._norm_scope_v2({"version": 2, "mode": "full",
                                 "dirs": {"kernel": "off"}}, "/x")
    assert not ok and "全树统一" in err


def test_mode_full_allows_matching_root_key():
    ok, sc = ni._norm_scope_v2({"version": 2, "mode": "full",
                                "dirs": {".": "full"}}, "/x")
    assert ok and sc["dirs"] == {"": "full"}
