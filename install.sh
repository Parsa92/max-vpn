#!/bin/bash
set -e

echo "=========================================="
echo "   MAX VPN - Telegram VPN Reselling Bot"
echo "=========================================="
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Please run as root: sudo bash install.sh${NC}"
    exit 1
fi

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo -e "${YELLOW}Docker not found. Installing Docker...${NC}"
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
    echo -e "${GREEN}Docker installed successfully${NC}"
fi

# Check if Docker Compose is installed
if ! docker compose version &> /dev/null; then
    echo -e "${YELLOW}Docker Compose not found. Installing...${NC}"
    apt-get update && apt-get install -y docker-compose-plugin
    echo -e "${GREEN}Docker Compose installed successfully${NC}"
fi

# Check if config.json exists
if [ ! -f "config.json" ]; then
    echo ""
    echo -e "${YELLOW}config.json not found. Let's create it...${NC}"
    echo ""
    
    # Copy example
    cp config.example.json config.json
    
    echo -e "${GREEN}Created config.json from template${NC}"
    echo ""
    echo -e "${YELLOW}Please edit config.json with your details:${NC}"
    echo "  nano config.json"
    echo ""
    echo "Required fields:"
    echo "  - telegram.bot_token    : Get from @BotFather on Telegram"
    echo "  - telegram.api_id       : Get from my.telegram.org"
    echo "  - telegram.api_hash     : Get from my.telegram.org"
    echo "  - telegram.admin_id     : Your Telegram user ID"
    echo "  - payment.bank_card_number : Your bank card for payments"
    echo "  - gemini.api_key        : Get from aistudio.google.com"
    echo "  - server.host           : Your server IP or domain"
    echo ""
    
    read -p "Press Enter after editing config.json..."
fi

# Validate config.json
echo "Validating config.json..."
python3 -c "
import json, sys
with open('config.json') as f:
    cfg = json.load(f)
required = ['telegram', 'payment', 'database', 'gemini', 'server']
for key in required:
    if key not in cfg:
        print(f'Missing section: {key}')
        sys.exit(1)
tg = cfg['telegram']
for field in ['bot_token', 'api_id', 'api_hash', 'admin_id']:
    if not tg.get(field) or tg[field].startswith('YOUR_'):
        print(f'Please fill in telegram.{field}')
        sys.exit(1)
if not cfg['server'].get('host') or cfg['server']['host'].startswith('YOUR_'):
    print('Please fill in server.host')
    sys.exit(1)
print('Config validation passed!')
" || { echo -e "${RED}Config validation failed. Please fix config.json${NC}"; exit 1; }

# Generate Pyrogram session string if empty
if [ -z "$(python3 -c "import json; print(json.load(open('config.json'))['telegram'].get('pyrogram_session_string', ''))")" ]; then
    echo ""
    echo -e "${YELLOW}Pyrogram session string is empty. Generating...${NC}"
    echo "You will be asked for your phone number and verification code."
    echo ""
    
    # Install pyrogram if not present
    pip3 install --break-system-packages -q pyrogram tgcrypto 2>/dev/null || true
    
    python3 -c "
import json, asyncio
from pyrogram import Client

with open('config.json') as f:
    cfg = json.load(f)

api_id = int(cfg['telegram']['api_id'])
api_hash = cfg['telegram']['api_hash']

async def main():
    app = Client('session_gen', api_id=api_id, api_hash=api_hash)
    await app.start()
    session_string = await app.export_session_string()
    await app.stop()
    
    with open('config.json', 'r') as f:
        data = json.load(f)
    data['telegram']['pyrogram_session_string'] = session_string
    with open('config.json', 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print('Session string saved to config.json!')

asyncio.run(main())
"
    echo -e "${GREEN}Pyrogram session generated!${NC}"
fi

# Build and start services
echo ""
echo -e "${YELLOW}Building Docker images...${NC}"
DOCKER_BUILDKIT=0 docker build --network=host -t max-vpn-api -f Dockerfile.api . 2>&1 | tail -1
DOCKER_BUILDKIT=0 docker build --network=host -t max-vpn-bot -f Dockerfile.bot . 2>&1 | tail -1
DOCKER_BUILDKIT=0 docker build --network=host -t max-vpn-worker -f Dockerfile.worker . 2>&1 | tail -1

echo ""
echo -e "${YELLOW}Starting services...${NC}"
docker compose up -d

echo ""
echo -e "${GREEN}==========================================${NC}"
echo -e "${GREEN}   MAX VPN is now running!${NC}"
echo -e "${GREEN}==========================================${NC}"
echo ""
echo "Services:"
echo "  - Sales Bot:    Running as @maxv2raybot on Telegram"
echo "  - API:          http://localhost:8000/health"
echo "  - PostgreSQL:   localhost:5432"
echo "  - Redis:        localhost:6379"
echo ""
echo "Useful commands:"
echo "  docker compose logs -f                 # View all logs"
echo "  docker compose logs -f userbot-worker  # View worker logs"
echo "  docker compose logs -f sales-bot       # View bot logs"
echo "  docker compose restart                 # Restart all services"
echo "  docker compose down                    # Stop all services"
echo ""
echo "Admin panel: Send /admin to your bot on Telegram"
echo ""
