# -*- coding: utf-8 -*-
"""依赖图门禁（M09）：结构回归的机械校验。

用法：
    python tools/check_graph.py            # 人读输出，FAIL 退出码 1
    python tools/check_graph.py --json     # 机器可读（M09 消费）
    python tools/check_graph.py --update-baseline

检查项（硬规则，FAIL 阻断；防御性——正常迭代应恒 0）：
  1. 悬挂引用：A 文件 references 指向的目标文件不存在。
  2. 名字级断链：A 引用 B 的某名字，但 B 的 defines 里没有它。
     （注：dep-graph 的 references 构造本身以目标 defines 为源，本规则
     主要防生成器/手工改动引入的图损坏，价值在回归防御而非新检出。）

  说明：真正拦截「漏挂载/未声明引用」的是 AST 级检查（L0 M01/M05），
  本工具的不可替代价值是**结构趋势**：扇出/扇入相对基线的变化（WARN）。

趋势项（WARN，不阻断）：
  - 与基线相比的扇出/扇入变化（记录结构演进，供人工审视）。

说明：参考判定沿用 js_dep_graph 的全词启发式（不装 AST），所以「模块
漏挂」一项按引用名过滤掉明显是局部/参数名的误报源——以 L1 的运行时
M01r/M02r 为最终仲裁。
"""
import io
import json
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

BASELINE = os.path.join(ROOT, "tests", "js", "dep-graph-baseline.json")
MOUNT_RE = re.compile(r"(?:window|root|self|globalThis)\.([A-Za-z_$][\w$]*)\s*=[^=]")
DP_RE = re.compile(r"defineProperty\(\s*(?:window|root|self|globalThis)\s*,\s*['\"]([A-Za-z_$][\w$]*)")


def _build_graph():
    """现场生成依赖图到临时文件（不污染仓库里的 dep-graph.json）。"""
    import js_dep_graph as g
    fd, tmp = tempfile.mkstemp(prefix=".dep-graph-", suffix=".json", dir=ROOT)
    os.close(fd)
    old = g.OUT
    try:
        g.OUT = tmp
        buf = io.StringIO()
        _so = sys.stdout
        sys.stdout = buf                      # 抑制叶片摘要打印
        try:
            g.main()
        finally:
            sys.stdout = _so
        with open(tmp, encoding="utf-8") as f:
            return json.load(f)["files"]
    finally:
        g.OUT = old
        try:
            os.remove(tmp)
        except OSError:
            pass


def _mounts():
    """{file: set(window 挂载名)}（module 判定用）。"""
    out = {}
    js_dir = os.path.join(ROOT, "web", "js")
    for base, _d, names in os.walk(js_dir):
        for n in names:
            if not n.endswith(".js"):
                continue
            p = os.path.join(base, n)
            rel = os.path.relpath(p, os.path.join(ROOT, "web")).replace(os.sep, "/")
            with open(p, encoding="utf-8", errors="replace") as f:
                src = f.read()
            out[rel] = set(MOUNT_RE.findall(src)) | set(DP_RE.findall(src))
    return out


def run():
    files = _build_graph()
    mounts = _mounts()

    fail = []
    warn = []

    # 1) 悬挂引用（目标文件不存在）
    for f, info in files.items():
        for target in (info.get("references") or {}):
            if target not in files:
                fail.append({"kind": "dangling-file", "from": f, "to": target})

    # 2) 名字级断链
    for f, info in files.items():
        for target, names in (info.get("references") or {}).items():
            tinfo = files.get(target)
            if not tinfo:
                continue
            tdefs = set(tinfo.get("defines") or [])
            miss = sorted(n for n in names if n not in tdefs)
            if miss:
                fail.append({"kind": "dangling-name", "from": f,
                             "to": target, "names": miss})

    # 3) （已移除）「module 内声明未挂载却被引用」——全词启发式会把
    # match/counts/opt 这类局部变量名当成跨文件引用，误报率 100%。该维度
    # 由 L0 M01（动态取用 ⊆ 挂载）与 M05（espree+eslint-scope 自由标识符，
    # AST 级精确）覆盖，此处不再重复。

    # 4) 趋势：扇出/扇入 vs 基线
    fan = {f: len(v.get("references") or {}) for f, v in files.items()}
    fin = {f: len(v.get("referenced_by") or {}) for f, v in files.items()}
    if os.path.isfile(BASELINE):
        try:
            with open(BASELINE, encoding="utf-8") as fh:
                base = json.load(fh)
            bfan = base.get("fanout") or {}
            bfin = base.get("fanin") or {}
            for f, n in sorted(fan.items()):
                if f in bfan and abs(n - bfan[f]) >= 3:
                    warn.append({"kind": "fanout-change", "file": f,
                                 "before": bfan[f], "after": n})
            for f, n in sorted(fin.items()):
                if f in bfin and abs(n - bfin[f]) >= 3:
                    warn.append({"kind": "fanin-change", "file": f,
                                 "before": bfin[f], "after": n})
        except Exception as e:
            warn.append({"kind": "baseline-read", "err": repr(e)})
    else:
        warn.append({"kind": "baseline-missing", "path": BASELINE})

    return {"ok": not fail, "fail": fail, "warn": warn,
            "files": len(files), "fanout": fan, "fanin": fin}


def update_baseline(res):
    payload = {"generated_note": "check_graph --update-baseline 生成；扇出/扇入趋势基线",
               "fanout": res["fanout"], "fanin": res["fanin"]}
    os.makedirs(os.path.dirname(BASELINE), exist_ok=True)
    with open(BASELINE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1, sort_keys=True)


def main():
    res = run()
    if "--update-baseline" in sys.argv:
        update_baseline(res)
        print("基线已更新: %s" % os.path.relpath(BASELINE, ROOT))
        return 0
    if "--json" in sys.argv:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        print("依赖图门禁：%d 文件" % res["files"])
        for x in res["fail"]:
            print("  FAIL", json.dumps(x, ensure_ascii=False)[:300])
        for x in res["warn"]:
            print("  WARN", json.dumps(x, ensure_ascii=False)[:200])
        print("结论:", "PASS" if res["ok"] else "FAIL")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
