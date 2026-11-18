# -*- coding: utf-8 -*-
"""L0 静态门禁：挂载矩阵 / 动态取用 / 存取器 / 模块清单一致性。

不依赖运行中的应用；纯源码扫描，每次提交必跑（秒级）。
"""
import glob
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, _HERE)
from cdp_lib import result          # noqa: E402

JS_DIR = os.path.join(ROOT, "web", "js")
MODULES_TXT = os.path.join(ROOT, "tests", "js", "modules.txt")

MOUNT_RE = re.compile(r"(?:window|root|self|globalThis)\.([A-Za-z_$][\w$]*)\s*=[^=]")
DP_RE = re.compile(r"defineProperty\(\s*(?:window|root|self|globalThis)\s*,\s*['\"]([A-Za-z_$][\w$]*)")
DYN_RE = re.compile(r"_g\(\s*['\"]([A-Za-z_$][\w$]*)['\"]\s*\)")
DYN_IDX_RE = re.compile(r"(?:window|root|self|globalThis)\[\s*['\"]([A-Za-z_$][\w$]*)['\"]\s*\]")
DECL_RE = re.compile(
    r"^\s*(?:(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)"
    r"|(?:const|let|var|class)\s+([A-Za-z_$][\w$]*))", re.M)


def _js_files():
    out = []
    for base, _dirs, files in os.walk(JS_DIR):
        for f in files:
            if f.endswith(".js"):
                out.append(os.path.join(base, f).replace(os.sep, "/"))
    return sorted(out)


def _module_list():
    if not os.path.isfile(MODULES_TXT):
        return set()
    with open(MODULES_TXT, encoding="utf-8") as f:
        return {"web/" + ln.strip().replace("\\", "/") for ln in f if ln.strip()}


def _scan():
    mounts, dyn, decls = set(), set(), {}
    per_file_mounts = {}
    files = _js_files()
    for p in files:
        with open(p, encoding="utf-8", errors="replace") as f:
            src = f.read()
        rel = os.path.relpath(p, ROOT).replace(os.sep, "/")
        m = set(MOUNT_RE.findall(src)) | set(DP_RE.findall(src))
        per_file_mounts[rel] = m
        mounts |= m
        dyn |= set(DYN_RE.findall(src)) | set(DYN_IDX_RE.findall(src))
        decls[rel] = set(a or b for a, b in DECL_RE.findall(src))
    return files, mounts, dyn, decls, per_file_mounts


def m01_mount_matrix():
    """M01 静态：动态取用名 ⊆ window 挂载名。"""
    _files, mounts, dyn, _decls, _pf = _scan()
    missing = sorted(dyn - mounts)
    return result("M01", "动态取用 ⊆ window 挂载", "L0", "P0",
                  "PASS" if not missing else "FAIL",
                  "动态取用 %d 名，缺失 %d：%s" % (len(dyn), len(missing), missing[:10]))


def m02_dynamic_refs_source():
    """M02 静态：v4bridge 内 _g 调用点全部有字面量名（无动态拼接）。"""
    p = os.path.join(JS_DIR, "harness", "v4bridge.js")
    with open(p, encoding="utf-8") as f:
        src = f.read()
    bad = [ln for ln in src.splitlines()
           if "_g(" in ln and not re.search(r"_g\(\s*['\"]", ln)
           and not ln.strip().startswith("//")
           and "function _g(" not in ln]
    return result("M02", "_g 调用全部字面量化", "L0", "P1",
                  "PASS" if not bad else "CHECK",
                  "可疑行 %d：%s" % (len(bad), bad[:3]))


def m03_accessor_matrix():
    """M03 静态：defineProperty 存取器成对且带 configurable。"""
    pairs = {"get": 0, "set": 0, "configurable": 0, "bad": []}
    for p in _js_files():
        with open(p, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        for i, ln in enumerate(lines):
            if "defineProperty(" in ln and ("window" in ln or "root" in ln):
                block = "".join(lines[i:i + 3])
                if "get()" in block or "get ()" in block:
                    pairs["get"] += 1
                if "set(v)" in block or "set (v)" in block:
                    pairs["set"] += 1
                if "configurable: true" in block:
                    pairs["configurable"] += 1
                else:
                    pairs["bad"].append("%s:%d" % (os.path.basename(p), i + 1))
    ok = pairs["get"] == pairs["set"] == pairs["configurable"] and not pairs["bad"]
    return result("M03s", "存取器成对 + configurable", "L0", "P0",
                  "PASS" if ok else "FAIL",
                  "get=%d set=%d configurable=%d bad=%s" %
                  (pairs["get"], pairs["set"], pairs["configurable"], pairs["bad"][:5]))


def m07_module_list_sync():
    """M07：modules.txt 与 index.html 的 type=module 标签一致。"""
    with open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8") as f:
        html = f.read()
    tagged = {os.path.normpath(re.sub(r"\?.*$", "", m.group(1))).replace(os.sep, "/")
              for m in re.finditer(r'<script[^>]*type="module"[^>]*src="([^"]+)"', html)}
    listed = _module_list()
    missing = sorted(tagged - listed)
    extra = sorted(listed - tagged)
    return result("M07", "modules.txt ↔ index.html 模块一致", "L0", "P1",
                  "PASS" if not missing and not extra else "FAIL",
                  "标签多出=%s 清单多出=%s" % (missing[:5], extra[:5]))


def m05_strict_no_implicit():
    """M05 静态：module 内无未声明标识符写入（严格模式会抛）。

    用 AST（espree+eslint-scope）精确判定；node 不可用时 SKIP。
    """
    import shutil
    import subprocess
    if not shutil.which("node"):
        return result("M05", "module 内无未声明写入", "L0", "P1", "SKIP", "node 不可用")
    try:
        out = subprocess.run(
            ["node", os.path.join(_HERE, "ast_checks.mjs")],
            capture_output=True, text=True, encoding="utf-8", timeout=120).stdout
        data = json.loads(out)
    except Exception as e:
        return result("M05", "module 内无未声明写入", "L0", "P1", "SKIP", "AST 检查失败: %r" % e)
    susp = data.get("implicitWrites") or []
    free = data.get("freeRefs") or []
    detail = "未声明写入=%s；白名单外自由引用=%s" % (susp[:6], free[:6])
    ok = not susp and not free
    return result("M05", "module 内无未声明写入", "L0", "P1",
                  "PASS" if ok else "CHECK", detail)


def m09_graph_gate():
    """M09：依赖图门禁——悬挂引用 / 名字级断链（零误报硬规则）。"""
    tools_dir = os.path.join(ROOT, "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    try:
        import check_graph
        res = check_graph.run()
    except Exception as e:
        return result("M09", "依赖图门禁（悬挂/断链）", "L0", "P0", "SKIP", repr(e))
    fails = res.get("fail") or []
    return result("M09", "依赖图门禁（悬挂/断链）", "L0", "P0",
                  "PASS" if not fails else "FAIL",
                  "fail=%s warn=%d" % (fails[:5], len(res.get("warn") or [])))


def run():
    return [m01_mount_matrix(), m02_dynamic_refs_source(),
            m03_accessor_matrix(), m07_module_list_sync(),
            m05_strict_no_implicit(), m09_graph_gate()]


if __name__ == "__main__":
    import json as _j
    print(_j.dumps(run(), ensure_ascii=False, indent=2))
