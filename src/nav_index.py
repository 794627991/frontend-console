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
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, p)


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
           "lib_dir": ld if meta else ""}
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
    ld = lib_dir(root)
    if os.path.isdir(ld):
        shutil.rmtree(ld, ignore_errors=True)
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
        os.replace(ld, new_ld)          # 目录整体改名（meta 改名后再写新库）
        _write_json(os.path.join(new_ld, "meta.json"), meta)
    else:
        _write_json(os.path.join(ld, "meta.json"), meta)
    _invalidate_cache()
    return True, "已关联到 " + new_root


# ------------------------------------------------------------------ 建库管线

def _walk_files(root, should_cancel=None):
    """生成 (abs_path, rel_posix)。跳过 _SKIP_DIRS。"""
    for r, ds, fs in os.walk(root):
        ds[:] = [d for d in ds if d not in _SKIP_DIRS]
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


def build(root, log=None, progress=None, should_cancel=None):
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
    say("阶段 1/3：扫描编译产物（.cmd/.o）…")
    prog(2, "扫描编译产物")
    compiled = {}       # rel_src_posix -> {"o": rel_o, "src": "cmd"|"omap"|"bmap"}
    o_files = []        # 相对 .o（符号表阶段用）
    cmd_count = cmd_files = o_count = 0
    unit_by_base = {}   # basename（无后缀）-> [rel, ...] 编译单元源文件
    pending_o = []      # 未被 .cmd/同目录覆盖的 .o
    for abs_p, rel in _walk_files(root, should_cancel):
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
            stem = rel[:-2]
            mapped = False
            for ext in _UNIT_EXTS:      # 同目录同名
                crel = stem + ext
                if os.path.isfile(os.path.join(root, crel)):
                    compiled.setdefault(crel, {"o": rel, "src": "omap"})
                    mapped = True
                    break
            if not mapped:
                pending_o.append(rel)
        else:
            b, ext = os.path.splitext(low)
            if ext in _UNIT_EXTS:
                unit_by_base.setdefault(b, []).append(rel)
        # a361：文件级进度（每 500 个产物/每 5000 个源文件报一行——死等变活）
        _tot = cmd_count + o_count + len(unit_by_base)
        if _tot and _tot % 5000 < 1:
            say("  扫描中：产物 %d（.cmd %d/.o %d）· 源文件 %d …"
                % (_tot, cmd_count, o_count, len(unit_by_base)))
            prog(2 + min(28, _tot / 800), "扫描 %d 文件" % _tot)
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
        say("  ⚠ 未发现构建产物——跳转按启发式排序（基线编译后重建可精确化）")

    # ---- 阶段 2：ctags 全量 ----
    say("阶段 2/3：ctags 全量索引（%s）…" % NAV_LANGS)
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
        while not _hb_stop.wait(3.0):
            try:
                sz = os.path.getsize(tags_tmp) / 1048576
            except OSError:
                sz = 0
            if int(sz) != _last:
                _last = int(sz)
                say("  ctags 写入中 %d MB…" % _last)
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
    os.replace(tags_tmp, tags)
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
        rcg = subprocess.run(
            [rgp, "-l", "--no-messages", "--no-ignore", "-F", "--max-filesize", "4M",
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
                {"generated": sorted(_gen)})
    if _gen:
        say("  生成文件黑名单：%d 个（Cython/lex/protobuf 等指纹）" % len(_gen))

    # ---- 阶段 3：ELF 符号表（pyelftools；缺库/失败降级）----
    say("阶段 3/3：读取 .o 符号表（符号级消歧）…")
    prog(78, "符号表")
    symbols = {}
    sym_ok = False
    try:
        import elftools  # noqa: F401
        sym_ok = True
    except ImportError:
        say("  ⚠ pyelftools 未安装——跳过符号级消歧（不影响跳转，白名单仍生效）")
    o_rel_to_src = {}
    for srel, info in compiled.items():
        o_rel_to_src[info["o"]] = srel
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

    meta = {"version": 1, "root": root,
            "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "langs": NAV_LANGS, "code_files": tag_lines,
            "cmd_count": cmd_count, "cmd_files": cmd_files, "o_count": o_count,
            "symbols": len(symbols),
            "sizes": {"tags": os.path.getsize(tags) if os.path.isfile(tags) else 0,
                      "manifest": os.path.getsize(os.path.join(ld, "manifest.json")),
                      "symbols": os.path.getsize(os.path.join(ld, "symbols.json"))}}
    _write_json(os.path.join(ld, "meta.json"), meta)
    prog(100, "完成")
    say("✓ 索引完成：%d 符号 / 白名单 %d 文件 / 库 %.1f MB"
        % (tag_lines, len(compiled),
           sum(meta["sizes"].values()) / 1048576))
    _invalidate_cache()
    return meta


# ------------------------------------------------------------------ 查询

_tags_cache = {"key": None, "data": None}   # (lib, mtime) -> {name:[entries]}
_tags_files_cache = {"key": None, "set": set()}   # R28-4：references 用文件路径集（mtime 缓存）
_symbols_cache = {"key": None, "data": None}
_manifest_cache = {"key": None, "data": None}
_cache_lock = threading.Lock()


def _invalidate_cache():
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


def symbols(file_path, q, limit=50):
    """工作区符号面板（Ctrl+T）：按发起文件反查库，前缀/子串匹配。
    返回 [{name, rel, line, kind, in_build, dist}]（按 前缀命中>子串>
    路径近 排序）。"""
    ld, lib = find_lib_for(file_path)
    if not ld:
        return {"ok": False, "err": "no-index", "items": []}
    tags = _load_tags(ld)
    mf = _load_json_cached(ld, "manifest.json", _manifest_cache)
    compiled = mf.get("compiled") or {}
    root = lib["root"]
    qlow = (q or "").strip().lower()
    if not qlow:
        return {"ok": True, "items": [], "mode": "empty"}   # 空查询不给全量
    exact, prefix, substr = [], [], []
    for name in tags:
        nl = name.lower()
        if nl == qlow:
            exact.append(name)
        elif nl.startswith(qlow):
            prefix.append(name)
        elif qlow in nl:
            substr.append(name)
    out = []

    def push(name):
        for path, lineno, kind in tags[name][:6]:   # R16-10：与 F12 候选口径拉近
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
    # R28-4（实锤：references 每次 ~3s）：旧版 74 万行逐行 normcase+normpath
    # （唯一文件仅 ~5 千，99% 重复劳动且无缓存）。两刀：①先收集原始路径去重
    # 再归一化；②mtime 缓存（对齐 _manifest_cache）。实测 3s → 毫秒级
    global _tags_files_cache
    try:
        _tp = os.path.join(ld, "tags")
        _tk = (ld, os.path.getmtime(_tp))
    except OSError:
        _tk = None
    if _tags_files_cache["key"] == _tk and _tk:
        tags_set = _tags_files_cache["set"]
    else:
        _raw = set()
        try:
            with open(os.path.join(ld, "tags"), encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.startswith("!"):
                        continue
                    parts = line.split("\t", 2)
                    if len(parts) >= 2:
                        _raw.add(parts[1])
        except OSError:
            pass
        tags_set = set(os.path.normcase(os.path.normpath(
            p if os.path.isabs(p) else os.path.join(root, p))) for p in _raw)
        _tags_files_cache = {"key": _tk, "set": tags_set}
    gen_set = set()
    _genf = _read_json(os.path.join(ld, "gen_files.json"))
    if _genf is None:
        # R28-3（实锤：旧库无 gen_files.json 垃圾全回涌无提示）：即时补扫
        # 一次（rg 指纹扫描复用 build 的指纹清单）并落盘——升级即生效
        try:
            _rgp = os.path.normpath(os.path.join(os.path.dirname(_CTAGS_EXE), "..", "rg.exe"))
            _fps = ["Generated by Cython", "A lexical scanner generated by",
                    "Generated by the protocol buffer compiler",
                    "/* Generated by pybind11", "This file was generated by SWIG",
                    "auto-generated", "AUTOGENERATED"]
            _rg = subprocess.run(
                [_rgp, "-l", "--no-messages", "--no-ignore", "-F", "--max-filesize", "4M",
                 "-g", "*.c", "-g", "*.cc", "-g", "*.cpp", "-g", "*.h", "-g", "*.py",
                 "-g", "!**/node_modules/**", "-g", "!**/.git/**"]
                + sum([["-e", fp] for fp in _fps], []) + ["--", root],
                capture_output=True, timeout=300, creationflags=0x08000000,
                env={"LC_ALL": "C", **os.environ})
            _genf = {"generated": sorted(
                os.path.normcase(os.path.normpath(l.strip()))
                for l in (_rg.stdout or b"").decode("utf-8", "replace").splitlines() if l.strip())}
            _write_json(os.path.join(ld, "gen_files.json"), _genf)
        except Exception:
            _genf = None
    if _genf and isinstance(_genf.get("generated"), list):
        gen_set = set(_genf["generated"])
    _genf = _read_json(os.path.join(ld, "gen_files.json"))
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
    tags = _load_tags(ld)
    cands = tags.get(symbol)
    if not cands:
        # 大小写不敏感重试（readtags 同款体验）
        low = symbol.lower()
        for k, v in tags.items():
            if k.lower() == low:
                cands = v
                break
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
