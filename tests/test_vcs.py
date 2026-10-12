# -*- coding: utf-8 -*-
"""vcs.py 单元测试（v3.5.117，designer P1 测试段）：
①git porcelain -z 解析（普通/Rename/untracked/分支行）②svn status/info/log
XML 解析 ③_dec 三跳 ④门卫与临时件清理。全程 monkeypatch 临时目录，
绝不触碰真实 ~/.serialconsole_pro。直接 `py tests/test_vcs.py` 运行。
"""
import io
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import src.app_state as _st
_TMP = os.path.join(os.environ.get("TEMP", ROOT), "vcs_test_home")
os.makedirs(_TMP, exist_ok=True)
_st.HOME_DIR = _TMP
_st.DATA_DIR = os.path.join(_TMP, "data")
_st._HOME_CFG = {"data_dir": _st.DATA_DIR}

import time as _time
from src import vcs
from src import file_tree as _ft

_PASS, _FAIL = [], []


def check(name, cond, detail=""):
    if cond:
        _PASS.append(name)
        print("  PASS  %s" % name)
    else:
        _FAIL.append(name)
        print("  FAIL  %s  %s" % (name, detail))


def main():
    print("== 1. _dec 三跳 ==")
    check("utf-8 严格命中", vcs._dec("中文abc".encode("utf-8")) == "中文abc")
    check("GBK 兜底", vcs._dec("中文".encode("gbk")) == "中文")
    check("脏字节 replace 不炸", "\ufffd" in vcs._dec(b"\xff\xfe\xfa"))

    print("== 2. git porcelain -z 解析 ==")
    z = (b"## main...origin/main [ahead 1, behind 2]\x00"
         b" M src/a.py\x00"
         b"?? new.txt\x00"
         b"R  new_name.py\x00old_name.py\x00"
         b"D  gone.c\x00")
    import subprocess as _sp
    orig_run = vcs._run
    vcs._run = lambda argv, cwd, to: (
        (0, "a1b2c3d", "") if argv[1] == "rev-parse" else (0, z.decode("utf-8"), ""))
    try:
        res, e = vcs._git_status("D:\\fake")
        check("porcelain 无异常", e is None, str(e))
        check("分支/ahead/behind", res["branch"] == "main"
              and res["ahead"] == 1 and res["behind"] == 2, str(res)[:120])
        sts = {f["rel"]: f["st"] for f in res["files"]}
        check("M/?/D 三态", sts.get("src/a.py") == "M"
              and sts.get("new.txt") == "?" and sts.get("gone.c") == "D", str(sts))
        rn = [f for f in res["files"] if f["st"] == "R"]
        check("rename 记录 old_rel", len(rn) == 1
              and rn[0]["old_rel"] == "old_name.py"
              and rn[0]["rel"] == "new_name.py", str(rn))
    finally:
        vcs._run = orig_run

    print("== 3. svn XML 解析 ==")
    sx = (b'<?xml version="1.0" encoding="UTF-8"?>\n<status>\n<target path=".">\n'
          b'<entry path="src main.c"><wc-status item="modified" revision="10">'
          b'</wc-status></entry>\n'
          b'<entry path="build.log"><wc-status item="unversioned"></wc-status>'
          b'</entry>\n'
          b'<entry path="old.c"><wc-status item="deleted"></wc-status></entry>\n'
          b'</target>\n</status>')
    vcs._run = lambda argv, cwd, to: (0, sx.decode("utf-8"), "")
    ix = (b'<?xml version="1.0" encoding="UTF-8"?>\n<info>\n'
          b'<entry path="."><url>https://svn/svn/proj/branches/dev</url>'
          b'<commit revision="188"><author>zhang</author></commit></entry>\n</info>')
    orig_run2 = vcs._run
    calls = {"n": 0}
    def _svn_run(argv, cwd, to):
        calls["n"] += 1
        return (0, (sx if calls["n"] == 1 else ix).decode("utf-8"), "")
    vcs._run = _svn_run
    try:
        res, e = vcs._svn_status("D:\\fake")
        check("svn status 无异常", e is None, str(e))
        sts = {f["rel"]: f["st"] for f in res["files"]}
        check("svn M/?/D 映射", sts.get("src main.c") == "M"
              and sts.get("build.log") == "?" and sts.get("old.c") == "D", str(sts))
        check("svn rev/branch 取自 info --xml", res["rev"] == "188"
              and res["branch"] == "dev", "%s/%s" % (res["rev"], res["branch"]))
    finally:
        vcs._run = orig_run2

    print("== 4. svn log XML ==")
    lx = (b'<?xml version="1.0"?>\n<log>\n'
          b'<logentry revision="188"><author>zhang</author>'
          b'<date>2026-10-12T08:00:00.000000Z</date><msg>fix bug</msg></logentry>\n'
          b'<logentry revision="187"><author>li</author>'
          b'<date>2026-10-11T08:00:00.000000Z</date><msg>init</msg></logentry>\n'
          b'</log>')
    vcs._run = lambda argv, cwd, to: (0, lx.decode("utf-8"), "")
    _real_wcr = vcs._wc_root
    vcs._wc_root = lambda p: ("svn", "D:\\fake_svn", None)   # 门卫放行（路由解析专用）
    try:
        from src.server import app
        c = app.test_client()
        r = c.post("/api/vcs/log", json={"root": "D:\\fake_svn"})
        j = r.get_json()
        check("svn log 路由解析", j.get("ok") and len(j.get("commits") or []) == 2
              and j["commits"][0]["rev"] == "188"
              and j["commits"][0]["msg"] == "fix bug", str(j)[:150])
    finally:
        vcs._run = orig_run2
        vcs._wc_root = _real_wcr                           # 还原真门卫

    print("== 5. 门卫与 status 路由 ==")
    vcs._run = orig_run2
    from src.server import app as _app
    c = _app.test_client()
    r = c.post("/api/vcs/status", json={"root": "D:\\not_registered_at_all"})
    j = r.get_json()
    check("未登记根 → 400 + 中文 err", r.status_code == 400
          and not j.get("ok") and "文件树" in (j.get("err") or ""), str(j))

    print("== 6. 临时件物化与清理 ==")
    vcs._TMP_KEEP_S = 0           # 全部视为过期
    p1 = vcs._tmp_materialize(b"AAA", "a.txt")
    time.sleep(0.02)
    p2 = vcs._tmp_materialize(b"BBB", "b.txt")
    d = os.path.dirname(p1)
    left = os.listdir(d)
    check("过期件被清理", os.path.basename(p1) not in left
          and os.path.basename(p2) in left, str(left))
    vcs._TMP_KEEP_S = 24 * 3600

    print("=" * 56)
    print("通过 %d / 失败 %d" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        print("失败项：")
        for x in _FAIL:
            print("  -", x)
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
