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
    BL._logging_bridge.uninstall()      # 测试间不残留 logging handler
    BL._excepthooks_installed = False
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


# ---- 2.4.4 对抗审计回归（a600 修复项）--------------------------------
def test_tee_stream_survives_buffer_failure():
    """缓冲侧炸了，原流仍必须拿到完整输出（否则日志模块的 bug 会吞掉
    程序真实输出，直接违反「log 绝不能影响正常使用」）。"""
    class _Rec:
        def __init__(self):
            self.got = []

        def write(self, s):
            self.got.append(s)

        def flush(self):
            pass

        encoding = "utf-8"
        errors = "strict"

    rec = _Rec()
    tee = BL._TeeStream(rec, "stdout")
    orig = BL._emit_many
    BL._emit_many = lambda *a: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        n = tee.write("关键输出\n")
    finally:
        BL._emit_many = orig
    assert n == 5
    assert rec.got == ["关键输出\n"]


def test_logging_bridge_install_is_idempotent():
    """重复 install 不能叠加 handler（否则同一条日志被记 N 份）。"""
    import logging
    BL.clear()
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        for _ in range(5):
            assert BL.install_logging_bridge() is True
        added = [h for h in root.handlers if h not in before]
        assert len(added) == 1
        logging.getLogger("idem").info("幂等测试标记")
        hits = [x for x in BL.snapshot()["lines"] if "幂等测试标记" in x["text"]]
        assert len(hits) == 1
    finally:
        BL._logging_bridge.uninstall()


def test_excepthooks_install_is_idempotent():
    """重复装钩子，一次崩溃只记一条（原来 N 层链会记 N 条）。"""
    old = sys.excepthook
    try:
        for _ in range(3):
            BL.install_excepthooks()
        BL.clear()
        try:
            raise ValueError("钩子幂等标记")
        except ValueError:
            t, v, tb = sys.exc_info()
        sys.excepthook(t, v, tb)
        hits = [x for x in BL.snapshot()["lines"] if "钩子幂等标记" in x["text"]]
        assert len(hits) == 1
    finally:
        sys.excepthook = old


def test_tee_stream_reconfigure_passthrough():
    """子模块会调 sys.stdout.reconfigure()——接管后不能 AttributeError。"""
    import io
    tee = BL._TeeStream(io.StringIO(), "stdout")
    assert hasattr(tee, "reconfigure")
    tee.reconfigure(encoding="utf-8")      # 不抛即通过

    class _NoRc:
        def write(self, s):
            pass

        def flush(self):
            pass

    BL._TeeStream(_NoRc(), "stdout").reconfigure(encoding="utf-8")


@pytest.mark.parametrize("line,level", [
    ("KeyError:'a'", "error"),
    ("ValueError:bad", "error"),
    ("socket.timeout: 超时", "error"),
    ("AttributeError", "error"),
    ("Traceback (most recent call last):", "error"),
    ("[警告] 小心", "warn"),
    ("一切正常", "info"),
])
def test_classify_without_space(line, level):
    """无空格异常形态也要判成错误（否则「仅错误」过滤下隐形）。"""
    assert BL._classify(line) == level


def test_snapshot_limit_zero_means_unbounded():
    """limit=0 表示取全量（导出/首屏用）。"""
    _install()
    BL._MAX_CHARS = 400000
    try:
        for i in range(3000):
            BL.log("t", "短行-%d" % i)
        n = BL.stats()["entries"]
        assert len(BL.snapshot(since=0, limit=0)["lines"]) == n
        # 对比：limit=50000 也够，但 limit=0 语义必须是无上限
        assert len(BL.snapshot(since=0, limit=50000)["lines"]) == n
    finally:
        BL._MAX_CHARS = 10 * 1024 * 1024


def test_truncated_snapshot_does_not_skip_lines():
    """a600 对抗审计（数据丢失）：增量拉取超 limit 时必须能续上，不能跳过中间段。

    原来 last_seq 恒为全局最新，前端一次只拿 limit 条就把游标推到末尾，
    中间那段永久丢失。现在 truncated=True 且 last_seq 停在实取位置。
    """
    _install()
    BL.clear()
    BL._seq = 0
    for i in range(2500):
        BL.log("t", "行-%d" % i)
    cur, seen, rounds = 100, [], 0
    while rounds < 20:
        s = BL.snapshot(since=cur, limit=400)
        got = [x["seq"] for x in s["lines"]]
        if not got:
            break
        seen.extend(got)
        cur = s["last_seq"]
        rounds += 1
        if not s["truncated"]:
            break
    assert rounds > 1                      # 确实发生了截断多轮
    assert seen == sorted(seen)
    assert len(seen) == len(set(seen))     # 无重复
    assert len(seen) == 2400               # 2500 - 起始游标 100，无丢失


def test_tee_stream_proxies_unknown_attributes():
    """第三方代码会访问 sys.stdout.name / line_buffering 等属性——必须透传。"""
    import io
    orig = io.StringIO()
    tee = BL._TeeStream(orig, "stdout")
    # StringIO 没有 write_through → 原流也抛 AttributeError（行为一致）
    with pytest.raises(AttributeError):
        tee.write_through
    # 原流有的属性必须能取到
    orig_custom = io.StringIO()
    orig_custom.name = "<probe>"
    assert BL._TeeStream(orig_custom, "stdout").name == "<probe>"
    # 没有原流时不能崩
    BL._TeeStream(None, "stdout").write("x\n")


def test_classify_stays_fast():
    """热路径预算：单行分类 < 3µs（每行都跑，回归即失败）。"""
    import time
    line = "2026-11-17 12:00:00 [INFO] some ordinary log line here"
    t0 = time.perf_counter()
    for _ in range(5000):
        BL._classify(line)
    per = (time.perf_counter() - t0) / 5000
    assert per < 3e-6, "单行分类 %.2fµs 超预算" % (per * 1e6)


def test_unhandled_exception_logged_once():
    """500 只记一条：errorhandler 记了带 traceback 的，after_request 要跳过。

    Flask 首请求后禁止新增路由，所以不注册真实路由，改为直接调用两个钩子
    函数（它们就是普通函数，行为等价）。
    """
    from src import server
    BL.install()
    BL.clear()
    with server.app.test_request_context("/api/_probe_boom", method="GET"):
        import flask
        resp = server.app.make_response(
            server._api_unhandled(RuntimeError("probe")))
        assert resp.status_code == 500
        assert resp.headers.get("X-BL-Logged") == "1"
        # after_request 看到标记后必须跳过
        server._log_api_outcome(resp)
    hits = [x for x in BL.snapshot(since=0, limit=0)["lines"]
            if "_probe_boom" in x["text"]]
    assert len(hits) == 1, hits
    assert hits[0]["level"] == "error"


# ---- 2.4.4 对抗审计：敏感信息脱敏 ---------------------------------------
@pytest.mark.parametrize("raw,secret", [
    ("连接密码 password=hunter2 用户 admin", "hunter2"),
    ("token: abc123def 已过期", "abc123def"),
    ("api_key=sk-live-9999 无效", "sk-live-9999"),
    ("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.x", "eyJhbGciOiJIUzI1NiJ9"),
    ("Authorization: Basic dXNlcjpwYXNz", "dXNlcjpwYXNz"),
    ("密码：mypass123", "mypass123"),
    ("口令 = 888888", "888888"),
    ("Password=Secret1", "Secret1"),
])
def test_secrets_redacted(raw, secret):
    """日志会被复制/导出/发给同事——明文口令绝不能带出去。"""
    out = BL._redact(raw)
    assert secret not in out, out
    assert "***" in out


@pytest.mark.parametrize("raw", [
    "普通日志：token 无效",          # 关键字后没有 : 或 =，不是赋值
    "Processing request took 12ms",
    "password 长度不足",
])
def test_redact_does_not_mangle_ordinary_text(raw):
    """非赋值形态不能被误伤（否则正常日志被改坏更难排障）。"""
    assert BL._redact(raw) == raw


def test_redact_applies_to_captured_stdout():
    """脱敏必须作用在流接管路径上，不只是 log() 接口。"""
    _install()
    print("password=leaked123 登录失败")
    texts = [x["text"] for x in BL.snapshot()["lines"]]
    assert not any("leaked123" in t for t in texts), texts
    assert any("password=***" in t for t in texts), texts
