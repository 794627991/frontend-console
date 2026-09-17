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
import os, sys, json, time, html, secrets, threading, socket
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import unquote, quote

PORT = 8765
_MAX_AGE = 60          # manifest 缓存友好：发布后同事 1 分钟内必见新版
_SESSION_TTL = 12 * 3600
_DEFAULT_PWD = "888888"
_APP_VER = "2.2.0"


# ---------------------------------------------------------------------------
# 基础设施
# ---------------------------------------------------------------------------
def _releases_dir():
    """dist/releases 绝对路径（源码跑=项目根/dist/releases；frozen=exe 旁）。
    发布机是源码形态（要跑打包.bat），frozen 分支只是兜底。"""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.dirname(os.path.abspath(sys.executable)))
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
                    notes[n[7:-3]] = f.read().strip()[:500]
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
        if not (n.endswith(".exe") and "-v" in n):
            continue
        ver = n.rsplit("-v", 1)[-1][:-4] if n.endswith(".exe") else ""
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
    items.sort(key=lambda x: _ver_tuple(x["version"]), reverse=True)
    return items


# ---------------------------------------------------------------------------
# 页面（全内嵌：深色玻璃拟态门户，不依赖项目 web/ 资源）
# ---------------------------------------------------------------------------
def _esc(s):
    return html.escape(str(s or ""), quote=True)


_CSS = """
*{margin:0;padding:0;box-sizing:border-box}
:root{--fg:#e8ecf4;--muted:#8b94a7;--line:rgba(255,255,255,.08);
  --card:rgba(255,255,255,.04);--accent:#4f8cff;--accent2:#22d3ee}
body{font-family:system-ui,-apple-system,'Segoe UI','Microsoft YaHei',sans-serif;
  color:var(--fg);min-height:100vh;background:#0b1020;overflow-x:hidden}
body::before,body::after{content:'';position:fixed;border-radius:50%;
  filter:blur(120px);opacity:.32;pointer-events:none;z-index:0}
body::before{width:560px;height:560px;left:-140px;top:-160px;background:#1d4ed8}
body::after{width:520px;height:520px;right:-160px;bottom:-140px;background:#0891b2}
.wrap{position:relative;z-index:1;max-width:880px;margin:0 auto;padding:40px 24px 80px}
.brand{display:flex;align-items:center;gap:14px;margin-bottom:38px}
.logo{width:44px;height:44px;border-radius:12px;display:grid;place-items:center;
  font-size:22px;background:linear-gradient(135deg,var(--accent),var(--accent2));
  box-shadow:0 6px 24px rgba(79,140,255,.35)}
.brand h1{font-size:19px;font-weight:650;letter-spacing:.5px}
.brand .sub{font-size:12px;color:var(--muted);margin-top:3px}
.spacer{flex:1}
.status{display:flex;align-items:center;gap:7px;font-size:12px;color:var(--muted);
  background:var(--card);border:1px solid var(--line);padding:7px 13px;border-radius:99px}
.dot{width:7px;height:7px;border-radius:50%;background:#34d399;
  box-shadow:0 0 8px #34d39988;animation:pulse 2.2s infinite}
@keyframes pulse{50%{opacity:.45}}
.card{background:var(--card);border:1px solid var(--line);border-radius:20px;
  backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px)}
.hero{padding:28px 30px;margin-bottom:28px;position:relative;overflow:hidden}
.hero::before{content:'';position:absolute;inset:0;
  background:linear-gradient(120deg,rgba(79,140,255,.10),transparent 55%)}
.hero .lab{font-size:12px;color:var(--accent2);letter-spacing:2px;margin-bottom:10px}
.hero h2{font-size:34px;font-weight:750;font-family:ui-monospace,Consolas,monospace}
.hero .meta{display:flex;gap:18px;flex-wrap:wrap;margin-top:12px;font-size:13px;color:var(--muted)}
.hero .notes{margin-top:16px;font-size:13.5px;line-height:1.75;color:#c3cad9;
  white-space:pre-wrap;max-height:180px;overflow:auto}
.btn{display:inline-flex;align-items:center;gap:8px;border:none;cursor:pointer;
  font-size:13.5px;font-weight:600;color:#fff;padding:10px 20px;border-radius:11px;
  background:linear-gradient(135deg,var(--accent),var(--accent2));
  box-shadow:0 4px 18px rgba(79,140,255,.30);transition:.18s;text-decoration:none}
.btn:hover{transform:translateY(-1px);box-shadow:0 8px 26px rgba(79,140,255,.42)}
.btn:disabled{opacity:.5;cursor:default;transform:none}
.btn.ghost{background:var(--card);border:1px solid var(--line);box-shadow:none;color:var(--fg)}
.btn.ghost:hover{border-color:rgba(255,255,255,.22)}
.hero .row{display:flex;align-items:center;gap:14px;margin-top:22px;flex-wrap:wrap}
.badge{font-size:10.5px;font-weight:700;letter-spacing:1.5px;padding:4px 11px;
  border-radius:99px;background:linear-gradient(135deg,#34d399,#22d3ee);color:#04121a}
.vlist{display:flex;flex-direction:column;gap:12px}
.vitem{display:flex;align-items:center;gap:18px;padding:18px 22px;transition:.18s}
.vitem:hover{border-color:rgba(255,255,255,.16);background:rgba(255,255,255,.06)}
.vmain{flex:1;min-width:0}
.vname{font-family:ui-monospace,Consolas,monospace;font-size:16.5px;font-weight:650}
.vmeta{font-size:12px;color:var(--muted);margin-top:5px;display:flex;gap:14px;flex-wrap:wrap}
.sha{font-family:ui-monospace,Consolas,monospace}
.empty{text-align:center;color:var(--muted);padding:70px 0;font-size:14px}
.tip{margin-top:26px;font-size:12.5px;color:var(--muted);line-height:1.9;
  background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 20px}
.tip b{color:#aab6cc}
/* 登录页 */
.login-wrap{min-height:100vh;display:grid;place-items:center;position:relative;z-index:1}
.login{width:min(380px,92vw);padding:38px 34px;text-align:center}
.login .logo{margin:0 auto 18px;width:56px;height:56px;font-size:28px;border-radius:16px}
.login h1{font-size:18px;font-weight:680;margin-bottom:6px}
.login .sub{font-size:12.5px;color:var(--muted);margin-bottom:28px}
.login input{width:100%;padding:12px 16px;font-size:14px;color:var(--fg);
  background:rgba(255,255,255,.05);border:1px solid var(--line);border-radius:12px;
  outline:none;transition:.18s;margin-bottom:14px}
.login input:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(79,140,255,.18)}
.login .btn{width:100%;justify-content:center;padding:12px}
.err{color:#f87171;font-size:12.5px;min-height:18px;margin-bottom:8px}
.shake{animation:shake .4s}
@keyframes shake{20%,60%{transform:translateX(-6px)}40%,80%{transform:translateX(6px)}}
"""

_LOGIN_HTML = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>前端控制台 · 发布中心</title><style>__CSS__</style></head><body>
<div class="login-wrap"><div class="card login">
  <div class="logo">⬆</div>
  <h1>前端控制台 · 发布中心</h1>
  <div class="sub">版本下发与升级门户 · 仅限内网</div>
  <div class="err" id="err"></div>
  <input type="password" id="pwd" placeholder="访问密码" autofocus autocomplete="current-password">
  <button class="btn" id="go">进入</button>
  <div class="sub" style="margin:22px 0 0;">默认密码 __DEFPWD__（发布者可在工具 设置→关于与升级 中修改）</div>
</div></div>
<script>
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

_PORTAL_HTML = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>前端控制台 · 发布中心</title><style>__CSS__</style></head><body>
<div class="wrap">
  <div class="brand">
    <div class="logo">⬆</div>
    <div><h1>前端控制台 · 发布中心</h1>
      <div class="sub">__URL__ · 发布目录只读分发</div></div>
    <div class="spacer"></div>
    <div class="status"><span class="dot"></span>服务在线</div>
    <button class="btn ghost" id="out" style="padding:7px 14px;font-size:12px;">退出</button>
  </div>
  <div id="body"><div class="empty">版本加载中…</div></div>
  <div class="tip">
    <b>整包安装</b>：下载最新版 exe，替换旧文件即可（旁挂 offline_pkg / 数据目录不受影响）。<br>
    <b>工具内热更新</b>：把地址 <b>__URL__</b> 填到工具「设置 → 关于与升级 → 升级服务器地址」，
    以后有新版工具会自动检查、一键升级（旧版自动备份为 .bak 可回退）。
  </div>
</div>
<script>
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
      +'<span data-dlst style="font-size:12px;color:var(--muted)">下载后替换旧 exe 即完成升级</span></div></div>';
    const rest=j.items.slice(1);
    if(rest.length){
      h+='<div style="font-size:12px;color:var(--muted);letter-spacing:2px;margin:26px 0 12px">历史版本</div><div class="vlist">';
      for(const it of rest){
        h+='<div class="card vitem"><div class="vmain"><div class="vname">v'+esc(it.version)+'</div>'
          +'<div class="vmeta"><span>📅 '+fmtTs(it.mtime)+'</span><span>📦 '+fmtSize(it.size)+'</span></div>'
          +(it.notes?'<div class="vmeta" style="margin-top:6px;white-space:pre-wrap;color:#c3cad9">'+esc(it.notes.slice(0,200))+(it.notes.length>200?'…':'')+'</div>':'')
          +'</div>'
          +'<button class="btn ghost" data-dl="'+it.url+'" data-n="'+esc(it.file)+'">下载</button></div>';
      }
      h+='</div>';
    }
    el.innerHTML=h;
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
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(size))
            # manifest 短缓存（发布后 1 分钟内必见）；exe 长缓存（文件名含版本号，内容不可变）
            self.send_header("Cache-Control",
                             "max-age=%d" % (_MAX_AGE if ctype.startswith("application/json")
                                             else 3600))
            # 浏览器直接打开 → 下载而不是尝试执行；中文文件名走 RFC 5987
            self.send_header("Content-Disposition",
                             "attachment; filename=download.exe; filename*=UTF-8''%s"
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
            url = "http://%s:%d/" % (self.headers.get("Host") or
                                     ("%s:%d" % (_lan_ip(), PORT)), PORT)
            if self._session_ok():
                page = _PORTAL_HTML.replace("__CSS__", _CSS).replace("__URL__", _esc(url))
                self._text(200, page, "text/html; charset=utf-8")
            else:
                page = _LOGIN_HTML.replace("__CSS__", _CSS).replace("__DEFPWD__", _DEFAULT_PWD)
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
            self._json(200, {"ok": True, "items": items})
            return

        if name == "manifest.json":
            p = _safe_path(root, name)
            if p and os.path.isfile(p):
                self._file(p, "application/json")
            else:
                self._text(404, "not found")
            return

        # 版本包文件：manifest/整包下载双通道共用，不做登录校验
        # （同事工具无浏览器态；完整性由 manifest sha1 保证）
        if name.endswith(".exe"):
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
        if raw == "api/login":
            time.sleep(0.3)   # 轻微节流：暴力试密码的成本下限
            if str((body or {}).get("password") or "") != _portal_password():
                self._json(401, {"ok": False, "err": "密码不对"})
                return
            tok = secrets.token_urlsafe(24)
            _sessions[tok] = time.time() + _SESSION_TTL
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
        # 等旧 listener 干净退出再返回（最多 2s）
        try:
            srv.shutdown(timeout=2)
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
