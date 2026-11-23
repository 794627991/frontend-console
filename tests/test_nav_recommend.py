# -*- coding: utf-8 -*-
"""推荐器规则钉测（a570）。

规则来自内网定稿 §四（L0~L3），六平台实测验证过。这里把每条规则的
**边界**钉死——改阈值、改判据顺序都会红。
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import nav_index as ni   # noqa: E402


def _mk(root, rel_dir="", files=()):
    p = os.path.join(root, *rel_dir.split("/")) if rel_dir else root
    os.makedirs(p, exist_ok=True)
    for fn in files:
        with open(os.path.join(p, fn), "w") as f:
            f.write("int x;\n")
    return p


# ---- L0 形态先验 -------------------------------------------------------

def test_l0_buildroot_detected(tmp_path):
    d = _mk(str(tmp_path), "sb")
    _mk(str(tmp_path), "sb/package")
    _mk(str(tmp_path), "sb/output")
    open(os.path.join(d, "Config.in"), "w").close()
    got = ni._rule_level0(d)
    assert got == ("off", os.path.join("output", "build"))


def test_l0_requires_all_three_markers(tmp_path):
    d = _mk(str(tmp_path), "sb")
    _mk(str(tmp_path), "sb/package")
    open(os.path.join(d, "Config.in"), "w").close()
    assert ni._rule_level0(d) is None      # 缺 output/


def test_l0_ignores_directory_name(tmp_path):
    """E13 的 buildroot 目录叫 sbuilder，换个工程可能叫别的——必须认结构。"""
    d = _mk(str(tmp_path), "whatever_name")
    _mk(str(tmp_path), "whatever_name/package")
    _mk(str(tmp_path), "whatever_name/output")
    open(os.path.join(d, "Config.in"), "w").close()
    assert ni._rule_level0(d) is not None


# ---- L1 名称先验 -------------------------------------------------------

@pytest.mark.parametrize("name", ["rootfs", "eroot", "buildroot",
                                  "build_root", "rootfs_build"])
def test_l1_rootfs_family_off(name):
    assert ni._rule_level1(name)[0] == "off"


@pytest.mark.parametrize("name", ["zoos", "zoo_tmp", "zmo"])
def test_l1_zoo_family_off(name):
    assert ni._rule_level1(name)[0] == "off"


@pytest.mark.parametrize("name", ["release", "release_tmp", "temp_log"])
def test_l1_release_family_off(name):
    assert ni._rule_level1(name)[0] == "off"


@pytest.mark.parametrize("name", ["kernel", "libs", "modules", "tools",
                                  "uboot", "linux", "minisys"])
def test_l1_does_not_match_kernel_like(name):
    """探针：E13 的内核目录叫 linux——L1 不得认这些名字（走 L3 数值判定）。"""
    assert ni._rule_level1(name) is None


# ---- L2 数量先验 -------------------------------------------------------

def test_l2_empty_dir_off():
    assert ni._rule_level2(0, 0, 0)[0] == "off"


def test_l2_few_code_off():
    assert ni._rule_level2(4, 5, 5)[0] == "off"


def test_l2_code_without_artifacts_full():
    assert ni._rule_level2(100, 0, 0)[0] == "full"


def test_l2_code_with_artifacts_passes_through():
    assert ni._rule_level2(100, 10, 10) is None


# ---- L3 比值判定 -------------------------------------------------------

def test_l3_low_o_ratio_is_whitelist_with_warn():
    """o_ratio < 0.8：.o 比源还多 → 增量残留嫌疑。"""
    st, _, warn = ni._rule_level3(10, 20, 20)
    assert st == "whitelist" and warn


def test_l3_normal_coverage_whitelist():
    """10 源 / 5 .o → o_ratio=2 → 正常白名单。"""
    st, _, warn = ni._rule_level3(10, 5, 5)
    assert st == "whitelist" and not warn


def test_l3_kernel_shape_whitelist():
    """内核形态：32594 源 / 2296 .o / 3246 cmd（cmd_ratio 9.96%）。"""
    st, reason, warn = ni._rule_level3(32594, 2296, 3246)
    assert st == "whitelist" and not warn


def test_l3_no_cmd_is_full():
    """a570 新增（用户定调）：cmd==0 → 白名单单元必然为 0 → full。"""
    st, reason, _ = ni._rule_level3(5000, 100, 0)
    assert st == "full" and "必然为空" in reason


def test_l3_small_insufficient_coverage_full():
    """H8 seeboot：340 源 / 107 .o / 0 cmd → full。"""
    st, _, _ = ni._rule_level3(340, 107, 0)
    assert st == "full"


def test_l3_large_insufficient_coverage_whitelist_with_warn():
    """src >= 2000 且产物覆盖不足 → whitelist + 强告警（不能私自全收）。"""
    # o_ratio=50 > 2；cmd_ratio=0.2% < 3%；o_cmd=100/10=10 > 5；src>=2000
    st, _, warn = ni._rule_level3(5000, 100, 10)
    assert st == "whitelist" and warn


def test_l3_libs_shape_full():
    """G10/H9/E13/H13 的 libs：200+ 源 / ~90 .o / 1 cmd → full。"""
    for src, o in ((206, 96), (257, 97), (219, 97), (218, 82)):
        st, _, _ = ni._rule_level3(src, o, 1)
        assert st == "full", "libs(%d/%d) 应判 full" % (src, o)


# ---- _count_dir_full ---------------------------------------------------

def test_count_src_includes_upper_S(tmp_path):
    """定稿 §3.1：.S 大写必须计入 src（内核有 1343 个 .S）。"""
    d = _mk(str(tmp_path), "k", ["a.c", "b.S", "c.s", "d.h"])
    total, per_sub, _, _soft = ni._count_dir_full(d, time.time() + 10)
    assert total[0] == 3, "src 应含 .c/.S/.s，不含 .h"
    assert total[1] == 4, "code 应含 .h"


def test_count_groups_by_first_level_subdir(tmp_path):
    _mk(str(tmp_path), "k/sub1", ["a.c"])
    _mk(str(tmp_path), "k/sub2", ["b.c"])
    d = _mk(str(tmp_path), "k", ["top.c"])
    total, per_sub, _, _soft = ni._count_dir_full(d, time.time() + 10)
    assert total[0] == 3
    assert per_sub["sub1"][0] == 1
    assert per_sub["sub2"][0] == 1
    # 顶层直下文件用 __root__ 键（不是空串——空键会在 JSON 里变形）
    assert per_sub["__root__"][0] == 1


def test_count_skips_skip_dirs_and_tmp(tmp_path):
    d = _mk(str(tmp_path), "k/src", ["a.c"])
    _mk(str(tmp_path), "k/node_modules", ["x.js"])
    _mk(str(tmp_path), "k/tmp", ["y.c"])
    total, _, _, _soft = ni._count_dir_full(d, time.time() + 10)
    assert total[0] == 1


# ---- recommend_scope 端到端 --------------------------------------------

def test_recommend_scope_basic(tmp_path):
    root = str(tmp_path)
    # L2.2 判据 code<5 → off；内核形态至少要 5 个代码文件
    _mk(root, "kernel/kernel_sdk", ["a.c", "b.c", "c.c", "d.c", "e.c"])
    for i in range(5):
        open(os.path.join(root, "kernel", "kernel_sdk", "o%d.o" % i), "w").close()
        open(os.path.join(root, "kernel", "kernel_sdk", "o%d.o.cmd" % i), "w").close()
    # 规则 L2.2：code < 5 → off。要测 full 就得给够文件
    _mk(root, "tools", ["t%d.py" % i for i in range(6)])
    r = ni.recommend_scope(root, say=lambda _m: None)
    assert r["ok"]
    assert r["dirs"]["kernel"] == "whitelist", r["dirs"]
    assert r["dirs"]["tools"] == "full", r["dirs"]


def test_recommend_scope_buildroot_artifact_root(tmp_path):
    root = str(tmp_path)
    _mk(root, "sbuilder/package")
    _mk(root, "sbuilder/output")
    open(os.path.join(root, "sbuilder", "Config.in"), "w").close()
    _mk(root, "kernel", ["a.c"])
    r = ni.recommend_scope(root, say=lambda _m: None)
    assert r["dirs"]["sbuilder"] == "off"
    assert any("output/build" in p for p in r["artifact_roots"])


def test_recommend_scope_reports_nodes_with_data(tmp_path):
    root = str(tmp_path)
    _mk(root, "kernel", ["a.c", "a.o", "a.o.cmd"])
    r = ni.recommend_scope(root, say=lambda _m: None)
    node = next(n for n in r["nodes"] if n["rel"] == "kernel")
    assert node["src"] == 1 and node["o"] == 1 and node["cmd"] == 1


def test_recommend_scope_can_cancel(tmp_path):
    root = str(tmp_path)
    _mk(root, "a", ["x.c"])
    with pytest.raises(ni.Cancelled):
        ni.recommend_scope(root, should_cancel=lambda: True,
                           say=lambda _m: None)
