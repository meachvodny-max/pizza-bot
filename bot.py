import asyncio
import os
from aiogram import Bot, Dispatcher
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.base import StorageKey
from google import genai

TOKEN = os.environ["TOKEN"]
GEMINI_KEY = os.environ["GEMINI_KEY"]
OPERATOR_ID = int(os.environ["OPERATOR_ID"])


bot = Bot(token=TOKEN)
dp = Dispatcher()

client = genai.Client(api_key=GEMINI_KEY)

# Меню пиццерии
MENU = {
    "маргарита": 450,
    "пепперони": 550,
    "четыре сыра": 600,
    "гавайская": 580,
}


def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Маргарита"), KeyboardButton(text="Пепперони")],
            [KeyboardButton(text="Четыре сыра"), KeyboardButton(text="Гавайская")],
            [KeyboardButton(text="Заказать маргарита"), KeyboardButton(text="Заказать пепперони")],
            [KeyboardButton(text="Связаться с оператором")],
        ],
        resize_keyboard=True
    )


def operator_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Завершить диалог")]],
        resize_keyboard=True
    )


class Order(StatesGroup):
    waiting_for_quantity = State()


class Talk(StatesGroup):
    with_operator = State()


@dp.message(Command("start"))
async def start_command(message: Message):
    await message.answer(
        "Привет! Я бот пиццерии 🍕\n"
        "Выбирай пиццу кнопками или спрашивай — подскажу!\n"
        "Заказать: «заказать <название>». Нужен живой человек — жми кнопку оператора.",
        reply_markup=main_keyboard()
    )


# === ОПЕРАТОР ЗАВЕРШАЕТ (реплай + /close) ===
@dp.message(lambda m: m.from_user.id == OPERATOR_ID and m.reply_to_message and m.text == "/close")
async def operator_close(message: Message):
    replied = message.reply_to_message.text or ""
    if "ID клиента:" not in replied:
        await message.answer("Не вижу id клиента. Ответь /close реплаем на сообщение клиента.")
        return
    client_id = int(replied.split("ID клиента:")[1].split()[0])
    key = StorageKey(bot_id=bot.id, chat_id=client_id, user_id=client_id)
    await dp.storage.set_state(key, None)
    await bot.send_message(client_id, "Оператор завершил диалог. Снова отвечает бот 🤖")
    await message.answer("✅ Диалог завершён.")


# === ОПЕРАТОР ОТВЕЧАЕТ (реплай) ===
@dp.message(lambda m: m.from_user.id == OPERATOR_ID and m.reply_to_message)
async def operator_reply(message: Message):
    replied = message.reply_to_message.text or ""
    if "ID клиента:" not in replied:
        await message.answer("Не вижу id клиента. Ответь реплаем на сообщение клиента.")
        return
    client_id = int(replied.split("ID клиента:")[1].split()[0])
    await bot.send_message(client_id, f"👨‍💼 Оператор:\n{message.text}")
    await message.answer("✅ Отправлено клиенту.")


# === КЛИЕНТ ПРОСИТ ОПЕРАТОРА ===
@dp.message(lambda m: m.text and m.text.lower() in ["оператор", "связаться с оператором"])
async def call_operator(message: Message, state: FSMContext):
    await state.set_state(Talk.with_operator)
    await message.answer(
        "Вы на связи с оператором 👨‍💼\n"
        "Пишите ваш вопрос. Чтобы завершить — нажмите кнопку или напишите: стоп",
        reply_markup=operator_keyboard()
    )
    user = message.from_user
    await bot.send_message(
        OPERATOR_ID,
        f"🔔 Клиент подключился к оператору\n"
        f"Имя: {user.full_name}\nUsername: @{user.username}\nID клиента: {user.id}"
    )


# === СООБЩЕНИЯ КЛИЕНТА В РЕЖИМЕ ОПЕРАТОРА ===
@dp.message(Talk.with_operator)
async def client_in_operator_mode(message: Message, state: FSMContext):
    if message.text and message.text.lower() in ["стоп", "завершить диалог"]:
        await state.clear()
        await message.answer("Диалог с оператором завершён. Снова отвечает бот 🤖", reply_markup=main_keyboard())
        return
    user = message.from_user
    await bot.send_message(
        OPERATOR_ID,
        f"💬 Сообщение от клиента\n"
        f"Имя: {user.full_name}\nUsername: @{user.username}\nID клиента: {user.id}\n\n"
        f"Текст: {message.text}"
    )
    await message.answer("Сообщение передано оператору ✅")


# === ЗАКАЗ ПИЦЦЫ ===
@dp.message(lambda m: m.text and m.text.lower().startswith("заказать"))
async def order_start(message: Message, state: FSMContext):
    parts = message.text.lower().split()
    if len(parts) < 2:
        await message.answer("Напиши, что заказать. Например: заказать маргарита")
        return
    product = " ".join(parts[1:])
    if product not in MENU:
        await message.answer("Такой пиццы нет. Есть: маргарита, пепперони, четыре сыра, гавайская")
        return
    await state.update_data(product=product)
    await state.set_state(Order.waiting_for_quantity)
    await message.answer(f"Сколько штук? (пицца: {product})")


@dp.message(Order.waiting_for_quantity)
async def order_quantity(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Введи число, например: 2")
        return
    quantity = int(message.text)
    data = await state.get_data()
    product = data["product"]
    total = MENU[product] * quantity
    await message.answer(
        f"Заказ принят! {quantity} шт. «{product}» = {total} руб. 🍕\nСпасибо за заказ!",
        reply_markup=main_keyboard()
    )
    await state.clear()


# === ОБЫЧНЫЙ РЕЖИМ — ИИ ===
@dp.message()
async def smart_answer(message: Message):
    text = message.text.lower()
    if text in MENU:
        await message.answer(f"{text.capitalize()} — {MENU[text]} руб.")
        return

    await message.answer("Секунду... 🍕")
    system_prompt = (
        "Ты — дружелюбный консультант пиццерии. "
        "В меню: Маргарита (450 руб), Пепперони (550 руб), "
        "Четыре сыра (600 руб), Гавайская (580 руб). "
        "Отвечай ТОЛЬКО на вопросы про пиццу, меню, состав, цены, заказ, доставку. "
        "Если вопрос не про пиццерию — вежливо откажись и предложи выбрать пиццу. "
        "Отвечай коротко и аппетитно."
    )
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=message.text,
            config={"system_instruction": system_prompt}
        )
        full = response.text
        for i in range(0, len(full), 4000):
            await message.answer(full[i:i+4000])
    except Exception as e:
        await message.answer("Ошибка при обращении к ИИ: " + str(e))


async def main():
    await dp.start_polling(bot)


asyncio.run(main())