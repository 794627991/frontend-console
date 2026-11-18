# -*- coding: utf-8 -*-
"""2.4.4 后端日志缓冲：点版本号查看的那份内存日志。

用户定调（2.4.4 追加）：
- 容量按**内存字节**计，默认 10MB（不是按行数 2000）
- 本功能是**指定的调试手段**：任何报错/警告/有用信息都往这里放
- 只驻内存，不写磁盘
"""
import inspect
import io
import os
import re
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
    # 正文拼装已抽到 _backend_log_export_text（导出/保存共用）
    src = inspect.getsource(S._backend_log_export_text)
    assert "APP_VERSION" in src, "导出必须带版本号"
    assert "程序版本" in src
    exp = inspect.getsource(S.api_backend_log_export)
    assert "Content-Disposition" in exp, "要能当附件下载"
    assert "_backend_log_export_text" in exp


def test_export_save_writes_file():
    """WebView2 里浏览器下载走不通，导出改走后端落盘——必须真的写出文件。"""
    import os
    from src import server as S
    BL.install()
    BL.clear()
    BL.log("probe", "保存接口探针")
    j = S.app.test_client().post("/api/backend_log/save").get_json()
    assert j and j["ok"], j
    path = j["path"]
    try:
        txt = open(path, encoding="utf-8").read()
        assert "保存接口探针" in txt
        assert "程序版本" in txt
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


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

def test_batch_emit_is_single_lock(monkeypatch):
    """批量写走一次持锁（性能手段，a623R 审计 #4 真身化）。

    原测试只断言 entries == before+100——**逐行加锁的实现同样 +100**，
    测了个空心。现在用计数代理锁数 `with _lock` 的进入次数：100 行一批
    必须恰好 1 次持锁；逐行加锁的实现会数出 100 → 红。"""
    _install()
    real_lock = BL._lock

    class _CountingLock:
        def __init__(self, inner):
            self._inner = inner
            self.count = 0

        def __enter__(self):
            self.count += 1
            return self._inner.__enter__()

        def __exit__(self, *a):
            return self._inner.__exit__(*a)

        # 兼容裸 acquire/release 的调用方（如有）
        def acquire(self, *a):
            self.count += 1
            return self._inner.acquire(*a)

        def release(self):
            return self._inner.release()

    counting = _CountingLock(real_lock)
    monkeypatch.setattr(BL, "_lock", counting)
    before = BL.stats()["entries"]          # stats 也持锁——先取基线
    counting.count = 0                      # 基线取完清零，只数 emit 这一次
    BL._emit_many(["第 %d 行" % i for i in range(100)], "stdout")
    assert counting.count == 1, "100 行一批必须只持锁 1 次（数到 %d）" % counting.count
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


# ---- a616：审计点名的「只测自己会打的城门」补齐 ---------------------------
# 疯狗审计实测：CLI 旗标形态 `--password xxx` 与空格赋值 `password xxx`
# 整行穿透（分隔符类只有 [:=：＝]），而原 8 个参数化样例全落在实现已经
# 能挡的 key=value/Bearer 形态里。下面这组就是当时漏掉的形态。
@pytest.mark.parametrize("raw,secret", [
    ("--password hunter2 user=admin", "hunter2"),
    ("--token abc123456", "abc123456"),
    ("--api-key sk-1234567890", "sk-1234567890"),
    ("mysql -u root -p secret99 --database x", None),   # -p 紧凑形态：见下
    ("password mypass123", "mypass123"),
    ("passwd rootpass", "rootpass"),
    ("pwd abcdefgh", "abcdefgh"),
    ("secret shhhh123", "shhhh123"),
    ("api_key sk-live-abcdef", "sk-live-abcdef"),
    ("wget http://user:pw123456@host/x", "pw123456"),
])
def test_secrets_redacted_space_and_flag_forms(raw, secret):
    """空格/旗标分隔的凭据同样不能入库（审计实测原实现整行穿透）。"""
    if secret is None:
        pytest.skip("紧凑 -p 形态暂不覆盖（-p 与端口/路径歧义大）")
    out = BL._redact(raw)
    assert secret not in out, out
    assert "***" in out


# ---- a623R（对抗审计 #1 实锤穿透形态）-----------------------------------
# 疯狗审计拿真实模块实测 4 形态原样穿透：\b 在 client_secret 的下划线处
# 不成立（hiklink 真实凭据名就叫 app_secret！）；_URL_PASS_RE 要求用户名
# ≥1 字符漏掉 redis://:pass@；值含空格整行漏。修复后逐一回归。
@pytest.mark.parametrize("raw,secret", [
    ("client_secret=AbC123xyz99", "AbC123xyz99"),
    ("app_secret=wJK8sLm2NpQr", "wJK8sLm2NpQr"),
    ("redis://:Sup3rSecret@10.0.0.1:6379", "Sup3rSecret"),
    ("password abc 12345 leakme", "leakme"),
    ("SECRET_KEY=AbCdEf123456", "AbCdEf123456"),
    ("mysql://root:s3cr3t@localhost/db", "s3cr3t"),
    # a623R 复审（N2）：key 以数字/点序号结尾——词尾保护曾整行漏
    ("token2=AbCdEf123456", "AbCdEf123456"),
    ("password1=hunter2pass", "hunter2pass"),
    ("secret.1=AbCdEf123456", "AbCdEf123456"),
    ("password.1=Sup3rSecret", "Sup3rSecret"),
    # a623R 第三轮（R1）：小写复合字段——最高频真实凭据命名，
    # `=` 在场即赋值，前后缀任意放行（creds.token.1 属顺带修的历史缺口）
    ("secret_key=AbCdEf123456", "AbCdEf123456"),
    ("access_key_id=AKIAIOSFODNN7123", "AKIAIOSFODNN7123"),
    ("api_key_id=AKIAIOSFODNN7123", "AKIAIOSFODNN7123"),
    ("password_hash=s3cr3tvalue", "s3cr3tvalue"),
    ("token_value=AbCdEf123456", "AbCdEf123456"),
    ("secret_name=AbCdEf123456", "AbCdEf123456"),
    ("secret-key=AbCdEf123456", "AbCdEf123456"),
    ("creds.token.1=eyJhbGciOi", "eyJhbGciOi"),
    ("auth.token=x9x9x9x9x9", "x9x9x9x9x9"),
])
def test_secrets_redacted_audit_bypass_forms(raw, secret):
    """审计实锤的穿透形态：修复后必须脱敏，绝不能原样可导出。"""
    out = BL._redact(raw)
    assert secret not in out, out
    assert "***" in out


# ---- a623R 复审：引号值形态 + 词尾保护（误伤面回归）----------------------
@pytest.mark.parametrize("raw,secret", [
    ('password "hunter2pass"', "hunter2pass"),
    ('--password "hunter2 pass"', "hunter2 pass"),
    ('token "eyJhbGciOiJIUzI1NiIsInR5"', "eyJhbGciOiJIUzI1NiIsInR5"),
])
def test_secrets_redacted_quoted_values(raw, secret):
    """带引号的空格/旗标形态（复审实锤：a623R 重写时丢了 a616 的引号值
    分支，基线能挡、改漏——回归钉死）。"""
    out = BL._redact(raw)
    assert secret not in out, out
    assert "***" in out


@pytest.mark.parametrize("raw", [
    'File "C:\\Python314\\Lib\\tokenize.py", line 342, in _tokenize',
    'File "...src\\token_ring.py" line 9',
    "MyPassword123456",
    "loaded /etc/password.txt backup",
    "token.json updated to v2",
    "token ok",
    # a623R 复审（N3）：关键词+_续写的标识符后接正常行文——曾误伤
    "token_ring reset done",
    "secret_id is ok",
    # a623R 第三轮（R2）：数字/大写续写 + 空格 + 正常行文——曾误伤
    "MyPassword123456 is wrong",
    "TOKEN12345 expired",
    "password123 is incorrect",
    "token123 is fine",
])
def test_redact_does_not_mangle_keyword_continuations(raw):
    """关键词被续写（tokenize/token_ring/token.json/MyPassword…）不是赋值，
    绝不能抹——traceback 路径被抹坏会直接劣化 a624 的 crash 可诊断性。"""
    assert BL._redact(raw) == raw


def test_space_form_single_token_keeps_trailing_fields():
    """首段 ≥6 时只抹单段（a616 行为）：--password hunter2 user=admin 的
    user=admin 字段必须保留——多分词只在首段 <6（旧实现整行漏）时启用。"""
    assert BL._redact("--password hunter2 user=admin") == "--password *** user=admin"


@pytest.mark.parametrize("raw", [
    "password 错误，请重试",         # 中文值不能抹（宁可漏抹不抹坏日志）
    "token 无效",
    "default config loaded",        # 见下方 _classify 用例
])
def test_space_form_does_not_over_redact(raw):
    """空格形态的值限定 ASCII 可见字符——正常中文日志不能被抹成星号。

    a623R 口径变更：`secret sauce is tasty` 这类「keyword + 多个英文短词」
    从本表移除——它与审计漏报样例 `password abc 12345 leakme` 结构同构，
    无法既堵漏又保留（语义不可分），按「绝不漏」定调选择抹（多分词上限
    4 段 + 总长 ≥6，见 _SECRET_SPACE_RE）。"""
    assert BL._redact(raw) == raw


@pytest.mark.parametrize("line,level", [
    ("default config loaded", "info"),      # 审计：default 曾撞 "ault" 判成 error
    ("Default window size applied", "info"),
    ("SegmentationFault at 0x0", "error"),  # 真异常词不能被误放过
    ("PageFault in mmap", "error"),
])
def test_classify_default_is_not_error(line, level):
    """审计：`endswith("fault")` 撞上 default，「仅错误」过滤器混进噪声。"""
    assert BL._classify(line) == level, BL._classify(line)


def test_redact_applies_to_captured_stdout():
    """脱敏必须作用在流接管路径上，不只是 log() 接口。"""
    _install()
    print("password=leaked123 登录失败")
    texts = [x["text"] for x in BL.snapshot()["lines"]]
    assert not any("leaked123" in t for t in texts), texts
    assert any("password=***" in t for t in texts), texts


# ---- a601 对抗审计：并发与状态机 --------------------------------------
def test_tee_stream_partial_is_thread_safe():
    """多线程共用一个 TeeStream 时不能缝合/丢行（sys.stdout 全进程单例）。"""
    import threading

    class _Sink:
        def write(self, s):
            pass

        def flush(self):
            pass

    BL.clear()
    BL._MAX_CHARS = 40 * 1024 * 1024
    tee = BL._TeeStream(_Sink(), "stdout")

    def worker(tid):
        for k in range(300):
            tee.write("T%d-%d" % (tid, k))
            tee.write("\n")

    old = sys.getswitchinterval()
    sys.setswitchinterval(2e-6)          # 放大竞态窗口
    try:
        ts = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
    finally:
        sys.setswitchinterval(old)
    tee.flush()
    recs = [x["text"] for x in BL.snapshot(since=0, limit=0)["lines"]]
    # 原生流同样会「合并」（两次 write 之间被切走），所以这里只断言
    # 「没有行被拆丢/重复」，合并行不算缺陷（与 sys.stdout 行为一致）。
    # 注意不能再写 `assert len(bad) <= len(recs)`——bad 是 recs 的子集，
    # 那条断言恒真，审计指出是噪音（会让人误以为合并行已被验证）。
    seen = set()
    for r in recs:
        seen.update(re.findall(r"T\d+-\d+", r))
    assert len(seen) == 8 * 300, "丢行: %d/2400" % len(seen)


def test_disabled_period_partial_not_leaked():
    """set_enabled(False) 期间的残片不能在重开后进缓冲（可能是敏感数据）。"""
    import io
    BL.clear()
    BL.set_enabled(True)
    tee = BL._TeeStream(io.StringIO(), "stdout")
    tee.write("HEAD-PARTIAL")
    BL.set_enabled(False)
    tee.write("SECRET-WHILE-OFF")
    BL.set_enabled(True)
    try:
        tee.write("-AFTER\n")
        tee.flush()
        texts = [x["text"] for x in BL.snapshot(since=0, limit=0)["lines"]]
        assert not any("WHILE-OFF" in t for t in texts), texts
    finally:
        BL.set_enabled(True)


def test_install_concurrent_single_layer():
    """并发 install 只能产生一层 TeeStream（双层会让每行记两份）。"""
    import threading
    real_out, real_err = sys.stdout, sys.stderr
    BL._installed = False
    try:
        bar = threading.Barrier(8)

        def go():
            bar.wait()
            BL.install()

        ts = [threading.Thread(target=go) for _ in range(8)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        depth, s = 0, sys.stdout
        while isinstance(s, BL._TeeStream):
            depth += 1
            s = s._orig
        assert depth == 1
    finally:
        sys.stdout, sys.stderr = real_out, real_err
        BL._installed = False


def test_bridge_install_concurrent_single_handler():
    """并发 install_logging_bridge 只能加一个 handler。"""
    import logging
    import threading
    root = logging.getLogger()
    BL._logging_bridge.uninstall()
    before = len(root.handlers)
    try:
        bar = threading.Barrier(8)

        def go():
            bar.wait()
            BL.install_logging_bridge()

        ts = [threading.Thread(target=go) for _ in range(8)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        assert len(root.handlers) - before == 1
    finally:
        BL._logging_bridge.uninstall()


def test_snapshot_since_zero_reports_truncation():
    """首屏截断必须如实告知，但**不能**置 truncated（那会让前端空转追赶）。

    首屏只返回尾部 N 条时，更早的行没返回（head_truncated=True）；last_seq
    已是最新，不存在「还有更新的行没拿完」（truncated 必须 False）。
    """
    BL.clear()
    BL._seq = 0
    for i in range(3000):
        BL.log("t", "行-%d" % i)
    s = BL.snapshot(since=0, limit=500)
    assert len(s["lines"]) == 500
    assert s["head_truncated"] is True
    assert s["truncated"] is False
    full = BL.snapshot(since=0, limit=0)
    assert len(full["lines"]) == 3000
    assert full["head_truncated"] is False
    assert full["truncated"] is False


def test_ts_never_goes_backwards():
    """_ts 缓存只允许前进。

    审计指出原版是**零检出能力**的测试：串行 5 次 sleep(0.3) 的
    `assert seq == sorted(seq)` 对「永久返回同一值」甚至「永久返回空串」
    都恒真，而 a601 修的恰是**并发**写回旧值导致的回退。改为：
      ① 多线程并发调用，按时间顺序检查不回退（并发才是缺陷场景）
      ② 显式断言时间戳确实随时间推进（否则冻结实现也能过）
    """
    import threading
    import time

    BL._ts_cache = ("", 0.0)
    out = []
    lock = threading.Lock()

    def worker():
        for _ in range(200):
            v = BL._ts()
            with lock:
                out.append((time.time(), v))

    ts = [threading.Thread(target=worker) for _ in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    out.sort(key=lambda x: x[0])
    values = [v for _, v in out]
    assert values == sorted(values), "并发下时间戳出现回退"
    # 必须真的推进：跨过一个秒边界后值要变
    first = BL._ts()
    BL._ts_cache = ("", 0.0)
    time.sleep(1.05)
    second = BL._ts()
    assert second > first, "时间戳被冻结（%r -> %r）" % (first, second)


# ---- a601 对抗审计：HTTP/API 层 ---------------------------------------
def test_bad_limit_does_not_reset_since():
    """limit 传错不能把合法 since 一起重置（否则游标跳最新、中间段永久丢失）。"""
    from src.server import app
    BL.install()
    BL.clear()
    BL._seq = 0
    for i in range(3000):
        BL.log("t", "A%05d" % i)
    base = BL.snapshot(since=0, limit=1)["last_seq"]
    for i in range(1000):
        BL.log("y", "Y%05d" % i)
    j = app.test_client().get(
        "/api/backend_log?since=%d&limit=abc" % base).get_json()
    assert j["lines"][0]["text"] == "Y00000"      # since 未被重置
    assert j["truncated"] is True


def test_skip_prefix_uses_path_boundary():
    """`/api/statusx` 不属于 `/api/status`；跳过前缀内失败的请求必须记。"""
    from flask import Response
    from src.server import app as A, _log_api_outcome
    BL.install()

    def _probe(path, code):
        BL.clear()
        with A.test_request_context(path, method="GET"):
            _log_api_outcome(Response("", status=code))
        return len(BL.snapshot(since=0, limit=0)["lines"])

    assert _probe("/api/statusx", 404) == 1      # 不是 status 族
    assert _probe("/api/status", 200) == 0       # 成功轮询不记
    assert _probe("/api/status", 500) == 1       # 失败必须记
    assert _probe("/api/backend_log/save", 500) == 1


def test_redirects_and_head_options_not_logged():
    """3xx / HEAD / OPTIONS 是正常控制流，不能刷 warn。"""
    from flask import Response
    from src.server import app as A, _log_api_outcome
    BL.install()
    BL.clear()
    for code in (301, 302, 304, 307, 308):
        with A.test_request_context("/api/x", method="GET"):
            _log_api_outcome(Response("", status=code))
    for m in ("HEAD", "OPTIONS"):
        with A.test_request_context("/api/x", method=m):
            _log_api_outcome(Response("", status=200))
    assert len(BL.snapshot(since=0, limit=0)["lines"]) == 0


def test_export_escapes_control_chars():
    """导出的日志是发给同事的证据——控制字符可伪造行/清屏，必须转义。"""
    from src.server import _backend_log_export_text
    BL.install()
    BL.clear()
    BL.log("x", "AAA\rFAKE 2026-01-01 [INF] 伪造行")
    BL.log("x", "ESC \x1b[2J")
    BL.log("x", "NUL \x00 inside")
    txt = _backend_log_export_text()
    assert "\r" not in txt
    assert "\x1b" not in txt
    assert "\x00" not in txt
    # 转义后的可见字面（两个字符：反斜杠 + x）
    assert "\\x0d" in txt and "\\x1b" in txt and "\\x00" in txt


def test_export_filename_sanitized():
    """版本号含中文/特殊字符时，文件名不能带非法字符。"""
    from src.server import _safe_filename
    assert _safe_filename("backend-log-v2.4.4-x.txt") == "backend-log-v2.4.4-x.txt"
    out = _safe_filename("backend-log-v2.4.4 测试版-x.txt")
    assert not any(c in out for c in r'\/:*?"<>|')
    assert " " not in out


def test_save_concurrent_unique_paths():
    """并发导出不能互相覆盖（原来 TOCTOU 导致 8 个请求只落 4 个文件）。"""
    import os
    import threading
    from src.server import app as A
    import src.main as M
    BL.install()
    BL.clear()
    BL.log("x", "并发保存探针")
    orig = getattr(M, "_save_file_dialog", None)
    M._save_file_dialog = lambda fn: ""          # 强制走桌面目录分支
    paths = []
    lock = threading.Lock()
    try:
        def go():
            j = A.test_client().post("/api/backend_log/save").get_json()
            with lock:
                paths.append(j["path"])
        ts = [threading.Thread(target=go) for _ in range(6)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
    finally:
        if orig is not None:
            M._save_file_dialog = orig
        for p in paths:
            try:
                os.remove(p)
            except OSError:
                pass
    assert len(paths) == 6
    assert len(set(paths)) == 6, paths


def test_snapshot_reports_gap_when_cursor_behind_buffer():
    """游标落后到缓冲起点之前时，必须报告缺口（否则以为追平）。"""
    BL.clear()
    BL._seq = 0
    BL._MAX_CHARS = 3000
    try:
        for i in range(2001):
            BL.log("b", "B%05d" % i)
        j = BL.snapshot(since=10, limit=0)
        assert j["lost"] > 0, j
    finally:
        BL._MAX_CHARS = 10 * 1024 * 1024


# ---- a601 对抗审计：边界与资源 ---------------------------------------
@pytest.mark.parametrize("raw", [
    "PASSWORD=hunter2", "PaSsWoRd=hunter2", "TOKEN=abc123def", "SECRET=s",
    "COOKIE: a=b", "PASSWD=p", "API_KEY=k", "apiKey=sk-live-9999",
    '{"password":"hunter2"}', '{"password": "hunter2"}',
    "Bearer eyJhbGciOiJIUzI1NiJ9.x", "Basic dXNlcjpwYXNz",
    "using token eyJhbGciOiJIUzI1NiJ9.x",
    "postgresql://u:hunter2@host/db",
    "密码为 mypass123", "password：hunter2", "password＝hunter2",
])
def test_secret_variants_redacted(raw):
    """全大写 / JSON / 裸令牌 / 连接串 / 全角 / 「密码为」都必须脱敏。"""
    out = BL._redact(raw)
    for secret in ("hunter2", "abc123def", "sk-live-9999", "dXNlcjpwYXNz",
                   "mypass123", "eyJhbGciOiJIUzI1NiJ9"):
        assert secret not in out, (raw, out)
    assert "***" in out


def test_redact_keeps_context_after_chinese_value():
    """中文正文没有空格，不能把后半句一起吃掉。"""
    out = BL._redact("密码：123456，然后重试连接")
    assert "***" in out
    assert "然后重试连接" in out


def test_redact_is_line_by_line_for_multiline():
    """多行脱敏不能跨行吞掉 traceback 首行。"""
    import traceback
    try:
        1 / 0
    except ZeroDivisionError:
        tb = traceback.format_exc()
    out = BL._redact("token:\n" + tb)
    assert "Traceback" in out


def test_install_rejects_bool_capacity():
    """bool 是 int 子类：install(True) 曾把容量设成 1，缓冲永久失效。"""
    real_out, real_err = sys.stdout, sys.stderr
    old = BL._MAX_CHARS
    try:
        BL._installed = False
        BL.install(max_chars=True)
        assert BL._MAX_CHARS == old
    finally:
        sys.stdout, sys.stderr = real_out, real_err
        BL._installed = False


def test_uninstall_restores_streams():
    """install/uninstall 必须可逆（原来没有 uninstall，流被换掉就无法恢复）。"""
    real_out, real_err = sys.stdout, sys.stderr
    try:
        BL._installed = False
        BL.install()
        assert isinstance(sys.stdout, BL._TeeStream)
        BL.uninstall()
        assert not isinstance(sys.stdout, BL._TeeStream)
        assert BL._installed is False
        # 外部替换流后再 install 必须重新接管
        BL.install()
        sys.stdout = io.StringIO()
        BL.install()
        assert isinstance(sys.stdout, BL._TeeStream)
    finally:
        BL.uninstall()
        sys.stdout, sys.stderr = real_out, real_err
        BL._installed = False


def test_ipv6_access_log_filtered():
    """werkzeug 经 IPv6 回环访问时也必须过滤，否则轮询刷满缓冲。"""
    import io
    _install()
    BL.clear()
    sys.stdout.write('::1 - - [17/Nov/2026 10:12:36] "GET /api/x HTTP/1.1" 200 -\n')
    sys.stdout.write('[::1] - - [17/Nov/2026 10:12:36] "GET /api/y HTTP/1.1" 200 -\n')
    sys.stdout.flush()
    texts = [x["text"] for x in BL.snapshot(since=0, limit=0)["lines"]]
    assert not any("GET /api/x" in t for t in texts), texts


def test_carriage_return_progress_keeps_tail():
    """\r 刷新的进度条截断时保留最新状态，不是几秒前的旧值。"""
    import io
    _install()
    BL.clear()
    tee = BL._TeeStream(io.StringIO(), "stdout")
    for i in range(30000):
        tee.write("进度 %d%%\r" % i)
    tee.flush()
    lines = BL.snapshot(since=0, limit=0)["lines"]
    assert lines
    assert "29999" in lines[-1]["text"]


def test_snapshot_does_not_busy_catch_up_after_head():
    """首屏截断后不应触发追赶（last_seq 已在末尾，truncated 必须 False）。"""
    BL.install()
    BL.clear()
    BL._seq = 0
    for i in range(5000):
        BL.log("t", "行-%d" % i)
    s = BL.snapshot(since=0, limit=1000)
    assert s["head_truncated"] is True
    assert s["truncated"] is False
    # 用返回的 last_seq 续拉应为空
    assert BL.snapshot(since=s["last_seq"], limit=1000)["lines"] == []


def test_iter_entries_streams_all():
    """导出走流式迭代器：条数一致、顺序一致、不建 dict 列表。"""
    BL.clear()
    BL._seq = 0
    for i in range(5000):
        BL.log("t", "行-%d" % i)
    n = 0
    prev = 0
    for seq, ts, level, src, tag, text in BL.iter_entries(0):
        assert seq > prev
        prev = seq
        n += 1
    assert n == BL.stats()["entries"] == 5000


def test_entry_count_cap_bounds_memory():
    """条数硬上限：极短行场景下不能无限堆积（10MB 字符上限会把真实内存
    放大到上百 MB）。"""
    old = BL._MAX_ENTRIES
    try:
        BL.clear()
        BL._MAX_ENTRIES = 100
        BL._MAX_CHARS = 10 * 1024 * 1024
        for i in range(500):
            BL.log("t", "x")
        assert BL.stats()["entries"] == 100
        assert BL.stats()["dropped"] > 0     # 超出部分确实被淘汰
    finally:
        BL._MAX_ENTRIES = old


# ---- 曾经被「文档化」成缺口、a635 起必须真抹的形态 ------------------------
# a629 把这六条钉成了「有意不抹（基线同漏）」——审计实测：其中五条在更早的
# 实现上是抹掉的，变成了新引入的退化；第六条（引号紧贴）确实是这种情况。
# 把漏洞钉成预期行为，等于测试在替缺陷背书。现在改为断言必须抹掉。
@pytest.mark.parametrize("raw,secret", [
    ("password1 hunter2pass", "hunter2pass"),      # 尾缀 + 空格
    ("secret_key AbCdEf123456", "AbCdEf123456"),   # 小写复合 + 空格
    ("--password abc.def.ghi", "abc.def.ghi"),     # 值含点
    ("password ab_cd123 leakme", "ab_cd123"),      # 值含下划线
    ('password"hunter2pass"', "hunter2pass"),      # 引号紧贴 keyword
])
def test_redact_documents_gaps_now_fixed(raw, secret):
    out = BL._redact(raw)
    assert secret not in out, out
    assert "***" in out, out


# 唯一仍未覆盖的形态（点前缀把 keyword 变成扩展名，与路径形态不可区分）
def test_redact_dot_prefixed_keyword_still_gap():
    """`.token hunter2pass`：点前缀按文件名/扩展名处理——与 `token.json:4:`
    路径形态无法区分，保留为声明缺口。"""
    assert BL._redact(".token hunter2pass") == ".token hunter2pass"
