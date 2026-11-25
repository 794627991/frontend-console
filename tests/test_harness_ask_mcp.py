# -*- coding: utf-8 -*-
"""harness 的 ask_user MCP 注入链（2026-11-25 用户实锤「ask_user 一定存在、
一定好使，必须严查」）。

查明的真相：这条链**存在且一直在**（src/harness/askmcp.py 写 --mcp-config，
session.py 传给 claude），但 `ask_mcp.py` / `vision_mcp.py` 开头是
`from src import app_state`，而 claude 以**会话工程目录**为 cwd 拉起它们
（session.py 的 cwd=self.cwd），脚本模式下 sys.path[0] 只含 src/harness/，
工具根不在搜索路径上 → ModuleNotFoundError → 进程秒退。MCP 起不来时 claude
只表现为「少了这个工具」，不报错，于是静默失效。

修复：_ask_mcp_cfg_path 给两个 server 都注入 PYTHONPATH=<工具根>，不赌 cwd。

直接 `python tests/test_harness_ask_mcp.py`。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_PASS, _FAIL = [], []


def check(name, cond, detail=""):
    if cond:
        _PASS.append(name)
        print("  PASS  %s" % name)
    else:
        _FAIL.append(name)
        print("  FAIL  %s  %s" % (name, detail))


def _probe(entry, cwd, keep_pythonpath):
    """按 claude 的方式拉起 server：指定 cwd、只给配置里的 env。"""
    env = {}
    for k in ("SYSTEMROOT", "PATH", "TEMP", "TMP", "USERPROFILE", "APPDATA"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    env.update(entry.get("env") or {})
    if not keep_pythonpath:
        env.pop("PYTHONPATH", None)
    msg = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                      "params": {"protocolVersion": "2024-11-05",
                                 "capabilities": {},
                                 "clientInfo": {"name": "t", "version": "1"}}})
    tools = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list",
                        "params": {}})
    probe = msg + "\n" + json.dumps({"jsonrpc": "2.0",
                                     "method": "notifications/initialized"}) \
        + "\n" + tools + "\n"
    try:
        p = subprocess.run([entry["command"]] + list(entry.get("args") or []),
                           input=probe, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           cwd=cwd, env=env, timeout=60)
        return p.returncode, p.stdout or "", p.stderr or ""
    except Exception as e:
        return -1, "", repr(e)


def main():
    from src.harness.askmcp import _ask_mcp_cfg_path

    print("== 1. 配置里两个 server 都带 PYTHONPATH（工具根）==")
    cfg = _ask_mcp_cfg_path("deadbeefcafe1234", "auto", include_vision=True)
    check("配置文件已生成", bool(cfg) and os.path.isfile(cfg), str(cfg))
    d = json.load(open(cfg, encoding="utf-8"))
    servers = d.get("mcpServers") or {}
    check("harness server 在", "harness" in servers, str(list(servers)))
    hs = servers.get("harness") or {}
    check("harness 有 PYTHONPATH", bool((hs.get("env") or {}).get("PYTHONPATH")),
          str(hs.get("env")))
    want = os.path.normcase(os.path.normpath(ROOT))
    got = os.path.normcase(os.path.normpath(
        (hs.get("env") or {}).get("PYTHONPATH") or ""))
    check("PYTHONPATH 指向工具根", got == want, "%r vs %r" % (got, want))
    check("原有 sid/perm 没丢",
          (hs.get("env") or {}).get("HARNESS_SID") == "deadbeefcafe1234"
          and (hs.get("env") or {}).get("HARNESS_PERM") == "auto",
          str(hs.get("env")))

    print("== 2. 真实场景：cwd 是用户工程目录时 server 能起来 ==")
    fake = tempfile.mkdtemp(prefix="fake_proj_")
    try:
        rc, out, err = _probe(hs, fake, keep_pythonpath=True)
        check("进程正常退出", rc == 0, "rc=%s err=%s" % (rc, err[-300:]))
        check("initialize 有应答", '"serverInfo"' in out, out[:200])
        check("工具列表里有 ask_user", '"name": "ask_user"' in out, out[:300])
    finally:
        shutil.rmtree(fake, ignore_errors=True)

    print("== 3. 反向对照：去掉 PYTHONPATH 必须复现原故障 ==")
    fake2 = tempfile.mkdtemp(prefix="fake_proj2_")
    try:
        rc2, out2, _err2 = _probe(hs, fake2, keep_pythonpath=False)
        check("无 PYTHONPATH 时起不来（证明修复非空转）",
              rc2 != 0 and '"serverInfo"' not in out2,
              "rc=%s out=%r" % (rc2, out2[:120]))
    finally:
        shutil.rmtree(fake2, ignore_errors=True)

    print("== 4. vision server 同样带 PYTHONPATH ==")
    vs = servers.get("vision") or {}
    if vs:
        check("vision 有 PYTHONPATH",
              bool((vs.get("env") or {}).get("PYTHONPATH")), str(vs.get("env")))
        check("vision 的 env 里原有键没丢",
              (vs.get("env") or {}).get("PYTHONIOENCODING") == "utf-8",
              str(vs.get("env")))
    else:
        check("vision 未启用时跳过（识图关闭/多模态 inline 属正常）", True)

    print("== 5. 打包形态不写 PYTHONPATH（exe 自带 --mcp-ask，无需路径）==")
    src = open(os.path.join(ROOT, "src", "harness", "askmcp.py"),
               encoding="utf-8").read()
    check("frozen 分支把 _pyroot 置空",
          "_pyroot = \"\"" in src, "未见 frozen 分支的 _pyroot 清空")

    print("=" * 56)
    print("通过 %d / 失败 %d" % (len(_PASS), len(_FAIL)))
    for x in _FAIL:
        print("  -", x)
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
