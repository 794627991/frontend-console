# -*- coding: utf-8 -*-
"""测试自隔离本身的回归（2026-11-26 用户令：测试不得在 C 盘留任何文件）。

钉住的行为（都在 src/app_state.py 里：_fc_test_scratch_root / _fc_test_isolation /
_fc_test_rmtree）：
1. 隔离已生效——且由**被测进程自己**报出来：FC_STATE_DIR、config 的家、
   tempfile.gettempdir()、TMPDIR/TEMP/TMP 全落在该落的地方（AGENTS.md 铁律：
   隔离是否成立不能靠机制推定）。
2. 退出即清真的清得掉。此前它对三类文件一直是静默失效的：日志句柄（logging
   的 FileHandler）、常开的文件描述符（os.open）、只读文件（git 的松散对象）——
   系统临时目录里 31 个旧沙箱清一色只剩 server_errors.log 与 hiklink_bot.log
   就是证据。沙箱搬进工程内的 .temp\\ 之后，失效一次就在工程里堆一份。
3. 清理只碰指定目录之下的：兄弟目录里的句柄一个不关。
4. 落盘根建不出来、或被指到系统临时目录里 → 报错停下，不回退系统临时目录。

为什么 4 要用子进程：主进程里隔离在导入期就生效了，改无可改。子进程都从仓库
工作区直接 import src.app_state——原件，不导出副本（副本落盘曾被火绒隔离）。
"""
import logging
import os
import shutil
import stat
import subprocess
import sys
import tempfile

import pytest

sys.path.insert(0, '.')

import src.app_state as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------- 判据与自证

def test_under_judges_both_ways():
    """「在目录之内」的判据先自检（AGENTS.md 铁律第 3 条）：既判得出在内，也判得出
    不在。恒真的判据配出来的隔离自证一文不值。"""
    root = st._fc_test_scratch_root()
    assert st._fc_under(root, root)                                      # 就是它自己
    assert st._fc_under(os.path.join(root, "a", "b"), root)              # 在它之下
    assert st._fc_under(os.path.join(root.upper(), "A"), root)           # 大小写不敏感
    assert not st._fc_under(root + "x", root)                            # 同名前缀的兄弟目录
    assert not st._fc_under(os.path.join(os.path.dirname(root), "elsewhere"), root)


def test_isolation_reports_its_own_locations():
    """隔离自证：位置由本进程自己报，逐个核对。显式设过 FC_STATE_DIR 的运行方式下
    沙箱可以在测试落盘根之外（机制「尊重不改」），所以它只要求非空。"""
    root = st._fc_test_scratch_root()
    iso = os.environ.get("FC_STATE_DIR")
    assert iso, "测试自隔离未生效（FC_STATE_DIR 为空）——拒绝运行"
    # config 的家：认两种合法位置——沙箱里，或测试落盘根里。别的测试会在导入期把
    # 它改到自己建的临时目录（tests/test_audit_boundary.py 就是，改走后不恢复）；
    # 显式设过 FC_STATE_DIR 的运行方式下，沙箱本身也不在落盘根里。工具目录的
    # data\config.json（真实配置）两种都不是。
    cfg_ok = st._fc_under(st.CONFIG_FILE, iso) or st._fc_under(st.CONFIG_FILE, root)
    assert cfg_ok, "config 的家既不在沙箱里、也不在测试落盘根里：%s" % st.CONFIG_FILE
    # 临时文件四处：机制无条件钉进测试落盘根，不区分沙箱是怎么来的
    tmp_locs = {
        "tempfile.gettempdir()": tempfile.gettempdir(),
        "TMPDIR": os.environ.get("TMPDIR"),
        "TEMP": os.environ.get("TEMP"),
        "TMP": os.environ.get("TMP"),
    }
    stray = {k: v for k, v in tmp_locs.items() if not (v and st._fc_under(v, root))}
    assert not stray, "这些临时文件位置不在测试落盘根里：%s" % stray
    # 专用目录随进程走，共享目录常驻（见 _fc_test_isolation 里「分层」那段注释）
    assert os.environ["TMPDIR"] != os.environ["TEMP"]


# ---------------------------------------------------------------- 退出即清

def _force_rm(path):
    """测试自己的兜底清理（只对自己的 mkdtemp 目录用）：先去掉只读再删。"""
    for dp, dns, fns in os.walk(path):
        for n in dns + fns:
            try:
                os.chmod(os.path.join(dp, n), stat.S_IWRITE)
            except OSError:
                pass
    shutil.rmtree(path, ignore_errors=True)


def _open_log(path):
    h = logging.FileHandler(path, encoding="utf-8")
    lg = logging.getLogger("fc_iso_rmtree_probe")
    lg.addHandler(h)
    lg.error("x")
    return h, lg


def test_rmtree_clears_open_handles_and_readonly_files():
    """一个「什么都删不掉」的沙箱：日志句柄、三种打开方式的常开描述符、只读文件
    （git 松散对象的形态，连所在目录也只读）、几层空目录。"""
    base = tempfile.mkdtemp(prefix="fc_iso_clean_")
    v = h = lg = None
    fds = []
    try:
        v = os.path.join(base, "victim")
        os.makedirs(os.path.join(v, "data"))
        os.makedirs(os.path.join(v, "objects", "4b"))
        os.makedirs(os.path.join(v, "pytest-of-user", "pytest-0", "x", "y"))
        h, lg = _open_log(os.path.join(v, "data", "server_errors.log"))
        for name, flags in (("rw.wseq", os.O_RDWR | os.O_CREAT),
                            ("wr.log", os.O_WRONLY | os.O_CREAT),
                            ("rd.bin", os.O_RDONLY | os.O_CREAT)):
            fds.append(os.open(os.path.join(v, "data", name), flags))
        ro = os.path.join(v, "objects", "4b", "825dc642cb6eb9a060e54bf8d69288fbee4904")
        with open(ro, "wb") as f:
            f.write(b"blob 5\x00xxxxx")
        os.chmod(ro, stat.S_IREAD)
        os.chmod(os.path.dirname(ro), stat.S_IREAD)

        st._fc_test_rmtree(v)

        assert not os.path.exists(v), "沙箱没删干净"
        assert h.stream is None, "日志句柄没关"
        opened, fds = fds, []                     # 被测代码已经关了，finally 不必再关
        for fd in opened:
            with pytest.raises(OSError):
                os.fstat(fd)                     # 描述符已关
    finally:
        if lg is not None and h is not None:
            lg.removeHandler(h)
        for fd in fds:
            try:
                os.close(fd)
            except OSError:
                pass
        _force_rm(base)


def test_rmtree_leaves_other_dirs_and_their_handles_alone():
    """清理只认指定目录之下的：兄弟目录（含同名前缀的）里的文件、句柄一个不碰，
    落盘根本身也照常可用。"""
    base = tempfile.mkdtemp(prefix="fc_iso_kept_")
    h = lg = fd = None
    try:
        v = os.path.join(base, "victim")
        keep = os.path.join(base, "neighbor")
        twin = v + "2"                              # 同名前缀的兄弟目录
        for d in (v, keep, twin):
            os.makedirs(d)
        h, lg = _open_log(os.path.join(keep, "x.log"))
        fd = os.open(os.path.join(twin, "y.wseq"), os.O_RDWR | os.O_CREAT)

        st._fc_test_rmtree(v)

        assert not os.path.exists(v)
        assert os.path.isfile(os.path.join(keep, "x.log"))
        assert os.path.isfile(os.path.join(twin, "y.wseq"))
        assert h.stream is not None, "关错了：兄弟目录的日志句柄被关了"
        os.write(fd, b"1")                          # 仍可写 = 没被关
        with open(os.path.join(base, "still-usable.txt"), "w") as f:
            f.write("1")
    finally:
        if lg is not None and h is not None:
            lg.removeHandler(h)
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        _force_rm(base)


def test_rmtree_on_missing_dir_is_quiet():
    st._fc_test_rmtree(os.path.join(tempfile.gettempdir(), "fc_iso_never_existed_%d" % os.getpid()))


# ---------------------------------------------------------------- 子进程（端到端）

def _child_env(**over):
    """子进程环境：不继承沙箱与临时目录变量，让它自己走默认分支建沙箱；
    FC_TEST_CHILD 必须带——`python -c` 认不出测试身份（见 AGENTS.md「边界」）。"""
    env = {k: v for k, v in os.environ.items()
           if k not in ("FC_STATE_DIR", "TMPDIR", "TEMP", "TMP", "PYTEST_CURRENT_TEST")}
    env["FC_TEST_CHILD"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(over)
    return env


def _run_child(code, env, *args):
    p = subprocess.run([sys.executable, "-B", "-c", code] + list(args), cwd=ROOT, env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=240)
    kv = {}
    for line in p.stdout.splitlines():
        k, sep, val = line.partition("=")
        if sep and k.replace("_", "").isalnum() and k.isupper():
            kv[k] = val
    return p, kv


_CHILD_IMPORT = r'''
import os, sys, tempfile
sys.path.insert(0, ".")
_before = tempfile.gettempdir()
_ok, _err = True, ""
try:
    import src.app_state as st
except RuntimeError as e:
    _ok, _err = False, str(e)
print("RESULT=" + ("IMPORTED" if _ok else "BLOCKED"))
print("WHY=" + _err.replace("\n", " "))
print("STATE=" + os.environ.get("FC_STATE_DIR", ""))
print("TMP_SAME=%s" % (_before == tempfile.gettempdir()))
'''

_CHILD_HOLD = r'''
import logging, os, stat, sys, tempfile
sys.path.insert(0, ".")
import src.app_state as st
root = os.environ["FC_STATE_DIR"]
tmp = tempfile.gettempdir()
# 此前删不掉的三类各造一个，退出时不关、不恢复只读
h = logging.FileHandler(os.path.join(root, "data", "server_errors.log"), encoding="utf-8")
lg = logging.getLogger("fc_iso_child_probe")
lg.addHandler(h)
lg.error("x")
fd = os.open(os.path.join(tmp, "held.wseq"), os.O_RDWR | os.O_CREAT)
os.write(fd, b"00000000000000000001")
ro = os.path.join(tmp, "objects", "4b", "825dc642cb6eb9a060e54bf8d69288fbee4904")
os.makedirs(os.path.dirname(ro))
with open(ro, "wb") as f:
    f.write(b"blob 5\x00xxxxx")
os.chmod(ro, stat.S_IREAD)
print("STATE=" + root)
print("TMP=" + tmp)
'''


def test_child_sandbox_is_gone_after_exit():
    """端到端：一个真的测试进程（自己建的沙箱 + 自己的专用临时目录），里面留着
    日志句柄、常开描述符、只读文件，正常退出——两处都应当已经被清掉。"""
    p, kv = _run_child(_CHILD_HOLD, _child_env())
    assert p.returncode == 0, "子进程没跑起来：\n%s" % p.stderr[-1200:]
    root, tmp = kv.get("STATE", ""), kv.get("TMP", "")
    scratch = st._fc_test_scratch_root()
    assert root and tmp, "子进程没报出位置：\n%s" % p.stdout
    assert st._fc_under(root, scratch) and st._fc_under(tmp, scratch), (root, tmp, scratch)
    assert not os.path.exists(root), "沙箱在进程退出后还在：%s" % root
    assert not os.path.exists(tmp), "专用临时目录在进程退出后还在：%s" % tmp


def test_unusable_scratch_root_stops_without_fallback():
    """落盘根建不出来：报错停下，沙箱变量不设、临时目录不改——绝不退回系统临时
    目录。用一个已存在的**文件**当落盘根，确定建不成目录。"""
    box = tempfile.mkdtemp(prefix="fc_iso_blocked_")
    try:
        blocker = os.path.join(box, "blocker")
        with open(blocker, "w") as f:
            f.write("x")
        p, kv = _run_child(_CHILD_IMPORT, _child_env(FC_TEST_TMP=blocker))
        assert kv.get("RESULT") == "BLOCKED", p.stdout + p.stderr[-800:]
        assert "测试落盘目录不可用" in kv.get("WHY", "")
        assert kv.get("STATE") == "", "报错了却还把沙箱变量设上了"
        assert kv.get("TMP_SAME") == "True", "报错了却还改了临时目录"
    finally:
        _force_rm(box)


def test_scratch_root_inside_system_temp_is_refused():
    """落盘根被指到系统临时目录里：拒绝，且在那之前一个字节都不往那儿写。
    子进程不继承 TEMP/TMP，它眼里的默认临时目录就是系统临时目录。"""
    # 先问子进程「你的系统临时目录是哪」——主进程里它早已被钉进工程内，问不出来
    _, kv0 = _run_child("import tempfile\nprint('SYSTMP=' + tempfile.gettempdir())\n",
                        _child_env())
    probe = os.path.join(kv0.get("SYSTMP", ""), "fc_iso_probe_%d" % os.getpid())
    p, kv = _run_child(_CHILD_IMPORT, _child_env(FC_TEST_TMP=probe))
    try:
        assert kv.get("RESULT") == "BLOCKED", p.stdout + p.stderr[-800:]
        assert "系统临时目录" in kv.get("WHY", ""), kv
        assert kv.get("STATE") == "" and kv.get("TMP_SAME") == "True"
        assert probe and not os.path.exists(probe), \
            "被拒绝之前已经在系统临时目录里建了东西：%s" % probe
    finally:
        # 机制哪天退化了，目录会真被建出来——顺手清掉，别留在 C 盘
        if probe:
            shutil.rmtree(probe, ignore_errors=True)


if __name__ == "__main__":
    import pytest as _pt
    sys.exit(_pt.main([__file__, "-q"]))
