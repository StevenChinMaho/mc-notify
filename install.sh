#!/usr/bin/env bash
# mc-notify 安裝工具
#
#   sudo ./install.sh [--user U]               安裝或更新程式與 systemd 服務
#   sudo ./install.sh add <名稱> [--user U] [--group G]
#                                              新增一個伺服器的設定檔
#   sudo ./install.sh check <名稱> [--send-test]
#                                              用服務的身分檢查設定（可順便發測試訊息）
#
#   --user  服務要用哪個帳號執行。省略時使用專用帳號 mc-notify（不存在就建立）；
#           指定既有帳號（例如跑伺服器的 minecraft）時不會建立新帳號。
#           在 install 指定是全域預設，在 add 指定則只套用到該實例。
#   --group 把服務帳號加入這個群組，讓它讀得到伺服器的 log
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
    awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "${BASH_SOURCE[0]}"
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

# 寫入 systemd drop-in，指定服務要用哪個帳號執行
# $1 = drop-in 目錄（全域或單一實例）  $2 = 帳號
write_user_dropin() {
    local dir="$1" user="$2" group
    group="$(id -gn "$user")"
    install -d -o root -g root -m 755 "$dir"
    cat > "$dir/10-user.conf" <<CONF
# 由 install.sh 產生：指定服務的執行身分
[Service]
User=$user
Group=$group
CONF
    chmod 644 "$dir/10-user.conf"
    ok "執行身分設為 ${user}:${group}（$dir/10-user.conf）"
}

# 目前實際生效的執行身分（會把 drop-in 算進去）
effective_user() {
    local unit="mc-notify@$1.service" user
    user="$(systemctl show -p User --value "$unit" 2>/dev/null || true)"
    echo "${user:-$SVC_USER}"
}

cmd_install() {
    require_root
    require_systemd
    local user=""
    while (($#)); do
        case $1 in
            --user) user="${2:-}"; [[ -n $user ]] || die "--user 需要帳號名稱"; shift 2 ;;
            *) die "未知的參數：$1" ;;
        esac
    done

    info "檢查 Python"
    command -v python3 >/dev/null || die "找不到 python3（sudo apt install python3）"
    python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' \
        || die "需要 Python 3.8 以上，目前是 $(python3 --version)"
    ok "$(python3 --version)"

    info "服務帳號"
    local configured=""
    if [[ -f "$UNIT_DIR/mc-notify@.service.d/10-user.conf" ]]; then
        configured="$(sed -n 's/^User=//p' "$UNIT_DIR/mc-notify@.service.d/10-user.conf" | head -n1)"
    fi
    if [[ -n $user && $user != "$SVC_USER" ]]; then
        id -u "$user" >/dev/null 2>&1 || die "帳號不存在：$user"
        ok "使用既有帳號 $user"
    elif [[ -z $user && -n $configured && $configured != "$SVC_USER" ]]; then
        # 之前設定過其他帳號，更新時沿用，不建立專用帳號
        ok "沿用現有的執行身分 $configured（要改回專用帳號請加 --user $SVC_USER）"
    elif id -u "$SVC_USER" >/dev/null 2>&1; then
        ok "使用專用帳號 $SVC_USER（已存在）"
    else
        useradd --system --no-create-home --shell /usr/sbin/nologin "$SVC_USER"
        ok "已建立專用帳號 $SVC_USER"
    fi

    info "安裝程式到 ${PREFIX}"
    install -d -o root -g root -m 755 "$PREFIX"
    install -o root -g root -m 644 "$SRC_DIR/mc_notify.py" "$PREFIX/mc_notify.py"
    install -o root -g root -m 644 "$SRC_DIR/mc-notify.env.example" "$PREFIX/mc-notify.env.example"
    ok "$(python3 "$PREFIX/mc_notify.py" --version)"

    info "安裝 systemd 服務"
    install -d -o root -g root -m 700 "$CONF_DIR"
    install -o root -g root -m 644 "$SRC_DIR/systemd/mc-notify@.service" "$UNIT_DIR/mc-notify@.service"
    ok "$UNIT_DIR/mc-notify@.service"
    if [[ -n $user && $user == "$SVC_USER" ]]; then
        rm -rf "$UNIT_DIR/mc-notify@.service.d"
        ok "已改回專用帳號 $SVC_USER"
    elif [[ -n $user ]]; then
        write_user_dropin "$UNIT_DIR/mc-notify@.service.d" "$user"
    elif [[ -n $configured ]]; then
        ok "保留現有的執行身分設定（$UNIT_DIR/mc-notify@.service.d/10-user.conf）"
    fi
    systemctl daemon-reload

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
    require_systemd
    local name="${1:-}" group="" user=""
    [[ -n $name ]] || usage 1
    valid_name "$name"
    shift
    while (($#)); do
        case $1 in
            --group) group="${2:-}"; [[ -n $group ]] || die "--group 需要群組名稱"; shift 2 ;;
            --user)  user="${2:-}";  [[ -n $user ]]  || die "--user 需要帳號名稱"; shift 2 ;;
            *) die "未知的參數：$1" ;;
        esac
    done

    [[ -f "$PREFIX/mc-notify.env.example" ]] || die "請先執行 sudo $0 安裝"
    if [[ -n $group ]]; then
        getent group "$group" >/dev/null || die "群組不存在：$group"
    fi
    if [[ -n $user ]]; then
        id -u "$user" >/dev/null 2>&1 || die "帳號不存在：$user"
    fi
    local conf="$CONF_DIR/$name.env"
    if [[ -e $conf ]]; then
        warn "設定檔已存在，不覆蓋：$conf"
    else
        install -o root -g root -m 600 "$PREFIX/mc-notify.env.example" "$conf"
        ok "已建立 $conf"
    fi

    if [[ -n $user ]]; then
        write_user_dropin "$UNIT_DIR/mc-notify@$name.service.d" "$user"
        systemctl daemon-reload
    fi

    local svc_user
    svc_user="$(effective_user "$name")"
    if [[ -n $group ]]; then
        usermod -aG "$group" "$svc_user"
        ok "已將 ${svc_user} 加入群組 ${group}（讓它能讀取伺服器的 log）"
    fi
    ok "mc-notify@${name} 將以 ${svc_user} 的身分執行"

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

    local svc_user svc_group
    svc_user="$(effective_user "$name")"
    svc_group="$(id -gn "$svc_user")"
    info "以 ${svc_user}:${svc_group} 的身分檢查 mc-notify@${name}"

    # 用跟正式服務相同的帳號、設定檔與沙箱執行，結果才準確
    systemd-run --quiet --wait --pipe --collect \
        -p User="$svc_user" -p Group="$svc_group" \
        -p EnvironmentFile="$conf" \
        -p StateDirectory="mc-notify/$name" \
        -p NoNewPrivileges=yes -p ProtectSystem=strict -p ProtectHome=read-only -p PrivateTmp=yes \
        /usr/bin/python3 "$PREFIX/mc_notify.py" --check "$@"
}

case "${1:-}" in
    "")               cmd_install ;;
    install)          shift; cmd_install "$@" ;;
    --user)           cmd_install "$@" ;;
    add)              shift; cmd_add "$@" ;;
    check)            shift; cmd_check "$@" ;;
    -h|--help|help)   usage 0 ;;
    *)                usage 1 ;;
esac
