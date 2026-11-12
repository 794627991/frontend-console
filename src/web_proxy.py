# -*- coding: utf-8 -*-
"""Web 代理模块（a507 自 server.py 拆分解耦）。

网页 tab 的全部服务端逻辑集中于此，server.py 只留一行注册（蓝图路由
路径不变，前端零感知）。三层结构：

纯函数（tests 直测）
    _web_detect_charset     charset 三跳探测（a473）
    _web_html_to_text       HTML→纯文本（a473「发给 Claude」）
    _proxy_url_rewrite      资源 URL → 路径式代理 URL（a502/a506）
    _proxy_sanitize_setcookie  Set-Cookie 域适配清洗（a505）

路由（蓝图 bp）
    /api/web/proxy              query 式（a502 原始形态，兼容旧收藏）
    /api/web/proxy/<sch>/<rest> 路径式（a506 主形态，publicPath 语义正确）
    /api/web/fetch_text         取页转纯文本（a473）

app 级挂钩（register）
    404 兜底——蓝图级 errorhandler 拦不到全局 404（未匹配路由的
    location.href 跳转），必须注册在 app 上

演进史（a473→a506）详见各函数 docstring 与 git log。"""

import threading

import requests as _requests
try:
    from urllib3.exceptions import InsecureRequestWarning
    import urllib3 as _u3
    _u3.disable_warnings(InsecureRequestWarning)
except Exception:
    pass

from flask import Blueprint, Response, jsonify, redirect, request

bp = Blueprint("web_proxy", __name__)

_THREAD_LOCAL = threading.local()   # a511：线程局部代理连接池
_CSD_SENT = []                      # a512：进程内一次性清缓存标记


def _web_detect_charset(headers_ct, raw):
    """a473/审计修：charset 三跳探测（纯函数，tests 直测）。

    ① Content-Type 的 charset=（RFC 9110 允许带引号 charset="GBK"——
    审计实证带引号形态原正则失配回落 utf-8 全页乱码）
    ② body 前 2KB 的 <meta charset=…>（老内网页只写 meta 不写 header）
    ③ 兜底 utf-8"""
    import re as _re
    m = _re.search(r'charset=["\']?([\w-]+)', (headers_ct or "").lower())
    if m:
        return m.group(1)
    head = raw[:2048].decode("ascii", "replace").lower()
    m = _re.search(r'<meta[^>]+charset=["\']?([\w-]+)', head)
    if m:
        return m.group(1)
    return "utf-8"


def _web_html_to_text(html_src):
    """a473/审计修：HTML→纯文本（纯函数）。返回 (title, body)。"""
    import html as _html
    import re as _re
    title = ""
    m = _re.search(r"<title[^>]*>([\s\S]*?)</title>", html_src, _re.I)
    if m:
        title = _html.unescape(_re.sub(r"\s+", " ", m.group(1))).strip()[:120]
    # 审计修（隐藏级）：re.sub 第 4 个位置参数是 count 不是 flags——
    # (…, body, _re.I) 等于 count=2，每种替换最多做 2 次（长页面第 3 个
    # script 起全部漏剥）。flags 一律关键字传参
    body = _re.sub(r"<(script|style|noscript|title)[^>]*>[\s\S]*?</\1>", " ",
                   html_src, flags=_re.I)
    body = _re.sub(r"<!--[\s\S]*?-->", " ", body)
    body = _re.sub(r"<br\s*/?>|</p>|</div>|</tr>|</li>|</h[1-6]>", "\n",
                   body, flags=_re.I)
    body = _re.sub(r"<[^>]+>", " ", body)
    body = _html.unescape(body)
    body = _re.sub(r"[ \t\r\f\v]+", " ", body)
    body = _re.sub(r"\n\s*\n\s*", "\n", body)
    body = "\n".join(ln.strip() for ln in body.splitlines() if ln.strip())
    if body.startswith("\ufeff"):
        body = body[1:].lstrip()   # 审计观察：BOM 残留正文首行（连带其后紧邻的标签占位空格）
    return title, body


# ---- a502：Web 代理（用户令「网页里的链接必须在工具内正常打开显示」）----
# 根因：内网代理对带 Referer 的响应注入 X-Frame-Options: sameorigin，
# iframe 子页导航被拒（a495–a501 七版在 WebView2 层的修改全部不可行）。
# 方案：iframe src 改为 /api/web/proxy?url=<encoded>——同源无 XFO 限制。
# 静态资源（img/js/css）通过注入 <base> 从原始服务器加载（XFO 不影响
# 子资源）；<a> 点击由注入的 JS 拦截 → postMessage → 父页面代理导航。

_PROXY_NAV_JS = r"""<script>
(function(){
  window.__pxNav = 1;   // a521：子 iframe 注入去重标记
  // a506：路径式代理前缀——webpack 取 currentScript.src 的 dirname 做
  // publicPath，query 式会折叠成 /api/web/ 导致动态 chunk 404；路径式
  // 的 dirname 还原出 CDN 基址，相对 chunk 自动落回代理路由。
  // a508：不再注入 <base href="原始URL">——SPA router（Vue/React）按
  // baseURI 拼绝对 URL，会把当前代理路径拼到原始域上整页跳出代理
  // （掘金实锤：跳到 juejin.cn/api/web/proxy/... 后白屏「打不开」）。
  // 相对 URL 解析基准改用注入的 _orig（本页原始 URL 常量）。
  var _orig = __PX_ORIG__;
  // a508：SPA pathname 伪装——代理路径 /api/web/proxy/<sch>/<host>/<path>
  // 会被 Vue/React router 当成路由路径（掘金 router 直接 404「找不到页
  // 面」；GitHub hydration 的路径校验同源）。replaceState 同源合法地把
  // 地址栏 pathname 还原成原始路径，router/相对解析回到原生语义。
  // 代价：404 兜底不能再从 Referer 还原基址（pathname 已不含代理前缀）
  // → 原始 URL 存 sessionStorage，兜底页客户端还原。
  try{
    sessionStorage.setItem('__px_orig', _orig);
    var _ou = new URL(_orig);
    history.replaceState(null, '', _ou.pathname + _ou.search);
  }catch(_){}
  // a516：诊断透传——资源加载失败（script/img 404 等，捕获阶段 e.target
  // 是元素）与 JS 运行错误的完整 URL/消息打到本窗口 console（工具 F12
  // 可见）。此前只能看到截断的文件名（runtime.xxx.js:1 Unexpected
  // token '<'），无法定位请求真实打到了哪里。
  window.addEventListener('error', function(e){
    try{
      if (e.target && e.target.src){
        console.warn('[px-res-fail]', e.target.tagName, String(e.target.src).slice(0, 200));
      } else {
        console.warn('[px-js-err]', String(e.message||'').slice(0, 160),
                     String(e.filename||'').slice(0, 120) + ':' + e.lineno);
      }
    }catch(_){}
  }, true);
  var _pb = location.origin + '/api/web/proxy/';
  function _px(u){
    if (!u || u[0]==='#' || u.indexOf('data:')===0 || u.indexOf('blob:')===0
        || u.indexOf('javascript:')===0) return null;
    try{
      var a = new URL(u, _orig);
      // a515：同源 ≠ 已代理——a508 的 pathname 伪装后，页面 JS 以
      // 伪装 location 拼出的工具域相对/绝对 URL（如 runtime.xxx.js?hash）
      // 也同源，原判定放行 → 打到 Flask 404（默认 404 页是 HTML）→
      // 脚本 Unexpected token '<'（SSO 实锤，Fingerprint2 同通道）。
      // 处理：真代理路径（/api/web/proxy/ 前缀）放行；其余同源 URL 把
      // path+query 重挂回原始域再代理化。
      if (a.origin === location.origin){
        if (a.pathname.indexOf('/api/web/proxy/') === 0) return null;
        a = new URL(a.pathname + a.search, _orig);
      }
      if (a.origin === location.origin) return null;   // 防御（原始域=工具域）
      return _pb + a.protocol.replace(':','') + '/' + a.host
             + a.pathname + a.search;
    }catch(_){ return null; }
  }
  function _rw(el){
    if (!el || !el.tagName) return;
    var tag = el.tagName.toUpperCase();
    if (tag!=='IMG' && tag!=='SCRIPT' && tag!=='LINK' && tag!=='SOURCE'
        && tag!=='IFRAME' && tag!=='VIDEO' && tag!=='AUDIO' && tag!=='EMBED') return;
    var attrs = ['src','href','data-src','poster'];
    for (var i=0;i<attrs.length;i++){
      var v = el.getAttribute(attrs[i]);
      if (v){
        var p = _px(v);
        if (p) el.setAttribute(attrs[i], p);
      }
    }
  }
  // a513：innerHTML / document.write 注入的 HTML 串同步重写——这两个
  // 通道只有 MutationObserver 异步兜底，回调执行前浏览器已开始下载原始
  // URL → 内网透明代理返回注入页（HTML）→ 脚本执行 Unexpected token
  // '<'（SSO 工作台实锤）。赋值阶段在字符串上直接替换，窗口归零。
  // a517：属性值支持无引号形态（构建产物常见 <script src=https://x>）；
  // 补 insertAdjacentHTML / outerHTML 两个漏网注入通道。
  function _rwHtml(h){
    return String(h).replace(
      /(<(?:script|img|link|source|iframe|video|audio|embed)[^>]*?\s(?:src|href|data-src|poster)\s*=\s*)(["'][\s\S]*?\2|[^>\s"']+)/gi,
      function(m, pre, u){
        var q = '';
        if (u[0] === '"' || u[0] === "'"){ q = u[0]; u = u.slice(1, -1); }
        var p = _px(u);
        return p ? pre + q + p + q : m;
      });
  }
  try{
    var _ipd = Object.getOwnPropertyDescriptor(Element.prototype, 'innerHTML') || {};
    if (_ipd.get && _ipd.set){
      Object.defineProperty(Element.prototype, 'innerHTML', {
        get: function(){ return _ipd.get.call(this); },
        set: function(v){ _ipd.set.call(this, _rwHtml(v)); },
        configurable: true
      });
    }
  }catch(_){}
  try{
    var _oIAH = Element.prototype.insertAdjacentHTML;
    Element.prototype.insertAdjacentHTML = function(pos, h){
      return _oIAH.call(this, pos, _rwHtml(h));
    };
  }catch(_){}
  try{
    var _opd = Object.getOwnPropertyDescriptor(Element.prototype, 'outerHTML') || {};
    if (_opd.get && _opd.set){
      Object.defineProperty(Element.prototype, 'outerHTML', {
        get: function(){ return _opd.get.call(this); },
        set: function(v){ _opd.set.call(this, _rwHtml(v)); },
        configurable: true
      });
    }
  }catch(_){}
  try{
    var _odw = document.write.bind(document);
    document.write = function(h){ return _odw(_rwHtml(h)); };
  }catch(_){}
  // a503：拦截 createElement——MutationObserver 是异步的（microtask），
  // 浏览器在回调执行前就已经开始下载 src。在 createElement 时就 hook
  // setAttribute，src/href 被设置的第一时间就重写为代理路径。
  var _tags = {IMG:1,SCRIPT:1,LINK:1,SOURCE:1,IFRAME:1,VIDEO:1,AUDIO:1,EMBED:1};
  var _origCE = document.createElement.bind(document);
  document.createElement = function(tag){
    var el = _origCE(tag);
    if (_tags[(tag||'').toUpperCase()]){
      var _sa = el.setAttribute.bind(el);
      el.setAttribute = function(name, value){
        if ((name==='src'||name==='href'||name==='data-src'||name==='poster') && value){
          var p = _px(String(value));
          if (p) value = p;
        }
        return _sa(name, value);
      };
      // 直接赋值 el.src = '...' 也拦（属性 setter）——a508 修两处：
      // ① 旧版 set 只把重写值存进闭包变量、不写 content attribute →
      //    IDL 赋值（el.href=x）根本没进 DOM → 浏览器认为 href 空：
      //    「<link rel=preload> invalid href」+ script 不加载。掘金
      //    loader 全走 IDL 赋值 → chunk 链断（script 仅 7 个）→ 页面
      //    停在 SSR 骨架「一直打不开」（GitHub 走 setAttribute 侥幸活）
      // ② 旧版 for-in 闭包共享 _val/_prop，多属性互相串值
      // 正确做法：转发原生原型 get/set（写 content attribute、绝对 URL
      // 语义都由浏览器保证），只拦截 value 重写
      var _props = ['src', 'href', 'dataSrc'];
      for (var pi = 0; pi < _props.length; pi++){
        (function(prop){
          try{
            var _name = prop==='dataSrc' ? 'data-src' : prop;
            var _d = Object.getOwnPropertyDescriptor(
              Object.getPrototypeOf(el), _name) || {};
            if (!_d.get || !_d.set) return;   // data-src 无原生 IDL，走 setAttribute hook 足够
            Object.defineProperty(el, _name, {
              get: function(){ return _d.get.call(el); },
              set: function(v){
                var p = _px(String(v||''));
                _d.set.call(el, p || v);
              },
              configurable: true
            });
          }catch(_){}
        })(_props[pi]);
      }
    }
    return el;
  };
  // MutationObserver 兜底（处理 innerHTML 批量插入等非 createElement 路径）
  var _mo = new MutationObserver(function(muts){
    for (var i=0;i<muts.length;i++){
      var m = muts[i];
      for (var j=0;j<m.addedNodes.length;j++){
        var n = m.addedNodes[j];
        if (n.nodeType!==1) continue;
        _rw(n);
        if (n.querySelectorAll){
          n.querySelectorAll('img,script,link,source,iframe,video,audio,embed')
            .forEach(_rw);
        }
      }
    }
  });
  _mo.observe(document.documentElement||document, {
    childList:true, subtree:true,
    attributes:true, attributeFilter:['src','href','data-src']
  });
  // a504：拦截 fetch / XMLHttpRequest——AJAX 请求也走代理（登录/API 等）
  var _origFetch = window.fetch ? window.fetch.bind(window) : null;
  if (_origFetch){
    window.fetch = function(input, init){
      try{
        var u = typeof input==='string' ? input : (input&&input.url) || '';
        var p = _px(u);
        if (p){
          if (typeof input==='string') input = p;
          else input = new Request(p, input);
        }
      }catch(_){}
      return _origFetch(input, init);
    };
  }
  var _origOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function(method, url){
    try{
      var p = _px(String(url||''));
      if (p) url = p;
    }catch(_){}
    arguments[1] = url;
    return _origOpen.apply(this, arguments);
  };
  // 链接导航拦截。a522 关键演进：**同站链接放行**——只把 href 改写为
  // 代理 URL、不 preventDefault。页面自身的 SPA 路由（GitHub pjax /
  // vue-router 等）若接管 click 则零导航零重载（Edge 同款 2s 体验）；
  // 纯多页站点则退化为 iframe 内导航（仍是代理 URL，EscapeGuard 的
  // load 监听同步导航栈）。此前一律劫持成父页整页导航——GitHub 切
  // tab 从 Edge 的 2s（前端路由）劣化成 10s+（重拉全部 JS+hydration）。
  // 跨站链接仍走父页导航（软过渡）。target=_blank 不碰（新窗口链路）。
  document.addEventListener('click', function(e){
    var a = e.target.closest ? e.target.closest('a[href]') : null;
    if (!a) return;
    if (a.target === '_blank') return;
    var href = a.getAttribute('href')||'';
    if (!href || href[0]==='#' || href.indexOf('javascript:')===0) return;
    var abs = href;
    try { abs = new URL(href, _orig).href; } catch(_){}
    var px = _px(abs);
    if (!px) return;                      // 已是代理/不可代理，放行原生
    try {
      if (new URL(abs).host === new URL(_orig).host) {
        a.setAttribute('href', px);       // 同站：改写后放行（SPA 路由接管）
        return;
      }
    } catch(_){}
    e.preventDefault(); e.stopPropagation();
    window.parent.postMessage({__webProxyNav: abs}, '*');
  }, true);
  // a522：iframe 内导航开始时通知父页点亮加载指示（beforeunload 对
  // 任何整页导航触发；SPA 路由不导航、本来就快无需指示）
  window.addEventListener('beforeunload', function(){
    try { parent.postMessage({__pxLoading: true}, '*'); } catch(_){}
  });
  // a512：表单提交统一「action 代理化 + 原生提交」。原方案 preventDefault
  // 后 postMessage 转 GET 导航——表单数据（密码）全丢，登录类表单必坏。
  // 原生提交把 POST 体交给浏览器带上，代理转发（a504 已支持）。
  document.addEventListener('submit', function(e){
    var f = e.target;
    if (!f || f.tagName !== 'FORM') return;
    try{
      var act = f.getAttribute('action') || '';
      if (act && act.indexOf('/api/web/proxy/') !== 0){
        var abs = new URL(act, _orig).href;
        var px = _px(abs);
        if (px) f.setAttribute('action', px);
      }
    }catch(_){}
  }, true);
  // a512：编程式 form.submit() 不触发 submit 事件（HTML 规范）——SSO
  // 登录（casLogin RSA 加密后原生提交）绕过上面的拦截 → POST 打到
  // 127.0.0.1/login → 405（用户实锤）。hook 原型方法：同样代理化 action
  // 后走原生提交。
  var _origSubmit = HTMLFormElement.prototype.submit;
  HTMLFormElement.prototype.submit = function(){
    try{
      var act = this.getAttribute('action') || '';
      if (act && act.indexOf('/api/web/proxy/') !== 0){
        var abs = new URL(act, _orig).href;
        var px = _px(abs);
        if (px) this.setAttribute('action', px);
      }
    }catch(_){}
    return _origSubmit.call(this);
  };
  // a521：同源子 iframe 注入——微前端子应用（qiankun 等的 about:blank/
  // srcdoc iframe 沙箱）内的 XHR/fetch 在独立 window 里跑，不经本页的
  // 拦截，相对路径打到工具域 404（SWMS icoding/review/list 等实锤）。
  // 同源空白 iframe 可写：load 后把本脚本的源码注入进去，递归覆盖多层。
  var _NAV_SRC = (document.currentScript && document.currentScript.textContent) || '';
  function _injectSub(f){
    try{
      if (!f.contentWindow || f.contentWindow.__pxNav) return;
      var d = f.contentDocument;
      if (!d || !d.head) return;
      f.contentWindow.__pxNav = 1;
      var s = d.createElement('script');
      s.textContent = _NAV_SRC;
      d.head.prepend(s);
    }catch(_){}
  }
  document.querySelectorAll('iframe').forEach(function(f){
    f.addEventListener('load', function(){ _injectSub(f); }, { once: true });
  });
  _mo2 = new MutationObserver(function(muts){
    for (var i=0;i<muts.length;i++){
      muts[i].addedNodes.forEach(function(n){
        if (n.nodeType===1 && n.tagName==='IFRAME'){
          n.addEventListener('load', function(){ _injectSub(n); }, { once: true });
          setTimeout(function(){ _injectSub(n); }, 300);
        }
      });
    }
  });
  _mo2.observe(document.documentElement||document, { childList:true, subtree:true });
})();
</script>"""


def _proxy_url_rewrite(base_url, proxy_base):
    """生成 URL 重写函数：把资源 URL 转为**绝对路径式**代理 URL。

    a504：不能用相对路径——<base href="原始URL"> 会把相对代理路径解析到
    原始域名，必须绝对路径。
    a506：query 式（?url=<编码>）升级为路径式 /proxy/<scheme>/<host>/<path>
    ——webpack 等运行时取 currentScript.src 的 dirname 做 publicPath，
    query 式折叠成 /api/web/ 导致动态 chunk 全 404（GitHub 实锤 40 个），
    路径式的 dirname 还原出 CDN 基址，相对 chunk 自动落回代理路由。
    query 串原样附加（代理自身无参数）；fragment 丢弃（锚点不发请求）。
    """
    import re as _re
    from urllib.parse import urljoin, quote

    def _to_proxy(u):
        if not u or u.startswith(("javascript:", "data:", "#", "blob:", "mailto:",
                                  "tel:", "about:")):
            return u
        try:
            _abs = urljoin(base_url, u)
        except Exception:
            return u
        _m = _re.match(r"(https?)://([^/?#]+)([^?#]*)(\?[^#]*)?(#.*)?$", _abs)
        if not _m:
            return u
        _sch, _host, _path, _q = _m.group(1), _m.group(2), _m.group(3), _m.group(4)
        return (proxy_base.rstrip("/") + "/" + _sch + "/" + _host
                + quote(_path or "/", safe="/%:") + (_q or ""))
    return _to_proxy


def _proxy_sanitize_setcookie(sc, persist_days=7):
    """a505：Set-Cookie 透传前的域适配（纯函数供测试）。

    原始服务器的 Set-Cookie 面向自己的域（Domain=10.17.97.73 / Path=/api /
    Secure / SameSite=None 等），浏览器对照当前域 127.0.0.1 逐条校验：
    - Domain=非当前域 → 整条拒收（session 直接丢）
    - Secure → http://127.0.0.1 上存不下
    - SameSite=None（无 Secure 时）→ 新 Chromium 拒收
    - Path=/api → 只匹配 /api 前缀，/api/web/proxy 虽碰巧同前缀但非普适
    处理：剥 Domain/Secure/SameSite，Path 统一改 /。HttpOnly 保留——
    浏览器请求代理是同源自动带 cookie，JS 读不读得到无关紧要。

    a519：会话 cookie（无 Expires/Max-Age）补 7 天持久——CAS 的 CASTGC
    等 TGT 默认是会话 cookie（浏览器关闭即失效），而代理域 127.0.0.1 的
    「浏览器」就是 WebView2：每次重启工具 = 会话结束 = 登录态清零 → 用户
    实锤「每次都要输密码」。内网单用户工具语境，便利优先于会话隔离。
    """
    _keep = []
    _has_life = False
    for _p in (sc or "").split(";"):
        _pl = _p.strip().lower()
        if not _pl:
            continue
        if (_pl.startswith("domain=") or _pl.startswith("secure")
                or _pl.startswith("path=") or _pl.startswith("samesite=")):
            continue
        if _pl.startswith(("expires=", "max-age=")):
            _has_life = True
        _keep.append(_p.strip())
    if not _keep:
        return ""
    _out = "; ".join(_keep) + "; Path=/"
    if not _has_life and persist_days:
        from email.utils import formatdate
        import time as _time
        _out += "; Expires=" + formatdate(
            _time.time() + persist_days * 86400, usegmt=True)
    return _out


@bp.route("/api/web/proxy",
           methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
def api_web_proxy():
    """query 式代理（a502 原始形态）：/api/web/proxy?url=<编码原始URL>。

    a506 起主形态是路径式（/api/web/proxy/https/host/path——webpack
    publicPath 等相对解析天然正确）；本路由保留做兼容（旧收藏/导航栈/
    _webProxyUrl 兜底）。
    """
    url = (request.args.get("url") or "").strip()
    return _proxy_core(url)


@bp.route("/api/web/proxy/<any(http, https):_sch>/<path:_rest>",
           methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
def api_web_proxy_path(_sch, _rest):
    """a506 路径式代理：/api/web/proxy/<scheme>/<host>/<path>。

    为什么放弃 query 式做主形态：webpack runtime 从 currentScript.src 取
    dirname 当 publicPath，query 式代理 URL 的 dirname 折叠成 /api/web/
    → 动态 chunk 拼出 origin+/api/web/xxx.js → Flask 404（GitHub 40 个
    chunk 全灭、commit 列骨架）。路径式下 script src 是
    /api/web/proxy/https/cdn.host/assets/app.js，dirname 还原出 CDN 基址
    → chunk 相对路径拼出 /api/web/proxy/https/cdn.host/assets/xxx.js →
    命中本路由，闭环。CSS 相对字体/importmap/未来的 SW 同理天然正确。
    path 段由 Flask 解码——转发前由调用方拼回原始 URL；query 原样透传
    （代理自身无参数，query 全属于原始请求）。
    """
    _u = _sch + "://" + _rest
    if request.query_string:
        _u += "?" + request.query_string.decode("latin-1")
    return _proxy_core(_u)


def _proxy_session():
    """a511：线程局部 requests.Session——HTTPS keep-alive 连接复用。

    urllib 每请求全新 DNS+TCP+TLS 握手，重站点（掘金 128 资源）光握手
    就几十秒（用户实锤整页 1 分钟）。Session 连接池同域只握手一次。
    每请求清 cookie jar——会话主体是浏览器侧（cookie 由代理手动转发），
    代理进程保持无状态，避免多 tab 会话串染。"""
    s = getattr(_THREAD_LOCAL, "s", None)
    if s is None:
        s = _requests.Session()
        s.verify = False
        _THREAD_LOCAL.s = s
    s.cookies.clear()
    return s


def _sc_list(r):
    """a511：requests 响应提取多条 Set-Cookie（urllib3 getlist）。"""
    try:
        return r.raw.headers.getlist("Set-Cookie") or []
    except Exception:
        return []


def _proxy_core(url):
    """代理核心（a506 从 api_web_proxy 提取，query/路径式两路由共用）：
    取页 → 删 XFO → 重写资源 URL 为代理路径 → 注入导航拦截。

    a502：所有子资源（img/js/css/font）也走代理。
    a504：支持 POST/PUT/DELETE 等——AJAX（登录/API）也走代理。
    a505：会话三件套——①请求转发浏览器 Cookie ②Set-Cookie 透传（剥
    Domain/Secure/SameSite、Path 改 /，浏览器存进 127.0.0.1 域）③302 不
    跟随、Location 代理化后透传（登录 302 的 Set-Cookie 不丢、跳转不逃出
    代理模式）。
    a511：urllib → 线程局部 requests.Session（keep-alive 连接复用）。
    """
    from urllib.parse import quote as _quote
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        return Response("Bad URL", status=400)
    _hdrs = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0 Safari/537.36"),
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": url,
    }
    # a513：转发浏览器原始请求头（Accept/X-Requested-With 等）——GitHub
    # 的 hydration XHR 严格校验 Accept（*/* → 400、application/json →
    # 200，实测）。排除：连接管理类（requests 自管）、Origin（127.0.0.1
    # 的 Origin 触发目标站 CSRF 拒绝）、Referer（自设目标自指）、Cookie
    #（下方单独转发）、浏览器缓存控制。
    _SKIP_IN = {"host", "connection", "content-length", "accept-encoding",
                "origin", "referer", "cookie", "cache-control", "pragma"}
    for _k, _v in request.headers:
        if _k.lower() not in _SKIP_IN:
            _hdrs[_k] = _v
    # a505：转发浏览器 Cookie——登录后服务器 Set-Cookie 的 session 存在
    # 127.0.0.1 域（代理已透传回来），浏览器后续同源请求自动带上，这里
    # 转发给原始服务器，会话才能贯穿（否则登录成功后下一请求又变未登录）
    _ck = request.headers.get("Cookie")
    if _ck:
        _hdrs["Cookie"] = _ck
    # a504：转发 Content-Type 和请求体（POST/PUT/PATCH）
    _body = None
    if request.method in ("POST", "PUT", "PATCH"):
        _body = request.get_data()
        _ct_req = request.headers.get("Content-Type")
        if _ct_req:
            _hdrs["Content-Type"] = _ct_req
        _hdrs["X-Requested-With"] = request.headers.get("X-Requested-With", "")
    _method = request.method if request.method != "HEAD" else "GET"

    def _fetch(u):
        return _proxy_session().request(
            _method, u, headers=_hdrs, data=_body,
            timeout=15, allow_redirects=False)

    # a505：禁自动跟随重定向——中间响应（其 Set-Cookie）不能丢，且浏览器
    # 要看到跳转。透传 30x：Location 代理化后交还浏览器跟，Set-Cookie 透传。
    # a521：连接失败两级重试——①http 失败升级 https 重试（页面硬编码
    # http:// 的资源在内网 80 不通：swms-tool/*.svg 实锤 502）；②https
    # 失败同 URL 重试一次（内网透明代理链路偶发抖动：code-api 502 实锤）
    try:
        try:
            _r = _fetch(url)
        except Exception:
            _r = _fetch("https://" + url[7:] if url.startswith("http://") else url)
        # a518：上限 5MB → 50MB——现代 SPA 主 bundle 超 5MB 不罕见
        # （SWMS app.js 5.2MB 实锤：截断 → Unexpected end of input →
        # 页面白屏）。50MB 覆盖极端 vendor 全量包，内存垫得住（内网单
        # 用户工具语境）
        _raw = (_r.content or b"")[:50 * 1024 * 1024]
        _ct = _r.headers.get("Content-Type") or ""
        _final = url           # 无跟随重定向，最终地址即请求地址
    except Exception as e:
        return Response("Proxy fetch failed: %s" % str(e)[:200], status=502)

    def _set_cookies_into(resp, scs):
        """a505：原始响应 Set-Cookie 清洗后透传（可多条）。"""
        for _sc in scs:
            _clean = _proxy_sanitize_setcookie(_sc)
            if _clean:
                resp.headers.add("Set-Cookie", _clean)
        return resp

    # a505：30x 透传——Location 代理化（相对地址基于原始 URL 解析），
    # Set-Cookie 同步透传（登录 302 的 session 落地在浏览器侧）。
    # a506：_fn 产路径式（dirname 语义对 publicPath 类运行时正确）
    if 300 <= _r.status_code < 400:
        _loc = _r.headers.get("Location") or ""
        if _loc:
            _fn_e = _proxy_url_rewrite(
                url, "http://" + request.host + "/api/web/proxy")
            _resp = Response(b"", status=_r.status_code)
            _resp.headers["Location"] = _fn_e(_loc)
            return _set_cookies_into(_resp, _sc_list(_r))
        # 无 Location 的 30x：无处可代理化，空体透传状态码（a511 修：
        # 原会落进正常响应分支变 200）
        return _set_cookies_into(
            Response(b"", status=_r.status_code), _sc_list(_r))
    # a504：转发原始错误码和响应体（401/403/404 等——AJAX 需要看到）
    if _r.status_code >= 400:
        return _set_cookies_into(
            Response(_raw, status=_r.status_code,
                     mimetype=_ct.split(";")[0].strip() or "text/plain"),
            _sc_list(_r))

    _ct_low = _ct.lower()

    # CSS：重写 url(...) 为代理路径（字体/背景图等）
    if "text/css" in _ct_low:
        import re as _re
        _fn = _proxy_url_rewrite(_final, "http://" + request.host + "/api/web/proxy")
        _css = _raw.decode("utf-8", "replace")
        _css = _re.sub(
            r"url\((['\"]?)([^'\")\s]+)\1\)",
            lambda m: "url(%s%s%s)" % (m.group(1), _fn(m.group(2)), m.group(1)),
            _css)
        return _set_cookies_into(Response(_css, mimetype="text/css"), _sc_list(_r))

    # 非 HTML/CSS 直接透传（图片/字体等二进制资源）
    if "text/html" not in _ct_low and "application/xhtml" not in _ct_low:
        return _set_cookies_into(
            Response(_raw,
                     mimetype=_ct.split(";")[0].strip() or "application/octet-stream"),
            _sc_list(_r))

    # ---- HTML 处理 ----
    _cs = _web_detect_charset(_ct, _raw)
    try:
        _html = _raw.decode(_cs, "replace")
    except LookupError:
        _html = _raw.decode("utf-8", "replace")

    import re as _re
    from urllib.parse import urljoin as _urljoin
    _fn = _proxy_url_rewrite(_final, "http://" + request.host + "/api/web/proxy")

    # 重写资源 URL：匹配整个资源标签，在标签内全局替换 src/href
    # 不匹配 <a>（导航拦截 JS 处理）——<a> 不在标签列表中。
    # a517：属性值支持无引号形态——Vue CLI 等构建产物常见
    # <script src=https://host/x.js?hash>（不带引号，HTML5 合法），
    # 原正则漏配 → 脚本直连原始域 → 未认证拿到登录页 HTML →
    # Unexpected token '<'（SWMS 实锤 runtime/vendor/app 三件套）
    def _rw_tag(m):
        _tag = m.group(1)          # 标签名（保持原大小写）
        _attrs = m.group(2) or ''  # 标签内所有属性
        _attrs = _re.sub(
            r"""(src|href|data-src)=(["'][^"']*["']|[^>\s]+)""",
            lambda mm: '%s="%s"' % (
                mm.group(1),
                _fn(mm.group(2)[1:-1] if mm.group(2)[:1] in "\"'"
                   else mm.group(2))),
            _attrs, flags=_re.I)
        return "<%s%s" % (_tag, _attrs)
    _html = _re.sub(
        r"<(img|script|link|source|video|audio|iframe|embed|track|object)"
        r"(\s[^>]*)?(/?>)",
        lambda m: _rw_tag(m) + (m.group(3) or ""),
        _html, flags=_re.I)

    # 重写 srcset（响应式图片）
    def _rw_srcset(m):
        _urls = m.group(2).split(",")
        _out = []
        for _part in _urls:
            _part = _part.strip()
            if " " in _part:
                _u, _d = _part.rsplit(" ", 1)
                _out.append(_fn(_u) + " " + _d)
            else:
                _out.append(_fn(_part))
        return "%s=\"%s\"" % (m.group(1), ", ".join(_out))
    _html = _re.sub(
        r"(srcset)=['\"]([^'\"]+)['\"]",
        _rw_srcset, _html, flags=_re.I)

    # a506：重写 importmap JSON 里的 URL——裸模块名（import "react"）经
    # 浏览器模块加载器按 importmap 解析，不走任何 src/href 属性或 fetch
    # 拦截；不重写则直接打原始 CDN → 内网阻断 → module graph 断裂、
    # hydration 永不接管（GitHub 实锤：文件列表 commit 列永久骨架）
    def _rw_importmap(m):
        # 字符类：排除 双引号/单引号/空白/反斜杠/逗号（JSON 值边界）。
        # 反斜杠歧义坑（a506 实锤）：多重转义写错会把裸 s 变字面 s、
        # URL 从 githubassets 的 s 处截断——单引号 raw 下 " 免转义最稳
        _body = _re.sub(r'https?://[^"\'\s\\,]+',
                        lambda mm: _fn(mm.group(0)), m.group(2))
        return m.group(1) + _body + "</script>"
    _html = _re.sub(
        r"(<script[^>]*type=[\"']importmap[^>]*>)(.*?)</script>",
        _rw_importmap, _html, flags=_re.I | _re.S)

    # a508：导航拦截 JS 参数化——原始 URL 以 JSON 字面量注入为 _orig
    # （安全转义），作为相对 URL 的解析基准（替代被移除的 <base>）
    import json as _json
    _nav = _PROXY_NAV_JS.replace("__PX_ORIG__", _json.dumps(_final))

    # a508：不再注入 <base href="原始URL">——SPA router（Vue/React 的
    # history 模式）按 document.baseURI 拼绝对 URL，base 会把当前代理
    # 路径拼到原始域上（掘金实锤：router 整页跳 juejin.cn/api/web/
    # proxy/... 跳出代理白屏）。原始站的 <base> 同样删（防它反向把代理
    # 域相对路径带偏）。CSS 相对路径已在服务端重写为绝对代理 URL，base
    # 的兜底价值仅剩内联 style url()，两害取轻。
    # a505：referrer same-origin——404 兜底路由靠同源 Referer 还原站点。
    _html = _re.sub(r"<base\b[^>]*>", "", _html, flags=_re.I)
    _meta_ref = '<meta name="referrer" content="same-origin">'
    if "<head" in _html.lower():
        _html = _re.sub(r"(<head[^>]*>)", r"\1" + _meta_ref,
                        _html, count=1, flags=_re.I)
    else:
        _html = _meta_ref + _html

    # 注入导航拦截 JS（a508：参数化注入原始 URL 做相对解析基准 _orig）。
    # a513：必须用函数 repl——字符串 repl 会把 JS 正则里的 \s \2 当正则
    # 替换转义解析（re.PatternError，注入串含 _rwHtml 正则后实锤）
    if "</head>" in _html.lower():
        _html = _re.sub(r"</head>", lambda _m: _nav + "</head>",
                        _html, count=1, flags=_re.I)
    elif "</body>" in _html.lower():
        _html = _re.sub(r"</body>", lambda _m: _nav + "</body>",
                        _html, count=1, flags=_re.I)
    else:
        _html += _nav

    _resp = _set_cookies_into(
        Response(_html, mimetype="text/html; charset=utf-8"), _sc_list(_r))
    # a512：进程首次代理 HTML 响应带一次 Clear-Site-Data:"cache"——
    # WebView2 可能存有代理演进期（a504-a510 无缓存策略）的旧/坏缓存
    # 条目（SSO 页实锤 ERR_CACHE_READ_FAILURE → fingerprint2 读缓存失败
    # → Fingerprint2 is not defined）。只清 cache 不动 cookie/storage
    #（登录态与逃逸回收的 sessionStorage 无损），进程内只发一次。
    if not _CSD_SENT:
        _CSD_SENT.append(1)
        _resp.headers["Clear-Site-Data"] = '"cache"'
    return _resp


def _proxy_404_fallback(err):
    """a505：代理域 404 兜底——登录成功后页面 JS 常写 location.href='/main'
    这类站内相对跳转（location 赋值浏览器安全限制拦不住），在代理 iframe
    里解析为 127.0.0.1/main → Flask 404 → 用户看到「跳转失败」。

    a508：服务端 302 兜底改为客户端还原页——SPA pathname 伪装
    （replaceState）后 Referer 不再含代理前缀，服务端无从还原基址；
    原始 URL 已由注入 JS 存入 sessionStorage.__px_orig，兜底页用 JS
    读取后拼回代理路径跳转。条件：GET + Accept 含 text/html（AJAX 的
    404 原样返回，fetch 期待原状态码）+ Referer 同源。sessionStorage
    无记录（非代理来源的普通 404）→ 渲染普通 404 文案，无行为差异。
    """
    _ref = request.headers.get("Referer", "")
    if (request.method == "GET"
            and _ref.startswith("http://" + request.host + "/")):
        _acc = request.headers.get("Accept") or ""
        if "text/html" not in _acc:
            # a515：脚本/样式等资源类 404 返回空体——Flask 默认 404 页是
            # HTML，漏网 <script> 拿到会报 Unexpected token '<' 掩盖真实
            # 状态（SSO runtime/vendor/app 实锤）
            return Response(b"", status=404,
                            mimetype="text/plain")
        _page = (
            "<!doctype html><meta charset='utf-8'><title>404</title>"
            "<body style='font:14px/1.6 sans-serif;padding:40px;"
            "color:#666'>Redirecting..."
            "<script>(function(){var o=null;"
            "try{o=sessionStorage.getItem('__px_orig');}catch(e){}"
            "if(o){try{var b=new URL(o);"
            "location.replace('/api/web/proxy/'+b.protocol.replace(':','')"
            "+'/'+b.host+location.pathname+location.search);return;}"
            "catch(e){}}"
            "document.body.innerText='404 Not Found';})();</script>")
        return Response(_page, status=404, mimetype="text/html")
    return err


@bp.route("/api/web/fetch_text", methods=["POST"])
def api_web_fetch_text():
    """a473：网页 tab「发给 Claude」——服务端取页转纯文本。

    为什么在服务端做：跨域 iframe 的 DOM 父页读不到（安全边界），取正文
    只能再走一次 HTTP。SSO 登录态拿不到（cookie 在 WebView2 档里，Flask
    够不着）——主用目标是无登录态的内网页（Jenkins/svn web 公开视图/
    构建日志页），带登录态的页面走 AI 的 devtools_* MCP 工具（CDP 在
    浏览器进程内，带全 cookie）。

    轻量 HTML→文本：去 script/style/注释/标签 + 实体解码，不引依赖。
    上限：响应体 5MB、正文 40K 字符（Claude 上下文友好）。
    审计修：内网 https 常自签——不校验证书（本地单用户工具语境，与
    浏览器「继续访问」同权）。"""
    import ssl as _ssl
    import urllib.request
    data = request.get_json(force=True, silent=True) or {}
    url = str(data.get("url") or "").strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        return jsonify({"ok": False, "err": "仅支持 http(s) 链接"}), 400
    req = urllib.request.Request(url, headers={
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0 Safari/537.36"),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })
    try:
        ctx = _ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = _ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
            raw = r.read(5 * 1024 * 1024)
            # 审计修：无效编码名（老页面 charset=unicode 之类）decode 抛
            # LookupError 会整页「取页失败」——回落 utf-8
            cs = _web_detect_charset(r.headers.get("Content-Type"), raw)
            try:
                text = raw.decode(cs, "replace")
            except LookupError:
                text = raw.decode("utf-8", "replace")
    except Exception as e:
        return jsonify({"ok": False, "err": "取页失败：%s" % str(e)[:180]})
    title, body = _web_html_to_text(text)
    capped = len(body) > 40000
    return jsonify({"ok": True, "url": url, "title": title,
                    "text": body[:40000], "truncated": capped})


def register(app):
    """挂载到主应用：蓝图 + app 级 404 兜底 + 代理响应禁缓存。"""
    app.register_blueprint(bp)
    app.errorhandler(404)(_proxy_404_fallback)

    @app.after_request
    def _no_store(resp):
        """a510：代理响应一律禁缓存。代理产物是动态改写的（URL 重写/
        注入 JS/会话 cookie 都随版本与页面变化），可缓存毫无收益；
        WebView2 缓存旧版产物后升级会撞 ERR_CACHE_READ_FAILURE 或执行
        过期注入逻辑（SSO 页实锤）。no-store=不写不读，最彻底。
        只作用于本蓝图路由——工具自身响应的缓存策略归 _no_cache_static。
        a511 分型：HTML/API（json 等动态内容）no-store；静态资源
        （js/css/img/font——URL 普遍带 contenthash，内容不可变）给
        max-age=1800，二次加载走 WebView2 缓存不重拉（a510 全量 no-store
        后掘金整页 128 资源每次全拉，用户实锤二次加载也慢）。"""
        if request.blueprint == "web_proxy":
            _mt = (resp.mimetype or "").lower()
            _static = (_mt in ("text/css", "application/javascript",
                               "text/javascript", "image/svg+xml")
                       or _mt.startswith(("image/", "font/"))
                       or _mt.startswith("application/font"))
            if _static:
                resp.headers["Cache-Control"] = "private, max-age=1800"
            else:
                resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return resp
