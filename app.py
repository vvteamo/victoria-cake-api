import os
import base64
import requests
import time
import logging
from flask import Flask, request, jsonify
from flask_cors import CORS
from PIL import Image, ImageDraw, ImageFont
import io

# --- ИНИЦИАЛИЗАЦИЯ ---
app = Flask(__name__)
CORS(app)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

def log_error(message): logging.error(message)
def log_info(message): logging.info(message)

# --- ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ---
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
WAVESPEED_API_KEY = os.environ.get('WAVESPEED_API_KEY')
WAVESPEED_API_URL = "https://api.wavespeed.ai/api/v3/wavespeed-ai/flux-dev"
FONT_PATH = os.environ.get('FONT_PATH', 'fonts/GreatVibes-Regular.ttf')

# --- СЛОВАРИ ---
EVENT_MAP = {
    "Mariage": "wedding",
    "Anniversaire adulte": "adult birthday",
    "Anniversaire enfant": "child's birthday",
    "Baptême": "baptism",
    "Fête corporative": "corporate party",
    "Autre": "celebration"
}

STYLE_MAP = {
    "Minimaliste": "minimalistic white fondant, clean geometric lines, smooth satin finish",
    "Classique Chic": "classic chic, smooth royal icing, elegant refined piping patterns",
    "Floral / Romantique": "romantic, realistic sugar flowers, cascading petals, velvet texture frosting",
    "Artistique": "artistic, watercolor-style edible paint, abstract patterns, textured buttercream",
    "Sur mesure": "custom designed"
}

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def download_image_as_pil(image_url):
    """Скачивает изображение по URL и возвращает PIL Image."""
    try:
        response = requests.get(image_url, timeout=30)
        if response.status_code == 200:
            return Image.open(io.BytesIO(response.content))
        else:
            log_error(f"Failed to download image: {response.status_code}")
            return None
    except Exception as e:
        log_error(f"Download error: {str(e)}")
        return None

def pil_to_base64(pil_image):
    """Конвертирует PIL Image в base64."""
    buffered = io.BytesIO()
    pil_image.save(buffered, format="PNG")
    image_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
    return f"data:image/png;base64,{image_base64}"

def wait_for_image_pil(result_url, max_attempts=60, delay=2):
    """Опрашивает Wavespeed до готовности изображения, возвращает PIL Image."""
    headers = {'Authorization': f'Bearer {WAVESPEED_API_KEY}'}
    for attempt in range(max_attempts):
        try:
            response = requests.get(result_url, headers=headers)
            if response.status_code == 200:
                result = response.json()
                if isinstance(result, dict) and 'data' in result:
                    data = result['data']
                    status = data.get('status')
                    if status == 'completed':
                        outputs = data.get('outputs', [])
                        if outputs:
                            image_url = outputs[0]
                            return download_image_as_pil(image_url)
                    elif status in ['failed', 'error']:
                        return None
            time.sleep(delay)
        except Exception as e:
            log_error(f"Poll error: {str(e)}")
            time.sleep(delay)
    return None

def generate_parallel_variations(payloads, headers):
    """Запускает две генерации и собирает результаты."""
    task_urls = []
    for payload in payloads:
        response = requests.post(WAVESPEED_API_URL, headers=headers, json=payload)
        if response.status_code == 200:
            result = response.json()
            if isinstance(result, dict) and 'data' in result and 'urls' in result['data']:
                task_urls.append(result['data']['urls'].get('get'))
    
    pil_images = []
    for i, url in enumerate(task_urls):
        image = wait_for_image_pil(url)
        if image:
            pil_images.append(image)
    return pil_images

# --- ОСНОВНАЯ ЛОГИКА: УЛУЧШЕННЫЙ ПРОМПТ И ОБРАБОТКА ТЕКСТА ---

def build_hybrid_prompt(data):
    """Собирает улучшенный промпт."""
    etages_raw = data.get('etages', '1 étage')
    etages = etages_raw.split()[0] if etages_raw else '1'
    style = data.get('style', 'Classique Chic')
    event = data.get('event', 'Mariage')
    wishes = data.get('wishes', '').strip()
    shape_type = data.get('shapeType', 'classic')
    inscription = data.get('inscription', '').strip()

    event_en = EVENT_MAP.get(event, event)
    style_desc = STYLE_MAP.get(style, f"{style} style frosting")

    # Динамический декор под событие
    if event == 'Mariage':
        deco_desc = "decorated with cascading realistic sugar roses, delicate edible pearls, and a thin gold ribbon"
    elif event == 'Anniversaire enfant':
        deco_desc = "decorated with playful colorful sugar stars, edible glitter, and a friendly fondant figure of a rocket and a small astronaut"
    elif event == 'Baptême':
        deco_desc = "decorated with delicate lace patterns, a small edible fondant figure of baby shoes, and soft pastel colors"
    else:
        deco_desc = "decorated with fresh seasonal flowers and an elegant marble effect frosting"

    # Описание места для надписи (Pillow добавит текст позже)
    if inscription:
        text_placement_desc = "On the top tier of the cake, there is a clean, smooth, elegant white fondant plaque (like a small edible scroll) positioned centrally, perfectly ready for an inscription."
    else:
        text_placement_desc = "On top of the cake, there is an elegant gold topper featuring the stylized logo of Victoria Pâtisserie."

    # Логика формы
    shape_desc = ""
    wishes_desc = ""
    if wishes:
        if shape_type != 'classic':
            shape_desc = f"The entire cake is sculpted in the shape of {wishes}. "
        else:
            wishes_desc = f"Incorporating user's specific decoration wishes: {wishes}. "

    # Сборка промпта
    prompt_parts = [
        f"A hyper-realistic photograph of a {etages}-tier {event_en} cake.",
        f"The cake is covered in {style_desc}.",
        shape_desc,
        f"{wishes_desc} {deco_desc}.",
        "placed on a polished marble table.",
        text_placement_desc,
        "Background is a blurred, sunlit view of the Mediterranean Sea and the coastline of Nice, France.",
        "Soft natural daylight, professional food photography, 8k resolution, sharp focus, incredibly detailed textures, cinematic lighting."
    ]
    final_prompt = " ".join(prompt_parts)
    return final_prompt, inscription

def apply_text_postprocessing(pil_image, inscription):
    """Накладывает красивый текст на изображение с помощью Pillow."""
    if not inscription:
        return pil_image

    draw = ImageDraw.Draw(pil_image)
    width, height = pil_image.size

    try:
        # Размер шрифта пропорционален высоте изображения
        font = ImageFont.truetype(FONT_PATH, int(height * 0.06))
    except IOError:
        log_error(f"Font not found at {FONT_PATH}. Using default.")
        font = ImageFont.load_default()

    # Цвет текста (золотой)
    text_color = (212, 175, 55)

    # Используем getbbox() для более точного расчета
    bbox = draw.textbbox((0, 0), inscription, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    # Позиция: по центру, немного выше середины
    x = (width - text_width) / 2
    y = height * 0.3 - text_height / 2

    # Тень для объема
    draw.text((x+3, y+3), inscription, font=font, fill=(0, 0, 0, 128))
    draw.text((x, y), inscription, font=font, fill=text_color)

    return pil_image

def build_hybrid_negative_prompt():
    """Возвращает negative prompt."""
    return (
        "blurry, cartoon, illustration, drawing, painting, deformed, ugly, bad proportions, "
        "plastic texture, toy-like, synthetic, non-edible materials, weird shapes, extra items on cake, "
        "distorted flowers, bad lettering, extra text, symbols, people, hands, faces, animals, "
        "silhouettes, reflections of people, dark shadows, low resolution, bad lighting, "
        "halloween theme, pumpkins, vegetables, fruits (unless specified), strange objects."
    )

# --- ЭНДПОИНТЫ ---

@app.route('/', methods=['GET'])
def index():
    """Корневой маршрут для проверки работоспособности API."""
    return jsonify({
        'service': 'Victoria Cake API',
        'status': 'running',
        'endpoints': ['/generate', '/send-order', '/health'],
        'version': 'hybrid-1.0'
    }), 200

@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.get_json()
        log_info(f"Generate request received.")

        # 1. Сборка промпта
        prompt, inscription = build_hybrid_prompt(data)
        negative_prompt = build_hybrid_negative_prompt()

        headers = {
            'Authorization': f'Bearer {WAVESPEED_API_KEY}',
            'Content-Type': 'application/json'
        }

        # Настройки для генерации
        common_payload = {
            'prompt': prompt,
            'negative_prompt': negative_prompt,
            'size': '1024*1024',
            'num_inference_steps': 35,
            'guidance_scale': 4.5,
            'num_images': 1,
            'seed': -1
        }

        # Два запроса с разными seed для вариативности
        payloads = [common_payload.copy(), common_payload.copy()]
        payloads[1]['seed'] = 12345

        # 2. Генерация двух вариантов
        log_info("Starting parallel image generation...")
        pil_images_raw = generate_parallel_variations(payloads, headers)
        log_info(f"Generated {len(pil_images_raw)} variations.")

        image_base64_list = []

        # 3. Постобработка (наложение текста) для каждого варианта
        for i, pil_image in enumerate(pil_images_raw):
            pil_image_processed = apply_text_postprocessing(pil_image, inscription)
            base64_string = pil_to_base64(pil_image_processed)
            image_base64_list.append(base64_string)

        # 4. Заглушки, если не хватает картинок
        if len(image_base64_list) < 2:
            log_info("Insufficient images from API, using fallback.")
            fallback_base64 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
            while len(image_base64_list) < 2:
                image_base64_list.append(fallback_base64)

        return jsonify({'images': image_base64_list})

    except Exception as e:
        log_error(f"Generate error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/send-order', methods=['POST'])
def send_order():
    try:
        data = request.get_json()
        log_info("Send-order request received.")

        required_fields = ['image_base64', 'name', 'contact', 'order_details', 'selected_design']
        if not all(field in data for field in required_fields):
            missing = [f for f in required_fields if f not in data]
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
        except Exception as e:
            return jsonify({'error': 'Invalid image data'}), 400

        # Формируем сообщение для Telegram
        caption = f"""📦 *Nouvelle commande (Victoria Pâtisserie)*
👤 *Nom Client:* {name}
📱 *Contact:* {contact}
✨ *Design choisi:* {selected_design}
📝 *Détails de la commande:*
{order_details}
_En attente de validation par le Chef._"""

        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        files = {'photo': ('cake_design.png', image_data, 'image/png')}
        payload = {
            'chat_id': TELEGRAM_CHAT_ID,
            'caption': caption,
            'parse_mode': 'Markdown'
        }

        response = requests.post(url, files=files, data=payload)

        if response.status_code == 200:
            return jsonify({'success': True}), 200
        else:
            log_error(f"Telegram API error: {response.status_code} - {response.text}")
            return jsonify({'error': 'Failed to send to Telegram'}), 500

    except Exception as e:
        log_error(f"Send-order error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'running', 'platform': 'Hybrid'}), 200


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
