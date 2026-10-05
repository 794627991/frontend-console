# -*- coding: utf-8 -*-
"""MCP 识图管线测试 v2:
A. _ask_mcp_cfg_path 生成的 --mcp-config 里 py 路径真实存在
B. spawn vision_mcp.py,initialize→tools/list→tools/call analyze_image 真调识图。
   修复 v1 卡死:notification 不应答,不能对它 readline;stdout 加实时 flush。
"""
import base64, json, os, subprocess, sys, threading, zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("=" * 30, "A. --mcp-config 路径检查", "=" * 30, flush=True)
import src.claude_harness as ch
cfg_path = ch._ask_mcp_cfg_path("pipeline-test")
cfg = json.load(open(cfg_path, encoding="utf-8"))
ok_all = bool(cfg.get("mcpServers"))
for srv, scfg in (cfg.get("mcpServers") or {}).items():
    print(f"server[{srv}]: {scfg.get('command')} {scfg.get('args')}", flush=True)
    for a in scfg.get("args", []):
        if a.endswith(".py"):
            hit = os.path.isfile(a)
            print("   ", "OK " if hit else "MISSING", a, flush=True)
            ok_all = ok_all and hit
print("A 结果:", "PASS" if ok_all else "FAIL", flush=True)

print("=" * 30, "B. vision_mcp 真连识图", "=" * 30, flush=True)
def chunk(typ, data):
    c = typ + data
    return len(data).to_bytes(4, "big") + c + zlib.crc32(c).to_bytes(4, "big")
w = h = 64
raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))
png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", w.to_bytes(4, "big") + h.to_bytes(4, "big")
       + bytes([8, 2, 0, 0, 0])) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
img = os.path.join(os.path.expanduser("~"), ".serialconsole_pro", "pipeline_test.png")
open(img, "wb").write(png)

proc = subprocess.Popen([sys.executable, os.path.join("src", "harness", "vision_mcp.py")],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL)

resp = {}   # id -> dict(解析线程填)
def reader():
    for line in proc.stdout:
        line = line.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        print("  <<", line[:150], flush=True)
        try:
            o = json.loads(line)
            if o.get("id") is not None:
                resp[o["id"]] = o
        except Exception:
            pass

threading.Thread(target=reader, daemon=True).start()

def send(obj):
    proc.stdin.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
    proc.stdin.flush()

def wait(rid, timeout=150):
    import time
    t0 = time.time()
    while rid not in resp:
        if time.time() - t0 > timeout:
            return {"error": "timeout %ss" % timeout}
        time.sleep(0.3)
    return resp[rid]

send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
r1 = wait(1, 15)
print("init:", json.dumps(r1.get("result", r1), ensure_ascii=False)[:120], flush=True)
send({"jsonrpc": "2.0", "method": "notifications/initialized"})   # 不等应答
send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
r2 = wait(2, 15)
names = [t.get("name") for t in (r2.get("result", {}).get("tools") or [])]
print("tools:", names, flush=True)
send({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
    "name": "analyze_image",
    "arguments": {"prompt": "这张图是什么颜色?只回答颜色名", "imageSource": img},
}})
r3 = wait(3, 150)
res = r3.get("result", {})
content = res.get("content") or []
text = content[0].get("text", "") if content else json.dumps(r3, ensure_ascii=False)[:200]
print("识图结论:", text[:300], flush=True)
proc.stdin.close()
try: proc.wait(timeout=5)
except Exception: proc.kill()
print("B 结果:", "PASS" if ("红" in text or "red" in text.lower()) else "FAIL", flush=True)
