# -*- coding: utf-8 -*-
"""应用共享状态与配置工具。
集中管理跨模块共享的全局状态（连接表/AI 订阅/日志索引/MCP 调用记录/序列号）
及路径常量、配置/命令库读写、序列号生成。各功能模块从此 import。
"""
import os, sys, json, threading, itertools

# ---- 路径常量 ----
# app_state 在 src/ 下，上溯两层到项目根（server/main 等也从 src/ 以 src.* 引用本模块）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def _resource_base():
    return getattr(sys, "_MEIPASS", BASE_DIR)
RES_DIR = _resource_base()

# ---- home 锚点（用户定调：只有这两样放 home，data_dir 只管数据）----
# endpoint.json：MCP 服务发现锚点，路径必须固定（main/mcp_server/
#   harness_ask_mcp 各自本地定义 STATE_DIR=HOME_DIR 读写它，不随数据目录走）
# config.json：配置本体（含 data_dir），也需稳定位置——数据目录本身由它决定，
#   不能随数据目录搬。用户指定的 data_dir 只是现有数据所在，不含这两样。
HOME_DIR = os.path.join(os.path.expanduser("~"), ".serialconsole_pro")
CONFIG_FILE = os.path.join(HOME_DIR, "config.json")

def _app_dir():
    """应用目录（exe 所在目录 / 源码项目根）——**用户数据必须落这里**。

    a594（真实事故：同事升完级机器人凭据全没了）：打包形态下
    `__file__` 是 `<app>/_internal/src/app_state.pyd`，BASE_DIR 上溯两层得到
    `<app>/_internal` —— 于是默认数据目录变成 `<app>/_internal/data`。
    updater 的升级 bat 只把 `<app>/data` 从备份搬回（那一层根本没有用户数据），
    于是每次升级后：凭据/session/命令库全部「消失」，用户被迫重填，
    旧数据还静静躺在 `_internal/data` 里。
    修：frozen 一律用 exe 所在目录；源码运行仍用项目根（两者 BASE_DIR 相同
    时行为不变）。"""
    if getattr(sys, "frozen", False):
        try:
            return os.path.dirname(os.path.abspath(sys.executable))
        except Exception:
            pass
    return BASE_DIR


APP_DIR = _app_dir()


def _looks_like_user_data(p):
    """判断目录里是否有**有价值的**用户数据（凭据/命令库/笔记）。

    用于区分「真空目录」与「曾经装过数据的旧位置」。判据刻意不收 logs/
    webview_cache/nav/skill_cache —— 它们要么每次启动必建（空 logs/ 会让
    任意同名目录都被认成「有数据」，进而触发搬几百 MB 的误判），要么可
    再生。a602 审计：旧版 _internal/data/logs 曾经足以让归位逻辑在导入期
    同步搬 797MB，直接违反「不许拖慢启动」。

    定义必须早于 DATA_DIR 的顶层判定（a594 兼容兜底要调用它）——Python
    顶层按执行顺序解析名字，放后面会被 try/except 静默吞成 no-op。"""
    for name in ("hiklink_session.json", "lanz_credentials.json",
                 "lanz_login_marks.json", "cmdlib.json", "proxy_state.json",
                 "retry_config.json", "skill_meta.json", "pw_pending_del.json"):
        if os.path.exists(os.path.join(p, name)):
            return True
    # 笔记目录：空目录不算（用户可能只是打开过工具没写过笔记）
    files = os.path.join(p, "files")
    try:
        if os.path.isdir(files) and os.listdir(files):
            return True
    except OSError:
        pass
    return False


def _default_data_dir():
    """数据目录（日志/笔记/缓存）默认值。用户定调（v2.2.2）：
    - 未指定路径 → 统一在工具目录下建英文名文件夹 data（源码=项目根\\data，
      exe=exe 旁\\data），所有数据都进这里，备份工具目录即备份全部数据
    - 不允许临时目录——工具目录不可写时不偷偷落到别处（凭据会散落两处，
      同事机实锤踩坑），保持指向工具目录并记录告警：登录等写盘操作会
      显式报错，引导用户把工具挪到可写目录
    - 实际生效值可被 config.json 的 data_dir 覆盖（设置界面可改+迁移），
      迁移后以迁移的为准
    a594：候选目录改用 APP_DIR（exe 旁），不再用 BASE_DIR（打包版指向
    _internal/）——见 _app_dir 注释里的真实事故。"""
    cand = os.path.join(APP_DIR, "data")
    try:
        os.makedirs(cand, exist_ok=True)
        # 真实写测试替代 os.access——W_OK 在受控目录/网络盘上会误报可写
        probe = os.path.join(cand, ".wprobe")
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
    except Exception as e:
        import logging
        logging.getLogger("app_state").error(
            "数据目录不可写：%s（%s）——请把工具移到可写目录后重启，"
            "登录/凭据等写盘操作将失败", cand, e)
    return cand

def _load_home_config():
    """读 home 锚点 config.json；损坏时自动回退 .bak（a242：进程强杀半写/
    磁盘异常后的自愈——上一版由 cfg_commit 滚动留底），再不行回空配置。"""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        pass
    try:
        with open(CONFIG_FILE + ".bak", "r", encoding="utf-8") as f:
            d = json.load(f)
        logging.getLogger("app_state").warning(
            "config.json 损坏，已从 .bak 自动恢复")
        try:
            import shutil as _sh
            _sh.copyfile(CONFIG_FILE + ".bak", CONFIG_FILE)
        except OSError:
            pass
        return d
    except Exception:
        return {}

_HOME_CFG = _load_home_config()
# 数据目录：config 的 data_dir > 默认值（config 里旧的 log_dir 是单独日志目录，继续生效）
# v2.2.2 用户定调：迁移/指定过的 data_dir 以它为准；默认=工具目录\data。
# makedirs 失败不换临时目录（同 _default_data_dir 口径），保持指向并让
# 写盘操作显式报错
DATA_DIR = _HOME_CFG.get("data_dir") or _default_data_dir()
# a594 兼容兜底：config 里的 data_dir 指向已不存在的路径（换机器/删目录/
# 盘符变更）时，`os.makedirs(exist_ok=True)` 会**新建一个空目录**——用户看到
# 的是「凭据/笔记全没了」，而真实数据可能仍在默认位置。
#
# a602 审计修正：**只改运行时内存值，绝不改写 config.json**。原实现会永久
# 改写配置，而「路径暂时不可用」（移动硬盘/网络盘没插、UNC 没挂）和「永久
# 失效」在启动那一刻无法区分——写回去等于制造两份数据（默认目录一份、原盘
# 接回来后又是一份），正是 a594 要消灭的分裂。运行时回落 + 明确日志已经够
# 让用户找回数据；盘接回来的下次启动配置照旧生效。
# 判据：配置值不存在、且默认位置**确实有有价值数据**、且两者不同。
try:
    _cfg_dd = _HOME_CFG.get("data_dir")
    if _cfg_dd and not os.path.isdir(_cfg_dd):
        _def_dd = _default_data_dir()
        if (_looks_like_user_data(_def_dd) and
                os.path.normpath(_def_dd) != os.path.normpath(_cfg_dd)):
            import logging as _lg
            _lg.getLogger("app_state").warning(
                "配置的数据目录当前不可用（未挂载/已删？），本次启动临时使用"
                "默认目录：原配置 %s → %s。若原路径恢复可用，重启即可继续"
                "使用该目录；配置未做改动。", _cfg_dd, _def_dd)
            DATA_DIR = _def_dd
except Exception:
    pass
try:
    os.makedirs(DATA_DIR, exist_ok=True)
except Exception as e:
    import logging
    logging.getLogger("app_state").error(
        "数据目录创建失败：%s（%s）——请检查路径权限", DATA_DIR, e)
# ⚠ 命名陷阱：本处 STATE_DIR=数据目录（mm_probe/迁移逻辑用）；而 main/
# mcp_server/harness_ask_mcp 各自本地定义的 STATE_DIR=HOME_DIR
# （endpoint.json 锚点）。同名不同义，互不相干——endpoint/config 永远固定
# HOME_DIR，不随 data_dir 迁移（用户定调：指定目录只是数据所在）
STATE_DIR = DATA_DIR

# ---- 用户数据写盘通知（a602）----
# 凭据镜像（cred_mirror）要「写盘就备份」，而不是定时轮询整个数据目录。
# app_state 不能反向 import cred_mirror（循环依赖），故留一个钩子表：
# cred_mirror 启动时注册回调，各写入点在落盘成功后调用 notify_user_file_written。
_write_hooks = []

def notify_user_file_written(name):
    """告知「数据目录下的某个用户文件刚写完」。回调异常一律吞掉——
    备份是尽力而为，绝不能因为备份失败影响正常写盘。"""
    for cb in _write_hooks:
        try:
            cb(name)
        except Exception:
            pass


def replace_retry(src, dst, tries=6, wait=0.02):
    """os.replace 带短重试。a602：备份镜像会短暂读同一文件（Windows 下
    默认 open() 不带 FILE_SHARE_DELETE），替换可能吃 PermissionError；
    而这绝不能让**业务落盘**失败——重试几次一般就过去了。
    其它 OSError（磁盘满、路径非法）不重试，直接抛给调用方如实报错。"""
    last = None
    for i in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError as e:
            last = e
            if i + 1 < tries:
                import time
                time.sleep(wait)
    raise last

# 日志目录：config 旧 log_dir（老用户自定义过）> 数据目录/logs
DEFAULT_LOG_DIR = os.path.join(DATA_DIR, "logs")
# 命令库持久化（跨端口/重启保留）——数据目录内（备份数据目录即备份全部用户数据）。
# 旧版本在 BASE_DIR/cmdlib.json：启动自动归位到数据目录（不覆盖，删旧位置）。
CMD_LIB_FILE = os.path.join(DATA_DIR, "cmdlib.json")

def _merge_small_first(src_dir, dst_dir):
    """导入期同步搬**小凭据**（白名单 + 根级小 json），大目录留给后台。
    a602：启动路径上几 KB 无感；几百 MB 的 nav/logs/webview_cache 绝不
    在这里动——凭据回来后用户立刻能用，其余数据后台慢慢搬。"""
    try:
        names = os.listdir(src_dir)
    except Exception:
        return
    for name in names:
        s = os.path.join(src_dir, name)
        d = os.path.join(dst_dir, name)
        try:
            if os.path.exists(d):
                continue
            if os.path.isdir(s):
                continue          # 目录一律留后台（files/logs/nav...）
            st_ = os.stat(s)
            if st_.st_size > 512 * 1024:
                continue          # 大文件也留后台
            _move_no_overwrite(s, d)
        except FileExistsError:
            continue              # 新位置已有 → 以它为准
        except Exception:
            continue


def _merge_dir_into(src_dir, dst_dir):
    """把 src_dir 的子项逐个搬进 dst_dir：目标已有同名 → **不覆盖**（新位置
    优先），跳过。返回 (搬入数, 失败数)。全部搬完且源目录空才删源目录。"""
    import shutil
    moved = failed = 0
    try:
        names = os.listdir(src_dir)
    except Exception:
        return 0, 0
    for name in names:
        s = os.path.join(src_dir, name)
        d = os.path.join(dst_dir, name)
        try:
            if os.path.exists(d):
                failed += 1        # 新位置已有 → 保留两者，不覆盖
                continue
            _move_no_overwrite(s, d)
            moved += 1
        except FileExistsError:
            failed += 1            # 并发创建：以新位置为准
        except Exception:
            failed += 1
    if not failed:
        try:
            if not os.listdir(src_dir):
                os.rmdir(src_dir)
        except Exception:
            pass
    return moved, failed


def _move_no_overwrite(src, dst):
    """搬运且**绝不覆盖目标**（a602 审计 P2：shutil.move 对已存在目标会
    静默覆盖，exists 判断与真正搬运之间的窗口能顶掉用户刚写的凭据）。
    文件用 os.link 原子「不存在才创建」；不支持硬链接的盘回退 O_EXCL 复制。
    目录用 os.rename（Windows 下目标已存在会直接失败，不会覆盖）。

    a616（疯狗审计 v4）：**目录跨卷**。os.rename 跨盘符（C: → D:）抛
    FileExistsError 之外的 OSError(EXDEV)，调用方一口吞掉——该目录永远
    迁不过去且每次启动重试（永动循环）。数据目录被指定到另一块盘是这个
    功能的真实场景，旧代码 shutil.move 天生跨卷，为了不覆盖不能把跨卷
    能力一起切掉。目录 rename 失败时降级为递归「逐项 _move_no_overwrite
    + makedirs」，仍然绝不覆盖。
    """
    import shutil
    if os.path.isdir(src):
        try:
            os.rename(src, dst)      # 目标存在 → 抛错，由调用方按「已有」处理
            return
        except FileExistsError:
            raise
        except OSError:
            # 跨卷（EXDEV）或无权限 rename：降级逐项搬运。目标已有同名的
            # 项跳过（绝不覆盖），不能让一个 FileExistsError 中断整个目录
            # ——否则排在它后面的项全部迁不过去。
            os.makedirs(dst, exist_ok=True)
            leftover = False
            for name in os.listdir(src):
                try:
                    _move_no_overwrite(os.path.join(src, name),
                                       os.path.join(dst, name))
                except FileExistsError:
                    leftover = True      # 新位置已有 → 保留两者
                except OSError:
                    leftover = True      # 单项失败：留在源目录下次重试
            try:
                if not leftover and not os.listdir(src):
                    os.rmdir(src)        # 空目录才删得掉
            except OSError:
                pass
            return
    try:
        os.link(src, dst)
    except FileExistsError:
        raise
    except OSError:
        fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     getattr(os, "O_BINARY", 0))
        try:
            with os.fdopen(fd, "wb") as out:
                with open(src, "rb") as inp:
                    shutil.copyfileobj(inp, out)
        except Exception:
            try:
                os.remove(dst)
            except OSError:
                pass
            raise
    try:
        os.remove(src)
    except OSError:
        pass


def _legacy_data_sources():
    """a594：枚举所有可能藏着用户数据的旧位置（按可信度排序）。

    覆盖真实升级路径（内置升级会留下 `<app>.bak-<时间戳>/` 备份目录，
    其中的 `_internal/data` 才是旧版实际写入位置）：
      1. `<app>/_internal/data`        —— 本版之前的错位位置（升级后仍在）
      2. `<parent>/<app>.bak-*/_internal/data` —— 升级备份里的错位位置
      3. `<parent>/<app>.bak-*/data`           —— 升级备份里 bat 搬回的那层
      4. `<parent>/<app>.bak-*/` 下任意 `*_internal/data`（嵌套壳目录兜底）
    只返回「确实像用户数据」且不等于当前 DATA_DIR 的目录。
    """
    out = []
    cur = os.path.normpath(DATA_DIR)
    cands = []
    if getattr(sys, "frozen", False):
        cands.append(os.path.join(BASE_DIR, "data"))          # <app>/_internal/data
        try:
            parent = os.path.dirname(APP_DIR)
            prefix = os.path.basename(APP_DIR) + ".bak-"
            for name in sorted(os.listdir(parent), reverse=True):   # 时间戳倒序：最新优先
                if not name.startswith(prefix) or name == prefix:
                    continue
                bak = os.path.join(parent, name)
                if not os.path.isdir(bak):
                    continue
                cands.append(os.path.join(bak, "data"))
                # 嵌套壳目录形态（zip 顶层带应用名壳）：<bak>/<app>/_internal/data
                try:
                    for sub in os.listdir(bak):
                        sp = os.path.join(bak, sub)
                        if os.path.isdir(sp):
                            cands.append(os.path.join(sp, "_internal", "data"))
                except Exception:
                    pass
                cands.append(os.path.join(bak, "_internal", "data"))
        except Exception:
            pass
    seen = set()
    for p in cands:
        try:
            p = os.path.normpath(p)
            if p in seen or p == cur:
                continue
            seen.add(p)
            if os.path.isdir(p) and _looks_like_user_data(p):
                out.append(p)
        except Exception:
            continue
    return out


def _merge_log_dir(legacy, final_logs):
    """把一个旧日志目录递归并入 data/logs（后台线程调用）。
    宁可留旧目录也不能丢文件：全部条目处理成功才删源。

    a616（疯狗审计 v4）：原实现把「子目录在目标侧不存在」也记进 unmerged，
    而它自己从不创建这些子目录 —— 于是**空子目录**永远算未合并，源目录
    永远删不掉，每次启动重扫同一批死目录（永动巡逻）。另外 `merged_this
    and not unmerged` 的删除条件让「源里全是已存在同名文件」的情形也永远
    收敛不了（merged_this=0）。改为：子目录直接建（只建目录不覆盖文件），
    只要没有复制失败就删源。
    """
    import shutil
    merged_this = 0
    unmerged = []
    for root, dirs, files in os.walk(legacy):
        rel = os.path.relpath(root, legacy)
        droot = final_logs if rel == "." else os.path.join(final_logs, rel)
        os.makedirs(droot, exist_ok=True)
        for fn in files:
            s, d = os.path.join(root, fn), os.path.join(droot, fn)
            if os.path.exists(d):
                continue
            try:
                # 目标已存在时 copy2 会覆盖——外面已判 exists，但并发窗口
                # 仍可能顶掉；用独占创建保住「不覆盖」语义
                with open(s, "rb") as inp:
                    fd = os.open(d, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                                 getattr(os, "O_BINARY", 0))
                    with os.fdopen(fd, "wb") as out:
                        shutil.copyfileobj(inp, out)
                try:
                    shutil.copystat(s, d)
                except OSError:
                    pass
                merged_this += 1
            except FileExistsError:
                pass                    # 并发创建：以新位置为准
            except Exception:
                unmerged.append(fn)
        for dn in dirs:                 # 只建目录，绝不覆盖已有内容
            try:
                os.makedirs(os.path.join(droot, dn), exist_ok=True)
            except OSError:
                unmerged.append(dn + os.sep)
    if not unmerged:
        shutil.rmtree(legacy, ignore_errors=True)
    return merged_this, unmerged


def _migrate_legacy_user_data():
    """旧位置用户数据自动归位到数据目录（防「找不到了」，不阻塞启动）：
    - BASE_DIR/cmdlib.json → DATA_DIR/cmdlib.json
    - 旧日志（BASE_DIR/serial_logs/ 及其历史形态 ~/.serialconsole_pro/logs、
      旧数据目录 logs）→ 一律并入 DATA_DIR/logs（目录合一：只留一个 logs），
      并清掉 config.log_dir 让其走默认——日志库从此只认 data/logs。
    - a594：`<app>/_internal/data`、升级备份 `<app>.bak-*/.../data` →
      `<app>/data`。打包版曾把默认数据目录算成 _internal/ 下（见 _app_dir
      注释），升级后旧凭据/session/命令库都留在那些位置；自动搬回来，
      否则用户看到「凭据没了、要重配」。
    归位原则：新位置已有同名不覆盖；全部搬入成功才删旧目录。"""
    import shutil
    try:
        # a594：先把错位的用户数据整体归位——必须排在 cmdlib/logs 归位之前
        # （那些逻辑把 BASE_DIR/data 当旧位置，顺序反了会对刚搬完的目录重复处理）
        # 归位目标是**实际生效的** DATA_DIR：用户若在设置里指定过数据目录，
        # 数据就该落那儿，不能硬塞进 app/data 造成两份。
        # 短路：DATA_DIR 已有用户数据 = 正常在用的机器，不必去翻历史目录
        #（.bak-*/ 里可能有几十万文件，listdir 有成本；也避免把旧机器的
        # 陈旧数据混进已正常的安装）
        #
        # a602 审计：**导入期只同步搬小凭据，大目录交给后台线程**。原实现
        # 在模块导入时 shutil.move 整个旧目录，实测同类目录 797MB（nav 110MB
        # + logs 66MB + webview_cache 600MB）；数据目录被指定到另一块盘时
        # 变成数百 MB 同步复制，界面无进度地卡住——直接违反「不许拖慢启动」。
        if getattr(sys, "frozen", False) and not _looks_like_user_data(DATA_DIR):
            target = DATA_DIR
            srcs = _legacy_data_sources()
            for src_dir in srcs:
                try:
                    os.makedirs(target, exist_ok=True)
                    _merge_small_first(src_dir, target)
                except Exception:
                    pass
            if srcs:
                def _bg_merge(srcs=srcs, target=target):
                    for src_dir in srcs:
                        try:
                            _merge_dir_into(src_dir, target)
                        except Exception:
                            pass
                try:
                    threading.Thread(target=_bg_merge, daemon=True,
                                     name="legacy-data-merge").start()
                except Exception:
                    pass
        # cmdlib.json
        legacy_cmd = os.path.join(BASE_DIR, "cmdlib.json")
        if os.path.isfile(legacy_cmd) and os.path.normpath(legacy_cmd) != os.path.normpath(CMD_LIB_FILE):
            if not os.path.exists(CMD_LIB_FILE):
                shutil.copy2(legacy_cmd, CMD_LIB_FILE)
            if os.path.exists(CMD_LIB_FILE):
                os.remove(legacy_cmd)
                # a602：命令库换了来源，通知一次（此刻钩子可能还没注册，
                # cred_mirror 的启动全量对齐会兜底）
                notify_user_file_written(os.path.basename(CMD_LIB_FILE))
        # 旧日志目录合并入 data/logs
        # a602 审计 P1：这里原先在导入期同步 os.walk + copy2，旧 serial_logs
        # 有几百 MB 时同样卡启动（用户红线：启动不许有耗时操作）。改为：
        # 导入期只建目录 + 修正 config.log_dir（微秒级），实际复制交后台线程。
        final_logs = os.path.join(DATA_DIR, "logs")
        os.makedirs(final_logs, exist_ok=True)
        legacy_log_dirs = [
            os.path.join(APP_DIR, "serial_logs"),                     # 旧版本工具目录
            os.path.join(BASE_DIR, "serial_logs"),                    # 旧版本工具目录（源码形态）
            os.path.join(BASE_DIR, "data", "serial_logs"),            # 上一版归位目标
            os.path.join(DATA_DIR, "serial_logs"),
        ]
        _pending = [p for p in legacy_log_dirs
                    if os.path.isdir(p) and
                    os.path.normpath(p) != os.path.normpath(final_logs)]
        if _pending:
            def _bg_merge_logs(dirs=_pending, dst=final_logs):
                import shutil as _sh
                for legacy in dirs:
                    try:
                        _merge_log_dir(legacy, dst)
                    except Exception:
                        pass
            try:
                threading.Thread(target=_bg_merge_logs, daemon=True,
                                 name="legacy-logs-merge").start()
            except Exception:
                pass
        # config.log_dir 指旧位置的 → 清掉走默认（data/logs）；指外部自定义的不动
        cfg = _load_config()
        old_ld = cfg.get("log_dir") or ""
        if old_ld and os.path.abspath(old_ld) != os.path.abspath(final_logs):
            # 指向的不是最终目录：若在已知旧位置集合内则清除（走默认合一）；
            # 指向完全外部目录的保留（用户特意自定义）
            known_old = {os.path.abspath(p) for p in legacy_log_dirs if os.path.isdir(p)}
            if os.path.abspath(old_ld) in known_old or os.path.abspath(old_ld).endswith("serial_logs"):
                cfg.pop("log_dir", None)
                _save_config(cfg)
                global LOG_DIR
                if not os.environ.get("SERIAL_LOG_DIR"):
                    LOG_DIR = final_logs
    except Exception:
        pass

_migrate_legacy_user_data()

# ---- 配置 ----
# v3.4.54：config.json 五方共写（roles/vision/prompts/routes×2/app_state/
# tftp）互不加锁、_save_config 还是裸 "w" 直写——撕裂一旦发生，各读方
# except 返回 {} 会让下一次任一保存把全量配置静默清零。收敛为：模块级
# _CONFIG_LOCK 串行化全部落盘 + 原子写（tmp+replace，唯一 tmp 名）+ 坏读
# .bad 隔离（对齐 harness meta.py 惯例）。
_CONFIG_LOCK = threading.Lock()

def cfg_read():
    """读 config.json。FileNotFoundError → {}；损坏（JSONDecodeError/
    OSError）→ 先改名 .bad 留档供人工找回，再当 {} 起步——坏内容绝不
    再经保存路径放大成全量清空。"""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception:
        try:
            os.replace(CONFIG_FILE, CONFIG_FILE + ".bad")
        except OSError:
            pass
        return {}

def cfg_commit(mutator):
    """原子读-改-写 config.json（锁内整事务）。mutator(d) 就地修改 d。
    返回 (ok, err)。读方语义：锁外热路径读不加锁（GIL 下瞬时陈旧可容忍），
    关键在坏文件已被 cfg_read 隔离、写方全部串行。
    a242：替换成功后把**上一版**内容留底到 config.json.bak（滚动一份）——
    误操作（清空 recent/roots 的端点被意外触发）与半写损坏后可手工恢复。
    上一版的字节在替换前从盘上读（本次写失败不动 .bak）。"""
    import time as _time
    with _CONFIG_LOCK:
        d = cfg_read()
        if not isinstance(d, dict):
            d = {}
        try:
            r = mutator(d)
            if isinstance(r, dict):
                d = r
            os.makedirs(HOME_DIR, exist_ok=True)
            _prev = None
            try:
                with open(CONFIG_FILE, "rb") as f:
                    _prev = f.read()   # 上一版字节（替换前留底）
            except OSError:
                pass
            tmp = "%s.tmp.%d.%d" % (CONFIG_FILE, os.getpid(), threading.get_ident())
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=1)
            try:
                os.replace(tmp, CONFIG_FILE)
            except PermissionError:
                _time.sleep(0.08)   # 目标被读句柄/杀软短暂持有：重试一次
                os.replace(tmp, CONFIG_FILE)
            if _prev:
                try:
                    with open(CONFIG_FILE + ".bak", "wb") as f:
                        f.write(_prev)
                except OSError:
                    pass
            return True, None
        except Exception as e:
            return False, str(e)

def _load_config():
    """读取持久化配置（home 锚点 config.json：数据目录/日志目录/主题/最近记录）。"""
    return cfg_read()

def _save_config(cfg):
    """保存配置到 home 锚点 config.json。整量替换语义（历史 22 调用点不
    改）；v3.4.54 起锁内原子写（此前裸 "w" 直写是撕裂的头号来源）。"""
    def _whole(d):
        d.clear()
        d.update(cfg)
    cfg_commit(_whole)

# 优先级：环境变量 > 配置文件 > 默认值
_cfg = _load_config()
LOG_DIR = os.environ.get("SERIAL_LOG_DIR") or _cfg.get("log_dir") or DEFAULT_LOG_DIR
COMMON_BAUDS = [9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600]

# ---- 命令库持久化 ----
def _load_cmd_lib():
    """读取持久化命令库 [{name, cmd}]。"""
    try:
        with open(CMD_LIB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 兼容旧格式：字符串数组 → [{name:'', cmd:旧值}]
        return [c if isinstance(c, dict) else {"name": "", "cmd": c} for c in data]
    except Exception:
        return []

CMD_LIB_BAK = CMD_LIB_FILE + ".bak"      # 上一版（每次写前滚动留底）
CMD_LIB_SNAP_DIR = CMD_LIB_FILE + ".snap"  # 最近 N 份带时间戳快照
CMD_LIB_SNAP_KEEP = 5


def _rotate_cmd_lib_backup():
    """写前把当前 cmdlib.json 留底（a645 用户实锤：命令库被清成一条
    `{"name":"a","cmd":"echo 1"}`，全盘无任何副本可恢复，只能从旧版安装
    目录里翻出来）。

    cfg_commit 早就做了同样的 .bak 滚动（a242），命令库这条一直漏着——
    它是用户手写的资产，比 config 更难重建。两层留底：
      · cmdlib.json.bak        上一版（覆盖即可，手工恢复首选）
      · cmdlib.json.snap/      最近 N 份带时间戳（防「连续两次异常写」把
                               .bak 也洗掉——真实事故里前端正是连续提交）
    """
    try:
        if not os.path.isfile(CMD_LIB_FILE):
            return
        import shutil
        import time as _t
        # 1) 滚动 .bak
        try:
            shutil.copy2(CMD_LIB_FILE, CMD_LIB_BAK)
        except OSError:
            pass
        # 2) 时间戳快照（同一秒内多次写只留最新一份，防抖）
        os.makedirs(CMD_LIB_SNAP_DIR, exist_ok=True)
        stamp = _t.strftime("%Y%m%d-%H%M%S", _t.localtime())
        snap = os.path.join(CMD_LIB_SNAP_DIR, "cmdlib-%s.json" % stamp)
        if not os.path.exists(snap):
            shutil.copy2(CMD_LIB_FILE, snap)
        snaps = sorted(os.listdir(CMD_LIB_SNAP_DIR))
        for old in snaps[:-CMD_LIB_SNAP_KEEP]:
            try:
                os.remove(os.path.join(CMD_LIB_SNAP_DIR, old))
            except OSError:
                pass
    except Exception:
        pass        # 留底失败绝不能挡住正常保存


def _save_cmd_lib(lib):
    """保存命令库到工具目录 cmdlib.json。（用户铁律：外部不得改命令库，仅工具 UI 写）
    a602：改原子写——裸 "w" 直写期间镜像线程可能读到半截 JSON。
    a645：写前滚动留底（见 _rotate_cmd_lib_backup）。"""
    tmp = None
    try:
        txt = json.dumps(lib, ensure_ascii=False, indent=2)
        tmp = "%s.%d.%d.tmp" % (CMD_LIB_FILE, os.getpid(),
                                threading.get_ident())
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(txt)
        _rotate_cmd_lib_backup()
        replace_retry(tmp, CMD_LIB_FILE)
        tmp = None
        notify_user_file_written(os.path.basename(CMD_LIB_FILE))
        return True
    except Exception:
        if tmp:
            try:
                os.remove(tmp)
            except Exception:
                pass
        # a616（疯狗审计 v3 #6）：原来这里一言不发——重试 6 次仍失败时
        # 用户的命令库改动就无声蒸发了（别的落盘点至少 log.warning）。
        # 至少留一条错误日志，让「保存失败」可被发现。
        try:
            import logging
            logging.getLogger("app_state").error(
                "命令库保存失败（改动未落盘）：%s", CMD_LIB_FILE,
                exc_info=True)
        except Exception:
            pass
        return False

# ---- 全局单调递增序列号 ----
# 作为分页/搜索的稳定游标（避免 ms 时间戳同值）
_SEQ_COUNTER = itertools.count(1)
_SEQ_LOCK = threading.Lock()

def _next_seq():
    with _SEQ_LOCK:
        return next(_SEQ_COUNTER)

# ---- 连接表（port_id -> SerialPort/SSHConnection）----
_ports = {}
_ports_lock = threading.Lock()

# ---- AI 接入层状态 ----
# AI 订阅：跨所有串口的全局流，AI 可实时获取所有串口数据
_ai_clients = []       # AI SSE Queue 列表
_ai_clients_lock = threading.Lock()

# 前端已打开的日志文件列表（前端上报，供 MCP/AI 查询"用户当前在看哪个日志"）
# 每项: {"name": 显示名, "path": 绝对路径或日志目录内文件名, "port_id": 前端 tab id, "total": 行数}
_open_logs = []
_open_logs_lock = threading.Lock()

# MCP 最近调用记录（mcp_server.py 通过 /api/ai/mcp_report 上报，前端状态面板展示）
# 每项: {"ts": 时间戳, "tool": 工具名, "args摘要": 参数摘要, "ok": 是否成功}
_mcp_calls = []
_mcp_calls_lock = threading.Lock()
_MCP_CALLS_MAX = 50

# ---- 日志索引缓存 ----
from .log_index import LogIndex
_log_index_cache = {}  # path -> LogIndex
_log_index_lock = threading.Lock()

def _get_log_index(path):
    """获取/缓存日志索引。每次调用都触发 build()——内部按 _built_size
    判断文件是否追加，未变则 O(1) 返回，追加则增量续扫。"""
    with _log_index_lock:
        if path not in _log_index_cache:
            _log_index_cache[path] = LogIndex(path)
        idx = _log_index_cache[path]
        idx.build()
        return idx

def _broadcast_to_ai(item):
    """串口有新行时，同时推给所有 AI 订阅者。
    队列满时丢最旧腾位，不移除客户端（避免误杀仍在消费的订阅者）。"""
    with _ai_clients_lock:
        for q in _ai_clients:
            try:
                q.put_nowait(item)
            except Exception:
                try:
                    q.get_nowait()
                    q.put_nowait(item)
                except Exception:
                    pass


# ---- Windows 保留设备名防线（a239 第5轮B1：CON/COM1 等设备名传给 open() 会
# 永久阻塞 worker 线程——flask threaded 下 30 并发即泄漏 30 线程不可回收）----
_WIN_RESERVED = ({"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
                 | {"COM%d" % i for i in range(1, 10)}
                 | {"LPT%d" % i for i in range(1, 10)})


def reject_win_devpath(path):
    """路径含 NUL 或 basename 命中 Windows 保留设备名 → True（调用方 400 拒）。
    CON.txt 这类「带扩展名的设备名」同样会打开设备，按去扩展名判定。"""
    try:
        s = str(path)
    except Exception:
        return True
    if not s:
        return False   # F10: 空路径=缺参语义，交调用方原校验
    if "\x00" in s:
        return True
    base = os.path.basename(s.rstrip(chr(92) + "/"))   # \ 与 /（避免源码转义歧义）
    # a250 P1（a247/a248复审实测推翻 a247 前提）：Windows 剥组件尾空白后与设备名
    # 比对——本机(win 19045)实测 "CON .txt" 家族 open() 内容写入控制台、read()
    # 永久阻塞（=a239 挂线程洞）。首段必须再 rstrip 点空格；a247 的"点前空格
    # =合法文件名"论断错误，其"解锁"的全是设备路径。整名预剥保留（无害）。
    b = base.rstrip(". ")
    stem = b.split(".")[0].rstrip(". ") if "." in b else b
    return stem.upper() in _WIN_RESERVED
