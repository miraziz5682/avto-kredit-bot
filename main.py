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

DOWN_PERCENTS = [25, 30, 40, 50]


def nearest_tier(percent: float) -> int:
    """Kiritilgan foizni pastki (mos) tayyor tugma qiymatiga moslaydi.
    Masalan 35% -> 30%, 47% -> 40%. 25% dan kichik bo'lsa 25% olinadi."""
    tiers = sorted(DOWN_PERCENTS)
    chosen = tiers[0]
    for t in tiers:
        if percent >= t:
            chosen = t
    return chosen


# ============================================================
# MUDDAT (OY) JADVALLARI - har bank, har model uchun
# ============================================================

# ---- KAPITALBANK ----
def kb_months_tracker(percent, position):
    table = {25: 30, 30: 33, 50: 54}
    if percent in table:
        return table[percent]
    if percent == 40:
        return 44 if position == "LS PLUS AT" else 41
    return None


def kb_months_onix(percent, position=None):
    return {25: 30, 30: 33, 40: 41, 50: 54}.get(percent)


def kb_months_damas_labo(percent, position=None):
    return {25: 12, 30: 15, 40: 19, 50: 26}.get(percent)


# ---- INFINBANK ----
def inf_months_tracker_onix(percent, position=None):
    return {25: 36, 30: 40, 40: 52, 50: 60}.get(percent)


def inf_months_damas(percent, position=None):
    return {25: 14, 30: 17, 40: 21, 50: 28}.get(percent)


def inf_months_labo(percent, position=None):
    return {25: 12, 30: 14, 40: 18, 50: 23}.get(percent)


def inf_months_captiva(percent, position=None):
    return {25: 14, 30: 17, 40: 21, 50: 28}.get(percent)


# ============================================================
# AVTOMOBIL KATALOGI
# ============================================================
# Har bir model: positions (yoki price, agar pozitsiyasiz),
# banks: {"Kapitalbank": months_fn yoki None, "Infinbank": months_fn yoki None}
# "mode": "bank_choice" - bank tanlanadi, "credit_manual" - Cobalt kabi qo'lda

CARS = {
    "TRACKER-2": {
        "positions": {
            "LS PLUS AT": 220_951_000,
            "LTZ TURBO AT": 244_108_840,
            "PREMIER TURBO AT": 272_656_160,
            "REDLINE TURBO AT": 282_474_080,
        },
        "mode": "bank_choice",
        "banks": {
            "Kapitalbank": kb_months_tracker,
            "Infinbank": inf_months_tracker_onix,
        },
    },
    "ONIX": {
        "positions": {
            "3 LT MT": 184_750_000,
            "LTZ TURBO AT": 199_899_000,
            "PREMIER 2 TURBO AT": 221_640_160,
            "REDLINE TURBO AT": 230_474_000,
        },
        "mode": "bank_choice",
        "banks": {
            "Kapitalbank": kb_months_onix,
            "Infinbank": inf_months_tracker_onix,
        },
    },
    "DAMAS": {
        "positions": {
            "STAYL": 96_932_000,
            "VAN": 93_170_000,
            "KOMBI": 96_449_000,
        },
        "mode": "bank_choice",
        "banks": {
            "Kapitalbank": kb_months_damas_labo,
            "Infinbank": inf_months_damas,
        },
    },
    "LABO": {
        "price": 96_370_000,
        "mode": "bank_choice",
        "banks": {
            "Kapitalbank": kb_months_damas_labo,
            "Infinbank": inf_months_labo,
        },
    },
    "COBALT": {
        "positions": {
            "Style MCM": 156_100_000,
            "Midnight MCM": 165_200_000,
        },
        "mode": "credit_manual",
    },
    "CAPTIVA 5": {
        "price": 349_900_000,
        "mode": "bank_choice",
        "banks": {
            "Infinbank": inf_months_captiva,
        },
    },
}


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
        is_sum = False
    else:
        amount = value
        percent = amount / price * 100
        is_sum = True
    return amount, percent, is_sum


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


SIGNATURE = "\n\n━━━━━━━━━━━━━━━━━━\nMS AUTOCREDIT Sabrina\n+998908060889"


# ============================================================
# KLAVIATURALAR
# ============================================================

def build_main_menu_kb():
    rows = [[types.InlineKeyboardButton(text=model, callback_data=f"car_model:{model}")] for model in CARS]
    rows.append([types.InlineKeyboardButton(text="✏️ Qo'lda kiritish", callback_data="manual_start")])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def build_bank_kb(model):
    banks = CARS[model]["banks"]
    rows = [[types.InlineKeyboardButton(text=bank, callback_data=f"bank:{model}:{bank}")] for bank in banks]
    rows.append([types.InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back:main")])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def build_positions_kb(model, bank):
    rows = [
        [types.InlineKeyboardButton(text=f"{pos} — {price:,.0f} so'm", callback_data=f"pos:{model}:{bank}:{i}")]
        for i, (pos, price) in enumerate(CARS[model]["positions"].items())
    ]
    rows.append([types.InlineKeyboardButton(text="⬅️ Orqaga", callback_data=f"back:bank:{model}")])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def build_percent_kb(model, bank, back_data):
    rows = [[types.InlineKeyboardButton(text=f"{p}%", callback_data=f"pct:{model}:{bank}:{p}")] for p in DOWN_PERCENTS]
    rows.append([types.InlineKeyboardButton(text="✏️ Boshqa", callback_data=f"pctcustom:{model}:{bank}")])
    rows.append([types.InlineKeyboardButton(text="⬅️ Orqaga", callback_data=back_data)])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


# ============================================================
# HOLATLAR
# ============================================================

class Flow(StatesGroup):
    manual_price = State()
    manual_down = State()
    manual_rate = State()
    manual_term = State()
    credit_rate = State()
    credit_term = State()
    credit_down = State()
    custom_down = State()
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
    await state.update_data(model=model)

    if info["mode"] == "credit_manual":
        await callback.message.edit_text(
            f"🚘 {model} uchun pozitsiyani tanlang:", reply_markup=build_positions_kb_credit(model)
        )
    else:
        banks = info["banks"]
        if len(banks) == 1:
            # Faqat bitta bank mavjud (masalan Captiva -> Infinbank) - avtomatik tanlanadi
            bank = list(banks.keys())[0]
            await proceed_after_bank(callback, state, model, bank)
        else:
            await callback.message.edit_text(
                f"🚘 {model}\n\n🏦 Bankni tanlang:", reply_markup=build_bank_kb(model)
            )
    await callback.answer()


def build_positions_kb_credit(model):
    rows = [
        [types.InlineKeyboardButton(text=f"{pos} — {price:,.0f} so'm", callback_data=f"poscredit:{model}:{i}")]
        for i, (pos, price) in enumerate(CARS[model]["positions"].items())
    ]
    rows.append([types.InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back:main")])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


@dp.callback_query(F.data.startswith("poscredit:"))
async def position_credit_selected(callback: types.CallbackQuery, state: FSMContext):
    _, model, idx = callback.data.split(":")
    idx = int(idx)
    positions = list(CARS[model]["positions"].items())
    position, price = positions[idx]
    await state.update_data(model=model, position=position, price=price)

    await callback.message.edit_text(
        f"✅ {model} {position}\n💰 Narxi: {price:,.0f} so'm\n\n"
        f"🏦 Yillik foiz stavkasini kiriting (masalan: 26):"
    )
    await state.set_state(Flow.credit_rate)
    await callback.answer()


@dp.callback_query(F.data.startswith("back:bank:"))
async def back_to_bank(callback: types.CallbackQuery, state: FSMContext):
    model = callback.data.split(":", 2)[2]
    await callback.message.edit_text(
        f"🚘 {model}\n\n🏦 Bankni tanlang:", reply_markup=build_bank_kb(model)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("bank:"))
async def bank_selected(callback: types.CallbackQuery, state: FSMContext):
    _, model, bank = callback.data.split(":")
    await proceed_after_bank(callback, state, model, bank)
    await callback.answer()


async def proceed_after_bank(callback, state, model, bank):
    info = CARS[model]
    await state.update_data(model=model, bank=bank)

    if "positions" in info:
        await callback.message.edit_text(
            f"🚘 {model} ({bank}) uchun pozitsiyani tanlang:",
            reply_markup=build_positions_kb(model, bank),
        )
    else:
        price = info["price"]
        await state.update_data(price=price, position=None)
        await callback.message.edit_text(
            f"🚐 {model} ({bank})\n💰 Narxi: {price:,.0f} so'm\n\nBoshlang'ich to'lov necha foiz bo'lsin?",
            reply_markup=build_percent_kb(model, bank, "back:main"),
        )


@dp.callback_query(F.data.startswith("pos:"))
async def position_selected(callback: types.CallbackQuery, state: FSMContext):
    _, model, bank, idx = callback.data.split(":")
    idx = int(idx)
    positions = list(CARS[model]["positions"].items())
    position, price = positions[idx]
    await state.update_data(model=model, bank=bank, position=position, price=price)

    await callback.message.edit_text(
        f"✅ {model} {position} ({bank})\n💰 Narxi: {price:,.0f} so'm\n\nBoshlang'ich to'lov necha foiz bo'lsin?",
        reply_markup=build_percent_kb(model, bank, f"back:bank:{model}"),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("pct:"))
async def percent_selected(callback: types.CallbackQuery, state: FSMContext):
    _, model, bank, percent = callback.data.split(":")
    percent = int(percent)
    data = await state.get_data()
    price = data["price"]
    position = data.get("position")

    months_fn = CARS[model]["banks"][bank]
    months = months_fn(percent, position)
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


@dp.callback_query(F.data.startswith("pctcustom:"))
async def percent_custom(callback: types.CallbackQuery, state: FSMContext):
    _, model, bank = callback.data.split(":")
    await state.update_data(model=model, bank=bank)
    await callback.message.edit_text(
        "✏️ Boshlang'ich to'lovni kiriting:\n"
        "— 1-2 xonali son = foiz (masalan: 35)\n"
        "— 3+ xonali son = aniq summa (masalan: 70000000)"
    )
    await state.set_state(Flow.custom_down)
    await callback.answer()


@dp.message(Flow.custom_down)
async def custom_down_handler(message: types.Message, state: FSMContext):
    data = await state.get_data()
    try:
        amount, percent, is_sum = parse_down_payment(message.text, data["price"])
    except ValueError:
        await message.answer("Iltimos, faqat raqam kiriting.")
        return

    if not is_sum and (percent < 25 or percent > 100):
        await message.answer(
            "❌ Boshlang'ich to'lov kamida 25%, ko'pi bilan 100% bo'lishi kerak.\n"
            "Iltimos, qaytadan kiriting:"
        )
        return

    await state.update_data(
        down_payment=amount, down_percent=percent, down_is_sum=is_sum, custom_entry=True
    )
    await message.answer("🛡 Sug'urta necha foiz? (faqat raqam kiriting, masalan: 0.7)")
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
        amount, percent, is_sum = parse_down_payment(message.text, data["price"])
    except ValueError:
        await message.answer("Iltimos, faqat raqam kiriting.")
        return
    loan_amount = data["price"] - amount
    await state.update_data(
        down_payment=amount, down_percent=percent, loan_amount=loan_amount, down_is_sum=is_sum
    )
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
# KREDIT OQIMI (Cobalt)
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
        amount, percent, is_sum = parse_down_payment(message.text, data["price"])
    except ValueError:
        await message.answer("Iltimos, faqat raqam kiriting.")
        return
    loan_amount = data["price"] - amount
    await state.update_data(
        down_payment=amount, down_percent=percent, loan_amount=loan_amount, down_is_sum=is_sum
    )
    await message.answer("🛡 Sug'urta necha foiz? (faqat raqam kiriting, masalan: 0.7)")
    await state.set_state(Flow.insurance)


# ============================================================
# INFINBANK UCHUN ODDIY NATIJA (sug'urta/komissiyasiz)
# ============================================================

async def show_simple_result(message_obj, state: FSMContext):
    data = await state.get_data()
    model = data["model"]
    bank = data.get("bank", "")
    position = data.get("position")
    price = data["price"]
    down_payment = data["down_payment"]
    down_percent = data["down_percent"]
    loan_amount = data["loan_amount"]
    months = data["months"]

    monthly_payment = loan_amount / months
    final_total = down_payment + loan_amount  # foizsiz, xarajatlarsiz

    await state.update_data(
        final_monthly_payment=monthly_payment,
        final_annual_rate=0,
        final_loan_amount=loan_amount,
        final_down_payment=down_payment,
        final_down_percent=down_percent,
    )

    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[[
            types.InlineKeyboardButton(text="📷 To'liq jadval (rasm)", callback_data="show_schedule_img")
        ]]
    )

    position_line = f" {position}" if position else ""

    await message_obj.answer(
        f"📊 Yakuniy hisob-kitob ({bank})\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🚗 {model}{position_line}\n"
        f"💰 Narxi: {price:,.0f} so'm\n"
        f"📅 Muddat: {months} oy\n\n"
        f"💵 Boshlang'ich to'lov ({down_percent:.0f}%): {down_payment:,.0f} so'm\n"
        f"📦 Kredit summasi: {loan_amount:,.0f} so'm\n"
        f"💳 Oylik to'lov: {monthly_payment:,.0f} so'm\n\n"
        f"🔚 YAKUNIY TO'LANADIGAN JAMI SUMMA: {final_total:,.0f} so'm\n\n"
        f"Yana hisoblash uchun /start ni bosing."
        f"{SIGNATURE}",
        reply_markup=keyboard,
    )


# ============================================================
# UMUMIY: SUG'URTA, KOMISSIYA, YAKUNIY HISOB-KITOB (Kapitalbank, Cobalt, Qo'lda)
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
    bank = data.get("bank", "")
    position = data.get("position")
    price = data["price"]
    annual_rate = data.get("annual_rate")
    insurance_percent = data["insurance_percent"]

    if data.get("custom_entry") and bank:
        # Erkin (Boshqa) summa/foiz kiritilgan - muddat tier bo'yicha aniqlanadi
        months_fn = CARS[model]["banks"][bank]
        is_sum = data.get("down_is_sum", False)
        if is_sum:
            raw_sum = data["down_payment"]
            raw_percent_guess = raw_sum / price * 100
            tier_guess = nearest_tier(raw_percent_guess)
            months_guess = months_fn(tier_guess, position) or 12
            years_guess = math.ceil(months_guess / 12)
            loan_amount_est = price - raw_sum
            insurance_est = loan_amount_est * 1.25 * insurance_percent / 100 * years_guess
            commission_total = price * commission_percent / 100
            net = raw_sum - insurance_est - commission_total
            down_percent = round(net / price * 100)
        else:
            down_percent = round(data["down_percent"])
            commission_total = price * commission_percent / 100

        if down_percent < 25 or down_percent > 100:
            await message.answer(
                f"❌ Xarajatlar ayirilgandan keyin boshlang'ich to'lov {down_percent}% chiqdi.\n"
                f"Bu kamida 25%, ko'pi bilan 100% bo'lishi kerak.\n\n"
                f"Iltimos, boshlang'ich to'lov summasini/foizini qaytadan kiriting:"
            )
            await state.set_state(Flow.custom_down)
            return

        tier = nearest_tier(down_percent)
        months = months_fn(tier, position) or 12
        down_payment = price * down_percent / 100
        loan_amount = price - down_payment
        years = math.ceil(months / 12)
        insurance_total = loan_amount * 1.25 * insurance_percent / 100 * years
        commission_total = price * commission_percent / 100
    else:
        months = data["months"]
        years = math.ceil(months / 12)

        if data.get("down_is_sum"):
            raw_sum = data["down_payment"]
            loan_amount_est = data["loan_amount"]
            insurance_est = loan_amount_est * 1.25 * insurance_percent / 100 * years
            commission_total = price * commission_percent / 100
            net = raw_sum - insurance_est - commission_total
            down_percent = round(net / price * 100)
            down_payment = price * down_percent / 100
            loan_amount = price - down_payment
            insurance_total = loan_amount * 1.25 * insurance_percent / 100 * years
        else:
            down_payment = data["down_payment"]
            down_percent = data["down_percent"]
            loan_amount = data["loan_amount"]
            insurance_total = loan_amount * 1.25 * insurance_percent / 100 * years
            commission_total = price * commission_percent / 100

    if annual_rate:
        monthly_payment = annuity_payment(loan_amount, annual_rate, months)
    else:
        monthly_payment = loan_amount / months

    total_loan_payment = monthly_payment * months
    overpayment = total_loan_payment - loan_amount

    initial_total = down_payment + insurance_total + commission_total
    final_total = down_payment + total_loan_payment

    await state.update_data(
        commission_percent=commission_percent,
        final_monthly_payment=monthly_payment,
        final_annual_rate=annual_rate or 0,
        final_loan_amount=loan_amount,
        final_down_payment=down_payment,
        final_down_percent=down_percent,
    )

    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[[
            types.InlineKeyboardButton(text="📷 To'liq jadval (rasm)", callback_data="show_schedule_img")
        ]]
    )

    position_line = f" {position}" if position else ""
    bank_line = f" ({bank})" if bank else ""
    rate_line = f"🏦 Yillik foiz: {annual_rate}%\n" if annual_rate else ""
    overpay_line = f"📈 Foiz hisobiga ortiqcha to'lov: {overpayment:,.0f} so'm\n\n" if annual_rate else "\n"

    await message.answer(
        f"📊 Yakuniy hisob-kitob{bank_line}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🚗 {model}{position_line}\n"
        f"💰 Narxi: {price:,.0f} so'm\n"
        f"📅 Muddat: {months} oy\n"
        f"{rate_line}\n"
        f"💵 Boshlang'ich to'lov ({down_percent:.0f}%): {down_payment:,.0f} so'm\n"
        f"🛡 Sug'urta ({insurance_percent}%/yil, {years} yil): {insurance_total:,.0f} so'm\n"
        f"🏢 Komissiya ({commission_percent}%): {commission_total:,.0f} so'm\n"
        f"➡️ Boshida to'lanadigan jami (xarajatlar bilan): {initial_total:,.0f} so'm\n\n"
        f"📦 Kredit summasi: {loan_amount:,.0f} so'm\n"
        f"💳 Oylik to'lov: {monthly_payment:,.0f} so'm\n"
        f"{overpay_line}"
        f"🔚 YAKUNIY TO'LANADIGAN JAMI SUMMA: {final_total:,.0f} so'm\n\n"
        f"Yana hisoblash uchun /start ni bosing."
        f"{SIGNATURE}",
        reply_markup=keyboard,
    )


@dp.callback_query(F.data == "show_schedule_img")
async def show_schedule_img(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if "final_loan_amount" not in data:
        await callback.answer("Avval /start orqali yangi hisoblash boshlang.", show_alert=True)
        return
    await callback.answer()

    buf = generate_schedule_image(
        model=data["model"],
        position=data.get("position"),
        price=data["price"],
        loan_amount=data["final_loan_amount"],
        annual_rate=data.get("final_annual_rate", 0),
        monthly_payment=data["final_monthly_payment"],
        months=data["months"],
    )
    photo = types.BufferedInputFile(buf.read(), filename="jadval.png")
    await callback.message.answer_photo(photo, caption="📋 To'liq to'lov jadvali")


# ============================================================
# WEB APP: NATIJANI TELEGRAM'GA YUBORISH
# ============================================================

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}


async def send_result_options(request):
    return web.Response(headers=CORS_HEADERS)


async def send_result(request):
    try:
        data = await request.json()
        chat_id = int(data["chat_id"])
        text = data["text"]
        await bot.send_message(chat_id=chat_id, text=text)
        return web.json_response({"ok": True}, headers=CORS_HEADERS)
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400, headers=CORS_HEADERS)


# ============================================================
# WEBHOOK SOZLAMASI
# ============================================================

async def on_startup(app: web.Application):
    await bot.set_webhook(f"{WEBHOOK_HOST}{WEBHOOK_PATH}")


async def health_check(request):
    return web.json_response({"status": "ok"})


def main():
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_post("/api/send-result", send_result)
    app.router.add_options("/api/send-result", send_result_options)
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    app.on_startup.append(on_startup)
    web.run_app(app, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()
