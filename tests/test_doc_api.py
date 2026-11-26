# -*- coding: utf-8 -*-
"""doc_api / doc_store 的单测：路径校验、等待回传、索引缓存、文本格式。

不打真前端——用 monkeypatch 把 `doc_store.wait_for` 换成立即返回的桩，
证明后端这条链路（校验 → 等回传 → 建索引 → 出文本）本身是对的。
"""
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import doc_store as st          # noqa: E402
import src.doc_api as api                # noqa: E402
from src.doc_anchor import format_locator, parse_locator   # noqa: E402


@pytest.fixture(autouse=True)
def _clean():
    st.reset_all()
    yield
    st.reset_all()


@pytest.fixture
def client():
    from flask import Flask
    app = Flask(__name__)
    app.register_blueprint(api.bp)
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def docx_file(tmp_path):
    p = tmp_path / "报告.docx"
    p.write_bytes(b"PK\x03\x04" + b"x" * 200)
    return str(p)


# ---------------- 路径校验（6.4.2 五步） ----------------

def test_validate_rejects_empty():
    with pytest.raises(st.DocError) as e:
        st.validate_path("")
    assert e.value.code == "invalid_path"


def test_validate_rejects_reserved_device(tmp_path):
    # CON 等设备名会让 open/getsize 永久阻塞，必须挡在第一步
    with pytest.raises(st.DocError) as e:
        st.validate_path("CON")
    assert e.value.code == "invalid_path"


def test_validate_not_found(tmp_path):
    with pytest.raises(st.DocError) as e:
        st.validate_path(str(tmp_path / "没有这个.docx"))
    assert e.value.code == "not_found"


def test_validate_unsupported_type(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("x")
    with pytest.raises(st.DocError) as e:
        st.validate_path(str(p))
    assert e.value.code == "unsupported_type"
    assert ".txt" in e.value.msg


def test_validate_relative_to_base(tmp_path, docx_file):
    # 相对路径按 base_dir 补全
    npath, kind = st.validate_path("报告.docx", str(tmp_path))
    assert os.path.isabs(npath) and kind == "docx"
    assert os.path.normcase(npath) == os.path.normcase(docx_file)


def test_validate_accepts_all_kinds(tmp_path):
    for name, kind in [("a.docx", "docx"), ("a.pdf", "pdf"), ("a.xlsx", "xlsx"),
                       ("a.pptx", "pptx"), ("a.png", "image"), ("a.SVG", "image")]:
        p = tmp_path / name
        p.write_bytes(b"x")
        _, k = st.validate_path(str(p))
        assert k == kind, name


# ---------------- 等待回传（6.4.3） ----------------

def test_wait_for_delivers_and_clears(monkeypatch):
    """成功路径：deliver 唤醒等待方，_pending 里不留条目。"""
    monkeypatch.setattr("src.app_state._broadcast_to_ai",
                        lambda d: _deliver_later(d["req_id"], {"ok": True, "v": 7}))

    def _deliver_later(rid, res):
        threading.Timer(0.02, lambda: st.deliver(rid, res)).start()

    r = st.wait_for("doc_open", {"path": "x"}, 2.0)
    assert r.get("ok") is True and r.get("v") == 7
    assert st.pending_count() == 0


def test_wait_for_timeout_clears(monkeypatch):
    """超时：返回 timeout 码，且 _pending 不留条目（不泄漏）。"""
    monkeypatch.setattr("src.app_state._broadcast_to_ai", lambda d: None)
    t0 = time.time()
    r = st.wait_for("doc_open", {}, 0.1)
    assert r["code"] == "timeout"
    assert "文档面板没有响应" in r["err"]
    assert st.pending_count() == 0
    assert time.time() - t0 < 2.0


def test_deliver_unknown_req_id_returns_false():
    assert st.deliver("不存在的req", {"ok": True}) is False


def test_wait_for_envelope_kind_not_overridden_by_payload(monkeypatch):
    """回归：payload 里有 kind（文档类型 docx/pdf/…）时不能覆盖信封的 kind。

    实测事故：`d = {"kind": "ui_action", ...}; d.update(payload)` —— payload
    带 kind="docx"，信封变成 {"kind": "docx"}，前端 sense.js 按 kind 分发时
    整帧被丢弃。后端广播成功、AI 那边等满 15 秒超时，日志里毫无线索。
    """
    got = {}

    def fake_bcast(d):
        got.update(d)
        threading.Timer(0.01, lambda: st.deliver(d["req_id"], {"ok": True})).start()

    monkeypatch.setattr("src.app_state._broadcast_to_ai", fake_bcast)
    st.wait_for("doc_show", {"path": "a.docx", "kind": "docx", "targets": []}, 2.0)
    assert got["kind"] == "ui_action", "信封 kind 被子载荷覆盖了"
    assert got["action"] == "doc_show"
    assert got["req_id"]
    # 载荷自己的字段仍要在（后端要拿 path/targets）
    assert got["path"] == "a.docx"
    assert got["targets"] == []


def test_report_after_timeout_returns_404(client):
    """前端迟到回传：req_id 已清，返回 404（前端忽略）。"""
    r = client.post("/api/doc/report_open",
                    json={"req_id": "gone", "ok": True, "document": {"path": "x.docx"}})
    assert r.status_code == 404
    assert r.get_json()["code"] == "gone"


def test_report_with_empty_req_id_just_indexes(client, docx_file):
    """胶囊手动打开：req_id 为空，只登记索引，不找等待方。"""
    r = client.post("/api/doc/report_open", json={
        "req_id": "", "ok": True,
        "document": {"path": docx_file, "kind": "docx", "revision": "1:1",
                     "outline": [{"at": "p:1", "label": "标题", "level": 1}],
                     "units": [{"at": "p:1", "text": "标题"}]},
    })
    assert r.status_code == 200 and r.get_json()["ok"] is True
    assert st.index_count() == 1
    e = st.index_get(docx_file)
    assert e["units"][0]["at"] == "p:1"


# ---------------- 索引缓存（6.4.4） ----------------

def test_index_invalidated_by_revision(docx_file):
    st.index_store(docx_file, "100:1", {"kind": "docx"}, [{"at": "p:1", "text": "旧"}])
    assert st.index_get(docx_file, "100:1") is not None
    # revision 变了（文件被改）→ 缓存作废
    assert st.index_get(docx_file, "100:2") is None
    assert st.index_get(docx_file) is None     # 顺手已清掉


def test_index_evicts_oldest(tmp_path):
    paths = []
    for i in range(st.MAX_INDEX_DOCS + 4):
        p = tmp_path / ("f%d.docx" % i)
        p.write_bytes(b"x")
        paths.append(str(p))
        st.index_store(str(p), "1:1", {"kind": "docx"}, [])
        time.sleep(0.001)
    assert st.index_count() == st.MAX_INDEX_DOCS
    # 最早那批被淘汰
    assert st.index_get(paths[0]) is None
    assert st.index_get(paths[-1]) is not None


def test_index_drops_units_over_budget(tmp_path):
    p = tmp_path / "big.docx"
    p.write_bytes(b"x")
    huge = [{"at": "p:%d" % i, "text": "字" * 1000} for i in range(3000)]  # ≈9MB UTF-8
    e = st.index_store(str(p), "1:1", {"kind": "docx"}, huge)
    assert e["text_ok"] is False
    assert e["units"] == []


# ---------------- 文本格式（4.2.7） ----------------

def test_describe_document_shape():
    text = api.describe_document("D:\\a\\报告.docx", {
        "kind": "docx", "bytes": 36864, "revision": "36864:1732500000000",
        "outline": [{"at": "p:1", "label": "季度报告", "level": 1},
                    {"at": "p:3", "label": "收入", "level": 2}],
        "units": [{}, {}, {}],
    })
    lines = text.split("\n")
    assert lines[0] == ("D:\\a\\报告.docx: Word document, 3 blocks, 36 KiB, "
                        "revision 36864:1732500000000.")
    assert "Outline:" in lines
    # 缩进两位乘 level-1，锚点与 label 之间两个空格
    assert "- D:\\a\\报告.docx#p:1  季度报告" in lines
    assert "  - D:\\a\\报告.docx#p:3  收入" in lines
    assert lines[-1].startswith("Locations: p:N (paragraph)")


def test_describe_document_truncates_outline():
    outline = [{"at": "p:%d" % i, "label": "L%d" % i, "level": 1} for i in range(100)]
    text = api.describe_document("a.docx", {"kind": "docx", "outline": outline, "units": []})
    assert "… 40 more" in text


def test_describe_snapshot():
    assert api.describe_snapshot("a.docx") == "Opened a.docx in the Documents panel."
    assert api.describe_snapshot("a.docx", "p:4") == (
        "Opened a.docx in the Documents panel.\nShowing: a.docx#p:4.")


def test_render_read_pagination():
    units = [{"at": "p:%d" % i, "text": "段落%d " % i + "字" * 50} for i in range(1, 400)]
    text, nxt = api.render_read("a.docx", "docx", units, 0)
    assert text.startswith("a.docx (Word document)")   # 没有 revision 时不输出空字段
    assert "[p:1] 段落1" in text
    # 超预算 → 有续读提示，next 是下一个没读的下标
    assert nxt is not None and 0 < nxt < len(units)
    assert '[more: call read_document with anchor "a.docx" and cursor %d]' % nxt in text
    # 从 next 续读接着往下，最终能读到底（399 个单元约三次）
    seen = 0
    cur = nxt
    while cur is not None:
        t2, cur2 = api.render_read("a.docx", "docx", units, cur)
        if cur2 is None:
            assert t2.rstrip().endswith("[end]"), "读完那一屏必须有 [end]"
        cur = cur2
        seen += 1
        assert seen < 10, "续读陷入死循环"
    assert seen >= 1


def test_render_read_single_unit_over_budget():
    units = [{"at": "p:1", "text": "字" * 40000}]
    text, nxt = api.render_read("a.docx", "docx", units, 0)
    assert "[… truncated; read a narrower location to see the rest]" in text
    # 唯一一个单元被截断后已消费掉 → 没有下一个
    assert nxt is None


def test_render_read_empty():
    text, nxt = api.render_read("a.docx", "docx", [], 0)
    assert "(no text)" in text and text.rstrip().endswith("[end]")
    assert nxt is None


def test_render_read_utf16_safe_truncation():
    """代理对被切在预算边界时，输出仍是合法 UTF-8（Python 侧按 utf-8 切，天然安全）。"""
    units = [{"at": "p:1", "text": "😀" * 20000}]
    text, _ = api.render_read("a.docx", "docx", units, 0)
    text.encode("utf-8")   # 不抛 = 没有落单的代理项


def test_search_units():
    units = [{"at": "p:1", "text": "收入增长了百分之十二"},
             {"at": "p:2", "text": "其他内容"},
             {"at": "p:3", "text": "收入与利润"}]
    text = api.search_units("a.docx", units, "收入")
    assert text.startswith('2 matches for "收入" in a.docx:')
    assert "a.docx#p:1" in text and "a.docx#p:3" in text
    # 大小写不敏感
    units2 = [{"at": "p:1", "text": "Revenue GREW"}]
    assert '1 matches' in api.search_units("a.docx", units2, "revenue")
    # 没命中
    assert api.search_units("a.docx", units, "不存在") == 'No matches for "不存在" in a.docx.'


def test_search_snippet_truncation():
    units = [{"at": "p:1", "text": "前" * 200 + "命中" + "后" * 200}]
    text = api.search_units("a.docx", units, "命中")
    line = [l for l in text.split("\n") if l.startswith("- ")][0]
    assert line.startswith("- a.docx#p:1  …")
    assert line.endswith("…")


def test_search_limit():
    units = [{"at": "p:%d" % i, "text": "x hit"} for i in range(10)]
    text = api.search_units("a.docx", units, "hit", limit=3)
    assert text.startswith("3 matches")


# ---------------- 路由层 ----------------

def test_api_open_rejects_bad_anchor(client, docx_file):
    r = client.post("/api/doc/open", json={"path": docx_file, "at": "p:0"})
    assert r.status_code == 400
    j = r.get_json()
    assert j["code"] == "invalid_anchor"
    assert "Word 文档的锚点写法" in j["err"]


def test_api_open_rejects_unsupported(client, tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("x")
    r = client.post("/api/doc/open", json={"path": str(p)})
    assert r.status_code == 400
    assert r.get_json()["code"] == "unsupported_type"


def test_api_open_uses_cache_without_waiting(client, docx_file, monkeypatch):
    """索引已在且 revision 未变 → 不打前端、不等待（AC-3.9 的反面）。"""
    rev = st.revision_of(docx_file)
    st.index_store(docx_file, rev, {
        "path": docx_file, "kind": "docx", "bytes": 200, "revision": rev,
        "outline": [{"at": "p:1", "label": "标题", "level": 1}],
    }, [{"at": "p:1", "text": "标题"}])

    called = []
    monkeypatch.setattr(st, "wait_for", lambda *a, **k: called.append(1) or {"ok": False})
    r = client.post("/api/doc/open", json={"path": docx_file})
    assert r.status_code == 200
    j = r.get_json()
    assert j["ok"] is True
    assert not called, "缓存命中不该再等前端"
    assert "标题" in j["text"]


def test_api_open_waits_for_frontend(client, docx_file, monkeypatch):
    """索引未命中 → 等前端，回传后建索引并返回文本。"""
    rev = st.revision_of(docx_file)

    def fake_wait(action, payload, timeout):
        assert action == "doc_open"
        assert payload["path"].endswith("报告.docx")
        return {"ok": True, "document": {
            "path": docx_file, "kind": "docx", "bytes": 200, "revision": rev,
            "outline": [{"at": "p:1", "label": "季度报告", "level": 1}],
            "units": [{"at": "p:1", "text": "季度报告"}],
        }}
    monkeypatch.setattr(st, "wait_for", fake_wait)
    r = client.post("/api/doc/open", json={"path": docx_file})
    j = r.get_json()
    assert j["ok"] is True and j["kind"] == "docx"
    assert "季度报告" in j["text"]
    assert st.index_get(docx_file, rev) is not None


def test_api_open_timeout_returns_504(client, docx_file, monkeypatch):
    monkeypatch.setattr(st, "wait_for", lambda *a, **k: {
        "ok": False, "code": "timeout", "err": "文档面板没有响应。请确认 AI 会话页处于打开状态"})
    r = client.post("/api/doc/open", json={"path": docx_file})
    assert r.status_code == 504
    assert "文档面板没有响应" in r.get_json()["err"]


def test_api_show_rejects_too_many_targets(client, docx_file):
    r = client.post("/api/doc/show", json={"targets": [{"anchor": "p:1"}] * 21})
    assert r.status_code == 400
    assert "最多 20 个" in r.get_json()["err"]


def test_api_show_requires_targets(client):
    r = client.post("/api/doc/show", json={})
    assert r.status_code == 400


def test_api_read_requires_anchor(client):
    r = client.post("/api/doc/read", json={})
    assert r.status_code == 400
    assert "anchor" in r.get_json()["err"]


def test_api_view_empty(client):
    r = client.get("/api/doc/view")
    j = r.get_json()
    assert j["ok"] is True
    assert "No document is open" in j["text"]


def test_api_view_after_report(client):
    st.view_set("D:\\a\\报告.docx", "docx", "p:3", {"text": "选中的话"})
    j = client.get("/api/doc/view").get_json()
    assert "D:\\a\\报告.docx#p:3" in j["text"]
    assert "选中的话" in j["text"]


def test_api_report_view_updates(client):
    client.post("/api/doc/report_view", json={
        "path": "a.docx", "kind": "docx", "at": "p:9", "selection": {"text": "sel"}})
    v = st.view_get()
    assert v["path"] == "a.docx" and v["at"] == "p:9"
    assert v["selection"]["text"] == "sel"


def test_api_stat(client, docx_file):
    j = client.get("/api/doc/stat?path=" + docx_file).get_json()
    assert j["ok"] is True
    assert j["size"] == 204
    assert j["revision"].startswith("204:")
