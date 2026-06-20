# MAX VPN Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a complete Telegram VPN Reselling platform with automated server provisioning via Pyrogram userbot, manual payment approval, and HTTPS subscription delivery.

**Architecture:** Aiogram sales bot handles user interactions and payments. Pyrogram userbot automates purchasing from source bot. FastAPI serves rebranded subscription links. Nginx handles SSL termination with self-signed or Let's Encrypt certificates.

**Tech Stack:** Python 3.11+, aiogram 3.x, pyrogram 2.x, PostgreSQL (asyncpg), Redis + arq, FastAPI, Nginx, Docker Compose

---

## File Structure

```
max-vpn/
├── docker-compose.yml
├── nginx/
│   ├── default.conf
│   └── ssl_setup.sh
├── database.py
├── models.py
├── config.py
├── sales_bot/
│   ├── __init__.py
│   ├── main.py
│   └── handlers.py
├── userbot/
│   ├── __init__.py
│   ├── worker.py
│   └── ai_fallback.py
├── api/
│   ├── __init__.py
│   └── main.py
└── requirements.txt
```

---

### Task 1: Docker Compose Configuration

**Covers:** Infrastructure setup, container orchestration

**Files:**
- Create: `docker-compose.yml`

- [ ] **Step 1: Create docker-compose.yml**

```yaml
version: '3.8'

services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: ${DB_USER:-maxvpn}
      POSTGRES_PASSWORD: ${DB_PASS:-maxvpn_pass}
      POSTGRES_DB: ${DB_NAME:-maxvpn_db}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER:-maxvpn}"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    volumes:
      - redis_data:/data
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/default.conf:/etc/nginx/conf.d/default.conf
      - ./nginx/ssl_setup.sh:/docker-entrypoint.d/ssl_setup.sh
      - certbot_conf:/etc/letsencrypt
      - certbot_www:/var/www/certbot
    depends_on:
      - api
    restart: unless-stopped

  api:
    build:
      context: .
      dockerfile: Dockerfile.api
    command: uvicorn api.main:app --host 0.0.0.0 --port 8000
    env_file: .env
    volumes:
      - ./api:/app/api
    expose:
      - "8000"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped

  sales-bot:
    build:
      context: .
      dockerfile: Dockerfile.bot
    command: python -m sales_bot.main
    env_file: .env
    volumes:
      - ./sales_bot:/app/sales_bot
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped

  userbot-worker:
    build:
      context: .
      dockerfile: Dockerfile.worker
    command: arq userbot.worker.WorkerSettings
    env_file: .env
    volumes:
      - ./userbot:/app/userbot
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped

  certbot:
    image: certbot/certbot
    volumes:
      - certbot_conf:/etc/letsencrypt
      - certbot_www:/var/www/certbot
    entrypoint: "/bin/sh -c 'trap exit TERM; while :; do certbot renew; sleep 12h & wait $${!}; done;'"
    profiles:
      - production

volumes:
  postgres_data:
  redis_data:
  certbot_conf:
  certbot_www:
```

- [ ] **Step 2: Create Dockerfile.api**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 3: Create Dockerfile.bot**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "-m", "sales_bot.main"]
```

- [ ] **Step 4: Create Dockerfile.worker**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["arq", "userbot.worker.WorkerSettings"]
```

---

### Task 2: Nginx Configuration

**Covers:** SSL termination, reverse proxy, IP vs domain handling

**Files:**
- Create: `nginx/default.conf`
- Create: `nginx/ssl_setup.sh`

- [ ] **Step 1: Create nginx/default.conf**

```nginx
server {
    listen 80;
    server_name _;
    
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }
    
    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl;
    server_name _;

    ssl_certificate /etc/nginx/ssl/cert.pem;
    ssl_certificate_key /etc/nginx/ssl/key.pem;
    
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    location / {
        proxy_pass http://api:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

- [ ] **Step 2: Create nginx/ssl_setup.sh**

```bash
#!/bin/sh

SSL_DIR="/etc/nginx/ssl"
CERT_FILE="$SSL_DIR/cert.pem"
KEY_FILE="$SSL_DIR/key.pem"

mkdir -p "$SSL_DIR"

USE_VALID_SSL="${USE_VALID_SSL:-False}"
SERVER_HOST="${SERVER_HOST:-localhost}"

if [ "$USE_VALID_SSL" = "True" ]; then
    echo "Setting up Let's Encrypt SSL for domain: $SERVER_HOST"
    
    certbot certonly --webroot -w /var/www/certbot \
        -d "$SERVER_HOST" \
        --email admin@"$SERVER_HOST" \
        --agree-tos \
        --no-eff-email \
        --force-renewal || true
    
    ln -sf /etc/letsencrypt/live/"$SERVER_HOST"/fullchain.pem "$CERT_FILE"
    ln -sf /etc/letsencrypt/live/"$SERVER_HOST"/privkey.pem "$KEY_FILE"
else
    echo "Generating self-signed certificate for IP/host: $SERVER_HOST"
    
    if [ ! -f "$CERT_FILE" ]; then
        openssl req -x509 -nodes -days 365 \
            -newkey rsa:2048 \
            -keyout "$KEY_FILE" \
            -out "$CERT_FILE" \
            -subj "/CN=$SERVER_HOST"
        
        echo "Self-signed certificate generated successfully"
    else
        echo "Certificate already exists, skipping generation"
    fi
fi

nginx -g 'daemon off;'
```

---

### Task 3: Userbot Worker (Pyrogram + Queue)

**Covers:** Source bot automation, plan purchase, link extraction

**Files:**
- Create: `userbot/__init__.py`
- Create: `userbot/worker.py`

- [ ] **Step 1: Create userbot/__init__.py**

```python
# Userbot package
```

- [ ] **Step 2: Create userbot/worker.py**

```python
import asyncio
import random
import re
import logging
from datetime import datetime
from sqlalchemy import select
from pyrogram import Client
from pyrogram.enums import ChatAction
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import config
from database import async_session, engine
from models import Order, User
from userbot.ai_fallback import fallback_ai_agent

logger = logging.getLogger("userbot.worker")

pyro_app = Client(
    "max_vpn_userbot",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    session_string=config.PYROGRAM_SESSION_STRING,
)


async def generate_username() -> str:
    timestamp = int(datetime.utcnow().timestamp())
    random_suffix = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=6))
    return f"user{timestamp}{random_suffix}"


async def wait_for_message(client: Client, chat_id: int, timeout: int = 30):
    try:
        messages = []
        async for message in client.get_chat_history(chat_id, limit=1):
            messages.append(message)
        return messages[0] if messages else None
    except Exception as e:
        logger.error(f"Error waiting for message: {e}")
        return None


async def click_reply_button(client: Client, chat_id: int, button_text: str, timeout: int = 30):
    try:
        await asyncio.sleep(random.uniform(1.5, 3.0))
        
        messages = []
        async for message in client.get_chat_history(chat_id, limit=5):
            messages.append(message)
        
        for message in messages:
            if message.reply_markup and hasattr(message.reply_markup, 'keyboard'):
                for row in message.reply_markup.keyboard:
                    for button in row:
                        if button_text in button.text:
                            await client.send_message(chat_id, button.text)
                            logger.info(f"Clicked reply button: {button.text}")
                            return True
        
        logger.warning(f"Reply button '{button_text}' not found")
        return False
    except Exception as e:
        logger.error(f"Error clicking reply button: {e}")
        return False


async def click_inline_button(client: Client, chat_id: int, button_text: str, timeout: int = 30):
    try:
        await asyncio.sleep(random.uniform(1.5, 3.0))
        
        messages = []
        async for message in client.get_chat_history(chat_id, limit=5):
            messages.append(message)
        
        for message in messages:
            if message.reply_markup and isinstance(message.reply_markup, InlineKeyboardMarkup):
                for row in message.reply_markup.inline_keyboard:
                    for button in row:
                        if button_text in button.text:
                            await client.answer_callback_query(button.callback_data)
                            logger.info(f"Clicked inline button: {button.text}")
                            return True
        
        logger.warning(f"Inline button '{button_text}' not found")
        return False
    except Exception as e:
        logger.error(f"Error clicking inline button: {e}")
        return False


async def extract_subscription_link(client: Client, chat_id: int) -> str | None:
    try:
        await asyncio.sleep(random.uniform(2.0, 4.0))
        
        messages = []
        async for message in client.get_chat_history(chat_id, limit=5):
            messages.append(message)
        
        for message in messages:
            if message.text:
                url_match = re.search(r'https?://[^\s]+', message.text)
                if url_match:
                    return url_match.group(0)
        
        return None
    except Exception as e:
        logger.error(f"Error extracting subscription link: {e}")
        return None


async def purchase_from_source_bot(plan_id: int, username: str) -> str | None:
    try:
        async with pyro_app:
            source_bot = config.SOURCE_BOT
            
            logger.info(f"Starting purchase flow for plan {plan_id}, username: {username}")
            
            await pyro_app.send_message(source_bot, "/start")
            await asyncio.sleep(random.uniform(2.0, 3.0))
            
            clicked = await click_reply_button(pyro_app, source_bot, "خرید سرور نیم بها")
            if not clicked:
                raise TimeoutError("Failed to find buy button")
            
            await asyncio.sleep(random.uniform(1.5, 2.5))
            
            clicked = await click_reply_button(pyro_app, source_bot, "خرید سرور نیم بها با کیف پول")
            if not clicked:
                raise TimeoutError("Failed to find wallet buy button")
            
            await asyncio.sleep(random.uniform(2.0, 3.0))
            
            messages = []
            async for message in pyro_app.get_chat_history(source_bot, limit=5):
                messages.append(message)
            
            name_prompt_found = False
            for message in messages:
                if message.text and "لطفا اسم انتخابی اشتراک خود را وارد کنید" in message.text:
                    await pyro_app.send_message(source_bot, username, reply_to_message_id=message.id)
                    name_prompt_found = True
                    break
            
            if not name_prompt_found:
                raise TimeoutError("Name prompt not found")
            
            await asyncio.sleep(random.uniform(2.0, 3.0))
            
            plan = config.PLAN_MAP.get(plan_id)
            if not plan:
                raise ValueError(f"Invalid plan ID: {plan_id}")
            
            clicked = await click_inline_button(pyro_app, source_bot, plan["name"])
            if not clicked:
                raise TimeoutError(f"Failed to select plan {plan['name']}")
            
            await asyncio.sleep(random.uniform(2.0, 3.0))
            
            await pyro_app.send_message(source_bot, "/start")
            await asyncio.sleep(random.uniform(1.5, 2.5))
            
            clicked = await click_reply_button(pyro_app, source_bot, "دریافت لینک آپدیت خودکار سرور نیم بها")
            if not clicked:
                raise TimeoutError("Failed to find link button")
            
            await asyncio.sleep(random.uniform(2.0, 3.0))
            
            clicked = await click_inline_button(pyro_app, source_bot, username)
            if not clicked:
                raise TimeoutError(f"Failed to find username button: {username}")
            
            sub_link = await extract_subscription_link(pyro_app, source_bot)
            if not sub_link:
                raise TimeoutError("Failed to extract subscription link")
            
            logger.info(f"Successfully purchased plan {plan_id}, link: {sub_link}")
            return sub_link
            
    except Exception as e:
        logger.error(f"Purchase failed: {e}")
        return None


async def process_order(order_id: int, plan_id: int):
    try:
        async with async_session() as session:
            result = await session.execute(select(Order).where(Order.id == order_id))
            order = result.scalar_one_or_none()
            
            if not order:
                logger.error(f"Order {order_id} not found")
                return
            
            order.status = "PROCESSING"
            await session.commit()
            
            username = await generate_username()
            
            sub_link = await purchase_from_source_bot(plan_id, username)
            
            if not sub_link:
                logger.warning(f"Pyrogram purchase failed for order {order_id}, trying AI fallback")
                
                async with async_session() as session:
                    result = await session.execute(select(Order).where(Order.id == order_id))
                    order = result.scalar_one_or_none()
                    if order:
                        order.status = "AI_FALLBACK"
                        await session.commit()
                
                chat_history = []
                sub_link = await fallback_ai_agent(chat_history, plan_id, username)
            
            if sub_link:
                from api.main import rebrand_config
                rebranded_link = await rebrand_config(sub_link)
                
                async with async_session() as session:
                    result = await session.execute(select(Order).where(Order.id == order_id))
                    order = result.scalar_one_or_none()
                    
                    if order:
                        order.raw_sub_link = sub_link
                        order.sub_link = rebranded_link
                        order.status = "COMPLETED"
                        order.completed_at = datetime.utcnow()
                        await session.commit()
                
                user_result = await session.execute(select(User).where(User.id == order.user_id))
                user = user_result.scalar_one_or_none()
                
                if user:
                    try:
                        bot_client = pyro_app
                        await bot_client.send_message(
                            user.telegram_id,
                            f"✅ سرور شما آماده است!\n\n"
                            f"📦 پلن: {order.plan_name}\n"
                            f"🔗 لینک اشتراک: {rebranded_link}\n\n"
                            f"⚠️ این لینک را در نرم‌افزار v2rayNG یا similar وارد کنید."
                        )
                    except Exception as e:
                        logger.error(f"Failed to notify user: {e}")
            else:
                async with async_session() as session:
                    result = await session.execute(select(Order).where(Order.id == order_id))
                    order = result.scalar_one_or_none()
                    if order:
                        order.status = "FAILED"
                        await session.commit()
                
                logger.error(f"Order {order_id} failed - no subscription link obtained")
                
    except Exception as e:
        logger.error(f"Error processing order {order_id}: {e}")
        
        try:
            async with async_session() as session:
                result = await session.execute(select(Order).where(Order.id == order_id))
                order = result.scalar_one_or_none()
                if order:
                    order.status = "FAILED"
                    await session.commit()
        except Exception as inner_e:
            logger.error(f"Failed to mark order as failed: {inner_e}")


class WorkerSettings:
    functions = [process_order]
    redis_settings = config.REDIS_URL
    max_jobs = 5
    job_timeout = 300
    
    async def on_startup(self):
        logger.info("Worker starting up...")
        
    async def on_shutdown(self):
        logger.info("Worker shutting down...")
```

---

### Task 4: Gemini AI Fallback

**Covers:** Fallback automation when Pyrogram fails

**Files:**
- Create: `userbot/ai_fallback.py`

- [ ] **Step 1: Create userbot/ai_fallback.py**

```python
import json
import logging
import os
from datetime import datetime
import google.generativeai as genai
import config

logger = logging.getLogger("userbot.ai_fallback")

genai.configure(api_key=config.GEMINI_API_KEY)
model = genai.GenerativeModel(config.GEMINI_MODEL)


async def fallback_ai_agent(chat_history: list, plan_id: int, username: str) -> str | None:
    try:
        plan = config.PLAN_MAP.get(plan_id)
        if not plan:
            logger.error(f"Invalid plan ID: {plan_id}")
            return None
        
        system_prompt = (
            "You are an agent navigating a Telegram bot to buy a VPN. "
            f"The target plan is {plan['name']} ({plan['price']} Toman). "
            "The username to use is: {username}\n\n"
            "Look at the recent messages and keyboards. "
            "Reply ONLY with a JSON object in this format:\n"
            "{'action': 'send_text' | 'click_inline' | 'click_reply', 'value': 'text_to_send_or_button_text'}\n\n"
            "Rules:\n"
            "- action 'send_text': Send the value as a text message\n"
            "- action 'click_inline': Click an inline keyboard button containing the value\n"
            "- action 'click_reply': Click a reply keyboard button containing the value\n"
            "- Only respond with the JSON object, no other text\n"
            "- If you see a URL starting with http/https, return {'action': 'extract_url', 'value': 'the_url'}"
        )
        
        history_text = "\n".join([
            f"[{msg.get('role', 'unknown')}] {msg.get('text', '')}" 
            for msg in chat_history[-5:]
        ]) if chat_history else "No history available"
        
        user_prompt = (
            f"Current chat history with the source bot:\n{history_text}\n\n"
            f"I need to buy a VPN server with plan: {plan['name']}\n"
            f"Username to use: {username}\n\n"
            "What action should I take next?"
        )
        
        response = model.generate_content(
            [system_prompt, user_prompt],
            generation_config=genai.types.GenerationConfig(
                temperature=0.3,
                max_output_tokens=200,
            )
        )
        
        response_text = response.text.strip()
        
        if response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
        
        try:
            action_data = json.loads(response_text)
        except json.JSONDecodeError:
            json_match = response_text.split("{")
            if len(json_match) > 1:
                json_str = "{" + json_match[1].split("}")[0] + "}"
                action_data = json.loads(json_str)
            else:
                logger.error(f"Failed to parse AI response: {response_text}")
                return None
        
        action = action_data.get("action")
        value = action_data.get("value")
        
        logger.info(f"AI action: {action}, value: {value}")
        
        if action == "extract_url":
            return value
        
        return None
        
    except Exception as e:
        logger.error(f"AI fallback error: {e}")
        return None
```

---

### Task 5: FastAPI Delivery Server

**Covers:** Rebranding, HTTPS subscription delivery

**Files:**
- Create: `api/__init__.py`
- Create: `api/main.py`

- [ ] **Step 1: Create api/__init__.py**

```python
# API package
```

- [ ] **Step 2: Create api/main.py**

```python
import base64
import logging
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
import httpx
import config
from database import async_session, init_db
from models import Order

logger = logging.getLogger("api.main")

app = FastAPI(title="MAX VPN API", version="1.0.0")


@app.on_event("startup")
async def startup():
    await init_db()
    logger.info("API server started")


async def rebrand_config(raw_url: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(raw_url)
            response.raise_for_status()
            
            base64_content = response.text.strip()
            
            decoded_bytes = base64.b64decode(base64_content)
            decoded_string = decoded_bytes.decode('utf-8')
            
            rebranded_string = decoded_string.replace("MMDLeecher", "max_v2connect")
            rebranded_string = rebranded_string.replace("mmdleecher", "max_v2connect")
            rebranded_string = rebranded_string.replace("MMDleecher", "max_v2connect")
            rebranded_string = rebranded_string.replace("mmdLeecher", "max_v2connect")
            
            rebranded_bytes = rebranded_string.encode('utf-8')
            rebranded_base64 = base64.b64encode(rebranded_bytes).decode('utf-8')
            
            logger.info(f"Successfully rebranded config from {raw_url}")
            return rebranded_base64
            
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error fetching config: {e}")
        raise
    except base64.binascii.Error as e:
        logger.error(f"Base64 decode error: {e}")
        raise
    except Exception as e:
        logger.error(f"Rebranding error: {e}")
        raise


@app.get("/sub/{order_id}", response_class=PlainTextResponse)
async def get_subscription(order_id: int):
    try:
        async with async_session() as session:
            result = await session.execute(
                select(Order).where(Order.id == order_id)
            )
            order = result.scalar_one_or_none()
            
            if not order:
                raise HTTPException(status_code=404, detail="Order not found")
            
            if order.status != "COMPLETED":
                raise HTTPException(status_code=400, detail="Order not completed")
            
            if not order.sub_link:
                raise HTTPException(status_code=404, detail="Subscription link not available")
            
            return PlainTextResponse(content=order.sub_link)
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching subscription: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
```

---

### Task 6: Create __init__.py Files

**Covers:** Package initialization

**Files:**
- Create: `sales_bot/__init__.py`

- [ ] **Step 1: Create sales_bot/__init__.py**

```python
# Sales bot package
```

---

## Execution Handoff

After implementing all tasks, verify the deployment:

1. Run `docker-compose build` to build all images
2. Run `docker-compose up -d` to start all services
3. Check logs with `docker-compose logs -f`
4. Test the bot by sending `/start` to the Telegram bot

**Testing Commands:**
```bash
# Build and start
docker-compose build
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f sales-bot
docker-compose logs -f userbot-worker
docker-compose logs -f api

# Test API
curl http://localhost/health
curl -k https://localhost/sub/1
```
