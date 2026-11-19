# -*- coding: utf-8 -*-
"""Lanzi 相关配置项读写（a672）。

落 config.json，与代理自己的配置（retry_config.json 等）分开——这两项只
影响额度抓取，与转发无关。
"""
from src.app_state import cfg_read, cfg_commit


def get_quota_auto():
    """「自动刷新(10min)」：定时拉额度。默认 True。

    只管刷新额度，不管登录失败后要不要重登——自动重登是独立开关
    get_auto_relogin（a448 用户令：不许混为一谈）。
    """
    try:
        v = (cfg_read() or {}).get("proxy_quota_auto")
        return True if v is None else bool(v)
    except Exception:
        return True


def set_quota_auto(on):
    try:
        ok, _err = cfg_commit(lambda d: d.__setitem__("proxy_quota_auto", bool(on)))
        return ok
    except Exception:
        return False


def get_auto_relogin():
    """a448：自动重登独立开关。默认 True（用户令：默认开启，可手动关闭）。"""
    try:
        v = (cfg_read() or {}).get("proxy_quota_auto_relogin")
        return True if v is None else bool(v)
    except Exception:
        return True


def set_auto_relogin(on):
    try:
        ok, _err = cfg_commit(
            lambda d: d.__setitem__("proxy_quota_auto_relogin", bool(on)))
        return ok
    except Exception:
        return False
