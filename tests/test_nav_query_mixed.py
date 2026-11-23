# -*- coding: utf-8 -*-
"""查询层混合档适配钉测（a570 / P3）。

两处改动：
1. `manifest.full_dirs` —— 混合档下 full 目录的源没有 .o 记录，不加这档
   会被 `in_build` 降权，真定义输给白名单目录的同名符号（内网 §7.1 实测）。
2. `nm_lock` 语义修正 —— 原实现 `len(syms[sym])==1` 就全局锁定，但那只说明
   「只有一个 .o 编译了它」，不等于「源码只定义一次」。H8 实测 4728 个短符号
   （flags/mode/start）被拽走。
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import nav_index as ni   # noqa: E402


# ---- _under_any --------------------------------------------------------

def test_under_any_prefix_match():
    assert ni._under_any("kernel/tools/x.c", ["kernel/tools"])
    assert ni._under_any("kernel/tools/x.c", ["kernel"])
    assert not ni._under_any("kernelx/x.c", ["kernel"]), "必须按路径段匹配"
    assert not ni._under_any("x.c", [])


def test_under_any_case_insensitive_and_backslash():
    assert ni._under_any("Kernel/Tools/X.C", ["kernel/tools"])
    assert ni._under_any("kernel\\tools\\x.c", ["kernel/tools"])


def test_under_any_exact_dir_is_not_a_file():
    """目录自身不算（rel 是文件路径；但前缀判定允许相等，用于稳健）。"""
    assert ni._under_any("kernel/tools", ["kernel/tools"])


# ---- full_dirs 写进 manifest -------------------------------------------

def _mk(root, rel_dir="", files=()):
    p = os.path.join(root, *rel_dir.split("/")) if rel_dir else root
    os.makedirs(p, exist_ok=True)
    for fn in files:
        with open(os.path.join(p, fn), "w") as f:
            f.write("int x;\n")


def test_build_writes_full_dirs(tmp_path):
    root = str(tmp_path)
    _mk(root, "kernel/lib", ["a.c"])
    _mk(root, "tools", ["t.c"])
    sc = {"version": 2, "name": "t", "mode": "manual", "arch": "auto",
          "dirs": {"kernel": "whitelist", "tools": "full"},
          "artifact_roots": [], "exclude_names": []}
    try:
        ni.build(root, log=lambda _m: None, scope=sc)
    except Exception:
        pass   # ctags 缺失也会先写 manifest
    ld = ni.lib_dir(root)
    mf = json.load(open(os.path.join(ld, "manifest.json"), encoding="utf-8"))
    # a570 第十六轮：零产物下白名单区推导为 0，会按全量收录（P0-2），
    # 于是 kernel 也进 full_dirs。这里钉住「形成的 full 区都被写进去」。
    assert "tools" in (mf.get("full_dirs") or []), mf.get("full_dirs")
    assert "kernel" in (mf.get("full_dirs") or []), \
        "白名单区零单元时已降全量，full_dirs 必须同步：%r" % mf.get("full_dirs")


def test_build_mode_full_writes_empty_full_dirs(tmp_path):
    """mode=full 时全树都是 full，不该把每个目录都写进 full_dirs。"""
    root = str(tmp_path)
    _mk(root, "a", ["x.c"])
    sc = {"version": 2, "name": "t", "mode": "full", "arch": "auto",
          "dirs": {}, "artifact_roots": [], "exclude_names": []}
    try:
        ni.build(root, log=lambda _m: None, scope=sc)
    except Exception:
        pass
    ld = ni.lib_dir(root)
    mf = json.load(open(os.path.join(ld, "manifest.json"), encoding="utf-8"))
    assert mf.get("full_dirs") == []


# ---- nm_lock 语义 ------------------------------------------------------

def _prepare_lib(tmp_path, files, compiled=None, symbols=None,
                 full_dirs=None):
    """造一个最小索引库，供 definition/symbols 直接读。"""
    root = str(tmp_path)
    _mk(root, "src", list(files))
    ld = ni.lib_dir(root)
    os.makedirs(ld, exist_ok=True)
    # find_lib_for 靠 list_libs() 遍历 meta.json 反查——缺它查不到库
    ni._write_json(os.path.join(ld, "meta.json"), {
        "version": 1, "root": root, "built_at": "",
        "code_files": 1, "sizes": {},
    })
    ni._write_json(os.path.join(ld, "manifest.json"), {
        "version": 1, "root": root, "built_at": "",
        "compiled": compiled or {}, "cmd_count": 0, "o_count": 0,
        "full_dirs": full_dirs or [],
    })
    ni._write_json(os.path.join(ld, "symbols.json"),
                   {"symbols": symbols or {}})
    ni._invalidate_cache()
    return root, ld


def test_nm_lock_not_applied_when_multiple_candidates(tmp_path):
    """核心回归：多候选时**不锁定** nm 源（H8 flags/mode/start 场景）。"""
    files = ["flags.c", "other.c"]
    compiled = {"src/flags.c": {"o": "flags.o", "src": "cmd"},
                "src/other.c": {"o": "other.o", "src": "cmd"}}
    symbols = {"flags": ["src/flags.c"]}   # nm 唯一源
    root, ld = _prepare_lib(tmp_path, files, compiled, symbols)
    # 伪造 tags 后端让两个文件都是 flags 的定义处
    class FakeBe:
        def lookup(self, sym):
            return [(os.path.join(root, "src", "flags.c"), 1, "f", 0),
                    (os.path.join(root, "src", "other.c"), 1, "f", 0)]
        def lookup_ci(self, sym):
            return []
        def files(self):
            return []
    real_open = ni._open_tags
    ni._open_tags = lambda _ld: FakeBe()
    try:
        r = ni.definition(os.path.join(root, "src", "other.c"), "flags")
    finally:
        ni._open_tags = real_open
    assert len(r["candidates"]) == 2
    assert not any(c["nm_lock"] for c in r["candidates"]), \
        "多候选时不应锁定 nm 源（这会让用户在自己文件里点符号被拽走）"


def test_nm_lock_applied_when_unique_candidate(tmp_path):
    """闭源 SDK 场景（tags 只有一处定义，且就是 nm 源）→ 锁定。"""
    files = ["only.c"]
    compiled = {"src/only.c": {"o": "only.o", "src": "cmd"}}
    symbols = {"only_sym": ["src/only.c"]}
    root, ld = _prepare_lib(tmp_path, files, compiled, symbols)

    class FakeBe:
        def lookup(self, sym):
            return [(os.path.join(root, "src", "only.c"), 3, "f", 0)]
        def lookup_ci(self, sym):
            return []
        def files(self):
            return []
    real_open = ni._open_tags
    ni._open_tags = lambda _ld: FakeBe()
    try:
        r = ni.definition(os.path.join(root, "src", "only.c"), "only_sym")
    finally:
        ni._open_tags = real_open
    assert len(r["candidates"]) == 1
    assert r["candidates"][0]["nm_lock"] is True


def test_nm_lock_field_always_present(tmp_path):
    """字段不能删——rank() 直接读 c["nm_lock"]，缺了会 KeyError。"""
    files = ["a.c"]
    root, ld = _prepare_lib(tmp_path, files)

    class FakeBe:
        def lookup(self, sym):
            return [(os.path.join(root, "src", "a.c"), 1, "f", 0)]
        def lookup_ci(self, sym):
            return []
        def files(self):
            return []
    real_open = ni._open_tags
    ni._open_tags = lambda _ld: FakeBe()
    try:
        r = ni.definition(os.path.join(root, "src", "a.c"), "zzz")
    finally:
        ni._open_tags = real_open
    assert "nm_lock" in r["candidates"][0]


# ---- full_dirs 参与 in_build -------------------------------------------

def test_full_dir_source_counts_as_in_build(tmp_path):
    """mixed 档：full 目录的源没有 .o 记录，但仍应算 in_build=True。"""
    files = ["tool.c"]
    root, ld = _prepare_lib(tmp_path, files, compiled={},
                            full_dirs=["src"])
    class FakeBe:
        def lookup(self, sym):
            return [(os.path.join(root, "src", "tool.c"), 1, "f", 0)]
        def lookup_ci(self, sym):
            return []
        def files(self):
            return []
    real_open = ni._open_tags
    ni._open_tags = lambda _ld: FakeBe()
    try:
        r = ni.definition(os.path.join(root, "src", "tool.c"), "zzz")
    finally:
        ni._open_tags = real_open
    assert r["candidates"][0]["in_build"] is True


def test_old_lib_without_full_dirs_still_works(tmp_path):
    """旧库（manifest 无 full_dirs 字段）→ 退化为纯白名单判断，不报错。"""
    files = ["a.c"]
    root = str(tmp_path)
    _mk(root, "src", files)
    ld = ni.lib_dir(root)
    os.makedirs(ld, exist_ok=True)
    ni._write_json(os.path.join(ld, "meta.json"), {
        "version": 1, "root": root, "built_at": "", "code_files": 1,
        "sizes": {}})
    ni._write_json(os.path.join(ld, "manifest.json"),
                   {"version": 1, "root": root, "compiled": {},
                    "cmd_count": 0, "o_count": 0})   # 无 full_dirs
    ni._write_json(os.path.join(ld, "symbols.json"), {"symbols": {}})
    ni._invalidate_cache()

    class FakeBe:
        def lookup(self, sym):
            return [(os.path.join(root, "src", "a.c"), 1, "f", 0)]
        def lookup_ci(self, sym):
            return []
        def files(self):
            return []
    real_open = ni._open_tags
    ni._open_tags = lambda _ld: FakeBe()
    try:
        r = ni.definition(os.path.join(root, "src", "a.c"), "zzz")
    finally:
        ni._open_tags = real_open
    assert r["candidates"][0]["in_build"] is False
