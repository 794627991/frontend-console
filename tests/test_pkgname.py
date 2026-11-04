# -*- coding: utf-8 -*-
"""资源包文件名分类 / 选包优先级单元测试（v4.1，a342R 第13轮 P3-4）。

为什么要有这个文件：`pkgname` 的判据在第 7~13 轮里被反复修改，每轮都靠
一次性脚本验证、改完就丢 —— 「修 A 坏 B」连了五轮。这里把那些脚本固化成
可重复执行的回归网：分类期望表 + 三档 rank + 门户/闸门端到端选包。

纯标准库 + 打桩目录，不碰真实数据。直接 `python tests/test_pkgname.py`。
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import pkgname
from src.pkgname import pkg_class, pkg_rank, pkg_derived, is_res_pkg

_PASS, _FAIL = [], []
_APP = pkgname.APP_NAME


def check(name, cond, detail=""):
    (_PASS if cond else _FAIL).append(name)
    print(("  [ok] " if cond else "  [FAIL] ") + name
          + ("" if cond else "  " + str(detail)))


# ---- 分类期望表 ----------------------------------------------------------
# 每组 {名字: 期望 class}。危险方向（子集包被判 full）必须为 0。
_CLASS_CASES = {
    # 正牌主包
    "前端控制台-资源包.fcpk": "full",
    "资源包.fcpk": "full",
    "前端控制台资源包.fcpk": "full",
    "前端控制台 - 资源包.fcpk": "full",
    "前端控制台－资源包.fcpk": "full",       # 全角连字符
    "前端控制台（资源包）.fcpk": "full",
    "前端控制台_资源包.fcpk": "full",
    # 派生全量
    "前端控制台-资源包 (1).fcpk": "full",    # 浏览器重名
    "前端控制台-资源包（2）.fcpk": "full",
    "前端控制台-资源包 - 副本.fcpk": "full",
    "前端控制台-资源包 - 副本 (2).fcpk": "full",
    "前端控制台-资源包-副本副本.fcpk": "full",
    "前端控制台-资源包-copycopy.fcpk": "full",
    "前端控制台-资源包-副本2024.fcpk": "full",
    "前端控制台-资源包-v2.fcpk": "full",
    "前端控制台-资源包-v2.1.fcpk": "full",
    "前端控制台-资源包-2024.fcpk": "full",   # 无名 tag（旧版全量留档）
    "前端控制台-资源包-old.fcpk": "full",
    "前端控制台-资源包-1.fcpk": "full",
    "前端控制台-资源包-office365.fcpk": "full",   # office 后接数字不算子集
    "前端控制台-资源包-gitlab.fcpk": "full",
    "前端控制台-资源包-node_modules.fcpk": "subset",
    "前端控制台-office文档-资源包.fcpk": "full",   # 关键字在左但非紧贴
    "前端控制台-digital资源包.fcpk": "full",       # digital 含 git
    "前端控制台-legit资源包.fcpk": "full",
    # 子集包（8 个 kind + 别称）
    "前端控制台-资源包-拓展.fcpk": "subset",
    "前端控制台-资源包(拓展).fcpk": "subset",
    "前端控制台-资源包－拓展.fcpk": "subset",
    "前端控制台-资源包（副本）拓展.fcpk": "subset",
    "前端控制台-资源包2024-拓展.fcpk": "subset",
    "前端控制台-资源包2-拓展.fcpk": "subset",
    "前端控制台-资源包-拓展-v2.fcpk": "subset",
    "前端控制台-资源包-拓展(1).fcpk": "subset",
    "前端控制台-资源包-副本-拓展.fcpk": "subset",
    "前端控制台-资源包-副本-副本-拓展.fcpk": "subset",
    "前端控制台-资源包-copy拓展.fcpk": "subset",
    "前端控制台-资源包-claude.fcpk": "subset",
    "前端控制台-资源包-node.fcpk": "subset",
    "前端控制台-资源包-nodejs.fcpk": "subset",
    "前端控制台-资源包-OnlyOffice.fcpk": "subset",
    "前端控制台-资源包-基础资源.fcpk": "subset",
    "前端控制台-资源包-webview2-dotnet.fcpk": "subset",
    "前端控制台-资源包-bili.fcpk": "subset",
    "前端控制台-资源包-pydeps.fcpk": "subset",
    "资源包-拓展.fcpk": "subset",
    "前端控制台-claude资源包.fcpk": "subset",      # 关键字紧贴左
    "前端控制台-拓展-资源包.fcpk": "subset",
    "前端控制台-webview2资源包.fcpk": "subset",
    # 非资源包
    "other.fcpk": None,
    "前端控制台-其他.fcpk": None,
    "x.zip": None,
    "": None,
}


def _test_class():
    for n, want in _CLASS_CASES.items():
        check("class %s" % n, pkg_class(n) == want,
              "got %r want %r" % (pkg_class(n), want))


def _test_rank_consistency():
    """rank 与 class 不得矛盾：rank=3/2 ⇒ full，rank=1 ⇒ subset。"""
    bad = []
    for n in _CLASS_CASES:
        r, c = pkg_rank(n), pkg_class(n)
        if r < 0:
            continue
        if c == "full" and r == 1:
            bad.append((n, r, c))
        if c == "subset" and r in (2, 3):
            bad.append((n, r, c))
    check("rank/class 无矛盾", not bad, bad[:5])
    check("正牌主包 rank=3", pkg_rank("前端控制台-资源包.fcpk") == 3)
    check("副本 rank=2", pkg_rank("前端控制台-资源包-副本.fcpk") == 2)
    check("备份全量 rank=1（与正规子集同档，低于正牌主包）",
          pkg_rank("前端控制台-资源包备份.fcpk", require_prefix=_APP) == 1
          and pkg_rank("前端控制台-资源包备份.fcpk", require_prefix=_APP)
          < pkg_rank("前端控制台-资源包.fcpk", require_prefix=_APP))
    # 第16轮 P1-1：备份全量(1) 必须压过备份子集(0)——"两份备份"取全量；
    # 但备份子集仍可见（唯一一份时闸门要能装，base 预设含全部硬项）
    check("备份全量 > 备份子集",
          pkg_rank("前端控制台-资源包备份.fcpk", require_prefix=_APP)
          > pkg_rank("前端控制台-资源包-拓展-备份.fcpk",
                     require_prefix=_APP))
    check("备份子集闸门仍可见",
          pkg_rank("前端控制台-资源包-基础-备份.fcpk",
                   require_prefix=_APP) >= 0)
    # 第15轮 P2-1：bak/backup 词边界，正常命名不误杀
    check("bakery 不误杀",
          pkg_rank("前端控制台-资源包-bakery.fcpk", require_prefix=_APP) == 2)
    check("旧金山 不误杀",
          pkg_rank("前端控制台-资源包-旧金山.fcpk", require_prefix=_APP) == 2)
    check("子集 rank=1", pkg_rank("前端控制台-资源包-拓展.fcpk") == 1)


def _test_derived():
    """第16轮 P2-1：正规子集包不是留档，门户不能同时报"子集"和"派生"。"""
    for n in ("前端控制台-资源包-基础.fcpk", "前端控制台-资源包-拓展.fcpk",
              "前端控制台-资源包-claude.fcpk", "前端控制台-资源包-bili.fcpk"):
        check("derived=False %s" % n, pkg_derived(n) is False)
    for n in ("前端控制台-资源包-副本.fcpk", "前端控制台-资源包-v2.fcpk",
              "前端控制台-资源包-old.fcpk", "前端控制台-资源包备份.fcpk"):
        check("derived=True %s" % n, pkg_derived(n) is True)
    check("正牌主包 derived=False", pkg_derived("前端控制台-资源包.fcpk") is False)


def _test_visibility():
    # 门户：前缀 + 备份过滤
    ok = ck = 0
    for n, want in [
            ("前端控制台-资源包.fcpk", True),
            ("前端控制台 - 资源包.fcpk", True),
            ("前端控制台－资源包.fcpk", True),
            ("前端控制台（资源包）.fcpk", True),
            ("前端控制台_资源包.fcpk", True),
            ("资源包.fcpk", True),
            ("别家工具-资源包.fcpk", False),
            ("资源包备份.fcpk", False),
            ("前端控制台-资源包备份.fcpk", False),
            ("前端控制台-资源包.bak2.fcpk", False),
            ("前端控制台-资源包-旧版本-v2.fcpk", True),   # 第16轮 P2-2：与 -old 对齐
            ("前端控制台-资源包-副本-备份-v2.fcpk", False),   # 第14轮 P1-1
            ("前端控制台-资源包-拓展-备份-v2.fcpk", False),
            ("前端控制台-备份-资源包.fcpk", False),           # 第14轮 P1-2
            ("前端控制台-资源包-旧金山.fcpk", True),          # 不误杀
            ("前端控制台-资源包-office365.fcpk", True),
            ("前端控制台-资源包-拓展-备份.fcpk", False),
            ("前端控制台-资源包-备份中心.fcpk", True),    # 第16轮 P2-4：不误伤
            ("前端控制台-资源包-双备份切换.fcpk", True),
            ("前端控制台-资源包（旧金山）.fcpk", True)]:  # 第16轮 P2-3
        got = is_res_pkg(n, require_prefix=_APP, filter_backup=True)
        check("portal 可见 %s" % n, got == want, "got %r" % got)
        ck += 1
        ok += got == want
    # 闸门：前缀有，但**不过滤备份**（唯一一份包叫 -备份 时仍要能装）
    for n in ("前端控制台-资源包备份.fcpk", "前端控制台-资源包-备份.fcpk",
              "前端控制台-资源包-bak2.fcpk",
              "前端控制台-资源包-旧版本-v2.fcpk",
              "前端控制台-资源包-old.fcpk"):
        check("gate 可见 %s" % n,
              is_res_pkg(n, require_prefix=_APP, filter_backup=False))
    check("闸门仍排除别家工具",
          not is_res_pkg("别家工具-资源包.fcpk", require_prefix=_APP))
    check("可见性汇总", ok == ck and ck > 0, (ok, ck))


def _e2e(cases):
    """cases: [(label, [(filename, mtime)], 期望)]，期望可为
    `文件名`（两侧一致）或 `(门户期望, 闸门期望)`。
    门户与闸门各跑一次真实选包逻辑。"""
    from src import res_ui, update_server

    for label, files, want in cases:
        d = tempfile.mkdtemp(prefix="pkgname_e2e_")
        old_releases = update_server._releases_dir
        old_app = res_ui._app_dir
        old_dirs = res_ui._search_dirs
        try:
            update_server._releases_dir = lambda d=d: d
            res_ui._app_dir = lambda d=d: d
            # a343R（第14轮 P1-3）：必须同时桩搜索目录——否则会读真实
            # ~/Desktop、~/Downloads（发布者桌面常放着资源包，测试必假红）
            res_ui._search_dirs = lambda d=d: (d,)
            for n, mt in files:
                p = os.path.join(d, n)
                with open(p, "wb") as f:
                    f.write(b"x")
                os.utime(p, (mt, mt))
            por = update_server._offline_pkg()
            got_por = por["file"] if por else None
            got_af = os.path.basename(res_ui.autofind_fcpk()) or None
        finally:
            update_server._releases_dir = old_releases
            res_ui._app_dir = old_app
            res_ui._search_dirs = old_dirs
            shutil.rmtree(d, ignore_errors=True)
        w_por, w_af = want if isinstance(want, tuple) else (want, want)
        check("e2e[%s] 门户" % label, got_por == w_por,
              "got %r want %r" % (got_por, w_por))
        check("e2e[%s] 闸门" % label, got_af == w_af,
              "got %r want %r" % (got_af, w_af))


def _test_e2e():
    P = "前端控制台-资源包.fcpk"
    S = "前端控制台-资源包-拓展.fcpk"
    _e2e([
        ("主包+子集(子集新)", [(P, 1e9), (S, 2e9)], P),
        ("主包+派生副本(副本新)",
         [(P, 1e9), ("前端控制台-资源包-副本副本.fcpk", 3e9)], P),
        ("主包+备份(备份新)",
         [(P, 1e9), ("前端控制台-资源包备份.fcpk", 3e9)], P),
        ("主包+子集+副本全在",
         [(P, 1e9), (S, 2e9), ("前端控制台-资源包-副本.fcpk", 3e9)], P),
        ("只有派生副本",
         [("前端控制台-资源包-副本.fcpk", 1e9)],
         "前端控制台-资源包-副本.fcpk"),
        ("只有子集", [(S, 1e9)], S),
        ("主包带空格+子集",
         [("前端控制台 - 资源包.fcpk", 1e9), (S, 2e9)],
         "前端控制台 - 资源包.fcpk"),
        ("主包+别家工具(别家新)",
         [(P, 1e9), ("别家工具-资源包.fcpk", 3e9)], P),
        ("主包+浏览器重名(重名新)",
         [(P, 1e9), ("前端控制台-资源包 (1).fcpk", 3e9)], P),
        ("两个子集(取新的)", [(S, 1e9),
                              ("前端控制台-资源包-claude.fcpk", 2e9)],
         "前端控制台-资源包-claude.fcpk"),
        # 门户排除备份，闸门必须还能选（否则唯一一份包装不上）
        ("两份备份(全量 vs 子集)",
         [("前端控制台-资源包-拓展-备份.fcpk", 3e9),
          ("前端控制台-资源包备份.fcpk", 1e9)],
         (None, "前端控制台-资源包备份.fcpk")),
        # 第16轮：备份全量与正规子集同档(1)——备份件是完整包，内容上强于
        # 子集，同档按 mtime 取它是可接受的；关键是它绝不能压过正牌主包。
        ("备份+子集(同档取新的)",
         [("前端控制台-资源包备份.fcpk", 3e9), (S, 1e9)],
         # 门户排除备份 → 只剩子集；闸门同档按 mtime → 备份（完整包）
         (S, "前端控制台-资源包备份.fcpk")),
        ("只有备份(闸门要能选、门户不能)",
         [("前端控制台-资源包备份.fcpk", 1e9)],
         (None, "前端控制台-资源包备份.fcpk")),
        ("无关 fcpk", [("other.fcpk", 1e9)], None),
        ("空目录", [], None),
        # 第13轮 P2-3 实锤：旧版全量改名 -old 后不能被子集顶掉
        ("旧版全量-old + 子集(子集新)",
         [("前端控制台-资源包-old.fcpk", 1e9), (S, 2e9)],
         "前端控制台-资源包-old.fcpk"),
    ])


def main():
    for title, fn in (("分类期望表", _test_class),
                      ("rank 一致性", _test_rank_consistency),
                      ("derived 判定", _test_derived),
                      ("可见性口径", _test_visibility),
                      ("端到端选包", _test_e2e)):
        print("[%s]" % title)
        fn()
    print("\n%d passed, %d failed" % (len(_PASS), len(_FAIL)))
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
