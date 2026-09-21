#!/usr/bin/env bash
# yuMAArin 安装脚本：把程序装到用户目录，并写好桌面项/自启项。
# 用法：./install.sh          （不需要 root）
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
H="$HOME"

mkdir -p "$H/.local/share/yumaarin" "$H/.local/bin" \
         "$H/.local/share/applications" "$H/.local/share/icons" "$H/.config/autostart"

cp "$HERE/yumaarin.py" "$H/.local/share/yumaarin/yumaarin.py"

cat > "$H/.local/bin/yumaarin" <<EOF
#!/usr/bin/env bash
exec python3 "$H/.local/share/yumaarin/yumaarin.py" "\$@"
EOF
chmod +x "$H/.local/bin/yumaarin"

cp "$HERE/scripts/yumaarin-autostart.sh" "$H/.local/bin/yumaarin-autostart.sh"
chmod +x "$H/.local/bin/yumaarin-autostart.sh"
[ -f "$HERE/scripts/backup-config.sh" ] && cp "$HERE/scripts/backup-config.sh" "$H/.local/bin/yumaarin-backup.sh" || true

cat > "$H/.local/share/applications/yumaarin.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=yuMAArin
Comment=明日方舟日常（maa-cli 前端）
Exec=$H/.local/bin/yumaarin
Icon=$H/.local/share/icons/yumaarin.png
Terminal=false
Categories=Game;
StartupNotify=true
EOF

cat > "$H/.config/autostart/yumaarin.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=yuMAArin
Comment=明日方舟日常（maa-cli 前端，开机自启）
Exec=$H/.local/bin/yumaarin-autostart.sh
Icon=$H/.local/share/icons/yumaarin.png
Terminal=false
X-GNOME-Autostart-enabled=true
EOF

update-desktop-database "$H/.local/share/applications" >/dev/null 2>&1 || true

echo "安装完成：应用菜单搜 yuMAArin，或终端运行 yumaarin"
echo "提示：首次使用请先安装并配置好 maa-cli（maa install / maa update）。"
