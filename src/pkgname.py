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
# 副本名（`资源包-副本` / `资源包 - 副本.fcpk`）。a338R（第9轮 P2-2）：
# 原实现在 `资源包-副本-拓展` 这类「副本 + 子集后缀」上会判成 full。
# 现在先把副本词剥掉再判子集关键字——副本只说明"这是重名下载"，
# 不覆盖子集语义。
_RE_COPYWORD = re.compile(r"(?:[-_][ \t]*(?:副本|copy)[ \t]*(?=[-_]|\.))+")
# 纯「重名副本」整名（`资源包 - 副本.fcpk` 归一化后 `资源包-副本.fcpk`）——
# 剥掉副本词后只剩 `.fcpk` 就说明除了副本词没有其它语义
_RE_ONLY_COPY = re.compile(r"资源包[-_]*(?:副本|copy)[-_]*\.fcpk$")


def _norm(s):
    """去掉空白与括号——吃下各种重命名形态后再做关键字判断。"""
    return re.sub(r"[\s()（）]+", "", s)


def is_res_pkg(name):
    """是不是资源包文件名（两侧共用的前置判定）。

    a338R（第9轮 P2-3）：原先 autofind 判 `"资源包" in name`、门户判
    `"-资源包" in name` —— 分裂从分类转移到了**可见性**：用户把包改名成
    `资源包.fcpk` 时闸门选得中、门户看不见。统一到这里，两边都只问它。
    """
    if not name:
        return False
    b = str(name).replace("\\", "/").rsplit("/", 1)[-1].lower()
    return b.endswith(".fcpk") and "资源包" in b


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
    # 先剥副本词（`资源包-副本-拓展` → `资源包-拓展`），再判一切
    t2 = _RE_COPYWORD.sub("-", t)
    # ① 子集关键字最先判（归一化后 `资源包(拓展)` → `资源包拓展`；
    #    剥副本后 `资源包-副本-拓展` 仍是子集）
    if re.search(r"资源包[-_]?(?:%s)" % _SUBSET_KW, t2):
        return "subset"
    # ② 全量形态：重名副本 / 带版本后缀 / 就是「资源包-副本」整名
    if _RE_COPY.search(b) or _RE_VER.search(t) or _RE_ONLY_COPY.search(t):
        return "full"
    # ③ 兜底：含 `资源包-` 即子集，否则全量（对资源包名永不返回 None）
    return "subset" if "资源包-" in t2 else "full"
