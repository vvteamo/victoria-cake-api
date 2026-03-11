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

# --- СЛОВАРИ ДЛЯ ПЕРЕВОДА ---
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

# --- ПОСТРОЕНИЕ ПРОМПТА (УПРОЩЁННЫЙ) ---
def build_prompt(data):
    """Собирает промпт в зависимости от формы."""
    # Извлекаем параметры
    etages_raw = data.get('etages', '1 étage')
    etages = etages_raw.split()[0] if etages_raw else '1'
    style = data.get('style', 'Classique Chic')
    event = data.get('event', 'Mariage')
    shape_type = data.get('shapeType', 'classic')
    shape_details = data.get('shapeDetails', '').strip()
    wishes = data.get('wishes', '').strip()

    event_en = EVENT_MAP.get(event, event)
    style_desc = STYLE_MAP.get(style, f"{style} style frosting")

    # Базовые части
    base = f"placed on a polished marble table. Background is a blurred, sunlit view of the Mediterranean Sea in Nice, France. Soft natural daylight, professional food photography, 8k resolution, sharp focus, detailed textures."
    topper = "On top of the cake, there is an elegant gold topper featuring the logo of Victoria Pâtisserie."

    # Формируем описание в зависимости от типа формы
    if shape_type == 'classic_circle':
        shape_part = f"A hyper-realistic photograph of a {etages}-tier {event_en} cake, {style_desc}."
    elif shape_type == 'classic_square':
        shape_part = f"A hyper-realistic photograph of a {etages}-tier square {event_en} cake, {style_desc}."
    elif shape_type == 'classic_rectangle':
        shape_part = f"A hyper-realistic photograph of a {etages}-tier rectangular {event_en} cake, {style_desc}."
    elif shape_type == 'number':
        number = shape_details if shape_details else "0"
        shape_part = f"A hyper-realistic cake in the shape of the number {number}, consisting of two separate digits standing side by side on a cake board. The digits are made of cake, covered in {style_desc}."
        topper = ""  # для цифр топпер убираем, чтобы не загромождать
    else:  # other
        desc = shape_details if shape_details else "custom shape"
        shape_part = f"A hyper-realistic photograph of a {etages}-tier {event_en} cake in the shape of {desc}, {style_desc}."

    # Добавляем пожелания (wishes) если есть
    if wishes:
        wishes_part = f" Additional details: {wishes}."
    else:
        wishes_part = ""

    prompt = f"{shape_part} {wishes_part} {base} {topper}".strip()
    return prompt, shape_type

# --- НАЛОЖЕНИЕ ТЕКСТА (PILLOW) ---
def apply_text_postprocessing(pil_image, inscription, shape_type):
    """Накладывает текст клиента на изображение."""
    if not inscription:
        return pil_image

    draw = ImageDraw.Draw(pil_image)
    width, height = pil_image.size

    try:
        font = ImageFont.truetype(FONT_PATH, int(height * 0.06))
    except IOError:
        log_error(f"Font not found at {FONT_PATH}. Using default.")
        font = ImageFont.load_default()

    text_color = (212, 175, 55)  # золотой

    bbox = draw.textbbox((0, 0), inscription, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    # Выбор позиции в зависимости от формы
    if shape_type == 'number':
        # Для цифр – внизу по центру
        x = (width - text_width) / 2
        y = height * 0.85 - text_height / 2
    else:
        # Для классических – на боку верхнего яруса
        x = width * 0.1  # смещение от левого края
        y = height * 0.2  # примерно уровень верхнего яруса

    # Тень для объёма
    draw.text((x+2, y+2), inscription, font=font, fill=(0, 0, 0, 128))
    draw.text((x, y), inscription, font=font, fill=text_color)

    return pil_image

# --- NEGATIVE PROMPT ---
def get_negative_prompt():
    return (
        "blurry, cartoon, illustration, drawing, painting, deformed, ugly, bad proportions, "
        "plastic texture, toy-like, synthetic, non-edible materials, weird shapes, extra items on cake, "
        "people, hands, faces, animals, low resolution, bad lighting"
    )

# --- ЭНДПОИНТ ГЕНЕРАЦИИ ---
@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.get_json()
        log_info(f"Generate request: {data}")

        prompt, shape_type = build_prompt(data)
        negative_prompt = get_negative_prompt()
        inscription = data.get('inscription', '').strip()

        headers = {
            'Authorization': f'Bearer {WAVESPEED_API_KEY}',
            'Content-Type': 'application/json'
        }

        common_payload = {
            'prompt': prompt,
            'negative_prompt': negative_prompt,
            'size': '1024*1024',
            'num_inference_steps': 35,
            'guidance_scale': 4.5,
            'num_images': 1,
            'seed': -1
        }

        # Два варианта с разными seed
        payloads = [common_payload.copy(), common_payload.copy()]
        payloads[1]['seed'] = 12345

        pil_images_raw = generate_parallel_variations(payloads, headers)
        log_info(f"Generated {len(pil_images_raw)} variations.")

        image_base64_list = []
        for i, pil_image in enumerate(pil_images_raw):
            pil_image_processed = apply_text_postprocessing(pil_image, inscription, shape_type)
            base64_string = pil_to_base64(pil_image_processed)
            image_base64_list.append(base64_string)

        # fallback
        if len(image_base64_list) < 2:
            fallback_base64 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
            while len(image_base64_list) < 2:
                image_base64_list.append(fallback_base64)

        return jsonify({'images': image_base64_list})

    except Exception as e:
        log_error(f"Generate error: {str(e)}")
        return jsonify({'error': str(e)}), 500

# --- ЭНДПОИНТ ОТПРАВКИ ЗАКАЗА ---
@app.route('/send-order', methods=['POST'])
def send_order():
    try:
        data = request.get_json()
        log_info("Send-order request received.")

        required = ['image_base64', 'name', 'contact', 'order_details', 'selected_design']
        if not all(field in data for field in required):
            missing = [f for f in required if f not in data]
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
        except:
            return jsonify({'error': 'Invalid image data'}), 400

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
            log_error(f"Telegram API error: {response.text}")
            return jsonify({'error': 'Failed to send to Telegram'}), 500

    except Exception as e:
        log_error(f"Send-order error: {str(e)}")
        return jsonify({'error': str(e)}), 500

# --- НОВЫЙ ЭНДПОИНТ ДЛЯ ЗАГРУЗКИ ФОТО ---
@app.route('/upload-order', methods=['POST'])
def upload_order():
    try:
        # Принимаем multipart/form-data
        name = request.form.get('name')
        contact = request.form.get('contact')
        description = request.form.get('description', '')
        photo = request.files.get('photo')

        if not all([name, contact, photo]):
            return jsonify({'error': 'Missing fields'}), 400

        # Читаем фото в байты
        photo_bytes = photo.read()

        caption = f"""📸 *Nouvelle commande (photo personnelle)*
👤 *Nom Client:* {name}
📱 *Contact:* {contact}
📝 *Description:*
{description}
_En attente de validation par le Chef._"""

        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        files = {'photo': ('photo.jpg', photo_bytes, photo.mimetype)}
        payload = {
            'chat_id': TELEGRAM_CHAT_ID,
            'caption': caption,
            'parse_mode': 'Markdown'
        }

        response = requests.post(url, files=files, data=payload)

        if response.status_code == 200:
            return jsonify({'success': True}), 200
        else:
            log_error(f"Telegram API error: {response.text}")
            return jsonify({'error': 'Failed to send to Telegram'}), 500

    except Exception as e:
        log_error(f"Upload-order error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'running'}), 200

@app.route('/', methods=['GET'])
def index():
    return jsonify({'service': 'Victoria Cake API', 'status': 'running'}), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
