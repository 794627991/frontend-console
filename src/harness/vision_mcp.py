# -*- coding: utf-8 -*-
"""识图 MCP server（harness 会话内，stdio）——本地兜底通道 analyze_image。

架构（v2.28.5 双通道定案）：识图主通道是 BigModel 网关在服务端注入的
mcp__4_5v_mcp__analyze_image（同名本地工具会被网关遮蔽成影子——实测 log
零记录、零 tool_use）；但它依赖模型逐字复制长签名 CDN 链接，抄坏/截断/
过期即 400/1210，且服务端黑盒不可观测不可配置。

本文件是兜底通道：注册为名为 vision 的 MCP server，工具全名
mcp__vision__analyze_image——独立名字不被网关遮蔽，主通道失败后模型
按引导词兜底阶梯改调它，imageSource 直接传图片本地绝对路径（本工具
直接读盘，不依赖链接，从结构上绕开抄 URL 这一失败类）。每次调用落
vision_mcp.log 诊断日志。

链路：模型传图片（本地路径 / http(s) 链接 / data: URL 均可）→ 本进程
取图转 base64 → 调 Anthropic 兼容 /v1/messages，模型按识图配置解析
（v3.5.19：面板直选多模态模型，端点映射已退役；[1M] 后缀自动降级
裸名）→ 结论作为工具返回值交回主会话。

端点与密钥解析顺序：env（HARNESS_VISION_BASE_URL/HARNESS_VISION_KEY）→
~/.claude/settings.json 的 env.ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN
（与主会话同源，代理挂着就走代理）→ 兜底智谱直连。主端点连不上自动改走
直连重试，识图不因代理缺席而断。
"""
import base64
import json
import os
import sys
import time
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
# v2.28.8 恢复默认 glm-5.3-flash（用户定调）：此前会话 AI 误把 [1M] 变体的
# 1211 当成 flash 不存在（实为窗口后缀不被网关认，v2.28.6 裸名优先已修）。
# flash 在 bigmodel 一直存在且可用；偶发空回复由 v2.28.7 同模型重试兜住。
# 若嫌 flash 不稳，实测 glm-4.5v 更稳（识图配置/端点映射可覆盖，不必改这里）。
DEFAULT_MODEL = "glm-5.3-flash"

# 诊断日志（v2.28.4）：无头进程静默失败难排查（用户实锤两次 HTTP 400 无从
# 定位入参）——每次调用记 imageSource/端点/模型/结果/耗时，超 512K 截半
LOG_FILE = os.path.join(os.path.expanduser("~"), ".serialconsole_pro",
                        "vision_mcp.log")


def _log(msg):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
        if os.path.getsize(LOG_FILE) > 512 * 1024:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                tail = f.read()[256 * 1024:]
            tmp = LOG_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(tail)
            os.replace(tmp, LOG_FILE)
    except Exception:
        pass


def _src_brief(s):
    """imageSource 日志形态：掐头去尾留中间签名段，可判截断不泄全链。"""
    s = str(s or "")
    return (s[:60] + " …[" + str(len(s)) + " chars]… " + s[-40:]) if len(s) > 120 else s

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


# v3.5.19：normalize_model_map（端点映射归一化）随 model_map 退役删除——
# 识图模型由用户在面板直接选（resolve_model: env > 配置 model > 默认）


def resolve_model(base_url, cfg=None):
    """解析识图模型（v3.5.19 用户拍板「去除端点映射，完全由用户选择」）：
    env 覆盖 → 配置 model（识图面板主选择框，用户直接选多模态模型）→
    默认。端点映射（model_map）已退役——多方案场景在面板重选即可。"""
    env = (os.environ.get("HARNESS_VISION_MODEL") or "").strip()
    if env:
        return env
    cfg = cfg if cfg is not None else load_vision_cfg()
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
    """候选 (base_url, key) 列表：主端点在前，智谱直连兜底在后。
    v3.5.86 解析链扩容：env > 识图配置节（base_url/api_key，内网/自建
    网关专用——设置面板「识图配置」可填）> ~/.claude/settings.json 同源
    > 智谱直连兜底。内网机器此前落不到 settings.json 就恒为智谱兜底
    =连接拒绝（用户实锤 lanzi 内网机识图必炸）。"""
    cfg = load_vision_cfg()
    c_base = str(cfg.get("base_url") or "").strip()
    c_key = str(cfg.get("api_key") or "").strip()
    s_base, s_key = _claude_env()
    primary_base = BASE_OVERRIDE or c_base or s_base or DIRECT_FALLBACK
    key = KEY_OVERRIDE or c_key or s_key
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
    """API 请求模型名变体（裸名优先，v2.28.6）：[1M] 类窗口后缀是 CLI/
    settings 层的上下文窗口选择器，网关 /v1/messages 不认——实测带后缀
    400、claude CLI 自己也报 unrecognized_model 后改发别名。识图请求上下文
    极小、窗口无意义，一律先发去后缀的裸名（配置带不带 [1M] 都正常）；
    原始带后缀形式保留为次选变体，兜需要精确名的 exotic 网关。"""
    if "[" in m and m.endswith("]"):
        base = m[:m.rindex("[")].strip()
        if base and base != m:
            return [base, m]
    return [m]


def _model_name_err(info):
    """错误是否为「模型名不存在/非法」类。对变体重试：这类换名字可能救；
    对最终报错：是噪音——v2.28.7 实测教训：[1M] 变体的 1211 把真因
    （flash 偶发空回复）遮住了。"""
    s = info or ""
    lo = s.lower()
    return ("模型不存在" in s) or ("1211" in s) or (
        "model" in lo and ("not exist" in lo or "unknown" in lo
                           or "unrecognized" in lo))


def _call_vision(b64, media_type, prompt):
    """调 Anthropic 兼容 /v1/messages 做识图。v2.28.7 韧性策略（按实测
    失败模式设计）：
    - 模型裸名优先（[1M] 后缀 API 不认）；后缀变体仅在「模型名错误」时
      才值得试，其余失败换变体纯属浪费还制造报错噪音；
    - 200 空正文是网关对部分模型的偶发行为（实测 flash 时空时有不空，
    同图同参直连复测即正常）——同模型补发一次再降级，不当场判死；
    - 主端点连不上换直连兜底；模型按实际端点解析（model_map 多方案）；
    - 最终报错优先非模型名错误，不让变体噪音遮真因。"""
    cfg = load_vision_cfg()
    sys_prompt = resolve_prompt(cfg)
    last_err = None
    real_err = None        # 第一个非模型名错误（最终报错的优先来源）
    ep_errs = []           # v3.5.86：按端点聚合错误——内网上多端点全连不上时，
                           # 旧实现 last_err 逐次覆盖，报错只剩最后一个端点
                           #（用户误以为「端点写死了」），真因（主端点失败）被遮
    for base, key in _endpoints():
        next_variant = True
        for model in _model_variants(resolve_model(base, cfg)):
            if not next_variant:
                break
            for attempt in (0, 1):        # 第 2 发只留给「空正文」重试
                t0 = time.time()
                kind, info = _post_vision(base, key, model, sys_prompt,
                                          b64, media_type, prompt)
                _log("api %s model=%s -> %s (%.1fs) %s"
                     % (base, model, kind, time.time() - t0,
                        info[:120] if kind != "ok" else ""))
                if kind == "ok":
                    return _result(info)
                last_err = info
                if real_err is None and not _model_name_err(info):
                    real_err = info
                if kind == "conn":
                    next_variant = False   # 端点不可达，换模型名没意义
                    break
                if kind == "empty" and attempt == 0:
                    time.sleep(1.0)
                    continue               # 网关偶发空文——同模型补一发
                # hard / 空文二连：只有模型名问题才值得试下一个变体
                next_variant = _model_name_err(info)
                break
        ep_errs.append("%s → %s" % (base, last_err or "未知错误"))
    if len(ep_errs) > 1:
        # 多端点都试过：逐个列出（端点→错误），一眼看出主端点与兜底各自死因
        return _result("识图请求失败（试了 %d 个端点）：%s"
                       % (len(ep_errs), "；".join(ep_errs)), is_error=True)
    final = last_err
    if _model_name_err(final or "") and real_err:
        final = real_err                   # 1211 噪音不遮真因
    return _result("识图请求失败：%s" % (final or "无可用端点"), is_error=True)


def _post_vision(base, key, model, sys_prompt, b64, media_type, prompt):
    """单次识图请求。返回 ("ok", text) / ("empty", err)（200 但无文本——
    网关偶发，值得同模型重试）/ ("hard", err)（服务端明确拒绝）/
    ("conn", err)（连接层失败，可换端点）。"""
    body = json.dumps({
        "model": model,
        # v2.28.9：2048 会被网关的 thinking 全额吃掉（实测 stop=max_tokens、
        # 块=[thinking]、正文为零——经代理的 flash 尤其饿）→ 8192 给正文留足
        "max_tokens": 8192,
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
        blocks = ",".join(str(b.get("type")) for b in (d.get("content") or [])
                          if isinstance(b, dict)) or "无 content"
        return "empty", ("端点 %s（%s）返回 200 但正文无文本（stop=%s，块=[%s]）"
                         "——网关偶发空回复" % (base, model,
                                                 d.get("stop_reason"), blocks))
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
        return _result("imageSource 必填（图片的本地路径 / http(s) 链接 / data: URL）",
                       is_error=True)
    if not prompt:
        return _result("prompt 必填（想从图里知道什么，要求结论先行）", is_error=True)
    t0 = time.time()
    _log("call src=%s prompt=%r" % (_src_brief(source), prompt[:60]))
    data, mt = _load_image(source)
    if data is None:
        _log("load FAIL (%.1fs): %s" % (time.time() - t0, mt))
        return _result(mt, is_error=True)   # _load_image 失败时 mt 装的是错误文案
    r = _call_vision(base64.b64encode(data).decode("ascii"), mt, prompt)
    _log("done (%.1fs) err=%s" % (time.time() - t0,
                                  bool(r.get("isError"))))
    return r


_TOOLS = [{
    "name": "analyze_image",
    "description": (
        "本地兜底识图工具——主通道 mcp__4_5v_mcp__analyze_image 报错"
        "（1210/400/超时）后才使用本工具。\n"
        "imageSource 首选图片的本地绝对路径（用户附件消息里就有，本工具直接"
        "读盘，不依赖 CDN 链接）；也支持 http(s) 直链与 data: URL。\n"
        "prompt 写清楚想从图里知道什么；返回结论先行、位置带坐标参考。"
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
                "serverInfo": {"name": "vision", "version": "1.0.0"}}})
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
