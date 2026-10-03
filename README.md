# Trae-workbuddy-checkin-server

## 这是什么

把闲置旧手机改造成一台**家庭小服务器** ( 手机端改造 -- HONOR7-HomeServer.md )，跑 TRAE / WorkBuddy 自动签到。

服务端也兼容任意 Linux / macOS，不局限于手机。 

旧手机不用装 Docker，不用刷系统，装个 Termux 即可。插上电源常年待机，白天不用时顺手当个常开的服务节点。

### 能做什么 -- Trae、WorkBuddy

- **定时签到**：每日 **06:00 / 12:00 / 20:00** 三次触发，自动登录 TRAE / WorkBuddy 提交签到，无需人工干预。签到幂等，重复触发不会重复累加积分
- **WorkBuddy 派猫猫旅行**：每日 **06:00 / 12:00 / 20:00** 三次派发旅行任务，保持活跃度
- **HTML 简报台**：电脑浏览器访问 `http://<服务器IP>:8080/report`，实时查看账户状态、今日结果、最近 7 天历史，可直接点按钮手动触发签到或删账户
- **凭据同步**：电脑端跑 `sync-to-nas.bat`，从本机 Trae / WorkBuddy 客户端自动提取登录态并上传到服务端，凭据走本机不经过云
- **断电自愈**：服务以 cron 常驻，手机重启后自动拉起，历史数据自动清理（180 天过期 + 重复账户合并）
- **防干扰执行**：每次签到/旅行触发时 `termux-wake-lock` 保持系统不休眠，失败自动 60s 后重试一次，应对网络抖动和服务未就绪
- **健康自检**：`check.sh` 一键跑 9 项部署完整性检查，覆盖环境/依赖/配置/凭据/服务/日志/数据

### 不做什么

- 不爬 TRAE web 模式（需要 `curl_cffi` 浏览器指纹，Android 6.0 不可行），仅客户端凭据
- 不对外网暴露（默认绑 `0.0.0.0`，需自己配路由器/防火墙）
- 不收集用户数据，所有凭据和历史记录都落在部署机本地 `data/` 目录

### 部署目标

- 一台能开机、有 Wi-Fi、能插电的旧安卓手机（Android 6.0+），或任意 Linux/macOS
- 不想折腾 Docker、不想常驻运行一台主机
- 想让签到/旅行这类定时任务不占电脑，且断电重启后自愈

**不适合**

- 需要多实例、高可用、对外网暴露 —— 那台机器不该是手机
- 追求"服务器"语义纯净度 —— 这台机器本质是台手机，只是被当服务器用

本目录是签到服务的**服务端**实现。配套的电脑端凭据采集脚本在 `local/`，与服务端解耦，仅改一行 `sync.conf` 的目标 IP。

## 架构

```
[电脑端] 采集令牌 → sync-to-nas.bat → HTTP POST 上传到手机
                                         ↓
[手机端] Termux 常驻 HTTP 服务（http.server，绑 0.0.0.0:8080）
         ├─ /api/accounts/trae_client   接收 TRAE 凭据
         ├─ /api/accounts/workbuddy     接收 WorkBuddy 凭据
         ├─ /report                     HTML 简报台（电脑浏览器访问）
         └─ /api/checkin                手动触发签到（简报台按钮）
                                         ↓
         cron 触发签到/旅行：
         ├─ 06:00  python -m checkin --once     # 每日签到（与旅行同步，兜底）
         ├─ 06:00  python -m checkin --travel   # WorkBuddy 派猫猫旅行
         ├─ 12:00  python -m checkin --once     # 签到兜底
         ├─ 12:00  python -m checkin --travel   # WorkBuddy 派猫猫旅行
         ├─ 20:00  python -m checkin --once     # 签到兜底
         └─ 20:00  python -m checkin --travel   # WorkBuddy 派猫猫旅行
```

## 特性

- **零 Docker**：直接在 Termux 跑 Python
- **零 FastAPI/uvicorn**：用 `http.server.ThreadingHTTPServer`（标准库）
- **零 curl_cffi**：仅 TRAE 客户端模式 + WorkBuddy，不依赖浏览器指纹
- **电脑端零改动**：`sync_credentials.py` / `sync-to-nas.bat` 独立于服务端版本，仅 `sync.conf` 改 `NAS_IP`
- **HTML 简报台**：电脑浏览器访问 `http://手机IP:8080/report`，含手动签到/删账户按钮
- **cron 调度**：06:00 / 12:00 / 20:00 三次签到 + 三次旅行，签到幂等，重复触发不累加积分

## 依赖

| 包 | 用途 | Termux v0.79 Python 3.7+ |
| --- | --- | --- |
| requests | HTTP 客户端 | ✓ |
| pycryptodome | WorkBuddy .info 解密 | ✓（wheel 普遍可用） |
| PyYAML | config.yaml 读写 | ✓ |
| tzdata | 时区数据 | ✓ |

砍掉的依赖：`curl_cffi`、`fastapi`、`uvicorn`。

## 部署步骤

### 1. 项目部署

把项目整个目录传到手机 Termux（推荐放 `~/`，目录名随 clone/解压而定）：

```bash
# 电脑端 adb push 通过 USB 数据线或无线调试连接手机
adb push trae-workbuddy-checkin-server /data/data/com.termux/files/home/

# 或 Termux 
git clone https://github.com/rt-dlogix/trae-workbuddy-checkin-server.git

# 内 scp / 复制粘贴
scp -r -P 8022 trae-workbuddy-checkin-server <用户名>@<手机IP>:~/

> Termux 下用户名通常是 `u0_a109` 这类匿名账号（`whoami` 查看）。

```

### 2. 安装

```bash
cd ~/trae-workbuddy-checkin-server
bash install.sh
```

`install.sh` 自动完成：
- `pkg install python termux-api`（crond 已在 Termux v0.79 内置，无需另装）
- `pip install -r requirements.txt`
- 配置 crontab（06:00/12:00/20:00 签到 + 旅行各 3 次 / 周日 03:00 清理）
- 写入 `~/.bashrc`：TZ 时区 + crond 自启 + HTTP 服务自启段

> 时区与 bashrc 自启段已由 `install.sh` 自动写入，无需手动改。

### 3. 启动服务

```bash
cd ~/trae-workbuddy-checkin-server
bash server.sh
```

后台启动 HTTP 服务，监听 `0.0.0.0:8080`，日志写 `data/server.log`。

### 4. 自检

```bash
cd ~/trae-workbuddy-checkin-server
bash check.sh
```

`check.sh` 验证全链部署完整性，9 项检查：

| 项 | 检查内容 |
| --- | --- |
| 1. 系统依赖 | python / crond / termux-api |
| 2. Python 依赖 | requests / Crypto / yaml / tzdata |
| 3. 时区 | `TZ=Asia/Shanghai`，cron 调度时间基准 |
| 4. crond 进程 | 守护进程运行中 |
| 5. crontab | 签到 + 旅行×3 + 清理 任务齐全 |
| 6. bashrc 自启段 | crond + HTTP 服务自启逻辑已写入 |
| 7. HTTP 服务 | 进程运行 + 端口 8080 响应 `/report` |
| 8. 数据目录 | config.yaml / history.json / 账户数 |
| 9. 清理机制 | cron-cleanup.sh 可执行 + cleanup.log 历史 + logger 轮转 + store 180 天删除 + crontab 清理任务 |

输出 `通过 N / 失败 N / 警告 N` 汇总，失败项附修复提示。`install.sh` 安装末尾自动调用一次。

> 日后排查定时任务失效，先跑 `bash check.sh` 一键定位。

### 5. 电脑端配置

改 `local\sync.conf`：

```ini
NAS_IP=手机IP
WEB_PORT=8080
```

（手机 IP 在手机「设置 → WLAN → 当前网络」查看；建议路由器绑定 MAC 固定 IP）

### 6. 上传令牌

电脑端双击 `sync-to-nas.bat`，输入手机 IP，自动上传本机 Trae / WorkBuddy 登录态。

### 7. 查看简报

电脑浏览器访问 `http://手机IP:8080/report`，显示账户状态、今日结果、最近 7 天历史、手动签到按钮。

## 保活与自启

Android 6.0 + Termux v0.79 无 root，用 **MacroDroid + bashrc** 方案（已验证）：

### 开机自启

1. 装 [MacroDroid](https://play.google.com/store/apps/details?id=com.arlosoft.macrodroid)（旧版兼容 Android 6.0）
2. 新建宏：
   - **触发器**：设备开机
   - **动作**：打开应用 → Termux
3. Termux 启动后自动执行 `~/.bashrc`

### bashrc 自动启动

`install.sh` 第 4 步已自动将以下段写入 `~/.bashrc`（幂等，检测标记行 `# checkin-server 自启段`）：

```bash
# 时区（install.sh 已写，此处兜底）
export TZ="Asia/Shanghai"

# 启动 crond（cron 调度签到；继承 TZ 保证 06:00 是北京时间）
if ! pgrep -x crond >/dev/null 2>&1; then
    crond 2>/dev/null
fi

# 启动 checkin-server HTTP 服务（若未运行）
# 项目目录由 install.sh 写入 marker，不依赖固定文件夹名
CHECKIN_SERVER_DIR='/data/data/com.termux/files/home/trae-workbuddy-checkin-server'
if ! pgrep -f "python -m checkin --serve" >/dev/null 2>&1; then
    cd "$CHECKIN_SERVER_DIR" 2>/dev/null && bash server.sh
fi
```

验证已写入：

```bash
grep -A2 'checkin-server 自启段' ~/.bashrc
pgrep -x crond    # 应有 PID
```

### 电池优化

- 手机「设置 → 电池 → Termux」设为「无限制」/「不受限」
- 多任务界面锁死 Termux（锁定后台）
- `server.sh` 已含 `termux-wake-lock` 防 CPU 休眠

## 自动清理

为避免长期累积占满存储，内置清理机制：

| 项 | 机制 | 触发 |
| --- | --- | --- |
| 签到历史 | `store.py` 自动删 >180 天记录 | 每次签到后 |
| 日志轮转 | `logger.py` `TimedRotatingFileHandler` 保留 30 天 | 每天午夜 |
| 重复账户 | `store.dedupe_accounts()` 合并 | 服务启动时 |
| `data/*.log` 截断 | `cron-cleanup.sh` 保留最后 1000 行 | 每周日 03:00 |
| pip 缓存 | `pip cache purge` | 每周日 03:00 |
| apt 缓存 | `apt clean` | 每周日 03:00 |
| `__pycache__` | 删 >7 天未访问 | 每周日 03:00 |
| 轮转日志旧档 | 删 >30 天 `checkin.log.*` | 每周日 03:00 |

清理脚本 `cron-cleanup.sh`，由 `install.sh` 自动配进 crontab。手动跑：

```bash
bash cron-cleanup.sh
cat data/cleanup.log   # 查清理记录
```

## 目录结构

```
trae-workbuddy-checkin-server/
├── checkin/
│   ├── __init__.py
│   ├── __main__.py        # 入口：--serve / --once / --travel
│   ├── logger.py          # 日志（按天轮转）
│   ├── runner.py          # 签到执行
│   ├── store.py           # 数据持久化
│   ├── travel.py          # WorkBuddy 派猫猫旅行状态机
│   ├── web_mobile.py      # HTTP 服务（替代 FastAPI）
│   ├── report.py          # HTML 简报台生成
│   └── platforms/
│       ├── __init__.py
│       ├── base.py
│       ├── trae.py        # TRAE 客户端模式
│       └── workbuddy.py
├── local/                 # 电脑端凭据采集（不部署到手机，仅电脑本地用）
│   ├── sync-to-nas.bat    # 双击运行，自动装依赖 + 交互填 IP
│   └── sync_credentials.py # 从本机 Trae/WorkBuddy 客户端提取登录态并上传
│                            # 注：sync.conf 含内网 IP，不入库，首次运行自动生成
├── data/                  # 运行时生成（含凭据，不入库）
├── config.example.yaml    # 配置模板说明（真实 config.yaml 在 data/，自动生成）
├── requirements.txt
├── install.sh             # 一键安装
├── check.sh               # 自检（install.sh 末尾自动调用）
├── server.sh              # 启动 HTTP 服务
├── stop.sh                # 停止服务
├── cron-checkin.sh        # cron 06:00/12:00/20:00 触发签到（与旅行同步，幂等兜底）
├── cron-travel.sh         # cron 06:00/12:00/20:00 触发旅行
└── cron-cleanup.sh        # cron 周日 03:00 清理日志/缓存
```

> `local/` 内的脚本跑在电脑 Windows 上，采集本机 Trae / WorkBuddy 客户端登录态后 HTTP 上传到服务端。手机端部署时**不需要**这层，`sync-to-nas.bat` 双击即完成凭据导入。

## 与 Docker 部署方案的对比

| 项 | 容器化方案 | 本项目（Termux 直跑） |
| --- | --- | --- |
| 部署 | Docker 容器 | Termux 直跑 |
| Web 框架 | FastAPI + uvicorn | http.server（标准库） |
| Web 控制台 | 完整 static/ HTML | `/report` 简报台 |
| 调度 | 进程内后台线程 | cron 触发 `--once` / `--travel` |
| 依赖数 | 7 | 4（含 tzdata） |
| 常驻目标 | 需一台主机长期运行 | 闲置旧手机插电即可 |

## 故障排查

### `pkg update` 失败

Termux v0.79 旧仓库签名可能失效。换镜像：

```bash
termux-change-repo   # 选镜像
# 或手动改 sources.list
```

### `pip install pycryptodome` 失败

Python 3.7-3.8 wheel 可能缺失。降级：

```bash
pip install pycryptodomex   # 纯 Python 兜底
# 或编译（需 clang + make，3GB 内存可承受）
pkg install clang make
pip install pycryptodome --no-binary :all:
```

### 服务起不来

```bash
cat data/server.log       # 查日志
bash stop.sh && bash server.sh   # 重启
```

### cron 没触发

先跑自检一键定位：

```bash
bash check.sh                 # 8 项全链检查
```

再逐项查：

```bash
crontab -l                # 确认配置
pgrep crond               # 确认 crond 运行
cat data/cron.log         # 查签到日志
cat data/cron-travel.log  # 查旅行日志
```

### 手机休眠漏跑

- 确认 `server.sh` 启动时 `termux-wake-lock` 成功
- MacroDroid 定时（如每小时）打开 Termux 一次，触发 bashrc 检查
- 电池设置：Termux 设「无限制」

## 限制

- **无 TRAE web 模式**：仅客户端凭据（refresh_token 长期续期）。如需 web 模式，需加回 curl_cffi（Android 6.0 不可行）。
- **手机 IP 变动**：DHCP 重分配会断电脑端上传。路由器绑 MAC。
- **WorkBuddy token 过期**：需打开客户端刷新后电脑端重新上传。
- **简报台无鉴权**：默认无密码。如需密码：`export WEB_PASSWORD=xxx` 后启动 server.sh，电脑端 sync-to-nas.bat 会提示输入。

## 致谢

本项目基于 [devilardis/auto-checkin](https://github.com/devilardis/auto-checkin)（MIT License）二次开发。上游项目提供 TRAE / WorkBuddy 的凭据提取、登录态加密与签到 API 交互逻辑，本项目在此基础上改造为 Termux 直跑的服务端实现。

## License

MIT，详见 [LICENSE](LICENSE)。
