#!/usr/bin/env bash
# mc-notify 安裝工具
#
#   sudo ./install.sh                          安裝或更新程式與 systemd 服務
#   sudo ./install.sh add <名稱> [--group G]   新增一個伺服器的設定檔
#   sudo ./install.sh check <名稱> [--send-test]
#                                              用服務的身分檢查設定（可順便發測試訊息）
#
# 詳細說明：docs/installation.md
set -euo pipefail

PREFIX=/opt/mc-notify
CONF_DIR=/etc/mc-notify
UNIT_DIR=/etc/systemd/system
SVC_USER=mc-notify
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

info()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m ✓\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m !\033[0m %s\n' "$*" >&2; }
die()   { printf '\033[1;31m ✗\033[0m %s\n' "$*" >&2; exit 1; }

usage() {
    sed -n '2,9p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

require_root() {
    [[ $EUID -eq 0 ]] || die "請用 sudo 執行"
}

require_systemd() {
    command -v systemctl >/dev/null || die "找不到 systemctl，這個工具需要 systemd"
}

valid_name() {
    [[ $1 =~ ^[A-Za-z0-9_-]+$ ]] || die "名稱只能包含英數字、底線和連字號：$1"
}

cmd_install() {
    require_root
    require_systemd

    info "檢查 Python"
    command -v python3 >/dev/null || die "找不到 python3（sudo apt install python3）"
    python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' \
        || die "需要 Python 3.8 以上，目前是 $(python3 --version)"
    ok "$(python3 --version)"

    info "建立服務帳號 ${SVC_USER}"
    if id -u "$SVC_USER" >/dev/null 2>&1; then
        ok "帳號已存在"
    else
        useradd --system --no-create-home --shell /usr/sbin/nologin "$SVC_USER"
        ok "已建立"
    fi

    info "安裝程式到 ${PREFIX}"
    install -d -o root -g root -m 755 "$PREFIX"
    install -o root -g root -m 644 "$SRC_DIR/mc_notify.py" "$PREFIX/mc_notify.py"
    install -o root -g root -m 644 "$SRC_DIR/mc-notify.env.example" "$PREFIX/mc-notify.env.example"
    ok "$(python3 "$PREFIX/mc_notify.py" --version)"

    info "安裝 systemd 服務"
    install -d -o root -g root -m 700 "$CONF_DIR"
    install -o root -g root -m 644 "$SRC_DIR/systemd/mc-notify@.service" "$UNIT_DIR/mc-notify@.service"
    systemctl daemon-reload
    ok "$UNIT_DIR/mc-notify@.service"

    if [[ -e "$UNIT_DIR/mc-notify.service" ]]; then
        warn "偵測到舊版的 mc-notify.service，新舊服務同時執行會重複通知"
        warn "請參考 docs/migration.md 移除舊服務"
    fi

    # 重新啟動正在執行的實例，套用新版程式
    mapfile -t running < <(systemctl list-units --type=service --state=running --plain --no-legend \
        'mc-notify@*.service' | awk '{print $1}')
    if ((${#running[@]})); then
        info "重新啟動執行中的實例"
        systemctl restart "${running[@]}"
        for u in "${running[@]}"; do ok "$u"; done
    fi

    echo
    info "完成。新增伺服器：sudo $0 add <名稱>"
}

cmd_add() {
    require_root
    local name="${1:-}" group=""
    [[ -n $name ]] || usage 1
    valid_name "$name"
    shift
    while (($#)); do
        case $1 in
            --group) group="${2:-}"; [[ -n $group ]] || die "--group 需要群組名稱"; shift 2 ;;
            *) die "未知的參數：$1" ;;
        esac
    done

    [[ -f "$PREFIX/mc-notify.env.example" ]] || die "請先執行 sudo $0 安裝"
    if [[ -n $group ]]; then
        getent group "$group" >/dev/null || die "群組不存在：$group"
    fi
    local conf="$CONF_DIR/$name.env"
    if [[ -e $conf ]]; then
        warn "設定檔已存在，不覆蓋：$conf"
    else
        install -o root -g root -m 600 "$PREFIX/mc-notify.env.example" "$conf"
        ok "已建立 $conf"
    fi

    if [[ -n $group ]]; then
        usermod -aG "$group" "$SVC_USER"
        ok "已將 ${SVC_USER} 加入群組 ${group}（讓它能讀取伺服器的 log）"
    fi

    cat <<MSG

接下來：
  1. 編輯設定檔（至少填 MC_WEBHOOK_URL、MC_RCON_PASSWORD、MC_LOG_PATH）
       sudo nano $conf
  2. 確認伺服器的 server.properties 已開啟 RCON（見 docs/installation.md）
  3. 檢查設定並發送測試訊息
       sudo $0 check $name --send-test
  4. 啟動並設定開機自動執行
       sudo systemctl enable --now mc-notify@$name
MSG
}

cmd_check() {
    require_root
    require_systemd
    local name="${1:-}"
    [[ -n $name ]] || usage 1
    valid_name "$name"
    shift
    local conf="$CONF_DIR/$name.env"
    [[ -f $conf ]] || die "找不到設定檔：$conf（先執行 sudo $0 add $name）"
    command -v systemd-run >/dev/null || die "找不到 systemd-run"

    # 用跟正式服務相同的帳號、設定檔與沙箱執行，結果才準確
    systemd-run --quiet --wait --pipe --collect \
        -p User="$SVC_USER" -p Group="$SVC_USER" \
        -p EnvironmentFile="$conf" \
        -p StateDirectory="mc-notify/$name" \
        -p NoNewPrivileges=yes -p ProtectSystem=strict -p ProtectHome=read-only -p PrivateTmp=yes \
        /usr/bin/python3 "$PREFIX/mc_notify.py" --check "$@"
}

case "${1:-}" in
    "")               cmd_install ;;
    install)          cmd_install ;;
    add)              shift; cmd_add "$@" ;;
    check)            shift; cmd_check "$@" ;;
    -h|--help|help)   usage 0 ;;
    *)                usage 1 ;;
esac
