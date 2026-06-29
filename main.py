import os
import math
import logging
from io import BytesIO

from aiohttp import web

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import (
    SimpleRequestHandler,
    setup_application,
)

from PIL import Image, ImageDraw, ImageFont


logging.basicConfig(level=logging.INFO)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
WEBHOOK_HOST = os.environ["WEBHOOK_HOST"]
WEBHOOK_PATH = f"/webhook/{TELEGRAM_TOKEN}"
PORT = int(os.environ.get("PORT", 10000))

bot = Bot(TELEGRAM_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# ==========================================================
# MA'LUMOTLAR
# ==========================================================

CARS = {

    "TRACKER-2": {

        "kind": "installment",

        "positions": {

            "LS PLUS AT":220_951_000,

            "LTZ TURBO AT":244_108_840,

            "PREMIER TURBO AT":272_656_160,

            "REDLINE TURBO AT":282_474_080,

        }

    },

    "ONIX":{

        "kind":"installment",

        "positions":{

            "3 LT MT":184_750_000,

            "LTZ TURBO AT":199_899_000,

            "PREMIER 2 TURBO AT":221_640_160,

            "REDLINE TURBO AT":230_474_000,

        }

    },

    "COBALT":{

        "kind":"credit",

        "positions":{

            "STYLE MCM":156_100_000,

            "MIDNIGHT MCM":165_200_000,

        }

    },

    "DAMAS":{

        "kind":"both",

        "price":96_932_000,

    },

    "LABO":{

        "kind":"both",

        "price":96_370_000,

    },

    "QO'LDA KIRITISH":{

        "kind":"manual",

    }

}


DOWN_PERCENTS=[25,30,40,50]


# ==========================================================
# STATES
# ==========================================================

class Form(StatesGroup):

    choose_sale=State()

    custom_price=State()

    payment=State()

    annual=State()

    months=State()

    insurance=State()

    commission=State()


# ==========================================================
# FUNCTIONS
# ==========================================================

def parse_number(text):

    return float(

        text.replace(" ","")

        .replace(",", ".")

        .replace("%","")

    )


def money(x):

    return f"{x:,.0f}".replace(","," ")


def tracker_month(percent,position):

    if percent==25:
        return 30

    if percent==30:
        return 33

    if percent==40:

        if position=="LS PLUS AT":
            return 44

        return 41

    if percent==50:
        return 54


def onix_month(percent):

    if percent==25:
        return 30

    if percent==30:
        return 33

    if percent==40:
        return 41

    if percent==50:
        return 54


def mini_month(percent):

    if percent==25:
        return 12

    if percent==30:
        return 15

    if percent==40:
        return 19

    if percent==50:
        return 26


def insurance_amount(balance,percent,months):

    return (

        balance

        *1.25

        *(percent/100)

        *(months/12)

    )


def commission_amount(price,percent):

    return price*percent/100


def annuity(summa,annual,months):

    if annual==0:

        return summa/months

    r=annual/12/100

    k=(r*(1+r)**months)/((1+r)**months-1)

    return summa*k


@dp.message(CommandStart())
async def start(message:types.Message,state:FSMContext):

    await state.clear()

    keyboard=types.InlineKeyboardMarkup(

        inline_keyboard=[

            [
                types.InlineKeyboardButton(
                    text="🚗 TRACKER-2",
                    callback_data="model:TRACKER-2"
                )
            ],

            [
                types.InlineKeyboardButton(
                    text="🚗 ONIX",
                    callback_data="model:ONIX"
                )
            ],

            [
                types.InlineKeyboardButton(
                    text="🚗 COBALT",
                    callback_data="model:COBALT"
                )
            ],

            [
                types.InlineKeyboardButton(
                    text="🚗 DAMAS",
                    callback_data="model:DAMAS"
                )
            ],

            [
                types.InlineKeyboardButton(
                    text="🚗 LABO",
                    callback_data="model:LABO"
                )
            ],

            [
                types.InlineKeyboardButton(
                    text="📝 Qo'lda kiritish",
                    callback_data="model:QO'LDA KIRITISH"
                )
            ],

        ]

    )

    await message.answer(

        "🚗 Avtomobilni tanlang.",

        reply_markup=keyboard

) 
# ==========================================================
# MODEL TANLASH
# ==========================================================

@dp.callback_query(F.data.startswith("model:"))
async def choose_model(callback: types.CallbackQuery, state: FSMContext):

    model = callback.data.split(":")[1]

    await state.update_data(model=model)

    car = CARS[model]

    if car["kind"] == "manual":

        await callback.message.edit_text(
            "💰 Avtomobil narxini kiriting."
        )

        await state.set_state(Form.custom_price)

        await callback.answer()

        return

    if "positions" in car:

        keyboard = types.InlineKeyboardMarkup(

            inline_keyboard=[

                [

                    types.InlineKeyboardButton(

                        text=f"{name} — {money(price)}",

                        callback_data=f"position:{i}"

                    )

                ]

                for i, (name, price) in enumerate(
                    car["positions"].items()
                )

            ]

        )

        await callback.message.edit_text(

            f"🚗 {model}\n\n"
            "Pozitsiyani tanlang.",

            reply_markup=keyboard

        )

        await callback.answer()

        return

    await state.update_data(

        position=model,

        price=car["price"]

    )

    keyboard = types.InlineKeyboardMarkup(

        inline_keyboard=[

            [

                types.InlineKeyboardButton(

                    text="💳 Rasrochka",

                    callback_data="sale:installment"

                )

            ],

            [

                types.InlineKeyboardButton(

                    text="🏦 Kredit",

                    callback_data="sale:credit"

                )

            ]

        ]

    )

    await callback.message.edit_text(

        f"🚗 {model}\n"
        f"💰 {money(car['price'])} so'm\n\n"
        "Hisoblash turini tanlang.",

        reply_markup=keyboard

    )

    await callback.answer()


# ==========================================================
# POZITSIYA TANLASH
# ==========================================================

@dp.callback_query(F.data.startswith("position:"))
async def choose_position(callback: types.CallbackQuery, state: FSMContext):

    index = int(callback.data.split(":")[1])

    data = await state.get_data()

    model = data["model"]

    items = list(
        CARS[model]["positions"].items()
    )

    position, price = items[index]

    await state.update_data(

        position=position,

        price=price

    )

    kind = CARS[model]["kind"]

    if kind == "installment":

        keyboard = types.InlineKeyboardMarkup(

            inline_keyboard=[

                [

                    types.InlineKeyboardButton(

                        text=f"{p}%",

                        callback_data=f"percent:{p}"

                    )

                ]

                for p in DOWN_PERCENTS

            ]

        )

        await callback.message.edit_text(

            f"🚗 {model}\n"
            f"{position}\n\n"
            f"💰 {money(price)} so'm\n\n"
            "Boshlang'ich to'lov foizini tanlang.",

            reply_markup=keyboard

        )

        await callback.answer()

        return

    await callback.message.edit_text(

        f"🚗 {model}\n"
        f"{position}\n\n"
        f"💰 {money(price)} so'm\n\n"

        "Boshlang'ich to'lovni kiriting.\n\n"

        "Misol:\n"

        "30 → 30%\n"

        "70000000 → 70 000 000"

    )

    await state.set_state(Form.payment)

    await callback.answer()


# ==========================================================
# DAMAS / LABO
# ==========================================================

@dp.callback_query(F.data.startswith("sale:"))
async def choose_sale(callback: types.CallbackQuery, state: FSMContext):

    sale = callback.data.split(":")[1]

    await state.update_data(

        sale=sale

    )

    data = await state.get_data()

    model = data["model"]

    price = data["price"]

    if sale == "installment":

        keyboard = types.InlineKeyboardMarkup(

            inline_keyboard=[

                [

                    types.InlineKeyboardButton(

                        text=f"{p}%",

                        callback_data=f"percent:{p}"

                    )

                ]

                for p in DOWN_PERCENTS

            ]

        )

        await callback.message.edit_text(

            f"🚗 {model}\n"
            f"💰 {money(price)} so'm\n\n"
            "Boshlang'ich to'lov foizini tanlang.",

            reply_markup=keyboard

        )

        await callback.answer()

        return

    await callback.message.edit_text(

        f"🚗 {model}\n"
        f"💰 {money(price)} so'm\n\n"

        "Boshlang'ich to'lovni kiriting.\n\n"

        "30 → 30%\n"

        "70000000 → 70 000 000"

    )

    await state.set_state(Form.payment)

    await callback.answer()
    # ==========================================================
# RASROCHKA FOIZ TANLASH
# ==========================================================

@dp.callback_query(F.data.startswith("percent:"))
async def choose_percent(callback: types.CallbackQuery, state: FSMContext):

    percent = int(callback.data.split(":")[1])

    data = await state.get_data()

    model = data["model"]
    position = data["position"]
    price = data["price"]

    payment_sum = price * percent / 100

    if model == "TRACKER-2":

        months = tracker_month(
            percent,
            position
        )

    elif model == "ONIX":

        months = onix_month(
            percent
        )

    else:

        months = mini_month(
            percent
        )

    await state.update_data(

        payment_percent=percent,

        payment_sum=payment_sum,

        annual=0,

        months=months,

    )

    await callback.message.edit_text(

        f"🚗 {model}\n"
        f"📌 {position}\n\n"

        f"💰 Narxi: {money(price)} so'm\n"

        f"💵 Boshlang'ich to'lov: {money(payment_sum)} so'm\n"

        f"📈 Foiz: {percent}%\n"

        f"📅 Muddat: {months} oy\n\n"

        "🛡 Sug'urta foizini kiriting.\n"
        "Masalan: 0.7"

    )

    await state.set_state(Form.insurance)

    await callback.answer()


# ==========================================================
# QO'LDA NARX KIRITISH
# ==========================================================

@dp.message(Form.custom_price)
async def custom_price(message: types.Message, state: FSMContext):

    try:

        price = parse_number(message.text)

    except:

        await message.answer(
            "Narxni to'g'ri kiriting."
        )

        return

    await state.update_data(

        price=price,

        position="",

        sale="credit",

    )

    await message.answer(

        "Boshlang'ich to'lovni kiriting.\n\n"

        "30 → 30%\n"

        "70000000 → 70 000 000"

    )

    await state.set_state(Form.payment)


# ==========================================================
# BOSHLANG'ICH TO'LOV
# ==========================================================

@dp.message(Form.payment)
async def payment_handler(message: types.Message, state: FSMContext):

    try:

        value = parse_number(message.text)

    except:

        await message.answer(
            "Raqam kiriting."
        )

        return

    data = await state.get_data()

    price = data["price"]

    if value < 100:

        payment_percent = value

        payment_sum = (

            price

            * payment_percent

            / 100

        )

    else:

        payment_sum = value

        payment_percent = (

            payment_sum

            / price

            * 100

        )

    await state.update_data(

        payment_sum=payment_sum,

        payment_percent=payment_percent,

    )

    await message.answer(

        "🏦 Bank foiz stavkasini kiriting.\n"
        "Masalan: 28"

    )

    await state.set_state(Form.annual)
    # ==========================================================
# BANK FOIZI
# ==========================================================

@dp.message(Form.annual)
async def annual_handler(message: types.Message, state: FSMContext):

    try:

        annual = parse_number(message.text)

    except:

        await message.answer(
            "Foizni to'g'ri kiriting."
        )

        return

    await state.update_data(

        annual=annual

    )

    await message.answer(

        "📅 Kredit muddatini oyda kiriting."

    )

    await state.set_state(Form.months)


# ==========================================================
# MUDDAT
# ==========================================================

@dp.message(Form.months)
async def months_handler(message: types.Message, state: FSMContext):

    try:

        months = int(parse_number(message.text))

    except:

        await message.answer(
            "Oy sonini kiriting."
        )

        return

    await state.update_data(

        months=months

    )

    await message.answer(

        "🛡 Sug'urta foizini kiriting.\n"
        "Masalan: 0.7"

    )

    await state.set_state(Form.insurance)


# ==========================================================
# SUG'URTA
# ==========================================================

@dp.message(Form.insurance)
async def insurance_handler(message: types.Message, state: FSMContext):

    try:

        insurance = parse_number(message.text)

    except:

        await message.answer(
            "Sug'urta foizini kiriting."
        )

        return

    await state.update_data(

        insurance=insurance

    )

    await message.answer(

        "🏢 Komissiya foizini kiriting.\n"
        "Masalan: 2"

    )

    await state.set_state(Form.commission)
    # ==========================================================
# KOMISSIYA VA YAKUNIY HISOB
# ==========================================================

@dp.message(Form.commission)
async def commission_handler(message: types.Message, state: FSMContext):

    try:

        commission = parse_number(message.text)

    except:

        await message.answer(
            "Komissiya foizini kiriting."
        )

        return

    data = await state.get_data()

    model = data["model"]
    position = data["position"]
    price = data["price"]

    payment_sum = data["payment_sum"]
    payment_percent = data["payment_percent"]

    annual = data["annual"]
    months = data["months"]

    insurance_percent = data["insurance"]

    balance = price - payment_sum

    insurance_total = insurance_amount(

        balance,

        insurance_percent,

        months

    )

    commission_total = commission_amount(

        price,

        commission

    )

    # =====================================================
    # SUMMADA KIRITILGAN BOSHLANG'ICH TO'LOVNI
    # SUG'URTA VA KOMISSIYADAN TOZALASH
    # =====================================================

    if payment_sum > 99:

        payment_sum = (

            payment_sum

            - insurance_total

            - commission_total

        )

        if payment_sum < 0:

            payment_sum = 0

        payment_percent = round(

            payment_sum

            / price

            * 100

        )

        payment_sum = (

            price

            * payment_percent

            / 100

        )

        balance = price - payment_sum

        insurance_total = insurance_amount(

            balance,

            insurance_percent,

            months

        )

    # =====================================================

    monthly = annuity(

        balance,

        annual,

        months

    )

    total_credit = monthly * months

    interest_total = total_credit - balance

    final_total = (

        payment_sum

        + balance

        + interest_total

    )

    first_payment = (

        payment_sum

        + insurance_total

        + commission_total

    )

    report = (

        "📊 HISOB-KITOB\n\n"

        f"🚗 Avto: {model}\n"

        f"📌 Pozitsiya: {position}\n"

        f"💰 Avto narxi: {money(price)} so'm\n"

        f"📅 Muddat: {months} oy\n\n"

        f"💵 Boshlang'ich to'lov: {money(payment_sum)} so'm\n"

        f"📈 Boshlang'ich foiz: {payment_percent:.0f}%\n"

        f"🏦 Bank stavkasi: {annual:.2f}%\n"

        f"🛡 Sug'urta: {money(insurance_total)} so'm\n"

        f"🏢 Komissiya: {money(commission_total)} so'm\n"

        f"💸 Boshida jami: {money(first_payment)} so'm\n\n"

        f"📦 Kredit summasi: {money(balance)} so'm\n"

        f"💳 Oylik to'lov: {money(monthly)} so'm\n"

        f"📈 Foiz hisobiga ortiqcha to'lov: {money(interest_total)} so'm\n\n"

        f"✅ Yakuniy jami:\n"

        f"{money(final_total)} so'm\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━\n"

        "MS AUTOCREDIT Sabrina\n"

        "+998908060889"

    )

    await message.answer(report)

    await state.clear()
