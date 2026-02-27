from flask import Flask, request, jsonify
from flask_cors import CORS
import wavespeed
import requests
import base64
import os

app = Flask(__name__)
CORS(app, origins=['*'])

def build_prompt(data):
    etages = data.get('etages', '1 étage')
    style = data.get('style', 'Classique Chic')
    event = data.get('event', 'Mariage')
    guests = data.get('guests', 6)
    hasCustomTopper = data.get('hasCustomTopper', False)
    inscription = data.get('inscription', '')
    wishes = data.get('wishes', '')
    date = data.get('date', '')
    
    prompt = f"A luxurious {etages} tier wedding cake in {style} style. "
    prompt += f"For a {event} event with {guests} guests. "
    
    if date:
        prompt += f"The cake is needed for {date}. "
    
    if not hasCustomTopper:
        prompt += ("On the top tier, an elegant golden topper stands upright. "
                   "The topper clearly displays the name 'Victoria' in a refined serif font. "
                   "Below the name, finely engraved, reads 'NICE, FRANCE'. "
                   "The topper catches the light, appearing as delicate edible gold. ")
    else:
        prompt += ("On the edge of the marble cake stand, there is a subtle gold engraving "
                   "that reads 'Victoria' in an elegant script. Just below, delicately engraved, "
                   "'NICE, FRANCE'. The engraving looks like it's part of the marble, "
                   "very refined and understated. ")
    
    if inscription:
        prompt += f"On the cake, there is an inscription that says: '{inscription}'. "
    
    if wishes:
        prompt += f"Additional wishes: {wishes}. "
    
    prompt += ("The cake is set on an elegant marble table with a blurred Mediterranean Sea background, "
               "Nice coastline. Professional food photography, soft daylight, 8k resolution, hyper-realistic.")
    
    return prompt

@app.route('/', methods=['GET'])
def home():
    return "API de génération de gâteaux Victoria fonctionne !"

@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.json
        prompt = build_prompt(data)
        print(f"Prompt: {prompt}")
        
        api_key = os.environ.get('WAVESPEED_API_KEY')
        if not api_key:
            return jsonify({'error': 'API key not configured'}), 500
        
        # Прямой вызов wavespeed.run (без создания клиента)
        output = wavespeed.run(
            "wavespeed-ai/z-image/turbo",
            {"input": prompt}
        )
        
        # Получаем URL изображения из ответа
        # Формат ответа может отличаться, пробуем разные варианты
        if isinstance(output, dict) and "outputs" in output:
            image_url = output["outputs"][0]
        elif isinstance(output, dict) and "images" in output:
            image_url = output["images"][0]
        elif isinstance(output, str):
            image_url = output
        else:
            return jsonify({'error': 'Unexpected response format'}), 500
        
        # Скачиваем изображение
        img_response = requests.get(image_url)
        img_response.raise_for_status()
        
        # Конвертируем в base64 для отправки на фронтенд
        base64_image = base64.b64encode(img_response.content).decode('utf-8')
        data_url = f"data:image/png;base64,{base64_image}"
        
        return jsonify({'images': [data_url, data_url]})
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
