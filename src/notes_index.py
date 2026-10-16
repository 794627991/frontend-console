# -*- coding: utf-8 -*-
"""笔记库索引层（Blueprint /api/notes/*）：全局搜索/双链反链/标签聚合/导出 .md
的共享解析层。与 /api/ed/*（编辑器本体，12 路由）完全隔离——本模块只读扫描
files/，不碰任何编辑器写路径（红线：不影响现有功能）。

解析策略（designer 方案 v3.5.296）：按需扫描 + mtime/size 增量缓存（进程内），
不预建索引不落盘——个人笔记量级（几十~几百个 KB 级文件）冷全量 100-300ms 达标，
落盘索引换不来收益反引入失效/损坏/迁移三类问题。
"""

import json
import os
import re
import time

from flask import Blueprint, jsonify, request

from src.editor_files import FILES_DIR, _read_text

notes_bp = Blueprint("notes", __name__)

# 单文件纳入上限：超过则跳过（防御性——个人笔记远小于此，>5MB 多半是误存的数据）
_MAX_FILE = 5 * 1024 * 1024
# 搜索响应上限：50 文件 × 每文件 5 条命中（防千行 DOM，前端守流畅）
_MAX_FILES, _MAX_HITS_PER_FILE = 50, 5

# 进程内缓存：name -> {mtime, size, blocks, links, tags}（blocks=[{kind,text}]）
_CACHE = {}


# ==================== 解析层（共享内核） ====================

# 内联标签剥离（Editor.js 行内标记渲染态：<b>/<mark class=..>/<code class=../<a href=..>）
_INLINE_TAG_RE = re.compile(r"</?(?:b|mark|code|a)\b[^>]*>", re.I)
_ENTITIES = {"&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">",
             "&quot;": "\"", "&#39;": "'"}


def _strip_inline(s):
    """去内联 HTML 标签 + 反转义实体——搜索/反链/标签提纯用。"""
    if not s:
        return ""
    s = _INLINE_TAG_RE.sub("", str(s))
    for k, v in _ENTITIES.items():
        s = s.replace(k, v)
    return s


def _iter_list_items(items, out):
    """Editor.js list 嵌套树（items[i].content + items[i].items 递归）展平。"""
    for it in items or []:
        if not isinstance(it, dict):
            continue
        c = it.get("content")
        if c:
            out.append(_strip_inline(c))
        _iter_list_items(it.get("items"), out)


def _note_to_blocks(raw):
    """Editor.js JSON 文本 → [{kind, text}]（text 已提纯内联标签）。
    list 嵌套 items 递归展平为多行文本；table 展平 content 为 | 分隔行；
    code 标 kind='code'（双链/标签解析跳过它）。兼容 items/content 双形态
    （旧版数据形状差异，同 editor.js doEdSearch 的既有兜底口径）。
    data 非字典（用户手改坏文件）按空处理——单坏块不炸全链路。"""
    try:
        data = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except (ValueError, TypeError):
        return [{"kind": "paragraph", "text": str(raw or "")}]
    if not isinstance(data, dict):
        return [{"kind": "paragraph", "text": str(raw or "")}]
    blocks_out = []
    for b in (data.get("blocks") or []):
        if not isinstance(b, dict):
            continue
        t = b.get("type") or ""
        d = b.get("data")
        if not isinstance(d, dict):
            d = {}
        kind, texts = "paragraph", []
        if t in ("paragraph",):
            texts = [d.get("text") or ""]
        elif t in ("header",):
            kind = "header"
            texts = [d.get("text") or ""]
        elif t in ("list", "nestedList", "olUL"):
            kind = "list"
            # 双形态兜底：items 树 / content 串（旧版）
            if isinstance(d.get("items"), list):
                _iter_list_items(d["items"], texts)
            elif d.get("content"):
                texts = [d["content"]]
        elif t in ("checklist",):
            kind = "checklist"
            for it in (d.get("items") or []):
                if isinstance(it, dict) and it.get("text"):
                    texts.append(it["text"])
        elif t in ("quote",):
            kind = "quote"
            texts = [d.get("text") or ""]
            if d.get("caption"):
                texts.append(d["caption"])
        elif t in ("code", "codeTool"):
            kind = "code"
            texts = [d.get("code") or ""]
        elif t in ("table",):
            kind = "table"
            for row in (d.get("content") or []):
                if isinstance(row, list):
                    texts.append(" | ".join(_strip_inline(c) for c in row))
        elif t in ("image", "simpleImage"):
            kind = "image"
            texts = [(d.get("caption") or "") + " " + ((d.get("file") or {}).get("url") or "")]
        elif t in ("delimiter",):
            continue
        else:
            # 未知块：尽力取 text 字段（导出降级同口径）
            texts = [d.get("text") or ""]
        for x in texts:
            blocks_out.append({"kind": kind, "text": _strip_inline(x)})
    return blocks_out


# 双链：[[目标]]——目标名禁 [ ] 换行，限 120 字（与文件名上限同量级）
_WIKI_RE = re.compile(r"\[\[([^\[\]\n]{1,120})\]\]")

# 标签：#词。前/后边界=串首或空白/中英常用标点；三条排除：首字符非数字
# （杀 issue #123）、纯 hex 3/6 位（杀颜色码 #fff/#aabbcc）、井号后空格天然
# 不命中（# 标题）。代价：纯 hex 拼写的英文标签（#add/#bed/#facade）收不到，
# 文档如实注明。code 块内不解析（调用方过滤 kind）。
_TAG_EDGE = r"[\s，。、；：！？（）【】《》「」「」\"'`~,;:!?\.\(\)\[\]\{\}<>\-—/|*=+&%$@~^]"
_TAG_RE = re.compile(
    "(^|" + _TAG_EDGE + r")#([^\W\d_][^\W_]{0,39}?)(?=$|" + _TAG_EDGE + ")")


def _extract_links(blocks):
    """[[双链]] 提取（去重保序）。code 块跳过——代码里的 [[ 不算链接。"""
    seen, out = set(), []
    for b in blocks:
        if b.get("kind") == "code":
            continue
        for m in _WIKI_RE.finditer(b.get("text") or ""):
            t = m.group(1).strip()
            if t and t not in seen:
                seen.add(t)
                out.append(t)
    return out


def _extract_tags(blocks):
    """#标签 提取（去重保序）。code 块跳过；hex/数字开头由正则排除。"""
    seen, out = set(), []
    for b in blocks:
        if b.get("kind") == "code":
            continue
        for m in _TAG_RE.finditer(b.get("text") or ""):
            t = m.group(2).lower()
            if len(t) in (3, 6) and re.fullmatch(r"[0-9a-fA-F]+", t):
                continue   # 颜色码（正则只挡了首字符数字，全 hex 字母还要再挡）
            if t not in seen:
                seen.add(t)
                out.append(t)
    return out


def _scan(force=False):
    """按需全量扫描 files/ → 增量刷新缓存。返回 (缓存dict, 跳过的大文件数)。
    排除：images/ 子目录、*.tmp（保存原子替换的中间态，搜出半截内容=事故）、
    >5MB 大文件。mtime+size 双比对，没变不重读。"""
    skipped = 0
    if not os.path.isdir(FILES_DIR):
        return {}, 0
    seen = set()
    for fn in os.listdir(FILES_DIR):
        p = os.path.join(FILES_DIR, fn)
        if not os.path.isfile(p):
            continue                     # images/ 等子目录跳过
        if fn.endswith(".tmp"):
            continue                     # 保存原子替换中间态
        seen.add(fn)
        try:
            st = os.stat(p)
        except OSError:
            continue
        mtime, size = st.st_mtime, st.st_size
        old = _CACHE.get(fn)
        if old and not force and old["mtime"] == mtime and old["size"] == size:
            continue                     # 未变：沿用缓存（500 文件 stat 只花几 ms）
        if size > _MAX_FILE:
            skipped += 1
            continue
        text, err, _enc = _read_text(p, max_bytes=_MAX_FILE)
        if err:
            continue
        try:
            if fn.lower().endswith(".note"):
                blocks = _note_to_blocks(text)
            else:
                blocks = [{"kind": "line", "text": ln}
                          for ln in text.split("\n")]
            _CACHE[fn] = {
                "mtime": mtime, "size": size, "blocks": blocks,
                "links": _extract_links(blocks), "tags": _extract_tags(blocks),
            }
        except Exception:
            # 全审 S2：单个结构损坏的文件（JSON 合法但字段类型错）不得瘫痪
            # 搜索/反链/标签/导出四功能——坏文件跳过，其余照常入库
            continue
    for gone in [k for k in _CACHE if k not in seen]:
        _CACHE.pop(gone, None)           # 已删除的文件清出缓存
    # 浅拷贝快照：路由侧迭代快照键，并发 _scan 改活 dict 不再炸
    # 「dictionary changed size during iteration」（全审 G1，threaded=True）
    return dict(_CACHE), skipped


# ==================== 路由 ====================

def _compile_query(q, regex, case):
    """搜索词编译：正则可选（默认尝试正则、非法降级字面量——与编辑器内搜索
    同语法），case 关闭时 re.I。返回 (compiled|None, is_regex)。"""
    flags = 0 if case else re.I
    if regex:
        try:
            return re.compile(q, flags), True
        except re.error:
            pass
    try:
        return re.compile(re.escape(q), flags), False
    except re.error:
        return None, False


def _snippet(text, marks_abs, width=200):
    """命中行截窗：行 >width 时取首个命中前后窗，marks 坐标同步平移。
    返回 (snippet, marks_rel)。前缀「…」占 1 字符，marks 随之 +1（全审 L1）。"""
    if len(text) <= width:
        return text, marks_abs
    first = marks_abs[0][0] if marks_abs else 0
    lo = max(0, first - 60)
    hi = min(len(text), lo + width)
    if hi - lo < width:
        lo = max(0, hi - width)
    pre = "…" if lo > 0 else ""
    off = len(pre)
    rel = [[max(0, s - lo + off), min(len(text) - lo + off, e - lo + off)]
           for s, e in marks_abs]
    return pre + text[lo:hi] + ("…" if hi < len(text) else ""), rel


def _resolve_target(target):
    """双链目标解析：①全名精确存在 → ②裸名按 .note>.md>.txt 补后缀取首个
    存在者 → ③None（未解析，前端给「新建」入口）。"""
    t = (target or "").strip()
    if not t:
        return None
    p = os.path.join(FILES_DIR, t)
    if os.path.isfile(p):
        return t
    for ext in (".note", ".md", ".txt"):
        cand = t if t.lower().endswith(ext) else t + ext
        if os.path.isfile(os.path.join(FILES_DIR, cand)):
            return cand
    return None


@notes_bp.route("/api/notes/backlinks")
def notes_backlinks():
    """双链关系：?name=文件名 → {ok, incoming:[{from,count,snippet,at_line}],
    outgoing:[{target,resolved,count}], tags:[...]}。
    incoming=谁引用了我（扫全库 links，code 块已排除）；outgoing=我引用了谁
    （resolved=None 表示目标不存在，前端给新建入口）。at_line=首个引用的
    块序/行号（跳转锚点）。外部拖入文件不参与图谱（不可枚举+路径迁移断链）。"""
    name = (request.args.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "err": "缺少 name"}), 400
    cache, _skipped = _scan()
    me = cache.get(name)
    if me is None:
        # 未入库（新建草稿/超大文件/外部文件）：不报错，返回空图谱
        return jsonify({"ok": True, "incoming": [], "outgoing": [],
                        "tags": [], "external": name not in cache})
    incoming = []
    for fn, d in cache.items():
        if fn == name:
            continue
        cnt, at_line, snip = 0, None, ""
        for ln, b in enumerate(d["blocks"], 1):
            hits = _WIKI_RE.findall(b.get("text") or "") if b.get("kind") != "code" else []
            hit_me = [h for h in hits if h.strip() == name or
                      _resolve_target(h.strip()) == name]
            if hit_me:
                cnt += len(hit_me)
                if at_line is None:
                    at_line = ln
                    snip = (b.get("text") or "")[:160]
        if cnt:
            incoming.append({"from": fn, "count": cnt, "snippet": snip,
                             "at_line": at_line})
    incoming.sort(key=lambda x: -x["count"])
    seen, outgoing = set(), []
    for t in me["links"]:
        if t in seen:
            continue
        seen.add(t)
        resolved = _resolve_target(t)
        cnt = sum(1 for x in me["links"] if x == t)
        outgoing.append({"target": t, "resolved": resolved, "count": cnt})
    return jsonify({"ok": True, "incoming": incoming, "outgoing": outgoing,
                    "tags": me["tags"]})


@notes_bp.route("/api/notes/tags")
def notes_tags():
    """标签聚合：{ok, tags: [{tag, count, files: [name..]}]}（count 降序）。
    count=该标签的文件数（非出现次数——聚合视图按文件算直觉）。"""
    cache, _skipped = _scan()
    agg = {}
    for fn, d in cache.items():
        for t in d["tags"]:
            e = agg.setdefault(t, {"tag": t, "count": 0, "files": []})
            e["count"] += 1
            e["files"].append(fn)
    tags = sorted(agg.values(), key=lambda x: (-x["count"], x["tag"]))
    return jsonify({"ok": True, "tags": tags})


# ==================== 导出 .md ====================

_MD_ENT = {"&nbsp;": " ", "&amp;": "&amp;", "&lt;": "<", "&gt;": ">",
           "&quot;": "\"", "&#39;": "'"}


def _md_inline(s):
    """Editor.js 行内 HTML → Markdown 内联：<b>→**x**、<mark>→==x==（Obsidian
    高亮语法）、<code>→`x`、<a href>→[t](href)；实体反转义（&amp; 保留转义——
    md 里裸 & 合法但转义更稳， Obsidian/VSCode 都接受）。"""
    s = str(s or "")
    s = re.sub(r"<b>(.*?)</b>", r"**\1**", s, flags=re.I | re.S)
    s = re.sub(r"<mark[^>]*>(.*?)</mark>", r"==\1==", s, flags=re.I | re.S)
    s = re.sub(r"<code[^>]*>(.*?)</code>", r"`\1`", s, flags=re.I | re.S)
    s = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', r"[\2](\1)", s,
               flags=re.I | re.S)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    for k, v in _MD_ENT.items():
        s = s.replace(k, v)
    return s


def _md_table_cell(s):
    """表格单元格：| 转义、内联换行转 <br>（GFM 单元格禁裸换行）。"""
    return _md_inline(s).replace("|", "\\|").replace("\n", "<br>")


def _md_list_walk(items, ordered, depth, start_num, out):
    """list 嵌套树递归：unordered '- ' / ordered 序号（首层从 meta.start 起，
    嵌套层重置 1——md 有序列表嵌套编号各层独立）；每深一层缩进 4 空格。"""
    n = start_num
    for it in items or []:
        if not isinstance(it, dict):
            continue
        indent = "    " * depth
        marker = (str(n) + ". ") if ordered else "- "
        out.append(indent + marker + _md_inline(it.get("content") or ""))
        if ordered:
            n += 1
        sub = it.get("items")
        if isinstance(sub, list) and sub:
            _md_list_walk(sub, ordered, depth + 1, 1, out)


def _blocks_to_md(blocks):
    """Editor.js blocks（原始 data，含内联 HTML）→ Markdown 文本。
    映射表见 designer 方案 v3.5.299（vendor 实测形状）。[[双链]]/#tag 原样
    保留（Obsidian 原生兼容——导出的核心收益）。
    全审 S3：畸形字段（level 非 int/meta 非字典/table 行全非 list）逐处防御，
    坏块降级不炸导出。"""
    if isinstance(blocks, dict):
        blocks = blocks.get("blocks")   # 全审 F1：前端传 OutputData 包装对象 {blocks,time,version}
    out = []
    for b in blocks or []:
        if not isinstance(b, dict):
            continue
        t = b.get("type") or ""
        d = b.get("data")
        if not isinstance(d, dict):
            d = {}
        if t == "paragraph":
            out += ["", _md_inline(d.get("text") or "")]
        elif t == "header":
            try:
                lvl = max(1, min(3, int(d.get("level") or 2)))
            except (TypeError, ValueError):
                lvl = 2
            out += ["", "#" * lvl + " " + _md_inline(d.get("text") or "")]
        elif t in ("list", "nestedList", "olUL"):
            lines = []
            ordered = (d.get("style") == "ordered")
            start = 1
            meta = d.get("meta")
            if isinstance(meta, dict):
                try:
                    start = int(meta.get("start") or 1)
                except (TypeError, ValueError):
                    start = 1
            _md_list_walk(d.get("items"), ordered, 0, start, lines)
            if lines:
                out += [""]
            out += lines
        elif t == "checklist":
            out += [""]
            for it in (d.get("items") or []):
                if isinstance(it, dict):
                    mark = "x" if it.get("checked") else " "
                    out.append("- [" + mark + "] " + _md_inline(it.get("text") or ""))
        elif t == "quote":
            txt = _md_inline(d.get("text") or "")
            cap = _md_inline(d.get("caption") or "")
            lines = ["> " + x for x in txt.split("\n")] or [">"]
            if cap:
                lines.append("> — " + cap)
            out += [""] + lines   # alignment 丢弃（md 无语义）
        elif t in ("code", "codeTool"):
            code = d.get("code") or ""
            fence = "~~~~" if "```" in code else "```"
            out += ["", fence, code, fence]
        elif t == "table":
            rows = d.get("content") or []
            list_rows = [r for r in rows if isinstance(r, list)]
            if list_rows:
                width = max(len(r) for r in list_rows)
                out += [""]
                r0 = rows[0] if isinstance(rows[0], list) else []
                head = [_md_table_cell(r0[i]) if i < len(r0) else ""
                        for i in range(width)]
                out.append("| " + " | ".join(head) + " |")
                if d.get("withHeadings"):
                    out.append("|" + "|".join([" --- "] * width) + "|")
                else:
                    # GFM 结构必需表头分隔行：无表头语义时输出空表头占位
                    out.append("|" + "|".join(["   "] * width) + "|")
                    out.append("|" + "|".join([" --- "] * width) + "|")
                for r in list_rows[(1 if d.get("withHeadings") else 0):]:
                    cells = [_md_table_cell(r[i]) if i < len(r) else ""
                             for i in range(width)]
                    out.append("| " + " | ".join(cells) + " |")
        elif t in ("image", "simpleImage"):
            url = ((d.get("file") or {}).get("url")) or ""
            # 库内图片绝对路由 → 相对路径（files/ 当 Obsidian vault 时图片可见）
            url = url.replace("/api/ed/img/", "images/") if url.startswith("/api/ed/img/") else url
            cap = _md_inline(d.get("caption") or "")
            out += ["", "![" + cap + "](" + url + ")"]
        elif t == "delimiter":
            out += ["", "---"]
        else:
            txt = _md_inline(d.get("text") or "")
            out += ["", txt, "<!-- 导出降级：块类型 " + (t or "?") + " -->"]
    md = "\n".join(out)
    # 收敛空行（≥3 连空 → 1 空行）+ 首尾整洁
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip() + "\n"


@notes_bp.route("/api/notes/export_md", methods=["POST"])
def notes_export_md():
    """导出 .note → 同目录同名 .md（files/ 平铺 + images/ = 天然 Obsidian vault，
    图片相对路径不断链——designer 方案决策 5）。入参 {name, blocks?, overwrite?}：
    blocks 传前端当前内容（脏内容所见即所得）；不传则读盘。同名 .md 已存在且未
    overwrite → 409。原子写（tmp+replace，同 /api/ed/save 口径）。"""
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    overwrite = bool(data.get("overwrite"))
    src = _safe_path_notes(name)
    if not src:
        return jsonify({"ok": False, "err": "非法文件名"}), 400
    blocks = data.get("blocks")
    if blocks is None:
        raw, err, _enc = _read_text(src)
        if err:
            return jsonify({"ok": False, "err": err}), 400
        try:
            blocks = (json.loads(raw) or {}).get("blocks") or []
        except (ValueError, TypeError):
            return jsonify({"ok": False, "err": "笔记 JSON 解析失败"}), 400
    md = _blocks_to_md(blocks)
    out_name = os.path.splitext(name)[0] + ".md"
    out = _safe_path_notes(out_name)
    if not out:
        return jsonify({"ok": False, "err": "导出文件名非法"}), 400
    if os.path.exists(out) and not overwrite:
        return jsonify({"ok": False, "err": "已存在 " + out_name,
                        "exists": True}), 409
    try:
        tmp = out + ".tmp"
        try:
            # newline=""：禁 Windows 换行翻译，与 /api/ed/save 落盘口径一致（全审 L3）
            with open(tmp, "w", encoding="utf-8", newline="") as f:
                f.write(md)
            os.replace(tmp, out)
        except OSError:
            if os.path.exists(tmp):
                try: os.remove(tmp)   # 全审 L3：失败不留 .tmp 残骸
                except OSError: pass
            raise
    except OSError as e:
        return jsonify({"ok": False, "err": "写入失败: %s" % e}), 500
    return jsonify({"ok": True, "name": out_name})


def _safe_path_notes(name):
    """files/ 内路径校验（同 editor_files._safe_path 口径——不直接 import 其
    私有函数，防上游签名变化牵连）。"""
    if not re.match(r'^[^\\/:*?"<>|\x00-\x1f]{1,120}$', name or ""):
        return None
    p = os.path.normpath(os.path.join(FILES_DIR, name))
    if not os.path.realpath(p).startswith(os.path.realpath(FILES_DIR) + os.sep):
        return None
    return p


@notes_bp.route("/api/notes/search", methods=["POST"])
def notes_search():
    """全局全文搜索。入参 {q, regex?, case?, tag?}：
    - q：搜索词（tag 模式下忽略，走标签过滤=等价于「标签→文件」）
    - regex：按正则解释（默认尝试，非法降级字面量）
    - case：区分大小写（默认不区分）
    - tag：只搜打了该标签的文件（#tag 聚合的搜索入口）
    返回 {ok, took_ms, total_hits, truncated, skipped_big,
          files: [{name, mtime, hits: [{line, kind, snippet, marks}]}]}。
    .note 的 line=块序（1-based，与 editor.js edJumpToHit 块跳转约定对齐）；
    .txt/.md 的 line=物理行号。"""
    t0 = time.time()
    data = request.get_json(force=True, silent=True) or {}
    q = str(data.get("q") or "").strip()
    tag = str(data.get("tag") or "").strip().lower()
    if not q and not tag:
        return jsonify({"ok": False, "err": "搜索词为空"}), 400
    cache, skipped = _scan()
    rx, _is_re = (None, False)
    if q:
        rx, _is_re = _compile_query(q, bool(data.get("regex")), bool(data.get("case")))
        if rx is None:
            return jsonify({"ok": False, "err": "无效的搜索表达式"}), 400
    files_out, total, truncated = [], 0, False
    for fn in sorted(cache.keys()):
        if tag and tag not in cache[fn]["tags"]:
            continue
        hits = []
        for ln, b in enumerate(cache[fn]["blocks"], 1):
            text = b.get("text") or ""
            if not text:
                continue
            marks = [m.span() for m in rx.finditer(text)] if rx else []
            if q and not marks:
                continue
            if len(hits) >= _MAX_HITS_PER_FILE:
                truncated = True
                break
            sn, rel = _snippet(text, marks)
            hits.append({"line": ln, "kind": b.get("kind") or "",
                         "snippet": sn, "marks": rel})
            total += 1
        if hits:
            files_out.append({"name": fn, "mtime": cache[fn]["mtime"], "hits": hits})
            if len(files_out) >= _MAX_FILES:
                truncated = True
                break
    return jsonify({"ok": True, "took_ms": int((time.time() - t0) * 1000),
                    "total_hits": total, "truncated": truncated,
                    "skipped_big": skipped, "files": files_out})
