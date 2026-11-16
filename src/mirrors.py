# -*- coding: utf-8 -*-
"""在线安装镜像源注册表（a595 二批，用户定调「镜像要多、可自选、默认加速」）。

为什么独立成模块：镜像档位同时被四处消费——claude_setup 的下载器（node/git
安装器）、_npm_install_global / codegraph 分支（npm registry）、install_online
的 pydeps 分支（pip index）、net_check 预检（探测口径必须与真实下载源一致）。
注册表放一处，任何一处改判据都不会分裂成「预检说通、下载走另一条」。

档位（config.json 的 `online_mirror` 键，用户在 设置→外部依赖安装 选择）：
  auto      默认——国内镜像优先、官方兜底（每通道取首选镜像，见 _PREFERRED）
  official  官方直连优先、镜像兜底（外网无障碍机器）
  off       纯官方直连（镜像完全不参与）
  <pid>     指定服务商优先；该家没覆盖的通道回退 auto 行为

所有镜像 URL 均 2026-11-16 curl 实测 200/302（含 node msi/zip 与 git exe 的
完整路径拼接）；换 URL 前必须重测——仓库铁律（_GIT_URL 曾 404 的教训）。
"""

# 服务商 → 各通道镜像基址（None = 该家不镜像此通道）
_PROVIDERS = {
    "npmmirror": {"name": "淘宝 npmmirror",
                  "pip": None,
                  "npm": "https://registry.npmmirror.com",
                  "node_bin": "https://registry.npmmirror.com/-/binary/node",
                  "git_bin": "https://registry.npmmirror.com/-/binary/git-for-windows"},
    "tencent":   {"name": "腾讯云",
                  "pip": "https://mirrors.cloud.tencent.com/pypi/simple/",
                  "npm": "https://mirrors.cloud.tencent.com/npm/",
                  "node_bin": "https://mirrors.cloud.tencent.com/nodejs-release",
                  "git_bin": None},
    "huawei":    {"name": "华为云",
                  "pip": "https://mirrors.huaweicloud.com/repository/pypi/simple",
                  "npm": "https://mirrors.huaweicloud.com/repository/npm/",
                  "node_bin": "https://mirrors.huaweicloud.com/nodejs",
                  "git_bin": None},
    "aliyun":    {"name": "阿里云",
                  "pip": "https://mirrors.aliyun.com/pypi/simple/",
                  "npm": None,
                  "node_bin": "https://mirrors.aliyun.com/nodejs-release",
                  "git_bin": None},
    "tuna":      {"name": "清华 TUNA",
                  "pip": "https://pypi.tuna.tsinghua.edu.cn/simple",
                  "npm": None, "node_bin": None, "git_bin": None},
    "ustc":      {"name": "中国科大",
                  "pip": "https://mirrors.ustc.edu.cn/pypi/simple/",
                  "npm": None, "node_bin": None, "git_bin": None},
    "bfsu":      {"name": "北京外国语",
                  "pip": "https://mirrors.bfsu.edu.cn/pypi/web/simple/",
                  "npm": None, "node_bin": None, "git_bin": None},
}

# auto 档每通道的首选镜像（国内实测最稳的组合）
_PREFERRED = {"pip": "tuna", "npm": "npmmirror",
              "node_bin": "npmmirror", "git_bin": "npmmirror"}

_CHANNEL_NAMES = {"pip": "pip 依赖", "npm": "npm 包",
                  "node_bin": "Node 安装器", "git_bin": "Git 安装器"}

_OFFICIAL = {"pip": "https://pypi.org/simple",
             "npm": "https://registry.npmjs.org",
             "node_bin": "https://nodejs.org/dist",
             "git_bin": "https://github.com/git-for-windows/git/releases/download"}

MODES = ("auto", "official", "off")


def mode_ids():
    """全部合法档位 id（auto/official/off + 服务商 pid）——API 校验用。"""
    return set(MODES) | set(_PROVIDERS)


def mode():
    """当前档位。config 读不到/非法值一律回 auto（默认镜像优先）。"""
    try:
        from .app_state import _load_config
        m = (_load_config().get("online_mirror") or "auto").strip()
    except Exception:
        return "auto"
    return m if (m in MODES or m in _PROVIDERS) else "auto"


def options():
    """前端下拉的完整选项表 [{id, name}]（auto/official/off + 服务商）。"""
    out = [{"id": "auto", "name": "智能·镜像优先（推荐）"},
           {"id": "official", "name": "官方直连优先（镜像兜底）"},
           {"id": "off", "name": "纯官方直连（不走镜像）"}]
    out += [{"id": pid, "name": p["name"] + " 优先"} for pid, p in _PROVIDERS.items()]
    return out


def _order(channel, official_url, prov_urls):
    """按档位排出该通道的候选 URL（首位=首选，官方恒在列兜底）。

    prov_urls: {pid: url}——该通道有镜像的服务商。
    """
    m = mode()
    if m == "off":
        return [official_url]
    if m == "official":
        return [official_url] + list(prov_urls.values())
    if m in prov_urls:
        rest = [u for p, u in prov_urls.items() if p != m]
        return [prov_urls[m], official_url] + rest
    # auto（或指定服务商不覆盖此通道 → 回退 auto 行为）
    pref = _PREFERRED.get(channel)
    ordered = []
    if pref and pref in prov_urls:
        ordered.append(prov_urls[pref])
    ordered += [u for p, u in prov_urls.items() if p != pref]
    ordered.append(official_url)
    return ordered


def pip_index_list():
    """pip -i 候选（有序）。"""
    return _order("pip", _OFFICIAL["pip"],
                  {pid: p["pip"] for pid, p in _PROVIDERS.items() if p["pip"]})


def npm_registry_list():
    """npm --registry 候选（有序）。"""
    return _order("npm", _OFFICIAL["npm"],
                  {pid: p["npm"] for pid, p in _PROVIDERS.items() if p["npm"]})


def node_bin_urls(ver_dir, fname):
    """Node 安装器候选（有序）：ver_dir 如 v24.19.0，fname 如 node-v24.19.0-x64.msi。"""
    official = "%s/%s/%s" % (_OFFICIAL["node_bin"], ver_dir, fname)
    provs = {pid: "%s/%s/%s" % (p["node_bin"], ver_dir, fname)
             for pid, p in _PROVIDERS.items() if p["node_bin"]}
    return _order("node_bin", official, provs)


def git_bin_urls(tag, fname):
    """Git 安装器候选（有序）：tag 如 v2.55.0.windows.5，fname 如 Git-2.55.0.5-64-bit.exe。"""
    official = "%s/%s/%s" % (_OFFICIAL["git_bin"], tag, fname)
    provs = {pid: "%s/%s/%s" % (p["git_bin"], tag, fname)
             for pid, p in _PROVIDERS.items() if p["git_bin"]}
    return _order("git_bin", official, provs)


def describe():
    """当前镜像计划的人话（日志首行 / 设置页提示共用一份口径）。"""
    m = mode()
    if m == "off":
        return "镜像加速：已关闭（纯官方直连）"
    if m == "official":
        return "镜像加速：官方直连优先，失败自动换镜像"
    if m in _PROVIDERS:
        cov = [name for ch, name in _CHANNEL_NAMES.items() if _PROVIDERS[m][ch]]
        return "镜像加速：%s 优先（覆盖：%s；未覆盖通道回退智能）" % (
            _PROVIDERS[m]["name"], "、".join(cov) or "无")
    pref = "、".join("%s→%s" % (_CHANNEL_NAMES[ch], _PROVIDERS[p]["name"])
                     for ch, p in _PREFERRED.items())
    return "镜像加速：智能模式（%s · 微软下载走官方 fwlink）" % pref
