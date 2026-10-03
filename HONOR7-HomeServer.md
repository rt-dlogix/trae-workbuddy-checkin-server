# 华为荣耀7 改造 Home Server 实战完整记录

> 设备：荣耀7（PLK-TL01H），Android 6.0，麒麟935，3GB RAM，16/32GB ROM  
> 目标：旧手机变低功耗家庭服务器，运行定时任务、自动化脚本等  
> 最终定位：轻量级个人自动化服务器，不追求 Docker 与重型服务

---

## 一、设备与环境基础信息

| 项目 | 详情 |
|------|------|
| 型号 | 华为荣耀7（PLK-TL01H） |
| 处理器 | 海思麒麟935（八核） |
| 内存 | 3GB RAM |
| 存储 | 16GB / 32GB，支持 MicroSD |
| 系统 | Android 6.0（EMUI 4.0） |
| 网络 | 家庭 Wi-Fi 2.4GHz，路由器支持 DHCP 保留 |

---

## 二、核心原则与限制

- **不要 Root**：荣耀7 Root 风险极高，且收益有限。
- **不要 Docker**：Android 6 内核缺少 cgroups/namespaces，无法运行标准 Docker。
- **不要 Termux:Boot**：与 v0.79 版本签名冲突，Android 6 上极难生效。
- **不要 curl_cffi**：需要 Python 3.13+，旧 Termux 无法安装，改用纯 requests。
- **推荐方案**：Termux + MacroDroid + `.bashrc` 自动执行 + crond（或 busybox crond）。

---

## 三、第一阶段：Termux 安装与基础配置

### 1. 安装包选择
- 必须使用 `termux-v0.79-offline-bootstraps.apk`（GitHub 渠道，签名指纹 `B6:DA:01:48...`）。
- 不要用 Google Play 版本（不支持 Android 6）。

### 2. 修正软件源
安装后打开 Termux，粘贴执行：
```bash
termux-setup-storage && cd ../usr/etc/apt/sources.list.d && rm -rf * && cd ~ && cd ../usr/etc/apt/ && rm -f sources.list && echo "deb http://packages.termux.dev/apt/termux-main-21 stable main" > sources.list && cd ~
```
然后执行：
```bash
pkg update && pkg upgrade -y
```
遇到 `sources.list` 等配置文件提示时，按 `N` 保留当前版本。

### 3. 安装基础工具
```bash
pkg install -y wget curl git nano openssh net-tools tmux
```

### 4. 验证安装
```bash
pkg update
pkg upgrade
apt-get check
dpkg --audit
```
确保无报错，并能成功安装 `openssh`。

---

## 四、第二阶段：SSH 远程控制

### 手机端启动 SSH
```bash
pkg install -y openssh
passwd          # 设置密码，输入时无显示
sshd            # 启动服务
whoami          # 查看用户名，如 u*_a***
ifconfig        # 查看 wlan0 的 inet IP
```

### 电脑端连接
```powershell
ssh -p 8022 u*_a***@192.168.1.xxx
```
首次连接输入 `yes` 接受指纹。

---

## 五、第三阶段：保活与开机自启（核心闭环）

### 1. 系统级保活
- 手机管家 → 应用启动管理 → Termux / MacroDroid：允许自启动、关联启动、后台活动。
- 设置 → 电池 → 电池优化 → 这两个应用设为“不优化”。
- 多任务界面：给 Termux 卡片加锁。

### 2. 放弃 Termux:Boot，采用 MacroDroid
- **MacroDroid 免费版足够**（5 个宏上限，有广告，不影响使用）。
- 宏配置：
  - 触发器：设备启动
  - 动作1：启动应用 → Termux
  - 动作2：等待 30 秒
- 不需要在 MacroDroid 中执行 shell 脚本。

### 3. Termux 内部自动执行
执行一次：
```bash
echo 'termux-wake-lock && sshd' >> ~/.bashrc
```
验证：
```bash
cat ~/.bashrc
```
确保只有一行，无重复。

### 4. 验证开机自启
重启手机 → 等 30 秒 → 观察 Termux 是否自动打开并执行命令。  
然后用电脑重新 SSH 连接（IP 可能变化，用 `ifconfig` 查新 IP）。

---

## 六、踩坑记录与解决方案

| 问题 | 原因 | 解决 |
|------|------|------|
| `E: dpkg was interrupted` | 升级被系统杀后台中断 | `apt --fix-broken install` 或重装 Termux |
| `dpkg: unknown option --configure` | dpkg 主程序损坏 | 同上 |
| 安装 APK 提示签名不一致 | 旧版残留 | 彻底卸载所有 Termux 相关应用（含插件）后重装 |
| `nano` 卡在配置文件冲突 | 等待用户输入 | 按 `N` 或回车保留旧文件 |
| 手机自动重启 | 电池老化或过热 | 拆电池用稳压电源，或智能插座定时供电 |
| 内存不足 | 3GB RAM 被系统占用 | 关闭动画、限制后台进程、停用预装应用 |
| `df -h` 报错 | 缺少 coreutils | `pkg install -y coreutils` |
| `cronie` 无法安装 | 旧源无此包 | 使用 busybox 的 `crond` 或 Shell 死循环 |
| `python-dev` 不存在 | Termux 合并到 python | 直接 `pkg install python` |
| `curl_cffi` 安装失败 | 需要 Python 3.13+ | 从 requirements.txt 删除，改用 requests |

---

## 七、系统优化与内存管理

- 关闭动画：开发者选项 → 窗口/过渡/动画程序时长缩放 → 全关。
- 后台进程限制：开发者选项 → 后台进程限制 → 不得超过 2 个进程。
- 停用预装应用：设置 → 应用管理 → 停用（不要卸载）。
- 查看内存：`free -h`，关注 `available` 值。
- 查看存储：`df -h`，关注 `/data` 分区。
- CPU 限制：`pkg install cpulimit`，`cpulimit -e python -l 50`。
- 进程监控：`htop`、`uptime`。

---

## 八、常用命令速查

```bash
# 查看当前目录
pwd

# 查看 IP
ifconfig

# 启动 SSH
sshd

# 获取唤醒锁
termux-wake-lock

# 进入 tmux 会话
tmux attach -t 会话名

# 脱离 tmux
Ctrl+B 松开 D

# 杀掉指定进程
pkill -f 进程名

# 后台运行
nohup 命令 > 日志 2>&1 &

# 查看内存
free -h

# 查看存储
df -h

# 查看 Python 版本
python --version

# 安装 Python 包
pip install 包名

# 使用 busybox crond
crond
crontab -e
```

---

## 九、最终建议

1. **手机定位**：低功耗、24 小时在线的个人自动化小助手，适合跑 Python 定时任务、轻量 API、文件同步。
2. **不要碰**：Docker、重型数据库、图形界面、完整 Ubuntu 虚拟机。
3. **开发流程**：电脑写代码 → `scp` 传到手机 → 手机 `cron` 定时运行 → 日志排查。
4. **固定 IP**：路由器 DHCP 保留，避免手机重启后 IP 变化导致服务不可用。
5. **定期维护**：检查电池是否鼓包、散热是否良好、存储是否充足。
6. **数据备份**：重要数据不要只存手机，定期同步到电脑或云盘。
