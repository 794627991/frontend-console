# -*- coding: utf-8 -*-
"""a650 版本面板全功能一期的后端断言：
  ① _git_ref_ok 非法名拦截  ② _log_plan 的 graph/all/rev  ③ 分支分类
  （feature/x 这种带斜杠的必须在本地列表）④ 脏工作区切换分支 409
  ⑤ discard 未跟踪文件走「删文件」而非 checkout（并落快照）
全程 monkeypatch _run，不碰真实仓库。直接 `py tests/test_vcs_git_ops.py`。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import src.app_state as _st
_TMP = os.path.join(os.environ.get("TEMP", ROOT), "vcs_gitops_test_home")
os.makedirs(_TMP, exist_ok=True)
_st.HOME_DIR = _TMP
_st.DATA_DIR = os.path.join(_TMP, "data")
_st._HOME_CFG = {"data_dir": _st.DATA_DIR}

from src import vcs

_PASS, _FAIL = [], []


def check(name, cond, detail=""):
    if cond:
        _PASS.append(name)
        print("  PASS  %s" % name)
    else:
        _FAIL.append(name)
        print("  FAIL  %s  %s" % (name, detail))


def _client():
    from flask import Flask
    app = Flask(__name__)
    app.register_blueprint(vcs.vcs_bp)
    return app.test_client()


class _Fake(object):
    """把 _run 换成按 argv 关键字分派的假 git/svn。"""

    def __init__(self, table):
        self.table = table
        self.calls = []

    def __call__(self, argv, cwd, to):
        self.calls.append(list(argv))
        for key, resp in self.table:
            if all(k in argv for k in key):
                return resp
        return (0, "", "")

    def hit(self, *words):
        return [c for c in self.calls if all(w in c for w in words)]


def _patch_run(fake, guard_root="D:\\fake"):
    vcs._run = fake
    vcs._guard = lambda root, need_tool=False: ("git", guard_root, None, True)


def main():
    print("== 1. _git_ref_ok 拦截 ==")
    bad = ["", "-x", "a b", "a..b", "a~1", "a^", "a:b", "a?b", "a*b",
           "a[b", "a\\b", "a/", "/a", "a//b", "x" * 201]
    check("非法名全拒", all(not vcs._git_ref_ok(x) for x in bad),
          str([x for x in bad if vcs._git_ref_ok(x)]))
    good = ["master", "feature/x", "release-1.0", "v1.0.0", "深/分支"]
    check("正常名全放行", all(vcs._git_ref_ok(x) for x in good),
          str([x for x in good if not vcs._git_ref_ok(x)]))

    print("== 2. _log_plan graph / all / rev ==")
    e, g, c, sv, skip, lim = vcs._log_plan("git", {"limit": 5, "graph": True, "all": True})
    check("graph+all 落到 argv", e is None and "--graph" in g and "--all" in g, str(g))
    e, g, c, sv, skip, lim = vcs._log_plan("git", {"limit": 5})
    check("默认不带 graph/all", "--graph" not in g and "--all" not in g, str(g))
    e, g, c, sv, skip, lim = vcs._log_plan("git", {"limit": 5, "rev": "master"})
    check("rev 目标追加", e is None and g[-1] == "master", str(g))
    check("rev 非法 400", vcs._log_plan("git", {"rev": "a..b"})[0][1] == 400)

    print("== 3. 分支分类（refs/heads 的斜杠名不当事远程）==")
    fmt_out = ("feature/x\x1fabc123\x1forigin/feature/x\x1f[ahead 2]\x1fdo x\n"
               "master\x1fdef456\x1forigin/master\x1f\x1fmain line")
    fake = _Fake([
        (("rev-parse",), (0, "master", "")),
        (("for-each-ref", "refs/heads"), (0, fmt_out, "")),
        (("for-each-ref", "refs/remotes"),
         (0, "origin/master\x1fdef456\x1f\x1f\x1fmain line\n"
             "origin/HEAD\x1fdef456\x1f\x1f\x1fmain line\n"
             "origin/dev\x1f999\x1f\x1f\x1fdev work", "")),
    ])
    _patch_run(fake)
    r = _client().post("/api/vcs/branches", json={"root": "D:\\fake"})
    j = r.get_json()
    names = [b["name"] for b in (j.get("local") or [])]
    check("带斜杠的本地分支在 local", j.get("ok") and "feature/x" in names, str(j)[:200])
    check("当前分支标记", any(b["current"] for b in (j.get("local") or [])
                              if b["name"] == "master"), str(j.get("local"))[:200])
    check("ahead 解析", [b["ahead"] for b in (j.get("local") or [])
                          if b["name"] == "feature/x"] == [2], str(j.get("local"))[:200])
    rn = [b["name"] for b in (j.get("remote") or [])]
    check("远程列表剔除 origin/HEAD", "origin/HEAD" not in rn and "origin/dev" in rn, str(rn))
    check("detached=false", j.get("detached") is False and j.get("current") == "master",
          str(j.get("current")))

    print("== 4. 脏工作区切换分支 → 409 + 文件清单 ==")
    fake = _Fake([
        (("status",), (0, " M src/a.py\x1e?? new.txt", "")),
        (("switch",), (0, "", "")),
    ])
    _patch_run(fake)
    r = _client().post("/api/vcs/branch/switch", json={"root": "D:\\fake", "name": "dev"})
    j = r.get_json()
    check("脏 → 409", r.status_code == 409 and j.get("dirty") is True, str(j)[:200])
    check("附脏文件清单", "src/a.py" in (j.get("files") or []), str(j.get("files")))
    check("未真执行 switch", not fake.hit("switch"), str(fake.calls)[:200])
    r2 = _client().post("/api/vcs/branch/switch",
                        json={"root": "D:\\fake", "name": "dev", "dirty": "ignore"})
    check("dirty=ignore 才执行", fake.hit("switch") and r2.get_json().get("ok"),
          str(r2.get_json())[:200])

    print("== 5. discard 未跟踪文件 ==")
    d = os.path.join(_TMP, "wc")
    os.makedirs(d, exist_ok=True)
    newp = os.path.join(d, "new.txt")
    with open(newp, "w", encoding="utf-8") as f:
        f.write("hello")
    fake = _Fake([
        (("ls-files",), (0, "new.txt", "")),
    ])
    _patch_run(fake, guard_root=d)
    r = _client().post("/api/vcs/discard",
                       json={"root": d, "paths": ["new.txt"], "confirm": True})
    j = r.get_json()
    check("未跟踪文件被删", j.get("ok") and not os.path.exists(newp), str(j)[:200])
    check("回报 removed", "new.txt" in (j.get("removed") or []), str(j)[:200])
    check("不调用 checkout", not fake.hit("checkout"), str(fake.calls))
    snaps = j.get("snapshot") or ""
    check("丢弃前落快照", bool(snaps) and os.path.isfile(
        os.path.join(snaps, "new.txt")), snaps)

    print("== 6. discard 必须显式确认 ==")
    fake = _Fake([])
    _patch_run(fake, guard_root=d)
    r = _client().post("/api/vcs/discard", json={"root": d, "paths": ["x"]})
    check("缺 confirm → 400", r.status_code == 400 and not fake.calls, str(r.get_json()))

    print("== 7. --graph 行首连线列不污染 rev ==")
    g = ("* \x1fa1b2c3d\x1fa1b2c\x1fgaoyi\x1f2026-11-18\x1fa650 版本面板\x1f"
         " (HEAD -> master)\n"
         "| * \x1f9f8e7d\x1f9f8e7\x1fgaoyi\x1f2026-11-17\x1f并行会话\x1f (origin/dev)")
    fake = _Fake([(("log",), (0, g, ""))])
    _patch_run(fake)
    j = _client().post("/api/vcs/log",
                       json={"root": "D:\\fake", "limit": 5, "graph": 1, "all": 1}).get_json()
    cs = j.get("commits") or []
    check("两条都解析出来", len(cs) == 2, str(j)[:200])
    check("rev 无连线前缀", cs and cs[0]["rev"] == "a1b2c3d", str(cs[:1]))
    check("graph 列保留", cs and cs[1]["graph"].strip() == "| *", str(cs[:2]))
    check("subject 完整", cs and cs[0]["msg"] == "a650 版本面板", str(cs[:1]))
    j2 = _client().post("/api/vcs/log",
                        json={"root": "D:\\fake", "limit": 5}).get_json()
    check("不带 graph 时不剥首段（保持既有解析）",
          (j2.get("commits") or [{}])[0].get("rev") == "* ", str(j2)[:160])

    print("=" * 56)
    print("通过 %d / 失败 %d" % (len(_PASS), len(_FAIL)))
    for x in _FAIL:
        print("  -", x)
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
