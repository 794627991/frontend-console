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
    sr.set_source_mode("jsdelivr")
    assert sr.source_mode() == "jsdelivr"   # 写入即时可读（cfg_commit 原子）
    # 非法值回退 auto（读侧防御）+ 写侧拒绝
    import src.app_state as _st
    _st._load_config = lambda: {"skill_source": "bogus"}
    assert sr.source_mode() == "auto"
    with pytest.raises(ValueError):
        sr.set_source_mode("bogus")


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

def _md(text):
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def test_verified_consistent(monkeypatch):
    """两源内容一致 → 正常装。"""
    def fake_http(url, **kw):
        if "testingcf" in url:
            return b"SKILL CONTENT" * 4
        if "raw.githubusercontent" in url:
            return b"SKILL CONTENT" * 4
        return None

    monkeypatch.setattr(sr, "_http", fake_http)
    content, hashes, consistent = sr._fetch_skill_md_verified("o", "r", "s")
    assert content == "SKILL CONTENT" * 4
    assert consistent is True
    assert len(set(hashes.values())) == 1


def test_verified_conflict(monkeypatch):
    """两源不一致 → consistent=False（默认拒装依据）。"""
    def fake_http(url, **kw):
        if "testingcf" in url:
            return b"EVIL CONTENT" * 4
        if "raw.githubusercontent" in url:
            return b"SKILL CONTENT" * 4
        return None

    monkeypatch.setattr(sr, "_http", fake_http)
    content, hashes, consistent = sr._fetch_skill_md_verified("o", "r", "s")
    assert consistent is False
    assert set(hashes) == {"official", "jsdelivr"}
    assert hashes["official"] != hashes["jsdelivr"]
    # content = 官方源版本（confirm 强制装时装这份，不由实现替用户选边）
    assert content == "SKILL CONTENT" * 4


def test_verified_single_source(monkeypatch):
    """仅一源可达 → 单源放行（consistent=None）。"""
    def fake_http(url, **kw):
        return b"SKILL CONTENT" * 4 if "raw.githubusercontent" in url else None

    monkeypatch.setattr(sr, "_http", fake_http)
    content, hashes, consistent = sr._fetch_skill_md_verified("o", "r", "s")
    assert content == "SKILL CONTENT" * 4 and consistent is None
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
        return b"FALLBACK COMBO CONTENT" + b"-" * 20

    monkeypatch.setattr(sr, "_http", fake_http)
    content, hashes, consistent = sr._fetch_skill_md_verified("o", "r", "s")
    assert content == "FALLBACK COMBO CONTENT" + "-" * 20
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

    def fake_fetch_multi(variants, timeout=20, want_bytes=True):
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
            b = b"STALE-CDN-VERSION-" + b"-" * 20
        elif "api.github.com" in url:
            b = b"FRESH-GHAPI-VERSION" + b"-" * 20
        elif "raw.githubusercontent" in url:
            return None   # official 被墙（目标环境常态）
        if b is not None:
            _th.Event().wait(delays.get(
                "jsdelivr" if "testingcf" in url else "gh_api", 0))
        return b

    monkeypatch.setattr(sr, "_http", fake_http)
    for _ in range(3):   # 重复多次：竞速顺序不得影响 pick
        content, hashes, consistent = sr._fetch_skill_md_verified("o", "r", "s")
        assert content == b"FRESH-GHAPI-VERSION".decode() + "-" * 20, \
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
    X = "VERSION-X-" + "a" * 24
    Y = "VERSION-Y-" + "b" * 24
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

