import os
import tempfile
import uuid
import telebot
from PIL import Image
from collections import defaultdict
import threading
import logging
import zipfile
import datetime

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = "7960773738:AAFGK51UFNOjWAAg-_WZPXQBYtiiXMr3NtI"
bot = telebot.TeleBot(TOKEN)

# Константы для режимов и задержек
FAST_WAIT_TIME = 2
SLOW_WAIT_TIME = 10

MIN_PHOTOS_TO_SEND = 1  # Можно поставить 1, чтобы не ждать слишком долго

# Словари для хранения данных по пользователям
user_photos = defaultdict(list)       # chat_id -> список путей к фото
user_timers = {}                      # chat_id -> объект Timer
user_mode = {}                        # chat_id -> "fast" или "slow"

def convert_to_jpg(file_path: str, output_dir: str, index: int, quality: int = 90) -> str:
    img = Image.open(file_path)
    output_filename = f"photo_{index:03d}.jpg"  # photo_001.jpg, photo_002.jpg
    output_path = os.path.join(output_dir, output_filename)
    img.convert("RGB").save(output_path, "JPEG", quality=quality)
    return output_path

def cleanup_files(files):
    """Удаляет временные файлы."""
    for f in files:
        try:
            if os.path.exists(f):
                os.remove(f)
        except Exception as e:
            logger.warning(f"Не удалось удалить файл {f}: {e}")

def cleanup_dir(directory):
    """Удаляет папку, если она пуста."""
    try:
        if os.path.exists(directory) and not os.listdir(directory):
            os.rmdir(directory)
    except Exception as e:
        logger.warning(f"Не удалось удалить папку {directory}: {e}")

def send_archive_for_user(chat_id):
    photos = user_photos.pop(chat_id, [])
    if not photos:
        return

    # Если фото меньше минимального порога, вернём обратно и не отправим
    if len(photos) < MIN_PHOTOS_TO_SEND:
        user_photos[chat_id].extend(photos)
        return

    temp_dir = tempfile.mkdtemp(prefix="converted_")
    converted_files = []
    now_str = datetime.datetime.now().strftime("%d-%m-%Y_%H-%M-%S")
    zip_name = f"photos_{now_str}.zip"
    zip_path = os.path.join(tempfile.gettempdir(), zip_name)

    try:
        for i, temp_input in enumerate(photos, start=1):
            try:
                jpg_path = convert_to_jpg(temp_input, temp_dir, index=i)
                converted_files.append(jpg_path)
            except Exception as e:
                logger.error(f"Ошибка при конвертации {temp_input}: {e}")
                continue

        if not converted_files:
            bot.send_message(chat_id, "❌ Не удалось конвертировать ни одного фото.")
            return

        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for file in converted_files:
                zipf.write(file, os.path.basename(file))

        with open(zip_path, "rb") as f:
            bot.send_document(chat_id, f, caption=f"✅ Готово! В архиве {len(converted_files)} фото.")

    except Exception as e:
        logger.error(f"Ошибка при отправке архива: {e}")
        bot.send_message(chat_id, f"❌ Произошла ошибка: {e}")

    finally:
        cleanup_files(photos + converted_files)
        try:
            if os.path.exists(zip_path):
                os.remove(zip_path)
            cleanup_dir(temp_dir)
        except Exception as e:
            logger.warning(f"Ошибка при очистке: {e}")

def schedule_send(chat_id):
    if chat_id in user_timers:
        user_timers[chat_id].cancel()

    mode = user_mode.get(chat_id, "fast")
    wait_time = FAST_WAIT_TIME if mode == "fast" else SLOW_WAIT_TIME

    timer = threading.Timer(wait_time, send_archive_for_user, args=(chat_id,))
    user_timers[chat_id] = timer
    timer.start()

@bot.message_handler(commands=['start'])
def send_welcome(message):
    chat_id = message.chat.id
    user_mode[chat_id] = "fast"  # режим по умолчанию

    markup = telebot.types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    markup.add("Быстрый режим", "Долгий режим")
    bot.send_message(chat_id, "Привет! Выберите режим конвертации фото:", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text in ["Быстрый режим", "Долгий режим"])
def set_mode(message):
    chat_id = message.chat.id
    if message.text == "Быстрый режим":
        user_mode[chat_id] = "fast"
        bot.send_message(chat_id, "Выбран быстрый режим.", reply_markup=telebot.types.ReplyKeyboardRemove())
    else:
        user_mode[chat_id] = "slow"
        bot.send_message(chat_id, "Выбран долгий режим.", reply_markup=telebot.types.ReplyKeyboardRemove())

@bot.message_handler(content_types=['photo'])
def handle_photos_accumulate(message):
    try:
        file_id = message.photo[-1].file_id
        file_info = bot.get_file(file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        temp_input = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4()}.jpg")
        with open(temp_input, "wb") as f:
            f.write(downloaded_file)

        user_photos[message.chat.id].append(temp_input)
        schedule_send(message.chat.id)

    except Exception as e:
        logger.error(f"Ошибка в handle_photos_accumulate: {e}")
        bot.reply_to(message, f"❌ Произошла ошибка: {str(e)}")

@bot.message_handler(commands=['help'])
def send_help(message):
    bot.reply_to(message, "Отправьте мне фото (несколько подряд), я конвертирую их в JPG и отправлю архив.\n"
                          "Для выбора режима используйте команду /start.")

@bot.message_handler(content_types=['document'])
def handle_documents(message):
    bot.reply_to(message, "Пожалуйста, отправляйте фотографии как фото (не документами).")

if __name__ == "__main__":
    logger.info("Бот запущен")
    bot.polling(none_stop=True)
