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


def parse_number(text: str) -> float:
    """Foydalanuvchi yozgan raqamni tozalab, songa o'tkazadi (bo'sh joy, vergul bo'lsa ham ishlaydi)."""
    return float(text.replace(" ", "").replace(",", "."))


# Bot ketma-ket 6 ta savol so'raydi - shu uchun har biri uchun "holat" kerak
class Credit(StatesGroup):
    price = State()          # 1. avtomobil narxi
    down_percent = State()   # 2. boshlang'ich to'lov, %
    rate = State()           # 3. yillik foiz stavkasi, %
    months = State()         # 4. muddat, oy
    insurance = State()      # 5. sug'urta, yillik %
    commission = State()     # 6. firma komissiyasi, %


@dp.message(CommandStart())
async def start_handler(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Salom! Men avtokredit kalkulyatoriman.\n\n"
        "1️⃣ Avtomobil narxi qancha? (so'mda, masalan: 200000000)"
    )
    await state.set_state(Credit.price)


@dp.message(Credit.price)
async def get_price(message: types.Message, state: FSMContext):
    try:
        price = parse_number(message.text)
    except ValueError:
        await message.answer("Iltimos, faqat raqam kiriting. Masalan: 200000000")
        return

    await state.update_data(price=price)
    await message.answer("2️⃣ Boshlang'ich to'lov necha foiz? (masalan: 30)")
    await state.set_state(Credit.down_percent)


@dp.message(Credit.down_percent)
async def get_down_percent(message: types.Message, state: FSMContext):
    try:
        down_percent = parse_number(message.text)
    except ValueError:
        await message.answer("Iltimos, faqat raqam kiriting. Masalan: 30")
        return

    await state.update_data(down_percent=down_percent)
    await message.answer("3️⃣ Yillik foiz stavkasi necha foiz? (masalan: 24)")
    await state.set_state(Credit.rate)


@dp.message(Credit.rate)
async def get_rate(message: types.Message, state: FSMContext):
    try:
        rate = parse_number(message.text)
    except ValueError:
        await message.answer("Iltimos, faqat raqam kiriting. Masalan: 24")
        return

    await state.update_data(rate=rate)
    await message.answer("4️⃣ Necha oyga olmoqchisiz? (masalan: 36)")
    await state.set_state(Credit.months)


@dp.message(Credit.months)
async def get_months(message: types.Message, state: FSMContext):
    try:
        months = int(parse_number(message.text))
    except ValueError:
        await message.answer("Iltimos, faqat butun son kiriting. Masalan: 36")
        return

    await state.update_data(months=months)
    await message.answer(
        "5️⃣ Sug'urta har yili (12 oyda) avtomobil narxidan necha foiz? (masalan: 3)"
    )
    await state.set_state(Credit.insurance)


@dp.message(Credit.insurance)
async def get_insurance(message: types.Message, state: FSMContext):
    try:
        insurance_percent = parse_number(message.text)
    except ValueError:
        await message.answer("Iltimos, faqat raqam kiriting. Masalan: 3")
        return

    await state.update_data(insurance_percent=insurance_percent)
    await message.answer(
        "6️⃣ Firma komissiyasi avtomobil tannarxidan necha foiz? (masalan: 2)"
    )
    await state.set_state(Credit.commission)


@dp.message(Credit.commission)
async def get_commission(message: types.Message, state: FSMContext):
    try:
        commission_percent = parse_number(message.text)
    except ValueError:
        await message.answer("Iltimos, faqat raqam kiriting. Masalan: 2")
        return

    data = await state.get_data()
    price = data["price"]
    down_percent = data["down_percent"]
    annual_rate = data["rate"]
    months = data["months"]
    insurance_percent = data["insurance_percent"]

    # 1. Boshlang'ich to'lov
    down_payment = price * down_percent / 100

    # 2. Kredit summasi (bank to'laydigan qism)
    loan_amount = price - down_payment

    # 3. Oylik to'lov (annuitet formulasi)
    monthly_rate = annual_rate / 12 / 100
    if monthly_rate == 0:
        monthly_payment = loan_amount / months
    else:
        monthly_payment = (
            loan_amount * monthly_rate * (1 + monthly_rate) ** months
        ) / ((1 + monthly_rate) ** months - 1)

    total_loan_payment = monthly_payment * months
    loan_overpayment = total_loan_payment - loan_amount  # foiz hisobiga ortiqcha to'lov

    # 4. Sug'urta - har 12 oyda avtomobil narxidan foiz, muddat necha yilga yetsa shuncha marta
    years = math.ceil(months / 12)
    insurance_total = price * insurance_percent / 100 * years

    # 5. Firma komissiyasi - bir martalik, tannarxdan foiz
    commission_total = price * commission_percent / 100

    # 6. Boshida to'lanadigan jami summa (boshlang'ich + sug'urta + komissiya)
    initial_total = down_payment + insurance_total + commission_total

    # 7. Umuman to'lanadigan jami summa (boshida to'langanlar + kredit bo'yicha jami to'lov)
    grand_total = initial_total + total_loan_payment

    # 8. Tugma orqali keyinroq to'lov jadvalini chiqarish uchun kerakli ma'lumotlarni saqlab qo'yamiz
    await state.update_data(
        loan_amount=loan_amount,
        monthly_rate=monthly_rate,
        monthly_payment=monthly_payment,
        months=months,
    )

    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[[
            types.InlineKeyboardButton(
                text="📋 To'lov jadvalini ko'rsatish", callback_data="show_schedule"
            )
        ]]
    )

    await message.answer(
        f"📊 Avtokredit hisob-kitobi\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🚗 Avtomobil narxi: {price:,.0f} so'm\n"
        f"📅 Muddat: {months} oy\n\n"
        f"💵 Boshlang'ich to'lov ({down_percent}%): {down_payment:,.0f} so'm\n"
        f"🛡 Sug'urta ({insurance_percent}%/yil, {years} yil): {insurance_total:,.0f} so'm\n"
        f"🏢 Firma komissiyasi ({commission_percent}%): {commission_total:,.0f} so'm\n"
        f"➡️ Boshida to'lanadigan jami: {initial_total:,.0f} so'm\n\n"
        f"💰 Kredit summasi: {loan_amount:,.0f} so'm\n"
        f"💳 Oylik to'lov: {monthly_payment:,.0f} so'm\n"
        f"📈 Foiz hisobiga ortiqcha to'lov: {loan_overpayment:,.0f} so'm\n\n"
        f"🔚 JAMI TO'LANADIGAN SUMMA: {grand_total:,.0f} so'm\n\n"
        f"Yana hisoblash uchun /start ni bosing.",
        reply_markup=keyboard,
    )


@dp.callback_query(F.data == "show_schedule")
async def show_schedule(callback: types.CallbackQuery, state: FSMContext):
    """Tugma bosilganda har oy bo'yicha to'lov jadvalini chiqaradi."""
    data = await state.get_data()

    # Agar foydalanuvchi hisoblashni hali tugatmagan bo'lsa (eski tugma bosilsa)
    if "loan_amount" not in data:
        await callback.answer("Avval /start orqali yangi hisoblash boshlang.", show_alert=True)
        return

    await callback.answer()  # tugmadagi "yuklanmoqda" belgisini olib tashlash

    loan_amount = data["loan_amount"]
    monthly_rate = data["monthly_rate"]
    monthly_payment = data["monthly_payment"]
    months = data["months"]

    balance = loan_amount
    lines = [f"📋 To'lov jadvali ({months} oy):\n"]
    for m in range(1, months + 1):
        interest = balance * monthly_rate
        principal = monthly_payment - interest
        balance -= principal
        if m == months:
            balance = 0  # yumaloqlash xatosini tuzatish
        lines.append(
            f"{m}-oy: to'lov {monthly_payment:,.0f} | "
            f"asosiy qarz {principal:,.0f} | foiz {interest:,.0f} | "
            f"qoldiq {max(balance, 0):,.0f}"
        )

    # Telegram bitta xabarda ~4096 belgidan ko'p qabul qilmaydi,
    # shu uchun jadvalni bo'laklarga bo'lib, ketma-ket yuboramiz
    chunk_size = 20
    for i in range(0, len(lines), chunk_size):
        chunk = lines[i:i + chunk_size]
        await callback.message.answer("\n".join(chunk))


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
