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
import re
import shutil
import threading
import urllib.error
import urllib.request

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
    # 原子写（tmp+replace）：裸 open("w") 与后台代理联动的字段级写并发时，
    # 会留半截 JSON / 交错覆盖（用户定调：任何情况不能破坏 settings.json）
    p = _settings_path()
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


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
        # v2.25：完整 token 一并返回——前端「眼睛显示」与「按 base_url+token
        # 获取模型列表」都要用。本机单用户工具，settings.json 本就在本机明文。
        "token": token,
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
                # _NAME 是显示名：剥掉 [1M] 窗口后缀。MODEL 键带 [1M] 是
                # Claude Code 自己的 1M 上下文开关（CLI 发请求前剥掉，网关
                # 不认后缀），显示名带后缀纯属噪音，还会误导「模型不认」排查。
                env[hit[2]] = re.sub(r"\s*\[1m\]\s*$", "", val, flags=re.I)
    for field, key in (("ctx_window", "CLAUDE_CODE_AUTO_COMPACT_WINDOW"),
                       ("max_ctx", "CLAUDE_CODE_MAX_CONTEXT_TOKENS"),
                       ("compact_pct", "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE")):
        v = (data.get(field) or "").strip()
        if v:
            env[key] = v
    _write_settings(cur)
    return jsonify({"ok": True})


@claude_default_bp.route("/api/claude/models_probe", methods=["POST"])
def claude_models_probe():
    """按 base_url + token 探测网关可用模型列表（设置页「🔍 获取模型」）。
    GET {base}/v1/models——OpenAI 兼容与 Anthropic 兼容网关返回格式一致
    （{"data":[{"id":…}]}），鉴权头两种都试（Bearer / x-api-key）。
    base_url 末段形态各异（…/anthropic、…/v3、…/v1），无 /v数字 结尾时
    先试补 /v1，再试原样拼接。body: {base_url, token}"""
    data = request.get_json(force=True, silent=True) or {}
    base = (data.get("base_url") or "").strip().rstrip("/")
    token = (data.get("token") or "").strip()
    if not base or not token:
        return jsonify({"ok": False, "err": "需要 BASE_URL 和 Token 都已填写"})
    cands = [] if re.search(r"/v\d+$", base) else [base + "/v1"]
    cands += [base]
    auths = [{"Authorization": "Bearer " + token},                      # OpenAI 兼容
             {"x-api-key": token, "anthropic-version": "2023-06-01"}]   # Anthropic
    last_err = ""
    for stem in cands:
        url = stem + "/models"
        for h in auths:
            try:
                req = urllib.request.Request(url, headers=h)
                with urllib.request.urlopen(req, timeout=8) as r:
                    j = json.loads(r.read().decode("utf-8", "replace") or "{}")
                items = j.get("data") if isinstance(j.get("data"), list) else j.get("models")
                ids = []
                for m in items or []:
                    if isinstance(m, dict):
                        mid = str(m.get("id") or m.get("name") or "").strip()
                        if mid:
                            ids.append(mid)
                    elif isinstance(m, str) and m.strip():
                        ids.append(m.strip())
                if ids:
                    return jsonify({"ok": True, "models": ids, "url": url})
                last_err = "响应里没有模型列表 @ " + url
            except urllib.error.HTTPError as e:
                last_err = "HTTP %s @ %s" % (e.code, url)
            except Exception as e:
                last_err = "%s @ %s" % (e, url)
    return jsonify({"ok": False, "err": last_err or "探测失败"})


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
                    "legacy": not bool(p.get("settings")),
                    "token_masked": _mask_token(env.get("ANTHROPIC_AUTH_TOKEN", "")),
                    "base_url": env.get("ANTHROPIC_BASE_URL", "")})
    switching = False
    try:
        from src import proxy as _proxy
        switching = _proxy.profile_switch_in_flight()
    except Exception:
        pass
    return jsonify({"ok": True, "profiles": out, "active": d.get("active", ""),
                    "switching": switching,   # 切换未稳定：前端禁「应用」按钮
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
    _last_applied_profile["name"] = None   # 覆盖保存后内容已变，清幂等短路
    return jsonify({"ok": True})


# 上次成功 apply 的方案名（进程内幂等短路标记：连点同方案直接返回，
# 不重写 settings/profiles、不起联动 worker——用户实锤连点 7 次排队卡顿）。
# 「存当前为方案」覆盖同名后必须清（内容已变，不能跳过真正的切换）
_last_applied_profile = {"name": None}


@claude_default_bp.route("/api/claude/profiles/apply", methods=["POST"])
def claude_profiles_apply():
    """一键切换：方案整份写回 settings.json（v2.22 快照制）。
    旧格式方案（v2.21 只存 env 两键）退回合并模式。
    对已运行的 claude 进程不生效——env 是启动时注入的，新会话起效。body: {name}

    v2.27：代理在跑时切方案 → 同步重指代理上游到方案网关（用户实锤 405：
    快照制会把代理运行期存的 127.0.0.1 入口整份写回，且重试代理上游
    仍指旧网关——请求打到旧网关带新 token，405 Not Allowed）。"""
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    d = _read_profiles()
    prof = next((p for p in d["profiles"] if p.get("name") == name), None)
    if not prof:
        return jsonify({"ok": False, "err": "方案不存在"}), 404
    if _last_applied_profile["name"] == name:
        return jsonify({"ok": True, "msg": "已是当前方案"})   # 幂等短路
    from src import proxy as _proxy
    # 未稳定保护（用户定调）：上一方案的后台联动（上游热切/base_url 回代理
    # 入口/headroom 重拉）没收尾前，禁止切下一方案——快速连点的竞态窗口
    # 整个关掉（曾出「新 token+旧上游」错配 → Claude 打错网关卡死）
    if _proxy.profile_switch_in_flight():
        return jsonify({"ok": False,
                        "err": "上一个方案仍在切换中（后台同步代理上游），"
                               "请稍候几秒再切"}), 409
    # 全临界区上锁（v2.27.2 竞态收口，用户定调三条铁律：最后一次切换为准 /
    # 不破坏 settings.json / 最终代理生效且上游=最后方案）：连点切方案时
    # 各请求的「读-净化-整份写回-写 profiles」串行化，与后台 re_point
    # worker（同锁）互斥——杜绝整份写回与字段级改写交错覆盖。
    # 同步段全是毫秒级文件操作，锁不伤「立即返回」体感。
    with _proxy.switch_lock():
        _sanitize_prev_profile(d)   # 上一方案快照若存了代理入口 → 换成真实网关
        # 整份写回前捕获「链路是否应处代理模式」——写完 settings 再读就只剩
        # 新方案直连值（v2.27.1 时序坑）。连点连切时上一刀已把 base_url 写成
        # 直连中间态，纯读 settings 会误判直连 → 用 proxy_intent_active
        # （含 _autoswitched 意图）兜住：最后一刀必须把 base_url 拉回代理入口
        try:
            was_proxy = _proxy.proxy_intent_active()
        except Exception:
            was_proxy = False
        snap = prof.get("settings")
        if isinstance(snap, dict) and snap:
            # 快照净化：代理运行期保存的方案，base_url 可能是 127.0.0.1 自家
            # 入口——照写回等于让 Claude 连「指旧网关的代理」，切网关必 405。
            snap = json.loads(json.dumps(snap))   # 深拷贝——不改动存的方案本体
            env = snap.get("env")
            prof_base = env.get("ANTHROPIC_BASE_URL") if isinstance(env, dict) else None
            if prof_base and str(prof_base).startswith(
                    ("http://127.0.0.1:37349", "http://127.0.0.1:8787")):
                env["ANTHROPIC_BASE_URL"] = DEFAULT_BASE_URL   # 脏快照回默认网关
                prof_base = DEFAULT_BASE_URL
            _write_settings(snap)                     # v2.22：整份替换
        else:
            # 旧格式：只并入 env 两键。模型映射等不会跟着切（旧方案里没存过），
            # 必须显式警告——静默回退让用户以为切换完整（A↔B 切来切去模型全乱）
            cur = _read_settings()
            env = cur.setdefault("env", {})
            if not isinstance(env, dict):
                env = cur["env"] = {}
            for k, v in (prof.get("env") or {}).items():
                if v:
                    env[k] = v
            prof_base = env.get("ANTHROPIC_BASE_URL")
            _write_settings(cur)
            d["active"] = name
            _write_profiles(d)
            _sync_proxy_upstream(prof_base, was_proxy)
            return jsonify({"ok": True, "warning":
                            "方案「%s」是旧格式（只存了 Token/网关），模型映射没有切换。"
                            "请在该网关下配好模型映射后重新「存当前为方案」升级为完整快照。" % name})
        d["active"] = name
        _write_profiles(d)
        _sync_proxy_upstream(prof_base, was_proxy)
        # v2.27.15：切方案后活 harness 进程仍揣旧 token/模型映射（env 是
        # 启动时注入的）——代理上游已热切到新网关，旧 token 打新网关必
        # 401/405。后台静默重启小助手会话（kill + --resume 续上下文），
        # 新进程读新 settings；GUI 会话不打扰（其引导词/自愈机制会在
        # 下次发送时按需换新进程）。超窗续命见 send_message 拦截分支。
        threading.Thread(target=_renew_bot_after_switch, daemon=True).start()
    _last_applied_profile["name"] = name   # 成功收尾才记（失败下次重做全量）
    return jsonify({"ok": True})


def _renew_bot_after_switch():
    """切 API 方案收尾：小助手 harness 进程 kill+resume 换新 token。
    任何一步失败静默——续不上的会话在下次发送时由超窗拒发/自愈兜底。"""
    try:
        from src import hiklink_bot as hb
        ctl = hb._controller
        s = ctl._session() if ctl else None
        if s and s.alive and not s.busy:
            s.kill_proc(quiet=True)
            s.revive_if_dead()
    except Exception:
        pass


def _sanitize_prev_profile(d):
    """切走前净化「上一个激活方案」的快照（v2.27）：方案若在代理运行期
    保存，快照里的 base_url 是 127.0.0.1 自家代理入口——照原样留着，
    下次切回它就等于整份写回代理地址（上游还指别人网关 → 405）。
    用 proxy 的直连记忆（切代理前的真源）替换之。"""
    active = d.get("active")
    if not active:
        return
    try:
        from src import proxy as _proxy
        real = _proxy.saved_direct_url()
    except Exception:
        return
    if not real or str(real).startswith(
            ("http://127.0.0.1:37349", "http://127.0.0.1:8787")):
        return   # 无记忆或记忆本身是代理地址：无从净化，不动方案
    for p in d.get("profiles") or []:
        if p.get("name") != active:
            continue
        snap = p.get("settings")
        env = (snap or {}).get("env")
        if isinstance(env, dict) and str(
                env.get("ANTHROPIC_BASE_URL", "")).startswith(
                ("http://127.0.0.1:37349", "http://127.0.0.1:8787")):
            env["ANTHROPIC_BASE_URL"] = real
            _write_profiles(d)
        break


def _sync_proxy_upstream(prof_base, was_proxy=None):
    """切方案后联动代理（后台执行，接口立即返回——用户定调体感零等待）：
    重指上游 + base_url 切回代理入口，逻辑在 proxy.queue_re_point。
    was_proxy=写回 settings 前捕获的「是否代理模式」，见 claude_profiles_apply。"""
    if not prof_base or str(prof_base).startswith(
            ("http://127.0.0.1:37349", "http://127.0.0.1:8787")):
        return   # 旧格式方案没存 base_url 或已净化：拿不到新网关，不联动
    try:
        from src import proxy as _proxy
        _proxy.queue_re_point(str(prof_base), was_proxy=was_proxy)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("切方案联动代理失败: %s", e)


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
