# -*- coding: utf-8 -*-
"""MCP 自注册的校正语义（2026-11-25 用户令「启动后必须每次注入或至少校正」）。

起因：~/.claude.json 里 serial-console-pro 指向早已删除的
D:\\AI\\串口控制台Pro，MCP 每次启动 CONNECTION_CLOSED，整套能力全废；
旧实现「只补缺不覆盖」让死条目永久僵住。用户定调：工具启动就该按当前
形态注入自己的 MCP，不对就要改。

直接 `python tests/test_mcp_self_register.py`。全程在临时 HOME 沙箱里，
绝不碰真实 ~/.claude.json。

第 7~9 组（2026-11-25 审查 a696 时补）：自注册改成每次启动自动跑之后，
「配置文件读不出来 → 当成空配置 → 补键落盘」这条路会把整份 ~/.claude.json /
settings.json 清空（带 BOM 的文件就会触发，不需要任何巧合）。现在读不出来
就放弃写入、如实报告；这里每一项都要求两份文件一个字节不变。
"""
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_PASS, _FAIL = [], []


def check(name, cond, detail=""):
    if cond:
        _PASS.append(name)
        print("  PASS  %s" % name)
    else:
        _FAIL.append(name)
        print("  FAIL  %s  %s" % (name, detail))


_BOXES = []            # 这次运行建的全部沙箱：main 的 finally 里删掉（只删自己建的）


def _sandbox():
    """临时 HOME + 空的 .claude.json / settings.json。"""
    sb = tempfile.mkdtemp(prefix="mcp_selfreg_")
    _BOXES.append(sb)
    os.makedirs(os.path.join(sb, ".claude"), exist_ok=True)
    json.dump({"permissions": {"allow": [], "defaultMode": "auto"}},
              open(os.path.join(sb, ".claude", "settings.json"), "w"))
    return sb


def _write_cfg(sb, servers):
    json.dump({"mcpServers": servers},
              open(os.path.join(sb, ".claude.json"), "w", encoding="utf-8"))


def _read_cfg(sb):
    return json.load(open(os.path.join(sb, ".claude.json"), encoding="utf-8"))


def main():
    old_home = os.environ.get("USERPROFILE")
    old_home2 = os.environ.get("HOME")
    try:
        # 模块在 import 时就定了路径常量，所以每次换沙箱都重新加载
        import importlib
        from src import claude_default as cd

        expect_args = [os.path.join(ROOT, "src", "mcp_server.py")]

        print("== 1. 指向已删除目录的死条目 → 校正 ==")
        sb = _sandbox()
        os.environ["USERPROFILE"] = sb
        os.environ["HOME"] = sb
        _write_cfg(sb, {"serial-console-pro": {
            "type": "stdio", "command": r"C:\old\python.exe",
            "args": [r"D:\AI\串口控制台Pro\src\mcp_server.py"],
            "env": {"PYTHONIOENCODING": "utf-8"}}})
        cd = importlib.reload(cd)
        wrote = cd._register_self_mcp()
        check("死条目被重写", "mcpServers" in wrote, str(wrote))
        got = _read_cfg(sb)["mcpServers"]["serial-console-pro"]
        check("args 指向当前工程的 mcp_server.py",
              [os.path.normcase(os.path.normpath(x)) for x in got["args"]]
              == [os.path.normcase(os.path.normpath(x)) for x in expect_args],
              str(got["args"]))

        print("== 2. 已正确 → 不重复写盘（幂等）==")
        before = open(os.path.join(sb, ".claude.json"), "rb").read()
        wrote = cd._register_self_mcp()
        after = open(os.path.join(sb, ".claude.json"), "rb").read()
        check("返回空列表", wrote == [], str(wrote))
        check("文件一个字节都没动", before == after)

        print("== 3. 指向另一个副本（文件存在但连错实例）→ 也要校正 ==")
        sb2 = _sandbox()
        os.environ["USERPROFILE"] = sb2
        os.environ["HOME"] = sb2
        other = os.path.join(sb2, "other_copy")
        os.makedirs(other)
        other_srv = os.path.join(other, "mcp_server.py")
        open(other_srv, "w").write("# another copy\n")
        _write_cfg(sb2, {"serial-console-pro": {
            "type": "stdio", "command": sys.executable,
            "args": [other_srv], "env": {"PYTHONIOENCODING": "utf-8"}}})
        cd = importlib.reload(cd)
        wrote = cd._register_self_mcp()
        check("活着的错误副本也被校正", "mcpServers" in wrote, str(wrote))
        got = _read_cfg(sb2)["mcpServers"]["serial-console-pro"]
        check("改回当前工程",
              os.path.normcase(os.path.normpath(got["args"][0]))
              == os.path.normcase(os.path.normpath(expect_args[0])),
              str(got["args"]))

        print("== 4. 路径大小写/分隔符差异不算「不对」==")
        sb3 = _sandbox()
        os.environ["USERPROFILE"] = sb3
        os.environ["HOME"] = sb3
        variant = expect_args[0].replace("\\", "/").upper()
        _write_cfg(sb3, {"serial-console-pro": {
            "type": "stdio", "command": sys.executable,
            "args": [variant], "env": {"PYTHONIOENCODING": "utf-8"}}})
        cd = importlib.reload(cd)
        wrote = cd._register_self_mcp()
        check("等价写法不触发重写", "mcpServers" not in wrote, str(wrote))

        print("== 5. 用户给条目加的自定义 env 不被吃掉 ==")
        sb4 = _sandbox()
        os.environ["USERPROFILE"] = sb4
        os.environ["HOME"] = sb4
        _write_cfg(sb4, {"serial-console-pro": {
            "type": "stdio", "command": sys.executable,
            "args": list(expect_args),
            "env": {"PYTHONIOENCODING": "utf-8", "MY_CUSTOM": "1"}}})
        cd = importlib.reload(cd)
        wrote = cd._register_self_mcp()
        check("command/args 正确时不动条目", "mcpServers" not in wrote, str(wrote))
        got = _read_cfg(sb4)["mcpServers"]["serial-console-pro"]
        check("自定义 env 仍在", (got.get("env") or {}).get("MY_CUSTOM") == "1",
              str(got.get("env")))

        print("== 6. 授权条目补齐 ==")
        allow = (json.load(open(os.path.join(sb4, ".claude", "settings.json"),
                                encoding="utf-8")).get("permissions") or {}).get("allow") or []
        check("mcp__serial-console-pro 已授权", "mcp__serial-console-pro" in allow,
              str(allow))
        check("通配授权已在", "mcp__serial-console-pro__*" in allow, str(allow))

        # ================================================================
        # 2026-11-25 审查 a696 时复现（沙箱）：自注册改成每次启动自动跑之后，
        # 「配置文件读不出来 → 当成空配置 → 补键落盘」这条路不再需要人手点。
        # 读不出来（别的进程写到一半 / 被独占 / 带 BOM / 结构不对）时，整份
        # ~/.claude.json 被写成只剩一条 mcpServers（登录凭据、全部项目历史、别的
        # MCP 全没），settings.json 同理只剩 permissions。带 BOM 那种不需要任何
        # 巧合：PowerShell 5.1 存 UTF8 就带 BOM，此后每次启动、每次保存 API 配置
        # 都会清空它。下面每一项都要求：放弃写入、如实报告、文件一个字节不变。
        # ================================================================
        import builtins
        import flask

        _real_open = builtins.open
        HALF = b'{"mcpServers": {"rea": {"type":"stdio","comm'      # 别的进程写到一半
        BOM = b"\xef\xbb\xbf"                                       # PowerShell 5.1 存 UTF8 就带
        ready = {"type": "stdio", "command": sys.executable,
                 "args": [os.path.join(ROOT, "src", "mcp_server.py")],
                 "env": {"PYTHONIOENCODING": "utf-8"}}

        def _rich_cj(entry):
            return json.dumps({
                "oauthAccount": {"accessToken": "SECRET-TOKEN"},
                "projects": {"D:/p": {"history": [1]}},
                "mcpServers": {"rea": {"command": "node", "args": ["rea.mjs"]},
                               "codegraph": {"command": "codegraph", "args": ["serve"]},
                               "serial-console-pro": entry},
            }, ensure_ascii=False).encode("utf-8")

        def _rich_st(allow=("Bash(git *)",)):
            return json.dumps({
                "apiKeyHelper": "C:/x/helper.ps1", "env": {"ANTHROPIC_MODEL": "m"},
                "permissions": {"allow": list(allow), "defaultMode": "auto"},
                "hooks": {"PreToolUse": []},
            }, ensure_ascii=False).encode("utf-8")

        def _put(path, data):
            with _real_open(path, "wb") as f:
                f.write(data)

        def _unchanged(path, data):
            return os.path.exists(path) and _real_open(path, "rb").read() == data

        def _client():
            a = flask.Flask("selfreg_probe")
            a.register_blueprint(cd.claude_default_bp)      # reload 之后蓝图是新的，每次重新挂
            return a.test_client()

        def _guarded(name, cj, st, call, busy=None, http=False):
            """沙箱里放好两份文件 → 调用 → 期望放弃写入，两份文件一个字节都没变。
            busy：要模拟「被别的程序独占着」的文件名（读它的时候抛 PermissionError）。
            http：call 返回 (状态码, 响应体)，期望 200 + ok=False + 说明读不出来。"""
            nonlocal cd
            sb = _sandbox()
            os.environ["USERPROFILE"] = sb
            os.environ["HOME"] = sb
            cjp, stp = os.path.join(sb, ".claude.json"), os.path.join(sb, ".claude", "settings.json")
            _put(cjp, cj)
            _put(stp, st)
            cd = importlib.reload(cd)

            def busy_open(p, *a, **k):
                if busy and str(p).replace("\\", "/").endswith("/" + busy):
                    raise PermissionError(13, "另一个程序正在使用此文件")
                return _real_open(p, *a, **k)
            if busy:
                builtins.open = busy_open
            try:
                out = call()
                if http:
                    code, body = out
                    passed = (code == 200 and body.get("ok") is False
                              and "读不出来" in (body.get("err") or ""))
                    how = "HTTP %s，ok=%s" % (code, body.get("ok"))
                else:
                    how, passed = "返回了（没抛）", False
            except cd._CfgUnreadable:
                how, passed = "抛 _CfgUnreadable", not http
            except Exception as e:                               # noqa: BLE001 —— 如实报告
                how, passed = "抛了别的异常 %s: %s" % (type(e).__name__, e), False
            finally:
                builtins.open = _real_open
            same = _unchanged(cjp, cj) and _unchanged(stp, st)
            check(name, passed and same,
                  "%s；claude.json %s，settings.json %s" % (
                      how, "没变" if _unchanged(cjp, cj) else "被改了",
                      "没变" if _unchanged(stp, st) else "被改了"))
            return sb

        def _self_reg():
            return cd._register_self_mcp()

        def _post(path, body):
            r = _client().post(path, json=body)
            return r.status_code, r.get_json()

        print("== 7. 配置读不出来 → 放弃写入、文件不动 ==")
        print("  （每次启动自动跑的自注册）")
        _guarded("claude.json 是半截的", HALF, _rich_st(), _self_reg)
        _guarded("settings.json 是半截的", _rich_cj(ready), HALF, _self_reg)
        _guarded("claude.json 的内容不是对象", b'[1, 2, 3]', _rich_st(), _self_reg)
        _guarded("claude.json 被别的程序独占着", _rich_cj(ready), _rich_st(), _self_reg,
                 busy=".claude.json")
        print("  （设置页的两个接口：返回失败和原因，不能报成成功）")
        _guarded("保存 API 配置：settings.json 是半截的", _rich_cj(ready), HALF,
                 lambda: _post("/api/claude/api_config", {"token": "NEW"}), http=True)
        _guarded("保存 API 配置：settings.json 被独占着", _rich_cj(ready), _rich_st(),
                 lambda: _post("/api/claude/api_config", {"token": "NEW"}), http=True,
                 busy="settings.json")
        _guarded("恢复默认配置：settings.json 是半截的", _rich_cj(ready), HALF,
                 lambda: _post("/api/claude/provision", {}), http=True)
        print("  （同文件里其余两处读-改-写）")
        # 用 lambda 而不直接传函数：_guarded 里会 reload 模块，直接传过去的是重载前的
        # 函数对象，它抛的 _CfgUnreadable 和重载后比对的不是同一个类，会被误报成
        # 「抛了别的异常」
        _guarded("首次确认位预置：claude.json 是半截的", HALF, _rich_st(),
                 lambda: cd._preaccept_onboarding())
        from src import nav_codegraph as _ncg
        _real_argv = _ncg._cg_argv
        _ncg._cg_argv = lambda: ["node", "D:/x/codegraph.js"]     # 装没装 codegraph 都走到读取那一步
        try:
            _guarded("codegraph 注册：claude.json 是半截的", HALF, _rich_st(),
                     lambda: cd._register_codegraph_mcp())
        finally:
            _ncg._cg_argv = _real_argv

        print("== 8. 带 BOM 的合法文件：读得出来，只补该补的 ==")
        stale = dict(ready, command="python", args=["D:/nope/src/mcp_server.py"],
                     env={"PYTHONIOENCODING": "utf-8", "MY_CUSTOM": "keep-me"})

        def _load(path):
            # 写回时不带 BOM；读的时候带不带都认
            with _real_open(path, encoding="utf-8-sig") as f:
                return json.load(f)

        sb = _sandbox()
        os.environ["USERPROFILE"] = sb
        os.environ["HOME"] = sb
        _put(os.path.join(sb, ".claude.json"), BOM + _rich_cj(stale))
        _put(os.path.join(sb, ".claude", "settings.json"), BOM + _rich_st())
        cd = importlib.reload(cd)
        wrote = None
        try:
            wrote = cd._register_self_mcp()
            how = str(wrote)
        except Exception as e:                                    # noqa: BLE001 —— 如实报告
            how = "%s: %s" % (type(e).__name__, e)
        cj_obj = _load(os.path.join(sb, ".claude.json"))
        st_obj = _load(os.path.join(sb, ".claude", "settings.json"))
        check("没抛，条目与授权都补上了",
              isinstance(wrote, list) and set(wrote) == {"mcpServers", "permissions"}, how)
        check("claude.json：登录凭据 / 项目历史 / 另外两个 MCP 都还在",
              "oauthAccount" in cj_obj and "projects" in cj_obj
              and set(cj_obj["mcpServers"]) >= {"rea", "codegraph", "serial-console-pro"},
              str(sorted(cj_obj)))
        got = cj_obj["mcpServers"]["serial-console-pro"]
        check("条目已校正为当前工程",
              [os.path.normcase(os.path.normpath(x)) for x in got["args"]]
              == [os.path.normcase(os.path.normpath(x)) for x in ready["args"]], str(got.get("args")))
        check("覆盖条目时保留用户加的自定义环境变量",
              (got.get("env") or {}).get("MY_CUSTOM") == "keep-me", str(got.get("env")))
        check("settings.json：只追加授权，apiKeyHelper / env / hooks 都还在",
              all(k in st_obj for k in ("apiKeyHelper", "env", "hooks"))
              and "Bash(git *)" in st_obj["permissions"]["allow"]
              and "mcp__serial-console-pro" in st_obj["permissions"]["allow"], str(sorted(st_obj)))

        print("== 9. 正常路径不受影响 ==")
        sb = _sandbox()
        os.environ["USERPROFILE"] = sb
        os.environ["HOME"] = sb
        cjp, stp = os.path.join(sb, ".claude.json"), os.path.join(sb, ".claude", "settings.json")
        _put(cjp, _rich_cj(ready))
        _put(stp, _rich_st(("Bash(git *)", "mcp__serial-console-pro", "mcp__serial-console-pro__*")))
        cd = importlib.reload(cd)
        before = (_real_open(cjp, "rb").read(), _real_open(stp, "rb").read())
        wrote = cd._register_self_mcp()
        check("条目与授权都就绪：不写盘（两个文件一个字节都没动）",
              wrote == []
              and before == (_real_open(cjp, "rb").read(), _real_open(stp, "rb").read()), str(wrote))
        sb = _sandbox()
        os.environ["USERPROFILE"] = sb
        os.environ["HOME"] = sb
        os.remove(os.path.join(sb, ".claude", "settings.json"))      # 两份都不存在：首次使用
        cd = importlib.reload(cd)
        wrote = cd._register_self_mcp()
        check("两份都不存在：照常新建",
              set(wrote) == {"mcpServers", "permissions"}
              and os.path.isfile(os.path.join(sb, ".claude.json"))
              and os.path.isfile(os.path.join(sb, ".claude", "settings.json")), str(wrote))
    finally:
        for k, v in (("USERPROFILE", old_home), ("HOME", old_home2)):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        for sb in _BOXES:              # 只删这次运行自己建的沙箱
            shutil.rmtree(sb, ignore_errors=True)

    print("=" * 56)
    print("通过 %d / 失败 %d" % (len(_PASS), len(_FAIL)))
    for x in _FAIL:
        print("  -", x)
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
