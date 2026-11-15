#!/bin/sh
# Генерує самопідписаний сертифікат для HTTPS, якщо його немає (для демо/локальної мережі).
set -e
if [ ! -f /etc/nginx/certs/wms.crt ]; then
  mkdir -p /etc/nginx/certs
  openssl req -x509 -nodes -newkey rsa:2048 -days 825 -subj "/CN=wms.local" \
    -addext "subjectAltName=DNS:localhost,DNS:wms.local,IP:127.0.0.1" \
    -keyout /etc/nginx/certs/wms.key -out /etc/nginx/certs/wms.crt
fi
# Порт HTTPS на хості для редиректу HTTP -> HTTPS
sed -i "s/__HTTPS_PORT__/${WMS_HTTPS_PORT:-8443}/" /etc/nginx/conf.d/default.conf
exec nginx -g "daemon off;"
