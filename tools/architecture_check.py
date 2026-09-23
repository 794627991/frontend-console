# -*- coding: utf-8 -*-
"""架构治理校验（v3.0，对照 ZCode scripts/architecture/ 的 Python 移植）。

用法：
  py tools/architecture_check.py            # 全量校验 managed 模块
  py tools/architecture_check.py --changed  # 只查 git 改动波及的文件

规则（architecture-policy.yaml 声明，此处只做机器校验）：
  1. module-dependency  managed 模块的 import 不得指向 requires 白名单外的模块
  2. deep-import        跨模块 import 只准走 publicEntrypoints（eventlog 只许
                       `from src.eventlog import ...`，深 import 子模块即违规）
  3. max-file-lines     managed 模块文件行数上限
  4. forbid-cycles      managed 模块内/间循环依赖
豁免：违规指纹 sha256(rule\\0file\\0detail)[:16] 存
.architecture-baseline.json——存量不阻塞，只有新增违规退出码 1。
"""
import ast
import hashlib
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POLICY = os.path.join(ROOT, "architecture-policy.yaml")
BASELINE = os.path.join(ROOT, ".architecture-baseline.json")


def load_policy():
    """极简 YAML 读取（本项目的 policy 结构固定，不引第三方依赖）。"""
    text = open(POLICY, encoding="utf-8").read()
    # modules 段
    mods = []
    cur = None
    for ln in text.splitlines():
        m = re.match(r"\s+- id:\s*(\S+)", ln)
        if m:
            cur = {"id": m.group(1)}
            mods.append(cur)
            continue
        if cur is None:
            continue
        m = re.match(r"\s+roots:\s*\[(.*?)\]", ln)
        if m:
            cur["roots"] = [x.strip() for x in m.group(1).split(",") if x.strip()]
        m = re.match(r"\s+managed:\s*(\S+)", ln)
        if m:
            cur["managed"] = m.group(1) == "true"
        m = re.match(r"\s+requires:\s*\[(.*?)\]", ln)
        if m:
            cur["requires"] = [x.strip() for x in m.group(1).split(",") if x.strip()]
        m = re.match(r"\s+publicEntrypoints:\s*\[(.*?)\]", ln)
        if m:
            cur["publicEntrypoints"] = [x.strip() for x in m.group(1).split(",")
                                        if x.strip()]
    glob = {}
    m = re.search(r"maxFileLines:\s*(\d+)", text)
    if m:
        glob["maxFileLines"] = int(m.group(1))
    glob["forbidCycles"] = "forbidCycles: true" in text
    glob["forbidDeepImports"] = "forbidDeepImports: true" in text
    return mods, glob


def module_of(path, mods):
    """roots 最长前缀匹配（相对路径、目录前缀）。"""
    rel = os.path.relpath(path, ROOT).replace("\\", "/")
    best, best_len = None, 0
    for mod in mods:
        for r in mod.get("roots", []):
            if (rel == r or rel.startswith(r + "/")) and len(r) > best_len:
                best, best_len = mod, len(r)
    return best, rel


def imports_of(path):
    """AST 提取工程内 import 边（src.* 开头才算，stdlib/三方不计）。"""
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except (OSError, SyntaxError):
        return []
    edges = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("src."):
                    edges.append(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("src."):
                for a in node.names:
                    edges.append(node.module + "." + a.name
                                 if a.name != "*" else node.module)
    return edges


def changed_files():
    """git 改动 + 反向依赖闭包（改了 eventlog，import 它的 harness 文件也在波及面）。"""
    try:
        out = subprocess.run(["git", "-C", ROOT, "diff", "--name-only",
                              "master...HEAD"],
                             capture_output=True, text=True).stdout
        names = [x.strip() for x in out.splitlines() if x.strip().endswith(".py")]
    except Exception:
        return None
    if not names:
        return set(names)
    full = set(names)
    # 反向闭包：全仓扫 import，谁 import 了改动文件所属模块，谁入围
    for dp, _, fs in os.walk(os.path.join(ROOT, "src")):
        if "__pycache__" in dp:
            continue
        for f in fs:
            if not f.endswith(".py"):
                continue
            p = os.path.join(dp, f)
            for edge in imports_of(p):
                if any(n.replace("\\", "/").startswith(
                        os.path.dirname(edge).replace(".", "/"))
                        or edge.startswith(_mod_prefix(n)) for n in names):
                    full.add(os.path.relpath(p, ROOT).replace("\\", "/"))
                    break
    return full


def _mod_prefix(name):
    return name.replace("\\", "/").rstrip("/") + "/"


def main():
    mods, glob_cfg = load_policy()
    managed = [m for m in mods if m.get("managed")]
    violations = []

    scope = changed_files() if "--changed" in sys.argv else None
    if scope is not None and not scope:
        print("architecture-check: no changed python files — skip")
        return 0

    # 收集全部 py 文件（模块归属判定用）
    all_py = []
    for dp, _, fs in os.walk(os.path.join(ROOT, "src")):
        if "__pycache__" in dp:
            continue
        for f in fs:
            if f.endswith(".py"):
                all_py.append(os.path.join(dp, f))

    # 模块归属表（file -> module id），含 managed 与否
    owner = {}
    for p in all_py:
        mod, _ = module_of(p, mods)
        if mod:
            owner[p] = mod

    graph = {}   # (modA, modB) -> set(file)
    for p in all_py:
        mod, rel = module_of(p, mods)
        if not mod or not mod.get("managed"):
            continue
        if scope is not None and rel not in scope:
            continue
        # 行数
        n = sum(1 for _ in open(p, encoding="utf-8"))
        if glob_cfg.get("maxFileLines") and n > glob_cfg["maxFileLines"]:
            violations.append(("max-file-lines", rel, "%d>%d" % (n, glob_cfg["maxFileLines"])))
        for edge in imports_of(p):
            target_mod_id = edge.split(".")[1] if edge.count(".") >= 1 else ""
            # 归一：src.harness.xxx → 模块 harness
            tgt = next((m for m in mods if m["id"] == target_mod_id), None)
            if tgt is None:
                continue
            if tgt["id"] == mod["id"]:
                continue    # 模块内部自由
            if tgt["id"] not in mod.get("requires", []):
                violations.append(("module-dependency", rel,
                                   "未声明依赖 %s -> %s" % (mod["id"], tgt["id"])))
            if glob_cfg.get("forbidDeepImports") and tgt.get("publicEntrypoints"):
                # 深 import 判定：from src.eventlog.store import X（模块路径超过
                # 包根）且入口文件不在允许清单
                depth_ok = edge.count(".") <= 1 or \
                    any(edge == e.replace("/", ".").replace(".py", "")
                        for e in tgt["publicEntrypoints"])
                if not depth_ok:
                    violations.append(("deep-import", rel,
                                       "跨模块深 import %s（只准走公开入口）" % edge))
            graph.setdefault((mod["id"], tgt["id"]), set()).add(rel)

    # 循环依赖（managed 之间）
    if glob_cfg.get("forbidCycles"):
        for (a, b) in graph:
            if a != b and (b, a) in graph:
                violations.append(("forbid-cycles", "%s/%s" % (a, b), "循环依赖"))

    # baseline 豁免：只红新增
    base = {}
    if os.path.isfile(BASELINE):
        try:
            base = json.load(open(BASELINE, encoding="utf-8"))
        except Exception:
            base = {}
    new_v = []
    for rule, file, detail in violations:
        fp = hashlib.sha256(("%s\0%s\0%s" % (rule, file, detail)).encode("utf-8")
                            ).hexdigest()[:16]
        if fp not in base:
            new_v.append((rule, file, detail))

    for rule, file, detail in sorted(new_v):
        print("[arch] %s: %s — %s" % (rule, file, detail))
    print("architecture-check: %d violations (%d new) in %d managed files"
          % (len(violations), len(new_v), len(managed)))
    return 1 if new_v else 0


if __name__ == "__main__":
    sys.exit(main())
