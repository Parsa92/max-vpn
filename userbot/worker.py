import asyncio
import random
import re
import base64
import logging
import datetime
import time
from pyrogram import Client, raw
from pyrogram.types import Message
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


async def get_new_messages(client: Client, chat: str, since: float, limit: int = 10) -> list[Message]:
    messages = []
    try:
        async for msg in client.get_chat_history(chat, limit=limit):
            msg_ts = msg.date.timestamp()
            if msg_ts > since:
                messages.append(msg)
            else:
                break
    except Exception as e:
        logger.debug(f"Error getting chat history: {e}")
    return messages


async def get_latest_messages(client: Client, chat: str, limit: int = 20) -> list[Message]:
    messages = []
    try:
        async for msg in client.get_chat_history(chat, limit=limit):
            messages.append(msg)
    except Exception as e:
        logger.debug(f"Error getting chat history: {e}")
    return messages


async def wait_for_new_message(client: Client, chat: str, timeout: int = 30, since: float = None) -> Message | None:
    if since is None:
        since = time.time() - 1
    deadline = time.time() + timeout
    while time.time() < deadline:
        await asyncio.sleep(2.0)
        messages = await get_new_messages(client, chat, since)
        if messages:
            return messages[0]
    return None


async def wait_for_multiple_messages(client: Client, chat: str, count: int, timeout: int = 45) -> list[Message]:
    since = time.time() - 1
    collected = []
    deadline = time.time() + timeout
    while time.time() < deadline and len(collected) < count:
        await asyncio.sleep(2.0)
        messages = await get_new_messages(client, chat, since)
        if messages:
            collected = messages
    return collected


def find_button_in_message(message: Message, text: str) -> bool:
    if not message.reply_markup:
        return False
    keyboard = message.reply_markup
    if hasattr(keyboard, "keyboard"):
        for row in keyboard.keyboard:
            for button in row:
                if text in button.text:
                    return True
    if hasattr(keyboard, "inline_keyboard"):
        for row in keyboard.inline_keyboard:
            for button in row:
                if text in button.text:
                    return True
    return False


def find_inline_callback(message: Message, text_contains: str) -> str | None:
    if not message.reply_markup:
        return None
    keyboard = message.reply_markup
    if hasattr(keyboard, "inline_keyboard"):
        for row in keyboard.inline_keyboard:
            for button in row:
                if text_contains in button.text:
                    return button.callback_data
    return None


def get_plan_button_gb(button_text: str) -> int | None:
    persian_to_int = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
    normalized = button_text.translate(persian_to_int)
    match = re.search(r'(\d+)\s*گیگ', normalized)
    if match:
        return int(match.group(1))
    match = re.search(r'(\d+)\s*GB', normalized, re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.search(r'(\d+)\s*گیگ', button_text)
    if match:
        return int(match.group(1))
    return None


async def click_inline_button(client: Client, chat: str, message: Message, text_contains: str) -> bool:
    callback_data = find_inline_callback(message, text_contains)
    if not callback_data:
        logger.warning(f"Inline button '{text_contains}' not found")
        return False
    try:
        peer = await client.resolve_peer(chat)
        await client.invoke(
            raw.functions.messages.GetBotCallbackAnswer(
                peer=peer,
                msg_id=message.id,
                data=callback_data.encode('utf-8'),
            )
        )
        logger.info(f"Clicked inline button: {text_contains}")
        return True
    except Exception as e:
        logger.warning(f"GetBotCallbackAnswer failed: {e}, sending text")
        await client.send_message(chat, text_contains)
        return True


async def click_inline_by_gb(client: Client, chat: str, message: Message, target_gb: int) -> bool:
    if not message.reply_markup:
        return False
    keyboard = message.reply_markup
    if not hasattr(keyboard, "inline_keyboard"):
        return False
    for row in keyboard.inline_keyboard:
        for button in row:
            btn_gb = get_plan_button_gb(button.text)
            if btn_gb == target_gb:
                logger.info(f"Found matching button: {button.text[:50]} callback_data={button.callback_data}")
                try:
                    peer = await client.resolve_peer(chat)
                    await client.invoke(
                        raw.functions.messages.GetBotCallbackAnswer(
                            peer=peer,
                            msg_id=message.id,
                            data=button.callback_data.encode('utf-8'),
                        )
                    )
                    logger.info(f"Clicked plan button for {target_gb}GB: {button.text[:50]}")
                    return True
                except Exception as e:
                    logger.warning(f"GetBotCallbackAnswer failed: {e}, sending text")
                    await client.send_message(chat, button.text)
                    return True
    return False


def extract_all_configs(text: str) -> list[str]:
    configs = []
    vless_urls = re.findall(r'vless://[^\s<"]+', text)
    vmess_urls = re.findall(r'vmess://[^\s<"]+', text)
    configs.extend(vless_urls)
    configs.extend(vmess_urls)
    return configs


def rebrand_configs(configs: list[str]) -> str:
    all_text = "\n".join(configs)
    rebranded = all_text.replace("MMDLeecher", "max_v2connect")
    rebranded = rebranded.replace("mmdleecher", "max_v2connect")
    encoded = base64.b64encode(rebranded.encode("utf-8")).decode("utf-8")
    return encoded


async def purchase_from_source_bot(client: Client, plan: dict) -> tuple[str, str]:
    chat = config.SOURCE_BOT
    username = f"user{int(time.time())}{random.randint(1000, 9999)}"
    target_gb = plan["data_gb"]

    logger.info(f"Step 1: Sending /start to {chat}")
    since = time.time() - 1
    await client.send_message(chat, "/start")
    await asyncio.sleep(2)
    msg = await wait_for_new_message(client, chat, timeout=30, since=since)
    if not msg:
        raise ValueError("No reply after /start")
    logger.info(f"Got: {(msg.text or '')[:80]}")

    logger.info("Step 2: Sending 'خرید سرور نیم بها'")
    since = time.time() - 1
    await client.send_message(chat, "🛒 خرید سرور نیم بها")
    await asyncio.sleep(2)
    msg = await wait_for_new_message(client, chat, timeout=30, since=since)
    if not msg:
        raise ValueError("No reply after buy text")
    logger.info(f"Got: {(msg.text or '')[:80]}")

    logger.info("Step 3: Sending 'خرید سرور نیم بها با کیف پول'")
    since = time.time() - 1
    await client.send_message(chat, "🛒 خرید سرور نیم بها با کیف پول")
    await asyncio.sleep(2)
    msg = await wait_for_new_message(client, chat, timeout=30, since=since)
    if not msg:
        raise ValueError("No reply after wallet buy text")
    logger.info(f"Got: {(msg.text or '')[:80]}")

    logger.info(f"Step 4: Replying with username: {username}")
    if msg:
        await client.send_message(chat, username, reply_to_message_id=msg.id)
    else:
        await client.send_message(chat, username)
    await asyncio.sleep(2)

    logger.info(f"Step 5: Waiting 8 seconds for plan buttons to appear...")
    username_reply_id = msg.id if msg else 0
    await asyncio.sleep(8.0)

    logger.info(f"Step 5: Selecting plan {target_gb}GB from inline keyboard (username_reply_id={username_reply_id})")
    msg = None
    for attempt in range(15):
        messages = await get_latest_messages(client, chat, limit=20)
        messages.sort(key=lambda m: m.date.timestamp(), reverse=True)
        logger.info(f"  Attempt {attempt+1}: {len(messages)} latest messages")
        for m in messages:
            if m.id <= username_reply_id:
                continue
            m_ts = m.date.timestamp()
            has_inline = m.reply_markup and hasattr(m.reply_markup, "inline_keyboard") and m.reply_markup.inline_keyboard
            logger.info(f"  msg_id={m.id} date_ts={m_ts:.2f} has_inline={has_inline} text={repr((m.text or '')[:60])}")
            if has_inline:
                msg = m
                logger.info(f"  Found inline keyboard on attempt {attempt+1}, msg_id={m.id}")
                break
        if msg:
            break
        await asyncio.sleep(3.0)

    if msg:
        clicked = await click_inline_by_gb(client, chat, msg, target_gb)
        if not clicked:
            logger.warning(f"Could not find {target_gb}GB button, listing available buttons:")
            if msg.reply_markup and hasattr(msg.reply_markup, "inline_keyboard"):
                for row in msg.reply_markup.inline_keyboard:
                    for btn in row:
                        gb = get_plan_button_gb(btn.text)
                        logger.warning(f"  RAW BUTTON TEXT: [{btn.text}] -> detected: {gb}GB")
            else:
                logger.warning(f"  No inline_keyboard in reply_markup. Type: {type(msg.reply_markup)}")
                logger.warning(f"  msg.text: {(msg.text or '')[:200]}")
    else:
        logger.error("No message with plan buttons found after all attempts")
        raise ValueError("No message with plan buttons after 15 attempts")
    await asyncio.sleep(2)

    logger.info("Step 6: Sending /start again for link retrieval")
    since = time.time() - 1
    await client.send_message(chat, "/start")
    await asyncio.sleep(2)
    msg = await wait_for_new_message(client, chat, timeout=30)
    if not msg:
        raise ValueError("No reply after second /start")
    logger.info(f"Got: {(msg.text or '')[:80]}")

    logger.info("Step 7: Sending '🧩 دریافت لینک تکی سرور نیم بها'")
    await client.send_message(chat, "🧩 دریافت لینک تکی سرور نیم بها")
    await asyncio.sleep(2)

    logger.info("Step 8: Looking for username in inline keyboard")
    username_clicked = False
    deadline = time.time() + 45
    while time.time() < deadline and not username_clicked:
        messages = await get_latest_messages(client, chat, limit=20)
        messages.sort(key=lambda m: m.date.timestamp(), reverse=True)
        for msg in messages:
            if not (msg.reply_markup and hasattr(msg.reply_markup, "inline_keyboard")):
                continue
            for row in msg.reply_markup.inline_keyboard:
                for btn in row:
                    if username in btn.text:
                        try:
                            peer = await client.resolve_peer(chat)
                            await client.invoke(
                                raw.functions.messages.GetBotCallbackAnswer(
                                    peer=peer,
                                    msg_id=msg.id,
                                    data=btn.callback_data.encode('utf-8'),
                                )
                            )
                            username_clicked = True
                            logger.info(f"Clicked username button: {btn.text[:50]}")
                            break
                        except Exception as e:
                            logger.warning(f"Failed to click username: {e}")
            if username_clicked:
                break
        if not username_clicked:
            await asyncio.sleep(3.0)

    if not username_clicked:
        logger.warning("Username button not found, trying to find any username button")
        messages = await get_latest_messages(client, chat, limit=20)
        messages.sort(key=lambda m: m.date.timestamp(), reverse=True)
        for msg in messages:
            if not (msg.reply_markup and hasattr(msg.reply_markup, "inline_keyboard")):
                continue
            for row in msg.reply_markup.inline_keyboard:
                for btn in row:
                    if "user" in btn.text.lower():
                        try:
                            peer = await client.resolve_peer(chat)
                            await client.invoke(
                                raw.functions.messages.GetBotCallbackAnswer(
                                    peer=peer,
                                    msg_id=msg.id,
                                    data=btn.callback_data.encode('utf-8'),
                                )
                            )
                            username_clicked = True
                            logger.info(f"Clicked fallback username: {btn.text[:50]}")
                            break
                        except Exception:
                            pass
            if username_clicked:
                break

    logger.info("Step 9: Collecting vless/vmess configs from multiple messages")
    all_configs = []
    deadline = time.time() + 30
    seen_texts = set()
    while time.time() < deadline:
        msg = await wait_for_new_message(client, chat, timeout=10)
        if msg and msg.text:
            if msg.text not in seen_texts:
                seen_texts.add(msg.text)
                configs = extract_all_configs(msg.text)
                if configs:
                    all_configs.extend(configs)
                    logger.info(f"Found {len(configs)} configs in message (total: {len(all_configs)})")
        if all_configs:
            await asyncio.sleep(3.0)
            msg2 = await wait_for_new_message(client, chat, timeout=5)
            if msg2 and msg2.text:
                configs2 = extract_all_configs(msg2.text)
                if configs2:
                    all_configs.extend(configs2)
                    logger.info(f"Found {len(configs2)} more configs (total: {len(all_configs)})")
            break

    if not all_configs:
        raise ValueError("No vless/vmess configs found in any messages")

    logger.info(f"Total configs collected: {len(all_configs)}")
    rebranded_b64 = rebrand_configs(all_configs)
    return rebranded_b64, username


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

        rebranded_b64, source_username = await purchase_from_source_bot(client, plan)
        logger.info(f"Order #{order_id}: Got rebranded config")

        delivery_link = f"https://{config.SERVER_HOST}/sub/{order_id}"

        async with async_session() as session:
            result = await session.execute(select(Order).where(Order.id == order_id))
            db_order = result.scalar_one_or_none()
            if db_order:
                db_order.status = "COMPLETED"
                db_order.sub_link = delivery_link
                db_order.raw_sub_link = rebranded_b64
                db_order.source_username = source_username
                db_order.completed_at = datetime.datetime.utcnow()
                await session.commit()

                user_result = await session.execute(select(User).where(User.id == db_order.user_id))
                db_user = user_result.scalar_one_or_none()
                if db_user:
                    try:
                        from aiogram import Bot
                        from aiogram.client.default import DefaultBotProperties
                        from aiogram.enums import ParseMode
                        bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
                        await bot.send_message(
                            chat_id=db_user.telegram_id,
                            text=(
                                f"✅ سرور شما آماده است!\n\n"
                                f"📦 پلن: {plan['name']}\n"
                                f"🔗 لینک اشتراک:\n<code>{delivery_link}</code>\n\n"
                                f"💡 این لینک را در اپلیکیشن VPN خود وارد کنید.\n"
                                f"🔄 لینک‌ها روزانه آپدیت می‌شوند."
                            ),
                        )
                        await bot.session.close()
                    except Exception as e:
                        logger.error(f"Failed to send delivery to user {db_user.telegram_id}: {e}")

        logger.info(f"Order #{order_id}: Completed successfully")

    except Exception as e:
        logger.error(f"Order #{order_id} failed: {e}")

        async with async_session() as session:
            result = await session.execute(select(Order).where(Order.id == order_id))
            db_order = result.scalar_one_or_none()
            if db_order and db_order.status != "FAILED":
                db_order.status = "FAILED"
                await session.commit()

                user_result = await session.execute(select(User).where(User.id == db_order.user_id))
                db_user = user_result.scalar_one_or_none()
                if db_user:
                    db_user.balance += db_order.price
                    await session.commit()
                    logger.info(f"Refunded {db_order.price} to user {db_user.telegram_id}")
                    try:
                        from aiogram import Bot
                        from aiogram.client.default import DefaultBotProperties
                        from aiogram.enums import ParseMode
                        bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
                        await bot.send_message(
                            chat_id=db_user.telegram_id,
                            text=(
                                f"❌ پردازش سرور ناموفق بود.\n"
                                f"مبلغ <b>{db_order.price:,} تومان</b> به کیف پول شما بازگشت داده شد.\n"
                                f"لطفاً دوباره تلاش کنید."
                            ),
                        )
                        await bot.session.close()
                    except Exception as notify_err:
                        logger.error(f"Failed to notify user: {notify_err}")


async def refresh_subscriptions(ctx: dict):
    logger.info("Starting daily subscription refresh")
    try:
        client = await get_client()
        async with async_session() as session:
            result = await session.execute(
                select(Order).where(Order.status == "COMPLETED")
            )
            orders = result.scalars().all()

        for order in orders:
            try:
                plan = config.PLAN_MAP.get(order.plan_id)
                if not plan:
                    continue

                chat = config.SOURCE_BOT
                username = order.source_username
                if not username:
                    logger.warning(f"No source_username for order #{order.id}, skipping")
                    continue

                since = time.time() - 1
                await client.send_message(chat, "/start")
                await asyncio.sleep(2)
                await wait_for_new_message(client, chat, timeout=30)

                await client.send_message(chat, "🧩 دریافت لینک تکی سرور نیم بها")
                await asyncio.sleep(2)

                msg = await wait_for_new_message(client, chat, timeout=30)
                if msg and msg.reply_markup and hasattr(msg.reply_markup, "inline_keyboard"):
                    for row in msg.reply_markup.inline_keyboard:
                        for btn in row:
                            if username in btn.text:
                                peer = await client.resolve_peer(chat)
                                await client.invoke(
                                    raw.functions.messages.GetBotCallbackAnswer(
                                        peer=peer,
                                        msg_id=msg.id,
                                        data=btn.callback_data.encode('utf-8'),
                                    )
                                )
                                logger.info(f"Clicked username button for refresh: {btn.text[:50]}")
                                break

                all_configs = []
                deadline = time.time() + 30
                seen_texts = set()
                while time.time() < deadline:
                    msg = await wait_for_new_message(client, chat, timeout=10)
                    if msg and msg.text and msg.text not in seen_texts:
                        seen_texts.add(msg.text)
                        configs = extract_all_configs(msg.text)
                        if configs:
                            all_configs.extend(configs)

                if all_configs:
                    rebranded_b64 = rebrand_configs(all_configs)
                    async with async_session() as session:
                        result = await session.execute(select(Order).where(Order.id == order.id))
                        db_order = result.scalar_one_or_none()
                        if db_order:
                            db_order.raw_sub_link = rebranded_b64
                            await session.commit()
                    logger.info(f"Refreshed links for order #{order.id}")

                await asyncio.sleep(2)

            except Exception as e:
                logger.error(f"Failed to refresh order #{order.id}: {e}")

        logger.info("Daily subscription refresh completed")

    except Exception as e:
        logger.error(f"Subscription refresh failed: {e}")


class ArqSettings:
    functions = [process_order, refresh_subscriptions]
    redis_settings = RedisSettings(host="127.0.0.1", port=6379)
    max_jobs = 1
    job_timeout = 300
