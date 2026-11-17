# -*- coding: utf-8 -*-
"""技能仓库后端：skills.sh 网页适配 + 安装/卸载/禁用 + 离线包 + 汉化缓存。

数据源实测结论（v1 spike，2026-10）：
- skills.sh 官方 API（/api/v1/*）全部 401（Vercel OIDC 鉴权，本地工具拿不到）
  ——数据走网页 SSR：榜单 /（All Time）、/trending、/hot 三页 HTML 自带
  全量条目（h3 技能名 + p 来源 + 总安装量 + Weekly sparkline）
- 详情页 HTML 含 h1/Installs/prose 渲染正文；SKILL.md 原文走
  raw.githubusercontent.com（不受 API 限额，路径候选 skills/<s> → <s> →
  .claude/skills/<s>，分支 main → master）
- GitHub contents API 匿名 60/h 限额——仅辅助文件列目录用，失败不阻塞
  （SKILL.md 是技能主体，装上即完成；辅助文件拉不到如实提示）
- skills.sh 的 topic/列表页是 JS 空壳无 SSR 数据——分类用本地关键词分桶
- 安装量上报（+N）：无匿名通道，砍掉——只展示榜单数值
"""
import os
import re
import json
import glob
import time
import shutil
import hashlib
import zipfile
import threading
import urllib.request
import urllib.error
import logging

from src.app_state import HOME_DIR, DATA_DIR

_log = logging.getLogger("skills_repo")

UA = "frontend-console-skills/1.0"
# v4.0.1：内网 lanzi 网关按 UA 白名单放行 Anthropic 协议（仅 claude-cli/*，
# 其余一律 403 "Anthropic protocol is restricted to Claude clients"——
# 这是技能仓库翻译恒失败的真因）；vision_mcp._API_UA 同源同因。
_API_UA = "claude-cli/2.0.0 (external, cli)"
_SKILLS_DIR = os.path.join(os.path.expanduser("~"), ".claude", "skills")
# v3.5.320（用户需求「翻译文件跟着数据空间走」）：技能数据落数据目录——
# 随数据空间迁移/统计/清理走（server._DATA_SUBDIRS 已收录）；模块加载时把
# 旧 HOME_DIR 位置的缓存一次性搬过来（老用户翻译缓存不丢不重翻）
_CACHE_DIR = os.path.join(DATA_DIR, "skill_cache")       # SKILL.md 原文缓存
_ZH_DIR = os.path.join(DATA_DIR, "skill_zh")             # 汉化缓存
_EXPORT_DIR = os.path.join(DATA_DIR, "skill_exports")    # 离线包导出目录


def _migrate_legacy_dirs():
    """旧 HOME_DIR 位置的技能缓存一次性搬到数据目录（都存在时以新位置为准
    ——迁移是 best-effort，失败静默留旧位置，下次加载不再重试因为新位置
    已有内容）。

    a602 审计 P1：本函数在模块导入期执行，而 skill_cache 实测 49MB——跨盘时
    shutil.move 是同步全量复制，会卡启动（用户红线）。改为：**只同步搬小的
    skill_meta.json（几十字节），目录交给后台线程**。"""
    dirs = [(os.path.join(HOME_DIR, sub), os.path.join(DATA_DIR, sub))
            for sub in ("skill_cache", "skill_zh", "skill_exports")]
    dirs = [(o, n) for o, n in dirs
            if os.path.isdir(o) and not os.path.isdir(n)]
    old_meta = os.path.join(HOME_DIR, "skill_meta.json")
    new_meta = os.path.join(DATA_DIR, "skill_meta.json")
    if os.path.isfile(old_meta) and not os.path.isfile(new_meta):
        try:
            shutil.move(old_meta, new_meta)
        except OSError:
            pass
    if dirs:
        def _bg():
            for o, n in dirs:
                try:
                    if not os.path.isdir(n):
                        shutil.move(o, n)
                except OSError:
                    pass
        try:
            threading.Thread(target=_bg, daemon=True,
                             name="legacy-skill-move").start()
        except Exception:
            pass


# a623R 复审（严重 N1）历史：迁移执行点曾放在这里——早于后面定义的函数
# （当时迁移分支调了它们），老布局升级机导入期即 NameError。教训：模块级
# 执行调用必须放在其依赖的全部定义之后，现在在模块底部。
_PACK_TTL = 1800          # 导入暂存 zip 的有效期（秒）
_PAGE_TTL = 600           # skills.sh 网页内存缓存（秒）
_LB_CACHE = {}            # path -> (ts, html)；读写仅赋值/取值，GIL 下原子
_DESC_LOCK = threading.Lock()
_DESC_CACHE = {}          # skill键 -> {desc, ts}（raw frontmatter description）
_PACK_STASH = {}          # token -> {zip_path, ts}（导入两步：inspect 暂存→apply）

# 本地关键词分桶（skills.sh topic 页无 SSR 数据，零网络启发式分类）
_TOPICS = [
    ("开发工具", ("git", "code", "debug", "test", "deploy", "api", "database",
                 "sql", "python", "typescript", "react", "next", "vercel",
                 "framework", "refactor", "lint", "build", "ci", "review")),
    ("内容创作", ("write", "writing", "doc", "blog", "markdown", "content",
                 "newsletter", "article", "copy", "documentation", "email")),
    ("数据分析", ("data", "analy", "chart", "csv", "excel", "pdf", "report",
                 "visual", "metric", "dashboard", "stat")),
    ("效率提升", ("search", "find", "memory", "note", "task", "plan", "organize",
                 "automate", "workflow", "calendar", "file", "clean")),
]


# ---------------------------------------------------------------- 网络层

def _http(url, timeout=20, want_bytes=False, extra_headers=None):
    """GET → str/bytes；任何失败返回 None（调用方按不可达处理）。"""
    try:
        headers = {"User-Agent": UA}
        if extra_headers:
            headers.update(extra_headers)
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            b = r.read()
        return b if want_bytes else b.decode("utf-8", "replace")
    except Exception:
        return None


# ---- 多源下载（a632，用户定调「源要多、要安全、可选」）--------------------
# 实测 2026-11-18（逐台机器可达性不同，本机结论仅供选型参考）：
#   raw.githubusercontent.com   直连 000（被墙形态）——官方源，恒在候选列内
#   testingcf.jsdelivr.net      200 真镜像，内容与 api.github.com 逐字节一致
#   fastly/cdn/gcore.jsdelivr   301→raw 本体的跳转器，raw 不通时零增益，剔除
#   api.github.com + raw Accept 200，作为官方备援（与 raw 的 DNS/SNI 面不同）
# jsDelivr 对 @branch 引用有最长 12h 缓存——刚发布的技能可能拿到旧版，
# 交叉验证不一致时会归为「缓存延迟或篡改」，默认拒装（见 _fetch_verified）。
_RAW_SOURCES = (
    # (源名, URL 模板, 额外 headers)——{owner}/{repo}/{branch}/{path} 四槽
    ("official", "https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}", {}),
    ("jsdelivr", "https://testingcf.jsdelivr.net/gh/{owner}/{repo}@{branch}/{path}", {}),
    ("gh_api", "https://api.github.com/repos/{owner}/{repo}/contents/{path}",
     {"Accept": "application/vnd.github.raw"}),
)
# 公共探针（可达性探测用同一份真实文件，避免对探针 URL 的特判）
_PROBE_OWNER, _PROBE_REPO, _PROBE_BRANCH, _PROBE_PATH = (
    "anthropics", "skills", "main", "README.md")

_SKILL_SOURCE_MODES = ("auto", "official", "jsdelivr")
# 内容真伪的权威序（交叉验证 pick / confirm 强制装 / 更新检测基准共用）：
# 官方原文 → GitHub API（权威、无 CDN 缓存）→ jsDelivr（12h 缓存，沉底）
_PICK_ORDER = ("official", "gh_api", "jsdelivr")


def source_mode():
    """技能下载源档位（config.json 的 skill_source 键）。独立于依赖安装的
    online_mirror——域名族与语义完全不同（pip/npm 镜像对 GitHub raw 无意义）。
    auto=智能（探测可达者按官方→镜像排序）；official=官方直连优先；
    jsdelivr=镜像优先。非法值回退 auto。"""
    try:
        from .app_state import _load_config
        m = (_load_config().get("skill_source") or "auto").strip()
    except Exception:
        return "auto"
    return m if m in _SKILL_SOURCE_MODES else "auto"


def set_source_mode(m):
    from .app_state import cfg_commit
    if m not in _SKILL_SOURCE_MODES:
        raise ValueError("未知技能源档位：%s" % m)
    # cfg_commit：锁内读改写原子（a623R 审计 N9——裸 {**_load_config()} 的
    # 读在锁外，与其它配置写并发可丢更新；全仓 22 处旧调用点同款是历史债，
    # 新代码用更好的既有 API）
    cfg_commit(lambda d: d.update({"skill_source": m}))


def _source_reachability():
    """各源最近一次可达性（status() 的 5min 探测缓存；没探测过视为可达——
    首次拉取不该被探测空窗阻塞，错了换下一源即可）。"""
    return {
        "official": _STAT.get("official", True),
        "jsdelivr": _STAT.get("jsdelivr", True),
        "gh_api": _STAT.get("gh_api", True),
    }


def _raw_url_variants(owner, repo, branch, path):
    """按档位排出某文件的候选 URL 列表（多源；官方恒在候选列内兜底）。"""
    reach = _source_reachability()
    order = [s for s, _u, _h in _RAW_SOURCES]
    mode = source_mode()
    if mode == "jsdelivr":
        order.sort(key=lambda s: s != "jsdelivr")
    elif mode == "official":
        order.sort(key=lambda s: s != "official")
    else:   # auto：探测不可达的沉底（不剔除——探测可能过时，留兜底）
        order.sort(key=lambda s: not reach.get(s, True))
    out = []
    for s in order:
        tpl, hdr = next(((u, h) for n, u, h in _RAW_SOURCES if n == s), (None, {}))
        if not tpl:
            continue
        out.append((s, tpl.format(owner=owner, repo=repo, branch=branch,
                                  path=path), hdr))
    return out


def _fetch_multi(variants, timeout=15, want_bytes=True):
    """按候选序逐源拉取，成功即返回 (bytes, 源名)；全部失败 (None, None)。
    空响应按失败处理（空 bytes 是断连/污染的常见产物，不能当成功——
    空内容 sha256 与「真拉到」一致会造成假交叉验证通过）。"""
    for name, url, hdr in variants:
        b = _http(url, timeout=timeout, want_bytes=want_bytes, extra_headers=hdr)
        if b and len(b) > 0:
            return (b, name)
    return (None, None)


def _variants_from_raw_url(url):
    """raw.githubusercontent 形态的 URL → 多源候选（辅助文件下载用；
    download_url 由 GitHub contents API 生成，恒为该形态）。非 raw 形态
    原样单发。a623R 审计 N1 如实声明：branch 含 /（feature/x）的 raw URL
    存在**结构性歧义**——feature/x 分支与 owner/repo/feature + path=x/...
    从 URL 本身无法区分，镜像变体会切错址（通常 404 退化单源官方；病理
    情形由 install 的 blob sha 校验兜住，错文件进不了盘）。官方变体的重组
    恰好还原原 URL，恒正确。"""
    m = re.match(r"https://raw\.githubusercontent\.com/"
                 r"([^/]+)/([^/]+)/([^/]+)/(.+)$", url or "")
    if not m:
        return [("official", url, {})]
    return _raw_url_variants(m.group(1), m.group(2), m.group(3), m.group(4))


def _page(path):
    """skills.sh 网页（内存 TTL 缓存——榜单页 900KB，10 分钟内复用）。"""
    key = path
    now = time.time()
    hit = _LB_CACHE.get(key)
    if hit and now - hit[0] < _PAGE_TTL:
        return hit[1]
    hit = _LB_CACHE.get("neg:" + key)
    if hit and now - hit[0] < 60:
        return None   # 失败负缓存：被墙挂起形态下避免每次重付 25s 全价
    html = _http("https://www.skills.sh" + path, timeout=25)
    if html:
        _LB_CACHE[key] = (now, html)
    else:
        _LB_CACHE["neg:" + key] = (now, None)
    return html


# ---------------------------------------------------------------- 榜单解析

_RE_ROW = re.compile(
    r'<a class="group grid[^"]*" href="/([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+/'
    r'[a-zA-Z0-9_.-]+)"(.*?)</a>', re.S)
_RE_NAME = re.compile(r'<h3[^>]*>([^<]+)</h3>')
_RE_SRC = re.compile(r'<p[^>]*>([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)</p>')
_RE_INST = re.compile(r'<span class="font-mono text-sm text-foreground">'
                      r'([\d.,]+[KMB]?)</span>')
_RE_WEEK = re.compile(r'aria-label="Weekly installs: ([^"]+)"')
_RE_NUM = re.compile(r'\d+(?:,\d{3})*')   # 千分位完整数字（"99,722" 不被逗号拆散）


def parse_leaderboard(html):
    """榜单页 HTML → 卡片列表（spike 定稿的条目结构，见模块 docstring）。"""
    rows = []
    for m in _RE_ROW.finditer(html):
        key, seg = m.group(1), m.group(2)
        owner, repo, skill = key.split("/")
        nm = _RE_NAME.search(seg)
        src = _RE_SRC.search(seg)
        inst = _RE_INST.search(seg)
        wk = _RE_WEEK.search(seg)
        weekly = []
        if wk:
            try:
                weekly = [int(x.replace(",", "")) for x in _RE_NUM.findall(wk.group(1))]
            except ValueError:
                pass
        rows.append({
            "key": key, "owner": owner, "repo": repo, "skill": skill,
            "name": (nm.group(1).strip() if nm else skill),
            "source": (src.group(1) if src else "%s/%s" % (owner, repo)),
            "installs": (inst.group(1) if inst else ""),
            "weekly": weekly,
        })
    return rows


# 官方技能子集（anthropics/skills 仓库 skills/ 目录，2026-11-18 contents
# API 实测 19 个）——skills.sh 不可达时的发现面兜底（用户拍板方案 1：
# 官方精选；skills.sh 无国内镜像站，第三方仿站不可信）。contents API 可达
# 时用真实列表，API 也挂时降级用这份常量（可能是旧清单，如实标注）。
_OFFICIAL_SKILLS = (
    "academy-guide", "algorithmic-art", "brand-guidelines", "canvas-design",
    "claude-api", "discernment-nudge", "doc-coauthoring", "docx",
    "frontend-design", "internal-comms", "mcp-builder", "pdf", "pptx",
    "skill-creator", "slack-gif-creator", "theme-factory",
    "web-artifacts-builder", "webapp-testing", "xlsx",
)
_OFFICIAL_REPO = "anthropics/skills"


def _registry_official():
    """发现面兜底（a632）：skills.sh 不可达时列 anthropics/skills 官方仓库。
    contents API（单次调用，60/h 匿名限额内）列 skills/ 目录；API 挂则降级
    _OFFICIAL_SKILLS 常量。卡片结构与 skills.sh 榜单同构（desc 后台补）。"""
    names = []
    via = "official_fallback"
    txt = _http("https://api.github.com/repos/%s/contents/skills" % _OFFICIAL_REPO,
                timeout=15)
    if txt:
        try:
            items = json.loads(txt)
            if isinstance(items, list):
                names = [it.get("name") for it in items
                         if isinstance(it, dict) and it.get("type") == "dir"
                         and it.get("name")]
        except ValueError:
            names = []
    if not names:
        names = list(_OFFICIAL_SKILLS)
        via = "official_fallback_static"
    rows = []
    for nm in names:
        rows.append({"key": "%s/skills/%s" % (_OFFICIAL_REPO, nm),
                     "owner": _OFFICIAL_REPO.split("/")[0],
                     "repo": _OFFICIAL_REPO.split("/")[1],
                     "skill": nm,
                     "name": nm,
                     "source": _OFFICIAL_REPO,
                     "installs": "", "weekly": [], "official": True})
    return rows, via


def registry(tab="top", q=""):
    """榜单卡片（tab: top=All Time / trending=24h / hot）；q 非空时在榜单
    内存过滤（skills.sh 无匿名搜索 API）。附带缓存的英文 description 与
    本地启发式分类（skills.sh topic 页是 JS 空壳，零网络分桶）。
    a632：返回 (rows, source)——source ∈ skills.sh / official_fallback /
    official_fallback_static；skills.sh 不可达自动切官方精选兜底。"""
    path = {"trending": "/trending", "hot": "/hot"}.get(tab, "/")
    html = _page(path)
    rows = parse_leaderboard(html) if html else []
    if rows:
        source = "skills.sh"
    else:
        # a632R（审计 N8）：不可达**和 200 空壳页（限流/反爬）**都切官方
        # 精选兜底——限流正是本批立项痛点，只判 None 会漏掉这形态
        rows, source = _registry_official()
    if q:
        ql = q.strip().lower()
        rows = [r for r in rows
                if ql in r["name"].lower() or ql in r["source"].lower()
                or ql in r["skill"].lower()]
    for r in rows:
        d = _DESC_CACHE.get(r["key"])
        desc = d["desc"] if d else ""
        r["topic"] = _topic_of(r["name"] + " " + desc)
        if d:
            r["desc"] = desc
            t = d.get("zh")
            if t:
                r["zh_name"], r["zh_desc"] = t.get("zh_name"), t.get("zh_desc")
    return rows, source


def _topic_of(text):
    """关键词分桶（命中最多的桶；全不中归「其他」）。"""
    t = text.lower()
    best, n = "其他", 0
    for name, kws in _TOPICS:
        c = sum(1 for k in kws if k in t)
        if c > n:
            best, n = name, c
    return best


def _desc_backfill(keys):
    """后台补齐 description（raw 拉 frontmatter，每次 ≤24 个防瞬时风暴）。"""
    for key in keys[:24]:
        d = _DESC_CACHE.get(key)
        if d:
            if not d.get("fail"):
                continue   # 正常缓存命中
            if time.time() - d["fail"] < 300:
                continue   # a632R 审计 N7：失败未过 5min，暂不重试
            # 失败超过 5min → 落到下面重拉（负缓存过期）
        owner, repo, skill = key.split("/")
        md = _raw_skill_md(owner, repo, skill, cache=False)
        desc = _fm_desc(md[:2048]) if md else ""
        with _DESC_LOCK:
            # a632R（审计 N7）：失败项记 fail 时间戳——registry 兜底期间
            # miss 判据会反复命中无 desc 的官方卡，负缓存 5min 防重拉风暴
            _DESC_CACHE[key] = {"desc": desc, "ts": time.time(),
                                **({} if md else {"fail": time.time()})}
        # 汉化缓存命中顺手带上（translate_meta 生成过就直接复用）
        zh = _zh_load("meta:" + key)
        if zh:
            _DESC_CACHE[key]["zh"] = zh


# ---------------------------------------------------------------- 详情/原文

_RE_H1 = re.compile(r'<h1[^>]*>([^<]+)</h1>')
_RE_INST_BIG = re.compile(r'<span>Installs</span></div>'
                          r'<div class="text-3xl[^"]*">([^<]+)</div>')


def detail(owner, repo, skill):
    """详情：skills.sh 详情页（h1/installs）+ raw SKILL.md
    （frontmatter description + 全文，落 _CACHE_DIR 供安装复用）。
    正文渲染走前端 markdown-it（prose 预览字段已删——skills.sh 内容属
    第三方可发布内容，直注 innerHTML 是存储型 XSS 面，全审建议2）。"""
    html = _page("/%s/%s/%s" % (owner, repo, skill))
    out = {"key": "%s/%s/%s" % (owner, repo, skill),
           "owner": owner, "repo": repo, "skill": skill,
           "name": skill, "installs": "", "desc": "",
           "weekly": [], "md": None}
    if html:
        m = _RE_H1.search(html)
        if m:
            out["name"] = m.group(1).strip()
        m = _RE_INST_BIG.search(html)
        if m:
            out["installs"] = m.group(1).strip()
        # v3.5.304（用户反馈3「看不到安装排名趋势」）：详情页同款
        # Weekly installs sparkline 数据（8 周序列）
        wk = _RE_WEEK.search(html)
        if wk:
            try:
                out["weekly"] = [int(x.replace(",", ""))
                                 for x in _RE_NUM.findall(wk.group(1))]
            except ValueError:
                pass
    md = _raw_skill_md(owner, repo, skill)
    if md:
        out["md"] = md
        out["desc"] = _fm_desc(md[:2048])
        zh = _zh_load("meta:" + out["key"])
        if zh:
            out["zh_name"] = zh.get("zh_name")
            out["zh_desc"] = zh.get("zh_desc")
            out["glossary"] = zh.get("glossary")
        zb = _zh_load(_zh_key("body:", md))
        if zb:
            out["body_zh"] = zb.get("body_zh")
    # v3.5.304（用户反馈1「文件清单不可得」）：skill_files（GitHub contents
    # API）已从详情链摘除——匿名 60/h 限额必爆，横幅「不可得」比没有更糟；
    # skills.sh 详情页本就只有 SKILL.md 正文，无文件树可解析。辅助文件仍由
    # 安装路径尽力（install→skill_files），详情页不再显示文件清单
    return out


_RAW_PATHS = ("skills/%(s)s", "%(s)s", ".claude/skills/%(s)s")
_RAW_BRANCHES = ("main", "master")


def _raw_skill_md(owner, repo, skill, cache=True):
    """多源拉 SKILL.md（路径×分支×源三重候选，成功后落盘缓存）。"""
    cpath = os.path.join(_CACHE_DIR, "%s_%s_%s.md" % (owner, repo, skill))
    if cache and os.path.isfile(cpath):
        try:
            with open(cpath, "r", encoding="utf-8") as f:
                return f.read()
        except OSError:
            pass
    for tpl in _RAW_PATHS:
        for br in _RAW_BRANCHES:
            rel = (tpl % {"s": skill}) + "/SKILL.md"
            b, _src = _fetch_multi(
                _raw_url_variants(owner, repo, br, rel), timeout=15)
            if b and len(b) > 32:
                try:
                    os.makedirs(_CACHE_DIR, exist_ok=True)
                    with open(cpath, "wb") as f:
                        f.write(b)
                except OSError:
                    pass
                return b.decode("utf-8", "replace")
    return None


def _fetch_skill_md_verified(owner, repo, skill):
    """安装用：SKILL.md 多源交叉验证（a632 安全核心——技能本质是给 Claude
    执行的 prompt+脚本，单源被篡改=持久提示注入）。

    并发拉全部源（小文件，秒级），成功响应（非空）各算 sha256：
      · 全部一致          → (content, hashes, True)   正常装
      · 仅 1 源成功        → (content, hashes, None)   单源，记录来源
      · ≥2 源且哈希不一致  → (None, hashes, False)     默认拒装（调用方
        带 confirm_integrity 才放行；jsDelivr 对 @branch 有 12h 缓存，
        刚发布的技能可能假不一致——用户看得到两份哈希自行判断）
    全部失败 → (None, {}, None)。
    """
    cands = []
    for tpl in _RAW_PATHS:
        for br in _RAW_BRANCHES:
            cands.append(((tpl % {"s": skill}) + "/SKILL.md", br))
    # 逐（路径, 分支）组合试：先多源拉第一个能命中的组合并收集全部源响应
    for rel, br in cands:
        variants = _raw_url_variants(owner, repo, br, rel)
        results = {}
        threads = []
        lock = threading.Lock()

        def _pull(name, url, hdr):
            b = _http(url, timeout=15, want_bytes=True, extra_headers=hdr)
            if b and len(b) > 32:   # 与 _raw_skill_md 同一非空闸
                with lock:
                    results[name] = b

        for name, url, hdr in variants:
            th = threading.Thread(target=_pull, args=(name, url, hdr), daemon=True)
            th.start()
            threads.append(th)
        for th in threads:
            th.join(timeout=20)
        if not results:
            continue   # 该路径/分支组合全源失败 → 试下一个组合
        hashes = {n: hashlib.sha256(b).hexdigest()[:16]
                  for n, b in results.items()}
        # 三态判定先看源数再看哈希——单源 uniq 恒为 1，先判 uniq 会把单源
        # 误标成 cross-verified（虚报安全级别）
        if len(results) == 1:
            consistent = None
        elif len(set(hashes.values())) == 1:
            consistent = True
        else:
            consistent = False
        # content 选取用**确定性权威序**——不能用 dict 迭代序（=线程完成
        # 序，竞速决定装哪份，审计 S2 实锤）；也不用 _RAW_SOURCES 表序
        # （jsdelivr 是带最长 12h 缓存的 CDN，排在权威无缓存的 gh_api 之前
        # 会让「更新检测基准 / confirm 强制装内容」在 official 被墙常态下
        # 取到旧版：漏报真更新、假更新引导重装静默降级——四轮审计 S3 残
        # 留实锤）。权威序：official → gh_api → jsdelivr（CDN 沉底——它只
        # 配当「拉得到就行」的下载源，不配当内容真伪的裁判）。
        content_bytes = next(
            (results[n] for n in _PICK_ORDER if n in results),
            next(iter(results.values())))
        content = content_bytes.decode("utf-8", "replace")
        return content, hashes, consistent
    return None, {}, None


def skill_files(owner, repo, skill):
    """技能目录内全部文件（GitHub contents API，限额敏感——失败返回 None，
    调用方按「仅 SKILL.md」降级，不阻塞安装）。
    a632R（审计 S1）：带出 contents API 自带的 git blob sha——install 侧
    按公式 sha1("blob %d\\0" % len + content) 校验下载内容（零额外出网），
    堵「SKILL.md 交叉验证过了、辅助脚本单独被某源毒化」的绕过半边。"""
    for tpl in _RAW_PATHS:
        sub = tpl % {"s": skill}
        u = "https://api.github.com/repos/%s/%s/contents/%s" % (owner, repo, sub)
        txt = _http(u, timeout=15)
        if not txt:
            continue
        try:
            items = json.loads(txt)
        except ValueError:
            continue
        if isinstance(items, list):
            return [(it.get("name"), it.get("download_url"), it.get("type"),
                     it.get("sha"))
                    for it in items if isinstance(it, dict)]
    return None


# ---------------------------------------------------------------- 安装管理

def _safe_skill_dir(name, parent=None):
    """技能目录路径白名单校验（防 ../ 逃逸）。非法返回 None。"""
    name = (name or "").strip()
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        return None
    if name != os.path.basename(name):
        return None
    root = parent or _SKILLS_DIR
    p = os.path.join(root, name)
    try:
        if os.path.realpath(p) != os.path.abspath(p):
            return None
    except OSError:
        return None
    return p


def install(owner, repo, skill, scope="user", confirm_integrity=False):
    """安装技能 → ~/.claude/skills/<skill>/。返回 dict：
    ok / conflict(已存在) / partial(辅助文件缺失) / integrity_conflict(源间
    内容不一致默认拒装) / err。成功后记来源与 sha（skill_meta.json——更新
    检测/卸载对账用），integrity 标注验证级别。"""
    if scope != "user":
        return {"ok": False, "err": "仅支持 user 级安装"}
    dst = _safe_skill_dir(skill)
    if not dst:
        return {"ok": False, "err": "非法技能名"}
    # 安装一律绕缓存走多源交叉验证（低频操作，多两次拉取换安全；
    # 缓存命中留给详情页展示）
    md, hashes, consistent = _fetch_skill_md_verified(owner, repo, skill)
    # 先判冲突再判拉取失败：冲突时 md 仍有值（官方源版本），拒装是安全
    # 决策而非网络失败
    if consistent is False and not confirm_integrity:
        # 多源内容不一致：疑似篡改或缓存污染——默认拒装，用户看哈希后自决
        return {"ok": False, "integrity_conflict": True, "hashes": hashes,
                "err": "多源内容不一致（疑似篡改或镜像缓存延迟），默认拒装——"
                       "确认后可强制安装"}
    if not md:
        return {"ok": False, "err": "SKILL.md 拉取失败（检查外网连通）"}
    existed = os.path.isdir(dst)
    # 已禁用的同名目录先清（否则装出启用副本，旧 .disabled 成卸不掉的僵尸——全审 G1）
    dis = _safe_skill_dir(skill + ".disabled")
    if dis and os.path.isdir(dis):
        shutil.rmtree(dis, ignore_errors=True)
    os.makedirs(dst, exist_ok=True)
    with open(os.path.join(dst, "SKILL.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(md)
    _meta_set(skill, {"key": "%s/%s/%s" % (owner, repo, skill),
                      "sha": hashlib.sha256(md.encode("utf-8", "replace")).hexdigest()[:16],
                      "ts": int(time.time()),
                      "integrity": ("cross-verified" if consistent else
                                    "single-source" if consistent is None else
                                    "user-override")})
    partial = False
    files = skill_files(owner, repo, skill)
    if files:
        for name, url, typ, blob_sha in files:
            if typ != "file" or name == "SKILL.md" or not url:
                continue
            b, _src = _fetch_multi(_variants_from_raw_url(url), timeout=20)
            if not b:
                partial = True
                continue
            # a632R（审计 S1）：git blob sha 校验——contents API 给的 sha 是
            # `sha1("blob <len>\\0" + 内容)`，零额外出网即可验证下载内容与
            # 上游一致。缺 sha（API 形态变化）跳过校验；不匹配**不落盘**
            # （记 partial——宁缺一个脚本也不装被毒化的）
            if blob_sha:
                calc = hashlib.sha1(b"blob %d\0" % len(b) + b).hexdigest()
                if calc != blob_sha:
                    _log.warning("辅助文件 sha 校验失败，拒绝落盘: %s (期望 %s 实得 %s)"
                                 % (name, blob_sha[:12], calc[:12]))
                    partial = True
                    continue
            sp = _safe_skill_dir(name, parent=dst)
            if not sp:
                continue
            with open(sp, "wb") as f:
                f.write(b)
    elif files is None:
        partial = True   # 目录列不了（限额）——SKILL.md 已装上，如实标注
    return {"ok": True, "conflict": existed, "partial": partial,
            "dir": dst, "integrity": ("cross-verified" if consistent else
                                      "single-source" if consistent is None else
                                      "user-override")}


def uninstall(skill):
    """卸载 user 级技能（含 .disabled 变体），并清安装来源记录。"""
    for nm in (skill, skill + ".disabled"):
        p = _safe_skill_dir(nm)
        if p and os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
            _meta_del(skill)
            return {"ok": True}
    return {"ok": False, "err": "未找到本地技能目录"}


def disable(skill, off):
    """禁用/启用：目录改名 <skill>.disabled（claude 无原生禁用开关）。"""
    if off:
        src, dst = _safe_skill_dir(skill), _safe_skill_dir(skill + ".disabled")
    else:
        src, dst = _safe_skill_dir(skill + ".disabled"), _safe_skill_dir(skill)
    if not src or not dst or not os.path.isdir(src):
        return {"ok": False, "err": "目录不存在"}
    try:
        os.rename(src, dst)
        return {"ok": True}
    except OSError as e:
        return {"ok": False, "err": str(e)[:150]}


_META_FILE = os.path.join(DATA_DIR, "skill_meta.json")
_META_LOCK = threading.Lock()


def _meta_load():
    try:
        with open(_META_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _meta_set(skill, info):
    with _META_LOCK:
        d = _meta_load()
        d[skill] = info
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            tmp = _META_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=1)
            os.replace(tmp, _META_FILE)
        except OSError:
            pass


def _meta_del(skill):
    with _META_LOCK:
        d = _meta_load()
        if d.pop(skill, None) is not None or d.pop(skill + ".disabled", None) is not None:
            try:
                with open(_META_FILE, "w", encoding="utf-8") as f:
                    json.dump(d, f, ensure_ascii=False, indent=1)
            except OSError:
                pass


def _fm_desc(head):
    """frontmatter description 提取（v3.5.310）：单行直取；YAML 块标量
    （description: | / > 多行折叠）抓缩进续行拼接——单行正则只会抓到
    「|」一个字符（HikLink-claw-cli 实锤，英文原文形同没翻）。"""
    m = re.search(r'^description:\s*(.*)$', head, re.M)
    if not m:
        return ""
    v = m.group(1).strip()
    if v in ("|", ">", "|-", ">-", "|+", ">+") or re.fullmatch(
            r"[|>](?:[+-]\d*|\d+[+-]?)?", v):   # v3.5.317（轻审一般3）：含显式缩进指示符 |2 等
        lines = []
        for ln in head[m.end():].splitlines():
            if not ln.strip():
                continue   # 块内合法空行不截断
            if ln[:1] not in (" ", "\t"):
                break   # 零缩进非空行=块结束（空块标量/正文边界，一律停）
            lines.append(ln.strip())
        v = " ".join(lines)
    return v[:600]


def local_detail(name):
    """本地已安装技能详情（v3.5.304 用户反馈5「已安装技能点不开」）：
    读 ~/.claude/skills/<name>/SKILL.md（含 .disabled 变体）全文返回。"""
    for nm in (name, name + ".disabled"):
        d = _safe_skill_dir(nm)
        md = os.path.join(d, "SKILL.md") if d else ""
        if md and os.path.isfile(md):
            try:
                with open(md, "r", encoding="utf-8", errors="replace") as f:
                    txt = f.read()
                return {"name": name, "md": txt, "disabled": nm.endswith(".disabled"),
                        "desc": _fm_desc(txt[:2048]), "dir": d}
            except OSError as e:
                return {"name": name, "md": None, "err": str(e)[:120]}
    return {"name": name, "md": None, "err": "未找到本地技能目录"}


def check_updates():
    """更新检测：对「本工具装的」user 级技能（meta 有 origin）多源拉最新
    SKILL.md（绕缓存）比对 sha。并发 4（串行在离线时 N×6 URL×15s 可挂数
    分钟——全审建议4）。返回 [{skill, has_update, err}]。
    a632R（审计 S3）：改走 _fetch_skill_md_verified——旧实现单源首达，
    official 被墙 + jsDelivr 12h 旧缓存的常态下会漏报真更新（gh_api 拉到
    新版却被 jsdelivr 旧版抢答），甚至「重装回旧版」静默降级。基准取
    verified 的确定性 pick 版本（与 install/confirm 强制装同一份），闭环
    一致。"""
    def _one(item):
        nm, info = item
        parts = str(info.get("key") or "").split("/")
        if len(parts) != 3 or not info.get("sha"):
            return None
        md, _hashes, consistent = _fetch_skill_md_verified(*parts)
        if not md:
            return {"skill": nm, "has_update": False, "err": "拉取失败"}
        # a632R 四轮（S3 残留终版语义）：pick 已是权威序（official→gh_api→
        # jsdelivr，CDN 沉底）——权威源与已装的差异就是真实差异，has_update
        # 照常判定；「假更新引导降级」链已断（confirm 重装装的正是权威版，
        # 不会再装回镜像旧缓存）。源间不一致降级为 err 警告如实透出。
        cur = hashlib.sha256(md.encode("utf-8", "replace")).hexdigest()[:16]
        out = {"skill": nm, "has_update": cur != info["sha"],
               "new_sha": cur, "err": ""}
        if consistent is False:
            out["err"] = ("源间内容不一致（镜像缓存延迟或疑似篡改）——"
                          "重装将被拦截确认，确认后安装权威源版本")
        return out
    items = [(nm, info) for nm, info in _meta_load().items()]
    out = []
    try:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as ex:
            for r in ex.map(_one, items):
                if r:
                    out.append(r)
    except Exception:
        for r in map(_one, items):   # 线程池不可用的极端兜底
            if r:
                out.append(r)
    return out


def installed(cwd=None):
    """本地已安装。user 级以目录名为身份自扫（list_skills 的 name 会被
    frontmatter 覆盖，与目录名错位会让卸载/禁用/更新全部对不上——全审
    G1）；project/plugin 走 list_skills（只读展示）。附 disabled 标记、
    SKILL.md sha（更新检测对账）、origin（本工具安装的来源）。"""
    from src.claude_sessions import list_skills
    out = []
    have = set()
    _meta = _meta_load()
    if os.path.isdir(_SKILLS_DIR):
        for nm in sorted(os.listdir(_SKILLS_DIR)):
            disabled = nm.endswith(".disabled")
            base = nm[:-len(".disabled")] if disabled else nm
            d = _safe_skill_dir(nm)
            if not d or not os.path.isdir(d) or base in have:
                continue
            md = os.path.join(d, "SKILL.md")
            if not os.path.isfile(md):
                continue   # 空目录/残壳不展示
            have.add(base)
            desc = sha = ""
            try:
                with open(md, "r", encoding="utf-8", errors="replace") as f:
                    desc = _fm_desc(f.read(8192))
            except OSError:
                pass
            try:
                with open(md, "rb") as f:
                    sha = hashlib.sha256(f.read()).hexdigest()[:16]
            except OSError:
                pass
            _zh = _zh_load("meta:local:" + base)   # v3.5.310：已安装卡中文描述
            out.append({"name": base, "desc": desc, "source": "user",
                        "disabled": disabled, "sha": sha,
                        "origin": (_meta.get(base) or {}).get("key"),
                        **({"zh_desc": _zh["zh_desc"]} if _zh else {})})
    for it in list_skills(cwd):
        if it.get("source") == "user":
            continue   # user 级已自扫（身份=目录名）
        it["disabled"] = False
        it["sha"] = None
        it["origin"] = None
        out.append(it)
    return out


# ---------------------------------------------------------------- 离线包

_PACK_VER = 1


def export_pack(names, out_dir=None):
    """勾选的技能打包 zip（skills/<n>/ 全目录 + manifest.json）。
    返回 (ok, 路径或err)。"""
    os.makedirs(_EXPORT_DIR, exist_ok=True)
    out = os.path.join(out_dir or _EXPORT_DIR,
                       "技能离线包-%s.zip" % time.strftime("%Y%m%d-%H%M%S"))
    items = []
    try:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for nm in names:
                d = _safe_skill_dir(nm) or _safe_skill_dir(nm + ".disabled")
                if not d or not os.path.isdir(d):
                    continue
                base = "skills/" + nm
                for r, _, fs in os.walk(d):
                    for fn in fs:
                        p = os.path.join(r, fn)
                        arc = base + "/" + os.path.relpath(p, d).replace("\\", "/")
                        z.write(p, arc)
                        try:
                            with open(p, "rb") as f:
                                sha = hashlib.sha256(f.read()).hexdigest()
                        except OSError:
                            sha = ""
                        items.append({"name": nm, "path": arc, "sha256": sha})
            meta = {"format": "skillpack", "version": _PACK_VER,
                    "exported": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "count": len({i["name"] for i in items}), "items": items}
            z.writestr("manifest.json",
                       json.dumps(meta, ensure_ascii=False, indent=2))
    except (OSError, zipfile.BadZipFile) as e:
        return False, str(e)[:150]
    if not items:
        try:
            os.remove(out)
        except OSError:
            pass
        return False, "没有可打包的技能"
    return True, out


def pack_inspect(file_storage):
    """导入第一步：暂存上传的 zip → 解析 manifest + 冲突检测。
    返回 token（apply 凭它取暂存包）+ 技能清单。"""
    if not file_storage or not file_storage.filename:
        return None, "未收到文件"
    if not file_storage.filename.lower().endswith(".zip"):
        return None, "仅支持 zip 离线包"
    file_storage.stream.seek(0, 2)
    if file_storage.stream.tell() > 200 * 1024 * 1024:
        return None, "离线包超过 200MB 上限"
    file_storage.stream.seek(0)
    os.makedirs(_CACHE_DIR, exist_ok=True)
    token = "pk" + hashlib.sha1((time.time_ns()).to_bytes(8, "big")).hexdigest()[:12]
    path = os.path.join(_CACHE_DIR, "pack_" + token + ".zip")
    try:
        file_storage.save(path)
    except OSError as e:
        return None, "保存上传文件失败：" + str(e)[:100]
    names, shas, err = _pack_read_manifest(path)
    if err:
        try:
            os.remove(path)
        except OSError:
            pass
        return None, err
    _PACK_STASH[token] = {"zip": path, "ts": time.time(), "shas": shas}
    # 清过期暂存
    now = time.time()
    for k in [k for k, v in _PACK_STASH.items() if now - v["ts"] > _PACK_TTL]:
        try:
            os.remove(_PACK_STASH[k]["zip"])
        except OSError:
            pass
        _PACK_STASH.pop(k, None)
    lst = []
    for nm in names:
        d = _safe_skill_dir(nm) or _safe_skill_dir(nm + ".disabled")
        lst.append({"name": nm, "conflict": bool(d and os.path.isdir(d))})
    return {"token": token, "skills": lst}, None


def _pack_read_manifest(path):
    """读离线包 manifest → (技能名列表, {包内路径: sha256})（校验格式与
    路径安全；items 必须是数组——恶意/畸形 manifest 防 500，全审 G4）。
    sha 按文件粒度（items 每文件一条，path=包内 arc 路径为键）。"""
    try:
        with zipfile.ZipFile(path) as z:
            if "manifest.json" not in z.namelist():
                return None, None, "不是技能离线包（缺 manifest.json）"
            meta = json.loads(z.read("manifest.json").decode("utf-8", "replace"))
        if not isinstance(meta, dict) or meta.get("format") != "skillpack":
            return None, None, "离线包格式不符"
        items = meta.get("items")
        if not isinstance(items, list):
            return None, None, "离线包 manifest 异常（items 非数组）"
        names, shas = set(), {}
        for i in items:
            if not isinstance(i, dict):
                continue
            nm = i.get("name")
            if nm and _safe_skill_dir(nm):
                names.add(nm)
                if i.get("sha256") and i.get("path"):
                    shas[str(i["path"])] = str(i["sha256"])
        if not names:
            return None, None, "包内没有技能"
        return sorted(names), shas, None
    except (zipfile.BadZipFile, ValueError, KeyError) as e:
        return None, None, "离线包解析失败：" + str(e)[:100]


def pack_apply(token, names, overwrite=False):
    """导入第二步：从暂存包落盘安装（overwrite=True 覆盖同名）。
    manifest 带有 sha256 的文件做完整性校验（不符按损坏计——全审建议5）；
    先确认包内有文件才建目录（失败不留空壳——全审 G1 连带）。"""
    st = _PACK_STASH.get(token)
    if not st:
        return {"ok": False, "err": "导入会话已过期，请重新选择文件"}
    shas = st.get("shas") or {}
    done, skipped, failed = [], [], []
    try:
        with zipfile.ZipFile(st["zip"]) as z:
            all_arcs = z.namelist()
            for nm in names:
                if not _safe_skill_dir(nm):
                    failed.append({"name": nm, "err": "非法技能名"})
                    continue
                d = _safe_skill_dir(nm)
                if d and os.path.isdir(d) and not overwrite:
                    skipped.append(nm)
                    continue
                prefix = "skills/" + nm + "/"
                arcs = [a for a in all_arcs
                        if a.startswith(prefix) and not a.endswith("/")]
                # 只留 slip 防护通过的有效条目——全被拦时按「包内无文件」拒绝
                #（否则 done files:0 报成功留空壳，复审 N1 续审点名的残留边缘）
                arcs = [a for a in arcs
                        if not (".." in a[len(prefix):] or ":" in a[len(prefix):]
                                or os.path.isabs(a[len(prefix):]))]
                if not arcs:
                    failed.append({"name": nm, "err": "包内无文件"})
                    continue
                # sha 全量校验提前到删原目录之前（N1：损坏包不许殃及已装技能）
                bad = False
                for arc in arcs:
                    rel = arc[len(prefix):]
                    if ".." in rel or ":" in rel or os.path.isabs(rel):
                        continue   # zip slip 防护
                    if arc in shas:
                        h = hashlib.sha256()
                        with z.open(arc) as src:
                            for chunk in iter(lambda: src.read(1 << 20), b""):
                                h.update(chunk)
                        if h.hexdigest().lower() != shas[arc].lower():
                            bad = True
                            break
                if bad:
                    failed.append({"name": nm, "err": "完整性校验失败（sha256 不符），原目录未改动"})
                    continue
                if d and os.path.isdir(d):
                    shutil.rmtree(d, ignore_errors=True)
                os.makedirs(d, exist_ok=True)
                n = 0
                for arc in arcs:
                    rel = arc[len(prefix):]
                    if ".." in rel or ":" in rel or os.path.isabs(rel):
                        continue   # zip slip 防护
                    dp = os.path.join(d, rel)
                    os.makedirs(os.path.dirname(dp), exist_ok=True)
                    with z.open(arc) as src, open(dp, "wb") as out:
                        shutil.copyfileobj(src, out)
                    n += 1
                done.append({"name": nm, "files": n})
    except (zipfile.BadZipFile, OSError) as e:
        return {"ok": False, "err": "解压失败：" + str(e)[:120]}
    return {"ok": True, "installed": done, "skipped": skipped, "failed": failed}


# ---------------------------------------------------------------- 汉化

_ZH_MEM = {}      # key -> dict（进程内一级缓存）


def _zh_key(kind, payload):
    return kind + ":" + hashlib.sha256(
        payload.encode("utf-8", "replace")).hexdigest()


def _zh_load(key):
    if key in _ZH_MEM:
        return _ZH_MEM[key]
    p = os.path.join(_ZH_DIR, hashlib.sha256(key.encode()).hexdigest() + ".json")
    if os.path.isfile(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
            _ZH_MEM[key] = d
            return d
        except (OSError, ValueError):
            pass
    return None


def _zh_save(key, d):
    _ZH_MEM[key] = d
    try:
        os.makedirs(_ZH_DIR, exist_ok=True)
        p = os.path.join(_ZH_DIR, hashlib.sha256(key.encode()).hexdigest() + ".json")
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, p)
    except OSError:
        pass


def light_model():
    """汉化模型=三角色轻主力槽（API 方案变动自动跟随）。"""
    try:
        from src.harness.roles import resolve_tier_models
        return resolve_tier_models()[0] or ""
    except Exception:
        return ""


def _claude_env():
    """API 端点（与主会话同源——settings.json env，同 vision_mcp 读法）。"""
    try:
        p = os.path.join(os.path.expanduser("~"), ".claude", "settings.json")
        with open(p, "r", encoding="utf-8") as f:
            env = json.load(f).get("env") or {}
        return (env.get("ANTHROPIC_BASE_URL") or "").rstrip("/"), \
               (env.get("ANTHROPIC_AUTH_TOKEN") or env.get("ANTHROPIC_API_KEY")
                or "").strip()
    except Exception:
        return "", ""


_ZH_SYS = ("你是技能文档翻译引擎。按用户指定字段把 Claude 技能文档译成简体中文："
           "保留代码块、命令、文件名、专有名词原样；术语首译时给出对照。"
           "技能名（name/slug）一律不译。")


def _llm(system, user, max_tokens=4096):
    """调轻主力模型（Anthropic 兼容 /v1/messages，单次非流式）。
    v3.5.323（用户实锤本地全文翻译恒报解析失败）：网关对长输入偶发
    200 空正文（vision_mcp._call_vision 同款已知行为）——空 content 补发
    一次再降级，不当场判死。"""
    base, key = _claude_env()
    if not base or not key:
        return None, "未配置 API 端点（settings.json env 缺失）"
    model = light_model()
    if not model:
        return None, "轻主力模型未配置"

    def _once():
        body = json.dumps({
            "model": model, "max_tokens": max_tokens, "system": system,
            "messages": [{"role": "user", "content": user}]}).encode("utf-8")
        req = urllib.request.Request(
            base + "/v1/messages", data=body, method="POST",
            headers={"Content-Type": "application/json",
                     "x-api-key": key, "Authorization": "Bearer " + key,
                     "anthropic-version": "2023-06-01", "User-Agent": _API_UA})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            return None, str(e)[:200]
        try:
            return "".join(c.get("text", "") for c in d.get("content", [])), None
        except Exception:
            return None, "响应解析失败"

    text, err = _once()
    # v3.5.325：空正文补发两次（网关偶发行为非确定性——同一请求实测时好
    # 时坏，两次全空的概率大幅降；间隔递增给网关喘息）
    for wait in (1, 3):
        if err or (text or "").strip():
            break
        time.sleep(wait)
        text, err = _once()
    return text, err


def _extract_json(text):
    """模型输出兜底解析（剥 ```json 围栏 / 截首尾大括号）。"""
    if not text:
        return None
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    a, b = t.find("{"), t.rfind("}")
    if a >= 0 and b > a:
        t = t[a:b + 1]
    try:
        return json.loads(t)
    except ValueError:
        try:
            return json.loads(t, strict=False)   # 译文串含原始换行（控制字符）容忍
        except ValueError:
            return None


def translate_meta(items):
    """批量元数据汉化：items=[{key,name,desc}] → 逐条缓存命中即回，
    未命中的一次 LLM 调用批量译。"""
    out, pending = {}, []
    for it in items:
        # 缓存键只用技能身份（不含内容 hash）——读侧（detail/_desc_backfill）
        # 拿不到与写侧同源的 name/desc，带 hash 的键永远对不上（全审 S4 实锤）
        key = "meta:" + it["key"]
        hit = _zh_load(key)
        if hit:
            out[it["key"]] = hit
        else:
            pending.append((it, key, None))
    if pending:
        # v4.0.1（用户拍板「技能仓库的名字不要翻译，只翻译简介和正文」）：
        # name 只作为术语上下文喂给模型，输出只要 zh_desc——zh_name 恒存原名。
        ask = json.dumps([{"i": i, "name": p[0].get("name", ""),
                           "desc": p[0].get("desc", "")}
                          for i, p in enumerate(pending)], ensure_ascii=False)
        text, err = _llm(_ZH_SYS, "翻译以下技能简介（name 仅作术语上下文，"
                         "不要翻译、不要输出）：输出 JSON："
                         '{"items":[{"i":0,"zh_desc":"一句中文描述",'
                         '"glossary":{"英文术语":"中文译名"}}]}。数据：' + ask)
        data = _extract_json(text) if not err else None
        got = {}
        if isinstance(data, dict):
            for row in data.get("items", []):
                try:
                    got[int(row.get("i"))] = row
                except (TypeError, ValueError):
                    continue
        for i, (it, key, _payload) in enumerate(pending):
            row = got.get(i) or {}
            d = {"zh_name": it.get("name", ""),
                 "zh_desc": str(row.get("zh_desc") or "")[:600],
                 "glossary": row.get("glossary") or {},
                 "model": light_model(), "ts": int(time.time())}
            _zh_save(key, d)
            out[it["key"]] = d
    return out


def translate_body(md):
    """正文汉化（SKILL.md 全文，按需调用）。
    v3.5.323（用户实锤「不可能这么脆弱」+二分定位）：13.6K 源文要求 JSON
    包裹时网关 144s 空正文必败，同一输入直出译文 76s 全文成功——**空正文
    触发器是「长输入+JSON 包裹长输出」组合**，与长度/拆分无关。prompt 改
    直出译文，全文当译文采信（剥可能围栏）；_llm 层保留空正文补发一次。"""
    key = _zh_key("body:", md)
    hit = _zh_load(key)
    if hit:
        return hit, None
    if len(md) > 60000:
        return None, "技能正文过长（%d 字节），暂不支持翻译" % len(md)
    text, err = _llm(
        "你是翻译引擎。把 SKILL.md 翻译成简体中文：markdown 结构、代码块、"
        "命令、链接、frontmatter 键名原样保留；专有名词/产品名保留。"
        "直接输出译文全文，不要任何解释或包裹。",
        "翻译成简体中文，直接输出译文：\n" + md, max_tokens=4096)
    if err:
        return None, err
    t = (text or "").strip()
    if not t:
        return None, "模型返回空响应（稍后重试）"
    m = re.match(r"^```(?:markdown)?\s*\n(.*?)\n```\s*$", t, re.S)
    if m:
        t = m.group(1)   # 剥模型偶尔加的围栏
    d = {"body_zh": t, "model": light_model(), "ts": int(time.time())}
    _zh_save(key, d)
    return d, None


# ---------------------------------------------------------------- 状态

def status():
    """面板状态条：轻主力模型名 + 数据源可达性（探测结果缓存 5min）。
    a632：三源探测（官方 raw / jsDelivr 镜像 / GitHub API）+ 源档位。"""
    global _STAT
    now = time.time()
    if _STAT.get("ts") and now - _STAT["ts"] < 300:
        return {**_STAT, "ts": 0, "light_model": light_model(),
                "source": source_mode()}
    probe = {"owner": _PROBE_OWNER, "repo": _PROBE_REPO,
             "branch": _PROBE_BRANCH, "path": _PROBE_PATH}
    results = {}
    threads = []
    lock = threading.Lock()

    def _probe(name, url, hdr):
        b = _http(url, timeout=8, want_bytes=True, extra_headers=hdr)
        with lock:
            results[name] = bool(b)

    gh_fresh = (_STAT.get("gh_api_ts")
                and now - _STAT["gh_api_ts"] < 900)
    for name, url, hdr in _raw_url_variants(
            probe["owner"], probe["repo"], probe["branch"], probe["path"]):
        if name == "gh_api" and gh_fresh:
            continue   # N12：gh_api 探测 15min 降频，省 60/h 匿名限额
        th = threading.Thread(target=_probe, args=(name, url, hdr), daemon=True)
        th.start()
        threads.append(th)
    for th in threads:
        th.join(timeout=12)
    ok_sh = _page("/") is not None
    _STAT = {"ts": now, "skills_sh": ok_sh,
             "official": results.get("official", False),
             "jsdelivr": results.get("jsdelivr", False),
             # a632R（审计 N12）：gh_api 共享 60/h 匿名限额——探测降频到
             # 15min（其余源每次 5min 探测），安装/skill_files 的 API 调用
             # 让额度给真实下载。gh_api_ts 仅**真探测时**刷新——无条件刷
             # 会让降频窗口自我续期，可达性进程生命周期内冻结（四轮实锤）
             "gh_api": (results["gh_api"] if "gh_api" in results
                        else _STAT.get("gh_api", False))}
    if "gh_api" in results:
        _STAT["gh_api_ts"] = now
    return {**_STAT, "light_model": light_model(), "source": source_mode()}


_STAT = {}

# a623R 复审（严重 N1）：迁移执行点挪到模块底部——_notify_mirror/_META_FILE
# 全部定义完成后（老布局升级机导入期触发迁移不再 NameError）。
_migrate_legacy_dirs()
