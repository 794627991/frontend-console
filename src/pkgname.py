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
_RE_VER = re.compile(r"[-_]v\d+(?:\.\d+)*")
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
# a345R（第16轮）最终形态：备份词必须**独立成段**（前后是分隔符/边界），
# 避免 `备份中心`/`双备份切换`/`bakery` 误伤；`资源包旧` 必须后接边界，
# 避免 `（旧金山）` 归一化后被误杀。`旧版/旧包` 已移出——它们与英文
# `old` 同义，属「派生」档（rank 2、门户可见），不再一个可见一个隐藏。
# a346R（第17轮 P1-1/P1-2/P2-2）：**左右对称**——"让位词"不论出现在「资源包」
# 左侧还是右侧都要认。第 14~16 轮三个 P1 都是同一件事换形态复发：
#   `备份-资源包`(14轮) → `备份资源包`(17轮) → `旧-资源包`(17轮)。
# 现在规定：备份词前后必须是 串首/分隔符/数字/「资源包」/结尾；
# `旧` 除上述外还接受「版」「包」（旧版、旧包），但拒绝「旧金山」「怀旧」。
_RE_BACKUP = re.compile(r"(?:^|[-_.]|资源包)备份(?:$|[-_.\d]|资源包)|"
                        r"(?<![a-z])(?:bak|backup)\d*(?![a-z])")
_RE_OLD = re.compile(r"(?:^|[-_.]|资源包)旧(?:$|[-_.\d版包]|资源包)|"
                     r"(?<![a-z])old(?![a-z])")


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
    b = _base(name)
    t = _norm(b)
    _bk = bool(_RE_BACKUP.search(t))
    if cls == "subset":
        # a345R（第16轮 P1-1，实锤回归）：上一版让备份子集直接不可见，结果
        # 闸门也一刀切 —— 用户唯一一份包是 `-资源包-基础-备份.fcpk` 时工具
        # 直接起不来。而 build.py 的 base 预设（webview2+dotnet+pydeps）恰好
        # 就是 MANIFEST 里全部三个硬项，它**能**救急。
        # 档位差：备份全量(1) > 备份子集(0)；改名/留档子集(0) 让位于正规子集(1)。
        # 「只有备份子集」仍能装（它是唯一候选）。
        return 1 if (not _bk and not pkg_derived(name)) else 0
    if _bk:
        return 1                     # 备份全量：与正规子集同档，让位于全量
    # 没有应用名前缀（闸门的救急路径）：降一档，别压过带前缀的正规包
    if require_prefix:
        _pn = _norm(str(require_prefix).lower())
        if not t.startswith(_pn):
            return 2
    # a346R（第17轮 P2-1）：派生判定统一走 pkg_derived——原先把
    # 副本/版本尾/无名 tag 在这里重复写一遍，与 pkg_derived 两处维护，
    # 于是 `-基础-old`（子集 + 旧 tag）被判成正牌子集、与正规子集同档抢包。
    if pkg_derived(name):
        return 2
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
    # 让位词左右对称扫（第17轮 P1-1/P1-2：`备份资源包`、`旧-资源包`）
    if _RE_BACKUP.search(t) or _RE_OLD.search(t):
        return True
    core = _RE_COPYWORD.sub("", t)[:-5]
    i = core.find("资源包")
    if i < 0:
        return False
    after = core[i + 3:].lstrip("-_.")
    if not after:
        return False
    if re.fullmatch(r"v\d+(?:\.\d+)*", after):
        return True
    # a347R（第18轮 P1-2，实锤回归）：右侧没有子集关键字 ⇒ 是**无名 tag**
    # （`-2024` / `-1` / `-2024.09`），即用户把旧版全量改名留档。
    # 上一版把「剥掉关键字+版本尾后只剩数字」当正规产物，`-2024` 因此
    # 被判成 rank 3 正牌，与真主包按 mtime 抢且不报"可能不是最新"。
    if not re.search(_SUBSET_KW, after):
        return True
    # a346R（第17轮 P2-1）：正规子集（`-基础`/`-拓展`/`-claude`…）是
    # build.py --preset 的唯一规范产物，不算留档；但 `-基础-old`、
    # `-拓展-2024`、`-拓展-v3` 剥掉关键字后还剩无名 tag → 是留档。
    # a347R（第18轮 P3-2）：剥掉子集关键字与版本/日期尾后，剩下能**独立成段**
    # 的字母才算留档。`-拓展-bakery` / `-拓展-旧金山` 是带注释的正规子集，
    # 不该被门户打上"派生/留档包"（与第16轮"旧金山/备份中心不误杀"同口径）。
    rest = re.sub(_SUBSET_KW, "", after)
    rest = re.sub(r"v\d+(?:\.\d+)*", "", rest)
    rest = re.sub(r"[-_.\d]", " ", rest).strip()
    # 剩下的每一段都必须是「已认可的无名 tag」才算留档：纯数字已在上一步
    # 抹掉；含字母/中文的段——只有 old / 旧 / 备份 类才是留档标记，
    # 其余（bakery / 旧金山 / 备份中心 之类）是注释，属正规子集。
    for seg in rest.split():
        if _RE_BACKUP.search(seg) or _RE_OLD.search(seg):
            return True
    return False


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
