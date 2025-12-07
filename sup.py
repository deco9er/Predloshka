import sqlite3
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
import asyncio

# Конфигурация
ADMIN_ID = 1234567890  # Замените на ваш ID
BOT_TOKEN = "твой токен/your token"

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Подключение к БД
conn = sqlite3.connect('support_bot.db', check_same_thread=False)
cursor = conn.cursor()

# Создание таблиц
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    is_banned INTEGER DEFAULT 0
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS messages (
    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    admin_message_id INTEGER,
    status TEXT DEFAULT 'new',
    FOREIGN KEY (user_id) REFERENCES users (user_id)
)
''')
conn.commit()

# FSM состояния
class AdminReply(StatesGroup):
    waiting_for_reply = State()

# Клавиатура для админа
# Исправленная функция get_admin_keyboard
def get_admin_keyboard(user_id, message_id=None):
    """
    Создает клавиатуру для админа.
    Если message_id равен None, кнопка 'Прочитано' не добавляется.
    """
    builder = InlineKeyboardBuilder()
    
    # Всегда добавляем кнопки "Забанить" и "Ответить"
    builder.add(
        InlineKeyboardButton(text="🔨 Забанить", callback_data=f"ban_{user_id}"),
        InlineKeyboardButton(text="💬 Ответить", callback_data=f"reply_{user_id}")
    )
    
    # Добавляем кнопку "Прочитано" только если передан message_id
    if message_id is not None:
        builder.add(InlineKeyboardButton(text="✓ Прочитано", callback_data=f"read_{message_id}"))
    
    # Настраиваем расположение кнопок (2 в первом ряду, 1 во втором если есть)
    builder.adjust(2, 1)
    
    return builder.as_markup()

# Исправленный обработчик нажатий на кнопки админа
@dp.callback_query(F.data.startswith(('ban_', 'reply_', 'read_')))
async def admin_callback_handler(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Эта функция доступна только администратору.", show_alert=True)
        return
    
    data = callback.data
    
    if data.startswith('ban_'):
        user_id = int(data.split('_')[1])
        
        # Баним пользователя
        cursor.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (user_id,))
        conn.commit()
        
        # Уведомляем пользователя
        try:
            await bot.send_message(user_id, "🚫 Вы были заблокированы администратором.")
        except:
            pass
        
        await callback.message.edit_text(
            callback.message.text + "\n\n✅ Пользователь заблокирован.",
            reply_markup=None  # Убираем все кнопки после бана
        )
        await callback.answer()
        
    elif data.startswith('reply_'):
        user_id = int(data.split('_')[1])
        
        # Сохраняем ID пользователя для ответа
        await state.update_data(reply_to_user=user_id)
        await state.set_state(AdminReply.waiting_for_reply)
        
        await callback.message.answer(f"✍️ Введите ответ для пользователя {user_id} (или /cancel для отмены):")
        await callback.answer()
        
    elif data.startswith('read_'):
        # Безопасно извлекаем message_id, проверяя что это число
        try:
            message_id_str = data.split('_')[1]
            # Если это строка 'None' или пустая, пропускаем
            if message_id_str == 'None' or not message_id_str:
                await callback.answer("❌ Не удалось отметить как прочитанное: отсутствует ID сообщения")
                return
                
            message_id = int(message_id_str)
        except (ValueError, IndexError) as e:
            await callback.answer("❌ Ошибка обработки запроса")
            logger.error(f"Ошибка при обработке callback_data '{data}': {e}")
            return
        
        # Помечаем сообщение как прочитанное
        cursor.execute("UPDATE messages SET status = 'read' WHERE admin_message_id = ?", (message_id,))
        conn.commit()
        
        # Получаем user_id из сообщения
        cursor.execute("SELECT user_id FROM messages WHERE admin_message_id = ?", (message_id,))
        result = cursor.fetchone()
        
        if result:
            user_id = result[0]
            try:
                await bot.send_message(user_id, "👁 Администратор прочитал ваше сообщение.")
            except:
                pass
            
            # Убираем кнопки ВСЕХ сообщений от этого пользователя
            cursor.execute("SELECT admin_message_id FROM messages WHERE user_id = ? AND status = 'new'", (user_id,))
            all_messages = cursor.fetchall()
            
            for msg in all_messages:
                try:
                    # Пытаемся получить сообщение по его ID
                    msg_id = msg[0]
                    # Обновляем текст, убирая кнопки
                    await bot.edit_message_reply_markup(
                        chat_id=ADMIN_ID,
                        message_id=msg_id,
                        reply_markup=None
                    )
                    # Обновляем статус в БД
                    cursor.execute("UPDATE messages SET status = 'read' WHERE admin_message_id = ?", (msg_id,))
                except Exception as e:
                    logger.error(f"Не удалось обновить сообщение {msg[0]}: {e}")
            
            conn.commit()
        
        # Редактируем текущее сообщение
        try:
            await callback.message.edit_text(
                callback.message.text + "\n\n✓ Помечено как прочитанное",
                reply_markup=None  # Полностью убираем клавиатуру
            )
        except Exception as e:
            logger.error(f"Не удалось отредактировать сообщение: {e}")
            await callback.answer("✅ Отмечено как прочитанное")
        
        await callback.answer()

# Обработчик команды /start
@dp.message(Command("start"))
async def start_handler(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username
    
    # Сохраняем пользователя в БД
    cursor.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
    conn.commit()
    
    await message.answer("👋 Привет! Отправьте ваше сообщение для связи с администратором.")

# Обработчик команды /help
@dp.message(Command("help"))
async def help_handler(message: types.Message):
    await message.answer("ℹ️ Отправьте любое сообщение или файл для связи с администратором.")

# Обработчик команды /unb для разбана
@dp.message(Command("unb"))
async def unban_command(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Эта команда доступна только администратору.")
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /unb <user_id или username>")
        return
    
    identifier = args[1].lstrip('@')
    
    # Пытаемся найти пользователя
    if identifier.isdigit():
        cursor.execute("SELECT user_id, username FROM users WHERE user_id = ?", (int(identifier),))
    else:
        cursor.execute("SELECT user_id, username FROM users WHERE username = ?", (identifier,))
    
    user = cursor.fetchone()
    
    if not user:
        await message.answer("❌ Пользователь не найден.")
        return
    
    user_id, username = user
    
    # Разбаниваем
    cursor.execute("UPDATE users SET is_banned = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    
    # Уведомляем пользователя
    try:
        await bot.send_message(user_id, "✅ Вы были разблокированы администратором.")
    except Exception as e:
        logger.error(f"Не удалось уведомить пользователя о разбане: {e}")
    
    await message.answer(f"✅ Пользователь {username or user_id} разблокирован.")

# Обработчик команды /stats для статистики
@dp.message(Command("stats"))
async def stats_command(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Эта команда доступна только администратору.")
        return
    
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1")
    banned_users = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM messages")
    total_messages = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM messages WHERE status = 'new'")
    new_messages = cursor.fetchone()[0]
    
    stats_text = (
        f"📊 Статистика бота:\n\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"🚫 Заблокировано: {banned_users}\n"
        f"📨 Всего сообщений: {total_messages}\n"
        f"🆕 Новых сообщений: {new_messages}"
    )
    
    await message.answer(stats_text)

# Обработчик команды /cancel для отмены состояния
@dp.message(Command("cancel"))
async def cancel_handler(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        return
    
    await state.clear()
    await message.answer("❌ Действие отменено.")

# Обработчик всех сообщений от пользователей (кроме команд)
@dp.message(F.chat.type == "private")
async def user_message_handler(message: types.Message, state: FSMContext):
    # Проверяем, является ли сообщение командой
    if message.text and message.text.startswith('/'):
        return  # Игнорируем команды, они обрабатываются отдельно
    
    user_id = message.from_user.id
    username = message.from_user.username
    current_state = await state.get_state()
    
    # Если админ в состоянии ожидания ответа
    if user_id == ADMIN_ID and current_state == AdminReply.waiting_for_reply.state:
        data = await state.get_data()
        reply_to_user = data.get('reply_to_user')
        
        if reply_to_user:
            try:
                # Отправляем ответ пользователю
                if message.text:
                    await bot.send_message(
                        reply_to_user,
                        f"📨 Ответ от администратора:\n\n{message.text}"
                    )
                elif message.photo:
                    await bot.send_photo(
                        reply_to_user,
                        message.photo[-1].file_id,
                        caption=f"📨 Ответ от администратора:\n\n{message.caption if message.caption else ''}"
                    )
                elif message.document:
                    await bot.send_document(
                        reply_to_user,
                        message.document.file_id,
                        caption=f"📨 Ответ от администратора:\n\n{message.caption if message.caption else ''}"
                    )
                elif message.video:
                    await bot.send_video(
                        reply_to_user,
                        message.video.file_id,
                        caption=f"📨 Ответ от администратора:\n\n{message.caption if message.caption else ''}"
                    )
                elif message.audio:
                    await bot.send_audio(
                        reply_to_user,
                        message.audio.file_id,
                        caption=f"📨 Ответ от администратора:\n\n{message.caption if message.caption else ''}"
                    )
                else:
                    await bot.copy_message(
                        reply_to_user,
                        message.chat.id,
                        message.message_id,
                        caption=f"📨 Ответ от администратора:\n\n{message.caption if message.caption else ''}"
                    )
                
                await message.answer("✅ Ответ отправлен пользователю.")
            except Exception as e:
                await message.answer(f"❌ Не удалось отправить ответ: {e}")
            
            await state.clear()
        return
    
    # Проверяем не забанен ли пользователь (кроме админа)
    if user_id != ADMIN_ID:
        cursor.execute("SELECT is_banned FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()
        
        if user and user[0] == 1:
            await message.answer("🚫 Вы заблокированы и не можете отправлять сообщения.")
            return
    
    # Сохраняем пользователя (кроме админа)
    if user_id != ADMIN_ID:
        cursor.execute("INSERT OR REPLACE INTO users (user_id, username, is_banned) VALUES (?, ?, 0)", (user_id, username))
    
    # Если сообщение от обычного пользователя, пересылаем админу
    if user_id != ADMIN_ID:
        try:
            if message.text:
                sent_msg = await bot.send_message(
                    ADMIN_ID,
                    f"📩 Новое сообщение от пользователя:\n"
                    f"ID: {user_id}\n"
                    f"Юзер: @{username if username else 'нет'}\n\n"
                    f"{message.text}",
                    reply_markup=get_admin_keyboard(user_id)
                )
            else:
                # Для медиафайлов
                if message.photo:
                    file_id = message.photo[-1].file_id
                    sent = await bot.send_photo(
                        ADMIN_ID,
                        file_id,
                        caption=f"📸 Фото от пользователя:\nID: {user_id}\nЮзер: @{username if username else 'нет'}\n\n{message.caption if message.caption else ''}",
                        reply_markup=get_admin_keyboard(user_id)
                    )
                elif message.document:
                    file_id = message.document.file_id
                    sent = await bot.send_document(
                        ADMIN_ID,
                        file_id,
                        caption=f"📎 Документ от пользователя:\nID: {user_id}\nЮзер: @{username if username else 'нет'}\n\n{message.caption if message.caption else ''}",
                        reply_markup=get_admin_keyboard(user_id)
                    )
                elif message.video:
                    file_id = message.video.file_id
                    sent = await bot.send_video(
                        ADMIN_ID,
                        file_id,
                        caption=f"🎥 Видео от пользователя:\nID: {user_id}\nЮзер: @{username if username else 'нет'}\n\n{message.caption if message.caption else ''}",
                        reply_markup=get_admin_keyboard(user_id)
                    )
                elif message.audio:
                    file_id = message.audio.file_id
                    sent = await bot.send_audio(
                        ADMIN_ID,
                        file_id,
                        caption=f"🎵 Аудио от пользователя:\nID: {user_id}\nЮзер: @{username if username else 'нет'}\n\n{message.caption if message.caption else ''}",
                        reply_markup=get_admin_keyboard(user_id)
                    )
                else:
                    sent = await bot.send_message(
                        ADMIN_ID,
                        f"📎 Медиафайл от пользователя:\nID: {user_id}\nЮзер: @{username if username else 'нет'}",
                        reply_markup=get_admin_keyboard(user_id)
                    )
                sent_msg = sent
                
            # Сохраняем в БД
            cursor.execute("INSERT INTO messages (user_id, admin_message_id) VALUES (?, ?)", (user_id, sent_msg.message_id))
            conn.commit()
            
            await message.answer("✅ Ваше сообщение отправлено администратору.")
            
        except Exception as e:
            logger.error(f"Ошибка при пересылке сообщения: {e}")
            await message.answer("❌ Произошла ошибка при отправке сообщения.")

# Обработчик нажатий на кнопки админа
@dp.callback_query(F.data.startswith(('ban_', 'reply_', 'read_')))
async def admin_callback_handler(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Эта функция доступна только администратору.", show_alert=True)
        return
    
    data = callback.data
    
    if data.startswith('ban_'):
        user_id = int(data.split('_')[1])
        
        # Баним пользователя
        cursor.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (user_id,))
        conn.commit()
        
        # Уведомляем пользователя
        try:
            await bot.send_message(user_id, "🚫 Вы были заблокированы администратором.")
        except:
            pass
        
        await callback.message.edit_text(
            callback.message.text + "\n\n✅ Пользователь заблокирован.",
            reply_markup=None
        )
        await callback.answer()
        
    elif data.startswith('reply_'):
        user_id = int(data.split('_')[1])
        
        # Сохраняем ID пользователя для ответа
        await state.update_data(reply_to_user=user_id)
        await state.set_state(AdminReply.waiting_for_reply)
        
        await callback.message.answer(f"✍️ Введите ответ для пользователя {user_id} (или /cancel для отмены):")
        await callback.answer()
        
    elif data.startswith('read_'):
        message_id = int(data.split('_')[1])
        
        # Помечаем сообщение как прочитанное
        cursor.execute("UPDATE messages SET status = 'read' WHERE admin_message_id = ?", (message_id,))
        conn.commit()
        
        # Получаем user_id из сообщения
        cursor.execute("SELECT user_id FROM messages WHERE admin_message_id = ?", (message_id,))
        result = cursor.fetchone()
        
        if result:
            user_id = result[0]
            try:
                await bot.send_message(user_id, "👁 Администратор прочитал ваше сообщение.")
            except:
                pass
        
        await callback.message.edit_text(
            callback.message.text + "\n\n✓ Помечено как прочитанное",
            reply_markup=None
        )
        await callback.answer()

# Запуск бота
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    print("Бот запущен...")

    asyncio.run(main())
