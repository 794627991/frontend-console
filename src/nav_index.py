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
    tmp = p + ".tmp"
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
        stale = False
        if meta.get("cmd_count", 0) == 0 and (probe.get("cmd_hits", 0) > 0):
            stale = True     # 建库时无产物、现在有了——白名单可升级
        elif meta.get("cmd_count", 0) > 0 and probe.get("cmd_hits", 0) == 0:
            stale = True     # 建库时有、现在浅层一个没有——树可能换了
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
    cmd_count = o_count = 0
    unit_by_base = {}   # basename（无后缀）-> [rel, ...] 编译单元源文件
    pending_o = []      # 未被 .cmd/同目录覆盖的 .o
    for abs_p, rel in _walk_files(root, should_cancel):
        low = rel.rsplit("/", 1)[-1].lower()
        if low.endswith(".cmd"):
            src = _parse_cmd_file(abs_p)
            if src and os.path.isfile(src):
                srel = os.path.relpath(src, root).replace(os.sep, "/")
                base, _ = os.path.splitext(rel)
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
        if (cmd_count + o_count) % 2000 == 0 and (cmd_count + o_count):
            say("  已发现 .cmd %d / .o %d …" % (cmd_count, o_count))
            prog(2 + min(28, (cmd_count + o_count) / 400), "扫描编译产物")
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
           root]
    try:
        env = dict(os.environ)
        env["LC_ALL"] = "C"
        r = subprocess.run(cmd, capture_output=True, timeout=3600,
                           creationflags=0x08000000, env=env)
    except FileNotFoundError:
        raise RuntimeError("ctags.exe 缺失（vendor/ctags/）")
    except subprocess.TimeoutExpired:
        raise RuntimeError("ctags 超时（60 分钟）——目录过大？")
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
            "cmd_count": cmd_count, "o_count": o_count,
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
        for path, lineno, kind in tags[name][:2]:
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


def import_nm_list(root, nm_file):
    """批3：Linux 侧 `find -name '*.o' | xargs nm -A --defined-only > syms.txt`
    输出清单的导入（可选增强——符号级消歧对齐真机）。格式：
    `rel/path.o: 00000000 T funcname`。合并进库的 symbols.json。"""
    root = os.path.abspath(root)
    ld = lib_dir(root)
    if not os.path.isfile(os.path.join(ld, "meta.json")):
        return False, "该目录没有索引库——先建索引"
    mf = _read_json(os.path.join(ld, "manifest.json")) or {}
    compiled = mf.get("compiled") or {}
    def _norm_o(x):
        x = x.replace(os.sep, "/").lower()
        return x[:-2] if x.endswith(".o") else x
    o_rel_to_src = {_norm_o(info["o"]): srel for srel, info in compiled.items()}
    syms = (_read_json(os.path.join(ld, "symbols.json")) or {}).get("symbols") or {}
    n_line = n_used = 0
    try:
        with open(nm_file, encoding="utf-8", errors="replace") as f:
            for line in f:
                n_line += 1
                # 形态：path.o: [addr] [TtDdBbRrCcWw] name
                m = re.match(r"^(.+?\.o):\s+(?:[0-9a-fA-F]+\s+)?([A-Za-z])\s+(\S+)$",
                             line.rstrip("\n"))
                if not m:
                    continue
                orel, typ, name = m.group(1), m.group(2), m.group(3)
                if typ not in "TtDdBbRrCcWw" or not name or name[0] in "$.":
                    continue
                srel = o_rel_to_src.get(_norm_o(orel))
                if not srel:
                    # 直接文件名兜底（nm 输出路径形态多样）
                    base = _norm_o(orel).rsplit("/", 1)[-1]
                    hits = [v for k, v in compiled.items()
                            if _norm_o(v.get("o") or "").rsplit("/", 1)[-1] == base]
                    srel = hits[0] if len(hits) == 1 else None
                if not srel:
                    continue
                lst = syms.setdefault(name, [])
                if srel not in lst:
                    lst.append(srel)
                n_used += 1
    except OSError as e:
        return False, "读清单失败：%s" % e
    _write_json(os.path.join(ld, "symbols.json"),
                {"version": 1, "symbols": syms, "nm_imported": True})
    with open(os.path.join(ld, "meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    meta["symbols"] = len(syms)
    meta["nm_imported"] = True
    _write_json(os.path.join(ld, "meta.json"), meta)
    _invalidate_cache()
    return True, "导入 %d 行 / 生效 %d 符号（总 %d）" % (n_line, n_used, len(syms))


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
    cmd = [rg, "--json", "--no-messages", "-w", symbol,
           "-g", "*.c", "-g", "*.h", "-g", "*.cpp", "-g", "*.hpp",
           "-g", "*.cc", "-g", "*.py", "-g", "*.js", "-g", "*.ts",
           "--max-count", "30", root]
    try:
        r = _sp.run(cmd, capture_output=True, timeout=120,
                    creationflags=0x08000000, env={"LC_ALL": "C", **os.environ})
    except Exception as e:
        return {"ok": False, "err": "rg 失败：%s" % e, "items": []}
    # 定义行集合（排除）
    dres = definition(file_path, symbol)
    deflines = {(os.path.normcase(c["path"]), c["line"])
                for c in (dres.get("candidates") or [])}
    mf = _load_json_cached(ld, "manifest.json", _manifest_cache)
    compiled = mf.get("compiled") or {}
    items = []
    import json as _json
    for line in (r.stdout or b"").decode("utf-8", "replace").splitlines():
        if len(items) >= limit:
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
    return {"ok": True, "items": items, "defs": len(deflines)}


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
    if not cands:
        return {"symbol": symbol, "auto": False, "mode": "not-found",
                "candidates": []}
    mf = _load_json_cached(ld, "manifest.json", _manifest_cache)
    compiled = mf.get("compiled") or {}
    syms = _load_json_cached(ld, "symbols.json", _symbols_cache).get("symbols") or {}
    root = lib["root"]

    # 决策链 0：nm 符号锁定（唯一编译单元定义了该符号）
    nm_lock = None
    nm_srcs = syms.get(symbol)
    if nm_srcs and len(nm_srcs) == 1:
        nm_lock = nm_srcs[0]

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
            "candidates": out[:30]}
