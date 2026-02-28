from flask import Flask, request, jsonify
from flask_cors import CORS
import wavespeed
import requests
import base64
import os
import tempfile
from deep_translator import GoogleTranslator

app = Flask(__name__)
CORS(app, origins=['*'])

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
    
    # Брендирование: топпер или подложка
    if not hasCustomTopper:
        prompt += ". On top, an elegant gold topper that reads 'Victoria' and 'NICE, FRANCE' below"
    else:
        prompt += ". On the marble base, a subtle gold engraving 'Victoria' and 'NICE, FRANCE'"
    
    prompt += ". Marble table, blurred Mediterranean Sea background, Nice coastline. 8k, sharp focus, detailed texture, soft daylight."
    
    if creative:
        prompt += " Slightly more artistic interpretation."
    
    return prompt

@app.route('/', methods=['GET'])
def home():
    return "API de génération de gâteaux Victoria fonctionne !"

@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.json
        api_key = os.environ.get('WAVESPEED_API_KEY')
        if not api_key:
            return jsonify({'error': 'API key not configured'}), 500
        
        client = wavespeed.Client(
            api_key=api_key,
            max_retries=3,
            max_connection_retries=5,
            retry_interval=1.0
        )
        
        images = []
        
        if 'image_base64' in data:
            # === ВТОРОЙ ПУТЬ: редактирование фото ===
            user_prompt = data.get('wishes', '')  # запрос на любом языке
            if not user_prompt:
                return jsonify({'error': 'Veuillez décrire les modifications souhaitées'}), 400
            
            # --- ПЕРЕВОД НА АНГЛИЙСКИЙ ---
            try:
                translator = GoogleTranslator(source='auto', target='en')
                prompt_en = translator.translate(user_prompt).lower()
                print(f"Original: {user_prompt}")
                print(f"Translated (EN): {prompt_en}")
            except Exception as e:
                prompt_en = user_prompt.lower()
                print(f"Translation failed, using original: {prompt_en}")
            
            # --- Брендирование (обязательное для второго пути) ---
            branding = (
                "IMPORTANT: On the marble cake stand, there MUST be a subtle gold engraving "
                "that clearly reads 'Victoria' and 'NICE, FRANCE' below. The engraving should look like part of the marble, "
                "elegant and refined. This is a mandatory element."
            )
            
            # --- Умеренная сила изменений, чтобы избежать мультяшности ---
            strength = 0.55  # единое значение для всех случаев во втором пути
            
            # --- Формирование промпта на основе анализа переведённого запроса ---
            # Запрос на изменение цвета
            if any(word in prompt_en for word in ['color', 'colour', 'couleur', 'make it', 'turn it']):
                full_prompt = (
                    f"{prompt_en}. IMPORTANT: Change the cake's color as requested. "
                    f"Keep the exact same shape, decorations, and composition. "
                    f"Only the color should change. Do NOT add or remove any decorative elements. "
                    f"Ensure the result is photorealistic, high quality, 8k, detailed texture, NO cartoon, NO artistic interpretation. "
                    f"{branding}"
                )
            # Запрос на добавление элементов
            elif any(word in prompt_en for word in ['add', 'with', 'put', 'place', 'decorate', 'ajouter', 'avec']):
                full_prompt = (
                    f"{prompt_en}. IMPORTANT: Keep the original cake's shape and color exactly the same. "
                    f"Add the new element(s) as requested. The new element should look natural and photorealistic. "
                    f"Do NOT change the existing decorations, do NOT change the cake's color. "
                    f"Ensure the result is photorealistic, high quality, 8k, detailed texture, NO cartoon, NO artistic interpretation. "
                    f"{branding}"
                )
            # Другие запросы
            else:
                full_prompt = (
                    f"{prompt_en}. IMPORTANT: Keep the original cake's design as much as possible. "
                    f"Apply the changes requested. Ensure the result is photorealistic, high quality, 8k, detailed texture, NO cartoon, NO artistic interpretation. "
                    f"{branding}"
                )
            
            # Сохраняем base64 во временный файл
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
                f.write(base64.b64decode(data['image_base64']))
                temp_path = f.name
            
            try:
                # Загружаем фото, получаем URL
                image_url = wavespeed.upload(temp_path)
                
                result = client.run(
                    "wavespeed-ai/z-image/turbo",
                    {
                        "image": image_url,
                        "prompt": full_prompt,
                        "strength": strength
                    }
                )
                
                if isinstance(result, dict) and 'outputs' in result:
                    img_url = result['outputs'][0]
                    img_response = requests.get(img_url)
                    img_response.raise_for_status()
                    base64_image = base64.b64encode(img_response.content).decode('utf-8')
                    data_url = f"data:image/png;base64,{base64_image}"
                    images.append(data_url)
                else:
                    return jsonify({'error': f'Unexpected SDK result: {result}'}), 500
                    
            finally:
                os.unlink(temp_path)
            
        else:
            # === ПЕРВЫЙ ПУТЬ: генерация с нуля ===
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
                    base64_image = base64.b64encode(img_response.content).decode('utf-8')
                    data_url = f"data:image/png;base64,{base64_image}"
                    images.append(data_url)
                else:
                    return jsonify({'error': f'Unexpected SDK result: {result}'}), 500
        
        return jsonify({'images': images})
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
