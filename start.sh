#!/bin/bash
cd /root/max-vpn

echo "Starting MAX VPN services..."

# Kill existing processes
pkill -f "uvicorn api.main" 2>/dev/null
pkill -f "sales_bot.main" 2>/dev/null
pkill -f "arq userbot" 2>/dev/null
sleep 1

# Start API
nohup python3 -m uvicorn api.main:app --host 0.0.0.0 --port 8000 > /tmp/api.log 2>&1 &
echo "API started (PID: $!)"

# Start Sales Bot
nohup python3 -m sales_bot.main > /tmp/bot.log 2>&1 &
echo "Sales Bot started (PID: $!)"

# Start Worker
nohup python3 -m arq userbot.worker.ArqSettings > /tmp/worker.log 2>&1 &
echo "Worker started (PID: $!)"

sleep 3
echo ""
echo "=== Service Status ==="
echo "API:     $(tail -1 /tmp/api.log)"
echo "Bot:     $(tail -1 /tmp/bot.log)"
echo "Worker:  $(tail -1 /tmp/worker.log)"
echo ""
echo "Logs: tail -f /tmp/{api,bot,worker}.log"
