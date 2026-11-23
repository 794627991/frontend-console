# -*- coding: utf-8 -*-
"""锚点公式一致性钉子（复审 N4 建议）。

公式在五处复制（各有苦衷不能合并）：main.py 三处内联（解密前钩子，不能
import src）+ app_state._anchor_dir + electron/main.js 显式公式。任何一处
单方面改动都会造成壳/后端/钩子三方分家——本测试把五处钉死，改必须五处
一起改（改完同步本测试的期望值）。直接 `py tests/test_anchor_formula.py`。
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src import app_state as st

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _py_inline_formulas():
    """从 main.py 源码抓内联锚点公式的求值结果（exec 同款表达式）。"""
    src = open(os.path.join(BASE, "src", "main.py"), encoding="utf-8").read()
    # 内联公式形如 os.environ.get("FC_STATE_DIR") or os.path.join(... ...)
    pats = re.findall(
        r'os\.environ\.get\("FC_STATE_DIR"\)\s*\n?\s*or\s*\n?\s*'
        r'os\.path\.join\(os\.environ\.get\("APPDATA"\)\s*\n?\s*or\s*\n?\s*'
        r'os\.path\.expanduser\("~"\),\s*\n?\s*"frontend-console-shell",\s*'
        r'\n?\s*"backend"\)', src)
    assert len(pats) == 3, "main.py 内联锚点公式应为 3 处,实抓 %d 处" % len(pats)
    out = []
    for env_anchor, env_appdata in ((None, None), ("T_A", None), (None, "T_B"),
                                    ("T_A", "T_B")):
        e = dict(os.environ)
        if env_anchor:
            e["FC_STATE_DIR"] = env_anchor
        else:
            e.pop("FC_STATE_DIR", None)
        if env_appdata:
            e["APPDATA"] = env_appdata
        else:
            e.pop("APPDATA", None)
        out.append((env_anchor, env_appdata,
                    os.path.join(env_anchor or os.path.join(
                        env_appdata or os.path.expanduser("~"),
                        "frontend-console-shell", "backend"))))
    return out


def main():
    n = 0
    # ① app_state._anchor_dir 权威值
    for env_anchor, env_appdata, expect in _py_inline_formulas():
        old_a, old_d = os.environ.get("FC_STATE_DIR"), os.environ.get("APPDATA")
        # 2026-11-23 总审计 a686-A11：原为 os.environ.clear() + 整份回填——
        # 被别的测试 import 后会把进程环境整个洗一遍（PATH/tempfile 等全丢）。
        # 这里只动 _anchor_dir 实际读的两个键，其余原样不碰。
        try:
            if env_anchor:
                os.environ["FC_STATE_DIR"] = env_anchor
            else:
                os.environ.pop("FC_STATE_DIR", None)
            if env_appdata:
                os.environ["APPDATA"] = env_appdata
            else:
                os.environ.pop("APPDATA", None)
            got = st._anchor_dir()
        finally:
            for _k, _old in (("FC_STATE_DIR", old_a), ("APPDATA", old_d)):
                if _old is None:
                    os.environ.pop(_k, None)
                else:
                    os.environ[_k] = _old
        assert got == expect, "_anchor_dir(%r,%r)=%r != 内联公式 %r" % (
            env_anchor, env_appdata, got, expect)
        n += 1
    # ② main.js 显式公式:FC_STATE_DIR 覆盖口(复审 N7①)+ appData 三段常量
    js = open(os.path.join(BASE, "electron", "main.js"), encoding="utf-8").read()
    m = re.search(r"const STATE_DIR = process\.env\.FC_STATE_DIR \|\|\s*"
                  r"path\.join\(app\.getPath\('appData'\),\s*"
                  r"'frontend-console-shell',\s*'backend'\)", js)
    assert m, "electron/main.js STATE_DIR 显式公式被改/漂移"
    n += 1
    print("通过 %d / 失败 0" % n)


if __name__ == "__main__":
    main()
