import os
import base64
import requests
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
WAVESPEED_API_URL = "https://api.wavespeed.ai/api/v3/wavespeed-ai/model"

def log_error(message):
    logging.error(message)

def log_info(message):
    logging.info(message)

@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.get_json()
        log_info(f"Generate request: {data}")
        
        # Формируем промпт на основе данных заказа
        etages = data.get('etages', '1 étage')
        style = data.get('style', 'Classique Chic')
        event = data.get('event', 'Mariage')
        wishes = data.get('wishes', '')
        
        # Базовый промпт
        prompt = f"Photorealistic professional shot of a {etages} tier {event.lower()} cake, {style} style, decorated with fresh flowers. On top, an elegant gold topper that reads 'Victoria' and 'NICE, FRANCE' below. Marble table, blurred Mediterranean Sea background, Nice coastline. 8k, sharp focus, detailed texture, soft daylight."
        
        # Дополнительные пожелания
        if wishes:
            prompt += f" Additional details: {wishes}"
            
        log_info(f"Prompt: {prompt}")
        
        # Запрос к Wavespeed API v3
        headers = {
            'Authorization': f'Bearer {WAVESPEED_API_KEY}',
            'Content-Type': 'application/json'
        }
        
        payload = {
            'prompt': prompt,
            'stream': False
        }
        
        log_info(f"Sending request to Wavespeed API")
        response = requests.post(WAVESPEED_API_URL, headers=headers, json=payload)
        
        if response.status_code != 200:
            log_error(f"Wavespeed API error: {response.status_code} - {response.text}")
            return jsonify({'error': 'Generation failed'}), 500
            
        result = response.json()
        log_info(f"Wavespeed response: {result}")
        
        # Парсим ответ - пробуем разные возможные форматы
        image_urls = []
        
        # Вариант 1: массив в поле 'data'
        if isinstance(result, dict) and 'data' in result:
            data_field = result['data']
            if isinstance(data_field, list):
                for item in data_field:
                    if isinstance(item, str):
                        image_urls.append(item)
                    elif isinstance(item, dict) and 'url' in item:
                        image_urls.append(item['url'])
        
        # Вариант 2: массив в поле 'images'
        if not image_urls and isinstance(result, dict) and 'images' in result:
            images_field = result['images']
            if isinstance(images_field, list):
                for item in images_field:
                    if isinstance(item, str):
                        image_urls.append(item)
                    elif isinstance(item, dict) and 'url' in item:
                        image_urls.append(item['url'])
        
        # Вариант 3: массив в поле 'output'
        if not image_urls and isinstance(result, dict) and 'output' in result:
            output_field = result['output']
            if isinstance(output_field, list):
                for item in output_field:
                    if isinstance(item, str):
                        image_urls.append(item)
        
        # Вариант 4: сам результат - массив
        if not image_urls and isinstance(result, list):
            for item in result:
                if isinstance(item, str):
                    image_urls.append(item)
                elif isinstance(item, dict) and 'url' in item:
                    image_urls.append(item['url'])
        
        # Если не нашли изображения, возвращаем тестовые заглушки
        if not image_urls:
            log_info("No images found in response, using fallback test images")
            image_urls = [
                "https://via.placeholder.com/1024x1024/b08d57/ffffff?text=Design+1",
                "https://via.placeholder.com/1024x1024/8B7355/ffffff?text=Design+2"
            ]
        
        log_info(f"Returning {len(image_urls)} images")
        return jsonify({'images': image_urls})
        
    except Exception as e:
        log_error(f"Generate error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/send-order', methods=['POST'])
def send_order():
    try:
        data = request.get_json()
        log_info(f"Send-order request received")
        
        # Проверяем наличие всех полей
        required_fields = ['image_base64', 'name', 'contact', 'order_details', 'selected_design']
        if not all(field in data for field in required_fields):
            missing = [f for f in required_fields if f not in data]
            log_error(f"Missing fields: {missing}")
            return jsonify({'error': f'Missing fields: {missing}'}), 400

        # Извлекаем данные
        image_base64 = data['image_base64']
        name = data['name']
        contact = data['contact']
        order_details = data['order_details']
        selected_design = data['selected_design']
        
        log_info(f"Field 'image_base64' present: {image_base64[:50]}...")
        log_info(f"Field 'name' present: {name}")
        log_info(f"Field 'contact' present: {contact}")
        log_info(f"Field 'order_details' present: {order_details}")
        log_info(f"Field 'selected_design' present: {selected_design}")
        
        # Убираем префикс data:image/... если он есть
        if ',' in image_base64:
            image_base64 = image_base64.split(',')[1]
        
        # Декодируем base64 в бинарные данные
        try:
            image_data = base64.b64decode(image_base64)
            log_info(f"Image data size: {len(image_data)} bytes")
        except Exception as e:
            log_error(f"Base64 decode error: {str(e)}")
            return jsonify({'error': 'Invalid image data'}), 400

        # Формируем текст сообщения
        caption = f"""📦 *Nouvelle commande*
👤 *Nom:* {name}
📱 *Contact:* {contact}
📝 *Détails:*
{order_details}
✨ *Design choisi:* {selected_design}
_En attente de validation par le Chef._"""

        # Проверяем длину подписи
        log_info(f"Caption length: {len(caption)} chars")

        # Отправляем в Telegram
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
