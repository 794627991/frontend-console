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


def _cg_argv():
    """完整启动 argv 前缀（a386 用户令工具内置——工作机无 npm 实锤）：
    ①安装态/npm 态 bundle（node.exe + lib 自带运行时，标准 APPDATA 位）
    ②开发态 offline_assets/codegraph/
    ③npm which codegraph（真全局安装，cmd shim 形态）
    返回 list 或 None。bundle 直启 = bin/codegraph.cmd 的等价展开
    （node.exe --liftoff-only lib/dist/bin/codegraph.js）"""
    appdata = os.environ.get("APPDATA", "")
    _cands = []
    if appdata:
        _nm = os.path.join(appdata, "npm", "node_modules", "@colbymchenry")
        # ①工具资源包安装位（res_install 直铺）②npm 全局嵌套位
        # （@colbymchenry/codegraph 主包内嵌平台包）
        _cands.append(os.path.join(_nm, "codegraph-win32-x64"))
        _cands.append(os.path.join(_nm, "codegraph", "node_modules",
                                   "@colbymchenry", "codegraph-win32-x64"))
    _cands.append(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "offline_assets", "codegraph"))
    for root in _cands:
        node = os.path.join(root, "node.exe")
        js = os.path.join(root, "lib", "dist", "bin", "codegraph.js")
        if os.path.isfile(node) and os.path.isfile(js):
            return [node, "--liftoff-only", "--disable-warning=ExperimentalWarning", js]
    p = shutil.which("codegraph")
    return [p] if p else None


def _cg_exe():
    """兼容旧调用：返回首个可执行路径（bundle 场景=node.exe）"""
    argv = _cg_argv()
    return argv[0] if argv else None


def _run(args, root, timeout=3600):
    """跑 codegraph 子命令（cwd=root）。返回 (rc, stdout+stderr)。"""
    if not _cg_argv():
        return -1, "codegraph 不可用（工具资源包安装 codegraph 后可用）"
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        return -1, "目录不存在：%s" % root
    try:
        # R26-1（高，实锤：GBK 解码崩 → 幽灵态+假成功）：codegraph 输出恒含
        # UTF-8 非 ASCII（em dash/⚠/中文路径）——中文 Windows 默认 GBK 下
        # reader 线程 UnicodeDecodeError → stdout=None → installed=True
        # files=0 幽灵态；index --force 输出 not initialized 却 rc=0 假成功。
        # 必须显式 UTF-8 + replace
        r = subprocess.run(_cg_argv() + args, cwd=root, capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=timeout,
                           creationflags=0x08000000)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return -2, "codegraph 超时"
    except Exception as e:
        return -3, str(e)


def available():
    return bool(_cg_argv())


def status(root):
    """解析 codegraph status → {ok, installed, files, nodes, edges, db_mb, err}
    R26-3（实锤：向上递归误报）：codegraph 按祖先目录定位索引——子目录
    status 会报父级的数字。先守卫本目录 .codegraph 存在才认 installed"""
    if not available():
        return {"ok": False, "installed": False,
                "err": "codegraph 未安装（设置→外部依赖安装，或重装资源包）"}
    if not os.path.isdir(os.path.join(root, ".codegraph")):
        return {"ok": True, "installed": False}
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


class CgCancelled(Exception):
    pass


def build(root, log=None, progress=None, should_cancel=None):
    """init（首次）或 index 全量重建。返回 (ok, msg)。
    log=callable 收进度行；progress=callable(pct, label)。
    a361：codegraph 自身无机器可读进度（TTY 进度条）——用 .codegraph/
    下的 DB 文件增长做心跳（每 2 秒报 MB），死等变活进度。
    R27-1（实锤：取消钮假动作）：should_cancel 由 work() 传入——心跳每
    拍检查，已取消即杀子进程（_run 的 Popen 句柄）并抛 CgCancelled"""
    say = log or (lambda _m: None)
    prog = progress or (lambda *_a: None)
    st = status(root)
    if not st.get("ok"):
        return False, st.get("err", "status 失败")
    action = "index" if st.get("installed") else "init"
    say("codegraph %s（首次 init 数十秒，重建同量级）…" % action)
    prog(5, "codegraph %s" % action)
    import subprocess as _sp
    import threading as _th
    _stop = _th.Event()
    _proc = [None]
    db = os.path.join(root, ".codegraph")
    import time as _cgt
    _t0 = _cgt.time()
    def _hb():
        _last = -1
        _last_say = 0.0
        while not _stop.wait(2.0):
            if should_cancel and should_cancel():
                _stop.set()
                try:
                    if _proc[0]:
                        _proc[0].kill()
                except Exception:
                    pass
                return
            total = 0
            filecnt = 0
            for r, _ds, fs in os.walk(db):
                for f in fs:
                    filecnt += 1
                    try:
                        total += os.path.getsize(os.path.join(r, f))
                    except OSError:
                        pass
            mb = int(total / 1048576)
            elapsed = int(_cgt.time() - _t0)
            # 用户实锤：大库 init 扫描阶段 DB 为 0 MB——只报"0 MB"死寂几分钟。
            # 改为：DB 有数据报 MB+文件数，扫描阶段报"扫描中 Xs"（5s 一拍防刷屏）
            now = _cgt.time()
            if mb != _last:
                _last = mb
                _last_say = now
                if mb > 0:
                    say("  codegraph 数据 %.0f MB（%d 文件）…" % (mb, filecnt))
                else:
                    say("  codegraph 扫描中…（已 %ds）" % elapsed)
            elif now - _last_say >= 5.0:
                _last_say = now
                if mb > 0:
                    say("  codegraph 数据 %.0f MB（%d 文件）· 已 %ds…" % (mb, filecnt, elapsed))
                else:
                    say("  codegraph 扫描中…（已 %ds）" % elapsed)
    _hb_t = _th.Thread(target=_hb, daemon=True)
    _hb_t.start()
    proc = None
    try:
        if not _cg_argv():
            return False, "codegraph 不可用（工具资源包安装后可用）"
        # a368R（用户定调：隐藏目录优先排除）：codegraph 实测会收
        # .history/x.c 这类隐藏目录文件（files 表实锤）。CLI 无 --exclude
        # 参数（help 实核）——官方机制是工程根 codegraph.json 的 exclude
        # （project-config.d.ts 佐证，实测 ".history/ 等 pattern"生效：
        # 收录从 2 文件 → 1）。建/重建前写入（只补缺不覆盖用户手写的）
        try:
            import json as _json2
            cfgp = os.path.join(root, "codegraph.json")
            cfg = {}
            if os.path.isfile(cfgp):
                try:
                    cfg = _json2.load(open(cfgp, encoding="utf-8")) or {}
                except Exception:
                    cfg = {}
            excl = cfg.get("exclude")
            if not isinstance(excl, list):
                excl = []
            need = [p for p in (".*", ".*/*") if p not in excl]
            if need:
                cfg["exclude"] = excl + need
                with open(cfgp, "w", encoding="utf-8") as f:
                    _json2.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        # 用户实锤（h11 大库）：codegraph 自带 watchdog 在扫描大目录时误杀
        # 主线程忙于同步 I/O → 判"无响应"60s 即杀（#850）——索引场景禁掉
        _env = {**os.environ, "CODEGRAPH_NO_WATCHDOG": "1"}
        proc = _sp.Popen(_cg_argv() + [action, "--force"], cwd=root,
                         stdout=_sp.PIPE, stderr=_sp.STDOUT,
                         env=_env, creationflags=0x08000000)
        _proc[0] = proc
        out = proc.communicate(timeout=3500)[0]
        rc = proc.returncode
    except _sp.TimeoutExpired:
        try:
            proc.kill()
        except Exception:
            pass
        return False, "codegraph 超时"
    finally:
        _stop.set()
        _proc[0] = None
    # 被取消：心跳杀了进程 → 非零 rc + cancel 态
    if should_cancel and should_cancel():
        raise CgCancelled("用户取消 codegraph")
    if rc != 0:
        try:
            txt = (out or b"").decode("utf-8", "replace")
        except Exception:
            txt = ""
        return False, txt[-300:]
    prog(90, "codegraph 收尾")
    st2 = status(root)
    if not st2.get("ok") or not st2.get("installed"):
        return False, "索引未生效：" + json_safe(st2)
    say("✓ %d 文件 · %d 节点 · %d 边 · %.1fMB"
        % (st2["files"], st2["nodes"], st2["edges"], st2["db_mb"]))
    return True, "codegraph 索引就绪"


def sync(root, log=None, should_cancel=None):
    """增量同步（代码大改后；秒级）。
    R28-1（实锤：sync 取消假动作）：已安装分支原走 _run（subprocess.run
    无中断）——cancel 置位后任务照常跑完（600 文件全量 diff 10-19s 实测）。
    改 Popen+句柄注入，取消时 kill（build 同款链）"""
    say = log or (lambda _m: None)
    st = status(root)
    if not st.get("installed"):
        return build(root, log, should_cancel=should_cancel)
    say("codegraph sync（增量）…")
    import subprocess as _sp
    import threading as _th
    if not _cg_argv():
        return False, "codegraph 不可用（工具资源包安装后可用）"
    _stop = _th.Event()
    _proc = [None]
    def _watch():
        # 取消监视线程：cancel 即杀子进程
        while not _stop.wait(1.0):
            if should_cancel and should_cancel():
                _stop.set()
                try:
                    if _proc[0]:
                        _proc[0].kill()
                except Exception:
                    pass
                return
    _wt = _th.Thread(target=_watch, daemon=True)
    _wt.start()
    try:
        _env = {**os.environ, "CODEGRAPH_NO_WATCHDOG": "1"}   # 同 build：大库扫描禁误杀
        proc = _sp.Popen(_cg_argv() + ["sync"], cwd=root,
                         stdout=_sp.PIPE, stderr=_sp.STDOUT,
                         env=_env, creationflags=0x08000000)
        _proc[0] = proc
        out = proc.communicate(timeout=590)[0]
        rc = proc.returncode
    except _sp.TimeoutExpired:
        try:
            proc.kill()
        except Exception:
            pass
        return False, "codegraph sync 超时"
    finally:
        _stop.set()
        _proc[0] = None
    if should_cancel and should_cancel():
        raise CgCancelled("用户取消 codegraph sync")
    try:
        txt = (out or b"").decode("utf-8", "replace")
    except Exception:
        txt = ""
    out = txt
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
