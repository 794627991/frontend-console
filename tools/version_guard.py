# -*- coding: utf-8 -*-
"""提交号守卫（a645）：让 `v4.1.0-aNNN` 不再靠人肉 git log -5 取号。

撞号成了传统（a584 双胞胎、a641 三次），根因不是粗心，是**手工取号**：
看一眼当前最大号 → 写代码 → 几分钟后提交，这段时间里别的会话已经用掉了
同一号。本工具把取号搬到提交瞬间，并把两件事钉死：

  1. commit-msg 钩子：标题的 aNNN 一律改写为「全仓库已用最大号 + 1」。
     写对了不动；写错/写旧/跳号/和别人撞，都由钩子纠正。
  2. pre-commit 钩子：新增行里的**未来号**（aNNN > 本次号）必然是笔误，
     自动改成本次号并重新 add；比本次号小的视为历史引用，只提示不改
     （"a629 曾把…" 这类跨提交引用必须保留原号）。

命令行（不装钩子也能用）：
  python tools/version_guard.py next         # 打印下一个号
  python tools/version_guard.py check        # 体检：撞号/跳号/未来号
  python tools/version_guard.py install      # 装两个钩子到 .git/hooks
  python tools/version_guard.py uninstall    # 卸掉（只卸本工具的）
"""
import os
import re
import subprocess
import sys

# 标题形如 `v4.1.0-a643 修 worker …`；只认这套 harness 号（与
# src/version.py 的 APP_VERSION 无关，那个是发版号）。
TITLE_RE = re.compile(r"^v(\d+\.\d+\.\d+)-a(\d+)")
# 任意位置的 aNNN（含 `v4.1.0-a643` 里的）。\b 在 `-a643` 处成立。
A_RE = re.compile(r"\ba(\d{3,})\b")
HOOK_BEGIN = "# >>> version_guard"


def _git(repo, *args):
    try:
        p = subprocess.run(["git"] + list(args), cwd=repo,
                           capture_output=True, timeout=30)
        return p.stdout.decode("utf-8", "replace")
    except Exception:
        return ""


def repo_root(start=None):
    d = os.path.abspath(start or os.path.dirname(__file__))
    for _ in range(8):
        if os.path.isdir(os.path.join(d, ".git")):
            return d
        nd = os.path.dirname(d)
        if nd == d:
            break
        d = nd
    return ""


def used_numbers(repo):
    """全仓库（所有分支）标题里出现过的 a 号集合。"""
    out = _git(repo, "log", "--all", "--format=%s")
    nums = set()
    for line in out.splitlines():
        m = TITLE_RE.match(line.strip())
        if m:
            nums.add(int(m.group(2)))
    return nums


def head_version(repo):
    """(主.次.修订, 号) —— 取 HEAD 标题的第一个版本号。"""
    out = _git(repo, "log", "-n", "50", "--format=%s")
    for line in out.splitlines():
        m = TITLE_RE.match(line.strip())
        if m:
            return m.group(1), int(m.group(2))
    return "", 0


def next_version(repo):
    """下一个号 = 全仓库已用最大号 + 1（没有历史时从 1 起）。"""
    nums = used_numbers(repo)
    return (max(nums) + 1) if nums else 1


def _retitle(msg, ver, num):
    """把消息里的标题号改成 (ver, num)。

    返回 (新消息, 原标题号或 None)。正文里**等于原标题号**的版本号同步
    改写；其他号的引用视为跨提交历史引用，保持原样。
    """
    lines = msg.split("\n")
    old_num = None
    for i, line in enumerate(lines):
        m = TITLE_RE.match(line)
        if m:
            old_num = int(m.group(2))
            lines[i] = TITLE_RE.sub("v%s-a%d" % (ver, num), line, count=1)
            break
    if old_num is None:
        return msg, None
    new = []
    old_tok = "a%d" % old_num
    new_tok = "a%d" % num
    for line in lines:
        if old_num != num:
            line = A_RE.sub(lambda mm: new_tok if mm.group(0) == old_tok
                            else mm.group(0), line)
        new.append(line)
    return "\n".join(new), old_num


def cmd_next(repo):
    ver, _ = head_version(repo)
    print("v%s-a%d" % (ver or "4.1.0", next_version(repo)))


def cmd_check(repo):
    nums = used_numbers(repo)
    if not nums:
        print("没有历史版本号")
        return 0
    mx = max(nums)
    print("已用最大号 a%d，下一个 v4.1.0-a%d" % (mx, mx + 1))
    # 只看最近 200 个提交的标题——远古历史里的撞号改不了，也没意义
    out = _git(repo, "log", "-n", "200", "--format=%s")
    seen = {}
    for line in out.splitlines():
        m = TITLE_RE.match(line.strip())
        if m:
            seen.setdefault(int(m.group(2)), []).append(
                line.strip().split(" ")[0])
    dups = {k: v for k, v in seen.items() if len(v) > 1}
    if dups:
        print("最近 200 个提交里仍有撞号（已发生，无法回改）：")
        for k in sorted(dups):
            print("  a%d ×%d" % (k, len(dups[k])))
        return 1
    print("最近 200 个提交无撞号")
    return 0


# ---- 钩子 ----------------------------------------------------------------

def _hook_path(repo, name):
    return os.path.join(repo, ".git", "hooks", name)


HOOK_TMPL = """#!/bin/sh
%(begin)s —— 由 tools/version_guard.py install 生成，勿手改
# 守卫本体不在仓库里时静默放行（别让一次误装挡住所有提交）。
t="$(git rev-parse --show-toplevel)/tools/version_guard.py"
[ -f "$t" ] || exit 0
command -v python >/dev/null 2>&1 || exit 0
python "$t" %(mode)s
rc=$?
# 2 = 本工具异常（python/文件/环境），放行
[ "$rc" = "2" ] && exit 0
exit $rc
%(end)s
"""


def install(repo):
    os.makedirs(_hook_path(repo, "x") and os.path.dirname(
        _hook_path(repo, "x")), exist_ok=True)
    for name, mode in (("commit-msg", "hook-commit-msg \"$1\""),
                       ("pre-commit", "hook-pre-commit")):
        p = _hook_path(repo, name)
        old = ""
        if os.path.isfile(p):
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                old = f.read()
            if HOOK_BEGIN not in old:
                print("已存在无关的 %s，拒绝覆盖：%s" % (name, p))
                return 3
        body = HOOK_TMPL % {"begin": HOOK_BEGIN, "end": "# <<< version_guard",
                            "mode": mode}
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
        try:
            os.chmod(p, 0o755)
        except OSError:
            pass
    print("已安装 commit-msg + pre-commit 钩子（%s）" % os.path.dirname(
        _hook_path(repo, "x")))
    return 0


def uninstall(repo):
    for name in ("commit-msg", "pre-commit"):
        p = _hook_path(repo, name)
        if os.path.isfile(p):
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                s = f.read()
            if HOOK_BEGIN in s:
                os.remove(p)
                print("已移除 .git/hooks/%s" % name)
    return 0


def _ver_for_commit(repo):
    """提交瞬间的版本：主.次.修订 取 HEAD，号取全仓库 max+1。"""
    ver, _ = head_version(repo)
    return (ver or "4.1.0"), next_version(repo)


def hook_commit_msg(path, repo=None):
    repo = repo or repo_root()
    if not repo:
        return 2
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            msg = f.read()
    except OSError:
        return 2
    ver, num = _ver_for_commit(repo)
    head = head_version(repo)[1]
    new, old = _retitle(msg, ver, num)
    if old is None:
        # 没有版本前缀的提交（merge/revert 等）只提示，不改写
        print("[version_guard] 提交标题缺少 v%s-aN 版本号，未改写" % ver,
              file=sys.stderr)
        return 0
    if new != msg:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(new)
        why = ("HEAD 已是 a%d" % head) if old <= head else "号不连续/撞号"
        print("[version_guard] %s：a%d → a%d（下一个可用的号）"
              % (why, old, num), file=sys.stderr)
    return 0


def _staged_added_lines(repo):
    """{文件: [(行文本)]} —— 只取暂存区里**新增的行文本**（不含行号）。

    pre-commit 里要改的是工作区文件再 add，行号会随改写漂移，没有意义；
    按文本匹配就够——只有出现在新增行里的未来号才算笔误。
    """
    out = _git(repo, "diff", "--cached", "-U0", "--no-color")
    res, cur = {}, ""
    for line in out.split("\n"):
        if line.startswith("+++ b/"):
            cur = line[6:]
            res.setdefault(cur, [])
        elif line.startswith("+") and not line.startswith("+++"):
            if cur:
                res[cur].append(line[1:])
    return res


def hook_pre_commit(repo=None):
    repo = repo or repo_root()
    if not repo:
        return 2
    _ver, num = _ver_for_commit(repo)
    bumped = []
    for path, rows in _staged_added_lines(repo).items():
        if not path.endswith((".py", ".js", ".css", ".html", ".md")):
            continue
        fp = os.path.join(repo, path)
        if not os.path.isfile(fp):
            continue
        tok_re = re.compile(r"\ba(\d{3,})\b")
        future = set()
        for row in rows:
            for m in tok_re.finditer(row):
                if int(m.group(1)) > num:
                    future.add(m.group(0))
        if not future:
            continue
        with open(fp, "r", encoding="utf-8", errors="replace") as f:
            src = f.read()
        new_src = src
        for tok in future:
            new_src = new_src.replace(tok, "a%d" % num)
        if new_src != src:
            with open(fp, "w", encoding="utf-8", newline="\n") as f:
                f.write(new_src)
            _git(repo, "add", "--", path)
            bumped.append("%s(%s)" % (path, "/".join(sorted(future))))
    if bumped:
        print("[version_guard] 未来号改成本次 a%d：%s"
              % (num, "、".join(bumped)), file=sys.stderr)
    return 0


def main(argv):
    cmd = (argv[1] if len(argv) > 1 else "").strip()
    repo = repo_root()
    if cmd == "hook-commit-msg":
        return hook_commit_msg(argv[2] if len(argv) > 2 else "")
    if cmd == "hook-pre-commit":
        return hook_pre_commit()
    if not repo:
        print("不在 git 仓库内", file=sys.stderr)
        return 2
    if cmd == "next":
        cmd_next(repo); return 0
    if cmd == "check":
        return cmd_check(repo)
    if cmd == "install":
        return install(repo)
    if cmd == "uninstall":
        return uninstall(repo)
    print(__doc__)
    return 0 if not cmd else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
