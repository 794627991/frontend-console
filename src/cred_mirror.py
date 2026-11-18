# -*- coding: utf-8 -*-
"""凭据镜像备份（a602：防「先删旧包再解压新包」把凭据一起删掉）。

真实场景：同事升级时不走内置升级，而是手动删掉旧程序包再解压新的。
凭据默认就写在 DATA_DIR（= 程序包旁边的 data/），包一删凭据全没；home 里的
config.json 只剩一个指向已消失目录的 data_dir 指针。

用户定调（三条）：
1. **DATA_DIR 是唯一真源**，home 下的只是备份副本，任何时候都以 DATA_DIR 为准
2. **只放有价值的小文件**——凭据/命令库这类几十字节到几 KB 的 json；
   大文件（日志/笔记/附件/索引）绝不纳入（home 不是数据仓库）
3. **触发式备份，不轮询**——各写入点落盘成功后主动通知，正常情况下零开销

安全边界：
- 只镜像 _MIRROR_FILES 白名单，绝不遍历目录
- 单文件超过 _MAX_BYTES 跳过（防将来有东西变肥撑爆 home）
- 恢复只在「DATA_DIR 里一个凭据都不剩」时进行，且只补缺失，绝不覆盖
- 备份目录与 DATA_DIR 有包含关系时整体跳过（别把数据「备份」到自己身上）
"""
import logging
import os
import queue
import shutil
import threading
import time

import src.app_state as _st

# 有价值的凭据/配置小文件（全部实测 <2KB）
# a631（用户定调）：skill_meta.json 移出——技能装了哪些丢了顶重重装，不是
# 凭据也不在用户要备份的范围内（此前以「重装后可对账」纳入，撤销）
_MIRROR_FILES = (
    "hiklink_session.json",       # 机器人 app_id/app_secret/robot_uid（最重要）
    "hiklink_session.json.bak",   # 上一版，session 损坏时可回滚
    "lanz_credentials.json",      # lanz 账号密码（机器人也复用它登录）
    "lanz_login_marks.json",      # 各账号登录状态标记
    "cmdlib.json",                # 命令库
    "retry_config.json",          # 代理重试配置
    "proxy_state.json",           # 代理开关状态
    "pw_pending_del.json",        # 网页密码删除/修改挂起队列（加密 blob）
)

BACKUP_DIR = os.path.join(_st.HOME_DIR, "data_backup")
_MAX_BYTES = 256 * 1024          # 单文件上限：白名单里的都远小于此
_log = logging.getLogger("cred_mirror")
_last = {}                        # name -> (mtime_ns, size)，避免重复拷贝
_started = False
_warned_overlap = False
_lock = threading.Lock()
_q = queue.Queue()                # 待镜像文件名（去重由 _flush 内的 sig 比对负责）


def _sig(p):
    try:
        s = os.stat(p)
        return (s.st_mtime_ns, s.st_size)
    except OSError:
        return None


def _overlaps(a, b):
    """两个目录是否相同/互相包含。算不清就当重叠（宁可不备份，也不写坏）。"""
    try:
        a = os.path.normcase(os.path.abspath(a)).rstrip("\\/")
        b = os.path.normcase(os.path.abspath(b)).rstrip("\\/")
        return a == b or a.startswith(b + os.sep) or b.startswith(a + os.sep)
    except Exception:
        return True


def _read_bytes(path, limit):
    """把源文件读进内存后立刻关闭句柄。**绝不能长时间持有读句柄**：
    Windows 下 open() 默认不带 FILE_SHARE_DELETE，镜像读文件的那几毫秒里
    业务线程对同一路径做 os.replace/os.remove 会直接 PermissionError
    （实测 WinError 5 / 32）——备份反过来把正常写盘打挂。"""
    with open(path, "rb") as f:
        return f.read(limit + 1)


def _write_atomic(dst, data):
    """写目标文件：唯一 tmp 名 + os.replace。tmp 必须唯一——主进程与
    worker 进程会同时镜像同一个 home 目录，固定 tmp 名会互相踩。"""
    import tempfile
    d = os.path.dirname(dst) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=os.path.basename(dst) + ".",
                              suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            fd = None
            f.write(data)
        os.replace(tmp, dst)
        tmp = None
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if tmp is not None:
            try:
                os.remove(tmp)
            except OSError:
                pass


def _is_valid_json(data):
    """白名单里的文件都是 json。内容解析不了 = 读到写入中间态（业务侧
    非原子写的窗口），此时绝不能覆盖镜像——否则把坏内容永久化，
    下次恢复就是搬回一个坏凭据文件。"""
    import json
    try:
        json.loads(data.decode("utf-8-sig"))
        return True
    except Exception:
        return False


def _tomb_file():
    """墓碑存放在镜像目录内的子目录，与镜像文件本身分开——
    镜像目录顶层始终只有白名单文件，人工核对一眼就能看清。"""
    return os.path.join(BACKUP_DIR, ".meta", "tombstones.json")


def _tomb_load():
    """墓碑：记录「用户主动删除过」的文件名。恢复时跳过。
    a602 审计：只靠「DATA_DIR 里没有凭据」判断会在「登出清空凭据后立刻删包
    重装」时把已删除的明文密码复活。墓碑让删除这件事本身持久化——
    a623R（审计 #7）起删除事件由 notify **同步**落墓碑，异步窗口闭合，
    本句宣称至此成立。"""
    import json
    try:
        with open(_tomb_file(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _tomb_write(d):
    import json
    try:
        _write_atomic(_tomb_file(),
                      json.dumps(d, ensure_ascii=False).encode("utf-8"))
    except OSError:
        pass


def _dir_has_any_entry(d):
    """目录里有没有任何条目（忽略空目录壳）。判「用户是否还在这目录里用」的
    粗判据，避免把迁移残留的空壳当成「用户逐个删了凭据」。"""
    try:
        return bool(os.listdir(d))
    except OSError:
        return False


def _tomb_mutate(fn):
    """墓碑的读-改-写必须串行：主进程与 worker 两个进程都会读写同一份
    tombstones.json，无锁时后写者会用旧快照整份覆盖，丢掉对方刚写的墓碑
    → 已登出的凭据被 restore_missing 搬回来。用跨进程文件锁兜住。"""
    import json
    lock_path = _tomb_file() + ".lock"
    try:
        os.makedirs(os.path.dirname(lock_path), exist_ok=True)
        lf = open(lock_path, "a+b")
    except OSError:
        return
    try:
        try:
            import msvcrt
            lf.seek(0)
            msvcrt.locking(lf.fileno(), msvcrt.LK_LOCK, 1)
        except Exception:
            try:
                import fcntl
                fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            except Exception:
                pass
        try:
            with open(_tomb_file(), encoding="utf-8") as f:
                d = json.load(f)
            if not isinstance(d, dict):
                d = {}
        except Exception:
            d = {}
        before = dict(d)
        fn(d)
        if d != before:
            try:
                _write_atomic(_tomb_file(),
                              json.dumps(d, ensure_ascii=False).encode("utf-8"))
            except OSError:
                pass
    finally:
        try:
            try:
                import msvcrt
                lf.seek(0)
                msvcrt.locking(lf.fileno(), msvcrt.LK_UNLCK, 1)
            except Exception:
                pass
        except Exception:
            pass
        try:
            lf.close()
        except OSError:
            pass


def _tomb_add(name):
    def _add(d):
        d.setdefault(name, time.time())
    _tomb_mutate(_add)


def _tomb_clear(name):
    def _clr(d):
        d.pop(name, None)
    _tomb_mutate(_clr)


def _warn_overlap_once(src_dir):
    """备份目录与数据目录重叠 → 备份整体跳过。只告警一次，避免刷屏；
    静默失效会让用户以为「有备份」其实没有。"""
    global _warned_overlap
    if _warned_overlap:
        return
    _warned_overlap = True
    _log.warning(
        "凭据镜像已禁用：数据目录 %s 与备份目录 %s 互相包含（数据目录"
        "不要设在 home 下）。凭据仍照常工作，只是没有 home 副本兜底。",
        src_dir, BACKUP_DIR)


_m1_lock = threading.Lock()   # _mirror_one 进程内串行（a623R 审计 #6）


def _mirror_one(name, deleting_ok=True):
    """串行外壳：同一进程内 daemon 队列消费与 notify 的同步删除路径可能
    并发处理**同一个文件**（登出流程先入队 .bak 写通知、紧接着删 .bak 并
    同步打墓碑）——旧实现单 daemon 串行不可能此交错，同步化后必须显式
    互斥，否则 stat/写/墓碑三步交错出「墓碑已清+副本是旧凭据」终态，
    删包重装即复活已登出明文凭据。锁内只有几 KB 读写，无争用零成本。"""
    with _m1_lock:
        return _mirror_one_impl(name, deleting_ok=deleting_ok)


def _mirror_one_impl(name, deleting_ok=True):
    """镜像单个文件。DATA_DIR 为准：文件在就同步副本，不在就删副本并留墓碑
    （用户主动删凭据后不能让它复活）。返回 1 表示实际拷贝了。

    deleting_ok=False：**禁止删除/打墓碑**。启动全量对齐用它——那时只能
    「补拷贝」，因为一份还来不及恢复的备份绝不是「用户删的」。此前
    _bootstrap 里 restore 有一项失败（被占用/坏 json）后，sync_once 会把
    那份唯一备份删掉并打墓碑，兜底机制被自己的启动流程一次性毁掉。"""
    src_dir = _st.DATA_DIR
    if _overlaps(src_dir, BACKUP_DIR):
        _warn_overlap_once(src_dir)
        return 0
    # 源目录整个不存在 ≠ 用户删了某个文件。迁移/换盘后另一进程可能还持有
    # 旧的 DATA_DIR（worker 进程值不随主进程迁移更新），此时若把它当「用户
    # 删除」就会删掉 home 副本并打墓碑——备份被永久毁掉。目录不在就什么都不做。
    if not os.path.isdir(src_dir):
        return 0
    sp = os.path.join(src_dir, name)
    dp = os.path.join(BACKUP_DIR, name)
    sig = _sig(sp)
    if sig is None:
        # 目录存在但**一个用户文件都没有** → 多半是迁移后残留的空壳目录
        #（server.py 的 rmtree 带 ignore_errors，删不干净时目录还在）。
        # 这种情况同样不能当作「用户逐个删了凭据」。
        if deleting_ok and _dir_has_any_entry(src_dir):
            # 只有「镜像里本来有副本、现在源头没了」才算用户主动删除并留墓碑。
            # 从没存在过的文件（新装机只有 2~3 个白名单文件）不能打墓碑，
            # 否则首次 sync_once 就把其余名字全标成「用户删过」。
            if os.path.exists(dp):
                try:
                    os.remove(dp)
                    _last.pop(name, None)
                except OSError as e:
                    _log.warning("凭据镜像清理失败 %s: %s", name, e)
                _tomb_add(name)
        return 0
    if sig[1] > _MAX_BYTES:
        return 0
    if _last.get(name) == sig and os.path.exists(dp):
        return 0
    try:
        data = _read_bytes(sp, _MAX_BYTES)
    except OSError as e:
        _log.warning("凭据镜像读取失败 %s: %s", name, e)
        return 0
    if len(data) > _MAX_BYTES:
        return 0
    if not _is_valid_json(data):
        # 读到半截（业务侧正在非原子写）→ 本轮放弃，不更新签名，
        # 下次 notify 会重试；镜像里保留上一份完整内容
        _log.warning("凭据镜像跳过（内容不是完整 json）: %s", name)
        return 0
    try:
        _write_atomic(dp, data)
        _last[name] = sig
        _tomb_clear(name)     # 文件回来了（用户重新填了）→ 撤销墓碑
        return 1
    except OSError as e:
        _log.warning("凭据镜像写入失败 %s: %s", name, e)
        return 0


def sync_once():
    """启动时全量对齐一次。**只补拷贝，绝不删除备份、绝不打墓碑**——
    此刻尚未恢复正常，缺席的备份只可能是「本进程还没处理到」，不是用户删的。"""
    _cleanup_orphans()
    return sum(_mirror_one(n, deleting_ok=False) for n in _MIRROR_FILES)


def _cleanup_orphans():
    """收掉**曾经在白名单里、现在被移出**的存量副本（目前只有 skill_meta.json）。

    a636（对抗审计 P0-5）：原实现遍历备份目录顶层，把**所有非白名单文件**
    都删掉——实测往 `data_backup/` 放「我的凭据副本.json」「README_BU_
    BACKUP.txt」全部被无声删除；更强的是若 DATA_DIR 被误配成 BACKUP_DIR，
    `skill_meta.json` 与用户笔记也会被直接删（本文件其它路径都用 _overlaps
    显式防这个误配置，唯独这里没有）。这与本函数所在模块的承诺
    「只补拷贝，绝不删除备份」直接矛盾。
    现在只按**具名清单**清理，且先做重叠短路；绝不遍历删除未知文件。
    """
    # a636：备份目录与数据目录重叠（误配置/迁移中）时一律不动手
    if _overlaps(_st.DATA_DIR, BACKUP_DIR):
        return
    _KNOWN_ORPHANS = ("skill_meta.json",)     # 曾经在 _MIRROR_FILES 里
    for entry in _KNOWN_ORPHANS:
        p = os.path.join(BACKUP_DIR, entry)
        if entry in _MIRROR_FILES or not os.path.isfile(p):
            continue
        try:
            os.remove(p)
            _last.pop(entry, None)
            _log.info("凭据镜像清理已移出白名单的存量副本: %s", entry)
        except OSError as e:
            _log.warning("凭据镜像清理失败 %s: %s", entry, e)


def notify(name):
    """某个用户文件刚写完/刚被删（由 app_state.notify_user_file_written 转来）。
    非白名单文件直接忽略——日志/笔记不归这里管。

    a623R（审计 #7）：**删除事件同步处理**。原来删除和写入一样只入队，
    墓碑要等 daemon 消费才落盘——登出后立刻杀进程，墓碑没落，之后删包
    重装 restore_missing 会把已登出的明文密码复活（_tomb_load 注释里
    「异步窗口不再是问题」的宣称过头了）。源头已消失 = 删除：同步跑
    _mirror_one（一次 stat 定生死，微秒级；墓碑在跨进程锁内原子落盘），
    不再入队。写路径保持异步（写后状态完整，进程死亡不丢墓碑语义）。"""
    if name not in _MIRROR_FILES:
        return
    if _sig(os.path.join(_st.DATA_DIR, name)) is None:
        try:
            _mirror_one(name)
        except Exception as e:
            _log.warning("凭据镜像删除同步失败 %s: %s", name, e)
        return
    _q.put(name)


# 真正意义上的「凭据」（a623R 审计 #6）：_any_cred_present 只看它们。
# 白名单 _MIRROR_FILES 里 proxy_state/retry_config/cmdlib/pw_pending_del
# 是**状态/配置**文件——新装机上业务线程启动期就会写出
# （如代理 autostart 一开就写 proxy_state.json），把它们算「在用」会让
# 删包重装后的凭据恢复整体静默跳过。用户删除凭据的防线是墓碑（notify
# 已同步落盘），不依赖这个粗判据。
_CRED_FILES = (
    "hiklink_session.json",
    "hiklink_session.json.bak",
    "lanz_credentials.json",
)


def _any_cred_present(d):
    """数据目录里是否还有**有效**凭据（任意一个，只看 _CRED_FILES）。
    0 字节/坏 json 不算——恢复被打断留下的残片不能挡住后续恢复。"""
    for name in _CRED_FILES:
        p = os.path.join(d, name)
        try:
            if os.path.getsize(p) > 0:
                return True
        except OSError:
            continue
    return False


def _pending_file():
    return os.path.join(BACKUP_DIR, ".meta", "pending.json")


def _pending_load():
    """「本次该恢复却失败了」的文件名。下次启动即使数据目录已有其它凭据，
    也要把这些补上——否则一项恢复失败（文件被占用/磁盘瞬断）之后，那项
    备份就永久补不回来（目录已被其它凭据占成「在用」状态）。"""
    import json
    try:
        with open(_pending_file(), encoding="utf-8") as f:
            d = json.load(f)
        return set(d) if isinstance(d, list) else set()
    except Exception:
        return set()


def _pending_save(names):
    import json
    try:
        if not names:
            try:
                os.remove(_pending_file())
            except OSError:
                pass
            return
        os.makedirs(os.path.dirname(_pending_file()), exist_ok=True)
        _write_atomic(_pending_file(),
                      json.dumps(sorted(names), ensure_ascii=False).encode())
    except OSError:
        pass


def restore_missing():
    """DATA_DIR 里缺失的凭据从镜像搬回。**只补缺失，绝不覆盖**。
    返回恢复的文件名列表。

    主判据：只在「DATA_DIR 里一个有效凭据都不剩」时整体恢复（= 新装机 /
    整个包被删后重建）。只剩部分凭据、某几个缺了 → 那是用户**主动删除**
    （登出清凭据），绝不能凭空复活。
    例外：上次恢复失败的项（_pending）无条件补——那不是用户删的。"""
    target = _st.DATA_DIR
    if _overlaps(target, BACKUP_DIR):
        _warn_overlap_once(target)
        return []
    pending = _pending_load()
    in_use = _any_cred_present(target)
    if in_use and not pending:
        return []
    recovered, still_pending = [], set()
    tombstones = _tomb_load()
    for name in _MIRROR_FILES:
        if name in tombstones:
            continue          # 用户主动删过 → 绝不复活
        if in_use and name not in pending:
            continue          # 目录在用，这项缺失是用户删的
        tp = os.path.join(target, name)
        sp = os.path.join(BACKUP_DIR, name)
        if os.path.exists(tp) or not os.path.isfile(sp):
            continue
        try:
            data = _read_bytes(sp, _MAX_BYTES)
        except OSError as e:
            _log.warning("凭据镜像读取失败 %s: %s", name, e)
            still_pending.add(name)
            continue
        if len(data) > _MAX_BYTES or not _is_valid_json(data):
            _log.warning("凭据镜像内容损坏，跳过恢复: %s", name)
            still_pending.add(name)
            continue
        # 先写唯一临时文件，再用 os.link 原子「不存在才创建」地放到位。
        # 不用 O_EXCL 直写目标：那样进程被杀/磁盘满会留下空或半截文件，
        # 下次启动 _any_cred_present 看到「文件在」就不再恢复 → 凭据永久丢。
        # link 要么成功（目标瞬间是完整内容），要么 FileExistsError（业务抢先）。
        try:
            os.makedirs(target, exist_ok=True)
            import tempfile
            fd, tmp = tempfile.mkstemp(dir=target, prefix=name + ".",
                                       suffix=".restore")
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                try:
                    os.link(tmp, tp)
                except FileExistsError:
                    continue      # 业务抢先建好了，以它为准
                except OSError:
                    # FAT/exFAT/部分网络盘不支持硬链接 → 回退到 O_EXCL 直写
                    # （窗口内被打断会留半截文件，但比完全不恢复好；
                    # 半截内容不是合法 json，下次启动会被 restore_missing
                    # 的 _is_valid_json 判为损坏而跳过，不会误判「凭据还在」）
                    fd2 = os.open(tp, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                                  getattr(os, "O_BINARY", 0))
                    try:
                        os.write(fd2, data)
                    finally:
                        os.close(fd2)
            finally:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            _last[name] = _sig(tp)
            recovered.append(name)
        except OSError as e:
            _log.warning("凭据镜像恢复失败 %s: %s", name, e)
            still_pending.add(name)
    _pending_save(still_pending)
    return recovered


def _worker():
    """只处理队列里的名字，空闲时阻塞在 get() 上——不轮询、不占 CPU。"""
    while True:
        try:
            name = _q.get()
        except Exception:
            return
        try:
            _mirror_one(name)
        except Exception as e:
            _log.warning("凭据镜像同步异常 %s: %s", name, e)
        finally:
            _q.task_done()


def start():
    """注册写盘钩子并起后台线程。**启动路径上不做任何拷贝**（用户红线：
    不许拖慢启动）。

    线程里依次做：补缺失 → 全量对齐一次 → 之后只处理队列。
    补缺失放在后台是安全的：它只在「DATA_DIR 一个凭据都不剩」时才动作，
    而那种情况意味着用户本来就登录不了、要先重填——晚几百毫秒无影响；
    正常机器上它是 7 次 stat，微秒级。"""
    global _started
    with _lock:
        if _started:
            return
        _started = True
    _st._write_hooks.append(notify)
    threading.Thread(target=_bootstrap, daemon=True, name="cred-mirror").start()


def _bootstrap():
    """后台一次性初始化，然后转入事件循环。"""
    try:
        rec = restore_missing()
        if rec:
            _log.warning("凭据镜像恢复 %d 项到 %s：%s",
                         len(rec), _st.DATA_DIR, ", ".join(rec))
        sync_once()
    except Exception as e:
        _log.warning("凭据镜像启动同步异常: %s", e)
    _worker()
