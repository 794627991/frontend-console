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
_RE_VER = re.compile(r"资源包-v\d+(?:\.\d+)*\.fcpk$")
_RE_COPYWORD = re.compile(r"资源包-(?:副本|copy)[^/]*\.fcpk$")


def _norm(s):
    """去掉空白与括号——吃下各种重命名形态后再做关键字判断。"""
    return re.sub(r"[\s()（）]+", "", s)


def pkg_class(name):
    """资源包分类：'full' | 'subset' | None。

    判定只看 basename（目录名不参与——第5轮 P2-1 的教训）。

      subset : 含 `资源包-<子集关键字>`（`-资源包-拓展`、`-资源包-claude`…），
               也认括号变体 `资源包(拓展).fcpk`
      full   : `…资源包.fcpk`、浏览器重名副本（`资源包 (1).fcpk`）、
               `资源包-副本.fcpk`、`资源包-v<数字>…fcpk`（带版本后缀全量）
      None   : 不是资源包（不做任何猜测）
    """
    if not name:
        return None
    b = str(name).replace("\\", "/").rsplit("/", 1)[-1].lower()
    if not b.endswith(".fcpk") or "资源包" not in b:
        return None
    t = _norm(b)
    # ① 子集关键字优先——归一化后 `资源包(拓展)` 会变成 `资源包拓展`，
    #    先判关键字才不会把它误当成全量
    if re.search(r"资源包[-_]?(?:%s)" % _SUBSET_KW, t) and \
            not t.startswith("资源包.fcpk") and t != "资源包.fcpk":
        return "subset"
    # ② 全量形态
    if t == "资源包.fcpk" or _RE_COPY.search(b) or _RE_VER.search(t):
        return "full"
    if _RE_COPYWORD.search(t):
        return "full"
    # ③ 兜底：含 `资源包-` 即子集，否则全量（永不返回 None）
    return "subset" if "资源包-" in t else "full"
