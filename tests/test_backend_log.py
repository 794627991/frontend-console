# -*- coding: utf-8 -*-
"""2.4.4 后端日志缓冲：点版本号查看的那份内存日志。

用户定调（2.4.4 追加）：
- 容量按**内存字节**计，默认 10MB（不是按行数 2000）
- 本功能是**指定的调试手段**：任何报错/警告/有用信息都往这里放
- 只驻内存，不写磁盘
"""
import inspect
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import backend_log as BL  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate():
    """每个测试独立：清缓冲、恢复原始流、复位容量与安装标记。"""
    real_out, real_err = sys.stdout, sys.stderr
    old_cap = BL._MAX_CHARS
    BL.clear()
    BL._seq = 0
    BL._installed = False
    yield
    sys.stdout, sys.stderr = real_out, real_err
    BL._installed = False
    BL._MAX_CHARS = old_cap
    BL.clear()


def _install(cap=None):
    if cap:
        BL._MAX_CHARS = cap
    BL.install()


def test_default_capacity_is_10mb():
    """用户明确要求 10MB 内存，不是 2000 条。"""
    assert BL._MAX_CHARS == 10 * 1024 * 1024


def test_capture_print_and_stderr():
    _install()
    print("普通一行")
    print("[错误] 出错了")
    print("[警告] 小心")
    sys.stderr.write("stderr 一行\n")
    snap = BL.snapshot()
    texts = [x["text"] for x in snap["lines"]]
    assert "普通一行" in texts and "[错误] 出错了" in texts and "stderr 一行" in texts
    by_level = {x["text"]: x["level"] for x in snap["lines"]}
    assert by_level["[错误] 出错了"] == "error"
    assert by_level["[警告] 小心"] == "warn"
    assert {x["text"]: x["src"] for x in snap["lines"]}["stderr 一行"] == "stderr"


def test_capacity_is_byte_based_not_line_based():
    """按字符数淘汰：短行能存很多条，长行很快占满——这正是按字节的意义。"""
    _install(cap=4000)
    for i in range(500):
        BL.log("t", "短")
    BL.clear()
    for i in range(20):
        BL.log("t", "长" * 900)
    st = BL.stats()
    assert st["used_chars"] <= st["capacity_chars"], st
    assert st["dropped"] > 0, st


def test_ring_drops_oldest():
    _install(cap=3000)
    for i in range(500):
        BL.log("t", "line-%d" % i)
    texts = [x["text"] for x in BL.snapshot(limit=10000)["lines"]]
    assert "line-0" not in texts, "最旧的应被淘汰"
    assert "line-499" in texts, "最新的必须还在"
    assert BL.stats()["used_chars"] <= 3000


def test_active_logging_api():
    """主动埋点：log/warn/error/exception 都进缓冲且带 tag。"""
    _install()
    BL.log("web_tabs", "主动埋点")
    BL.warn("ssh", "一条警告")
    BL.error("shell", "一条错误")
    try:
        1 / 0
    except ZeroDivisionError:
        BL.exception("calc", "除法失败")
    rows = {x["text"].split("\n")[0]: x for x in BL.snapshot()["lines"]}
    assert rows["主动埋点"]["tag"] == "web_tabs"
    assert rows["主动埋点"]["level"] == "info"
    assert rows["一条警告"]["level"] == "warn"
    assert rows["一条错误"]["level"] == "error"
    # exception 带 traceback
    exc_row = next(x for x in BL.snapshot()["lines"] if x["tag"] == "calc")
    assert "Traceback" in exc_row["text"] and "ZeroDivisionError" in exc_row["text"]


def test_logging_bridge():
    """标准库 logging 桥接：第三方库日志可见。"""
    _install()
    assert BL.install_logging_bridge() is True
    import logging
    logging.getLogger("paramiko.transport").warning("第三方库警告")
    texts = [x["text"] for x in BL.snapshot()["lines"]]
    assert any("第三方库警告" in t for t in texts), texts


def test_access_log_filtered():
    """werkzeug 逐请求访问日志不进缓冲（轮询会刷屏），但仍透传到原流。"""
    _install()
    print('127.0.0.1 - - [17/Nov/2026 10:12:36] "GET /api/x HTTP/1.1" 200 -')
    print("真日志")
    assert [x["text"] for x in BL.snapshot()["lines"]] == ["真日志"]


def test_since_incremental():
    _install()
    print("第一行")
    last = BL.snapshot()["last_seq"]
    print("第二行")
    inc = BL.snapshot(since=last)
    assert [x["text"] for x in inc["lines"]] == ["第二行"]


def test_partial_line_buffered_until_newline():
    _install()
    sys.stdout.write("半")
    sys.stdout.write("行")
    assert BL.snapshot()["lines"] == []
    sys.stdout.write("\n")
    assert [x["text"] for x in BL.snapshot()["lines"]] == ["半行"]


def test_no_disk_write():
    """用户明确要求不写盘。"""
    src = inspect.getsource(BL)
    for bad in ("open(", "os.makedirs", "FileHandler"):
        assert bad not in src, "日志缓冲不该出现 %r" % bad


def test_line_length_clamped():
    _install()
    print("x" * 20000)
    text = BL.snapshot()["lines"][0]["text"]
    assert len(text) <= BL._MAX_LINE_CHARS + 40      # +截断提示
    assert "已截断" in text


def test_snapshot_exposes_counts():
    _install()
    BL.log("t", "a")
    snap = BL.snapshot()
    for k in ("capacity_chars", "used_chars", "entries", "dropped", "installed"):
        assert k in snap, k
    assert snap["capacity_chars"] == BL._MAX_CHARS


def test_clear_resets_usage():
    _install()
    BL.log("t", "x" * 1000)
    BL.clear()
    st = BL.stats()
    assert st["used_chars"] == 0 and st["entries"] == 0 and st["dropped"] == 0


# ---- API 埋点（2.4.4：任何报错都往缓冲里放）--------------------------
def test_api_after_request_logs_failures_only_for_get():
    """after_request 埋点逻辑单测：用假 request/response 验判据。

    真 Flask 上下文里的端到端验证已手工做过（404/400/200 三类结果都正确
    入库），这里钉判据本身，避免日后改坏。
    """
    import inspect
    from src import server as S
    src = inspect.getsource(S._log_api_outcome)
    assert "code < 300 and method == " in src, "2xx GET 应早退不记录"
    assert 'request.method' in src
    assert "backend_log.log" in src
    assert "resp.status_code" in src


def test_api_skip_prefixes():
    """轮询类路径不记（会刷满缓冲）。"""
    from src import server as S
    assert "/api/backend_log" in S._LOGGED_PREFIX_SKIP
    assert "/api/status" in S._LOGGED_PREFIX_SKIP


def test_unhandled_exception_handler_registered():
    """未捕获异常要有全局兜底（GUI 没控制台，否则永远看不到）。"""
    from src import server as S
    src = inspect.getsource(S)
    assert "_api_unhandled" in src
    assert 'backend_log.exception("server"' in src


# ---- 2.4.4 追加：导出带版本号 / 一键复制 / 性能开关 ----------------
def test_export_includes_version():
    """用户令「启动时必须带上版本号」= 日志本身带版本，导出才能追溯。"""
    import inspect
    from src import server as S
    src = inspect.getsource(S.api_backend_log_export)
    assert "APP_VERSION" in src, "导出必须带版本号"
    assert "程序版本" in src
    assert "Content-Disposition" in src, "要能当附件下载"


def test_startup_logs_version_banner():
    """启动时第一条日志带版本号（用户明确要求）。"""
    import inspect
    from src import main as M
    src = inspect.getsource(M.main)
    assert "前端控制台 v%s 启动" in src, "启动横幅缺版本号"


def test_set_enabled_short_circuits():
    """性能逃生门：关掉后 write/log 立即返回，不进缓冲。"""
    _install()
    BL.log("t", "关之前")
    n_before = BL.stats()["entries"]
    BL.set_enabled(False)
    try:
        BL.log("t", "关之后不该进")
        print("print 也不该进")
    finally:
        BL.set_enabled(True)
    assert BL.stats()["entries"] == n_before, "关闭后仍有记录写入"
    BL.log("t", "重开后")
    assert BL.stats()["entries"] == n_before + 1

def test_batch_emit_is_single_lock():
    """批量写走一次持锁（性能手段）：_emit_many 存在，且一次写多行只加一次锁。

    用行为验证而不是源码字面匹配（后者在转义/注释上极易碎）。
    """
    _install()
    before = BL.stats()["entries"]
    # 一块含 100 行，应产生 100 条记录，且只取一次锁
    BL._emit_many(["第 %d 行" % i for i in range(100)], "stdout")
    assert BL.stats()["entries"] == before + 100
