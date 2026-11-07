# SSO 认证与连接机制（源码级说明）

> 面向接手的 AI / 开发者：读完本文即可独立复现两条 SSO 链路、定位登录失败原因、以及扩展机器人连接。
> 所有源码引用均为 `D:\AI\前端控制台` 仓库内实际路径与行号（随代码变动可能漂移，以函数名为准）。

---

## 0. 一页速览

本工具（前端控制台，海康内网工具）**同时存在两套互相独立的 SSO 认证**，账号体系相同（同一 SSO 账号），但协议、端点、加密方式完全不同：

| 链路 | 目标系统 | 用途 | 源码 |
|---|---|---|---|
| **A. Lanz CAS** | `sso.hikvision.com` → `lanz.hikvision.com` | 查询 AI 额度/用量；提供账号密码给机器人复用 | `src/lanz_quota.py` |
| **B. HikLink PC 登录** | `moa.hikvision.com` → `hiklink-blue/red.hikvision.com` | 登录后注册「机器人」，再走 WebSocket 长连接收发指令 | `src/hiklink_bot.py` |

两条链路都**不走浏览器、不依赖 SSO 前端 JS**，全部是 Python 标准库 + `pycryptodome` 手工还原：

- A：CAS 表单登录 + RSA(PKCS1 v1.5) 加密密码 + AES 自定义请求头令牌
- B：私有登录接口 + **RSA_NO_PADDING 裸模幂**加密密码 + SHA256 设备指纹 + 机器人注册 + WS 协议

关键事实（容易踩坑）：

1. **B 的「SSO 自动注册」已被用户拍板退役**。`ensure_started()` 现在只认「手填 App ID + App Secret」，没有任何 SSO 凭据时明确返回「未配置机器人凭据」。`login_pc()` / `ensure_robot()` 仍保留，仅用于凭据自愈（`_on_auth_failed`）。
2. **A 的凭据是唯一的账号事实源**：`data/lanz_credentials.json`。机器人自愈也从这里取账号密码。
3. 两条链都**绕过系统代理**（公司代理会挂）、**禁用 SSL 证书校验**（内网证书缺 Authority Key Identifier）。
4. 请求头必须带 `Accept-Encoding: identity`，否则网关返回 gzip，`json.loads` 报 `char 0`。

---

## 1. 目录与常量

### 1.1 路径

```
HOME_DIR  = %USERPROFILE%\.serialconsole_pro\          # 锚点目录（固定，不随数据目录迁移）
CONFIG    = HOME_DIR\config.json                       # 含 data_dir 配置
DATA_DIR  = config.data_dir 或 <工具目录>\data          # 默认：源码=项目根\data，exe=exe 旁\data
```

相关文件：

| 文件 | 内容 |
|---|---|
| `DATA_DIR\lanz_credentials.json` | `{"version":1,"username":"...","password":"..."}`，**明文**，原子写 |
| `DATA_DIR\hiklink_session.json` | 机器人/会话状态（见 §4.4），写前自动留 `.bak` |
| `DATA_DIR\hiklink_bot.log` | 机器人链路日志（pythonw 无控制台，排查全靠它） |
| `src/_hiklink_his.blob` | 同事生产实现（zlib + marshal 字节码），仅 `_his()` 兜底加载 |

路径定义见 `src/app_state.py:20-74`；数据目录迁移时会同步 patch `hiklink_bot.SESSION_PATH` 等（`src/server.py:2274-2277`）。

### 1.2 Lanz（链路 A）常量 —— `src/lanz_quota.py:47-65`

```python
LANZ_DASHBOARD = "https://lanz.hikvision.com/resource/dashboard"
API_BASE       = "https://lanz.hikvision.com/v1/ai-resource"
SSO_HOME       = "https://sso.hikvision.com"
UA             = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ... Chrome/120.0 Safari/537.36"
REQUEST_TIMEOUT = 15

RSA_PUB_B64 = "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCqc90wxTr7..."  # 1024-bit, PKCS#8 DER
AES_KEY = b"139074101@SR&LYJ"   # 16 字节
AES_IV  = b"N6s87ssQyWB9ZRFK"   # 16 字节
```

- RSA 公钥来自 `sso.hikvision.com/js/rsa_public_key.js`，1024 位，页面写死。
- AES key/iv 来自 Lanz 前端 `app.js` 模块 9685，写死。

### 1.3 HikLink（链路 B）常量 —— `src/hiklink_bot.py:58-76`

```python
WS_BLUE      = "wss://hiklink-blue.hikvision.com/bot/gateway"
WS_RED       = "wss://hiklink-red.hikvision.com/bot/gateway"
MOAREST_BLUE = "https://hiklink-blue.hikvision.com"
MOAREST_RED  = "https://hiklink-red.hikvision.com"
LOGIN_URL    = "https://moa.hikvision.com/moarestapi/login/pc/v2"
RSA_PUB      = "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAwIxSPJ1umAW8..."  # 2048-bit PEM
UA           = "Mozilla/5.0 (...) Chrome/138.0.0.0 Safari/537.36;name:HiClawPc;platform:win32;arch:x64;user:%s;"
```

双集群（blue / red）：注册与 WS 都先试 blue，失败再试 red。

---

## 2. 链路 A：Lanz CAS 登录（`LanzClient`）

### 2.1 完整流程（`lanz_quota.py:262-327`）

```
1) GET  https://lanz.hikvision.com/resource/dashboard
        └─ opener 自动跟随 302 → sso.hikvision.com 登录页 HTML
        └─ 从 HTML 提取 4 个字段：
             lt          <input name="lt" value="...">
             execution   <input name="execution" value="...">
             salt        <input id="salt" value="...">
             action      <form action="...">
2) POST {SSO_HOME}{action}   (Content-Type: application/x-www-form-urlencoded,
                              Origin/Referer 均设为 SSO)
        username   = 账号
        password   = base64( RSA_PKCS1v15(salt + 明文密码) )
        lt / execution / _eventId=submit
        localDate="" ver="2.0" loginForm="qrLoginForm" fingerprint=""
3) 校验：GET {API_BASE}/dashboard 必须返回 JSON {"code":2001,...}
        code==3001 → 未授权（凭据错/会话没建立）
```

注意：**登录成功的判据是业务 API 的 `code==2001`，不是 302 跳转 URL**。跳转细节不可靠，业务码可证伪。

### 2.2 密码加密（`lanz_quota.py:99-108`）

```python
def encrypt_password(plain, salt):          # salt 每次登录页随机
    msg = (salt + plain).encode("utf-8")
    cipher = PKCS1_v1_5.new(_rsa_key())     # Crypto.Cipher.PKCS1_v1_5
    return base64.b64encode(cipher.encrypt(msg)).decode("ascii")
```

`salt` 是**明文前缀**（不是哈希盐），直接与密码拼接后做 PKCS#1 v1.5 填充加密。

### 2.3 API 请求头令牌（`lanz_quota.py:111-122`）

每个业务 API 请求都必须带：

```
Swms-Request-Token: base64( AES-CBC-PKCS7( "SWMS_<uuid4>_<毫秒时间戳>" ) )
Referer: https://lanz.hikvision.com/resource/dashboard
```

服务端只校验该头**存在且可解密**，不校验内容 —— 每次随机生成即可。

### 2.4 网络层要点（`lanz_quota.py:218-260`）

```python
jar    = http.cookiejar.CookieJar()
ctx    = ssl._create_unverified_context()
opener = build_opener(
    HTTPCookieProcessor(jar),
    ProxyHandler({}),                     # 关键：绕系统代理
    HTTPSHandler(context=ctx))            # 关键：不校验证书
opener.addheaders = [("User-Agent", UA), ("Accept-Encoding", "identity")]
```

- `HTTPError` 也要读 body 前 500 字节（SSO 锁号/风控原因写在响应体里）。
- 非 JSON 响应由 `_classify_nonjson()`（`:143-191`）分类成可读根因：
  - 登录页 + `locked`/`error limit` → 账号锁定（约 8 分钟自动解锁）
  - 登录页 + `wrong`/`password`/`invalid` → 用户名或密码错误
  - 登录页无提示 → 会话失效被重定向（非主动登录失败）
  - gzip 残留（`\x1f\x8b`）→ 编码协商问题
  - 其它 HTML → WAF / 网关错误页（提取 `<title>`）

### 2.5 业务 API

| 方法 | 路径（前缀 `/v1/ai-resource`） | 说明 |
|---|---|---|
| `get_dashboard()` | `/dashboard` | 总览 overview / trend / modelRank / modelTrend |
| `get_budget_overview()` | `/budget/overview` | 部门预算，非管理员可能无权 |
| `get_records(page,size)` | `/records?page=&size=` | 明细，1≤size≤100 |
| `get_credit_pricing()` | `/creditPricing` | 模型积分定价 |
| `is_admin()` | `/budget/isAdmin` | 是否管理员 |

统一返回 `code==2001 → data`；`3001 → LanzSessionExpired`（同时清 `_logged_in`，下次 `login()` 免 force 即可重登）。

### 2.6 线程模型与使用者

- `src/proxy.py:732` `LanzQuotaWorker`：daemon 线程，10 分钟自动刷新（`REFRESH_INTERVAL=600`），失败 60 秒重试，`force_relogin()` 通过 epoch++ 换新 client。
- 凭据读写：`load_credentials / save_credentials / delete_credentials`（`:407-468`），原子写（`tempfile.mkstemp` + `os.replace`）。
- HTTP 接口：`POST /api/proxy/credentials`（`proxy.py:2160`）
  - `{"action":"save","username","password"}` → 落盘 + 提交 worker + 尝试 `hiklink_bot.ensure_started()`
  - `{"action":"clear"}` → 删凭据文件 + `hiklink_bot.clear_account()`（机器人手填凭据不受影响）
- CLI 自测：`python -m src.lanz_quota <账号> <密码>`（打印额度总览）。

---

## 3. 链路 B：HikLink PC 登录 + 机器人注册 + WS

### 3.1 三段式

```
① PC 登录     POST https://moa.hikvision.com/moarestapi/login/pc/v2?pcUid=<uid>
              body(urlencoded): uid, password, pcCode, deviceType=pc,
                                needAutoLogin=true, rsaVer=V2209
              → {"errcode":0,"data":{"token":"..."}}

② 机器人注册   GET  {base}/moarestapi/robot/openclaw                      列表
              POST {base}/moarestapi/robot/openclaw/create                 multipart 创建
              GET  {base}/moarestapi/robot/openclaw/credential?robotNum=X  取 appSecret
              认证头：Authorization: <token>   （原样，不加 Bearer）

③ WS 长连     wss://hiklink-{blue|red}.hikvision.com/bot/gateway
              CLIENT_AUTH → SERVER_AUTH_REPLY → 收 SERVER_MSG_PUSH / 回 CLIENT_MSG_PUSH
```

### 3.2 设备指纹 `pcCode`（`hiklink_bot.py:163-173`）

```python
cpu  = wmic cpu get name 的第一行（失败则 "CPU"）
raw  = "|".join([node(), cpu, architecture()[0], system()])
pcCode = sha256(raw).hexdigest()      # 64 位小写 hex
```

### 3.3 密码加密：RSA_NO_PADDING 裸模幂（`hiklink_bot.py:176-188`）

这是全仓库最容易还原错的地方：

```python
raw = (pc_code + "\u200b" + password).encode("utf-8")   # U+200B 零宽空格，必须保留
m   = bytes_to_long(raw)
sig = pow(m, key.e, key.n)                              # 无填充的 RSA 原语
out = long_to_bytes(sig, 256)                           # 右对齐补零到 256 字节（2048-bit）
return base64.b64encode(out).decode()
```

三个不可省略的细节：

1. 分隔符 `U+200B` 按 **UTF-8 三字节 `E2 80 8B`** 参与加密。用 `encode("ascii","ignore")` 会丢掉它 → 服务端恒报「请求参数不正常」。
2. **不是** PKCS#1 填充，是 `pow(m, e, n)` 裸模幂。
3. 结果定长 256 字节（左补零），不是按密文实际长度输出。

### 3.4 机器人注册 `ensure_robot()`（`hiklink_bot.py:242-316`）

匹配规则（v2.27.9 起的硬要求）：

```
同名机器人中优先 slogan == "前端控制台远程指令通道" 的那台
否则回落：同名第一台（老账号兼容）
```

原因：账号里常有同事 ClaudeDesktop 建的同名机器人，按名字优先会抢别人的机器人 → `KICK_OUT` 互踢、消息收不到。

创建请求是 **multipart/form-data**，必须包含 `name`、`slogan`、`file`（`icon.png`，`image/png`）。头像创建后**平台无更新接口**，所以图标加载失败时 `ensure_robot()` **直接拒绝创建**并报错（避免建出永远灰头像的机器人）。注意 multipart 拼接顺序：文件字节流必须在结束边界 `--boundary--` **之前**，否则服务端收不到文件。

图标来源：`ico/app.png` 或 `ico/app.ico`，PIL 缩放到 ≤256px PNG；都失败 → `_png_1px()` 1x1 灰图（此时拒绝创建）。

### 3.5 WS 协议（`hiklink_bot.py:388-636`）

**连接与重连**：先 blue 后 red，握手超时 5s；失败退避 3s→6→12→30s 封顶。

**认证帧**：

```json
{"appId":"<robot_num>","cmd":"CLIENT_AUTH","transId":"<uuid4>","version":"1.0","appSecret":"<secret>"}
```

**服务端认证回包**：

```json
{"cmd":"SERVER_AUTH_REPLY","result":true,"uid":"<机主登录名>","..."}
```

`result=false` → `auth_failed=True` → 触发 `on_auth_failed` 自愈（非手填模式下：重新 `login_pc` + `ensure_robot` + 换凭据重连，10 分钟防抖）。

**心跳**：每 10 秒 `{"cmd":"HEART_PING","appId":...,"transId":...,"version":"1.0"}`，收到 `HEART_PONG` 忽略。实测服务端约 20s 无有效心跳即断，30s 档活不过首拍。

**收到消息**：

```json
{"cmd":"SERVER_MSG_PUSH",
 "session":"<uid>_<后缀>",
 "transId":"...",
 "msgJson":"{\"asrText\":\"用户文本\",\"sender\":\"<uid>\"}"}
```

`msgJson` 是**字符串**，需二次 `json.loads`。

**回复 / 进度推送**（`:590-635`）：业务体必须序列化后放进 `msgJson`（字符串）。放成对象字段服务端静默丢弃 —— 这是「推送成功但 HikLink 收不到」的历史根因。

```json
{"appId":"<robot_num>","cmd":"CLIENT_MSG_PUSH","finished":0|1,
 "msgJson":"{\"code\":0,\"data\":{\"qaReply\":{\"credibleQa\":{\"id\":\"robot<ms>\",\"answerList\":[{\"type\":\"text\",\"text\":\"...\"}]}}},\"msg\":\"SUCCESS\"}",
 "msgType":"DEFAULT","transId":"<uuid4>","version":"1.2.0","session":"<session>"}
```

- 回复按 1000 字分段（`SEG=1000`），最后一段 `finished=1`；`reply()` 每段重试 8 次（3s 间隔）。
- `push()` 是进度推送，不重试。

**KICK_OUT 是广播不是被踢**：`appId` 为空，服务端在某机器人上线/下线时广播。误当踢下线会自激振荡（每 20-40s 假掉线）。正确处理：忽略，连接保持（`:538-542`）。

**transId 去重**：`_last_trans` 用 `OrderedDict` 保序去重（服务端会重推，重复执行指令）。

### 3.6 机主鉴权（重要安全边界）

- `session` 与 `sender` 均以 SSO 登录名起头（如 `gaoyi13_xxxx`）。
- `_is_owner_session()`（`:1272-1299`）判据：**整串全等** 或 **`候选 + 分隔符（_ - . / :）` 起头**。不能用裸前缀（`gaoyi` 会误匹配 `gaoyi13`），也不能先切首段（账号本身可含 `.`/`-`）。
- `_owner_uids()`（`:1235-1269`）候选来源：
  - 手填模式：`SERVER_AUTH_REPLY` 回包的 `uid` + 磁盘 `robot_uid`；**绝不并入本机当前 SSO 登录名**（共用机场景下 A 手填机器人、B 登录额度，会误把 B 当机主）。
  - 归属未知时返回**空集合** → 调用方 `_is_owner_session` 全拒（fail-closed）。
  - 自动注册模式（已退役）：`robot_uid` / `uid` / `_sso_username()`。
- 非机主消息：回执「该机器人仅响应机主本人的指令」，且**临时切换 session 发回执后恢复原 session_id**（否则后续机主输出会投给攻击者）。

### 3.7 会话状态文件 `hiklink_session.json` 字段

| 字段 | 含义 |
|---|---|
| `uid` / `password` | SSO 账号（自动注册模式残留；`clear_account` 会清） |
| `robot_uid` | 机器人归属登录名（鉴权候选） |
| `robot_num` / `robot_name` / `app_secret` | 自动注册得到的机器人凭据 |
| `app_id` / `app_secret` | **手填**机器人凭据（存在即为手填模式，`is_manual_mode()`） |
| `last_session` | 最近活跃 session，重启后发「已上线」通告用 |
| `harness_sid` | 绑定的小助理 harness 会话 id（登出也不清） |

写入一律走 `_update_session_file(mutate)`（`:99-121`）：锁内读改写 + 写前 `copy2` 到 `.bak` + `tmp` + `os.replace`。登出/清除时**必须删 `.bak`**，否则主文件损坏回滚会让已删凭据「复活」。

### 3.8 手填凭据 API（当前唯一启用途径）

- `set_manual_credentials(app_id, app_secret)`（`:1369-1442`）
  - 两项皆空 = 清除（停机器人 + 删 `.bak`）
  - 只填一项 = 拒绝（不静默清除）
  - 只改 `app_id` + 空 secret = 沿用旧 secret（前端掩码语义）
  - 保存后直接 `_launch()` 重连，不走 `ensure_started()`（避免 `running` 误挡）
- `ensure_started()`（`:1306-1317`）：无手填凭据 → 明确拒绝，**不再回落 SSO 注册**
- `ensure_stopped()`（`:1320-1340`）：`stop()` 后 `join(3)`，否则紧接着的启动会被判定「已在运行」
- `status_snapshot()`（`:1445-1470`）：返回 `username / running / connected / auth_failed / robot_num / manual / app_id / app_secret`
  - `app_secret` 回传明文给本机页面（loopback + Host/Origin 收口）

### 3.9 接入点

| 接入点 | 说明 |
|---|---|
| `src/worker_app.py:151-181` | `/api/hiklink/status`、`/activate`、`/credentials`（进程隔离形态，正常形态） |
| `src/server.py:3417-3447` | 同三路由的 inline 形态（`CLAUDE_INLINE=1` 排障用） |
| `src/server.py:3461-3477` | `CLAUDE_OFFLOAD` 下的 307 兜底重定向到 worker |
| `src/harness/session.py:463` | 判断「hiklink 单例占用的 sid 是否就是本会话」 |
| `src/claude_default.py:1043` | 登出/切账号时的机器人处理 |

前端：`web/js/harness/shell.js:287-380`（登录胶囊、保存机器人、登出）。

### 3.10 指令执行链路（`HikLinkBotController`）

```
SERVER_MSG_PUSH(文本)
  → _on_command → 若有待答 ask 卡片则先当答案提交
  → _run_cmd（后台线程）
      /stop → s.stop()
      否则 → _session() 取/建小助理 harness 会话
             s.send_message(text)
             轮询 s.get_events_after(cursor)：
               ask      → 推编号选择题到 HikLink，记录 _pending_ask
               ask_done → 清 _pending_ask
               tool_use → 每 5s 推一条「工具: 摘要」进度
             等到 result 帧（turn 终止）→ 取最后 assistant 文本 → reply()
```

- 只认 `result` 帧，不信任 `busy`（时序竞态会把中间文本当最终回复）。
- 进程死亡自动 `revive_if_dead()` + 重发一次。
- 单条指令上限 `CMD_TIMEOUT=1800` 秒。
- 忙时新指令入队并立即回进度。

---

## 4. 新 AI 上手：最小可运行复现

### 4.1 依赖

```python
# 必需
pycryptodome          # Crypto.Cipher.PKCS1_v1_5 / AES / Crypto.PublicKey.RSA / Crypto.Util.number
websocket-client      # WS 长连（缺失时 HAS_WS=False，机器人不可用）
pillow                # 机器人头像（可选，缺失则拒绝创建机器人）
```

### 4.2 链路 A：最小验证脚本

```python
import sys
sys.path.insert(0, r"D:\AI\前端控制台")
from src.lanz_quota import LanzClient

c = LanzClient("your_uid", "your_password")
c.login()                       # 成功即 cookie 就位
print(c.get_dashboard()["overview"])
```

CLI 等价：`python -m src.lanz_quota <uid> <pwd>`。

失败时按异常类型分流：`LanzAuthError`（凭据/锁号/登录页结构变化）、`LanzNetworkError`（内网/VPN/代理）、`LanzSessionExpired`（3001，重登即可）。

### 4.3 链路 B：最小验证脚本

```python
import sys, json
sys.path.insert(0, r"D:\AI\前端控制台")
from src import hiklink_bot as hb

token, msg = hb.login_pc("your_uid", "your_password")
print("token:", (token or "")[:12], "...", msg)

num, secret, msg2 = hb.ensure_robot(token)          # 会列表→（必要时）创建→取凭据
print("robot:", num, secret[:8], msg2)

bot = hb.HikLinkBot(num, secret)
bot.on_command = lambda text, tid: bot.reply("收到: " + text[:50])
bot.start()
```

若已有手填凭据，直接走 UI 语义：`hiklink_bot.set_manual_credentials(app_id, app_secret)`。

### 4.4 一步到位的「手工 curl 式」验证（不含 WS）

```bash
# ① 设备指纹（Python 计算，无法用 curl）
python -c "import sys; sys.path.insert(0,r'D:\AI\前端控制台'); from src.hiklink_bot import get_pc_code, encrypt_password; pc=get_pc_code(); print(pc); print(encrypt_password(pc,'密码'))"

# ② 登录
curl -k -X POST "https://moa.hikvision.com/moarestapi/login/pc/v2?pcUid=<uid>" \
  -H "User-Agent: Mozilla/5.0 (...);name:HiClawPc;platform:win32;arch:x64;user:;" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "uid=<uid>&password=<上一步密文>&pcCode=<上一步指纹>&deviceType=pc&needAutoLogin=true&rsaVer=V2209"

# ③ 列机器人
curl -k "https://hiklink-blue.hikvision.com/moarestapi/robot/openclaw" -H "Authorization: <token>"

# ④ 取凭据
curl -k "https://hiklink-blue.hikvision.com/moarestapi/robot/openclaw/credential?robotNum=<num>" -H "Authorization: <token>"
```

---

## 5. 故障排查对照表

| 现象 | 根因 | 处理 |
|---|---|---|
| `响应非 JSON: expecting value: line 1 column 1 (char 0)` | gzip 正文 / WAF / 被重定向回登录页 | 确认 `Accept-Encoding: identity`；看 `_classify_nonjson` 给出的分类 |
| `登录页结构变化：缺少 lt/execution/salt/action` | SSO 页面改版 | 更新 `_extract_field` 正则；注意排除 `data-value` |
| 账号锁定 | 密码错多次 | 等约 8 分钟，或到 sso.hikvision.com 点 Unlock account |
| HikLink 登录恒报「请求参数不正常」 | 密码加密丢了 `U+200B` 或用错填充方式 | 严格按 §3.3：UTF-8 + 裸模幂 + 256 字节右对齐 |
| 机器人消息发得出去但收不到 | 回复业务体放错字段（须在 `msgJson` 字符串里） | 照 `reply()` 的帧结构 |
| 机器人每 20-40s 假掉线 | 把 `KICK_OUT` 广播当踢下线 | 忽略该帧 |
| 机器人互踢 | 账号里有同名机器人（同事 ClaudeDesktop） | 按 `slogan` 匹配；别按名字抢 |
| 机器人头像是默认灰图 | 创建时 multipart 把文件拼在结束边界之后 | 文件字节流置于 `--boundary--` 之前 |
| 保存新凭据后永久离线却回报成功 | `stop()` 未 join，`running` 仍为真 | 用 `ensure_stopped()`（内部 join 3s） |
| 「已上线」通告发给了别人 | `last_session` 是上一个账号的 | `_is_owner_session` 前缀+分隔符判归属 |
| 内网证书报错 | Missing Authority Key Identifier | 两条链都禁用 SSL 校验（`_create_unverified_context` / `CERT_NONE`） |
| 公司代理导致挂死 | 系统代理不可用 | `ProxyHandler({})` 绕过 |

---

## 6. 安全边界（改动前必读）

1. **禁用 SSL 校验 + 需要内网** → 威胁模型是「内网可被 MITM」。因此 CAS 登录页的 `action` 必须校验：只允许相对路径或 `sso.hikvision.com`，否则拒绝（`lanz_quota.py:297-310`）——防止凭据被 POST 到攻击者主机。
2. **凭据明文落盘**（`lanz_credentials.json`、`hiklink_session.json`），依赖目录权限，不做额外加密。
3. **机器人是远程指令通道**：任意能给机器人发消息的 HikLink 用户都能驱动本机 Claude，因此有 `_is_owner_session` fail-closed 鉴权 + ask 卡片鉴权 + 拒绝路径不改 `session_id`。
4. **手填凭据与 SSO 账号正交**：登出只清账号字段，不停机器人、不删手填 `app_secret`；有 `app_id` 时任何自愈/注册路径都**绝不覆盖**用户手填值。
5. 所有跨线程共享文件的写操作走 `_update_session_file`，禁止裸「读-改-写」。

---

## 7. 代码地图（按职责）

```
src/lanz_quota.py           链路 A 全部实现（加密/登录/API/凭据/CLI）
src/proxy.py                LanzQuotaWorker（额度轮询）+ /api/proxy/credentials
src/hiklink_bot.py          链路 B 全部实现（设备指纹/登录/注册/WS/控制器/鉴权）
src/worker_app.py           /api/hiklink/* 路由（进程隔离常态）
src/server.py               inline 路由 + CLAUDE_OFFLOAD 307 兜底
src/app_state.py            HOME_DIR / CONFIG_FILE / DATA_DIR
src/harness/session.py      hiklink 与 harness 会话的绑定判定
src/claude_default.py       账号切换时的机器人协同
web/js/harness/shell.js     登录胶囊/机器人凭据 UI
前端控制台.spec             hiddenimports：Crypto.* / websocket
```

---

## 8. 一句话交接

- 想要**额度数据**：用 `LanzClient`（`src/lanz_quota.py`），账号密码来自 `data/lanz_credentials.json`。
- 想要**远程收发指令**：机器人走「手填 App ID + App Secret」直连 WS，协议实现在 `src/hiklink_bot.py`；SSO 登录/注册只在凭据自愈时使用。
- 任何登录失败，先看 `_classify_nonjson` 的根因字符串和 `data/hiklink_bot.log`，不要盲目重试（会锁号）。
