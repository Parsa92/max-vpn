import asyncio
import random
import re
import logging
import datetime
import time
from pyrogram import Client
from pyrogram.types import Message, CallbackQuery as PyroCallbackQuery
from pyrogram.errors import FloodWait
from arq.connections import RedisSettings
import config
from database import async_session
from models import Order, User
from sqlalchemy import select

logger = logging.getLogger("userbot.worker")


pyro_client = Client(
    name="maxvpn_userbot",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    session_string=config.PYROGRAM_SESSION_STRING if config.PYROGRAM_SESSION_STRING else None,
)


async def get_client() -> Client:
    if not pyro_client.is_connected:
        await pyro_client.start()
    return pyro_client


async def wait_for_reply(client: Client, chat: str, timeout: int = 60) -> list[Message]:
    start = time.time()
    messages: list[Message] = []
    while time.time() - start < timeout:
        await asyncio.sleep(1.0)
        try:
            async for msg in client.get_chat_history(chat, limit=5):
                if msg.date.timestamp() > start - 2:
                    messages.append(msg)
            if messages:
                return sorted(messages, key=lambda m: m.date)
        except Exception:
            continue
    return messages


async def find_button_text(message: Message, text: str) -> bool:
    if not message.reply_markup:
        return False
    keyboard = message.reply_markup
    if hasattr(keyboard, "keyboard"):
        for row in keyboard.keyboard:
            for button in row:
                if text in button.text:
                    return True
    elif hasattr(keyboard, "inline_keyboard"):
        for row in keyboard.inline_keyboard:
            for button in row:
                if text in button.text:
                    return True
    return False


async def click_reply_keyboard(client: Client, chat: str, text: str, reply_to: int = None):
    await client.send_message(chat, text, reply_to_message_id=reply_to)
    await asyncio.sleep(random.uniform(1.5, 3.0))


async def click_inline_button(message: Message, text_contains: str):
    if not message.reply_markup:
        return None
    keyboard = message.reply_markup
    buttons = []
    if hasattr(keyboard, "inline_keyboard"):
        buttons = [b for row in keyboard.inline_keyboard for b in row]
    elif hasattr(keyboard, "keyboard"):
        buttons = [b for row in keyboard.keyboard for b in row]

    for button in buttons:
        if text_contains in button.text:
            if hasattr(button, "callback_data") and button.callback_data:
                return button.callback_data
            return button.text
    return None


async def press_inline_button(client: Client, chat: str, message: Message, text_contains: str):
    callback_data = await click_inline_button(message, text_contains)
    if not callback_data:
        return False
    try:
        me = await client.get_me()
        await client.invoke(
            PyroCallbackQuery(
                chat_id=chat,
                message_id=message.id,
                data=callback_data.encode() if isinstance(callback_data, str) else callback_data,
                from_user=me,
            )
        )
    except Exception as e:
        logger.debug(f"Callback invoke failed, sending text instead: {e}")
        await client.send_message(chat, callback_data)
    return True


def extract_url(text: str) -> str | None:
    urls = re.findall(r'https?://[^\s<>"]+', text)
    for url in urls:
        if "http" in url:
            return url
    return None


async def purchase_from_source_bot(client: Client, plan: dict) -> str:
    chat = config.SOURCE_BOT

    logger.info("Sending /start to source bot")
    await client.send_message(chat, "/start")
    await asyncio.sleep(random.uniform(1.5, 3.0))

    messages = await wait_for_reply(client, chat, timeout=30)
    logger.info(f"Got {len(messages)} messages after /start")

    if messages:
        latest_msg = messages[-1]
        if await find_button_text(latest_msg, "خرید سرور نیم بها"):
            await click_reply_keyboard(client, chat, "خرید سرور نیم بها")
            await asyncio.sleep(random.uniform(1.5, 3.0))
        else:
            logger.warning("Button 'خرید سرور نیم بها' not found")

    messages = await wait_for_reply(client, chat, timeout=30)
    if messages:
        latest_msg = messages[-1]
        if await find_button_text(latest_msg, "خرید سرور نیم بها با کیف پول"):
            await click_reply_keyboard(client, chat, "خرید سرور نیم بها با کیف پول")
            await asyncio.sleep(random.uniform(1.5, 3.0))
        else:
            logger.warning("Button 'خرید سرور نیم بها با کیف پول' not found")

    messages = await wait_for_reply(client, chat, timeout=30)
    username = f"user{int(time.time())}{random.randint(1000, 9999)}"

    name_prompt = None
    for msg in messages:
        if msg.text and ("لطفا اسم انتخابی" in msg.text or "نام" in msg.text.lower()):
            name_prompt = msg
            break

    if name_prompt:
        await client.send_message(chat, username, reply_to_message_id=name_prompt.id)
    else:
        logger.warning("Name prompt not found, sending username anyway")
        await client.send_message(chat, username)
    await asyncio.sleep(random.uniform(1.5, 3.0))

    messages = await wait_for_reply(client, chat, timeout=30)
    if messages:
        latest_msg = messages[-1]
        await press_inline_button(client, chat, latest_msg, str(plan["data_gb"]))
    else:
        logger.warning("No messages after sending username, plan button might be missing")

    await asyncio.sleep(random.uniform(1.5, 3.0))

    logger.info("Sending /start again to get link")
    await client.send_message(chat, "/start")
    await asyncio.sleep(random.uniform(1.5, 3.0))

    messages = await wait_for_reply(client, chat, timeout=30)
    if messages:
        latest_msg = messages[-1]
        if await find_button_text(latest_msg, "دریافت لینک آپدیت خودکار سرور نیم بها"):
            await click_reply_keyboard(client, chat, "دریافت لینک آپدیت خودکار سرور نیم بها")
            await asyncio.sleep(random.uniform(1.5, 3.0))

    messages = await wait_for_reply(client, chat, timeout=30)
    if messages:
        latest_msg = messages[-1]
        await press_inline_button(client, chat, latest_msg, username)

    await asyncio.sleep(random.uniform(2.0, 4.0))

    messages = await wait_for_reply(client, chat, timeout=30)
    for msg in messages:
        if msg.text:
            found_url = extract_url(msg.text)
            if found_url:
                return found_url

    raise ValueError("Failed to extract subscription URL from source bot")


async def process_order(ctx: dict, order_id: int, plan_id: int):
    logger.info(f"Processing order #{order_id} with plan {plan_id}")
    plan = config.PLAN_MAP.get(plan_id)
    if not plan:
        logger.error(f"Plan {plan_id} not found")
        return

    try:
        client = await get_client()

        async with async_session() as session:
            result = await session.execute(select(Order).where(Order.id == order_id))
            order = result.scalar_one_or_none()
            if not order:
                logger.error(f"Order #{order_id} not found")
                return
            order.status = "PROCESSING"
            await session.commit()

        raw_url = await purchase_from_source_bot(client, plan)
        logger.info(f"Order #{order_id}: Got raw URL")

        from api.main import rebrand_config
        rebranded = await rebrand_config(raw_url)
        delivery_link = f"https://{config.SERVER_HOST}/sub/{order_id}"

        async with async_session() as session:
            result = await session.execute(select(Order).where(Order.id == order_id))
            db_order = result.scalar_one_or_none()
            if db_order:
                db_order.status = "COMPLETED"
                db_order.sub_link = delivery_link
                db_order.raw_sub_link = rebranded
                db_order.completed_at = datetime.datetime.utcnow()
                await session.commit()

                user_result = await session.execute(select(User).where(User.id == db_order.user_id))
                db_user = user_result.scalar_one_or_none()
                if db_user:
                    try:
                        await client.send_message(
                            db_user.telegram_id,
                            f"✅ سرور شما آماده است!\n\n"
                            f"📦 پلن: {plan['name']}\n"
                            f"🔗 لینک اشتراک:\n<code>{delivery_link}</code>\n\n"
                            f"💡 این لینک را در اپلیکیشن VPN خود وارد کنید.",
                        )
                    except Exception as e:
                        logger.error(f"Failed to send delivery to user {db_user.telegram_id}: {e}")

        logger.info(f"Order #{order_id}: Completed successfully")

    except Exception as e:
        logger.error(f"Order #{order_id} failed: {e}", exc_info=True)
        try:
            async with async_session() as session:
                result = await session.execute(select(Order).where(Order.id == order_id))
                db_order = result.scalar_one_or_none()
                if db_order:
                    db_order.status = "FAILED"
                    await session.commit()
        except Exception:
            pass

        try:
            from userbot.ai_fallback import fallback_ai_agent
            client = await get_client()
            chat_history = []
            async for msg in client.get_chat_history(config.SOURCE_BOT, limit=5):
                chat_history.append({
                    "text": msg.text or "",
                    "reply_markup": msg.reply_markup,
                    "from_user": msg.from_user.is_bot if msg.from_user else False,
                })
            fallback_result = await fallback_ai_agent(chat_history, plan)
            if fallback_result:
                logger.info(f"Order #{order_id}: AI fallback action: {fallback_result}")
                action = fallback_result.get("action")
                value = fallback_result.get("value", "")
                if action == "send_text":
                    await client.send_message(config.SOURCE_BOT, value)
                elif action == "click_inline":
                    messages = await wait_for_reply(client, config.SOURCE_BOT, timeout=15)
                    if messages:
                        latest = messages[-1]
                        await press_inline_button(client, config.SOURCE_BOT, latest, value)
                elif action == "click_reply":
                    await click_reply_keyboard(client, config.SOURCE_BOT, value)
                elif action == "extract_url" and value:
                    from api.main import rebrand_config
                    rebranded = await rebrand_config(value)
                    delivery_link = f"https://{config.SERVER_HOST}/sub/{order_id}"
                    async with async_session() as session:
                        result = await session.execute(select(Order).where(Order.id == order_id))
                        db_order = result.scalar_one_or_none()
                        if db_order:
                            db_order.status = "COMPLETED"
                            db_order.sub_link = delivery_link
                            db_order.raw_sub_link = rebranded
                            db_order.completed_at = datetime.datetime.utcnow()
                            await session.commit()
                            user_result = await session.execute(select(User).where(User.id == db_order.user_id))
                            db_user = user_result.scalar_one_or_none()
                            if db_user:
                                try:
                                    await client.send_message(
                                        db_user.telegram_id,
                                        f"✅ سرور شما آماده است!\n\n"
                                        f"📦 پلن: {plan['name']}\n"
                                        f"🔗 لینک اشتراک:\n<code>{delivery_link}</code>\n\n"
                                        f"💡 این لینک را در اپلیکیشن VPN خود وارد کنید.",
                                    )
                                except Exception as e:
                                    logger.error(f"Failed to send delivery to user {db_user.telegram_id}: {e}")
                    logger.info(f"Order #{order_id}: Completed via AI fallback URL extraction")
        except Exception as ai_err:
            logger.error(f"AI fallback also failed for order #{order_id}: {ai_err}")


class ArqSettings:
    functions = [process_order]
    redis_settings = RedisSettings.from_dsn(config.REDIS_URL)
    max_jobs = 5
