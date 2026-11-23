# -*- coding: utf-8 -*-
"""凭据镜像备份单测（a602：同事「先删旧包再解压」把凭据一起删掉的场景）。

用户定调三条，本测逐条钉住：
1. DATA_DIR 是唯一真源——镜像跟着它走，删除也要同步删除（不复活）
2. 只放有价值的小文件——白名单之外（日志/笔记/大文件）绝不进 home
3. 触发式备份不轮询——写入点 notify 才动，队列外的名字直接忽略
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, '.')

import src.app_state as st
import src.cred_mirror as cm


def _write(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def _setup(monkeypatch):
    """夹具：data 兼作「工具目录\\data」与「数据目录」（没迁移时的生产布局）。
    config.json 永远在 工具目录\\data、镜像在其下的 data_backup（2026-11-23
    用户令：config 不随数据迁移走）——所以这两个路径也要一起指进临时目录，
    否则 sync_once 会对真实位置的工具目录 data 做镜像。"""
    root = tempfile.mkdtemp(prefix="fc_cm_")
    data = os.path.join(root, "data")
    backup = os.path.join(root, "home_backup")
    os.makedirs(data, exist_ok=True)
    monkeypatch.setattr(st, "DATA_DIR", data)
    monkeypatch.setattr(cm, "BACKUP_DIR", backup)
    monkeypatch.setattr(st, "CONFIG_FILE", os.path.join(data, "config.json"))
    monkeypatch.setattr(st, "CONFIG_BACKUP_FILE",
                        os.path.join(data, "data_backup", "config.json"))
    monkeypatch.setattr(cm, "_last", {})
    monkeypatch.setattr(cm, "_q", __import__("queue").Queue())
    return root, data, backup


def test_whitelist_excludes_big_and_derived():
    """白名单只含小凭据；日志/笔记/使用量/技能缓存一律不在。"""
    assert "hiklink_session.json" in cm._MIRROR_FILES
    assert "lanz_credentials.json" in cm._MIRROR_FILES
    for bad in ("logs", "files", "proxy_usage.json", "nav",
                "skill_cache", "web_passwords.json"):
        assert bad not in cm._MIRROR_FILES


def test_sync_only_whitelist(monkeypatch):
    """sync_once 只搬白名单文件，目录里的其它东西绝不进 home。"""
    root, data, backup = _setup(monkeypatch)
    try:
        _write(os.path.join(data, "hiklink_session.json"), {"app_id": "A1"})
        _write(os.path.join(data, "lanz_credentials.json"), {"username": "u"})
        _write(os.path.join(data, "cmdlib.json"), [{"cmd": "ls"}])
        _write(os.path.join(data, "proxy_usage.json"), {"big": "x"})
        os.makedirs(os.path.join(data, "logs"), exist_ok=True)
        with open(os.path.join(data, "logs", "a.log"), "w") as f:
            f.write("x" * 1000)

        assert cm.sync_once() == 3
        mirrored = {n for n in os.listdir(backup)
                    if not n.startswith(".")}      # 墓碑等元数据不算
        assert mirrored == {
            "hiklink_session.json", "lanz_credentials.json", "cmdlib.json"}
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_oversized_file_skipped(monkeypatch):
    """单文件超上限跳过——home 只放小有价值的东西。"""
    root, data, backup = _setup(monkeypatch)
    try:
        with open(os.path.join(data, "cmdlib.json"), "w", encoding="utf-8") as f:
            f.write("x" * (cm._MAX_BYTES + 10))
        cm.sync_once()
        assert not os.path.exists(os.path.join(backup, "cmdlib.json"))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_restore_only_when_no_cred_left(monkeypatch):
    """数据目录里还剩凭据 → 目录在用，缺的是用户主动删的，不复活。"""
    root, data, backup = _setup(monkeypatch)
    try:
        _write(os.path.join(backup, "hiklink_session.json"), {"app_id": "OLD"})
        _write(os.path.join(backup, "lanz_credentials.json"), {"username": "old"})
        _write(os.path.join(data, "hiklink_session.json"), {"app_id": "CURRENT"})

        assert cm.restore_missing() == []
        with open(os.path.join(data, "hiklink_session.json"), encoding="utf-8") as f:
            assert json.load(f)["app_id"] == "CURRENT"
        assert not os.path.exists(os.path.join(data, "lanz_credentials.json"))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_restore_when_data_dir_empty(monkeypatch):
    """一个凭据都不剩（整包被删后重建）→ 全部恢复。"""
    root, data, backup = _setup(monkeypatch)
    try:
        _write(os.path.join(backup, "hiklink_session.json"), {"app_id": "OLD"})
        _write(os.path.join(backup, "lanz_credentials.json"), {"username": "old"})
        os.makedirs(os.path.join(data, "logs"), exist_ok=True)   # 空 logs 不算凭据

        rec = cm.restore_missing()
        assert set(rec) == {"hiklink_session.json", "lanz_credentials.json"}
        with open(os.path.join(data, "hiklink_session.json"), encoding="utf-8") as f:
            assert json.load(f)["app_id"] == "OLD"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_data_dir_wins_deletion_syncs(monkeypatch):
    """DATA_DIR 为准：用户删了凭据 → 镜像副本跟着删，不会被复活。"""
    root, data, backup = _setup(monkeypatch)
    try:
        _write(os.path.join(data, "hiklink_session.json"), {"app_id": "A"})
        _write(os.path.join(data, "retry_config.json"), {"max": 1})
        cm.sync_once()
        assert os.path.exists(os.path.join(backup, "retry_config.json"))

        os.remove(os.path.join(data, "retry_config.json"))
        cm._mirror_one("retry_config.json")
        assert not os.path.exists(os.path.join(backup, "retry_config.json"))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_notify_ignores_non_whitelist(monkeypatch):
    """触发式：非白名单名字（日志/笔记）直接丢弃，不进队列。

    a623R：白名单名分写/删两路——**写**（文件在）入队走 daemon；**删**
    （文件不在）同步落墓碑不入队。本测试 data 里没有 hiklink_session.json，
    notify 它=删除事件 → 不入队（墓碑分支另有专测）。"""
    root, data, backup = _setup(monkeypatch)
    try:
        cm.notify("server_errors.log")
        cm.notify("files")
        cm.notify("proxy_usage.json")
        assert cm._q.empty()
        # 删除形态：源头不存在 → 同步处理，不入队
        cm.notify("hiklink_session.json")
        assert cm._q.empty()
        # 写形态：文件在 → 入队
        _write(os.path.join(data, "hiklink_session.json"), {"app_id": "A"})
        cm.notify("hiklink_session.json")
        assert cm._q.get_nowait() == "hiklink_session.json"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_notify_hook_wired_through_app_state(monkeypatch):
    """写入点只认 app_state 钩子——cred_mirror 不反向 import 各模块。"""
    root, data, backup = _setup(monkeypatch)
    try:
        _write(os.path.join(data, "cmdlib.json"), [{"cmd": "ls"}])
        st._write_hooks.append(cm.notify)
        try:
            st.notify_user_file_written("cmdlib.json")
            assert cm._q.get_nowait() == "cmdlib.json"
        finally:
            st._write_hooks.remove(cm.notify)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_startup_never_wipes_backup(monkeypatch):
    """启动时 restore 有 1 项失败 → sync_once 绝不能再删其余备份、也不打墓碑。
    （实测过的严重缺陷：兜底机制被自己的启动流程一次性清空）"""
    root, data, backup = _setup(monkeypatch)
    try:
        names = ["hiklink_session.json", "lanz_credentials.json", "cmdlib.json",
                 "retry_config.json"]
        for i, n in enumerate(names):
            _write(os.path.join(backup, n), {"i": i})
        orig = cm._read_bytes

        def flaky(p, lim):
            if "retry_config" in p:
                raise OSError("被占用")
            return orig(p, lim)

        monkeypatch.setattr(cm, "_read_bytes", flaky)
        cm.restore_missing()
        monkeypatch.setattr(cm, "_read_bytes", orig)
        cm.sync_once()
        left = {n for n in os.listdir(backup) if not n.startswith(".")}
        assert left == set(names)              # 一个都没被删
        assert cm._tomb_load() == {}           # 也没打墓碑
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_partial_restore_retried_next_boot(monkeypatch):
    """某项恢复失败 → 记 pending，下次启动即使目录已有其它凭据也要补上。"""
    root, data, backup = _setup(monkeypatch)
    try:
        _write(os.path.join(backup, "hiklink_session.json"), {"app_id": "A"})
        _write(os.path.join(backup, "lanz_credentials.json"), {"password": "p"})
        orig = cm._read_bytes

        def flaky(p, lim):
            if "lanz_cred" in p:
                raise OSError("被占用")
            return orig(p, lim)

        monkeypatch.setattr(cm, "_read_bytes", flaky)
        assert cm.restore_missing() == ["hiklink_session.json"]
        assert cm._pending_load() == {"lanz_credentials.json"}
        monkeypatch.setattr(cm, "_read_bytes", orig)
        # 目录里已有凭据（此前会整体跳过），但 pending 里的必须补
        assert cm.restore_missing() == ["lanz_credentials.json"]
        assert cm._pending_load() == set()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_empty_shell_dir_does_not_tombstone(monkeypatch):
    """迁移后 rmtree 没删干净的空壳旧目录（另一进程还持旧 DATA_DIR）：
    不能当成「用户逐个删了凭据」把 home 副本毁掉。"""
    root, data, backup = _setup(monkeypatch)
    try:
        _write(os.path.join(backup, "hiklink_session.json"), {"app_id": "A"})
        # data 是空目录（旧目录被清空残留）
        cm._mirror_one("hiklink_session.json")
        assert os.path.exists(os.path.join(backup, "hiklink_session.json"))
        assert cm._tomb_load() == {}
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_merge_small_first_no_overwrite():
    """导入期小文件搬运不得覆盖新位置已有文件（用户此刻正在登录）。"""
    src = tempfile.mkdtemp(prefix="fc_mss_")
    dst = tempfile.mkdtemp(prefix="fc_msd_")
    try:
        _write(os.path.join(src, "hiklink_session.json"), {"app_id": "OLD"})
        _write(os.path.join(dst, "hiklink_session.json"), {"app_id": "NEW"})
        st._merge_small_first(src, dst)
        with open(os.path.join(dst, "hiklink_session.json"), encoding="utf-8") as f:
            assert json.load(f)["app_id"] == "NEW"
        # 大文件与目录不搬
        with open(os.path.join(src, "big.bin"), "wb") as f:
            f.write(b"x" * (600 * 1024))
        os.makedirs(os.path.join(src, "files"), exist_ok=True)
        _write(os.path.join(src, "files", "a.note"), {"n": 1})
        st._merge_small_first(src, dst)
        assert not os.path.exists(os.path.join(dst, "big.bin"))
        assert not os.path.exists(os.path.join(dst, "files"))
    finally:
        shutil.rmtree(src, ignore_errors=True)
        shutil.rmtree(dst, ignore_errors=True)



def test_overlap_dir_skipped(monkeypatch):
    """备份目录与数据目录的关系分三种（第七轮 R7-2 修正语义）：
       相同 / 数据目录在备份目录里面 → 整体跳过（否则自己备份自己）
       备份目录是数据目录的**子目录**   → 放行。这才是生产布局
         （数据目录\\data_backup）。此前它也被当成「重叠」跳过，于是凭据镜像
         在生产布局下整体静默禁用——config/凭据没有任何备份。
    """
    root, data, _ = _setup(monkeypatch)
    try:
        _write(os.path.join(data, "cmdlib.json"), [{"cmd": "ls"}])

        # ① 子目录：必须放行——镜像真的发生
        sub = os.path.join(data, "backup")
        monkeypatch.setattr(cm, "BACKUP_DIR", sub)
        assert cm.sync_once() == 1, "备份目录是数据目录子目录时镜像被跳过"
        assert os.path.isfile(os.path.join(sub, "cmdlib.json"))

        # ② 相同：仍然跳过
        monkeypatch.setattr(cm, "BACKUP_DIR", data)
        assert cm.sync_once() == 0
        assert cm.restore_missing() == []

        # ③ 数据目录在备份目录里面（备份目录是数据目录的上级）：仍然跳过
        monkeypatch.setattr(cm, "BACKUP_DIR", root)
        assert cm.sync_once() == 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_real_layout_backup_dir_is_inside_data_dir(monkeypatch):
    """**用生产布局**（BACKUP_DIR = 数据目录\\data_backup）验证 config 真的进
    了备份。此前的测试都把 BACKUP_DIR 改到独立目录——所以 R7-2 那个「镜像
    整体禁用」的洞在它们全绿的情况下存在。这条测试不许改 BACKUP_DIR。"""
    import src.app_state as st
    root, data, _ = _setup(monkeypatch)
    try:
        monkeypatch.setattr(cm, "BACKUP_DIR",
                            os.path.join(data, "data_backup"))
        _write(os.path.join(data, "config.json"),
               {"data_dir": data, "theme": "prod-layout"})
        _write(os.path.join(data, "hiklink_session.json"),
               {"app_id": "aid", "app_secret": "sec"})
        assert "config.json" in cm._MIRROR_FILES
        cm.sync_once()
        bk = os.path.join(data, "data_backup", "config.json")
        assert os.path.isfile(bk), "生产布局下 config.json 没有进备份"
        assert json.load(open(bk, encoding="utf-8"))["theme"] == "prod-layout"
        assert os.path.isfile(os.path.join(data, "data_backup",
                                           "hiklink_session.json"))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_unchanged_not_recopied(monkeypatch):
    """内容没变不重复拷贝（触发式下同一文件多次 notify 也只拷一次）。"""
    root, data, backup = _setup(monkeypatch)
    try:
        _write(os.path.join(data, "cmdlib.json"), [{"cmd": "ls"}])
        assert cm._mirror_one("cmdlib.json") == 1
        assert cm._mirror_one("cmdlib.json") == 0
        _write(os.path.join(data, "cmdlib.json"), [{"cmd": "ls"}, {"cmd": "pwd"}])
        assert cm._mirror_one("cmdlib.json") == 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_tombstone_blocks_resurrection(monkeypatch):
    """用户登出清空全部凭据后删包重装：墓碑必须挡住旧凭据复活。
    （审计缺陷：原来只判「DATA_DIR 没凭据」就把镜像全搬回去）"""
    root, data, backup = _setup(monkeypatch)
    try:
        # 真实数据目录里总有 logs/ 等过程文件；空壳目录（迁移残留）不算在用
        os.makedirs(os.path.join(data, "logs"), exist_ok=True)
        _write(os.path.join(data, "hiklink_session.json"), {"app_id": "A"})
        _write(os.path.join(data, "lanz_credentials.json"), {"password": "p"})
        cm.sync_once()
        # 用户主动删除（登出清凭据）
        os.remove(os.path.join(data, "hiklink_session.json"))
        os.remove(os.path.join(data, "lanz_credentials.json"))
        cm._mirror_one("hiklink_session.json")
        cm._mirror_one("lanz_credentials.json")
        # 现在删包重装：DATA_DIR 是全新的空目录
        data2 = os.path.join(root, "data_new")
        os.makedirs(data2)
        monkeypatch.setattr(st, "DATA_DIR", data2)
        assert cm.restore_missing() == []        # 墓碑挡住
        assert not os.path.exists(os.path.join(data2, "hiklink_session.json"))
        assert not os.path.exists(os.path.join(data2, "lanz_credentials.json"))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_tombstone_cleared_when_refilled(monkeypatch):
    """用户重新填了凭据 → 墓碑撤销，之后照常镜像/恢复。"""
    root, data, backup = _setup(monkeypatch)
    try:
        _write(os.path.join(data, "hiklink_session.json"), {"app_id": "A"})
        cm.sync_once()
        os.remove(os.path.join(data, "hiklink_session.json"))
        cm._mirror_one("hiklink_session.json")          # 留墓碑
        _write(os.path.join(data, "hiklink_session.json"), {"app_id": "B"})
        assert cm._mirror_one("hiklink_session.json") == 1
        assert cm._tomb_load() == {}                     # 墓碑已清
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_restore_does_not_overwrite_race(monkeypatch):
    """判 exists 与落盘之间业务抢先建了同名文件 → O_EXCL 保证不覆盖。"""
    root, data, backup = _setup(monkeypatch)
    try:
        _write(os.path.join(backup, "hiklink_session.json"), {"app_id": "OLD"})
        # 模拟竞态：restore 走到落盘时文件已存在（用 _any_cred_present 骗不过去，
        # 直接预置一个非白名单文件 + 目标已存在的情况）
        os.makedirs(data, exist_ok=True)
        _write(os.path.join(data, "hiklink_session.json"), {"app_id": "NEW"})
        assert cm.restore_missing() == []
        with open(os.path.join(data, "hiklink_session.json"), encoding="utf-8") as f:
            assert json.load(f)["app_id"] == "NEW"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_truncated_json_not_mirrored(monkeypatch):
    """读到半截 JSON（业务侧非原子写窗口）→ 不覆盖镜像，也不记签名。"""
    root, data, backup = _setup(monkeypatch)
    try:
        _write(os.path.join(data, "cmdlib.json"), [{"cmd": "good"}])
        cm.sync_once()
        with open(os.path.join(backup, "cmdlib.json"), encoding="utf-8") as f:
            before = f.read()
        # 半截内容
        with open(os.path.join(data, "cmdlib.json"), "w", encoding="utf-8") as f:
            f.write('[{"cmd": "trunc')
        assert cm._mirror_one("cmdlib.json") == 0
        with open(os.path.join(backup, "cmdlib.json"), encoding="utf-8") as f:
            assert f.read() == before               # 镜像保留上一份完整的
    finally:
        shutil.rmtree(root, ignore_errors=True)



# ---- a623R（对抗审计 #6/#5/#7）：恢复判据与墓碑时序的真身回归 ------------

def test_restore_not_blocked_by_state_files(monkeypatch):
    """审计 #6：proxy_state.json（状态文件）存在 ≠ 凭据在用。新装机上业务
    线程启动期就会写状态文件（如代理 autostart），旧判据把它算「在用」→
    凭据恢复整体静默跳过。修复后 _any_cred_present 只看真凭据。"""
    root, data, backup = _setup(monkeypatch)
    try:
        _write(os.path.join(backup, "hiklink_session.json"), {"app_id": "A"})
        _write(os.path.join(backup, "lanz_credentials.json"), {"u": "x"})
        # 业务抢先：状态文件先落盘，凭据一个都还没有
        _write(os.path.join(data, "proxy_state.json"), {"on": True})
        _write(os.path.join(data, "pw_pending_del.json"), [{"p": 1}])
        rec = cm.restore_missing()
        assert "hiklink_session.json" in rec, rec
        assert "lanz_credentials.json" in rec, rec
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_notify_delete_writes_tombstone_synchronously(monkeypatch):
    """审计 #7：删除事件 notify 必须同步落墓碑。原实现入队等 daemon——
    登出后立刻杀进程，墓碑没落，之后删包重装会复活已登出的明文密码。
    （目录里放一个非白名单文件：_mirror_one 对「删到目录全空」有壳保护，
    真实 DATA_DIR 恒有其他条目，空壳是迁移残留特例。）"""
    root, data, backup = _setup(monkeypatch)
    try:
        _write(os.path.join(data, "unrelated_notes.json"), {"n": 1})
        _write(os.path.join(data, "hiklink_session.json"), {"app_id": "A"})
        _write(os.path.join(backup, "hiklink_session.json"), {"app_id": "A"})
        os.remove(os.path.join(data, "hiklink_session.json"))
        cm.notify("hiklink_session.json")      # 不起 worker 线程——必须同步生效
        assert "hiklink_session.json" in cm._tomb_load(), \
            "删除通知返回时墓碑必须已落盘（不能等队列消费）"
        assert not os.path.exists(os.path.join(backup, "hiklink_session.json")), \
            "副本也要同步清掉"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_notify_write_stays_async(monkeypatch):
    """写路径保持异步（删除才同步）——queue 收到名字即过，不此刻拷贝。"""
    import queue as _q
    root, data, backup = _setup(monkeypatch)
    try:
        _write(os.path.join(data, "cmdlib.json"), [{"cmd": "x"}])
        cm.notify("cmdlib.json")
        assert cm._q.get_nowait() == "cmdlib.json"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_restore_oexcl_real_paths(monkeypatch):
    """审计 #5：O_EXCL「只补不盖」的真路径覆盖。原测试预置真凭据走了
    _any_cred_present 早退，os.link/FileExistsError 分支零执行——实现若
    退化成 shutil.copy 静默覆盖，测试照样绿。"""
    root, data, backup = _setup(monkeypatch)
    try:
        _write(os.path.join(backup, "hiklink_session.json"), {"app_id": "OLD"})
        # 场景①：正常恢复——link 必须被调用，内容搬回
        calls = {"link": 0}
        real_link = os.link
        def _counting_link(a, b, **kw):
            calls["link"] += 1
            return real_link(a, b, **kw)
        monkeypatch.setattr(os, "link", _counting_link)
        assert cm.restore_missing() == ["hiklink_session.json"]
        assert calls["link"] == 1, "恢复必须走 os.link（O_EXCL 语义），而不是 copy"
        with open(os.path.join(data, "hiklink_session.json"), encoding="utf-8") as f:
            assert json.load(f)["app_id"] == "OLD"

        # 场景②：判 exists 与落盘之间业务抢先建了同名文件 → link 抛
        # FileExistsError → 绝不覆盖，以业务为准
        os.remove(os.path.join(data, "hiklink_session.json"))
        _write(os.path.join(data, "hiklink_session.json"), {"app_id": "NEW"})
        # 目录里现在有凭据 → 走 in_use 早退，测不到 link 分支——
        # 所以移走其它凭据源：直接把恢复判据指向无凭据状态
        os.remove(os.path.join(data, "hiklink_session.json"))
        def _link_exists(a, b, **kw):
            raise FileExistsError(17, "业务抢先")
        monkeypatch.setattr(os, "link", _link_exists)
        assert cm.restore_missing() == []      # FileExistsError → 当轮跳过
        # 目标此刻被业务重建（模拟抢先者已落盘）——绝不能被覆盖成 OLD
        _write(os.path.join(data, "hiklink_session.json"), {"app_id": "NEW"})
        monkeypatch.setattr(os, "link", _link_exists)
        cm.restore_missing()
        with open(os.path.join(data, "hiklink_session.json"), encoding="utf-8") as f:
            assert json.load(f)["app_id"] == "NEW", "O_EXCL：绝不能覆盖业务文件"

        # 场景③（a623R 复审修正）：「目标已存在 → continue」的真分支——
        # 用**非凭据**白名单文件（cmdlib.json）测：凭据文件在 data 里会让
        # in_use 早退，根本走不到循环内的 exists(tp) continue。
        _write(os.path.join(backup, "cmdlib.json"), [{"cmd": "x"}])
        _write(os.path.join(data, "cmdlib.json"), [{"cmd": "x"}])
        calls2 = {"link": 0}
        def _counting2(a, b, **kw):
            calls2["link"] += 1
            return real_link(a, b, **kw)
        monkeypatch.setattr(os, "link", _counting2)
        assert cm.restore_missing() == []
        assert calls2["link"] == 0, "目标已存在必须走 exists(tp) continue，不碰 link"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_skill_meta_no_longer_backed_up(monkeypatch):
    """a630（用户定调）：skill_meta.json 移出备份白名单——技能清单丢了
    顶多重装，不是凭据也不在备份范围。写点 notify 直接忽略，不再有副本。"""
    root, data, backup = _setup(monkeypatch)
    try:
        _write(os.path.join(data, "skill_meta.json"), {"s": 1})
        cm.notify("skill_meta.json")
        assert cm._q.empty(), "非白名单名字不得入队"
        cm.sync_once()
        assert not os.path.exists(os.path.join(backup, "skill_meta.json")), \
            "skill_meta.json 不应再被镜像"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_backup_orphan_cleanup(monkeypatch):
    """a630：白名单移除 skill_meta.json 后，老机器 home 里已躺着的旧副本
    要在启动对齐时收掉（备份目录顶层始终只有白名单文件——既有设计约定）；
    .meta/ 子目录（墓碑/pending）与白名单内文件不碰。"""
    root, data, backup = _setup(monkeypatch)
    try:
        _write(os.path.join(data, "hiklink_session.json"), {"app_id": "A"})
        _write(os.path.join(backup, "skill_meta.json"), {"old": 1})   # 存量孤儿
        _write(os.path.join(backup, "pw_pending_del.json"), [{"p": 1}])  # 白名单内
        os.makedirs(os.path.join(backup, ".meta"), exist_ok=True)
        _write(os.path.join(backup, ".meta", "tombstones.json"), {})
        cm.sync_once()
        assert not os.path.exists(os.path.join(backup, "skill_meta.json")), \
            "白名单外的存量副本必须被清理"
        assert os.path.exists(os.path.join(backup, "pw_pending_del.json"))
        assert os.path.exists(os.path.join(backup, ".meta", "tombstones.json"))
        assert os.path.exists(os.path.join(backup, "hiklink_session.json"))
    finally:
        shutil.rmtree(root, ignore_errors=True)
