# -*- coding: utf-8 -*-
"""托盘「Lanzi」菜单段（a672）。

与代理段分开：额度是 lanzi 网关的数据，不是代理转发数据。两种形态同构：

  - worker 分离（_base 非空）：走 HTTP 桥读 /api/lanzi/status（2s 缓存，
    一次右键打开菜单的多个 text 求值共享同一次拉取）
  - inline 形态（_offload=False）：直接读本地 lanzi 状态槽，零网络

「立即刷新」在 worker 形态经 HTTP POST，inline 形态直接调 lanzi.api。
"""
import json
import time

from src.lanzi import api


def _local_rows():
    return api.tray_quota_rows()


def menu_items(base="", offload=False):
    """返回原生菜单描述树（tray.py 格式）。"""
    if base:
        import urllib.request

        cache = {"ts": 0.0, "data": None}

        def _st():
            now = time.time()
            if cache["data"] is None or now - cache["ts"] > 2.0:
                try:
                    req = urllib.request.urlopen(
                        base + "/api/lanzi/status", timeout=1.5)
                    cache["data"] = json.loads(
                        req.read().decode("utf-8", "replace"))
                except Exception:
                    if cache["data"] is None:
                        cache["data"] = {}
                cache["ts"] = now
            return cache["data"] or {}

        def _post(path):
            try:
                req = urllib.request.Request(
                    base + path, data=b"{}",
                    headers={"Content-Type": "application/json"}, method="POST")
                urllib.request.urlopen(req, timeout=3).read()
            except Exception:
                pass

        def _row():
            d = _st()
            ov = d.get("quota_overview")
            u = d.get("quota_user")
            if not ov:
                return "额度: %s" % ("已登录 " + u if u else "未登录/暂无数据")
            return "今日 外 %s/%s  内 %s/%s" % (
                api.fnum(ov.get("externalDailyUsed") or 0),
                api.fnum(ov.get("externalDailyLimit") or 0),
                api.fnum(ov.get("internalDailyUsed") or 0),
                api.fnum(ov.get("internalDailyLimit") or 0))

        # 用户定调（a680）：Lanzi 只对内网有效，未登录/无数据时整段不出现，
        # 不给外部用户看无意义的灰字占位；登录成功后自动出现。
        d = _st()
        if not (d.get("quota_overview") or d.get("quota_user")):
            return []
        return [
            ("sep",),
            ("item", "Lanzi", None, {"enabled": False}),
            ("item", _row, None, {"enabled": False}),
            ("item", "额度立即刷新",
             lambda: _post("/api/lanzi/refresh"), {}),
        ]

    # inline 形态：本进程直接持有状态，零网络
    if offload:
        # 分离但 worker 未就绪：整段不显示（同上，不给无意义占位）
        return []

    # 未登录/无额度数据：整段不显示（内网专属功能不打扰其他用户）
    if not _local_rows():
        return []

    # 与远端形态不同，本进程直接持有完整额度缓存，可给全 4 行
    # （今日汇总 + Lanz-Auto/Flash/Medium）——与原 proxy._tray_quota_items 同构
    def _row_local():
        rows = _local_rows()
        return rows[0] if rows else "额度: 未登录/暂无数据"

    def _mk_local(idx):
        def _text():
            rows = _local_rows()
            return rows[idx] if idx < len(rows) else "-"
        return _text

    def _refresh_local():
        try:
            api.refresh_now()
        except Exception:
            pass

    return [
        ("sep",),
        ("item", "Lanzi", None, {"enabled": False}),
        ("item", _row_local, None, {"enabled": False}),
        ("item", _mk_local(1), None, {"enabled": False}),
        ("item", _mk_local(2), None, {"enabled": False}),
        ("item", _mk_local(3), None, {"enabled": False}),
        ("item", "额度立即刷新", _refresh_local, {}),
    ]
