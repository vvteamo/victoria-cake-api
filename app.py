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
WAVESPEED_API_URL = "https://api.wavespeed.ai/v1/images/generations"

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
        guests = data.get('guests', 6)
        wishes = data.get('wishes', '')
        
        # Базовый промпт
        prompt = f"Photorealistic professional shot of a {etages} tier {event.lower()} cake, {style} style, decorated with fresh flowers. On top, an elegant gold topper that reads 'Victoria' and 'NICE, FRANCE' below. Marble table, blurred Mediterranean Sea background, Nice coastline. 8k, sharp focus, detailed texture, soft daylight."
        
        # Дополнительные пожелания
        if wishes:
            prompt += f" Additional details: {wishes}"
            
        creative_prompt = prompt + " Make it even more elegant with enhanced lighting and refined details."
        
        log_info(f"Prompt (standard): {prompt}")
        log_info(f"Prompt (creative): {creative_prompt}")
        
        # Запрос к Wavespeed API
        headers = {
            'Authorization': f'Bearer {WAVESPEED_API_KEY}',
            'Content-Type': 'application/json'
        }
        
        payload = {
            'prompt': creative_prompt,
            'model': 'flux',
            'n': 2,  # Генерируем 2 изображения
            'size': '1024x1024'
        }
        
        response = requests.post(WAVESPEED_API_URL, headers=headers, json=payload)
        
        if response.status_code != 200:
            log_error(f"Wavespeed API error: {response.text}")
            return jsonify({'error': 'Generation failed'}), 500
            
        result = response.json()
        
        # Извлекаем URL изображений из ответа Wavespeed
        images = result.get('data', [])
        image_urls = [img.get('url') for img in images if img.get('url')]
        
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
