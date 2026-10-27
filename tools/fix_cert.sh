#!/system/bin/sh
# 系统证书重挂载(Android 14 tmpfs 方案), 模拟器重启后由 install_cert.bat 调用
mount -t tmpfs tmpfs /apex/com.android.conscrypt/cacerts 2>/dev/null
cp /data/local/tmp/cacerts-backup/* /apex/com.android.conscrypt/cacerts/
for f in /data/local/tmp/cacerts-extra/*.0; do
  [ -f "$f" ] && cp "$f" /apex/com.android.conscrypt/cacerts/
done
chown root:root /apex/com.android.conscrypt/cacerts/*
chmod 644 /apex/com.android.conscrypt/cacerts/*
chcon u:object_r:system_file:s0 /apex/com.android.conscrypt/cacerts/* 2>/dev/null
echo "OK, certs: $(ls /apex/com.android.conscrypt/cacerts/ | wc -l)"
