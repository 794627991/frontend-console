# -*- coding: utf-8 -*-
"""网页 tab 后端残路（Electron 壳形态，2026-11-22 P4）。

网页视图自 P3 起归前端 DOM（Electron `<webview>`），旧 WebView2 控件池/
密码库/生命周期管理已随 pywebview 链整体删除。本模块只保留一个后端单一
真源：防自动签到注入脚本（前端 did-attach-webview 时拉取并注入每个 guest
文档）。控制类旧 API 保留空实现，兼容旧页面缓存/第三方调用不炸。

密码存储/填充已迁到 Electron 主进程（safeStorage + guest-preload），
后端不再读 WebView2 Login Data。
"""
from flask import Blueprint, jsonify, request

# a557/a582：防自动签到脚本——密码表单 submit 若无近 3s 用户手势
# （pointerdown/keydown）则拦截。浏览器 auto sign-in 无手势必被拦；
# 用户真实点击/回车天然带手势不受影响。
_ANTI_AUTOSIGNIN_JS = (
    "// a582（内网方案·根因3）：原 var g=0 使 Date.now()-0 恒>3000 →"
    "// 所有提交（含 cookie 自动登录）全被拦 = 登录态记忆失效。"
    "// 语义=最近 3 秒内无手势才拦（自动签到防护不变）"
    "(function(){var g=Date.now();"
    "addEventListener('pointerdown',function(){g=Date.now()},true);"
    "addEventListener('keydown',function(){g=Date.now()},true);"
    "addEventListener('submit',function(e){try{"
    "var f=e.target;if(!f||!f.querySelector)return;"
    "if(!f.querySelector('input[type=password]'))return;"
    "if(Date.now()-g>3000){e.preventDefault();}"
    "}catch(_){}},true);})();")


def register(app):
    bp = Blueprint("web_tabs", __name__)

    @bp.route("/api/web/tabs/inject")
    def api_web_inject_js():
        """前端注入源（唯一仍在用的接口）。"""
        return jsonify({"ok": True, "js": _ANTI_AUTOSIGNIN_JS})

    @bp.route("/api/web/tabs", methods=["POST"])
    def api_web_tabs():
        """旧控件命令通道（P3 起视图归前端 DOM）——空实现兼容。"""
        req = request.get_json(force=True, silent=True) or {}
        act = str(req.get("act") or "")
        if act.startswith("pw_"):
            # 文案会进界面：UI 禁 emoji 铁律——不写 🔑，直接点明按钮名
            return jsonify({"ok": False,
                            "err": "密码管理已迁至 Electron 壳（点网页工具栏的「密码管理」按钮）"})
        return jsonify({"ok": True})

    app.register_blueprint(bp)
