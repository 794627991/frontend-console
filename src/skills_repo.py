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

from src.app_state import HOME_DIR

UA = "frontend-console-skills/1.0"
_SKILLS_DIR = os.path.join(os.path.expanduser("~"), ".claude", "skills")
_CACHE_DIR = os.path.join(HOME_DIR, "skill_cache")       # SKILL.md 原文缓存
_ZH_DIR = os.path.join(HOME_DIR, "skill_zh")             # 汉化缓存
_EXPORT_DIR = os.path.join(HOME_DIR, "skill_exports")    # 离线包导出目录
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

def _http(url, timeout=20, want_bytes=False):
    """GET → str/bytes；任何失败返回 None（调用方按不可达处理）。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            b = r.read()
        return b if want_bytes else b.decode("utf-8", "replace")
    except Exception:
        return None


def _page(path):
    """skills.sh 网页（内存 TTL 缓存——榜单页 900KB，10 分钟内复用）。"""
    key = path
    now = time.time()
    hit = _LB_CACHE.get(key)
    if hit and now - hit[0] < _PAGE_TTL:
        return hit[1]
    html = _http("https://www.skills.sh" + path, timeout=25)
    if html:
        _LB_CACHE[key] = (now, html)
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


def registry(tab="top", q=""):
    """榜单卡片（tab: top=All Time / trending=24h / hot）；q 非空时在榜单
    内存过滤（skills.sh 无匿名搜索 API）。附带缓存的英文 description 与
    本地启发式分类（skills.sh topic 页是 JS 空壳，零网络分桶）。"""
    path = {"trending": "/trending", "hot": "/hot"}.get(tab, "/")
    html = _page(path)
    if not html:
        return None
    rows = parse_leaderboard(html)
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
    return rows


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
        if key in _DESC_CACHE:
            continue
        owner, repo, skill = key.split("/")
        md = _raw_skill_md(owner, repo, skill, cache=False)
        desc = ""
        if md:
            m = re.search(r'^description:\s*(.+)$', md[:2048], re.M)
            desc = m.group(1).strip()[:300] if m else ""
        with _DESC_LOCK:
            _DESC_CACHE[key] = {"desc": desc, "ts": time.time()}
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
           "md": None}
    if html:
        m = _RE_H1.search(html)
        if m:
            out["name"] = m.group(1).strip()
        m = _RE_INST_BIG.search(html)
        if m:
            out["installs"] = m.group(1).strip()
    md = _raw_skill_md(owner, repo, skill)
    if md:
        out["md"] = md
        m = re.search(r'^description:\s*(.+)$', md[:2048], re.M)
        if m:
            out["desc"] = m.group(1).strip()[:600]
        zh = _zh_load("meta:" + out["key"])
        if zh:
            out["zh_name"] = zh.get("zh_name")
            out["zh_desc"] = zh.get("zh_desc")
            out["glossary"] = zh.get("glossary")
        zb = _zh_load(_zh_key("body:", md))
        if zb:
            out["body_zh"] = zb.get("body_zh")
    # 文件清单（GitHub contents API 限额敏感——None=列不了，前端如实标注）
    fl = skill_files(owner, repo, skill)
    if fl is not None:
        out["files"] = [{"name": n, "type": t} for n, u, t in fl]
    return out


_RAW_PATHS = ("skills/%(s)s", "%(s)s", ".claude/skills/%(s)s")
_RAW_BRANCHES = ("main", "master")


def _raw_skill_md(owner, repo, skill, cache=True):
    """raw 直拉 SKILL.md（无限额）。路径候选序列逐个试；成功后落盘缓存。"""
    cpath = os.path.join(_CACHE_DIR, "%s_%s_%s.md" % (owner, repo, skill))
    if cache and os.path.isfile(cpath):
        try:
            with open(cpath, "r", encoding="utf-8") as f:
                return f.read()
        except OSError:
            pass
    for tpl in _RAW_PATHS:
        for br in _RAW_BRANCHES:
            u = ("https://raw.githubusercontent.com/%s/%s/%s/"
                 % (owner, repo, br)) + (tpl % {"s": skill}) + "/SKILL.md"
            b = _http(u, timeout=15, want_bytes=True)
            if b and len(b) > 32:
                try:
                    os.makedirs(_CACHE_DIR, exist_ok=True)
                    with open(cpath, "wb") as f:
                        f.write(b)
                except OSError:
                    pass
                return b.decode("utf-8", "replace")
    return None


def skill_files(owner, repo, skill):
    """技能目录内全部文件（GitHub contents API，限额敏感——失败返回 None，
    调用方按「仅 SKILL.md」降级，不阻塞安装）。"""
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
            return [(it.get("name"), it.get("download_url"), it.get("type"))
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


def install(owner, repo, skill, scope="user"):
    """安装技能 → ~/.claude/skills/<skill>/。返回 dict：
    ok / conflict(已存在) / partial(辅助文件缺失) / err。
    成功后记来源与 sha（skill_meta.json——更新检测/卸载对账用）。"""
    if scope != "user":
        return {"ok": False, "err": "仅支持 user 级安装"}
    dst = _safe_skill_dir(skill)
    if not dst:
        return {"ok": False, "err": "非法技能名"}
    md = _raw_skill_md(owner, repo, skill)   # 缓存命中则不再出网
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
                      "ts": int(time.time())})
    partial = False
    files = skill_files(owner, repo, skill)
    if files:
        for name, url, typ in files:
            if typ != "file" or name == "SKILL.md" or not url:
                continue
            b = _http(url, timeout=20, want_bytes=True)
            if not b:
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
            "dir": dst}


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


_META_FILE = os.path.join(HOME_DIR, "skill_meta.json")
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
            os.makedirs(HOME_DIR, exist_ok=True)
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


def check_updates():
    """更新检测：对「本工具装的」user 级技能（meta 有 origin）raw 拉最新
    SKILL.md（绕缓存）比对 sha。并发 4（串行在离线时 N×6 URL×15s 可挂数
    分钟——全审建议4）。返回 [{skill, has_update, err}]。"""
    def _one(item):
        nm, info = item
        parts = str(info.get("key") or "").split("/")
        if len(parts) != 3 or not info.get("sha"):
            return None
        md = _raw_skill_md(parts[0], parts[1], parts[2], cache=False)
        if not md:
            return {"skill": nm, "has_update": False, "err": "拉取失败"}
        cur = hashlib.sha256(md.encode("utf-8", "replace")).hexdigest()[:16]
        return {"skill": nm, "has_update": cur != info["sha"],
                "new_sha": cur, "err": ""}
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
                    m = re.search(r'^description:\s*(.+)$', f.read(8192), re.M)
                desc = m.group(1).strip() if m else ""
            except OSError:
                pass
            try:
                with open(md, "rb") as f:
                    sha = hashlib.sha256(f.read()).hexdigest()[:16]
            except OSError:
                pass
            out.append({"name": base, "desc": desc, "source": "user",
                        "disabled": disabled, "sha": sha,
                        "origin": (_meta.get(base) or {}).get("key")})
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


_ZH_SYS = ("你是技能文档翻译引擎。把给定的 Claude 技能元数据/正文译成简体中文："
           "保留代码块、命令、文件名、专有名词原样；术语首译时给出对照。"
           "只输出 JSON，不要解释。")


def _llm(system, user, max_tokens=4096):
    """调轻主力模型（Anthropic 兼容 /v1/messages，单次非流式）。"""
    base, key = _claude_env()
    if not base or not key:
        return None, "未配置 API 端点（settings.json env 缺失）"
    model = light_model()
    if not model:
        return None, "轻主力模型未配置"
    body = json.dumps({
        "model": model, "max_tokens": max_tokens, "system": system,
        "messages": [{"role": "user", "content": user}]}).encode("utf-8")
    req = urllib.request.Request(
        base + "/v1/messages", data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "x-api-key": key, "Authorization": "Bearer " + key,
                 "anthropic-version": "2023-06-01", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        return None, str(e)[:200]
    try:
        return "".join(c.get("text", "") for c in d.get("content", [])), None
    except Exception:
        return None, "响应解析失败"


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
        ask = json.dumps([{"i": i, "name": p[0].get("name", ""),
                           "desc": p[0].get("desc", "")}
                          for i, p in enumerate(pending)], ensure_ascii=False)
        text, err = _llm(_ZH_SYS, "翻译以下技能元数据数组，输出 JSON："
                         '{"items":[{"i":0,"zh_name":"中文名","zh_desc":"一句中文描述",'
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
            d = {"zh_name": str(row.get("zh_name") or it.get("name", ""))[:120],
                 "zh_desc": str(row.get("zh_desc") or "")[:600],
                 "glossary": row.get("glossary") or {},
                 "model": light_model(), "ts": int(time.time())}
            _zh_save(key, d)
            out[it["key"]] = d
    return out


def translate_body(md):
    """正文汉化（SKILL.md 全文，按需调用）。"""
    key = _zh_key("body:", md)
    hit = _zh_load(key)
    if hit:
        return hit, None
    if len(md) > 60000:
        return None, "技能正文过长（%d 字节），暂不支持翻译" % len(md)
    text, err = _llm(_ZH_SYS, "翻译以下 SKILL.md 全文为简体中文，"
                     "保留 markdown 结构/代码块/命令/frontmatter 键名原样，"
                     "输出 JSON：{\"body_zh\":\"译文\"}。正文：\n" + md)
    data = _extract_json(text) if not err else None
    if not data or not data.get("body_zh"):
        return None, err or "翻译结果解析失败"
    d = {"body_zh": data["body_zh"], "model": light_model(),
         "ts": int(time.time())}
    _zh_save(key, d)
    return d, None


# ---------------------------------------------------------------- 状态

def status():
    """面板状态条：轻主力模型名 + 数据源可达性（探测结果缓存 5min）。"""
    global _STAT
    now = time.time()
    if _STAT.get("ts") and now - _STAT["ts"] < 300:
        return {**_STAT, "ts": 0, "light_model": light_model()}
    ok_sh = _page("/") is not None
    ok_gh = _http("https://raw.githubusercontent.com/anthropics/skills/main/"
                  "README.md", timeout=8, want_bytes=True) is not None
    _STAT = {"ts": now, "skills_sh": ok_sh, "github": ok_gh}
    return {**_STAT, "light_model": light_model()}


_STAT = {}
