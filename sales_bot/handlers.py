import datetime
import logging
import io
from aiogram import Router, F, Bot
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.filters import CommandStart, Command
from sqlalchemy import select
import config
from database import async_session
from models import User, Order, Payment

logger = logging.getLogger("sales_bot.handlers")
router = Router()

MAIN_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🛒 خرید سرور"), KeyboardButton(text="💰 کیف پول")],
        [KeyboardButton(text="📋 سفارشات من"), KeyboardButton(text="📞 پشتیبانی")],
    ],
    resize_keyboard=True,
)


async def get_or_create_user(message: Message) -> User:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = result.scalar_one_or_none()
        if not user:
            user = User(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                full_name=message.from_user.full_name,
                balance=0,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
        return user


async def get_user_by_tg_id(tg_id: int) -> User | None:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == tg_id))
        return result.scalar_one_or_none()


@router.message(CommandStart())
async def cmd_start(message: Message):
    await get_or_create_user(message)
    await message.answer(
        f"👋 به MAX VPN خوش آمدید!\n\n"
        f"🔒 بدون نیاز به KYC\n"
        f"⚡ فعال‌سازی خودکار سرور\n"
        f"💳 پرداخت با کیف پول داخلی\n\n"
        f"از منوی زیر استفاده کنید:",
        reply_markup=MAIN_KB,
    )


@router.message(F.text == "💰 کیف پول")
async def wallet_menu(message: Message):
    user = await get_or_create_user(message)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 شارژ کیف پول", callback_data="recharge")],
        [InlineKeyboardButton(text="📊 موجودی من", callback_data="balance")],
    ])
    await message.answer(
        f"💰 موجودی کیف پول شما:\n<b>{int(user.balance):,} تومان</b>",
        reply_markup=kb,
    )


@router.callback_query(F.data == "balance")
async def cb_balance(callback: CallbackQuery):
    user = await get_user_by_tg_id(callback.from_user.id)
    if user:
        await callback.answer(f"موجودی: {int(user.balance):,} تومان", show_alert=True)
    else:
        await callback.answer("کاربر یافت نشد", show_alert=True)


@router.callback_query(F.data == "recharge")
async def cb_recharge(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ ارسال رسید پرداخت", callback_data="send_receipt")],
    ])
    await callback.message.answer(
        f"💳 برای شارژ کیف پول، مبلغ مورد نظر را به کارت زیر واریز کنید:\n\n"
        f"<b>💳 شماره کارت:</b>\n<code>{config.BANK_CARD_NUMBER}</code>\n\n"
        f"سپس رسید پرداخت را ارسال کنید.",
        reply_markup=kb,
    )
    await callback.answer()


@router.callback_query(F.data == "send_receipt")
async def cb_send_receipt(callback: CallbackQuery):
    await callback.message.answer("📸 لطفاً تصویر رسید پرداخت را ارسال کنید:")
    await callback.answer()


@router.message(F.photo)
async def handle_photo(message: Message):
    user = await get_or_create_user(message)
    receipt_file_id = message.photo[-1].file_id

    async with async_session() as session:
        payment = Payment(
            user_id=user.id,
            amount=0,
            status="PENDING",
            receipt_file_id=receipt_file_id,
        )
        session.add(payment)
        await session.commit()
        await session.refresh(payment)

    approve_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ تایید 100K", callback_data=f"approve:{payment.id}:100000"),
            InlineKeyboardButton(text="✅ تایید 250K", callback_data=f"approve:{payment.id}:250000"),
        ],
        [
            InlineKeyboardButton(text="✅ تایید 500K", callback_data=f"approve:{payment.id}:500000"),
            InlineKeyboardButton(text="✅ تایید 1M", callback_data=f"approve:{payment.id}:1000000"),
        ],
        [
            InlineKeyboardButton(text="❌ رد", callback_data=f"reject:{payment.id}"),
        ],
    ])

    bot = message.bot
    admin_msg = await bot.send_photo(
        chat_id=config.ADMIN_ID,
        photo=receipt_file_id,
        caption=(
            f"📥 رسید پرداخت جدید\n"
            f"کاربر: @{user.username or 'ندارد'} (ID: {user.telegram_id})\n"
            f"شناسه پرداخت: {payment.id}"
        ),
        reply_markup=approve_kb,
    )

    await message.answer(
        "✅ رسید شما دریافت شد.\nلطفاً منتظر بررسی ادمین باشید."
    )


@router.callback_query(F.data.startswith("approve:"))
async def cb_approve_payment(callback: CallbackQuery, bot: Bot):
    if callback.from_user.id != config.ADMIN_ID:
        await callback.answer("⛔ فقط ادمین", show_alert=True)
        return

    parts = callback.data.split(":")
    payment_id = int(parts[1])
    amount = int(parts[2])

    async with async_session() as session:
        result = await session.execute(select(Payment).where(Payment.id == payment_id))
        payment = result.scalar_one_or_none()
        if not payment:
            await callback.answer("پرداخت یافت نشد", show_alert=True)
            return

        payment.amount = amount
        payment.status = "APPROVED"
        payment.reviewed_at = datetime.datetime.utcnow()

        user_result = await session.execute(select(User).where(User.id == payment.user_id))
        user = user_result.scalar_one_or_none()
        if user:
            user.balance += amount

        await session.commit()

    await bot.edit_message_caption(
        chat_id=config.ADMIN_ID,
        message_id=callback.message.message_id,
        caption=(
            f"✅ پرداخت تایید شد\n"
            f"مبلغ: {int(amount):,} تومان\n"
            f"شناسه: {payment_id}"
        ),
        reply_markup=None,
    )

    if user:
        try:
            await bot.send_message(
                chat_id=user.telegram_id,
                text=f"✅ کیف پول شما شارژ شد!\nمبلغ: <b>{int(amount):,} تومان</b>\n"
                     f"موجودی فعلی: <b>{int(user.balance):,} تومان</b>",
            )
        except Exception as e:
            logger.error(f"Failed to notify user {user.telegram_id}: {e}")

    await callback.answer("تایید شد")


@router.callback_query(F.data.startswith("reject:"))
async def cb_reject_payment(callback: CallbackQuery, bot: Bot):
    if callback.from_user.id != config.ADMIN_ID:
        await callback.answer("⛔ فقط ادمین", show_alert=True)
        return

    payment_id = int(callback.data.split(":")[1])

    async with async_session() as session:
        result = await session.execute(select(Payment).where(Payment.id == payment_id))
        payment = result.scalar_one_or_none()
        if payment:
            payment.status = "REJECTED"
            payment.reviewed_at = datetime.datetime.utcnow()
            await session.commit()

    await bot.edit_message_caption(
        chat_id=config.ADMIN_ID,
        message_id=callback.message.message_id,
        caption=f"❌ پرداخت رد شد (شناسه: {payment_id})",
        reply_markup=None,
    )

    if payment:
        async with async_session() as session:
            user_result = await session.execute(select(User).where(User.id == payment.user_id))
            user = user_result.scalar_one_or_none()
            if user:
                try:
                    await bot.send_message(
                        chat_id=user.telegram_id,
                        text="❌ پرداخت شما توسط ادمین رد شد.\nدر صورت نیاز با پشتیبانی تماس بگیرید.",
                    )
                except Exception as e:
                    logger.error(f"Failed to notify user {user.telegram_id}: {e}")

    await callback.answer("رد شد")


@router.message(F.text == "🛒 خرید سرور")
async def buy_server(message: Message):
    user = await get_or_create_user(message)
    buttons = []
    for plan in config.PLANS:
        buttons.append([
            InlineKeyboardButton(
                text=f"📦 {plan['name']} - {plan['price']:,} تومان",
                callback_data=f"plan:{plan['id']}",
            )
        ])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(
        "🛒 انتخاب پلن سرور:\n\n"
        "⚡ همه پلن‌ها ۳۰ روزه هستند\n"
        "🔒 بدون نیاز به KYC\n"
        "🔄 تمدید خودکار با شارژ کیف پول",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("plan:"))
async def cb_select_plan(callback: CallbackQuery, bot: Bot):
    plan_id = int(callback.data.split(":")[1])
    plan = config.PLAN_MAP.get(plan_id)
    if not plan:
        await callback.answer("پلن یافت نشد", show_alert=True)
        return

    user = await get_user_by_tg_id(callback.from_user.id)
    if not user:
        await callback.answer("خطا: کاربر یافت نشد", show_alert=True)
        return

    if user.balance < plan["price"]:
        await callback.answer(
            f"موجودی کافی نیست!\nموجودی: {int(user.balance):,} تومان\nقیمت: {plan['price']:,} تومان",
            show_alert=True,
        )
        return

    async with async_session() as session:
        user_result = await session.execute(select(User).where(User.id == user.id))
        db_user = user_result.scalar_one_or_none()
        if db_user.balance < plan["price"]:
            await callback.answer("موجودی کافی نیست", show_alert=True)
            return

        db_user.balance -= plan["price"]

        order = Order(
            user_id=db_user.id,
            plan_id=plan["id"],
            plan_name=plan["name"],
            price=plan["price"],
            status="PENDING",
        )
        session.add(order)
        await session.commit()
        await session.refresh(order)

    await bot.edit_message_text(
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id,
        text=(
            f"✅ سفارش ثبت شد!\n\n"
            f"📦 پلن: {plan['name']}\n"
            f"💰 مبلغ: {plan['price']:,} تومان\n"
            f"🔢 شماره سفارش: #{order.id}\n\n"
            f"⏳ در حال پردازش سرور...\n"
            f"لطفاً چند دقیقه صبر کنید."
        ),
        reply_markup=None,
    )

    from arq import create_pool
    from userbot.worker import ArqSettings

    try:
        pool = await create_pool(
            config.REDIS_URL,
            jobs_registry=None,
        )
        await pool.enqueue_job("process_order", order_id=order.id, plan_id=plan["id"])
        logger.info(f"Order #{order.id} queued for processing")
    except Exception as e:
        logger.error(f"Failed to enqueue order #{order.id}: {e}")
        async with async_session() as session:
            result = await session.execute(select(Order).where(Order.id == order.id))
            db_order = result.scalar_one_or_none()
            if db_order:
                db_order.status = "FAILED"
                await session.commit()

    await callback.answer()


@router.message(F.text == "📋 سفارشات من")
async def my_orders(message: Message):
    user = await get_or_create_user(message)
    async with async_session() as session:
        result = await session.execute(
            select(Order).where(Order.user_id == user.id).order_by(Order.created_at.desc()).limit(10)
        )
        orders = result.scalars().all()

    if not orders:
        await message.answer("📋 شما هنوز سفارشی ندارید.")
        return

    lines = ["📋 آخرین سفارشات شما:\n"]
    for order in orders:
        status_emoji = {"PENDING": "⏳", "COMPLETED": "✅", "FAILED": "❌"}.get(order.status, "❓")
        lines.append(
            f"{status_emoji} #{order.id} | {order.plan_name} | {int(order.price):,} تومان | {order.status}"
        )
        if order.sub_link:
            lines.append(f"   🔗 {order.sub_link}")

    await message.answer("\n".join(lines))


@router.message(F.text == "📞 پشتیبانی")
async def support(message: Message):
    await message.answer(
        "📞 پشتیبانی MAX VPN\n\n"
        "برای ارتباط با پشتیبانی پیام دهید:\n"
        f"👤 ادمین: @{(await message.bot.get_me()).username}"
    )


@router.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id != config.ADMIN_ID:
        await message.answer("⛔ شما ادمین نیستید.")
        return

    async with async_session() as session:
        user_count = (await session.execute(select(User))).scalars().all()
        order_result = await session.execute(
            select(Order).where(Order.status == "PENDING")
        )
        pending_orders = order_result.scalars().all()

    await message.answer(
        f"🔧 پنل ادمین\n\n"
        f"👥 کل کاربران: {len(user_count)}\n"
        f"⏳ سفارشات در انتظار: {len(pending_orders)}"
    )
