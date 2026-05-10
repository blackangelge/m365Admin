#!/bin/sh
# Runs automatically via nginx:alpine's /docker-entrypoint.d/ hook before nginx starts.
# Generates a self-signed TLS certificate on first boot and stores it in the certs volume.

CERT_DIR=/etc/nginx/certs
CERT_FILE="$CERT_DIR/cert.pem"
KEY_FILE="$CERT_DIR/key.pem"

if [ -f "$CERT_FILE" ] && [ -f "$KEY_FILE" ]; then
    echo "[cert] Certificate already exists — skipping generation."
    exit 0
fi

echo "[cert] Generating self-signed TLS certificate..."

# Build Subject Alternative Name: prefer IP, fall back to CN as DNS
if [ -n "$CERT_IP" ]; then
    SAN="IP:${CERT_IP}"
else
    SAN="DNS:${CERT_CN:-m365admin}"
fi

openssl req -x509 \
    -newkey rsa:4096 \
    -keyout "$KEY_FILE" \
    -out "$CERT_FILE" \
    -days "${CERT_DAYS:-365}" \
    -nodes \
    -subj "/CN=${CERT_CN:-m365admin}" \
    -addext "subjectAltName=${SAN}" \
    2>&1

echo "[cert] Certificate generated and saved to $CERT_FILE (valid ${CERT_DAYS:-365} days, SAN=${SAN})"
