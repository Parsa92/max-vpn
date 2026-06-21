import datetime
import logging
from aiogram import Router, F, Bot
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select
from arq.connections import RedisSettings
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


class AdminAmountState(StatesGroup):
    waiting_for_amount = State()


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

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ وارد کردن مبلغ", callback_data=f"enter_amount:{payment.id}")],
        [InlineKeyboardButton(text="❌ رد", callback_data=f"reject:{payment.id}")],
    ])

    bot = message.bot
    await bot.send_photo(
        chat_id=config.ADMIN_ID,
        photo=receipt_file_id,
        caption=(
            f"📥 رسید پرداخت جدید\n"
            f"کاربر: @{user.username or 'ندارد'} (ID: {user.telegram_id})\n"
            f"شناسه پرداخت: {payment.id}\n\n"
            f"مبلغ را وارد کنید:"
        ),
        reply_markup=kb,
    )

    await message.answer(
        "✅ رسید شما دریافت شد.\nلطفاً منتظر بررسی ادمین باشید."
    )


@router.callback_query(F.data.startswith("enter_amount:"))
async def cb_enter_amount(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != config.ADMIN_ID:
        await callback.answer("⛔ فقط ادمین", show_alert=True)
        return

    payment_id = int(callback.data.split(":")[1])
    await state.update_data(payment_id=payment_id)
    await state.set_state(AdminAmountState.waiting_for_amount)

    await callback.message.answer("✍️ مبلغ پرداخت را به تومان وارد کنید (فقط عدد):")
    await callback.answer()


@router.message(AdminAmountState.waiting_for_amount)
async def process_admin_amount(message: Message, state: FSMContext, bot: Bot):
    if message.from_user.id != config.ADMIN_ID:
        return

    try:
        amount = int(message.text.strip().replace(",", "").replace(" ", ""))
        if amount <= 0:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("❌ لطفاً یک عدد معتبر وارد کنید:")
        return

    data = await state.get_data()
    payment_id = data.get("payment_id")
    await state.clear()

    async with async_session() as session:
        result = await session.execute(select(Payment).where(Payment.id == payment_id))
        payment = result.scalar_one_or_none()
        if not payment:
            await message.answer("پرداخت یافت نشد")
            return

        payment.amount = amount
        payment.status = "APPROVED"
        payment.reviewed_at = datetime.datetime.utcnow()

        user_result = await session.execute(select(User).where(User.id == payment.user_id))
        user = user_result.scalar_one_or_none()
        if user:
            user.balance += amount

        await session.commit()

    await message.answer(
        f"✅ پرداخت تایید شد\n"
        f"مبلغ: {amount:,} تومان\n"
        f"شناسه: {payment_id}"
    )

    if user:
        try:
            await bot.send_message(
                chat_id=user.telegram_id,
                text=f"✅ کیف پول شما شارژ شد!\nمبلغ: <b>{amount:,} تومان</b>\n"
                     f"موجودی فعلی: <b>{user.balance:,} تومان</b>",
            )
        except Exception as e:
            logger.error(f"Failed to notify user {user.telegram_id}: {e}")


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

        updated_balance = db_user.balance

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
    from arq.connections import RedisSettings

    try:
        pool = await create_pool(RedisSettings(host="127.0.0.1", port=6379))
        await pool.enqueue_job("process_order", order_id=order.id, plan_id=plan["id"])
        await pool.aclose()
        logger.info(f"Order #{order.id} queued for processing")
    except Exception as e:
        logger.error(f"Failed to enqueue order #{order.id}: {e}")
        async with async_session() as session:
            result = await session.execute(select(Order).where(Order.id == order.id))
            db_order = result.scalar_one_or_none()
            if db_order:
                db_order.status = "FAILED"
                user_result = await session.execute(select(User).where(User.id == db_order.user_id))
                db_user = user_result.scalar_one_or_none()
                if db_user:
                    db_user.balance += db_order.price
                await session.commit()

        try:
            from aiogram import Bot
            from aiogram.client.default import DefaultBotProperties
            from aiogram.enums import ParseMode
            bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
            await bot.send_message(
                chat_id=callback.from_user.id,
                text=f"❌ پردازش سرور ناموفق بود.\nمبلغ <b>{plan['price']:,} تومان</b> به کیف پول شما بازگشت داده شد.",
            )
            await bot.session.close()
        except Exception as notify_err:
            logger.error(f"Failed to notify user: {notify_err}")

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
        completed_result = await session.execute(
            select(Order).where(Order.status == "COMPLETED")
        )
        completed_orders = completed_result.scalars().all()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 لیست کاربران", callback_data="admin:users")],
        [InlineKeyboardButton(text="📋 سفارشات در انتظار", callback_data="admin:pending")],
        [InlineKeyboardButton(text="✅ سفارشات تکمیل شده", callback_data="admin:completed")],
        [InlineKeyboardButton(text="💰 تغییر قیمت پلن‌ها", callback_data="admin:prices")],
        [InlineKeyboardButton(text="🔄 رفرش لینک‌ها", callback_data="admin:refresh")],
    ])

    await message.answer(
        f"🔧 پنل ادمین\n\n"
        f"👥 کل کاربران: {len(user_count)}\n"
        f"⏳ سفارشات در انتظار: {len(pending_orders)}\n"
        f"✅ سفارشات تکمیل شده: {len(completed_orders)}",
        reply_markup=kb,
    )


@router.callback_query(F.data == "admin:users")
async def admin_users(callback: CallbackQuery):
    if callback.from_user.id != config.ADMIN_ID:
        await callback.answer("⛔ فقط ادمین", show_alert=True)
        return

    async with async_session() as session:
        result = await session.execute(select(User).order_by(User.created_at.desc()).limit(20))
        users = result.scalars().all()

    if not users:
        await callback.answer("کاربری یافت نشد", show_alert=True)
        return

    lines = ["👥 ۲۰ کاربر آخر:\n"]
    for u in users:
        lines.append(f"• @{u.username or 'ندارد'} | ID: {u.telegram_id} | 💰 {u.balance:,}")

    await callback.message.answer("\n".join(lines))
    await callback.answer()


@router.callback_query(F.data == "admin:pending")
async def admin_pending(callback: CallbackQuery):
    if callback.from_user.id != config.ADMIN_ID:
        await callback.answer("⛔ فقط ادمین", show_alert=True)
        return

    async with async_session() as session:
        result = await session.execute(
            select(Order).where(Order.status.in_(["PENDING", "PROCESSING"])).order_by(Order.created_at.desc()).limit(20)
        )
        orders = result.scalars().all()

    if not orders:
        await callback.answer("سفارش در انتظاری نیست", show_alert=True)
        return

    lines = ["⏳ سفارشات در انتظار:\n"]
    for o in orders:
        lines.append(f"• #{o.id} | {o.plan_name} | {o.status}")

    await callback.message.answer("\n".join(lines))
    await callback.answer()


@router.callback_query(F.data == "admin:completed")
async def admin_completed(callback: CallbackQuery):
    if callback.from_user.id != config.ADMIN_ID:
        await callback.answer("⛔ فقط ادمین", show_alert=True)
        return

    async with async_session() as session:
        result = await session.execute(
            select(Order).where(Order.status == "COMPLETED").order_by(Order.created_at.desc()).limit(20)
        )
        orders = result.scalars().all()

    if not orders:
        await callback.answer("سفارش تکمیل شده‌ای نیست", show_alert=True)
        return

    lines = ["✅ ۲۰ سفارش آخر:\n"]
    for o in orders:
        lines.append(f"• #{o.id} | {o.plan_name} | {o.price:,} تومان")

    await callback.message.answer("\n".join(lines))
    await callback.answer()


class PriceEditState(StatesGroup):
    waiting_for_plan = State()
    waiting_for_price = State()


@router.callback_query(F.data == "admin:prices")
async def admin_prices(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != config.ADMIN_ID:
        await callback.answer("⛔ فقط ادمین", show_alert=True)
        return

    lines = ["💰 قیمت فعلی پلن‌ها:\n"]
    for p in config.PLANS:
        lines.append(f"{p['id']}. {p['name']} - {p['price']:,} تومان")
    lines.append("\nشماره پلن مورد نظر را وارد کنید (۱-۴):")

    await callback.message.answer("\n".join(lines))
    await state.set_state(PriceEditState.waiting_for_plan)
    await callback.answer()


@router.message(PriceEditState.waiting_for_plan)
async def process_price_plan(message: Message, state: FSMContext):
    if message.from_user.id != config.ADMIN_ID:
        return

    try:
        plan_id = int(message.text.strip())
        if plan_id not in [1, 2, 3, 4]:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("❌ شماره پلن معتبر نیست (۱-۴):")
        return

    plan = config.PLAN_MAP.get(plan_id)
    await state.update_data(plan_id=plan_id)
    await message.answer(
        f"پلن {plan['name']} انتخاب شد.\n"
        f"قیمت فعلی: {plan['price']:,} تومان\n"
        f"قیمت جدید را به تومان وارد کنید:"
    )
    await state.set_state(PriceEditState.waiting_for_price)


@router.message(PriceEditState.waiting_for_price)
async def process_price_value(message: Message, state: FSMContext):
    if message.from_user.id != config.ADMIN_ID:
        return

    try:
        new_price = int(message.text.strip().replace(",", "").replace(" ", ""))
        if new_price <= 0:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("❌ لطفاً یک عدد معتبر وارد کنید:")
        return

    data = await state.get_data()
    plan_id = data.get("plan_id")
    await state.clear()

    import json

    for p in config.PLANS:
        if p["id"] == plan_id:
            old_price = p["price"]
            p["price"] = new_price
            break

    config_file = config.CONFIG_FILE
    try:
        with open(config_file, "r") as f:
            cfg = json.load(f)
        if "plans" not in cfg:
            cfg["plans"] = []
        for p in config.PLANS:
            found = False
            for i, saved in enumerate(cfg["plans"]):
                if saved.get("id") == p["id"]:
                    cfg["plans"][i]["price"] = p["price"]
                    found = True
                    break
            if not found:
                cfg["plans"].append(p)
        with open(config_file, "w") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to save prices to config: {e}")

    await message.answer(
        f"✅ قیمت پلن {config.PLAN_MAP[plan_id]['name']} تغییر کرد.\n"
        f"قبل: {old_price:,} تومان\n"
        f"بعد: {new_price:,} تومان"
    )


@router.callback_query(F.data == "admin:refresh")
async def admin_refresh(callback: CallbackQuery):
    if callback.from_user.id != config.ADMIN_ID:
        await callback.answer("⛔ فقط ادمین", show_alert=True)
        return

    from arq import create_pool
    from arq.connections import RedisSettings

    try:
        pool = await create_pool(RedisSettings(host="127.0.0.1", port=6379))
        await pool.enqueue_job("refresh_subscriptions")
        await pool.aclose()
        await callback.answer("🔄 رفرش لینک‌ها شروع شد", show_alert=True)
    except Exception as e:
        logger.error(f"Failed to enqueue refresh: {e}")
        await callback.answer("خطا در شروع رفرش", show_alert=True)
