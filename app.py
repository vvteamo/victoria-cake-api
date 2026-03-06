import os
import base64
import requests
import time
import re
from flask import Flask, request, jsonify
from flask_cors import CORS
import logging

app = Flask(__name__)
CORS(app)

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Конфигурация из переменных окружения
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
WAVESPEED_API_KEY = os.environ.get('WAVESPEED_API_KEY')
# ===== СМЕНИЛИ МОДЕЛЬ НА SEEDREAM =====
WAVESPEED_API_URL = "https://api.wavespeed.ai/api/v3/wavespeed-ai/seedream"

# Словари для перевода событий и стилей на английский
EVENT_MAP = {
    "Mariage": "wedding",
    "Anniversaire adulte": "adult birthday",
    "Anniversaire enfant": "child's birthday",
    "Baptême": "baptism",
    "Fête corporative": "corporate party",
    "Autre": "celebration"
}

STYLE_MAP = {
    "Minimaliste": "minimalistic",
    "Classique Chic": "classic chic",
    "Floral / Romantique": "floral romantic",
    "Artistique": "artistic",
    "Sur mesure": "custom"
}

# Список ключевых слов для фруктов и овощей
FRUIT_KEYWORDS = [
    "poire", "pomme", "banane", "fraise", "citron", "orange", "pear", "apple",
    "banana", "strawberry", "lemon", "orange", "tomate", "tomato", "concombre",
    "cucumber", "carotte", "carrot", "fruits", "fruit", "légume", "vegetable",
    "pasteque", "watermelon", "ananas", "pineapple", "peche", "peach", "cerise",
    "cherry", "raisin", "grape", "kiwi", "mangue", "mango"
]

def log_error(message):
    logging.error(message)

def log_info(message):
    logging.info(message)

def download_image_as_base64(image_url):
    """Скачивает изображение по URL и возвращает в формате base64"""
    try:
        response = requests.get(image_url, timeout=30)
        if response.status_code == 200:
            image_base64 = base64.b64encode(response.content).decode('utf-8')
            return f"data:image/jpeg;base64,{image_base64}"
        else:
            log_error(f"Failed to download image: {response.status_code}")
            return None
    except Exception as e:
        log_error(f"Download error: {str(e)}")
        return None

def wait_for_image(result_url, max_attempts=60, delay=2):
    """Опрашивает URL результата, пока изображение не будет готово"""
    headers = {
        'Authorization': f'Bearer {WAVESPEED_API_KEY}'
    }
    
    for attempt in range(max_attempts):
        try:
            response = requests.get(result_url, headers=headers)
            if response.status_code == 200:
                result = response.json()
                log_info(f"Poll response: {result}")
                
                if isinstance(result, dict) and 'data' in result:
                    data = result['data']
                    status = data.get('status')
                    
                    if status == 'completed':
                        outputs = data.get('outputs', [])
                        if outputs and len(outputs) > 0:
                            image_url = outputs[0]
                            log_info(f"Image URL: {image_url}")
                            return download_image_as_base64(image_url)
                    elif status in ['failed', 'error']:
                        log_error(f"Generation failed: {result}")
                        return None
            time.sleep(delay)
        except Exception as e:
            log_error(f"Poll error: {str(e)}")
            time.sleep(delay)
    
    log_error("Timeout waiting for image")
    return None

def extract_fruit_name(wishes):
    """Извлекает название фрукта из пожелания"""
    words = wishes.lower().split()
    for word in words:
        # Очищаем слово от знаков препинания
        clean_word = re.sub(r'[^\w\s]', '', word)
        if clean_word in FRUIT_KEYWORDS:
            return clean_word
    return None

def build_prompt(data):
    """Собирает промпт из структурированных блоков"""
    
    # Извлекаем параметры
    etages_raw = data.get('etages', '1 étage')
    etages = etages_raw.split()[0] if etages_raw else '1'
    style = data.get('style', 'Classique Chic')
    event = data.get('event', 'Mariage')
    inscription = data.get('inscription', '').strip()
    wishes = data.get('wishes', '').strip()
    shape_type = data.get('shapeType', 'classic')

    # Перевод
    event_en = EVENT_MAP.get(event, event)
    style_en = STYLE_MAP.get(style, style)

    # Блок 1: Subject (объект)
    if shape_type != 'classic' and wishes:
        fruit_name = extract_fruit_name(wishes)
        if fruit_name:
            subject = f"A whole cake sculpted as a giant realistic {fruit_name}"
            log_info(f"Fruit detected: {fruit_name}")
        else:
            subject = f"A whole cake sculpted as {wishes}"
    else:
        subject = f"A {etages}-tier {event_en} cake, {style_en} style"
    
    # Блок 2: Action/Pose (детали)
    if shape_type != 'classic' and wishes:
        if fruit_name:
            action = f"with natural color gradient and realistic texture, and a small green leaf on the stem if applicable"
        else:
            action = f"with realistic details: {wishes}"
    else:
        action = "with elegant decorations"
    
    # Блок 3: Topper (надпись)
    if inscription:
        topper = f"On top, a simple elegant gold plaque with the inscription: '{inscription}'"
    else:
        topper = "On top, a simple elegant gold plaque with the text 'Victoria'"
    
    # Блоки 4-6: Окружение, свет, стиль, качество (всегда одинаковые)
    environment = "The cake is placed on a marble table. Background is a blurred, sunlit view of the Mediterranean Sea in Nice, France"
    lighting = "Soft daylight, cinematic lighting"
    style_quality = "Photorealistic, professional food photography, 8k resolution, sharp focus, detailed textures"
    
    # Собираем всё в один промпт
    prompt_parts = [
        subject,
        action,
        topper,
        environment,
        lighting,
        style_quality
    ]
    
    prompt = ". ".join(prompt_parts) + "."
    return prompt

@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.get_json()
        log_info(f"Generate request: {data}")

        # Собираем промпт из блоков
        prompt = build_prompt(data)
        log_info(f"Structured prompt: {prompt}")

        # Улучшенный negative prompt
        negative_prompt = (
            "no pumpkin, no squash, no orange color, no cartoon style, no plasticine, "
            "no clay, no playdough, no flat colors, no solid blocks, no patches, no spots, "
            "no separate fruit on cake, no fruit on top, no extra objects, no distorted shapes, "
            "no weird textures, no low quality, no blurry, no bad anatomy, no extra hands, "
            "no text except on the plaque, no people, no silhouettes, no reflections with faces"
        )
        log_info(f"Negative prompt: {negative_prompt}")

        # Запрос к Wavespeed API
        headers = {
            'Authorization': f'Bearer {WAVESPEED_API_KEY}',
            'Content-Type': 'application/json'
        }

        image_base64_list = []

        for i in range(2):  # Генерируем два варианта
            payload = {
                'prompt': prompt,
                'negative_prompt': negative_prompt,
                'size': '1024*1024',
                'num_inference_steps': 28,
                'guidance_scale': 3.5,
                'num_images': 1,
                'seed': -1
            }

            log_info(f"Sending request {i+1} to Wavespeed API")
            response = requests.post(WAVESPEED_API_URL, headers=headers, json=payload)

            if response.status_code != 200:
                log_error(f"Wavespeed API error: {response.status_code} - {response.text}")
                continue

            result = response.json()
            log_info(f"Wavespeed response {i+1}: {result}")

            # Извлекаем URL для получения результата (асинхронно)
            if isinstance(result, dict) and 'data' in result:
                data_field = result['data']
                if isinstance(data_field, dict) and 'urls' in data_field:
                    result_url = data_field['urls'].get('get')
                    if result_url:
                        image_base64 = wait_for_image(result_url)
                        if image_base64:
                            image_base64_list.append(image_base64)
                        else:
                            log_error(f"Failed to get image for request {i+1}")

        # Если не удалось получить изображения, используем заглушку
        if len(image_base64_list) < 2:
            log_info("Not enough images from API, using fallback")
            fallback_base64 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
            while len(image_base64_list) < 2:
                image_base64_list.append(fallback_base64)

        log_info(f"Returning {len(image_base64_list)} images")
        return jsonify({'images': image_base64_list})

    except Exception as e:
        log_error(f"Generate error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/send-order', methods=['POST'])
def send_order():
    try:
        data = request.get_json()
        log_info(f"Send-order request received")

        required_fields = ['image_base64', 'name', 'contact', 'order_details', 'selected_design']
        if not all(field in data for field in required_fields):
            missing = [f for f in required_fields if f not in data]
            log_error(f"Missing fields: {missing}")
            return jsonify({'error': f'Missing fields: {missing}'}), 400

        image_base64 = data['image_base64']
        name = data['name']
        contact = data['contact']
        order_details = data['order_details']
        selected_design = data['selected_design']

        if ',' in image_base64:
            image_base64 = image_base64.split(',')[1]

        try:
            image_data = base64.b64decode(image_base64)
            log_info(f"Image data size: {len(image_data)} bytes")
        except Exception as e:
            log_error(f"Base64 decode error: {str(e)}")
            return jsonify({'error': 'Invalid image data'}), 400

        caption = f"""📦 *Nouvelle commande*
👤 *Nom:* {name}
📱 *Contact:* {contact}
📝 *Détails:*
{order_details}
✨ *Design choisi:* {selected_design}
_En attente de validation par le Chef._"""

        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"

        files = {
            'photo': ('cake.png', image_data, 'image/png')
        }

        payload = {
            'chat_id': TELEGRAM_CHAT_ID,
            'caption': caption,
            'parse_mode': 'Markdown'
        }

        log_info(f"Sending to Telegram chat_id: {TELEGRAM_CHAT_ID}")

        response = requests.post(url, files=files, data=payload)

        if response.status_code == 200:
            result = response.json()
            log_info(f"Telegram response: {result}")
            return jsonify({'success': True}), 200
        else:
            log_error(f"Telegram API error: {response.status_code} - {response.text}")
            return jsonify({'error': 'Telegram send failed'}), 500

    except Exception as e:
        log_error(f"Send-order error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
