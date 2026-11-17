# -*- coding: utf-8 -*-
"""2.4.4 后端日志缓冲：点版本号查看的那份内存日志。

用户需求要点（钉在测试里）：
- 只驻内存，不写磁盘
- 有限容量（环形，超出丢最旧）
- 接管 print / stderr，原来的输出都能在界面上看到
- werkzeug 逐请求访问日志不进缓冲（否则轮询刷屏淹没真日志）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import backend_log as BL  # noqa: E402


def _reset():
    """每个测试独立：清缓冲并摘掉已安装的接管。"""
    BL.clear()
    BL._seq = 0


def test_capture_print_and_stderr():
    _reset()
    real_out, real_err = sys.stdout, sys.stderr
    BL._installed = False
    try:
        BL.install()
        print("普通一行")
        print("[错误] 出错了")
        print("[警告] 小心")
        sys.stderr.write("stderr 一行\n")
    finally:
        sys.stdout, sys.stderr = real_out, real_err
        BL._installed = False
    snap = BL.snapshot()
    texts = [x["text"] for x in snap["lines"]]
    assert "普通一行" in texts
    assert "[错误] 出错了" in texts
    assert "stderr 一行" in texts
    by_level = {x["text"]: x["level"] for x in snap["lines"]}
    assert by_level["[错误] 出错了"] == "error"
    assert by_level["[警告] 小心"] == "warn"
    assert by_level["普通一行"] == "info"
    srcs = {x["text"]: x["src"] for x in snap["lines"]}
    assert srcs["stderr 一行"] == "stderr"


def test_ring_drops_oldest():
    """定长环形：超出容量丢最旧，内存不会无限增长。"""
    _reset()
    real = sys.stdout
    BL._installed = False
    try:
        BL.install(max_lines=5)
        for i in range(12):
            print("line-%d" % i)
    finally:
        sys.stdout = real
        BL._installed = False
    texts = [x["text"] for x in BL.snapshot()["lines"]]
    assert len(texts) == 5, texts
    assert texts == ["line-7", "line-8", "line-9", "line-10", "line-11"], texts


def test_access_log_filtered():
    """werkzeug 逐请求日志不进缓冲（轮询会刷屏），但仍透传到原流。"""
    _reset()
    real = sys.stdout
    BL._installed = False
    try:
        BL.install()
        print('127.0.0.1 - - [17/Nov/2026 10:12:36] "GET /api/x HTTP/1.1" 200 -')
        print("真日志")
    finally:
        sys.stdout = real
        BL._installed = False
    texts = [x["text"] for x in BL.snapshot()["lines"]]
    assert texts == ["真日志"], texts


def test_since_incremental():
    """since 增量拉取：只返回 seq 更大的行。"""
    _reset()
    real = sys.stdout
    BL._installed = False
    try:
        BL.install()
        print("第一行")
    finally:
        sys.stdout = real
        BL._installed = False
    first = BL.snapshot(since=0)
    assert len(first["lines"]) == 1
    last = first["last_seq"]
    real = sys.stdout
    BL._installed = False
    try:
        BL.install()
        print("第二行")
    finally:
        sys.stdout = real
        BL._installed = False
    inc = BL.snapshot(since=last)
    assert [x["text"] for x in inc["lines"]] == ["第二行"]


def test_partial_line_buffered_until_newline():
    """没有换行的残片不该作为半行入缓冲。"""
    _reset()
    real = sys.stdout
    BL._installed = False
    try:
        BL.install()
        sys.stdout.write("半")
        sys.stdout.write("行")
        assert BL.snapshot()["lines"] == []
        sys.stdout.write("\n")
    finally:
        sys.stdout = real
        BL._installed = False
    assert [x["text"] for x in BL.snapshot()["lines"]] == ["半行"]


def test_no_disk_write():
    """用户明确要求不写盘：模块不存在任何文件写入。"""
    import inspect
    src = inspect.getsource(BL)
    for bad in ("open(", "os.makedirs", "logging.FileHandler"):
        assert bad not in src, "日志缓冲不该出现 %r" % bad


def test_line_length_clamped():
    """单行超长要钳位，防一条巨型输出吃掉整个缓冲。"""
    _reset()
    real = sys.stdout
    BL._installed = False
    try:
        BL.install()
        print("x" * 10000)
    finally:
        sys.stdout = real
        BL._installed = False
    assert len(BL.snapshot()["lines"][0]["text"]) == 4000
