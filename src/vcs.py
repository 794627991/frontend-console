# -*- coding: utf-8 -*-
"""版本控制 API（Flask Blueprint）——git / svn 工作副本查看与常用写操作。

范围（用户拍板）：只读查看（类型识别/分支修订/改动列表/单文件 diff/最近
提交）+ 常用写（add / commit 自填说明 / git pull --ff-only / svn update）。
明确不含 push、还原/丢弃改动、冲突解决——分叉/冲突时干净失败并引导去
命令行，绝不留半合并态。

安全模型（沿 file_tree.py 根目录登记制）：所有路径必须落在文件树已登记
根的子树内（_under_roots 门卫）；仓库根解析出登记根之外 → 拒绝并引导。
argv 一律 list（无 shell 拼接）；git 路径参数带 `--` 分隔符。

编码：git 输出 UTF-8（-c core.quotepath=false）→ GBK（svn 人类可读输出在
中文 Windows 是 ACP）→ utf-8 replace 三跳；svn 结构化数据走 --xml（恒
UTF-8）从根上免猜。subprocess 禁 text=True（默认按 locale 解，跨机不稳）。
"""
import hashlib
import os
import re
import shutil
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from src import app_state as _st
from src.file_tree import _under_roots, _under_roots_or_projects

vcs_bp = Blueprint("vcs", __name__)

CREATE_NO_WINDOW = 0x08000000
VCS_TIMEOUT_RO = 20
# v3.5.264（SVN三问题报告 Q1）：全树 status 移出 status 端点关键路径——
# 网络盘大仓库（SMB+内核树）实测 54s+，独立 changes 端点配长超时 ≥90s
VCS_TIMEOUT_CHG = 90     # status/log/diff/show/cat
VCS_TIMEOUT_RW = 60     # add/commit
VCS_TIMEOUT_NET = 120   # pull/update
FILES_CAP = 500         # 改动列表上限（对齐 file_tree LIST_CAP 文化）
_LOG_CAP = 500         # v2：单次 log 上限（翻页/回补一次拿够）
_SKIP_CAP = 5000       # v2：skip+limit 累积深度上限（巨仓深翻脚注引导命令行）
_TMP_KEEP_S = 24 * 3600
_TMP_MAX = 60

_ROOT_LOCKS = {}
_ROOT_LOCKS_GUARD = threading.Lock()


def _root_lock(wc_dir):
    """每个工作副本一把写锁——同仓 commit/update 串行，跨仓互不阻塞。
    键 normcase 归一（轻审 P9：Windows 同仓异形态防两把锁）。"""
    with _ROOT_LOCKS_GUARD:
        return _ROOT_LOCKS.setdefault(os.path.normcase(wc_dir), threading.Lock())


_LAST_REMOTE_ERR = {}        # root(normcase) -> (ts, msg)；status 端点透给 UI
_REMOTE_ERR_TTL = 300        # 5 分钟内的回退原因保持可见，之后自动消失
_REMOTE_CUR = threading.local()   # 每请求线程正在处理的工程根（防并发串扰）


def _set_remote_err(e):
    """记录一次远端回退原因，供 status/changes 端点透给 UI。"""
    try:
        r = getattr(_REMOTE_CUR, "root", None)
        if r:
            _LAST_REMOTE_ERR[os.path.normcase(r)] = (time.time(), str(e)[:200])
    except Exception:
        pass


def _remote_ctx(cwd):
    """判断 cwd 是否该走 SSH 远端。

    只为**网络盘上的工程根**启用（纯 Windows 本地盘一次 stat 是微秒级，
    走 SSH 反而多一跳网络）。返回 entry 或 None。

    a455：优先用 _guard 记下的请求根；但该值是线程局部，Flask 的工作线程
    会被复用——上一次请求的 root 会残留到下一次。所以只有「cwd 确实落在
    那个 root 下」时才采信，否则以 cwd 自己为准（就地判断网络盘）。"""
    try:
        from src import vcs_remote
    except Exception:
        return None
    root = getattr(_REMOTE_CUR, "root", None) or ""
    if root:
        nr = os.path.normcase(os.path.normpath(str(root)))
        nc = os.path.normcase(os.path.normpath(str(cwd)))
        if not (nc == nr or nc.startswith(nr + os.sep)):
            root = ""          # 残留的旧 root，与本次 cwd 无关——丢弃
    if not root:
        root = cwd
    try:
        entry = vcs_remote.get_for_root(root)
        if not entry and root != cwd:
            entry = vcs_remote.get_for_root(cwd)
            if entry:
                root = cwd
    except Exception:
        return None
    if not entry:
        return None
    # 三路审计 B-F02/C-F7：回退窗口期（hint TTL 5 分钟内）直接按本地处理。
    # 原判定不查 hint——配置在而远端失联时，_run 每条命令都先吃一次 SSH
    # 连接超时再回退，且 depth/超时/符号链接过滤按「远端」口径选择，shallow
    # 一段退化成本地全树扫、前端还要二段再扫一遍（实测 2×47s）。在单点
    # 对齐后，_svn_changes 的三处判定与 _run/_run_bytes 的分流自动回本地
    # 语义（分层加载、SMB 符号链接补偿全部照旧生效）。恢复路径：hint 到期
    # 或「测试连接」成功清除。
    if _remote_hint(root):
        return None
    try:
        if not _is_network_drive(root):
            return None
    except Exception:
        return None
    _REMOTE_CUR.root = root
    return entry


def _remote_hint(root):
    """给 UI 的回退提示（有则返回 (msg, ts)，否则 None）。"""
    v = _LAST_REMOTE_ERR.get(os.path.normcase(str(root or "")))
    if not v:
        return None
    if time.time() - v[0] > _REMOTE_ERR_TTL:
        _LAST_REMOTE_ERR.pop(os.path.normcase(str(root or "")), None)
        return None
    return v[1]


def _clear_remote_err(root):
    _LAST_REMOTE_ERR.pop(os.path.normcase(str(root or "")), None)


def _mirror_effective(root):
    """该工程当前**实际**走的执行模式：'ssh' | 'smb' | 'local'。

    注意与「配置了」不同——配置了但连接失败会回退本地，此处如实反映回退后
    的真实状态，前端顶部据此显示「SSH 加速」还是「本地（已回退）」。"""
    try:
        from src import vcs_remote
    except Exception:
        return "local"
    try:
        entry = vcs_remote.get_for_root(root)
    except Exception:
        entry = None
    if not entry:
        try:
            return "smb" if _is_network_drive(root) else "local"
        except Exception:
            return "local"
    if _remote_hint(root):
        return "smb"          # 配了但刚回退过
    try:
        return "ssh" if _is_network_drive(root) else "local"
    except Exception:
        return "local"


def _data_dir():
    """运行时取 app_state.DATA_DIR（v3.5.118，轻审 P4：from-import 是值
    拷贝，数据目录迁移端点回写 _st.DATA_DIR 后这里仍指旧目录——vcs_tmp
    会落已删除的旧位置并复活目录。函数内查 _st 属性根治，测试同受益）。"""
    d = _st.DATA_DIR
    os.makedirs(d, exist_ok=True)
    return d


def _dec(b):
    """命令输出解码三跳：utf-8 严格 → GBK 严格 → utf-8 replace。"""
    for enc in ("utf-8", "gbk"):
        try:
            return b.decode(enc)
        except (UnicodeDecodeError, LookupError):
            pass
    return b.decode("utf-8", "replace")


def _remote_used_now(cwd):
    """本次调用**实际**是否走了 SSH 远端（threading.local 单次标记）。

    a456（第三轮审计 P2）：原来 _svn_changes 用 `_remote_ctx(...) and not
    _remote_hint(...)` 推「这次走了远端」——但 hint 只在失败时写、成功从不清
    (TTL 300s)。网络盘工程某次远端抖动后 5 分钟内 SSH 已恢复、`_run` 明明
    走的是远端，判据仍说「本地」，于是对**远端结果**套用 SMB 符号链接误报
    过滤，把真实的链改动当误报隐藏。现在由 _run 自己记真实路径。
    """
    try:
        return bool(getattr(_REMOTE_CUR, "used", False))
    except Exception:
        return False


def _run(argv, cwd, timeout):
    """subprocess 统一入口：list argv / bytes 输出 / 隐藏窗口 / 超时保护。
    返回 (rc, out_str, err_str)——超时转 rc=-1 + err 文案。

    a455：网络盘工程若配了 SSH 远端，改为在构建机上执行（SMB 上每次 stat
    都是网络往返，全树 status 实测 47.9s vs 远端 1.1s）。远端不可达/未配置
    → 静默回退本地，版本面板绝不因远端故障不可用。"""
    try:
        _REMOTE_CUR.used = False      # a456：每次调用重置，由本函数如实置位
    except Exception:
        pass
    r = _remote_ctx(cwd)
    if r is not None:
        try:
            from src import vcs_remote
            entry = r
            rc, raw, e = vcs_remote.run(entry, argv, cwd, timeout)
            try:
                _REMOTE_CUR.used = True
            except Exception:
                pass
            return rc, _dec(raw), e
        except Exception as _e:
            # 回退本地：把原因记进 _LAST_REMOTE_ERR，status 端点透给 UI 提示
            _set_remote_err(_e)
    return _run_local(argv, cwd, timeout)


def _run_local(argv, cwd, timeout):
    """本地 subprocess 执行（原 _run 实现，逐字保留）。"""
    try:
        # B组P7：git/svn 子进程强制 C locale——shortstat 解析按英文
        # 「N insertions/deletions」配对，zh_CN gettext 下徽章会整体消失
        import subprocess as _sp
        _env = dict(os.environ, LC_ALL="C", LANG="C")
        p = subprocess.run([str(a) for a in argv], cwd=cwd,
                           capture_output=True, timeout=timeout,
                           env=_env, creationflags=CREATE_NO_WINDOW)
        return p.returncode, _dec(p.stdout), _dec(p.stderr)
    except subprocess.TimeoutExpired:
        return -1, "", "命令超时（%ds）——仓库过大或命令行假死" % timeout
    except FileNotFoundError:
        return -1, "", "命令不存在"
    except Exception as e:
        return -1, "", str(e)


def _tool(name):
    """CLI 探测：None = 未安装（调用方呈现「未安装」占位，绝不抛错）。"""
    return shutil.which(name)


def _tmp_materialize(data, name_hint):
    """把旧版本字节物化成临时文件，供 buildDiffViewerTab 走真实路径打开。
    命名 <sha1 短前缀>_<hint>；顺带清理 >24h 或总数 >60 的旧件。"""
    d = os.path.join(_data_dir(), "vcs_tmp")
    os.makedirs(d, exist_ok=True)
    now = time.time()
    try:
        olds = sorted((os.path.join(d, f) for f in os.listdir(d)),
                      key=lambda p: os.path.getmtime(p))
        stale = [p for p in olds if now - os.path.getmtime(p) > _TMP_KEEP_S]
        for p in stale:
            try:
                os.remove(p)
            except OSError:
                pass
        keep = [p for p in olds if p not in stale]
        for p in keep[:max(0, len(keep) - _TMP_MAX)]:
            try:
                os.remove(p)
            except OSError:
                pass
    except OSError:
        pass
    h = hashlib.sha1(data).hexdigest()[:10] if data else "empty"
    safe = re.sub(r"[^0-9A-Za-z._@\[\]-]", "_", name_hint or "file")
    path = os.path.join(d, "%s_%s" % (h, safe))
    with open(path, "wb") as f:
        f.write(data)
    return path


def _is_git_wc(d):
    """有效 git 工作副本判定（vcs-report 问题1：空 .git 残留目录曾被
    exists() 误判成 git 仓库——.svn 检查永远轮不到，g10_trunk 实锤）。
    .git 是文件（worktree/submodule）看 gitdir: 前缀；是目录看 HEAD+objects"""
    g = os.path.join(d, ".git")
    if os.path.isfile(g):
        try:
            with open(g, encoding="utf-8", errors="replace") as f:
                return f.read(16).startswith("gitdir:")
        except OSError:
            return False
    return (os.path.isdir(g)
            and os.path.exists(os.path.join(g, "HEAD"))
            and os.path.isdir(os.path.join(g, "objects")))


def _is_svn_wc(d):
    """有效 svn 1.7+ 工作副本判定（.svn/wc.db 存在）"""
    s_ = os.path.join(d, ".svn")
    return os.path.isdir(s_) and os.path.exists(os.path.join(s_, "wc.db"))


def _is_network_drive(path):
    """网络盘判定（vcs-report 问题2/3：SMB 盘展开 Unix 符号链接成实体
    文件——svn 报海量 M/~/! 误报）。DRIVE_REMOTE=4"""
    try:
        import ctypes
        drive = os.path.splitdrive(os.path.abspath(path))[0]
        if not drive:
            return False
        # R34-1（实锤：UNC 路径恒 False——同一 SMB 仓库映射盘符享受误报
        # 过滤、\\server\share 形态打开全回涌）。实测本机 GetDriveTypeW 对
        # UNC share 根返回 1（NO_ROOT_DIR，直连未认证）而映射盘符返 4——
        # API 对 UNC 靠不住。UNC 形态天然是网络路径直接判 True；盘符走
        # GetDriveTypeW（DRIVE_REMOTE=4）
        if drive.startswith("\\\\"):
            return True
        return ctypes.windll.kernel32.GetDriveTypeW(drive + "\\") == 4
    except Exception:
        return False


def _svn_symlink_paths(wc):
    """svn 1.7+ 符号链接全量清单（一次 SQL，零进程创建）：NODES 表
    svn:special 属性即符号链接（pristine 内容 'link <target>'）。
    只读 URI 连接不锁库；SQLITE_BUSY（svn 正写）→ 空集=不过滤（安全侧）"""
    db = os.path.join(wc, ".svn", "wc.db")
    if not os.path.isfile(db):
        return set()
    try:
        import sqlite3
        from urllib.parse import quote
        _uri = quote(db.replace("\\", "/"))
        con = sqlite3.connect("file:%s?mode=ro" % _uri,
                              uri=True, timeout=3)
        try:
            rows = con.execute(
                "SELECT local_relpath FROM NODES "
                "WHERE op_depth=0 AND properties LIKE '%svn:special%'").fetchall()
            return set(r[0].replace("\\", "/") for r in rows if r and r[0])
        finally:
            con.close()
    except Exception:
        return set()


def _wc_root(path):
    """解析 path 所属工作副本。返回 (vcs, wc_dir, err)：
    - vcs ∈ {'git','svn'}，wc_dir 为仓库根绝对路径（登记根子树内）
    - vcs=None：err 带原因（不在登记根内 / 非版本控制目录 / 仓库根越界）"""
    p = _under_roots_or_projects(path)
    if not p:
        return None, None, ("路径不在文件树已登记目录内，也不是已打开的工程"
                            "——请先在左侧文件树打开该工程目录")
    cur = p
    for _ in range(8):                      # 向上最多 8 跳找标记
        if _is_git_wc(cur):                 # vcs-report 问题1：结构验证（空 .git 残留不再误判）
            return "git", cur, None
        if _is_svn_wc(cur):
            return "svn", cur, None
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    # 目录树标记没找到（如 bare 布局/极深嵌套）再借命令确认一次
    for vcs, argv in (("git", ["git", "rev-parse", "--show-toplevel"]),
                      ("svn", ["svn", "info", "--xml", p])):
        if _tool(vcs):
            # 三路审计 B-F06：仓库根探测问的是**本地路径**的归属，必须本地
            # 执行——走 _run 会被 SSH 分流，远端回传 /data1/... 被 abspath
            # 当成本地盘根路径，_under_roots_or_projects 不认 → 400 假「越界」。
            rc, out, _e = _run_local(argv, p, VCS_TIMEOUT_RO)
            if rc == 0:
                if vcs == "git":
                    cand = out.strip().splitlines()[0].strip() if out.strip() else None
                else:
                    m = re.search(r"<wcroot-abspath>(.+?)</wcroot-abspath>", out)
                    cand = m.group(1).strip() if m else None
                if cand:
                    cand = os.path.abspath(cand)
                    pc = _under_roots_or_projects(cand)
                    if pc and (cand == pc or cand.startswith(pc + os.sep)):
                        if _is_git_wc(cand):
                            return "git", cand, None
                        if _is_svn_wc(cand):
                            return "svn", cand, None
                    return None, None, "仓库根（%s）在文件树登记根之外——请把仓库根目录加入左侧文件树" % cand
    return None, None, "该目录不是 git / svn 工作副本"


def _guard(root, need_tool=None):
    """公共前置：解析工作副本 + 工具探测。返回 (vcs, wc, err_resp, tool)。
    err_resp 非 None 时调用方直接返回它。

    a455：顺带把本次请求的工程根写进线程局部，供 _run 判定走不走 SSH 远端。
    未配置/非网络盘时这里什么也不做，行为与改动前完全一致。"""
    _REMOTE_CUR.root = str(root or "")
    vcs, wc, err = _wc_root(root)
    if err:
        return None, None, (jsonify({"ok": False, "err": err}), 400), None
    tool = bool(_tool(vcs))
    if need_tool and not tool:
        # 三路审计 B-F03：SSH 生效时命令在构建机执行，不依赖本地 svn/git
        # 二进制——否则「log 无门卫能刷历史、commit/update 被 400 拒」行为
        # 割裂。回退窗口期 _remote_ctx 为 None，此时仍要求本地 CLI（自洽）。
        try:
            if _remote_ctx(wc) is None:
                return (None, None,
                        (jsonify({"ok": False,
                                  "err": "%s 客户端未安装——安装 %s 命令行"
                                         "并重启后可用" % (vcs, vcs)}), 400), False)
        except Exception:
            return (None, None,
                    (jsonify({"ok": False,
                              "err": "%s 客户端未安装——安装 %s 命令行"
                                     "并重启后可用" % (vcs, vcs)}), 400), False)
    return vcs, wc, None, tool


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

_GIT_ST_MAP = {"M": "M", "A": "A", "D": "D", "R": "R", "C": "C", "?": "?", "!": "!"}

# 性能批（VCS 面板卡顿）：status 结果 2s memo——激活时 /status 与 /changes
# 两端点同拍各跑一次一模一样的 `git status`（每条 0.3~0.5s 热态、冷态
# Defender 扫 git.exe 可秒级），同拍第二次直接复用。写操作（add/commit/
# update）即时失效防陈旧闪现。
_st_memo = {}
_ST_MEMO_TTL = 2.0


def _st_memo_inval(wc=None):
    if wc is None:
        _st_memo.clear()
    else:
        _st_memo.pop(wc, None)


def _git_status(wc):
    c = _st_memo.get(wc)
    if c and time.time() - c[0] < _ST_MEMO_TTL:
        return c[1]
    res_t = _git_status_run(wc)
    if len(_st_memo) > 32:
        _st_memo.clear()
    _st_memo[wc] = (time.time(), res_t)
    return res_t


def _git_status_run(wc):
    rc, out, err = _run(["git", "-c", "core.quotepath=false",
                         "status", "--porcelain=v1", "-z", "--branch"],
                        wc, VCS_TIMEOUT_RO)
    if rc != 0:
        return None, err or "git status 失败"
    branch, ahead, behind = "", 0, 0
    files = []
    toks = out.split("\0")
    it = iter(toks)
    for tok in it:
        if not tok:
            continue
        if tok.startswith("## "):
            head = tok[3:]
            m = re.match(r"(\S+?)\.\.\.\S+\s*\[(?:ahead (\d+))?[,\s]*(?:behind (\d+))?\]",
                         head)
            if m:
                branch = m.group(1)
                ahead, behind = int(m.group(2) or 0), int(m.group(3) or 0)
            elif head.startswith("No commits"):
                branch = re.sub(r"^No commits yet on ", "", head)
            else:
                branch = head.split("...")[0].strip() or head
            continue
        xy = tok[:2]
        st = _GIT_ST_MAP.get(xy[0] if xy[0] not in " M" else
                             (xy[1] if xy[1] != " " else xy[0]), "?")
        # v3.5.118（轻审 P5）：unmerged（UU/AU/DD 等）→ C 冲突态，绝不显示成
        # 「未纳管」给 ＋add 按钮（git add 强收冲突是破坏性误导）
        if "U" in xy:
            st = "C"
        rel = tok[3:]
        if xy[0] in "RC":                   # rename/copy: new\0old（轻审 P7：C 同消费）
            old_rel = next(it, "")
            files.append({"rel": rel.replace("\\", "/"), "path": rel,
                          "st": st, "old_rel": old_rel.replace("\\", "/")})
        else:
            files.append({"rel": rel.replace("\\", "/"), "path": rel, "st": st})
    rc, rev, _e = _run(["git", "rev-parse", "--short", "HEAD"], wc, 10)
    # a455：与 svn 同因——git status 也按路径字典序，未纳入版本控制的文件
    # （构建产物等）可能吃掉全部额度，把真实改动挤出列表。实质改动优先。
    _core = [f for f in files if f["st"] != "?"]
    _unv = [f for f in files if f["st"] == "?"]
    _core_kept = _core[:FILES_CAP]
    _room = FILES_CAP - len(_core_kept)
    _unv_kept = _unv[:_room] if _room > 0 else []
    _trunc_unv = max(0, len(_unv) - len(_unv_kept))
    return {"vcs": "git", "tool": True, "branch": branch, "rev": rev.strip(),
            "ahead": ahead, "behind": behind,
            "files": _core_kept + _unv_kept,
            "truncated": max(0, len(_core) - len(_core_kept)),
            **({"truncated_unv": _trunc_unv} if _trunc_unv else {})}, None


def _svn_info(wc):
    """v3.5.264（Q1 主修）：O(1) svn info——rev/branch 0.3s 级，status 端点
    只跑这个（全树 status 移出关键路径，见 /api/vcs/changes）。"""
    rc, out, err = _run(["svn", "info", "--xml"], wc, VCS_TIMEOUT_RO)
    rev, branch = "", ""
    if rc == 0:
        try:
            root = ET.fromstring(out.encode("utf-8"))
            e = root.find("entry")
            if e is not None:
                c = e.find("commit")
                rev = (c.get("revision") if c is not None else "") or ""
                u = e.findtext("url") or ""
                branch = u.rstrip("/").rsplit("/", 1)[-1]
        except ET.ParseError:
            pass
    return rev, branch


def _svn_changes(wc, depth=None):
    """v3.5.264（Q1 主修）：svn status 独立函数——配长超时，由
    /api/vcs/changes 单独调用（前端惰性加载），不再阻塞 status。
    v3.5.272b（报告 §6 分层加载）：depth='empty' 顶层模式（--depth empty
    实测 0.45s vs 全树 39~54s）——首屏秒出顶层改动，全树由前端二段补扫
    覆盖；超时 30s 对秒级余量充足。"""
    argv = ["svn", "status", "--xml"]
    # a455：走 SSH 远端时取消分层加载——分层是为绕开 SMB 全树 40~50s 的
    # 痛点，而远端全量只要 1~2s；照旧发 --depth empty 反而在 Linux 侧要全表
    # 扫 wc.db（实测 37s 且顶层恒空），比全量还慢。
    if depth and _remote_ctx(wc) is None:
        argv += ["--depth", depth]
    # a455：远端全量 1~2s，无需为分层单独缩短超时
    _to = 30 if (depth == "empty" and _remote_ctx(wc) is None) else VCS_TIMEOUT_CHG
    rc, out, err = _run(argv, wc, _to)
    if rc != 0:
        if "超时" in (err or ""):
            return {"files": [], "truncated": 0,
                    "changes_timeout": True, "shallow": bool(depth)}, None
        return None, err or "svn status 失败"
    files = []
    try:
        root = ET.fromstring(out.encode("utf-8"))
        for t in root.iter("target"):
            for e in t.iter("entry"):
                rel = e.get("path", "").replace("\\", "/")
                if not rel:
                    continue
                it = e.find("wc-status")
                if it is None:
                    continue
                st_raw = it.get("item", "none")
                st = {"modified": "M", "added": "A", "deleted": "D",
                      "unversioned": "?", "conflicted": "C",
                      "replaced": "R", "missing": "!", "none": ""}.get(st_raw)
                if not st:
                    continue
                old = (it.findtext("move-to") or "")
                files.append({"rel": rel, "path": rel, "st": st,
                              **({"old_rel": old} if old else {})})
    except ET.ParseError as e:
        return None, "svn status 输出解析失败：%s" % e
    # vcs-report 问题2/3（用户实锤：SMB 盘 218 条误报 vs Linux 9 条真实）：
    # SMB 默认把 Unix 符号链接展开成实体文件——svn 报 M（内容=链接定义 vs
    # 目标内容）；~/! 是类型变更/目标不可达。网络盘上按 wc.db 的 svn:special
    # 清单过滤（绝不静默：symlink_hidden 透出，前端提示）
    sym_hidden = 0
    # a456：走 SSH 远端时结果来自 Linux 侧——那里的符号链接是真实的，
    # 不该按 SMB 展开误报去过滤（否则会误删真实改动条目）。
    # 判据用**本次调用真实路径**（_run 置的线程局部标记），不用 hint——
    # hint 只在失败时写、成功不清，远端恢复后 5 分钟内仍会误判成「本地」。
    _use_remote = _remote_used_now(wc)
    if files and not _use_remote and _is_network_drive(wc):
        sym = _svn_symlink_paths(wc)
        sym_low = {x.lower() for x in sym}
        kept = []
        for f in files:
            # S37-4（P3）：! 不查清单无条件隐藏——真实删除文件（网络盘上同样
            # 报 !）被当误报吞掉（假阴性比假阳性危险）；~ 实际到不了（映射表
            # 无 obstructed），分支收进符号链接清单判定
            if f["st"] in ("!", "~") and (f["rel"] in sym or f["rel"].lower() in sym_low):
                sym_hidden += 1
                continue
            if f["st"] == "M" and (f["rel"] in sym or f["rel"].lower() in sym_low):
                sym_hidden += 1
                continue
            kept.append(f)
        files = kept
    truncated_unv = 0
    if files:
        # a455（实锤：G10 有 5 个真实 M 却显示「没有实质改动」）：svn status
        # 按路径字典序输出，未版本控制文件（编译产物）动辄数万个，把 500 条
        # 额度全吃掉——实质改动落在第几千位以后被截断，前端折叠 ? 后就只剩
        # 空白。截断前**分区**：实质改动优先，? 用剩余额度补。
        _core = [f for f in files if f["st"] != "?"]
        _unv = [f for f in files if f["st"] == "?"]
        _core_kept = _core[:FILES_CAP]
        _room = FILES_CAP - len(_core_kept)
        _unv_kept = _unv[:_room] if _room > 0 else []
        files = _core_kept + _unv_kept
        truncated = max(0, len(_core) - len(_core_kept))
        truncated_unv = max(0, len(_unv) - len(_unv_kept))
    else:
        truncated = 0
    return {"files": files[:FILES_CAP], "truncated": truncated,
            **({"truncated_unv": truncated_unv} if truncated_unv else {}),
            "shallow": bool(depth),
            # a455：远端模式下请求虽标了 shallow，实际做的是全量——前端据此
            # 跳过第二段补扫（否则同一份全量结果白拉两遍）
            **({"shallow_skipped": True} if (depth and _use_remote) else {}),
            **({"symlink_hidden": sym_hidden} if sym_hidden else {})}, None


def _svn_status(wc):
    """v3.5.267（全审收编）：组合 _svn_info + _svn_changes——原实现与
    _svn_changes 整段重复（解析块两份）。生产零调用者（status 端点已拆轻
    路径），保留仅为 tests/test_vcs.py 旧语义兼容。"""
    rev, branch = _svn_info(wc)
    chg, e = _svn_changes(wc)
    if e:
        return None, e
    d = {"vcs": "svn", "tool": True, "branch": branch, "rev": rev,
         "ahead": 0, "behind": 0}
    d.update(chg or {"files": [], "truncated": 0, "changes_timeout": True})
    return d, None


@vcs_bp.route("/api/vcs/status", methods=["POST"])
def vcs_status():
    data = request.get_json(force=True, silent=True) or {}
    vcs, wc, err, _tool_ok = _guard(data.get("root"))
    if err:
        return err
    # v3.5.118（轻审 P3）：「未安装 = tool:False 占位」设计内首态——status 是
    # 只读探测，未装 CLI 时返回 200 + 空 files，前端渲染占位而非报错。
    # 三路审计 B-F03：SSH 生效时执行在构建机、不依赖本地二进制——占位分支
    # 让路（否则「历史能刷、状态显示未安装」割裂；回退窗口期 _remote_ctx
    # 为 None，此时仍走占位，判定自洽）。
    if not _tool(vcs) and _remote_ctx(wc) is None:
        return jsonify({"ok": True, "vcs": vcs, "tool": False, "branch": "",
                        "rev": "", "ahead": 0, "behind": 0,
                        "files": [], "truncated": 0})
    # v3.5.264（Q1）：svn 走轻路径——只 svn info（0.3s 级），全树 status 移
    # 出关键路径（/api/vcs/changes 惰性加载）；files 空表+changes_pending 标
  # 记，前端显示「改动扫描中」占位。git 的 status 本身亚秒级，维持原样。
    # 三路审计 B-F07：hint/芯片按**实际工作根 wc** 取数——工程开在子目录时
    # 请求根 ≠ wc，按请求根查询会谎报 ssh/丢回退提示。
    if vcs == "svn":
        rev, branch = _svn_info(wc)
        give_miss = _remote_hint(wc)
        return jsonify({"ok": True, "vcs": "svn", "tool": True,
                        "branch": branch, "rev": rev, "ahead": 0, "behind": 0,
                        "files": [], "truncated": 0, "changes_pending": True,
                        "remote_used": _mirror_effective(wc),
                        **({"remote_hint": give_miss} if give_miss else {})})
    res, e = _git_status(wc)
    if e:
        return jsonify({"ok": False, "err": e}), 500
    _h = _remote_hint(wc)
    return jsonify({"ok": True, **res,
                    "remote_used": _mirror_effective(wc),
                    **({"remote_hint": _h} if _h else {})})


@vcs_bp.route("/api/vcs/changes", methods=["POST"])
def vcs_changes():
    """v3.5.264（Q1）：改动列表独立端点——svn 全树 status（长超时 90s）/
    git 复用 _git_status。前端版本 tab 激活/手动⟳/写操作后惰性调用，
    不再拖垮 status 关键路径与 logbtn。"""
    data = request.get_json(force=True, silent=True) or {}
    vcs, wc, err, _tool_ok = _guard(data.get("root"))
    if err:
        return err
    if not _tool(vcs) and _remote_ctx(wc) is None:   # B-F03：SSH 生效让路（同 status）
        return jsonify({"ok": True, "vcs": vcs, "tool": False,
                        "files": [], "truncated": 0})
    if vcs == "svn":
        # v3.5.275（对抗审 F1）：端点接线——272 首笔 vcs.py 未进提交、272b
        # 只补了函数体，端点从未透传 shallow（分层加载端到端失效实锤）。
        # shallow=1 → depth='empty' 顶层模式（--depth empty 秒级）
        res, e = _svn_changes(wc, depth="empty" if data.get("shallow") else None)
        if e:
            return jsonify({"ok": False, "err": e}), 500
        _h = _remote_hint(wc)               # B-F07：按实际工作根取数
        return jsonify({"ok": True, "vcs": "svn", **res,
                        "remote_used": _mirror_effective(wc),
                        **({"remote_hint": _h} if _h else {})})
    res, e = _git_status(wc)
    if e:
        return jsonify({"ok": False, "err": e}), 500
    _h = _remote_hint(wc)
    return jsonify({"ok": True, "vcs": "git",
                    "files": res.get("files", []),
                    "truncated": res.get("truncated", 0),
                    "truncated_unv": res.get("truncated_unv", 0),
                    "remote_used": _mirror_effective(wc),
                    **({"remote_hint": _h} if _h else {})})


# ---------------------------------------------------------------------------
# log
# ---------------------------------------------------------------------------

# ---- v2（designer 方案 S1）：log 查询计划——参数校验+命令组装纯函数 ----

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")
# git --author 是 BRE 正则——仅转义这 6 个元字符（GNU BRE 里转义 +?(){}| 反而
# 制造元字符，切不可用 re.escape，designer D10）
_BRE_META = "\\.*[]^$"
# a650：git log --graph 的行首 ASCII 连线列（"* "、"| * "、"|/ "、"|\\ "）
_GRAPH_COL_RE = re.compile(r"^[\s|*\\/]+")
# 行尾的连线列（--graph 与 --shortstat 共用行时出现）
_GRAPH_TAIL_RE = re.compile(r"[\s|\\/]+$")


def _bre_lit(s):
    return "".join(("\\" + c) if c in _BRE_META else c for c in s)


def _log_plan(vcs, data):
    """校验并组装 log 查询。返回 (err_tuple|None, git_argv|None,
    git_count_argv|None, svn_argv|None, skip, limit)。"""
    try:
        limit = max(1, min(_LOG_CAP, int(data.get("limit") or 30)))
    except (TypeError, ValueError):
        limit = 30
    try:
        skip = max(0, int(data.get("skip") or 0))
    except (TypeError, ValueError):
        skip = 0
    if skip + limit > _SKIP_CAP:
        return (("深度超限：skip+limit ≤ %d（更早历史请用命令行）" % _SKIP_CAP), 400), \
            None, None, None, skip, limit
    text = _CTRL_RE.sub("", str(data.get("text") or "").strip())[:200]
    author = _CTRL_RE.sub("", str(data.get("author") or "").strip())[:200]
    since = str(data.get("since") or "").strip()
    until = str(data.get("until") or "").strip()
    for d in (since, until):
        if d and not _DATE_RE.match(d):
            return (("日期格式应为 YYYY-MM-DD"), 400), None, None, None, skip, limit
        if d:
            # 全审L3：正则之外补语义校验——2026-13-45 这类正则可过、git 静默
            # 返回空的假日期在此真拒
            try:
                import datetime as _dt
                _dt.date(*[int(x) for x in d.split("-")])
            except ValueError:
                return (("日期无效：%s" % d), 400), None, None, None, skip, limit
    if since and until and since > until:
        return (("起始日期不能晚于结束日期"), 400), None, None, None, skip, limit
    before_rev = str(data.get("before_rev") or "").strip()
    # a650：图形视图的两个开关（缺省关闭，保持既有线性列表行为不变）。
    # 用 _truthy：前端若发字符串 "0"/"false"，bool() 会把它当开。
    graph = _truthy(data.get("graph"))
    all_refs = _truthy(data.get("all"))
    rev_target = str(data.get("rev") or "").strip()

    if vcs == "git":
        argv = ["git", "log", "-n", str(limit), "--date=iso-strict",
                "--decorate=short", "--shortstat",
                "--pretty=format:%H%x1f%h%x1f%an%x1f%ad%x1f%s%x1f%d"]
        if graph:
            # --graph 会插入 ASCII 连线列，解析时按 \x1f 分隔仍成立（列在
            # 行首，不影响字段切分）；前端按首段是否只含图形字符判定
            argv.append("--graph")
        if all_refs:
            argv.append("--all")
        rev_arg = ""
        if before_rev:
            if not _git_ref_ok(before_rev):
                return (("修订引用非法"), 400), None, None, None, skip, limit
            rev_arg = before_rev
        elif rev_target:
            if not _git_ref_ok(rev_target):
                return (("修订引用非法"), 400), None, None, None, skip, limit
            rev_arg = rev_target
        # a650 审计 P3：--all 与指定 rev 互斥（git log --all <rev> 里 --all
        # 直接压过 rev，等于参数没生效）。带 --all 时不追加 rev。
        if rev_arg and not all_refs:
            argv.append(rev_arg)
        # 总数按日志范围同口径统计（--all / 指定 rev 时不能用 HEAD 计数，
        # 否则前端分页终点会提前截断）
        cargv = ["git", "rev-list", "--count"]
        cargv += (["--all"] if all_refs else [rev_arg or "HEAD"])
        if skip:
            argv += ["--skip", str(skip)]
        if text:
            argv += ["--fixed-strings", "-i", "--all-match"]
            for w in text.split():
                argv += ["--grep", w]
            cargv += ["--fixed-strings", "-i", "--all-match"]
            for w in text.split():
                cargv += ["--grep", w]
        if author:
            argv += ["--author", _bre_lit(author)]
            cargv += ["--author", _bre_lit(author)]
        if since:
            argv += ["--since", since + "T00:00:00"]
            cargv += ["--since", since + "T00:00:00"]
        if until:
            argv += ["--until", until + "T23:59:59"]
            cargv += ["--until", until + "T23:59:59"]
        return None, argv, (None if skip else cargv), None, skip, limit

    # svn：-r 游标/日期花括号 + --search（1.8+，整串 OR 语义，与 git AND 差异
    # 由前端 placeholder 文档化）；作者无等价参数（不显示控件，designer D10）
    argv = ["svn", "log", "--xml"]
    lo = "{%s}" % (since + "T00:00:00") if since else "1"
    hi = "{%s}" % (until + "T23:59:59") if until else "HEAD"
    if before_rev:
        if not before_rev.isdigit():
            return (("svn 游标必须是数字修订号"), 400), None, None, None, skip, limit
        argv += ["-r", "%s:%s" % (before_rev, lo)]
    else:
        argv += ["-r", "%s:%s" % (hi, lo)]
    argv += ["-l", str(limit)]
    if text:
        argv += ["--search", text]
    return None, None, None, argv, skip, limit


@vcs_bp.route("/api/vcs/log", methods=["POST"])
def vcs_log():
    data = request.get_json(force=True, silent=True) or {}
    vcs, wc, err, _tool_ok = _guard(data.get("root"))
    if err:
        return err
    plan = _log_plan(vcs, data)
    err_t, git_argv, git_count_argv, svn_argv, skip, limit = plan
    if err_t:
        return jsonify({"ok": False, "err": err_t[0]}), err_t[1]
    commits = []
    total = None
    if vcs == "git":
        rc, out, e = _run(git_argv, wc, VCS_TIMEOUT_RO)
        if rc != 0:
            if "does not have any commits yet" in (e or "") or rc == 128 and not out:
                return jsonify({"ok": True, "commits": []})
            return jsonify({"ok": False, "err": e or "git log 失败"}), 500
        for line in out.splitlines():
            # a650：--graph 会在行首插 ASCII 连线列（"* "、"| * "、"|/" 等），
            # 不剥掉的话 rev 字段会被污染成「| * abc123」。只剥行首——subject
            # 里的同样字符不受影响。无 graph 时行首是 hex，正则不匹配。
            gpre = ""
            if data.get("graph"):
                m = _GRAPH_COL_RE.match(line)
                if m:
                    gpre = m.group(0)
                    line = line[m.end():]
            parts = line.split("\x1f")
            # v2 D9：5 字段放宽为 ≥5（第 6 可选 deco，带前导空格须 trim）
            if len(parts) >= 5:
                deco = parts[5].strip() if len(parts) > 5 else ""
                if data.get("graph"):
                    # --graph 在共用行时行尾也会补连线字符（"(HEAD -> main)|"）
                    deco = _GRAPH_TAIL_RE.sub("", deco).rstrip()
                commits.append({"rev": parts[0], "short": parts[1],
                                "author": parts[2], "date": parts[3],
                                "msg": parts[4], "deco": deco,
                                **({"graph": gpre} if gpre else {})})
            elif commits and " changed" in line:
                # v3.5.198（用户需求「提交列表加增减数字」）：--shortstat 追加行
                # 「 N files changed, N insertions(+), N deletions(-)」配对上一条
                _mi = re.search(r"(\d+) insertion", line)
                _md = re.search(r"(\d+) deletion", line)
                commits[-1]["ins"] = int(_mi.group(1)) if _mi else 0
                commits[-1]["del"] = int(_md.group(1)) if _md else 0
        if git_count_argv:   # 仅首页（skip==0）附带精确总数（svn 无此能力）
            rc2, out2, _e2 = _run(git_count_argv, wc, VCS_TIMEOUT_RO)
            if rc2 == 0:
                try:
                    total = int(out2.strip() or 0) or None
                except ValueError:
                    total = None
    else:
        rc, out, e = _run(svn_argv, wc, VCS_TIMEOUT_RO)
        if rc != 0 and "--search" in svn_argv and (
                "invalid option" in (e or "") or "unknown option" in (e or "")):
            # svn <1.8 无 --search：APR getopt 实证 stderr 是「svn: invalid
            # option: --search」（unknown option 是 git 措辞——P1 修）；去掉
            # 重拉，客户端过滤由前端按 banner 提示处理已载分页
            _argv2 = list(svn_argv)
            _i = _argv2.index("--search")
            del _argv2[_i:_i + 2]
            rc, out, e = _run(_argv2, wc, VCS_TIMEOUT_RO)
        if rc != 0:
            return jsonify({"ok": False, "err": e or "svn log 失败"}), 500
        try:
            root = ET.fromstring(out.encode("utf-8"))
            for le in root.iter("logentry"):
                commits.append({"rev": le.get("revision", ""),
                                "short": "r%s" % le.get("revision", ""),
                                "author": le.findtext("author") or "",
                                "date": le.findtext("date") or "",
                                "msg": (le.findtext("msg") or "").strip(),
                                "deco": ""})
        except ET.ParseError as pe:
            return jsonify({"ok": False, "err": "svn log 解析失败：%s" % pe}), 500
    resp = {"ok": True, "commits": commits}
    if total is not None:
        resp["total"] = total
    if vcs == "git":
        # a650：HEAD 指纹——前端据此检测「上下文已切换」（换分支/rebase）
        # 并整表重建；否则切分支后新页 append 到旧数组尾部 = 新旧两段拼接
        #（用户实锤「任意切一下 git 排序就不对」）
        rc_h, out_h, _eh = _run(["git", "rev-parse", "HEAD"], wc, VCS_TIMEOUT_RO)
        if rc_h == 0 and out_h.strip():
            resp["head"] = out_h.strip()
    return jsonify(resp)


# ---------------------------------------------------------------------------
# diff（旧版本物化成临时文件，前端 buildDiffViewerTab 走真实路径）
# ---------------------------------------------------------------------------

def _run_bytes(argv, cwd, timeout=None):
    """取原始字节（diff 用）。a455：与 _run 同样优先走 SSH 远端——
    否则 diff 在网盘上仍要 47s 级。失败返回 b''（原有降级语义不变）。"""
    to = timeout or VCS_TIMEOUT_RO
    entry = _remote_ctx(cwd)
    if entry is not None:
        try:
            from src import vcs_remote
            rc, raw, _e = vcs_remote.run(entry, argv, cwd, to)
            return raw if rc == 0 else b""
        except Exception as _e:
            _set_remote_err(_e)
    try:
        p = subprocess.run([str(a) for a in argv], cwd=cwd,
                           capture_output=True, timeout=to,
                           creationflags=CREATE_NO_WINDOW)
        return p.stdout if p.returncode == 0 else b""
    except Exception:
        return b""


def _git_old_bytes(wc, rel, st):
    if st == "A":                           # 新增文件：旧版为空
        return b""
    # 轻审 P6：超时/异常降级空旧版
    return _run_bytes(["git", "show", "HEAD:%s" % rel], wc)


def _svn_old_bytes(wc, rel, st):
    if st == "A":
        return b""
    return _run_bytes(["svn", "cat", "-r", "BASE", os.path.join(wc, rel)], wc)


@vcs_bp.route("/api/vcs/commit_files", methods=["POST"])
def vcs_commit_files():
    """v3.5.131：点「最近提交」行查看该提交的改动文件清单（用户需求
    「历史提交点开查看历史修改情况」）。git：show --name-status；svn：
    diff --summarize -c rev。rev 走 _run 原样传参（无 shell 注入面）。"""
    data = request.get_json(force=True, silent=True) or {}
    vcs, wc, err, _tool_ok = _guard(data.get("root"), need_tool=True)
    if err:
        return err
    rev = str(data.get("rev") or "").strip()
    if not rev or len(rev) > 64 or not re.match(r"^[0-9a-zA-Z^-]{1,64}$", rev):
        return jsonify({"ok": False, "err": "非法修订号"}), 400
    if vcs == "svn" and not rev.isdigit():
        return jsonify({"ok": False, "err": "svn 修订号必须是数字"}), 400
    files = []
    if vcs == "git":
        # v3.5.132（轻审严重2）：quotepath=false——非 ASCII 文件名默认输出
        # 引号+八进制转义，下游 git show rev:path 实测 fatal 假无差异
        rc, out, e = _run(["git", "-c", "core.quotepath=false", "show",
                           "--name-status", "--no-renames",
                           "--format=", rev], wc, VCS_TIMEOUT_RO)
        if rc != 0:
            return jsonify({"ok": False, "err": e or "git show 失败"}), 500
        for line in out.splitlines():
            m = re.match(r"^([AMD])\t(.+)$", line)
            if m:
                files.append({"st": m.group(1), "path": m.group(2)})
    else:
        rc, out, e = _run(["svn", "diff", "--summarize", "-c", rev, wc],
                          wc, VCS_TIMEOUT_RO)
        if rc != 0:
            return jsonify({"ok": False, "err": e or "svn diff 失败"}), 500
        wcp = wc.replace("/", os.sep).rstrip(os.sep) + os.sep
        # 三路审计 B-F01：SSH 生效时 summarize 以**远端绝对路径**回传
        # （_map_argv 把 wc 译成了 remote_root）——只剥本地前缀会把
        # /data1/... 原样透传，前端点开 diff 必 400「非法文件路径」。
        # 先剥远端前缀再走本地前缀逻辑，两条路径都归一到 rel。
        _rr = ""
        try:
            _re = _remote_ctx(wc)
            if _re:
                _rr = str(_re.get("remote_root") or "").replace("\\", "/").rstrip("/")
        except Exception:
            _rr = ""
        for line in out.splitlines():
            # v3.5.132（轻审严重1）：双捕获组——旧单组取路径首字符当状态字母
            m = re.match(r"^([AMD])\s+(.+)$", line.strip())
            if not m:
                continue
            path = m.group(2).replace("\\", "/")
            if _rr and (path == _rr or path.startswith(_rr + "/")):
                path = path[len(_rr):].lstrip("/")
            apath = path.replace("/", os.sep)
            if apath.startswith(wcp):   # svn summarize 可能输出绝对路径——剥工作副本前缀转 rel
                path = apath[len(wcp):].replace(os.sep, "/")
            files.append({"st": m.group(1), "path": path})
    return jsonify({"ok": True, "files": files[:200]})


@vcs_bp.route("/api/vcs/commit_diff", methods=["POST"])
def vcs_commit_diff():
    """v3.5.131：单文件在某提交的改动对比——父修订/该修订两版物化临时文件，
    前端 buildDiffViewerTab 走真实路径（与 /api/vcs/diff 同机制）。"""
    data = request.get_json(force=True, silent=True) or {}
    vcs, wc, err, _tool_ok = _guard(data.get("root"), need_tool=True)
    if err:
        return err
    rev = str(data.get("rev") or "").strip()
    if not rev or len(rev) > 64 or not re.match(r"^[0-9a-zA-Z^-]{1,64}$", rev):
        return jsonify({"ok": False, "err": "非法修订号"}), 400
    # v3.5.132（轻审一般3）：svn 分支要算 rev-1——非数字提前 400（int() 异常
    # 会裸 500 HTML）
    if vcs == "svn" and not rev.isdigit():
        return jsonify({"ok": False, "err": "svn 修订号必须是数字"}), 400
    rel = str(data.get("path") or "").replace("\\", "/").strip()
    if _bad_rel(rel):
        return jsonify({"ok": False, "err": "非法文件路径"}), 400
    st = str(data.get("st") or "M")

    def _git_rev_bytes(spec):
        # v3.5.132（轻审严重2）：quotepath 同步——rel 含非 ASCII 时 rev:rel
        # 必须按原字节名寻址。a455：统一走 _run_bytes（自动优先 SSH 远端）。
        return _run_bytes(["git", "-c", "core.quotepath=false", "show",
                           "%s:%s" % (spec, rel)], wc)

    base = os.path.basename(rel)
    if vcs == "git":
        a_bytes = b"" if st == "A" else _git_rev_bytes(rev + "~1")
        b_bytes = b"" if st == "D" else _git_rev_bytes(rev)
        a_hint, b_hint = "%s@%s~1" % (base, rev[:8]), "%s@%s" % (base, rev[:8])
    else:
        def _svn_rev_bytes(r):
            return _run_bytes(["svn", "cat", "-r", r,
                               os.path.join(wc, rel)], wc)
        a_bytes = b"" if st == "A" else _svn_rev_bytes(str(int(rev) - 1))
        b_bytes = b"" if st == "D" else _svn_rev_bytes(rev)
        a_hint, b_hint = "%s@r%s-1" % (base, rev), "%s@r%s" % (base, rev)
    return jsonify({"ok": True, "a": _tmp_materialize(a_bytes, a_hint),
                    "b": _tmp_materialize(b_bytes, b_hint)})


@vcs_bp.route("/api/vcs/diff", methods=["POST"])
def vcs_diff():
    data = request.get_json(force=True, silent=True) or {}
    vcs, wc, err, tool_ok = _guard(data.get("root"), need_tool=True)
    if err:
        return err
    rel = str(data.get("path") or "").replace("\\", "/").strip()
    if _bad_rel(rel):
        return jsonify({"ok": False, "err": "非法文件路径"}), 400
    full = os.path.join(wc, *rel.split("/"))
    st = str(data.get("st") or "M")
    if vcs == "git":
        a_bytes = _git_old_bytes(wc, rel, st)
    else:
        a_bytes = _svn_old_bytes(wc, rel, st)
    try:
        b_bytes = open(full, "rb").read() if os.path.isfile(full) else b""
    except OSError:
        b_bytes = b""
    a_hint, b_hint = "%s@%s" % (os.path.basename(rel),
                                "HEAD" if vcs == "git" else "BASE"), os.path.basename(rel)
    return jsonify({"ok": True, "a": _tmp_materialize(a_bytes, a_hint),
                    "b": _tmp_materialize(b_bytes, b_hint)})


# ---------------------------------------------------------------------------
# 写操作：add / commit / update（per-root 锁 + 显式确认语义）
# ---------------------------------------------------------------------------

def _bad_rel(p):
    """rel 路径统一校验（轻审 P2）：空 / 绝对（/ 或盘符）/ .. 穿越全拒。

    a650 审计 P3：控制符（含 NUL）也要拒——NUL 会流进 subprocess 触发
    ValueError，被吞成 rc=-1 的假故障。
    """
    p = (p or "").replace("\\", "/").strip()
    return (not p or p.startswith("/") or re.match(r"^[A-Za-z]:", p)
            or ".." in p.split("/")
            or re.search(r"[\x00-\x1f\x7f]", p) is not None)


def _git_add_missing(wc, paths):
    """勾选中未跟踪的先 add（git 提交 pathspec 限定时未跟踪文件必须先入索引）。
    v3.5.118（轻审 P1 严重）：porcelain -z 的 untracked token 是 "?? path"
    （两个问号+空格）——旧代码 startswith("? ")+tok[2:] 永假，新文件从不
    自动 add，git commit 原子失败连坐同组已跟踪文件。"""
    rc, out, _e = _run(["git", "-c", "core.quotepath=false",
                        "status", "--porcelain=v1", "-z"], wc, VCS_TIMEOUT_RO)
    if rc != 0:
        return
    untracked = set()
    toks = out.split("\0")
    it = iter(toks)
    for tok in it:
        if tok.startswith("?? "):
            untracked.add(tok[3:].replace("\\", "/"))
        elif tok[:2] in ("R ", "C "):
            next(it, None)                  # rename/copy 的 old 占位跳过
    want = [p for p in paths if p.replace("\\", "/") in untracked]
    if want:
        _run(["git", "add", "--"] + want, wc, VCS_TIMEOUT_RW)


@vcs_bp.route("/api/vcs/add", methods=["POST"])
def vcs_add():
    data = request.get_json(force=True, silent=True) or {}
    vcs, wc, err, _tool_ok = _guard(data.get("root"), need_tool=True)
    if err:
        return err
    paths = [str(p).replace("\\", "/") for p in (data.get("paths") or []) if p]
    if not paths or any(_bad_rel(p) for p in paths):
        return jsonify({"ok": False, "err": "未选择文件或路径非法"}), 400
    with _root_lock(wc):
        if vcs == "git":
            rc, out, e = _run(["git", "add", "--"] + paths, wc, VCS_TIMEOUT_RW)
        else:
            rc, out, e = _run(["svn", "add", "--"] + [
                os.path.join(wc, *p.split("/")) for p in paths], wc, VCS_TIMEOUT_RW)
        if rc != 0:
            return jsonify({"ok": False, "err": e or out or "add 失败"}), 500
    _st_memo_inval(wc)   # 写后失效 status memo（性能批）
    return jsonify({"ok": True, "out": (out or "").strip()})


@vcs_bp.route("/api/vcs/commit", methods=["POST"])
def vcs_commit():
    data = request.get_json(force=True, silent=True) or {}
    vcs, wc, err, _tool_ok = _guard(data.get("root"), need_tool=True)
    if err:
        return err
    msg = str(data.get("message") or "").strip()
    if not msg:
        return jsonify({"ok": False, "err": "提交说明必填"}), 400
    paths = [str(p).replace("\\", "/") for p in (data.get("paths") or []) if p]
    if not paths or any(_bad_rel(p) for p in paths):
        return jsonify({"ok": False, "err": "未选择文件或路径非法"}), 400
    with _root_lock(wc):
        if vcs == "git":
            _git_add_missing(wc, paths)
            rc, out, e = _run(["git", "commit", "-m", msg, "--"] + paths,
                              wc, VCS_TIMEOUT_RW)
            if rc != 0:
                return jsonify({"ok": False,
                                "err": (e or out or "commit 失败").strip()}), 500
            m = re.search(r"\[[\s\S]*? ([0-9a-f]{7,40})\]", out)
            _st_memo_inval(wc)   # 写后失效 status memo（性能批）
            return jsonify({"ok": True, "out": out.strip(),
                            **({"rev": m.group(1)} if m else {})})
        # svn：勾选中未跟踪（?）的先 svn add，再显式 target 提交
        rc, out, _e = _run(["svn", "status", "--xml"], wc, VCS_TIMEOUT_RO)
        if rc == 0:
            unv = []
            try:
                root = ET.fromstring(out.encode("utf-8"))
                for t in root.iter("target"):
                    for en in t.iter("entry"):
                        it = en.find("wc-status")
                        if it is not None and it.get("item") == "unversioned":
                            unv.append(en.get("path", "").replace("\\", "/"))
            except ET.ParseError:
                pass
            want = [os.path.join(wc, *p.split("/"))
                    for p in paths if p in unv]
            if want:
                _run(["svn", "add", "--"] + want, wc, VCS_TIMEOUT_RW)
        rc, out, e = _run(["svn", "commit", "-m", msg] + [
            os.path.join(wc, *p.split("/")) for p in paths], wc, VCS_TIMEOUT_NET)
        if rc != 0:
            return jsonify({"ok": False, "err": e or out or "commit 失败"}), 500
        _st_memo_inval(wc)   # 写后失效 status memo（性能批）
        return jsonify({"ok": True, "out": (out or "").strip()})


@vcs_bp.route("/api/vcs/update", methods=["POST"])
def vcs_update():
    data = request.get_json(force=True, silent=True) or {}
    vcs, wc, err, _tool_ok = _guard(data.get("root"), need_tool=True)
    if err:
        return err
    with _root_lock(wc):
        if vcs == "git":
            rc, out, e = _run(["git", "pull", "--ff-only"], wc, VCS_TIMEOUT_NET)
        else:
            rc, out, e = _run(["svn", "update", "--accept", "postpone"],
                              wc, VCS_TIMEOUT_NET)
        text = (out or e or "").strip()
        if rc != 0:
            hint = ("本地与远端已分叉——本工具不含合并/冲突处理，"
                    "请在 git 命令行解决后刷新") if vcs == "git" else \
                   ("存在冲突（ postpone 保现场）——本工具不含冲突解决，"
                    "请用 svn 命令行/TortoiseSVN 处理后刷新")
            conflicts = sorted(set(re.findall(r"^\s*C\s+(.+)$", out or "",
                                              flags=re.M)))
            return jsonify({"ok": False, "err": hint, "out": text[:4000],
                            "conflicts": conflicts}), 500
        conflicts = sorted(set(re.findall(r"^\s*C\s+(.+)$", out or "",
                                          flags=re.M)))
        _st_memo_inval(wc)   # 写后失效 status memo（性能批）
        return jsonify({"ok": True, "out": text[:4000],
                        "conflicts": conflicts})


# ---------------------------------------------------------------------------
# 远端加速（a455）：版本面板内的 SSH 配置 / 探测 / 一键部署公钥
# ---------------------------------------------------------------------------

@vcs_bp.route("/api/vcs/remote/probe", methods=["POST"])
def vcs_remote_probe():
    """当前工程该不该、能不能走 SSH 远端。前端据此决定显示哪种引导。

    返回 {ok, vcs, is_network, drive, configured, enabled, remote_ok, reason,
          entry(脱敏), hint(上次回退原因)}
    纯本地盘：is_network=False，前端什么都不显示（不打扰）。
    网络盘未配置：reason='unconfigured'，前端出「建议启用 SSH 加速」卡片。"""
    from src import vcs_remote
    data = request.get_json(force=True, silent=True) or {}
    root = str(data.get("root") or "").strip()
    vcs, wc, err, _tool_ok = _guard(root)
    if err:
        return err
    # a460（复审 a455）：配置/提示统一按 **wc（仓库根）** 归键。执行侧
    # _run 的 cwd 恒为 wc、_remote_ctx 落点也是 wc——面板以子目录打开时
    # （root≠wc）按 root 存的配置永远匹配不上：SSH 静默失效、芯片谎报
    # 「建议启用」、_set_remote_err 落 root 键而 status/changes 按 wc 查
    # （B-F07），回退提示也丢——B-F02 的回退窗口对子目录入口重新漏风。
    probe = vcs_remote.probe_scope(wc)
    entry = vcs_remote.get_for_root(wc)
    profiles = vcs_remote.list_profiles()
    # a455：连接档案全局复用——换工程时不用重填主机/口令；这里顺带给出
    # 按共享根推导出的远端路径，用户确认一下就能保存。
    _basis = entry or (profiles[0] if profiles else {})
    # a455：档案没设共享根时，连上去自动探测一次（结果只用于本次提示）
    _share = (_basis or {}).get("share_root") or ""
    if _basis and not _share:
        _prof = vcs_remote.get_profile(_basis.get("profile_id")
                                       or _basis.get("id"))
        if _prof:
            _share = vcs_remote.detect_share_root(_prof, wc)
            if _share:
                _basis = dict(_basis, share_root=_share)
    resp = {"ok": True, "vcs": vcs, "wc": wc, **probe,
            "entry": vcs_remote.public_view(entry),
            "profiles": profiles,
            "mappings": vcs_remote.list_mappings(),
            "detected_share_root": _share,
            "suggest_remote_root": vcs_remote.guess_remote_root(wc, _basis)
            if _basis else "",
            "hint": _remote_hint(wc) or ""}
    # 已配置但从未测通时，顺带做一次轻探测（12s 上限，失败也返回 200）
    if entry and probe.get("reason") == "configured" and data.get("check"):
        t = vcs_remote.test(entry)
        resp["test"] = t
        resp["remote_ok"] = bool(t.get("ok"))
        if not t.get("ok"):
            resp["hint"] = t.get("err") or ""
    return jsonify(resp)


@vcs_bp.route("/api/vcs/remote/save", methods=["POST"])
def vcs_remote_save():
    """保存工程映射；若同时给了主机信息则一并维护连接档案。body:
    {root, profile_id?, host?, user?, remote_root?, auth?, password?,
     key_path?, port?, share_root?, name?, enabled?}

    典型两种调用：
      换工程复用已有档案 → {root, profile_id: 1, remote_root: "/data1/..."}
      首次配置          → {root, host, user, password, share_root}
    password 省略/空 = 保留已存口令（改主机名不丢密码）。"""
    from src import vcs_remote
    data = request.get_json(force=True, silent=True) or {}
    root = str(data.get("root") or "").strip()
    _vcs, _wc, err, _t = _guard(root)
    if err:
        return err
    auth = str(data.get("auth") or "").strip().lower()
    if auth and auth not in ("password", "key", "agent"):
        return jsonify({"ok": False, "err": "auth 必须是 password/key/agent"}), 400
    pwd = data.get("password")
    pid = data.get("profile_id")
    try:
        pid = int(pid) if pid not in (None, "") else None
    except (TypeError, ValueError):
        return jsonify({"ok": False, "err": "profile_id 必须是数字"}), 400
    # 三路审计 B-F18：enabled 字符串形态严格布尔化——"false" 经 bool() 是
    # True，API 直调会造出「名义启用实为关」的映射。
    _en = data.get("enabled", True)
    if isinstance(_en, str):
        _en = _en.strip().lower() not in ("false", "0", "off", "no", "")
    try:
        # a460：按 wc（仓库根）归键（见 probe 端点同款注释）——执行侧匹配
        # 的是 wc，按请求 root 存在子目录场景下永不命中
        entry = vcs_remote.upsert(
            local_root=_wc,
            host=data.get("host") or None,
            user=data.get("user") or None,
            remote_root=data.get("remote_root") or None,
            auth=auth or "password",
            password=(str(pwd) if pwd else None),
            key_path=data.get("key_path") or "",
            port=data.get("port") or 22,
            enabled=bool(_en),
            profile_id=pid,
            share_root=data.get("share_root") or "",
            name=data.get("name") or "")
    except ValueError as e:
        return jsonify({"ok": False, "err": str(e)}), 400
    # 旧版本可能按「请求根」存过（子目录场景下是死配置）——顺手清掉，
    # 避免 mappings 列表里出现两条指向同一仓库的影子条目
    if root and os.path.normcase(os.path.normpath(root)) \
            != os.path.normcase(os.path.normpath(_wc)):
        vcs_remote.remove(root)
    _clear_remote_err(_wc)
    _clear_remote_err(root)
    return jsonify({"ok": True, "entry": vcs_remote.public_view(
        vcs_remote.get_for_root(_wc)),
        "profiles": vcs_remote.list_profiles()})


@vcs_bp.route("/api/vcs/remote/profiles", methods=["POST"])
def vcs_remote_profiles():
    """连接档案的独立管理（新增/修改/删除），与工程无关。

    body {action: "save"|"delete", id?, name?, host?, user?, auth?,
          password?, key_path?, port?, share_root?}"""
    from src import vcs_remote
    data = request.get_json(force=True, silent=True) or {}
    act = str(data.get("action") or "").strip().lower()
    if act == "delete":
        try:
            pid = int(data.get("id"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "err": "id 必须是数字"}), 400
        r = vcs_remote.remove_profile(pid)
        return jsonify({"ok": True, **r,
                        "profiles": vcs_remote.list_profiles()})
    if act != "save":
        return jsonify({"ok": False, "err": "action 必须是 save/delete"}), 400
    auth = str(data.get("auth") or "password").strip().lower()
    if auth not in ("password", "key", "agent"):
        return jsonify({"ok": False, "err": "auth 必须是 password/key/agent"}), 400
    pwd = data.get("password")
    pid = data.get("id")
    try:
        pid = int(pid) if pid not in (None, "") else None
    except (TypeError, ValueError):
        return jsonify({"ok": False, "err": "id 必须是数字"}), 400
    try:
        prof = vcs_remote.upsert_profile(
            profile_id=pid, name=data.get("name") or "",
            host=data.get("host"), user=data.get("user"), auth=auth,
            password=(str(pwd) if pwd else None),
            key_path=data.get("key_path") or "",
            port=data.get("port") or 22,
            share_root=data.get("share_root") or "")
    except ValueError as e:
        return jsonify({"ok": False, "err": str(e)}), 400
    return jsonify({"ok": True, "profile": vcs_remote.public_profile(prof),
                    "profiles": vcs_remote.list_profiles()})


@vcs_bp.route("/api/vcs/remote/test", methods=["POST"])
def vcs_remote_test():
    """用已存配置测连通性（不传 body 也能测：默认用 root 对应那条）。"""
    from src import vcs_remote
    data = request.get_json(force=True, silent=True) or {}
    root = str(data.get("root") or "").strip()
    _vcs, wc, err, _t = _guard(root)
    if err:
        return err
    # a460：按 wc 归键（probe 端点同款注释）——root 为子目录时按 root 查
    # 永远「没有保存配置」，且失败 hint 落错键、status 按 wc 查不到
    entry = vcs_remote.get_for_root(wc) or vcs_remote.get_for_root(root)
    if not entry:
        return jsonify({"ok": False, "err": "该工程还没有保存 SSH 配置"}), 400
    t = vcs_remote.test(entry)
    if t.get("ok"):
        _clear_remote_err(wc)
        _clear_remote_err(root)
    else:
        _LAST_REMOTE_ERR[os.path.normcase(wc)] = (time.time(),
                                                  t.get("err") or "连接失败")
    return jsonify({"ok": bool(t.get("ok")), **t})


@vcs_bp.route("/api/vcs/remote/deploy_key", methods=["POST"])
def vcs_remote_deploy_key():
    """一键部署公钥：用已存口令登录一次，把公钥追加到远端 authorized_keys，
    成功后把配置切到免密登录。返回公钥内容供用户手工兜底。"""
    from src import vcs_remote
    data = request.get_json(force=True, silent=True) or {}
    root = str(data.get("root") or "").strip()
    _vcs, _wc, err, _t = _guard(root)
    if err:
        return err
    # a460：按 wc 归键（probe 端点同款注释）
    entry = vcs_remote.get_for_root(_wc) or vcs_remote.get_for_root(root)
    if not entry:
        return jsonify({"ok": False, "err": "请先保存 SSH 配置"}), 400
    res = vcs_remote.deploy_key(entry, data.get("key_path") or "")
    if not res.get("ok"):
        return jsonify({"ok": False, **res}), 400
    vcs_remote.drop_pool()
    return jsonify({"ok": True, **res})


@vcs_bp.route("/api/vcs/remote/delete", methods=["POST"])
def vcs_remote_delete():
    """删除该工程的 SSH 配置（回到本地 svn 模式）。"""
    from src import vcs_remote
    data = request.get_json(force=True, silent=True) or {}
    root = str(data.get("root") or "").strip()
    # a460：按 wc 归键（probe 端点同款注释）；root 一并删，清掉旧版本
    # 按请求根存的影子条目
    _vcs, _wc, err, _t = _guard(root)
    if err:
        return err
    vcs_remote.remove(_wc)
    if root and os.path.normcase(os.path.normpath(root)) \
            != os.path.normcase(os.path.normpath(_wc)):
        vcs_remote.remove(root)
    _clear_remote_err(_wc)
    _clear_remote_err(root)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# a650：分支 / 标签 / stash / 撤销 / 推送 / 图形历史（全功能一期）
#
# 设计边界（与既有口径一致）：
#   · 切换分支前必须「干净工作区」——有未提交改动时返回 409 并给出三条
#     可选路径（提交 / stash / 丢弃）。绝不静默 stash：用户不知道 stash
#     存在时那些改动等于消失。
#   · 丢弃改动（git restore / svn revert）是唯一不可逆操作：强制 confirm=true，
#     且服务端先做一次自动快照（落到数据目录），响应里回报路径。
#   · svn 无分支/标签/stash 概念 → 对应接口一律 400 + 明确文案，
#     前端据此隐藏入口（不留「点了没反应」的空洞）。
# ---------------------------------------------------------------------------

_SNAP_DIR_NAME = "vcs_discard_snapshots"
# a650 审计 P2-6：快照是丢弃操作唯一的恢复手段。单个目录树可能很大
# （编译产物），但为不可逆操作留底优先，这里给一个宽松上限并如实回报截断。
_SNAP_MAX_BYTES = 512 * 1024 * 1024


def _git_ref_ok(name):
    """分支/标签名校验（对齐 git check-ref-format）。

    a650 审计 P1-1：原版只拒 "-" 开头，放行 "+" 开头——`git push origin +main`
    里的 `+` 是**强制推送 refspec 前缀**，一个叫 `+main` 的分支会让推送静默
    变成强推、覆盖远端他人提交。一并补齐 git 实际拒收的名字（`@{`、`@`、
    首尾 "."、".lock" 结尾），免得这些名字走到 git 才报 500。
    """
    if not name or len(name) > 200:
        return False
    if re.search(r"[\s~^:?*\[\]\\\x00-\x1f\x7f]", name):
        return False
    if name.startswith(("-", "+", "/", ".")) or name.endswith(("/", ".")):
        return False
    if ".." in name or "@{" in name or "//" in name or name == "@":
        return False
    if name.endswith(".lock"):
        return False
    return True


def _truthy(v):
    """请求体布尔的严格解析：字符串 "0"/"false" 不能被当开。"""
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


def _snap_discard(wc, rels):
    """丢弃改动前把当前内容快照到数据目录。

    a650 审计修复：
      · P2-4 目录名带 pid + uuid，同一秒内两次丢弃不再互相覆盖
      · P2-6 失败不再静默——返回 (路径, 失败原因) 由调用方如实回报；
        目录/符号链接目标同样留底（目录递归复制，链接只存目标字符串）
    返回 (snap_dir, err)；snap_dir 为空串表示没有可快照的内容。
    """
    import datetime as _dt
    import uuid
    err = ""
    try:
        stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        base = os.path.join(_st.DATA_DIR, _SNAP_DIR_NAME)
        d = os.path.join(base, "%s-%s-%s" % (
            stamp, hashlib.md5(wc.encode("utf-8", "replace")).hexdigest()[:8],
            uuid.uuid4().hex[:8]))
        n = 0
        for rel in rels:
            src = os.path.join(wc, *rel.split("/"))
            dst = os.path.join(d, *rel.split("/"))
            try:
                if os.path.islink(src):
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    with open(dst + ".symlink.txt", "w", encoding="utf-8") as f:
                        f.write(os.readlink(src))
                    n += 1
                elif os.path.isdir(src):
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copytree(src, dst, symlinks=True, dirs_exist_ok=True)
                    n += 1
                elif os.path.isfile(src):
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(src, dst)
                    n += 1
            except (OSError, shutil.Error) as e:
                err = "部分文件未能快照：%s" % str(e)[:300]
                continue
        try:
            total = sum(os.path.getsize(os.path.join(dp, f))
                        for dp, _dn, fn in os.walk(d) for f in fn
                        if not os.path.islink(os.path.join(dp, f)))
            if total > _SNAP_MAX_BYTES:
                err = (err + "；" if err else "") + "快照超过 %d MB，可能有内容未完整留底" % (
                    _SNAP_MAX_BYTES // (1024 * 1024))
        except OSError:
            pass
        if n:
            return d, err
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
    except Exception as e:                       # 磁盘满 / 权限 / 数据目录不可写
        err = "快照失败：%s" % str(e)[:300]
    return "", err


def _git_current_branch(wc):
    """当前分支名；detached HEAD 时返回空串（UI 显示「游离 HEAD」）。

    a650 审计 P3：空仓库（尚无 commit）时 rev-parse rc=128 且 stdout 仍是
    "HEAD"——原实现返回空串 = 误报「游离 HEAD」。用 symbolic-ref 区分：
    它能拿到未出生分支名（git ≥2.0 的输出是 refs/heads/master），失败才是真游离。
    """
    rc, out, _e = _run(["git", "symbolic-ref", "--quiet", "--short", "HEAD"], wc, 10)
    if rc == 0:
        b = out.strip()
        return "" if b in ("HEAD", "") else b
    rc, out, _e = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], wc, 10)
    if rc != 0:
        return ""
    b = out.strip()
    return "" if b in ("HEAD", "") else b


def _branch_ref(name):
    """分支名 → 完整 ref（推送达 refspec 用，杜绝 "+" 被当强制前缀）。"""
    return name if name.startswith("refs/") else "refs/heads/" + name


def _git_is_clean(wc):
    """工作区是否干净（未跟踪文件也算脏——切换分支前要让用户知情）。"""
    rc, out, _e = _run(["git", "-c", "core.quotepath=false", "status",
                        "--porcelain=v1"], wc, VCS_TIMEOUT_RO)
    return rc == 0 and not out.strip()


@vcs_bp.route("/api/vcs/branches", methods=["POST"])
def vcs_branches():
    """列出本地/远程分支 + 当前分支 + 是否游离。

    返回 {ok, current, detached, local:[{name, rev, subject, upstream,
          ahead, behind, current}], remote:[{name, rev, subject}]}
    """
    data = request.get_json(force=True, silent=True) or {}
    vcs, wc, err, _tool_ok = _guard(data.get("root"), need_tool=True)
    if err:
        return err
    if vcs != "git":
        return jsonify({"ok": False,
                        "err": "svn 没有分支概念（可查看历史 / 修订号）"}), 400
    fmt = ("%(refname:short)%1f%(objectname:short)%1f"
           "%(upstream:short)%1f%(upstream:track)%1f%(contents:subject)")
    cur = _git_current_branch(wc)
    detached = not cur
    local, remote = [], []

    def _refs(ns, is_local):
        rc, out, e = _run(["git", "for-each-ref", "--format=" + fmt, ns],
                          wc, VCS_TIMEOUT_RO)
        if rc != 0:
            return e or "读取分支失败"
        for line in out.splitlines():
            parts = line.split("\x1f")
            if len(parts) < 5:
                continue
            name, rev, up, track, subject = parts[:5]
            item = {"name": name, "rev": rev, "subject": subject}
            if is_local:
                ahead = behind = 0
                ma = re.search(r"ahead (\d+)", track or "")
                mb = re.search(r"behind (\d+)", track or "")
                if ma:
                    ahead = int(ma.group(1))
                if mb:
                    behind = int(mb.group(1))
                item.update({"upstream": up or "", "ahead": ahead,
                             "behind": behind, "current": (name == cur)})
                local.append(item)
            elif not name.endswith("/HEAD"):   # origin/HEAD 是别名
                remote.append(item)
        return None

    # a650 审计 P3：本地/远程分开取，互不连坐——远程取失败不该把已拿到的
    # 本地分支整体丢掉。任一失败时降级返回已取到的部分并附 warn。
    warns = []
    for ns, is_local in (("refs/heads", True), ("refs/remotes", False)):
        e2 = _refs(ns, is_local)
        if e2:
            warns.append(e2)
    body = {"ok": True, "current": cur, "detached": detached,
            "local": local, "remote": remote}
    if warns and not local:
        # 一条都没取到才算失败（部分成功带着 warn 照常可用）
        return jsonify({"ok": False, "err": "；".join(warns)[:2000]}), 500
    if warns:
        body["warn"] = "；".join(warns)[:600]
    return jsonify(body)


@vcs_bp.route("/api/vcs/branch/create", methods=["POST"])
def vcs_branch_create():
    """新建分支（不切换）。body: {root, name, from?}"""
    data = request.get_json(force=True, silent=True) or {}
    vcs, wc, err, _tool_ok = _guard(data.get("root"), need_tool=True)
    if err:
        return err
    if vcs != "git":
        return jsonify({"ok": False, "err": "svn 不支持分支操作"}), 400
    name = str(data.get("name") or "").strip()
    frm = str(data.get("from") or "").strip()
    if not name or not _git_ref_ok(name):
        return jsonify({"ok": False,
                        "err": "分支名非法（不能含空格 / .. / ~ ^ : ? * [ \\）"}), 400
    if frm and not _git_ref_ok(frm):
        return jsonify({"ok": False, "err": "起点引用非法"}), 400
    argv = ["git", "branch", "--", name] + ([frm] if frm else [])
    with _root_lock(wc):
        rc, out, e = _run(argv, wc, VCS_TIMEOUT_RW)
        if rc != 0:
            return jsonify({"ok": False,
                            "err": (e or out or "创建分支失败").strip()[:2000]}), 500
    _st_memo_inval(wc)
    return jsonify({"ok": True, "name": name})


@vcs_bp.route("/api/vcs/branch/switch", methods=["POST"])
def vcs_branch_switch():
    """切换分支。body: {root, name, dirty?(fail|ignore)}

    dirty 语义：
      · 缺省 / "fail"：工作区不干净 → 409，附脏文件清单（前端据此提示
        先提交或 stash）
      · "ignore"：把决定权交给 git，失败原样回报
    绝不静默 stash。
    """
    data = request.get_json(force=True, silent=True) or {}
    vcs, wc, err, _tool_ok = _guard(data.get("root"), need_tool=True)
    if err:
        return err
    if vcs != "git":
        return jsonify({"ok": False, "err": "svn 不支持分支切换"}), 400
    name = str(data.get("name") or "").strip()
    if not name or not _git_ref_ok(name):
        return jsonify({"ok": False, "err": "分支名非法"}), 400
    dirty_mode = str(data.get("dirty") or "fail")
    with _root_lock(wc):
        if dirty_mode != "ignore" and not _git_is_clean(wc):
            rc, out, _e = _run(["git", "-c", "core.quotepath=false", "status",
                                "--porcelain=v1"], wc, VCS_TIMEOUT_RO)
            files = [ln[3:] for ln in out.splitlines() if len(ln) > 3]
            return jsonify({
                "ok": False, "dirty": True, "files": files[:200],
                "err": "工作区有 %d 个未提交改动，切换分支可能冲突或丢失。"
                       "请先提交或 stash；确认要让 git 自行处理时带 "
                       "dirty=ignore 重试。" % len(files)}), 409
        # a650 审计 P1-2：老 git（< 2.23）回退**只能**用 `checkout <名称>`。
        # 旧代码回退成 `git checkout -- <名称>`——`--` 之后是 pathspec 语义，
        # 会把同名文件的工作区改动还原掉，分支根本没切，还报成功。
        rc, out, e = _run(["git", "switch", "--", name], wc, VCS_TIMEOUT_RW)
        if rc != 0:
            low = (e or "") + (out or "")
            if "not a git command" in low or "unknown subcommand" in low:
                rc, out, e = _run(["git", "checkout", name],
                                  wc, VCS_TIMEOUT_RW)
        if rc != 0:
            return jsonify({"ok": False,
                            "err": (e or out or "切换分支失败").strip()[:4000]}), 500
    _st_memo_inval(wc)
    return jsonify({"ok": True, "branch": _git_current_branch(wc)})


@vcs_bp.route("/api/vcs/branch/delete", methods=["POST"])
def vcs_branch_delete():
    """删除分支。body: {root, name, force?}
    当前分支拒绝；未合并分支需 force。"""
    data = request.get_json(force=True, silent=True) or {}
    vcs, wc, err, _tool_ok = _guard(data.get("root"), need_tool=True)
    if err:
        return err
    if vcs != "git":
        return jsonify({"ok": False, "err": "svn 不支持分支操作"}), 400
    name = str(data.get("name") or "").strip()
    if not name or not _git_ref_ok(name):
        return jsonify({"ok": False, "err": "分支名非法"}), 400
    if name == _git_current_branch(wc):
        return jsonify({"ok": False,
                        "err": "不能删除当前所在分支，请先切换到其它分支"}), 400
    flag = "-D" if data.get("force") else "-d"
    with _root_lock(wc):
        rc, out, e = _run(["git", "branch", flag, "--", name], wc, VCS_TIMEOUT_RW)
        if rc != 0:
            return jsonify({"ok": False,
                            "err": (e or out or "删除分支失败").strip()[:2000]}), 500
    _st_memo_inval(wc)
    return jsonify({"ok": True})


@vcs_bp.route("/api/vcs/stash", methods=["POST"])
def vcs_stash():
    """stash。body: {root, action: list|push|pop|apply|drop, message?, index?}"""
    data = request.get_json(force=True, silent=True) or {}
    vcs, wc, err, _tool_ok = _guard(data.get("root"), need_tool=True)
    if err:
        return err
    if vcs != "git":
        return jsonify({"ok": False, "err": "svn 无 stash（svn shelve 另说）"}), 400
    act = str(data.get("action") or "list")
    if act == "list":
        # 只读，不占写锁（写锁只用于和同仓库写操作互斥）
        rc, out, e = _run(["git", "stash", "list", "--format=%gd\x1f%s"],
                          wc, VCS_TIMEOUT_RO)
        if rc != 0:
            return jsonify({"ok": False, "err": e or "stash list 失败"}), 500
        items = []
        for ln in out.splitlines():
            p = ln.split("\x1f")
            if len(p) >= 2:
                items.append({"ref": p[0], "msg": p[1]})
        return jsonify({"ok": True, "stashes": items})
    with _root_lock(wc):
        if act == "push":
            msg = str(data.get("message") or "").strip()
            argv = ["git", "stash", "push", "--include-untracked"]
            if msg:
                argv += ["-m", msg]
            rc, out, e = _run(argv, wc, VCS_TIMEOUT_RW)
        elif act in ("pop", "apply", "drop"):
            try:
                idx = int(data.get("index") or 0)
            except (TypeError, ValueError):
                return jsonify({"ok": False, "err": "index 非法"}), 400
            if idx < 0 or idx > 200:
                return jsonify({"ok": False, "err": "index 越界"}), 400
            # a650 审计 P3：index 越界是用户输入错误，不是服务器故障——
            # 先确认该 stash 存在，不存在回 400。
            rc0, out0, _e0 = _run(["git", "stash", "list", "--format=%gd"],
                                  wc, VCS_TIMEOUT_RO)
            if rc0 == 0:
                refs = [x.strip() for x in out0.splitlines() if x.strip()]
                if idx >= len(refs):
                    return jsonify({"ok": False,
                                    "err": "第 %d 条 stash 不存在（共 %d 条）" % (
                                        idx, len(refs))}), 400
            rc, out, e = _run(["git", "stash", act, "stash@{%d}" % idx],
                              wc, VCS_TIMEOUT_RW)
        else:
            return jsonify({"ok": False, "err": "未知 action"}), 400
        if rc != 0:
            return jsonify({"ok": False,
                            "err": (e or out or "stash 失败").strip()[:4000]}), 500
    _st_memo_inval(wc)
    return jsonify({"ok": True, "out": (out or "").strip()[:4000]})


@vcs_bp.route("/api/vcs/unstage", methods=["POST"])
def vcs_unstage():
    """撤销暂存（git restore --staged）。body: {root, paths[]}"""
    data = request.get_json(force=True, silent=True) or {}
    vcs, wc, err, _tool_ok = _guard(data.get("root"), need_tool=True)
    if err:
        return err
    if vcs != "git":
        return jsonify({"ok": False, "err": "svn 没有暂存区概念"}), 400
    paths = [str(p).replace("\\", "/") for p in (data.get("paths") or []) if p]
    if not paths or any(_bad_rel(p) for p in paths):
        return jsonify({"ok": False, "err": "未选择文件或路径非法"}), 400
    with _root_lock(wc):
        rc, out, e = _run(["git", "restore", "--staged", "--"] + paths,
                          wc, VCS_TIMEOUT_RW)
        if rc != 0 and ("not a git command" in (e or "")
                        or "unknown subcommand" in (e or "")):
            # 只在「老 git 不认识 restore」时回退；其它失败原样上报。
            # a650 审计 P3：旧实现的回退判据是「rc != 0」——勾选未跟踪文件
            # 时 restore 报 pathspec 不符，reset 却 rc=0 什么都没做，于是
            # 接口谎报成功。
            rc, out, e = _run(["git", "reset", "HEAD", "--"] + paths,
                              wc, VCS_TIMEOUT_RW)
        if rc != 0:
            return jsonify({"ok": False,
                            "err": (e or out or "撤销暂存失败").strip()[:2000]}), 500
    _st_memo_inval(wc)
    return jsonify({"ok": True})


@vcs_bp.route("/api/vcs/discard", methods=["POST"])
def vcs_discard():
    """丢弃工作区改动（**不可逆**）。body: {root, paths[], confirm:true}

    必须 confirm=true；执行前把当前内容快照到数据目录并在响应里回报路径。
    语义 = 「回到 HEAD 状态」：工作区 + 暂存区一起还原（a650 审计 P2-1——
    旧实现只 checkout 工作区，已 add 的内容原样留在 index 里，下一次提交
    照样带出去，可前端却说「已丢弃」）。
    """
    data = request.get_json(force=True, silent=True) or {}
    vcs, wc, err, _tool_ok = _guard(data.get("root"), need_tool=True)
    if err:
        return err
    if not data.get("confirm"):
        return jsonify({"ok": False,
                        "err": "丢弃改动不可逆，需带 confirm=true 明确确认"}), 400
    paths = [str(p).replace("\\", "/").rstrip("/")
             for p in (data.get("paths") or []) if p]
    if not paths or any(_bad_rel(p) for p in paths):
        return jsonify({"ok": False, "err": "未选择文件或路径非法"}), 400

    removed, failed = [], []
    with _root_lock(wc):
        # 快照必须在锁内（P2-5）：否则可能读到别的写操作中途的状态，
        # 留底内容不等于实际被丢弃的内容。
        snap, snap_err = _snap_discard(wc, paths)
        if vcs == "git":
            rc, out, _e = _run(["git", "-c", "core.quotepath=false", "ls-files",
                                "--others", "--exclude-standard", "-z", "--"] + paths,
                               wc, VCS_TIMEOUT_RO)
            untracked = [x for x in out.split("\0") if x] if rc == 0 else []
            uset = set(untracked)
            for p in list(paths):
                if p in uset:
                    try:
                        os.remove(os.path.join(wc, *p.split("/")))
                        removed.append(p)
                        paths.remove(p)
                        continue
                    except OSError as e:
                        failed.append("%s（%s）" % (p, e))
                        paths.remove(p)
                        continue
                # 未纳管**目录**（P2-2）：ls-files 只列目录内文件，目录名
                # 本身不在集合里。要求目录下全部文件都未纳管才整体删除。
                pre = p + "/"
                kids = [x for x in untracked if x.startswith(pre)]
                if not kids:
                    continue
                rc2, out2, _e2 = _run(["git", "ls-files", "-z", "--", p],
                                      wc, VCS_TIMEOUT_RO)
                if rc2 != 0 or [x for x in out2.split("\0") if x]:
                    continue                      # 目录里混有已纳管文件，交给 git
                try:
                    shutil.rmtree(os.path.join(wc, *p.split("/")))
                    removed.append(p)
                except OSError as e:
                    failed.append("%s（%s）" % (p, e))
                paths.remove(p)
            if paths:
                rc, out, e = _run(["git", "restore", "--source=HEAD",
                                   "--staged", "--worktree", "--"] + paths,
                                  wc, VCS_TIMEOUT_RW)
                if rc != 0:
                    # 老 git（< 2.23）没有 restore；checkout HEAD 同时改
                    # index 与工作区，语义等价（但必须带 HEAD，绝不能是把
                    # 分支名当 pathspec 的 `checkout -- <name>`）
                    rc, out, e = _run(["git", "checkout", "HEAD", "--"] + paths,
                                      wc, VCS_TIMEOUT_RW)
                if rc != 0:
                    failed.append((e or out or "git 还原失败").strip()[:1000])
        else:
            # P2-3：`svn status -q` 会隐藏 unversioned（? 项），拿它判
            # 未纳管恒为空集——旧实现因此对 svn 的未纳管文件静默什么都没做。
            rc, out, _e = _run(["svn", "status"] + [
                os.path.join(wc, *p.split("/")) for p in paths],
                wc, VCS_TIMEOUT_RO)
            untracked = set()
            if rc == 0:
                for ln in out.splitlines():
                    if not ln.startswith("?"):
                        continue
                    ap = ln[1:].strip()
                    try:
                        rel = os.path.relpath(ap, wc).replace("\\", "/")
                    except ValueError:            # 跨盘符（理论上不可达）
                        continue
                    untracked.add(rel)
            for p in list(paths):
                here = os.path.join(wc, *p.split("/"))
                if p in untracked:
                    try:
                        if os.path.isdir(here) and not os.path.islink(here):
                            shutil.rmtree(here)
                        else:
                            os.remove(here)
                        removed.append(p)
                    except OSError as e:
                        failed.append("%s（%s）" % (p, e))
                    paths.remove(p)
            if paths:
                rc, out, e = _run(["svn", "revert"] + [
                    os.path.join(wc, *p.split("/")) for p in paths],
                    wc, VCS_TIMEOUT_RW)
                if rc != 0:
                    failed.append((e or out or "svn revert 失败").strip()[:1000])
        _st_memo_inval(wc)

    body = {"ok": not failed, "removed": removed}
    if snap:
        body["snapshot"] = snap
    if snap_err:
        body["snapshot_err"] = snap_err
    elif not snap:
        body["snapshot_err"] = "没有可快照的内容（目标已不存在）"
    if failed:
        body["err"] = "；".join(failed)[:2000]
        return jsonify(body), 500
    return jsonify(body)


@vcs_bp.route("/api/vcs/tags", methods=["POST"])
def vcs_tags():
    """标签。body: {root, action: list|create|delete, name?, message?, rev?}"""
    data = request.get_json(force=True, silent=True) or {}
    vcs, wc, err, _tool_ok = _guard(data.get("root"), need_tool=True)
    if err:
        return err
    if vcs != "git":
        return jsonify({"ok": False,
                        "err": "svn 用 tags 目录约定，没有标签命令"}), 400
    act = str(data.get("action") or "list")
    if act == "list":
        rc, out, e = _run(["git", "for-each-ref",
                           "--format=%(refname:short)\x1f%(objectname:short)"
                           "\x1f%(contents:subject)", "refs/tags"],
                          wc, VCS_TIMEOUT_RO)
        if rc != 0:
            return jsonify({"ok": False, "err": e or "读取标签失败"}), 500
        tags = []
        for ln in out.splitlines():
            p = ln.split("\x1f")
            if len(p) >= 3:
                tags.append({"name": p[0], "rev": p[1], "msg": p[2]})
        return jsonify({"ok": True, "tags": tags})
    name = str(data.get("name") or "").strip()
    if not name or not _git_ref_ok(name):
        return jsonify({"ok": False, "err": "标签名非法"}), 400
    with _root_lock(wc):
        if act == "create":
            msg = str(data.get("message") or "").strip()
            rev = str(data.get("rev") or "").strip()
            # a650 审计 P3：tag 的 rev 位置只接受明确的提交/标签引用——
            # `@{1}` 这类 reflog 写法 _git_ref_ok 放行但语义是「上次 checkout
            # 的提交」，会把标签打歪。
            if rev and (not _git_ref_ok(rev) or "@{" in rev):
                return jsonify({"ok": False, "err": "修订引用非法"}), 400
            if msg:
                argv = ["git", "tag", "-a", name, "-m", msg] + ([rev] if rev else [])
            else:
                argv = ["git", "tag", name] + ([rev] if rev else [])
            rc, out, e = _run(argv, wc, VCS_TIMEOUT_RW)
        elif act == "delete":
            rc, out, e = _run(["git", "tag", "-d", "--", name], wc, VCS_TIMEOUT_RW)
        else:
            return jsonify({"ok": False, "err": "未知 action"}), 400
        if rc != 0:
            return jsonify({"ok": False,
                            "err": (e or out or "标签操作失败").strip()[:2000]}), 500
    return jsonify({"ok": True})


@vcs_bp.route("/api/vcs/push", methods=["POST"])
def vcs_push():
    """推送到远端（只在用户显式点击时执行）。body: {root, remote?, branch?, set_upstream?}"""
    data = request.get_json(force=True, silent=True) or {}
    vcs, wc, err, _tool_ok = _guard(data.get("root"), need_tool=True)
    if err:
        return err
    if vcs != "git":
        return jsonify({"ok": False, "err": "svn 由 commit 直接入库，无 push"}), 400
    cur = _git_current_branch(wc)
    remote = str(data.get("remote") or "origin").strip()
    branch = str(data.get("branch") or cur).strip()
    if not branch:
        return jsonify({"ok": False, "err": "当前处于游离 HEAD，请指定分支"}), 400
    if not _git_ref_ok(remote) or not _git_ref_ok(branch):
        return jsonify({"ok": False, "err": "远端名或分支名非法"}), 400
    argv = ["git", "push"]
    if data.get("set_upstream"):
        argv.append("-u")
    # a650 审计 P1-1：分支名直接当 refspec 时，以 "+" 开头会被 git 解析成
    # 「强制推送」。写成完整 ref → ref 的 refspec，`+` 只可能出现在名字中间，
    # 语义固定；推不上（非快进）由 git 报错，绝不静默强推。
    argv += [remote, "%s:%s" % (_branch_ref(branch), _branch_ref(branch))]
    with _root_lock(wc):
        rc, out, e = _run(argv, wc, VCS_TIMEOUT_NET)
        if rc != 0:
            text = (e or out or "").strip()
            hint = ""
            if "rejected" in text or "non-fast-forward" in text:
                hint = ("远端有你本地没有的提交——请先 Pull"
                        "（本工具只做 --ff-only，分叉需命令行合并）")
            return jsonify({"ok": False,
                            "err": hint or text[:4000] or "推送失败",
                            "out": text[:4000]}), 500
    _st_memo_inval(wc)
    return jsonify({"ok": True, "out": (out or "").strip()[:4000]})


@vcs_bp.route("/api/vcs/fetch", methods=["POST"])
def vcs_fetch():
    """只取远端引用不合并（update 是 pull --ff-only）。body: {root, remote?}"""
    data = request.get_json(force=True, silent=True) or {}
    vcs, wc, err, _tool_ok = _guard(data.get("root"), need_tool=True)
    if err:
        return err
    if vcs != "git":
        return jsonify({"ok": False, "err": "svn 用 update"}), 400
    remote = str(data.get("remote") or "").strip()
    if remote and not _git_ref_ok(remote):
        return jsonify({"ok": False, "err": "远端名非法"}), 400
    argv = ["git", "fetch", "--prune"] + ([remote] if remote else [])
    with _root_lock(wc):
        rc, out, e = _run(argv, wc, VCS_TIMEOUT_NET)
        if rc != 0:
            return jsonify({"ok": False,
                            "err": (e or out or "fetch 失败").strip()[:4000]}), 500
    _st_memo_inval(wc)
    return jsonify({"ok": True, "out": (out or "").strip()[:4000]})
