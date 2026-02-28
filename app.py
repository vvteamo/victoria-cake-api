from flask import Flask, request, jsonify
from flask_cors import CORS
import wavespeed
import requests
import base64
import os
import tempfile
from transformers import pipeline
from PIL import Image

app = Flask(__name__)
CORS(app, origins=['*'])

# Инициализируем модель для распознавания изображений (загружается один раз при старте)
print("Loading image captioning model...")
captioner = pipeline("image-to-text", model="Salesforce/blip-image-captioning-base")
print("Model loaded successfully!")

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

def analyze_image(image_path):
    """
    Анализирует изображение и возвращает текстовое описание
    """
    try:
        image = Image.open(image_path)
        result = captioner(image)
        description = result[0]['generated_text']
        return description
    except Exception as e:
        print(f"Error analyzing image: {e}")
        return None

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
            # === ВТОРОЙ ПУТЬ: анализ фото + генерация с нуля ===
            user_prompt = data.get('wishes', '')
            if not user_prompt:
                return jsonify({'error': 'Veuillez décrire les modifications souhaitées'}), 400
            
            # Сохраняем base64 во временный файл
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
                f.write(base64.b64decode(data['image_base64']))
                temp_path = f.name
            
            try:
                # ШАГ 1: Анализируем изображение
                print("Analyzing reference image...")
                image_description = analyze_image(temp_path)
                if not image_description:
                    return jsonify({'error': 'Failed to analyze the reference image'}), 500
                print(f"Image description: {image_description}")
                
                # ШАГ 2: Формируем промпт для генерации
                # Берём описание изображения и добавляем пожелания пользователя
                full_prompt = f"{image_description}. {user_prompt}. IMPORTANT: Keep the same cake shape and decorations. Make it photorealistic, high quality, 8k, detailed texture, NO cartoon, NO artistic interpretation."
                
                # Добавляем брендирование (как в первом пути)
                full_prompt += " On the marble base, a subtle gold engraving 'Victoria' and 'NICE, FRANCE'"
                full_prompt += ". Marble table, blurred Mediterranean Sea background, Nice coastline. Professional food photography, soft daylight, 8k, hyper-realistic."
                
                print(f"Final generation prompt: {full_prompt}")
                
                # ШАГ 3: Генерируем новое изображение (первый путь)
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
                    return jsonify({'error': f'Unexpected SDK result: {result}'}), 500
                    
            finally:
                os.unlink(temp_path)
            
        else:
            # === ПЕРВЫЙ ПУТЬ: генерация с нуля (без изменений) ===
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
