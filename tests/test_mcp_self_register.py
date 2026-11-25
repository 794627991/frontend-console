# -*- coding: utf-8 -*-
"""MCP 自注册的校正语义（2026-11-25 用户令「启动后必须每次注入或至少校正」）。

起因：~/.claude.json 里 serial-console-pro 指向早已删除的
D:\\AI\\串口控制台Pro，MCP 每次启动 CONNECTION_CLOSED，整套能力全废；
旧实现「只补缺不覆盖」让死条目永久僵住。用户定调：工具启动就该按当前
形态注入自己的 MCP，不对就要改。

直接 `python tests/test_mcp_self_register.py`。全程在临时 HOME 沙箱里，
绝不碰真实 ~/.claude.json。
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


def _sandbox():
    """临时 HOME + 空的 .claude.json / settings.json。"""
    sb = tempfile.mkdtemp(prefix="mcp_selfreg_")
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
    finally:
        for k, v in (("USERPROFILE", old_home), ("HOME", old_home2)):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    print("=" * 56)
    print("通过 %d / 失败 %d" % (len(_PASS), len(_FAIL)))
    for x in _FAIL:
        print("  -", x)
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
