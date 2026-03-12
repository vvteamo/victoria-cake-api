import os
import base64
import requests
import time
import logging
import re
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS
# Для конвертации base64 нам все еще нужны Image и io
from PIL import Image
import io
from deep_translator import GoogleTranslator

# --- ИНИЦИАЛИЗАЦИЯ ---
app = Flask(__name__)
# Разрешаем запросы только с твоего сайта (CORS для безопасности)
CORS(app, resources={r"/generate": {"origins": "https://vvteamo.github.io"}})

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
# ПУТЬ К ШРИФТУ БОЛЬШЕ НЕ НУЖЕН

# --- СЛОВАРИ ДЛЯ ПЕРЕВОДА И ШАБЛОНИЗАТОРА ---
EVENT_MAP = {
    "Mariage": "wedding",
    "Anniversaire adulte": "adult birthday",
    "Anniversaire enfant": "child's birthday",
    "Baptême": "baptism",
    "Fête corporative": "corporate party",
    "Autre": "celebration"
}

# Обновленные, детализированные стили для нейросети
STYLE_MAP = {
    "Minimaliste": "smooth clean fondant, sharp edges, pure minimalist aesthetic, modern elegance",
    "Classique Chic": "classic elegant structure, delicate royal icing piping, timeless luxury, satin ribbon details, haute couture pastry",
    "Floral / Romantique": "adorned with hyperrealistic handcrafted sugar flowers, soft pastel tones, romantic cascading petals, pearls",
    "Artistique": "avant-garde sculptural shapes, hand-painted watercolor textures, edible gold leaf splashes, modern art concept",
    "Sur mesure": "custom bespoke design, highly detailed, unique creative masterpiece"
}

# ШАБЛОНЫ (Скелеты) для разных событий
EVENT_TEMPLATES = {
    "Mariage": (
        "{shape_part} Style and texture: {style_desc}. "
        "{details} "
        "Professional wedding photography, soft romantic lighting, set on an elegant reception table, blurred background of the Mediterranean Sea, 8k resolution, photorealistic. "
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

# --- ФУНКЦИЯ ЭКРАНИРОВАНИЯ ТЕКСТА ДЛЯ TELEGRAM ---
def escape_markdown(text):
    """Экранирует специальные символы Markdown, чтобы Telegram не ломался."""
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text

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

# --- ПАРСИНГ ПОЖЕЛАНИЙ ---
def parse_wishes(wishes):
    """Превращает свободный текст на французском в структурированные инструкции на английском."""
    parsed = {
        'color': '',
        'decor': [],
        'ribbons': '',
        'flavor': '',
        'special': wishes
    }
    
    if not wishes:
        return parsed
    
    wishes_lower = wishes.lower()
    
    # Ищем цвет
    color_map = {
        'lavande': 'lavender',
        'violet': 'purple',
        'lilas': 'lilac',
        'menthe': 'mint green',
        'vert': 'green',
        'rose': 'pink',
        'blanc': 'white',
        'jaune': 'yellow',
        'rouge': 'red',
        'bleu': 'blue',
        'or': 'gold',
        'argent': 'silver'
    }
    
    for fr_color, en_color in color_map.items():
        if fr_color in wishes_lower:
            parsed['color'] = en_color
            break
    
    # Ищем ленты
    ribbon_keywords = ['ruban', 'rubans', 'satin', 'nœud', 'neoud', 'bow']
    if any(keyword in wishes_lower for keyword in ribbon_keywords):
        parsed['ribbons'] = 'with elegant satin ribbons tied in a bow at the base'
    
    # Ищем конкретные растения
    if 'lavande' in wishes_lower:
        parsed['decor'].append('fresh sprigs of lavender')
    if 'menthe' in wishes_lower:
        parsed['decor'].append('fresh mint leaves')
    if 'rose' in wishes_lower and 'couleur' not in wishes_lower:
        parsed['decor'].append('fresh roses')
    if 'fleurs' in wishes_lower:
        parsed['decor'].append('fresh seasonal flowers')
    
    return parsed

# --- ПОСТРОЕНИЕ ПРОМПТА (ОБНОВЛЕНО: ТЕКСТ ДОВЕРЯЕМ ИИ) ---
def remove_emojis(text):
    """Удаляет эмодзи из строки перед передачей в промпт ИИ."""
    emoji_pattern = re.compile(
        "["
        "\U0001f600-\U0001f64f"  # emoticons
        "\U0001f300-\U0001f5ff"  # symbols & pictographs
        "\U0001f680-\U0001f6ff"  # transport & map symbols
        "\U0001f1e0-\U0001f1ff"  # flags (iOS)
        "\U00002702-\U000027b0"
        "\U000024c2-\U0001f251"
        "]+", flags=re.UNICODE)
    return emoji_pattern.sub(r'', text)

def build_prompt(data):
    """Собирает промпт с использованием шаблонизатора и распарсенных данных."""
    etages_raw = data.get('etages', '1 étage')
    etages = etages_raw.split()[0] if etages_raw else '1'
    style = data.get('style', 'Classique Chic')
    event = data.get('event', 'Mariage')
    shape_type = data.get('shapeType', 'classic_circle')
    shape_details = data.get('shapeDetails', '').strip()
    wishes_fr = data.get('wishes', '').strip()
    
    # Чистим текст клиента от эмодзи перед передачей в ИИ
    inscription = data.get('inscription', '').strip()
    cleaned_inscription = remove_emojis(inscription).strip()
    
    event_en = EVENT_MAP.get(event, 'celebration')
    style_desc = STYLE_MAP.get(style, STYLE_MAP["Classique Chic"])
    wishes_lower_fr = wishes_fr.lower() if wishes_fr else ""

    # Парсим пожелания (вытаскиваем цвета, ленты, растения)
    parsed = parse_wishes(wishes_fr) if wishes_fr else {}

    # 1. Логотип (топпер) - оставляем ИИ
    topper = "On top of the cake, there is an elegant gold topper with the text 'Victoria'."

    # 2. База формы (shape_part)
    if shape_type == 'classic_circle':
        shape_part = f"A hyper-realistic photograph of a {etages}-tier {event_en} cake."
    elif shape_type == 'classic_square':
        shape_part = f"A hyper-realistic photograph of a {etages}-tier square {event_en} cake."
    elif shape_type == 'classic_rectangle':
        shape_part = f"A hyper-realistic photograph of a {etages}-tier rectangular {event_en} cake."
    elif shape_type == 'number':
        number = shape_details if shape_details else "0"
        shape_part = f"A hyper-realistic cake in the shape of the number {number}, consisting of two separate digits standing side by side on a cake board. The digits are made of cake."
        topper = "" # Для цифр топпер обычно не нужен
    else:
        desc = shape_details if shape_details else "custom shape"
        shape_part = f"A hyper-realistic photograph of a {etages}-tier {event_en} cake in the shape of {desc}."

    # 3. УМНЫЙ ПАРСИНГ ДЕТАЛЕЙ (details)
    details_parts = []
    
    # 3.1. Обработка цвета frosting
    if parsed and parsed.get('color'):
        details_parts.append(f"The cake has a textured {parsed['color']}-colored buttercream frosting with visible piping.")
    
    # 3.2. Обработка НАДПИСИ (ФИЗИЧЕСКИ НА ТОРТЕ)
    if cleaned_inscription:
        # ИИ напишет этот текст шоколадным курсивом прямо на ярусе
        details_parts.append(f"The name '{cleaned_inscription}' is elegantly written in chocolate script on the cake.")

    # 3.3. Обработка конкретных растений (если нашли через парсер)
    if parsed and parsed.get('decor'):
        decor_str = " and ".join(parsed['decor'])
        details_parts.append(f"The cake is decorated with {decor_str} placed on top and around the base.")
    elif wishes_fr and not parsed.get('decor'):
        # Если не нашли конкретных растений, умно переводим сырой текст целиком
        try:
            wishes_en = GoogleTranslator(source='auto', target='en').translate(wishes_fr)
            details_parts.append(f"The cake incorporates: {wishes_en}.")
        except:
            details_parts.append(f"The cake incorporates: {wishes_fr}.")

    # 3.4. Обработка текстуры
    if wishes_lower_fr and ('crème' in wishes_lower_fr or 'creme' in wishes_lower_fr or 'décor' in wishes_lower_fr or 'decor' in wishes_lower_fr):
        details_parts.append("The cake has decorative piped buttercream borders and swirls.")

    # 3.5. Обработка лент
    if parsed and parsed.get('ribbons'):
        details_parts.append(parsed['ribbons'])

    details_str = " ".join(details_parts)
    
    # 3.6. Обязательный модификатор текстуры крема и минимализма
    texture_modifiers = []
    if "minimaliste" in wishes_lower_fr or "minimalist" in wishes_lower_fr:
        texture_modifiers.append("minimalist elegant decor")
    
    texture_modifiers.append("RUSTIC, HIGHLY TEXTURED, detailed icing")
    
    final_modifiers = ", ".join(texture_modifiers)
    if final_modifiers not in details_str:
        details_str += f" {final_modifiers}."

    # 4. ШАБЛОНИЗАЦИЯ: выбираем скелет промпта в зависимости от события
    template = EVENT_TEMPLATES.get(event, EVENT_TEMPLATES["Autre"])
    
    # Вставляем все наши кусочки в шаблон
    prompt = template.format(
        shape_part=shape_part,
        style_desc=style_desc,
        details=details_str,
        topper=topper
    )

    # Убираем лишние двойные пробелы
    prompt = " ".join(prompt.split())
    
    log_info(f"Generated structured prompt with built-in text: {prompt}")
    return prompt, shape_type

# --- НАЛОЖЕНИЕ ТЕКСТА БОЛЬШЕ НЕ НУЖНО ( Pillow функция удалена) ---

# --- NEGATIVE PROMPT ---
def get_negative_prompt():
    return (
        "blurry, cartoon, illustration, drawing, painting, deformed, ugly, bad proportions, "
        "plastic texture, toy-like, synthetic, non-edible materials, weird shapes, extra items on cake, "
        "people, hands, faces, animals, low resolution, bad lighting, no topper unless specified, "
        "no logo except text 'Victoria', no abstract flowers, no fantasy plants, "
        "no smooth surface, no perfect smooth fondant, no glossy finish"
    )

# --- ГЕНЕРАЦИЯ ---
@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.get_json()
        log_info("Generate request received.")

        prompt, shape_type = build_prompt(data)
        negative_prompt = get_negative_prompt()
        # НАДПИСЬ БОЛЬШЕ НЕ ЗАПРАШИВАЕМ, ОНА УЖЕ В build_prompt ЧЕРЕЗ cleaned_inscription

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
        log_info(f"Generated {len(pil_images_raw)} variations.")

        image_base64_list = []
        for pil_image in pil_images_raw:
            # Изображение, полученное от Wavespeed, уже содержит текст
            base64_string = pil_to_base64(pil_image)
            image_base64_list.append(base64_string)

        if len(image_base64_list) < 2:
            fallback_base64 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
            while len(image_base64_list) < 2:
                image_base64_list.append(fallback_base64)

        return jsonify({'images': image_base64_list})

    except Exception as e:
        log_error(f"Generate error: {str(e)}")
        return jsonify({'error': str(e)}), 500

# --- ОТПРАВКА ЗАКАЗА (ПУТЬ А) ---
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

        # Экранируем спецсимволы Markdown
        safe_order_details = escape_markdown(order_details)

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
{safe_order_details}
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

# --- ЗАГРУЗКА ФОТО (ПУТЬ Б) ---
@app.route('/upload-order', methods=['POST'])
def upload_order():
    try:
        name = request.form.get('name')
        contact = request.form.get('contact')
        guests = request.form.get('guests')
        date = request.form.get('date')
        description = request.form.get('description', '')
        photo = request.files.get('photo')

        if not all([name, contact, guests, date, photo]):
            return jsonify({'error': 'Missing required fields'}), 400

        try:
            if int(guests) < 6:
                return jsonify({'error': 'Minimum 6 guests'}), 400
        except:
            return jsonify({'error': 'Invalid guests number'}), 400

        try:
            event_date = datetime.strptime(date, '%Y-%m-%d').date()
            min_date = datetime.now().date() + timedelta(days=2)
            if event_date < min_date:
                return jsonify({'error': 'Date must be at least 2 days in advance'}), 400
        except:
            return jsonify({'error': 'Invalid date format'}), 400

        photo_bytes = photo.read()
        safe_description = escape_markdown(description)

        caption = f"""📸 *Nouvelle commande (photo personnelle)*
👤 *Nom Client:* {name}
📱 *Contact:* {contact}
👥 *Nombre d'invités:* {guests}
📅 *Date de l'événement:* {date}
📝 *Description:*
{safe_description}
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
