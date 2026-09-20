# -*- coding: utf-8 -*-
"""识图 MCP server（harness 会话内，stdio）——本地直通版 analyze_image。

背景（2026-09-20 诊断定案）：主会话模型 glm-5.3 是纯文本模型（ZCode provider
配置 modalities=["text"]、harness 双段探测也判 false），识图靠 mcp 通道。但
`mcp__4_5v_mcp__analyze_image` 是 BigModel 网关在服务端注入的能力，claude CLI
这条链路上拿不到（用户级/项目级/--mcp-config 三处都没有该 server，zcode.cjs
bundle 里连字符串都搜不到）——模型按引导词去调，每次都死在执行层。

本文件就是补上这个洞：注册成名为 4_5v_mcp 的 MCP server，暴露 analyze_image
工具，全名恰好是 mcp__4_5v_mcp__analyze_image——harness 引导词一字不用改。

链路：模型传图片 URL（识图 CDN 链接 / 任意 http(s) 链接 / data: URL / 本地
路径均可）→ 本进程下载转 base64 → 调 Anthropic 兼容 /v1/messages，模型用
glm-5.3-flash（多模态，modalities=["text","image"]，探测缓存 inline=true）
→ 结论作为工具返回值交回主会话。不依赖网关注入，直接通。

端点与密钥解析顺序：env（HARNESS_VISION_BASE_URL/HARNESS_VISION_KEY，留空
禁用该项）→ ~/.claude/settings.json 的 env.ANTHROPIC_BASE_URL /
ANTHROPIC_AUTH_TOKEN（与主会话同源，代理挂着就走代理）→ 兜底智谱直连。
主端点连不上（代理没跑）时自动改走直连重试一次，识图不因代理缺席而断。
"""
import base64
import json
import os
import sys
import urllib.error
import urllib.request

# 可调项（env 覆盖，最高优先级；常规配置走 ~/.serialconsole_pro/config.json
# 的 harness_vision 节——设置面板「识图配置」写的正是那里）
BASE_OVERRIDE = (os.environ.get("HARNESS_VISION_BASE_URL") or "").strip()
KEY_OVERRIDE = (os.environ.get("HARNESS_VISION_KEY") or "").strip()
DIRECT_FALLBACK = "https://open.bigmodel.cn/api/anthropic"

# 识图配置文件（与主程序同源：HOME_DIR/config.json 的 harness_vision 节）
CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".serialconsole_pro",
                           "config.json")
_VISION_CFG_KEY = "harness_vision"
DEFAULT_MODEL = "glm-5.3-flash"

_DL_TIMEOUT = 25          # 图片下载超时（秒）
_DL_MAX = 15 * 1024 * 1024  # 图片大小上限（15MB，超限直接报错不硬扛）
_API_TIMEOUT = 120        # 视觉模型响应超时（秒）
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# 给视觉模型 system：与会话版识图提示词同一口径（结论先行/坐标可复核/客观
# 不猜）——harness 引导词向主会话承诺的返回风格由这里兑现
_VISION_SYSTEM = (
    "你是识图服务。根据图片回答用户问题，要求：\n"
    "- 结论先行：第一句直接给答案，再给支撑细节。\n"
    "- 客观描述优先于推测；看不清、分辨率不足、图中没有该信息就直说，不要猜。\n"
    "- 提到位置时给可复核的坐标或区域描述（如「左上角状态栏第 2 行」）。\n"
    "- 言简意赅，不废话。"
)
MCP_DEFAULT_SYSTEM = _VISION_SYSTEM


def _send(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _result(text, is_error=False):
    r = {"content": [{"type": "text", "text": text}]}
    if is_error:
        r["isError"] = True
    return r


def _claude_env():
    """读 ~/.claude/settings.json 的 env（ANTHROPIC_BASE_URL / AUTH_TOKEN）。"""
    try:
        p = os.path.join(os.path.expanduser("~"), ".claude", "settings.json")
        with open(p, "r", encoding="utf-8") as f:
            env = (json.load(f).get("env") or {})
        return (env.get("ANTHROPIC_BASE_URL") or "").strip(), \
               (env.get("ANTHROPIC_AUTH_TOKEN") or "").strip()
    except Exception:
        return "", ""


def load_vision_cfg():
    """读识图配置（config.json 的 harness_vision 节）。每次调用时读——
    设置面板改完即刻生效，无需重启会话/MCP 进程。"""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        v = d.get(_VISION_CFG_KEY)
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def normalize_model_map(raw):
    """归一化端点模型映射：接受 {关键字: 模型} 或 ["关键字=模型"] 行。
    关键字小写（匹配时对 base_url 做 contains，大小写不敏感）。"""
    out = {}
    if isinstance(raw, dict):
        items = raw.items()
    elif isinstance(raw, list):
        items = (tuple(str(x).split("=", 1)) for x in raw if "=" in str(x))
    else:
        return out
    for k, v in items:
        k = str(k).strip().lower()
        v = str(v).strip()
        if k and v:
            out[k] = v
    return out


def resolve_model(base_url, cfg=None):
    """按端点解析识图模型：env 覆盖 → model_map 最长关键字命中 → 配置
    model → 默认。多方案适配的关键——lanz 端点配 Lanz-Medium-V、
    bigmodel 端点配 glm-5.3-flash，切方案自动跟着走。"""
    env = (os.environ.get("HARNESS_VISION_MODEL") or "").strip()
    if env:
        return env
    cfg = cfg if cfg is not None else load_vision_cfg()
    url = (base_url or "").lower()
    best_k, best_m = "", None
    for k, m in normalize_model_map(cfg.get("model_map")).items():
        if k in url and len(k) > len(best_k):
            best_k, best_m = k, m
    if best_m:
        return best_m
    m = str(cfg.get("model") or "").strip()
    return m or DEFAULT_MODEL


def resolve_prompt(cfg=None):
    """识图 system 提示词：env 覆盖 → 配置 mcp_prompt → 内置默认。
    注意不读旧会话时代的 prompt 键（内含 SendMessage 回传指令，对 MCP
    上下文是错误指令）。"""
    env = (os.environ.get("HARNESS_VISION_PROMPT") or "").strip()
    if env:
        return env
    cfg = cfg if cfg is not None else load_vision_cfg()
    return str(cfg.get("mcp_prompt") or "").strip() or MCP_DEFAULT_SYSTEM


def _endpoints():
    """候选 (base_url, key) 列表：主端点在前，智谱直连兜底在后。"""
    s_base, s_key = _claude_env()
    primary_base = BASE_OVERRIDE or s_base or DIRECT_FALLBACK
    key = KEY_OVERRIDE or s_key
    eps = [(primary_base, key)]
    if primary_base.rstrip("/") != DIRECT_FALLBACK:
        eps.append((DIRECT_FALLBACK, key))
    return eps


def _sniff_media_type(data):
    """Content-Type 缺失/不可信时按魔数判图片类型。"""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:2] == b"BM":
        return "image/bmp"       # 调用方明确拒绝（API 不收 BMP）
    return None


def _load_image(source):
    """把 imageSource 变成 (bytes, media_type)。支持 http(s)/data:/本地路径。"""
    source = (source or "").strip()
    if not source:
        return None, "imageSource 为空"
    # data: URL —— 模型偶尔会直接塞（引导词允许它从 Read 返回里取链接）
    if source.startswith("data:"):
        try:
            head, b64 = source.split(",", 1)
            mt = head[5:].split(";")[0] or "image/png"
            # v2.28.3：非 image/* 的 data: URL 提前拒绝——放过去只会在
            # API 侧得到一个费解的 400（审计项）
            if not mt.lower().startswith("image/"):
                return None, "data: URL 媒体类型不是图片：%s" % mt
            return base64.b64decode(b64), mt
        except Exception:
            return None, "data: URL 解析失败（base64 段不完整）"
    # 本地路径 —— Read 若给了路径而非链接，模型可能原样传过来，顺手接住
    if not source.lower().startswith(("http://", "https://")):
        if os.path.isfile(source):
            with open(source, "rb") as f:
                data = f.read(_DL_MAX + 1)
            if len(data) > _DL_MAX:
                return None, "图片超过 15MB 上限"
            # v2.28.3：魔数校验本地文件——非图片明确拒绝（原实现兜
            # "image/png" 把任意文件送进 API，只换来费解的 400）；BMP 同拒
            mt = _sniff_media_type(data)
            if mt == "image/bmp":
                return None, "暂不支持 BMP 图片（请用 PNG/JPEG/GIF/WebP）"
            if not mt:
                return None, "该文件不是图片（魔数校验未通过）"
            return data, mt
        return None, "imageSource 既不是 http(s) 链接也不是存在的本地文件：%s" % source[:200]
    # http(s)：下载。带 UA——部分 CDN（含识图 CDN）对无 UA 请求回 403/非图片内容
    try:
        req = urllib.request.Request(source, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=_DL_TIMEOUT) as r:
            ct = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            data = r.read(_DL_MAX + 1)
    except urllib.error.HTTPError as e:
        return None, "图片链接返回 HTTP %d（链接可能已过期或签名失效）" % e.code
    except Exception as e:
        return None, "图片下载失败：%s" % e
    if len(data) > _DL_MAX:
        return None, "图片超过 15MB 上限"
    # 内容不是图片（CDN 401 的 XML 错误页就是这形态）→ 明确告知，别让模型
    # 误以为服务故障瞎重试（旧 1210 的本地版语义）。BMP 同拒——视觉 API
    # 只收 jpeg/png/gif/webp，放过去只是换个地方 400（v2.28.3 审计项）
    mt = ct if ct.startswith("image/") else _sniff_media_type(data)
    if mt == "image/bmp":
        return None, "暂不支持 BMP 图片（请用 PNG/JPEG/GIF/WebP）"
    if not mt:
        return None, ("下载到的不是图片（Content-Type: %s），"
                      "链接可能已过期/签名失效/被截断" % (ct or "未知"))
    return data, mt


def _model_variants(m):
    """模型名变体：带 [窗口后缀]（如 glm-5.3-flash[1M]——lanz 网关认，
    bigmodel 直连不认）时补一个去后缀的裸名，400 时降级重试用。"""
    if "[" in m and m.endswith("]"):
        base = m[:m.rindex("[")].strip()
        if base and base != m:
            return [m, base]
    return [m]


def _call_vision(b64, media_type, prompt):
    """调 Anthropic 兼容 /v1/messages 做识图。主端点连不上自动走直连兜底；
    模型按「本次实际尝试的端点」解析（model_map 命中 lanz 配 Lanz 模型、
    回落 bigmodel 直连时换回 glm 系）——多方案下模型永远与端点匹配。
    [1M] 类窗口后缀在部分端点 400 → 自动降级裸名重试一次。"""
    cfg = load_vision_cfg()
    sys_prompt = resolve_prompt(cfg)
    last_err = "无可用端点"
    for base, key in _endpoints():
        for model in _model_variants(resolve_model(base, cfg)):
            kind, info = _post_vision(base, key, model, sys_prompt,
                                      b64, media_type, prompt)
            if kind == "ok":
                return _result(info)
            last_err = info
            if kind == "conn":
                break          # 端点不可达——换端点（模型变体没意义）
            # hard（4xx/5xx/无文本）：带 [后缀] 的模型还有裸名变体可试，
            # 变体循环自然降级；变体耗尽换端点
    return _result("识图请求失败：%s" % last_err, is_error=True)


def _post_vision(base, key, model, sys_prompt, b64, media_type, prompt):
    """单次识图请求。返回 ("ok", text) / ("hard", err)（服务端拒绝或无文本）
    / ("conn", err)（连接层失败，可换端点）。"""
    body = json.dumps({
        "model": model,
        "max_tokens": 2048,
        "system": sys_prompt,
        "messages": [{"role": "user", "content": [
            {"type": "image",
             "source": {"type": "base64", "media_type": media_type,
                        "data": b64}},
            {"type": "text", "text": prompt},
        ]}],
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        base.rstrip("/") + "/v1/messages", data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "User-Agent": _UA,
                 "anthropic-version": "2023-06-01",
                 # 两种鉴权头都带：claude 系网关认 x-api-key，
                 # anthropic 兼容层多认 Bearer，冗余无害
                 "x-api-key": key, "authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(req, timeout=_API_TIMEOUT) as r:
            d = json.loads(r.read().decode("utf-8", "replace") or "{}")
        texts = [b.get("text", "") for b in (d.get("content") or [])
                 if isinstance(b, dict) and b.get("type") == "text"]
        if texts:
            return "ok", "\n".join(t for t in texts if t)
        return "hard", ("端点 %s（%s）成功但无文本，响应：%s"
                        % (base, model, json.dumps(d, ensure_ascii=False)[:200]))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        # 4xx/5xx 是服务端明确拒绝——可能是 [1M] 类窗口后缀不被端点认
        # （调用方会降级裸名变体重试），也可能是鉴权/模型不存在等换端点
        # 也解不了的问题，错误详情如实带回
        return "hard", "端点 %s（%s）返回 HTTP %d：%s" % (base, model, e.code, detail)
    except Exception as e:
        # 连接层失败（代理没跑/断网）→ 可换端点
        return "conn", "端点 %s 连接失败：%s" % (base, e)


def _analyze(args):
    source = str(args.get("imageSource") or "").strip()
    prompt = str(args.get("prompt") or "").strip()
    if not source:
        return _result("imageSource 必填（图片的 http(s) 链接 / data: URL / 本地路径）",
                       is_error=True)
    if not prompt:
        return _result("prompt 必填（想从图里知道什么，要求结论先行）", is_error=True)
    data, mt = _load_image(source)
    if data is None:
        return _result(mt, is_error=True)   # _load_image 失败时 mt 装的是错误文案
    return _call_vision(base64.b64encode(data).decode("ascii"), mt, prompt)


_TOOLS = [{
    "name": "analyze_image",
    "description": (
        "分析一张图片并回答问题（本会话模型看不了图，识图靠本工具）。\n"
        "imageSource 支持：http(s) 图片直链（识图 CDN 链接须原样保留完整 query "
        "签名，一个参数都不能少、不能截断）、data: URL、本地文件路径。\n"
        "prompt 写清楚想从图里知道什么；返回结论先行、位置带坐标参考。\n"
        "链接过期/签名失效时工具会明确报错，此时可让用户重新提供图片。"
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "imageSource": {
                "type": "string",
                "description": "图片来源：http(s) 直链 / data: URL / 本地路径",
            },
            "prompt": {
                "type": "string",
                "description": "想从图里知道的问题，如「图中报错信息是什么」",
            },
        },
        "required": ["imageSource", "prompt"],
    },
}]


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
        sys.stdin.reconfigure(encoding="utf-8")
    except Exception:
        pass
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue
        method = req.get("method")
        req_id = req.get("id")
        if req_id is None:
            continue          # notification（initialized 等），无需应答
        if method == "initialize":
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "4_5v_mcp", "version": "1.0.0"}}})
        elif method == "tools/list":
            _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": _TOOLS}})
        elif method == "tools/call":
            params = req.get("params") or {}
            if params.get("name") != "analyze_image":
                _send({"jsonrpc": "2.0", "id": req_id,
                       "result": _result("未知工具", is_error=True)})
                continue
            try:
                res = _analyze(params.get("arguments") or {})
            except Exception as e:
                res = _result("识图失败：%s" % e, is_error=True)
            _send({"jsonrpc": "2.0", "id": req_id, "result": res})
        else:
            _send({"jsonrpc": "2.0", "id": req_id, "result": {}})


if __name__ == "__main__":
    main()
