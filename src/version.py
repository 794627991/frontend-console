# -*- coding: utf-8 -*-
"""版本单一源（v2.27.22 起升级功能配套）。

此前版本号散布硬编码在 main/mcp_server/server/serial_cli 多处，改版要逐个
找——升级功能（manifest 比对、打包发布、关于页显示）都依赖它，必须收敛到
一处。发版流程：改这里 → 跑打包.bat（build.py 读它生成 manifest.json）。

semver（主.次.修订）：不兼容改动动主号，新功能动次号，修 bug 动修订号。
用户定调（v2.2.0 起）：近期迭代都走 2.2.x 小版本序列。
"""
APP_VERSION = "2.2.0"
