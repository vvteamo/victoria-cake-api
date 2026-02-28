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

# Получаем API-ключи из переменных окружения
WAVESPEED_API_KEY = os.environ.get('WAVESPEED_API_KEY')
HF_API_KEY = os.environ.get('HF_API_KEY')

if not WAVESPEED_API_KEY:
    print("Warning: WAVESPEED_API_KEY not set")
if not HF_API_KEY:
    print("Warning: HF_API_KEY not set")

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
        prompt += " Slightly more artistic interpretation."
    
    return prompt

def analyze_image_with_hf(image_path):
    """Отправляет изображение в Hugging Face API и получает описание"""
    if not HF_API_KEY:
        raise Exception("HF_API_KEY not configured")
    
    # ИСПРАВЛЕНО: используем работающую модель
    API_URL = "https://api-inference.huggingface.co/models/nlpconnect/vit-gpt2-image-captioning"
    headers = {"Authorization": f"Bearer {HF_API_KEY}"}
    
    with open(image_path, "rb") as f:
        img_data = f.read()
    
    response = requests.post(API_URL, headers=headers, data=img_data, timeout=30)
    
    if response.status_code != 200:
        raise Exception(f"Hugging Face API error: {response.status_code} - {response.text}")
    
    result = response.json()
    # Разные модели возвращают результат в разных форматах
    if isinstance(result, list) and len(result) > 0:
        if 'generated_text' in result[0]:
            return result[0].get('generated_text', '')
        elif isinstance(result[0], dict) and 'caption' in result[0]:
            return result[0].get('caption', '')
    elif isinstance(result, dict) and 'generated_text' in result:
        return result['generated_text']
    
    return str(result)

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
        
        images = []
        
        if 'image_base64' in data:
            # === ВТОРОЙ ПУТЬ ===
            user_prompt = data.get('wishes', '')
            if not user_prompt:
                return jsonify({'error': 'Veuillez décrire les modifications souhaitées'}), 400
            
            # Переводим пожелания
            try:
                translator = GoogleTranslator(source='auto', target='en')
                user_prompt_en = translator.translate(user_prompt)
                print(f"Original: {user_prompt}")
                print(f"Translated: {user_prompt_en}")
            except Exception as e:
                user_prompt_en = user_prompt
                print(f"Translation failed: {e}")
            
            # Сохраняем фото
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
                f.write(base64.b64decode(data['image_base64']))
                temp_path = f.name
            
            try:
                # Анализируем фото
                print("Analyzing image with Hugging Face...")
                image_description = analyze_image_with_hf(temp_path)
                print(f"Description: {image_description}")
                
                # Формируем промпт
                full_prompt = (
                    f"{image_description}. {user_prompt_en}. "
                    f"IMPORTANT: Keep the same cake shape and decorations. "
                    f"Make it photorealistic, high quality, 8k, detailed texture, NO cartoon, NO artistic interpretation. "
                    f"On the marble base, a subtle gold engraving 'Victoria' and 'NICE, FRANCE'. "
                    f"Marble table, blurred Mediterranean Sea background, Nice coastline. "
                    f"Professional food photography, soft daylight, 8k, hyper-realistic."
                )
                print(f"Final prompt: {full_prompt}")
                
                # Генерируем
                result = client.run(
                    "wavespeed-ai/z-image/turbo",
                    {"prompt": full_prompt}
                )
                
                if isinstance(result, dict) and 'outputs' in result:
                    img_url = result['outputs'][0]
                    img_response = requests.get(img_url)
                    img_response.raise_for_status()
                    base64_image = base64.b64encode(img_response.content).decode('utf-8')
                    data_url = f"data:image/png;base64,{base64_image}"
                    images.append(data_url)
                else:
                    return jsonify({'error': f'Unexpected Wavespeed result: {result}'}), 500
                    
            finally:
                os.unlink(temp_path)
            
        else:
            # === ПЕРВЫЙ ПУТЬ ===
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
                    return jsonify({'error': f'Unexpected Wavespeed result: {result}'}), 500
        
        return jsonify({'images': images})
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
