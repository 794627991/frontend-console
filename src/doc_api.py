# -*- coding: utf-8 -*-
"""`/api/doc/*` 蓝图（设计文档 6.4.1）。

路由分组：

    给 MCP 工具用的（内部）：open / show / search / read / view
    给前端回传用的：        report_open / report_show / report_view
    给前端轮询用的：        stat

**返回文本的格式照抄 4.2.7**（ZCode 的 describeSnapshot / describeDocument /
read_document / search_document）——缩进两位乘 level-1、锚点与 label 之间
两个空格、`[more: …]` 续读提示。模型对格式敏感，别自己发明写法。
"""

import os
import re

from flask import Blueprint, jsonify, request

from src import doc_store as st
from src.doc_anchor import (KIND_DOCX, KIND_PPTX, KIND_PDF, KIND_XLSX, KIND_IMAGE,
                            HINTS, format_locator, parse_locator, parse_anchor,
                            kind_of_path, format_cell)

bp = Blueprint("doc_api", __name__)

# 24KiB 的读取预算（4.2.7 的 cursor 说明）
READ_BUDGET = 24 * 1024
MAX_OUTLINE_LINES = 60
SNIPPET_RADIUS = 60


def _err(code, msg, status=400):
    return jsonify({"ok": False, "code": code, "err": msg}), status


# ================================================================
# 给模型看的文本（4.2.7）
# ================================================================

_KIND_NAME = {
    KIND_DOCX: "Word document",
    KIND_PDF: "PDF document",
    KIND_XLSX: "Excel workbook",
    KIND_PPTX: "PowerPoint deck",
    KIND_IMAGE: "Image",
}

_LIST_TITLE = {
    KIND_XLSX: "Sheets",
    KIND_PPTX: "Slides",
    KIND_PDF: "Outline",
    KIND_DOCX: "Outline",
}

_LOC_HINT = {
    KIND_DOCX: "Locations: p:N (paragraph), p:N-M, t:N (table), t:N/rRcC (table cell).",
    KIND_PDF: "Locations: page:N, page:N-M.",
    KIND_PPTX: "Locations: slide:N, slide:N-M, slide:N/shape:M.",
    KIND_XLSX: "Locations: Sheet, Sheet!A1, Sheet!A1:D20 (quote names with spaces: 'Q3 data'!A1).",
    KIND_IMAGE: "No locations.",
}


def describe_document(path, doc):
    """文档摘要（4.2.7 的 describeDocument）。"""
    kind = doc.get("kind") or kind_of_path(path) or ""
    units = doc.get("units") or []
    blocks = len(units)
    kb = max(1, int(round((doc.get("bytes") or 0) / 1024.0)))
    rev = doc.get("revision") or ""
    name = _KIND_NAME.get(kind, "Document")
    lines = ["%s: %s, %d blocks, %d KiB, revision %s."
             % (path, name, blocks, kb, rev)]
    title = (doc.get("title") or "").strip()
    if title and title != os.path.basename(path):
        lines.append("Title: %s" % title)

    outline = doc.get("outline") or []
    if outline:
        lines.append("%s:" % _LIST_TITLE.get(kind, "Outline"))
        shown = outline[:MAX_OUTLINE_LINES]
        for item in shown:
            label = item.get("label") or ""
            at = item.get("at") or ""
            level = max(1, int(item.get("level") or 1))
            anchor = ("%s#%s" % (path, at)) if at else path
            lines.append("%s- %s  %s" % ("  " * (level - 1), anchor, label))
        if len(outline) > len(shown):
            lines.append("  … %d more" % (len(outline) - len(shown)))
    hint = _LOC_HINT.get(kind)
    if hint:
        lines.append(hint)
    return "\n".join(lines)


def describe_snapshot(path, at=None):
    """打开 / 定位后的头两行（4.2.7 的 describeSnapshot）。"""
    lines = ["Opened %s in the Documents panel." % path]
    if at:
        lines.append("Showing: %s#%s." % (path, at))
    return "\n".join(lines)


def _unit_prefix(u):
    at = u.get("at") or ""
    if at.startswith("p:"):
        return "[%s] " % at
    if at.startswith("t:"):
        return "[%s]\n" % at
    return "## %s\n" % at if at else ""


def render_read(path, kind, units, cursor, quote_at=None, revision=""):
    """read_document 的输出（4.2.7 的 read_document 段）。

    cursor 以**单元下标**计数、从 0 起；按 UTF-8 字节 24KiB 预算累加，
    单元之间两个换行连接。单个单元超预算时截断并加提示。
    """
    head = "%s%s" % (path, ("#" + quote_at) if quote_at else "")
    head_type = _KIND_NAME.get(kind, "Document")
    head_full = ("%s (%s, revision %s)" % (head, head_type, revision)) if revision \
        else ("%s (%s)" % (head, head_type))
    all_units = units or []
    if not all_units:
        return "%s\n\n(no text)\n\n[end]" % head_full, None

    start = max(0, min(int(cursor or 0), len(all_units)))
    parts, used, i = [], 0, start
    while i < len(all_units):
        u = all_units[i]
        text = u.get("text") or ""
        body = _unit_prefix(u) + text
        b = body.encode("utf-8", "replace")
        if used + len(b) > READ_BUDGET:
            if not parts:
                # 单个单元超预算：截断后交付，并提示读更窄的位置
                cut = b[:READ_BUDGET].decode("utf-8", "ignore")
                parts.append(cut + "\n[… truncated; read a narrower location to see the rest]")
                i += 1
            break
        parts.append(body)
        used += len(b) + 2
        i += 1

    # next = 下一个没读的下标。**已消费的单元不能再指回去**：末尾那个
    # 单元被截断时它的 i 已经 +1，i >= len 就是读完了——此时给 [end]，
    # 截断提示本身就写了「读更窄的位置」（否则 AI 会拿同一个 cursor 反复读
    # 同一屏，实测就是这么死循环的）。
    nxt = None if i >= len(all_units) else i
    lines = [head_full,
             "", "\n\n".join(parts) if parts else "(no text)", ""]
    if nxt is None:
        lines.append("[end]")
    else:
        # 4.2.7：cursor 是下一个没读的下标
        lines.append('[more: call read_document with anchor "%s" and cursor %d]'
                     % (_base_path(path), nxt))
    return "\n".join(lines), nxt


def _base_path(path):
    """把锚点里的 # 部分去掉，给 `[more: …]` 的 anchor 参数用。"""
    i = str(path).find("#")
    return str(path) if i < 0 else str(path)[:i]


def _snippet(text, pos, qlen):
    a = max(0, pos - SNIPPET_RADIUS)
    b = min(len(text), pos + qlen + SNIPPET_RADIUS)
    s = re.sub(r"\s+", " ", text[a:b]).strip()
    if a > 0:
        s = "…" + s
    if b < len(text):
        s = s + "…"
    return s


def search_units(path, units, query, limit=20):
    """search_document 的输出（4.2.7）。大小写不敏感，返回锚点加片段。"""
    q = (query or "").strip()
    if not q:
        return "No matches for \"\" in %s." % path
    ql = q.lower()
    hits = []
    for u in units or []:
        text = u.get("text") or ""
        low = text.lower()
        pos = low.find(ql)
        while pos >= 0 and len(hits) < limit:
            hits.append((u.get("at") or "", _snippet(text, pos, len(q))))
            pos = low.find(ql, pos + len(q))
            if len(hits) >= limit:
                break
        if len(hits) >= limit:
            break
    if not hits:
        return "No matches for \"%s\" in %s." % (q, path)
    lines = ["%d matches for \"%s\" in %s:" % (len(hits), q, path)]
    for at, snip in hits:
        anchor = ("%s#%s" % (path, at)) if at else path
        lines.append("- %s  %s" % (anchor, snip))
    return "\n".join(lines)


# ================================================================
# 内部：打开 / 定位
# ================================================================

def _open(path, at=""):
    """打开文档，返回 (normalized_path, kind, index_entry, err_response)。

    有缓存且 revision 未变 → 直接返回缓存（AC-3.9 的反面：没变就不折腾前端）。
    没有或已变 → 走前端打开流程让页面重新解析。
    """
    try:
        npath, kind = st.validate_path(path, request_base_dir())
    except st.DocError as e:
        return None, None, None, _err(e.code, e.msg)
    rev = st.revision_of(npath)
    entry = st.index_get(npath, rev)
    if entry:
        return npath, kind, entry, None

    # 让前端打开并解析
    r = st.wait_for("doc_open", {"path": npath, "kind": kind, "at": at}, st.WAIT_OPEN)
    if not r.get("ok"):
        return None, None, None, _err(r.get("code") or "timeout",
                                      r.get("err") or "文档面板没有响应", 504)
    doc = r.get("document") or {}
    units = doc.get("units") or []
    entry = st.index_store(npath, doc.get("revision") or rev, doc, units)
    return npath, kind, entry, None


def request_base_dir():
    """相对路径的基准目录。MCP 工具进程的 cwd 就是会话的项目目录。"""
    return os.getcwd()


# ================================================================
# 路由
# ================================================================

@bp.route("/api/doc/open", methods=["POST"])
def api_doc_open():
    """打开文档并返回大纲。body: {path, at?}"""
    data = request.get_json(force=True, silent=True) or {}
    path = (data.get("path") or "").strip()
    at = (data.get("at") or "").strip()

    # 锚点先校验（写错要明确报错，AC-3.5）
    if at:
        _, _, _, loc = parse_anchor(path + "#" + at)
        if loc is None:
            k = kind_of_path(path)
            return _err("invalid_anchor",
                        "无法识别位置“%s”。%s" % (at, HINTS.get(k, "")))

    npath, kind, entry, err = _open(path, at)
    if err:
        return err
    doc = entry.get("info") or {}
    doc["units"] = entry.get("units") or []
    doc.setdefault("revision", entry.get("revision"))
    text = describe_document(npath, doc)
    at2 = ""
    if at:
        loc = parse_locator(kind, at)
        at2 = format_locator(loc) if loc else ""
    text = describe_snapshot(npath, at2) + "\n\n" + text
    return jsonify({"ok": True, "path": npath, "kind": kind, "at": at2, "text": text})


@bp.route("/api/doc/show", methods=["POST"])
def api_doc_show():
    """定位并高亮。body: {targets: [{anchor, quote?}], note?, seq?}"""
    data = request.get_json(force=True, silent=True) or {}
    targets = data.get("targets") or []
    note = (data.get("note") or "").strip()
    seq = data.get("seq")

    if not targets:
        return _err("invalid_anchor", "至少要给一个定位目标")
    if len(targets) > 20:
        return _err("invalid_anchor", "定位目标最多 20 个（本次 %d 个）" % len(targets))

    parsed = []
    for t in targets:
        anchor = (t.get("anchor") or "").strip() if isinstance(t, dict) else ""
        quote = (t.get("quote") or "").strip() if isinstance(t, dict) else ""
        if not anchor:
            return _err("invalid_anchor", "定位目标里有空锚点")
        # 锚点可以只写位置（p:3），也可以带路径（a.docx#p:3）
        if "#" in anchor:
            k, p, at, loc = parse_anchor(anchor)
        else:
            p, at = "", anchor
            k, loc = None, None
        if not p:
            # 位置形态：文档取第一个 target 的 path 或视图里的
            p = (targets[0].get("path") if isinstance(targets[0], dict) else "") or \
                st.view_get().get("path") or ""
            k = kind_of_path(p)
            at = anchor
            loc = parse_locator(k, at) if k else None
        if loc is None:
            return _err("invalid_anchor",
                        "无法识别位置“%s”。%s" % (anchor, HINTS.get(k, "")))
        parsed.append({"path": p, "kind": k, "at": format_locator(loc),
                       "quote": quote[:500]})

    # 所有锚点必须在同一文档（4.1）
    paths = {os.path.normcase(x["path"]) for x in parsed if x["path"]}
    if len(paths) > 1:
        return _err("invalid_anchor", "所有定位目标必须在同一份文档里")

    path = parsed[0]["path"] or st.view_get().get("path") or ""
    try:
        npath, kind = st.validate_path(path, request_base_dir())
    except st.DocError as e:
        return _err(e.code, e.msg)

    r = st.wait_for("doc_show", {
        "path": npath, "kind": kind,
        "targets": [{"anchor": x["at"], "quote": x["quote"]} for x in parsed],
        "note": note, "seq": seq,
    }, st.WAIT_SHOW)
    if not r.get("ok"):
        return _err(r.get("code") or "timeout",
                    r.get("err") or "文档面板没有响应", 504)

    located = r.get("located") or []
    first = parsed[0]["at"]
    head = describe_snapshot(npath, first)
    if note:
        head += "\n\nNote shown in the panel: " + note
    miss = [x for x in located if not x.get("found")]
    if miss:
        head += "\n\nNot found: " + ", ".join(x.get("at") or "?" for x in miss)
    return jsonify({"ok": True, "path": npath, "kind": kind, "at": first,
                    "located": located, "text": head})


@bp.route("/api/doc/read", methods=["POST"])
def api_doc_read():
    """读一段文本。body: {anchor, cursor?}"""
    data = request.get_json(force=True, silent=True) or {}
    anchor = (data.get("anchor") or "").strip()
    cursor = data.get("cursor")
    if not anchor:
        return _err("invalid_path", "缺少 anchor 参数")

    k, path, at, loc = parse_anchor(anchor)
    if not path:
        # 只给位置时按当前视图的文档
        path = st.view_get().get("path") or ""
        at = anchor
        k = kind_of_path(path)
        loc = parse_locator(k, at) if k else None
    if not path:
        return _err("invalid_path", "无法确定要读哪份文档，请给出完整路径")
    if at and loc is None:
        return _err("invalid_anchor", "无法识别位置“%s”。%s" % (at, HINTS.get(k, "")))
    if cursor is not None:
        try:
            cursor = int(cursor)
        except (TypeError, ValueError):
            return _err("invalid_anchor", "cursor 必须是整数")

    npath, kind, entry, err = _open(path, at)
    if err:
        return err
    if not entry.get("text_ok", True):
        return _err("too_large", "文档过大，无法建立文本索引")

    text, nxt = render_read(npath, kind, entry.get("units") or [], cursor or 0,
                            format_locator(loc) if loc else None,
                            revision=entry.get("revision") or "")
    if at:
        st.view_set(npath, kind, format_locator(loc) if loc else at,
                    {"text": ""})
    return jsonify({"ok": True, "path": npath, "kind": kind,
                    "at": format_locator(loc) if loc else "", "next": nxt, "text": text})


@bp.route("/api/doc/search", methods=["POST"])
def api_doc_search():
    """在已解析的文档里搜。body: {path, query, limit?}"""
    data = request.get_json(force=True, silent=True) or {}
    path = (data.get("path") or "").strip()
    query = (data.get("query") or "").strip()
    try:
        limit = int(data.get("limit") or 20)
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(100, limit))

    if not query:
        return _err("invalid_path", "缺少 query 参数")
    if len(query) > 200:
        return _err("invalid_path", "查询词最多 200 字符")

    npath, kind, entry, err = _open(path)
    if err:
        return err
    if not entry.get("text_ok", True):
        return _err("too_large", "文档过大，无法建立文本索引")
    text = search_units(npath, entry.get("units") or [], query, limit)
    return jsonify({"ok": True, "path": npath, "kind": kind, "text": text})


@bp.route("/api/doc/view", methods=["GET"])
def api_doc_view():
    """取最近一次上报的视图状态。"""
    v = st.view_get()
    if not v.get("path"):
        return jsonify({"ok": True, "text": "No document is open in the Documents panel.",
                        "path": "", "kind": "", "at": "", "selection": {"text": ""}})
    text = "Viewer is showing %s" % v["path"]
    if v.get("at"):
        text += "#" + v["at"]
    text += "."
    sel = (v.get("selection") or {}).get("text") or ""
    if sel:
        text += "\n\nSelected text:\n" + sel
    return jsonify({"ok": True, "text": text, **v})


# ---------------- 前端回传 ----------------

@bp.route("/api/doc/report_open", methods=["POST"])
def api_doc_report_open():
    """前端解析完成后的回传（6.6）。

    两种调用形态：
      · 带 req_id —— 应答后端的 doc_open 等待（deliver 唤醒等待方）
      · req_id 为空串 —— **用户从胶囊「打开文件」手动开的文档**：没有人在等，
        只是把解析结果登记进索引，好让 AI 之后能直接 search / read 这份文档。
    """
    data = request.get_json(force=True, silent=True) or {}
    req_id = data.get("req_id") or ""
    doc = data.get("document") or {}
    path = doc.get("path") or ""
    if data.get("ok") and path:
        st.index_store(path, doc.get("revision") or st.revision_of(path), doc,
                       doc.get("units") or [])
        st.view_set(path, doc.get("kind") or "", "", {"text": ""})
    if not req_id:
        # 手动打开的登记：没有等待方，到此为止
        return jsonify({"ok": True})
    if not st.deliver(req_id, data):
        # 已超时被清理：前端忽略即可（6.4.3）
        return jsonify({"ok": False, "code": "gone", "err": "请求已超时"}), 404
    return jsonify({"ok": True})


@bp.route("/api/doc/report_show", methods=["POST"])
def api_doc_report_show():
    data = request.get_json(force=True, silent=True) or {}
    req_id = data.get("req_id") or ""
    if not req_id:
        return _err("invalid_path", "缺少 req_id")
    if not st.deliver(req_id, data):
        return jsonify({"ok": False, "code": "gone", "err": "请求已超时"}), 404
    return jsonify({"ok": True})


@bp.route("/api/doc/report_view", methods=["POST"])
def api_doc_report_view():
    """前端防抖上报（6.1.8 / 6.4.5）。"""
    data = request.get_json(force=True, silent=True) or {}
    st.view_set((data.get("path") or ""), (data.get("kind") or ""),
                (data.get("at") or ""), data.get("selection") or {})
    return jsonify({"ok": True})


@bp.route("/api/doc/stat", methods=["GET"])
def api_doc_stat():
    """给变更轮询用：{path}。返回 {ok, size, mtime, revision}。"""
    path = (request.args.get("path") or "").strip()
    if not path:
        return _err("invalid_path", "缺少 path 参数")
    try:
        s = os.stat(path)
    except OSError:
        return jsonify({"ok": False, "err": "文件不存在"}), 400
    return jsonify({"ok": True, "size": s.st_size, "mtime": s.st_mtime,
                    "revision": "%d:%d" % (s.st_size, int(round(s.st_mtime * 1000)))})
