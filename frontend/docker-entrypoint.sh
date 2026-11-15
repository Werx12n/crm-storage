#!/bin/sh
# Генерує самопідписаний сертифікат для HTTPS, якщо його немає (для демо/локальної мережі).
set -e
if [ ! -f /etc/nginx/certs/wms.crt ]; then
  mkdir -p /etc/nginx/certs
  openssl req -x509 -nodes -newkey rsa:2048 -days 825 -subj "/CN=wms.local" \
    -addext "subjectAltName=DNS:localhost,DNS:wms.local,IP:127.0.0.1" \
    -keyout /etc/nginx/certs/wms.key -out /etc/nginx/certs/wms.crt
fi
exec nginx -g "daemon off;"
