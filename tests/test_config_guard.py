# -*- coding: utf-8 -*-
"""a669 回归锚：config.json 的「暂时读不到」绝不能被当成「空的」。

事故（用户实锤 2026-11-19 11:39）：config.json 内容完全合法（39 个键、
18KB），但某次读取时被另一进程/杀软占用，`cfg_read` 的
`except Exception` 把它當成内容损坏 → os.replace 改名 .bad → 返回 {}。
随后任一字段级保存 `_save_config({**_load_config(), ...})` 以空 dict 为
基线落盘，37 个键被永久抹掉，用户下次启动看到「首次启动」提示。

本测试锁三件事：
  1. 读侧 IO 故障 → 不改名、不返回空配置、正常返回值保持完整
  2. 写侧 IO 故障 → 直接失败，绝不落盘
  3. 写侧「键数骤减」→ 拒绝写入并留现场（防逻辑 bug 洗库）
  4. 内容真的坏了（JSON 解析失败）→ 仍然隔离 .bad（原行为保留）

直接 `py tests/test_config_guard.py` 运行。
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import src.app_state as st

_PASS, _FAIL = [], []


def check(name, cond, detail=""):
    if cond:
        _PASS.append(name)
        print("  PASS  %s" % name)
    else:
        _FAIL.append(name)
        print("  FAIL  %s  %s" % (name, detail))


GOOD = {("k%d" % i): i for i in range(39)}   # 39 个 + theme = 40 键
GOOD["theme"] = "onedark"


def _home(td):
    """把 app_state 的配置路径指到临时目录（不碰用户真实配置）。"""
    global _OLD
    if "_OLD" not in globals():
        _OLD = {}
    _OLD = {"CONFIG_FILE": st.CONFIG_FILE, "HOME_DIR": st.HOME_DIR}
    st.HOME_DIR = td
    st.CONFIG_FILE = os.path.join(td, "config.json")
    st._CFG_LAST["d"] = {}


def _restore():
    st.CONFIG_FILE = _OLD["CONFIG_FILE"]
    st.HOME_DIR = _OLD["HOME_DIR"]


def main():
    td = tempfile.mkdtemp(prefix="cfg_guard_")
    _home(td)
    p = st.CONFIG_FILE
    try:
        print("== 1. 正常读取 ==")
        json.dump(GOOD, open(p, "w", encoding="utf-8"), ensure_ascii=False)
        d = st.cfg_read()
        check("读到全部键", len(d) == 40, str(len(d)))
        check("内存缓存同步", len(st._CFG_LAST["d"]) == 40, str(len(st._CFG_LAST["d"])))

        print("== 2. 读侧 IO 故障（占用）不改名、不返回空 ==")
        real_open = open

        def _busy_open(fn, *a, **kw):
            if os.path.normcase(str(fn)) == os.path.normcase(p) and "r" in (a[0] if a else kw.get("mode", "r")):
                raise PermissionError(13, "Permission denied (模拟占用)")
            return real_open(fn, *a, **kw)

        import builtins
        builtins.open = _busy_open
        try:
            d2 = st.cfg_read()
        finally:
            builtins.open = real_open
        check("占用时不改名 .bad", not os.path.exists(p + ".bad"))
        check("原文件仍在", os.path.exists(p))
        check("返回上次成功读到的内容（不是空）", len(d2) == 40, str(len(d2)))
        check("theme 仍在", d2.get("theme") == "onedark")

        print("== 3. 写侧 IO 故障 → 拒绝写入 ==")
        builtins.open = _busy_open
        try:
            ok, err = st.cfg_commit(lambda x: x.__setitem__("probe", 1))
        finally:
            builtins.open = real_open
        check("写入失败", ok is False, str(ok))
        check("磁盘内容未被破坏",
              len(json.load(open(p, encoding="utf-8"))) == 40)

        print("== 4. 键数骤减 → 拒绝写入并留现场 ==")
        ok, err = st.cfg_commit(lambda x: x.clear())
        check("清空被拒", ok is False, str(ok))
        check("理由提到骤减", "骤减" in (err or ""), str(err))
        check("磁盘仍是 40 键", len(json.load(open(p, encoding="utf-8"))) == 40)
        rej = [f for f in os.listdir(td) if f.startswith("config.json.reject-")]
        check("留了现场文件", bool(rej), str(os.listdir(td)))

        print("== 5. 正常增量写仍然可用 ==")
        ok, err = st.cfg_commit(lambda x: x.__setitem__("newkey", "v"))
        check("正常写入成功", ok is True, str(err))
        dd = json.load(open(p, encoding="utf-8"))
        check("新键写入且旧键保留", dd.get("newkey") == "v" and len(dd) == 41,
              "%s / %d" % (dd.get("newkey"), len(dd)))

        print("== 6. 内容真的坏了 → 仍然隔离（原行为保留）==")
        open(p, "w", encoding="utf-8").write("{ this is not json ")
        d3 = st.cfg_read()
        check("坏了返回空", d3 == {})
        check("隔离为 .bad", os.path.exists(p + ".bad"))
    finally:
        _restore()

    print("=" * 56)
    print("通过 %d / 失败 %d" % (len(_PASS), len(_FAIL)))
    for x in _FAIL:
        print("  -", x)
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
