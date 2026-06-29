import os
import math
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

logging.basicConfig(level=logging.INFO)

# Render'da "Environment" bo'limida o'rnatiladigan qiymatlar
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
WEBHOOK_HOST = os.environ["WEBHOOK_HOST"]   # masalan: https://sizning-bot.onrender.com
WEBHOOK_PATH = f"/webhook/{TELEGRAM_TOKEN}"
PORT = int(os.environ.get("PORT", 10000))

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# ============================================================
# AVTOMOBIL MODELLARI VA NARXLARI
# Yangi model qo'shish kerak bo'lsa - shu yerga qo'shiladi.
# ============================================================
CARS = {
    "TRACKER-2": {
        "LS PLUS AT": 220_951_000,
        "LTZ TURBO AT": 244_108_840,
        "PREMIER TURBO AT": 272_656_160,
        "REDLINE TURBO AT": 282_474_080,
    },
}

# Boshlang'ich to'lov foizi bo'yicha tanlov tugmalari
DOWN_PERCENTS = [25, 30, 40, 50]


def get_months(down_percent: int, position: str) -> int:
    """Boshlang'ich to'lov foiziga va pozitsiyaga qarab, muddatni (oy) qaytaradi."""
    if down_percent == 25:
        return 30
    if down_percent == 30:
        return 33
    if down_percent == 40:
        return 44 if position == "LS PLUS AT" else 41
    if down_percent == 50:
        return 54
    raise ValueError(f"Noma'lum foiz: {down_percent}")


def parse_number(text: str) -> float:
    """Foydalanuvchi yozgan raqamni tozalab, songa o'tkazadi (bo'sh joy, vergul, % bo'lsa ham ishlaydi)."""
    return float(text.replace(" ", "").replace(",", ".").replace("%", ""))


def quick_keyboard(values, suffix="", per_row=4):
    """Tez-tez ishlatiladigan qiymatlar uchun tayyor tugmalar yaratadi."""
    buttons = [types.KeyboardButton(text=f"{v}{suffix}") for v in values]
    rows = [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]
    return types.ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, one_time_keyboard=True)


# Sug'urta va komissiya savollari uchun holatlar
class Extra(StatesGroup):
    insurance = State()
    commission = State()


@dp.message(CommandStart())
async def start_handler(message: types.Message, state: FSMContext):
    await state.clear()
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text=model, callback_data=f"car_model:{model}")]
            for model in CARS
        ]
    )
    await message.answer(
        "Salom! Men avtokredit kalkulyatoriman.\n\n🚗 Avtomobil modelini tanlang:",
        reply_markup=keyboard,
    )


@dp.callback_query(F.data.startswith("car_model:"))
async def choose_model(callback: types.CallbackQuery, state: FSMContext):
    model = callback.data.split(":", 1)[1]
    await state.update_data(model=model)

    positions = list(CARS[model].keys())
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(
                text=f"{pos} — {CARS[model][pos]:,.0f} so'm",
                callback_data=f"car_pos:{i}",
            )]
            for i, pos in enumerate(positions)
        ]
    )
    await callback.message.edit_text(
        f"🚘 {model} uchun pozitsiyani tanlang:", reply_markup=keyboard
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("car_pos:"))
async def choose_position(callback: types.CallbackQuery, state: FSMContext):
    idx = int(callback.data.split(":", 1)[1])
    data = await state.get_data()
    model = data["model"]

    positions = list(CARS[model].keys())
    position = positions[idx]
    price = CARS[model][position]
    await state.update_data(position=position, price=price)

    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text=f"{p}%", callback_data=f"car_pct:{p}")]
            for p in DOWN_PERCENTS
        ]
    )
    await callback.message.edit_text(
        f"✅ Tanlandi: {model} {position}\n"
        f"💰 Narxi: {price:,.0f} so'm\n\n"
        f"Boshlang'ich to'lov necha foiz bo'lsin?",
        reply_markup=keyboard,
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("car_pct:"))
async def choose_percent(callback: types.CallbackQuery, state: FSMContext):
    percent = int(callback.data.split(":", 1)[1])
    data = await state.get_data()
    model = data["model"]
    position = data["position"]
    price = data["price"]

    months = get_months(percent, position)
    down_payment = price * percent / 100
    loan_amount = price - down_payment

    # Keyingi savollar (sug'urta, komissiya) uchun hozirgача hisoblanganlarni saqlab qo'yamiz
    await state.update_data(
        percent=percent, months=months, down_payment=down_payment, loan_amount=loan_amount
    )

    await callback.message.edit_text(
        f"✅ {model} {position}\n"
        f"💰 Narxi: {price:,.0f} so'm\n"
        f"💵 Boshlang'ich to'lov ({percent}%): {down_payment:,.0f} so'm\n"
        f"📅 Muddat: {months} oy"
    )
    await callback.answer()

    await callback.message.answer(
        "🛡 Sug'urta har yili (12 oyda) avtomobil narxidan necha foiz?",
        reply_markup=quick_keyboard([1, 2, 3, 4, 5], suffix="%"),
    )
    await state.set_state(Extra.insurance)


@dp.message(Extra.insurance)
async def get_insurance(message: types.Message, state: FSMContext):
    try:
        insurance_percent = parse_number(message.text)
    except ValueError:
        await message.answer("Iltimos, faqat raqam kiriting. Masalan: 3")
        return

    await state.update_data(insurance_percent=insurance_percent)
    await message.answer(
        "🏢 Firma komissiyasi avtomobil tannarxidan necha foiz?",
        reply_markup=quick_keyboard([0, 1, 2, 3], suffix="%"),
    )
    await state.set_state(Extra.commission)


@dp.message(Extra.commission)
async def get_commission(message: types.Message, state: FSMContext):
    try:
        commission_percent = parse_number(message.text)
    except ValueError:
        await message.answer("Iltimos, faqat raqam kiriting. Masalan: 2")
        return

    data = await state.get_data()
    model = data["model"]
    position = data["position"]
    price = data["price"]
    percent = data["percent"]
    months = data["months"]
    down_payment = data["down_payment"]
    loan_amount = data["loan_amount"]
    insurance_percent = data["insurance_percent"]

    monthly_payment = loan_amount / months
    years = math.ceil(months / 12)
    insurance_total = price * insurance_percent / 100 * years
    commission_total = price * commission_percent / 100

    initial_total = down_payment + insurance_total + commission_total
    total_payment = initial_total + loan_amount  # foizsiz - kredit summasi ustiga ustama yo'q

    await message.answer(
        f"📊 Yakuniy hisob-kitob\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🚗 {model} {position}\n"
        f"💰 Narxi: {price:,.0f} so'm\n"
        f"📅 Muddat: {months} oy\n\n"
        f"💵 Boshlang'ich to'lov ({percent}%): {down_payment:,.0f} so'm\n"
        f"🛡 Sug'urta ({insurance_percent:.0f}%/yil, {years} yil): {insurance_total:,.0f} so'm\n"
        f"🏢 Komissiya ({commission_percent:.0f}%): {commission_total:,.0f} so'm\n"
        f"➡️ Boshida to'lanadigan jami: {initial_total:,.0f} so'm\n\n"
        f"📦 Kredit summasi: {loan_amount:,.0f} so'm\n"
        f"💳 Oylik to'lov: {monthly_payment:,.0f} so'm\n\n"
        f"🔚 JAMI TO'LANADIGAN SUMMA: {total_payment:,.0f} so'm\n\n"
        f"Yana hisoblash uchun /start ni bosing.",
        reply_markup=types.ReplyKeyboardRemove(),
    )
    await state.clear()


async def on_startup(app: web.Application):
    await bot.set_webhook(f"{WEBHOOK_HOST}{WEBHOOK_PATH}")


def main():
    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    app.on_startup.append(on_startup)
    web.run_app(app, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()
