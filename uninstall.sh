#!/usr/bin/env bash
# mc-notify 移除工具
#
#   sudo ./uninstall.sh            移除程式與 systemd 服務，保留設定檔與看板紀錄
#   sudo ./uninstall.sh --purge    連同設定檔、看板紀錄與服務帳號一起刪除
#   加上 -y 可略過確認
set -euo pipefail

PREFIX=/opt/mc-notify
CONF_DIR=/etc/mc-notify
STATE_DIR=/var/lib/mc-notify
UNIT_DIR=/etc/systemd/system
SVC_USER=mc-notify

purge=0 yes=0
for arg in "$@"; do
    case $arg in
        --purge) purge=1 ;;
        -y|--yes) yes=1 ;;
        -h|--help) sed -n '2,7p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "未知的參數：$arg" >&2; exit 1 ;;
    esac
done

[[ $EUID -eq 0 ]] || { echo "請用 sudo 執行" >&2; exit 1; }

echo "將會移除："
echo "  - 所有 mc-notify@ 實例（停止並取消開機啟動）"
echo "  - $UNIT_DIR/mc-notify@.service"
echo "  - $PREFIX"
if ((purge)); then
    echo "  - $CONF_DIR（設定檔，包含 webhook 與 RCON 密碼）"
    echo "  - $STATE_DIR（狀態看板紀錄）"
    echo "  - 帳號 $SVC_USER"
fi
if ((!yes)); then
    read -r -p "確定要繼續嗎？[y/N] " answer
    [[ $answer =~ ^[Yy]$ ]] || { echo "已取消"; exit 0; }
fi

# 找出所有實例：已載入的，加上設定為開機啟動的
mapfile -t units < <(
    {
        systemctl list-units --all --type=service --plain --no-legend 'mc-notify@*.service' 2>/dev/null \
            | awk '{print $1}'
        find "$UNIT_DIR" -path '*.wants/mc-notify@*.service' -printf '%f\n' 2>/dev/null
    } | grep -E '^mc-notify@.+\.service$' | sort -u
)
if ((${#units[@]})); then
    systemctl disable --now "${units[@]}" || true
    printf '已停用 %s\n' "${units[@]}"
fi

rm -f "$UNIT_DIR/mc-notify@.service"
rm -rf "$UNIT_DIR/mc-notify@.service.d"
systemctl daemon-reload
systemctl reset-failed 'mc-notify@*' 2>/dev/null || true
rm -rf "$PREFIX"
echo "已移除程式與服務"

if ((purge)); then
    rm -rf "$CONF_DIR" "$STATE_DIR"
    if id -u "$SVC_USER" >/dev/null 2>&1; then
        userdel "$SVC_USER"
    fi
    echo "已刪除設定檔、看板紀錄與帳號 $SVC_USER"
else
    echo "設定檔保留在 $CONF_DIR（重新安裝後可直接使用；完全刪除請加 --purge）"
fi
echo "提醒：Discord 上的狀態看板訊息不會自動刪除，需要的話請手動刪除"
