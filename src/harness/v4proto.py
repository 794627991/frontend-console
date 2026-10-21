# -*- coding: utf-8 -*-
"""v4 投影协议纯函数：行模型 + delta 封闭五操作 + apply + coalesce。

对照 ZCode packages/shared/src/zcode-protocol-v4/{rows,delta,apply,coalesce}.ts：

- 操作集封闭：row.appended / row.upserted / row.removed / row.delta /
  state.updated。没有中间插入、没有移动、没有字段级 patch——模型表达不了
  的结构变化一律由服务端发 snapshot resync，客户端没有猜结构的代码路径。
- 行规则：row 自包含（渲染任一行不需看别的行）；结构变化换整行
  （upserted）；文本增长只 append（row.delta）；turnId 是行上的标签不是容器。
- apply 与 coalesce 语义保持：apply(s, coalesce(ds)) 与 apply(s, ds) 逐字节
  一致（tests/v4_golden/golden.json 黄金夹具，Python 端与 JS 端
  web/js/harness/v4proto.js 双端必须同时跑绿——双端共享代码的替身）。

纯函数无 IO 无锁；snapshot 为可变 dict，apply 就地修改并返回同一引用
（服务端投影与前端 store 各自持有，互不共享实例）。
"""

ROW_KINDS = (
    "turn_header",     # 回合头（组）：state=running|success|error|cancelled
    "user_input",      # 用户消息行（文本/files/images 计数）
    "assistant_text",  # 助手正文行（可流式 append text）
    "reasoning",       # 思考行（可流式 append text，默认折叠滚播）
    "tool_call",       # 工具行：status 流转，终态带 output/endedAt/dur
    "subagent",        # 子代理行（主窗口唯一形态：无正文，childTopic 供下钻）
    "vision",          # 识图卡行（pending→done/error，结果定格卡内）
    "peer_notify",     # 协作回传通知行（单行摘要）
    "marker",          # 杂项分隔行：renew/sysnote/audit/exit/model_switch/interrupted
)

TOOL_STATUS = (
    "streaming_input", "running", "success", "error", "cancelled",
)

# row.delta 允许的流式路径（行内字符串追加；越界 no-op）
STREAM_PATHS = ("text", "inputText", "summary")


def new_snapshot(epoch=""):
    """空快照。state 为 A 区（键级浅合并），rows 为全量行（服务端持有；
    出 wire 时才截尾窗）。"""
    return {"seq": 0, "epoch": epoch, "state": {}, "rows": [], "total": 0}


def mk_row(row_id, turn_id, kind, at, at_seq, **fields):
    row = {"rowId": row_id, "turnId": turn_id, "kind": kind,
           "at": at, "atSeq": at_seq}
    row.update(fields)
    return row


def d_row_appended(row):
    return {"op": "row.appended", "row": row}


def d_row_upserted(row):
    return {"op": "row.upserted", "row": row}


def d_row_removed(from_row_id):
    """后缀截断：删除 rowId >= from_row_id 的全部行（rewind 用）。"""
    return {"op": "row.removed", "fromRowId": from_row_id}


def d_row_delta(row_id, path, append):
    return {"op": "row.delta", "rowId": row_id, "path": path, "append": append}


def d_state(patch):
    return {"op": "state.updated", "patch": patch}


# ---------------------------------------------------------------------------
# apply（协议规范实现；服务端投影推进与前端 store 共用同一语义）
# ---------------------------------------------------------------------------

def _apply_appended(snap, row):
    rid = row["rowId"]
    for r in snap["rows"]:
        if r["rowId"] == rid:
            return snap                     # 已存在：幂等 no-op
    snap["rows"].append(dict(row))          # 拷贝入账：不与 delta 输入共享引用
    snap["total"] += 1
    return snap


def _apply_upserted(snap, row):
    rid = row["rowId"]
    for i, r in enumerate(snap["rows"]):
        if r["rowId"] == rid:
            snap["rows"][i] = dict(row)     # 换整行（结构变化）
            return snap
    snap["rows"].append(dict(row))          # 未加载/新增：等价 appended
    snap["total"] += 1
    return snap


def _apply_removed(snap, from_row_id):
    keep = [r for r in snap["rows"] if r["rowId"] < from_row_id]
    removed = len(snap["rows"]) - len(keep)
    snap["rows"][:] = keep
    snap["total"] = max(0, snap["total"] - removed)
    return snap


def _apply_row_delta(snap, row_id, path, append):
    if path not in STREAM_PATHS or not append:
        return snap
    for r in snap["rows"]:
        if r["rowId"] == row_id:
            r[path] = (r.get(path) or "") + append
            break                           # 窗口外/未加载：no-op 不猜
    return snap


def _apply_state(snap, patch):
    snap["state"].update(patch)             # 键级整体替换，绝不深合并
    return snap


def apply_delta(snap, d):
    op = d.get("op")
    if op == "row.appended":
        return _apply_appended(snap, d["row"])
    if op == "row.upserted":
        return _apply_upserted(snap, d["row"])
    if op == "row.removed":
        return _apply_removed(snap, d["fromRowId"])
    if op == "row.delta":
        return _apply_row_delta(snap, d["rowId"], d["path"], d["append"])
    if op == "state.updated":
        return _apply_state(snap, d["patch"])
    return snap                             # 未知 op：no-op（协议封闭集外不猜）


def apply_deltas(snap, deltas):
    for d in deltas:
        apply_delta(snap, d)
    return snap


# ---------------------------------------------------------------------------
# coalesce（帧内 delta 合并；语义保持：apply(s, coalesce(ds)) ≡ apply(s, ds)）
# ---------------------------------------------------------------------------

def coalesce(deltas):
    out = []
    for d in deltas:
        op = d.get("op")
        if op == "row.delta":
            prev = out[-1] if out else None
            if (prev is not None and prev.get("op") == "row.delta"
                    and prev["rowId"] == d["rowId"] and prev["path"] == d["path"]):
                prev["append"] += d["append"]          # 相邻同 (rowId,path) 拼接
            else:
                out.append(dict(d))
        elif op == "state.updated":
            prev = out[-1] if out else None
            if prev is not None and prev.get("op") == "state.updated":
                prev["patch"].update(d["patch"])       # 相邻浅合并
            else:
                out.append({"op": "state.updated", "patch": dict(d["patch"])})
        elif op == "row.upserted":
            # 换整行吞掉更早的同 rowId 流式 delta（整行已含最新文本）
            rid = d["row"]["rowId"]
            out[:] = [x for x in out
                      if not (x.get("op") == "row.delta" and x["rowId"] == rid)]
            out.append(dict(d))
        elif op == "row.removed":
            # 后缀截断吞掉被截行的一切在途操作（屏障）
            frid = d["fromRowId"]
            out[:] = [x for x in out if not (
                (x.get("op") in ("row.delta",)
                 and x["rowId"] >= frid)
                or (x.get("op") in ("row.appended", "row.upserted")
                    and x["row"]["rowId"] >= frid))]
            out.append(dict(d))
        else:
            out.append(dict(d))
    return out


def wire_snapshot(snap, tail=0, tail_turns=0):
    """出线快照：A 区 + rows 尾窗（fromSeq 固定 0，客户端整体替换）。
    turnsTotal=全量 user 轮数（rows 被尾窗裁掉的历史轮数只能由服务端数，
    前端归档条「前 N 轮已归档」的真源——a24 实测尾窗重放数出「前 1 轮」）。

    tail_turns（a41）：按回合数裁窗——用户实测重启后「会话变短/导轨数量
    不对/归档条没了」三现象同源：行数窗装不下 V3 形态的 20 回合窗（43 轮
    会话 385 行只剩 13 轮），回合被拦腰截断、窗内 <20 轮时前端
    _hgHistWinStart 算出 start=0 → 归档条自插判据（start>0）不触发。裁窗
    保最后 N 个完整回合（N+1 个 user 行为起点，多带 1 轮让前端窗口计算
    产生 start>0=归档条恢复）。
    tail（a41c）：默认 0=不启用。行数闸与回合闸并存必打架——a41c 实锤
    调用点删了 TAIL_ROWS 但本函数默认 tail=400 仍二次裁剪（22 轮≈410 行
    恰卡 400 被裁回 13 轮，「重启没修好」二连）。回合窗是唯一裁剪；tail
    仅剩单测直传用途。"""
    rows = snap["rows"]
    if tail_turns and len(rows) > 1:
        cnt = 0
        start = 0
        for i in range(len(rows) - 1, -1, -1):
            r = rows[i]
            if (r.get("kind") == "user_input"
                    and str(r.get("text") or "").strip()):
                cnt += 1
                if cnt > tail_turns:
                    start = i
                    break
        if start:
            rows = rows[start:]
    if tail and len(rows) > tail:
        rows = rows[-tail:]
    return {
        "seq": snap["seq"], "epoch": snap["epoch"],
        "state": dict(snap["state"]),
        "rows": [dict(r) for r in rows],
        "total": snap["total"],
        "firstRowId": rows[0]["rowId"] if rows else 0,
        "turnsTotal": sum(1 for r in snap["rows"]
                          if r.get("kind") == "user_input"
                          and str(r.get("text") or "").strip()),
    }
