# -*- coding: utf-8 -*-
"""升级分发门户（发布机专用，v2.1.0→v2.2.0）：Web 界面 + 下载 + 自动更新源。

方案 B（用户定调）：无共享盘/无制品库，发布机起 HTTP 服务，同事浏览器访问
http://<本机内网IP>:8765/ 看版本/下整包，同事的工具也从同一地址自动热更。

双通道并存：
- 浏览器门户：密码登录（config.update_portal_password，默认 888888——内网
  务实默认，发布者可在工具「设置→关于与升级」改）→ 版本列表 + 整包下载
- 工具自动更新：GET /manifest.json + /<包文件> 不走登录（同事工具没有
  浏览器态；完整性靠 sha1——manifest 指纹在发布端 build 时算死）

工程约束：ThreadingHTTPServer 单文件自持——HTML/CSS/JS 全内嵌，不依赖
项目 web/ 目录（发布机丢了前端资源也能跑）；路径限定 dist/releases；
0.0.0.0 监听，首次启动防火墙弹窗需允许。
"""
import os, sys, json, time, html, re, secrets, threading, socket
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import unquote, quote

PORT = 8765
_MAX_AGE = 60          # manifest 缓存友好：发布后同事 1 分钟内必见新版
_SESSION_TTL = 12 * 3600
_DEFAULT_PWD = "888888"
try:
    from src.version import APP_VERSION as _APP_VER   # 单一源（version.py）
except Exception:
    _APP_VER = "2.3.0"


# ---------------------------------------------------------------------------
# 基础设施
# ---------------------------------------------------------------------------
def _releases_dir():
    """dist/releases 绝对路径（源码跑=项目根/dist/releases；frozen=exe 旁）。
    发布机是源码形态（要跑打包.bat），frozen 分支只是兜底。"""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))   # onedir: exe 所在应用目录
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "dist", "releases")


def _lan_ip():
    """本机内网 IP（UDP connect 让路由选源地址；失败回退 hostname 解析）。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"


def _safe_path(root, name):
    """拼路径并校验没跑出 root（防 ../ 穿越）。"""
    p = os.path.realpath(os.path.join(root, name))
    root = os.path.realpath(root)
    if p == root or not p.startswith(root + os.sep):
        return None
    return p


def _portal_password():
    """门户登录密码（config.update_portal_password，未设=默认）。"""
    try:
        from src.app_state import _load_config
        return str((_load_config().get("update_portal_password") or "").strip()
                   or _DEFAULT_PWD)
    except Exception:
        return _DEFAULT_PWD


def _set_portal_password(pwd):
    from src.app_state import _load_config, _save_config
    cfg = _load_config()
    cfg["update_portal_password"] = (pwd or "").strip()
    _save_config(cfg)


_sessions = {}   # token -> expiry（内存态：服务重启即失效，重新登录，可接受）


def _ver_tuple(v):
    out = []
    for seg in str(v or "").split("."):
        digits = "".join(ch for ch in seg if ch.isdigit())
        out.append(int(digits) if digits else 0)
    while len(out) < 3:
        out.append(0)
    return tuple(out[:3])


def _versions():
    """releases 目录的版本清单（降序）：manifest 定「最新」，历史版全列。"""
    root = _releases_dir()
    items = []
    try:
        names = os.listdir(root)
    except OSError:
        names = []
    latest = ""
    try:
        with open(os.path.join(root, "manifest.json"), encoding="utf-8") as f:
            latest = str(json.load(f).get("version") or "")
    except Exception:
        pass
    notes = {}
    # v2.2.1：每版独立说明文件 notes-v<ver>.md（build.py 发布时随包落盘），
    # manifest 的 notes 只保最新版——历史版的说明也能显示（用户需求）
    for n in names:
        if n.startswith("notes-v") and n.endswith(".md"):
            try:
                with open(os.path.join(root, n), encoding="utf-8") as f:
                    notes[n[7:-3]] = f.read().strip()[:4000]
            except OSError:
                pass
    try:
        with open(os.path.join(root, "manifest.json"), encoding="utf-8") as f:
            m = json.load(f)
        notes[str(m.get("version"))] = notes.get(str(m.get("version"))) \
            or str(m.get("notes") or "")
    except Exception:
        pass
    for n in names:
        # v2.3.0：发布形态 zip（onedir 应用目录打包）；旧 .exe 历史包也列出（可下载）
        # a333R（第4轮 P1）：大小写不敏感——Windows 上 .ZIP/.EXE 同样可下载
        _ln2 = n.lower()
        if not ((_ln2.endswith(".zip") or _ln2.endswith(".exe")) and "-v" in _ln2):
            continue
        # 离线资源包不是应用版本（用户定调「离线包和实际包分开」）：留着会与
        # 整包同版本号并列、按文件名序抢 hero 卡位还错挂整包 sha1——主清单
        # 剔除，_offline_pkg() 单独通道出去各显各的（新名不带版本号，检测串
        # 不带尾连字符）
        if "-offline-pkg" in n:
            continue
        ver = n.rsplit("-v", 1)[-1][:-4]
        p = os.path.join(root, n)
        try:
            st = os.stat(p)
        except OSError:
            continue
        items.append({
            "file": n, "version": ver,
            "size": st.st_size, "mtime": int(st.st_mtime * 1000),
            "url": "/" + quote(n), "latest": ver == latest and bool(latest),
            "notes": notes.get(ver, ""),
        })
    # v2.3.2：纯说明条目（notes-v<ver>.md 有归档但无安装包的早期版本）也进
    # 日志——用户定调「过往的历史也要」；无包不可下载，仅展示（前端日志区
    # 本就不渲染下载按钮）。mtime 用说明文件的。
    have = {it["version"] for it in items}
    for ver, note in notes.items():
        if ver in have or not note:
            continue
        nf = os.path.join(root, "notes-v%s.md" % ver)
        try:
            mtime = int(os.path.getmtime(nf) * 1000)
        except OSError:
            mtime = 0
        items.append({"file": "", "version": ver, "size": 0, "mtime": mtime,
                      "url": "", "latest": False, "notes": note})
    items.sort(key=lambda x: _ver_tuple(x["version"]), reverse=True)
    return items


def pkg_class(name):
    """资源包分类（a335R，第6轮对抗审 P1-4）：门户与 res_ui.autofind_fcpk
    必须用同一套口径，否则会出现「门户说是子集包不让用、闸门却自动选中它」
    这类分裂。返回 'full' | 'subset' | None。

    判定只看 basename（目录名不参与——第5轮 P2-1 的教训）：
      full   : `…资源包.fcpk`，或不带子集后缀的 `资源包-v<数字>[.数字]*.fcpk`
      subset : 其余含 `资源包-` 的（`-资源包-拓展`、`-资源包-claude` …）
    """
    b = name.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if not (b.endswith(".fcpk") and "资源包" in b):
        return None
    if b.endswith("资源包.fcpk"):
        return "full"
    if re.search(r"资源包-v\d+(?:\.\d+)*\.fcpk$", b):
        return "full"
    if "资源包-" in b:
        return "subset"
    return None


def _offline_pkg():
    """离线资源包单独通道。v4.1 起统一为加密的 `<应用名>-资源包.fcpk`。
    旧 zip（`-offline-pkg.zip`）通道已退役（用户令「彻底退役，不要了」），
    不再产出新 zip——仅在没有 fcpk 时回退兼容读取历史 release 目录里的 zip。

    a325R（第2轮对抗审 P1）：rank 必须区分**主包与子集包**。本目录实测同时
    存在 `-资源包.fcpk`（全量 1.7GB）与 `-资源包-拓展.fcpk`（只有 onlyoffice，
    916MB 且 mtime 更新），旧逻辑同 rank 按 mtime 取 → 门户把子集包当"离线
    资源包"发给同事 → 缺 WebView2/.NET 的新机器装完仍缺，启动闸门再拦，
    且下述 res_boot 的死循环会跟着触发。现改为：
      rank 2 = 主包（文件名精确 `<任意>-资源包.fcpk`）
      rank 1 = 子集包（`-资源包-*.fcpk`）
      rank 0 = 历史 zip
    主包存在时，子集包永不顶替。

    不进版本清单/更新日志——它不是应用版本，只是无外网机器的部署资源。
    sha1 不提供：manifest 刻意不收它（updater 不能把它当应用更新推下去），
    700MB 级大文件也不宜每请求现算。"""
    root = _releases_dir()
    try:
        names = os.listdir(root)
    except OSError:
        return None
    best = None
    for n in sorted(names):
        _ln = n.lower()
        is_new = _ln.endswith(".fcpk") and "-资源包" in _ln
        is_old = _ln.endswith(".zip") and "-offline-pkg" in _ln
        if not (is_new or is_old):
            continue
        p = os.path.join(root, n)
        try:
            st = os.stat(p)
        except OSError:
            continue
        if is_new:
            # a335R（第6轮 P1-4）：分类统一走 pkg_class，与 res_ui.autofind
            # 同口径——原来两边各写一套正则，导致 `-资源包-v2.fcpk`（真全量）
            # 在门户被标成子集包、在闸门却被当主包。
            _cls = pkg_class(n)
            if _cls is None:
                continue
            rank = 2 if _cls == "full" else 1
        else:
            rank = 0
        if best and (rank, st.st_mtime) <= (best[1][0], best[1][1]):
            continue
        ver = n.rsplit("-v", 1)[-1][:-4] if ("-v" in n and n.endswith(".zip")) else ""
        best = (n, (rank, st.st_mtime), st.st_size, ver,
                "fcpk" if is_new else "zip")
    if not best:
        return None
    return {"file": best[0], "version": best[3], "size": best[2],
            "mtime": int(best[1][1] * 1000), "format": best[4],
            "subset": best[1][0] == 1,     # 子集包：门户应如实标注
            "url": "/" + quote(best[0])}


# ---------------------------------------------------------------------------
# 页面（全内嵌：深色玻璃拟态门户，不依赖项目 web/ 资源）
# ---------------------------------------------------------------------------
def _esc(s):
    return html.escape(str(s or ""), quote=True)


_CSS = """
/* ============ 布局骨架（无色彩，皮肤只改变量+特化覆盖） ============ */
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:var(--font);color:var(--fg);min-height:100vh;
  background:var(--bg);overflow-x:hidden;transition:background .35s,color .35s}
.wrap{position:relative;z-index:1;max-width:880px;margin:0 auto;padding:40px 24px 80px}
.brand{display:flex;align-items:center;gap:14px;margin-bottom:38px;flex-wrap:wrap}
.logo{width:44px;height:44px;border-radius:var(--rad);display:grid;place-items:center;
  font-size:22px;background:var(--logoBg);box-shadow:var(--logoShadow)}
.brand h1{font-size:19px;font-weight:650;letter-spacing:.5px}
.brand .sub{font-size:12px;color:var(--muted);margin-top:3px}
.spacer{flex:1}
.status{display:flex;align-items:center;gap:7px;font-size:12px;color:var(--muted);
  background:var(--card);border:1px solid var(--line);padding:7px 13px;border-radius:99px}
.dot{width:7px;height:7px;border-radius:50%;background:var(--ok);
  box-shadow:0 0 8px var(--okGlow);animation:pulse 2.2s infinite}
@keyframes pulse{50%{opacity:.45}}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--radL);
  backdrop-filter:var(--blur);-webkit-backdrop-filter:var(--blur)}
.hero{padding:28px 30px;margin-bottom:28px;position:relative;overflow:hidden}
.hero::before{content:'';position:absolute;inset:0;pointer-events:none;
  background:var(--heroGlow)}
.hero .lab{font-size:12px;color:var(--lab);letter-spacing:2px;margin-bottom:10px}
.hero h2{font-size:34px;font-weight:750;font-family:var(--fontMono)}
.hero .meta{display:flex;gap:18px;flex-wrap:wrap;margin-top:12px;font-size:13px;color:var(--muted)}
.hero .notes{margin-top:16px;font-size:13.5px;line-height:1.75;color:var(--notes);
  white-space:pre-wrap;max-height:180px;overflow:auto}
.btn{display:inline-flex;align-items:center;gap:8px;cursor:pointer;
  font-size:13.5px;font-weight:600;color:var(--btnFg);padding:10px 20px;
  border-radius:var(--rad);border:var(--btnBorder);background:var(--btnBg);
  box-shadow:var(--btnShadow);transition:.18s;text-decoration:none;font-family:inherit}
.btn:hover{transform:var(--btnHoverTf);box-shadow:var(--btnHoverShadow);filter:var(--btnHoverFlt)}
.btn:disabled{opacity:.5;cursor:default;transform:none}
.btn.ghost{background:var(--card);border:1px solid var(--line);box-shadow:none;color:var(--fg)}
.btn.ghost:hover{border-color:var(--lineHover);filter:none;transform:none}
.hero .row{display:flex;align-items:center;gap:14px;margin-top:22px;flex-wrap:wrap}
.badge{font-size:10.5px;font-weight:700;letter-spacing:1.5px;padding:4px 11px;
  border-radius:var(--badgeRad);background:var(--badgeBg);color:var(--badgeFg)}
.vlist{display:flex;flex-direction:column;gap:12px}
/* v2.3.5 鼠标跟随辉光 + 粒子背景（用户要「背景特效，鼠标跟随」） */
.fx-glow{position:fixed;inset:0;pointer-events:none;z-index:0;
  background:radial-gradient(560px circle at var(--mx,50%) var(--my,30%),
    var(--fxGlow,transparent),transparent 62%);opacity:0;transition:opacity .6s}
body:hover .fx-glow{opacity:1}
#fxCanvas{position:fixed;inset:0;pointer-events:none;z-index:0}
body[data-skin=dark]{--fxGlow:rgba(79,140,255,.10)}
body[data-skin=paper]{--fxGlow:rgba(90,80,60,.07)}
body[data-skin=term]{--fxGlow:rgba(74,246,38,.05)}
.vitem{display:flex;align-items:center;gap:18px;padding:18px 22px;transition:.18s}
.vitem:hover{border-color:var(--lineHover);background:var(--cardHover)}
.vmain{flex:1;min-width:0}
.vname{font-family:var(--fontMono);font-size:16.5px;font-weight:650}
.vmeta{font-size:12px;color:var(--muted);margin-top:5px;display:flex;gap:14px;flex-wrap:wrap}
.sha{font-family:var(--fontMono)}
.empty{text-align:center;color:var(--muted);padding:70px 0;font-size:14px}
.tip{margin-top:26px;margin-bottom:28px;font-size:12.5px;color:var(--muted);line-height:1.9;
  background:var(--card);border:1px solid var(--line);border-radius:var(--radL);padding:16px 20px}
.tip b{color:var(--tipB)}
/* 换肤按钮（登录页/门户页共用） */
.skinbtn{position:fixed;right:18px;bottom:18px;z-index:50;font-size:12px;
  padding:8px 14px}
.skinbtn::after{display:none}   /* v2.3.6 关扫光——fixed 按钮上光带周期穿过形成残影（用户实锤）*/
.login-wrap{min-height:100vh;display:grid;place-items:center;position:relative;z-index:1}
.login{width:min(380px,92vw);padding:38px 34px;text-align:center}
.login .logo{margin:0 auto 18px;width:56px;height:56px;font-size:28px}
.login h1{font-size:18px;font-weight:680;margin-bottom:6px}
.login .sub{font-size:12.5px;color:var(--muted);margin-bottom:28px}
.login input{width:100%;padding:12px 16px;font-size:14px;color:var(--fg);
  background:var(--inputBg);border:1px solid var(--line);border-radius:var(--rad);
  outline:none;transition:.18s;margin-bottom:14px;font-family:inherit}
.login input:focus{border-color:var(--accent);box-shadow:var(--inputFocus)}
.login .btn{width:100%;justify-content:center;padding:12px}
.err{color:var(--err);font-size:12.5px;min-height:18px;margin-bottom:8px}
.shake{animation:shake .4s}
@keyframes shake{20%,60%{transform:translateX(-6px)}40%,80%{transform:translateX(6px)}}

/* ============ 皮肤一：璃青（深色玻璃，精修） ============ */
body[data-skin=dark]{
  --font:system-ui,-apple-system,'Segoe UI','Microsoft YaHei',sans-serif;
  --fontMono:ui-monospace,Consolas,'Cascadia Mono',monospace;
  --bg:#0a0f1e;--fg:#eaeffa;--muted:#86909f;--notes:#c5cddd;--tipB:#aab6cc;
  --card:rgba(255,255,255,.045);--cardHover:rgba(255,255,255,.07);
  --line:rgba(255,255,255,.09);--lineHover:rgba(255,255,255,.2);
  --rad:11px;--radL:18px;
  --accent:#5b9dff;--lab:#39c8d8;--ok:#34d399;--okGlow:#34d39988;--err:#f87171;
  --btnBg:linear-gradient(135deg,#4f8cff,#2bd4c4);--btnFg:#fff;--btnBorder:none;
  --btnShadow:0 4px 18px rgba(79,140,255,.28);--btnHoverTf:translateY(-1px);
  --btnHoverShadow:0 8px 26px rgba(79,140,255,.4);--btnHoverFlt:none;
  --logoBg:linear-gradient(135deg,#4f8cff,#2bd4c4);--logoShadow:0 6px 22px rgba(79,140,255,.32);
  --badgeBg:linear-gradient(135deg,#34d399,#22d3ee);--badgeFg:#04121a;--badgeRad:99px;
  --blur:blur(16px);--heroGlow:linear-gradient(120deg,rgba(79,140,255,.09),transparent 55%);
  --inputBg:rgba(255,255,255,.05);--inputFocus:0 0 0 3px rgba(79,140,255,.18)}
body[data-skin=dark]::before,body[data-skin=dark]::after{content:'';position:fixed;
  border-radius:50%;filter:blur(110px);opacity:.22;pointer-events:none;z-index:0}
body[data-skin=dark]::before{width:520px;height:520px;left:-150px;top:-170px;background:#1d4ed8}
body[data-skin=dark]::after{width:480px;height:480px;right:-170px;bottom:-150px;background:#0d9488}

/* ============ 皮肤二：素白（纸感极简，衬线标题） ============ */
body[data-skin=paper]{
  --font:system-ui,-apple-system,'Segoe UI','Microsoft YaHei',sans-serif;
  --fontMono:'SF Mono',ui-monospace,Consolas,monospace;
  --bg:#f7f5f0;--fg:#1c1a17;--muted:#8a857b;--notes:#3d3a34;--tipB:#1c1a17;
  --card:#ffffff;--cardHover:#fdfcf9;
  --line:#e6e2d8;--lineHover:#c9c3b4;
  --rad:10px;--radL:12px;
  --accent:#1c1a17;--lab:#9a6b2f;--ok:#3d8b5f;--okGlow:#3d8b5f44;--err:#c0392b;
  --btnBg:#1c1a17;--btnFg:#f7f5f0;--btnBorder:1px solid #1c1a17;
  --btnShadow:0 1px 2px rgba(28,26,23,.18);--btnHoverTf:translateY(-1px);
  --btnHoverShadow:0 3px 10px rgba(28,26,23,.22);--btnHoverFlt:none;
  --logoBg:#1c1a17;--logoShadow:0 2px 10px rgba(28,26,23,.25);--logoFg:#f7f5f0;
  --badgeBg:#1c1a17;--badgeFg:#f7f5f0;--badgeRad:3px;
  --blur:none;--heroGlow:none;
  --inputBg:#ffffff;--inputFocus:0 0 0 3px rgba(28,26,23,.08)}
body[data-skin=paper] .logo{color:#f7f5f0}
body[data-skin=paper]::before{content:'';position:fixed;inset:0;pointer-events:none;z-index:0;
  background-image:radial-gradient(#d8d2c4 1px,transparent 1px);background-size:26px 26px;
  opacity:.5}
body[data-skin=paper] .hero h2{font-family:Georgia,'Times New Roman','STSong','SimSun',serif;
  font-weight:600;letter-spacing:-.5px}
body[data-skin=paper] .hero .lab{font-family:Georgia,serif;font-style:italic;
  letter-spacing:1px;text-transform:none}
body[data-skin=paper] .card{box-shadow:0 1px 3px rgba(28,26,23,.05)}
body[data-skin=paper] .vitem:hover{box-shadow:0 2px 8px rgba(28,26,23,.06)}

/* ============ 皮肤三：终端（全等宽荧光绿，扫描线） ============ */
body[data-skin=term]{
  --font:ui-monospace,Consolas,'Cascadia Mono','Courier New',monospace;
  --fontMono:inherit;
  --bg:#0a0d0a;--fg:#c9f5c9;--muted:#5d7a5d;--notes:#a8e0a8;--tipB:#7dd87d;
  --card:#0e130e;--cardHover:#121a12;
  --line:#1d2e1d;--lineHover:#3a5c3a;
  --rad:0px;--radL:0px;
  --accent:#4af626;--lab:#4af626;--ok:#4af626;--okGlow:#4af62666;--err:#ff5f5f;
  --btnBg:transparent;--btnFg:#4af626;--btnBorder:1px solid #4af626;
  --btnShadow:none;--btnHoverTf:none;--btnHoverShadow:none;
  --btnHoverFlt:none;
  --logoBg:transparent;--logoShadow:none;--logoBorder:1px solid #4af626;
  --badgeBg:#4af626;--badgeFg:#0a0d0a;--badgeRad:0px;
  --blur:none;--heroGlow:none;
  --inputBg:#0a0d0a;--inputFocus:0 0 0 1px #4af626}
body[data-skin=term] .logo{border:1px solid #4af626;color:#4af626;
  text-shadow:0 0 10px #4af62688}
body[data-skin=term] .hero h2,body[data-skin=term] .vname,body[data-skin=term] .brand h1{
  text-shadow:0 0 12px rgba(74,246,38,.35)}
body[data-skin=term] .btn{font-family:inherit}
body[data-skin=term] .btn:hover{background:#4af626;color:#0a0d0a;
  text-shadow:none;box-shadow:0 0 18px rgba(74,246,38,.5)}
body[data-skin=term] .btn.ghost:hover{background:transparent;color:#4af626;
  box-shadow:none;border-color:#4af626}
body[data-skin=term] .hero .lab::before{content:'> '}
body[data-skin=term] .status{border-radius:0}
body[data-skin=term]::after{content:'';position:fixed;inset:0;pointer-events:none;z-index:40;
  background:repeating-linear-gradient(0deg,rgba(0,0,0,.16) 0 1px,transparent 1px 3px)}
body[data-skin=term] .dot{animation:none}

/* ============ v2.3.3 动效层（三皮肤通用骨架 + 各自风格化） ============ */
/* 1) 入场编排：卡片依次上浮淡入（stagger） */
@keyframes fcUp{from{opacity:0;transform:translateY(18px)}to{opacity:1;transform:none}}
.wrap>.brand{animation:fcUp .5s .05s cubic-bezier(.2,.7,.3,1) both}
.wrap>.tip{animation:fcUp .5s .15s cubic-bezier(.2,.7,.3,1) both}
.card.hero{animation:fcUp .6s .22s cubic-bezier(.2,.7,.3,1) both}
.vlist .card{animation:fcUp .5s both}
.vlist .card:nth-child(1){animation-delay:.32s}
.vlist .card:nth-child(2){animation-delay:.40s}
.vlist .card:nth-child(3){animation-delay:.48s}
.vlist .card:nth-child(4){animation-delay:.56s}
.vlist .card:nth-child(5){animation-delay:.62s}
.vlist .card:nth-child(n+6){animation-delay:.68s}
.card.login{animation:fcUp .55s .1s cubic-bezier(.2,.7,.3,1) both}
/* 2) 版本号/徽标呼吸 */
@keyframes fcBreath{0%,100%{transform:scale(1)}50%{transform:scale(1.045)}}
.hero .badge{animation:fcBreath 2.6s ease-in-out infinite}
.hero .logo,.login .logo{animation:fcBreath 3.4s ease-in-out infinite}
/* 3) 状态点涟漪（更立体） */
.dot{position:relative}
@keyframes fcPing{from{box-shadow:0 0 0 0 var(--okGlow)}to{box-shadow:0 0 0 9px transparent}}
.dot{animation:pulse 2.2s infinite,fcPing 2.2s infinite}
/* 4) 按钮 shimmer 扫光（仅主按钮） */
.btn:not(.skinbtn){position:relative;overflow:hidden}   /* 不覆盖 skinbtn 的 fixed（用户实锤按钮掉左下）*/
.btn::after{content:'';position:absolute;top:0;left:-70%;width:45%;height:100%;
  background:linear-gradient(105deg,transparent,rgba(255,255,255,.28),transparent);
  transform:skewX(-18deg);animation:fcShimmer 3.6s ease-in-out infinite}
@keyframes fcShimmer{0%,55%{left:-70%}85%,100%{left:130%}}
/* 5) 卡片 hover 精修：轻抬 + 亮度 */
.card.hero,.vlist .card{transition:transform .25s cubic-bezier(.2,.7,.3,1),box-shadow .25s,border-color .25s}
.card.hero:hover{transform:translateY(-3px)}
/* 6) 滚动条主题化 */
::-webkit-scrollbar{width:9px;height:9px}
::-webkit-scrollbar-thumb{background:var(--lineHover);border-radius:99px}
::-webkit-scrollbar-thumb:hover{background:var(--accent)}
::-webkit-scrollbar-track{background:transparent}
/* 7) reduced-motion：全套关闭（无障碍/低端机） */
@media (prefers-reduced-motion: reduce){
  *,*::before,*::after{animation:none!important;transition:none!important}
}

/* ---- 皮肤一 dark：光斑漂移 + 版本号流光 ---- */
@keyframes fcDrift1{0%,100%{transform:translate(0,0) scale(1)}50%{transform:translate(70px,50px) scale(1.12)}}
@keyframes fcDrift2{0%,100%{transform:translate(0,0) scale(1)}50%{transform:translate(-60px,-44px) scale(1.08)}}
body[data-skin=dark]::before{animation:fcDrift1 22s ease-in-out infinite}
body[data-skin=dark]::after{animation:fcDrift2 27s ease-in-out infinite}
@keyframes fcFlow{to{background-position:220% 0}}
body[data-skin=dark] .hero h2{
  background:linear-gradient(100deg,#eaeffa 20%,#5b9dff 42%,#2bd4c4 58%,#eaeffa 80%);
  background-size:220% 100%;-webkit-background-clip:text;background-clip:text;
  -webkit-text-fill-color:transparent;color:transparent;
  animation:fcFlow 5s linear infinite}
body[data-skin=dark] .card.hero{border-image:none}
body[data-skin=dark] .card.hero::after{content:'';position:absolute;inset:-1px;pointer-events:none;
  border-radius:inherit;padding:1px;
  background:linear-gradient(120deg,rgba(91,157,255,.55),transparent 30%,transparent 70%,rgba(43,212,196,.5));
  -webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);
  -webkit-mask-composite:xor;mask-composite:exclude;
  animation:fcBorderGlow 4.5s ease-in-out infinite}
@keyframes fcBorderGlow{0%,100%{opacity:.35}50%{opacity:1}}

/* ---- 皮肤二 paper：墨迹呼吸 + 卡片提笔感 ---- */
@keyframes fcInk{0%,100%{letter-spacing:1px}50%{letter-spacing:2.4px}}
body[data-skin=paper] .hero .lab{animation:fcInk 5s ease-in-out infinite}
body[data-skin=paper] .hero .badge{animation:fcBreath 3.6s ease-in-out infinite}
body[data-skin=paper] .vlist .card:hover{transform:translateY(-2px)}
body[data-skin=paper] .hero h2{transition:letter-spacing .5s}
body[data-skin=paper] .hero:hover h2{letter-spacing:1.5px}

/* ---- 皮肤三 term：扫描线滚动 + 光标闪烁 + 输入呼吸 ---- */
@keyframes fcScan{from{background-position:0 0}to{background-position:0 120px}}
body[data-skin=term]::after{animation:fcScan 9s linear infinite;opacity:.75}
@keyframes fcBlink{0%,49%{opacity:1}50%,100%{opacity:0}}
body[data-skin=term] .hero .lab::after{content:'_';animation:fcBlink 1.1s steps(1) infinite;
  color:#4af626;margin-left:2px}
body[data-skin=term] .hero h2{animation:fcGlow 3s ease-in-out infinite}
@keyframes fcGlow{0%,100%{text-shadow:0 0 12px rgba(74,246,38,.3)}50%{text-shadow:0 0 22px rgba(74,246,38,.65)}}
body[data-skin=term] .btn::after{display:none}
body[data-skin=term] .vlist .card{animation:fcUp .4s both,fcGlow2 4s ease-in-out infinite}
@keyframes fcGlow2{0%,100%{border-color:#1d2e1d}50%{border-color:#2a452a}}

/* ---- v3.5.290 工具说明书 tab ---- */
.pgtabs { display:flex; gap:10px; margin:0 0 18px; }
.pgtab { padding:9px 22px; border-radius:99px; border:1px solid var(--line);
  background:var(--card); color:var(--muted); cursor:pointer; font-size:13.5px; font-weight:600; }
.pgtab.on { background:var(--accent,#4f8fff); color:#fff; border-color:transparent; }
.mn-hero { padding:6px 4px 14px; }
.mn-hero h2 { font-size:22px; font-weight:700; }
.mn-hero p { color:var(--muted); font-size:13.5px; margin-top:6px; }
.mn-sec { font-size:15px; font-weight:700; margin:22px 0 12px; }
.mn-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:12px; }
.mn-card { background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:14px 16px; font-size:13px; line-height:1.7; color:var(--muted); }
.mn-card b { display:block; color:var(--fg); font-size:13.5px; margin-bottom:4px; }
.mn-step { background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:16px 18px; margin-bottom:16px; }
.mn-step-t { font-size:14.5px; font-weight:700; margin-bottom:8px; }
.mn-step p { font-size:13px; line-height:1.75; color:var(--muted); margin-bottom:10px; }
.mn-step img { width:100%; border-radius:8px; border:1px solid var(--line); display:block; }
.mn-tip { font-size:12.5px; color:var(--muted); }

.mn-svg { width:100%; max-width:720px; height:auto; display:block; margin:4px 0 12px;
  color:var(--fg); background:color-mix(in srgb, var(--bg) 40%, transparent);
  border-radius:8px; padding:6px 4px; }
"""

_LOGIN_HTML = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>前端控制台 · 发布中心</title>
<link rel="icon" type="image/png" href="__ICON__">
<style>__CSS__</style></head><body data-skin="dark">
<div class="login-wrap"><div class="card login">
  <div class="logo"><img src="__ICON__" style="width:36px;height:36px;" alt=""></div>
  <h1>前端控制台 · 发布中心</h1>
  <div class="sub">版本下发与升级门户 · 仅限内网</div>
  <div class="err" id="err"></div>
  <input type="password" id="pwd" placeholder="访问密码" autofocus autocomplete="current-password">
  <button class="btn" id="go">进入</button>
  <div class="sub" style="margin:22px 0 0;">默认密码 __DEFPWD__（发布者可在工具 设置→关于与升级 中修改）</div>
</div></div>
<button class="btn ghost skinbtn" id="skin" title="切换界面风格">🎨 换肤</button>
<canvas id="fxCanvas"></canvas>
<div class="fx-glow"></div>
<script>
// ---- v2.3.6 背景特效（三皮肤差异化，用户定调「不能全是粒子」）----
// dark 璃青：粒子星野（鼠标推开）+ 辉光跟随
// paper 素白：墨晕拖尾——鼠标划过宣纸留下淡淡墨痕，慢慢晕开消散
// term 终端：数据雨——稀疏绿色字符列下落（克制的 Matrix）
(function(){
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  // 共用：鼠标辉光缓动跟随（三皮肤都有，颜色各异 CSS 已定）
  var tx=innerWidth/2, ty=innerHeight*0.3, cx=tx, cy=ty;
  addEventListener('mousemove', function(e){ tx=e.clientX; ty=e.clientY; }, {passive:true});
  (function glide(){
    cx += (tx-cx)*0.08; cy += (ty-cy)*0.08;
    document.documentElement.style.setProperty('--mx', cx+'px');
    document.documentElement.style.setProperty('--my', cy+'px');
    requestAnimationFrame(glide);
  })();
  var cv = document.getElementById('fxCanvas'), ctx = cv.getContext('2d');
  function resize(){ cv.width=innerWidth; cv.height=innerHeight; }
  resize(); addEventListener('resize', resize);
  var mouse={x:-999,y:-999,lx:-999,ly:-999};
  addEventListener('mousemove', function(e){ mouse.lx=mouse.x; mouse.ly=mouse.y;
    mouse.x=e.clientX; mouse.y=e.clientY; }, {passive:true});
  function skin(){ return document.body.dataset.skin; }

  // ---- 模式一 dark：粒子星野 ----
  var P=[], N=Math.min(46, Math.floor(innerWidth/30));
  for (var i=0;i<N;i++) P.push({x:Math.random()*cv.width, y:Math.random()*cv.height,
    vx:(Math.random()-.5)*.22, vy:(Math.random()-.5)*.22,
    r:Math.random()*1.6+.5, a:Math.random()*.5+.15});
  function fxDark(){
    for (var i=0;i<P.length;i++){ var p=P[i];
      var dx=p.x-mouse.x, dy=p.y-mouse.y, d2=dx*dx+dy*dy;
      if (d2<8100){ var d=Math.sqrt(d2)||1, f=(90-d)/90*.6; p.x+=dx/d*f; p.y+=dy/d*f; }
      p.x+=p.vx; p.y+=p.vy;
      if (p.x<-9)p.x=cv.width+9; if (p.x>cv.width+9)p.x=-9;
      if (p.y<-9)p.y=cv.height+9; if (p.y>cv.height+9)p.y=-9;
      ctx.beginPath(); ctx.arc(p.x,p.y,p.r,0,6.283);
      ctx.fillStyle='rgba(120,160,255,'+p.a+')'; ctx.fill();
    }
  }

  // ---- 模式二 paper：墨晕拖尾（鼠标在宣纸上划出墨痕，晕开淡出）----
  var ink=[];
  function fxPaper(){
    // 鼠标移动才产墨点（间距>7px 一个，带随机偏移像笔锋）
    var mdx=mouse.x-mouse.lx, mdy=mouse.y-mouse.ly;
    if (mdx*mdx+mdy*mdy>49){
      ink.push({x:mouse.x+(Math.random()-.5)*6, y:mouse.y+(Math.random()-.5)*6,
                r:2+Math.random()*3, life:1});
      mouse.lx=mouse.x; mouse.ly=mouse.y;
    }
    for (var i=ink.length-1;i>=0;i--){ var k=ink[i];
      k.life-=0.006;                       // 慢慢消散
      k.r+=0.06;                           // 墨在纸里晕开
      if (k.life<=0){ ink.splice(i,1); continue; }
      ctx.beginPath(); ctx.arc(k.x,k.y,k.r,0,6.283);
      ctx.fillStyle='rgba(70,60,45,'+(k.life*0.10).toFixed(3)+')'; ctx.fill();
    }
    if (ink.length>140) ink.splice(0, ink.length-140);
  }

  // ---- 模式三 term：数据雨（稀疏字符列，克制下落）----
  var CH='01<>/{}[]#$%&*+=?'; 
  var rain=[];
  (function mkRain(){ var cols=Math.floor(innerWidth/90);   // 90px 一列，很稀
    for (var i=0;i<cols;i++) rain.push({x:i*90+20, y:Math.random()*-innerHeight,
      v:1.2+Math.random()*1.6, len:5+Math.floor(Math.random()*7), t:0});
  })();
  function fxTerm(){
    ctx.font='12px Consolas,monospace';
    for (var i=0;i<rain.length;i++){ var rp=rain[i];
      rp.y+=rp.v; rp.t++;
      for (var j=0;j<rp.len;j++){ var y=rp.y-j*14;
        if (y<-14||y>cv.height+14) continue;
        var a=(1-j/rp.len)*(j===0?0.9:0.45);   // 头亮尾淡
        ctx.fillStyle='rgba(74,246,38,'+a+')';
        ctx.fillText(CH[(i*7+j*3+rp.t)%CH.length|0], rp.x, y);
      }
      if (rp.y-rp.len*14>cv.height){ rp.y=-Math.random()*300; rp.v=1.2+Math.random()*1.6; }
    }
  }

  (function loop(){
    ctx.clearRect(0,0,cv.width,cv.height);
    var s=skin();
    if (s==='paper') fxPaper();
    else if (s==='term') fxTerm();
    else fxDark();
    requestAnimationFrame(loop);
  })();
})();

// ---- 三套皮肤切换（登录页/门户页共用逻辑，选择存 localStorage）----
const SKINS=[['dark','璃青'],['paper','素白'],['term','终端']];
let _fcCur=localStorage.getItem('fc_skin')||'dark';
if(!SKINS.some(s=>s[0]===_fcCur))_fcCur='dark';
function _fcSkinApply(){document.body.dataset.skin=_fcCur;
  const b=document.getElementById('skin');if(b)b.textContent='🎨 '+SKINS.find(s=>s[0]===_fcCur)[1];}
_fcSkinApply();
document.getElementById('skin').onclick=()=>{
  _fcCur=SKINS[(SKINS.findIndex(s=>s[0]===_fcCur)+1)%SKINS.length][0];
  localStorage.setItem('fc_skin',_fcCur);_fcSkinApply();};
const go=document.getElementById('go'),pwd=document.getElementById('pwd'),err=document.getElementById('err');
async function login(){
  go.disabled=true;go.textContent='验证中…';
  try{
    const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({password:pwd.value})});
    const j=await r.json();
    if(j.ok){location.replace('/');return}
    err.textContent=j.err||'密码不对';
    document.querySelector('.login').classList.remove('shake');
    void document.querySelector('.login').offsetWidth;
    document.querySelector('.login').classList.add('shake');
  }catch(e){err.textContent='网络异常：'+e}
  go.disabled=false;go.textContent='进入';
}
go.onclick=login;pwd.addEventListener('keydown',e=>{if(e.key==='Enter')login()});
</script></body></html>"""

def _app_icon_b64():
    """工具图标 base64（ico/app.png，发布机源码运行必有）——门户 favicon
    与页内 logo 用真图标替换 emoji（用户定调：和工具相同图标）。"""
    import base64
    for p in (os.path.join(os.path.dirname(os.path.dirname(
                    os.path.abspath(__file__))), "ico", "app.png"),
              os.path.join(_releases_dir(), "..", "..", "ico", "app.png")):
        try:
            with open(p, "rb") as f:
                return base64.b64encode(f.read()).decode()
        except OSError:
            continue
    return ""


_PORTAL_HTML = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>前端控制台 · 发布中心</title>
<link rel="icon" type="image/png" href="__ICON__">
<style>__CSS__</style></head><body data-skin="dark">
<div class="wrap">
  <div class="brand">
    <div class="logo"><img src="__ICON__" style="width:30px;height:30px;" alt=""></div>
    <div><h1>前端控制台 · 发布中心</h1>
      <div class="sub">__URL__ · 发布目录只读分发</div></div>
    <div class="spacer"></div>
    <div class="status"><span class="dot"></span>服务在线</div>
    <button class="btn ghost" id="out" style="padding:7px 14px;font-size:12px;">退出</button>
  </div>
  <!-- v2.3.2 使用说明提到最前（用户定调：一眼看到），原在页尾被日志顶到看不见 -->
  <div class="tip">
    <b>整包安装</b>：下载最新版 zip 解压即用。<br>
    <b>工具内热更新</b>：把地址 <b>__URL__</b> 填到工具「设置 → 关于与升级 → 升级服务器地址」，
    以后有新版工具会自动检查、一键升级（旧版自动备份为 .bak 可回退）。
  </div>
  <div class="pgtabs">
    <button class="pgtab on" data-pg="dl" onclick="pgSwitch('dl')">📦 版本下载</button>
    <button class="pgtab" data-pg="mn" onclick="pgSwitch('mn')">📖 工具说明书</button>
  </div>
  <div id="pg-dl"><div id="body"><div class="empty">版本加载中…</div></div></div>
  <div id="pg-mn" style="display:none">
    <div class="mn-hero">
      <h2>前端控制台 —— 一站式嵌入式调试工作台</h2>
      <p>常用工具全部集成 × Claude AI 深度赋能，装一个顶一堆</p>
    </div>
    <div class="mn-sec"><b>✨ 产品亮点</b></div>
    <div class="mn-grid">
      <div class="mn-card"><b>🔩 调试工具全家桶</b>串口 · SSH · Telnet · TFTP · HFS 文件服务，一个窗口全搞定</div>
      <div class="mn-card"><b>📄 大文件友好</b>1GB+ 级日志阅读器（缩放虚拟列表，再大也不卡）、文本编辑器、二进制查看、文件对比、程序员计算器</div>
      <div class="mn-card"><b>🤖 Claude AI 深度集成</b>AI 会话多开并行、子代理全程实况跟随、任务/审计/复盘体系，AI 直接帮你操作和排查</div>
      <div class="mn-card"><b>👥 三角色智能体（可分配模型）</b>轻/中/重三档形态，主会话 / 设计者 / 审计者三槽模型各自分配，审计模式与分级线可调</div>
      <div class="mn-card"><b>👁 内置 MCP 识图</b>截图发给 AI 即懂——真多模态模型直读，其余自动走内置识图通道，面板一键配置</div>
      <div class="mn-card"><b>🛡 稳定性基建</b>请求看门狗（超时自动打断+留证）、SSE 断线水位续传、会话恢复、热更新带备份回退</div>
    </div>
    <div class="mn-sec"><b>🚀 快速上手 · 三个配置</b></div>
    <div class="mn-step">
      <div class="mn-step-t">1️⃣ 接入 Claude Code —— 让 AI 在工具里跑起来</div>
      <svg class="mn-svg" viewBox="0 0 720 96" xmlns="http://www.w3.org/2000/svg">
        <defs><linearGradient id="g1" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stop-color="#4f8fff"/><stop offset="1" stop-color="#8957e5"/></linearGradient></defs>
        <rect x="10" y="18" width="200" height="56" rx="10" fill="none" stroke="url(#g1)" stroke-width="1.5"/>
        <text x="110" y="42" text-anchor="middle" fill="currentColor" font-size="13" font-weight="600">① 自动检测环境</text>
        <text x="110" y="62" text-anchor="middle" fill="#8899aa" font-size="11">Claude CLI / Node / Git</text>
        <path d="M 218 46 H 262" stroke="url(#g1)" stroke-width="1.5" marker-end="url(#ar1)"/>
        <rect x="270" y="18" width="200" height="56" rx="10" fill="none" stroke="url(#g1)" stroke-width="1.5"/>
        <text x="370" y="42" text-anchor="middle" fill="currentColor" font-size="13" font-weight="600">② 引导安装（缺啥装啥）</text>
        <text x="370" y="62" text-anchor="middle" fill="#8899aa" font-size="11">资源包一键装</text>
        <path d="M 478 46 H 522" stroke="url(#g1)" stroke-width="1.5"/>
        <rect x="530" y="18" width="180" height="56" rx="10" fill="none" stroke="url(#g1)" stroke-width="1.5"/>
        <text x="620" y="42" text-anchor="middle" fill="currentColor" font-size="13" font-weight="600">③ 自动拉起 Claude</text>
        <text x="620" y="62" text-anchor="middle" fill="#8899aa" font-size="11">API Token 配好即用</text>
      </svg>
      <p><b>怎么配：</b>在「设置 → 外部依赖安装」里选资源包（.fcpk），勾选所需项一键装（无网机器把资源包拷过去即可）。装好即用。<br>
      <b>API 接入：</b>需要 Anthropic 兼容 API 的（企业内网网关 / 智谱等），在 Claude 对话页的接入引导里填 <b>Base URL + API Token</b>（支持 settings.json 同源自动读取）；官方账号用户装好 CLI 登录即可。<br>
      <b>提示：</b>工具页左下角有「Claude」状态徽章，绿色=通道就绪。之后每个会话页签就是一个独立 AI，互不干扰。</p>
    </div>
    <div class="mn-step">
      <div class="mn-step-t">2️⃣ 配置识图 —— 让 AI 看懂你的截图</div>
      <svg class="mn-svg" viewBox="0 0 720 96" xmlns="http://www.w3.org/2000/svg">
        <rect x="10" y="18" width="170" height="56" rx="10" fill="none" stroke="#4f8fff" stroke-width="1.5"/>
        <rect x="30" y="30" width="44" height="32" rx="4" fill="none" stroke="#4f8fff" stroke-width="1.2"/>
        <circle cx="44" cy="40" r="4" fill="#4f8fff"/><path d="M 36 58 L 52 46 L 66 58" stroke="#4f8fff" stroke-width="1.2" fill="none"/>
        <text x="95" y="50" text-anchor="middle" fill="currentColor" font-size="12">截图拖进会话</text>
        <path d="M 190 46 H 300" stroke="#4f8fff" stroke-width="1.5"/>
        <rect x="308" y="18" width="120" height="56" rx="28" fill="none" stroke="#8957e5" stroke-width="1.5"/>
        <text x="368" y="50" text-anchor="middle" fill="currentColor" font-size="13" font-weight="600">🤖 AI 识图</text>
        <path d="M 436 46 H 546" stroke="#8957e5" stroke-width="1.5"/>
        <rect x="554" y="18" width="160" height="56" rx="10" fill="none" stroke="#3fb950" stroke-width="1.5"/>
        <text x="634" y="50" text-anchor="middle" fill="currentColor" font-size="12">分析结论 / 修改建议</text>
      </svg>
      <p><b>怎么配：</b>工具页点 <b>👁 识图配置</b> 按钮（Claude 会话页输入区上方）→<br>
      ① 勾选「<b>启用识图</b>」；<br>
      ② 「识图模型」下拉选择一个多模态模型（如 glm-5.3-flash，带 👁 标记的都是）；<br>
      ③ 企业内网 / 自建网关用户：展开高级配置填专用 <b>端点 + 密钥</b>（留空自动跟随主会话 API）；<br>
      ④ 点「保存」——即改即生效，无需重启。<br>
      <b>智能通道：</b>真多模态模型（如 glm-5.3）AI 直接看图；非多模态模型自动走内置 MCP 识图通道——<b>切换模型无需改任何配置</b>，工具自动判定。<br>
      <b>用法：</b>把截图拖进会话输入框（或粘贴），AI 直接分析图内内容。</p>
    </div>
    <div class="mn-step">
      <div class="mn-step-t">3️⃣ 配置三角色 —— AI 分身帮你干活</div>
      <svg class="mn-svg" viewBox="0 0 720 110" xmlns="http://www.w3.org/2000/svg">
        <rect x="10" y="10" width="200" height="40" rx="8" fill="none" stroke="#4f8fff" stroke-width="1.5"/>
        <text x="110" y="35" text-anchor="middle" fill="currentColor" font-size="12">主会话（调度+干活）· 模型槽 A</text>
        <rect x="10" y="60" width="200" height="40" rx="8" fill="none" stroke="#8957e5" stroke-width="1.5"/>
        <text x="110" y="85" text-anchor="middle" fill="currentColor" font-size="12">设计者（出方案）· 模型槽 B</text>
        <rect x="510" y="35" width="200" height="40" rx="8" fill="none" stroke="#3fb950" stroke-width="1.5"/>
        <text x="610" y="60" text-anchor="middle" fill="currentColor" font-size="12">审计者（复核把关）· 模型槽 C</text>
        <path d="M 215 55 C 350 55 400 55 505 55" stroke="#8899aa" stroke-width="1.2" fill="none" stroke-dasharray="5 4"/>
        <path d="M 215 80 C 350 90 420 70 505 60" stroke="#8899aa" stroke-width="1.2" fill="none" stroke-dasharray="5 4"/>
        <text x="360" y="45" text-anchor="middle" fill="#8899aa" font-size="11">派出任务</text>
        <text x="360" y="95" text-anchor="middle" fill="#8899aa" font-size="11">回报结论</text>
      </svg>
      <p><b>怎么配：</b>工具页点 <b>👥 三角色</b> 按钮 →<br>
      ① 打开「<b>启用三角色</b>」开关；<br>
      ② 三档模型槽各自下拉分配：<b>主会话模型</b>（调度与干活）/ <b>设计者</b>（出方案，可配强模型）/ <b>审计者</b>（复核把关，可配快模型省钱）——<b>三个槽可以用不同模型</b>；<br>
      ③ 审计模式与分级线可调（直改多少行触发审计由你定）；<br>
      ④ 点「保存」——<b>下条消息热更生效，无需重启</b>。<br>
      <b>效果：</b>之后派任务时 AI 自动分工——设计者出方案、执行者落地、审计者复核打回，全程在窗格里实时可见，各角色干完自动汇报。</p>
    </div>
    <div class="mn-sec"><b>💡 提示</b></div>
    <p class="mn-tip">识图与三角色均支持按 API 方案独立配置（切方案各配各的）；所有配置即改即生效，无需重启。</p>
  </div>
</div>
<script>
function pgSwitch(pg){
  document.querySelectorAll('.pgtab').forEach(function(b){ b.classList.toggle('on', b.dataset.pg === pg); });
  document.getElementById('pg-dl').style.display = pg === 'dl' ? '' : 'none';
  document.getElementById('pg-mn').style.display = pg === 'mn' ? '' : 'none';
}
</script>
<button class="btn ghost skinbtn" id="skin" title="切换界面风格">🎨 换肤</button>
<canvas id="fxCanvas"></canvas>
<div class="fx-glow"></div>
<script>
// ---- v2.3.6 背景特效（三皮肤差异化，用户定调「不能全是粒子」）----
// dark 璃青：粒子星野（鼠标推开）+ 辉光跟随
// paper 素白：墨晕拖尾——鼠标划过宣纸留下淡淡墨痕，慢慢晕开消散
// term 终端：数据雨——稀疏绿色字符列下落（克制的 Matrix）
(function(){
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  // 共用：鼠标辉光缓动跟随（三皮肤都有，颜色各异 CSS 已定）
  var tx=innerWidth/2, ty=innerHeight*0.3, cx=tx, cy=ty;
  addEventListener('mousemove', function(e){ tx=e.clientX; ty=e.clientY; }, {passive:true});
  (function glide(){
    cx += (tx-cx)*0.08; cy += (ty-cy)*0.08;
    document.documentElement.style.setProperty('--mx', cx+'px');
    document.documentElement.style.setProperty('--my', cy+'px');
    requestAnimationFrame(glide);
  })();
  var cv = document.getElementById('fxCanvas'), ctx = cv.getContext('2d');
  function resize(){ cv.width=innerWidth; cv.height=innerHeight; }
  resize(); addEventListener('resize', resize);
  var mouse={x:-999,y:-999,lx:-999,ly:-999};
  addEventListener('mousemove', function(e){ mouse.lx=mouse.x; mouse.ly=mouse.y;
    mouse.x=e.clientX; mouse.y=e.clientY; }, {passive:true});
  function skin(){ return document.body.dataset.skin; }

  // ---- 模式一 dark：粒子星野 ----
  var P=[], N=Math.min(46, Math.floor(innerWidth/30));
  for (var i=0;i<N;i++) P.push({x:Math.random()*cv.width, y:Math.random()*cv.height,
    vx:(Math.random()-.5)*.22, vy:(Math.random()-.5)*.22,
    r:Math.random()*1.6+.5, a:Math.random()*.5+.15});
  function fxDark(){
    for (var i=0;i<P.length;i++){ var p=P[i];
      var dx=p.x-mouse.x, dy=p.y-mouse.y, d2=dx*dx+dy*dy;
      if (d2<8100){ var d=Math.sqrt(d2)||1, f=(90-d)/90*.6; p.x+=dx/d*f; p.y+=dy/d*f; }
      p.x+=p.vx; p.y+=p.vy;
      if (p.x<-9)p.x=cv.width+9; if (p.x>cv.width+9)p.x=-9;
      if (p.y<-9)p.y=cv.height+9; if (p.y>cv.height+9)p.y=-9;
      ctx.beginPath(); ctx.arc(p.x,p.y,p.r,0,6.283);
      ctx.fillStyle='rgba(120,160,255,'+p.a+')'; ctx.fill();
    }
  }

  // ---- 模式二 paper：墨晕拖尾（鼠标在宣纸上划出墨痕，晕开淡出）----
  var ink=[];
  function fxPaper(){
    // 鼠标移动才产墨点（间距>7px 一个，带随机偏移像笔锋）
    var mdx=mouse.x-mouse.lx, mdy=mouse.y-mouse.ly;
    if (mdx*mdx+mdy*mdy>49){
      ink.push({x:mouse.x+(Math.random()-.5)*6, y:mouse.y+(Math.random()-.5)*6,
                r:2+Math.random()*3, life:1});
      mouse.lx=mouse.x; mouse.ly=mouse.y;
    }
    for (var i=ink.length-1;i>=0;i--){ var k=ink[i];
      k.life-=0.006;                       // 慢慢消散
      k.r+=0.06;                           // 墨在纸里晕开
      if (k.life<=0){ ink.splice(i,1); continue; }
      ctx.beginPath(); ctx.arc(k.x,k.y,k.r,0,6.283);
      ctx.fillStyle='rgba(70,60,45,'+(k.life*0.10).toFixed(3)+')'; ctx.fill();
    }
    if (ink.length>140) ink.splice(0, ink.length-140);
  }

  // ---- 模式三 term：数据雨（稀疏字符列，克制下落）----
  var CH='01<>/{}[]#$%&*+=?'; 
  var rain=[];
  (function mkRain(){ var cols=Math.floor(innerWidth/90);   // 90px 一列，很稀
    for (var i=0;i<cols;i++) rain.push({x:i*90+20, y:Math.random()*-innerHeight,
      v:1.2+Math.random()*1.6, len:5+Math.floor(Math.random()*7), t:0});
  })();
  function fxTerm(){
    ctx.font='12px Consolas,monospace';
    for (var i=0;i<rain.length;i++){ var rp=rain[i];
      rp.y+=rp.v; rp.t++;
      for (var j=0;j<rp.len;j++){ var y=rp.y-j*14;
        if (y<-14||y>cv.height+14) continue;
        var a=(1-j/rp.len)*(j===0?0.9:0.45);   // 头亮尾淡
        ctx.fillStyle='rgba(74,246,38,'+a+')';
        ctx.fillText(CH[(i*7+j*3+rp.t)%CH.length|0], rp.x, y);
      }
      if (rp.y-rp.len*14>cv.height){ rp.y=-Math.random()*300; rp.v=1.2+Math.random()*1.6; }
    }
  }

  (function loop(){
    ctx.clearRect(0,0,cv.width,cv.height);
    var s=skin();
    if (s==='paper') fxPaper();
    else if (s==='term') fxTerm();
    else fxDark();
    requestAnimationFrame(loop);
  })();
})();

// ---- 三套皮肤切换（登录页/门户页共用逻辑，选择存 localStorage）----
const SKINS=[['dark','璃青'],['paper','素白'],['term','终端']];
let _fcCur=localStorage.getItem('fc_skin')||'dark';
if(!SKINS.some(s=>s[0]===_fcCur))_fcCur='dark';
function _fcSkinApply(){document.body.dataset.skin=_fcCur;
  const b=document.getElementById('skin');if(b)b.textContent='🎨 '+SKINS.find(s=>s[0]===_fcCur)[1];}
_fcSkinApply();
document.getElementById('skin').onclick=()=>{
  _fcCur=SKINS[(SKINS.findIndex(s=>s[0]===_fcCur)+1)%SKINS.length][0];
  localStorage.setItem('fc_skin',_fcCur);_fcSkinApply();};
const fmtSize=n=>n>=1073741824?(n/1073741824).toFixed(2)+' GB'
  :n>=1048576?(n/1048576).toFixed(1)+' MB':(n/1024).toFixed(0)+' KB';
const fmtTs=ms=>{const d=new Date(ms);return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')
  +'-'+String(d.getDate()).padStart(2,'0')+' '+String(d.getHours()).padStart(2,'0')
  +':'+String(d.getMinutes()).padStart(2,'0')};
const esc=s=>String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function load(){
  try{
    const j=await(await fetch('/api/versions')).json();
    if(!j.ok){location.replace('/');return}
    const el=document.getElementById('body');
    if(!j.items.length){el.innerHTML='<div class="card empty">还没有发布过版本——发布者跑一次打包.bat 再来</div>';return}
    const top=j.items[0];
    let h='<div class="card hero"><div class="lab">LATEST RELEASE · 最新版本</div>'
      +'<div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap"><h2>v'+esc(top.version)+'</h2>'
      +'<span class="badge">LATEST</span></div>'
      +'<div class="meta"><span>📅 '+fmtTs(top.mtime)+'</span><span>📦 '+fmtSize(top.size)+'</span>'
      +(top.sha1?'<span class="sha" title="'+esc(top.sha1)+'">sha1 '+esc(top.sha1.slice(0,12))+'…</span>':'')+'</div>'
      +(top.notes?'<div class="notes">'+esc(top.notes)+'</div>'
        :'<div class="notes" style="color:var(--muted)">（本版未写更新说明——发布者在项目根 RELEASE_NOTES.md 写好后重新打包，说明会随版本带上）</div>')
      +'<div class="row"><button class="btn" data-dl="'+top.url+'" data-n="'+esc(top.file)+'">⬇ 下载整包</button>'
      +'<span data-dlst style="font-size:12px;color:var(--muted)">下载后解压即完成安装</span></div></div>';
    // 离线资源包独立卡片（用户定调「离线包和实际包分开」）：不是应用版本，
    // 不占 hero、不进更新日志；包名不带版本号——内容与工具版本无关
    if(j.offline&&j.offline.url){
      h+='<div class="card" style="padding:16px 22px;margin-bottom:28px;display:flex;align-items:center;gap:16px;flex-wrap:wrap">'
        +'<div style="flex:1;min-width:240px">'
        +'<div style="font-size:14px;font-weight:650">🧰 离线资源包'
        +'<span style="font-size:11px;font-weight:400;color:var(--muted);margin-left:8px">OFFLINE PKG</span></div>'
        +'<div style="font-size:12px;color:var(--muted);margin-top:5px">📅 '+fmtTs(j.offline.mtime)+' · 📦 '+fmtSize(j.offline.size)
        +(j.offline.subset
          ? ' · <b style="color:#e8a33d">子集包——只含部分资源，不能用于全新机器</b>，请让发布者上传完整资源包'
          : (j.offline.format==='fcpk'
            ?' · 无外网机器部署资源（WebView2 / .NET / Node / Git / claude-code / Python 依赖 / OnlyOffice），加密资源包，<b style="color:var(--fg)">须用工具安装（双击打不开）</b>'
            :' · 无外网机器部署资源（Git / Node / claude-code / Python 依赖），与工具版本无关'))
        +'</div></div>'
        +'<button class="btn" data-dl="'+esc(j.offline.url)+'" data-n="'+esc(j.offline.file)+'" style="flex-shrink:0">⬇ 下载'+(j.offline.format==='fcpk'?'资源包':'离线包')+'</button></div>';
    }
    const rest=j.items.slice(1);
    if(rest.length){
      // 历史更新日志默认收起（用户定调「只有点开才显示」）：标题条兼开关，
      // 默认页面只呈现最新版大卡 + 离线资源包，点标题才展开历史条目
      h+='<div id="hlog" title="点击展开/收起历史更新日志" style="font-size:12px;color:var(--muted);letter-spacing:2px;margin:26px 0 12px;cursor:pointer;user-select:none">▸ 更新日志 · 历史版本 '+rest.length+' 条</div>'
        +'<div class="vlist" id="hlogList" style="display:none">';
      for(const it of rest){
        h+='<div class="card vitem" style="align-items:flex-start"><div class="vmain">'
          +'<div class="vname">v'+esc(it.version)
          +' <span style="font-size:11px;font-weight:400;color:var(--muted);margin-left:6px">'
          +(it.file?fmtTs(it.mtime):'历史回溯')+'</span></div>'
          +(it.notes?'<div style="margin-top:8px;font-size:12.5px;line-height:1.8;white-space:pre-wrap;color:var(--notes,inherit)">'
            +esc(it.notes)+'</div>'
            :'<div class="vmeta" style="margin-top:6px">（该版无记录说明）</div>')
          +'</div></div>';
      }
      h+='</div>';
    }
    el.innerHTML=h;
    const hlog=document.getElementById('hlog'), hlist=document.getElementById('hlogList');
    if(hlog) hlog.onclick=()=>{
      const open=hlist.style.display!=='none';
      hlist.style.display=open?'none':'';
      hlog.textContent=(open?'▸':'▾')+' 更新日志 · 历史版本 '+rest.length+' 条';
    };
  }catch(e){document.getElementById('body').innerHTML=
    '<div class="card empty">加载失败：'+esc(e)+'</div>'}
}
// v2.2.1 下载走 fetch→Blob→a.download：Chrome/Edge 对 HTTP（非 HTTPS）
// 站点的可执行文件下载默认静默拦截（insecure download blocking），直接
// <a href> 点击毫无反应（用户两次实锤）。Blob 是页面内本地生成，不受该
// 策略限制；fetch 失败（网络异常）兜底退回导航式让浏览器给提示条。
el_body=document.getElementById('body');
el_body.addEventListener('click', async (e)=>{
  const b=e.target.closest('[data-dl]');
  if(!b) return;
  const url=b.dataset.dl, name=b.dataset.n||'download.exe';
  const st=document.querySelector('[data-dlst]');
  const old=b.textContent;
  b.disabled=true; b.textContent='下载中…';
  if(st) st.textContent='正在拉取 '+name+' …';
  try{
    const r=await fetch(url);
    if(!r.ok) throw new Error('HTTP '+r.status);
    const blob=await r.blob();
    const u=URL.createObjectURL(blob);
    const a=document.createElement('a');
    a.href=u; a.download=name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(()=>URL.revokeObjectURL(u), 60000);
    if(st) st.textContent='已开始下载 '+name+'（浏览器下载列表可见）';
  }catch(err){
    if(st) st.textContent='浏览器下载失败，尝试直接打开…';
    location.href=url;
  }
  b.disabled=false; b.textContent=old;
});
document.getElementById('out').onclick=async()=>{
  try{await fetch('/api/logout',{method:'POST'})}catch(_){}
  location.replace('/');
};
load();
</script></body></html>"""


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------
class _Handler(BaseHTTPRequestHandler):
    # 类属性由 start() 注入（handler 每请求新建实例，闭包不可用）
    root = ""

    # ---- 工具方法 ----
    def _cookie_token(self):
        raw = self.headers.get("Cookie") or ""
        for part in raw.split(";"):
            k, _, v = part.strip().partition("=")
            if k == "fc_token":
                return v
        return ""

    def _session_ok(self):
        tok = self._cookie_token()
        exp = _sessions.get(tok)
        if exp is None or exp < time.time():
            _sessions.pop(tok, None)
            return False
        return True

    def _text(self, code, body, ctype="text/plain; charset=utf-8", extra=None):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or []):
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj, extra=None):
        self._text(code, json.dumps(obj, ensure_ascii=False),
                   "application/json; charset=utf-8", extra)

    def _file(self, path, ctype):
        try:
            size = os.path.getsize(path)
            # 对抗审 P2：706MB 资源包无断点续传——断线从零重来。支持
            # Range: bytes=start-end / bytes=start-（206 + Content-Range）
            rng = (self.headers.get("Range") or "").strip()
            m = re.match(r"bytes=(\d+)-(\d*)$", rng) if rng else None
            if m:
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else size - 1
                # 对抗审二轮 P3-1：反转区间/越界起点一律 416（曾算出负长度）
                if start >= size or end < start:
                    self._text(416, '{"ok":false,"err":"range not satisfiable"}',
                               "application/json; charset=utf-8")
                    return
                end = min(end, size - 1)
                self.send_response(206)
                self.send_header("Content-Range",
                                 "bytes %d-%d/%d" % (start, end, size))
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(end - start + 1))
                self.send_header("Content-Disposition",
                                 "attachment; filename=download.bin; "
                                 "filename*=UTF-8''%s"
                                 % quote(os.path.basename(path)))
                self.end_headers()
                if self.command != "HEAD":
                    with open(path, "rb") as f:
                        f.seek(start)
                        left = end - start + 1
                        while left > 0:
                            chunk = f.read(min(1 << 18, left))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            left -= len(chunk)
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(size))
            self.send_header("Accept-Ranges", "bytes")
            # manifest 短缓存（发布后 1 分钟内必见）；exe 长缓存（文件名含版本号，内容不可变）
            self.send_header("Cache-Control",
                             "max-age=%d" % (_MAX_AGE if ctype.startswith("application/json")
                                             else 3600))
            # 浏览器直接打开 → 下载而不是尝试执行；中文文件名走 RFC 5987
            self.send_header("Content-Disposition",
                             "attachment; filename=download.bin; filename*=UTF-8''%s"
                             % quote(os.path.basename(path)))
            self.end_headers()
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(1 << 18)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass   # 客户端中断（下载取消/工具端断开），正常
        except Exception as e:
            try:
                self._text(500, str(e)[:200])
            except Exception:
                pass

    # ---- GET ----
    def do_GET(self):
        root = _Handler.root or _releases_dir()
        raw = self.path.split("?", 1)[0].split("#", 1)[0]
        name = unquote(raw.lstrip("/"))

        if name in ("", "index.html"):
            # Host 头自带端口（ip:port）——直接用；缺失才自拼（v2.3.2 修
            # 端口重复 bug：Host 含端口时再拼 :PORT 得出 :8765:8765，用户实锤）
            host = self.headers.get("Host") or "%s:%d" % (_lan_ip(), PORT)
            url = "http://%s/" % host
            icon = "data:image/png;base64," + _app_icon_b64()
            if self._session_ok():
                page = (_PORTAL_HTML.replace("__CSS__", _CSS)
                        .replace("__URL__", _esc(url))
                        .replace("__ICON__", icon))
                self._text(200, page, "text/html; charset=utf-8")
            else:
                page = (_LOGIN_HTML.replace("__CSS__", _CSS)
                        .replace("__DEFPWD__", _DEFAULT_PWD)
                        .replace("__ICON__", icon))
                self._text(200, page, "text/html; charset=utf-8")
            return

        if name == "api/versions":
            if not self._session_ok():
                self._json(401, {"ok": False, "err": "未登录"})
                return
            items = _versions()
            # sha1 只在 manifest（最新版）——历史版没有，不现算（发布目录可能几十个包）
            try:
                with open(os.path.join(root, "manifest.json"), encoding="utf-8") as f:
                    m = json.load(f)
                for it in items:
                    if it["version"] == str(m.get("version")):
                        it["sha1"] = str(m.get("sha1") or "")
            except Exception:
                pass
            self._json(200, {"ok": True, "items": items,
                             "offline": _offline_pkg()})
            return

        if name == "manifest.json":
            p = _safe_path(root, name)
            if p and os.path.isfile(p):
                self._file(p, "application/json")
            else:
                self._text(404, "not found")
            return

        # v3.5.290（工具说明书 tab）：配置教程截图（manual/*.png，登录态
        # 可见；_safe_path 防穿越；只放行 png）
        if name.startswith("manual/"):
            if not self._session_ok():
                self._text(401, "not found")
                return
            p = _safe_path(root, name)
            if p and os.path.isfile(p) and p.lower().endswith(".png"):
                self._file(p, "image/png")
            else:
                self._text(404, "not found")
            return

        # 版本包文件：manifest/整包下载双通道共用，不做登录校验
        # （同事工具无浏览器态；完整性由 manifest sha1 保证）
        # a333R（第4轮 P1-1，实测死链）：这里漏了 lower——_offline_pkg 能把
        # `…-资源包.FCPK` 认成主包并在门户展示，但点下载必 404。
        if name.lower().endswith((".zip", ".exe", ".fcpk")):
            p = _safe_path(root, name)
            if p and os.path.isfile(p):
                self._file(p, "application/octet-stream")
                return
        self._text(404, "not found")

    # ---- POST ----
    def do_POST(self):
        raw = self.path.split("?", 1)[0].lstrip("/")
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(min(n, 4096)).decode("utf-8")) if n else {}
        except Exception:
            body = {}
        # a238 P3：JSON 数组/字符串顶替对象时 (body or {}).get 抛 AttributeError →
        # BaseHTTPRequestHandler 打 traceback；统一归一到 dict
        if not isinstance(body, dict):
            body = {}
        if raw == "api/login":
            time.sleep(0.3)   # 轻微节流：暴力试密码的成本下限
            # a238 P3：常数时间比较（secrets.compare_digest）
            _pw = str(body.get("password") or "")
            if not secrets.compare_digest(_pw, _portal_password()):
                self._json(401, {"ok": False, "err": "密码不对"})
                return
            tok = secrets.token_urlsafe(24)
            # a238 P3：登录路径顺手清过期 token（字典长开服务无界增长）
            _now = time.time()
            for k in [k for k, exp in _sessions.items() if exp < _now]:
                _sessions.pop(k, None)
            _sessions[tok] = _now + _SESSION_TTL
            self._json(200, {"ok": True}, [("Set-Cookie",
                          "fc_token=%s; Path=/; HttpOnly; SameSite=Strict; Max-Age=%d"
                          % (tok, _SESSION_TTL))])
            return
        if raw == "api/logout":
            _sessions.pop(self._cookie_token(), None)
            self._json(200, {"ok": True}, [("Set-Cookie",
                          "fc_token=; Path=/; Max-Age=0")])
            return
        self._json(404, {"ok": False, "err": "not found"})

    def log_message(self, fmt, *args):
        pass   # 静默：不刷屏（下载日志无价值）


_server = None
_lock = threading.Lock()


def is_running():
    return _server is not None


def start():
    """按需拉起（幂等）。返回 (ok, msg)。"""
    global _server
    with _lock:
        if _server is not None:
            return True, "已在运行"
        root = _releases_dir()
        if not os.path.isdir(root):
            return False, "发布目录不存在：%s（先跑一次打包.bat）" % root
        _Handler.root = root
        try:
            srv = ThreadingHTTPServer(("0.0.0.0", PORT), _Handler)
        except OSError as e:
            return False, "端口 %d 起不来（被占用/防火墙拒）：%s" % (PORT, e)
        srv.daemon_threads = True
        _server = srv
        threading.Thread(target=srv.serve_forever, daemon=True,
                         name="update-server").start()
        return True, "http://%s:%d/ （发布目录 %s）" % (_lan_ip(), PORT, root)


def stop():
    global _server
    with _lock:
        srv, _server = _server, None
    if srv is not None:
        # v2.2.1 同步收尾（原异步 shutdown）：热重载要立刻重新 bind 同端口，
        # 等旧 listener 干净退出再返回
        # a238 P2（第5轮A1）：BaseServer.shutdown 签名是 (self)——传 timeout=
        # 必抛 TypeError 且被 except 吞掉，serve_forever 线程从未被真正停过，
        # 热重载 rebind 撞旧线程的「端口被占用」假报错由此而来
        try:
            srv.shutdown()
        except Exception:
            pass
        try:
            srv.server_close()
        except Exception:
            pass


def status():
    """设置页显示用：运行态 + 同事升级地址 + 已发布版本。
    code_ver=本模块代码版本（_APP_VER）：热重载后随之变化，发布者开关一次
    即可肉眼确认新代码已生效。"""
    base = {"code_ver": _APP_VER, "port": PORT,
            "dir": _releases_dir(), "lan_ip": _lan_ip()}
    if _server is None:
        return {"running": False, **base}
    m = None
    try:
        with open(os.path.join(_releases_dir(), "manifest.json"),
                  encoding="utf-8") as f:
            m = json.load(f)
    except Exception:
        pass
    return {"running": True, **base,
            "published": (m or {}).get("version") or "",
            "url": "http://%s:%d/" % (_lan_ip(), PORT)}
