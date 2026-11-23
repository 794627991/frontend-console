# -*- coding: utf-8 -*-
"""harness 版本推导四形态钉子（第四轮自审实锤后的回归）。

病历史：①exe 显示 a467——frozen 无 .git 只能落手 bump 常量（80 个提交没人
记得 bump）；②修①后加「frozen 不做 .git 上溯」时写成了裸 return ""，
把读章一起绕过，frozen 又直接落兜底常量。两次都是没有测试钉住形态矩阵。

四形态（子进程隔离，各带独立 sys.frozen/_MEIPASS）：
  T1 frozen + 有章            → 读章
  T2 frozen + 无章            → 空（落兜底常量），且不被所在 git 仓库劫持
  T3 源码形态（仓库内）       → git 推导，含 HEAD 短哈希
  T4 非冻结 + 无 .git + 有章  → 读章兜底
直接 `py tests/test_harness_version.py` 运行；全程 %TEMP%，不碰真实状态。
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 【测试身份声明——本文件必须有】
# 本测试**自己不导入 src.app_state**（只用子进程跑 `from src.harness ...`），
# 所以 app_state 的测试自隔离（_fc_test_isolation）在本进程里从未执行，
# FC_STATE_DIR / FC_TEST_CHILD 都不会被设。子进程用 `python -c` 起，argv[0]
# 是 "-c"，app_state 也认不出它是测试——于是子进程以「正常运行」身份读到
# 真实的锚点 config，并把指针写进了真实的 %APPDATA%（受控实验实锤）。
# 血缘标记随环境继承：在这里设一次，本进程起的所有子进程都会认。
# 教训：隔离是否成立不能假定，要由子进程自报路径来验证。
os.environ["FC_TEST_CHILD"] = "1"

NL = chr(10)
BASE = ("import sys" + NL +
        "sys.path.insert(0, %(root)r)" + NL +
        "from src.harness import _git_harness_version as g" + NL +
        "print('GOT', repr(g()))" + NL)


def _env():
    """子进程环境——每次调用时现取（保证带上上面设的血缘标记）。"""
    return dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")


def _run(code, cwd=None):
    r = subprocess.run([sys.executable, "-c", code], env=_env(), cwd=cwd,
                       capture_output=True, text=True)
    out = (r.stdout + r.stderr).strip()
    return out.splitlines()[-1] if out else ""


def _frozen(stamp_dir):
    return ("import sys" + NL + "sys.frozen = True" + NL +
            "sys._MEIPASS = %r" % stamp_dir + NL)


def main():
    n = 0
    # T1 frozen + 有章 → 读章
    T = tempfile.mkdtemp(prefix="hv1_")
    try:
        with open(os.path.join(T, "harness_version.txt"), "w") as f:
            f.write("4.1.0-a686-deadbee" + NL)
        got = _run((_frozen(T) + BASE) % {"root": ROOT})
        assert got == "GOT '4.1.0-a686-deadbee'", got
    finally:
        shutil.rmtree(T, ignore_errors=True)
    n += 1

    # T1b frozen + 带 BOM 的章 → 同样读到干净版本串（本仓库编辑链会产出
    # BOM 文件：version.py / installer.nsh 皆然；裸 utf-8 会读进 \ufeff）
    T = tempfile.mkdtemp(prefix="hv1b_")
    try:
        with open(os.path.join(T, "harness_version.txt"), "w",
                  encoding="utf-8-sig") as f:
            f.write("4.1.0-a686-bomfile" + NL)
        got = _run((_frozen(T) + BASE) % {"root": ROOT})
        assert got == "GOT '4.1.0-a686-bomfile'", got
    finally:
        shutil.rmtree(T, ignore_errors=True)
    n += 1

    # T2 frozen + 无章 → 空，且不被仓库根的 .git 劫持（cwd 故意设在仓库内）
    T = tempfile.mkdtemp(prefix="hv2_")
    try:
        got = _run((_frozen(T) + BASE) % {"root": ROOT}, cwd=ROOT)
        assert got == "GOT ''", got
    finally:
        shutil.rmtree(T, ignore_errors=True)
    n += 1

    # T3 源码形态 → git 推导（含 HEAD 短哈希）
    got = _run(BASE % {"root": ROOT}, cwd=ROOT)
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()
    assert head and head in got and "-a" in got, (got, head)
    n += 1

    # T4 非冻结 + 找不到仓库根（嵌套 >6 层）+ 有章 → 读章兜底
    T = tempfile.mkdtemp(prefix="hv4_")
    try:
        src_dst = os.path.join(T, *(("d",) * 8), "src")
        shutil.copytree(os.path.join(ROOT, "src"), src_dst,
                        ignore=shutil.ignore_patterns("__pycache__"))
        with open(os.path.join(T, "harness_version.txt"), "w") as f:
            f.write("4.1.0-a686-cafe" + NL)
        code = ("import sys" + NL + "sys._MEIPASS = %r" % T + NL +
                "sys.path.insert(0, %r)" % os.path.dirname(src_dst) + NL +
                "from src.harness import _git_harness_version as g" + NL +
                "print('GOT', repr(g()))" + NL)
        got = _run(code, cwd=T)
        assert got == "GOT '4.1.0-a686-cafe'", got
    finally:
        shutil.rmtree(T, ignore_errors=True)
    n += 1
    print("通过 %d / 失败 0" % n)


if __name__ == "__main__":
    main()
