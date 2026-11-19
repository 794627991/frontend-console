# -*- coding: utf-8 -*-
"""Lanzi 专栏后端包（a672）。

把「Lanzi 网关相关的一切」集中到这里，代理模块只留纯转发职责：

    bot.py      HikLink 机器人（WS 客户端 / 注册 / 凭据）
    sso.py      SSO 锁定状态匿名探测
    quota.py    Lanz 平台客户端（CAS 登录 + 额度/负载查询）
    worker.py   额度后台线程（自动刷新 / 自动重登 / 熔断）
    state.py    凭据缓存、登录态、额度快照、跨进程登录标记
    routes.py   /api/lanzi/* HTTP 端点
    api.py      对外稳定门面（proxy / server 只从这里取）

生效判据（用户定调）：认**上游 host** 不认 base_url——代理会改 base_url，
但上游不会改。见 api.is_lanz_upstream()。
"""
