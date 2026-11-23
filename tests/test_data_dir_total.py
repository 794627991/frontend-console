# -*- coding: utf-8 -*-
"""data_hygiene.data_dir_total 回归锚（2026-11-23，闲时审计 a687 B-1/B-2）。

面板「共 X」那一个数此前每次 GET /api/data_dir 都同步全量深扫、无缓存，
且统计失败回 0（面板显示「共 0 B」，用户以为数据没了）。锁住：
  1. 有 60s TTL 缓存，同一目录 60s 内不重扫
  2. 按目录作键：数据目录迁移后自然失效
  3. manual_clean 后缓存失效（清理完数字要跟上）
  4. 目录不存在/读不了 → None（不是 0）；空目录 → 0
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import src.app_state as st
import src.data_hygiene as dh


def _reset(monkeypatch, path):
    monkeypatch.setattr(st, "DATA_DIR", path)
    dh._dir_total_cache.update(key=None, ts=0.0, val=None)


def test_counts_real_bytes_and_caches(tmp_path, monkeypatch):
    d = tmp_path / "data"
    d.mkdir()
    (d / "a.bin").write_bytes(b"x" * 1000)
    (d / "sub").mkdir()
    (d / "sub" / "b.bin").write_bytes(b"y" * 250)
    _reset(monkeypatch, str(d))
    assert dh.data_dir_total() == 1250
    (d / "c.bin").write_bytes(b"z" * 7)          # 缓存期内改了目录
    assert dh.data_dir_total() == 1250          # 60s 内不重扫
    assert dh.data_dir_total(force=True) == 1257


def test_cache_key_follows_data_dir(tmp_path, monkeypatch):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    (a / "x").write_bytes(b"x" * 10)
    (b / "y").write_bytes(b"y" * 20)
    _reset(monkeypatch, str(a))
    assert dh.data_dir_total() == 10
    monkeypatch.setattr(st, "DATA_DIR", str(b))     # 迁移后换了目录
    assert dh.data_dir_total() == 20                # 不能吃旧目录的缓存


def test_manual_clean_invalidates_cache(tmp_path, monkeypatch):
    d = tmp_path / "data" / "logs"
    d.mkdir(parents=True)
    (d / "serial_1.log").write_bytes(b"x" * 500)
    monkeypatch.setattr(st, "LOG_DIR", str(d))
    _reset(monkeypatch, str(tmp_path / "data"))
    assert dh.data_dir_total() == 500
    removed, freed = dh.manual_clean("logs", "all")
    assert removed == 1
    assert dh.data_dir_total() == 0                 # 清理后数字跟上


def test_missing_dir_is_none_not_zero(tmp_path, monkeypatch):
    _reset(monkeypatch, str(tmp_path / "nope"))
    assert dh.data_dir_total() is None
    empty = tmp_path / "empty"
    empty.mkdir()
    _reset(monkeypatch, str(empty))
    assert dh.data_dir_total() == 0                 # 空目录才是 0


if __name__ == "__main__":
    import pytest as _pt
    sys.exit(_pt.main([__file__, "-q"]))
