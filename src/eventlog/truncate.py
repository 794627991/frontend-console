# -*- coding: utf-8 -*-
"""工具输出协议层截断（v3.0，对照 ZCode core.ts:64 + projection-rows.ts:160）。

终态工具输出按 UTF-8 字节数判断，超过 head+tail（各 32KB）取头尾、中间
以「\n…\n」标记，并附 `truncated: {total_bytes, ref}` 元数据——ref 是按需
拉取全文的稳定句柄（本会话 stash 的 LRU 键）。UI 永不收大块：此前 Read
大文件/巨量日志的原样透传会把 SSE 帧和前端渲染同时打爆。

字节切点可能落在多字节字符中间——两侧解码 errors="ignore"（ZCode 用
Buffer.toString 同样产生 U+FFFD，这里直接丢孤立尾字节更干净）。

只动 kind='event' 的 CLI tool_result 块；text/thinking 块不截（正文是
对话本体）。深拷贝仅发生在确有超限块时（探测先行，常态零拷贝）。
"""
import hashlib
from collections import OrderedDict

PROTOCOL_LIMITS = {
    "tool_output_head_bytes": 32 * 1024,
    "tool_output_tail_bytes": 32 * 1024,
    # stash：截断原文的暂存（按需拉取用），超限即 LRU 逐出——丢的只是
    # 「查看全文」能力，事件流本体无损
    "stash_max_entries": 32,
    "stash_max_bytes": 4 * 1024 * 1024,
}

_MARK = "\n…\n"


class ToolOutputStash(object):
    """截断原文暂存（每会话一只，LRU：条目数与总字节数双上限）。"""

    def __init__(self):
        self._data = OrderedDict()      # ref -> text
        self._bytes = 0

    def put(self, text):
        ref = hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()[:16]
        if ref in self._data:
            self._data.move_to_end(ref)
            return ref
        self._data[ref] = text
        self._bytes += len(text.encode("utf-8", "ignore"))
        self._trim()
        return ref

    def _trim(self):
        lim = PROTOCOL_LIMITS
        while self._data and (len(self._data) > lim["stash_max_entries"]
                              or self._bytes > lim["stash_max_bytes"]):
            _, evicted = self._data.popitem(last=False)
            self._bytes -= len(evicted.encode("utf-8", "ignore"))

    def get(self, ref):
        text = self._data.get(ref)
        if text is not None:
            self._data.move_to_end(ref)
        return text


def _block_text(b):
    """tool_result 块的文本量（str 或 [{type:text,text}] 列表两形态）。"""
    c = b.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "".join(x.get("text", "") for x in c
                       if isinstance(x, dict) and x.get("type") == "text")
    return ""


def _find_oversized(cli_event):
    """只读探测：CLI user 事件里 tool_result 块是否有超限者。"""
    lim = PROTOCOL_LIMITS
    threshold = lim["tool_output_head_bytes"] + lim["tool_output_tail_bytes"]
    if cli_event.get("type") != "user":
        return False
    content = ((cli_event.get("message") or {}).get("content"))
    if not isinstance(content, list):
        return False
    for b in content:
        if isinstance(b, dict) and b.get("type") == "tool_result":
            if len(_block_text(b).encode("utf-8", "ignore")) > threshold:
                return True
    return False


def truncate_tool_output(cli_event, stash):
    """入口：超限时返回截断版深拷贝，否则原样返回原对象（零拷贝）。"""
    if not _find_oversized(cli_event):
        return cli_event
    import copy
    ev = copy.deepcopy(cli_event)
    content = ((ev.get("message") or {}).get("content"))
    lim = PROTOCOL_LIMITS
    for b in content:
        if not (isinstance(b, dict) and b.get("type") == "tool_result"):
            continue
        text = _block_text(b)
        blob = text.encode("utf-8", "ignore")
        if len(blob) <= lim["tool_output_head_bytes"] + lim["tool_output_tail_bytes"]:
            continue
        head = blob[:lim["tool_output_head_bytes"]].decode("utf-8", "ignore")
        tail = blob[len(blob) - lim["tool_output_tail_bytes"]:].decode("utf-8", "ignore")
        ref = stash.put(text)
        b["content"] = head + _MARK + tail
        b["_truncated"] = {"total_bytes": len(blob), "ref": ref}
    return ev
