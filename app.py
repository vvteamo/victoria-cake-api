import os
import base64
import tempfile
import uuid
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
import wavespeed
from deep_translator import GoogleTranslator

app = Flask(__name__)
CORS(app, origins=['*'])

# Получаем API-ключи из переменных окружения
WAVESPEED_API_KEY = os.environ.get('WAVESPEED_API_KEY')
WHATSAPP_PHONE_ID = os.environ.get('WHATSAPP_PHONE_ID')
WHATSAPP_TOKEN = os.environ.get('WHATSAPP_TOKEN')
HF_API_KEY = os.environ.get('HF_API_KEY')  # для второго пути (скрыт)

if not WAVESPEED_API_KEY:
    print("Warning: WAVESPEED_API_KEY not set")
if not WHATSAPP_PHONE_ID or not WHATSAPP_TOKEN:
    print("Warning: WhatsApp credentials not set")

def build_prompt(data, creative=False):
    """Формирует промпт для text-to-image (первый путь)"""
    etages = data.get('etages', '1 étage')
    style = data.get('style', 'Classique Chic')
    event = data.get('event', 'Mariage')
    guests = data.get('guests', 6)
    hasCustomTopper = data.get('hasCustomTopper', False)
    inscription = data.get('inscription', '')
    wishes = data.get('wishes', '')
    date = data.get('date', '')
    
    prompt = f"Photorealistic professional shot of a {etages} tier wedding cake, {style} style, decorated with fresh flowers"
    
    if inscription:
        prompt += f", with inscription '{inscription}'"
    
    if not hasCustomTopper:
        prompt += ". On top, an elegant gold topper that reads 'Victoria' and 'NICE, FRANCE' below"
    else:
        prompt += ". On the marble base, a subtle gold engraving 'Victoria' and 'NICE, FRANCE'"
    
    prompt += ". Marble table, blurred Mediterranean Sea background, Nice coastline. 8k, sharp focus, detailed texture, soft daylight."
    
    if creative:
        prompt += " Make it even more elegant with enhanced lighting and refined details."
    
    return prompt

@app.route('/', methods=['GET'])
def home():
    return "API de génération de gâteaux Victoria fonctionne !"

@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.json
        if not WAVESPEED_API_KEY:
            return jsonify({'error': 'WAVESPEED_API_KEY not configured'}), 500
        
        client = wavespeed.Client(api_key=WAVESPEED_API_KEY)
        
        images_base64 = []
        image_urls = []
        
        if 'image_base64' in data:
            # Второй путь (скрыт) – оставляем как есть
            pass
        else:
            # Первый путь
            for creative in [False, True]:
                prompt = build_prompt(data, creative=creative)
                print(f"Prompt ({'creative' if creative else 'standard'}): {prompt}")
                
                result = client.run(
                    "wavespeed-ai/z-image/turbo",
                    {"prompt": prompt}
                )
                
                if isinstance(result, dict) and 'outputs' in result:
                    img_url = result['outputs'][0]
                    img_response = requests.get(img_url)
                    img_response.raise_for_status()
                    image_data = img_response.content
                    
                    base64_image = base64.b64encode(image_data).decode('utf-8')
                    images_base64.append(f"data:image/png;base64,{base64_image}")
                    image_urls.append(img_url)
                else:
                    return jsonify({'error': f'Unexpected Wavespeed result: {result}'}), 500
        
        return jsonify({'images': images_base64, 'image_urls': image_urls})
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/send-order', methods=['POST'])
def send_order():
    """
    Принимает заказ и отправляет изображение в WhatsApp через Cloud API
    """
    try:
        data = request.json
        required = ['image_base64', 'name', 'contact', 'order_details', 'selected_design']
        for field in required:
            if field not in data:
                return jsonify({'error': f'Missing field: {field}'}), 400
        
        # Проверяем наличие ключей
        if not WHATSAPP_PHONE_ID or not WHATSAPP_TOKEN:
            return jsonify({'error': 'WhatsApp credentials not configured'}), 500
        
        # Извлекаем бинарные данные из base64
        image_base64 = data['image_base64']
        if ',' in image_base64:
            image_base64 = image_base64.split(',')[1]
        image_data = base64.b64decode(image_base64)
        
        # Сохраняем во временный файл
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            tmp.write(image_data)
            tmp_path = tmp.name
        
        # Загружаем медиа в WhatsApp (исправлено: добавлен messaging_product)
        upload_url = f'https://graph.facebook.com/v17.0/{WHATSAPP_PHONE_ID}/media'
        headers = {'Authorization': f'Bearer {WHATSAPP_TOKEN}'}
        
        with open(tmp_path, 'rb') as f:
            files = {'file': (f'{uuid.uuid4()}.png', f, 'image/png')}
            # Важно: добавляем messaging_product в запрос
            data = {'messaging_product': 'whatsapp'}
            upload_resp = requests.post(upload_url, headers=headers, files=files, data=data)
        
        os.unlink(tmp_path)
        
        if upload_resp.status_code != 200:
            return jsonify({'error': f'WhatsApp media upload failed: {upload_resp.text}'}), 500
        
        media_id = upload_resp.json()['id']
        
        # Формируем подпись
        caption = (
            f"📦 *Nouvelle commande*\n\n"
            f"👤 *Nom:* {data['name']}\n"
            f"📱 *Contact:* {data['contact']}\n"
            f"📝 *Détails:*\n{data['order_details']}\n"
            f"✨ *Design choisi:* {data['selected_design']}\n\n"
            f"_En attente de validation par le Chef._"
        )
        
        # Отправляем сообщение с изображением на номер Виктории (исправлено)
        message_url = f'https://graph.facebook.com/v17.0/{WHATSAPP_PHONE_ID}/messages'
        message_body = {
            "messaging_product": "whatsapp",  # обязательно
            "to": "33602353716",  # номер Виктории
            "type": "image",
            "image": {
                "id": media_id,
                "caption": caption
            }
        }
        
        msg_resp = requests.post(message_url, headers=headers, json=message_body)
        
        if msg_resp.status_code != 200:
            return jsonify({'error': f'WhatsApp message send failed: {msg_resp.text}'}), 500
        
        msg_id = msg_resp.json().get('messages', [{}])[0].get('id')
        
        return jsonify({'success': True, 'message_id': msg_id})
        
    except Exception as e:
        print(f"Send order error: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
