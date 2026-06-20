#!/bin/sh

SSL_DIR="/etc/nginx/ssl"
CERT_FILE="$SSL_DIR/cert.pem"
KEY_FILE="$SSL_DIR/key.pem"

mkdir -p "$SSL_DIR"

# Read from config.json
CONFIG_FILE="/app/config.json"
if [ -f "$CONFIG_FILE" ]; then
    SERVER_HOST=$(cat "$CONFIG_FILE" | grep -o '"host"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"host"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/')
    USE_VALID_SSL=$(cat "$CONFIG_FILE" | grep -o '"use_valid_ssl"[[:space:]]*:[[:space:]]*[a-z]*' | head -1 | sed 's/.*"use_valid_ssl"[[:space:]]*:[[:space:]]*\(.*\)/\1/')
fi

SERVER_HOST=${SERVER_HOST:-localhost}
USE_VALID_SSL=${USE_VALID_SSL:-false}

if [ "$USE_VALID_SSL" = "true" ] || [ "$USE_VALID_SSL" = "True" ]; then
    echo "Setting up Let's Encrypt SSL for domain: $SERVER_HOST"

    certbot certonly --webroot \
        --webroot-path=/var/www/certbot \
        -d "$SERVER_HOST" \
        --email admin@$SERVER_HOST \
        --agree-tos \
        --no-eff-email \
        --non-interactive \
        2>/dev/null || true

    if [ -f "/etc/letsencrypt/live/$SERVER_HOST/fullchain.pem" ]; then
        ln -sf "/etc/letsencrypt/live/$SERVER_HOST/fullchain.pem" "$CERT_FILE"
        ln -sf "/etc/letsencrypt/live/$SERVER_HOST/privkey.pem" "$KEY_FILE"
        echo "Let's Encrypt certificate installed successfully"
    else
        echo "Let's Encrypt failed, falling back to self-signed certificate"
        USE_VALID_SSL="false"
    fi
fi

if [ "$USE_VALID_SSL" != "true" ] && [ "$USE_VALID_SSL" != "True" ]; then
    echo "Generating self-signed SSL certificate for: $SERVER_HOST"

    if [ ! -f "$CERT_FILE" ]; then
        openssl req -x509 -nodes -days 365 \
            -newkey rsa:2048 \
            -keyout "$KEY_FILE" \
            -out "$CERT_FILE" \
            -subj "/C=US/ST=Local/L=Local/O=MAX VPN/CN=$SERVER_HOST" \
            2>/dev/null
        echo "Self-signed certificate generated"
    else
        echo "Self-signed certificate already exists"
    fi
fi

if [ ! -f "$CERT_FILE" ] || [ ! -f "$KEY_FILE" ]; then
    echo "ERROR: SSL certificates not found at $SSL_DIR"
    echo "Generating emergency self-signed certificate"
    openssl req -x509 -nodes -days 30 \
        -newkey rsa:2048 \
        -keyout "$KEY_FILE" \
        -out "$CERT_FILE" \
        -subj "/CN=localhost" \
        2>/dev/null
fi

echo "SSL setup complete"

nginx -g 'daemon off;'
