# -*- coding: utf-8 -*-
"""应用共享状态与配置工具。
集中管理跨模块共享的全局状态（连接表/AI 订阅/日志索引/MCP 调用记录/序列号）
及路径常量、配置/命令库读写、序列号生成。各功能模块从此 import。
"""
import os, sys, json, threading, itertools, time

# ---- 测试进程自动隔离（2026-11-23）----
# 必须在任何路径定义之前执行。
# 为什么需要：config 现在住在数据目录里，而源码形态下默认数据目录就是
# **项目根\\data**——任何导入 app_state 的测试都会在那儿读写真实的开发
# 配置。tests/conftest.py 只在 pytest 下加载；本项目多数测试是
# `python tests/xxx.py` 直接跑的（21 个带 __main__），那条路径上没有任何
# 隔离。所以由 app_state 自己认「我是不是在被测试」，是就把 FC_STATE_DIR
# 指到临时目录——自举链各处已认这个开关（锚点、默认数据目录、不读历史
# 位置、不写指针）。
# 判定依据（任一成立即是测试）：
#   ① 启动脚本在项目的 tests\\ 目录下，或 pytest 设了 PYTEST_CURRENT_TEST；
#   ② 环境里有 FC_TEST_CHILD——测试进程传下来的血缘标记。
# 正常运行（run.bat / exe / src\\main.py）不满足任一条，零影响。
# 显式已设 FC_STATE_DIR 的，尊重不改。
#
# 【血缘标记能管什么、管不了什么——2026-11-23 受控实验的实话】
# 能管：父进程**已经导入过 app_state**（于是已被标记）之后再起的子进程，
#       不论 argv[0] 是什么（`python -c`、其它脚本）都认得出。
# 管不了：测试文件自己不导入 app_state、却用 `python -c` 起子进程——
#       父进程从未被标记，子进程 argv[0] 是 "-c" 又认不出来，于是子进程
#       以「正常运行」身份读真实的锚点 config、把指针写进真实的 %APPDATA%
#       （tests/test_harness_version.py 实锤过，已在文件顶部显式设
#       FC_TEST_CHILD 修掉）。这类测试必须自己声明一次血缘标记。
# 所以：**隔离是否成立不能靠机制推定，要由子进程自报路径来验证**。
def _fc_test_isolation():
    if os.environ.get("FC_TEST_CHILD"):
        _is_test = True
    else:
        _argv0 = os.path.normcase(os.path.abspath(sys.argv[0] or "."))
        _tests_dir = os.path.normcase(
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "tests"))
        # pytest：`python -m pytest` 时 argv[0] 是 pytest 包里的 __main__.py；
        # `pytest`/`py.test` 命令时 argv[0] 以 pytest.exe / py.test.exe 结尾。
        # PYTEST_CURRENT_TEST 只在**每条用例执行期间**存在——收集阶段导入
        # 测试模块时还没设，而测试模块正是在那时导入 app_state 的，所以
        # 光靠它挡不住（第七轮 R7-1 实测：pytest 下隔离完全失效）。
        _a0 = _argv0.replace("/", os.sep)
        _pytest = (_a0.endswith(os.sep + "pytest" + os.sep + "__main__.py")
                   or _a0.endswith(os.sep + "pytest.exe")
                   or _a0.endswith(os.sep + "py.test.exe")
                   or bool(os.environ.get("PYTEST_CURRENT_TEST")))
        _is_test = (_argv0 == _tests_dir
                    or _argv0.startswith(_tests_dir + os.sep)
                    or _pytest)
    if _is_test:
        os.environ["FC_TEST_CHILD"] = "1"      # 血缘标记：传给所有后代进程
    if os.environ.get("FC_STATE_DIR"):
        return _is_test
    if not _is_test:
        return False
    import tempfile as _tf
    _root = os.path.join(_tf.gettempdir(), "fc_test_state_%d" % os.getpid())
    os.makedirs(os.path.join(_root, "data"), exist_ok=True)
    os.environ["FC_STATE_DIR"] = _root
    # R7-10：测试沙箱退出即清，不在 %TEMP% 里堆残骸（此前每跑一次留一个）
    try:
        import atexit as _ae
        import shutil as _sh
        _ae.register(_sh.rmtree, _root, True)
    except Exception:
        pass
    return True


FC_TEST_ISOLATED = _fc_test_isolation()

# ---- 路径常量 ----
# app_state 在 src/ 下，上溯两层到项目根（server/main 等也从 src/ 以 src.* 引用本模块）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def _resource_base():
    return getattr(sys, "_MEIPASS", BASE_DIR)
RES_DIR = _resource_base()

# ---- 锚点（2026-11-23 用户令：config 搬进工具目录的 data，%APPDATA% 只留最基础的）----
# 背景（事故实锤）：config.json 原先住在 %APPDATA%\...\backend\，卸载器清除
# 用户数据时会连它一起删，而且它**不在任何备份流程里**——丢了只能靠运气找回。
# 现行口径（用户令，最终版）：config.json **永远在 工具目录\data**。它是
# 「数据迁到了哪」的唯一记录者（config 里的 data_dir），所以自己不跟着数据走。
# 数据目录 = config 记的 data_dir（若那个目录存在），否则 工具目录\data。
# 没有指针文件、不读历史位置、不搬不借、不做兼容。详见下方「数据目录」一节。
# %APPDATA% 锚点只放最基础的东西：endpoint.json（服务发现，每轮重写）、
# 崩溃取证日志。
def _anchor_dir():
    _env = os.environ.get("FC_STATE_DIR")
    if _env:
        return _env
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "frontend-console-shell", "backend")


HOME_DIR = _anchor_dir()        # 锚点：endpoint.json 与取证日志，不放 config

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
    - 实际生效值**固定**为 `工具目录\\data`——config 的 data_dir 键不再参与
      启动决策（用户令 2026-11-23：不考虑任何其他位置）。
    a594：候选目录改用 APP_DIR（exe 旁），不再用 BASE_DIR（打包版指向
    _internal/）——见 _app_dir 注释里的真实事故。

    【隔离态】FC_STATE_DIR 已设时，默认数据目录 = <FC_STATE_DIR>\\data。
    此前这个开关只管锚点、不管数据目录——于是「设了隔离开关」的测试进程
    仍把 config 读写到真实的项目根\\data（2026-11-23 实锤：跑单元测试在
    项目根 data\\ 留下了一份被洗成 2 个键的 config 残片）。一个开关必须
    管住全部路径，隔离才算成立。"""
    _iso = os.environ.get("FC_STATE_DIR")
    cand = os.path.join(_iso, "data") if _iso else os.path.join(APP_DIR, "data")
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

def _bootstrap_anchor():
    """导入期引导：只确保锚点目录存在（endpoint.json 与取证日志的落点）。
    config 本体在数据目录里，锚点不承载它。
    FC_STATE_DIR 隔离态下同样只建目录，不碰任何历史位置的文件。"""
    try:
        os.makedirs(HOME_DIR, exist_ok=True)
    except Exception:
        pass


# ---- config：只住在工具目录的 data 里，别无分号 ----
# 【用户令 2026-11-23，最终版，不再改】
#   config.json 就在 工具目录\data\config.json。
#   不从任何别处读、不从任何别处搬、没有指针、不看历史位置、不考虑兼容。
#   没有它就以空配置起步；坏了自己用同目录的副本恢复。
# 这条规则之前的版本（指针文件 + 多处历史位置 + 按可信度挑）在今天 18:01
# 把用户 39 项设置覆盖成 2 项：它「去别处借了一份配置」，借到的是垃圾。
# 越复杂的找回逻辑，越多机会找错。所以只剩一条规则。
#
# 备份（用户令「本身要有备份」）——全部在**工具目录\data** 里，和 config 本体
# 在一起（数据目录迁走后，备份不能跟着走——否则本体在工具目录、备份在 D 盘，
# 工具目录一坏两边都指望不上）：
#   config.json.bak                 上一版（cfg_commit 每次保存滚动留底）
#   data_backup\config.json         镜像副本（cred_mirror，保存后通知）
# 自愈顺序：config.json 坏 → .bak → data_backup 镜像；都救不了 → 空配置起步，
# 但先把坏文件复制留证（.bad-<时间>），不让它被下一次保存悄悄盖掉。


def _read_cfg(p):
    # utf-8-sig：本仓库编辑链会产出带 BOM 的文件，裸 utf-8 会让 json.load 抛错
    with open(p, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def _selfheal_cfg():
    """读 工具目录/data/config.json；坏了按 .bak → data_backup 镜像 的顺序恢复。
    返回 dict。文件不存在 → {}。存在但坏且无处恢复 → {}（坏件已留证）。

    【恢复到的配置必须落盘】只在内存里用副本、盘上仍是坏文件的话，下一次
    保存会以坏文件为底——实测把配置洗成只剩新加的那 1 个键。所以：坏件复制
    成 .bad-<时间> 留证，再把可用副本写回 config.json。"""
    import logging
    import shutil as _sh
    main = CONFIG_FILE
    try:
        return _read_cfg(main)
    except FileNotFoundError:
        return {}
    except Exception:
        pass                       # 文件在但读不出：坏了，找副本
    for cand in (main + ".bak", CONFIG_BACKUP_FILE):
        try:
            d = _read_cfg(cand)
        except Exception:
            continue
        if not isinstance(d, dict) or not d:
            continue
        try:
            _stamp = time.strftime("%Y%m%d-%H%M%S")
            _sh.copy2(main, "%s.bad-%s" % (main, _stamp))      # 坏件留证
        except OSError:
            pass
        try:
            _sh.copyfile(cand, main)                           # 可用副本落盘
            logging.getLogger("app_state").warning(
                "config.json 损坏，已从 %s 恢复", os.path.basename(cand))
        except OSError:
            pass
        return d
    try:
        _stamp = time.strftime("%Y%m%d-%H%M%S")
        _sh.copy2(main, "%s.bad-%s" % (main, _stamp))
        logging.getLogger("app_state").warning(
            "config.json 损坏且没有可用的恢复副本，已留证为 config.json.bad-%s；"
            "本次以空配置起步", _stamp)
    except OSError:
        pass
    return {}


_bootstrap_anchor()
# ============================================================
# 数据目录——只有一条规则（用户令 2026-11-23，最终版，不再改）
#
#   config.json  永远在  工具目录\data\config.json   （不跟着数据走）
#   数据目录     = config 里记的 data_dir，若那个目录存在
#               否则 = 工具目录\data
#
# config.json 是「数据迁到了哪」的唯一记录者，所以它自己必须留在工具目录——
# 否则它跟着数据走了，就没人知道去哪找它。
# 不看任何别的位置，不做任何兼容，没有指针文件。没有 config 就空配置起步。
# ============================================================
TOOL_DATA_DIR = _default_data_dir()            # 工具目录\data
try:
    os.makedirs(TOOL_DATA_DIR, exist_ok=True)
except Exception as e:
    import logging
    logging.getLogger("app_state").error(
        "数据目录创建失败：%s（%s）——请检查路径权限", TOOL_DATA_DIR, e)

CONFIG_FILE = os.path.join(TOOL_DATA_DIR, "config.json")   # 固定，不随数据目录走
# config 的镜像副本：固定在 工具目录/data/data_backup（不随数据目录迁走）
CONFIG_BACKUP_FILE = os.path.join(TOOL_DATA_DIR, "data_backup", "config.json")
_HOME_CFG = _selfheal_cfg()


def _same_dir(a, b):
    """两个路径是否指向同一目录（忽略大小写与斜杠写法——Windows 路径
    d:\\X 和 D:\\x 是同一个目录，直接比字符串会误判成不同）。"""
    try:
        return (os.path.normcase(os.path.abspath(a))
                == os.path.normcase(os.path.abspath(b)))
    except Exception:
        return False


def _resolve_data_dir():
    """config 记了 data_dir 且那个目录存在 → 用它；否则 工具目录\\data。
    目录不存在时不认（a594）：移动硬盘没插时若认它，后面 makedirs 会凭空造出
    一个空的数据目录，用户看到的就是「数据全没了」。"""
    dd = _HOME_CFG.get("data_dir")
    if isinstance(dd, str) and dd.strip() and os.path.isdir(dd):
        return os.path.abspath(dd)
    return TOOL_DATA_DIR


DATA_DIR = _resolve_data_dir()
STATE_DIR = DATA_DIR
try:
    os.makedirs(DATA_DIR, exist_ok=True)
except Exception as e:
    import logging
    logging.getLogger("app_state").error(
        "数据目录创建失败：%s（%s）——请检查路径权限", DATA_DIR, e)
# 日志目录：config 旧 log_dir（老用户自定义过）> 数据目录/logs
DEFAULT_LOG_DIR = os.path.join(DATA_DIR, "logs")
# 命令库持久化（跨端口/重启保留）——数据目录内（备份数据目录即备份全部用户数据）。
CMD_LIB_FILE = os.path.join(DATA_DIR, "cmdlib.json")

# ---- 用户数据写盘通知（a602）----
# 凭据镜像（cred_mirror）要「写盘就备份」，而不是定时轮询整个数据目录。
# app_state 不能反向 import cred_mirror（循环依赖），故留一个钩子表：
# cred_mirror 启动时注册回调，各写入点在落盘成功后调用 notify_user_file_written。
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


# ---- 配置 ----
# v3.4.54：config.json 五方共写（roles/vision/prompts/routes×2/app_state/
# tftp）互不加锁、_save_config 还是裸 "w" 直写——撕裂一旦发生，各读方
# except 返回 {} 会让下一次任一保存把全量配置静默清零。收敛为：模块级
# _CONFIG_LOCK 串行化全部落盘 + 原子写（tmp+replace，唯一 tmp 名）+ 坏读
# .bad 隔离（对齐 harness meta.py 惯例）。
_CONFIG_LOCK = threading.Lock()
# a669：内存中最后一次成功读到的配置。读取侧 IO 故障时用它兜底——「读不到」
# 绝不能等价于「空的」，否则下一次任何字段级保存都会把整份配置写没。
_CFG_LAST = {"d": {}}

# a669（用户实锤 config 被洗成 2 个键）：只有「内容真的坏了」才允许隔离。
# 判定用 json.JSONDecodeError / UnicodeDecodeError；PermissionError、共享
# 冲突（WinError 32，另一个进程正持有）、杀软扫描占用等**读取侧 IO 故障
# 一律不算坏**——文件内容可能是完好的，改个名就永久把它踢出视线。
_CONFIG_CORRUPT_EXC = (json.JSONDecodeError, UnicodeDecodeError)
# 读侧 IO 故障重试次数（间隔递增，总计约 0.35s——杀软扫描窗口量级）
_CONFIG_READ_TRIES = 4


def _cfg_read_strict():
    """读 config.json，区分「不存在 / 内容坏 / 暂时读不到」三种情况。

    返回 (data, state)：
      · ("ok", dict)        正常
      · ("missing", {})     文件不存在（首次启动）
      · ("corrupt", {})     内容确实坏了（解析失败）——只有这种才隔离
      · ("io_error", None)  暂时读不到（占用/权限/IO 故障）——调用方**不得**
                            把它当空配置写回，否则就是全量清空
    """
    data = None
    state = "ok"
    for i in range(_CONFIG_READ_TRIES):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            state = "ok"
            break
        except FileNotFoundError:
            return None, "missing"
        except _CONFIG_CORRUPT_EXC:
            state = "corrupt"
            data = None
            break                      # 内容坏：重试没有意义
        except OSError:
            # 占用/权限/瞬时 IO：等一会儿再试，绝不在这里下结论
            state = "io_error"
            if i < _CONFIG_READ_TRIES - 1:
                time.sleep(0.05 * (i + 1))
    if state == "io_error":
        return None, "io_error"
    if not isinstance(data, dict):
        return None, "corrupt"
    return data, state


def cfg_read():
    """读 config.json。不存在 → {}；内容坏（JSON 解析失败）→ 隔离 .bad 后
    返回 {}；**暂时读不到 → 返回内存中最后一次成功读到的那份**（没有就用
    {}），绝不改名、绝不假装是空配置。

    a669：原实现把所有异常都当损坏——实测用户 config 内容完全合法（39 键），
    只因某次读取时被占用就走 os.replace 改名 .bad，随后任一写入点
    `_save_config({**_load_config(), ...})` 拿 {} 落盘 = 全量抹掉 37 个键
    （用户看到「首次启动」提示）。隔离判据现在只认解析失败。
    """
    data, state = _cfg_read_strict()
    if state == "ok":
        _CFG_LAST["d"] = data
        return data
    if state == "missing":
        return {}
    if state == "io_error":
        # 读不到 ≠ 空。返回上次成功读到的内容（初始为空，但至少不会主动清盘）
        import src.backend_log as _bl
        try:
            _bl.warn("config", "读取 config.json 暂时失败（占用/权限），"
                               "本次按上次成功读取的内容处理")
        except Exception:
            pass
        return dict(_CFG_LAST["d"] or {})
    # state == "corrupt"：内容确实解析不了，隔离留档
    try:
        os.replace(CONFIG_FILE, CONFIG_FILE + ".bad")
    except OSError:
        pass
    try:
        import src.backend_log as _bl
        _bl.error("config", "config.json 内容损坏（JSON 解析失败），已隔离为 "
                            "config.json.bad")
    except Exception:
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
        # a669：写前必须确认「读到的是真实内容」——暂时读不到（占用/权限）
        # 时不做任何写入，直接失败返回。否则以空 dict 为基线落盘 = 全量清空。
        d, _st = _cfg_read_strict()
        if _st == "io_error":
            return False, "config.json 暂时不可读（占用/权限），本次未写入"
        if not isinstance(d, dict):
            d = {}
        # 护栏基线 = 磁盘上刚读到的内容（不是内存缓存）：要防的是「这一次
        # 写入把盘上已有的配置写没」，拿盘上的现状比才对得上语义。
        _before = dict(d)
        try:
            r = mutator(d)
            if isinstance(r, dict):
                d = r
            # a669 护栏二：新配置比旧配置少了大量键 → 极可能是灾变（读失败/
            # 逻辑 bug 把内存配置洗空了），拒绝落盘并留现场。用户实锤场景：
            # 39 键被写成 2 键。
            # 判据必须收紧（a669 测试回归实锤）：只有**旧配置本身就健壮**
            # 才拦——空白配置起步、或本来就是小配置（测试夹具/新用户）时
            # 删几个键是正常操作，不能误伤。两个下限：旧配置 ≥ 8 键，
            # 且丢失 ≥ 5 键、≥ 40%。
            if _st == "ok" and isinstance(d, dict):
                old = _before
                if len(old) >= 8:
                    lost = len(set(old) - set(d))
                    if lost >= 5 and lost * 10 >= len(old) * 4:
                        try:
                            import src.backend_log as _bl
                            _bl.error(
                                "config", "拒绝写入：新配置比现有少 %d 个键"
                                          "（%d → %d），疑似内存配置被清空。"
                                          "现场：config.json.reject-%d"
                                          % (lost, len(old), len(d), int(_time.time())))
                        except Exception:
                            pass
                        try:
                            import shutil as _sh
                            _sh.copy2(CONFIG_FILE, CONFIG_FILE + ".reject-%d"
                                      % int(_time.time()))
                        except Exception:
                            pass
                        return False, "配置骤减 %d 键，拒绝写入" % lost
            # config 在数据目录里（不在锚点）——目录导入期已建，不再动 HOME_DIR
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
            if isinstance(d, dict):
                _CFG_LAST["d"] = d
            # 通知 cred_mirror 把 config 镜像进 data_backup\（此前 config 的
            # 保存从不通知——它也就从不在任何备份里；今天的事故正因如此）
            try:
                notify_user_file_written("config.json")
            except Exception:
                pass
            return True, None
        except Exception as e:
            return False, str(e)

def _load_config():
    """读取持久化配置（数据目录里的 config.json：数据目录/日志目录/主题/最近记录）。"""
    return cfg_read()

def _save_config(cfg):
    """保存配置到数据目录里的 config.json。整量替换语义（历史 22 调用点不
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
