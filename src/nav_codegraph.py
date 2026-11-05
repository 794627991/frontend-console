# -*- coding: utf-8 -*-
"""Claude 代码图集成（用户需求：codegraph 做进工具，claude 读代码方便）。

与 ctags 跳转索引（nav_index，喂用户 F12）完全独立的两套：
- codegraph（npm 全局命令）→ 知识图谱（函数/调用/继承边），喂 claude
  会话（MCP 已全局注册 `codegraph serve --mcp`，按会话 cwd 自动定位
  .codegraph/ 索引）——工程没 init 过则 claude 查询报 not initialized，
  本模块补的就是"工具内一键建/同步索引"
- ctags（vendor 内置）→ 符号跳转，喂 F12/Ctrl+T

索引落在 <工程>/.codegraph/（工程根，非 DATA_DIR——codegraph 的定位
机制如此；其自带 .gitignore 全排除，不污染仓库）。
实测：本仓库 174 文件 1.9s；SDK 2254 文件 32s / 216MB。
"""
import os
import re
import shutil
import subprocess


def _cg_exe():
    p = shutil.which("codegraph")
    return p


def _run(args, root, timeout=3600):
    """跑 codegraph 子命令（cwd=root）。返回 (rc, stdout+stderr)。"""
    exe = _cg_exe()
    if not exe:
        return -1, "codegraph 命令不存在（npm install -g codegraph 安装）"
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        return -1, "目录不存在：%s" % root
    try:
        r = subprocess.run([exe] + args, cwd=root, capture_output=True,
                           text=True, timeout=timeout,
                           creationflags=0x08000000)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return -2, "codegraph 超时"
    except Exception as e:
        return -3, str(e)


def available():
    return bool(_cg_exe())


def status(root):
    """解析 codegraph status → {ok, installed, files, nodes, edges, db_mb, err}"""
    if not available():
        return {"ok": False, "installed": False,
                "err": "codegraph 未安装（npm install -g codegraph）"}
    rc, out = _run(["status"], root, timeout=60)
    if rc != 0:
        # status 在未 init 时 rc 可能非 0 且输出 "Not initialized"
        if "Not initialized" in out:
            return {"ok": True, "installed": False}
        return {"ok": False, "installed": False, "err": out[:200]}
    if "Not initialized" in out:
        return {"ok": True, "installed": False}
    def _num(pat):
        m = re.search(pat + r"[\s:]*([\d,]+)", out)
        return int(m.group(1).replace(",", "")) if m else 0
    m = re.search(r"DB Size:\s*([\d.]+)\s*(KB|MB|GB)", out)
    db = float(m.group(1)) if m else 0.0
    unit = {"KB": 1 / 1024, "MB": 1, "GB": 1024}.get(m.group(2) if m else "MB", 1)
    return {"ok": True, "installed": True,
            "files": _num(r"Files"), "nodes": _num(r"Nodes"),
            "edges": _num(r"Edges"), "db_mb": round(db * unit, 1)}


def build(root, log=None):
    """init（首次）或 index 全量重建。返回 (ok, msg)。log=callable 收进度行。"""
    say = log or (lambda _m: None)
    st = status(root)
    if not st.get("ok"):
        return False, st.get("err", "status 失败")
    action = "index" if st.get("installed") else "init"
    say("codegraph %s（首次 init 数十秒，重建同量级）…" % action)
    rc, out = _run([action, "--force" if action == "init" else "--force"], root)
    # init/index 默认即建索引；--force 防home判定误伤（工程根都是普通目录）
    if rc != 0:
        return False, out[-300:]
    st2 = status(root)
    if not st2.get("ok") or not st2.get("installed"):
        return False, "索引未生效：" + json_safe(st2)
    say("✓ %d 文件 · %d 节点 · %d 边 · %.1fMB"
        % (st2["files"], st2["nodes"], st2["edges"], st2["db_mb"]))
    return True, "codegraph 索引就绪"


def sync(root, log=None):
    """增量同步（代码大改后；秒级）。"""
    say = log or (lambda _m: None)
    st = status(root)
    if not st.get("installed"):
        return build(root, log)   # 未建过 → 全量
    say("codegraph sync（增量）…")
    rc, out = _run(["sync"], root, timeout=600)
    if rc != 0:
        # sync 对空 diff 也可能非零？宽松：重查 status 确认仍健康
        st2 = status(root)
        if st2.get("ok") and st2.get("installed"):
            say("✓ 已同步（%d 文件 · %d 节点）" % (st2["files"], st2["nodes"]))
            return True, "ok"
        return False, out[-300:]
    st2 = status(root)
    say("✓ 已同步（%d 文件 · %d 节点 · %d 边）"
        % (st2.get("files", 0), st2.get("nodes", 0), st2.get("edges", 0)))
    return True, "ok"


def remove(root):
    """删除工程内 .codegraph/（uninit）。"""
    st = status(root)
    if not st.get("installed"):
        # 目录可能存在但 status 判未装——直接物理删
        pass
    d = os.path.join(root, ".codegraph")
    if not os.path.isdir(d):
        return False, "该工程没有 codegraph 索引"
    rc, out = _run(["uninit", "--force"], root, timeout=120)
    if rc != 0 and os.path.isdir(d):
        return False, out[-200:]
    return True, "已删除 .codegraph/"


def json_safe(d):
    import json
    return json.dumps(d, ensure_ascii=False)[:200]
