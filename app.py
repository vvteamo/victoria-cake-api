import os
import base64
import requests
import time
import logging
import re
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS
from PIL import Image
import io
from deep_translator import GoogleTranslator

# --- ИНИЦИАЛИЗАЦИЯ ---
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": ["https://vvteamo.github.io", "https://atelier-patisserie.profy.top"]}})

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

# --- СЛОВАРИ ДЛЯ ПЕРЕВОДА И ШАБЛОНИЗАТОРА ---
EVENT_MAP = {
    "Mariage": "wedding",
    "Anniversaire adulte": "adult birthday",
    "Anniversaire enfant": "child's birthday",
    "Baptême": "baptism",
    "Fête corporative": "corporate party",
    "Autre": "celebration"
}

STYLE_MAP = {
    "Minimaliste": "smooth clean fondant, sharp edges, pure minimalist aesthetic, modern elegance",
    "Classique Chic": "classic elegant structure, delicate royal icing piping, timeless luxury, satin ribbon details, haute couture pastry",
    "Floral / Romantique": "adorned with hyperrealistic handcrafted sugar flowers, soft pastel tones, romantic cascading petals, pearls",
    "Artistique": "avant-garde sculptural shapes, hand-painted watercolor textures, edible gold leaf splashes, modern art concept",
    "Sur mesure": "custom bespoke design, highly detailed, unique creative masterpiece"
}

EVENT_TEMPLATES = {
    "Mariage": (
        "{shape_part} Style and texture: {style_desc}. "
        "{details} "
        "Professional wedding photography, soft romantic lighting, set on an elegant reception table, blurred background, 8k resolution, photorealistic. "
        "{topper}"
    ),
    "Anniversaire adulte": (
        "{shape_part} Style and texture: {style_desc}. "
        "{details} "
        "High-end food photography, moody studio lighting, dark elegant background, highly detailed, sophisticated atmosphere. "
        "{topper}"
    ),
    "Anniversaire enfant": (
        "{shape_part} Style: {style_desc}. "
        "{details} "
        "Bright and joyful colors, playful design, fairy-tale atmosphere, sharp focus, vibrant food photography, party setting. "
        "{topper}"
    ),
    "Baptême": (
        "{shape_part} Style and texture: {style_desc}. "
        "{details} "
        "Soft pastel tones, bright airy lighting, elegant pure presentation, hyperrealistic, delicate atmosphere. "
        "{topper}"
    ),
    "Fête corporative": (
        "{shape_part} Style: {style_desc}. "
        "{details} "
        "Clean corporate aesthetic, sharp studio lighting, modern presentation, polished marble table, 8k. "
        "{topper}"
    ),
    "Autre": (
        "{shape_part} Visual style: {style_desc}. "
        "{details} "
        "Cinematic studio lighting, 8k resolution, food photography, placed on a polished marble table. "
        "{topper}"
    )
}

# --- ФУНКЦИИ ---
def escape_markdown(text):
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text

def download_image_as_pil(image_url):
    try:
        response = requests.get(image_url, timeout=30)
        if response.status_code == 200:
            return Image.open(io.BytesIO(response.content))
    except Exception as e:
        log_error(f"Download error: {str(e)}")
    return None

def pil_to_base64(pil_image):
    buffered = io.BytesIO()
    pil_image.save(buffered, format="PNG")
    image_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
    return f"data:image/png;base64,{image_base64}"

def wait_for_image_pil(result_url, max_attempts=60, delay=2):
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
                            return download_image_as_pil(outputs[0])
                    elif status in ['failed', 'error']:
                        return None
            time.sleep(delay)
        except Exception as e:
            time.sleep(delay)
    return None

def generate_parallel_variations(payloads, headers):
    task_urls = []
    for payload in payloads:
        response = requests.post(WAVESPEED_API_URL, headers=headers, json=payload)
        if response.status_code == 200:
            result = response.json()
            if isinstance(result, dict) and 'data' in result and 'urls' in result['data']:
                task_urls.append(result['data']['urls'].get('get'))
    
    pil_images = []
    for url in task_urls:
        image = wait_for_image_pil(url)
        if image:
            pil_images.append(image)
    return pil_images

# --- ВОДЯНОЙ ЗНАК ИЗ ЛОКАЛЬНОГО ФАЙЛА ---
def add_logo_watermark(base_image):
    try:
        logo_path = os.path.join(os.path.dirname(__file__), 'logo.png')
        if not os.path.exists(logo_path):
            return base_image.convert("RGB")
            
        watermark = Image.open(logo_path).convert("RGBA")
        base_width, base_height = base_image.size
        w_width = int(base_width * 0.25)
        w_percent = (w_width / float(watermark.size[0]))
        w_height = int((float(watermark.size[1]) * float(w_percent)))
        watermark = watermark.resize((w_width, w_height), Image.Resampling.LANCZOS)
        
        if base_image.mode != 'RGBA':
            base_image = base_image.convert('RGBA')
            
        position = (40, 40)
        transparent = Image.new('RGBA', base_image.size, (0,0,0,0))
        transparent.paste(base_image, (0,0))
        transparent.paste(watermark, position, mask=watermark)
        return transparent.convert("RGB")
    except Exception as e:
        log_error(f"Ошибка наложения водяного знака: {e}")
    return base_image.convert("RGB")

def remove_emojis(text):
    emoji_pattern = re.compile(
        "["
        "\U0001f600-\U0001f64f"
        "\U0001f300-\U0001f5ff"
        "\U0001f680-\U0001f6ff"
        "\U0001f1e0-\U0001f1ff"
        "\U00002702-\U000027b0"
        "\U000024c2-\U0001f251"
        "]+", flags=re.UNICODE)
    return emoji_pattern.sub(r'', text)

def build_prompt(data):
    etages_raw = data.get('etages', '1 étage')
    etages = etages_raw.split()[0] if etages_raw else '1'
    style = data.get('style', 'Classique Chic')
    event = data.get('event', 'Mariage')
    shape_type = data.get('shapeType', 'classic_circle')
    shape_details = data.get('shapeDetails', '').strip()
    wishes_fr = data.get('wishes', '').strip()
    
    inscription = data.get('inscription', '').strip()
    cleaned_inscription = remove_emojis(inscription).strip()
    
    event_en = EVENT_MAP.get(event, 'celebration')
    style_desc = STYLE_MAP.get(style, STYLE_MAP["Classique Chic"])

    topper = ""
    if not cleaned_inscription:
        topper = "On top of the cake, there is an elegant gold topper with the text 'Victoria'."

    # Заменяем "1-tier" на более понятное ИИ "single tier"
    etages_text = f"{etages}-tier" if etages != "1" else "SINGLE tier"

    if shape_type == 'classic_circle':
        shape_part = f"A hyper-realistic photograph of a {etages_text} {event_en} cake."
    elif shape_type == 'classic_square':
        shape_part = f"A hyper-realistic photograph of a {etages_text} square {event_en} cake."
    elif shape_type == 'classic_rectangle':
        shape_part = f"A hyper-realistic photograph of a {etages_text} rectangular {event_en} cake."
    elif shape_type == 'number':
        number = shape_details if shape_details else "0"
        shape_part = f"A hyper-realistic photograph of a number cake in the shape of the number {number}. The cake is LYING FLAT horizontally on the cake board, tart style, viewed from slightly above. The digits are made of cake layers and cream."
        topper = "" 
    else:
        desc = shape_details if shape_details else "custom shape"
        shape_part = f"A hyper-realistic photograph of a {etages_text} {event_en} cake in the shape of {desc}."

    details_parts = []
    
    if cleaned_inscription:
        details_parts.append(f"The name '{cleaned_inscription}' is elegantly PIPED FLAT directly onto the flat surface of the cake using buttercream (strictly NOT standing up, NOT a topper).")

    if wishes_fr:
        try:
            wishes_en = GoogleTranslator(source='auto', target='en').translate(wishes_fr)
            details_parts.append(f"The cake incorporates: {wishes_en}.")
        except:
            details_parts.append(f"The cake incorporates: {wishes_fr}.")

    # Строгие текстовые команды в промпт
    if shape_type == 'number':
        details_parts.append("FLAT CAKE, ZERO TIERS, NO TIERS, NOT A TIERED CAKE, SINGLE FLAT STRUCTURE.")
    elif etages == "1":
        details_parts.append("EXACTLY ONE TIER CAKE, ONLY ONE LEVEL, ABSOLUTELY NO ADDED TIERS, SINGLE LAYER DESIGN, NOT A MULTI-TIER CAKE.")
    elif etages == "2":
        details_parts.append("EXACTLY TWO TIERS CAKE, ONLY 2 LEVELS, STRICTLY TWO TIERS.")
    elif etages == "3":
        details_parts.append("EXACTLY THREE TIERS CAKE, ONLY 3 LEVELS.")

    details_str = " ".join(details_parts)
    
    wishes_lower_fr = wishes_fr.lower() if wishes_fr else ""
    texture_modifiers = []
    if "minimaliste" in wishes_lower_fr or "minimalist" in wishes_lower_fr:
        texture_modifiers.append("minimalist elegant decor")
    
    texture_modifiers.append("RUSTIC, HIGHLY TEXTURED, detailed icing")
    
    final_modifiers = ", ".join(texture_modifiers)
    if final_modifiers not in details_str:
        details_str += f" {final_modifiers}."

    template = EVENT_TEMPLATES.get(event, EVENT_TEMPLATES["Autre"])
    
    prompt = template.format(
        shape_part=shape_part,
        style_desc=style_desc,
        details=details_str,
        topper=topper
    )

    return " ".join(prompt.split()), shape_type, etages

# --- ДИНАМИЧЕСКИЙ ОТРИЦАТЕЛЬНЫЙ ПРОМПТ ---
def get_negative_prompt(shape_type, etages):
    base_neg = (
        "blurry, cartoon, illustration, drawing, painting, deformed, ugly, bad proportions, "
        "plastic texture, toy-like, synthetic, non-edible materials, weird shapes, extra items on cake, "
        "people, hands, faces, animals, low resolution, bad lighting, no topper unless specified, "
        "no abstract flowers, no fantasy plants, standing numbers, vertical numbers, "
        "floating text, standing text, 3D letters, text topper, text on the board, "
        "no smooth surface, no perfect smooth fondant, no glossy finish"
    )
    
    # Жесткие запреты для ИИ: чего НЕ должно быть на картинке
    if shape_type == 'number':
        base_neg += ", tiered cake, stacked cake, tall cake, multi-tier, 2 tiers, 3 tiers, vertical cake"
    elif etages == "1":
        base_neg += ", multi-tier cake, multiple tiers, 2 tiers, 3 tiers, 4 tiers, tall stacked cake, multi-level"
    elif etages == "2":
        base_neg += ", single tier, 1 tier, flat cake, 3 tiers, 4 tiers"
    elif etages == "3":
        base_neg += ", single tier, 1 tier, 2 tiers, 4 tiers"
        
    return base_neg

@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.get_json()
        prompt, shape_type, etages = build_prompt(data)
        
        # Теперь негативный промпт генерируется в зависимости от выбора этажей
        negative_prompt = get_negative_prompt(shape_type, etages)

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

        payloads = [common_payload.copy(), common_payload.copy()]
        payloads[1]['seed'] = 12345

        pil_images_raw = generate_parallel_variations(payloads, headers)

        image_base64_list = []
        for pil_image in pil_images_raw:
            watermarked_image = add_logo_watermark(pil_image)
            base64_string = pil_to_base64(watermarked_image)
            image_base64_list.append(base64_string)

        if len(image_base64_list) < 2:
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
        
        image_base64 = data.get('image_base64', '')
        name = data.get('name', 'Не указано')
        contact = data.get('contact', 'Не указано')
        date = data.get('date', 'Не указана')
        guests = data.get('guests', 'Не указано')
        order_details = data.get('order_details', '')
        selected_design = data.get('selected_design', 'Дизайн')

        if ',' in image_base64:
            image_base64 = image_base64.split(',')[1]

        image_data = base64.b64decode(image_base64)

        try:
            details_ru = GoogleTranslator(source='auto', target='ru').translate(order_details) if order_details else "Нет описания"
        except:
            details_ru = order_details

        caption = f"""📦 *Новый заказ (Сгенерировано ИИ)*
👤 *Имя клиента:* {name}
📱 *Контакт:* {contact}
👥 *Количество гостей:* {guests}
📅 *Дата мероприятия:* {date}
✨ *Выбранный дизайн:* {selected_design}

📝 *Детали заказа (автоперевод):*
{escape_markdown(details_ru)}

_Ожидает подтверждения Шефом._"""

        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        files = {'photo': ('cake_design.png', image_data, 'image/png')}
        payload = {'chat_id': TELEGRAM_CHAT_ID, 'caption': caption, 'parse_mode': 'Markdown'}

        response = requests.post(url, files=files, data=payload)
        if response.status_code == 200:
            return jsonify({'success': True}), 200
        else:
            return jsonify({'error': 'Failed to send to Telegram'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/upload-order', methods=['POST'])
def upload_order():
    try:
        name = request.form.get('name', 'Не указано')
        contact = request.form.get('contact', 'Не указано')
        guests = request.form.get('guests', 'Не указано')
        date = request.form.get('date', 'Не указана')
        description = request.form.get('description', '')
        photo = request.files.get('photo')

        if not photo:
            return jsonify({'error': 'Missing photo'}), 400

        photo_bytes = photo.read()
        
        try:
            desc_ru = GoogleTranslator(source='auto', target='ru').translate(description) if description else "Нет описания"
        except:
            desc_ru = description
        
        caption = f"""📸 *Новый заказ (Свое фото)*
👤 *Имя клиента:* {name}
📱 *Контакт:* {contact}
👥 *Количество гостей:* {guests}
📅 *Дата мероприятия:* {date}

📝 *Описание (автоперевод):*
{escape_markdown(desc_ru)}

_Ожидает подтверждения Шефом._"""

        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        files = {'photo': ('photo.jpg', photo_bytes, photo.mimetype)}
        payload = {'chat_id': TELEGRAM_CHAT_ID, 'caption': caption, 'parse_mode': 'Markdown'}

        response = requests.post(url, files=files, data=payload)
        if response.status_code == 200:
            return jsonify({'success': True}), 200
        else:
            return jsonify({'error': 'Failed to send to Telegram'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health(): return jsonify({'status': 'running'}), 200

@app.route('/', methods=['GET'])
def index(): return jsonify({'service': 'Victoria Cake API'}), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
