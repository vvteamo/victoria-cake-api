import os
import base64
import requests
import time
import sys
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
WAVESPEED_API_URL = "https://api.wavespeed.ai/api/v3/wavespeed-ai/flux-dev"

def log_error(message):
    logging.error(message)

def log_info(message):
    logging.info(message)

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
                        # Изображение готово
                        outputs = data.get('outputs', [])
                        if outputs and len(outputs) > 0:
                            return outputs[0]
                    elif status in ['failed', 'error']:
                        log_error(f"Generation failed: {result}")
                        return None
                    # else: still processing - продолжаем ждать
            time.sleep(delay)
        except Exception as e:
            log_error(f"Poll error: {str(e)}")
            time.sleep(delay)
    
    log_error("Timeout waiting for image")
    return None

@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.get_json()
        log_info(f"Generate request: {data}")
        
        # Формируем промпт
        etages = data.get('etages', '1 étage')
        style = data.get('style', 'Classique Chic')
        event = data.get('event', 'Mariage')
        wishes = data.get('wishes', '')
        
        prompt = f"Photorealistic professional shot of a {etages} tier {event.lower()} cake, {style} style, decorated with fresh flowers. On top, an elegant gold topper that reads 'Victoria' and 'NICE, FRANCE' below. Marble table, blurred Mediterranean Sea background, Nice coastline. 8k, sharp focus, detailed texture, soft daylight. Make it even more elegant with enhanced lighting and refined details."
        
        if wishes:
            prompt += f" Additional details: {wishes}"
            
        log_info(f"Prompt: {prompt}")
        
        headers = {
            'Authorization': f'Bearer {WAVESPEED_API_KEY}',
            'Content-Type': 'application/json'
        }
        
        image_urls = []
        
        # Генерируем 2 изображения
        for i in range(2):
            payload = {
                'prompt': prompt,
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
            
            # Извлекаем URL для получения результата
            if isinstance(result, dict) and 'data' in result:
                data_field = result['data']
                if isinstance(data_field, dict) and 'urls' in data_field:
                    result_url = data_field['urls'].get('get')
                    if result_url:
                        # Ждём готовности изображения
                        image_url = wait_for_image(result_url)
                        if image_url:
                            image_urls.append(image_url)
                        else:
                            log_error(f"Failed to get image for request {i+1}")
        
        # Если не удалось получить изображения, используем заглушки
        if len(image_urls) < 2:
            log_info("Not enough images from API, using fallback")
            fallback_images = [
                "https://via.placeholder.com/1024x1024/b08d57/ffffff?text=Design+Principal",
                "https://via.placeholder.com/1024x1024/8B7355/ffffff?text=Variante+Atelier"
            ]
            while len(image_urls) < 2:
                image_urls.append(fallback_images[len(image_urls)])
        
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
    # Увеличиваем таймаут для Gunicorn
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
