import base64
import re
import logging
import httpx
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import async_session, init_db
from models import Order

logger = logging.getLogger("api.main")
security = HTTPBearer(auto_error=False)

SUB_API_TOKEN = os.environ.get("SUB_API_TOKEN")


async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if SUB_API_TOKEN:
        if not credentials or credentials.credentials != SUB_API_TOKEN:
            raise HTTPException(status_code=401, detail="Unauthorized")
    return True


@asynccontextmanager
async def lifespan(app):
    await init_db()
    logger.info("Database initialized")
    yield

app = FastAPI(title="MAX VPN Delivery API", lifespan=lifespan)


async def rebrand_config(raw_url: str) -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(raw_url)
        response.raise_for_status()

    payload = response.text.strip()
    try:
        decoded_bytes = base64.b64decode(payload)
        decoded_str = decoded_bytes.decode("utf-8")
    except Exception as e:
        logger.error(f"Failed to decode base64 payload: {e}")
        raise

    modified_str = re.sub(r"MMDLeecher", "max_v2connect", decoded_str, flags=re.IGNORECASE)

    rebranded_b64 = base64.b64encode(modified_str.encode("utf-8")).decode("utf-8")
    return rebranded_b64


@app.get("/sub/{order_id}", response_class=PlainTextResponse)
async def get_subscription(order_id: int, _auth: bool = Depends(verify_token)):
    async with async_session() as session:
        result = await session.execute(
            select(Order).where(Order.id == order_id, Order.status == "COMPLETED")
        )
        order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(status_code=404, detail="Subscription not found or not active")

    if not order.raw_sub_link:
        raise HTTPException(status_code=404, detail="Subscription data not available")

    return PlainTextResponse(content=order.raw_sub_link, media_type="text/plain")


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
