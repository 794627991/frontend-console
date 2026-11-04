# -*- coding: utf-8 -*-
"""资源包文件名分类（零依赖，可被门户/闸门/打包侧共同引用）。

a336R（第7轮 P1-1）：本函数原先在 update_server.py，而该模块被
tools/cythonize_build.py 的 _EXCLUDE 排除出发布包 —— frozen 机上
`from src.update_server import pkg_class` 必然 ImportError，自动找包静默
失效（明明有包却报"没有选择资源包"）。

a337R（第8轮 P1/P2-2/P2-3/P2-4）：上一版挪进 fcpk.py 又踩了两个坑：
  ① fcpk 顶层 `from Crypto.Cipher import AES` —— 门户（发布机可能没装
     pycryptodome）为了分个类就被绑上加密库，api/versions 会直接 500；
  ② 三处调用方各自写「认不出时怎么办」的 fallback，口径必然再次分裂。
本模块只 import re，且对任何「.fcpk + 含资源包」的名字**永不返回 None**
（判不出语义时按「有无子集后缀」兜底）——调用方只消费返回值，结构上
不可能分裂。
"""

import re

# 子集包语义关键字（与 res_install.ORDER + 常见中文别名对齐）
_SUBSET_KW = (r"拓展|扩展|claude|基础|node|git|dotnet|webview2|onlyoffice|"
              r"bili|pydeps|office")

# 浏览器重名下载形态：`资源包 (1).fcpk` / `资源包（2）.fcpk`。
# 序号**必须**处在空白/括号里——`资源包2.fcpk` 可能是用户手改的子集包，
# 不能无条件当副本（第8轮 P2-2 实锤：原 `\d*` 把 `资源包-2024` 也吃成 full）。
_RE_COPY = re.compile(r"资源包[ \t]*[()（）][ \t]*\d+[ \t]*[)）][ \t]*\.fcpk$")
_RE_VER = re.compile(r"资源包[-_]v\d+(?:\.\d+)*\.fcpk$")
# 副本名（`资源包-副本` / `资源包 - 副本 (2).fcpk` / `资源包（副本）-拓展`）。
# a338R（第9轮 P2-2）：原实现在 `资源包-副本-拓展` 上会判成 full。
# a339R（第10轮 P2-1/P2-2/P3-1）三处修正：
#   · 副本词前导可选——中文输入法写出的 `资源包（副本）-拓展` 归一化后
#     副本词前面是「包」而不是 `-`，原正则不匹配 → 子集被判 full；
#   · 副本词吞掉紧随的序号——Windows 二次同名复制产出 `资源包 - 副本 (2)`，
#     原正则要求副本词后紧跟 `-`/`.`，序号把它挡住 → 真全量被判 subset，
#     门户会把子集包发给同事（a325R 修掉的死锁循环复活）；
#   · 剥离用空串而不是 `-`——原 `sub("-")` 会产生 `资源包--拓展`，让 ① 的
#     `资源包[-_]?` 精确分支永远不命中，只是靠兜底侥幸判对。
_RE_COPYWORD = re.compile(r"(?:[-_]?(?:副本|copy)\d*(?=[-_]|\.))+")
# 纯「重名副本」整名（剥完副本词只剩主名）——含序号、多重副本
_RE_ONLY_COPY = re.compile(r"资源包[-_]*\.fcpk$")


def _norm(s):
    """去掉空白/括号，并把全角连字符折叠成 `-`（`资源包－拓展` 是输入法常见
    产物，不折叠会整个漏判）。故意**不**扩大空白折叠范围。"""
    s = re.sub(r"[－—–―﹣]", "-", s)
    return re.sub(r"[\s()（）]+", "", s)


def is_res_pkg(name, require_prefix=None):
    """是不是资源包文件名（两侧共用的前置判定）。

    a338R（第9轮 P2-3）：原先 autofind 判 `"资源包" in name`、门户判
    `"-资源包" in name` —— 分裂从分类转移到了**可见性**：用户把包改名成
    `资源包.fcpk` 时闸门选得中、门户看不见。统一到这里，两边都只问它。

    a339R（第10轮 P3-3）：门户放宽门槛后会误纳 `别家工具-资源包.fcpk`、
    `资源包备份.fcpk` 这类同目录文件。传 require_prefix（应用名）可要求
    basename 以 `<应用名>-` 开头，或以 `资源包` 开头（用户去掉前缀的形态）。
    """
    if not name:
        return False
    b = str(name).replace("\\", "/").rsplit("/", 1)[-1].lower()
    if not (b.endswith(".fcpk") and "资源包" in b):
        return False
    if require_prefix:
        pre = str(require_prefix).lower() + "-"
        if not (b.startswith(pre) or b.startswith("资源包")):
            return False
    return True


def pkg_class(name):
    """资源包分类：'full' | 'subset' | None。

    判定只看 basename（目录名不参与——第5轮 P2-1 的教训）。

      subset : 含子集关键字（`-资源包-拓展`、`资源包(拓展)`、`资源包-claude`…），
               **包括副本形态**（`资源包-副本-拓展`——副本不改变子集语义）
      full   : `…资源包.fcpk`、浏览器重名副本（`资源包 (1).fcpk`）、
               `资源包-v<数字>…fcpk`（带版本后缀全量）
      None   : 不是资源包（不做任何猜测）
    """
    if not is_res_pkg(name):
        return None
    b = str(name).replace("\\", "/").rsplit("/", 1)[-1].lower()
    t = _norm(b)
    # 先剥副本词（含序号），再判一切：`资源包-副本-拓展` → `资源包-拓展`
    t2 = _RE_COPYWORD.sub("", t)
    # ① 子集关键字最先判。a339R（第10轮 P2-2）：不再要求关键字紧跟在
    #    `资源包[-_]?` 之后——`资源包（副本）拓展`、`资源包2024-拓展` 这类
    #    中间夹了副本词/数字的形态会被漏判成全量（危险方向：子集顶替主包）。
    #    只要名字里有子集关键字就判子集（保守方向）。
    if re.search(r"(?:%s)" % _SUBSET_KW, t2):
        return "subset"
    # ② 全量形态：浏览器重名副本 / 带版本后缀 / 剥掉副本词后只剩主名
    if _RE_COPY.search(b) or _RE_VER.search(t) or _RE_ONLY_COPY.search(t2):
        return "full"
    # ③ 兜底：含 `资源包-` 即子集，否则全量（对资源包名永不返回 None）
    return "subset" if "资源包-" in t2 else "full"
