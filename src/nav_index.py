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
  3. 纯 struct 读 .o ELF 符号表（defined FUNC/OBJECT）→ symbols.json
     （a427 起无第三方依赖；原 pyelftools 因打包缺子模块弃用）

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
# a398 P0-4（内网报告实测：不含 Asm 时 850 个 .S 零 tag——entry.S/head.S
# 启动与异常处理代码全丢；加 Asm 仅 +3s，缺失 850→0）
NAV_LANGS = "C,C++,Asm,Python,JavaScript,TypeScript,Java,Go,Rust"
CODE_EXTS = {".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", ".hh", ".hxx",
             ".py", ".js", ".mjs", ".cjs", ".ts", ".java", ".go", ".rs",
             ".s", ".S"}
# 编译单元后缀（白名单/符号表只认这些——.h 是包含物不是单元）。
# a415R2 N13：补 .s（.S 汇编单元进白名单后，查询侧 in_build 判定/同名
# 映射没跟上——F12 会跳到未编译的同名 .S）
_UNIT_EXTS = {".c", ".cpp", ".cc", ".cxx", ".s"}
# 生成文件指纹扫描的 rg --max-filesize（a343：原 4M 恰好漏掉 4.06M 的
# Cython routes.c——写进 gen_files.json 的 scan_max 字段，旧库读到不一致
# 即自动补扫，不需要用户重建索引）
_GEN_SCAN_MAX = "32M"
# a398 P1-5（内网报告 §2.5 实测：工具自身缓存目录 11841 个文件白扫——
# .history 1864 / .cache 8117 / .ua 1856 / .codegraph 4）
_SKIP_DIRS = {".git", "node_modules", ".svn", ".hg", ".history", ".cache",
              ".ua", ".codegraph", ".agents", ".codex", ".vscode",
              ".tmp_versions", ".buildroot-ccache", "__pycache__"}
# a570（三档重构定稿 §三）：tmp 类目录完整名匹配后无条件剪枝（用户定调：
# 不检查内容）。G10 实测 sbuilder/output/build/boot-regbin/tmp/poifiles
# 有 35532 个文件且零 .cmd 价值。完整名匹配避免误伤 template/attempt。
_TMP_NAMES = {"tmp", "temp", "tmpdir", "tempdir"}
# a570（阻塞防护定稿）：单 item 硬超时（用户定调 180s）、看门狗巡检间隔、
# worker 总数上界（防卡死补 worker 无限增长）
_STALL_LIMIT = 180.0
_WD_TICK = 5.0
_MAX_WORKERS = 16
# a570 对抗审计（P1·第七轮 / 第十轮收敛）：硬卡死的 worker 永不退出，只按
# 线程总数限制名额会让队尾种子饿死。活跃名额按 `_MAX_WORKERS`，总线程数按
# `_hard_cap = max(8, N_WORKERS * 8)`（远程盘 64 / 本地盘 8，见 _walk_files）。
# a398：收录范围配置文件名（工程根，随 SVN 走团队共享——报告 §九推荐位）
SCOPE_FILE = ".fcpk-scope.json"
# a400（内网报告·用户令「只要有白名单一定用白名单」）：非 C/C++ 语言的
# "中间文件"——收录集出现任意一个即视为编译过，按白名单走不许私自全量
#   Python: .pyc/.pyo（__pycache__ 目录本身在 _ARTIFACT_DIRS 探测）
#   JS/TS : .js.map/.d.ts.map/.tsbuildinfo   Java: .class
#   Go    : .a/.test                          Rust : .d（dep-info）
_AUX_ARTIFACT_EXTS = (".pyc", ".pyo", ".class", ".tsbuildinfo",
                      ".js.map", ".d.ts.map", ".a", ".test", ".d")
# a400：产物目录——存在即算"编译过"（探测计数在剪枝前），内容不索引
_ARTIFACT_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache",
                  ".ruff_cache", "node_modules"}
# a401（内网报告）：软错误集——悬空符号链接（SMB 解析到不存在共享根：
# winerror 59/errno 22）与拒绝访问等单点不可读跳过；真断连靠连续计数闸
_SOFT_ERRNOS = {2, 3, 5, 13, 22, 206, 1920, 1921}
# a570 对抗审计（P2·第十一轮）：补 64（ERROR_NETNAME_DELETED，SMB 瞬时抖动
# 最典型一类）与 1231（网络位置不可达，链路抖动）——缺它们时单点抖动会绕过
# 「连续 N 个才判断连」的闸，直接当致命错误。
_SOFT_WINERR = {2, 3, 5, 53, 59, 64, 206, 1231, 1920, 1921}
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
           # a390：查询后端能力下发——前端档位下拉无 sqlite3 时藏 sql 档
           "sqlite_ok": sqlite_capable()}
    # a570：收录范围检测。v2 下 source 只可能是 project / v1-deprecated /
    # bad:*。v1 时明确告诉前端「旧格式已废弃」，不要显示成「未配置」。
    _sc, _sc_src = load_scope(root)
    if _sc:
        _dirs = _sc.get("dirs") or {}
        out["scope"] = {"source": "project",
                        "name": _sc.get("name", ""),
                        "mode": _sc.get("mode", "manual"),
                        "dir_count": len(_dirs),
                        "state_counts": {
                            "whitelist": sum(1 for v in _dirs.values()
                                             if v == "whitelist"),
                            "full": sum(1 for v in _dirs.values()
                                        if v == "full"),
                            "off": sum(1 for v in _dirs.values()
                                       if v == "off"),
                        },
                        "artifact_roots": (_sc.get("artifact_roots") or [])[:8]}
    elif _sc_src == "v1-deprecated":
        out["scope"] = {"source": "v1-deprecated", "name": "", "mode": ""}
    elif _sc_src.startswith("bad:"):
        out["scope"] = {"source": _sc_src, "name": "", "mode": ""}
    else:
        # 零配置：只有「识别出 sbuilder/内核形态」才下发提示（不写死模板）
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
            # a398（审计#14）：本次建库所用范围随 meta 下发（面板
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
    # a570：方案 A 下配置只在工程根。换根后配置跟着工程目录走，通常
    # 不需要迁移；但若旧根配置在、新根没有，则复制一份过去（不是移动——
    # 旧根文件属于旧路径，用户可能还会回去）。失败只记不抛（rebind 的
    # 主职责是绑库，配置迁移是附带的）。
    try:
        _sp_old = os.path.join(old_root, SCOPE_FILE)
        _sp_new = os.path.join(new_root, SCOPE_FILE)
        if os.path.isfile(_sp_old) and not os.path.isfile(_sp_new):
            import shutil as _sh
            _sh.copy2(_sp_old, _sp_new)
    except OSError:
        pass
    _invalidate_cache()
    return True, "已关联到 " + new_root


# ------------------------------------------------------------------ 建库管线

def _is_remote_fs(path):
    """网盘/UNC 判定（a396）：远程 FS 是 RTT 受限（每目录一次 SMB 往返），
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
                excl_names=(), excl_paths=(), stats=None,
                state_of=None, artifact_roots=(), dot_keep=False):
    """生成 (abs_path, rel_posix)（rel 一律相对 root）。
    a394→a396（用户实锤：W: 网盘大库阶段 1 扫描磨到像卡死）：网盘瓶颈是
    RTT——每目录一次 SMB 往返、单线程串行干等；并发分片 + 8 worker 近线性
    提速。停滞检测（120s 告警/300s 失败）与取消（消费侧循环头/DONE 双查）。
    a398：①subs=收录范围（scope.include 的 rel 目录列表；None=全 root）
    ②excl_names/excl_paths=scope 排除（名字任意层级/路径前缀，posix rel）
    ③P0-1 环防护：SMB 把 sysfs 自链符号链接展成无 reparse 标记的实体目录
    （内网报告 §2.1 实测单链 56 层多分叉组合爆炸，深度截断只砍最深分支、
    同层宽度照爆）——同名目录在一条路径上重复 >6 次即判环剪枝（报告 §8.1
    原方：depth>6 才启用计数，正常嵌套名不重复不误伤）
    ④点目录：a570 起按目录状态区分——`whitelist` 下保留（`.libs`/`.pio`
    里的 .o/.cmd 是合法产物输入），其余剪枝；点**文件**恒保留（Kbuild 的
    .foo.o.cmd 是白名单源）。
    a570（三档重构）：state_of(rel)->whitelist|full|off 决定收录（off 在
    scandir 层剪）；artifact_roots 为「仅产物源」目录（off 但仍扫 .cmd/.o）。
    stats 回填 {pruned, pruned_off, timeout_items, tmp_skipped}。"""
    import queue as _q
    import threading as _th
    say = say or (lambda _m: None)
    stats = stats if stats is not None else {}
    stats.setdefault("pruned", 0)
    N_WORKERS = 8 if _is_remote_fs(root) else 1   # a396：网盘并发/本地单线程
    out_q = _q.Queue(maxsize=256)
    _DONE = object()
    _err = [None]
    # a398（审计#17）：Windows 大小写不敏感——排除/跳过比较全部 lower
    # a570 对抗审计（P1·第十六轮）：用户 `exclude_names` 与硬编码 `_SKIP_DIRS`
    # 必须分开记——前者不该压过用户在该子树里显式勾的 white/full 后代
    # （否则面板显示「全 1」而实际零文件，死配置）。
    _hard_skip = {s.lower() for s in _SKIP_DIRS}
    _user_skip = {s.lower() for s in (excl_names or ())}
    _skip = _hard_skip | _user_skip
    _excl = tuple(sorted(p.strip("/").lower() for p in (excl_paths or ())
                         if p and p != "."))

    def _excluded(rel_l):
        for ep in _excl:
            if rel_l == ep or rel_l.startswith(ep + "/"):
                return True
        return False

    # a570：产物源目录（posix rel 小写），供「off 但扫产物」判定
    _arts = tuple(sorted(p.strip("/").lower() for p in (artifact_roots or ())
                         if p and p != "."))
    # a570：stats 由 8 worker + 分片阶段并发写，_keep_dir 也在分片期调用，
    # 锁必须先于 _keep_dir 定义
    _alock = _th.Lock()

    def _in_artifacts(rel_l):
        """rel 是产物源本身 / 其祖先 / 其后代 → True。
        祖先必须放行才能下去；后代必须放行才能读 .cmd/.o。"""
        if not rel_l:
            return True          # 根永远不剪
        for a in _arts:
            if rel_l == a or a.startswith(rel_l + "/") \
                    or rel_l.startswith(a + "/"):
                return True
        return False

    def _inside_art(rel_l):
        """rel 在产物源**自身或后代**内（不含祖先）——「仅产物源」语义
        只对这片区域生效（祖先只是下钻通道，其源码仍按三态收）。"""
        if not rel_l:
            return False
        for a in _arts:
            if rel_l == a or rel_l.startswith(a + "/"):
                return True
        return False

    def _state(rel_l):
        return state_of(rel_l) if state_of else None

    def _live_below(rel_l):
        fn = getattr(state_of, "has_live_desc", None)
        return bool(fn(rel_l)) if fn else False

    def _under_live(rel_l):
        """该路径是否落在用户显式 white/full 子树内（含自身）。"""
        fn = getattr(state_of, "under_live", None)
        return bool(fn(rel_l)) if fn else False

    def _scandir(d):
        with os.scandir(d) as it:
            ds, fs = [], []
            for e in it:
                (ds if e.is_dir() else fs).append(e.name)
        return ds, fs

    def _keep_dir(name, rel_l):
        # a570 对抗审计：统一 lower——`_in_artifacts`/`_arts` 是比较 lower 的，
        # 而调用点传的是磁盘真实大小写。`_resolve_dir_state` 自己也 lower（幂等）。
        rel_l = (rel_l or "").lower()
        _nl = name.lower()
        # a570 对抗审计（P0·第十七轮）：硬规则（_SKIP_DIRS/.git、_TMP_NAMES）
        # **不能**被用户排除名解锁——原实现先判 `_skip`，而 `_skip` 是
        # 硬规则与用户名的并集，于是 exclude_names=[".git"]/["tmp"] 会让
        # `.git`/`tmp` 变成「可以靠 live 后代放行」的普通目录，硬剪失效
        # （实测 `.git/src/evil.c` 进了索引）。硬规则先判、一律剪。
        if _nl in _hard_skip:
            return False
        if _nl in _TMP_NAMES:
            # a570：tmp 类无条件剪（用户定调，不检查内容），但计数让用户可见
            with _alock:
                stats["tmp_skipped"] = stats.get("tmp_skipped", 0) + 1
            return False
        if _nl in _user_skip:
            # a570 对抗审计（P1·第十六轮）：用户排除名命中的子树里若有
            # 显式 white/full 后代（含自身），必须下钻——与 off 分支对称。
            # 最终文件取舍由 _emit 的 _under_live 决定。
            if _live_below(rel_l):
                return True
            return False
        if name.startswith("."):
            # a570：点目录按状态区分。
            # a570 对抗审计（P1）：产物源扫描（artifact walk）**不传
            # state_of**，`_state()` 恒 None，点目录会被全部剪掉——但
            # `.libs`/`.pio` 里的 .o/.cmd 是合法产物输入（a398 审计#23）。
            # 该场景用 dot_keep=True 显式放行。
            # a570 对抗审计（P2·第十一轮）：full 档也要保留点目录——
            # 原只在 whitelist 保留，`lib: full` 时 `lib/.libs/*.o` 被剪
            # （a398#23 实测回归）。点目录里的 .o 对白名单推导有价值，
            # 而 full 档无论如何全收源码，多收几个也是对的。
            if dot_keep:
                return True
            _st_dot = _state(rel_l)
            if _st_dot in ("whitelist", "full") or _in_artifacts(rel_l):
                return True
            # a570 对抗审计（P2·第十五轮）：点目录自身 off、但子树里有显式
            # white/full 后代时也必须下钻（否则那条配置是死配置，面板显示
            # 「白 N」而实际零文件）。
            return _live_below(rel_l)
        st = _state(rel_l)
        if st == "off" and not _in_artifacts(rel_l):
            # a570 对抗审计：off 但子树里有用户显式设成 white/full 的节点
            # → 必须继续下钻，否则那条配置是死配置（面板显示「白 1」
            # 而实际零文件被收录）。
            if _live_below(rel_l):
                return True
            with _alock:
                stats["pruned_off"] = stats.get("pruned_off", 0) + 1
            return False
        return True

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
    # a398（审计#15）：重叠/重复 include 去重 + 剔除被包含的基（同树双走
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
            # a570 对抗审计（P1·第十六轮）：分片阶段是**同步**跑的，worker 与
            # 看门狗都还没启动——远程盘上任一 scandir 卡死，取消与 180s 硬
            # 超时都无从生效（实测「取消」后线程仍存活）。这里补检查点。
            if should_cancel and should_cancel():
                raise Cancelled("cancel")
            if _excluded(os.path.relpath(base, root).replace(os.sep, "/").lower()):
                continue
            try:
                l1_ds, b_fs = _scandir(base)
            except OSError as _e:
                # 与 worker 阶段一致：单个不可读根软跳过，不整库失败
                say("  ⚠ 收录根不可读，已跳过：%s（%s）"
                    % (base, str(_e)[:80]))
                with _alock:
                    stats["soft_skipped"] = stats.get("soft_skipped", 0) + 1
                continue
            # a400：种子层同探测产物目录（L1 在 worker 之前被过滤）
            stats["artifact_dirs"] = stats.get("artifact_dirs", 0) + sum(
                1 for d in l1_ds if d.lower() in _ARTIFACT_DIRS)
            l1_ds = [d for d in l1_ds
                     if _keep_dir(d, (os.path.relpath(base, root)
                                      .replace(os.sep, "/") + "/" + d)
                                  if base != root else d)]
            pre_batches.append((base, b_fs))
            if len(l1_ds) >= N_WORKERS:
                seeds.extend(os.path.join(base, d) for d in l1_ds)
            else:
                # 一级子目录太少（并发吃不满）：拆到二级
                for d in l1_ds:
                    if should_cancel and should_cancel():
                        raise Cancelled("cancel")
                    p = os.path.join(base, d)
                    try:
                        l2_ds, l2_fs = _scandir(p)
                    except OSError:
                        seeds.append(p)   # 展不开（权限/断连）：整子树任务
                        continue
                    pre_batches.append((p, l2_fs))
                    l2_rel = (os.path.relpath(p, root).replace(os.sep, "/"))
                    seeds.extend(os.path.join(p, s2)
                                 for s2 in l2_ds
                                 if _keep_dir(s2, (l2_rel + "/" + s2)
                                              if l2_rel not in (".", "")
                                              else s2))
    except OSError as e:
        raise RuntimeError("目录扫描失败（%s）" % e)

    work_q = _q.Queue()
    for s in seeds:
        work_q.put(s)
    _abandoned = [False]   # a398（审计#21）：消费侧退出后 worker 放弃投递

    def _loop_prune(r, sub):
        """a398（审计#2）：环防护收紧——只统计 sub 以下的路径段（base 段
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

    # a570（阻塞防护定稿）：item 级硬超时 + worker 补偿。
    # 为什么不是「目录级推进」：G10 hikudev-head 实测 60 秒推进 893 个目录
    # （0.067s/目录），任何「无推进」判据都永不触发；用户要解决的是「一个
    # 单元扫太久拖垮整体」，所以计时单元 = work_q 的一个 item（种子子树）。
    _sub_start = {}          # worker 名 -> (sub_abs, t0, gen)
    _gen = [0]
    _dead = {}               # worker 名 -> 已判超时并已主动放弃的**世代号**
    _live = set()            # 线程仍存活的 worker 名
    # a570 对抗审计（P0·第五轮，最终设计）：
    #   前五轮反复在 DONE 判定上翻车（_active 双扣 / _waiting 被移出 /
    #   _stalled 残留 / 最后退出者不看队列），根因是**拿线程状态推断工作是否
    #   完成**。改成直接对「工作项」记账：
    #
    #   `_pending` = 已发出但未结算的 item 数。取值两条路径二选一：
    #     · 正常完成（os.walk 耗尽/异常）→ item 级 finally 里减 1
    #     · 被判超时放弃            → 看门狗里减 1（且 worker 后续看到
    #                                  `_dead` 会立刻 return，不重复结算）
    #   `_pending` 归零 = 队列里没有待取任务、也没有任何在飞/被放弃的 item
    #   ⇒ 才发 DONE。这是唯一判据，worker 退出、看门狗都走它。
    _pending = [0]
    _done_sent = [False]
    _sending = [False]
    _settled_gens = set()     # 已结算的 item 世代号（恰好一方能结算成功）
    # a570 对抗审计（P2·第九轮）：硬上限按并发档位缩放——本地盘（单 worker）
    # 硬卡通常是磁盘故障，补到 64 个线程只是 64 倍 IO 压力且毫无收益。
    _hard_cap = max(8, N_WORKERS * 8)
    _dl = _th.Lock()
    _wd_stop = _th.Event()
    _wd = [None]             # 看门狗线程句柄

    def _spawn_worker():
        # a570 对抗审计（P1·第八轮）：`_gen` 自增与 `_live` 登记必须在同一
        # 锁内（原在锁外，与 worker 内锁内的自增共用计数器，理论上会丢增量
        # → gen 复用 → `_settled_gens` 误判 no-op）。`Thread.start()` 留在
        # 锁外（它会调系统调用）。启动失败时**回滚 `_live`**——原实现失败
        # 也留一个幽灵名，名额被永久虚占（约 64 次后彻底不给名额）。
        with _dl:
            _gen[0] += 1
            name = "nav_walk_%d_%d" % (_gen[0], _th.get_ident())
            _live.add(name)
        try:
            t = _th.Thread(target=_worker, name=name, daemon=True)
            t.start()
        except Exception:
            with _dl:
                _live.discard(name)
            raise

    def _maybe_done(block=True):
        """所有工作项都已结算且队列为空 → 发 DONE（幂等，单次投递）。

        a570 对抗审计（第五轮）：`_done_sent` 只在**真正投递成功后**置位。
        原实现先置位再投递，投递失败（队列满）就永久丢失 DONE，消费侧只能
        等 300s idle 报错。

        a570 对抗审计（P2·第六轮）：检查 `_done_sent` → 投递 → 置位必须在
        同一把锁内裁决，否则两个线程可能各投一条 DONE（无害但脏）。这里用
        `_sending` 标志占位：占位者投递，失败则清标志让后来者重试。

        `block=False` 供看门狗用——它**绝不能阻塞**（队列满时阻塞会让整个
        看门狗停摆，超时判定与补 worker 全部失效）。失败留给下个 tick 重试，
        或在 worker 退出路径（block=True）兜底。
        """
        with _dl:
            if _done_sent[0] or _sending[0]:
                return
            if _pending[0] != 0 or not work_q.empty():
                return
            _sending[0] = True
        ok = False
        try:
            ok = _send_done(block=block)
        finally:
            # a570 对抗审计（P2·第七轮）：`_send_done` 抛非 Full 异常时
            # 占位必须复位，否则此后所有 _maybe_done 短路 → DONE 永不发。
            with _dl:
                _sending[0] = False
                if ok:
                    _done_sent[0] = True

    def _settle(gen, block=True):
        """按世代号结算一个 item。

        a570 对抗审计（P1·第六轮）：原实现用 worker 局部的 `_settled=[False]`
        做「谁结算」的凭据——看门狗代结算后 worker 若**没走到 `_dead` 检查点**
        （walk 尾部长尾 / 异常结束 / cancel return）仍会再结算一次，`_pending`
        少减 → 提前 DONE → 仍在产出的 item 被截断（端到端实测 100% 丢文件）。
        改成按 gen 的共享集合：**恰恰一方**结算成功，另一方 no-op。
        """
        with _dl:
            if gen in _settled_gens:
                return False
            _settled_gens.add(gen)
            if _pending[0] > 0:
                _pending[0] -= 1
            else:
                # a570 对抗审计（P2·第七轮）：不该发生；真发生说明记账有
                # 缺陷，别静默吞掉——记进 stats 让用户/日志能看见。
                stats["settle_underflow"] = stats.get("settle_underflow", 0) + 1
        # a570 对抗审计（P1·第七轮）：看门狗路径绝不能阻塞——`block=False`
        # 透传下去，否则队列满时看门狗停摆，超时判定与补 worker 全失效。
        _maybe_done(block=block)
        return True

    def _send_done(block=True):
        # a415R2 N4：DONE 重试到消费侧放弃为止——原先 timeout=5 丢弃后，
        # 消费侧只是暂时忙（没退出）就会死等到 300s 停滞误判。
        # a570 对抗审计（P2·第四轮）：看门狗不能阻塞——out_q 满时这里会
        # 一直重试，看门狗线程停摆，此后超时判定与补 worker 全部失效。
        # 看门狗路径用 block=False（发不出去就算了，worker 退出时还会再发）。
        if not block:
            try:
                out_q.put_nowait(_DONE)
                return True
            except _q.Full:
                return False
        while not _abandoned[0]:
            try:
                out_q.put(_DONE, timeout=1.0)
                return True
            except _q.Full:
                continue
        return False

    def _watchdog():
        while not _wd_stop.wait(_WD_TICK):
            if _abandoned[0]:
                return
            try:
                _watchdog_tick()
            except Exception:
                # a570 对抗审计（P1）：原实现整体无 try——`list(d.items())`
                # 撞并发写抛 RuntimeError 会让看门狗线程直接死亡且无人重启，
                # 此后 180s 超时与补 worker 全部失效。吞掉单轮异常继续跑。
                pass

    def _watchdog_tick():
        now = time.time()
        # a570 对抗审计（P1）：遍历在 _dl 内完成——原实现在锁外
        # `list(_sub_start.items())`，worker 并发写会抛「dictionary changed
        # size during iteration」。
        with _dl:
            _snap = list(_sub_start.items())
        _settle_later = []
        for name, (sub, t0, gen) in _snap:
            if now - t0 < _STALL_LIMIT:
                continue
            with _dl:
                # a570 对抗审计（P1）：按**世代号**比对，不是「名字出现过」。
                # 原 `if name in _dead: continue` 让同一 worker 的第二、
                # 第三个 item 超时被永久跳过（本地盘单 worker 等于防护只
                # 生效一次），既不记 timeout_items 也不补 worker。
                if _dead.get(name) == gen:
                    continue
                cur = _sub_start.get(name)
                if not cur or cur[2] != gen:
                    continue       # 快照之后已换 item
                _dead[name] = gen  # worker 在下一个 yield 检查点会 return
                # a570 对抗审计（P1·第四轮）：pop 必须在**同一把锁内**并
                # 复查世代号——原实现先在锁内写 _dead、再在锁外无条件 pop，
                # worker 恰在此刻换 item 会被误删登记，该 item 永久失去超时
                # 保护（180s 硬约束被破坏）。
                if _sub_start.get(name) and _sub_start[name][2] == gen:
                    _sub_start.pop(name, None)
                _cur_d.pop(name, None)
                # a570（P0·第五轮 + P1·第六轮）：被放弃的 item 在此按 gen
                # 结算（与 worker 的 item-finally 互斥，先到先得）。
                _settle_later.append(gen)
            rel = (os.path.relpath(sub, root).replace(os.sep, "/")
                   if sub != root else ".")
            with _alock:
                # a570 对抗审计（P2·第十二轮）：调用方可能传非 list（公开
                # 函数），append 抛异常会被 `_watchdog` 的 except 吞掉 →
                # 本 tick 的 _settle_later 全部漏结算 → 挂到 idle 超时。
                if not isinstance(stats.get("timeout_items"), list):
                    stats["timeout_items"] = []
                stats["timeout_items"].append(
                    {"rel": rel, "elapsed": round(now - t0, 1)})
            try:
                say("  ⚠ 扫描超时 %ds，已跳过该子树：%s"
                    % (int(_STALL_LIMIT), rel))
            except Exception:
                # a570 对抗审计（P2·第七轮）：用户传入的 log callable 抛
                # 异常时，不能让本 tick 半途退出（`_settle_later` 里的 gen
                # 会永久漏结算 → `_pending` 永不归零 → 挂到 idle 超时）。
                pass
            # 补 worker：两个上界同时生效。
            # a570 对抗审计（P1·第四轮）：活跃名额必须对**能干活**的线程数
            # 生效——原按线程总数算，判过超时但仍干活的会被当成空名额，
            # 200 种子实测 200 线程。
            # a570 对抗审计（P1·第七轮）：但硬卡死在系统调用里的线程永远
            # 不退出，若只按线程总数判名额，全员僵死时永不补人 → 队尾健康
            # 种子被饿死（实测 16 硬卡 + 16 健康 → 健康 100% 静默丢失）。
            # 所以：活跃名额按 `_MAX_WORKERS`，总线程数按 `_hard_cap`
            # （= max(8, N_WORKERS*8)，远程盘 64 / 本地盘 8）。
            with _dl:
                _n_live = len(_live)
                _n_active = len(_live - set(_dead))
            if _n_active < _MAX_WORKERS and _n_live < _hard_cap \
                    and not work_q.empty() and not _abandoned[0]:
                try:
                    _spawn_worker()
                except Exception:
                    pass
            # a570 对抗审计（第十轮收敛）：**删掉了**「线程已用尽」的主动
            # 报错。理由：① 该判据无法可靠区分「全员僵死」与「有 worker
            # 正在干活、只是若干僵尸把总数顶到上界」（第八/九/十轮连续三次
            # 误报复现）；② 它的触发延迟随 `_STALL_LIMIT` 线性放大（生产
            # 参数下要 24 分钟），达不到「快速失败」的目的；③ 真正需要它
            # 覆盖的场景（全员硬卡）本身极罕见，且消费侧 300s idle 兜底
            # 已经会给出结构化失败。宁可少见一次慢失败，也不要常见的误报
            # 失败——后者会让「数据其实扫完了」的建库被判失败。
        # a570：锁外结算（`_settle` 内部自己取锁），再尝试收口。
        for _g in _settle_later:
            _settle(_g, block=False)
        # 非阻塞：看门狗阻塞会让超时判定与补 worker 全部停摆。
        _maybe_done(block=False)

    def _worker():
        # try/finally 包全程：取消 return 也不许跳过 _live 移出——否则
        # DONE 永远不发、消费侧死等停滞超时（自审实锤）
        me = _th.current_thread().name
        _soft_errs = [0]   # a409 BUG-3：连续软错误计数——worker 全程
                           # 跨 sub 累加（每 sub 重置会让多子树分摊绕过闸）
        _my_gen = [-1]
        try:
            while True:
                # a570 对抗审计（P1·第六轮）：取 item 与 `_pending += 1`
                # 必须是**同一临界区**——原实现在 get_nowait 与 +1 之间的
                # 窗口里 `_pending==0 && work_q.empty()` 成立，`_maybe_done`
                # 提前发 DONE（真实调度 80 轮丢 1~4 次）。锁内取队列入队
                # 不涉及阻塞调用（同进程 Queue），开销可忽略。
                with _dl:
                    try:
                        sub = work_q.get_nowait()
                    except _q.Empty:
                        break
                    _gen[0] += 1
                    gen = _gen[0]
                    _pending[0] += 1
                    _my_gen[0] = gen
                    _sub_start[me] = (sub, time.time(), gen)
                try:
                    # a415R2 N5 + 内网报告 a401：onerror 分级。原软错误集漏了
                    # 悬空符号链接（rootfs 的 lib64->/usr/lib 被 SMB 解析到不
                    # 存在的共享根：scandir=winerror 5，walk=winerror 59/
                    # errno 22）→ 判 SMB 断连整库失败。扩集 {13,22,53,59}，
                    # 但加连续计数闸：真断连时每个待访目录都报错，很快超
                    # _CONSEC_LIMIT 判真断仍抛错；悬空软链零散几个不触发。
                    # a409 BUG-3：_soft_errs 定义已上移到 while 之前
                    #（跨 sub 累加）——原在 per-sub 循环内每棵子树重置，
                    # 55 个软错误分两子树（30+25）即绕过闸静默成功（审计实测）
                    def _on_err(e):
                        # a570 对抗审计（P1·第十三轮）：本 item 已被看门狗判
                        # 超时放弃时，苏醒后的错误**不该**记进 `_err`——该
                        # 子树的数据已按「放弃」处理，DONE 分支据此判整库
                        # 失败会把「数据其实已收全」的建库废掉（实测 4800
                        # 文件全出却报失败）。只计软错误计数，不置 `_err`。
                        with _dl:
                            _discarded = _dead.get(me) == _my_gen[0]
                        we = getattr(e, "winerror", None)
                        en = getattr(e, "errno", None)
                        if we in _SOFT_WINERR or en in _SOFT_ERRNOS:
                            # a570 对抗审计（P1·第十四轮）：已放弃 item 苏醒
                            # 后打的软错误不能累加——它会把计数推到闸值，
                            # 下一个健康 item 的一个普通软错误就整库失败
                            # （生产参数实测 1.3s 即失败，文件其实全收齐）。
                            if not _discarded:
                                _soft_errs[0] += 1
                                # a570 对抗审计（P2·第十六轮）：已放弃 item 的
                                # 噪声不能计入 soft_skipped——它会打出「跳过
                                # 300 个不可读目录」的假告警，引用户去查权限。
                                with _alock:
                                    stats["soft_skipped"] = (
                                        stats.get("soft_skipped", 0) + 1)
                            if _soft_errs[0] > _CONSEC_LIMIT and not _discarded:
                                if _err[0] is None:
                                    _err[0] = e   # 连续爆炸=网络真断
                                # a570 对抗审计（P2·第十一轮）：原实现无条件
                                # 覆盖，会把更早的真实根因冲掉。
                            return
                        if _err[0] is None and not _discarded:
                            _err[0] = e
                    for r, ds, fs in os.walk(sub, onerror=_on_err):
                        # a570 对抗审计（P0·第三轮）：被看门狗判超时的 item
                        # **立即停止**。这才是「超时目录直接放弃」的本义——
                        # 原实现只是记录了一个超时条目，worker 继续扫，于是
                        # 「DONE 何时发」变成悬而未决的问题（早发丢数据、晚
                        # 发卡死）。这里的 return 让 worker 干净退出，DONE
                        # 判据回归「所有 worker 都已退出」。
                        with _dl:
                            _abandoned_item = _dead.get(me) == _my_gen[0]
                        if _abandoned_item:
                            # a570 对抗审计（P0·第五轮）：超时只放弃**这个
                            # item**，worker 必须继续取下一个——用户定调
                            # 「超时目录直接放弃，其余继续」。原实现 `return`
                            # 会退出整个线程，队列里剩余的种子无人处理，
                            # 实测 24 种子只有 16 个被扫（其余连 timeout_items
                            # 都不记）。
                            # 看门狗已代结算（按 gen 记账，item-finally
                            # 里的 _settle 会 no-op）。
                            break
                        # a570 对抗审计（P1·第十轮）：`_soft_errs` 的语义是
                        # **连续**软错误计数（闸门名 `_CONSEC_LIMIT`），但原
                        # 实现从不归零——大盘上零散 51 个「拒绝访问」就判整库
                        # 失败（1530 个目录其实都正常产出）。成功遍历一个目录
                        # 即视为「链路恢复」，清零。
                        _soft_errs[0] = 0
                        # a424：暴露 worker 当前目录（停滞告警用——用户能看到
                        # 到底卡在哪个目录上，而不是只知道「没进展」）
                        # 2026-11-23 总审计 a684-A4：看门狗摘键持 _dl、这里裸写
                        # ——同一本账两种护法。GIL 下侥幸无害，全部收到 _dl 下
                        # （锁内只有单键赋值，每目录一次，开销可忽略）。
                        with _dl:
                            _cur_d[me] = r
                        # a400（用户令·白名单优先）：产物目录存在即算"编译过"
                        # ——探测计数**在剪枝之前**（__pycache__ 里的 .pyc
                        # 目录一剪就永远扫不到）；探测完照常剪掉不索引
                        _arts_hit = sum(1 for d in ds
                                        if d.lower() in _ARTIFACT_DIRS)
                        if _arts_hit:
                            # a452（审计 P2）：stats 跨 8 个 worker 共享，裸
                            # 读-改-写会丢更新（artifact_dirs 还参与
                            # _has_artifact 判档）。与其他 stats 同用 _alock。
                            with _alock:
                                stats["artifact_dirs"] = \
                                    stats.get("artifact_dirs", 0) + _arts_hit
                        ds[:] = [d for d in ds if _keep_dir(
                            d, (os.path.relpath(r, root).replace(os.sep, "/")
                                + "/" + d))]
                        # P0-1 环防护（SMB 自链，报告 §2.1）
                        if _loop_prune(r, sub):
                            ds[:] = []
                            with _alock:
                                stats["pruned"] += 1
                            continue
                        if _excluded(os.path.relpath(
                                r, root).replace(os.sep, "/").lower()):
                            ds[:] = []
                            continue
                        if should_cancel and should_cancel():
                            return
                        # a398：有界投递+放弃检查（消费侧取消/异常后 worker
                        # 不再卡死在满队列上——每次泄漏 8 线程的旧账）
                        # a570：补 should_cancel——用户取消后消费侧不会再
                        # 取走队列，worker 会永远卡在满队列上
                        while True:
                            if _abandoned[0]:
                                return
                            if should_cancel and should_cancel():
                                return
                            try:
                                out_q.put((r, fs), timeout=1.0)
                                break
                            except _q.Full:
                                continue
                    # a570 对抗审计（P2·第十六轮）：os.walk 正常结束 = 该 item
                    # 的数据已全部投递。摘掉超时登记，避免「walk 之后的慢收尾
                    # 被看门狗判超时」→ 汇总成「这些目录未进索引」的假告警
                    # （实测数据全收齐却报 3 个超时）。结算仍在 finally。
                    with _dl:
                        if _sub_start.get(me) and _sub_start[me][2] == gen:
                            _sub_start.pop(me, None)
                except Exception as e:   # SMB 断连等：记录，其余子树继续
                    # a570 对抗审计（P2·第十轮）：只在空槽写——原实现后到
                    # 者覆盖先到者，真实根因（如看门狗写的「线程已用尽」）
                    # 会被worker 的次要错误冲掉，误导排障。
                    # a570 对抗审计（P1·第十三轮）：已被判超时放弃的 item
                    # 苏醒后抛的异常不算错误（该子树已按「放弃」记账）。
                    with _dl:
                        _disc2 = _dead.get(me) == _my_gen[0]
                    if _err[0] is None and not _disc2:
                        _err[0] = e
                finally:
                    # a570：item 扫完（正常/异常）都要摘登记，否则看门狗
                    # 误判「还在处理旧 item」。同时清 `_dead`——见第五轮审计。
                    with _dl:
                        _sub_start.pop(me, None)
                        _dead.pop(me, None)
                    # a570（P0·第五轮 + P1·第六轮）：按 gen 结算，与看门狗
                    # 的代结算互斥（先到先得，后来者 no-op）。
                    _settle(gen)
                    # a570 对抗审计（P2·第十五轮）：软错误计数按 item 归零——
                    # 「连续」语义的边界应是 item，否则放弃前的累计会带到
                    # 下一个健康 item（50 + 1 就整库失败）。
                    _soft_errs[0] = 0
        finally:
            # a452（审计 P2）：worker 退出必须从 _cur_d 摘掉自己——否则停了
            # 告警仍会打印已结束 worker 的最后目录，并把「在跑 worker 数」
            # 算多（用户看到的进度信息是错的）。
            # a684-A4：与其它三本账同一把锁摘。
            with _dl:
                _cur_d.pop(me, None)
                _sub_start.pop(me, None)
                _live.discard(me)
                _dead.pop(me, None)   # 世代号键随线程一起清，避免残留
            # a570 对抗审计（P0·第五轮）：收口判据统一是 `_pending` 记账，
            # 与线程存活无关。worker 退出时也试一次（最后退出的那个通常
            # 就是收口点）。
            _maybe_done()

    _n = min(N_WORKERS, len(seeds))
    _cur_d = {}          # a424：worker 当前正在扫描的目录（线程名→路径）
                         # a425 BUG：必须在**线程启动之前**赋值——worker 内
                         # 引用它，放到 start() 之后是竞态（本地单线程侥幸赢，
                         # 远程 8 worker 必输：cannot access free variable
                         # '_cur_d' where it is not associated with a value）
    # a570 对抗审计（P2）：Thread.start() 可能抛 RuntimeError（线程耗尽），
    # 此时已 spawn 的 worker 会因 _abandoned 未置位而在队列上死等——整体
    # 包 try，失败时把已起的 worker 全部放弃并抛。
    try:
        for _i in range(_n):
            _spawn_worker()
    except Exception:
        _abandoned[0] = True
        raise
    if _n == 0:
        out_q.put(_DONE)   # 无子树：收录根直下文件即全部
    # a570：看门狗（item 级硬超时 + 补 worker）。_n==0 时不启动，避免空转
    if _n > 0:
        _wd[0] = _th.Thread(target=_watchdog, name="nav_walkdog",
                            daemon=True)
        _wd[0].start()

    def _emit(r, fs):
        # a570 对抗审计（P0）：
        # ① 目录放行 ≠ 其直下文件收录。off 目录如果因「子树里有显式
        #    whitelist/full 后代」被放行下钻，它自身直下的文件仍必须按
        #    该目录的状态过滤——否则面板显示「不勾」而实际全进了索引。
        # ② 「仅产物源」目录（artifact_roots 自身及后代）同样只收 .cmd/.o，
        #    不能把生成源码/host 工具链源码拉进索引（设计 §4.1；G10 的
        #    sbuilder 有 3.9 万个源文件，全收等于索引爆炸）。
        _rd = (os.path.relpath(r, root).replace(os.sep, "/")
               if r != root else "")
        _rd_l = _rd.lower()
        _only_art = _inside_art(_rd_l)
        # a570 对抗审计（P2·第十七轮）：排除名命中的路径段判定必须两个分支
        # 共用——原只有主分支查，artifact 分支漏了，`out/gen/x.o` 仍被收集。
        _seg_hit = any(s.lower() in _user_skip for s in _rd.split("/"))
        if _seg_hit and not _under_live(_rd_l):
            return
        # a570 对抗审计（P2·第十六轮）：产物源区内用户显式勾了 white/full 的
        # 子树必须按显式状态收源码——否则那条配置是死配置（面板显示「白 1」
        # 而实际零文件）。祖先挂的 artifact_roots 不该压过显式后代。
        # a570 对抗审计（P1·第十八轮）：判据必须是**显式** live 节点，不能读
        # `_state()`——它把根默认（manual 下 = whitelist）也算进来，于是
        # `dirs={"rootfs":"off"}` + `artifact_roots=["sbuilder/output/build"]`
        # 这种合法导入配置会让整个产物源区源码进索引（实测）。
        if _only_art and _under_live(_rd_l):
            _only_art = False
        _dir_off = (not _only_art) and state_of is not None \
            and _state(_rd_l) == "off"
        if _dir_off:
            # a570 对抗审计（P2·第十四轮）：off 目录**直下**的 .cmd/.o 原本
            # 也放行，于是 off 区的 .o 被同目录同名映射写成 compiled 条目，
            # 查询期 in_build=True 把 off 区符号排到真定义之上（实测
            # dirs={kernel:off, kernel/src:whitelist} → compiled 含
            # kernel/leak.c）。off 区按定义「不收」，一律不产出。
            # 注意：artifact_roots 的 .cmd/.o 走下面的 `_only_art` 分支。
            return
        if _only_art:
            for f in fs:
                if should_cancel and should_cancel():
                    raise Cancelled()
                _fl = f.lower()
                if not (_fl.endswith(".cmd") or _fl.endswith(".o")):
                    continue
                rel = os.path.relpath(r + os.sep + f, root).replace(os.sep, "/")
                if _excluded(rel.lower()):
                    continue
                yield os.path.join(r, f), rel
            return
        for f in fs:
            if should_cancel and should_cancel():
                raise Cancelled()
            rel = os.path.relpath(r + os.sep + f, root).replace(os.sep, "/")
            if _excluded(rel.lower()):
                # a570 对抗审计（P1·第十六轮）：exclude_paths 命中的路径里，
                # 用户显式勾了 white/full 的子树仍要收——否则那条配置是死
                # 配置（面板显示「全 1」而实际零文件）。exclude_names 的同
                # 类场景在 _keep_dir 里放行下钻，这里负责最终文件取舍。
                if not _under_live(rel.lower()):
                    continue
            yield os.path.join(r, f), rel

    _last_t = time.time()
    _last_dir = [root]
    _err_t = [None]      # `_err` 首次被读到的时刻（用于 _ERR_SETTLE 判定）
    _last_say = [0.0]
    _n_out = [0]
    # a423→a424（用户实锤：日志停在「已处理 97500」后 2 分钟无输出，
    # 而原告警阈值 120s 只报一次——用户完全不知道卡在哪）：
    # ① 告警 15s 起、每 15s 重复（不再只报一次）
    # ② 附带 worker 当前正在扫描的目录（_cur_d）
    # ③ 附带累计已产出文件数（判断是「没进展」还是「在大目录里出文件」）
    _IDLE_WARN = 15.0
    _IDLE_FAIL = 300.0
    # a570 对抗审计（P1·第十二轮）：`_err` 首次置位后若持续这么久没有任何
    # 新产出，就认定「不会再有数据」→ 立即失败。取 30s：远大于 worker
    # 正常产出间隔（大目录也就几秒），又远小于 idle 的 300s 兜底。
    _ERR_SETTLE = 30.0
    try:
        # 分片期收获的文件批先回放（a415R2 N16：入 try——回放期取消/异常
        # 也要走 finally 置 abandoned，否则 worker 永久泄漏）
        for r, fs in pre_batches:
            for x in _emit(r, fs):
                _n_out[0] += 1
                yield x
        while True:
            # 循环头检查：取消先于一切（a395 单测实锤）
            if should_cancel and should_cancel():
                raise Cancelled()
            try:
                item = out_q.get(timeout=2.0)   # a424：2s 粒度，停滞可感知
            except _q.Empty:
                item = None
            if item is _DONE:
                # a395：DONE 分支必须先查 cancel（producer/worker 边界见取消
                # 发 DONE 与消费侧 get 竞态，否则取消被吞、walk 假完成）
                if should_cancel and should_cancel():
                    raise Cancelled()
                # a570 对抗审计（P1·第十二轮）：DONE 表示扫描**已经结束**
                # ——此时任何 `_err` 都意味着「有子树的数据没拿到」，必须
                # 失败。原实现加 `not _live` 条件是错的：`_live` 衡量「线程
                # 还活着」，而硬卡死的 worker 在 `_live` 里永久占位，于是
                # 「一个子树报错 + 另一个线程硬卡」会静默成功（实测 12/12
                # 复现，缺整棵子树且零提示）。
                if _err[0] is not None:
                    raise RuntimeError("目录扫描不完整（%s）" % _err[0])
                return
            if item is None:
                # a570 对抗审计（P1·第十二轮）：判定「`_err` 是否致命」不能
                # 依赖 `_live`（硬卡死的 worker 在 `_live` 里永久占位，会把
                # 真实错误吞掉）。改为计时：`_err` 首次置位后，若持续
                # `_ERR_SETTLE` 秒没有任何新产出，就认定「其它子树也停摆了，
                # 不会再有数据」→ 立即失败并带上真实原因。
                # 这既避免第十轮「2s 无产出就误杀」的坑（其它 worker 在正常
                # 产出时 `_last_t` 会刷新），也覆盖「错误 + 硬卡」的组合。
                if _err[0] is not None:
                    _err_at = _err_t[0]
                    if _err_at is None:
                        _err_t[0] = _err_at = time.time()
                    if time.time() - max(_err_at, _last_t) >= _ERR_SETTLE:
                        raise RuntimeError("目录扫描不完整（%s）" % _err[0])
                idle = time.time() - _last_t
                if idle >= _IDLE_FAIL:
                    raise RuntimeError(
                        "目录扫描 %.0fs 无进展——网盘停滞/断连（最后目录：%s）。"
                        "检查网络盘连接后重试" % (idle, _last_dir[0]))
                if idle >= _IDLE_WARN and time.time() - _last_say[0] >= _IDLE_WARN:
                    _last_say[0] = time.time()
                    # a684-A4：_cur_d 的读写全部持 _dl——原先这里裸读，靠
                    # try/except 兜「遍历中字典尺寸变化」。
                    with _dl:
                        _workers = [v for v in list(_cur_d.values()) if v]
                    # a452（审计 P2）：原实现逐个 worker 报当前目录，每次停滞
                    # 最多刷 9 行；那些目录名对用户没有价值（他只需要知道
                    # 「卡住了、还在跑」），却会把 400 条日志上限冲刷掉，让
                    # 阶段结论（递归 include 截断告警、收录方式选择等）被裁没。
                    # 改为单行汇总，不报具体路径（路径每次不同→进度键分裂→刷屏）。
                    say("  扫描等待中 · 已产出 %d 文件 · %d 个 worker 在跑"
                        "（若长时间不变，多为网盘大目录穿越或连接停滞）"
                        % (_n_out[0], len(_workers)))
                continue
            r, fs = item
            _last_t = time.time()   # 拿到新目录=有进展
            _last_dir[0] = r
            for x in _emit(r, fs):
                _n_out[0] += 1
                yield x
    finally:
        _abandoned[0] = True   # a398：消费侧退出（含异常）→ worker 放弃投递
        # a570：看门狗必须一并收（否则同进程多次建库会累积僵尸线程）
        _wd_stop.set()
        if _wd[0] is not None:
            _wd[0].join(2.0)


class Cancelled(Exception):
    """建库被取消 / 需要用户重新配置。

    a570：加 `reason`——`"reconfigure"` 表示不是真取消，而是用户选了
    「重新配置收录范围」。API 层据 reason 决定是否显示「已取消」文案。
    """

    def __init__(self, reason=""):
        super().__init__(reason)
        self.reason = reason


class _Beat(object):
    """a423（用户令：所有等待过程必须给日志，绝不让用户觉得卡死）：纯
    Python 循环的心跳节拍器。每 `interval` 秒报一次进度。
    用法：
        b = _Beat(say, 2.0)
        for i, x in enumerate(lst):
            b.tick(i + 1, len(lst), "  白名单映射 %d/%d")
    say=None 时全空转（零开销）。"""

    __slots__ = ("_say", "_iv", "_t", "_n")

    def __init__(self, say, interval=2.0):
        self._say = say
        self._iv = interval
        self._t = time.time()
        self._n = 0

    def tick(self, done=None, total=None, label=None, *largs):
        """a452（审计 P2）：节流必须在**取参之前**生效。原来 label 是已格式化
        好的字符串，调用点每项都构造一次（20 万个 .o 就是 20 万次无用
        %/len），节流形同虚设。现在支持传模板 + 参数：只有真正要报时才
        格式化。用法：`b.tick(i, n, "  白名单映射 %d/%d", i, n)`。
        """
        self._n += 1
        now = time.time()
        if now - self._t < self._iv:
            return
        self._t = now
        if not self._say:
            return
        if label is not None:
            self._say(label % largs if largs else label)
        elif total:
            self._say("  进行中：%d/%d（%.0f%%）" % (done, total,
                                                 100.0 * done / total))
        else:
            self._say("  进行中：%d" % done)


def _parse_cmd_file(p, src_roots=()):
    """Kbuild .cmd：`cmd_xxx.o := <cc> ... -c ... src.c`——命令行自带源文件
    路径（多 .c 合一 .o 的成员文件各有自己的 .cmd，天然正确）。返回源文件
    绝对路径或 None。
    a398 P0-2（内网报告 §2.2）：基准顺序——
    ① .cmd 所在目录（旧行为）
    ③ 候选源码根 src_roots（显式配置最优先；sbuilder/output 外挂形态，
      报告 §3.3）
    ② 后缀推断（a398 BUG-A：树内编译形态 source_roots 配
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
                    # a415R2 N6/NEW-4：③ 提到 ② 前——产物树里带源码副本时
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
    """读 ELF 符号表：defined FUNC/OBJECT。返回 [符号名]。

    a427（实锤：打包版 11020/11020 全失败——`ModuleNotFoundError:
    No module named 'elftools.elf.elffile'`。PyInstaller 只收了 elftools
    顶层包、子模块没收，`import elftools` 通过但真用时崩）：**弃用
    pyelftools，改纯 struct 直接解析**。.o 是小文件，只需 section header
    + .symtab + .strtab，自研更快、零依赖、不受打包影响。

    支持 ELF32/ELF64、大小端（Kbuild 产物按目标架构字节序）。"""
    try:
        with open(o_path, "rb") as f:
            data = f.read()
    except OSError:
        return []
    return _elf_defined_syms(data)


_ELF_MAGIC = b"\x7fELF"
# (st_info & 0xF) 取值：1=OBJECT 2=FUNC
# a434：不能只收 FUNC/OBJECT——交叉编译的 .S 产物，汇编器默认把全局符号
# 标成 STT_NOTYPE(0)，只收 1/2 会让 asm 里的 _start/entry_*/stext 全部丢失
# （本项目 NAV_LANGS 显式含 Asm）。10=STT_GNU_IFUNC（glibc 的 memcpy 等）。
# NOTYPE 里的内部符号（$a/$d/$t/$x、.L 标签、binutils 映射符）由后面的
# 名字前缀过滤 + 特殊节索引（0xFF00~0xFF1F，含 SHN_LORESERVE 等）排除兜住；
# SHN_ABS(0xFFF1)/SHN_COMMON(0xFFF2) 是真实定义，保留。
_ELF_WANT_TYPE = (0, 1, 2, 10)   # NOTYPE(asm) / OBJECT / FUNC / GNU_IFUNC


def _elf_defined_syms(data, max_syms=400000):
    """纯 struct 解 ELF 符号表，返回已定义的 FUNC/OBJECT 名列表。
    解析失败（非 ELF/截断/畸形）一律返回 []，绝不抛异常。"""
    import struct
    if len(data) < 52 or data[:4] != _ELF_MAGIC:
        return []
    ei_class = data[4]        # 1=32bit 2=64bit
    ei_data = data[5]         # 1=LE 2=BE
    e = "<" if ei_data == 1 else ">"
    try:
        if ei_class == 1:
            if len(data) < 52:
                return []
            e_shoff, = struct.unpack_from(e + "I", data, 0x20)
            e_shentsize, e_shnum, e_shstrndx = struct.unpack_from(
                e + "HHH", data, 0x2E)
            sh_fmt = e + "IIIIIIIIII"
        elif ei_class == 2:
            if len(data) < 64:
                return []
            e_shoff, = struct.unpack_from(e + "Q", data, 0x28)
            e_shentsize, e_shnum, e_shstrndx = struct.unpack_from(
                e + "HHH", data, 0x3A)
            sh_fmt = e + "IIQQQQIIQQ"
        else:
            return []
        # a434：ei_data 必须显式是 1(LE)/2(BE)——原实现把 0(DATANONE)/3
        # 都当大端「猜字节序」
        if ei_data not in (1, 2):
            return []
        if not e_shoff:
            return []
        sh_size = struct.calcsize(sh_fmt)
        if e_shentsize < sh_size:
            return []
        # a434：ELF 扩展节数格式——e_shnum==0 时真值在 section 0 的 sh_size
        if e_shnum == 0:
            if e_shoff + sh_size > len(data):
                return []
            e_shnum = struct.unpack_from(sh_fmt, data, e_shoff)[5]
            if not e_shnum:
                return []
        if e_shnum > 65535:
            return []
        # 越界直接判废（畸形/截断），绝不让后续 unpack 抛 struct.error
        if e_shoff + e_shnum * e_shentsize > len(data):
            return []

        def _sh(i):
            off = e_shoff + i * e_shentsize
            if off + sh_size > len(data):
                raise ValueError("shdr truncated")
            v = struct.unpack_from(sh_fmt, data, off)
            # (name, type, flags, addr, offset, size, link, info, align, entsize)
            return v

        if ei_class == 1:
            sfmt = e + "IIIBBH"      # st_name, st_value, st_size,
                                     # st_info, st_other, st_shndx
        else:
            sfmt = e + "IBBHQQ"      # st_name, st_info, st_other,
                                     # st_shndx, st_value, st_size
        ssize = struct.calcsize(sfmt)

        # a434：定位 .symtab 时**逐个校验**（原实现取第一个 SHT_SYMTAB 就
        # break，若它 size/entsize/link 有问题，后面存在合法 symtab 也会被
        # 误判整文件无符号）。校验项：非空、entsize 足够、sh_link 指向真正的
        # SHT_STRTAB(3) 且范围合法——否则会把 PROGBITS 节当字符串表用，
        # 输出垃圾符号名（比返回空更糟）。
        sym_hdr = None
        strtab = b""
        for i in range(e_shnum):
            try:
                v = _sh(i)
            except ValueError:
                break
            if v[1] != 2:                     # 只要 SHT_SYMTAB
                continue
            if not v[5] or v[9] < ssize:      # size 为空 / entsize 不足
                continue
            _li = v[6]
            if not (0 < _li < e_shnum):
                continue
            try:
                _sh2 = _sh(_li)
            except ValueError:
                continue
            if _sh2[1] != 3:                  # 必须是 SHT_STRTAB
                continue
            _so, _ss = _sh2[4], _sh2[5]
            if not _ss or _so + _ss > len(data):
                continue
            sym_hdr = v
            strtab = data[_so:_so + _ss]
            break
        if sym_hdr is None:
            return []
        sym_off, sym_size, sym_entsize = sym_hdr[4], sym_hdr[5], sym_hdr[9]
        if sym_entsize < ssize:
            return []
        n = min(sym_size // sym_entsize, max_syms)
        out = []
        base = sym_off
        if base + n * sym_entsize > len(data):
            n = max(0, (len(data) - base) // sym_entsize)
        for k in range(n):
            try:
                v = struct.unpack_from(sfmt, data, base + k * sym_entsize)
            except struct.error:
                break
            if ei_class == 1:
                st_name, st_info, st_shndx = v[0], v[3], v[5]
            else:
                st_name, st_info, st_shndx = v[0], v[1], v[3]
            t = st_info & 0xF
            if t not in _ELF_WANT_TYPE:      # FUNC / OBJECT / NOTYPE / IFUNC
                continue
            # a452（审计 P2）：NOTYPE 里还有 STB_LOCAL(binding=0) 的汇编局部
            # 标号（entry_foo / bss_start 之类，不以 $/./.L 开头，名字过滤
            # 兜不住）。它们不是可跳转的全局定义，收进 symbols 会把错误文件
            # 拉进同名符号候选、打乱消歧排序。只对 NOTYPE 用 binding 收紧
            # （FUNC/OBJECT 的 LOCAL 是 static 函数/变量，是合法跳转目标，
            # 必须保留）。
            if t == 0 and (st_info >> 4) == 0:
                continue
            if st_shndx == 0:                # SHN_UNDEF：引用不是定义
                continue
            # a434 修正：SHN_ABS 是 0xFFF1、SHN_COMMON 是 0xFFF2，
            # `>= 0xFF00` 会把两者一并丢掉（glibc 的 stdin/stdout 是 ABS 对象，
            # 收进来才对）。这里精确排除非「真实节」的特殊索引（0xFF00~0xFF1F），
            # 并保留 ABS/COMMON。
            if t == 0 and 0xFF00 <= st_shndx <= 0xFF1F:
                continue
            if st_name == 0 or st_name >= len(strtab):
                continue
            end = strtab.find(b"\x00", st_name)
            if end < 0:
                continue
            try:
                nm = strtab[st_name:end].decode("utf-8", "replace")
            except Exception:
                continue
            if not nm or nm[0] in "$." or nm.startswith("_GLOBAL_"):
                continue
            out.append(nm)
        return out
    except (struct.error, ValueError, IndexError):
        return []


# ------------------------------------------------------------------ 收录范围
# a570（三档重构定稿）：数据模型 v2。
#
# v1 是「平铺 include + 一堆兜底路径表」，表达不了「这个子树白名单、那个子树
# 全量」。v2 改成**显式覆盖树**：
#
#   {"version": 2, "mode": "whitelist|manual|full",
#    "dirs": {"kernel": "whitelist", "kernel/tools": "full"},
#    "artifact_roots": ["sbuilder/output/build"],
#    "exclude_names": []}
#
# `dirs` 只存用户显式设过的节点，继承靠 `_resolve_dir_state()` 求值（向上找最近
# 的显式祖先，到根仍无则取 mode 语义）。这样 JSON 小、可 review、父改一处全树跟随。
#
# **落盘只有一处**：工程根 `.fcpk-scope.json`（用户定调方案 A）。v1 的
# `scope_store_path`（DATA_DIR 备份）已删除——它会让「首次建库」判据变成两处。

SCOPE_MODE_ROOT_DEFAULT = "whitelist"   # manual 模式下根节点的默认状态


def _norm_dirs(dirs, dropped=None):
    """校验并归一 `dirs`。返回 dict 或 None（非法）。

    a570 对抗审计（P1·第二十轮）：含 tmp 段的键**忽略**而不是判整份非法
    ——walk 对 tmp 无条件硬剪（用户定调），这类节点本来就是死配置；但把
    整份配置判成 `bad:` 会让 build 当无配置走 detect 全量重生成并覆盖写盘
    （实测把用户明确 off 的 src 整棵收进来，且零备份）。忽略并在调用方
    告警，比毁掉配置好。`dropped` 收集被忽略的键名。

    与 v1 的 `_lst` 同风格严校验：拒绝绝对路径 / 盘符 / UNC / `..` 逃逸；
    根（"." / ""）不许有显式状态（根的默认值由 mode 决定）。
    """
    if dirs is None:
        return {}
    if not isinstance(dirs, dict):
        return None
    out = {}
    for k, v in dirs.items():
        if not isinstance(k, str) or not isinstance(v, str):
            return None
        # a570 对抗审计（P1·第十八轮）：`.`/空键表示「工程根自身」，归一成
        # ""。没有它，降级后的 mode=manual 配置无法表达「根直下源码也收」
        # ——根默认恒为 whitelist，根文件在下一次建库时静默丢失。
        # 必须是**原样**的 "" 或 "."：`"  "` 之类的空白键仍按非法处理
        # （strip 后才变空，用户本意不是根）。
        if k == "" or k == ".":
            st0 = v.strip().lower()
            if st0 not in ("whitelist", "full", "off"):
                return None
            out[""] = st0
            continue
        raw = k.strip().replace("\\", "/")
        if raw.startswith("/"):
            return None                      # 绝对路径（POSIX）/ UNC——必须先于
                                             # strip("/")，否则被判成相对路径
        p = raw.strip("/")
        if p == "" or p == ".":
            return None                      # 空白/多余分隔符造出的根形态
        segs = [s for s in p.split("/") if s not in ("", ".")]
        if not segs:
            return None
        # a570 对抗审计：盘符/冒号校验必须逐段（原只看 segs[0]，`a/C:/b`
        # 能穿过去；且 `startswith("\\\\")` 在 replace 之后是死条件）。
        # Windows 目录名不可能含冒号，逐段一律直接拒。
        if any(":" in s for s in segs):
            return None
        if any(s == ".." for s in segs):
            return None                      # 逃逸
        st = v.strip().lower()
        if st not in ("whitelist", "full", "off"):
            return None
        # a570 对抗审计（P2·第十九轮）：tmp 类目录在 walk 里是**无条件硬剪**
        # 的，显式配它必然是死配置。a570（P1·第二十轮）：改为**忽略该键**
        # 并在 dropped 里报告——判整份非法会让旧配置变 `bad:`，build 随即
        # 当无配置整棵全量重生成且覆盖写盘（实测丢掉用户显式 off 的目录）。
        if any(s.lower() in _TMP_NAMES for s in segs):
            if dropped is not None:
                dropped.append("/".join(segs))
            continue
        # a570 对抗审计：键统一 lower——Windows 目录大小写不敏感，配置里
        # 写 `Kernel` 而磁盘是 `kernel/` 时继承链会断裂（off 失效/全收）。
        out["/".join(segs).lower()] = st
    return out


def _norm_scope_v2(cfg, root):
    """v2 配置校验。返回 (ok, scope|err)。"""
    if not isinstance(cfg, dict):
        return False, "配置必须是 JSON 对象"
    dirs = _norm_dirs(cfg.get("dirs"))
    if dirs is None:
        return False, ("dirs 必须是 {相对路径: whitelist|full|off}，"
                       "且不得含绝对路径/../tmp 类目录")
    mode = str(cfg.get("mode") or "manual").strip().lower()
    if mode not in ("whitelist", "manual", "full"):
        return False, "mode 只认 whitelist/manual/full"
    arch = str(cfg.get("arch") or "auto").strip().lower()
    if arch not in ("auto", "arm", "arm64"):
        return False, "arch 只认 auto/arm/arm64"

    def _lst(v, key):
        """路径列表归一。a570 对抗审计：
        · `exclude_names` 的消费点是 `_skip`（按**单段目录名**比较），
          带 `/` 的值永远匹配不上 → 直接拒绝，而不是写一条静默无效的规则。
        · 冒号逐段校验（原只看首段）。
        """
        if v is None:
            return []
        if not isinstance(v, list):
            return None
        out = []
        for x in v:
            if not (isinstance(x, str) and x.strip()):
                continue
            p = x.strip().replace("\\", "/")
            if p.startswith("/"):
                return None
            segs = [s for s in p.split("/") if s not in ("", ".")]
            if not segs:
                continue
            if any(":" in s for s in segs):
                return None
            if any(s == ".." for s in segs):
                return None
            if key == "exclude_names" and len(segs) > 1:
                return None          # 名字不是路径
            out.append("/".join(segs).lower())
        return out

    fields = {}
    for k in ("artifact_roots", "exclude_names"):
        v = _lst(cfg.get(k), k)
        if v is None:
            return False, "%s 含非法路径（绝对路径/../）或类型错误" % k
        fields[k] = v
    _known = {"version", "name", "mode", "arch", "dirs"} | set(fields)
    _unknown = [k for k in cfg if k not in _known]
    if _unknown:
        return False, "未知字段：%s" % "、".join(_unknown[:5])
    # a570 对抗审计（P2·第三轮）：`mode=whitelist/full` 的语义是「全树统一」，
    # 此时 `dirs` 生效会让用户以为选了全量却有个别目录被剪（实测
    # mode=full + dirs={kernel:off} → kernel 被剪）。拒绝该组合，比静默
    # 让两处语义分裂（`_scope_root_default` 与 `_make_state_of`）更清楚。
    # a570 对抗审计（P1·第十八轮）：单独的根键（""）例外——它只表达「根
    # 自身」的状态，与 mode 同义，不与「全树统一」冲突。
    if mode in ("whitelist", "full") and [k for k in dirs if k]:
        return False, ("mode=%s 时全树统一，不能同时给 dirs 覆盖"
                       "（要按目录配置请用 mode=manual）" % mode)
    if mode in ("whitelist", "full") and dirs.get("") not in (None, mode):
        return False, ("mode=%s 与根状态 dirs['.']=%s 矛盾" % (mode, dirs[""]))
    return True, {
        "version": 2,
        "name": str(cfg.get("name") or "")[:60] or "未命名范围",
        "mode": mode, "arch": arch,
        "dirs": dirs,
        **fields,
    }


def _resolve_dir_state(rel, dirs, default=SCOPE_MODE_ROOT_DEFAULT):
    """求某目录的生效状态（whitelist|full|off）。O(目录深度)。

    rel 为空串/None = 根。向上逐级找最近的显式祖先；到根仍无 → default。
    a570：`dirs[""]`（由 `_norm_dirs` 从 "." 归一）表达**根自身**的显式状态，
    它优先于 default——否则根直下文件在降级后的下次建库会静默丢失。

    a570 对抗审计：`dirs` 的键由 `_norm_dirs` 统一 lower（Windows 大小写
    不敏感），所以这里也必须 lower 后再查——`_walk_files` 传进来的是
    磁盘真实大小写（可能是 `Kernel`）。
    """
    cur = (rel or "").strip("/").lower()
    while True:
        v = dirs.get(cur)
        if v in ("whitelist", "full", "off"):
            return v
        if not cur:
            return default
        cur = cur.rpartition("/")[0]


def _scope_root_default(sc):
    """scope 的根默认状态。mode=whitelist/full 时全树统一，manual 用常量。"""
    m = (sc or {}).get("mode")
    if m in ("whitelist", "full"):
        return m
    return SCOPE_MODE_ROOT_DEFAULT


def _make_state_of(sc):
    """构造 `state_of(rel)` 回调供 `_walk_files` 用。scope 为 None 时返回 None。"""
    if not sc:
        return None
    dirs = sc.get("dirs") or {}
    if not dirs and sc.get("mode") in ("whitelist", "full"):
        # 全树统一态：省掉逐级查表
        fixed = sc["mode"]
        _fixed_of = lambda _rel: fixed    # noqa: E731
        # 2026-11-23 总审计 a684-A10：两个能力查询在统一态下恒 False——全树
        # 统一没有「显式节点」概念，用户排除名命中的子树整棵剪。原实现不挂
        # 这两个属性，靠消费侧 getattr 取不到时的默认值巧合成立；这里把
        # 契约摆到明面上，行为不变。
        _fixed_of.has_live_desc = lambda _rel_l: False
        _fixed_of.under_live = lambda _rel_l: False
        return _fixed_of
    dflt = _scope_root_default(sc)

    def _state_of(rel_l):
        return _resolve_dir_state(rel_l, dirs, dflt)
    # a570 对抗审计：把「子树里还有显式非 off 节点」的能力一并挂出去，
    # 供 _walk_files 判断是否能在 off 父目录下继续下钻。
    _state_of.has_live_desc = lambda rel_l: _has_live_desc(
        (rel_l or "").lower(), dirs)
    # a570 对抗审计（P1·第十六轮）：用户 exclude_names 命中的目录只剪「没有
    # 显式 white/full 后代的」那部分。_emit 需要知道某文件是否落在显式
    # live 子树里，才能既不整树放行（drop.c 要剪）、也不整树剪掉（keep.c 要收）。
    # a570 对抗审计（P2·第十七轮）：原实现每个文件线性扫全部 live 键（实测
    # 2 万文件 + 2020 节点 0.33s→2.13s）。改成集合查前缀——O(路径深度)。
    # a570 对抗审计（P1·第十九轮）：**根键不参与**——`_under_live` 逐级上溯
    # 必然会走到 ""，把它算进来会让任意路径都判「在显式 live 子树内」，
    # 于是 exclude_names 与 artifact 隔离双双失效（实测）。根的 full 已经在
    # 别处按「全收」处理，不需要这层证据。
    _live_set = {k for k, v in dirs.items()
                 if k and v in ("whitelist", "full")}

    def _under_live(rel_l):
        cur = rel_l
        while True:
            if cur in _live_set:
                return True
            if not cur:
                return False
            cur = cur.rpartition("/")[0]
    _state_of.under_live = _under_live
    return _state_of


def _has_live_desc(rel_l, dirs):
    """`rel_l` **自身或**其子树里是否存在显式非 off 节点。

    a570 对抗审计：`off` 父目录下用户显式设成 whitelist/full 的子目录，
    若 scandir 层就整棵剪掉，那条配置永远是死配置（面板却显示「白 1」，
    用户以为已收录，静默丢文件）。有 live 后代就必须继续下钻。

    a570 对抗审计（P0·第十七轮）：必须**含自身**——用户排除名恰好等于某个
    显式勾选的目录名（`exclude_names=["include"]` + `dirs={"src/include":
    "full"}`）时，原实现只查 `k.startswith(pfx)`，该目录在 scandir 层就被
    剪掉，唯一的收录区被清空 → 建库硬失败。
    """
    cur = (rel_l or "").lower()
    pfx = (cur + "/") if cur else ""
    for k, v in dirs.items():
        if v == "off":
            continue
        if cur and (k == cur or k.startswith(pfx)):
            return True
        if not cur and k:
            return True
    return False


def _norm_scope(cfg, root):
    """校验+归一 scope 配置。返回 (ok, scope|err_msg)。

    a570：v2 优先。缺 `version: 2` 的一律按 v1 处理 → **(False, "v1-deprecated")**，
    由 `load_scope` 当「无配置」走推荐器（用户定调：不兼容旧格式）。
    """
    if not isinstance(cfg, dict):
        return False, "配置必须是 JSON 对象"
    if cfg.get("version") != 2:
        return False, "v1-deprecated"
    return _norm_scope_v2(cfg, root)


def load_scope(root, store=None):
    """加载收录范围配置。只读**工程根** `.fcpk-scope.json`（方案 A）。

    返回 (scope|None, source)：
      source ∈ "project" | "v1-deprecated" | "" | "bad:<err>"

    a570 相对 a398 的变化：
      · 删除 `scope_store_path`（DATA_DIR 备份）——两处配置会让「首次建库」
        判据变成「两个位置都不存在」，实现和排查都绕。
      · v1 配置（缺 version:2）**不兼容**，返回 `v1-deprecated` 让上层当
        无配置走推荐器（用户定调：旧格式已废弃，建库成功后直接覆盖写 v2）。
    """
    import json as _json
    p = os.path.join(root, SCOPE_FILE)
    if not os.path.isfile(p):
        return None, ""
    try:
        with open(p, encoding="utf-8-sig") as f:   # a398#20：兼容 BOM
            cfg = _json.load(f)
    except Exception as e:
        return None, "bad:%s" % str(e)[:80]
    if not isinstance(cfg, dict):
        return None, "bad:配置不是 JSON 对象"
    if cfg.get("version") != 2:
        return None, "v1-deprecated"
    ok, sc = _norm_scope_v2(cfg, root)
    if ok:
        return sc, "project"
    return None, "bad:%s" % sc


def save_scope(root, sc):
    """把生效的 v2 配置写到工程根 `.fcpk-scope.json`。

    只在**建库成功后**调用（内网定稿 §16.1：索引落盘之后）。旧 v1 配置
    覆盖前先备份为 `.v1.bak`（内网定稿 §16.3）。

    写失败**不抛**——工程根只读（只读挂载/权限不足）时不能因此让建库算失败。
    **但 v1 备份失败时必须中止覆盖**（对抗审计）：否则用户唯一一份旧配置
    被不可逆覆盖而无 .bak。
    返回 (ok, err)。
    """
    import json as _json
    p = os.path.join(root, SCOPE_FILE)
    # v1 备份（只备份一次，已有 .bak 不覆盖）。备份失败 → 放弃覆盖。
    try:
        if os.path.isfile(p):
            _old = None
            try:
                with open(p, encoding="utf-8-sig") as f:
                    _old = _json.load(f)
            except Exception:
                _old = None      # JSON 损坏：仍要备份（内容原样保下来）
            if not isinstance(_old, dict) or _old.get("version") != 2:
                bak = p + ".v1.bak"
                if not os.path.isfile(bak):
                    import shutil as _sh
                    _sh.copy2(p, bak)
    except OSError as e:
        return False, "v1 配置备份失败，已放弃覆盖（%s）" % str(e)[:80]
    try:
        _write_json(p, sc)
        return True, ""
    except Exception as e:      # a570 对抗审计：_write_json 可能抛
                                # UnicodeEncodeError/TypeError，原 except
                                # OSError 漏网会让建库被误报失败
        return False, str(e)[:120]


def v1_bakeup_path(root):
    """v1 备份文件路径（供 API 层提示用户）。"""
    return os.path.join(root, SCOPE_FILE) + ".v1.bak"

def _detect_arch(root, say=None):
    """a398 P1-7（报告 §六·补）：arm/arm64 自动识别，返回 'arm'/'arm64'/None。
    判据优先级：①.config/autoconf 的 CONFIG_ARM64=y / CONFIG_ARM=y
    ②arch/<a> 下谁的 .o/.cmd 产物多 ③None=无法判定（配置占位符两个都收，
    慢但不会错）。kernel 根候选：kernel/kernel_sdk > kernel > root。
    a398（审计#26）：逐候选试到底（原第一个判不出就放弃）"""
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




# a430（内网报告 whitelist_tier_final）：递归 include 头文件推导——
# 取代 header_roots 全量目录近似（实测 51% 头文件永不被引用；hal_inc
# 收录为 0）。从 .cmd 提取 -I 真实编译参数，从白名单单元 BFS 展开
# #include 依赖链，只收真实触达的头文件
_INC_RE = re.compile(r'^\s*#\s*include\s+[<"]([^>"]+\.h)[>"]', re.M)


def _extract_inc_dirs(cmd_abs_list, base_dirs, should_cancel=None, say=None,
                      quiet_rounds=None):
    """从已收集的 .cmd 列表提取 -I 目录（真实编译参数）。返回 (dirs, 扫描数)。

    a422：原实现**再走一遍整树**找 .cmd，source_roots 含 "." 时 →
    对 12 万文件 SMB 全树 walk，卡死且取消无效。现改为直接用阶段 1
    已经扫到的 .cmd 列表（零额外 I/O），并加取消点。

    a423（用户质疑「超过 4000 怎么办」——硬上限会丢 -I）：改为**收敛
    早停**而非截断。
    a434（对抗审查：早停 + 排序 = 系统性地漏 -I）：cmd_abs_list 是并发
    扫描产出的无序列表，早停在其中一段上收敛，等价于「按扫描顺序随机
    抽样」，同一工程两次建库可能收敛到不同 -I 集（G10 实测收录清单
    10173→9871，少 300 个头文件）。读 .cmd 是纯本地小文件顺序读，一万个
    也就几秒，远小于阶段 1 的目录遍历本身——**默认扫完全部**
    （quiet_rounds=None 关闭早停）。保留参数仅为兼容旧的调用方。

    base_dirs：.cmd 里 -I 为相对路径时的解析基准（产物根/源码根）。"""
    # a452：用有序去重列表保存 -I——gcc 语义是「按 -I 出现顺序取第一个」，
    # set 会丢掉这个顺序，而字典序不是 -I 顺序。_dir_seen 负责去重。
    dirs = []
    _dir_seen = set()
    def _add_dir(p):
        if p not in _dir_seen:
            _dir_seen.add(p)
            dirs.append(p)
    n = 0          # 已打开的 .cmd 数（含解析失败——空洞不能白吃收敛额度）
    _parsed = 0    # 真正解析出命令行的 .cmd 数
    _quiet = 0     # a426：按**解析成功的 .cmd** 计无新增，不按打开数
    _bases = [os.path.normpath(b) for b in base_dirs if os.path.isdir(b)]
    _probe = 0
    # a452（审计 P2）：-I 解析结果缓存。1 万个 .cmd × 平均 30 个相对 -I ×
    # 最多 5 个 base 逐个 isdir，SMB 上每次都是一次 RTT（分钟级纯等待）；
    # 而 .cmd 里反复出现的是同一批 include 目录，缓存命中率极高。
    _isdir_c = {}
    # a453（第二轮审计 P2）：缓存加容量上限。1 万 .cmd × 30 个相对 -I ×
    # 最多 5 个 base = 可达百万条长路径常驻（数百 MB），本地盘上没有 I/O
    # 收益时纯增内存。超过阈值后停止写入——已缓存的仍然有效。
    _ISDIR_C_MAX = 200000
    def _isdir(p):
        v = _isdir_c.get(p)
        if v is None:
            v = os.path.isdir(p)
            if len(_isdir_c) < _ISDIR_C_MAX:
                _isdir_c[p] = v
        return v
    # a434：cmd_abs_list 来自并发目录扫描（顺序不稳定），而下面有收敛早停
    # ——顺序不同会在不同的 .cmd 处收敛，提到不同的 -I 集，导致同一工程
    # 两次建库的收录清单漂移。排序使收敛点与结果都确定可复现。
    _cmd_seq = sorted(cmd_abs_list)
    for ap in _cmd_seq:
        if quiet_rounds is not None and _quiet >= quiet_rounds:
            if say:
                say("  编译参数提取：连续 %d 个已解析 .cmd 无新 -I，已收敛"
                    "（扫 %d/%d 个，其中可解析 %d）"
                    % (_quiet, n, len(_cmd_seq), _parsed))
            break
        _probe += 1
        if _probe >= 200:
            _probe = 0
            if should_cancel and should_cancel():
                raise Cancelled()
            if say:
                say("  编译参数提取：已扫 %d/%d 个 .cmd（可解析 %d），%d 个 -I"
                    % (n, len(_cmd_seq), _parsed, len(dirs)))
        _before = len(dirs)
        _got = False
        # a452（审计 P2）：日志口径按注释兑现——n 是「已打开数（含解析失败）」，
        # 原来 n+=1 写在识别到 cmd_ 行之后，空/异常 .cmd 根本走不到，n 恒等于
        # _parsed，日志「已扫 7000/10000（可解析 7000）」掩盖了 3000 个失败。
        n += 1
        try:
            with open(ap, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if not line.startswith("cmd_") or ":=" not in line:
                        continue
                    _got = True
                    toks = line.split(":=", 1)[1].split()
                    for i, t in enumerate(toks):
                        d2 = None
                        if t == "-I" and i + 1 < len(toks):
                            d2 = toks[i + 1]
                        elif t.startswith("-I") and len(t) > 2:
                            d2 = t[2:]
                        if not d2:
                            continue
                        d2 = d2.strip("'\"")
                        if os.path.isabs(d2):
                            # a452：绝对 -I 也走缓存（交叉工具链目录被上万个
                            # .cmd 重复引用，SMB 上每次 isdir 都是一次往返）
                            _hit = _isdir(d2)
                            if _hit:
                                _add_dir(os.path.normpath(d2))
                            continue
                        for bd in _bases:
                            norm = os.path.normpath(os.path.join(bd, d2))
                            if _isdir(norm):
                                _add_dir(norm)
                                break
                    break
        except OSError:
            pass
        if not _got:
            continue          # a426：空/异常 .cmd 不消耗收敛额度
        _parsed += 1
        if len(dirs) > _before:
            _quiet = 0
        else:
            _quiet += 1
    return dirs, n


def _resolve_includes(units_abs, inc_dirs, max_depth=32,
                      should_cancel=None, say=None):
    """白名单单元 BFS 递归解析 #include，返回触达的 .h 绝对路径集合。
    解析顺序：当前目录 > -I 目录。深度上限防 include 环。

    a422（实测卡死）：原实现对每个未命中的 include 名 × 几十个
    -I 目录逐个 os.path.isfile——SMB 上每次 stat 都是网络往返，几十万
    次必卡。现改为**一次建 -I 目录的倒排索引**（文件名 → 所在 -I 目录），
    后续解析纯内存字典查，零网络 I/O：
      ① _ls(inc_dir) 只列一次目录项（懒加载、按需、带取消）
      ② 同名头文件在多个 -I 目录时按 -I 顺序取第一个（gcc 语义）
      ③ 当前目录相对 include 仍走 _isfile（通常紧邻，量小）"""
    # a452（审计 P2）：注释写「按 -I 顺序取第一个（gcc 语义）」，实现却是
    # sorted(字典序)——两者在 `-Iarch/arm/include` 与 `-Iinclude` 都有
    # `asm/foo.h` 时给出相反结果。gcc 的 -I 顺序才是语义正源：让调用方把
    # 有序序列传进来（_extract_inc_dirs 已按 .cmd 顺序累积），这里只做
    # 「保序去重」——顺序要确定，但不能用字典序冒充 -I 顺序。
    try:
        _inc_list = list(dict.fromkeys(inc_dirs))
    except Exception:
        _inc_list = sorted(inc_dirs)
    _ls_cache = {}      # inc_dir -> {小写文件名: 真实文件名}；None=列不动
    _exists = {}
    _probe = 0

    def _check_cancel():
        nonlocal _probe
        _probe += 1
        if _probe >= 500:
            _probe = 0
            if should_cancel and should_cancel():
                raise Cancelled()

    # a452（审计 P2）：_isfile 是热点路径——子路径 include 每个都按 -I 顺序
    # 逐个 stat，SMB 上每次都是往返；单个文件 300 个 include × 50 个目录 =
    # 15000 次，而唯一的取消检查在外层「每 500 个文件」。这里也接检查点。
    def _isfile(p):
        _check_cancel()
        v = _exists.get(p)
        if v is None:
            try:
                v = os.path.isfile(p)
            except OSError:
                v = False
            if len(_exists) > 200000:   # a423：防无界增长（大库数万头文件）
                _exists.clear()
            _exists[p] = v
        return v

    def _list_dir(d):
        v = _ls_cache.get(d, 0)
        if v != 0:
            return v
        try:
            names = os.listdir(d)
        except OSError:
            names = None
        if names is not None:
            _ls_cache[d] = {nm.lower(): nm for nm in names}
        else:
            _ls_cache[d] = None
        _check_cancel()
        return _ls_cache[d]

    def _lookup(nm):
        """按 -I 顺序找头文件，返回绝对路径或 None。

        a423：带子路径的 include（`<linux/foo.h>`，内核工程占绝大多数）
        不能走顶层 listdir 索引——末级名在 -I 的子目录里，顶层永远没有。
        这类直接按 -I 顺序拼路径 stat（路径确定，通常第一个 -I 就命中，
        且 _exists 缓存去重）。裸文件名才走 listdir 倒排（`<foo.h>`
        可能藏在任意 -I 目录的任意深度，无路径可拼）。"""
        nl = nm.replace("\\", "/")
        if "/" in nl:
            for sd in _inc_list:
                cand = os.path.normpath(os.path.join(sd, nm))
                if _isfile(cand):
                    return cand
            return None
        leaf = nl.lower()
        for sd in _inc_list:
            idx = _list_dir(sd)
            if not idx or leaf not in idx:
                continue
            cand = os.path.normpath(os.path.join(sd, nm))
            if _isfile(cand):
                return cand
        return None

    # a562（MCU/CubeMX/Keil 工程实锤：索引建立但「完全不能跳转」）：
    # 这类工程没有 .cmd/.o → -I 提取为空 → 除「同目录」外一律找不到
    # 头文件。实测 MCU_IPC 有 173 个头文件，只收进 19 个（11%），
    # App/Drivers/inc、App/Middle/inc、Firmware/Peripherals/inc 全灭。
    # 头文件不进 tags 就等于宏/原型/typedef/结构体全部不可跳转。
    #
    # 修法：按 GCC 在这些工程里的实际行为补「邻近目录」解析——单元
    # 的 inc//include/ 同名兄弟目录。用 listdir 缓存做大小写无关
    # 匹配（Windows 上 `Inc`/`inc` 混用很常见）。放在全局 -I 之前，
    # 天然带「就近优先」语义，同名头文件不会跨模块串车。
    _HDIR_NAMES = ("inc", "include", "includes", "header", "headers")
    _prox_cache = {}        # curdir -> [(inc_dir, {小写名: 真实名}), ...]

    def _prox_dirs(curdir):
        v = _prox_cache.get(curdir)
        if v is not None:
            return v
        out = []
        seen = set()
        for base in (curdir, os.path.dirname(curdir)):
            idx = _list_dir(base)
            if not idx:
                continue
            for nm in _HDIR_NAMES:
                real = idx.get(nm)
                if not real:
                    continue
                d = os.path.normpath(os.path.join(base, real))
                if d in seen or not os.path.isdir(d):
                    continue
                seen.add(d)
                sub = _list_dir(d)
                if sub:
                    out.append((d, sub))
        if len(_prox_cache) > 20000:
            _prox_cache.clear()
        _prox_cache[curdir] = out
        return out

    def _lookup_prox(nm, curdir):
        nl = nm.replace("\\", "/")
        if "/" in nl:
            for d, _sub in _prox_dirs(curdir):
                cand = os.path.normpath(os.path.join(d, nm))
                if _isfile(cand):
                    return cand
            return None
        leaf = nl.lower()
        for d, sub in _prox_dirs(curdir):
            real = sub.get(leaf)
            if not real:
                continue
            cand = os.path.normpath(os.path.join(d, real))
            if _isfile(cand):
                return cand
        return None

    reach = set()
    # a434：初始队列必须**排序**——units_abs 来自 set，迭代顺序受 Python
    # 字符串 hash 随机化影响；访问顺序不同会让 max_depth 截断掉不同分支，
    # 同一工程两次建库的清单文件数因此漂移（实测 11231 / 11242）。
    # 同时改 LIFO→BFS 分层：每个文件总在**最小深度**首次访问，深度上限
    # 只截断真正超深的引用，不会因为先走了深分支而把浅层文件饿死。
    queue = [(p, 0) for p in sorted(units_abs)]
    scanned = set()
    # a452（审计 P2）：入队去重。原来只在出队时看 scanned，同一份头文件被
    # N 个父文件 include 就会入队 N 次——kernel 形态（1 万 .c / 5 万头文件 /
    # 平均出度 50）queue 峰值可达数十万到百万条元组（数百 MB），且深度截断
    # 计数对同一超深文件重复累加。_queued 与 scanned 同源口径（小写路径）。
    _queued = {p.lower() for p, _d in queue}
    _cut_depth = 0          # a434：因深度上限被丢弃的节点数（必须上报）
    _n = 0
    _head = 0               # BFS 游标（比 popleft 省 list 搬移）
    while _head < len(queue):
        p, depth = queue[_head]
        _head += 1
        pl = p.lower()
        if pl in scanned:
            continue
        if depth > max_depth:
            _cut_depth += 1
            continue
        scanned.add(pl)
        _n += 1
        if _n % 500 == 0:
            if should_cancel and should_cancel():
                raise Cancelled()
            if say:
                say("  递归 include：已扫 %d 个文件，触达 %d 个头文件，"
                    "待处理 %d" % (len(scanned), len(reach), len(queue)))
        if pl.endswith((".h", ".hpp")):
            reach.add(pl)
        if not pl.endswith((".h", ".hpp", ".c", ".cpp", ".cc", ".cxx",
                            ".s", ".S")):
            continue
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                txt = f.read()
        except OSError:
            continue
        curdir = os.path.dirname(p)
        for m in _INC_RE.finditer(txt):
            nm = m.group(1)
            cand = os.path.normpath(os.path.join(curdir, nm))
            if _isfile(cand):
                _cl = cand.lower()
                if _cl not in _queued and _cl not in scanned:
                    _queued.add(_cl)
                    queue.append((cand, depth + 1))
                continue
            # a562：邻近 inc//include/ 兄弟目录优先于全局 -I——MCU 工程
            # 无 .cmd 时 -I 恒空，不走这条整条 include 链就断在这里
            hit = _lookup_prox(nm, curdir)
            if not hit:
                hit = _lookup(nm)
            if hit:
                _hl = hit.lower()
                if _hl not in _queued and _hl not in scanned:
                    _queued.add(_hl)
                    queue.append((hit, depth + 1))
    if _cut_depth and say:
        # a434：深度截断是索引覆盖的隐含损失，必须让用户看见（不许静默）
        say("  ⚠ 递归 include 深度超过 %d 层：%d 处引用被截断"
            "（超大工程可能出现，可在设置中调整）" % (max_depth, _cut_depth))
    return reach


def detect_scope(root, say=None):
    """a400→a418（内网报告·用户重申设计）：原实现只认 sbuilder 布局，
    产物在源码树内、无 sbuilder/output/build 的工程直接返回 None——
    build() 里 `if sc:` 整段白名单判档被跳过，明明扫到大量 .cmd 仍
    全量索引（实测 tags 达数百 MB）。
    现改为：有内核根/sbuilder/常见源码目录即返回隐式 scope（tier=auto），
    由白名单优先判档接管——有中间文件必走白名单，零中间文件才全量。
    sbuilder 只是多填 artifact_roots/exclude_paths 的特例。
    返回 (scope|None, kind)；kind ∈ sbuilder / in-tree。"""
    say = say or (lambda _m: None)
    has_sbuilder = os.path.isdir(os.path.join(root, "sbuilder", "output", "build"))
    kernel_roots = []
    for cand in ("kernel/kernel_sdk", "kernel"):
        p = os.path.join(root, *cand.split("/"))
        if os.path.isdir(os.path.join(p, "arch")) or                 os.path.isfile(os.path.join(p, ".config")):
            kernel_roots.append(cand)
            break
    # 判据放宽：有内核根/有 sbuilder/有常见源码目录 = 代码工程——返回
    # 隐式 scope 让白名单判档生效，绝不静默全量（a402 的"必须有内核根"
    # 门槛随之作废：tier=auto 下误检出不丢覆盖——零产物自动回全量）
    _has_code_dirs = any(
        os.path.isdir(os.path.join(root, d))
        for d in ("kernel", "uboot", "modules", "libs", "src", "source",
                  "app", "rootfs", "tools"))
    if not (has_sbuilder or kernel_roots or _has_code_dirs):
        return None, ""
    # （2026-11-23 总审计 A-3）此处原有 v1 遗留的 `hdr`（头文件目录模式表：
    # kernel_roots 下的 include/*、逐架构探测 uboot/<d>/arch/<a>/include、
    # 非标准布局再补四个通配）——a570 改写为 v2 形态后只填「档位 + 产物源」，
    # hdr 构造完从未被读取：白做十几次 listdir，还会打一条「按 drivers/lib/
    # components 探测头文件区」的日志而探测结果根本不用。整段删除。）
    art_roots = []
    if has_sbuilder:
        art_roots = ["sbuilder/output/build"]
    # （同上：v1 遗留的 `src_roots`——kernel_roots + uboot 下各子目录 + "."，
    # 注释称「解析基准」，v2 形态下没有任何读取方。一并删除。）
    # a570：改写为 v2 形态。这是 **推荐器上线前的临时形态检测**——
    # 它只填「档位 + 产物源」，不填三态树（树由 recommend_scope 给）。
    # a570 对抗审计（P1·第三轮）：v1 的 exclude_paths=["sbuilder/output", …]
    # 在 v2 无对应字段，原实现只把它算进 `ex_p` 局部变量后丢弃（死代码）——
    # 于是 sbuilder/output 的 host/target/staging 全按 whitelist 收进索引
    # （G10 实测 host 工具链源码整体进收录集）。v2 用 `dirs` 的 off 表达。
    _dirs = {}
    if has_sbuilder:
        _dirs["sbuilder/output"] = "off"
        if os.path.isdir(os.path.join(root, "sbuilder",
                                      ".buildroot-ccache")):
            _dirs["sbuilder/.buildroot-ccache"] = "off"
    # a570 对抗审计（P2·第五轮）：detect_scope 的产物**必须自身合法**。
    # 原实现给 mode="whitelist" + 非空 dirs，`_norm_scope_v2` 明确拒绝该
    # 组合 —— 任何「detect → save」的新调用方都会写出一份下次读回即
    # `bad:*` 的配置（每次建库都弹四选一、用户手改配置被静默丢弃）。
    # 有显式 off 节点时用 mode=manual（语义等价：根默认 white + 显式 off）。
    sc = {"version": 2,
          "name": ("sbuilder 方案（自动检测）" if has_sbuilder
                   else "源码树内产物（自动检测）"),
          "mode": ("manual" if _dirs else "whitelist"), "arch": "auto",
          "dirs": _dirs,
          "artifact_roots": art_roots,
          "exclude_names": []}
    return sc, ("sbuilder" if has_sbuilder else "in-tree")


# ------------------------------------------------------------------ 推荐器
# a570（定稿 §四/§五）：把 v1 的 detect_scope（硬编码路径表）换成 L0~L3
# 四层规则，命中即停。**推荐可以有先验，执行不许有先验**——这里的名字先验
# 只影响推荐结果，用户可在树上改，不影响建库正确性。

_SCOPE_RULES_VERSION = 2
# L1 名称先验（经验默认值，非数据推导）
_L_NAME_OFF = {"rootfs", "eroot", "buildroot", "build_root", "rootfs_build"}
# 「成果物目录」的词根。2026-11-23 总审计 a684-A8：原为子串匹配
# （`zoo in n`，且 zoos 是 zoo 的冗余项）——`kazoo_lib` 这类前缀里带 zoo 的
# 目录被整棵推荐成 off。改词边界匹配：zoo 必须是一个完整的词（前后不紧
# 挨字母），`zoo_tmp` / `my-zoo` / `zoos` 仍命中。
_L_NAME_ZOO = ("zoo", "zmo")
_L_NAME_ZOO_RE = re.compile(
    "(?<![a-z])(?:%s)s?(?![a-z])" % "|".join(_L_NAME_ZOO))
_L_NAME_REL = {"release", "release_tmp", "temp_log"}
# 源代码后缀（用于统计 src）。定稿 §3.1：.S 与 .s 都要（内核有 1343 个 .S）
_SRC_EXTS = {".c", ".cpp", ".cc", ".cxx", ".s"}


def _rule_level0(path):
    """L0：buildroot 形态（结构识别，不认名字）。返回 (state, art_root) 或 None。"""
    try:
        if (os.path.isfile(os.path.join(path, "Config.in"))
                and os.path.isdir(os.path.join(path, "package"))
                and os.path.isdir(os.path.join(path, "output"))):
            return ("off", os.path.join("output", "build"))
    except OSError:
        pass
    return None


def _rule_level1(name):
    """L1：名称先验。返回 (state, reason) 或 None。"""
    n = name.lower()
    if n in _L_NAME_OFF:
        return "off", "根文件系统，第三方代码为主，推荐不收录"
    if _L_NAME_ZOO_RE.search(n):
        return "off", "成果物目录"
    if n in _L_NAME_REL:
        return "off", "发布/日志目录"
    return None


def _rule_level2(code, o, cmd):
    """L2：数量先验（按序）。"""
    if code == 0 and o == 0 and cmd == 0:
        return "off", "空目录"
    if code < 5:
        return "off", "代码极少"
    if o == 0 and cmd == 0:
        return "full", "有代码但无编译产物，白名单不可推导"
    return None


def _rule_level3(src, o, cmd):
    """L3：比值判定（有产物才进入）。返回 (state, reason, warn)。"""
    o_ratio = (src / float(o)) if o else float("inf")
    cmd_ratio = (cmd / float(src)) if src else 0.0
    o_cmd = (o / float(cmd)) if cmd else float("inf")
    if o_ratio < 0.8:
        return "whitelist", "增量残留嫌疑", True
    if o_ratio <= 2:
        return "whitelist", "", False
    if cmd_ratio >= 0.03:
        return "whitelist", "有完整构建描述", False
    if o_cmd > 5:
        if cmd == 0:
            # a570 新增（用户定调）：无 .cmd → 白名单单元必然为 0
            return "full", "无构建描述，白名单必然为空", False
        if src < 2000:
            return "full", "产物覆盖不足", False
        return "whitelist", "产物覆盖不足但规模过大", True
    return "whitelist", "", False


def _count_dir_full(path, deadline, should_cancel=None):
    """递归统计一个目录的三元组，并顺手按**一级子目录**分组。

    返回 (total, per_sub, timed_out, soft_skipped)：
      total   = [src, code, o, cmd]
      per_sub = {"__root__"|子目录名: [src, code, o, cmd]}
      timed_out = bool（deadline 到 → 数据不完整，调用方必须降级处理）
      soft_skipped = 读不了而被跳过的目录数（与「真空目录」必须能区分，
                     否则推荐器会把断连/权限目录判成「空目录」off）

    为什么一次递归出两种结果：顶层总计与一级子目录分组是同一批数据，
    分两次扫会让推荐器耗时翻倍（G10 单 sbuilder 就要 22 秒）。
    """
    import fnmatch as _fnm   # noqa: F401（保留：将来支持通配排除）
    total = [0, 0, 0, 0]
    per_sub = {}
    soft = [0]
    stack = [(path, None)]        # (目录, 所属一级子目录名)
    skipped = {s.lower() for s in _SKIP_DIRS}
    while stack:
        if should_cancel and should_cancel():
            raise Cancelled()
        if time.time() > deadline:
            return total, per_sub, True, soft[0]
        d, top_sub = stack.pop()
        try:
            with os.scandir(d) as it:
                ents = list(it)
        except OSError:
            soft[0] += 1
            continue
        for e in ents:
            try:
                if e.is_dir(follow_symlinks=False):
                    nm = e.name
                    if nm.startswith(".") or nm.lower() in skipped \
                            or nm.lower() in _TMP_NAMES:
                        continue
                    child_sub = top_sub if top_sub is not None else nm
                    stack.append((e.path, child_sub))
                else:
                    low = e.name.lower()
                    ext = os.path.splitext(low)[1]
                    key = top_sub if top_sub is not None else "__root__"
                    b = per_sub.setdefault(key, [0, 0, 0, 0])
                    if ext in _SRC_EXTS:      # 已 lower，.S 归一成 .s
                        total[0] += 1; b[0] += 1
                    if ext in CODE_EXTS:
                        total[1] += 1; b[1] += 1
                    if low.endswith(".o"):
                        total[2] += 1; b[2] += 1
                    elif low.endswith(".cmd"):
                        total[3] += 1; b[3] += 1
            except OSError:
                soft[0] += 1
                continue
    return total, per_sub, False, soft[0]


def _classify(name, path, stats, sub_stats):
    """把三元组喂给 L0~L3，返回 (state, reason, warn)。"""
    l0 = _rule_level0(path)
    if l0:
        st, art = l0
        return st, "buildroot 构建树（Config.in + package/ + output/）", False
    l1 = _rule_level1(name)
    if l1:
        return l1[0], l1[1], False
    src, code, o, cmd = stats
    l2 = _rule_level2(code, o, cmd)
    if l2:
        return l2[0], l2[1], False
    st, reason, warn = _rule_level3(src, o, cmd)
    return st, reason, warn


def recommend_scope(root, progress=None, should_cancel=None, say=None):
    """扫描工程并生成推荐配置（定稿 §11）。

    返回 dict：
      {"ok": True, "mode": "manual", "dirs": {...},
       "artifact_roots": [...], "detected": [...],
       "nodes": [{rel, state, reason, warn, src, code, o, cmd, subs:{...}}],
       "estimate": {...}, "scan_seconds": n}

    **完整递归统计**（定稿 §11.1）：只统计顶层目录的完整三元组；一级子
    目录的数值仅用于 UI 展开，不参与判定。
    """
    import time as _t
    say = say or (lambda _m: None)
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        return {"ok": False, "err": "目录不存在：%s" % root}
    tops = []
    try:
        with os.scandir(root) as it:
            for e in it:
                if not e.is_dir() or e.name.startswith(".") \
                        or e.name.lower() in _SKIP_DIRS \
                        or e.name.lower() in _TMP_NAMES:
                    # a570 对抗审计（P1·第十六轮）：推荐器也必须跳过 tmp 类——
                    # 否则树里显示「tmp 全 6 源」，而 walk 无条件剪 tmp →
                    # 用户按推荐确认后实际零文件（口径相反）。
                    continue
                tops.append(e.name)
    except OSError as ex:
        return {"ok": False, "err": "读取工程根失败：%s" % ex}
    tops.sort()
    t_start = _t.time()
    nodes = []
    dirs = {}
    artifact_roots = []
    detected = []
    infer_files = 0
    for i, top in enumerate(tops, 1):
        if should_cancel and should_cancel():
            raise Cancelled()
        abs_p = os.path.join(root, top)
        if progress:
            progress(i, len(tops), "正在扫描 %s/" % top)
        if say:
            say("  · 扫描 %s/（%d/%d）…" % (top, i, len(tops)))
        st_total, per_sub, timed_out, soft = _count_dir_full(
            abs_p, deadline=_t.time() + 300, should_cancel=should_cancel)
        state, reason, warn = _classify(top, abs_p, st_total, per_sub)
        # a570 对抗审计：残缺统计不能用来判档——
        # ① 超时：部分统计会让「code>=5,o=0,cmd=0」误判 full（索引爆炸）
        #    或「code<5」误判 off（静默丢源码）。强制降为 whitelist（最保守：
        #    有产物才收，不会把巨树全收）并告警，让用户自己在树上改。
        # ② 软错误：读不了的目录与真空目录无法区分，同样不能给 off。
        if timed_out:
            state, warn = "whitelist", True
            reason = "统计超时，数据不完整——默认按白名单保守收录，请在树上确认"
        elif soft:
            # a570 对抗审计（P1）：原判据是「soft and not any(st_total)」，
            # 只挡住「全零」；软错误 + 部分统计仍按残缺数据判档（实测
            # total=[2,2,0,0]/soft=7 → 判 off「代码极少」，静默丢源码）。
            # 有任何不可读目录就不能给 off —— 一律保守 whitelist + 告警。
            state, warn = "whitelist", True
            reason = ("目录不可读（%d 个），数据不完整——默认按白名单保守收录，"
                      "请在树上确认" % soft)
        _degraded = bool(timed_out or soft)
        l0 = None if _degraded else _rule_level0(abs_p)
        if l0:
            detected.append("buildroot")
            art = (top + "/" + l0[1]).replace("\\", "/").lower()
            artifact_roots.append(art)
        # a570 对抗审计：删掉残留的空 if 块（历史遗留死代码）
        dirs[top.lower()] = state        # 与 _norm_dirs 同口径（keys lower）
        infer_files += st_total[1]
        nodes.append({
            # a570 对抗审计（P2）：rel 必须与 dirs 的键同口径（lower）。
            # 原 rel 用磁盘真实大小写（`Kernel`）而 dirs 键是 lower
            # （`kernel`），前端按 rel 查 dirs 一律落空：按钮不高亮、
            # 显示「继承自根默认」，用户以为推荐没生效。name 保留原名。
            "rel": top.lower(), "name": top, "state": state,
            "reason": reason, "warn": bool(warn),
            "src": st_total[0], "code": st_total[1],
            "o": st_total[2], "cmd": st_total[3],
            "timed_out": bool(timed_out),
            "subs": [{"name": k, "src": v[0], "code": v[1],
                      "o": v[2], "cmd": v[3]}
                     for k, v in sorted(per_sub.items())],
        })
    # 估算（UI 展示用）
    _cnt = {"whitelist": 0, "full": 0, "off": 0}
    for v in dirs.values():
        _cnt[v] = _cnt.get(v, 0) + 1
    elapsed = _t.time() - t_start
    say("  推荐完成：%d 个顶层目录（白 %d · 全 %d · 不勾 %d），耗时 %.1fs"
        % (len(tops), _cnt["whitelist"], _cnt["full"], _cnt["off"], elapsed))
    return {
        "ok": True, "mode": "manual",
        "name": "推荐配置", "arch": "auto",
        "dirs": dirs,
        "artifact_roots": artifact_roots,
        "exclude_names": [],
        "detected": sorted(set(detected)),
        "nodes": nodes,
        "rules_version": _SCOPE_RULES_VERSION,
        "estimate": {"dirs": _cnt, "code_files": infer_files},
        "scan_seconds": round(elapsed, 1),
    }


def _expand_patterns(patterns, dirs_set):
    """scope 路径模式（支持 ${arch} 已替换后的通配，如
    uboot/*/arch/arm/include）→ 展开为命中目录集合。
    a398（审计#5/BUG-C）：①目录集须含**祖先目录**（arch/arm/include 直下
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


def _under_any(rel, dirs):
    """rel 是否落在任一路径前缀之下（大小写不敏感，posix 分隔符）。

    a570：`full_dirs` 判定用。dirs 存**显式节点**（不展开），所以这里做
    前缀匹配而不是集合成员判定。空 dirs 直接 False（旧库无该字段）。
    """
    if not dirs:
        return False
    rl = rel.lower().replace("\\", "/")
    for d in dirs:
        dl = d.lower().strip("/")
        # a570 对抗审计（P1·第十九轮）：空键 "" 表示「根自身也是 full」，
        # 必须让所有路径都命中——否则根全量区源码全被标 in_build=False，
        # 前端渲染红 ✗「不在编译内」。
        if not dl:
            return True
        if rl == dl or rl.startswith(dl + "/"):
            return True
    return False


def _top_dirs_of(rels):
    """文件 rel 集合 → 顶层**目录**首段（小写）。

    2026-11-23 总审计 a684-A2：rel 是文件相对路径，根直下文件（`Makefile`、
    不含 /）的首段是文件名而不是目录——落盘范围时把它补成 `makefile: full`
    等于往 dirs 里写一个不存在的节点。这里直接把不含 / 的排掉。
    """
    return {r.split("/", 1)[0].lower() for r in rels if "/" in r}


def _scope_summary(sc):
    """一行摘要（日志用）。a570：v2 的 dirs 只数显式节点。"""
    dirs = sc.get("dirs") or {}
    parts = ["%s（%s）" % (sc.get("name", ""), sc.get("mode", "manual"))]
    if dirs:
        _cnt = {"whitelist": 0, "full": 0, "off": 0}
        for v in dirs.values():
            _cnt[v] = _cnt.get(v, 0) + 1
        parts.append("白 %d · 全 %d · 不勾 %d"
                     % (_cnt["whitelist"], _cnt["full"], _cnt["off"]))
    if sc.get("artifact_roots"):
        parts.append("产物源 %d" % len(sc["artifact_roots"]))
    if sc.get("exclude_names"):
        parts.append("排除名 %d" % len(sc["exclude_names"]))
    return " · ".join(p for p in parts if p)


def build(root, log=None, progress=None, should_cancel=None,
          backend="auto", scope=None, ask_tier=None):
    """收录范围化建库（a398 档B）。scope：None=自动发现（工程
    .fcpk-scope.json > 已存范围 > 全量）；dict=内联配置（API 层建库成功后
    落盘独立存储位）。log=callable(str)；progress=callable(done,total,label)。
    ask_tier=callable(info)->"full"|"whitelist"|"cancel"：白名单覆盖率偏低
    时询问用户建库方式（None=不问，默认 full）。
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

    say("阶段 0/4：解析收录范围…")
    prog(1, "解析收录范围")

    # ---- 阶段 0：收录范围解析（a570 三档重构 v2）----
    sc, sc_src = None, ""
    if scope is not None:
        if not isinstance(scope, dict):
            raise RuntimeError("收录范围配置必须是 JSON 对象")
        _ok, _sc2 = _norm_scope(scope, root)
        if not _ok:
            raise RuntimeError("收录范围配置不合法：%s" % _sc2)
        sc, sc_src = _sc2, "inline"
    else:
        sc, sc_src = load_scope(root)
        if sc_src == "v1-deprecated":
            say("  ⚠ 旧版（v1）收录范围配置已废弃——本次按推荐器重新生成，"
                "建库成功后写回 v2 到工程根")
            sc, sc_src = None, ""
        elif sc_src.startswith("bad:"):
            say("  ⚠ 收录范围配置解析失败（%s）——按推荐器重新生成" % sc_src[4:])
            sc, sc_src = None, ""
    if sc is None:
        # 零配置：推荐器（P2 实现）未就绪前先退回形态检测 + 隐式范围。
        # 推荐器上线后这里换成 recommend_scope(root) 并自动预填三态树。
        _dsc, _dkind = detect_scope(root, say=say)
        if _dsc:
            sc, sc_src = _dsc, "detect"
    if sc is None:
        # 隐式范围：形态检测也没识别出来。按 mode=manual + 根默认 whitelist
        # 走（等价于旧 a418 的隐式范围——有 .cmd 走白名单，零产物降全量）
        sc = {"version": 2, "name": "自动（隐式范围）",
              "mode": "manual", "arch": "auto",
              "dirs": {}, "artifact_roots": [], "exclude_names": []}
        sc_src = "implicit"
    _src_label = {"project": "工程配置 " + SCOPE_FILE,
                  "inline": "本次指定",
                  "implicit": "自动（隐式范围）"}.get(sc_src)
    if sc_src == "detect":
        _src_label = "自动检测（%s 方案）" % _dkind
    say("收录范围：%s［来源：%s］" % (_scope_summary(sc), _src_label or sc_src))
    # a570：三态求值回调 + 产物源
    _state_of = _make_state_of(sc)
    _art_roots = tuple(sc.get("artifact_roots") or ())

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
    cmd_abs = []        # a422：已扫到的 .cmd 绝对路径（供 -I 提取复用，零额外 I/O）
    all_rels = set()    # a394：全量 rel 集合（同目录同名映射走 set 查，零网络 I/O）
    dirs_files = {}     # a398：rel 目录 → [文件名]（档B 同目录 .h 补收）
    all_dirs = set()    # a398：出现过的目录集合（header_roots glob 展开用）
    # a570：v2 去掉了显式的 source_roots 字段，但 out-of-tree 构建
    # （G10：`.cmd` 里写 `arch/arm64/.../x.c`，真源在 kernel/kernel_sdk）
    # 必须要有解析基准，否则退回「.cmd 同目录的产物副本」——跳转指向副本。
    # a570 对抗审计（P1）：由形态检测给出候选源码根，与旧 source_roots 等价。
    _src_roots_abs = [root]
    try:
        _det2, _dk2 = detect_scope(root)
        # in-tree 形态（有 kernel/kernel_sdk 但 O= 外挂构建）退回 [root]，
        # `.cmd` 里 `arch/arm/x.c` 这类相对源码根的 token 解析失败——旧版
        # source_roots 无论哪种形态都给 kernel_roots + uboot/*。
        if _det2:
            for _c in ("kernel/kernel_sdk", "kernel", "uboot"):
                _p = os.path.join(root, *_c.split("/"))
                if os.path.isdir(_p) and _p not in _src_roots_abs:
                    _src_roots_abs.append(_p)
            _ub = os.path.join(root, "uboot")
            if os.path.isdir(_ub):
                try:
                    for _d in sorted(os.listdir(_ub)):
                        _p = os.path.join(_ub, _d)
                        if not _d.startswith(".") and os.path.isdir(_p) \
                                and _p not in _src_roots_abs:
                            _src_roots_abs.append(_p)
                except OSError:
                    pass
            if len(_src_roots_abs) > 1:
                say("  .cmd 源路径解析基准：%d 个源码根（out-of-tree 构建）"
                    % (len(_src_roots_abs) - 1))
    except Exception:
        pass
    wstat = {"pruned": 0}
    _aux_n = 0            # a409：非 C/C++ 中间文件计数（白名单优先判据）
    _last_prog = 0.0    # 用户令：1s 一拍的过程显示计时
    _last_tot = -1      # a395：计数停滞可见——大目录/非代码区穿越时计数
    _last_tot_t = time.time()   # 不动（walk 活着），标签提示"无新增"防误判卡死

    def _eat_cmd(abs_p, rel):
        """a398：.cmd 消费抽出（index walk 与 artifact walk 共用）。
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

    # ① index walk：收录目标。a570：v2 三态树交给 state_of 求值——
    # off 在 scandir 层剪枝（不进 all_rels），比过去扫完再过滤快得多。
    # artifact_roots 的「仅产物源」目录由阶段 1b 单独走。
    for abs_p, rel in _walk_files(
            root, subs=["."],
            should_cancel=should_cancel, say=say,
            excl_names=(sc["exclude_names"] if sc else ()),
            excl_paths=(), stats=wstat,
            state_of=_state_of, artifact_roots=_art_roots):
        all_rels.add(rel)
        low = rel.rsplit("/", 1)[-1].lower()   # a415R2 N2：移出 if sc（原 _fn 仅 scope 分支赋值，全量建库必崩）
        if sc:   # a398（审计#29）：全量建库不建字典白占内存
            _d = rel.rpartition("/")[0]
            dirs_files.setdefault(_d, []).append(rel.rsplit("/", 1)[-1])
            # a398（审计#5）：祖先目录一并入集（include 直下零文件的
            # header_root 通配匹配靠它）
            while _d not in all_dirs:
                all_dirs.add(_d)
                _d = _d.rpartition("/")[0]
        if low.endswith(".cmd"):
            cmd_files += 1           # R17-4：文件名计数（stale 同口径）
            cmd_abs.append(abs_p)
            if _eat_cmd(abs_p, rel):
                cmd_count += 1
        elif low.endswith(".o"):
            o_files.append(rel)
            o_count += 1
            # a394：同目录同名映射延后到 walk 结束用集合查（原逐 .o
            # os.path.isfile——网盘上 2.3 万 .o × 每个多次 stat = 数万次
            # SMB 往返，扫描像卡死）
        elif any(low.endswith(e) for e in _AUX_ARTIFACT_EXTS):
            _aux_n += 1   # a409：非 C/C++ 中间文件（.pyc/.class/.js.map…）
        else:
            b, ext = os.path.splitext(low)
            if ext in _UNIT_EXTS | {".s"}:   # a398（审计#7/BUG-A）：.S 汇编单元也进 basename 兜底池
                unit_by_base.setdefault(b, set()).add(rel)
        # 用户令：全部过程显示 1s 一更新、同一行、不刷屏——中间进度走
        # prog()（前端 progress 文本同一行刷新），say() 只留阶段头和终态
        # a394：min(28,_tot/800) 在 2.2 万文件即顶格 30%，之后进度条假死
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

    # ② artifact walk（a570）：artifact_roots = 「仅产物源」目录——只读
    # .cmd/.o 推白名单，不收录源码。它们在 index walk 里已被 `off` 剪掉
    # （或用户显式标 off），所以这里单独再走一遍。
    if sc and _art_roots:
        say("  产物源扫描（只读 .cmd/.o，不索引源码）：%s"
            % "、".join(_art_roots))
        _w2 = {"pruned": 0}
        _a_n0, _a_o0 = cmd_files, o_count
        _a_tot = 0
        _a_skip = 0
        # a570：产物源目录内部不再按三态剪（它本身就是要扫的），但仍跳
        # _SKIP_DIRS / tmp / 环防护。excl_names 保留（用户明确的排除）。
        for abs_p, rel in _walk_files(
                root, subs=_art_roots,
                should_cancel=should_cancel, say=say,
                excl_names=sc["exclude_names"], excl_paths=(),
                stats=_w2, dot_keep=True):
            # a424（用户质疑「为什么扫描 4 万却处理 9.6 万」）：先计数再跳过，
            # 让「已处理」= 遍历到的文件总数，与 include∩artifact 去重无关
            _a_tot += 1
            if rel in all_rels:
                _a_skip += 1
                continue   # a415R2 N20：include∩artifact 重叠区已消费，不双计
            if _a_tot % 500 == 0:
                say("  产物源扫描中：已处理 %d（新增 .cmd %d · .o %d · 去重跳过 %d）"
                    % (_a_tot, cmd_files - _a_n0, o_count - _a_o0, _a_skip))
            low = rel.rsplit("/", 1)[-1].lower()
            if low.endswith(".cmd"):
                cmd_files += 1
                cmd_abs.append(abs_p)
                if _eat_cmd(abs_p, rel):
                    cmd_count += 1
            elif low.endswith(".o"):
                o_files.append(rel)
                o_count += 1
        wstat["pruned"] += _w2.get("pruned", 0)
        # a570 对抗审计（P2·第十二轮）：产物源阶段的超时/软错误原被丢弃——
        # 产物源被放弃时白名单源（.cmd）静默缺失，汇总告警与 meta 都看不到。
        for _k2 in ("timeout_items", "soft_skipped", "tmp_skipped"):
            _v2 = _w2.get(_k2)
            if not _v2:
                continue
            if _k2 == "timeout_items":
                # a570 对抗审计（P2·第十三轮）：调用方可能传非 list。
                if not isinstance(wstat.get(_k2), list):
                    wstat[_k2] = []
                wstat[_k2].extend(_v2 if isinstance(_v2, list) else [])
            else:
                wstat[_k2] = wstat.get(_k2, 0) + _v2
        say("  产物源扫描完成：遍历 %d 个文件 · 新增 .cmd %d · 新增 .o %d"
            " · 与收录集重复跳过 %d"
            % (_a_tot, cmd_files - _a_n0, o_count - _a_o0, _a_skip))
    if wstat.get("pruned"):
        say("  ⚠ 环防护剪枝 %d 个目录（SMB 符号链接自链，报告 §2.1）"
            % wstat["pruned"])
    # a570 对抗审计（P1·第十一轮）：超时被放弃的子树必须**明确告警**。
    # 原实现只记 stats，生产代码零消费——≤cap 个目录卡死时建库「成功完成」
    # 却静默缺整棵子树，用户只看到日志里几行「⚠ 扫描超时」淹没在进度中。
    # a570 对抗审计（P2·第十三轮）：tmp 类目录剪枝用户看不到——里面若有
    # 真源码就是静默丢失。汇总一行让用户能看见。
    if wstat.get("tmp_skipped"):
        say("  · 跳过 %d 个 tmp/temp 类目录（用户定调：无条件剪枝）"
            % wstat["tmp_skipped"])
    _tos = wstat.get("timeout_items") or []
    if _tos:
        say("  ⚠ 共 %d 个子树扫描超时被放弃（%s）——这些目录**未进索引**，"
            "如属正常大目录请调大超时或拆分收录范围后重建"
            % (len(_tos), "、".join(t["rel"] for t in _tos[:5])
               + ("…" if len(_tos) > 5 else "")))

    # a394：同目录同名映射（walk 内收集全量集合，set 查零 I/O）。
    # a398（审计#7）：候选后缀补 .S/.s（entry.S 靠 .o 同名兜底）+ 大小写
    # 不敏感（.o 与 .S 大小写形态不保证一致——用 lower 索引一次建好）
    # a434：o_files 由并发目录扫描产出，顺序不稳定。下面用 setdefault 记录
    # 「源 → 该源对应的 .o」，顺序不同会选中不同的 .o（同一源被多个产物
    # 覆盖时），进而让 manifest/symbols 两次建库不一致。排序固定。
    o_files.sort()
    _rel_by_l = {r.lower(): r for r in all_rels}
    say("  单元推导 ① 同目录同名：%d 个 .o…" % len(o_files))
    _bt = _Beat(say)
    _i_o = 0
    for orel in o_files:
        _i_o += 1
        _bt.tick(_i_o, len(o_files),
                 "  单元推导 ① 同目录同名 %d/%d（命中 %d）",
                 _i_o, len(o_files), len(compiled))
        stem = orel[:-2]
        for ext in (".c", ".cpp", ".cc", ".cxx", ".S", ".s"):
            hit = _rel_by_l.get((stem + ext).lower())
            if hit:
                compiled.setdefault(hit, {"o": orel, "src": "omap"})
                break
        else:
            pending_o.append(orel)
    # a427（实测：产物树里大量 .o 与源不同目录，靠上溯+命名约定能救回
    # 其中约六成）：原实现只看「当前目录 + 一级子目录」，
    # 且不认 libtool/CMake 的命名约定——libcurl 的
    # `lib/.libs/libcurl_la-base64.o` 对应 `lib/base64.c`（在**上两层**、
    # 且去掉了 libcurl_la- 前缀），一个都匹配不上。
    # 现改为：① 沿祖先逐层找（最多 8 层，每层「直接同名」+「一级子目录同名」）
    #         ② 名字先按 libtool/CMake 约定剥离前缀再试
    #         ③ 歧义时取路径深度最接近的（不猜，只在一处命中时采用）
    # a434：all_dirs / pending_o 都是并发扫描产出的无序容器。两个不同 .o
    # 可能都能推出同一个源文件，`setdefault` 让先遍历到的那个胜出——顺序
    # 不稳定就等于 manifest 不稳定。排序后先到者恒为字典序最小的 .o。
    _dsub = {}
    for _dd in sorted(all_dirs):
        _par = _dd.rpartition("/")[0]
        _dsub.setdefault(_par, []).append(_dd)
    pending_o.sort()

    def _name_variants(b):
        """libtool / CMake / 常见前缀剥离：libxxx_la-foo、libfoo-so-bar、
        pref-lib_la-baz → foo/bar/baz。返回 [原名, 各剥法]。"""
        out = [b]
        for sep in ("_la-", "_so-", ".libs-"):
            if sep in b:
                out.append(b.split(sep, 1)[1])
        # libcurl_la-base64 → 上面已处理；再补 xxx-yyy 的单破折号剥法
        # （仅当左侧像库前缀 lib*/xxx_ 或纯字母且右侧也非空）
        if "-" in b:
            _l, _r = b.split("-", 1)
            if _r and (_l.startswith("lib") or _l.endswith(("_la", "_so"))):
                out.append(_r)
        seen, uniq = set(), []
        for v in out:
            if v and v not in seen:
                seen.add(v)
                uniq.append(v)
        return uniq

    _EXT_SRC = (".c", ".cpp", ".cc", ".cxx", ".S", ".s")
    say("  单元推导 ② .o 上溯找源（≤8 层 + 前缀剥离 + 构建根剥离）："
        "%d 个待定 .o…" % len(pending_o))
    _bt = _Beat(say)
    _i_o = 0
    for orel in list(pending_o):
        _i_o += 1
        _bt.tick(_i_o, len(pending_o),
                 "  单元推导 ② .o 上溯 %d/%d（命中 %d）",
                 _i_o, len(pending_o), len(compiled))
        stem = os.path.splitext(orel)[0]
        bname = os.path.basename(stem)
        _names = _name_variants(bname)
        d = os.path.dirname(stem)
        _hit = None
        _amb = []
        # a428（实测：SCons 等非 Kbuild 工程的产物在 out/<mach>/obj/<cmp>/src/x.o，
        # 源码在 drivers/<cmp>/src/x.c 或 components/<cmp>/src/x.c——
        # 中间 mach/obj 两层不是源码路径，靠 8 层上溯永远找不到。
        # 解法：把 out/obj 这类构建根剥掉，用剩余相对路径直接查）
        _segs = stem.split("/")
        for _i_seg, _sg in enumerate(_segs):
            if _sg not in ("out", "obj", "Obj", "OBJ", "build"):
                continue
            _tail = "/".join(_segs[_i_seg + 1:])
            if not _tail:
                continue
            # 构建根剥离后，剩余路径要接回该构建根所在工程前缀
            # （uboot/<cfg>/out/<mach>/obj/<cmp>/src/x.o →
            #  uboot/<cfg>/ + drivers/<cmp>/src/x.c）
            _roots = ["/".join(_segs[:_i_seg]), ""]
            if _segs[0] == "uboot" and len(_segs) > 2:
                _roots.insert(0, "/".join(_segs[:2]))
            for _rt in _roots:
                for _pfx in ("", "drivers/", "components/", "lib/",
                             "arch/", "app/"):
                    _cand = (_rt + "/" if _rt else "") + _pfx + _tail
                    for _e in _EXT_SRC:
                        _h = _rel_by_l.get((_cand + _e).lower())
                        if _h:
                            if _hit is None:
                                _hit = _h
                            elif _h != _hit:
                                _amb.append(_h)
        if _hit and not _amb:
            compiled.setdefault(_hit, {"o": orel, "src": "buildroot"})
            pending_o.remove(orel)
            continue
        _hit = None
        _amb = []
        for _lvl in range(8):
            if not d:
                break
            _cands = []
            for _n in _names:
                _cands += [d + "/" + _n + e for e in _EXT_SRC]
                for _sd in _dsub.get(d, ()):
                    _cands += [_sd + "/" + _n + e for e in _EXT_SRC]
            for _cand in _cands:
                _h = _rel_by_l.get(_cand.lower())
                if not _h:
                    continue
                if _hit is None:
                    _hit = _h
                elif _h != _hit:
                    _amb.append(_h)
            if _hit and not _amb:
                break            # 该层唯一命中，采纳（就近优先，不猜）
            d = d.rpartition("/")[0]
        if _hit and not _amb:
            compiled.setdefault(_hit, {"o": orel, "src": "updir"})
            pending_o.remove(orel)
        # 多层多命中 = 歧义：保持未定，交给 ③ basename 唯一兜底
    # basename 全局唯一兜底（out-of-tree）
    say("  单元推导 ③ basename 全局唯一兜底：%d 个剩余 .o…" % len(pending_o))
    _bt = _Beat(say)
    _i_o = 0
    for orel in pending_o:
        _i_o += 1
        _bt.tick(_i_o, len(pending_o),
                 "  单元推导 ③ basename 兜底 %d/%d", _i_o, len(pending_o))
        b = os.path.splitext(os.path.basename(orel))[0].lower()
        hits = unit_by_base.get(b)
        if hits and len(hits) == 1:
            compiled.setdefault(next(iter(hits)), {"o": orel, "src": "bmap"})
            # a415R2 N3：值已是 set（#15 改），hits[0] 会 TypeError——
            # 海思 out/obj/libtool .libs/产物树 .o 全走这条，撞上必崩

    # ③ 最终清单（a570 v2）：
    #   · whitelist 单元 → 编译单元 + 同目录头 + 递归 include 触达
    #   · full 目录    → 该子树全部 CODE_EXTS（无视产物）
    #   · off 目录     → 不收（已在 walk 剪枝；被 include 触达的头文件例外）
    # 这取代了旧的三层兜底（always_include / fallback_full / manual 逐目录
    # 核覆盖）——目录状态本身就表达「这里全收还是只收推导结果」。
    def _strip_dg(nm):
        """去掉已有的降级后缀，避免重复建库时反复追加（P2·第十五轮）。

        a570 对抗审计（P1·第十七轮）：后缀表必须覆盖所有 `_collapse_wl`
        会写的形态——原来只有两条，`（白名单推导为空，自动全量）` 每次重建
        都再叠一层。
        """
        nm = (nm or "").strip() or "未命名范围"
        while True:
            for _sfx in ("（自动降级为全量）", "（非 C/C++ 工程，自动全量）",
                         "（白名单推导为空，自动全量）"):
                if nm.endswith(_sfx):
                    nm = nm[:-len(_sfx)].strip() or "未命名范围"
                    break
            else:
                break
        return nm

    _dflt = _scope_root_default(sc)
    # a570 对抗审计（P2·第十四轮）：全量降解后，manifest 的 full_dirs 必须
    # 表达「全树都在构建内」——否则查询期所有源被标 in_build=False（前端
    # 渲染红色 ✗「不在编译内」），且 dirs={} 落盘后重建也修不回。
    _all_full = False
    _has_full = any(v == "full" for v in (sc.get("dirs") or {}).values()) \
        or _dflt == "full"
    _has_wl = any(v == "whitelist" for v in (sc.get("dirs") or {}).values()) \
        or _dflt == "whitelist"
    # 收录集里存在 whitelist 区才需要跑白名单推导（纯 full 档直接全收）
    _need_wl = _has_wl

    def _st(rel):
        return _resolve_dir_state(rel, sc.get("dirs") or {}, _dflt)

    if wstat.get("soft_skipped"):
        say("  ⚠ 跳过 %d 个不可读目录（悬空符号链接/权限拒绝——如 rootfs 里"
            "指向宿主机绝对路径的 usr/lib64，不影响其余子树）"
            % wstat["soft_skipped"])
    # full 区：子树内全部代码文件（含头文件），一次遍历
    _full_files = set()
    if _has_full:
        for r in all_rels:
            if _st(r) == "full":
                _full_files.add(r)
        say("  全量区：%d 个代码文件（%d 个目录标 full）"
            % (len(_full_files),
               sum(1 for v in (sc.get("dirs") or {}).values() if v == "full")))
    final_files = _full_files if _has_full else set()
    if _need_wl:
        _units = {_rel_by_l[u.lower()] for u in compiled.keys()
                  if u.lower() in _rel_by_l}
        # 零单元 / 低覆盖的处理（a570 定稿 §4.3）：
        #   · 完全零单元 + 首次建库 → 暂停询问（四选一）
        #   · 完全零单元 + 已有配置 → 自动降全量 + 汇总告警
        #   · 有单元但覆盖率 < 2%  → 自动降全量 + 告警
        _all_code = {r for r in all_rels
                     if os.path.splitext(r)[1].lower()
                     in (".c", ".cpp", ".cc", ".cxx", ".S", ".s")}
        # a570 对抗审计（P2·第十二轮）：原 `_has_art` 前置让**零产物**工程
        # 既不询问也不降级 → 纯 whitelist 下 final_files 为空 →
        # 「收录清单为空」（文案还指向错误的配置项）。零产物 + 有源码
        # 时必须走同一条处理（降全量或询问）。
        _has_art = bool(cmd_files or o_count or _aux_n)
        _cover = (len(_units) / float(len(_all_code))) if _all_code else 1.0
        _ASK_COVER = 0.02
        # a570 对抗审计（P1·第十三轮）：纯非 C/C++ 工程（Python/JS/Go…）
        # `_all_code` 为空、无单元、无产物——白名单推导对它天然无解，
        # 必须直接降全量（NAV_LANGS 明示支持这些语言，HEAD 版也能建）。
        # a570 对抗审计（P2·第十五轮）：用户显式配了节点时不该自动降级
        # ——那是他明确的范围，降级会把 mixed 档的 full 区一起改掉。
        _explicit = bool(sc.get("dirs") or {})
        _nonc_only = (not _all_code) and bool(all_rels)
        # a570 对抗审计（P0·第十六轮）：_explicit 原先把「降级」和「告警/询问」
        # 一起关掉——推荐器给出的 `{kernel: whitelist}`（正好是显式 dirs）
        # 在零产物/零单元时既不询问也不降级，静默收 1% 或直接「收录清单为空」。
        # 正确语义：显式配置只保护 **off/full 节点**不被冲掉，白名单区推导
        # 不可信时照常降级（把 whitelist 区转 full，off 区原样保留）。
        _wl_bad = ((not _all_code and bool(all_rels))
                   or (not _units and bool(_all_code))
                   or (_has_art and (not _units or _cover < _ASK_COVER)))

        def _collapse_wl(why):
            """把「白名单生效区」整体转全量：off 区照旧剪掉，显式 dirs 不被
            冲掉（只把 whitelist 节点升级成 full，并给未显式的顶层补 full，
            让根默认不再影响下次建库）。"""
            nonlocal _units, _all_full
            for r in all_rels:
                if _st(r) != "off":
                    final_files.add(r)
            _units = set()
            _d0 = dict(sc.get("dirs") or {})
            _nd = {k: ("full" if v == "whitelist" else v)
                   for k, v in _d0.items()}
            # a570 对抗审计（P1·第二十轮）：**不再自动补顶层 full 键**。
            # 根键 ""=full 已经完整表达「未显式区全量」（`_resolve_dir_state`
            # 逐级上溯到 "" 即返回 full），补出来的 `vendor: full` 反而会成为
            # `_live_set` 里的「显式 live 证据」，让 exclude_names 与
            # artifact_roots 隔离双双失效（实测：二次建库多收 vendor/drop.c）。
            # 根显式 off 时保持 off；其余一律写 full。
            if _nd.get("") != "off":
                _nd[""] = "full"
            sc["dirs"] = _nd
            sc["mode"] = "manual" if _nd else "full"
            sc["name"] = _strip_dg(sc.get("name")) + "（%s，自动全量）" % why
            _all_full = True

        if _nonc_only:
            say("  · 未发现 C/C++/汇编源码（共 %d 个代码文件，语言不在"
                "白名单推导范围）——按全量收录" % len(all_rels))
            _collapse_wl("非 C/C++ 工程")
            _ask_needed = False
        else:
            # a570 对抗审计（P0·第十六轮）：显式 dirs 也要判定——只跳过
            # 「询问」（用户已确认过范围）。零单元时**先不降级**（显式
            # whitelist 可能是精准意图，mixed 档里别的 full 区仍有内容），
            # 留到最终清单兜底处：整体为空才降级，避免静默硬失败。
            if _explicit and _wl_bad:
                say("  ⚠ 显式范围里的白名单区推导不足（产物 %d 个 → 单元 %d 个，"
                    "共 %d 个源码文件）——先按你的配置收录"
                    % (o_count + cmd_files, len(_units), len(_all_code)))
            _ask_needed = (not _explicit) and _wl_bad
        # a570 对抗审计（P0·第十六轮）：显式 dirs 下白名单区推导为零
        # （推荐器给的 `{kernel: whitelist}` + 零产物 / 纯 Python 工程只勾了
        # 一个「不」）原先要么静默收 1%、要么「收录清单为空」硬失败。
        # 显式配置保护的是 off/full 节点，白名单区推不出来时照常降级。
        if _explicit and _wl_bad and not _ask_needed:
            _wl_n = sum(1 for r in all_rels if _st(r) == "whitelist")
            if not _units and _wl_n:
                say("  ⚠ 白名单区推导出 0 个源码单元（产物 %d 个，白名单区"
                    " %d 个源码文件）——该区按全量收录，「不勾」区不受影响"
                    % (o_count + cmd_files, _wl_n))
                _collapse_wl("白名单推导为空")
        if _ask_needed:
            _ask = {"o_count": o_count, "cmd_files": cmd_files,
                    "units": len(_units), "all_code": len(_all_code),
                    "cover": round(_cover * 100, 1)}
            say("  ⚠ 白名单可能不完整：产物 %d 个（.o %d / .cmd %d）→ "
                "推导出 %d 个源码单元；收录集内共 %d 个源码文件（%.1f%%）"
                % (o_count + cmd_files, o_count, cmd_files,
                   len(_units), len(_all_code), _cover * 100))
            if not _has_art:
                say("  · 未发现任何编译产物（.o/.cmd）——白名单无法推导，"
                    "建议按全量收源码")
            _choice = "full"
            if ask_tier is not None:
                say("  等待用户选择建库方式…")
                try:
                    _choice = ask_tier(_ask) or "full"
                except Exception as _e:
                    say("  ⚠ 建库方式选择失败（%s）——按全量收源码继续"
                        % str(_e)[:80])
                    _choice = "full"
                if _choice not in ("full", "whitelist", "reconfigure", "cancel"):
                    say("  ⚠ 未知选择 %r——按全量收源码继续" % (_choice,))
                    _choice = "full"
            if _choice == "cancel":
                raise Cancelled("cancel")
            if _choice == "reconfigure":
                raise Cancelled("reconfigure")
            if _choice == "full":
                say("  → 按「源码全量」收录（仅限非 off 区）")
                for r in all_rels:
                    if _st(r) != "off":
                        final_files.add(r)
                _units = set()
                # a570 对抗审计（P2·第十三轮）：降级后要同步口径——否则
                # 落盘的配置与 meta 仍标 whitelist，面板显示「白名单」而
                # 索引实际是全量，用户以为范围没被扩大。
                # a570 对抗审计（P1·第十五轮）：必须落成真正的 mode=full。
                # 原只把 mode 改成 manual + dirs 仍为 {} → 根默认是
                # whitelist，下次建库（配置已落盘、不再重写）会静默把范围
                # 收窄回白名单（实测 5 个 .c 收窄到 1 个）。
                # a570 对抗审计（P2·第十五轮）：**只**改根默认为 full，
                # 保留用户显式 dirs（否则 mixed 档的 tools:full 被冲掉）。
                sc["mode"] = "full"
                sc["name"] = _strip_dg(sc.get("name")) + "（自动降级为全量）"
                _all_full = True
            else:
                say("  → 按「仅白名单」收录（%d 个单元，其余源码不进索引）"
                    % len(_units))
            if _choice == "whitelist" and not _units:
                if not _all_code:
                    raise RuntimeError(
                        "收录集内没有任何 C/C++/汇编源码——请检查收录范围配置")
                raise RuntimeError(
                    "所选方式「仅白名单」推导出的源码单元为 0，无法建库。"
                    "请重新建库并选择「全量收源码」，或先编译工程")
        if _units:
            # -I 提取 + 递归 include 解析（a562 两处缺一不可，见定稿 §八）
            # a570 对抗审计（P1·第十四轮）：`-I` 里的相对路径要按「产物源
            # 根」与「源码根」解析——out-of-tree 构建的 .cmd 里写
            # `-Iarch/inc`（相对产物树根）或相对内核根。原实现只给 [root]，
            # G10 形态解析 0 个 -I（HEAD 版能解析 2 个），白名单区头文件漏收。
            # a570 对抗审计（P2·第十五轮）：顺序必须是「源码根 → 产物源根 →
            # 工程根」。产物源优先会把 `-Iarch/inc` 解析到产物树里的副本
            # （a453 已修过的镜像劫持），跳转指向副本而非真源码。
            _inc_bases = [p for p in _src_roots_abs if p != root]
            for _ap in _art_roots:
                _app = (os.path.join(root, *_ap.split("/")) if _ap else "")
                if _app and os.path.isdir(_app) and _app not in _inc_bases:
                    _inc_bases.append(_app)
            _inc_bases.append(root)
            _inc_dirs, _n_cmd = _extract_inc_dirs(
                cmd_abs, _inc_bases, should_cancel=should_cancel, say=say)
            say("  编译参数：从 %d 个 .cmd 提取 %d 个 -I 目录"
                % (_n_cmd, len(_inc_dirs)))
            if not _inc_dirs:
                _inc_dirs = []
                _pool = []
                _cand_dirs = set(all_dirs) | set(dirs_files)
                for _d in sorted(_cand_dirs):
                    if _d.rpartition("/")[2].lower() not in (
                            "inc", "include", "includes", "header", "headers"):
                        continue
                    _p = os.path.normpath(
                        os.path.join(root, _d.replace("/", os.sep)))
                    if os.path.isdir(_p) and _p not in _inc_dirs:
                        _pool.append(_p)
                if _pool:
                    _inc_dirs.extend(_pool)
                    say("  · 无构建描述：并入工程内 %d 个 inc/include 目录作 -I"
                        % len(_pool))
            _units_abs = [os.path.join(root, u.replace("/", os.sep))
                          for u in _units]
            _t0 = time.time()
            _reached = _resolve_includes(_units_abs, _inc_dirs,
                                         should_cancel=should_cancel, say=say)

            def _rel_of(p):
                try:
                    return os.path.relpath(p, root).replace(os.sep, "/")
                except ValueError:
                    return ""
            _reached_rel = {_rel_of(p) for p in _reached}
            _reached_rel.discard("")
            say("  递归 include：%d 个单元 → 触达 %d 个头文件（%.1fs）"
                % (len(_units), len(_reached_rel), time.time() - _t0))
            _same_h = set()
            _bt = _Beat(say)
            _i_u = 0
            for u in _units:
                _i_u += 1
                _bt.tick(_i_u, len(_units),
                         "  同目录头文件补收 %d/%d", _i_u, len(_units))
                ud = u.rpartition("/")[0]
                for fn2 in dirs_files.get(ud, ()):
                    if fn2.lower().endswith((".h", ".hpp", ".hh")):
                        _same_h.add((ud + "/" + fn2) if ud else fn2)
            final_files |= _units | _same_h | _reached_rel
            _n_fb = len(final_files) - len(_units | _same_h | _reached_rel
                                           | _full_files)
            say("  白名单清单：单元 %d · 同目录头 %d · 递归头 %d · 全量区 %d"
                " = 共 %d 文件"
                % (len(_units), len(_same_h), len(_reached_rel),
                   len(_full_files), len(final_files)))
            if not final_files:
                raise RuntimeError("收录清单为空——检查收录范围配置")
    # a415R2 WB#22b：最终 ctags 清单（点路径过滤后）**在写 manifest 前**
    # 拦截空清单——原 full 档空树走到阶段 2 才报错，manifest 已清空而
    # meta 未动 → status 误判 indexed。阶段 2 直接复用 _list_pool
    def _dot_path(rel):
        return any(seg.startswith(".") for seg in rel.split("/"))

    def _keep_in_list(rel):
        # a570 对抗审计（P2·第十二轮）：原实现把所有点路径段一律过滤，
        # 但十一轮起 full 档的 walk 会保留点目录（.libs 里的 .o 对白名单
        # 推导有价值）。于是「全量区 N 个代码文件」与最终清单对不上：
        # full 区的点目录源码被白收。这里让 full 区的点路径也进清单——
        # 口径统一（其余区域的点路径仍过滤，与旧行为一致）。
        if not _dot_path(rel):
            return True
        if _all_full:
            return True          # 降级/全量档：点路径也按全量收录
        return _has_full and _st(rel) == "full"

    # a434：final_files 是 set，直接写盘的话 files.txt 每次顺序都不同
    # （同一工程两次建库 diff 满是噪声，也妨碍「结果可复现」的验收）。
    _list_pool = sorted(r for r in (final_files if final_files is not None
                                    else all_rels) if _keep_in_list(r))
    if not _list_pool:
        # a570 对抗审计（P2·第十九轮）：v2 已无 include 字段，文案不能把
        # 用户引向不存在的配置项。这里按真实原因分类说明。
        # a570 对抗审计（P2·第二十轮）：原判据用 `all_rels`——但 off 目录在
        # scandir 层就被剪、根本不进 all_rels，于是「根设为不勾」这个最典型
        # 的原因永远判不到。改用**配置**判定：根显式 off 或所有显式节点
        # 都是 off（且无 live 节点）。
        _d0 = sc.get("dirs") or {}
        _root_off = _d0.get("") == "off"
        _no_live = not any(v in ("whitelist", "full") for v in _d0.values())
        if _root_off or (_no_live and bool(_d0)):
            raise RuntimeError(
                "收录清单为空：收录范围里没有可收录的子树（根或所有目录被"
                "设为「不勾」）——请在「选择目录…」里把根或某个子目录改回"
                "「白名单/全量」")
        raise RuntimeError(
            "收录清单为空——请检查收录范围（三态树配置或 exclude_names 排除名）")

    # a570：full_dirs = 显式 full 节点（不展开，查询期前缀匹配）。
    # 混合档下 full 目录的源没有 .o 记录，不加这档会被 in_build 降权，
    # 真定义输给白名单目录的同名符号（内网 §7.1 实测）。
    _full_dirs = [p for p, st in (sc.get("dirs") or {}).items()
                  if st == "full"]
    if _scope_root_default(sc) == "full":
        _full_dirs = []      # mode=full 时全树都是 full，写它无意义
    # a570 对抗审计（P2·第十五轮）：降级全量后 sc 已是 mode=full，上面两行
    # 自然得到空 full_dirs——查询期由 `_scope_root_default` 判 in_build，
    # 这正是想要的口径（含根直下文件，原「枚举顶层目录名」会漏掉它们）。
    mf = {"version": 1, "root": root, "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
          "compiled": compiled, "cmd_count": cmd_count, "o_count": o_count,
          "full_dirs": _full_dirs,
          # a570：全量档（含降级）→ 查询期一律 in_build=True
          "all_full": bool(_all_full or _scope_root_default(sc) == "full")}
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
    # a398 P0-3（报告 §2.3 实测：-R root 的 ctags 撞同一个 SMB 自链环，
    # test/sys 子树 300s 不结束）：改 -L 文件清单——范围控制只有 _walk_files
    # 一处（排除/环防护/收录规则单点），阶段 1 收录什么 ctags 就吃什么，
    # 不再出现「阶段 1 排除了、阶段 2 又收进来」。点文件跳过对齐旧
    # --exclude=.* 语义（a369R）
    listfile = os.path.join(ld, "files.txt")
    _n_list = 0
    # a398（审计#23）：点语义过滤已前移（manifest 前的 _list_pool）；此处
    # 只写清单。a415R2 N21：文件名含孤立代理字符时跳过该文件（原整库失败）
    say("  写 ctags 文件清单：%d 个文件…" % len(_list_pool))
    _bt = _Beat(say)
    with open(listfile, "w", encoding="utf-8") as _lf:
        for _ri, _rl in enumerate(_list_pool):
            _bt.tick(_ri + 1, len(_list_pool),
                     "  写文件清单 %d/%d", _ri + 1, len(_list_pool))
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
        raise RuntimeError(
            "收录清单为空——请检查收录范围（三态树配置或 exclude_names 排除名）")
    cmd = [_CTAGS_EXE, "--languages=" + NAV_LANGS,
           "--fields=+Kn", "--extras=+f",
           "-L", listfile, "-f", tags_tmp]
    # a361（用户实锤：30% 死等无文件进度）：大库 ctags 阶段数分钟只有一句
    # "ctags 索引"——心跳线程监控 tags.tmp 增长，每 3 秒报已写 MB，死等变
    # 活进度；ctags 完成后心跳自停
    # a395（用户实锤：取消后 ctags 阶段无法取消）：subprocess.run 阻塞期
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
        _lastsz = -1
        _stall = 0
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
            # a434：去掉超时上限后，ctags 若卡死必须仍有可见信号——
            # tags 连续 30s 不增长就报一次，用户至少知道卡在哪一步
            if sz == _lastsz:
                _stall += 1
                if _stall >= 30:
                    _stall = 0
                    say("  ctags 已 30s 无写入（%.1f MB）——仍在运行，可取消"
                        % sz)
            else:
                _lastsz = sz
                _stall = 0
    _hb = _th.Thread(target=_heartbeat, daemon=True)
    _hb.start()
    # a434：去掉 ctags 的 60 分钟硬上限（纯本地/网盘遍历耗时多久都可接受，
    # 超时反而丢掉整份索引）。取消由上面的心跳线程 kill 进程 → communicate
    # 立即返回。
    # a452（审计 P2）：「取消由心跳 kill」只在该函数传了 should_cancel 时成立
    # ——build() 是公共函数，脚本/测试直接调用时不传，心跳里的取消判断恒假，
    # communicate() 就再也无法被唤醒。这种调用形态下保留一个兜底超时。
    try:
        if should_cancel:
            out_b, _ = proc.communicate()
        else:
            out_b, _ = proc.communicate(timeout=7200)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
            proc.communicate()
        except Exception:
            pass
        raise RuntimeError("ctags 超时（2 小时，且调用方未提供取消能力）——目录过大？")
    finally:
        _hb_stop.set()
    # R15-3（实锤：取消被吞）：已取消则不落盘 tags/不写 meta（半成品库会被
    # status 误判 indexed）；a395 起取消在阻塞期内就杀进程，这里统一收尾
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
    say("  统计 tags 行数（%.1f MB）…"
        % (os.path.getsize(tags) / 1048576))
    with open(tags, encoding="utf-8", errors="replace") as f:
        for _ln in f:
            if not _ln.startswith("!"):   # a398（审计#22）： !_TAG_ 伪标签不计符号数
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
        # a343（用户实锤：build/_cython/routes.c 4.06M 恰超 4M 上限被
        # max-filesize 跳过——指纹头明明有 "Generated by Cython" 却漏进
        # 黑名单，引用混入 35 条生成文件命中）→ 32M。写盘带 scan_max 供
        # 旧库重扫判定（references 读到 scan_max 不一致即自动补扫）
        # a398：指纹扫描同走收录范围（原 -- root 在全树上
        # 白扫）；a398（审计#8）：排除规则同步成 rg -g；a415R2 N8/WB#8b：
        # rg 以 root 为 cwd + **相对路径**——-g '!x/**' 按 cwd 锚定，原先
        # 绝对路径参数下 exclude_paths 的 glob 永远匹配不上
        _rg_paths = ["."]
        _rg_g = ["-g", "!**/node_modules/**", "-g", "!**/.git/**"]
        if sc:
            # a570：v2 没有 exclude_paths。指纹扫描用「显式 off 节点」收窄
            # （树内更深处的 off 由后续使用侧忽略——只影响扫描范围精度）。
            for _p, _st in (sc.get("dirs") or {}).items():
                if _st == "off":
                    _rg_g += ["-g", "!%s/**" % _p]
            for en in sc["exclude_names"]:
                _rg_g += ["-g", "!**/%s/**" % en]
        say("  生成文件指纹扫描（rg）…")
        # a423（用户令：绝不让用户以为卡死）：原 subprocess.run 阻塞零输出
        # ——改 Popen + 1s 心跳计时，并把取消接进来
        # a426（用户质疑「为啥要限制时间？没必要吧」）：**去掉 300s 上限**。
        # 这是一个纯本地扫描，跑了多久都能接受；超时反而会静默丢掉整份
        # 生成文件黑名单（引用结果里混入生成代码）。只保留取消能力。
        _rg_cmd = [rgp, "-l", "--no-messages", "--no-ignore", "-F",
                   "--max-filesize", "32M", "--glob-case-insensitive",
                   "-g", "*.c", "-g", "*.cc", "-g", "*.cpp",
                   "-g", "*.h", "-g", "*.py"] + _rg_g \
            + sum([["-e", fp] for fp in fingerprints], []) \
            + ["--"] + _rg_paths
        _rg_proc = subprocess.Popen(
            _rg_cmd, cwd=root, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, creationflags=0x08000000,
            env={"LC_ALL": "C", **os.environ})
        _rt0 = time.time()
        _say_t = _rt0
        while True:
            try:
                _rout, _ = _rg_proc.communicate(timeout=1.0)
                break
            except subprocess.TimeoutExpired:
                if should_cancel and should_cancel():
                    try:
                        _rg_proc.kill()
                        _rg_proc.communicate()
                    except Exception:
                        pass
                    raise Cancelled()
                # a434：去掉超时上限后必须仍有可见进展——rg 在网盘上卡住
                # 时原先一行日志都没有（违「不许让用户觉得卡死」）。每 30s
                # 报一次仍在扫描，读秒本身交给前端独立计时器。
                if time.time() - _say_t >= 30.0:
                    _say_t = time.time()
                    say("  指纹扫描仍在进行（无输出阶段）——可取消")
        for pl in (_rout or b"").decode("utf-8", "replace").splitlines():
            if pl.strip():
                # a415R3 BUG-1：rg 以 root 为 cwd 后输出是相对路径，原样
                # normcase 进 gen_files.json → references 消费端拿绝对路径
                # 比对永远 miss=生成文件命中全部漏滤。写端归一成绝对路径
                _gp = pl.strip()
                if not os.path.isabs(_gp):
                    _gp = os.path.join(root, _gp)
                _gen.add(os.path.normcase(os.path.normpath(_gp)))
    except Cancelled:
        # a452（审计 P1）：取消必须穿透——原先 Cancelled 继承 Exception，被下面
        # 的兜底 `except Exception` 当成「rg 失败」吞掉，流程继续往下；工程没有
        # .o 时（阶段 3 唯一的取消点整段跳过）最终还会写 meta 报「✓ 索引完成」，
        # 用户点了取消却拿到一份成功索引。
        raise
    except Exception:
        _gen = set()
    _write_json(os.path.join(ld, "gen_files.json"),
                {"generated": sorted(_gen), "scan_max": _GEN_SCAN_MAX})
    if _gen:
        say("  生成文件黑名单：%d 个（Cython/lex/protobuf 等指纹）" % len(_gen))

    # ---- 阶段 3：ELF 符号表（a427：自研解析，无第三方依赖）----
    say("阶段 3/4：读取 .o 符号表（符号级消歧）…")
    prog(78, "符号表")
    symbols = {}
    # a427：原 `import elftools` 探测已删除——打包版只装了顶层包、子模块
    # 缺失，探测通过但真用必崩（11020/11020 全失败实锤）。改纯 struct 解析。
    # a369（用户实锤：阶段 3 没有过程显示）：白名单→.o 映射构建按文件数
    # 报进度——大库数千条可见推进；无 .o 时显式两步文案（不再是两行秒过）
    o_rel_to_src = {}
    _mi, _mt = 0, len(compiled)
    say("  构建白名单→.o 映射：%d 项…" % _mt)
    _bt = _Beat(say)
    # a434：compiled 的插入顺序取决于并发扫描（.cmd 阶段）与排序后的 .o
    # 阶段混合，不稳定。同一 .o 被多个源映射时（增量/并存产物），下面的
    # 反向表是「后写覆盖」——必须按确定顺序遍历，否则同一工程两次建库
    # 的符号归因源不同。排序遍历固定胜者。
    for srel, info in sorted(compiled.items()):
        o_rel_to_src[info["o"]] = srel
        _mi += 1
        _bt.tick(_mi, _mt, "  白名单映射 %d/%d", _mi, _mt)
        if _mt and _mi % 500 == 0:
            prog(78 + 2 * _mi / max(1, _mt), "白名单映射 %d/%d" % (_mi, _mt))
    if not o_files:
        say("  编译产物核对：白名单 %d 项，本工程无 .o——符号级消歧不适用" % _mt)
        say("  （跳转按 启发式排序：本文件 static > 编译白名单 > 路径深度）")
    else:
        say("  符号表候选 .o：%d 个（白名单 %d 项）" % (len(o_files), _mt))
    if o_files:
        done = 0
        used = 0
        _err_kinds = {}     # a426：异常类型 → 次数（原全静默，0 符号无从查）
        _err_first = []     # 首次样本消息（限 3 条）
        _bt = _Beat(say)
        for orel in o_files:
            if should_cancel and should_cancel():
                raise Cancelled()
            done += 1
            _bt.tick(done, len(o_files),
                     "  读符号表 %d/%d（符号 %d）", done, len(o_files),
                     len(symbols))
            if done % 100 == 0:
                prog(78 + 20 * done / max(1, len(o_files)), "符号表 %d/%d" % (done, len(o_files)))
            o_abs = os.path.join(root, orel.replace("/", os.sep))
            try:
                names = _read_symbols_from_o(o_abs)
            except Exception as _e:
                # a426（用户实锤：11020 个 .o 读出来 0 符号，日志只报
                # 「符号表：0 符号 / 0 个 .o」，异常被 continue 吞光）：
                # 分类统计 + 保留首样本，让失败原因可诊断
                _k = "%s: %s" % (type(_e).__name__, str(_e)[:80])
                _err_kinds[_k] = _err_kinds.get(_k, 0) + 1
                if len(_err_first) < 3:
                    _err_first.append("%s → %s" % (orel, _k))
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
        if _err_kinds:
            _n_err = sum(_err_kinds.values())
            say("  ⚠ %d/%d 个 .o 读取失败——符号级消歧对它们不生效："
                % (_n_err, len(o_files)))
            for _k, _c in sorted(_err_kinds.items(), key=lambda x: -x[1])[:5]:
                say("     × %d 次  %s" % (_c, _k))
            for _s in _err_first:
                say("     样本：%s" % _s)
    # a434：符号 → 源文件列表在查询侧可能被当作「候选顺序」直接使用，
    # 落盘前排序保证两次建库的 symbols.json 完全一致（o_files 已排序，
    # 这里再兜一层，防止将来有人改动上游遍历顺序）
    _write_json(os.path.join(ld, "symbols.json"),
                {"version": 1,
                 "symbols": {k: sorted(v) for k, v in symbols.items()}})

    # ---- 阶段 4：sqlite 快查索引（a369 三档后端；auto 按符号数判档）----
    # ctags-mem-v2 实测：600 万符号全量 dict ≈ 8GB 常驻；sqlite 0~4ms/50MB
    _bk_user = (backend or "auto").strip().lower()
    # a393（用户令：不允许全量方案）：memory 入参一律按 auto 重判
    # （api 层已显式拒，这里防御旧调用方）；只留 readtags/sqlite 两档
    if _bk_user == "memory":
        _bk_user = "auto"
    if _bk_user not in ("auto", "readtags", "sqlite"):
        _bk_user = "auto"
    _was_auto = _bk_user == "auto"
    if _was_auto:
        # a390：无 sqlite3 能力（旧版 exe 打包缺件）大库自动 readtags——
        # 不出现吓人的"构建失败"字样（readtags 查询速度相近，实测不慢）
        # a393：全量方案下线——小库也走 readtags（零建库成本，查询同级）
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
            # a570：收录范围随库记录（v2 三态树）。scope=None 时不写该键，
            # status 读旧 meta 无扰动。
            **({"scope": {"version": 2, "name": sc["name"],
                          "mode": sc["mode"], "source": sc_src,
                          # a570 对抗审计（P2·第十八轮）：arch 必须随 meta
                          # 下发——nav_api 用 meta.scope 作为落盘源，缺 arch
                          # 会静默回落 auto（实测 arch:"arm64" 被改写）。
                          "arch": sc.get("arch") or "auto",
                          "dirs": sc["dirs"],
                          "artifact_roots": sc["artifact_roots"],
                          "exclude_names": sc["exclude_names"],
                          # a570 对抗审计（P1·第十一轮）：把被放弃的超时
                          # 子树随 meta 下发——面板据此显示「本次建库 N 个
                          # 子树超时未收录」，而不是静默成功。
                          "timeout_items": _tos}}
               if sc else {}),
            "sizes": {"tags": os.path.getsize(tags) if os.path.isfile(tags) else 0,
                      "manifest": os.path.getsize(os.path.join(ld, "manifest.json")),
                      "symbols": os.path.getsize(os.path.join(ld, "symbols.json")),
                      **({"files_list": os.path.getsize(listfile)}
                         if os.path.isfile(listfile) else {}),
                      **({"db": os.path.getsize(db_path)} if os.path.isfile(db_path) else {})}}
    _write_json(os.path.join(ld, "meta.json"), meta)
    # a570 对抗审计（P2·第十二轮）：日志里承诺「建库成功后写回 v2 到工程根」，
    # 但 build 内部从未调用 save_scope（只有 nav_api 在「前端显式传 scope」
    # 时才写）。脚本/后端直调 build 的用户永远停在 v1 上、每次建库都重复告警。
    # 这里补上：本次用的是 detect/implicit/推荐 产物时，建库成功后写回。
    if sc_src in ("detect", "implicit") or sc_src == "recommended":
        try:
            # a570：mode=full 与显式 dirs 不能共存（_norm_scope_v2 拒绝）。
            # 降级时若用户已有显式节点，落盘改用 manual 并**把非显式区补成
            # full**，这样读回时语义与本次建库完全一致（根默认 full 表达
            # 不了，就显式写出来）。
            _sp = dict(sc)
            if _sp.get("mode") == "full" and (_sp.get("dirs") or {}):
                _d2 = dict(_sp.get("dirs") or {})
                # a570 对抗审计（P2·第十六轮）：补键必须 lower 归一——dirs
                # 的键一律 lower，磁盘真实大小写（`Kernel`）会与之并存，
                # 落盘后 `_norm_dirs` 逐条 lower，后写者覆盖前者，把用户的
                # `kernel: off` 翻成 full。
                _known_l = {k.lower() for k in _d2}
                # a684-A2：只补顶层目录（_top_dirs_of 已排掉根直下文件）
                for _r0 in sorted(_top_dirs_of(all_rels)):
                    if _r0 not in _known_l:
                        _d2[_r0] = "full"
                _sp["mode"] = "manual"
                _sp["dirs"] = _d2
            _sv_ok, _sv_err = save_scope(root, _sp)
            if _sv_ok:
                say("  · 收录范围已写入工程根 %s（v2）" % SCOPE_FILE)
            else:
                say("  ⚠ 收录范围未能写入工程根（%s）——下次建库需重新配置"
                    % _sv_err)
        except Exception as _e:
            say("  ⚠ 收录范围写入工程根异常（%s）" % str(_e)[:80])
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


# ================= a369：三档查询后端（ctags-mem-v2 §4）=================
# memory：全量 dict（小库 <20 万符号，现状路径）
# readtags：readtags.exe 二分查找（零建库，~0.2s/次，~10MB）
# sqlite：tags.db 快查（0~4ms，~50MB，建库 ~38s/600 万行）


_sqlite_capable = None


def sqlite_capable():
    """运行环境是否带 sqlite3（a390 用户实锤：exe 打包漏件——excludes
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
                        file_scope = 1   # a414：文件内可见标记（原先丢弃）
                    elif not kind and seg and ":" not in seg and seg != "file":
                        kind = seg   # --fields=+Kn 裸值 kind
                rows.append((name, path, lineno, kind, file_scope))
                n += 1
                if len(rows) >= 20000:
                    con.executemany("INSERT INTO t VALUES(?,?,?,?,?)", rows)
                    rows = []
                    say("  sqlite 导入：%d 行（共 %d 行 tags）…" % (n, total_lines))
                    prog(80 + 14.0 * n / max(1, total_lines),
                         "sqlite 导入 %d 行" % n)
        if rows:
            con.executemany("INSERT INTO t VALUES(?,?,?,?,?)", rows)
        con.commit()
        if prog:
            prog(96, "sqlite 建索引")
        say("  建索引 1/3：name（%d 行，大库需数分钟）…" % n)
        con.execute("CREATE INDEX idx_name ON t(name)")
        say("  建索引 2/3：path…")
        con.execute("CREATE INDEX idx_path ON t(path)")
        say("  建索引 3/3：lower(name)…")
        con.execute("CREATE INDEX idx_lower ON t(lower(name))")   # R35-1：不敏感前缀/子串
        con.commit()
        say("  索引建完：%d 行" % n)
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
                file_scope = 1   # a414：文件内可见标记（原先丢弃）
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
        # a393：全量方案下线——auto 小库也走 readtags。旧库显式
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
                        file_scope = 1   # a414：文件内可见标记
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
    # a570：混合档下 full 目录的源没有 .o 记录，需按前缀判定（manifest
    # 由建库期写入，旧库无该字段 → 空列表，行为等价于现状）
    full_dirs = mf.get("full_dirs") or []
    # a570 对抗审计（P2·第十五轮）：降级/全量档下 full_dirs 是空的，
    # 但全树都算 in_build——用 manifest 的 all_full 标志补上。
    _allf = bool(mf.get("all_full"))
    root = lib["root"]
    qlow = (q or "").strip().lower()
    # a383（Ctrl+Shift+O 文件内符号）：scope=file 精确到本文件，空查询给
    # 全量（按行号排——文件大纲语义），有 q 时子串过滤
    if kwargs.get("scope") == "file":
        # a369：三档后端统一 by_path（sqlite 走 idx_path 毫秒级——
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
                    # a570：full 目录的源也是「确定的源码」，与白名单同级
                    base_ok = _allf or (rel in compiled) \
                        or _under_any(rel, full_dirs)
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
    # a369：tags 收录域改后端 files()（sqlite DISTINCT 毫秒级；memory 档
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
    # R28-3（旧库无 gen_files.json 垃圾回涌）+ a343（旧库 scan_max 是旧上限
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
    # 定义行集合（排除）——a342：definition 候选已镜像去重，但引用结果过滤
    # 需要未去重的全 def 行（dist 镜像 def 在 15 行、src 在 15 行，行号不同——
    # deflines 用去重后集合会漏排镜像 def）。all_deflines 是 (path, line) 元组
    dres = definition(file_path, symbol)
    deflines = {(os.path.normcase(p), ln)
                for p, ln in (dres.get("all_deflines") or [])}
    mf = _load_json_cached(ld, "manifest.json", _manifest_cache)
    compiled = mf.get("compiled") or {}
    full_dirs = mf.get("full_dirs") or []   # a570：混合档 full 区
    _allf = bool(mf.get("all_full"))
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
                in_build = _allf or (rel in compiled) or _under_any(rel, full_dirs)
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
    # a369（真机实锤：R1 成功后全接口灭）：此处不得 close——_TagDB 连接由
    # _tagdb_cache 生命周期管理（换库时关旧），查询方关共享连接=后续全灭
    cands = _be.lookup(symbol)
    if not cands:
        # 大小写不敏感重试（返回 (name,path,line,kind)——取后三列）
        for _r in _be.lookup_ci(symbol):
            cands.append((_r[1], _r[2], _r[3], _r[4] if len(_r) > 4 else 0))
    mf = _load_json_cached(ld, "manifest.json", _manifest_cache)
    compiled = mf.get("compiled") or {}
    full_dirs = mf.get("full_dirs") or []   # a570：混合档 full 区
    _allf = bool(mf.get("all_full"))
    syms = _load_json_cached(ld, "symbols.json", _symbols_cache).get("symbols") or {}
    root = lib["root"]

    # 决策链 0：nm 符号锁定 (a570 语义修正，定稿 §九)。
    # `len(nm_srcs) == 1` 的含义是「只有一个 .o 编译了该符号」，
    # **不等于**「源码里只定义了一次」。原实现直接据此全局锁定，
    # 导致短符号（flags/mode/start）从任何文件点击都被拽到 nm 源——
    # H8 实测 4728 个符号误伤、H11 1367 个。
    # 修正：先算 nm_cand，建完 out 后**仅在 out 只剩它一个候选时**才锁定。
    nm_cand = None
    nm_srcs = syms.get(symbol)
    if nm_srcs and len(nm_srcs) == 1:
        nm_cand = nm_srcs[0]

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
        # a414 修复 A（内网报告 a419 缺陷一）：ctags file: 标记=该符号仅本
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
                in_build = _allf or (rel in compiled) or _under_any(rel, full_dirs)
                break
        if in_build is None:
            in_build = None     # 头文件/脚本：编译单元判定不适用
        out.append({
            "path": os.path.join(root, rel.replace("/", os.sep)),
            "rel": rel, "line": lineno, "kind": kind,
            "in_build": in_build,
            "dist": _common_depth(file_path, os.path.join(root, rel.replace("/", os.sep))),
            "file_local": os.path.normcase(os.path.abspath(os.path.join(root, rel.replace("/", os.sep)))) == os.path.normcase(os.path.abspath(file_path)),
            # a570：字段必须保留（rank() 读它，删了会 KeyError），值先置
            # False，建完 out 后按「只有它一个候选」回填
            "nm_lock": False,
        })

    # a570：nm_lock 回填——**严格 == 1 且就是 nm 源**才算锁定。
    # 用过滤后的 out 而不是原始 cands：cands 可能含 a414 已剔除的
    # file-scope 候选，用它会误判（外网方案乙，内网实测三场景全对）。
    if nm_cand and len(out) == 1 and out[0]["rel"] == nm_cand:
        out[0]["nm_lock"] = True

    # a414 修复 B+C-2（内网报告 a419 缺陷二）：排序加两档——
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
    # a369R：定义候选镜像去重（引用侧 a340 同款）——dist 类发布镜像是
    # 源码完整拷贝，同名同 kind 的镜像副本让 F12 弹 N 个"多候选"实际是
    # 同一符号。按 basename+kind 去重保留排序最前者（源码本体近镜像远）。
    # a342：去重前的全部 def 行以 all_deflines 透出——references 的
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
