# -*- coding: utf-8 -*-
"""ask_user 卡片全链测试:
后端(真 Flask):ask/reply 登记→事件流出→ask/answer 提交→ask/poll 取答
前端另由 tools/_chain_smoke.js 的 askRender/askDone 分支覆盖渲染。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.server import app
from src.harness import lifecycle as lc
from src.harness.session import HarnessSession

c = app.test_client()

# 1. 构造假会话(不 start——不 spawn claude 进程)
sid = "asktest"
s = HarnessSession(sid, cwd=os.getcwd())
with lc._sessions_lock:
    lc._sessions[sid] = s
print("[setup] 假会话已入表")

# 2. MCP 侧发起提问(ask/reply)
Q = {"questions": [
    {"question": "用方案A还是B?", "options": [{"label": "方案A"}, {"label": "方案B"}], "multi": False},
    {"question": "补充说明(可空)", "options": [], "multi": False},
]}
r = c.post("/api/harness/ask/reply", json={
    "sid": sid, "req_id": "rq1", "title": "选择实现方案", **Q})
print("ask/reply:", r.status_code, r.get_json())
assert r.status_code == 200 and r.get_json()["ok"], "reply 失败"
assert s.ask and s.ask["req_id"] == "rq1" and not s.ask["done"], "ask 状态未登记"
evs = [e.get("evt") or e for e in (s.get_events_after(0)[0] if isinstance(s.get_events_after(0), tuple) else s.get_events_after(0))]
assert any((e.get("kind") or (e.get("evt") or {}).get("kind")) == "ask" for e in evs), "ask 事件未入事件流"
print("[ok] ask 已登记,事件流含 kind=ask;ask 事件断言通过 OK")

# 3. 前端拉事件流(模拟 SSE 回放)
r = c.get("/api/harness/events?sid=%s&after=0" % sid)
data = r.get_json()
kinds = [e.get("kind") for e in (data.get("events") or [])]
print("events GET:", r.status_code, "kinds:", kinds)
assert "ask" in kinds, "事件流缺 ask"

# 4. 用户提交答案(ask/answer)
r = c.post("/api/harness/ask/answer", json={
    "sid": sid, "req_id": "rq1",
    "answer": {"用方案A还是B?": "方案A", "补充说明(可空)": "补充：快点"}})
print("ask/answer:", r.status_code, r.get_json())
assert r.status_code == 200 and r.get_json()["ok"], "answer 失败"
evs2 = s.get_events_after(0);
evs2 = evs2[0] if isinstance(evs2, tuple) else evs2
assert any((e.get("kind") or "") == "ask_done" or (e.get("evt") or {}).get("kind") == "ask_done" for e in evs2), "ask_done 事件未入流"

# 5. MCP 侧长轮询取答(ask/poll)
r = c.post("/api/harness/ask/poll", json={"sid": sid, "req_id": "rq1"})
j = r.get_json()
print("ask/poll:", r.status_code, j)
assert j["found"] and j["done"] and j["answer"]["用方案A还是B?"] == "方案A", "poll 结果不对"

# 6. 边界:错误 req_id / 重复提交 / 未知会话
r = c.post("/api/harness/ask/answer", json={"sid": sid, "req_id": "rqX", "answer": {}})
print("重复/错 req_id 提交:", r.status_code, "(预期 409)")
assert r.status_code == 409
r = c.post("/api/harness/ask/poll", json={"sid": "nosuch", "req_id": "rq1"})
j = r.get_json()
print("未知会话 poll:", j, "(预期 found=false)")
assert not j.get("found", False)

# 7. 清理
with lc._sessions_lock:
    lc._sessions.pop(sid, None)
print("\n=== ask_user 卡片全链 PASS ===")
