# -*- coding: utf-8 -*-
"""Claude 默认环境铺设 + API 配置（settings.json 的 AUTH_TOKEN 读写）。

首次安装完 claude 后铺设默认 ~/.claude/settings.json（基于用户当前
配置模板，BASE_URL 写死内网 lanz 网关）与 statusline.py（模型/思考等级/
上下文百分比状态栏）。API 配置界面只允许改 ANTHROPIC_AUTH_TOKEN。

设计约束：
- settings.json 已存在则只补缺的键（铁律4：不动用户已有配置）
- BASE_URL 写死只读（前端只显示不可改）
"""
import json
import os
import shutil

from flask import Blueprint, jsonify, request

claude_default_bp = Blueprint("claude_default", __name__)

# 内网模型网关（写死——API 配置界面只显示不可改）
DEFAULT_BASE_URL = "http://lanz.hikvision.com/v3/anthropic/model"


def _claude_dir():
    return os.path.join(os.path.expanduser("~"), ".claude")


def _settings_path():
    return os.path.join(_claude_dir(), "settings.json")


def _statusline_path():
    return os.path.join(_claude_dir(), "statusline.py")


# 默认 settings 模板（来自用户实机配置 2026-09；除 AUTH_TOKEN 外全部照搬。
# BASE_URL 写死内网网关——AUTH_TOKEN 由 API 配置界面填入）
DEFAULT_SETTINGS = {
    "env": {
        "ANTHROPIC_AUTH_TOKEN": "",   # 用户在 API 配置界面填
        "ANTHROPIC_BASE_URL": DEFAULT_BASE_URL,
        "ANTHROPIC_DEFAULT_FLASH_MODEL": "Lanz-Flash",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": "Lanz-Flash",
        "ANTHROPIC_DEFAULT_OPUS_MODEL": "Lanz-Auto",
        "ANTHROPIC_DEFAULT_SONNET_MODEL": "Lanz-Medium",
        "ANTHROPIC_MODEL": "Lanz-Auto",
        "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": "90",
        "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "256000",
        "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "256000",
    },
    "statusLine": {
        "type": "command",
        # python 路径安装时替换为本机解释器（statusline.py 依赖 python 运行）
        "command": "",
    },
    "permissions": {
        "allow": [],
        "defaultMode": "auto",
    },
    "outputStyle": "Concise",
    "language": "简体中文",
    "askUserQuestionTimeout": "never",
    "autoUpdatesChannel": "stable",
    "theme": "dark",
    "verbose": True,
    "autoCompactEnabled": True,
}

# statusline.py 内容（与用户实机 ~/.claude/statusline.py 一致）：
# 模型名 + 思考等级 + 上下文 tokens（按 256K 算百分比——本机模型实窗）
STATUSLINE_SRC = '''# -*- coding: utf-8 -*-
"""statusLine：显示 模型名 + 思考等级(effort.level) + 上下文（绝对 tokens + 按 256K 百分比）。

字段路径（claude.exe 二进制提取的权威 schema，2.1.239）：
  model.display_name / model.id      模型名
  effort.level                       思考等级（可选，模型不支持时缺失）
    合法值: low / medium / high / xhigh / max
  context_window.context_window_size  Claude Code 认为的窗口大小（200000）
  context_window.current_usage.*      当前用量明细
  context_window.used_percentage      按 context_window_size 算的百分比（默认 200K）

注：本机模型实际上下文为 256K，与 Claude Code 内置的 200K 不同，
故按 256K 重新计算百分比，并显示绝对 token 数。
"""
import sys, json

# 实际模型上下文窗口（tokens）。Lanz-Auto(GLM-5.2)=256K。
# 必须与 settings.json 的 CLAUDE_CODE_AUTO_COMPACT_WINDOW 一致，
# 否则状态栏百分比与 autocompact 触发时机对不上。
REAL_CTX = 256000

try:
    raw = sys.stdin.read()
    d = json.loads(raw) if raw.strip() else {}
except Exception:
    d = {}

if not isinstance(d, dict):
    d = {}

m = d.get("model", {}) if isinstance(d.get("model"), dict) else {}
name = m.get("display_name") or m.get("id") or ""
effort = None
if isinstance(d.get("effort"), dict):
    effort = d.get("effort").get("level")
cw = d.get("context_window", {}) if isinstance(d.get("context_window"), dict) else {}

# 已用 tokens：优先用 current_usage 各项之和（最贴近真实占用）
used_tokens = None
cu = cw.get("current_usage") if isinstance(cw.get("current_usage"), dict) else {}
if cu:
    try:
        used_tokens = sum(int(cu.get(k, 0) or 0) for k in
                          ("input_tokens", "output_tokens",
                           "cache_creation_input_tokens", "cache_read_input_tokens"))
    except Exception:
        used_tokens = None
# 退路：用 total_input_tokens
if not used_tokens:
    try:
        used_tokens = int(cw.get("total_input_tokens", 0) or 0)
    except Exception:
        used_tokens = None

parts = []
if name:
    parts.append("Model: %s" % name)
if effort:
    parts.append("Effort: %s" % effort)
if used_tokens:
    # 按 256K 重新算百分比
    try:
        pct = round(used_tokens * 100.0 / REAL_CTX)
    except Exception:
        pct = None
    if pct is not None:
        parts.append("Context: %sK / %dK (%d%%)" % (round(used_tokens / 1000), REAL_CTX // 1000, pct))
    else:
        parts.append("Context: %sK / %dK" % (round(used_tokens / 1000), REAL_CTX // 1000))
if parts:
    print("  ".join(parts))
'''


def _read_settings():
    """读 ~/.claude/settings.json；不存在/损坏返回空 dict。"""
    p = _settings_path()
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _write_settings(d):
    os.makedirs(_claude_dir(), exist_ok=True)
    with open(_settings_path(), "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


def provision_defaults(force_statusline=False):
    """安装完成后铺设默认环境（幂等，可重复调）：
    1. statusline.py 复制到 ~/.claude/（已存在跳过，除非 force）
    2. settings.json 补缺的键（已有键不动——铁律4）：
       env 模型映射/上下文窗口、statusLine 指向本机 python+statusline
    3. 默认授权（用户要求：别的用户不该每次手动选接受）：
       - settings.json permissions.defaultMode（auto 已是本机同款）
       - ~/.claude.json onboarding 位 + 全局 bypass 权限确认
    返回 (ok, 铺了什么/告警列表)。
    AUTH_TOKEN 不在铺设范围——留给 API 配置界面（首次打开 claude 前必填）。
    """
    notes = []
    # 1. statusline.py
    sl = _statusline_path()
    if force_statusline or not os.path.isfile(sl):
        with open(sl, "w", encoding="utf-8", newline="\n") as f:
            f.write(STATUSLINE_SRC)
        notes.append("statusline.py 已铺设")
    # 2. settings.json
    cur = _read_settings()
    changed = False
    env = cur.setdefault("env", {})
    if not isinstance(env, dict):
        env = cur["env"] = {}
    for k, v in DEFAULT_SETTINGS["env"].items():
        if k == "ANTHROPIC_AUTH_TOKEN":
            continue   # token 留给用户填
        if k not in env:
            env[k] = v
            changed = True
    # BASE_URL 强制写死 lanz 内网网关（用户定：别人机器没有本机代理，
    # 默认值必须是 lanz 网关才可用——只补缺不覆盖本机自定义值，
    # 全新机器首装必然拿到 lanz 网关）
    if "ANTHROPIC_BASE_URL" not in env:
        env["ANTHROPIC_BASE_URL"] = DEFAULT_BASE_URL
        changed = True
    # 顶层非 env 键
    for k, v in DEFAULT_SETTINGS.items():
        if k in ("env", "statusLine"):
            continue
        if k not in cur:
            cur[k] = v
            changed = True
    # statusLine：command 指向本机 python + statusline.py
    sl_cmd = cur.get("statusLine", {})
    if not isinstance(sl_cmd, dict) or not sl_cmd.get("command"):
        py = shutil.which("python.exe") or shutil.which("python") or sys_python()
        cur["statusLine"] = {
            "type": "command",
            "command": f"{py} {sl.replace(os.sep, '/')}",
        }
        changed = True
        notes.append("statusLine 已配置")
    if changed:
        _write_settings(cur)
        notes.append("settings.json 已补全缺省项")
    # 3. ~/.claude.json 首次确认位（默认授权——别的用户开箱不弹确认）：
    #    onboarding/主题/信任已见等布尔全部预置 true；新建 projects 条目也带
    #    hasTrustDialogAccepted（工作区 trust 不再问）。只补缺不覆盖。
    try:
        _preaccept_onboarding()
        notes.append("首次确认已预置（onboarding/信任）")
    except Exception as e:
        notes.append(f"首次确认预置失败（不影响使用）：{e}")
    return True, notes


def _preaccept_onboarding():
    """~/.claude.json 首次确认位预置（只补缺不覆盖已有值）。
    锁内原子写防并发（与 _trust_workspace 同款 tmp+replace）。"""
    import threading
    if not hasattr(_preaccept_onboarding, "_lock"):
        _preaccept_onboarding._lock = threading.Lock()
    with _preaccept_onboarding._lock:
        path = os.path.join(os.path.expanduser("~"), ".claude.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            d = {}
        changed = False
        # onboarding/提示类确认位（本机实机 .claude.json 全集——首次启动各弹窗）
        for k in ("hasCompletedOnboarding", "hasSeenTasksHint",
                  "hasSeenAutoModeEntryWarning", "hasOpenedAgentsView"):
            if k not in d:
                d[k] = True
                changed = True
        # 新会话所在目录的 trust 位：claude 每次换目录还会问 trust——
        # 启动会话时 claude_conn._trust_workspace 已做同样的事，这里兜首启
        projs = d.setdefault("projects", {})
        if isinstance(projs, dict):
            for key, ent in projs.items():
                if isinstance(ent, dict) and not ent.get("hasTrustDialogAccepted"):
                    ent["hasTrustDialogAccepted"] = True
                    changed = True
        if changed:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False)
            os.replace(tmp, path)


def sys_python():
    """当前解释器绝对路径（打包 exe 场景回退 'python'）。"""
    try:
        return os.path.abspath(__import__("sys").executable)
    except Exception:
        return "python"


# ---- API 配置接口 ----

@claude_default_bp.route("/api/claude/api_config")
def claude_api_config_get():
    """读当前 API 配置：token（打码显示）、BASE_URL（只读）、settings 路径。"""
    cur = _read_settings()
    env = cur.get("env", {}) if isinstance(cur.get("env"), dict) else {}
    token = env.get("ANTHROPIC_AUTH_TOKEN", "")
    masked = (token[:8] + "…" + token[-4:]) if len(token) > 16 else ("已设置" if token else "")
    return jsonify({
        "ok": True,
        "token_masked": masked,
        "has_token": bool(token),
        "base_url": env.get("ANTHROPIC_BASE_URL", ""),
        "default_base_url": DEFAULT_BASE_URL,
        "settings_path": _settings_path(),
        "statusline_path": _statusline_path(),
    })


@claude_default_bp.route("/api/claude/api_config", methods=["POST"])
def claude_api_config_set():
    """写 AUTH_TOKEN（唯一可改项）。body: {token}
    注意：不铺设默认 settings——settings/statusline 只在首次安装完成时
    铺一次（用户要求），这里只做纯 token 写入。"""
    data = request.get_json(force=True, silent=True) or {}
    token = (data.get("token") or "").strip()
    if not token:
        return jsonify({"ok": False, "err": "API Token 不能为空"}), 400
    cur = _read_settings()
    env = cur.setdefault("env", {})
    if not isinstance(env, dict):
        env = cur["env"] = {}
    env["ANTHROPIC_AUTH_TOKEN"] = token
    # BASE_URL 只补缺不覆盖（用户定）：已有值不动——本机代理/自定义网关
    # 不受保存 Token 影响；全新机器（首装铺设）拿到 lanz 网关默认值
    if not env.get("ANTHROPIC_BASE_URL"):
        env["ANTHROPIC_BASE_URL"] = DEFAULT_BASE_URL
    _write_settings(cur)
    return jsonify({"ok": True})


@claude_default_bp.route("/api/claude/settings_open", methods=["POST"])
def claude_settings_open():
    """资源管理器定位打开 ~/.claude/settings.json（explorer /select 亮选文件）。"""
    p = _settings_path()
    try:
        subprocess_open_select(p)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "err": str(e)}), 500


def subprocess_open_select(path):
    import subprocess
    subprocess.Popen(["explorer.exe", "/select,", path])


@claude_default_bp.route("/api/claude/provision", methods=["POST"])
def claude_provision():
    """手动触发铺设（设置界面「恢复默认配置」用）。body: {force_statusline?}"""
    data = request.get_json(force=True, silent=True) or {}
    ok, notes = provision_defaults(force_statusline=bool(data.get("force_statusline")))
    return jsonify({"ok": ok, "notes": notes})
