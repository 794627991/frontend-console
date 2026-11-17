# -*- coding: utf-8 -*-
"""数据目录归位单测（a594：打包版升级丢凭据的真实事故）。

事故链：frozen 形态下 __file__ = <app>/_internal/src/app_state.pyd，
BASE_DIR 上溯两层 = <app>/_internal → 默认数据目录写成 <app>/_internal/data；
而 updater 的升级 bat 只搬 <app>/data → 每升一次版凭据/session/命令库
全部「消失」，旧数据留在 _internal/data 与 .bak-*/ 备份里。

本测钉住：
1. _default_data_dir 在 frozen 下落在 exe 旁（APP_DIR/data），不是 _internal/
2. _legacy_data_sources 能枚举 _internal/data 与 .bak-*/.../_internal/data
3. _merge_dir_into 不覆盖已有同名文件、保留嵌套子目录、搬空后删源目录
4. 只搬「像用户数据」的目录（随机同名空目录不搬）
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, '.')

import src.app_state as st


def _mk_install(root, name="前端控制台"):
    app = os.path.join(root, name)
    os.makedirs(os.path.join(app, "_internal", "src"), exist_ok=True)
    return app


def _write(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def test_default_data_dir_uses_app_dir_when_frozen(monkeypatch):
    """frozen 下默认数据目录必须在 exe 旁，不能在 _internal 下。"""
    root = tempfile.mkdtemp(prefix="fc_dd_")
    try:
        app = _mk_install(root)
        internal = os.path.join(app, "_internal")
        monkeypatch.setattr(st, "BASE_DIR", internal)
        monkeypatch.setattr(st, "APP_DIR", app)
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable",
                            os.path.join(app, "前端控制台.exe"), raising=False)
        got = st._default_data_dir()
        assert os.path.normpath(got) == os.path.normpath(os.path.join(app, "data"))
        assert "_internal" not in got
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_default_data_dir_source_mode_unchanged(monkeypatch):
    """源码形态（非 frozen）行为必须与改动前一致：项目根/data。"""
    monkeypatch.delattr(sys, "frozen", raising=False)
    got = st._default_data_dir()
    assert os.path.normpath(got) == os.path.normpath(os.path.join(st.BASE_DIR, "data"))


def test_legacy_sources_find_internal_and_backup(monkeypatch):
    """能枚举 _internal/data 与升级备份 .bak-*/_internal/data。"""
    root = tempfile.mkdtemp(prefix="fc_ls_")
    try:
        app = _mk_install(root)
        internal_data = os.path.join(app, "_internal", "data")
        _write(os.path.join(internal_data, "hiklink_session.json"),
               {"app_id": "OLD"})
        bak = os.path.join(root, "前端控制台.bak-20260101-000000")
        bak_data = os.path.join(bak, "_internal", "data")
        _write(os.path.join(bak_data, "lanz_credentials.json"),
               {"username": "u", "password": "p"})

        monkeypatch.setattr(st, "BASE_DIR", os.path.join(app, "_internal"))
        monkeypatch.setattr(st, "APP_DIR", app)
        monkeypatch.setattr(st, "DATA_DIR", os.path.join(app, "data"))
        monkeypatch.setattr(sys, "frozen", True, raising=False)

        srcs = st._legacy_data_sources()
        norm = {os.path.normpath(x) for x in srcs}
        assert os.path.normpath(internal_data) in norm
        assert os.path.normpath(bak_data) in norm
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_legacy_sources_skip_empty_dirs(monkeypatch):
    """没有用户数据的同名目录不算数据源（防误搬）。"""
    root = tempfile.mkdtemp(prefix="fc_es_")
    try:
        app = _mk_install(root)
        os.makedirs(os.path.join(app, "_internal", "data"), exist_ok=True)
        monkeypatch.setattr(st, "BASE_DIR", os.path.join(app, "_internal"))
        monkeypatch.setattr(st, "APP_DIR", app)
        monkeypatch.setattr(st, "DATA_DIR", os.path.join(app, "data"))
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        assert st._legacy_data_sources() == []
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_merge_dir_into_no_overwrite_and_nested():
    """新位置同名不覆盖；嵌套子目录整体搬入；搬空后删源目录。"""
    src = tempfile.mkdtemp(prefix="fc_src_")
    dst = tempfile.mkdtemp(prefix="fc_dst_")
    try:
        _write(os.path.join(src, "hiklink_session.json"), {"app_id": "OLD"})
        _write(os.path.join(src, "lanz_credentials.json"), {"username": "u"})
        _write(os.path.join(src, "files", "images", "a.png"), {})
        _write(os.path.join(dst, "hiklink_session.json"), {"app_id": "NEW"})

        moved, failed = st._merge_dir_into(src, dst)
        assert moved == 2 and failed == 1     # 同名那个跳过
        with open(os.path.join(dst, "hiklink_session.json"), encoding="utf-8") as f:
            assert json.load(f)["app_id"] == "NEW"      # 新位置优先
        assert os.path.exists(os.path.join(dst, "files", "images", "a.png"))
        assert os.path.exists(os.path.join(dst, "lanz_credentials.json"))
        assert os.path.isdir(src)                   # 有跳过项 → 源目录保留
    finally:
        shutil.rmtree(src, ignore_errors=True)
        shutil.rmtree(dst, ignore_errors=True)


def test_merge_dir_into_removes_empty_src():
    """全部搬成功 → 源目录被删（避免每次启动重复扫）。"""
    src = tempfile.mkdtemp(prefix="fc_src2_")
    dst = tempfile.mkdtemp(prefix="fc_dst2_")
    try:
        _write(os.path.join(src, "cmdlib.json"), [{"a": 1}])
        moved, failed = st._merge_dir_into(src, dst)
        assert (moved, failed) == (1, 0)
        assert not os.path.exists(src)
        assert os.path.exists(os.path.join(dst, "cmdlib.json"))
    finally:
        shutil.rmtree(src, ignore_errors=True)
        shutil.rmtree(dst, ignore_errors=True)


# ---- a619（疯狗审计 v4）：跨卷与永动巡逻 ---------------------------------
def _xdev(a, b):
    raise OSError(18, "Invalid cross-device link")


def test_move_no_overwrite_dir_cross_volume(monkeypatch):
    """目录跨盘符：os.rename 抛 EXDEV，必须降级逐项搬运（原来整目录静默
    迁不过去且每次启动重试）。"""
    src = tempfile.mkdtemp(prefix="fc_xdev_s_")
    dst = tempfile.mkdtemp(prefix="fc_xdev_d_")
    try:
        os.makedirs(os.path.join(src, "sub"))
        with open(os.path.join(src, "a.txt"), "w") as f:
            f.write("A")
        with open(os.path.join(src, "sub", "b.txt"), "w") as f:
            f.write("B")
        target = os.path.join(dst, "data")
        monkeypatch.setattr(os, "rename", _xdev)
        st._move_no_overwrite(src, target)
        assert open(os.path.join(target, "a.txt")).read() == "A"
        assert open(os.path.join(target, "sub", "b.txt")).read() == "B"
        assert not os.path.exists(src), "全部搬完必须删源（否则永动重试）"
    finally:
        shutil.rmtree(src, ignore_errors=True)
        shutil.rmtree(dst, ignore_errors=True)


def test_move_no_overwrite_dir_cross_volume_no_overwrite(monkeypatch):
    """跨卷降级同样绝不覆盖：目标已有同名文件时保留旧值，源项留着。"""
    src = tempfile.mkdtemp(prefix="fc_xdev2_s_")
    dst = tempfile.mkdtemp(prefix="fc_xdev2_d_")
    try:
        with open(os.path.join(src, "a.txt"), "w") as f:
            f.write("NEW")
        with open(os.path.join(src, "b.txt"), "w") as f:
            f.write("B")
        target = os.path.join(dst, "data")
        os.makedirs(target)
        with open(os.path.join(target, "a.txt"), "w") as f:
            f.write("OLD")
        monkeypatch.setattr(os, "rename", _xdev)
        st._move_no_overwrite(src, target)
        assert open(os.path.join(target, "a.txt")).read() == "OLD"
        assert os.path.exists(os.path.join(target, "b.txt")), "其余项仍要搬"
        assert os.path.exists(os.path.join(src, "a.txt")), "未搬成的留在源目录"
    finally:
        shutil.rmtree(src, ignore_errors=True)
        shutil.rmtree(dst, ignore_errors=True)


def test_merge_log_dir_converges_with_empty_subdirs():
    """空子目录不能让源目录永远删不掉（原来被记成 unmerged → 每次启动
    重扫同一批死目录）。"""
    legacy = tempfile.mkdtemp(prefix="fc_log_s_")
    dst = tempfile.mkdtemp(prefix="fc_log_d_")
    try:
        os.makedirs(os.path.join(legacy, "empty_sub"))
        os.makedirs(os.path.join(legacy, "d1"))
        with open(os.path.join(legacy, "a.log"), "w") as f:
            f.write("A")
        with open(os.path.join(legacy, "d1", "b.log"), "w") as f:
            f.write("B")
        merged, unmerged = st._merge_log_dir(legacy, dst)
        assert merged == 2 and not unmerged
        assert os.path.isdir(os.path.join(dst, "empty_sub"))
        assert not os.path.exists(legacy), "全部处理完必须删源（否则永动巡逻）"
    finally:
        shutil.rmtree(legacy, ignore_errors=True)
        shutil.rmtree(dst, ignore_errors=True)


def test_merge_log_dir_converges_when_all_names_collide():
    """源里全是目标已有的同名文件（merged=0）也要删源。"""
    legacy = tempfile.mkdtemp(prefix="fc_log2_s_")
    dst = tempfile.mkdtemp(prefix="fc_log2_d_")
    try:
        with open(os.path.join(legacy, "a.log"), "w") as f:
            f.write("NEW")
        with open(os.path.join(dst, "a.log"), "w") as f:
            f.write("OLD")
        merged, unmerged = st._merge_log_dir(legacy, dst)
        assert (merged, unmerged) == (0, [])
        assert open(os.path.join(dst, "a.log")).read() == "OLD"
        assert not os.path.exists(legacy)
    finally:
        shutil.rmtree(legacy, ignore_errors=True)
        shutil.rmtree(dst, ignore_errors=True)


def test_save_cmd_lib_reports_failure(monkeypatch):
    """a619：保存失败必须有返回值+日志，不能无声吞掉（用户不知道丢了）。"""
    monkeypatch.setattr(st, "CMD_LIB_FILE",
                        os.path.join(tempfile.mkdtemp(), "cmdlib.json"))
    monkeypatch.setattr(st, "replace_retry",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("denied")))
    assert st._save_cmd_lib([{"name": "x", "cmd": "y"}]) is False
    monkeypatch.setattr(st, "replace_retry", lambda t, f: shutil.move(t, f))
    assert st._save_cmd_lib([{"name": "x", "cmd": "y"}]) is True
