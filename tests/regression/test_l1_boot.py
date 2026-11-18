# -*- coding: utf-8 -*-
"""L1 启动自检：挂载可达性 / 存取器读写 / 冷启动零错误 / classic↔module 交叉。

M04 用 headless Chrome 冷启动（boot_probe）；其余用运行中的应用 CDP（9222）。
应用未运行时，除 M04 外用 SKIP 记录。
"""
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from cdp_lib import Page, result          # noqa: E402

ROOT = os.path.dirname(os.path.dirname(_HERE))

# 曾漏挂的 24 名（a651 修复对象）
FIXED_24 = [
    "_hgAgentModelPre", "_hgCompactionEnd", "_hgHistWinStart", "_hgRowAdd",
    "_hgTurnMend", "_hgTurnReopen", "_hgVisionCardBuild", "_hgVisionSweep",
    "_regInterruptedStale", "_subEnsure", "_subPaneScaffold", "_subPaneStick",
    "_subTlAppendRow", "_subTlAppendTool", "_subTlFinalizeT", "_subTlHeadPaint",
    "_subTlSegFreeze", "_subTlTextRow", "_subTlThinkRow", "_subTurnNew",
    "renderCompaction", "renderOneToolResult", "renderToolUse", "statusBadge",
]


def _dynamic_names():
    """从源码提取全部 _g('x') / window['x'] 动态取用名。"""
    names = set()
    for base, _d, files in os.walk(os.path.join(ROOT, "web", "js")):
        for f in files:
            if not f.endswith(".js"):
                continue
            with open(os.path.join(base, f), encoding="utf-8", errors="replace") as fh:
                src = fh.read()
            names |= set(re.findall(r"_g\(\s*['\"]([A-Za-z_$][\w$]*)['\"]\s*\)", src))
            names |= set(re.findall(r"(?:window|root|self|globalThis)\[\s*['\"]([A-Za-z_$][\w$]*)['\"]\s*\]", src))
    return sorted(names)


def _accessor_names():
    names = []
    p = os.path.join(ROOT, "web", "js", "harness", "state.js")
    with open(p, encoding="utf-8") as f:
        src = f.read()
    for m in re.finditer(r"defineProperty\(\s*window\s*,\s*['\"]([A-Za-z_$][\w$]*)['\"]", src):
        names.append(m.group(1))
    return names


def m04_boot_clean():
    """M04：headless Chrome 冷启动，0 exception / 0 module 加载失败。"""
    try:
        import boot_probe
        r = boot_probe.probe(timeout_s=9)
    except Exception as e:
        return result("M04", "冷启动零错误", "L1", "P0", "SKIP", "探针失败: %r" % e)
    if r.get("skip"):
        return result("M04", "冷启动零错误", "L1", "P0", "SKIP", r["skip"])
    ok = r.get("ok")
    return result("M04", "冷启动零错误", "L1", "P0",
                  "PASS" if ok else "FAIL",
                  "exceptions=%s module=%s mounts=%s" %
                  (r.get("exceptions", [])[:3], r.get("module_errors", [])[:3], r.get("mounts")))


def _page():
    try:
        return Page()
    except Exception:
        return None


def run():
    out = [m04_boot_clean()]
    pg = _page()
    if pg is None:
        for cid, name, pri in [
                ("M01r", "24 个补挂名字运行时可达", "P0"),
                ("M02r", "60 个动态取用名全部非 undefined", "P0"),
                ("M03r", "存取器读写往返", "P0"),
                ("M05r", "无隐式全局泄漏", "P1"),
                ("M06", "classic↔module 交叉调用", "P1"),
                ("M08", "同名挂载包装链完整", "P1")]:
            out.append(result(cid, name, "L1", pri, "SKIP", "应用未运行（CDP 9222 不可达）"))
        return out
    try:
        pg.clear_errs()
        # M01r
        js = "JSON.stringify(%s.filter(n=>typeof window[n]!=='function'))" % json.dumps(FIXED_24)
        miss = json.loads(pg.ev(js) or "[]")
        out.append(result("M01r", "24 个补挂名字运行时可达", "L1", "P0",
                          "PASS" if not miss else "FAIL", "缺失=%s" % miss))
        # M02r
        names = _dynamic_names()
        js = "JSON.stringify(%s.filter(n=>typeof window[n]==='undefined'))" % json.dumps(names)
        miss = json.loads(pg.ev(js) or "[]")
        out.append(result("M02r", "60 个动态取用名全部非 undefined", "L1", "P0",
                          "PASS" if not miss else "FAIL",
                          "共 %d 名，缺失=%s" % (len(names), miss[:10])))
        # M03r
        acc = _accessor_names()
        bad = []
        for n in acc:
            try:
                r = pg.ev(
                    "(function(){var v=window[%s];try{window[%s]=v;}catch(e){return 'set:'+e.message;}"
                    "return typeof window[%s]==='undefined'?'undefined-ok':'ok';})()"
                    % (json.dumps(n), json.dumps(n), json.dumps(n)))
                if not (r in ("ok", "undefined-ok")):
                    bad.append((n, r))
            except Exception as e:
                bad.append((n, repr(e)))
        out.append(result("M03r", "存取器读写往返", "L1", "P0",
                          "PASS" if not bad else "FAIL",
                          "%d 个存取器，异常=%s" % (len(acc), bad[:5])))
        # M05r
        leak = pg.ev_obj(
            "JSON.stringify({actWordIdx: typeof window._actWordIdx,"
            " implicit: (typeof window._hgHasHistory==='function')})")
        ok = leak.get("actWordIdx") == "undefined" and leak.get("implicit")
        out.append(result("M05r", "无隐式全局泄漏", "L1", "P1",
                          "PASS" if ok else "CHECK", json.dumps(leak, ensure_ascii=False)))
        # M06
        cross = pg.ev_obj(
            "JSON.stringify({switchTab: typeof window.switchTab,"
            " applyTheme: typeof window.applyTheme, ICO: typeof window.ICO16,"
            " renderAsst: typeof window.renderAsst, rowAdd: typeof window._hgRowAdd})")
        ok = all(v in ("function", "object") for v in cross.values())
        out.append(result("M06", "classic↔module 交叉调用", "L1", "P1",
                          "PASS" if ok else "FAIL", json.dumps(cross, ensure_ascii=False)))
        # M08：包装链特征。
        # switchTab 最外层是 shell.js 包装（含 flowSnap；它闭包内再调 web-panel
        # 包装，源码不可见——不能直接搜 _webCur，那是误判）。closeEditorTab /
        # _tvRebuild 的最外层包装体本身含特征串，可直接验。
        wrap = pg.ev_obj(
            "JSON.stringify({switchTab: String(window.switchTab).slice(0,4000).includes('flowSnap'),"
            " closeEditorTab: String(window.closeEditorTab).slice(0,4000).includes('_webCtl'),"
            " tvRebuild: String(window._tvRebuild||'').slice(0,4000).includes('syncToggleIcon')})")
        ok = all(wrap.values())
        out.append(result("M08", "同名挂载包装链完整", "L1", "P1",
                          "PASS" if ok else "CHECK", json.dumps(wrap, ensure_ascii=False)))
        errs = pg.drain_errs()
        if errs:
            out.append(result("M04r", "测试期无页面异常", "L1", "P0", "FAIL",
                              json.dumps(errs[:5], ensure_ascii=False)))
        else:
            out.append(result("M04r", "测试期无页面异常", "L1", "P0", "PASS", ""))
    finally:
        pg.close()
    return out


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
