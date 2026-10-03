#!/data/data/com.termux/files/usr/bin/bash
# checkin-server 一键安装脚本（Termux）
# 用法：bash install.sh

set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

echo "============================================================"
echo "  checkin-server 安装（Termux 精简版）"
echo "============================================================"
echo

# ---------- 1. 系统依赖 ----------
echo "[1/6] 安装系统依赖（python / termux-api）..."
pkg update -y
pkg install -y python termux-api
# crond 已在 Termux v0.79 内置，无需额外装包；仅校验可执行
command -v crond >/dev/null 2>&1 \
    && echo "[OK] crond 已就绪（Termux 内置）" \
    || echo "[WARN] crond 未找到，cron 调度可能失败"

# ---------- 2. Python 版本检查 ----------
echo
echo "[2/6] 检查 Python 版本..."
PY_VER=$(python -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>/dev/null || echo "0.0")
echo "  Python 版本：$PY_VER"
if [ "$PY_VER" \< "3.7" ]; then
    echo "[FAIL] Python 版本过低（需 3.7+），当前 $PY_VER"
    echo "       旧版 Termux 仓库可能锁定旧 Python。尝试 pkg install python 或升级 Termux。"
    exit 1
fi

# ---------- 3. Python 依赖（幂等：已装跳过，仅旧版升级，离线可跑） ----------
echo
echo "[3/6] 检查 Python 依赖（requests / pycryptodome / PyYAML / tzdata）..."
# pip 老版本（<21）不支持 PEP 517 build backend，必须先升级
PIP_VER=$(pip --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+' | head -1)
if [ "${PIP_VER:-0}" \< "21" ]; then
    echo "[INFO] pip 版本过低（$PIP_VER），升级 pip ..."
    pip install --upgrade pip
fi
# build 工具链：pycryptodome 含 C 扩展，源编译需 clang + make + pkg-config
# Termux 的 python 包已含头文件，无需 python-dev
pkg install -y clang make pkg-config 2>/dev/null || pkg install -y clang make 2>/dev/null || true
# 已装的 pip 会输出 "Requirement already satisfied" 跳过；-q 安静；--no-cache-dir 不留缓存省空间
pip install -q --no-cache-dir -r requirements.txt
if [ $? -ne 0 ]; then
    echo "[WARN] 部分依赖安装失败，尝试逐个装 ..."
    pip install --no-cache-dir requests
    pip install --no-cache-dir PyYAML
    pip install --no-cache-dir tzdata
    pip install --no-cache-dir pycryptodome || echo "[FAIL] pycryptodome 装不上，WorkBuddy .info 解密将不可用"
fi
echo "[OK] Python 依赖已就绪"

# ---------- 4. 数据目录 + 时区 + bashrc 自启 ----------
echo
echo "[4/6] 创建数据目录 + 设北京时区 + 配 bashrc 自启..."
mkdir -p data
BASHRC="$HOME/.bashrc"

# 时区（幂等：已存在不重复写）
grep -q 'export TZ="Asia/Shanghai"' "$BASHRC" 2>/dev/null \
    || echo 'export TZ="Asia/Shanghai"' >> "$BASHRC"
export TZ="Asia/Shanghai"

# crond + HTTP 服务自启段（幂等：检测标记行，已存在不重复写）
# 注意：自启段内不写死目录名，运行时用 marker 文件动态定位项目目录
# 这样无论 clone 成什么文件夹名，bashrc 都能找到 server.sh
MARKER_PATH="$HERE/server.sh"
grep -q '# checkin-server 自启段' "$BASHRC" 2>/dev/null \
    || cat >> "$BASHRC" <<AUTOEOF

# checkin-server 自启段（install.sh 自动写入）
# 时区（install.sh 已写，此处兜底）
export TZ="Asia/Shanghai"

# 启动 crond（cron 调度签到；继承 TZ 保证 06:00 是北京时间）
if ! pgrep -x crond >/dev/null 2>&1; then
    crond 2>/dev/null
fi

# 启动 checkin-server HTTP 服务（若未运行）
# 项目目录由 install.sh 写入 marker，不依赖固定文件夹名
CHECKIN_SERVER_DIR='$HERE'
if ! pgrep -f "python -m checkin --serve" >/dev/null 2>&1; then
    cd "\$CHECKIN_SERVER_DIR" 2>/dev/null && bash server.sh
fi
AUTOEOF

echo "[OK] data/ 目录 + TZ=Asia/Shanghai + bashrc 自启段（crond + HTTP 服务）"

# ---------- 5. crontab 配置 ----------
echo
echo "[5/6] 配置 crontab（06:00/12:00/20:00 签到 / 06:00、12:00、20:00 旅行 / 周日 03:00 清理）..."
# 先给所有 .sh 加执行权限（Windows push 丢失 +x）
chmod +x *.sh 2>/dev/null || true

CRON_LINE_CHECKIN="0 6,12,20 * * * $HERE/cron-checkin.sh"
CRON_LINE_TRAVEL_06="0 6 * * * $HERE/cron-travel.sh"
CRON_LINE_TRAVEL_12="0 12 * * * $HERE/cron-travel.sh"
CRON_LINE_TRAVEL_20="0 20 * * * $HERE/cron-travel.sh"
CRON_LINE_CLEANUP="0 3 * * 0 $HERE/cron-cleanup.sh"

# Termux BusyBox crontab 不支持管道 stdin，必须用文件方式
# 保留旧 crontab 非本项目任务，合并去重后写临时文件
# 注意：grep 无匹配返回 1，set -e 下会退出，必须 || true
CRON_TMP="$HOME/.crontab.tmp"
{
    crontab -l 2>/dev/null | grep -v "cron-checkin.sh\|cron-travel.sh\|cron-cleanup.sh" || true
    echo "$CRON_LINE_CHECKIN"
    echo "$CRON_LINE_TRAVEL_06"
    echo "$CRON_LINE_TRAVEL_12"
    echo "$CRON_LINE_TRAVEL_20"
    echo "$CRON_LINE_CLEANUP"
} > "$CRON_TMP"

crontab "$CRON_TMP"
rm -f "$CRON_TMP"

# 验证写入成功
if crontab -l 2>/dev/null | grep -q "cron-checkin.sh"; then
    echo "[OK] crontab 已配置："
    echo "  $CRON_LINE_CHECKIN"
    echo "  $CRON_LINE_TRAVEL_06"
    echo "  $CRON_LINE_TRAVEL_12"
    echo "  $CRON_LINE_TRAVEL_20"
    echo "  $CRON_LINE_CLEANUP"
else
    echo "[FAIL] crontab 写入失败"
    echo "       BusyBox crontab 异常，请手动执行：crontab -e"
fi

# ---------- 6. 自检 ----------
echo
echo "[6/6] 运行自检（不阻塞，仅报告）..."
bash check.sh || true

# ---------- 完成 ----------
echo
echo "============================================================"
echo "  安装完成"
echo "============================================================"
echo
echo "下一步："
echo "  1. 启动服务：    bash server.sh（或重启 Termux 触发 bashrc 自启）"
echo "  2. 自检：         bash check.sh"
echo "  3. 保活：         见 README.md「保活与自启」章节"
echo "                   （MacroDroid 开机拉起 Termux + ~/.bashrc 启动 crond）"
echo "  4. 电脑端配置：   改 sync.conf 的 NAS_IP 为手机 IP"
echo "  5. 查看简报：     浏览器访问 http://手机IP:8080/report"
echo
echo "时区：Termux 设 Asia/Shanghai（见 README.md）"
echo
