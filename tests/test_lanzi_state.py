# -*- coding: utf-8 -*-
"""Lanzi 上游判定钉测（a675）。

为什么钉这一块：`is_lanz_upstream()` 是「Lanzi 专栏是否生效」的唯一判据，
判断错只有两种后果——(a) 非 lanzi 网关误显额度（数据无意义、可能误导），
(b) lanzi 网关不显额度（功能直接消失）。它在 a672 之前有过一个真实漏洞：

    原实现只看 `ctl.running` 就无条件信 `server.upstream_host`。
    而 `/api/claude/api_config` 改 base_url 时**不重指上游**，
    于是「代理在跑 → 用户把 base_url 改成智谱」会被判成 lanz_active=true：
    流量实际已绕过本机代理直连智谱，界面却还挂在 lanz 额度上。

用户定调（需求 5/6）：**认上游 host，不认 base_url**——代理会改 base_url，
但请求真正打到的上游不会变。当前实现在此基础上多一步前置校验：
先确认 base_url 是否仍指向自家代理入口，是才信桥上的 upstream_host，
否则以 base_url 本身的上游为准。

本文件把那五种情形钉死，任何人动 state.py 都会有红灯兜底。
"""
import os
import sys
import types
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src              # noqa: E402
from src.lanzi import state as st   # noqa: E402

LANZ_URL = "http://lanz.hikvision.com/v3/anthropic/model"
PROXY_PREFIXES = ("http://127.0.0.1:37349", "http://127.0.0.1:18788")


def _fake_proxy(base_url, running, upstream_host):
    """造一个 src.proxy 替身，只暴露判定所需的四个接口。

    口径与真实实现对齐：
      · _is_own_proxy_url：base_url 是否指向自家 37349/18788 入口
      · _ctl.running / _ctl.server.upstream_host：代理运行态与桥上真值
      · _upstream_of(url)：从 url 解析上游 host（lanz 含子串即 lanz）
      · _direct_url()：代理真正要转发的直连地址
    """
    m = mock.MagicMock()
    m._bmgr.read_current_url.return_value = base_url
    m._is_own_proxy_url.side_effect = (
        lambda u: bool(u) and str(u).startswith(PROXY_PREFIXES))
    m._ctl.running = running
    m._ctl.server = (types.SimpleNamespace(upstream_host=upstream_host)
                     if running else None)
    m._direct_url.return_value = LANZ_URL
    m._upstream_of.side_effect = lambda u: (
        "lanz.hikvision.com" if "lanz" in str(u) else "open.bigmodel.cn",
        80, "http")
    return m


def _judge(base_url, running, upstream_host):
    """在替身 proxy 下求值 is_lanz_upstream()。

    用 sys.modules 替换而不是 patch.object：state.py 里是
    `from src import proxy as _px`（函数内 import），它查的是
    sys.modules['src.proxy'] / src 包的属性。直接塞 sys.modules 最稳，
    也不依赖测试进程里是否已经真实导入过 proxy。
    """
    fake = _fake_proxy(base_url, running, upstream_host)
    with mock.patch.dict(sys.modules, {"src.proxy": fake}), \
            mock.patch.object(src, "proxy", fake, create=True):
        return st.is_lanz_upstream()


# ---- 五种情形（提交信息里宣称验证过的，这里钉成回归）------------------

def test_direct_lanz_without_proxy():
    """(a) 直连 lanz、代理没跑：读直连 url 的上游 → True。"""
    assert _judge(LANZ_URL, False, "") is True


def test_proxy_running_upstream_lanz():
    """(b) 代理在跑且 base_url 指向自家代理入口：读桥上 upstream_host → True。

    这是最常见的正常形态：代理改 base_url 成 127.0.0.1:37349，但上游还是 lanz。
    """
    assert _judge("http://127.0.0.1:37349/v3/anthropic/model",
                  True, "lanz.hikvision.com") is True


def test_proxy_running_upstream_other_gateway():
    """(c) 代理在跑但上游换成智谱：桥上 upstream_host 是 zhipu → False。"""
    assert _judge("http://127.0.0.1:37349/v3/anthropic/model",
                  True, "open.bigmodel.cn") is False


def test_proxy_running_but_baseurl_points_elsewhere():
    """(d) 回归钉测：代理在跑、桥上 upstream 仍是 lanz，但用户把 base_url
    改成了智谱（api_config 不重指上游）。

    此时流量已绕过本机代理直连智谱——**不能**再信桥上的 lanz，
    必须以 base_url 本身为准 → False。

    这是 a672 修掉的那个漏洞：原实现只看 ctl.running 就信 upstream_host。
    """
    assert _judge("https://open.bigmodel.cn/api/anthropic",
                  True, "lanz.hikvision.com") is False


def test_bili_entry_upstream_lanz():
    """(e) 压缩链 bili 入口（18788）+ 内嵌 37349 + 上游 lanz → True。"""
    assert _judge(
        "http://127.0.0.1:18788/bili/http://127.0.0.1:37349/v3/x",
        True, "lanz.hikvision.com") is True


# ---- 边界与防御 -------------------------------------------------------

def test_baseurl_points_to_third_party_without_proxy():
    """代理没跑、base_url 是第三方网关：以 base_url 为准 → False。"""
    assert _judge("https://open.bigmodel.cn/api/anthropic",
                  False, "") is False


def test_unknown_baseurl_falls_back_to_direct_url():
    """base_url 读不到（空串）→ 退回直连推导，与代理自身取值口径一致。"""
    assert _judge("", False, "") is True


def test_lanz_host_matching_is_substring():
    """host 判定用子串包含（与既有实现一致，勿擅自收紧成精确匹配——
    内网可能出现带端口/前缀的变体）。"""
    assert st.is_lanz_host("lanz.hikvision.com") is True
    assert st.is_lanz_host("LANZ.hikvision.com") is True    # 大小写不敏感
    assert st.is_lanz_host("open.bigmodel.cn") is False
    assert st.is_lanz_host("") is False
    assert st.is_lanz_host(None) is False


def test_host_of_url_never_raises():
    """畸形 url 不能把判定打挂（status 路由 3s 一轮，抛错等于面板冻结）。"""
    for bad in ("", "not a url", "://", "http://", None):
        assert isinstance(st.host_of_url(bad), str)


def test_unavailable_proxy_module_yields_false():
    """proxy 模块不可用（None / 属性访问抛错）时判 False。

    宁可额度区显示「不可用」，也不能把 status 路由炸掉——它 3s 一轮，
    抛错等于面板冻结。state.py 里所有 proxy 访问都有 except 兜底，
    这里钉住兜底后的保守取值。
    """
    with mock.patch.object(src, "proxy", None, create=True):
        assert st.is_lanz_upstream() is False
