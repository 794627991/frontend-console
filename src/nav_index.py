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
NAV_LANGS = "C,C++,Python,JavaScript,TypeScript,Java,Go,Rust"
CODE_EXTS = {".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", ".hh", ".hxx",
             ".py", ".js", ".mjs", ".cjs", ".ts", ".java", ".go", ".rs"}
# 编译单元后缀（白名单/符号表只认这些——.h 是包含物不是单元）
_UNIT_EXTS = {".c", ".cpp", ".cc", ".cxx"}
# 生成文件指纹扫描的 rg --max-filesize（a372：原 4M 恰好漏掉 4.06M 的
# Cython routes.c——写进 gen_files.json 的 scan_max 字段，旧库读到不一致
# 即自动补扫，不需要用户重建索引）
_GEN_SCAN_MAX = "32M"
_SKIP_DIRS = {".git", "node_modules", ".svn", ".hg"}
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
    _invalidate_cache()
    return True, "已关联到 " + new_root


# ------------------------------------------------------------------ 建库管线

def _walk_files(root, should_cancel=None, say=None):
    """生成 (abs_path, rel_posix)。跳过 _SKIP_DIRS。
    a411（用户实锤：W: 网盘大库阶段 1 永卡 30%）：os.walk 的 readdir 在
    网盘上单目录可停滞数分钟且零反馈——改生产者线程+目录级队列消费：
    120s 无进展先报停滞目录（面板可见），300s 判网盘停滞失败退出（把
    无限死等变成可诊断失败）。队列按目录批量、maxsize 有界，内存与
    原生 walk 同级；网盘断连的 OSError 也经此转给消费侧"""
    import queue as _q
    import threading as _th
    say = say or (lambda _m: None)
    _q0 = _q.Queue(maxsize=64)
    _DONE = object()
    _err = [None]

    def _produce():
        try:
            for r, ds, fs in os.walk(root):
                ds[:] = [d for d in ds if d not in _SKIP_DIRS]
                if should_cancel and should_cancel():
                    return
                _q0.put((r, fs))
        except Exception as e:      # SMB 断连等：转给消费侧统一抛
            _err[0] = e
        finally:
            _q0.put(_DONE)

    _th.Thread(target=_produce, daemon=True).start()
    _last_t = time.time()
    _last_dir = [root]
    _warned = False
    while True:
        # 循环头检查：producer 因取消提前退出时（DONE 先于任何目录），
        # 消费侧也必须立即取消——否则空扫描静默继续（单测实锤）
        if should_cancel and should_cancel():
            raise Cancelled()
        try:
            item = _q0.get(timeout=5.0)
        except _q.Empty:
            item = None
        if item is _DONE:
            if _err[0] is not None:
                raise RuntimeError("目录扫描失败（%s）" % _err[0])
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
        for f in fs:
            if should_cancel and should_cancel():
                raise Cancelled()
            yield os.path.join(r, f), os.path.relpath(r + os.sep + f, root).replace(os.sep, "/")


class Cancelled(Exception):
    pass


def _parse_cmd_file(p):
    """Kbuild .cmd：`cmd_xxx.o := <cc> ... -c ... src.c`——命令行自带源文件
    路径（多 .c 合一 .o 的成员文件各有自己的 .cmd，天然正确）。返回相对
    于 .cmd 所在目录的源文件绝对路径或 None。"""
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
                    # 相对路径也可能基于源码根（.cmd 在输出树、src 在源码树）
                    # Kbuild 常见 ../ 形式已被 normpath 处理；其余路径形态
                    # 交给 .o 同名兜底
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


def build(root, log=None, progress=None, should_cancel=None, backend="auto"):
    """三阶段建库。log=callable(str)；progress=callable(done,total,label)
    done/total 为 0-100 的阶段推进。返回 meta dict（失败抛异常）。"""
    say = log or (lambda _m: None)
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        raise RuntimeError("目录不存在：%s" % root)
    ld = lib_dir(root)
    os.makedirs(ld, exist_ok=True)

    def prog(pct, label):
        if progress:
            progress(int(pct), 100, label)

    # ---- 阶段 1：编译产物白名单 ----
    # 权威序：.cmd 命令行（自描述）> .o 同目录同名 > .o basename 全局唯一
    # （海思等 out-of-tree：.o 在 out/obj、.c 在 source——同目录映射失效，
    # basename 全局唯一兜底；basename 多处同名视为歧义放弃）
    say("阶段 1/4：扫描编译产物（.cmd/.o）…")
    prog(2, "扫描编译产物")
    compiled = {}       # rel_src_posix -> {"o": rel_o, "src": "cmd"|"omap"|"bmap"}
    o_files = []        # 相对 .o（符号表阶段用）
    cmd_count = cmd_files = o_count = 0
    unit_by_base = {}   # basename（无后缀）-> [rel, ...] 编译单元源文件
    pending_o = []      # 未被 .cmd/同目录覆盖的 .o
    all_rels = set()    # a411：全量 rel 集合（同目录同名映射走 set 查，零网络 I/O）
    _last_prog = 0.0    # 用户令：1s 一拍的过程显示计时
    for abs_p, rel in _walk_files(root, should_cancel, say):
        all_rels.add(rel)
        low = rel.rsplit("/", 1)[-1].lower()
        if low.endswith(".cmd"):
            cmd_files += 1           # R17-4：文件名计数（stale 同口径）
            src = _parse_cmd_file(abs_p)
            if src and os.path.isfile(src):
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
                cmd_count += 1
        elif low.endswith(".o"):
            o_files.append(rel)
            o_count += 1
            # a411：同目录同名映射延后到 walk 结束用集合查（原逐 .o
            # os.path.isfile——网盘上 2.3 万 .o × 每个多次 stat = 数万次
            # SMB 往返，扫描像卡死）
        else:
            b, ext = os.path.splitext(low)
            if ext in _UNIT_EXTS:
                unit_by_base.setdefault(b, []).append(rel)
        # 用户令：全部过程显示 1s 一更新、同一行、不刷屏——中间进度走
        # prog()（前端 progress 文本同一行刷新），say() 只留阶段头和终态
        # a411：min(28,_tot/800) 在 2.2 万文件即顶格 30%，之后进度条假死
        # ——改渐进逼近 30%（单调递增永不到顶，扫描活着条就动）
        _tot = cmd_count + o_count + len(unit_by_base)
        _now = time.time()
        if _tot and _now - _last_prog >= 1.0:
            _last_prog = _now
            prog(2 + 28.0 * _tot / (_tot + 8000),
                 "扫描中：产物 %d（.cmd %d/.o %d）· 源文件 %d" % (
                     _tot, cmd_count, o_count, len(unit_by_base)))
    # a411：同目录同名映射（walk 内收集全量集合，set 查零 I/O）
    for orel in o_files:
        stem = orel[:-2]
        for ext in _UNIT_EXTS:
            crel = stem + ext
            if crel in all_rels:
                compiled.setdefault(crel, {"o": orel, "src": "omap"})
                break
        else:
            pending_o.append(orel)
    # basename 全局唯一兜底（out-of-tree）
    for orel in pending_o:
        b = os.path.splitext(os.path.basename(orel))[0].lower()
        hits = unit_by_base.get(b)
        if hits and len(hits) == 1:
            compiled.setdefault(hits[0], {"o": orel, "src": "bmap"})
    mf = {"version": 1, "root": root, "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
          "compiled": compiled, "cmd_count": cmd_count, "o_count": o_count}
    _write_json(os.path.join(ld, "manifest.json"), mf)
    say("  编译白名单：%d 个源文件（.cmd %d / .o %d）"
        % (len(compiled), cmd_count, o_count))
    if not compiled:
        say("  未发现构建产物——跳转按启发式排序（基线编译后重建可精确化）")

    # ---- 阶段 2：ctags 全量 ----
    say("阶段 2/4：ctags 全量索引（%s）…" % NAV_LANGS)
    prog(30, "ctags 索引")
    tags_tmp = os.path.join(ld, "tags.tmp")
    tags = os.path.join(ld, "tags")
    cmd = [_CTAGS_EXE, "--languages=" + NAV_LANGS,
           "--fields=+Kn", "--extras=+f",
           "-R", "-f", tags_tmp,
           "--exclude=.git", "--exclude=node_modules",
           # a369R（用户令：ctags 同样套用隐藏排除）：ctags 只内置跳 .git/
           # .svn 等少数目录——.history/.idea 和 .hidden.c 实测全收。glob
           # 通配 --exclude=.* 一网打尽（实测：.history/.idea/.hidden.c 全
           # 排、src 正常收）
           "--exclude=.*",
           root]
    # a361（用户实锤：30% 死等无文件进度）：大库 ctags 阶段数分钟只有一句
    # "ctags 索引"——心跳线程监控 tags.tmp 增长，每 3 秒报已写 MB，死等变
    # 活进度；ctags 完成后心跳自停
    import threading as _th
    _hb_stop = _th.Event()
    def _heartbeat():
        _last = -1
        while not _hb_stop.wait(1.0):   # 用户令：1s 一拍
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
        env = dict(os.environ)
        env["LC_ALL"] = "C"
        r = subprocess.run(cmd, capture_output=True, timeout=3600,
                           creationflags=0x08000000, env=env)
    except FileNotFoundError:
        raise RuntimeError("ctags.exe 缺失（vendor/ctags/）")
    except subprocess.TimeoutExpired:
        raise RuntimeError("ctags 超时（60 分钟）——目录过大？")
    finally:
        _hb_stop.set()
    if not os.path.isfile(tags_tmp):
        raise RuntimeError("ctags 未产出 tags：%s" % (r.stderr or "")[:200])
    # R15-3（实锤：取消被吞）：ctags 阻塞期不查取消——跑完立即补查，
    # 已取消则不落盘 tags/不写 meta（半成品库会被 status 误判 indexed）
    if should_cancel and should_cancel():
        try:
            os.remove(tags_tmp)
        except OSError:
            pass
        raise Cancelled()
    for _i in range(3):
        try:
            os.replace(tags_tmp, tags); break
        except OSError:
            if _i == 2: raise
            time.sleep(0.05)
    tag_lines = 0
    with open(tags, encoding="utf-8", errors="replace") as f:
        for _ in f:
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
        rcg = subprocess.run(
            [rgp, "-l", "--no-messages", "--no-ignore", "-F", "--max-filesize", "32M",
             "-g", "*.c", "-g", "*.cc", "-g", "*.cpp", "-g", "*.h", "-g", "*.py",
             "-g", "!**/node_modules/**", "-g", "!**/.git/**"]
            + sum([["-e", fp] for fp in fingerprints], [])
            + ["--", root],
            capture_output=True, timeout=300, creationflags=0x08000000,
            env={"LC_ALL": "C", **os.environ})
        for pl in (rcg.stdout or b"").decode("utf-8", "replace").splitlines():
            if pl.strip():
                _gen.add(os.path.normcase(os.path.normpath(pl.strip())))
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
            "sizes": {"tags": os.path.getsize(tags) if os.path.isfile(tags) else 0,
                      "manifest": os.path.getsize(os.path.join(ld, "manifest.json")),
                      "symbols": os.path.getsize(os.path.join(ld, "symbols.json")),
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
        con.execute("CREATE TABLE t(name TEXT, path TEXT, line INTEGER, kind TEXT)")
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
                kind, lineno = "", 0
                for seg in parts[3:]:
                    if seg.startswith("kind:"):
                        kind = seg[5:]
                    elif seg.startswith("line:"):
                        try:
                            lineno = int(seg[5:])
                        except ValueError:
                            pass
                    elif not kind and seg and ":" not in seg and seg != "file":
                        kind = seg   # --fields=+Kn 裸值 kind
                rows.append((name, path, lineno, kind))
                n += 1
                if len(rows) >= 100000:
                    con.executemany("INSERT INTO t VALUES(?,?,?,?)", rows)
                    rows = []
                    prog(80 + 14 * n / max(1, total_lines),
                         "sqlite 导入 %d 行" % n)
        if rows:
            con.executemany("INSERT INTO t VALUES(?,?,?,?)", rows)
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
        return [(r[1], r[2], r[3]) for r in
                self._q("SELECT name, path, line, kind FROM t WHERE name=?", (name,))]

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
        kind, lineno = "", 0
        for seg in parts[3:]:
            if seg.startswith("kind:"):
                kind = seg[5:]
            elif seg.startswith("line:"):
                try:
                    lineno = int(seg[5:])
                except ValueError:
                    pass
            elif not kind and seg and ":" not in seg and seg != "file":
                kind = seg
        return (name, path, lineno, kind)

    def lookup(self, name):
        rows = []
        for line in self._run([], names=(name,)):
            r = self._parse(line)
            if r and r[0] == name:
                rows.append((r[1], r[2], r[3]))
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
                kind, lineno = "", 0
                for seg in parts[3:]:
                    if seg.startswith("kind:"):
                        kind = seg[5:]
                    elif seg.startswith("line:"):
                        try:
                            lineno = int(seg[5:])
                        except ValueError:
                            pass
                    elif not kind and seg and ":" not in seg and seg != "file":
                        # a383（存量 bug 实锤）：本库 ctags --fields=+Kn 产长名
                        # 裸值 kind（class/variable/function…，不带 kind: 前缀）
                        # ——旧解析恒空：符号面板徽标一直空白、definition 的
                        # file_local 优先级从未生效。裸段里除 kind 外只有
                        # extras=f 的 'file' 标记，可安全识别
                        kind = seg
                data.setdefault(name, []).append((path, lineno, kind))
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
        for path, lineno, kind in _be.lookup(name)[:6]:   # R16-10：与 F12 候选口径拉近
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
            cands.append((_r[1], _r[2], _r[3]))
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
            cands.append((sabs, ln, ""))
    if not cands:
        return {"symbol": symbol, "auto": False, "mode": "not-found",
                "candidates": []}

    out = []
    for path, lineno, kind in cands:
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

    def rank(c):
        return (
            0 if c["nm_lock"] else 1,                       # nm 符号级锁定最优先
            0 if c["file_local"] else 1,                    # 当前文件 static
            0 if c["in_build"] is True else 1,              # 编译白名单
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
