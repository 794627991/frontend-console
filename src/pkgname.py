# -*- coding: utf-8 -*-
"""资源包文件名分类（零依赖，可被门户/闸门/打包侧共同引用）。

a336R（第7轮 P1-1）：本函数原先在 update_server.py，而该模块被
tools/cythonize_build.py 的 _EXCLUDE 排除出发布包 —— frozen 机上
`from src.update_server import pkg_class` 必然 ImportError，自动找包静默
失效（明明有包却报"没有选择资源包"）。

a337R（第8轮）：挪进 fcpk.py 又踩坑——fcpk 顶层 import Crypto，发布机门户
为了分个文件名就要背上加密库。故独立成零依赖模块，且对资源包名永不返回
None，调用方不再各写 fallback。

a341R（第12轮）：前 5 轮在这套正则上反复"修 A 坏 B"（每轮新增 P1）。
本轮改为**结构化分解**而不是叠正则：把 basename 拆成「资源包」左侧 / 右侧
两段分别判，每段的规则互不干扰；并把「备份过滤」限定为门户专用
（require_prefix），闸门的目的是"找到能用的包"，不该因为叫 `-old` 就找不到。
"""

import re

# 应用名（a341R 第12轮）：门户与闸门的前缀过滤共用。
# 原先 update_server 里硬编码一份，闸门侧完全没有 → 同目录 `别家工具-资源包.fcpk`
# 会被闸门选中。build.py 有自己的 APP_NAME；改名时三处需同步（tests 会兜住）。
APP_NAME = "前端控制台"

# 子集包语义关键字。英文短词加词边界——`digital`/`legit` 含 git、
# `nodejs` 含 node，无边界会把 `前端控制台-digital资源包.fcpk` 判成子集。
_SUBSET_KW = (r"拓展|扩展|claude|基础|onlyoffice|webview2|dotnet|bili|"
              r"pydeps|(?<![a-z])(?:node|git|office)(?:js|s)?(?![a-z0-9])")

# 浏览器重名下载：`资源包 (1).fcpk`。序号必须在空白/括号里。
_RE_COPY = re.compile(r"资源包[ \t]*[()（）][ \t]*\d+[ \t]*[)）][ \t]*\.fcpk$")
# 版本尾巴：`-v2` / `-v2.1`（放右侧判定，见 pkg_class）
_RE_VER = re.compile(r"[-_]v\d+(?:\.\d+)+|[-_]v\d+$")
# 副本链：`-副本`、`- 副本 (2)`、`-副本副本`、`-copy2`。
# 序号用 `\d*`（不限长）——限长会让 `-副本2024` 剥不掉、整名落兜底判子集；
# lookahead 放在重复组**外**，否则第二个副本词紧贴第一个时整组首次迭代即失败。
_RE_COPYWORD = re.compile(r"(?:[-_]?(?:副本|copy)\d*)+(?=[-_]|\.)")
# 备份/历史文件。a343R（第14轮 P1-1/P1-2）：原实现只认「紧跟资源包」或
# 「文件名结尾」两种位置，`资源包-副本-备份-v2.fcpk`（备份词后面还挂版本尾）
# 整个漏判 → 门户把它当主包发出去；`备份-资源包.fcpk`（备份词在左侧）则
# 被判成 rank 3 正牌。现改为**全串搜索备份词**（不限位置）。
# 不含英文 `old`（`-old` 是"要发的旧版全量"的常见命名，误杀会让闸门空手）；
# `旧` 限定为 `旧版/旧包/-旧/_旧/旧.fcpk`，避免误伤「怀旧」「旧金山」。
# a344R（第15轮 P2-1/P2-2/P2-3）三处收紧：
#   · 英文 bak/backup 加词边界——`bakery`/`baked`/`abak` 是正常命名，原先误杀；
#   · 中文 `旧` 补回 `旧2`/`（旧）`/`资源包旧` 形态——上一版收紧过头，
#     用户按 `-副本2024` 的习惯把旧包命名成 `-旧2` 时门户会把旧版发出去；
#   · 中英对齐：`旧版/旧包` 与英文 `old` 同义，都归「派生」档（rank 2），
#     不再一个可见一个隐藏。
_RE_BACKUP = re.compile(r"备份|(?<![a-z])(?:bak|backup)\d*(?![a-z])|"
                        r"旧版本|旧包|[-_.]旧(?:[版包\d]|[-_.]|$)|资源包旧")


def _norm(s):
    """去掉空白与括号，并把全角连字符折叠成 `-`（`资源包－拓展` 是输入法常见
    产物，不折叠会整个漏判）。故意不扩大折叠范围。"""
    s = re.sub(r"[－—–―﹣]", "-", s)
    return re.sub(r"[\s()（）]+", "", s)


def _base(name):
    return str(name or "").replace("\\", "/").rsplit("/", 1)[-1].lower()


def is_res_pkg(name, require_prefix=None, filter_backup=False):
    """是不是资源包文件名（两侧共用的前置判定）。

    a338R（第9轮）：原先 autofind 判 `"资源包" in name`、门户判
    `"-资源包" in name` —— 分裂转移到了可见性：改名成 `资源包.fcpk` 时
    闸门选得中、门户看不见。
    a340R（第11轮）：前缀比对必须先过 _norm（`前端控制台 - 资源包.fcpk`
    闸门能找到、门户看不见）。
    a341R（第12轮）：前缀补下划线形态、把前缀过滤下沉到这里。
    a342R（第13轮 P2-1，实锤）：备份过滤原先绑在 require_prefix 上，而闸门
    也传了 require_prefix=APP_NAME —— 「闸门不过滤备份」从未成立：同事机
    唯一一份包叫 `-备份`/`-bak2` 时闸门直接返回空，提示"工具无法启动"。
    现拆成独立开关 filter_backup，只有门户传 True。
    """
    b = _base(name)
    if not (b.endswith(".fcpk") and "资源包" in b):
        return False
    nb = _norm(b)
    if filter_backup and _RE_BACKUP.search(nb):
        return False
    if require_prefix:
        _pn = _norm(str(require_prefix).lower())
        _rest = nb[len(_pn):] if nb.startswith(_pn) else None
        if _rest is None:
            # 用户去掉应用名前缀的 `资源包…`
            if not nb.startswith("资源包"):
                return False
        elif not (_rest.startswith("-") or _rest.startswith("_")
                  or _rest.startswith("资源包")):
            return False
    return True


def pkg_rank(name, require_prefix=None, filter_backup=False):
    """选包优先级（a341R 第12轮）：同名同类里必须让「正牌」赢。

    前三轮反复出现的真实事故都是**同 rank 按 mtime 竞争**：`资源包-副本副本`
    （mtime 更新）顶掉真主包、`资源包备份` 顶掉真主包。只分 full/subset 两档
    不够——副本/备份/带版本尾巴的包也是 full，但绝不该顶替正牌。

      3 = 正牌主包（`<前缀>-资源包.fcpk`，无副本词、无版本尾巴）
      2 = 派生全量（重名副本 / `-副本` 链 / `-v2` / `-2024` 这类无名 tag，
          以及「没有应用名前缀」的包——闸门允许它救急，但不该压过正牌）
      1 = 子集包
      0 = 备份/历史件（`备份`/`bak`/`旧版`，任意位置）
      -1 = 不可见（不是资源包 / 前缀不符 / 门户侧的备份文件）

    a343R（第14轮 P1-2/P2-3）：备份档降到 0 —— 原先把备份件算进派生全量(2)，
    于是 `备份-资源包.fcpk`、无前缀的 `资源包备份.fcpk` 都能压过带前缀的
    真子集包，闸门装错包后复查仍缺硬资源，回到「装完还拦」的老死循环。
    降到 0 后：只存在备份件时它仍会被选中（救急），一旦有正牌或子集就让位。

    注意：本函数内部的 `pkg_class(name)` **不传** require_prefix —— class 描述
    的是"这个文件是什么"，与"这个部署该不该看见它"是两件事。调用方判断可见性
    请用返回的 -1，不要直接调 pkg_class。
    """
    if not is_res_pkg(name, require_prefix=require_prefix,
                      filter_backup=filter_backup):
        return -1
    cls = pkg_class(name)
    if cls is None:
        return -1
    _bk = bool(_RE_BACKUP.search(_norm(_base(name))))
    if cls == "subset":
        # a344R（第15轮 P1-2）：备份**子集**不可见——原先与备份全量同档靠
        # mtime 抢，选中它时装完仍缺 WebView2/.NET，回到「装完还拦」。
        # 子集本来就救不了急（缺硬资源），没有必要给它留后门。
        return -1 if _bk else 1
    if _bk:
        return 0                     # 备份全量：能救急，但让位于任何正规包
    # 没有应用名前缀（闸门的救急路径）：降一档，别压过带前缀的正规包
    if require_prefix:
        _pn = _norm(str(require_prefix).lower())
        if not _norm(_base(name)).startswith(_pn):
            return 2
    b = _base(name)
    t = _norm(b)
    core = _RE_COPYWORD.sub("", t)[:-5]
    i = core.find("资源包")
    after = core[i + 3:].lstrip("-_.") if i >= 0 else ""
    # a341R：副本词在下面 core 里已被剥掉，必须回原始 t 上判存在性
    if (_RE_COPY.search(b) or _RE_VER.search(b) or _RE_COPYWORD.search(t)
            or after or re.search(r"(?:备份|bak|backup|旧)\d*\.fcpk$", t)):
        return 2                     # 重名副本 / 副本链 / 版本尾巴 → 派生
    return 3                         # 正牌主包


def pkg_derived(name):
    """是不是"派生/留档"包：重名副本、副本链、版本尾巴、备份件。

    a344R（第15轮 P3-1）：门户原先用 `rank == 2` 推断，把**无应用名前缀的
    正牌包**也算成派生（它只是因为"没前缀"被降档）。两个语义必须分开：
    rank 是"选谁"，derived 是"要不要提示用户这可能不是最新完整包"。
    """
    b = _base(name)
    t = _norm(b)
    if _RE_COPY.search(b) or _RE_VER.search(b) or _RE_COPYWORD.search(t):
        return True
    if _RE_BACKUP.search(t):
        return True
    core = _RE_COPYWORD.sub("", t)[:-5]
    i = core.find("资源包")
    return bool(i >= 0 and core[i + 3:].lstrip("-_."))


def pkg_class(name):
    """资源包分类：'full' | 'subset' | None。

    只看 basename。结构：`<前缀>资源包<右侧>.fcpk`，左右两段分别判。

      full   : 右侧为空（`-资源包.fcpk`）、右侧是版本号（`-v2` / `-v2.1`）、
               浏览器重名副本（`资源包 (1).fcpk`）、纯副本链（`-副本`）
      subset : 右侧出现子集关键字（`-拓展` / `-claude` / `-node`…），或
               右侧有任意 tag（`-2024` / `-1` / `-基础资源`）；关键字紧贴
               资源包左侧（`claude资源包.fcpk`）也算子集
      None   : 不是资源包
    """
    if not is_res_pkg(name):
        return None
    b = _base(name)
    t = _norm(b)
    if _RE_COPY.search(b):
        return "full"          # `资源包 (1).fcpk`：浏览器重名下载
    core = _RE_COPYWORD.sub("", t)[:-5]        # 剥副本链 + 去 `.fcpk`
    i = core.find("资源包")
    if i < 0:
        return "full"
    before, after = core[:i], core[i + 3:]
    after_s = after.lstrip("-_.")
    if not after_s:
        # `资源包.fcpk` / `资源包-副本.fcpk`；但 `claude资源包.fcpk` 这类
        # 「关键字紧贴资源包左侧」是子集
        if re.search(r"(?:%s)[-_]?$" % _SUBSET_KW, before):
            return "subset"
        return "full"
    if re.fullmatch(r"v\d+(?:\.\d+)*", after_s):
        return "full"                      # `资源包-v2.1.fcpk`
    if re.search(_SUBSET_KW, after_s):
        return "subset"                    # `资源包-拓展` / `资源包2024-拓展`
    if re.search(r"(?:%s)[-_]?$" % _SUBSET_KW, before):
        return "subset"
    # a342R（第13轮 P2-3，实锤）：右侧是**无名 tag**（`-2024` / `-old` / `-1`
    # / `.old`）时判 full —— 用户把旧版全量改名留档是常规操作，判成子集会让
    # 它与真子集同档、重新回到 mtime 抢包（本轮 P2-3 端到端已复现）。
    # build.py 产出的子集包永远带关键字（`-基础/-claude/-拓展/…`），不受影响。
    return "full"
