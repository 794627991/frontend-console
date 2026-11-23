# -*- coding: utf-8 -*-
"""app_state._selfheal_cfg 回归锚（2026-11-23 评审修复）。

此前导入期自愈与 a669 加固过的 cfg_read 口径不一致：读侧 IO 故障（占用/
权限/杀软扫描）被当成「损坏」，直接拿 .bak 覆盖掉磁盘上**完好**的现行
配置——隔离实验实锤 '{"a":1,"b":2,"new":3}' 被洗回 '{"a":1,"b":2}'，且因
坏件读不出来连 .bad 留证都没有。另一处：无副本可恢复时坏件原地不动，
每次启动再留一个 .bad-<时间>，无限堆。

本文件锁住：
  1. 正常 / 带 BOM / 不存在 三种基线行为不变
  2. 内容真坏 → .bak → 镜像 顺序恢复并落盘，坏件留证
  3. 顶层不是对象 → 按「坏」处理（不让导入期 .get() 崩）
  4. 同一份坏件反复自愈，留证只留一份
  5. 读取瞬间被占用 → **不动盘**、不覆盖、不留证
  6. 坏件无法留证 → 不覆盖主文件（内存暂用副本）

pytest 收集；也可 `python tests/test_selfheal_cfg.py` 直接跑（app_state
的测试自隔离靠 argv[0] 在 tests/ 下生效）。
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src import app_state as st


@pytest.fixture
def home(tmp_path, monkeypatch):
    """把 config 的家指到临时目录（pytest 下 app_state 已自动隔离，这里再把
    _selfheal_cfg 运行时读的两个全局名钉到用例自己的目录）。"""
    d = tmp_path / "data"
    (d / "data_backup").mkdir(parents=True)
    monkeypatch.setattr(st, "CONFIG_FILE", str(d / "config.json"))
    monkeypatch.setattr(st, "CONFIG_BACKUP_FILE",
                        str(d / "data_backup" / "config.json"))
    return d


def _w(path, text):
    path.write_text(text, encoding="utf-8")


def _bads(d):
    return sorted(n for n in os.listdir(str(d)) if n.startswith("config.json.bad-"))


def test_ok_untouched(home):
    _w(home / "config.json", '{"a": 1, "b": 2}')
    assert st._selfheal_cfg() == {"a": 1, "b": 2}
    assert _bads(home) == []


def test_bom_is_not_corruption(home):
    (home / "config.json").write_bytes(b"\xef\xbb\xbf" + '{"a": 1}'.encode())
    assert st._selfheal_cfg() == {"a": 1}
    assert _bads(home) == []


def test_missing_is_empty(home):
    assert st._selfheal_cfg() == {}
    assert not (home / "config.json").exists()


def test_corrupt_recovers_from_bak_and_preserves_bad(home):
    _w(home / "config.json", '{"a": 1, "b": ')          # 半截 JSON
    _w(home / "config.json.bak", '{"a": 1, "b": 2}')
    assert st._selfheal_cfg() == {"a": 1, "b": 2}
    assert json.loads((home / "config.json").read_text(encoding="utf-8")) \
        == {"a": 1, "b": 2}                             # 副本已落盘
    assert len(_bads(home)) == 1                        # 坏件留证


def test_corrupt_falls_back_to_mirror_when_no_bak(home):
    _w(home / "config.json", 'not json')
    _w(home / "data_backup" / "config.json", '{"a": 9}')
    assert st._selfheal_cfg() == {"a": 9}
    assert json.loads((home / "config.json").read_text(encoding="utf-8")) == {"a": 9}


def test_non_dict_top_level_is_treated_as_corrupt(home):
    _w(home / "config.json", '[1, 2, 3]')               # 合法 JSON 但不是对象
    _w(home / "config.json.bak", '{"a": 1}')
    assert st._selfheal_cfg() == {"a": 1}


def test_bad_evidence_not_duplicated_across_starts(home):
    _w(home / "config.json", '{"broken": ')             # 无任何副本
    assert st._selfheal_cfg() == {}
    assert st._selfheal_cfg() == {}
    assert st._selfheal_cfg() == {}
    assert len(_bads(home)) == 1                        # 旧实现：每启动一个
    assert (home / "config.json").read_text(encoding="utf-8") == '{"broken": '


def test_recovery_never_overwrites_when_bad_cannot_be_preserved(home, monkeypatch):
    _w(home / "config.json", '{"broken": ')
    _w(home / "config.json.bak", '{"a": 1}')
    monkeypatch.setattr(st, "_preserve_bad_cfg", lambda _main: False)
    assert st._selfheal_cfg() == {"a": 1}               # 内存用副本
    assert (home / "config.json").read_text(encoding="utf-8") == '{"broken": '


@pytest.mark.skipif(sys.platform != "win32", reason="用 Win32 共享模式制造读故障")
def test_transient_read_failure_does_not_touch_disk(home):
    """读取瞬间被占用：内容完好，只是别的句柄此刻不让读。"""
    import ctypes
    from ctypes import wintypes
    main = home / "config.json"
    _w(main, '{"a": 1, "b": 2, "new": 3}')
    _w(home / "config.json.bak", '{"a": 1, "b": 2}')
    before = main.read_bytes()
    k32 = ctypes.windll.kernel32
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                wintypes.HANDLE]
    INVALID = wintypes.HANDLE(-1).value
    # 只允许别人以「写」方式打开 → 别人 open(..., 'r') 报共享冲突
    h = k32.CreateFileW(str(main), 0x80000000 | 0x40000000, 0x2, None, 3, 0, None)
    assert h not in (None, 0, INVALID), "CreateFileW 失败"
    try:
        with pytest.raises(PermissionError):
            open(str(main), "r", encoding="utf-8-sig").read()   # 自检：确实读不了
        assert st._selfheal_cfg() == {}                  # 读不到 ≠ 空，更 ≠ 坏
    finally:
        k32.CloseHandle(h)
    assert main.read_bytes() == before                   # 现行配置原封不动
    assert _bads(home) == []                             # 没有留证（本就没有坏件）
    assert st._selfheal_cfg() == {"a": 1, "b": 2, "new": 3}   # 占用解除后回到真实配置


# ---------------- 运行期（cfg_commit）遇到坏文件 ----------------

def test_read_cfg_state_treats_non_dict_as_corrupt(home):
    """W-2：合法 JSON 但顶层不是对象 → corrupt，与 _cfg_read_strict 同口径。"""
    p = str(home / "config.json")
    for bad in ('[1, 2, 3]', '"just a string"', '42'):
        _w(home / "config.json", bad)
        assert st._read_cfg_state(p) == ("corrupt", None), bad
    _w(home / "config.json", '{"a": 1}')
    assert st._read_cfg_state(p) == ("ok", {"a": 1})
    assert st._read_cfg_state(str(home / "nope.json")) == ("missing", None)


def test_cfg_commit_on_corrupt_heals_instead_of_wiping(home):
    """W-1：保存时撞上坏文件——留证 + 从副本恢复为基线，而不是以空为底洗库。"""
    _w(home / "config.json", '{"a": 1, "b": 2, "broken": ')     # 坏件
    _w(home / "config.json.bak", '{"a": 1, "b": 2, "c": 3}')
    ok, err = st.cfg_commit(lambda d: d.update(theme="dark"))
    assert ok is True, err
    assert json.loads((home / "config.json").read_text(encoding="utf-8")) \
        == {"a": 1, "b": 2, "c": 3, "theme": "dark"}   # 副本的键一个没丢
    assert len(_bads(home)) == 1                             # 坏件留证
    # 留底仍是能用的配置，没被坏件污染
    assert json.loads((home / "config.json.bak").read_text(encoding="utf-8")) \
        == {"a": 1, "b": 2, "c": 3}


def test_cfg_commit_on_corrupt_without_backup_keeps_evidence(home):
    """没有任何可用副本（.bak / 镜像都不存在）：至少留证，从空起步，且
    坏件不会被当成「上一版」写进 .bak。"""
    _w(home / "config.json", '{"broken": ')
    ok, err = st.cfg_commit(lambda d: d.update(theme="dark"))
    assert ok is True, err
    assert json.loads((home / "config.json").read_text(encoding="utf-8")) \
        == {"theme": "dark"}
    assert len(_bads(home)) == 1                         # 坏件留了证
    assert not (home / "config.json.bak").exists()      # 坏件没有变成「上一版」


def test_cfg_commit_on_corrupt_recovers_from_mirror(home):
    """.bak 缺失时退到 data_backup 镜像；留底随后是恢复后的好内容。"""
    _w(home / "config.json", '{"broken": ')
    _w(home / "data_backup" / "config.json", '{"m": 1}')
    ok, err = st.cfg_commit(lambda d: d.update(theme="dark"))
    assert ok is True, err
    assert json.loads((home / "config.json").read_text(encoding="utf-8")) \
        == {"m": 1, "theme": "dark"}
    # .bak = 上一版（恢复出来的那份，不含本次修改），不是坏件
    assert json.loads((home / "config.json.bak").read_text(encoding="utf-8")) \
        == {"m": 1}


if __name__ == "__main__":
    import pytest as _pt
    sys.exit(_pt.main([__file__, "-q"]))
