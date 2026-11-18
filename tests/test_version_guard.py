# -*- coding: utf-8 -*-
"""提交号守卫单测（a645）。

撞号（a584、a641）根因是手工取号：看一眼最大号 → 写代码 → 几分钟后提交，
期间别的会话已经用掉同一号。这里钉住守卫的三条核心行为：
  1. 取号 = 全仓库已用最大号 + 1（--all，含其他分支）
  2. 标题号错/旧/跳/撞 → 改写成提交瞬间的下一个可用号
  3. 正文里**等于原标题号**的版本引用同步改写，别号（a629 这类历史引用）保留
"""
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import version_guard as V  # noqa: E402


def _git(repo, *a, **kw):
    return subprocess.run(["git"] + list(a), cwd=repo, check=True,
                          capture_output=True, **kw).stdout.decode()


@pytest.fixture
def repo(tmp_path):
    r = str(tmp_path / "r")
    os.makedirs(r)
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    for num in (10, 11, 12):
        _git(r, "commit", "-q", "--allow-empty", "-m", "v4.1.0-a%d x" % num)
    return r


def test_next_is_max_plus_one(repo):
    assert V.next_version(repo) == 13


def test_next_counts_other_branches(repo):
    """别的分支已用掉的号也要算——并发会话正是靠这条不撞号。"""
    _git(repo, "checkout", "-q", "-b", "side")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "v4.1.0-a20 side")
    _git(repo, "checkout", "-q", "master")
    assert V.next_version(repo) == 21


@pytest.mark.parametrize("old,expect_num", [
    ("v4.1.0-a11", 13),      # 写旧了
    ("v4.1.0-a99", 13),      # 跳号（未来号）
    ("v4.1.0-a12", 13),      # 就是 HEAD 号（撞号）
])
def test_retitle_rewrites_to_next(repo, old, expect_num):
    msg = "%s 做点事\n\n说明" % old
    new, _o = V._retitle(msg, "4.1.0", V.next_version(repo))
    assert new.split("\n")[0].startswith("v4.1.0-a%d " % expect_num)


def test_retitle_keeps_foreign_refs_and_updates_own():
    """正文里等于原标题号的引用跟着改；a629 这类历史引用必须保留。"""
    msg = ("v4.1.0-a640 删区块\n\n"
           "a640 删内容、a641 删入口；同时 a629 那次洗白测试也一并改判。")
    new, old = V._retitle(msg, "4.1.0", 645)
    assert old == 640
    assert new.split("\n")[0].startswith("v4.1.0-a645")
    assert "a645 删内容" in new          # 本号引用跟着改
    assert "a629" in new                 # 历史引用保留
    assert "a641" in new                 # 但 a641 是别的号 → 保留


def test_retitle_ignores_unversioned_message():
    msg = "Merge branch 'x'"
    new, old = V._retitle(msg, "4.1.0", 645)
    assert new == msg and old is None


def test_pre_commit_bumps_future_num_only(repo):
    """暂存的新增行里出现未来号 → 改成本次号并重新 add；小号引用不动。"""
    p = os.path.join(repo, "f.py")
    with open(p, "w", encoding="utf-8") as f:
        f.write("# a5 历史引用\nX = 1  # a645 笔误\n")
    _git(repo, "add", "f.py")
    V.hook_pre_commit(repo)
    s = open(p, encoding="utf-8").read()
    assert "a5 " in s, s
    assert "a645" not in s, s
    assert s.count("a%d" % V.next_version(repo)) == 1, s


def test_install_uninstall_roundtrip(repo):
    assert V.install(repo) == 0
    for n in ("commit-msg", "pre-commit"):
        assert os.path.isfile(os.path.join(repo, ".git", "hooks", n))
    V.uninstall(repo)
    for n in ("commit-msg", "pre-commit"):
        assert not os.path.exists(os.path.join(repo, ".git", "hooks", n))


def test_install_refuses_foreign_hook(repo):
    p = os.path.join(repo, ".git", "hooks", "pre-commit")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write("#!/bin/sh\necho mine\n")
    assert V.install(repo) == 3
    with open(p, encoding="utf-8") as f:
        assert "echo mine" in f.read(), "别人的钩子不能被覆盖"
