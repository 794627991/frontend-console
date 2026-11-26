// ../../node_modules/.pnpm/preact@10.29.8/node_modules/preact/dist/preact.mjs
var n;
var l;
var u;
var t;
var i;
var r;
var o;
var e;
var f;
var c;
var a;
var s;
var h;
var p;
var v;
var y;
var d = {};
var w = [];
var _ = /acit|ex(?:s|g|n|p|$)|rph|grid|ows|mnc|ntw|ine[ch]|zoo|^ord|itera/i;
var g = Array.isArray;
function m(n2, l3) {
  for (var u4 in l3) n2[u4] = l3[u4];
  return n2;
}
function b(n2) {
  n2 && n2.parentNode && n2.parentNode.removeChild(n2);
}
function k(l3, u4, t3) {
  var i3, r3, o3, e3 = {};
  for (o3 in u4) "key" == o3 ? i3 = u4[o3] : "ref" == o3 ? r3 = u4[o3] : e3[o3] = u4[o3];
  if (arguments.length > 2 && (e3.children = arguments.length > 3 ? n.call(arguments, 2) : t3), "function" == typeof l3 && null != l3.defaultProps) for (o3 in l3.defaultProps) void 0 === e3[o3] && (e3[o3] = l3.defaultProps[o3]);
  return x(l3, e3, i3, r3, null);
}
function x(n2, t3, i3, r3, o3) {
  var e3 = { type: n2, props: t3, key: i3, ref: r3, __k: null, __: null, __b: 0, __e: null, __c: null, constructor: void 0, __v: null == o3 ? ++u : o3, __i: -1, __u: 0 };
  return null == o3 && null != l.vnode && l.vnode(e3), e3;
}
function S(n2) {
  return n2.children;
}
function C(n2, l3) {
  this.props = n2, this.context = l3;
}
function $(n2, l3) {
  if (null == l3) return n2.__ ? $(n2.__, n2.__i + 1) : null;
  for (var u4; l3 < n2.__k.length; l3++) if (null != (u4 = n2.__k[l3]) && null != u4.__e) return u4.__e;
  return "function" == typeof n2.type ? $(n2) : null;
}
function I(n2) {
  if (n2.__P && n2.__d) {
    var u4 = n2.__v, t3 = u4.__e, i3 = [], r3 = [], o3 = m({}, u4);
    o3.__v = u4.__v + 1, l.vnode && l.vnode(o3), q(n2.__P, o3, u4, n2.__n, n2.__P.namespaceURI, 32 & u4.__u ? [t3] : null, i3, null == t3 ? $(u4) : t3, !!(32 & u4.__u), r3), o3.__v = u4.__v, o3.__.__k[o3.__i] = o3, D(i3, o3, r3), u4.__e = u4.__ = null, o3.__e != t3 && P(o3);
  }
}
function P(n2) {
  if (null != (n2 = n2.__) && null != n2.__c) return n2.__e = n2.__c.base = null, n2.__k.some(function(l3) {
    if (null != l3 && null != l3.__e) return n2.__e = n2.__c.base = l3.__e;
  }), P(n2);
}
function A(n2) {
  (!n2.__d && (n2.__d = true) && i.push(n2) && !H.__r++ || r != l.debounceRendering) && ((r = l.debounceRendering) || o)(H);
}
function H() {
  try {
    for (var n2, l3 = 1; i.length; ) i.length > l3 && i.sort(e), n2 = i.shift(), l3 = i.length, I(n2);
  } finally {
    i.length = H.__r = 0;
  }
}
function L(n2, l3, u4, t3, i3, r3, o3, e3, f4, c3, a3) {
  var s3, h3, p3, v3, y3, _3, g4 = t3 && t3.__k || w, m3 = l3.length;
  for (f4 = T(u4, l3, g4, f4, m3), s3 = 0; s3 < m3; s3++) null != (p3 = u4.__k[s3]) && (h3 = -1 != p3.__i && g4[p3.__i] || d, p3.__i = s3, _3 = q(n2, p3, h3, i3, r3, o3, e3, f4, c3, a3), v3 = p3.__e, p3.ref && h3.ref != p3.ref && (h3.ref && J(h3.ref, null, p3), a3.push(p3.ref, p3.__c || v3, p3)), null == y3 && null != v3 && (y3 = v3), 4 & p3.__u ? (f4 = j(p3, f4, n2), h3.__e && (h3.__e = null)) : "function" == typeof p3.type && void 0 !== _3 ? f4 = _3 : v3 && (f4 = v3.nextSibling), p3.__u &= -7);
  return u4.__e = y3, f4;
}
function T(n2, l3, u4, t3, i3) {
  var r3, o3, e3, f4, c3, a3 = u4.length, s3 = a3, h3 = 0;
  for (n2.__k = new Array(i3), r3 = 0; r3 < i3; r3++) null != (o3 = l3[r3]) && "boolean" != typeof o3 && "function" != typeof o3 ? ("string" == typeof o3 || "number" == typeof o3 || "bigint" == typeof o3 || o3.constructor == String ? o3 = n2.__k[r3] = x(null, o3, null, null, null) : g(o3) ? o3 = n2.__k[r3] = x(S, { children: o3 }, null, null, null) : void 0 === o3.constructor && o3.__b > 0 ? o3 = n2.__k[r3] = x(o3.type, o3.props, o3.key, o3.ref ? o3.ref : null, o3.__v) : n2.__k[r3] = o3, f4 = r3 + h3, o3.__ = n2, o3.__b = n2.__b + 1, e3 = null, -1 != (c3 = o3.__i = O(o3, u4, f4, s3)) && (s3--, (e3 = u4[c3]) && (e3.__u |= 2)), null == e3 || null == e3.__v ? (-1 == c3 && (i3 > a3 ? h3-- : i3 < a3 && h3++), "function" != typeof o3.type && (o3.__u |= 4)) : c3 != f4 && (c3 == f4 - 1 ? h3-- : c3 == f4 + 1 ? h3++ : (c3 > f4 ? h3-- : h3++, o3.__u |= 4))) : n2.__k[r3] = null;
  if (s3) for (r3 = 0; r3 < a3; r3++) null != (e3 = u4[r3]) && 0 == (2 & e3.__u) && (e3.__e == t3 && (t3 = $(e3)), K(e3, e3));
  return t3;
}
function j(n2, l3, u4) {
  var t3, i3;
  if ("function" == typeof n2.type) {
    for (t3 = n2.__k, i3 = 0; t3 && i3 < t3.length; i3++) t3[i3] && (t3[i3].__ = n2, l3 = j(t3[i3], l3, u4));
    return l3;
  }
  n2.__e != l3 && (l3 && n2.type && !l3.parentNode && (l3 = $(n2)), l3 = u4.insertBefore(n2.__e, l3 || null));
  do {
    l3 = l3 && l3.nextSibling;
  } while (null != l3 && 8 == l3.nodeType);
  return l3;
}
function F(n2, l3) {
  return l3 = l3 || [], null == n2 || "boolean" == typeof n2 || (g(n2) ? n2.some(function(n3) {
    F(n3, l3);
  }) : l3.push(n2)), l3;
}
function O(n2, l3, u4, t3) {
  var i3, r3, o3, e3 = n2.key, f4 = n2.type, c3 = l3[u4], a3 = null != c3 && 0 == (2 & c3.__u);
  if (null === c3 && null == e3 || a3 && e3 == c3.key && f4 == c3.type) return u4;
  if (t3 > (a3 ? 1 : 0)) {
    for (i3 = u4 - 1, r3 = u4 + 1; i3 >= 0 || r3 < l3.length; ) if (null != (c3 = l3[o3 = i3 >= 0 ? i3-- : r3++]) && 0 == (2 & c3.__u) && e3 == c3.key && f4 == c3.type) return o3;
  }
  return -1;
}
function z(n2, l3, u4) {
  "-" == l3[0] ? n2.setProperty(l3, null == u4 ? "" : u4) : n2[l3] = null == u4 ? "" : "number" != typeof u4 || _.test(l3) ? u4 : u4 + "px";
}
function N(n2, l3, u4, t3, i3) {
  var r3, o3;
  n: if ("style" == l3) if ("string" == typeof u4) n2.style.cssText = u4;
  else {
    if ("string" == typeof t3 && (n2.style.cssText = t3 = ""), t3) for (l3 in t3) u4 && l3 in u4 || z(n2.style, l3, "");
    if (u4) for (l3 in u4) t3 && u4[l3] == t3[l3] || z(n2.style, l3, u4[l3]);
  }
  else if ("o" == l3[0] && "n" == l3[1]) r3 = l3 != (l3 = l3.replace(s, "$1")), o3 = l3.toLowerCase(), l3 = o3 in n2 || "onFocusOut" == l3 || "onFocusIn" == l3 ? o3.slice(2) : l3.slice(2), n2.l || (n2.l = {}), n2.l[l3 + r3] = u4, u4 ? t3 ? u4[a] = t3[a] : (u4[a] = h, n2.addEventListener(l3, r3 ? v : p, r3)) : n2.removeEventListener(l3, r3 ? v : p, r3);
  else {
    if ("http://www.w3.org/2000/svg" == i3) l3 = l3.replace(/xlink(H|:h)/, "h").replace(/sName$/, "s");
    else if ("width" != l3 && "height" != l3 && "href" != l3 && "list" != l3 && "form" != l3 && "tabIndex" != l3 && "download" != l3 && "rowSpan" != l3 && "colSpan" != l3 && "role" != l3 && "popover" != l3 && l3 in n2) try {
      n2[l3] = null == u4 ? "" : u4;
      break n;
    } catch (n3) {
    }
    "function" == typeof u4 || (null == u4 || false === u4 && "-" != l3[4] ? n2.removeAttribute(l3) : n2.setAttribute(l3, "popover" == l3 && 1 == u4 ? "" : u4));
  }
}
function V(n2) {
  return function(u4) {
    if (this.l) {
      var t3 = this.l[u4.type + n2];
      if (null == u4[c]) u4[c] = h++;
      else if (u4[c] < t3[a]) return;
      return t3(l.event ? l.event(u4) : u4);
    }
  };
}
function q(n2, u4, t3, i3, r3, o3, e3, f4, c3, a3) {
  var s3, h3, p3, v3, y3, d3, _3, k4, x4, M3, I2, P4, A4, H3, T4, j4, F3 = u4.type;
  if (void 0 !== u4.constructor) return null;
  128 & t3.__u && (c3 = !!(32 & t3.__u), o3 = [f4 = u4.__e = t3.__e]), (s3 = l.__b) && s3(u4);
  n: if ("function" == typeof F3) {
    h3 = e3.length;
    try {
      if (x4 = u4.props, M3 = F3.prototype && F3.prototype.render, I2 = (s3 = F3.contextType) && i3[s3.__c], P4 = s3 ? I2 ? I2.props.value : s3.__ : i3, t3.__c ? k4 = (p3 = u4.__c = t3.__c).__ = p3.__E : (M3 ? u4.__c = p3 = new F3(x4, P4) : (u4.__c = p3 = new C(x4, P4), p3.constructor = F3, p3.render = Q), I2 && I2.sub(p3), p3.state || (p3.state = {}), p3.__n = i3, v3 = p3.__d = true, p3.__h = [], p3._sb = []), M3 && null == p3.__s && (p3.__s = p3.state), M3 && null != F3.getDerivedStateFromProps && (p3.__s == p3.state && (p3.__s = m({}, p3.__s)), m(p3.__s, F3.getDerivedStateFromProps(x4, p3.__s))), y3 = p3.props, d3 = p3.state, p3.__v = u4, v3) M3 && null == F3.getDerivedStateFromProps && null != p3.componentWillMount && p3.componentWillMount(), M3 && null != p3.componentDidMount && p3.__h.push(p3.componentDidMount);
      else {
        if (M3 && null == F3.getDerivedStateFromProps && x4 !== y3 && null != p3.componentWillReceiveProps && p3.componentWillReceiveProps(x4, P4), u4.__v == t3.__v || !p3.__e && null != p3.shouldComponentUpdate && false === p3.shouldComponentUpdate(x4, p3.__s, P4)) {
          u4.__v != t3.__v && (p3.props = x4, p3.state = p3.__s, p3.__d = false), u4.__e = t3.__e, u4.__k = t3.__k, u4.__k.some(function(n3) {
            n3 && (n3.__ = u4);
          }), w.push.apply(p3.__h, p3._sb), p3._sb = [], p3.__h.length && e3.push(p3), f4 = $(t3);
          break n;
        }
        null != p3.componentWillUpdate && p3.componentWillUpdate(x4, p3.__s, P4), M3 && null != p3.componentDidUpdate && p3.__h.push(function() {
          p3.componentDidUpdate(y3, d3, _3);
        });
      }
      if (p3.context = P4, p3.props = x4, p3.__P = n2, p3.__e = false, A4 = l.__r, H3 = 0, M3) p3.state = p3.__s, p3.__d = false, A4 && A4(u4), s3 = p3.render(p3.props, p3.state, p3.context), w.push.apply(p3.__h, p3._sb), p3._sb = [];
      else do {
        p3.__d = false, A4 && A4(u4), s3 = p3.render(p3.props, p3.state, p3.context), p3.state = p3.__s;
      } while (p3.__d && ++H3 < 25);
      p3.state = p3.__s, null != p3.getChildContext && (i3 = m(m({}, i3), p3.getChildContext())), M3 && !v3 && null != p3.getSnapshotBeforeUpdate && (_3 = p3.getSnapshotBeforeUpdate(y3, d3)), T4 = null != s3 && s3.type === S && null == s3.key ? E(s3.props.children) : s3, f4 = L(n2, g(T4) ? T4 : [T4], u4, t3, i3, r3, o3, e3, f4, c3, a3), p3.base = u4.__e, u4.__u &= -161, p3.__h.length && e3.push(p3), k4 && (p3.__E = p3.__ = null);
    } catch (n3) {
      if (e3.length = h3, u4.__v = null, c3 || null != o3) {
        if (n3.then) {
          for (u4.__u |= c3 ? 160 : 128; f4 && 8 == f4.nodeType && f4.nextSibling; ) f4 = f4.nextSibling;
          null != o3 && (o3[o3.indexOf(f4)] = null), u4.__e = f4;
        } else if (null != o3) for (j4 = o3.length; j4--; ) b(o3[j4]);
      } else u4.__e = t3.__e;
      null == u4.__k && (u4.__k = t3.__k || []), n3.then || B(u4), l.__e(n3, u4, t3);
    }
  } else null == o3 && u4.__v == t3.__v ? (u4.__k = t3.__k, u4.__e = t3.__e) : f4 = u4.__e = G(t3.__e, u4, t3, i3, r3, o3, e3, c3, a3);
  return (s3 = l.diffed) && s3(u4), 128 & u4.__u ? void 0 : f4;
}
function B(n2) {
  n2 && (n2.__c && (n2.__c.__e = true), n2.__k && n2.__k.some(B));
}
function D(n2, u4, t3) {
  for (var i3 = 0; i3 < t3.length; i3++) J(t3[i3], t3[++i3], t3[++i3]);
  l.__c && l.__c(u4, n2), n2.some(function(u5) {
    try {
      n2 = u5.__h, u5.__h = [], n2.some(function(n3) {
        n3.call(u5);
      });
    } catch (n3) {
      l.__e(n3, u5.__v);
    }
  });
}
function E(n2) {
  return "object" != typeof n2 || null == n2 || n2.__b > 0 ? n2 : g(n2) ? n2.map(E) : void 0 !== n2.constructor ? null : m({}, n2);
}
function G(u4, t3, i3, r3, o3, e3, f4, c3, a3) {
  var s3, h3, p3, v3, y3, w4, _3, m3 = i3.props || d, k4 = t3.props, x4 = t3.type;
  if ("svg" == x4 ? o3 = "http://www.w3.org/2000/svg" : "math" == x4 ? o3 = "http://www.w3.org/1998/Math/MathML" : o3 || (o3 = "http://www.w3.org/1999/xhtml"), null != e3) {
    for (s3 = 0; s3 < e3.length; s3++) if ((y3 = e3[s3]) && "setAttribute" in y3 == !!x4 && (x4 ? y3.localName == x4 : 3 == y3.nodeType)) {
      u4 = y3, e3[s3] = null;
      break;
    }
  }
  if (null == u4) {
    if (null == x4) return document.createTextNode(k4);
    u4 = document.createElementNS(o3, x4, k4.is && k4), c3 && (l.__m && l.__m(t3, e3), c3 = false), e3 = null;
  }
  if (null == x4) m3 === k4 || c3 && u4.data == k4 || (u4.data = k4);
  else {
    if (e3 = "textarea" == x4 && null != k4.defaultValue ? null : e3 && n.call(u4.childNodes), !c3 && null != e3) for (m3 = {}, s3 = 0; s3 < u4.attributes.length; s3++) m3[(y3 = u4.attributes[s3]).name] = y3.value;
    for (s3 in m3) y3 = m3[s3], "dangerouslySetInnerHTML" == s3 ? p3 = y3 : "children" == s3 || s3 in k4 || "value" == s3 && "defaultValue" in k4 || "checked" == s3 && "defaultChecked" in k4 || N(u4, s3, null, y3, o3);
    for (s3 in k4) y3 = k4[s3], "children" == s3 ? v3 = y3 : "dangerouslySetInnerHTML" == s3 ? h3 = y3 : "value" == s3 ? w4 = y3 : "checked" == s3 ? _3 = y3 : c3 && "function" != typeof y3 || m3[s3] === y3 || N(u4, s3, y3, m3[s3], o3);
    if (h3) c3 || p3 && (h3.__html == p3.__html || h3.__html == u4.innerHTML) || (u4.innerHTML = h3.__html), t3.__k = [];
    else if (p3 && (u4.innerHTML = ""), L("template" == t3.type ? u4.content : u4, g(v3) ? v3 : [v3], t3, i3, r3, "foreignObject" == x4 ? "http://www.w3.org/1999/xhtml" : o3, e3, f4, e3 ? e3[0] : i3.__k && $(i3, 0), c3, a3), null != e3) for (s3 = e3.length; s3--; ) b(e3[s3]);
    c3 && "textarea" != x4 || (s3 = "value", "progress" == x4 && null == w4 ? u4.removeAttribute("value") : null != w4 && (w4 !== u4[s3] || "progress" == x4 && !w4 || "option" == x4 && w4 != m3[s3]) && N(u4, s3, w4, m3[s3], o3), s3 = "checked", null != _3 && _3 != u4[s3] && N(u4, s3, _3, m3[s3], o3));
  }
  return u4;
}
function J(n2, u4, t3) {
  try {
    if ("function" == typeof n2) {
      var i3 = "function" == typeof n2.__u;
      i3 && n2.__u(), i3 && null == u4 || (n2.__u = n2(u4));
    } else n2.current = u4;
  } catch (n3) {
    l.__e(n3, t3);
  }
}
function K(n2, u4, t3) {
  var i3, r3;
  if (l.unmount && l.unmount(n2), (i3 = n2.ref) && (i3.current && i3.current != n2.__e || J(i3, null, u4)), null != (i3 = n2.__c)) {
    if (i3.componentWillUnmount) try {
      i3.componentWillUnmount();
    } catch (n3) {
      l.__e(n3, u4);
    }
    i3.base = i3.__P = i3.__n = null;
  }
  if (i3 = n2.__k) for (r3 = 0; r3 < i3.length; r3++) i3[r3] && K(i3[r3], u4, t3 || "function" != typeof n2.type);
  t3 || b(n2.__e), n2.__c = n2.__ = n2.__e = void 0;
}
function Q(n2, l3, u4) {
  return this.constructor(n2, u4);
}
function R(u4, t3, i3) {
  var r3, o3, e3, f4;
  t3 == document && (t3 = document.documentElement), l.__ && l.__(u4, t3), o3 = (r3 = "function" == typeof i3) ? null : i3 && i3.__k || t3.__k, e3 = [], f4 = [], q(t3, u4 = (!r3 && i3 || t3).__k = k(S, null, [u4]), o3 || d, d, t3.namespaceURI, !r3 && i3 ? [i3] : o3 ? null : t3.firstChild ? n.call(t3.childNodes) : null, e3, !r3 && i3 ? i3 : o3 ? o3.__e : t3.firstChild, r3, f4), D(e3, u4, f4), u4.props.children = null;
}
function X(n2) {
  function l3(n3) {
    var u4, t3;
    return this.getChildContext || (u4 = /* @__PURE__ */ new Set(), (t3 = {})[l3.__c] = this, this.getChildContext = function() {
      return t3;
    }, this.componentWillUnmount = function() {
      u4 = null;
    }, this.shouldComponentUpdate = function(n4) {
      this.props.value != n4.value && u4.forEach(function(n5) {
        n5.__e = true, A(n5);
      });
    }, this.sub = function(n4) {
      u4.add(n4);
      var l4 = n4.componentWillUnmount;
      n4.componentWillUnmount = function() {
        u4 && u4.delete(n4), l4 && l4.call(n4);
      };
    }), n3.children;
  }
  return l3.__c = "__cC" + y++, l3.__ = n2, l3.Provider = l3.__l = (l3.Consumer = function(n3, l4) {
    return n3.children(l4);
  }).contextType = l3, l3;
}
n = w.slice, l = { __e: function(n2, l3, u4, t3) {
  for (var i3, r3, o3; l3 = l3.__; ) if ((i3 = l3.__c) && !i3.__) try {
    if ((r3 = i3.constructor) && null != r3.getDerivedStateFromError && (i3.setState(r3.getDerivedStateFromError(n2)), o3 = i3.__d), null != i3.componentDidCatch && (i3.componentDidCatch(n2, t3 || {}), o3 = i3.__d), o3) return i3.__E = i3;
  } catch (l4) {
    n2 = l4;
  }
  throw n2;
} }, u = 0, t = function(n2) {
  return null != n2 && void 0 === n2.constructor;
}, C.prototype.setState = function(n2, l3) {
  var u4;
  u4 = null != this.__s && this.__s != this.state ? this.__s : this.__s = m({}, this.state), "function" == typeof n2 && (n2 = n2(m({}, u4), this.props)), n2 && m(u4, n2), null != n2 && this.__v && (l3 && this._sb.push(l3), A(this));
}, C.prototype.forceUpdate = function(n2) {
  this.__v && (this.__e = true, n2 && this.__h.push(n2), A(this));
}, C.prototype.render = S, i = [], o = "function" == typeof Promise ? Promise.prototype.then.bind(Promise.resolve()) : setTimeout, e = function(n2, l3) {
  return n2.__v.__b - l3.__v.__b;
}, H.__r = 0, f = Math.random().toString(8), c = "__d" + f, a = "__a" + f, s = /(PointerCapture)$|Capture$/i, h = 0, p = V(false), v = V(true), y = 0;

// ../../node_modules/.pnpm/preact@10.29.8/node_modules/preact/hooks/dist/hooks.mjs
var t2;
var r2;
var u2;
var i2;
var o2 = 0;
var f2 = [];
var c2 = l;
var e2 = c2.__b;
var a2 = c2.__r;
var v2 = c2.diffed;
var l2 = c2.__c;
var m2 = c2.unmount;
var p2 = c2.__;
function s2(n2, t3) {
  c2.__h && c2.__h(r2, n2, o2 || t3), o2 = 0;
  var u4 = r2.__H || (r2.__H = { __: [], __h: [] });
  return n2 >= u4.__.length && u4.__.push({}), u4.__[n2];
}
function d2(n2) {
  return o2 = 1, y2(D2, n2);
}
function y2(n2, u4, i3) {
  var o3 = s2(t2++, 2);
  if (o3.t = n2, !o3.__c && (o3.__ = [i3 ? i3(u4) : D2(void 0, u4), function(n3) {
    var t3 = o3.__N ? o3.__N[0] : o3.__[0], r3 = o3.t(t3, n3);
    t3 !== r3 && (o3.__N = [r3, o3.__[1]], o3.__c.setState({}));
  }], o3.__c = r2, !r2.__f)) {
    var f4 = function(n3, t3, r3) {
      if (!o3.__c.__H) return true;
      var u5 = false, i4 = o3.__c.props !== n3;
      if (o3.__c.__H.__.some(function(n4) {
        if (n4.__N) {
          u5 = true;
          var t4 = n4.__[0];
          n4.__ = n4.__N, n4.__N = void 0, t4 !== n4.__[0] && (i4 = true);
        }
      }), c3) {
        var f5 = c3.call(this, n3, t3, r3);
        return u5 ? f5 || i4 : f5;
      }
      return !u5 || i4;
    };
    r2.__f = true;
    var c3 = r2.shouldComponentUpdate, e3 = r2.componentWillUpdate;
    r2.componentWillUpdate = function(n3, t3, r3) {
      if (this.__e) {
        var u5 = c3;
        c3 = void 0, f4(n3, t3, r3), c3 = u5;
      }
      e3 && e3.call(this, n3, t3, r3);
    }, r2.shouldComponentUpdate = f4;
  }
  return o3.__N || o3.__;
}
function h2(n2, u4) {
  var i3 = s2(t2++, 3);
  !c2.__s && C2(i3.__H, u4) && (i3.__ = n2, i3.u = u4, r2.__H.__h.push(i3));
}
function _2(n2, u4) {
  var i3 = s2(t2++, 4);
  !c2.__s && C2(i3.__H, u4) && (i3.__ = n2, i3.u = u4, r2.__h.push(i3));
}
function A2(n2) {
  return o2 = 5, T2(function() {
    return { current: n2 };
  }, []);
}
function T2(n2, r3) {
  var u4 = s2(t2++, 7);
  return C2(u4.__H, r3) && (u4.__ = n2(), u4.__H = r3, u4.__h = n2), u4.__;
}
function q2(n2, t3) {
  return o2 = 8, T2(function() {
    return n2;
  }, t3);
}
function x2(n2) {
  var u4 = r2.context[n2.__c], i3 = s2(t2++, 9);
  return i3.c = n2, u4 ? (null == i3.__ && (i3.__ = true, u4.sub(r2)), u4.props.value) : n2.__;
}
function g2() {
  var n2 = s2(t2++, 11);
  if (!n2.__) {
    for (var u4 = r2.__v; null !== u4 && !u4.__m && null !== u4.__; ) u4 = u4.__;
    var i3 = u4.__m || (u4.__m = [0, 0]);
    n2.__ = "P" + i3[0] + "-" + i3[1]++;
  }
  return n2.__;
}
function j2() {
  for (var n2; n2 = f2.shift(); ) {
    var t3 = n2.__H;
    if (n2.__P && t3) try {
      t3.__h.some(z2), t3.__h.some(B2), t3.__h = [];
    } catch (r3) {
      t3.__h = [], c2.__e(r3, n2.__v);
    }
  }
}
c2.__b = function(n2) {
  r2 = null, e2 && e2(n2);
}, c2.__ = function(n2, t3) {
  n2 && t3.__k && t3.__k.__m && (n2.__m = t3.__k.__m), p2 && p2(n2, t3);
}, c2.__r = function(n2) {
  a2 && a2(n2), t2 = 0;
  var i3 = (r2 = n2.__c).__H;
  i3 && (u2 === r2 ? (i3.__h = [], r2.__h = [], i3.__.some(function(n3) {
    n3.__N && (n3.__ = n3.__N), n3.u = n3.__N = void 0;
  })) : (i3.__h.some(z2), i3.__h.some(B2), i3.__h = [], t2 = 0)), u2 = r2;
}, c2.diffed = function(n2) {
  v2 && v2(n2);
  var t3 = n2.__c;
  t3 && t3.__H && (t3.__H.__h.length && (1 !== f2.push(t3) && i2 === c2.requestAnimationFrame || ((i2 = c2.requestAnimationFrame) || w2)(j2)), t3.__H.__.some(function(n3) {
    n3.u && (n3.__H = n3.u, n3.u = void 0);
  })), u2 = r2 = null;
}, c2.__c = function(n2, t3) {
  t3.some(function(n3) {
    try {
      n3.__h.some(z2), n3.__h = n3.__h.filter(function(n4) {
        return !n4.__ || B2(n4);
      });
    } catch (r3) {
      t3.some(function(n4) {
        n4.__h && (n4.__h = []);
      }), t3 = [], c2.__e(r3, n3.__v);
    }
  }), l2 && l2(n2, t3);
}, c2.unmount = function(n2) {
  m2 && m2(n2);
  var t3, r3 = n2.__c;
  r3 && r3.__H && (r3.__H.__.some(function(n3) {
    try {
      z2(n3);
    } catch (n4) {
      t3 = n4;
    }
  }), r3.__H = void 0, t3 && c2.__e(t3, r3.__v));
};
var k2 = "function" == typeof requestAnimationFrame;
function w2(n2) {
  var t3, r3 = function() {
    clearTimeout(u4), k2 && cancelAnimationFrame(t3), setTimeout(n2);
  }, u4 = setTimeout(r3, 35);
  k2 && (t3 = requestAnimationFrame(r3));
}
function z2(n2) {
  var t3 = r2, u4 = n2.__c;
  "function" == typeof u4 && (n2.__c = void 0, u4()), r2 = t3;
}
function B2(n2) {
  var t3 = r2;
  n2.__c = n2.__(), r2 = t3;
}
function C2(n2, t3) {
  return !n2 || n2.length !== t3.length || t3.some(function(t4, r3) {
    return t4 !== n2[r3];
  });
}
function D2(n2, t3) {
  return "function" == typeof t3 ? t3(n2) : t3;
}

// ../../node_modules/.pnpm/preact@10.29.8/node_modules/preact/compat/dist/compat.mjs
function g3(n2, t3) {
  for (var e3 in t3) n2[e3] = t3[e3];
  return n2;
}
function E2(n2, t3) {
  for (var e3 in n2) if ("__source" !== e3 && !(e3 in t3)) return true;
  for (var r3 in t3) if ("__source" !== r3 && n2[r3] !== t3[r3]) return true;
  return false;
}
function C3(n2, t3) {
  var e3 = t3(), r3 = d2({ t: { __: e3, u: t3 } }), u4 = r3[0].t, o3 = r3[1];
  return _2(function() {
    u4.__ = e3, u4.u = t3, R2(u4) && o3({ t: u4 });
  }, [n2, e3, t3]), h2(function() {
    return R2(u4) && o3({ t: u4 }), n2(function() {
      R2(u4) && o3({ t: u4 });
    });
  }, [n2]), e3;
}
function R2(n2) {
  try {
    return !((t3 = n2.__) === (e3 = n2.u()) && (0 !== t3 || 1 / t3 == 1 / e3) || t3 != t3 && e3 != e3);
  } catch (n3) {
    return true;
  }
  var t3, e3;
}
function x3(n2) {
  n2();
}
function w3(n2) {
  return n2;
}
function k3() {
  return [false, x3];
}
function M2(n2, t3) {
  this.props = n2, this.context = t3;
}
function N2(n2, e3) {
  function r3(n3) {
    var t3 = this.props.ref;
    return t3 != n3.ref && t3 && ("function" == typeof t3 ? t3(null) : t3.current = null), e3 ? !e3(this.props, n3) || t3 != n3.ref : E2(this.props, n3);
  }
  function u4(e4) {
    return this.shouldComponentUpdate = r3, k(n2, e4);
  }
  return u4.displayName = "Memo(" + (n2.displayName || n2.name) + ")", u4.__f = u4.prototype.isReactComponent = true, u4.type = n2, u4;
}
(M2.prototype = new C()).isPureReactComponent = true, M2.prototype.shouldComponentUpdate = function(n2, t3) {
  return E2(this.props, n2) || E2(this.state, t3);
};
var T3 = l.__b;
l.__b = function(n2) {
  n2.type && n2.type.__f && n2.ref && (n2.props.ref = n2.ref, n2.ref = null), T3 && T3(n2);
};
var A3 = "undefined" != typeof Symbol && Symbol.for && /* @__PURE__ */ Symbol.for("react.forward_ref") || 3911;
var O2 = l.__e;
l.__e = function(n2, t3, e3, r3) {
  if (n2.then) {
    for (var u4, o3 = t3; o3 = o3.__; ) if ((u4 = o3.__c) && u4.__c) return null == t3.__e && (t3.__e = e3.__e, t3.__k = e3.__k || []), u4.__c(n2, t3);
  }
  O2(n2, t3, e3, r3);
};
var U2 = l.unmount;
function V2(n2, t3, e3) {
  return n2 && (n2.__c && n2.__c.__H && (n2.__c.__H.__.forEach(function(n3) {
    "function" == typeof n3.__c && n3.__c();
  }), n2.__c.__H = null), null != (n2 = g3({}, n2)).__c && (n2.__c.__P === e3 && (n2.__c.__P = t3), n2.__c.__e = true, n2.__c = null), n2.__k = n2.__k && n2.__k.map(function(n3) {
    return V2(n3, t3, e3);
  })), n2;
}
function W2(n2, t3, e3) {
  return n2 && e3 && (n2.__v = null, n2.__k = n2.__k && n2.__k.map(function(n3) {
    return W2(n3, t3, e3);
  }), n2.__c && n2.__c.__P === t3 && (n2.__e && e3.appendChild(n2.__e), n2.__c.__e = true, n2.__c.__P = e3)), n2;
}
function P3() {
  this.__u = 0, this.o = null, this.__b = null;
}
function j3(n2) {
  var t3 = n2.__ && n2.__.__c;
  return t3 && t3.__a && t3.__a(n2);
}
function B3() {
  this.i = null, this.l = null;
}
l.unmount = function(n2) {
  var t3 = n2.__c;
  t3 && (t3.__z = true), t3 && t3.__R && t3.__R(), t3 && 32 & n2.__u && (n2.type = null), U2 && U2(n2);
}, (P3.prototype = new C()).__c = function(n2, t3) {
  var e3 = t3.__c, r3 = this;
  null == r3.o && (r3.o = []), r3.o.push(e3);
  var u4 = j3(r3.__v), o3 = false, i3 = function() {
    o3 || r3.__z || (o3 = true, e3.__R = null, u4 ? u4(f4) : f4());
  };
  e3.__R = i3;
  var l3 = e3.__P;
  e3.__P = null;
  var f4 = function() {
    if (!--r3.__u) {
      if (r3.state.__a) {
        var n3 = r3.state.__a;
        r3.__v.__k[0] = W2(n3, n3.__c.__P, n3.__c.__O);
      }
      var t4;
      for (r3.setState({ __a: r3.__b = null }); t4 = r3.o.pop(); ) t4.__P = l3, t4.forceUpdate();
    }
  };
  r3.__u++ || 32 & t3.__u || r3.setState({ __a: r3.__b = r3.__v.__k[0] }), n2.then(i3, i3);
}, P3.prototype.componentWillUnmount = function() {
  this.o = [];
}, P3.prototype.render = function(n2, e3) {
  if (this.__b) {
    if (this.__v.__k) {
      var r3 = document.createElement("div"), o3 = this.__v.__k[0].__c;
      this.__v.__k[0] = V2(this.__b, r3, o3.__O = o3.__P);
    }
    this.__b = null;
  }
  var i3 = e3.__a && k(S, null, n2.fallback);
  return i3 && (i3.__u &= -33), [k(S, null, e3.__a ? null : n2.children), i3];
};
var H2 = function(n2, t3, e3) {
  if (++e3[1] === e3[0] && n2.l.delete(t3), n2.props.revealOrder && ("t" !== n2.props.revealOrder[0] || !n2.l.size)) for (e3 = n2.i; e3; ) {
    for (; e3.length > 3; ) e3.pop()();
    if (e3[1] < e3[0]) break;
    n2.i = e3 = e3[2];
  }
};
function Z(n2) {
  return this.getChildContext = function() {
    return n2.context;
  }, n2.children;
}
function Y(n2) {
  var e3 = this, r3 = n2.h;
  if (e3.componentWillUnmount = function() {
    R(null, e3.v), e3.v = null, e3.h = null;
  }, e3.h && e3.h !== r3 && e3.componentWillUnmount(), !e3.v) {
    for (var u4 = e3.__v; null !== u4 && !u4.__m && null !== u4.__; ) u4 = u4.__;
    e3.h = r3, e3.v = { nodeType: 1, parentNode: r3, childNodes: [], __k: { __m: u4.__m }, contains: function() {
      return true;
    }, namespaceURI: r3.namespaceURI, insertBefore: function(n3, t3) {
      this.childNodes.push(n3), e3.h.insertBefore(n3, t3);
    }, removeChild: function(n3) {
      this.childNodes.splice(this.childNodes.indexOf(n3) >>> 1, 1), e3.h.removeChild(n3);
    } };
  }
  R(k(Z, { context: e3.context }, n2.__v), e3.v);
}
function $2(n2, e3) {
  var r3 = k(Y, { __v: n2, h: e3 });
  return r3.containerInfo = e3, r3;
}
(B3.prototype = new C()).__a = function(n2) {
  var t3 = this, e3 = j3(t3.__v), r3 = t3.l.get(n2);
  return r3[0]++, function(u4) {
    var o3 = function() {
      t3.props.revealOrder ? (r3.push(u4), H2(t3, n2, r3)) : u4();
    };
    e3 ? e3(o3) : o3();
  };
}, B3.prototype.render = function(n2) {
  this.i = null, this.l = /* @__PURE__ */ new Map();
  var t3 = F(n2.children);
  n2.revealOrder && "b" === n2.revealOrder[0] && t3.reverse();
  for (var e3 = t3.length; e3--; ) this.l.set(t3[e3], this.i = [1, 0, this.i]);
  return n2.children;
}, B3.prototype.componentDidUpdate = B3.prototype.componentDidMount = function() {
  var n2 = this;
  this.l.forEach(function(t3, e3) {
    H2(n2, e3, t3);
  });
};
var q3 = "undefined" != typeof Symbol && Symbol.for && /* @__PURE__ */ Symbol.for("react.element") || 60103;
var G2 = /^(?:accent|alignment|arabic|baseline|cap|clip(?!PathU)|color|dominant|fill|flood|font|glyph(?!R)|horiz|image(!S)|letter|lighting|marker(?!H|W|U)|overline|paint|pointer|shape|stop|strikethrough|stroke|text(?!L)|transform|underline|unicode|units|v|vector|vert|word|writing|x(?!C))[A-Z]/;
var J2 = /^on(Ani|Tra|Tou|BeforeInp|Compo)/;
var K2 = /[A-Z0-9]/g;
var Q2 = "undefined" != typeof document;
var X2 = function(n2) {
  return ("undefined" != typeof Symbol && "symbol" == typeof /* @__PURE__ */ Symbol() ? /fil|che|rad/ : /fil|che|ra/).test(n2);
};
function nn(n2, t3, e3) {
  return null == t3.__k && (t3.textContent = ""), R(n2, t3), "function" == typeof e3 && e3(), n2 ? n2.__c : null;
}
C.prototype.isReactComponent = true, ["componentWillMount", "componentWillReceiveProps", "componentWillUpdate"].forEach(function(t3) {
  Object.defineProperty(C.prototype, t3, { configurable: true, get: function() {
    return this["UNSAFE_" + t3];
  }, set: function(n2) {
    Object.defineProperty(this, t3, { configurable: true, writable: true, value: n2 });
  } });
});
var en = l.event;
l.event = function(n2) {
  return en && (n2 = en(n2)), n2.persist = function() {
  }, n2.isPropagationStopped = function() {
    return this.cancelBubble;
  }, n2.isDefaultPrevented = function() {
    return this.defaultPrevented;
  }, n2.nativeEvent = n2;
};
var rn;
var un = { configurable: true, get: function() {
  return this.class;
} };
var on = l.vnode;
l.vnode = function(n2) {
  "string" == typeof n2.type && (function(n3) {
    var t3 = n3.props, e3 = n3.type, u4 = {}, o3 = -1 == e3.indexOf("-");
    for (var i3 in t3) {
      var l3 = t3[i3];
      if (!("value" === i3 && "defaultValue" in t3 && null == l3 || Q2 && "children" === i3 && "noscript" === e3 || "class" === i3 || "className" === i3)) {
        var f4 = i3.toLowerCase();
        "defaultValue" === i3 && "value" in t3 && null == t3.value ? i3 = "value" : "download" === i3 && true === l3 ? l3 = "" : "translate" === f4 && "no" === l3 ? l3 = false : "o" === f4[0] && "n" === f4[1] ? "ondoubleclick" === f4 ? i3 = "ondblclick" : "onchange" !== f4 || "input" !== e3 && "textarea" !== e3 || X2(t3.type) ? "onfocus" === f4 ? i3 = "onfocusin" : "onblur" === f4 ? i3 = "onfocusout" : J2.test(i3) && (i3 = f4) : f4 = i3 = "oninput" : o3 && G2.test(i3) ? i3 = i3.replace(K2, "-$&").toLowerCase() : null === l3 && (l3 = void 0), "oninput" === f4 && u4[i3 = f4] && (i3 = "oninputCapture"), u4[i3] = l3;
      }
    }
    "select" == e3 && (u4.multiple && Array.isArray(u4.value) && (u4.value = F(t3.children).forEach(function(n4) {
      n4.props.selected = -1 != u4.value.indexOf(n4.props.value);
    })), null != u4.defaultValue && (u4.value = F(t3.children).forEach(function(n4) {
      n4.props.selected = u4.multiple ? -1 != u4.defaultValue.indexOf(n4.props.value) : u4.defaultValue == n4.props.value;
    }))), t3.class && !t3.className ? (u4.class = t3.class, Object.defineProperty(u4, "className", un)) : t3.className && (u4.class = u4.className = t3.className), n3.props = u4;
  })(n2), n2.$$typeof = q3, on && on(n2);
};
var ln = l.__r;
l.__r = function(n2) {
  ln && ln(n2), rn = n2.__c;
};
var fn = l.diffed;
l.diffed = function(n2) {
  fn && fn(n2);
  var t3 = n2.props, e3 = n2.__e;
  null != e3 && "textarea" === n2.type && "value" in t3 && t3.value !== e3.value && (e3.value = null == t3.value ? "" : t3.value), rn = null;
};
function pn(n2) {
  return !!n2.__k && (R(null, n2), true);
}
var bn = function(n2, t3) {
  var r3, u4 = l.debounceRendering;
  l.debounceRendering = function(n3) {
    r3 = n3;
  };
  try {
    var o3 = n2(t3);
    return r3 && r3(), o3;
  } finally {
    l.debounceRendering = u4;
  }
};

// src/messages.ts
var englishMessages = {
  "sortAscending": "Sort ascending",
  "sortDescending": "Sort descending",
  "openMenuForColumn": "Open menu for {column}",
  "cut": "Cut",
  "copy": "Copy",
  "paste": "Paste",
  "editCell": "Edit cell",
  "clearContents": "Clear contents",
  "undo": "Undo",
  "redo": "Redo",
  "mergeAndCenter": "Merge & Center",
  "mergeAcross": "Merge Across",
  "mergeCells": "Merge Cells",
  "unmergeCells": "Unmerge Cells",
  "rowHeight": "Row Height",
  "columnWidth": "Column Width",
  "pixels": "Pixels",
  "cancel": "Cancel",
  "ok": "OK",
  "hide": "Hide",
  "unhide": "Unhide",
  "selectRow": "Select row",
  "selectColumn": "Select column",
  "selectAll": "Select all",
  "showPivotFieldList": "Show Field List",
  "hidePivotFieldList": "Hide Field List",
  "pivotTableFields": "PivotTable Fields",
  "refreshPivotTable": "Refresh PivotTable",
  "showPivotDetails": "Show Details",
  "expandPivotGroup": "Expand group",
  "collapsePivotGroup": "Collapse group",
  "contextMenu": "Spreadsheet context menu",
  "clipboardCopyUnavailable": "Clipboard access is unavailable. Use the keyboard shortcut to copy.",
  "clipboardPasteUnavailable": "Clipboard access is unavailable. Use the keyboard shortcut to paste.",
  "nothingToPaste": "No spreadsheet cells or text are available to paste.",
  "actionFailed": "The action could not be completed.",
  "workbookSheets": "Workbook sheets",
  "downloadWorkbook": "Download workbook",
  "zoomIn": "Zoom in",
  "zoomOut": "Zoom out",
  "resetZoom": "Reset zoom",
  "hiddenSheet": "{sheet} (hidden)",
  "veryHiddenSheet": "{sheet} (very hidden)",
  "loadingWorkbook": "Loading workbook...",
  "emptyWorkbook": "No workbook loaded.",
  "loadWorkbookFailed": "Could not load workbook.",
  "fileTooLarge": "File size {size} exceeds the configured limit of {limit}.",
  "largeWorkbook": "Large workbook detected",
  "deferredLoadDescription": "This workbook is {size}. Loading it may temporarily make the page unresponsive.",
  "loadAnyway": "Load anyway",
  "worksheetGrid": "{sheet} worksheet grid",
  "workbookGrid": "Workbook grid",
  "dropdownControl": "Dropdown form control",
  "listBoxControl": "List box form control",
  "scrollbarControl": "Scrollbar form control",
  "spinnerControl": "Spinner form control",
  "chart": "Chart",
  "loadingChart": "Loading chart...",
  "loadChartFailed": "Unable to load chart.",
  "mapUnavailable": "Map data is unavailable.",
  "chartUnavailable": "This chart cannot be rendered.",
  "chartsheetUnavailable": "No chart is available for this sheet."
};
var frMessages = {
  "sortAscending": "Trier par ordre croissant",
  "sortDescending": "Trier par ordre d\xE9croissant",
  "openMenuForColumn": "Ouvrir le menu de {column}",
  "cut": "Couper",
  "copy": "Copier",
  "paste": "Coller",
  "editCell": "Modifier la cellule",
  "clearContents": "Effacer le contenu",
  "undo": "Annuler",
  "redo": "R\xE9tablir",
  "mergeAndCenter": "Fusionner et centrer",
  "mergeAcross": "Fusionner par ligne",
  "mergeCells": "Fusionner les cellules",
  "unmergeCells": "Annuler la fusion des cellules",
  "rowHeight": "Hauteur de ligne",
  "columnWidth": "Largeur de colonne",
  "pixels": "Pixels",
  "cancel": "Annuler",
  "ok": "OK",
  "hide": "Masquer",
  "unhide": "Afficher",
  "selectRow": "S\xE9lectionner la ligne",
  "selectColumn": "S\xE9lectionner la colonne",
  "selectAll": "Tout s\xE9lectionner",
  "showPivotFieldList": "Afficher la liste des champs",
  "hidePivotFieldList": "Masquer la liste des champs",
  "pivotTableFields": "Champs du tableau crois\xE9 dynamique",
  "refreshPivotTable": "Actualiser le tableau crois\xE9 dynamique",
  "showPivotDetails": "Afficher les d\xE9tails",
  "expandPivotGroup": "D\xE9velopper le groupe",
  "collapsePivotGroup": "R\xE9duire le groupe",
  "contextMenu": "Menu contextuel du tableur",
  "clipboardCopyUnavailable": "Le presse-papiers est inaccessible. Utilisez le raccourci clavier pour copier.",
  "clipboardPasteUnavailable": "Le presse-papiers est inaccessible. Utilisez le raccourci clavier pour coller.",
  "nothingToPaste": "Aucune cellule ni aucun texte \xE0 coller.",
  "actionFailed": "Impossible de terminer cette action.",
  "workbookSheets": "Feuilles du classeur",
  "downloadWorkbook": "T\xE9l\xE9charger le classeur",
  "zoomIn": "Zoom avant",
  "zoomOut": "Zoom arri\xE8re",
  "resetZoom": "R\xE9initialiser le zoom",
  "hiddenSheet": "{sheet} (masqu\xE9e)",
  "veryHiddenSheet": "{sheet} (tr\xE8s masqu\xE9e)",
  "loadingWorkbook": "Chargement du classeur\u2026",
  "emptyWorkbook": "Aucun classeur charg\xE9.",
  "loadWorkbookFailed": "Impossible de charger le classeur.",
  "fileTooLarge": "La taille du fichier ({size}) d\xE9passe la limite configur\xE9e de {limit}.",
  "largeWorkbook": "Classeur volumineux d\xE9tect\xE9",
  "deferredLoadDescription": "Ce classeur fait {size}. Son chargement peut rendre la page temporairement indisponible.",
  "loadAnyway": "Charger quand m\xEAme",
  "worksheetGrid": "Grille de la feuille {sheet}",
  "workbookGrid": "Grille du classeur",
  "dropdownControl": "Liste d\xE9roulante",
  "listBoxControl": "Zone de liste",
  "scrollbarControl": "Barre de d\xE9filement",
  "spinnerControl": "Compteur",
  "chart": "Graphique",
  "loadingChart": "Chargement du graphique\u2026",
  "loadChartFailed": "Impossible de charger le graphique.",
  "mapUnavailable": "Les donn\xE9es cartographiques sont indisponibles.",
  "chartUnavailable": "Ce graphique ne peut pas \xEAtre affich\xE9.",
  "chartsheetUnavailable": "Aucun graphique disponible pour cette feuille."
};
var deMessages = {
  "sortAscending": "Aufsteigend sortieren",
  "sortDescending": "Absteigend sortieren",
  "openMenuForColumn": "Men\xFC f\xFCr {column} \xF6ffnen",
  "cut": "Ausschneiden",
  "copy": "Kopieren",
  "paste": "Einf\xFCgen",
  "editCell": "Zelle bearbeiten",
  "clearContents": "Inhalte l\xF6schen",
  "undo": "R\xFCckg\xE4ngig",
  "redo": "Wiederholen",
  "mergeAndCenter": "Verbinden und zentrieren",
  "mergeAcross": "Zeilenweise verbinden",
  "mergeCells": "Zellen verbinden",
  "unmergeCells": "Zellverbund aufheben",
  "rowHeight": "Zeilenh\xF6he",
  "columnWidth": "Spaltenbreite",
  "pixels": "Pixel",
  "cancel": "Abbrechen",
  "ok": "OK",
  "hide": "Ausblenden",
  "unhide": "Einblenden",
  "selectRow": "Zeile ausw\xE4hlen",
  "selectColumn": "Spalte ausw\xE4hlen",
  "selectAll": "Alles ausw\xE4hlen",
  "showPivotFieldList": "Feldliste anzeigen",
  "hidePivotFieldList": "Feldliste ausblenden",
  "pivotTableFields": "PivotTable-Felder",
  "refreshPivotTable": "PivotTable aktualisieren",
  "showPivotDetails": "Details anzeigen",
  "expandPivotGroup": "Gruppe erweitern",
  "collapsePivotGroup": "Gruppe reduzieren",
  "contextMenu": "Tabellen-Kontextmen\xFC",
  "clipboardCopyUnavailable": "Kein Zugriff auf die Zwischenablage. Verwenden Sie zum Kopieren die Tastenkombination.",
  "clipboardPasteUnavailable": "Kein Zugriff auf die Zwischenablage. Verwenden Sie zum Einf\xFCgen die Tastenkombination.",
  "nothingToPaste": "Keine Tabellenzellen oder Texte zum Einf\xFCgen verf\xFCgbar.",
  "actionFailed": "Die Aktion konnte nicht abgeschlossen werden.",
  "workbookSheets": "Arbeitsbl\xE4tter",
  "downloadWorkbook": "Arbeitsmappe herunterladen",
  "zoomIn": "Vergr\xF6\xDFern",
  "zoomOut": "Verkleinern",
  "resetZoom": "Zoom zur\xFCcksetzen",
  "hiddenSheet": "{sheet} (ausgeblendet)",
  "veryHiddenSheet": "{sheet} (stark ausgeblendet)",
  "loadingWorkbook": "Arbeitsmappe wird geladen\u2026",
  "emptyWorkbook": "Keine Arbeitsmappe geladen.",
  "loadWorkbookFailed": "Die Arbeitsmappe konnte nicht geladen werden.",
  "fileTooLarge": "Die Dateigr\xF6\xDFe {size} \xFCberschreitet das konfigurierte Limit von {limit}.",
  "largeWorkbook": "Gro\xDFe Arbeitsmappe erkannt",
  "deferredLoadDescription": "Diese Arbeitsmappe ist {size} gro\xDF. Beim Laden reagiert die Seite m\xF6glicherweise vor\xFCbergehend nicht.",
  "loadAnyway": "Trotzdem laden",
  "worksheetGrid": "Tabellenraster von {sheet}",
  "workbookGrid": "Arbeitsmappenraster",
  "dropdownControl": "Dropdown-Steuerelement",
  "listBoxControl": "Listenfeld-Steuerelement",
  "scrollbarControl": "Bildlaufleisten-Steuerelement",
  "spinnerControl": "Drehfeld-Steuerelement",
  "chart": "Diagramm",
  "loadingChart": "Diagramm wird geladen\u2026",
  "loadChartFailed": "Das Diagramm konnte nicht geladen werden.",
  "mapUnavailable": "Kartendaten sind nicht verf\xFCgbar.",
  "chartUnavailable": "Dieses Diagramm kann nicht dargestellt werden.",
  "chartsheetUnavailable": "F\xFCr dieses Blatt ist kein Diagramm verf\xFCgbar."
};
var esMessages = {
  "sortAscending": "Ordenar de forma ascendente",
  "sortDescending": "Ordenar de forma descendente",
  "openMenuForColumn": "Abrir el men\xFA de {column}",
  "cut": "Cortar",
  "copy": "Copiar",
  "paste": "Pegar",
  "editCell": "Editar celda",
  "clearContents": "Borrar contenido",
  "undo": "Deshacer",
  "redo": "Rehacer",
  "mergeAndCenter": "Combinar y centrar",
  "mergeAcross": "Combinar horizontalmente",
  "mergeCells": "Combinar celdas",
  "unmergeCells": "Separar celdas",
  "rowHeight": "Alto de fila",
  "columnWidth": "Ancho de columna",
  "pixels": "P\xEDxeles",
  "cancel": "Cancelar",
  "ok": "Aceptar",
  "hide": "Ocultar",
  "unhide": "Mostrar",
  "selectRow": "Seleccionar fila",
  "selectColumn": "Seleccionar columna",
  "selectAll": "Seleccionar todo",
  "showPivotFieldList": "Mostrar lista de campos",
  "hidePivotFieldList": "Ocultar lista de campos",
  "pivotTableFields": "Campos de tabla din\xE1mica",
  "refreshPivotTable": "Actualizar tabla din\xE1mica",
  "showPivotDetails": "Mostrar detalles",
  "expandPivotGroup": "Expandir grupo",
  "collapsePivotGroup": "Contraer grupo",
  "contextMenu": "Men\xFA contextual de la hoja de c\xE1lculo",
  "clipboardCopyUnavailable": "No se puede acceder al portapapeles. Usa el atajo de teclado para copiar.",
  "clipboardPasteUnavailable": "No se puede acceder al portapapeles. Usa el atajo de teclado para pegar.",
  "nothingToPaste": "No hay celdas ni texto disponibles para pegar.",
  "actionFailed": "No se pudo completar la acci\xF3n.",
  "workbookSheets": "Hojas del libro",
  "downloadWorkbook": "Descargar libro",
  "zoomIn": "Acercar",
  "zoomOut": "Alejar",
  "resetZoom": "Restablecer zoom",
  "hiddenSheet": "{sheet} (oculta)",
  "veryHiddenSheet": "{sheet} (muy oculta)",
  "loadingWorkbook": "Cargando libro\u2026",
  "emptyWorkbook": "No hay ning\xFAn libro cargado.",
  "loadWorkbookFailed": "No se pudo cargar el libro.",
  "fileTooLarge": "El tama\xF1o del archivo ({size}) supera el l\xEDmite configurado de {limit}.",
  "largeWorkbook": "Se ha detectado un libro grande",
  "deferredLoadDescription": "Este libro ocupa {size}. Es posible que la p\xE1gina deje de responder temporalmente al cargarlo.",
  "loadAnyway": "Cargar de todos modos",
  "worksheetGrid": "Cuadr\xEDcula de la hoja {sheet}",
  "workbookGrid": "Cuadr\xEDcula del libro",
  "dropdownControl": "Lista desplegable",
  "listBoxControl": "Cuadro de lista",
  "scrollbarControl": "Barra de desplazamiento",
  "spinnerControl": "Control de n\xFAmero",
  "chart": "Gr\xE1fico",
  "loadingChart": "Cargando gr\xE1fico\u2026",
  "loadChartFailed": "No se pudo cargar el gr\xE1fico.",
  "mapUnavailable": "Los datos del mapa no est\xE1n disponibles.",
  "chartUnavailable": "No se puede mostrar este gr\xE1fico.",
  "chartsheetUnavailable": "No hay ning\xFAn gr\xE1fico disponible para esta hoja."
};
var jaMessages = {
  "sortAscending": "\u6607\u9806\u3067\u4E26\u3079\u66FF\u3048",
  "sortDescending": "\u964D\u9806\u3067\u4E26\u3079\u66FF\u3048",
  "openMenuForColumn": "{column} \u306E\u30E1\u30CB\u30E5\u30FC\u3092\u958B\u304F",
  "cut": "\u5207\u308A\u53D6\u308A",
  "copy": "\u30B3\u30D4\u30FC",
  "paste": "\u8CBC\u308A\u4ED8\u3051",
  "editCell": "\u30BB\u30EB\u3092\u7DE8\u96C6",
  "clearContents": "\u5185\u5BB9\u3092\u30AF\u30EA\u30A2",
  "undo": "\u5143\u306B\u623B\u3059",
  "redo": "\u3084\u308A\u76F4\u3057",
  "mergeAndCenter": "\u30BB\u30EB\u3092\u7D50\u5408\u3057\u3066\u4E2D\u592E\u63C3\u3048",
  "mergeAcross": "\u6A2A\u65B9\u5411\u306B\u7D50\u5408",
  "mergeCells": "\u30BB\u30EB\u3092\u7D50\u5408",
  "unmergeCells": "\u30BB\u30EB\u306E\u7D50\u5408\u3092\u89E3\u9664",
  "rowHeight": "\u884C\u306E\u9AD8\u3055",
  "columnWidth": "\u5217\u306E\u5E45",
  "pixels": "\u30D4\u30AF\u30BB\u30EB",
  "cancel": "\u30AD\u30E3\u30F3\u30BB\u30EB",
  "ok": "OK",
  "hide": "\u975E\u8868\u793A",
  "unhide": "\u518D\u8868\u793A",
  "selectRow": "\u884C\u3092\u9078\u629E",
  "selectColumn": "\u5217\u3092\u9078\u629E",
  "selectAll": "\u3059\u3079\u3066\u9078\u629E",
  "showPivotFieldList": "\u30D5\u30A3\u30FC\u30EB\u30C9\u30EA\u30B9\u30C8\u3092\u8868\u793A",
  "hidePivotFieldList": "\u30D5\u30A3\u30FC\u30EB\u30C9\u30EA\u30B9\u30C8\u3092\u975E\u8868\u793A",
  "pivotTableFields": "\u30D4\u30DC\u30C3\u30C8\u30C6\u30FC\u30D6\u30EB\u306E\u30D5\u30A3\u30FC\u30EB\u30C9",
  "refreshPivotTable": "\u30D4\u30DC\u30C3\u30C8\u30C6\u30FC\u30D6\u30EB\u306E\u66F4\u65B0",
  "showPivotDetails": "\u8A73\u7D30\u306E\u8868\u793A",
  "expandPivotGroup": "\u30B0\u30EB\u30FC\u30D7\u3092\u5C55\u958B",
  "collapsePivotGroup": "\u30B0\u30EB\u30FC\u30D7\u3092\u6298\u308A\u305F\u305F\u3080",
  "contextMenu": "\u30B9\u30D7\u30EC\u30C3\u30C9\u30B7\u30FC\u30C8\u306E\u30B3\u30F3\u30C6\u30AD\u30B9\u30C8\u30E1\u30CB\u30E5\u30FC",
  "clipboardCopyUnavailable": "\u30AF\u30EA\u30C3\u30D7\u30DC\u30FC\u30C9\u306B\u30A2\u30AF\u30BB\u30B9\u3067\u304D\u307E\u305B\u3093\u3002\u30AD\u30FC\u30DC\u30FC\u30C9\u30B7\u30E7\u30FC\u30C8\u30AB\u30C3\u30C8\u3067\u30B3\u30D4\u30FC\u3057\u3066\u304F\u3060\u3055\u3044\u3002",
  "clipboardPasteUnavailable": "\u30AF\u30EA\u30C3\u30D7\u30DC\u30FC\u30C9\u306B\u30A2\u30AF\u30BB\u30B9\u3067\u304D\u307E\u305B\u3093\u3002\u30AD\u30FC\u30DC\u30FC\u30C9\u30B7\u30E7\u30FC\u30C8\u30AB\u30C3\u30C8\u3067\u8CBC\u308A\u4ED8\u3051\u3066\u304F\u3060\u3055\u3044\u3002",
  "nothingToPaste": "\u8CBC\u308A\u4ED8\u3051\u53EF\u80FD\u306A\u30BB\u30EB\u3084\u30C6\u30AD\u30B9\u30C8\u304C\u3042\u308A\u307E\u305B\u3093\u3002",
  "actionFailed": "\u64CD\u4F5C\u3092\u5B8C\u4E86\u3067\u304D\u307E\u305B\u3093\u3067\u3057\u305F\u3002",
  "workbookSheets": "\u30D6\u30C3\u30AF\u306E\u30B7\u30FC\u30C8",
  "downloadWorkbook": "\u30D6\u30C3\u30AF\u3092\u30C0\u30A6\u30F3\u30ED\u30FC\u30C9",
  "zoomIn": "\u62E1\u5927",
  "zoomOut": "\u7E2E\u5C0F",
  "resetZoom": "\u30BA\u30FC\u30E0\u3092\u30EA\u30BB\u30C3\u30C8",
  "hiddenSheet": "{sheet}\uFF08\u975E\u8868\u793A\uFF09",
  "veryHiddenSheet": "{sheet}\uFF08\u5B8C\u5168\u306B\u975E\u8868\u793A\uFF09",
  "loadingWorkbook": "\u30D6\u30C3\u30AF\u3092\u8AAD\u307F\u8FBC\u307F\u4E2D\u2026",
  "emptyWorkbook": "\u30D6\u30C3\u30AF\u304C\u8AAD\u307F\u8FBC\u307E\u308C\u3066\u3044\u307E\u305B\u3093\u3002",
  "loadWorkbookFailed": "\u30D6\u30C3\u30AF\u3092\u8AAD\u307F\u8FBC\u3081\u307E\u305B\u3093\u3067\u3057\u305F\u3002",
  "fileTooLarge": "\u30D5\u30A1\u30A4\u30EB\u30B5\u30A4\u30BA {size} \u306F\u8A2D\u5B9A\u3055\u308C\u305F\u4E0A\u9650 {limit} \u3092\u8D85\u3048\u3066\u3044\u307E\u3059\u3002",
  "largeWorkbook": "\u5927\u304D\u306A\u30D6\u30C3\u30AF\u304C\u691C\u51FA\u3055\u308C\u307E\u3057\u305F",
  "deferredLoadDescription": "\u3053\u306E\u30D6\u30C3\u30AF\u306E\u30B5\u30A4\u30BA\u306F {size} \u3067\u3059\u3002\u8AAD\u307F\u8FBC\u307F\u4E2D\u3001\u4E00\u6642\u7684\u306B\u30DA\u30FC\u30B8\u304C\u5FDC\u7B54\u3057\u306A\u304F\u306A\u308B\u5834\u5408\u304C\u3042\u308A\u307E\u3059\u3002",
  "loadAnyway": "\u8AAD\u307F\u8FBC\u3080",
  "worksheetGrid": "{sheet} \u30EF\u30FC\u30AF\u30B7\u30FC\u30C8\u306E\u30B0\u30EA\u30C3\u30C9",
  "workbookGrid": "\u30D6\u30C3\u30AF\u306E\u30B0\u30EA\u30C3\u30C9",
  "dropdownControl": "\u30C9\u30ED\u30C3\u30D7\u30C0\u30A6\u30F3",
  "listBoxControl": "\u30EA\u30B9\u30C8\u30DC\u30C3\u30AF\u30B9",
  "scrollbarControl": "\u30B9\u30AF\u30ED\u30FC\u30EB\u30D0\u30FC",
  "spinnerControl": "\u30B9\u30D4\u30F3\u30DC\u30BF\u30F3",
  "chart": "\u30B0\u30E9\u30D5",
  "loadingChart": "\u30B0\u30E9\u30D5\u3092\u8AAD\u307F\u8FBC\u307F\u4E2D\u2026",
  "loadChartFailed": "\u30B0\u30E9\u30D5\u3092\u8AAD\u307F\u8FBC\u3081\u307E\u305B\u3093\u3067\u3057\u305F\u3002",
  "mapUnavailable": "\u5730\u56F3\u30C7\u30FC\u30BF\u3092\u5229\u7528\u3067\u304D\u307E\u305B\u3093\u3002",
  "chartUnavailable": "\u3053\u306E\u30B0\u30E9\u30D5\u306F\u8868\u793A\u3067\u304D\u307E\u305B\u3093\u3002",
  "chartsheetUnavailable": "\u3053\u306E\u30B7\u30FC\u30C8\u306B\u306F\u8868\u793A\u53EF\u80FD\u306A\u30B0\u30E9\u30D5\u304C\u3042\u308A\u307E\u305B\u3093\u3002"
};
var ptMessages = {
  "sortAscending": "Ordenar em ordem crescente",
  "sortDescending": "Ordenar em ordem decrescente",
  "openMenuForColumn": "Abrir menu de {column}",
  "cut": "Recortar",
  "copy": "Copiar",
  "paste": "Colar",
  "editCell": "Editar c\xE9lula",
  "clearContents": "Limpar conte\xFAdo",
  "undo": "Desfazer",
  "redo": "Refazer",
  "mergeAndCenter": "Mesclar e centralizar",
  "mergeAcross": "Mesclar atrav\xE9s",
  "mergeCells": "Mesclar c\xE9lulas",
  "unmergeCells": "Desfazer mesclagem de c\xE9lulas",
  "rowHeight": "Altura da linha",
  "columnWidth": "Largura da coluna",
  "pixels": "Pixels",
  "cancel": "Cancelar",
  "ok": "OK",
  "hide": "Ocultar",
  "unhide": "Reexibir",
  "selectRow": "Selecionar linha",
  "selectColumn": "Selecionar coluna",
  "selectAll": "Selecionar tudo",
  "showPivotFieldList": "Mostrar lista de campos",
  "hidePivotFieldList": "Ocultar lista de campos",
  "pivotTableFields": "Campos da tabela din\xE2mica",
  "refreshPivotTable": "Atualizar tabela din\xE2mica",
  "showPivotDetails": "Mostrar detalhes",
  "expandPivotGroup": "Expandir grupo",
  "collapsePivotGroup": "Recolher grupo",
  "contextMenu": "Menu de contexto da planilha",
  "clipboardCopyUnavailable": "N\xE3o \xE9 poss\xEDvel acessar a \xE1rea de transfer\xEAncia. Use o atalho de teclado para copiar.",
  "clipboardPasteUnavailable": "N\xE3o \xE9 poss\xEDvel acessar a \xE1rea de transfer\xEAncia. Use o atalho de teclado para colar.",
  "nothingToPaste": "N\xE3o h\xE1 c\xE9lulas ou texto dispon\xEDveis para colar.",
  "actionFailed": "N\xE3o foi poss\xEDvel concluir a a\xE7\xE3o.",
  "workbookSheets": "Planilhas da pasta de trabalho",
  "downloadWorkbook": "Baixar pasta de trabalho",
  "zoomIn": "Ampliar",
  "zoomOut": "Reduzir",
  "resetZoom": "Redefinir zoom",
  "hiddenSheet": "{sheet} (oculta)",
  "veryHiddenSheet": "{sheet} (muito oculta)",
  "loadingWorkbook": "Carregando pasta de trabalho\u2026",
  "emptyWorkbook": "Nenhuma pasta de trabalho carregada.",
  "loadWorkbookFailed": "N\xE3o foi poss\xEDvel carregar a pasta de trabalho.",
  "fileTooLarge": "O tamanho do arquivo ({size}) excede o limite configurado de {limit}.",
  "largeWorkbook": "Pasta de trabalho grande detectada",
  "deferredLoadDescription": "Esta pasta de trabalho tem {size}. O carregamento pode deixar a p\xE1gina temporariamente sem resposta.",
  "loadAnyway": "Carregar mesmo assim",
  "worksheetGrid": "Grade da planilha {sheet}",
  "workbookGrid": "Grade da pasta de trabalho",
  "dropdownControl": "Lista suspensa",
  "listBoxControl": "Caixa de listagem",
  "scrollbarControl": "Barra de rolagem",
  "spinnerControl": "Controle girat\xF3rio",
  "chart": "Gr\xE1fico",
  "loadingChart": "Carregando gr\xE1fico\u2026",
  "loadChartFailed": "N\xE3o foi poss\xEDvel carregar o gr\xE1fico.",
  "mapUnavailable": "Os dados do mapa n\xE3o est\xE3o dispon\xEDveis.",
  "chartUnavailable": "N\xE3o \xE9 poss\xEDvel exibir este gr\xE1fico.",
  "chartsheetUnavailable": "Nenhum gr\xE1fico dispon\xEDvel para esta planilha."
};
var itMessages = {
  "sortAscending": "Ordina in modo crescente",
  "sortDescending": "Ordina in modo decrescente",
  "openMenuForColumn": "Apri il menu di {column}",
  "cut": "Taglia",
  "copy": "Copia",
  "paste": "Incolla",
  "editCell": "Modifica cella",
  "clearContents": "Cancella contenuto",
  "undo": "Annulla",
  "redo": "Ripeti",
  "mergeAndCenter": "Unisci e centra",
  "mergeAcross": "Unisci per riga",
  "mergeCells": "Unisci celle",
  "unmergeCells": "Separa celle",
  "rowHeight": "Altezza riga",
  "columnWidth": "Larghezza colonna",
  "pixels": "Pixel",
  "cancel": "Annulla",
  "ok": "OK",
  "hide": "Nascondi",
  "unhide": "Scopri",
  "selectRow": "Seleziona riga",
  "selectColumn": "Seleziona colonna",
  "selectAll": "Seleziona tutto",
  "showPivotFieldList": "Mostra elenco campi",
  "hidePivotFieldList": "Nascondi elenco campi",
  "pivotTableFields": "Campi tabella pivot",
  "refreshPivotTable": "Aggiorna tabella pivot",
  "showPivotDetails": "Mostra dettagli",
  "expandPivotGroup": "Espandi gruppo",
  "collapsePivotGroup": "Comprimi gruppo",
  "contextMenu": "Menu contestuale del foglio di calcolo",
  "clipboardCopyUnavailable": "Gli appunti non sono accessibili. Usa la scorciatoia da tastiera per copiare.",
  "clipboardPasteUnavailable": "Gli appunti non sono accessibili. Usa la scorciatoia da tastiera per incollare.",
  "nothingToPaste": "Nessuna cella o testo disponibile da incollare.",
  "actionFailed": "Impossibile completare l\u2019operazione.",
  "workbookSheets": "Fogli della cartella di lavoro",
  "downloadWorkbook": "Scarica cartella di lavoro",
  "zoomIn": "Ingrandisci",
  "zoomOut": "Riduci",
  "resetZoom": "Reimposta zoom",
  "hiddenSheet": "{sheet} (nascosto)",
  "veryHiddenSheet": "{sheet} (molto nascosto)",
  "loadingWorkbook": "Caricamento della cartella di lavoro\u2026",
  "emptyWorkbook": "Nessuna cartella di lavoro caricata.",
  "loadWorkbookFailed": "Impossibile caricare la cartella di lavoro.",
  "fileTooLarge": "La dimensione del file ({size}) supera il limite configurato di {limit}.",
  "largeWorkbook": "Rilevata una cartella di lavoro di grandi dimensioni",
  "deferredLoadDescription": "Questa cartella di lavoro occupa {size}. Durante il caricamento la pagina potrebbe non rispondere temporaneamente.",
  "loadAnyway": "Carica comunque",
  "worksheetGrid": "Griglia del foglio {sheet}",
  "workbookGrid": "Griglia della cartella di lavoro",
  "dropdownControl": "Elenco a discesa",
  "listBoxControl": "Casella di riepilogo",
  "scrollbarControl": "Barra di scorrimento",
  "spinnerControl": "Controllo numerico",
  "chart": "Grafico",
  "loadingChart": "Caricamento del grafico\u2026",
  "loadChartFailed": "Impossibile caricare il grafico.",
  "mapUnavailable": "I dati della mappa non sono disponibili.",
  "chartUnavailable": "Impossibile visualizzare questo grafico.",
  "chartsheetUnavailable": "Nessun grafico disponibile per questo foglio."
};
var zhMessages = {
  "sortAscending": "\u5347\u5E8F\u6392\u5E8F",
  "sortDescending": "\u964D\u5E8F\u6392\u5E8F",
  "openMenuForColumn": "\u6253\u5F00 {column} \u7684\u83DC\u5355",
  "cut": "\u526A\u5207",
  "copy": "\u590D\u5236",
  "paste": "\u7C98\u8D34",
  "editCell": "\u7F16\u8F91\u5355\u5143\u683C",
  "clearContents": "\u6E05\u9664\u5185\u5BB9",
  "undo": "\u64A4\u9500",
  "redo": "\u91CD\u505A",
  "mergeAndCenter": "\u5408\u5E76\u540E\u5C45\u4E2D",
  "mergeAcross": "\u8DE8\u8D8A\u5408\u5E76",
  "mergeCells": "\u5408\u5E76\u5355\u5143\u683C",
  "unmergeCells": "\u53D6\u6D88\u5408\u5E76\u5355\u5143\u683C",
  "rowHeight": "\u884C\u9AD8",
  "columnWidth": "\u5217\u5BBD",
  "pixels": "\u50CF\u7D20",
  "cancel": "\u53D6\u6D88",
  "ok": "\u786E\u5B9A",
  "hide": "\u9690\u85CF",
  "unhide": "\u53D6\u6D88\u9690\u85CF",
  "selectRow": "\u9009\u62E9\u884C",
  "selectColumn": "\u9009\u62E9\u5217",
  "selectAll": "\u5168\u9009",
  "showPivotFieldList": "\u663E\u793A\u5B57\u6BB5\u5217\u8868",
  "hidePivotFieldList": "\u9690\u85CF\u5B57\u6BB5\u5217\u8868",
  "pivotTableFields": "\u6570\u636E\u900F\u89C6\u8868\u5B57\u6BB5",
  "refreshPivotTable": "\u5237\u65B0\u6570\u636E\u900F\u89C6\u8868",
  "showPivotDetails": "\u663E\u793A\u660E\u7EC6",
  "expandPivotGroup": "\u5C55\u5F00\u5206\u7EC4",
  "collapsePivotGroup": "\u6298\u53E0\u5206\u7EC4",
  "contextMenu": "\u7535\u5B50\u8868\u683C\u4E0A\u4E0B\u6587\u83DC\u5355",
  "clipboardCopyUnavailable": "\u65E0\u6CD5\u8BBF\u95EE\u526A\u8D34\u677F\u3002\u8BF7\u4F7F\u7528\u952E\u76D8\u5FEB\u6377\u952E\u590D\u5236\u3002",
  "clipboardPasteUnavailable": "\u65E0\u6CD5\u8BBF\u95EE\u526A\u8D34\u677F\u3002\u8BF7\u4F7F\u7528\u952E\u76D8\u5FEB\u6377\u952E\u7C98\u8D34\u3002",
  "nothingToPaste": "\u6CA1\u6709\u53EF\u7C98\u8D34\u7684\u5355\u5143\u683C\u6216\u6587\u672C\u3002",
  "actionFailed": "\u65E0\u6CD5\u5B8C\u6210\u64CD\u4F5C\u3002",
  "workbookSheets": "\u5DE5\u4F5C\u7C3F\u4E2D\u7684\u5DE5\u4F5C\u8868",
  "downloadWorkbook": "\u4E0B\u8F7D\u5DE5\u4F5C\u7C3F",
  "zoomIn": "\u653E\u5927",
  "zoomOut": "\u7F29\u5C0F",
  "resetZoom": "\u91CD\u7F6E\u7F29\u653E",
  "hiddenSheet": "{sheet}\uFF08\u9690\u85CF\uFF09",
  "veryHiddenSheet": "{sheet}\uFF08\u6DF1\u5EA6\u9690\u85CF\uFF09",
  "loadingWorkbook": "\u6B63\u5728\u52A0\u8F7D\u5DE5\u4F5C\u7C3F\u2026",
  "emptyWorkbook": "\u672A\u52A0\u8F7D\u5DE5\u4F5C\u7C3F\u3002",
  "loadWorkbookFailed": "\u65E0\u6CD5\u52A0\u8F7D\u5DE5\u4F5C\u7C3F\u3002",
  "fileTooLarge": "\u6587\u4EF6\u5927\u5C0F {size} \u8D85\u8FC7\u4E86\u914D\u7F6E\u7684\u9650\u5236 {limit}\u3002",
  "largeWorkbook": "\u68C0\u6D4B\u5230\u5927\u578B\u5DE5\u4F5C\u7C3F",
  "deferredLoadDescription": "\u6B64\u5DE5\u4F5C\u7C3F\u7684\u5927\u5C0F\u4E3A {size}\u3002\u52A0\u8F7D\u65F6\u9875\u9762\u53EF\u80FD\u6682\u65F6\u65E0\u54CD\u5E94\u3002",
  "loadAnyway": "\u4ECD\u7136\u52A0\u8F7D",
  "worksheetGrid": "{sheet} \u5DE5\u4F5C\u8868\u7F51\u683C",
  "workbookGrid": "\u5DE5\u4F5C\u7C3F\u7F51\u683C",
  "dropdownControl": "\u4E0B\u62C9\u5217\u8868\u63A7\u4EF6",
  "listBoxControl": "\u5217\u8868\u6846\u63A7\u4EF6",
  "scrollbarControl": "\u6EDA\u52A8\u6761\u63A7\u4EF6",
  "spinnerControl": "\u6570\u503C\u8C03\u8282\u63A7\u4EF6",
  "chart": "\u56FE\u8868",
  "loadingChart": "\u6B63\u5728\u52A0\u8F7D\u56FE\u8868\u2026",
  "loadChartFailed": "\u65E0\u6CD5\u52A0\u8F7D\u56FE\u8868\u3002",
  "mapUnavailable": "\u5730\u56FE\u6570\u636E\u4E0D\u53EF\u7528\u3002",
  "chartUnavailable": "\u65E0\u6CD5\u663E\u793A\u6B64\u56FE\u8868\u3002",
  "chartsheetUnavailable": "\u6B64\u5DE5\u4F5C\u8868\u6CA1\u6709\u53EF\u7528\u7684\u56FE\u8868\u3002"
};
var catalogs = {
  en: englishMessages,
  fr: frMessages,
  de: deMessages,
  es: esMessages,
  ja: jaMessages,
  pt: ptMessages,
  it: itMessages,
  zh: zhMessages
};
function resolveMessages(locale = "en-US", overrides) {
  let language = "en";
  try {
    language = new Intl.Locale(locale).language;
  } catch {
  }
  return mergeMessages({ ...catalogs[language] ?? englishMessages }, overrides);
}
function mergeMessages(defaults, overrides) {
  if (!overrides) return defaults;
  const messages = { ...defaults };
  for (const key of Object.keys(englishMessages)) {
    if (overrides[key] !== void 0) messages[key] = overrides[key];
  }
  return messages;
}
function formatMessage(message, values) {
  return message.replace(/\{(\w+)\}/g, (placeholder, key) => values[key] ?? placeholder);
}

// src/messages-context.ts
var XlsxMessagesContext = X(englishMessages);
function useXlsxMessages() {
  return x2(XlsxMessagesContext);
}

// ../../node_modules/.pnpm/preact@10.29.8/node_modules/preact/jsx-runtime/dist/jsxRuntime.mjs
var f3 = 0;
function u3(e3, t3, n2, o3, i3, u4) {
  t3 || (t3 = {});
  var a3, c3, p3 = t3;
  if ("ref" in p3) for (c3 in p3 = {}, t3) "ref" == c3 ? a3 = t3[c3] : p3[c3] = t3[c3];
  var l3 = { type: e3, props: p3, key: n2, ref: a3, __k: null, __: null, __b: 0, __e: null, __c: null, constructor: void 0, __v: --f3, __i: -1, __u: 0, __source: i3, __self: u4 };
  if ("function" == typeof e3 && (a3 = e3.defaultProps)) for (c3 in a3) void 0 === p3[c3] && (p3[c3] = a3[c3]);
  return l.vnode && l.vnode(l3), l3;
}

export {
  S,
  C,
  X,
  d2 as d,
  y2 as y,
  h2 as h,
  _2 as _,
  A2 as A,
  T2 as T,
  q2 as q,
  x2 as x,
  g2 as g,
  C3 as C2,
  w3 as w,
  k3 as k,
  N2 as N,
  $2 as $,
  nn,
  pn,
  bn,
  resolveMessages,
  mergeMessages,
  formatMessage,
  XlsxMessagesContext,
  useXlsxMessages,
  u3 as u
};
//# sourceMappingURL=chunk-HAV76TR2.js.map