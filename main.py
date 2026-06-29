import os
import io
import math
import logging
from aiohttp import web
from PIL import Image, ImageDraw, ImageFont
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

logging.basicConfig(level=logging.INFO)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
WEBHOOK_HOST = os.environ["WEBHOOK_HOST"]
WEBHOOK_PATH = f"/webhook/{TELEGRAM_TOKEN}"
PORT = int(os.environ.get("PORT", 10000))

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# ============================================================
# AVTOMOBIL KATALOGI
# ============================================================

def months_tracker(percent, position):
    table = {25: 30, 30: 33, 50: 54}
    if percent in table:
        return table[percent]
    if percent == 40:
        return 44 if position == "LS PLUS AT" else 41
    return None


def months_onix(percent, position=None):
    return {25: 30, 30: 33, 40: 41, 50: 54}.get(percent)


def months_damas_labo(percent, position=None):
    return {25: 12, 30: 15, 40: 19, 50: 26}.get(percent)


CARS = {
    "TRACKER-2": {
        "positions": {
            "LS PLUS AT": 220_951_000,
            "LTZ TURBO AT": 244_108_840,
            "PREMIER TURBO AT": 272_656_160,
            "REDLINE TURBO AT": 282_474_080,
        },
        "mode": "rasrochka",
        "months_fn": months_tracker,
    },
    "ONIX": {
        "positions": {
            "3 LT MT": 184_750_000,
            "LTZ TURBO AT": 199_899_000,
            "PREMIER 2 TURBO AT": 221_640_160,
            "REDLINE TURBO AT": 230_474_000,
        },
        "mode": "rasrochka",
        "months_fn": months_onix,
    },
    "COBALT": {
        "positions": {
            "Style MCM": 156_100_000,
            "Midnight MCM": 165_200_000,
        },
        "mode": "credit",
    },
    "DAMAS": {
        "price": 96_932_000,
        "months_fn": months_damas_labo,
    },
    "LABO": {
        "price": 96_370_000,
        "months_fn": months_damas_labo,
    },
}

DOWN_PERCENTS = [25, 30, 40, 50]


# ============================================================
# YORDAMCHI FUNKSIYALAR
# ============================================================

def parse_number(text: str) -> float:
    return float(text.replace(" ", "").replace(",", ".").replace("%", ""))


def parse_down_payment(text: str, price: float):
    """1-2 xonali son = foiz, 3+ xonali son = aniq summa (so'mda)."""
    value = parse_number(text)
    if value < 100:
        percent = value
        amount = price * percent / 100
    else:
        amount = value
        percent = amount / price * 100
    return amount, percent


def annuity_payment(loan_amount: float, annual_rate: float, months: int) -> float:
    monthly_rate = annual_rate / 12 / 100
    if monthly_rate == 0:
        return loan_amount / months
    return (loan_amount * monthly_rate * (1 + monthly_rate) ** months) / (
        (1 + monthly_rate) ** months - 1
    )


def generate_schedule_image(model, position, price, loan_amount, annual_rate, monthly_payment, months):
    monthly_rate = (annual_rate / 12 / 100) if annual_rate else 0
    rows = []
    balance = loan_amount
    for m in range(1, months + 1):
        if monthly_rate > 0:
            interest = balance * monthly_rate
            principal = monthly_payment - interest
        else:
            interest = 0.0
            principal = monthly_payment
        balance -= principal
        if m == months:
            balance = 0.0
        rows.append((m, monthly_payment, principal, interest, max(balance, 0.0)))

    col_widths = [50, 150, 150, 130, 150]
    table_width = sum(col_widths)
    margin = 20
    row_h = 30
    header_text_h = 70
    img_width = table_width + margin * 2
    img_height = header_text_h + row_h * (len(rows) + 1) + margin

    img = Image.new("RGB", (img_width, img_height), "white")
    draw = ImageDraw.Draw(img)

    try:
        font_bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
    except Exception:
        font_bold = ImageFont.load_default()
        font = ImageFont.load_default()

    title = model + (f" — {position}" if position else "")
    draw.text((margin, 10), title, fill="black", font=font_bold)
    subtitle = (
        f"Narxi: {price:,.0f} so'm   |   Kredit summasi: {loan_amount:,.0f} so'm   |   Muddat: {months} oy"
    )
    draw.text((margin, 35), subtitle, fill="black", font=font)

    headers = ["Oy", "To'lov", "Asosiy qarz", "Foiz", "Qoldiq"]
    x = margin
    y = header_text_h
    draw.rectangle([x, y, x + table_width, y + row_h], fill="#2c3e50")
    cx = x
    for h, w in zip(headers, col_widths):
        draw.text((cx + 6, y + 7), h, fill="white", font=font_bold)
        cx += w
    y += row_h

    for i, (m, pay, princ, inte, bal) in enumerate(rows):
        bg = "#eef2f7" if i % 2 == 0 else "white"
        draw.rectangle([x, y, x + table_width, y + row_h], fill=bg)
        values = [str(m), f"{pay:,.0f}", f"{princ:,.0f}", f"{inte:,.0f}", f"{bal:,.0f}"]
        cx = x
        for v, w in zip(values, col_widths):
            draw.text((cx + 6, y + 7), v, fill="black", font=font)
            cx += w
        y += row_h

    table_top = header_text_h
    table_bottom = y
    draw.rectangle([x, table_top, x + table_width, table_bottom], outline="#444444", width=1)
    cx = x
    for w in col_widths[:-1]:
        cx += w
        draw.line([(cx, table_top), (cx, table_bottom)], fill="#444444", width=1)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


# ============================================================
# KLAVIATURALAR
# ============================================================

def build_main_menu_kb():
    rows = [[types.InlineKeyboardButton(text=model, callback_data=f"car_model:{model}")] for model in CARS]
    rows.append([types.InlineKeyboardButton(text="✏️ Qo'lda kiritish", callback_data="manual_start")])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def build_positions_kb(model):
    rows = [
        [types.InlineKeyboardButton(text=f"{pos} — {price:,.0f} so'm", callback_data=f"pos:{model}:{i}")]
        for i, (pos, price) in enumerate(CARS[model]["positions"].items())
    ]
    rows.append([types.InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back:main")])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def build_variant_kb(model):
    rows = [
        [types.InlineKeyboardButton(text="📅 Rasrochka (foizsiz)", callback_data=f"variant:{model}:rasrochka")],
        [types.InlineKeyboardButton(text="🏦 Kredit (foizli)", callback_data=f"variant:{model}:kredit")],
        [types.InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back:main")],
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def build_percent_kb(model, back_data):
    rows = [[types.InlineKeyboardButton(text=f"{p}%", callback_data=f"pct:{model}:{p}")] for p in DOWN_PERCENTS]
    rows.append([types.InlineKeyboardButton(text="⬅️ Orqaga", callback_data=back_data)])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


# ============================================================
# HOLATLAR (matn kutilayotgan bosqichlar)
# ============================================================

class Flow(StatesGroup):
    manual_price = State()
    manual_down = State()
    manual_rate = State()
    manual_term = State()
    credit_rate = State()
    credit_term = State()
    credit_down = State()
    insurance = State()
    commission = State()


# ============================================================
# ASOSIY MENYU VA NAVIGATSIYA
# ============================================================

@dp.message(CommandStart())
async def start_handler(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Salom! Avtomobil tanlang yoki qo'lda kiritish variantidan foydalaning:",
        reply_markup=build_main_menu_kb(),
    )


@dp.callback_query(F.data == "back:main")
async def back_main(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Salom! Avtomobil tanlang yoki qo'lda kiritish variantidan foydalaning:",
        reply_markup=build_main_menu_kb(),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("car_model:"))
async def model_selected(callback: types.CallbackQuery, state: FSMContext):
    model = callback.data.split(":", 1)[1]
    info = CARS[model]

    if "positions" in info:
        await state.update_data(model=model)
        await callback.message.edit_text(
            f"🚘 {model} uchun pozitsiyani tanlang:", reply_markup=build_positions_kb(model)
        )
    else:
        await state.update_data(model=model, price=info["price"], position=None)
        await callback.message.edit_text(
            f"🚐 {model}\n💰 Narxi: {info['price']:,.0f} so'm\n\nQaysi variantni tanlaysiz?",
            reply_markup=build_variant_kb(model),
        )
    await callback.answer()


@dp.callback_query(F.data.startswith("back:pos:"))
async def back_to_positions(callback: types.CallbackQuery, state: FSMContext):
    model = callback.data.split(":", 2)[2]
    await callback.message.edit_text(
        f"🚘 {model} uchun pozitsiyani tanlang:", reply_markup=build_positions_kb(model)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("back:variant:"))
async def back_to_variant(callback: types.CallbackQuery, state: FSMContext):
    model = callback.data.split(":", 2)[2]
    info = CARS[model]
    await callback.message.edit_text(
        f"🚐 {model}\n💰 Narxi: {info['price']:,.0f} so'm\n\nQaysi variantni tanlaysiz?",
        reply_markup=build_variant_kb(model),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("pos:"))
async def position_selected(callback: types.CallbackQuery, state: FSMContext):
    _, model, idx = callback.data.split(":")
    idx = int(idx)
    positions = list(CARS[model]["positions"].items())
    position, price = positions[idx]
    await state.update_data(model=model, position=position, price=price)

    if CARS[model]["mode"] == "credit":
        await callback.message.edit_text(
            f"✅ {model} {position}\n💰 Narxi: {price:,.0f} so'm\n\n"
            f"🏦 Yillik foiz stavkasini kiriting (masalan: 26):"
        )
        await state.set_state(Flow.credit_rate)
    else:
        await callback.message.edit_text(
            f"✅ {model} {position}\n💰 Narxi: {price:,.0f} so'm\n\nBoshlang'ich to'lov necha foiz bo'lsin?",
            reply_markup=build_percent_kb(model, f"back:pos:{model}"),
        )
    await callback.answer()


@dp.callback_query(F.data.startswith("variant:"))
async def variant_selected(callback: types.CallbackQuery, state: FSMContext):
    _, model, choice = callback.data.split(":")
    data = await state.get_data()
    price = data["price"]

    if choice == "kredit":
        await callback.message.edit_text(
            f"✅ {model} (Kredit)\n💰 Narxi: {price:,.0f} so'm\n\n"
            f"🏦 Yillik foiz stavkasini kiriting (masalan: 26):"
        )
        await state.set_state(Flow.credit_rate)
    else:
        await callback.message.edit_text(
            f"✅ {model} (Rasrochka)\n💰 Narxi: {price:,.0f} so'm\n\nBoshlang'ich to'lov necha foiz bo'lsin?",
            reply_markup=build_percent_kb(model, f"back:variant:{model}"),
        )
    await callback.answer()


@dp.callback_query(F.data.startswith("pct:"))
async def percent_selected(callback: types.CallbackQuery, state: FSMContext):
    _, model, percent = callback.data.split(":")
    percent = int(percent)
    data = await state.get_data()
    price = data["price"]
    position = data.get("position")

    months = CARS[model]["months_fn"](percent, position)
    down_payment = price * percent / 100
    loan_amount = price - down_payment
    await state.update_data(
        months=months, down_payment=down_payment, down_percent=percent, loan_amount=loan_amount
    )

    await callback.message.edit_text(
        f"✅ Boshlang'ich to'lov: {percent}% ({down_payment:,.0f} so'm)\n📅 Muddat: {months} oy"
    )
    await callback.answer()

    await callback.message.answer("🛡 Sug'urta necha foiz? (faqat raqam kiriting, masalan: 0.7)")
    await state.set_state(Flow.insurance)


@dp.callback_query(F.data == "manual_start")
async def manual_start(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(model="Qo'lda kiritilgan avtomobil", position=None)
    await callback.message.edit_text("✏️ Avtomobil narxini kiriting (so'mda, masalan: 200000000):")
    await state.set_state(Flow.manual_price)
    await callback.answer()


# ============================================================
# QO'LDA KIRITISH OQIMI
# ============================================================

@dp.message(Flow.manual_price)
async def manual_price_handler(message: types.Message, state: FSMContext):
    try:
        price = parse_number(message.text)
    except ValueError:
        await message.answer("Iltimos, faqat raqam kiriting.")
        return
    await state.update_data(price=price)
    await message.answer(
        "💵 Boshlang'ich to'lovni kiriting:\n"
        "— 1-2 xonali son = foiz (masalan: 30)\n"
        "— 3+ xonali son = aniq summa (masalan: 50000000)"
    )
    await state.set_state(Flow.manual_down)


@dp.message(Flow.manual_down)
async def manual_down_handler(message: types.Message, state: FSMContext):
    data = await state.get_data()
    try:
        amount, percent = parse_down_payment(message.text, data["price"])
    except ValueError:
        await message.answer("Iltimos, faqat raqam kiriting.")
        return
    loan_amount = data["price"] - amount
    await state.update_data(down_payment=amount, down_percent=percent, loan_amount=loan_amount)
    await message.answer("🏦 Yillik foiz stavkasini kiriting (masalan: 26):")
    await state.set_state(Flow.manual_rate)


@dp.message(Flow.manual_rate)
async def manual_rate_handler(message: types.Message, state: FSMContext):
    try:
        rate = parse_number(message.text)
    except ValueError:
        await message.answer("Iltimos, faqat raqam kiriting.")
        return
    await state.update_data(annual_rate=rate)
    await message.answer("📅 Necha oyga olmoqchisiz? (masalan: 36)")
    await state.set_state(Flow.manual_term)


@dp.message(Flow.manual_term)
async def manual_term_handler(message: types.Message, state: FSMContext):
    try:
        months = int(parse_number(message.text))
    except ValueError:
        await message.answer("Iltimos, faqat butun son kiriting.")
        return
    await state.update_data(months=months)
    await message.answer("🛡 Sug'urta necha foiz? (faqat raqam kiriting, masalan: 0.7)")
    await state.set_state(Flow.insurance)


# ============================================================
# KREDIT OQIMI (Cobalt va Damas/Labo - Kredit)
# ============================================================

@dp.message(Flow.credit_rate)
async def credit_rate_handler(message: types.Message, state: FSMContext):
    try:
        rate = parse_number(message.text)
    except ValueError:
        await message.answer("Iltimos, faqat raqam kiriting.")
        return
    await state.update_data(annual_rate=rate)
    await message.answer("📅 Necha oyga olmoqchisiz? (masalan: 36)")
    await state.set_state(Flow.credit_term)


@dp.message(Flow.credit_term)
async def credit_term_handler(message: types.Message, state: FSMContext):
    try:
        months = int(parse_number(message.text))
    except ValueError:
        await message.answer("Iltimos, faqat butun son kiriting.")
        return
    await state.update_data(months=months)
    await message.answer(
        "💵 Boshlang'ich to'lovni kiriting:\n"
        "— 1-2 xonali son = foiz (masalan: 30)\n"
        "— 3+ xonali son = aniq summa (masalan: 50000000)"
    )
    await state.set_state(Flow.credit_down)


@dp.message(Flow.credit_down)
async def credit_down_handler(message: types.Message, state: FSMContext):
    data = await state.get_data()
    try:
        amount, percent = parse_down_payment(message.text, data["price"])
    except ValueError:
        await message.answer("Iltimos, faqat raqam kiriting.")
        return
    loan_amount = data["price"] - amount
    await state.update_data(down_payment=amount, down_percent=percent, loan_amount=loan_amount)
    await message.answer("🛡 Sug'urta necha foiz? (faqat raqam kiriting, masalan: 0.7)")
    await state.set_state(Flow.insurance)


# ============================================================
# UMUMIY: SUG'URTA, KOMISSIYA, YAKUNIY HISOB-KITOB
# ============================================================

@dp.message(Flow.insurance)
async def insurance_handler(message: types.Message, state: FSMContext):
    try:
        insurance_percent = parse_number(message.text)
    except ValueError:
        await message.answer("Iltimos, faqat raqam kiriting.")
        return
    await state.update_data(insurance_percent=insurance_percent)
    await message.answer("🏢 Firma komissiyasi necha foiz? (faqat raqam kiriting, masalan: 2)")
    await state.set_state(Flow.commission)


@dp.message(Flow.commission)
async def commission_handler(message: types.Message, state: FSMContext):
    try:
        commission_percent = parse_number(message.text)
    except ValueError:
        await message.answer("Iltimos, faqat raqam kiriting.")
        return

    data = await state.get_data()
    model = data["model"]
    position = data.get("position")
    price = data["price"]
    down_payment = data["down_payment"]
    down_percent = data["down_percent"]
    loan_amount = data["loan_amount"]
    months = data["months"]
    annual_rate = data.get("annual_rate")
    insurance_percent = data["insurance_percent"]

    if annual_rate:
        monthly_payment = annuity_payment(loan_amount, annual_rate, months)
    else:
        monthly_payment = loan_amount / months

    total_loan_payment = monthly_payment * months
    overpayment = total_loan_payment - loan_amount

    years = math.ceil(months / 12)
    insurance_total = loan_amount * 1.25 * insurance_percent / 100 * years
    commission_total = price * commission_percent / 100

    initial_total = down_payment + insurance_total + commission_total
    grand_total = initial_total + total_loan_payment

    await state.update_data(
        commission_percent=commission_percent,
        final_monthly_payment=monthly_payment,
        final_annual_rate=annual_rate or 0,
    )

    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[[
            types.InlineKeyboardButton(text="📷 To'liq jadval (rasm)", callback_data="show_schedule_img")
        ]]
    )

    position_line = f" {position}" if position else ""
    rate_line = f"🏦 Yillik foiz: {annual_rate}%\n" if annual_rate else ""
    overpay_line = f"📈 Foiz hisobiga ortiqcha to'lov: {overpayment:,.0f} so'm\n\n" if annual_rate else "\n"

    await message.answer(
        f"📊 Yakuniy hisob-kitob\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🚗 {model}{position_line}\n"
        f"💰 Narxi: {price:,.0f} so'm\n"
        f"📅 Muddat: {months} oy\n"
        f"{rate_line}\n"
        f"💵 Boshlang'ich to'lov ({down_percent:.0f}%): {down_payment:,.0f} so'm\n"
        f"🛡 Sug'urta ({insurance_percent}%/yil, {years} yil): {insurance_total:,.0f} so'm\n"
        f"🏢 Komissiya ({commission_percent}%): {commission_total:,.0f} so'm\n"
        f"➡️ Boshida to'lanadigan jami: {initial_total:,.0f} so'm\n\n"
        f"📦 Kredit summasi: {loan_amount:,.0f} so'm\n"
        f"💳 Oylik to'lov: {monthly_payment:,.0f} so'm\n"
        f"{overpay_line}"
        f"🔚 JAMI TO'LANADIGAN SUMMA: {grand_total:,.0f} so'm\n\n"
        f"Yana hisoblash uchun /start ni bosing.",
        reply_markup=keyboard,
    )


@dp.callback_query(F.data == "show_schedule_img")
async def show_schedule_img(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if "loan_amount" not in data:
        await callback.answer("Avval /start orqali yangi hisoblash boshlang.", show_alert=True)
        return
    await callback.answer()

    buf = generate_schedule_image(
        model=data["model"],
        position=data.get("position"),
        price=data["price"],
        loan_amount=data["loan_amount"],
        annual_rate=data.get("final_annual_rate", 0),
        monthly_payment=data["final_monthly_payment"],
        months=data["months"],
    )
    photo = types.BufferedInputFile(buf.read(), filename="jadval.png")
    await callback.message.answer_photo(photo, caption="📋 To'liq to'lov jadvali")


# ============================================================
# WEBHOOK SOZLAMASI
# ============================================================

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
