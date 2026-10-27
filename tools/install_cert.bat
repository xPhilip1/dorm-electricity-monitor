@echo off
chcp 65001 >nul
echo === 雷电模拟器 Reqable 证书一键恢复 ===
echo (模拟器每次重启后运行一次本脚本)
echo.
set ADB=E:\leidian\LDPlayer14\adb.exe
"%ADB%" connect 127.0.0.1:5555
"%ADB%" shell "su -c 'sh /data/local/tmp/fix_cert.sh'"
echo.
echo 完成。如果上面显示 OK, certs: 135 即成功。
pause
