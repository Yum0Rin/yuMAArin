#!/usr/bin/env bash
# 重启 yuMAArin 前备份当前运行配置（state/queue/ui.json/profile）。
# 用法: backup-config.sh [目标目录]   缺省写到项目 历史版本/运行配置快照-<时间>/
set -euo pipefail
PROJ="$HOME/项目留痕/桌面应用/yumaarin"
DEST="${1:-$PROJ/历史版本/运行配置快照-$(date +%Y%m%d-%H%M)}"
mkdir -p "$DEST"
for f in \
  "$HOME/.config/yumaarin/state.json" \
  "$HOME/.config/yumaarin/queue.json" \
  "$HOME/.config/maa/tasks/ui.json" \
  "$HOME/.config/maa/profiles/default.json" ; do
  [ -f "$f" ] && cp "$f" "$DEST/$(echo "${f#$HOME/.config/}" | tr '/' '-')"
done
echo "已备份到: $DEST"
ls -la "$DEST"
