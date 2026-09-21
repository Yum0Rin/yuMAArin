#!/usr/bin/env bash
# 登录后等 Waydroid 会话就绪：
#  1) 保证容器“常亮”不被挂起（否则无界面时冻结→MAA 掉线）
#  2) 再打开 yuMAArin
ADB="$HOME/.local/bin/adb"
ip=""
for i in $(seq 1 60); do
  ip=$(timeout 6 waydroid status 2>/dev/null | awk -F'\t' '/IP address/{print $2}')
  [ -n "$ip" ] && [ "$ip" != "UNKNOWN" ] && break
  sleep 2
done
if [ -n "$ip" ] && [ "$ip" != "UNKNOWN" ]; then
  "$ADB" connect "$ip:5555" >/dev/null 2>&1
  "$ADB" -s "$ip:5555" shell settings put system screen_off_timeout 2147483647 >/dev/null 2>&1
  "$ADB" -s "$ip:5555" shell settings put global stay_on_while_plugged_in 7 >/dev/null 2>&1
  "$ADB" -s "$ip:5555" shell svc power stayon true >/dev/null 2>&1
fi
pgrep -f 'yumaarin.py' >/dev/null 2>&1 || exec "$HOME/.local/bin/yumaarin"
