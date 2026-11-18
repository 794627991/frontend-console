# -*- coding: utf-8 -*-
"""技能中心多源下载与交叉验证单测（a632）。

覆盖：源候选序（档位/探测沉底）、_fetch_multi 换源重试与空响应剔除、
交叉验证三态（一致/单源/不一致）、官方精选兜底榜单、integrity_conflict
拒装与 confirm 放行。全部 monkeypatch _http，不出网。
"""
import hashlib
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import skills_repo as sr  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """隔离：探测缓存清零（视为全可达）、DATA_DIR/HOME 指临时目录。"""
    monkeypatch.setattr(sr, "_STAT", {})
    monkeypatch.setattr(sr, "_LB_CACHE", {})
    monkeypatch.setattr(sr, "_DESC_CACHE", {})
    monkeypatch.setattr(sr, "_CACHE_DIR", str(tmp_path / "skill_cache"))
    monkeypatch.setattr(sr, "_SKILLS_DIR", str(tmp_path / "skills"))
    monkeypatch.setattr(sr, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(sr, "_META_FILE",
                        str(tmp_path / "data" / "skill_meta.json"))
    # a636：安装锁是模块级表，跨测试残留会让同名技能串行/互等
    monkeypatch.setattr(sr, "_INSTALL_LOCKS", {})
    # a623R 复审（N2 根修）：mock config 存储本身（读/写同一可变 dict）——
    # 上一轮钉 sr.source_mode=auto 的写法把 roundtrip 测试的读路径也钉死
    # 了（set 写入后读恒 auto，测试假绿都测不出来）；也不再有写穿真实
    # config.json 的风险
    cfg_store = {}
    import src.app_state as _st
    monkeypatch.setattr(_st, "_load_config", lambda: dict(cfg_store))
    monkeypatch.setattr(_st, "cfg_commit", lambda mutator: mutator(cfg_store))
    yield


# ---- 源候选序 ------------------------------------------------------------

def test_variants_default_order_official_first():
    """auto + 全可达（探测空窗）：官方在前、镜像次之、API 备援末位。"""
    v = sr._raw_url_variants("o", "r", "main", "SKILL.md")
    assert [n for n, _u, _h in v] == ["official", "jsdelivr", "gh_api"]
    assert v[0][1] == "https://raw.githubusercontent.com/o/r/main/SKILL.md"


def test_variants_probe_unreachable_sinks_but_keeps():
    """auto + 探测判官方不可达：官方沉底但**不剔除**（探测可能过时，留兜底）。"""
    sr._STAT.update({"official": False, "jsdelivr": True, "gh_api": True})
    v = sr._raw_url_variants("o", "r", "main", "SKILL.md")
    names = [n for n, _u, _h in v]
    assert names == ["jsdelivr", "gh_api", "official"]
    assert "official" in names   # 恒在候选列内


def test_variants_mode_official(monkeypatch):
    """official 档：官方恒首（探测全可达时也压过 auto 顺序）。"""
    monkeypatch.setattr(sr, "source_mode", lambda: "official")
    sr._STAT.update({"official": True, "jsdelivr": True, "gh_api": True})
    v = sr._raw_url_variants("o", "r", "main", "p")
    assert [n for n, _u, _h in v][0] == "official"


def test_variants_jsdelivr_url_form(monkeypatch):
    """jsDelivr 变体 URL 形态（@branch 连接）。"""
    monkeypatch.setattr(sr, "source_mode", lambda: "official")
    v = sr._raw_url_variants("o", "r", "main", "p")
    u = {n: url for n, url, _h in v}
    assert u["jsdelivr"] == "https://testingcf.jsdelivr.net/gh/o/r@main/p"
    assert u["gh_api"] == "https://api.github.com/repos/o/r/contents/p"
    assert u["official"] == "https://raw.githubusercontent.com/o/r/main/p"


def test_variants_branch_with_slash_declared_gap():
    """a632R（审计 N1）：branch 含 / 的 raw URL 存在**结构性歧义**——
    feature/x 分支与 owner/repo/feature + path=x/... 从 URL 无法区分，
    镜像变体会切错址（通常 404 退化单源 official 兜底）。钉现状：官方
    变体重组恰好还原原 URL。若未来 GitHub API 提供分支信息可精确重组。"""
    raw = ("https://raw.githubusercontent.com/o/r/feature/x/scripts/a.py")
    v = sr._variants_from_raw_url(raw)
    assert v[0][0] == "official" and v[0][1] == raw


def test_variants_mode_jsdelivr(monkeypatch):
    monkeypatch.setattr(sr, "source_mode", lambda: "jsdelivr")
    v = sr._raw_url_variants("o", "r", "main", "p")
    assert [n for n, _u, _h in v][0] == "jsdelivr"
    # 官方恒在候选列内兜底
    assert "official" in [n for n, _u, _h in v]


def test_source_mode_config_roundtrip():
    """档位写读闭环（走 fixture 的 mock config 存储——写与读同一可变 dict）。"""
    assert sr.source_mode() == "auto"
    ok, err = sr.set_source_mode("jsdelivr")
    assert ok is True and err == ""
    assert sr.source_mode() == "jsdelivr"   # 写入即时可读（cfg_commit 原子）
    # 非法值回退 auto（读侧防御）+ 写侧拒绝（a636：改为返回 (False, err)，
    # 不再抛 ValueError——调用方要能把失败如实转给前端）
    import src.app_state as _st
    _st._load_config = lambda: {"skill_source": "bogus"}
    assert sr.source_mode() == "auto"
    ok2, err2 = sr.set_source_mode("bogus")
    assert ok2 is False and "未知技能源档位" in err2


def test_source_mode_reports_write_failure(monkeypatch):
    """P1-12 回归：cfg_commit 失败时不能谎报成功（原来无条件 ok）。"""
    import src.app_state as _st
    monkeypatch.setattr(_st, "cfg_commit",
                        lambda mutator: (False, "Permission denied"))
    ok, err = sr.set_source_mode("jsdelivr")
    assert ok is False and "Permission denied" in err


# ---- _fetch_multi --------------------------------------------------------

def test_fetch_multi_falls_through_on_failure(monkeypatch):
    """首选源失败自动换下一源。"""
    calls = []

    def fake_http(url, **kw):
        calls.append(url)
        if "raw.githubusercontent" in url:
            return None
        return b"data"

    monkeypatch.setattr(sr, "_http", fake_http)
    b, src = sr._fetch_multi(
        sr._raw_url_variants("o", "r", "main", "SKILL.md"))
    assert b == b"data" and src == "jsdelivr"
    assert len(calls) == 2


def test_fetch_multi_rejects_empty_response(monkeypatch):
    """空响应按失败处理（空 sha 假一致是交叉验证的大坑）。"""
    monkeypatch.setattr(sr, "_http", lambda url, **kw: b"")   # 全空
    b, src = sr._fetch_multi(sr._raw_url_variants("o", "r", "main", "SKILL.md"))
    assert b is None and src is None


def test_variants_from_raw_url(monkeypatch):
    monkeypatch.setattr(sr, "source_mode", lambda: "official")
    v = sr._variants_from_raw_url(
        "https://raw.githubusercontent.com/o/r/main/scripts/a.py")
    assert [n for n, _u, _h in v] == ["official", "jsdelivr", "gh_api"]
    assert v[1][1] == "https://testingcf.jsdelivr.net/gh/o/r@main/scripts/a.py"
    assert v[2][2] == {"Accept": "application/vnd.github.raw"}
    # 非 raw 形态原样单发
    v2 = sr._variants_from_raw_url("https://example.com/x")
    assert len(v2) == 1 and v2[0][0] == "official"


# ---- 交叉验证 ------------------------------------------------------------

# a636：内容形态闸要求 SKILL.md 像 markdown 技能文件（frontmatter/标题开头），
# 纯 "SKILL CONTENT" 这种假数据会被正确拒掉——测试数据要贴近真实形态。
MD_GOOD = (b"---\nname: s\ndescription: demo\n---\n\n# Skill\n"
           + b"x" * 40)
MD_EVIL = (b"---\nname: s\ndescription: evil\n---\n\n# Evil\n"
           + b"y" * 40)


def _md(text):
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def test_verified_consistent(monkeypatch):
    """两源内容一致 → 正常装。"""
    def fake_http(url, **kw):
        if "testingcf" in url:
            return MD_GOOD
        if "raw.githubusercontent" in url:
            return MD_GOOD
        return None

    monkeypatch.setattr(sr, "_http", fake_http)
    content, hashes, consistent = sr._fetch_skill_md_verified("o", "r", "s")
    assert content == MD_GOOD.decode()
    assert consistent is True
    assert len(set(hashes.values())) == 1


def test_verified_conflict(monkeypatch):
    """两源不一致 → consistent=False（默认拒装依据）。"""
    def fake_http(url, **kw):
        if "testingcf" in url:
            return MD_EVIL
        if "raw.githubusercontent" in url:
            return MD_GOOD
        return None

    monkeypatch.setattr(sr, "_http", fake_http)
    content, hashes, consistent = sr._fetch_skill_md_verified("o", "r", "s")
    assert consistent is False
    assert set(hashes) == {"official", "jsdelivr"}
    assert hashes["official"] != hashes["jsdelivr"]
    # content = 官方源版本（confirm 强制装时装这份，不由实现替用户选边）
    assert content == MD_GOOD.decode()


def test_verified_single_source(monkeypatch):
    """仅一源可达 → 单源放行（consistent=None）。"""
    def fake_http(url, **kw):
        return MD_GOOD if "raw.githubusercontent" in url else None

    monkeypatch.setattr(sr, "_http", fake_http)
    content, hashes, consistent = sr._fetch_skill_md_verified("o", "r", "s")
    assert content == MD_GOOD.decode() and consistent is None
    assert list(hashes) == ["official"]


def test_verified_all_fail(monkeypatch):
    monkeypatch.setattr(sr, "_http", lambda url, **kw: None)
    content, hashes, consistent = sr._fetch_skill_md_verified("o", "r", "s")
    assert content is None and hashes == {} and consistent is None


# ---- install 的 integrity 拒装/放行 --------------------------------------

def test_install_rejects_on_conflict(monkeypatch, tmp_path):
    """源间不一致 → 默认拒装 + integrity_conflict，不落盘。"""
    monkeypatch.setattr(sr, "_fetch_skill_md_verified",
                        lambda *a: (None, {"official": "aaa", "jsdelivr": "bbb"},
                                   False))
    r = sr.install("o", "r", "s")
    assert r["ok"] is False and r["integrity_conflict"] is True
    assert not os.path.isdir(os.path.join(str(tmp_path), "skills", "s"))


def test_install_confirm_overrides(monkeypatch, tmp_path):
    """confirm_integrity=True 强制装，meta 记 user-override。"""
    content = "SKILL " + "x" * 40
    monkeypatch.setattr(sr, "_fetch_skill_md_verified",
                        lambda *a: (content, {"official": "aaa", "jsdelivr": "bbb"},
                                   False))
    monkeypatch.setattr(sr, "skill_files", lambda *a: None)
    r = sr.install("o", "r", "s", confirm_integrity=True)
    assert r["ok"] is True and r["integrity"] == "user-override"
    meta = json.load(open(os.path.join(str(tmp_path), "data", "skill_meta.json"),
                          encoding="utf-8"))
    assert meta["s"]["integrity"] == "user-override"


def test_install_single_source_ok(monkeypatch, tmp_path):
    monkeypatch.setattr(sr, "_fetch_skill_md_verified",
                        lambda *a: ("SKILL-CONTENT-" + "x" * 40, {"official": "aaa"},
                                    None))
    monkeypatch.setattr(sr, "skill_files", lambda *a: None)
    r = sr.install("o", "r", "s")
    assert r["ok"] is True and r["integrity"] == "single-source"


# ---- 官方精选兜底 ---------------------------------------------------------

def test_registry_official_via_api(monkeypatch):
    """skills.sh 挂 + contents API 通 → 官方真实列表。"""
    monkeypatch.setattr(sr, "_page", lambda path: None)
    api_items = [{"name": "pdf", "type": "dir"},
                 {"name": "README.md", "type": "file"},
                 {"name": "docx", "type": "dir"}]
    monkeypatch.setattr(sr, "_http",
                        lambda url, **kw: json.dumps(api_items)
                        if "api.github.com" in url else None)
    rows, source = sr.registry()
    assert source == "official_fallback"
    assert {r["skill"] for r in rows} == {"pdf", "docx"}
    assert all(r["official"] for r in rows)


def test_registry_official_static_fallback(monkeypatch):
    """API 也挂 → 硬编码官方子集（如实标注 static）。"""
    monkeypatch.setattr(sr, "_page", lambda path: None)
    monkeypatch.setattr(sr, "_http", lambda url, **kw: None)
    rows, source = sr.registry()
    assert source == "official_fallback_static"
    assert "pdf" in {r["skill"] for r in rows}


def test_registry_skills_sh_normal(monkeypatch):
    """skills.sh 可达 → 照旧走榜单。"""
    monkeypatch.setattr(sr, "_page", lambda path: "<html>ok</html>")
    monkeypatch.setattr(sr, "parse_leaderboard",
                        lambda html: [{"key": "a/b/c", "owner": "a", "repo": "b",
                                       "skill": "c", "name": "c", "source": "a/b",
                                       "installs": "", "weekly": []}])
    rows, source = sr.registry()
    assert source == "skills.sh" and rows[0]["key"] == "a/b/c"


# ---- a623R 审计缺口补钉 ---------------------------------------------------

def test_fetch_multi_passes_extra_headers(monkeypatch):
    """gh_api 变体的 raw Accept 头必须真传给 _http（fake **kw 吞参曾漏测）。"""
    seen = {}

    def fake_http(url, **kw):
        seen.update(kw)
        return b"data"

    monkeypatch.setattr(sr, "_http", fake_http)
    v = [x for x in sr._raw_url_variants("o", "r", "main", "p")
         if x[0] == "gh_api"]
    b, _ = sr._fetch_multi(v)
    assert b == b"data"
    assert seen.get("extra_headers") == {"Accept": "application/vnd.github.raw"}


def test_verified_next_combo_on_total_failure(monkeypatch):
    """首（路径,分支）组合全源失败 → 退化试下一组合（skills/<s> miss →
    <s> 命中）。"""
    def fake_http(url, **kw):
        # 第一组合 skills/s/SKILL.md 全部 404（None），第二组合 <s>/SKILL.md
        # 命中
        if "/skills/s/SKILL.md" in url or "/skills/s@main/" in url:
            return None
        if "/contents/s/SKILL.md" in url:
            return None
        return MD_GOOD

    monkeypatch.setattr(sr, "_http", fake_http)
    content, hashes, consistent = sr._fetch_skill_md_verified("o", "r", "s")
    assert content == MD_GOOD.decode()
    assert consistent is True   # 第二组合两源命中且一致（gh_api 对该路径 404）
    assert set(hashes) == {"official", "jsdelivr"}


# ---- a632R 四轮审计回归（S1/S2/S3 修复本体此前零测试钉住）----------------

def test_variants_branch_with_slash_official_roundtrip():
    """a632R 四轮（N1 死守卫清除后钉现状）：branch 含 / 的 URL 仍出 3 变体
    （结构性歧义无法判别），但官方变体重组恰好还原原 URL、恒首位。"""
    raw = ("https://raw.githubusercontent.com/o/r/feature/x/scripts/a.py")
    v = sr._variants_from_raw_url(raw)
    assert len(v) == 3
    assert v[0][0] == "official" and v[0][1] == raw


def test_install_helper_file_blob_sha_rejects_tampered(monkeypatch, tmp_path):
    """S1：辅助文件 blob sha 校验四形态——匹配落盘 / 不匹配**不落盘**记
    partial / 缺 sha 放行 / 走镜像下载同样被校验（校验与来源解耦）。"""
    content = b"print('helper')" * 4
    good_sha = hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest()
    evil = b"evil payload" * 4
    evil_sha = hashlib.sha1(b"blob %d\0" % len(evil) + evil).hexdigest()
    calls = {"n": 0}

    def fake_fetch_multi(variants, timeout=20, want_bytes=True,
                         max_bytes=None):
        url = variants[0][1]
        if "nohash.py" in url:
            return (b"no-hash-content", variants[0][0])
        calls["n"] += 1
        # 第一次安装返回毒化内容（sha 不匹配 → 拒落盘）；第二次返回好内容
        return ((evil, variants[0][0]) if calls["n"] == 1
                else (content, variants[0][0]))

    monkeypatch.setattr(sr, "_fetch_multi", fake_fetch_multi)
    monkeypatch.setattr(sr, "_fetch_skill_md_verified",
                        lambda *a: ("SKILL-MAIN-" + "x" * 40,
                                    {"official": "aaa"}, None))
    monkeypatch.setattr(sr, "skill_files",
                        lambda *a: [("helper.py", "https://raw.githubuser"
                                     "content.com/o/r/main/helper.py",
                                     "file", good_sha),
                                    ("nohash.py", "https://raw.githubuser"
                                     "content.com/o/r/main/nohash.py",
                                     "file", None)])
    monkeypatch.setattr(sr, "_log", _FakeLog())

    # ① 毒化内容：sha 不匹配 → 不落盘 + partial
    r = sr.install("o", "r", "s")
    assert r["ok"] and r["partial"] is True
    assert not os.path.exists(os.path.join(str(tmp_path), "skills", "s",
                                           "helper.py"))
    assert os.path.exists(os.path.join(str(tmp_path), "skills", "s",
                                       "nohash.py"))   # 缺 sha 放行
    assert any("sha 校验失败" in m for m in _FakeLog.msgs), "拒落盘必须留痕"

    # ② 好内容：sha 匹配 → 落盘
    _FakeLog.msgs.clear()
    r2 = sr.install("o", "r2", "s")
    assert r2["ok"] and r2["partial"] is False
    p = os.path.join(str(tmp_path), "skills", "s", "helper.py")
    assert open(p, "rb").read() == content


class _FakeLog:
    msgs = []
    def warning(self, fmt, *a):
        _FakeLog.msgs.append(fmt % a if a else fmt)
    def info(self, fmt, *a):
        pass


def test_verified_pick_deterministic_authoritative(monkeypatch):
    """S2/S3：content pick 按**权威序**（official→gh_api→jsdelivr）——镜像
    旧缓存不得抢在权威 API 前当基准。并发完成序不重要。"""
    import threading as _th
    delays = {"jsdelivr": 0.0, "gh_api": 0.3, "official": 0.3}
    def fake_http(url, **kw):
        b = None
        if "testingcf" in url:
            b = b"---\nname: s\n---\n\n# stale\n" + b"-" * 20
        elif "api.github.com" in url:
            b = b"---\nname: s\n---\n\n# fresh\n" + b"-" * 20
        elif "raw.githubusercontent" in url:
            return None   # official 被墙（目标环境常态）
        if b is not None:
            _th.Event().wait(delays.get(
                "jsdelivr" if "testingcf" in url else "gh_api", 0))
        return b

    monkeypatch.setattr(sr, "_http", fake_http)
    for _ in range(3):   # 重复多次：竞速顺序不得影响 pick
        content, hashes, consistent = sr._fetch_skill_md_verified("o", "r", "s")
        assert "# fresh" in content, \
            "权威序：gh_api（新鲜）必须压过 jsdelivr（12h 旧缓存）"
        assert consistent is False and set(hashes) == {"jsdelivr", "gh_api"}


def test_check_updates_conflict_warns_but_judges(monkeypatch):
    """S3 终版语义：不一致降级为 err 警告，has_update 仍按权威 pick 判定
    （降级链已断：confirm 重装装的是权威版，不会再装回镜像旧缓存）。"""
    monkeypatch.setattr(sr, "_fetch_skill_md_verified",
                        lambda *a: ("AUTH-PICK-" + "z" * 30,
                                    {"gh_api": "111", "jsdelivr": "222"},
                                    False))
    monkeypatch.setattr(sr, "_meta_load",
                        lambda: {"s": {"key": "o/r/s", "sha": "aaa"}})
    out = sr.check_updates()
    assert out[0]["has_update"] is True   # 权威版与已装不同 = 真实差异
    assert "不一致" in out[0]["err"]      # 不一致警告如实透出


def test_check_updates_fresh_version_detected(monkeypatch):
    """S3 主链路：权威 pick 拉到新版 → has_update=True（official 被墙、
    jsdelivr 旧缓存 X、gh_api 新版 Y 的目标环境形态）。"""
    X = ("---\nname: s\n---\n\n# X\n" + "a" * 24)
    Y = ("---\nname: s\n---\n\n# Y\n" + "b" * 24)
    def fake_http(url, **kw):
        if "testingcf" in url:
            return X.encode()
        if "api.github.com" in url:
            return Y.encode()
        return None   # official 被墙
    monkeypatch.setattr(sr, "_http", fake_http)
    monkeypatch.setattr(sr, "_meta_load",
                        lambda: {"s": {"key": "o/r/s",
                                       "sha": hashlib.sha256(X.encode()).hexdigest()[:16]}})
    out = sr.check_updates()
    assert out[0]["has_update"] is True   # 权威 pick（gh_api Y）≠ 已装 X
    assert out[0]["new_sha"] == hashlib.sha256(Y.encode()).hexdigest()[:16]
    # official 被墙 → results={jsdelivr:X, gh_api:Y} 不一致 → err 带警告
    assert "不一致" in out[0]["err"]



# ---- a636（对抗审计 P3-21）：补齐三组零覆盖契约 ---------------------------

def test_registry_fallback_key_is_three_segments(monkeypatch):
    """P0-1 回归：兜底卡的 key 必须是 owner/repo/skill **三段**。

    前端 skInstall / skOpenDetail 都按 `parts.length !== 3` 校验——4 段 key
    会让「安装」和「详情」全部静默无反应。原测试只断言 skill 名字集合，
    key 契约零覆盖，所以 4 段的缺陷一路绿到线上。
    """
    monkeypatch.setattr(sr, "_page", lambda path: None)
    monkeypatch.setattr(sr, "_http", lambda url, **kw: None)
    rows, source = sr.registry()
    assert source == "official_fallback_static"
    assert rows
    for r in rows:
        assert r["key"].count("/") == 2, r["key"]
        assert r["key"] == "%s/%s/%s" % (r["owner"], r["repo"], r["skill"])


def test_desc_backfill_tolerates_bad_key_segments(monkeypatch):
    """P0-1 连带：4 段 key 曾让 _desc_backfill 抛 ValueError——而它是裸
    daemon 线程入口，异常会静默杀死线程，desc 永远补不上。"""
    sr._DESC_CACHE.clear()
    called = []
    monkeypatch.setattr(sr, "_raw_skill_md",
                        lambda *a, **k: called.append(a) or "")
    sr._desc_backfill(["a/b/c/d", "a/b/c"])      # 4 段 + 3 段混合
    assert len(called) >= 1, "合法 key 必须继续处理，不能被一条坏 key 打断"


def test_verified_rejects_uniform_error_page(monkeypatch):
    """P1-8 回归：两源都返回同一张 HTML 错误页 → 不能当成 cross-verified。

    企业代理/网关统一返回拦截页时三源天然一致，原实现只看 sha 相等，会把
    HTML 404 页当技能装进用户目录。
    """
    err = b"<html><body>404: Not Found</body></html>" * 3

    def fake_http(url, **kw):
        return err
    monkeypatch.setattr(sr, "_http", fake_http)
    content, hashes, consistent = sr._fetch_skill_md_verified("o", "r", "s")
    assert content is None and hashes == {}

    def fake_ok(url, **kw):
        if "testingcf" in url:
            return MD_EVIL + b"\n"
        return MD_GOOD + b"\n"
    monkeypatch.setattr(sr, "_http", fake_ok)
    content2, _h2, consistent2 = sr._fetch_skill_md_verified("o", "r", "s")
    assert content2 is not None and consistent2 is False


def test_install_is_atomic_no_partial_dir_on_failure(monkeypatch, tmp_path):
    """P0-4 回归：安装过程失败不能留半装目录（原来先写 SKILL.md 再拉辅助
    文件，失败时目录已存在且已落盘）。"""
    monkeypatch.setattr(sr, "_fetch_skill_md_verified",
                        lambda *a: (MD_GOOD.decode(), {"official": "a"}, None))
    monkeypatch.setattr(sr, "skill_files", lambda *a: None)
    real_open = open

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr("builtins.open", boom)
    r = sr.install("o", "r", "s")
    assert r["ok"] is False and "回滚" in r["err"]
    assert not os.path.isdir(os.path.join(str(tmp_path), "skills", "s"))


def test_install_rejects_ntfs_ads_and_reserved_names(monkeypatch, tmp_path):
    """P2-10 回归：`payload:hidden.exe` 会写进 NTFS 备用数据流（资源管理器
    看不见），`aux.py`/`con.py` 是保留名。必须拒绝并如实上报。"""
    monkeypatch.setattr(sr, "_fetch_skill_md_verified",
                        lambda *a: (MD_GOOD.decode(), {"official": "a"}, None))
    monkeypatch.setattr(sr, "skill_files",
                        lambda *a: [("payload:hidden.exe", "https://raw."
                                     "githubusercontent.com/o/r/main/x", "file", None),
                                    ("aux.py", "https://raw.githubusercontent."
                                     ".com/o/r/main/aux.py", "file", None),
                                    ("ok.py", "https://raw.githubusercontent."
                                     ".com/o/r/main/ok.py", "file", None)])
    monkeypatch.setattr(sr, "_fetch_multi",
                        lambda v, **k: (b"# content\n" * 3, v[0][0]))
    r = sr.install("o", "r", "s")
    assert r["ok"] is True and r["partial"] is True
    d = os.path.join(str(tmp_path), "skills", "s")
    assert open(os.path.join(d, "ok.py"), "rb").read()
    assert set(r.get("skipped", [])) >= {"payload:hidden.exe", "aux.py"}
    # 注意：不能用 os.path.exists('...\aux.py') 判定——Windows 上 AUX 是设备名，
    # 该表达式恒为 True。改为看真实目录列表。
    assert sorted(os.listdir(d)) == ["SKILL.md", "ok.py"]


def test_skill_files_recurses_subdirs(monkeypatch):
    """P1-6 回归：子目录里的辅助文件不能被丢弃。

    官方技能 17 个里 13 个的辅助文件在子目录（pdf 的 8 个脚本在 scripts/）。
    原来 `typ != "file"` 直接跳过 dir 项，装完只剩 SKILL.md 且 partial=False。
    """
    pages = {
        "contents/skills/pdf": [{"name": "SKILL.md", "type": "file",
                                 "download_url": "u0", "sha": "s0"},
                                {"name": "scripts", "type": "dir"},
                                {"name": "README.md", "type": "file",
                                 "download_url": "u1", "sha": "s1"}],
        "contents/skills/pdf/scripts": [
            {"name": "fill.py", "type": "file", "download_url": "u2",
             "sha": "s2"},
            {"name": "deep", "type": "dir"}],
        "contents/skills/pdf/scripts/deep": [
            {"name": "x.py", "type": "file", "download_url": "u3", "sha": "s3"}],
    }

    def fake_http(url, **kw):
        for k, v in pages.items():
            if url.endswith(k):
                return json.dumps(v)
        return None
    monkeypatch.setattr(sr, "_http", fake_http)
    out = sr.skill_files("o", "r", "pdf")
    names = {n for n, _u, _t, _s in out}
    assert {"SKILL.md", "README.md", "scripts/fill.py",
            "scripts/deep/x.py"} <= names


def test_install_writes_subdir_files(monkeypatch, tmp_path):
    """P1-6 端到端：子目录文件真的落盘到对应层级。"""
    monkeypatch.setattr(sr, "_fetch_skill_md_verified",
                        lambda *a: (MD_GOOD.decode(), {"official": "a"}, None))
    monkeypatch.setattr(sr, "skill_files",
                        lambda *a: [("scripts/fill.py",
                                     "https://raw.githubusercontent.com/o/r/"
                                     "main/scripts/fill.py", "file", None)])
    monkeypatch.setattr(sr, "_fetch_multi",
                        lambda v, **k: (b"print(1)\n", v[0][0]))
    r = sr.install("o", "r", "s")
    assert r["ok"] is True
    p = os.path.join(str(tmp_path), "skills", "s", "scripts", "fill.py")
    assert open(p, "rb").read() == b"print(1)\n"


def test_install_rejects_path_traversal_in_aux(monkeypatch, tmp_path):
    """P1-6 安全面：子路径里带 `..` 的项必须拒绝（不能写穿技能目录）。"""
    monkeypatch.setattr(sr, "_fetch_skill_md_verified",
                        lambda *a: (MD_GOOD.decode(), {"official": "a"}, None))
    monkeypatch.setattr(sr, "skill_files",
                        lambda *a: [("../../evil.py",
                                     "https://raw.githubusercontent.com/o/r/"
                                     "main/evil.py", "file", None)])
    monkeypatch.setattr(sr, "_fetch_multi",
                        lambda v, **k: (b"EVIL\n", v[0][0]))
    r = sr.install("o", "r", "s")
    assert r["ok"] is True and r["partial"] is True
    assert "evil.py" in " ".join(r.get("skipped", []))
    assert not os.path.exists(os.path.join(str(tmp_path), "skills", "evil.py"))


def test_safe_skill_dir_allows_junction_root(monkeypatch, tmp_path):
    """P2-18 回归：技能根源头是 junction/符号链接时不能整页报「未安装」。"""
    real = tmp_path / "real_skills"
    real.mkdir()
    link = tmp_path / "skills"
    try:
        os.symlink(str(real), str(link), target_is_directory=True)
    except (OSError, NotImplementedError, AttributeError):
        pytest.skip("当前环境不支持创建目录符号链接")
    monkeypatch.setattr(sr, "_SKILLS_DIR", str(link))
    p = sr._safe_skill_dir("foo")
    assert p is not None, "根源头是链接时技能名仍应合法"
    # 反例：解析后跑出根外仍然要拒
    assert sr._safe_skill_dir("..") is None


def test_raw_skill_md_rejects_error_page_and_negative_caches(monkeypatch):
    """a644 回归：/api/skills/translate 的 502「SKILL.md 拉取失败」两类根因。

    1) 原判据只有 len>32——企业代理的 HTML 拦截页被当 SKILL.md 返回并落盘；
    2) 全候选都失败要跑 3 路径×2 分支×多源×15s 超时，且每次重试，前端一
       开详情页就长时间挂起、日志成串 502。现在失败记忆 60s，重试不再出网。
    """
    monkeypatch.setattr(sr, "_RAW_FAIL", {})
    err = b"<html><body>502 Bad Gateway</body></html>" * 3
    hits = []

    def fake_http(url, **kw):
        hits.append(url)
        return err
    monkeypatch.setattr(sr, "_http", fake_http)

    assert sr._raw_skill_md("o", "r", "bad") is None
    first = len(hits)
    assert first > 0
    # 失败记忆：同一 key 立刻再拉不再出网
    assert sr._raw_skill_md("o", "r", "bad") is None
    assert len(hits) == first, "失败后 60s 内必须走记忆，不得重复出网"

    # 真 SKILL.md 恢复后（TTL 过期）能重新探到并落缓存
    monkeypatch.setattr(sr, "_RAW_FAIL", {})
    monkeypatch.setattr(sr, "_http", lambda url, **kw: MD_GOOD + b"\n")
    got = sr._raw_skill_md("o", "r", "good")
    assert got and got.startswith("---")
    assert not os.path.exists(
        os.path.join(sr._CACHE_DIR, "o_r_bad.md")), "错误页不得写入缓存"


def test_raw_skill_md_does_not_cache_error_page(monkeypatch):
    """错误页即使先到也不能占住缓存位（原实现 len>32 直接落盘）。"""
    monkeypatch.setattr(sr, "_RAW_FAIL", {})
    err = b"<!DOCTYPE html><html>gateway</html>" * 4
    monkeypatch.setattr(sr, "_http", lambda url, **kw: err)
    assert sr._raw_skill_md("o2", "r2", "s2") is None
    assert not os.path.exists(os.path.join(sr._CACHE_DIR, "o2_r2_s2.md"))
