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


def provision_defaults(force_statusline=False, reset_statusline=False):
    """安装完成后铺设默认环境（幂等，可重复调）：
    1. statusline.py 复制到 ~/.claude/（已存在跳过，除非 force）
    2. settings.json 补缺的键（已有键不动——铁律4）：
       env 模型映射/上下文窗口、statusLine 指向本机 python+statusline
    3. 默认授权（用户要求：别的用户不该每次手动选接受）：
       - settings.json permissions.defaultMode（auto 已是本机同款）
       - ~/.claude.json onboarding 位 + 全局 bypass 权限确认
    返回 (ok, 铺了什么/告警列表)。
    AUTH_TOKEN 不在铺设范围——留给 API 配置界面（首次打开 claude 前必填）。
    reset_statusline：先删 statusLine 键再按现状重配——修历史写坏
    （exe 机器无 python 时 command 曾被写成工具 exe 自身路径）。
    """
    notes = []
    # 1. statusline.py （首次安装时 ~/.claude 可能还不存在——先建目录再写）
    sl = _statusline_path()
    if force_statusline or not os.path.isfile(sl):
        os.makedirs(os.path.dirname(sl), exist_ok=True)
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
    # 关键：目标机没装 python 时不能兜底 sys_python()——打包 exe 场景下
    # sys.executable 是前端控制台.exe 自己，写进 statusLine 会导致
    # claude 每次拿 exe 当 python 跑 statusline.py → 无输出 → 状态栏消失
    # （baoziyi 机器实测翻车）。找不到真 python 就不配 statusLine
    # （claude 无此键不显示状态栏，无害）。
    sl_cmd = cur.get("statusLine", {})
    if reset_statusline:
        # 强制重配：清掉历史写坏的 command（含把工具 exe 当 python 的）
        if isinstance(sl_cmd, dict) and sl_cmd.get("command"):
            cur.pop("statusLine", None)
            sl_cmd = {}
            changed = True
            notes.append("旧 statusLine 已清除（重配）")
    if not isinstance(sl_cmd, dict) or not sl_cmd.get("command"):
        py = shutil.which("python.exe") or shutil.which("python")
        if py:
            cur["statusLine"] = {
                "type": "command",
                "command": f"{py} {sl.replace(os.sep, '/')}",
            }
            changed = True
            notes.append("statusLine 已配置")
        else:
            notes.append("未找到 python，跳过 statusLine 配置（状态栏不显示，"
                         "不影响使用；装 python 后点「恢复默认配置」即可补上）")
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

# UI 管理的模型映射档位 → env 键（v2.22）。MODEL 与 MODEL_NAME 成对的档位
# 保存时两键同写同值；Flash/子代理只有 MODEL 键。
_MODEL_SLOTS = [
    ("main",    "ANTHROPIC_MODEL",                    None),
    ("opus",    "ANTHROPIC_DEFAULT_OPUS_MODEL",       "ANTHROPIC_DEFAULT_OPUS_MODEL_NAME"),
    ("sonnet",  "ANTHROPIC_DEFAULT_SONNET_MODEL",     "ANTHROPIC_DEFAULT_SONNET_MODEL_NAME"),
    ("haiku",   "ANTHROPIC_DEFAULT_HAIKU_MODEL",      "ANTHROPIC_DEFAULT_HAIKU_MODEL_NAME"),
    ("fable",   "ANTHROPIC_DEFAULT_FABLE_MODEL",      "ANTHROPIC_DEFAULT_FABLE_MODEL_NAME"),
    ("flash",   "ANTHROPIC_DEFAULT_FLASH_MODEL",      "ANTHROPIC_DEFAULT_FLASH_MODEL_NAME"),
    ("subagent", "CLAUDE_CODE_SUBAGENT_MODEL",        None),
]


def _env_models(env):
    """读出各模型档位现值（UI 显示用）。"""
    return {slot: env.get(k, "") for slot, k, _nk in _MODEL_SLOTS}


@claude_default_bp.route("/api/claude/api_config")
def claude_api_config_get():
    """读当前 API 配置：token（打码）、BASE_URL、模型映射、上下文窗口/压缩阈值。"""
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
        "models": _env_models(env),
        "ctx_window": env.get("CLAUDE_CODE_AUTO_COMPACT_WINDOW", ""),
        "max_ctx": env.get("CLAUDE_CODE_MAX_CONTEXT_TOKENS", ""),
        "compact_pct": env.get("CLAUDE_AUTOCOMPACT_PCT_OVERRIDE", ""),
        "settings_path": _settings_path(),
        "statusline_path": _statusline_path(),
    })


@claude_default_bp.route("/api/claude/api_config", methods=["POST"])
def claude_api_config_set():
    """写 API 配置（v2.22：不止 token）。body（全部可选，只写提供的字段）:
    {token?, base_url?, models?:{main,opus,...,subagent}, ctx_window?, max_ctx?, compact_pct?}
    空串 = 该项不改。模型档位写 MODEL 键，成对的同时写 _NAME 键（同值）。"""
    data = request.get_json(force=True, silent=True) or {}
    cur = _read_settings()
    env = cur.setdefault("env", {})
    if not isinstance(env, dict):
        env = cur["env"] = {}

    token = (data.get("token") or "").strip()
    if token:
        env["ANTHROPIC_AUTH_TOKEN"] = token
    base_url = (data.get("base_url") or "").strip()
    if base_url:
        env["ANTHROPIC_BASE_URL"] = base_url      # v2.22：网关可改（智谱/lanzi 多网关）
    models = data.get("models") or {}
    if isinstance(models, dict):
        for slot, val in models.items():
            val = (val or "").strip()
            if not val:
                continue                           # 留空 = 不改
            hit = next((s for s in _MODEL_SLOTS if s[0] == slot), None)
            if not hit:
                continue
            env[hit[1]] = val
            if hit[2]:
                env[hit[2]] = val
    for field, key in (("ctx_window", "CLAUDE_CODE_AUTO_COMPACT_WINDOW"),
                       ("max_ctx", "CLAUDE_CODE_MAX_CONTEXT_TOKENS"),
                       ("compact_pct", "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE")):
        v = (data.get(field) or "").strip()
        if v:
            env[key] = v
    _write_settings(cur)
    return jsonify({"ok": True})


# ---- API 配置方案（多套一键切换，设置界面「配置方案」区）----
# 存 ~/.serialconsole_pro/claude_profiles.json（工具自己的数据目录，与
# settings.json 分离）。v2.22 快照制：每个方案存整份 settings.json——
# 不同网关的 TOKEN/BASE_URL/模型映射/上下文窗口都不同，切换时整份写回。

def _profiles_path():
    d = os.path.join(os.path.expanduser("~"), ".serialconsole_pro")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return os.path.join(d, "claude_profiles.json")


def _read_profiles():
    try:
        with open(_profiles_path(), "r", encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("profiles"), list):
            return d
    except Exception:
        pass
    return {"profiles": [], "active": ""}


def _write_profiles(d):
    p = _profiles_path()
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def _mask_token(t):
    return (t[:8] + "…" + t[-4:]) if len(t) > 16 else ("已设置" if t else "")


@claude_default_bp.route("/api/claude/profiles")
def claude_profiles_get():
    """方案列表 + 当前激活名（打码显示 token）。"""
    d = _read_profiles()
    out = []
    for p in d["profiles"]:
        env = (p.get("settings") or {}).get("env") or p.get("env") or {}   # v2.22 快照 / v2.21 旧格式
        if not isinstance(env, dict):
            env = {}
        out.append({"name": p.get("name", ""),
                    "token_masked": _mask_token(env.get("ANTHROPIC_AUTH_TOKEN", "")),
                    "base_url": env.get("ANTHROPIC_BASE_URL", "")})
    return jsonify({"ok": True, "profiles": out, "active": d.get("active", ""),
                    "settings_path": _settings_path()})


@claude_default_bp.route("/api/claude/profiles/save", methods=["POST"])
def claude_profiles_save():
    """把当前 settings.json 整份存为一个方案（同名覆盖）。
    v2.22 快照制——不同网关不止 TOKEN/BASE_URL 不同，模型映射
    （ANTHROPIC_MODEL / ANTHROPIC_DEFAULT_*_MODEL）也随网关变，
    只切两键会得到「新网关 + 旧模型名」的废配置（用户实测）。body: {name}"""
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "err": "方案名不能为空"}), 400
    prof = {"name": name, "settings": _read_settings()}
    d = _read_profiles()
    for i, p in enumerate(d["profiles"]):
        if p.get("name") == name:
            d["profiles"][i] = prof
            break
    else:
        d["profiles"].append(prof)
    _write_profiles(d)
    return jsonify({"ok": True})


@claude_default_bp.route("/api/claude/profiles/apply", methods=["POST"])
def claude_profiles_apply():
    """一键切换：方案整份写回 settings.json（v2.22 快照制）。
    旧格式方案（v2.21 只存 env 两键）退回合并模式。
    对已运行的 claude 进程不生效——env 是启动时注入的，新会话起效。body: {name}"""
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    d = _read_profiles()
    prof = next((p for p in d["profiles"] if p.get("name") == name), None)
    if not prof:
        return jsonify({"ok": False, "err": "方案不存在"}), 404
    snap = prof.get("settings")
    if isinstance(snap, dict) and snap:
        _write_settings(snap)                     # v2.22：整份替换
    else:
        # 旧格式：只并入 env 两键
        cur = _read_settings()
        env = cur.setdefault("env", {})
        if not isinstance(env, dict):
            env = cur["env"] = {}
        for k, v in (prof.get("env") or {}).items():
            if v:
                env[k] = v
        _write_settings(cur)
    d["active"] = name
    _write_profiles(d)
    return jsonify({"ok": True})


@claude_default_bp.route("/api/claude/profiles/del", methods=["POST"])
def claude_profiles_del():
    """删除方案（不动 settings.json）。body: {name}"""
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    d = _read_profiles()
    d["profiles"] = [p for p in d["profiles"] if p.get("name") != name]
    if d.get("active") == name:
        d["active"] = ""
    _write_profiles(d)
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
    """手动触发铺设（设置界面「恢复默认配置」用）。
    body: {force_statusline?, reset_statusline?}"""
    data = request.get_json(force=True, silent=True) or {}
    ok, notes = provision_defaults(
        force_statusline=bool(data.get("force_statusline")),
        reset_statusline=bool(data.get("reset_statusline")))
    return jsonify({"ok": ok, "notes": notes})
