# -*- coding: utf-8 -*-
"""代码跳转索引（a333 批1）：ctags 全量候选 + 编译产物白名单 + ELF 符号表。

设计要点（用户四条铁律）：
- 手动触发：绝不自动建库——build 只由 /api/nav/build 显式调用
- 存储：DATA_DIR/nav/<md5(root)[:16]>/（用户数据空间·可迁移·衍生数据），
  绝不写工程目录/网盘
- 工程绑定：meta.json 记 root 绝对路径，跳转按「当前文件路径前缀匹配各库
  root」反查；换盘/移动 → 前缀失配 → rebind()（校验后才允许接管）
- 多语言：ctags 天然覆盖 C/C++/py/js 等，探测与索引同清单

三阶段管线（build）：
  1. 产物扫描：.cmd 命令行解析（Kbuild 自描述，多 .c 合一 .o 天然正确）
     + .o 同名映射兜底 → manifest.json（编译白名单）
  2. ctags 全量（多语言，tags 排序文本）
  3. pyelftools 读 .o ELF 符号表（defined FUNC/OBJECT）→ symbols.json
     （缺失则降级，不阻断）

决策链（definition，精→粗）：
  nm 符号锁定 → 白名单 in_build 唯一 → 路径公共祖先深度（零配置组件消歧）
  → 当前文件 static（ctags file: 标记）→ 候选列表（✓编译内/✗未编译/~头文件）
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time

_CTAGS_EXE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "vendor", "ctags", "ctags.exe")
# 可索引语言（与 ctags --languages 一致；探测用 CODE_EXTS 对应后缀）
# a415 P0-4（内网报告实测：不含 Asm 时 850 个 .S 零 tag——entry.S/head.S
# 启动与异常处理代码全丢；加 Asm 仅 +3s，缺失 850→0）
NAV_LANGS = "C,C++,Asm,Python,JavaScript,TypeScript,Java,Go,Rust"
CODE_EXTS = {".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", ".hh", ".hxx",
             ".py", ".js", ".mjs", ".cjs", ".ts", ".java", ".go", ".rs",
             ".s", ".S"}
# 编译单元后缀（白名单/符号表只认这些——.h 是包含物不是单元）。
# a415R2 N13：补 .s（.S 汇编单元进白名单后，查询侧 in_build 判定/同名
# 映射没跟上——F12 会跳到未编译的同名 .S）
_UNIT_EXTS = {".c", ".cpp", ".cc", ".cxx", ".s"}
# 生成文件指纹扫描的 rg --max-filesize（a372：原 4M 恰好漏掉 4.06M 的
# Cython routes.c——写进 gen_files.json 的 scan_max 字段，旧库读到不一致
# 即自动补扫，不需要用户重建索引）
_GEN_SCAN_MAX = "32M"
# a415 P1-5（内网报告 §2.5 实测：工具自身缓存目录 11841 个文件白扫——
# .history 1864 / .cache 8117 / .ua 1856 / .codegraph 4）
_SKIP_DIRS = {".git", "node_modules", ".svn", ".hg", ".history", ".cache",
              ".ua", ".codegraph", ".agents", ".codex", ".vscode",
              ".tmp_versions", ".buildroot-ccache", "__pycache__"}
# a415：收录范围配置文件名（工程根，随 SVN 走团队共享——报告 §九推荐位）
SCOPE_FILE = ".fcpk-scope.json"
# a416（内网报告·用户令「只要有白名单一定用白名单」）：非 C/C++ 语言的
# "中间文件"——收录集出现任意一个即视为编译过，按白名单走不许私自全量
#   Python: .pyc/.pyo（__pycache__ 目录本身在 _ARTIFACT_DIRS 探测）
#   JS/TS : .js.map/.d.ts.map/.tsbuildinfo   Java: .class
#   Go    : .a/.test                          Rust : .d（dep-info）
_AUX_ARTIFACT_EXTS = (".pyc", ".pyo", ".class", ".tsbuildinfo",
                      ".js.map", ".d.ts.map", ".a", ".test", ".d")
# a416：产物目录——存在即算"编译过"（探测计数在剪枝前），内容不索引
_ARTIFACT_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache",
                  ".ruff_cache", "node_modules"}
# a417（内网报告）：软错误集——悬空符号链接（SMB 解析到不存在共享根：
# winerror 59/errno 22）与拒绝访问等单点不可读跳过；真断连靠连续计数闸
_SOFT_ERRNOS = {2, 3, 5, 13, 22, 206, 1920, 1921}
_SOFT_WINERR = {2, 3, 5, 53, 59, 206, 1920, 1921}
_CONSEC_LIMIT = 50          # 连续软错误上限：超过=网络真断，仍判失败
# 浅探测优先下钻的常见代码目录名（大 SDK 里代码藏得深）
_HINT_DIRS = {"src", "source", "kernel", "linux", "uboot", "u-boot", "drivers",
              "driver", "lib", "app", "include", "open_source", "platform",
              "smp", "mpp", "component", "middleware", "sample"}
_PROBE_MAX_DIRS = 260          # 浅探测目录上限（秒级返回的关键）
_SRC_TOKEN_RE = re.compile(
    r"(?:^|\s)([^\s]+\.(?:c|cc|cpp|cxx|S|s|sx))(?:\s|$)")


def _nav_root():
    from src.app_state import DATA_DIR
    d = os.path.join(DATA_DIR, "nav")
    return d


def _lib_name(root):
    return hashlib.md5(os.path.normcase(os.path.abspath(root)).encode("utf-8")).hexdigest()[:16]


def lib_dir(root):
    return os.path.join(_nav_root(), _lib_name(root))


def _read_json(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_json(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    # tmp 唯一化（并发写同库时固定名交错覆盖）
    tmp = "%s.%d.tmp" % (p, threading.get_ident())
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
        for _i in range(3):                        # P-7/D-2：并发读者窗口重试
            try:
                os.replace(tmp, p); break
            except OSError:
                if _i == 2: raise
                time.sleep(0.05)                   # time :30 已导入
    except Exception:
        try: os.remove(tmp)                        # 清理包全段（含 dump TypeError）
        except OSError: pass
        raise


def _dir_size(root):
    total = 0
    for r, ds, fs in os.walk(root):
        for f in fs:
            try:
                total += os.path.getsize(os.path.join(r, f))
            except OSError:
                pass
    return total


# ------------------------------------------------------------------ 浅探测

def shallow_probe(root):
    """右键菜单「可建判定」：浅层抽样找代码文件。秒级，不扫全树。
    返回 {has_code, code_files, dirs_scanned, cmd_hits, o_hits}——
    cmd/o 浅层命中供 status 做粗粒度 stale 判定（批3）。"""
    hits, cmd_hits, o_hits, scanned = 0, 0, 0, 0
    try:
        roots = [(root, 0)]
        while roots and scanned < _PROBE_MAX_DIRS:
            d, depth = roots.pop(0)
            scanned += 1
            try:
                entries = os.listdir(d)
            except OSError:
                continue
            subdirs = []
            for name in entries:
                p = os.path.join(d, name)
                if os.path.isfile(p):
                    _, ext = os.path.splitext(name)
                    if ext.lower() in CODE_EXTS:
                        hits += 1
                    elif name.lower().endswith(".cmd"):
                        cmd_hits += 1
                    elif name.lower().endswith(".o"):
                        o_hits += 1
                    if hits >= 60:      # 够下结论了
                        return {"has_code": True, "code_files": hits,
                                "dirs_scanned": scanned,
                                "cmd_hits": cmd_hits, "o_hits": o_hits}
                elif os.path.isdir(p) and name not in _SKIP_DIRS:
                    subdirs.append((p, depth + 1))
            # 深度优先策略：常见代码目录名是强信号（kernel/drivers/serial
            # 这类 3+ 层是真形态）——深度 6 内全下钻；其余目录浅层广撒网
            hinted = [s for s in subdirs
                      if os.path.basename(s[0]).lower() in _HINT_DIRS]
            others = [s for s in subdirs if s not in hinted]
            if depth < 6:
                roots.extend(hinted)
            if depth < 2:
                roots.extend(others[:12])
            elif depth < 3:
                roots.extend(others[:4])
        return {"has_code": hits > 0, "code_files": hits,
                "dirs_scanned": scanned, "cmd_hits": cmd_hits, "o_hits": o_hits}
    except Exception:
        return {"has_code": False, "code_files": 0, "dirs_scanned": 0,
                "cmd_hits": 0, "o_hits": 0}


def status(root):
    """右键三态 + 跳转预探测。轻量：不触发任何扫描重活。"""
    root = os.path.abspath(root)
    ld = lib_dir(root)
    meta = _read_json(os.path.join(ld, "meta.json"))
    probe = shallow_probe(root)
    out = {"root": root, "has_code": probe["has_code"],
           "probe_files": probe["code_files"], "indexed": bool(meta),
           "lib_dir": ld if meta else "",
           # a407：查询后端能力下发——前端档位下拉无 sqlite3 时藏 sql 档
           "sqlite_ok": sqlite_capable()}
    # a415：收录范围检测（工程 .fcpk-scope.json > 已存范围；浅读秒级，
    # 面板建库前即显示"检测到工程配置"）
    _sc, _sc_src = load_scope(root)
    if _sc or _sc_src:
        out["scope"] = {"source": _sc_src,
                        "name": (_sc or {}).get("name", ""),
                        "tier": (_sc or {}).get("tier", ""),
                        "include": (_sc or {}).get("include", [])[:16],
                        "artifact_roots": (_sc or {}).get("artifact_roots", [])[:8]}
    else:
        # a416：零配置形态识别下发（面板显示"检测到 sbuilder 方案"，
        # 白名单档即用——不写死平台模板，只认结构特征）
        _dsc, _dkind = detect_scope(root)
        if _dsc:
            out["scope_detect"] = {"kind": _dkind}
    if meta:
        sizes = meta.get("sizes") or {}
        # 批3 stale 粗判：建库时记的 .cmd 计数与浅层现采对比——浅层命中
        # 显著多于建库记录（基线重新编译过）即提示重建（不自动）
        # R16-4（实锤：O= 输出树误报）：out/ 不在浅探测 hint 链——建库时有
        # 产物、浅层探不到 ≠ 树换了。反向判定删除，只保留"建库无产物现在
        # 浅层有"的升级提示（这是确定的增量信息）。
        # R17-4（实锤：计数口径不一）：cmd_count=解析成功数（受路径形态
        # 影响），probe.cmd_hits=文件名计数——同口径比较用 cmd_files
        # （建库时发现的 .cmd 文件总数，旧库无此键回退 cmd_count）
        cmd_files = meta.get("cmd_files", meta.get("cmd_count", 0))
        stale = bool(cmd_files == 0 and probe.get("cmd_hits", 0) > 0)
        out["stale"] = stale
        out["meta"] = {
            "built_at": meta.get("built_at", ""),
            "code_files": meta.get("code_files", 0),
            "symbols": meta.get("symbols", 0),
            "cmd_count": meta.get("cmd_count", 0),
            "o_count": meta.get("o_count", 0),
            "size": sum(sizes.values()),
            "root_reachable": os.path.isdir(meta.get("root", root)),
            # R35-5（实锤：UI 档位下拉数据链断裂）：backend 必须下发
            "backend": meta.get("backend", ""),
            "backend_auto": bool(meta.get("backend_auto")),
            # a415R（审计#14）：本次建库所用范围随 meta 下发（面板
            # 「本次建库范围」行的数据源）
            "scope": meta.get("scope") or None,
        }
    return out


def list_libs():
    """存储感知/管理用：全部索引库概览。"""
    out = []
    base = _nav_root()
    if not os.path.isdir(base):
        return out
    for name in os.listdir(base):
        meta = _read_json(os.path.join(base, name, "meta.json"))
        if meta:
            sizes = meta.get("sizes") or {}
            out.append({"lib": name, "root": meta.get("root", ""),
                        "built_at": meta.get("built_at", ""),
                        "size": sum(sizes.values()),
                        "code_files": meta.get("code_files", 0),
                        "reachable": os.path.isdir(meta.get("root", "\\\\"))})
    return out


def delete_lib(root):
    _close_tagdb()   # D-4（P3）：被查询过的库持有连接——不关则 tags.db 锁死
                     # （且 meta 先删后 find_lib_for 不再命中，连接永不释放）
    ld = lib_dir(root)
    if os.path.isdir(ld):
        import shutil as _sh
        _sh.rmtree(ld, ignore_errors=False)   # 失败如实抛（api 层转 err）
        return True
    return False


def rebind(old_root, new_root):
    """工程移动/换盘后的重新关联。校验防误绑：新根存在 + 记录的编译文件
    抽样仍在（白名单键相对路径拼新根）+ 代码文件数量级吻合。
    R15-4（实锤：rebind 撞已建库状态分裂）：目标库已存在时拒绝（先删后
    绑）；meta 落盘放到目录改名之后（改名失败不留半改状态）。"""
    old_root, new_root = os.path.abspath(old_root), os.path.abspath(new_root)
    ld = lib_dir(old_root)
    meta = _read_json(os.path.join(ld, "meta.json"))
    mf = _read_json(os.path.join(ld, "manifest.json"))
    if not meta or not mf:
        return False, "旧索引不存在"
    if not os.path.isdir(new_root):
        return False, "新路径不存在"
    new_ld = lib_dir(new_root)
    if os.path.abspath(new_ld) != os.path.abspath(ld) and os.path.isdir(new_ld):
        return False, "新路径已有自己的索引库——请先删除旧库再重关联"
    compiled = mf.get("compiled") or {}
    sample = list(compiled.keys())[:5]
    if sample:
        ok = sum(1 for rel in sample
                 if os.path.isfile(os.path.join(new_root, rel.replace("/", os.sep))))
        if ok < max(1, len(sample) - 1):
            return False, "校验失败：新路径下找不到索引记录的源文件（%d/%d）——不是同一个工程？" % (ok, len(sample))
    meta["root"] = new_root
    if os.path.abspath(new_ld) != os.path.abspath(ld):
        os.makedirs(os.path.dirname(new_ld), exist_ok=True)
        _close_tagdb()   # r1 新发现①（P3 同族）：库被查询过则 Windows 带句柄
                         # 改名必败——P-13 只补了 delete，rebind 同场景
        os.replace(ld, new_ld)          # 目录整体改名（meta 改名后再写新库）
        _write_json(os.path.join(new_ld, "meta.json"), meta)
    else:
        _write_json(os.path.join(ld, "meta.json"), meta)
    # a415R2 N11：已存范围随迁（存储位按 root 哈希）。a415R3 BUG-4：放到
    # 库改名/meta 写盘**都成功之后**——原先进去做，改名失败留半迁移态
    # （docstring 约定：改名失败不留半改状态）
    try:
        _sp_old, _sp_new = scope_store_path(old_root), scope_store_path(new_root)
        if os.path.isfile(_sp_old):
            os.replace(_sp_old, _sp_new)
    except OSError:
        pass
    _invalidate_cache()
    return True, "已关联到 " + new_root


# ------------------------------------------------------------------ 建库管线

def _is_remote_fs(path):
    """网盘/UNC 判定（a413）：远程 FS 是 RTT 受限（每目录一次 SMB 往返），
    并发分片近线性提速；本地盘并发反而慢（GIL/队列开销，实测 13179 文件
    4.3s vs 单线程 1.7s）——本地走单 worker"""
    try:
        import ctypes
        p = os.path.abspath(path)
        if p.startswith("\\\\"):
            return True                      # UNC 直连网络共享
        return ctypes.windll.kernel32.GetDriveTypeW(p[:3]) == 4   # DRIVE_REMOTE
    except Exception:
        return False


def _walk_files(root, subs=None, should_cancel=None, say=None,
                excl_names=(), excl_paths=(), stats=None):
    """生成 (abs_path, rel_posix)（rel 一律相对 root）。
    a411→a413（用户实锤：W: 网盘大库阶段 1 扫描磨到像卡死）：网盘瓶颈是
    RTT——每目录一次 SMB 往返、单线程串行干等；并发分片 + 8 worker 近线性
    提速。停滞检测（120s 告警/300s 失败）与取消（消费侧循环头/DONE 双查）。
    a415：①subs=收录范围（scope.include 的 rel 目录列表；None=全 root）
    ②excl_names/excl_paths=scope 排除（名字任意层级/路径前缀，posix rel）
    ③P0-1 环防护：SMB 把 sysfs 自链符号链接展成无 reparse 标记的实体目录
    （内网报告 §2.1 实测单链 56 层多分叉组合爆炸，深度截断只砍最深分支、
    同层宽度照爆）——同名目录在一条路径上重复 >6 次即判环剪枝（报告 §8.1
    原方：depth>6 才启用计数，正常嵌套名不重复不误伤）
    ④点目录一律跳过（对齐 ctags 旧 --exclude=.* 语义；点文件照常产出——
    Kbuild 的 .foo.o.cmd 是白名单源）。stats=dict 时回填 {pruned}"""
    import queue as _q
    import threading as _th
    say = say or (lambda _m: None)
    stats = stats if stats is not None else {}
    stats.setdefault("pruned", 0)
    N_WORKERS = 8 if _is_remote_fs(root) else 1   # a413：网盘并发/本地单线程
    out_q = _q.Queue(maxsize=256)
    _DONE = object()
    _err = [None]
    # a415R（审计#17）：Windows 大小写不敏感——排除/跳过比较全部 lower
    _skip = {s.lower() for s in (_SKIP_DIRS | set(excl_names or ()))}
    _excl = tuple(sorted(p.strip("/").lower() for p in (excl_paths or ())
                         if p and p != "."))

    def _excluded(rel_l):
        for ep in _excl:
            if rel_l == ep or rel_l.startswith(ep + "/"):
                return True
        return False

    def _scandir(d):
        with os.scandir(d) as it:
            ds, fs = [], []
            for e in it:
                (ds if e.is_dir() else fs).append(e.name)
        return ds, fs

    def _keep_dir(name):
        # a415R（审计#23）：不跳通用点目录——.libs/.pio 里的 .o/.cmd 是合法
        # 产物（旧版就没跳）；点目录的 ctags 语义在 files.txt 写出端过滤
        return name.lower() not in _skip

    # ---- 分片（同步秒级：每个收录根 L1（不足 8 个 worker 拆到 L2））----
    pre_batches = []      # 分片期收获的 (dir, files) 批（消费开始时先回放）
    seeds = []            # 子树任务（绝对路径）
    bases = [root] if not subs else []
    if subs:
        for s in subs:
            p = os.path.normpath(os.path.join(root, str(s).replace("/", os.sep)))
            if os.path.isdir(p):
                bases.append(p)
            else:
                say("  ⚠ 收录目录不存在，已跳过：%s" % s)
    # a415R（审计#15）：重叠/重复 include 去重 + 剔除被包含的基（同树双走
    # = .cmd/.o 计数翻倍、bmap 歧义误判）。a415R2 N22：比较基准补尾分隔
    # 符——盘符根（C:\）无尾 sep 时 startswith(k+sep) 恒假，去重失效双走
    bases.sort(key=lambda b: b.lower())
    _kept = []
    for b in bases:
        bl = b.lower().rstrip("\\/") + os.sep
        if not any(bl == k or bl.startswith(k) for k in
                   (kk.lower().rstrip("\\/") + os.sep for kk in _kept)):
            _kept.append(b)
    bases = _kept
    if not bases:
        return   # subs 全部无效：零文件
    try:
        for base in bases:
            if _excluded(os.path.relpath(base, root).replace(os.sep, "/").lower()):
                continue
            l1_ds, b_fs = _scandir(base)
            # a416：种子层同探测产物目录（L1 在 worker 之前被过滤）
            stats["artifact_dirs"] = stats.get("artifact_dirs", 0) + sum(
                1 for d in l1_ds if d.lower() in _ARTIFACT_DIRS)
            l1_ds = [d for d in l1_ds if _keep_dir(d)]
            pre_batches.append((base, b_fs))
            if len(l1_ds) >= N_WORKERS:
                seeds.extend(os.path.join(base, d) for d in l1_ds)
            else:
                # 一级子目录太少（并发吃不满）：拆到二级
                for d in l1_ds:
                    p = os.path.join(base, d)
                    try:
                        l2_ds, l2_fs = _scandir(p)
                    except OSError:
                        seeds.append(p)   # 展不开（权限/断连）：整子树任务
                        continue
                    pre_batches.append((p, l2_fs))
                    seeds.extend(os.path.join(p, s2)
                                 for s2 in l2_ds if _keep_dir(s2))
    except OSError as e:
        raise RuntimeError("目录扫描失败（%s）" % e)

    work_q = _q.Queue()
    for s in seeds:
        work_q.put(s)
    _active = [0]
    _alock = _th.Lock()
    _abandoned = [False]   # a415R（审计#21）：消费侧退出后 worker 放弃投递

    def _loop_prune(r, sub):
        """a415R（审计#2）：环防护收紧——只统计 sub 以下的路径段（base 段
        不算）、阈值 >3（审计建模：4 条回环路由下 >6 要磨 1.5 万目录/48min，
        >3 只 224 个）、另加绝对路径长度上限兜底。返回 True=剪枝。
        a415R2 N15：r==sub（种子根自身）直接放行——原 tail 取整条绝对
        路径，盘符/用户名段同名 4 个就把整个种子子树误剪"""
        if r == sub:
            return False
        if len(r) > 480:
            return True
        tail = r[len(sub) + 1:] if r.lower().startswith(sub.lower() + os.sep) \
            else r
        segs = tail.split(os.sep)
        if len(segs) <= 3:
            return False
        _c = {}
        for seg in segs:
            _c[seg.lower()] = _c.get(seg.lower(), 0) + 1
        return max(_c.values()) > 3

    def _worker():
        # try/finally 包全程：取消 return 也不许跳过 _active 递减——否则
        # DONE 永远不发、消费侧死等停滞超时（自审实锤）
        _soft_errs = [0]   # a423R BUG-3：连续软错误计数——worker 全程
                           # 跨 sub 累加（每 sub 重置会让多子树分摊绕过闸）
        try:
            while True:
                try:
                    sub = work_q.get_nowait()
                except _q.Empty:
                    break
                try:
                    # a415R2 N5 + 内网报告 a417：onerror 分级。原软错误集漏了
                    # 悬空符号链接（rootfs 的 lib64->/usr/lib 被 SMB 解析到不
                    # 存在的共享根：scandir=winerror 5，walk=winerror 59/
                    # errno 22）→ 判 SMB 断连整库失败。扩集 {13,22,53,59}，
                    # 但加连续计数闸：真断连时每个待访目录都报错，很快超
                    # _CONSEC_LIMIT 判真断仍抛错；悬空软链零散几个不触发。
                    # a423R BUG-3：_soft_errs 定义已上移到 while 之前
                    #（跨 sub 累加）——原在 per-sub 循环内每棵子树重置，
                    # 55 个软错误分两子树（30+25）即绕过闸静默成功（审计实测）
                    def _on_err(e):
                        we = getattr(e, "winerror", None)
                        en = getattr(e, "errno", None)
                        if we in _SOFT_WINERR or en in _SOFT_ERRNOS:
                            _soft_errs[0] += 1
                            stats["soft_skipped"] = stats.get("soft_skipped", 0) + 1
                            if _soft_errs[0] > _CONSEC_LIMIT:
                                _err[0] = e   # 连续爆炸=网络真断
                            return
                        _err[0] = e
                    for r, ds, fs in os.walk(sub, onerror=_on_err):
                        # a416（用户令·白名单优先）：产物目录存在即算"编译过"
                        # ——探测计数**在剪枝之前**（__pycache__ 里的 .pyc
                        # 目录一剪就永远扫不到）；探测完照常剪掉不索引
                        _arts_hit = sum(1 for d in ds
                                        if d.lower() in _ARTIFACT_DIRS)
                        if _arts_hit:
                            stats["artifact_dirs"] = \
                                stats.get("artifact_dirs", 0) + _arts_hit
                        ds[:] = [d for d in ds if _keep_dir(d)]
                        # P0-1 环防护（SMB 自链，报告 §2.1）
                        if _loop_prune(r, sub):
                            ds[:] = []
                            stats["pruned"] += 1
                            continue
                        if _excluded(os.path.relpath(
                                r, root).replace(os.sep, "/").lower()):
                            ds[:] = []
                            continue
                        if should_cancel and should_cancel():
                            return
                        # a415R：有界投递+放弃检查（消费侧取消/异常后 worker
                        # 不再卡死在满队列上——每次泄漏 8 线程的旧账）
                        while True:
                            if _abandoned[0]:
                                return
                            try:
                                out_q.put((r, fs), timeout=1.0)
                                break
                            except _q.Full:
                                continue
                except Exception as e:   # SMB 断连等：记录，其余子树继续
                    _err[0] = e
        finally:
            with _alock:
                _active[0] -= 1
                _last = _active[0] == 0
            if _last:
                # a415R2 N4：DONE 重试到消费侧放弃为止——原先 timeout=5
                # 丢弃后，消费侧只是暂时忙（没退出）就会死等到 300s 停滞
                # 误判（实测 300 文件 + 消费阻塞 10s 必现）
                while not _abandoned[0]:
                    try:
                        out_q.put(_DONE, timeout=1.0)
                        break
                    except _q.Full:
                        continue

    _n = min(N_WORKERS, len(seeds))
    _active[0] = _n
    for _i in range(_n):
        _th.Thread(target=_worker, daemon=True).start()
    if _n == 0:
        out_q.put(_DONE)   # 无子树：收录根直下文件即全部

    def _emit(r, fs):
        for f in fs:
            if should_cancel and should_cancel():
                raise Cancelled()
            rel = os.path.relpath(r + os.sep + f, root).replace(os.sep, "/")
            if _excluded(rel.lower()):
                continue
            yield os.path.join(r, f), rel

    _last_t = time.time()
    _last_dir = [root]
    _warned = False
    try:
        # 分片期收获的文件批先回放（a415R2 N16：入 try——回放期取消/异常
        # 也要走 finally 置 abandoned，否则 worker 永久泄漏）
        for r, fs in pre_batches:
            for x in _emit(r, fs):
                yield x
        while True:
            # 循环头检查：取消先于一切（a412 单测实锤）
            if should_cancel and should_cancel():
                raise Cancelled()
            try:
                item = out_q.get(timeout=5.0)
            except _q.Empty:
                item = None
            if item is _DONE:
                # a412：DONE 分支必须先查 cancel（producer/worker 边界见取消
                # 发 DONE 与消费侧 get 竞态，否则取消被吞、walk 假完成）
                if should_cancel and should_cancel():
                    raise Cancelled()
                if _err[0] is not None:
                    raise RuntimeError("目录扫描不完整（%s）" % _err[0])
                return
            if item is None:
                idle = time.time() - _last_t
                if idle >= 300:
                    raise RuntimeError(
                        "目录扫描 %.0fs 无进展——网盘停滞/断连（最后目录：%s）。"
                        "检查网络盘连接后重试" % (idle, _last_dir[0]))
                if idle >= 120 and not _warned:
                    _warned = True
                    say("  扫描 %.0fs 无进展（网盘大目录/停滞中，最后目录：%s）——"
                        "继续等待，超 300s 将判失败" % (idle, _last_dir[0]))
                continue
            r, fs = item
            _last_t = time.time()   # 拿到新目录=有进展
            _warned = False
            _last_dir[0] = r
            for x in _emit(r, fs):
                yield x
    finally:
        _abandoned[0] = True   # a415R：消费侧退出（含异常）→ worker 放弃投递


class Cancelled(Exception):
    pass


def _parse_cmd_file(p, src_roots=()):
    """Kbuild .cmd：`cmd_xxx.o := <cc> ... -c ... src.c`——命令行自带源文件
    路径（多 .c 合一 .o 的成员文件各有自己的 .cmd，天然正确）。返回源文件
    绝对路径或 None。
    a415 P0-2（内网报告 §2.2）：基准顺序——
    ① .cmd 所在目录（旧行为）
    ③ 候选源码根 src_roots（显式配置最优先；sbuilder/output 外挂形态，
      报告 §3.3）
    ② 后缀推断（a415R BUG-A：树内编译的 H11/H8 形态 source_roots 配
      "." 解析不了 arch/arm/... 相对路径——若 .cmd 所在目录恰好以
      dirname(src) 结尾，剥掉后缀即构建根；a415R2 N6：排在 ③ 后——
      产物树源码副本会劫持 ②）"""
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line.startswith("cmd_") or ":=" not in line:
                    continue
                cmd = line.split(":=", 1)[1]
                # 源文件 token：非 - 开头且是编译单元后缀（-o 目标要排除：
                # 其后缀是 .o 不在 _SRC 匹配里）
                for m in _SRC_TOKEN_RE.finditer(" " + cmd + " "):
                    src = m.group(1)
                    if src.startswith("-"):
                        continue
                    base = os.path.dirname(p)
                    cand = os.path.normpath(os.path.join(base, src))
                    if os.path.isfile(cand):
                        return cand
                    # ③ 候选源码根（Kbuild 路径相对源码根）。
                    # a415R2 N6/NEW-4：③ 提到 ② 前——G10 产物树里带源码副本
                    # （报告 §3.3 实测），② 先行会把单元劫到副本再被收录集
                    # 交集剔除=真源码整批丢失；③ 显式配置永远最优先
                    for sr in src_roots:
                        cand2 = os.path.normpath(os.path.join(sr, src))
                        if os.path.isfile(cand2):
                            return cand2
                    # ② 后缀推断：.cmd 目录尾 = 源路径的目录部分 → 剥出构建根
                    sdir = os.path.dirname(src).replace("/", os.sep)
                    if sdir:
                        bl = base.lower()
                        sl = sdir.lower()
                        if bl.endswith(sl) and len(bl) > len(sl):
                            root2 = base[:len(base) - len(sdir)].rstrip("\\/")
                            cand2 = os.path.normpath(os.path.join(root2, src))
                            if os.path.isfile(cand2):
                                return cand2
    except OSError:
        pass
    return None


def _read_symbols_from_o(o_path):
    """pyelftools 读 ELF 符号表：defined FUNC/OBJECT（T/t/D/d/B/b/R/r/C）。
    返回 [符号名]。文件非 ELF/损坏返回 []。"""
    from elftools.elf.elffile import ELFFile
    names = []
    with open(o_path, "rb") as f:
        elf = ELFFile(f)
        symtab = elf.get_section_by_name(".symtab")
        if symtab is None or not hasattr(symtab, "iter_symbols"):
            return []
        for sym in symtab.iter_symbols():
            name = sym.name
            if not name or name[0] in "$." or name.startswith("_GLOBAL_"):
                continue
            st = sym["st_info"]["type"]
            if st not in ("STT_FUNC", "STT_OBJECT"):
                continue
            if sym["st_shndx"] == "SHN_UNDEF":   # 引用不是定义
                continue
            if sym["st_size"] == 0 and st == "STT_FUNC":
                pass  # 别名/弱符号 size 0 也算定义
            names.append(name)
    return names


# ------------------------------------------------------------------ 收录范围
# a415（内网报告《收录方案定稿》档B）：把「索引目标」与「白名单来源」彻底
# 分开——include 收录 / artifact_roots 只读 .cmd.o 推白名单 / source_roots
# 是 .cmd 源路径解析基准 / header_roots 无条件全收 / fallback_full 兜无产物
# 目录 / exclude_names+exclude_paths 排除。配置三来源：工程 .fcpk-scope.json
# （团队共享，随 SVN 走）> 库目录 scope.json（UI 手选/导入保存）> 无=全量

def _detect_arch(root, say=None):
    """a415 P1-7（报告 §六·补）：arm/arm64 自动识别，返回 'arm'/'arm64'/None。
    判据优先级：①.config/autoconf 的 CONFIG_ARM64=y / CONFIG_ARM=y
    ②arch/<a> 下谁的 .o/.cmd 产物多 ③None=无法判定（配置占位符两个都收，
    慢但不会错）。kernel 根候选：kernel/kernel_sdk > kernel > root。
    a415R（审计#26）：逐候选试到底（原第一个判不出就放弃）"""
    say = say or (lambda _m: None)
    result = None
    for cand in ("kernel/kernel_sdk", "kernel", "."):
        kr = os.path.normpath(os.path.join(root, cand.replace("/", os.sep)))
        if not (os.path.isfile(os.path.join(kr, ".config"))
                or os.path.isdir(os.path.join(kr, "arch"))):
            continue
        # 判据 1：.config / autoconf（最快最准，三平台实测零误判）
        for cfg in (".config", "include/generated/autoconf.h",
                    "include/config/auto.conf"):
            p = os.path.join(kr, *cfg.split("/"))
            if not os.path.isfile(p):
                continue
            try:
                with open(p, encoding="utf-8", errors="replace") as f:
                    txt = f.read()
            except OSError:
                continue
            if "CONFIG_ARM64=y" in txt or "#define CONFIG_ARM64 1" in txt:
                say("  架构自动识别：arm64（判据：%s）" % cfg)
                return "arm64"
            if "CONFIG_ARM=y" in txt or "#define CONFIG_ARM 1" in txt:
                say("  架构自动识别：arm（判据：%s）" % cfg)
                return "arm"
        # 判据 2：arch/<a> 下谁的构建产物多（读到 20 个即止，秒级）
        hits = {}
        for a in ("arm", "arm64"):
            n = 0
            base = os.path.join(kr, "arch", a)
            if not os.path.isdir(base):
                continue
            for _r, _ds, _fs in os.walk(base):
                n += sum(1 for f in _fs if f.endswith((".cmd", ".o")))
                if n > 20:
                    break
            hits[a] = n
        if hits.get("arm64", 0) > hits.get("arm", 0):
            say("  架构自动识别：arm64（判据：arch 产物 %d vs %d）"
                % (hits["arm64"], hits.get("arm", 0)))
            return "arm64"
        if hits.get("arm", 0) > hits.get("arm64", 0):
            say("  架构自动识别：arm（判据：arch 产物 %d vs %d）"
                % (hits["arm"], hits.get("arm64", 0)))
            return "arm"
        result = result or None   # 本候选判不出：继续试下一个
    return result


def _norm_scope(cfg, root):
    """校验+归一 scope 配置。返回 (ok, scope|err_msg)。脏配置 (False, 原因)。
    a415R（审计#16/BUG-E）：严校验——include 非数组/字段拼错=显式 bad（原
    静默归一整根=一次手误绕过收录范围）；拒绝绝对路径/盘符/../ 段；'./x'
    'a//b' 规范化（原样导致 exclude_paths 失效）"""
    if not isinstance(cfg, dict):
        return False, "配置必须是 JSON 对象"

    def _lst(v, key):
        if v is None:
            return []
        if not isinstance(v, list):
            return None   # 字段存在但类型错：bad
        out = []
        for x in v:
            if not (isinstance(x, str) and x.strip()):
                continue
            p = x.strip().replace("\\", "/")
            if p.startswith("/"):
                return None   # 绝对路径（POSIX 形态）：越界
            segs = [s for s in p.split("/") if s not in ("", ".")]
            if not segs:
                out.append(".")   # "."/"./" = 整根（a415R2 N9：原条件反了
                continue          # 丢弃 "."、"\/" 反当根）
            if ":" in segs[0] or segs[0].startswith("\\\\"):
                return None   # 盘符/UNC：越界
            if any(s == ".." for s in segs):
                return None   # .. 逃逸登记根
            out.append("/".join(segs))
        return out
    inc = _lst(cfg.get("include"), "include")
    if inc is None:
        return False, "include 含非法路径（绝对路径/../）或类型错误"
    if not inc:
        return False, "include 为空"   # a415R2 N18：空数组显式 bad（原静默整根）
    fields = {}
    for k in ("artifact_roots", "source_roots", "header_roots",
              "fallback_full", "exclude_names", "exclude_paths"):
        v = _lst(cfg.get(k), k)
        if v is None:
            return False, "%s 含非法路径（绝对路径/../）或类型错误" % k
        fields[k] = v
    tier = str(cfg.get("tier") or "auto").strip().lower()
    if cfg.get("tier") is not None and tier not in ("whitelist", "full", "auto"):
        return False, "tier 只认 whitelist/full/auto"
    arch = str(cfg.get("arch") or "auto").strip().lower()
    if cfg.get("arch") is not None and arch not in ("auto", "arm", "arm64"):
        return False, "arch 只认 auto/arm/arm64"
    # a415R2 N18：未知键显式 bad（拼错 include→inlcude 曾静默整根收录）
    _known = {"version", "name", "tier", "arch", "include", "manual"} | set(fields)
    _unknown = [k for k in cfg if k not in _known]
    if _unknown:
        return False, "未知字段：%s" % "、".join(_unknown[:5])
    sc = {"version": 1,
          "name": str(cfg.get("name") or "")[:60] or "未命名范围",
          "tier": tier, "arch": arch,
          "manual": bool(cfg.get("manual")),
          "include": inc, **fields}
    return True, sc


def scope_store_path(root):
    """a415R（审计#13）：已存范围的独立存储位（DATA_DIR/nav-scopes/<md5>.json）
    ——不放库目录（删索引/数据清理会连带删掉用户手选/导入的范围）"""
    import hashlib as _hl
    d = os.path.join(_nav_root() + "-scopes")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return os.path.join(d, _hl.md5(os.path.normcase(
        os.path.abspath(root)).encode("utf-8")).hexdigest()[:16] + ".json")


def load_scope(root, store=None):
    """加载 scope：工程 .fcpk-scope.json > 独立存储位 scope.json（store=
    scope_store_path(root)）。返回 (scope|None, source)——
    source ∈ project/saved/''/bad:<err>。
    a415R（审计#20）：utf-8-sig 兼容 BOM（Windows 记事本写 JSON 常带）"""
    import json as _json
    p = os.path.join(root, SCOPE_FILE)
    if os.path.isfile(p):
        try:
            with open(p, encoding="utf-8-sig") as f:
                cfg = _json.load(f)
        except Exception as e:
            return None, "bad:%s" % str(e)[:80]
        ok, sc = _norm_scope(cfg, root)
        if ok:
            return sc, "project"
        return None, "bad:%s" % sc
    sp = store if store is not None else scope_store_path(root)
    if os.path.isfile(sp):
        try:
            with open(sp, encoding="utf-8-sig") as f:
                cfg = _json.load(f)
        except Exception as e:
            return None, "bad:%s" % str(e)[:80]
        if not isinstance(cfg, dict):
            return None, "bad:已存范围不是 JSON 对象"
        ok, sc = _norm_scope(cfg, root)
        if ok:
            return sc, "saved"
        return None, "bad:%s" % sc
    return None, ""


def detect_scope(root):
    """a416→a427（内网报告·用户重申设计）：原实现只认 sbuilder 布局，
    H11/H8（产物在源码树内、无 sbuilder/output/build）直接返回 None——
    build() 里 `if sc:` 整段白名单判档被跳过，明明扫到 3177 个 .cmd 仍
    全量索引（H11 实锤 ctags 写 450MB）。
    现改为：有内核根/sbuilder/常见源码目录即返回隐式 scope（tier=auto），
    由白名单优先判档接管——有中间文件必走白名单，零中间文件才全量。
    sbuilder 只是多填 artifact_roots/exclude_paths 的特例。
    返回 (scope|None, kind)；kind ∈ sbuilder / in-tree。"""
    has_sbuilder = os.path.isdir(os.path.join(root, "sbuilder", "output", "build"))
    kernel_roots = []
    for cand in ("kernel/kernel_sdk", "kernel"):
        p = os.path.join(root, *cand.split("/"))
        if os.path.isdir(os.path.join(p, "arch")) or                 os.path.isfile(os.path.join(p, ".config")):
            kernel_roots.append(cand)
            break
    # 判据放宽：有内核根/有 sbuilder/有常见源码目录 = 代码工程——返回
    # 隐式 scope 让白名单判档生效，绝不静默全量（a418 的"必须有内核根"
    # 门槛随之作废：tier=auto 下误检出不丢覆盖——零产物自动回全量）
    _has_code_dirs = any(
        os.path.isdir(os.path.join(root, d))
        for d in ("kernel", "uboot", "modules", "libs", "src", "source",
                  "app", "rootfs", "tools"))
    if not (has_sbuilder or kernel_roots or _has_code_dirs):
        return None, ""
    hdr = []
    for k in kernel_roots:
        hdr += [k + "/include", k + "/include/asm-generic",
                k + "/include/uapi/asm-generic",
                k + "/arch/${arch}/include",
                k + "/arch/${arch}/include/uapi"]
    if os.path.isdir(os.path.join(root, "uboot")):
        hdr.append("uboot/*/arch/arm/include")   # u-boot 无 arm64，一律 arm
    ex_p = []
    art_roots = []
    if has_sbuilder:
        art_roots = ["sbuilder/output/build"]
        ex_p = ["sbuilder/output"]
        if os.path.isdir(os.path.join(root, "sbuilder", ".buildroot-ccache")):
            ex_p.append("sbuilder/.buildroot-ccache")
    src_roots = list(kernel_roots)
    if os.path.isdir(os.path.join(root, "uboot")):
        # uboot 下真实源码根各平台命名不同（uboot_sdk/hik_uboot/hvb_uboot/
        # seeboot），同层还有 plat_private/release 等非源码目录——全纳入
        # （source_roots 只是解析基准，多列不影响正确性，漏列才解析失败）
        for d in sorted(os.listdir(os.path.join(root, "uboot"))):
            if d.startswith("."):
                continue
            if os.path.isdir(os.path.join(root, "uboot", d)):
                src_roots.append("uboot/" + d)
    src_roots.append(".")
    sc = {"version": 1,
          "name": ("sbuilder 方案（自动检测）" if has_sbuilder
                   else "源码树内产物（自动检测）"),
          "tier": "auto", "arch": "auto",
          "include": ["."],
          "artifact_roots": art_roots,
          "source_roots": src_roots,
          "header_roots": hdr,
          "fallback_full": [],
          "exclude_names": ["test", "release_tmp"],
          "exclude_paths": ex_p}
    return sc, ("sbuilder" if has_sbuilder else "in-tree")


def _expand_patterns(patterns, dirs_set):
    """scope 路径模式（支持 ${arch} 已替换后的通配，如
    uboot/*/arch/arm/include）→ 展开为命中目录集合。
    a415R（审计#5/BUG-C）：①目录集须含**祖先目录**（arch/arm/include 直下
    零文件、头文件全在 asm/ 子目录——原样匹配不到，u-boot asm 整区静默丢）
    ②按路径段逐段 fnmatch（原整串 fnmatch 的 * 跨 /，语义错）③大小写
    不敏感（Windows 口径统一）"""
    import fnmatch as _fnm
    ds = {d.lower() for d in dirs_set}
    hit = set()
    for pat in patterns:
        if not pat or pat == ".":
            continue
        segs = [s.lower() for s in pat.split("/")]
        for d in ds:
            dd = d.split("/") if d else []
            if len(dd) != len(segs):
                continue
            if all(_fnm.fnmatchcase(part, seg)
                   for part, seg in zip(dd, segs)):
                hit.add(d)
    return hit


def _scope_summary(sc):
    parts = ["%s（%s）" % (sc.get("name", ""), sc.get("tier", ""))]
    if sc.get("include"):
        parts.append("收录 %d 目录" % len(sc["include"]))
    if sc.get("artifact_roots"):
        parts.append("产物源 %d" % len(sc["artifact_roots"]))
    if sc.get("header_roots"):
        parts.append("头文件区 %d" % len(sc["header_roots"]))
    if sc.get("fallback_full"):
        parts.append("兜底 %d" % len(sc["fallback_full"]))
    if sc.get("exclude_paths") or sc.get("exclude_names"):
        parts.append("排除 %d+%d"
                     % (len(sc.get("exclude_paths") or []),
                        len(sc.get("exclude_names") or [])))
    return " · ".join(p for p in parts if p)


def build(root, log=None, progress=None, should_cancel=None,
          backend="auto", scope=None):
    """收录范围化建库（a415 档B）。scope：None=自动发现（工程
    .fcpk-scope.json > 已存范围 > 全量）；dict=内联配置（API 层建库成功后
    落盘独立存储位）。log=callable(str)；progress=callable(done,total,label)。
    返回 meta dict（失败抛异常）。"""
    say = log or (lambda _m: None)
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        raise RuntimeError("目录不存在：%s" % root)
    ld = lib_dir(root)
    os.makedirs(ld, exist_ok=True)

    def prog(pct, label):
        if progress:
            progress(int(pct), 100, label)

    # ---- 阶段 0：收录范围解析（a415 档B，内网报告《收录方案定稿》）----
    sc, sc_src = None, ""
    if scope is not None:
        if not isinstance(scope, dict):
            raise RuntimeError("收录范围配置必须是 JSON 对象")
        _ok, _sc2 = _norm_scope(scope, root)
        if not _ok:
            raise RuntimeError("收录范围配置不合法：%s" % _sc2)
        sc = _sc2
        sc_src = "inline"
    else:
        sc, sc_src = load_scope(root)
        if sc_src.startswith("bad:"):
            say("  ⚠ scope 配置解析失败（%s）——按全量建库" % sc_src[4:])
            sc, sc_src = None, ""
    if sc is None:
        # a416→a427：零配置形态识别——结构检测（sbuilder 外挂/源码树内产物）
        _dsc, _dkind = detect_scope(root)
        if _dsc:
            sc = _dsc
            sc_src = "detect"
    if sc is None:
        # a427（内网报告·用户重申设计·重点）：detect_scope() 放宽后极少数树
        # 仍返回 None（根下连常见源码目录名都没有）。此时**也必须**有隐式
        # scope，否则 `if sc:` 整段白名单判档被跳过——扫到 .cmd/.o 仍全量
        # 索引（H11「自动」档 450MB 的根因）。铁律：只要有白名单一定用白名单
        sc = {"version": 1, "name": "自动（隐式范围）",
              "tier": "auto", "arch": "auto",
              "include": ["."], "artifact_roots": [],
              "source_roots": ["."], "header_roots": [],
              "fallback_full": [],
              "exclude_names": [], "exclude_paths": []}
        sc_src = "implicit"
    if sc:
        _src_label = {"project": "工程配置 " + SCOPE_FILE,
                      "saved": "已保存的范围",
                      "inline": "本次指定",
                      "implicit": "自动（隐式范围）"}.get(sc_src)
        if sc_src == "detect":
            _src_label = "自动检测（%s 方案）" % _dkind
        say("收录范围：%s［来源：%s］" % (_scope_summary(sc),
                                        _src_label or sc_src))
        # P1-7：${arch} 占位替换（a415R 审计#26/#4：arch 钉住值优先；全列表
        # 字段替换；判不出时**按 key 各自展开**——原三组结果互相污染）
        _arch_keys = ("include", "artifact_roots", "source_roots",
                      "header_roots", "fallback_full", "exclude_paths")
        if any("${arch}" in p for k in _arch_keys for p in sc[k]):
            arch = sc["arch"] if sc["arch"] in ("arm", "arm64") \
                else _detect_arch(root, say)
            if not arch:
                say("  架构无法判定——arm/arm64 都收（慢但不会错）")
            for k in _arch_keys:
                out_l = []
                for p in sc[k]:
                    if "${arch}" not in p:
                        out_l.append(p)
                    elif arch:
                        out_l.append(p.replace("${arch}", arch))
                    else:
                        out_l.extend(p.replace("${arch}", a)
                                     for a in ("arm", "arm64"))
                sc[k] = out_l
    # tier=auto 的判档**后置到 index walk 之后**（a415R 审计#6/BUG-D：原用
    # shallow_probe，其 60 文件即早退 → code_files 封顶 60，<5万恒真=auto
    # 恒判 full，大库收录范围被整体绕过）

    # ---- 阶段 1：编译产物白名单 ----
    # 权威序：.cmd 命令行（自描述）> .o 同目录同名 > .o basename 全局唯一
    # （海思等 out-of-tree：.o 在 out/obj、.c 在 source——同目录映射失效，
    # basename 全局唯一兜底；basename 多处同名视为歧义放弃）
    say("阶段 1/4：扫描编译产物（.cmd/.o）…")
    prog(2, "扫描编译产物")
    compiled = {}       # rel_src_posix -> {"o": rel_o, "src": "cmd"|"omap"|"bmap"}
    o_files = []        # 相对 .o（符号表阶段用；含 artifact_roots 的 .o）
    cmd_count = cmd_files = o_count = 0
    unit_by_base = {}   # basename（无后缀）-> [rel, ...] 编译单元源文件
    pending_o = []      # 未被 .cmd/同目录覆盖的 .o
    all_rels = set()    # a411：全量 rel 集合（同目录同名映射走 set 查，零网络 I/O）
    dirs_files = {}     # a415：rel 目录 → [文件名]（档B 同目录 .h 补收）
    all_dirs = set()    # a415：出现过的目录集合（header_roots glob 展开用）
    _src_roots_abs = [os.path.normpath(os.path.join(
        root, s.replace("/", os.sep))) for s in (sc["source_roots"] if sc else [])]
    wstat = {"pruned": 0}
    _aux_n = 0            # a423：非 C/C++ 中间文件计数（白名单优先判据）
    _last_prog = 0.0    # 用户令：1s 一拍的过程显示计时
    _last_tot = -1      # a412：计数停滞可见——大目录/非代码区穿越时计数
    _last_tot_t = time.time()   # 不动（walk 活着），标签提示"无新增"防误判卡死

    def _eat_cmd(abs_p, rel):
        """a415：.cmd 消费抽出（index walk 与 artifact walk 共用）。
        返回 True=解析出源文件。"""
        src = _parse_cmd_file(abs_p, _src_roots_abs)
        if not (src and os.path.isfile(src)):
            return False
        srel = os.path.relpath(src, root).replace(os.sep, "/")
        base, _ = os.path.splitext(rel)
        # R16-1（高，实锤：Kbuild 点前缀幻影路径）：Kbuild 命名是
        # `.foo.o.cmd`（隐藏文件）——splitext 只剥 .cmd 得 `.foo.o`，
        # 幻影点让阶段 3/nm 导入的 .o 映射两连 miss。剥**文件名**
        # 的点前缀。R17-1（实锤：顶层 .cmd 崩）：rsplit 二元 unpack
        # 对不含 / 的顶层路径抛 ValueError 建库必败——先判含 /
        if "/" in base:
            dsep, fbase = base.rsplit("/", 1)
            if fbase.startswith("."):
                base = dsep + "/" + fbase[1:]
        elif base.startswith("."):
            base = base[1:]
        compiled.setdefault(srel, {"o": base, "src": "cmd"})
        return True

    # ① index walk：收录目标（scope.include；无 scope=全 root）
    for abs_p, rel in _walk_files(
            root, subs=(sc["include"] if sc else None),
            should_cancel=should_cancel, say=say,
            excl_names=(sc["exclude_names"] if sc else ()),
            excl_paths=(sc["exclude_paths"] if sc else ()), stats=wstat):
        all_rels.add(rel)
        low = rel.rsplit("/", 1)[-1].lower()   # a415R2 N2：移出 if sc（原 _fn 仅 scope 分支赋值，全量建库必崩）
        if sc:   # a415R（审计#29）：全量建库不建字典白占内存
            _d = rel.rpartition("/")[0]
            dirs_files.setdefault(_d, []).append(rel.rsplit("/", 1)[-1])
            # a415R（审计#5）：祖先目录一并入集（include 直下零文件的
            # header_root 通配匹配靠它）
            while _d not in all_dirs:
                all_dirs.add(_d)
                _d = _d.rpartition("/")[0]
        if low.endswith(".cmd"):
            cmd_files += 1           # R17-4：文件名计数（stale 同口径）
            if _eat_cmd(abs_p, rel):
                cmd_count += 1
        elif low.endswith(".o"):
            o_files.append(rel)
            o_count += 1
            # a411：同目录同名映射延后到 walk 结束用集合查（原逐 .o
            # os.path.isfile——网盘上 2.3 万 .o × 每个多次 stat = 数万次
            # SMB 往返，扫描像卡死）
        elif any(low.endswith(e) for e in _AUX_ARTIFACT_EXTS):
            _aux_n += 1   # a423：非 C/C++ 中间文件（.pyc/.class/.js.map…）
        else:
            b, ext = os.path.splitext(low)
            if ext in _UNIT_EXTS | {".s"}:   # a415R（审计#7/BUG-A）：.S 汇编单元也进 basename 兜底池
                unit_by_base.setdefault(b, set()).add(rel)
        # 用户令：全部过程显示 1s 一更新、同一行、不刷屏——中间进度走
        # prog()（前端 progress 文本同一行刷新），say() 只留阶段头和终态
        # a411：min(28,_tot/800) 在 2.2 万文件即顶格 30%，之后进度条假死
        # ——改渐进逼近 30%（单调递增永不到顶，扫描活着条就动）
        _tot = cmd_count + o_count + len(unit_by_base)
        _now = time.time()
        if _tot and _now - _last_prog >= 1.0:
            _last_prog = _now
            if _tot != _last_tot:
                _last_tot = _tot
                _last_tot_t = _now
            _stall = int(_now - _last_tot_t)
            _hint = ("（%ds 无新增——大目录/非代码区穿越中，未卡死）" % _stall) \
                if _stall >= 60 else ""
            prog(2 + 28.0 * _tot / (_tot + 8000),
                 "扫描中：产物 %d（.cmd %d/.o %d）· 源文件 %d%s" % (
                     _tot, cmd_count, o_count, len(unit_by_base), _hint))

    # ② artifact walk（a415 档B：sbuilder/output 这类产物外挂树——14 万
    # 源码不进索引，但 .cmd/.o 是白名单真源。报告 §3.3：2285 个 .o.cmd
    # 中 2280 个靠 source_roots 基准解析回 kernel/kernel_sdk）。
    # a415R（审计#19）：exclude_paths 里非产物根祖先的项照传（精确排除
    # test/sys 这类环目录），产物根本身/其祖先剔除（否则整个产物源被剪）
    if sc and sc["artifact_roots"]:
        say("  产物源扫描（只读 .cmd/.o，不索引源码）：%s"
            % "、".join(sc["artifact_roots"]))
        _arts_n = [a.lower().strip("/") for a in sc["artifact_roots"]]

        def _keep_ep(ep):
            # a415R2 N10：只剔除产物根**祖先**（剔除产物根本身会让整树被
            # 剪）；产物根内部的排除（test/sys 环）必须保留
            return not any(a == ep or a.startswith(ep + "/") for a in _arts_n)
        _ep2 = tuple(ep for ep in
                     (p.strip("/").lower() for p in sc["exclude_paths"])
                     if ep and _keep_ep(ep))
        _w2 = {"pruned": 0}
        for abs_p, rel in _walk_files(
                root, subs=sc["artifact_roots"],
                should_cancel=should_cancel, say=say,
                excl_names=sc["exclude_names"], excl_paths=_ep2, stats=_w2):
            if rel in all_rels:
                continue   # a415R2 N20：include∩artifact 重叠区已消费，不双计
            low = rel.rsplit("/", 1)[-1].lower()
            if low.endswith(".cmd"):
                cmd_files += 1
                if _eat_cmd(abs_p, rel):
                    cmd_count += 1
            elif low.endswith(".o"):
                o_files.append(rel)
                o_count += 1
        wstat["pruned"] += _w2.get("pruned", 0)
    if wstat.get("pruned"):
        say("  ⚠ 环防护剪枝 %d 个目录（SMB 符号链接自链，报告 §2.1）"
            % wstat["pruned"])

    # a411：同目录同名映射（walk 内收集全量集合，set 查零 I/O）。
    # a415R（审计#7）：候选后缀补 .S/.s（entry.S 靠 .o 同名兜底）+ 大小写
    # 不敏感（.o 与 .S 大小写形态不保证一致——用 lower 索引一次建好）
    _rel_by_l = {r.lower(): r for r in all_rels}
    for orel in o_files:
        stem = orel[:-2]
        for ext in (".c", ".cpp", ".cc", ".cxx", ".S", ".s"):
            hit = _rel_by_l.get((stem + ext).lower())
            if hit:
                compiled.setdefault(hit, {"o": orel, "src": "omap"})
                break
        else:
            pending_o.append(orel)
    # basename 全局唯一兜底（out-of-tree）
    for orel in pending_o:
        b = os.path.splitext(os.path.basename(orel))[0].lower()
        hits = unit_by_base.get(b)
        if hits and len(hits) == 1:
            compiled.setdefault(next(iter(hits)), {"o": orel, "src": "bmap"})
            # a415R2 N3：值已是 set（#15 改），hits[0] 会 TypeError——
            # 海思 out/obj/libtool .libs/产物树 .o 全走这条，撞上必崩

    # ③ 档B 最终清单（tier=whitelist）：编译单元 + 同目录头 + header_roots
    # 无条件全收 + fallback_full 兜底（报告 §4.1）。
    # a423（内网报告·用户令「只要有白名单一定用白名单，决不允许私自全建」）
    # **白名单优先**：收录集内扫到任何中间文件（.cmd/.o/.pyc/.class/
    # .js.map…或 __pycache__/node_modules 等产物目录）→ 必走白名单，
    # tier 字段（含显式 full）不再能放行全量；零中间文件=唯一合法降档。
    # 原 a415R 的"≥5 万代码文件且 compiled"阈值判档作废（H11 实锤：手选
    # 6 目录 tier=full 私自全建，tags 撑到 841MB）
    if sc:
        _has_artifact = bool(compiled) or o_count > 0 or cmd_files > 0 \
            or bool(_aux_n) or wstat.get("artifact_dirs", 0) > 0
        if _has_artifact and (compiled or cmd_files or o_count):
            # C/C++ 白名单可推导（.cmd/.o）→ 必走白名单，tier（含显式
            # full）不放行——"决不允许私自全建"
            sc["tier"] = "whitelist"
            say("  收录档位：白名单（发现 %d 个 .cmd · %d 个 .o · %d 个其他"
                "中间文件）" % (cmd_files, o_count, _aux_n))
        elif _has_artifact:
            # a423 折中：仅非 C/C++ 中间文件（.pyc 等）——白名单暂无法从
            # 这些推导，按报告字面强制白名单会让 Python 工程一律报错不可
            # 建。全量收录但**显式告警**（不静默，用户可看到为什么全量）
            sc["tier"] = "full"
            # a423R BUG-2：计数并上产物目录（.pyc 全在被剪的 __pycache__
            # 里，散置后缀恒 0——原文案"发现 0 个"自相矛盾）
            say("  ⚠ 发现 %d 个非 C/C++ 中间文件/产物目录（.pyc 等）但暂无法"
                "推导编译白名单（只支持 Kbuild .cmd/.o）——按全量收录"
                % (_aux_n + wstat.get("artifact_dirs", 0)))
        else:
            sc["tier"] = "full"
            say("  收录档位：全量（收录集内未发现任何中间文件——唯一降档条件）")
    if wstat.get("soft_skipped"):
        say("  ⚠ 跳过 %d 个不可读目录（悬空符号链接/权限拒绝——如 rootfs 里"
            "指向宿主机绝对路径的 usr/lib64，不影响其余子树）"
            % wstat["soft_skipped"])
    final_files = None
    if sc and sc["tier"] == "whitelist":
        _under = lambda r, ds: any(r == d or r.startswith(d + "/")
                                   for d in ds)
        # a415R2 N17/BUG-B2：逐 pattern 展开计数——原按组并集计数，同组
        # 一个命中其余 typo 全静默（H8 arm/arm64 配错丢 269 头文件场景）
        for _pats, _label in ((sc["header_roots"], "头文件区"),
                              (sc["fallback_full"], "兜底区")):
            for pat in _pats:
                _pset = _expand_patterns([pat], all_dirs)
                if not sum(1 for r in all_rels if _under(r.lower(), _pset)):
                    say("  ⚠ %s未命中收录集（0 文件）：%s" % (_label, pat))
        # a415R（审计#3）：单元与收录集求交——.cmd 解析出的源在 include
        # 之外/排除区（sbuilder/output 的 buildroot 源码副本）绝不进 ctags
        # 清单；compiled 全量保留供符号表阶段用。
        # a415R2 N19/CASE-1：交集按小写归一（include 写 kernel 磁盘 Kernel
        # 时原大小写敏感求交全丢）
        _units = {_rel_by_l[u.lower()] for u in compiled.keys()
                  if u.lower() in _rel_by_l}
        if not _units:
            # a423（内网报告 3.4）：有中间文件但白名单为空=配置病（多半
            # source_roots 没写源码根）——明确报错绝不静默降档全量（自动
            # 降档会让 12 万文件"看起来成功"，用户无从知道配置错了）
            _hint = ""
            if cmd_files or o_count:
                _hint = ("（收录集内扫到 %d 个 .cmd / %d 个 .o，但源路径解析"
                         "不到收录集内——请检查 source_roots 是否包含源码根，"
                         "如 kernel/kernel_sdk）" % (cmd_files, o_count))
            raise RuntimeError(
                "白名单为空%s。若确实要全量收录，请显式清空 include 或改用"
                "小工程全量档" % _hint)
        if len(_units) < len(compiled):
            say("  ⚠ %d 个白名单单元在收录集外（产物树源码副本/排除区），"
                "不进索引" % (len(compiled) - len(_units)))
        _same_h = set()
        for u in _units:
            ud = u.rpartition("/")[0]
            for fn2 in dirs_files.get(ud, ()):
                if fn2.lower().endswith((".h", ".hpp", ".hh")):
                    _same_h.add((ud + "/" + fn2) if ud else fn2)
        _hdr = _expand_patterns(sc["header_roots"], all_dirs)
        _fb = _expand_patterns(sc["fallback_full"], all_dirs)
        # a423R BUG-1（审计实锤：手选 [kernel,tools] 时 tools 零单元被静默
        # 整目录剔除，与选择器"全部代码递归收录"承诺直接矛盾）：手选范围
        # （manual）按收录目录逐个核覆盖——零单元目录自动整目录兜底；
        # 低覆盖（<50%）目录显式告警提示用 JSON 配 fallback_full
        if sc.get("manual"):
            for d in sc["include"]:
                if d == ".":
                    continue
                dl = d.lower()
                in_u = sum(1 for u in _units
                           if u.lower() == dl or u.lower().startswith(dl + "/"))
                n_code = sum(
                    1 for r in all_rels
                    if (r.lower() == dl or r.lower().startswith(dl + "/"))
                    and os.path.splitext(r)[1].lower() in CODE_EXTS)
                if n_code and in_u == 0:
                    _fb.add(dl)
                    say("  · %s 无编译单元——整目录兜底收录（手选承诺）" % d)
                elif n_code and in_u < n_code * 0.5:
                    say("  ⚠ %s 白名单覆盖 %d/%d——如需全收，导入 JSON 配 "
                        "fallback_full" % (d, in_u, n_code))
        final_files = _units | _same_h \
            | {r for r in all_rels if _under(r.lower(), _hdr)} \
            | {r for r in all_rels if _under(r.lower(), _fb)}
        say("  档B清单：单元 %d · 同目录头 %d · 头文件区/兜底 %d = 共 %d 文件"
            % (len(_units), len(_same_h), len(final_files) - len(_units | _same_h),
               len(final_files)))
        if not final_files:
            raise RuntimeError("收录清单为空——检查 include/排除配置")

    # a415R2 WB#22b：最终 ctags 清单（点路径过滤后）**在写 manifest 前**
    # 拦截空清单——原 full 档空树走到阶段 2 才报错，manifest 已清空而
    # meta 未动 → status 误判 indexed。阶段 2 直接复用 _list_pool
    def _dot_path(rel):
        return any(seg.startswith(".") for seg in rel.split("/"))

    _list_pool = [r for r in (final_files if final_files is not None
                              else all_rels) if not _dot_path(r)]
    if not _list_pool:
        raise RuntimeError("收录清单为空——检查 include/排除配置")

    mf = {"version": 1, "root": root, "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
          "compiled": compiled, "cmd_count": cmd_count, "o_count": o_count}
    _write_json(os.path.join(ld, "manifest.json"), mf)
    say("  编译白名单：%d 个源文件（.cmd %d / .o %d）"
        % (len(compiled), cmd_count, o_count))
    if not compiled:
        say("  未发现构建产物——跳转按启发式排序（基线编译后重建可精确化）")

    # ---- 阶段 2：ctags（-L 文件清单）----
    say("阶段 2/4：ctags 全量索引（%s）…" % NAV_LANGS)
    prog(30, "ctags 索引")
    tags_tmp = os.path.join(ld, "tags.tmp")
    tags = os.path.join(ld, "tags")
    # a415 P0-3（报告 §2.3 实测：-R root 的 ctags 撞同一个 SMB 自链环，
    # test/sys 子树 300s 不结束）：改 -L 文件清单——范围控制只有 _walk_files
    # 一处（排除/环防护/收录规则单点），阶段 1 收录什么 ctags 就吃什么，
    # 不再出现「阶段 1 排除了、阶段 2 又收进来」。点文件跳过对齐旧
    # --exclude=.* 语义（a369R）
    listfile = os.path.join(ld, "files.txt")
    _n_list = 0
    # a415R（审计#23）：点语义过滤已前移（manifest 前的 _list_pool）；此处
    # 只写清单。a415R2 N21：文件名含孤立代理字符时跳过该文件（原整库失败）
    with open(listfile, "w", encoding="utf-8") as _lf:
        for _rl in _list_pool:
            try:
                _lf.write(os.path.join(root, _rl.replace("/", os.sep)) + "\n")
            except UnicodeEncodeError:
                continue
            _n_list += 1
    if _n_list == 0:
        try:
            os.remove(listfile)
        except OSError:
            pass
        raise RuntimeError("收录清单为空——检查 include/排除配置")
    cmd = [_CTAGS_EXE, "--languages=" + NAV_LANGS,
           "--fields=+Kn", "--extras=+f",
           "-L", listfile, "-f", tags_tmp]
    # a361（用户实锤：30% 死等无文件进度）：大库 ctags 阶段数分钟只有一句
    # "ctags 索引"——心跳线程监控 tags.tmp 增长，每 3 秒报已写 MB，死等变
    # 活进度；ctags 完成后心跳自停
    # a412（用户实锤：取消后 ctags 阶段无法取消）：subprocess.run 阻塞期
    # 取消全程无效（R15-3 只在跑完后补查）——改 Popen，心跳 1s 查 cancel
    # 即杀进程，网盘大库数分钟的 ctags 全程可取消
    import threading as _th
    _hb_stop = _th.Event()
    try:
        env = dict(os.environ)
        env["LC_ALL"] = "C"
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                creationflags=0x08000000, env=env)
    except FileNotFoundError:
        raise RuntimeError("ctags.exe 缺失（vendor/ctags/）")
    def _heartbeat():
        _last = -1
        while not _hb_stop.wait(1.0):   # 用户令：1s 一拍
            if should_cancel and should_cancel():
                try:
                    proc.kill()
                except Exception:
                    pass
                return
            try:
                sz = os.path.getsize(tags_tmp) / 1048576
            except OSError:
                sz = 0
            if int(sz) != _last:
                _last = int(sz)
                prog(30 + min(45, sz / 10), "ctags 写入 %d MB" % _last)
    _hb = _th.Thread(target=_heartbeat, daemon=True)
    _hb.start()
    try:
        out_b, _ = proc.communicate(timeout=3600)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except Exception:
            pass
        proc.communicate()
        raise RuntimeError("ctags 超时（60 分钟）——目录过大？")
    finally:
        _hb_stop.set()
    # R15-3（实锤：取消被吞）：已取消则不落盘 tags/不写 meta（半成品库会被
    # status 误判 indexed）；a412 起取消在阻塞期内就杀进程，这里统一收尾
    if should_cancel and should_cancel():
        try:
            os.remove(tags_tmp)
        except OSError:
            pass
        raise Cancelled()
    if not os.path.isfile(tags_tmp):
        _e = ""
        try:
            _e = (out_b or b"").decode("utf-8", "replace")
        except Exception:
            pass
        raise RuntimeError("ctags 未产出 tags（rc=%s）：%s"
                           % (proc.returncode, _e[:200]))
    for _i in range(3):
        try:
            os.replace(tags_tmp, tags); break
        except OSError:
            if _i == 2: raise
            time.sleep(0.05)
    tag_lines = 0
    with open(tags, encoding="utf-8", errors="replace") as f:
        for _ln in f:
            if not _ln.startswith("!"):   # a415R（审计#22）： !_TAG_ 伪标签不计符号数
                tag_lines += 1
    say("  tags：%d 个符号 / %.1f MB" % (tag_lines, os.path.getsize(tags) / 1048576))
    prog(75, "ctags 索引完成")

    # a365R2（用户追问 Linux 无 .gitignore 的放大）：生成代码内容指纹黑名单
    # ——rg 按文件头指纹（Cython/lex/yacc/protobuf/pybind/SWIG 常见标记）
    # 一次性扫出生成文件清单存库目录；引用结果按此过滤（tags 收录集实测
    # 含产物——ctags 对生成 .c 一样收符号，域过滤无效；目录名排除误伤
    # SDK out/src 真源码。内容指纹不猜目录、按文件自身特征判——两个错
    # 误方向（硬编码目录/文件名模式）都实测翻车后的正解）
    _gen = set()
    try:
        rgp = os.path.normpath(os.path.join(os.path.dirname(_CTAGS_EXE), "..", "rg.exe"))
        fingerprints = ["Generated by Cython", "A lexical scanner generated by",
                       "Generated by the protocol buffer compiler",
                       "/* Generated by pybind11", "This file was generated by SWIG",
                       "auto-generated", "AUTOGENERATED"]
        # R28-2（实锤：清单 7 项只传 5 个 -e）：循环全量传，下标手写漏
        # index 5/6（auto-generated/AUTOGENERATED 永不生效）
        # a372（用户实锤：build/_cython/routes.c 4.06M 恰超 4M 上限被
        # max-filesize 跳过——指纹头明明有 "Generated by Cython" 却漏进
        # 黑名单，引用混入 35 条生成文件命中）→ 32M。写盘带 scan_max 供
        # 旧库重扫判定（references 读到 scan_max 不一致即自动补扫）
        # a415：指纹扫描同走收录范围（原 -- root 在 G10 全树 14 万文件上
        # 白扫）；a415R（审计#8）：排除规则同步成 rg -g；a415R2 N8/WB#8b：
        # rg 以 root 为 cwd + **相对路径**——-g '!x/**' 按 cwd 锚定，原先
        # 绝对路径参数下 exclude_paths 的 glob 永远匹配不上
        _rg_paths = (list(sc["include"]) if sc else ["."])
        _rg_g = ["-g", "!**/node_modules/**", "-g", "!**/.git/**"]
        if sc:
            for ep in sc["exclude_paths"]:
                _rg_g += ["-g", "!%s/**" % ep.strip("/")]
            for en in sc["exclude_names"]:
                _rg_g += ["-g", "!**/%s/**" % en]
        rcg = subprocess.run(
            [rgp, "-l", "--no-messages", "--no-ignore", "-F",
             "--max-filesize", "32M", "--glob-case-insensitive",
             "-g", "*.c", "-g", "*.cc", "-g", "*.cpp", "-g", "*.h", "-g", "*.py"]
            + _rg_g
            + sum([["-e", fp] for fp in fingerprints], [])
            + ["--"] + _rg_paths,
            cwd=root,
            capture_output=True, timeout=300, creationflags=0x08000000,
            env={"LC_ALL": "C", **os.environ})
        for pl in (rcg.stdout or b"").decode("utf-8", "replace").splitlines():
            if pl.strip():
                # a415R3 BUG-1：rg 以 root 为 cwd 后输出是相对路径，原样
                # normcase 进 gen_files.json → references 消费端拿绝对路径
                # 比对永远 miss=生成文件命中全部漏滤。写端归一成绝对路径
                _gp = pl.strip()
                if not os.path.isabs(_gp):
                    _gp = os.path.join(root, _gp)
                _gen.add(os.path.normcase(os.path.normpath(_gp)))
    except Exception:
        _gen = set()
    _write_json(os.path.join(ld, "gen_files.json"),
                {"generated": sorted(_gen), "scan_max": _GEN_SCAN_MAX})
    if _gen:
        say("  生成文件黑名单：%d 个（Cython/lex/protobuf 等指纹）" % len(_gen))

    # ---- 阶段 3：ELF 符号表（pyelftools；缺库/失败降级）----
    say("阶段 3/4：读取 .o 符号表（符号级消歧）…")
    prog(78, "符号表")
    symbols = {}
    sym_ok = False
    try:
        import elftools  # noqa. F401
        sym_ok = True
    except ImportError:
        say("  pyelftools 未安装——跳过符号级消歧（不影响跳转，白名单仍生效）")
    # a390（用户实锤：阶段 3 没有过程显示）：白名单→.o 映射构建按文件数
    # 报进度——大库数千条可见推进；无 .o 时显式两步文案（不再是两行秒过）
    o_rel_to_src = {}
    _mi, _mt = 0, len(compiled)
    for srel, info in compiled.items():
        o_rel_to_src[info["o"]] = srel
        _mi += 1
        if _mt and _mi % 500 == 0:
            prog(78 + 2 * _mi / max(1, _mt), "白名单映射 %d/%d" % (_mi, _mt))
    if not o_files:
        say("  编译产物核对：白名单 %d 项，本工程无 .o——符号级消歧不适用" % _mt)
        say("  （跳转按 启发式排序：本文件 static > 编译白名单 > 路径深度）")
    else:
        say("  符号表候选 .o：%d 个（白名单 %d 项）" % (len(o_files), _mt))
    if sym_ok and o_files:
        done = 0
        used = 0
        for orel in o_files:
            if should_cancel and should_cancel():
                raise Cancelled()
            done += 1
            if done % 100 == 0:
                prog(78 + 20 * done / max(1, len(o_files)), "符号表 %d/%d" % (done, len(o_files)))
            o_abs = os.path.join(root, orel.replace("/", os.sep))
            try:
                names = _read_symbols_from_o(o_abs)
            except Exception:
                continue            # 非 ELF（PE .obj 等）跳过
            srel = o_rel_to_src.get(orel.rsplit(".", 1)[0] + ".o") or o_rel_to_src.get(orel)
            if srel is None:
                # .o 没有白名单映射（如合并目标）——仍记录 o 相对路径
                srel = ""
            used += 1
            for n in names:
                lst = symbols.setdefault(n, [])
                if srel and srel not in lst:
                    lst.append(srel)
        say("  符号表：%d 符号 / %d 个 .o" % (len(symbols), used))
    _write_json(os.path.join(ld, "symbols.json"),
                {"version": 1, "symbols": symbols})

    # ---- 阶段 4：sqlite 快查索引（a390 三档后端；auto 按符号数判档）----
    # ctags-mem-v2 实测：600 万符号全量 dict ≈ 8GB 常驻；sqlite 0~4ms/50MB
    _bk_user = (backend or "auto").strip().lower()
    # a410（用户令：不允许全量方案）：memory 入参一律按 auto 重判
    # （api 层已显式拒，这里防御旧调用方）；只留 readtags/sqlite 两档
    if _bk_user == "memory":
        _bk_user = "auto"
    if _bk_user not in ("auto", "readtags", "sqlite"):
        _bk_user = "auto"
    _was_auto = _bk_user == "auto"
    if _was_auto:
        # a407：无 sqlite3 能力（旧版 exe 打包缺件）大库自动 readtags——
        # 不出现吓人的"构建失败"字样（readtags 查询速度相近，实测不慢）
        # a410：全量方案下线——小库也走 readtags（零建库成本，查询同级）
        if sqlite_capable():
            _bk_user = "sqlite" if tag_lines >= 200000 else "readtags"
        else:
            _bk_user = "readtags"
            if tag_lines >= 200000:
                say("  本环境未内置 sqlite3（旧版打包缺件，升级新版修复）"
                    "——大库自动 readtags 模式（查询速度相近）")
    db_path = os.path.join(ld, "tags.db")
    if _bk_user == "sqlite":
        say("阶段 4/4：sqlite 快查索引（%d 符号，大库低内存模式）…" % tag_lines)
        try:
            _build_tag_db(tags, db_path, say, prog)
        except ImportError as e:
            say("  本环境未内置 sqlite3（旧版打包缺件，升级新版修复）"
                "——已用 readtags 模式（查询速度相近）：%s" % str(e)[:60])
            _bk_user = "readtags"
            try:
                if os.path.isfile(db_path):
                    os.remove(db_path)
            except OSError:
                pass
        except Exception as e:
            # 建库失败回退 readtags（tags 永远可用）
            say("  tags.db 构建失败（%s）——回退 readtags 模式" % str(e)[:120])
            _bk_user = "readtags"
            try:
                if os.path.isfile(db_path):
                    os.remove(db_path)
            except OSError:
                pass
    else:
        if os.path.isfile(db_path):
            try:
                os.remove(db_path)
            except OSError:
                pass
        if _bk_user == "readtags":
            say("阶段 4/4：readtags 模式（零建库成本，查询约 0.2s/次）")

    meta = {"version": 1, "root": root,
            "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "langs": NAV_LANGS, "code_files": tag_lines,
            "cmd_count": cmd_count, "cmd_files": cmd_files, "o_count": o_count,
            "symbols": len(symbols),
            "backend": _bk_user, "backend_auto": _was_auto,
            # a415：收录范围随库记录（重建/状态展示用；scope=None 的旧式
            # 全量建库不写该键，status 读旧 meta 无扰动）
            **({"scope": {"name": sc["name"], "tier": sc["tier"],
                          "source": sc_src,
                          "include": sc["include"],
                          "artifact_roots": sc["artifact_roots"],
                          "header_roots": sc["header_roots"],
                          "fallback_full": sc["fallback_full"],
                          "exclude_names": sc["exclude_names"],
                          "exclude_paths": sc["exclude_paths"]}}
               if sc else {}),
            "sizes": {"tags": os.path.getsize(tags) if os.path.isfile(tags) else 0,
                      "manifest": os.path.getsize(os.path.join(ld, "manifest.json")),
                      "symbols": os.path.getsize(os.path.join(ld, "symbols.json")),
                      **({"files_list": os.path.getsize(listfile)}
                         if os.path.isfile(listfile) else {}),
                      **({"db": os.path.getsize(db_path)} if os.path.isfile(db_path) else {})}}
    _write_json(os.path.join(ld, "meta.json"), meta)
    prog(100, "完成")
    say("✓ 索引完成：%d 符号 / 白名单 %d 文件 / 库 %.1f MB"
        % (tag_lines, len(compiled),
           sum(meta["sizes"].values()) / 1048576))
    _invalidate_cache()
    return meta


# ------------------------------------------------------------------ 查询

_tags_cache = {"key": None, "data": None}
_file_sym_cache = {"key": None, "inv": {}}   # R33-1：file→[(name,line,kind)] 倒排（key 同 _tags_cache）   # (lib, mtime) -> {name:[entries]}
_tags_files_cache = {"key": None, "set": set()}   # R28-4：references 用文件路径集（mtime 缓存）
_symbols_cache = {"key": None, "data": None}
_manifest_cache = {"key": None, "data": None}
_cache_lock = threading.Lock()


# ================= a390：三档查询后端（ctags-mem-v2 §4）=================
# memory：全量 dict（小库 <20 万符号，现状路径）
# readtags：readtags.exe 二分查找（零建库，~0.2s/次，~10MB）
# sqlite：tags.db 快查（0~4ms，~50MB，建库 ~38s/600 万行）


_sqlite_capable = None


def sqlite_capable():
    """运行环境是否带 sqlite3（a407 用户实锤：exe 打包漏件——excludes
    'src' 后函数内 import sqlite3 不进模块图，_sqlite3.pyd/sqlite3.dll
    没被收集 → No module named 'sqlite3'，阶段 4 回退。spec 已补
    hiddenimports；此探测供 UI 档位下拉/auto 判档/端点早拒用）"""
    global _sqlite_capable
    if _sqlite_capable is None:
        try:
            import sqlite3  # noqa: F401
            _sqlite_capable = True
        except ImportError:
            _sqlite_capable = False
    return _sqlite_capable


def _build_tag_db(tags_path, db_path, say=None, prog=None):
    """tags → tags.db（阶段 4）。批量导入三 pragma 提速；idx_name/idx_path
    双索引（path 索引供 scope=file——_file_sym_cache 倒排随之退役）"""
    import sqlite3
    say = say or (lambda _m: None)
    tmp = db_path + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    con = sqlite3.connect(tmp)
    total_lines = 0
    try:
        con.execute("PRAGMA journal_mode=OFF")
        con.execute("PRAGMA synchronous=OFF")
        con.execute("PRAGMA temp_store=MEMORY")
        con.execute("CREATE TABLE t(name TEXT, path TEXT, line INTEGER, "
            "kind TEXT, file_scope INTEGER)")
        n, rows = 0, []
        with open(tags_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                total_lines += 1
                if line.startswith("!"):
                    continue
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 3:
                    continue
                name, path = parts[0], parts[1]
                kind, lineno, file_scope = "", 0, 0
                for seg in parts[3:]:
                    if seg.startswith("kind:"):
                        kind = seg[5:]
                    elif seg.startswith("line:"):
                        try:
                            lineno = int(seg[5:])
                        except ValueError:
                            pass
                    elif seg == "file:":
                        file_scope = 1   # a425：文件内可见标记（原先丢弃）
                    elif not kind and seg and ":" not in seg and seg != "file":
                        kind = seg   # --fields=+Kn 裸值 kind
                rows.append((name, path, lineno, kind, file_scope))
                n += 1
                if len(rows) >= 100000:
                    con.executemany("INSERT INTO t VALUES(?,?,?,?,?)", rows)
                    rows = []
                    prog(80 + 14 * n / max(1, total_lines),
                         "sqlite 导入 %d 行" % n)
        if rows:
            con.executemany("INSERT INTO t VALUES(?,?,?,?,?)", rows)
        con.commit()
        if prog:
            prog(96, "sqlite 建索引")
        say("  建索引（name/path）…")
        con.execute("CREATE INDEX idx_name ON t(name)")
        con.execute("CREATE INDEX idx_path ON t(path)")
        con.execute("CREATE INDEX idx_lower ON t(lower(name))")   # R35-1：不敏感前缀/子串
        con.commit()
    finally:
        con.close()
    # S37-3（P3）：窗口期并发查询可能重开连接——replace 失败短重试
    for _i in range(3):
        try:
            os.replace(tmp, db_path)
            break
        except OSError:
            if _i == 2:
                raise
            time.sleep(0.05)
            _close_tagdb()
    return n


class _TagDB(object):
    """sqlite 后端：只读连接 + mmap。线程锁串行（Flask 多线程共用）"""

    def __init__(self, db_path):
        import sqlite3
        self._path = db_path
        self._con = sqlite3.connect(
            "file:%s?mode=ro" % db_path.replace("\\", "/"),
            uri=True, check_same_thread=False, timeout=5)
        try:
            self._con.execute("PRAGMA mmap_size=268435456")
            self._con.execute("PRAGMA cache_size=-65536")
        except Exception:
            pass
        self._lock = threading.Lock()
        # R35-4：构造即探测（损坏 db/缺表立即失败 → _get_tagdb 回退）。
        # 探测失败必须自关（fd 泄漏会锁住 db 文件——WinError 32 实锤）
        try:
            self._con.execute("SELECT 1 FROM t LIMIT 1").fetchall()
        except Exception:
            try:
                self._con.close()
            except Exception:
                pass
            raise

    def _q(self, sql, args=()):
        with self._lock:
            return self._con.execute(sql, args).fetchall()

    def lookup(self, name):
        return [(r[1], r[2], r[3], r[4]) for r in
                self._q("SELECT name, path, line, kind, file_scope FROM t "
                        "WHERE name=?", (name,))]

    def lookup_ci(self, name):
        return self._q("SELECT name, path, line, kind FROM t "
                       "WHERE lower(name)=?", (name.lower(),))

    def prefix(self, q, limit):
        # R35-1：大小写不敏感前缀。S36-1（EXPLAIN 实锤：substr 截断比较
        # sqlite 不做范围代数变换→SCAN 全表 143ms；lower 范围比较命中
        # idx_lower→SEARCH 0ms）
        ql = q.lower()
        return self._q("SELECT name, path, line, kind FROM t "
                       "WHERE lower(name) >= ? AND lower(name) < ? LIMIT ?",
                       (ql, ql + "￿", limit))

    def substring(self, q, limit):
        return self._q("SELECT name, path, line, kind FROM t "
                       "WHERE lower(name) LIKE ? LIMIT ?",
                       ("%" + q.lower() + "%", limit))

    def by_path(self, path):
        # R35-6：tags 内为绝对正斜杠原样形态——反斜杠/盘符大小写形态兜底
        rows = self._q("SELECT name, line, kind FROM t WHERE path=?", (path,))
        if rows:
            return rows
        p2 = path.replace(os.sep, "/")
        if p2 != path:
            rows = self._q("SELECT name, line, kind FROM t WHERE path=?", (p2,))
            if rows:
                return rows
        return self._q("SELECT name, line, kind FROM t WHERE path=?",
                       (os.path.normcase(p2),))

    def files(self):
        return set(r[0] for r in self._q("SELECT DISTINCT path FROM t"))

    def close(self):
        try:
            self._con.close()
        except Exception:
            pass


class _ReadtagsBackend(object):
    """readtags 后端：-s1 强制二分；-e -n 拿 kind/line。子串/按路径无模式
    ——退化为 -l 全量后 Python 过滤（慢，调用方 UI 提示）"""

    def __init__(self, ld):
        self._tags = os.path.join(ld, "tags")
        self._exe = os.path.join(os.path.dirname(_CTAGS_EXE), "readtags.exe")
        if not os.path.isfile(self._exe):
            self._exe = None

    def _run(self, flags, names=(), timeout=30):
        if not self._exe:
            return []
        _q = next((n for n in names if n), "")
        if _q and not _q.isascii():
            flags = [f for f in flags if f not in ("-p", "-l")]
            if _q[0].isascii():
                return self._run_raw(flags + ["-p", _q[0]], timeout)
            return self._ascii_dump(max(timeout, 60))   # R6-2：timeout 注记与 diff 对齐
        # R2-10：flags 与查询名分离放调用点——用户查询串一律过 `[-]` 转义位
        # （readtags help：`[-] NAME...` 之后所有参数按 NAME 解析，`-l` 查询
        # 实证 `["-p","-","-l"]` 恰返回 ['-l'] 无尖峰）
        argv = [self._exe, "-s1", "-e", "-n", "-t", self._tags] + flags + (["-"] + list(names) if names else [])
        try:
            pr = subprocess.run(argv, capture_output=True, timeout=timeout,
                                creationflags=0x08000000)
            return pr.stdout.decode("utf-8", "replace").splitlines()
        except (subprocess.TimeoutExpired, OSError):
            return []

    def _run_raw(self, argv_tail, timeout):
        argv = [self._exe, "-s1", "-e", "-n", "-t", self._tags] + argv_tail
        try:
            pr = subprocess.run(argv, capture_output=True, timeout=timeout,
                                creationflags=0x08000000)
            return pr.stdout.decode("utf-8", "replace").splitlines()
        except (subprocess.TimeoutExpired, OSError):
            return []

    _ascii_cache = None   # (tags_mtime, lines)——C-1 桥接专用 dump 缓存

    def _ascii_dump(self, timeout=60):
        try:
            _mt = os.path.getmtime(self._tags)
        except OSError:
            return []
        if self._ascii_cache and self._ascii_cache[0] == _mt:
            return self._ascii_cache[1]
        lines = self._run_raw(["-l"], timeout)
        self._ascii_cache = (_mt, lines)
        return lines
    # _needs_ascii_bridge 删除（R4-1 内联判定取代；保留即死代码且引旧签名）

    @staticmethod
    def _parse(line):
        parts = line.split("\t")
        if len(parts) < 3:
            return None
        name, path = parts[0], parts[1]
        kind, lineno, file_scope = "", 0, 0
        for seg in parts[3:]:
            if seg.startswith("kind:"):
                kind = seg[5:]
            elif seg.startswith("line:"):
                try:
                    lineno = int(seg[5:])
                except ValueError:
                    pass
            elif seg == "file:":
                file_scope = 1   # a425：文件内可见标记（原先丢弃）
            elif not kind and seg and ":" not in seg and seg != "file":
                kind = seg
        return (name, path, lineno, kind, file_scope)

    def lookup(self, name):
        rows = []
        for line in self._run([], names=(name,)):
            r = self._parse(line)
            if r and r[0] == name:
                rows.append((r[1], r[2], r[3], r[4]))
        return rows

    def lookup_ci(self, name):
        low = name.lower()
        return [r for r in (self._parse(l) for l in self._run(["-i"], names=(name,)))
                if r and r[0].lower() == low]

    def prefix(self, q, limit):
        ql = q.lower()
        if not q.isascii():
            _lines = self._run(["-p"], names=(q,), timeout=60)   # 桥接（dump 或 -p 首字）
            out = [r for r in (self._parse(l) for l in _lines)
                   if r and r[0].lower().startswith(ql)][:limit]
            return out
        return [r for r in (self._parse(l) for l in self._run(["-p"], names=(q,))) if r][:limit]

    def substring(self, q, limit):
        ql = q.lower()
        out = []
        for l in self._run(["-l"], timeout=60):
            r = self._parse(l)
            if r and ql in r[0].lower():
                out.append(r)
                if len(out) >= limit:
                    break
        return out

    def by_path(self, path):
        want = os.path.normcase(os.path.normpath(path))
        out = []
        for l in self._run(["-l"], timeout=60):
            r = self._parse(l)
            if r and os.path.normcase(os.path.normpath(r[1])) == want:
                out.append((r[0], r[2], r[3]))
        return out

    def files(self):
        return set(r[1] for r in (x for x in (self._parse(l) for l in self._run(["-l"], timeout=60)) if x))

    def close(self):
        pass


class _MemBackend(object):
    """memory 后端：包装 _load_tags 全量 dict（小库现状路径）"""

    def __init__(self, ld):
        self._tags = _load_tags(ld)
        self._ld = ld

    def lookup(self, name):
        return list(self._tags.get(name) or [])

    def lookup_ci(self, name):
        low = name.lower()
        return [(k,) + v for k, v in self._tags.items() if k.lower() == low for v in v]

    def prefix(self, q, limit):
        out = []
        for k, v in self._tags.items():
            if k.lower().startswith(q):   # S37-1：q 已 lower，k 需同 lower（与 substring 档口径对齐）
                for e in v:
                    out.append((k,) + e)
                    if len(out) >= limit:
                        return out
        return out

    def substring(self, q, limit):
        ql = q.lower()
        out = []
        for k, v in self._tags.items():
            if ql in k.lower():
                for e in v:
                    out.append((k,) + e)
                    if len(out) >= limit:
                        return out
        return out

    def by_path(self, path):
        target = os.path.normcase(os.path.normpath(path))
        out = []
        for name, entries in self._tags.items():
            for p2, ln2, k2 in entries:
                if os.path.normcase(os.path.normpath(p2)) == target:
                    out.append((name, ln2, k2))
        return out

    def files(self):
        return set(p for v in self._tags.values() for (p, _l, _k) in v)

    def close(self):
        pass


# D-1（P1）：单槽缓存多库交替必换 key→旧连接挂 orphan 无界泄漏（200 次交替
# +404 句柄/+70MB，满载 60s 进程静默死亡）——改按 ld 键的多槽 dict：每库
# 一个常驻连接（并发查询本就经 _TagDB._lock 串行，多槽安全），换库不再产
# 生孤儿；连接上限 = 已索引库数（个位数），fd 面收敛
_tagdb_cache = {}          # {ld: _TagDB}
_tagdb_keys = {}           # {ld: (tags_mtime, db_mtime)} 失效判定
# FA-1 终审修正：锁外 close 杀在途查询（干跑锁内 534ms→锁外 ProgrammingError
# 两个极端都不对）。正解=有界延迟回收：被替换连接挂此列表（不立即关——
# 可能有线程正在 execute），超限时关最旧（此时在途概率极低）。文件操作前
# _close_tagdb 全量回收——两个出口互补，泄漏上界 = MAX_ORPHANS 个连接
_tagdb_orphans = []
_MAX_ORPHANS = 4
# FD-1 终审（P1）：reindex 切档期间目标库的 busy 集合——_get_tagdb 对
# busy 的 ld 返回 None（查询走 readtags/memory 兜底），防止文件操作窗口
# 内重建 sqlite 连接与 C 层竞态杀进程
_db_busy = set()


def _open_tags(ld):
    """按 meta.backend 选后端（auto：≥20 万符号 sqlite；db 缺失回退
    readtags；readtags.exe 缺失回退 memory）。返回统一接口对象"""
    meta = _load_json_cached(ld, "meta.json", _meta_cache_for_backend)
    bk = (meta or {}).get("backend") or "auto"
    if bk == "auto":
        n = (meta or {}).get("code_files") or 0
        # a410：全量方案下线——auto 小库也走 readtags。旧库显式
        # backend=memory 仍按原档查询（读兼容，不强制迁移；切档即迁）
        bk = "sqlite" if n >= 200000 else "readtags"
    if bk == "sqlite":
        db = _get_tagdb(ld)
        if db:
            return db
        bk = "readtags"   # db 缺失/损坏回退
    if bk == "readtags":
        be = _ReadtagsBackend(ld)
        if be._exe and os.path.isfile(be._tags):
            return be
    return _MemBackend(ld)


def _get_tagdb(ld):
    # FD-1 终审（P1）：busy 让路——reindex/build 文件操作窗口内不建
    # sqlite 连接（查询走 readtags/memory 兜底，正确性无损）
    if ld in _db_busy:
        return None
    db_p = os.path.join(ld, "tags.db")
    tags_p = os.path.join(ld, "tags")
    if not os.path.isfile(db_p) or not os.path.isfile(tags_p):
        return None
    try:
        key = (os.path.getmtime(tags_p), os.path.getmtime(db_p))
    except OSError:
        return None
    with _cache_lock:
        if _tagdb_keys.get(ld) == key and ld in _tagdb_cache:
            return _tagdb_cache[ld]
    try:
        db = _TagDB(db_p)
    except Exception:
        return None
    with _cache_lock:
        if _tagdb_keys.get(ld) == key and ld in _tagdb_cache:
            db.close()          # 他者先到——弃用自己的（他者连接已服务同 key）
            return _tagdb_cache[ld]
        _old = _tagdb_cache.get(ld)
        _tagdb_cache[ld] = db
        _tagdb_keys[ld] = key
        if _old is not None:
            # FA-1：不立即关——可能有线程正在 execute（锁外 close 杀在途
            # →ProgrammingError→500）。挂有界 orphan，超限才关最旧（此时
            # 在途概率极低）。_close_tagdb 全量回收兜底
            _tagdb_orphans.append(_old)
            while len(_tagdb_orphans) > _MAX_ORPHANS:
                _victim = _tagdb_orphans.pop(0)
                try: _victim.close()
                except Exception: pass
    return db


def _close_tagdb(ld=None):
    """关闭常驻连接并清缓存。ld=None 关全部（build/delete 等）；ld 指定
    只关该库（reindex 切档——FD-1 终审：全量关闭与并发查询线程的重建
    交叠触发 sqlite3 C 层竞态杀进程，3/3 复现。定向关+busy 让路后其他
    库不受干扰、目标库不会再锁文件）——orphan 列表一并回收"""
    with _cache_lock:
        if ld is None:
            dbs = list(_tagdb_cache.values())
            _tagdb_cache.clear()
            _tagdb_keys.clear()
            _db_busy.clear()
        else:
            dbs = []
            if ld in _tagdb_cache:
                dbs.append(_tagdb_cache.pop(ld))
                _tagdb_keys.pop(ld, None)
            _db_busy.add(ld)   # busy 让路：文件操作窗口内该库不再建 sqlite 连接
        orphans = list(_tagdb_orphans)
        del _tagdb_orphans[:]
    for d in dbs + orphans:
        try: d.close()
        except Exception: pass


def _unbusy_tagdb(ld):
    """reindex/build 完成后解除 busy 标记（恢复 sqlite 查询）"""
    with _cache_lock:
        _db_busy.discard(ld)


_meta_cache_for_backend = {"key": None, "data": None}


def _invalidate_cache():
    try:
        _close_tagdb()   # R35-2：索引重建后旧连接必须先关（Windows 删 db 挡死）
    except Exception:
        pass
    with _cache_lock:
        _tags_cache["key"] = None
        _symbols_cache["key"] = None
        _manifest_cache["key"] = None


def _load_tags(ld):
    key = (ld, os.path.getmtime(os.path.join(ld, "tags")) if os.path.isfile(os.path.join(ld, "tags")) else 0)
    with _cache_lock:
        if _tags_cache["key"] == key:
            return _tags_cache["data"]
    data = {}
    try:
        with open(os.path.join(ld, "tags"), encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("!"):
                    continue
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 3:
                    continue
                name, path = parts[0], parts[1]
                kind, lineno, file_scope = "", 0, 0
                for seg in parts[3:]:
                    if seg.startswith("kind:"):
                        kind = seg[5:]
                    elif seg.startswith("line:"):
                        try:
                            lineno = int(seg[5:])
                        except ValueError:
                            pass
                    elif seg == "file:":
                        file_scope = 1   # a425：文件内可见标记
                    elif not kind and seg and ":" not in seg and seg != "file":
                        # a383（存量 bug 实锤）：本库 ctags --fields=+Kn 产长名
                        # 裸值 kind（class/variable/function…，不带 kind: 前缀）
                        # ——旧解析恒空：符号面板徽标一直空白、definition 的
                        # file_local 优先级从未生效。裸段里除 kind 外只有
                        # extras=f 的 'file' 标记，可安全识别
                        kind = seg
                data.setdefault(name, []).append((path, lineno, kind, file_scope))
    except OSError:
        data = {}
    with _cache_lock:
        _tags_cache["key"] = key
        _tags_cache["data"] = data
    return data


def _load_json_cached(ld, name, cache):
    p = os.path.join(ld, name)
    key = (ld, os.path.getmtime(p) if os.path.isfile(p) else 0)
    with _cache_lock:
        if cache["key"] == key:
            return cache["data"]
    data = _read_json(p) or {}
    with _cache_lock:
        cache["key"] = key
        cache["data"] = data
    return data


def _common_depth(a, b):
    """路径公共祖先段数（组件消歧的零配置近似）。"""
    pa = os.path.normcase(os.path.abspath(a)).split(os.sep)
    pb = os.path.normcase(os.path.abspath(b)).split(os.sep)
    n = 0
    for x, y in zip(pa, pb):
        if x != y:
            break
        n += 1
    return n


def find_lib_for(file_path):
    """当前文件属于哪个索引库：遍历库 meta.root 做前缀匹配，取最深者。"""
    fp = os.path.normcase(os.path.abspath(file_path))
    best = None
    for lib in list_libs():
        r = os.path.normcase(lib["root"])
        if fp.startswith(r.rstrip(os.sep) + os.sep):
            if best is None or len(r) > len(os.path.normcase(best["root"])):
                best = lib
    if not best:
        return None, None
    ld = os.path.join(_nav_root(), best["lib"])
    return ld, best


def symbols(file_path, q, limit=50, **kwargs):
    """工作区符号面板（Ctrl+T）：按发起文件反查库，前缀/子串匹配。
    返回 [{name, rel, line, kind, in_build, dist}]（按 前缀命中>子串>
    路径近 排序）。"""
    ld, lib = find_lib_for(file_path)
    if not ld:
        return {"ok": False, "err": "no-index", "items": []}
    _be = _open_tags(ld)
    mf = _load_json_cached(ld, "manifest.json", _manifest_cache)
    compiled = mf.get("compiled") or {}
    root = lib["root"]
    qlow = (q or "").strip().lower()
    # a383（Ctrl+Shift+O 文件内符号）：scope=file 精确到本文件，空查询给
    # 全量（按行号排——文件大纲语义），有 q 时子串过滤
    if kwargs.get("scope") == "file":
        # a390：三档后端统一 by_path（sqlite 走 idx_path 毫秒级——
        # _file_sym_cache 倒排副本退役（ctags-mem-v2：内存翻倍元凶）；
        # readtags 档退化为 -l 全扫（慢，UI 已有提示）
        target = file_path   # tags 内路径为绝对正斜杠原样
        _base = os.path.basename(file_path)
        out = []
        for name2, lineno2, kind2 in _be.by_path(target):
            # R33-2：同名多定义全收；kind 空的文件名自条目剔除
            if not kind2 or name2 == _base:
                continue
            if qlow and qlow not in name2.lower():
                continue
            out.append({"name": name2, "rel": _base,
                        "path": file_path, "line": lineno2, "kind": kind2,
                        "in_build": None, "dist": 0})
        out.sort(key=lambda c: c["line"])
        return {"ok": True, "items": out[:limit], "mode": "file"}
    if not qlow:
        return {"ok": True, "items": [], "mode": "empty"}   # 空查询不给全量
    # R35-1（实锤：三分类从大小写不敏感变敏感——q='Application' 零结果）：
    # exact 用 lookup_ci（原名族），prefix/substring 后端按 lower 比对
    _exact_names = {r[0] for r in _be.lookup_ci(qlow)}
    exact = list(_exact_names)
    prefix = [n2 for n2 in dict.fromkeys(
        r[0] for r in _be.prefix(qlow, limit * 2)) if n2 not in _exact_names]
    substr = [] if (len(exact) + len(prefix) >= limit) else \
        list(dict.fromkeys(r[0] for r in _be.substring(qlow, limit * 2)))
    _seen = _exact_names | set(prefix)
    substr = [n2 for n2 in substr if n2 not in _seen]
    out = []

    def push(name):
        for path, lineno, kind, _fsc in _be.lookup(name)[:6]:   # R16-10：与 F12 候选口径拉近
            rel = path.replace(os.sep, "/")
            if os.path.isabs(path):
                rel = os.path.relpath(path, root).replace(os.sep, "/")
            base_ok = None
            for ext in _UNIT_EXTS:
                if rel.lower().endswith(ext):
                    base_ok = rel in compiled
                    break
            out.append({"name": name, "rel": rel,
                        "path": os.path.join(root, rel.replace("/", os.sep)),
                        "line": lineno, "kind": kind, "in_build": base_ok,
                        "dist": _common_depth(file_path,
                                              os.path.join(root, rel.replace("/", os.sep)))})

    for name in exact[:limit]:
        push(name)
    for name in prefix[:limit * 2]:
        if len(out) >= limit:
            break
        push(name)
    for name in substr[:limit * 2]:
        if len(out) >= limit:
            break
        push(name)
    out.sort(key=lambda c: (0 if c["in_build"] else 1, -c["dist"]))
    return {"ok": True, "items": out[:limit], "mode": "ok"}



def references(file_path, symbol, limit=200):
    """引用查找（Shift+F12）：rg 在库根内搜符号词法出现，排除定义行本身
    （definition 候选的 path+line），返回 [{rel,line,snippet,in_build}]。"""
    ld, lib = find_lib_for(file_path)
    if not ld:
        return {"ok": False, "err": "no-index", "items": []}
    root = lib["root"]
    rg = os.path.join(os.path.dirname(_CTAGS_EXE), "..", "rg.exe")
    rg = os.path.normpath(rg)
    if not os.path.isfile(rg):
        return {"ok": False, "err": "rg.exe 缺失", "items": []}
    import subprocess as _sp
    # R17-3（实锤：引用域分裂）：--no-ignore 打开了被忽略目录却没有对应
    # 排除——与 ctags 的 --exclude=.git/node_modules 对齐（否则 F12 与
    # Shift+F12 口径反向分裂，node_modules 淹没结果）。
    # R17-3b（R16-3 引入的真根因）：`--` 终结符曾放在 symbol 前——其后
    # 所有 -g/--max-count 全被当路径参数，include/exclude 从未生效。
    # 正确序：全部选项在前，`--` 只紧贴 pattern+root。
    # a365R2（用户追问 Linux 无 .gitignore 的放大风险）：目录名硬编码排除
    # 两个错误方向都实证了——硬编码 !build/!out 误伤 SDK 真源码（海思
    # out/init/src/*.c 41 个实测）；文件名指纹不排生成目录（28 条垃圾回
    # 涌实测）。正解=**tags 收录集过滤**：引用只报 ctags 索引收录过的
    # 文件——索引域是用户建索引时的单一真源（ctags 本身跳过纯产物文件
    # 收录不了符号的 .c 大文件？不——ctags 也收。真正的过滤源=建库时
    # 的 tags 文件路径集），rg 照常搜但结果按 tags 域过滤
    cmd = [rg, "--json", "--no-messages", "--no-ignore", "-F",
           "-g", "*.c", "-g", "*.h", "-g", "*.cpp", "-g", "*.hpp",
           "-g", "*.cc", "-g", "*.py", "-g", "*.js", "-g", "*.ts",
           "-g", "*.S", "-g", "*.s",   # a415R2 N13：汇编 label 的引用点
           "-g", "!**/node_modules/**", "-g", "!**/.git/**"]
    # tags 收录集（路径集——只在此域内报引用）+ 生成文件黑名单（a365R2：
    # 内容指纹判定的生成代码——ctags 对生成 .c 一样收符号，tags 域过滤
    # 不掉它们，黑名单才是真过滤源；tags_set 只兜底防域外垃圾）
    # a390：tags 收录域改后端 files()（sqlite DISTINCT 毫秒级；memory 档
    # 即 dict 遍历；readtags -l 一次性解析——_tags_files_cache 退役）
    _be = _open_tags(ld)
    tags_set = set(os.path.normcase(os.path.normpath(
        p if os.path.isabs(p) else os.path.join(root, p)))
        for p in _be.files())
    gen_set = set()
    _genf = _read_json(os.path.join(ld, "gen_files.json"))
    # a415R3 BUG-1 兜底：读端把相对条目拼回绝对（防手改/异版本库）
    if _genf and isinstance(_genf.get("generated"), list):
        _genf["generated"] = [
            g if os.path.isabs(g) else os.path.join(root, g)
            for g in _genf["generated"]]
    # R28-3（旧库无 gen_files.json 垃圾回涌）+ a372（旧库 scan_max 是旧上限
    # ——4M 时代漏掉的 >4M 生成文件）：两种都触发即时补扫并落盘——升级即
    # 生效，不需要用户重建索引
    if not isinstance(_genf, dict) or _genf.get("scan_max") != _GEN_SCAN_MAX:
        try:
            _rgp = os.path.normpath(os.path.join(os.path.dirname(_CTAGS_EXE), "..", "rg.exe"))
            _fps = ["Generated by Cython", "A lexical scanner generated by",
                    "Generated by the protocol buffer compiler",
                    "/* Generated by pybind11", "This file was generated by SWIG",
                    "auto-generated", "AUTOGENERATED"]
            _rg = subprocess.run(
                [_rgp, "-l", "--no-messages", "--no-ignore", "-F",
                 "--max-filesize", _GEN_SCAN_MAX,
                 "-g", "*.c", "-g", "*.cc", "-g", "*.cpp", "-g", "*.h", "-g", "*.py",
                 "-g", "!**/node_modules/**", "-g", "!**/.git/**"]
                + sum([["-e", fp] for fp in _fps], []) + ["--", root],
                capture_output=True, timeout=300, creationflags=0x08000000,
                env={"LC_ALL": "C", **os.environ})
            _genf = {"generated": sorted(
                os.path.normcase(os.path.normpath(l.strip()))
                for l in (_rg.stdout or b"").decode("utf-8", "replace").splitlines() if l.strip()),
                "scan_max": _GEN_SCAN_MAX}
            _write_json(os.path.join(ld, "gen_files.json"), _genf)
        except Exception:
            _genf = None
    if _genf and isinstance(_genf.get("generated"), list):
        gen_set = set(_genf["generated"])
    # R17-8（实锤：operator 类假阳性）：-w 的词边界语义只对纯标识符符号
    # 成立（operator+ 的 + 非词字符，-w 判界异常）——纯标识符才加 -w
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", symbol):
        cmd.append("-w")
    cmd += ["--", symbol, root]
    try:
        r = _sp.run(cmd, capture_output=True, timeout=120,
                    creationflags=0x08000000, env={"LC_ALL": "C", **os.environ})
    except Exception as e:
        return {"ok": False, "err": "rg 失败：%s" % e, "items": []}
    # 定义行集合（排除）——a371R：definition 候选已镜像去重，但引用结果过滤
    # 需要未去重的全 def 行（dist 镜像 def 在 15 行、src 在 15 行，行号不同——
    # deflines 用去重后集合会漏排镜像 def）。all_deflines 是 (path, line) 元组
    dres = definition(file_path, symbol)
    deflines = {(os.path.normcase(p), ln)
                for p, ln in (dres.get("all_deflines") or [])}
    mf = _load_json_cached(ld, "manifest.json", _manifest_cache)
    compiled = mf.get("compiled") or {}
    items = []
    truncated = False
    import json as _json
    # R18-2（实锤：单文件静默截断）：去掉 rg 每文件 --max-count（哨兵探测
    # 被定义行排除占配额绕不过）——rg 不限，全局 limit 断点即截断标记
    # （stdout 万条 JSON ~2MB 可接受，rg 120s 超时保底）
    for line in (r.stdout or b"").decode("utf-8", "replace").splitlines():
        if len(items) >= limit:
            truncated = True
            break
        try:
            evt = _json.loads(line)
        except ValueError:
            continue
        if evt.get("type") != "match":
            continue
        data = evt.get("data") or {}
        p = (data.get("path") or {}).get("text", "")
        ln = data.get("line_number") or 0
        if not p:
            continue
        # a365R2：生成文件黑名单（内容指纹）+ tags 收录域双过滤
        _pnc = os.path.normcase(os.path.normpath(p))
        if gen_set and _pnc in gen_set:
            continue
        if tags_set and _pnc not in tags_set:
            continue
        rel = os.path.relpath(p, root).replace(os.sep, "/")
        if (os.path.normcase(p), ln) in deflines:
            continue
        in_build = None
        for ext in _UNIT_EXTS:
            if rel.lower().endswith(ext):
                in_build = rel in compiled
                break
        items.append({"rel": rel, "path": p, "line": ln,
                      "snippet": ((data.get("lines") or {}).get("text") or "").strip()[:160],
                      "in_build": in_build})
    # a365R2 补：镜像目录去重——dist/ 类发布镜像是源码完整拷贝（无生成
    # 指纹），同 basename+line 的重复命中只保留离发起文件最近的一条（源
    # 码本体通常比镜像近）。不做的话引用数虚高且一半是重复项
    if len(items) > 1:
        _by = {}
        for it in items:
            key = (os.path.basename(it["rel"]).lower(), it["line"])
            cur = _by.get(key)
            if cur is None or _common_depth(file_path, it["path"]) > _common_depth(file_path, cur["path"]):
                _by[key] = it
        items = list(_by.values())
        items.sort(key=lambda c: -_common_depth(file_path, c["path"]))
    return {"ok": True, "items": items, "defs": len(deflines),
            "truncated": truncated}


def definition(file_path, symbol):
    """决策链查询。file_path=发起跳转的文件（组件上下文），symbol=光标词。
    返回 {symbol, auto, mode, candidates:[{path,line,kind,in_build,dist,file_local}]}
    auto=True 时前端可直接跳第一个候选。"""
    ld, lib = find_lib_for(file_path)
    if not ld:
        return {"symbol": symbol, "auto": False, "mode": "no-index",
                "candidates": [], "err": "该文件不在任何索引库内——请先在文件树右键建立索引"}
    _be = _open_tags(ld)
    # a390R（真机实锤：R1 成功后全接口灭）：此处不得 close——_TagDB 连接由
    # _tagdb_cache 生命周期管理（换库时关旧），查询方关共享连接=后续全灭
    cands = _be.lookup(symbol)
    if not cands:
        # 大小写不敏感重试（返回 (name,path,line,kind)——取后三列）
        for _r in _be.lookup_ci(symbol):
            cands.append((_r[1], _r[2], _r[3], _r[4] if len(_r) > 4 else 0))
    mf = _load_json_cached(ld, "manifest.json", _manifest_cache)
    compiled = mf.get("compiled") or {}
    syms = _load_json_cached(ld, "symbols.json", _symbols_cache).get("symbols") or {}
    root = lib["root"]

    # 决策链 0：nm 符号锁定（唯一编译单元定义了该符号）
    nm_lock = None
    nm_srcs = syms.get(symbol)
    if nm_srcs and len(nm_srcs) == 1:
        nm_lock = nm_srcs[0]

    # a362（用户实锤「nm 符号映射为什么没实现」）：SDK 场景 .o 是闭源
    # 预编译（符号在 .o 里、源文件里没有同名定义）→ ctags tags 无此条
    # → 旧流直接 not-found，nm 映射建好了却无候选可锁。修复：tags 无
    # 候选但 nm 有唯一源映射时，以该源文件生成候选（行号在源内文本搜
    # 索兜底，无则 1）
    if not cands and nm_srcs:
        cands = []
        for srel in nm_srcs[:5]:
            sabs = os.path.join(root, srel.replace("/", os.sep))
            ln = 1
            try:
                with open(sabs, encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f, 1):
                        if symbol in line:
                            ln = i
                            break
            except OSError:
                pass
            cands.append((sabs, ln, "", 0))
    if not cands:
        return {"symbol": symbol, "auto": False, "mode": "not-found",
                "candidates": []}

    out = []
    for path, lineno, kind, file_scope in cands:
        # a425 修复 A（内网报告 a419 缺陷一）：ctags file: 标记=该符号仅本
        # 源文件可见。发起跳转的文件不是它自己时该候选根本不可见，必须剔除
        # ——否则 11% 的 file-scope 符号（局部 static/局部宏）全当全局候选
        # 抢真定义（实测 pr_warn 被 uboot 工具的 fprintf 局部宏抢走）
        if file_scope and file_path and                 os.path.normcase(os.path.abspath(path)) !=                 os.path.normcase(os.path.abspath(file_path)):
            continue
        rel = path.replace(os.sep, "/")
        if os.path.isabs(path):
            rel = os.path.relpath(path, root).replace(os.sep, "/") if \
                os.path.normcase(path).startswith(os.path.normcase(root)) else path
        in_build = None
        base, _ = os.path.splitext(rel)
        for ext in _UNIT_EXTS:
            if rel.lower().endswith(ext):
                in_build = rel in compiled
                break
        if in_build is None:
            in_build = None     # 头文件/脚本：编译单元判定不适用
        out.append({
            "path": os.path.join(root, rel.replace("/", os.sep)),
            "rel": rel, "line": lineno, "kind": kind,
            "in_build": in_build,
            "dist": _common_depth(file_path, os.path.join(root, rel.replace("/", os.sep))),
            "file_local": os.path.normcase(os.path.abspath(os.path.join(root, rel.replace("/", os.sep)))) == os.path.normcase(os.path.abspath(file_path)),
            "nm_lock": bool(nm_lock and rel == nm_lock),
        })

    # a425 修复 B+C-2（内网报告 a419 缺陷二）：排序加两档——
    # ③ 第三方源码副本降权（先于 in_build）：sbuilder/board 的 optee/atf/
    # musl 树自带构建产物（1823 个 .o）→ in_build=True 抢走 copy_to_user
    # 这类内核真定义；④ 头文件宏优先（in_build 之后，dist 之前）：头文件
    # 的 in_build 恒为 None（非编译单元），不加这档任何编译过的 .c 里的
    # 同名 #define 都压过内核头文件宏（pr_warn 被 sunxi 工具的 fprintf
    # 局部宏抢走实锤）。in_build 必须仍在 ③④ 之前——真函数定义优先于
    # 头文件里的声明
    _VENDOR_TREES = ("sbuilder/board/", "/tools/atf/",
                     "/tools/optee_os", "/tools/musl/")

    def rank(c):
        _vendor = any(t in c["rel"] for t in _VENDOR_TREES)
        return (
            0 if c["nm_lock"] else 1,                       # nm 符号级锁定最优先
            0 if c["file_local"] else 1,                    # 当前文件 static
            1 if _vendor else 0,                            # ③ 第三方副本降权
            0 if c["in_build"] is True else 1,              # 编译白名单
            0 if ("/include/" in c["rel"] and c["kind"] == "macro") else 1,
                                                           # ④ 头文件宏
            -c["dist"],                                      # 路径公共祖先（组件消歧）
            c["rel"],
        )

    out.sort(key=rank)
    # a369R：定义候选镜像去重（引用侧 a368 同款）——dist 类发布镜像是
    # 源码完整拷贝，同名同 kind 的镜像副本让 F12 弹 N 个"多候选"实际是
    # 同一符号。按 basename+kind 去重保留排序最前者（源码本体近镜像远）。
    # a371R：去重前的全部 def 行以 all_deflines 透出——references 的
    # deflines 排除集需要它（镜像 def 行号与本体不同，用去重后集合漏排）
    _all_deflines = [(c["path"], c["line"]) for c in out]
    if len(out) > 1:
        _seen = set()
        _ded = []
        for cand in out:
            key = (os.path.basename(cand["rel"]).lower(), cand.get("kind") or "")
            if key in _seen:
                continue
            _seen.add(key)
            _ded.append(cand)
        out = _ded
    # a383（Hover 悬停看定义）：前几个候选附源码摘要（定义行+下 2 行）——
    # 按文件分组各读一次，逐行读到目标行号（大文件不整读）
    try:
        _by_file = {}
        for _c in out[:5]:
            _by_file.setdefault(_c["path"], []).append(_c)
        for _fp, _cs in _by_file.items():
            _need = max(_c["line"] for _c in _cs) + 2
            _lines = []
            try:
                with open(_fp, encoding="utf-8", errors="replace") as _f:
                    for _i, _ln in enumerate(_f, 1):
                        if _i > _need:
                            break
                        _lines.append(_ln.rstrip())
            except OSError:
                continue
            for _c in _cs:
                _st = max(0, _c["line"] - 1)
                _c["snippet"] = (chr(10).join(_lines[_st:_st + 3])).strip()[:300]
    except Exception:
        pass
    first = out[0]
    # a428（内网报告 问题5·建议1）：全部候选都是 struct member 且符号像
    # 局部变量（小写短名）→ 大概率是函数内局部变量（ctags 不索引局部变量，
    # 能力边界）——不自动跳转，明确降级提示+候选仅供参考，杜绝"跳到
    # aic8800/ipc_shared.h 的同名成员"这种误导
    if all((c.get("kind") or "") in ("member", "m") for c in out) \
            and symbol[:1].islower() and len(symbol) <= 12:
        return {"symbol": symbol, "auto": False,
                "mode": "ambiguous-local",
                "err": "可能为函数内局部变量（ctags 不索引局部变量）——"
                       "以下为同名结构体成员，仅供参考",
                "candidates": out[:5]}
    # auto 直跳：nm 锁定，或唯一 in_build 候选，或同文件 static
    others = out[1:]
    auto = bool(
        first["nm_lock"]
        or first["file_local"] and first["kind"] in ("function", "f", "member", "variable", "v")
        or (first["in_build"] is True
            and not any(c["in_build"] is True for c in others))
    )
    mode = "nm" if first["nm_lock"] else (
        "manifest" if compiled else "heuristic")
    return {"symbol": symbol, "auto": auto, "mode": mode,
            "candidates": out[:30], "all_deflines": _all_deflines}
