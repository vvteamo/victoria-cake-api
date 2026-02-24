from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import base64
import os
from datetime import datetime, timedelta

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
        
        # Пробуем разные эндпоинты WaveSpeed (по очереди)
        endpoints = [
            'https://api.wavespeed.ai/v1/z-image-turbo/generate',
            'https://api.wavespeed.ai/v1/generate',
            'https://api.wavespeed.ai/v1/images/generate',
            'https://api.wavespeed.ai/generate'
        ]
        
        last_error = None
        for endpoint in endpoints:
            try:
                response = requests.post(
                    endpoint,
                    headers={
                        'Authorization': f'Bearer {api_key}',
                        'Content-Type': 'application/json'
                    },
                    json={
                        'prompt': prompt,
                        'size': 1024,
                        'output_format': 'png',
                        'enable_sync_mode': True
                    },
                    timeout=10
                )
                
                if response.status_code == 200:
                    image_data = response.content
                    base64_image = base64.b64encode(image_data).decode('utf-8')
                    data_url = f"data:image/png;base64,{base64_image}"
                    return jsonify({'images': [data_url, data_url]})
                else:
                    last_error = f"Endpoint {endpoint} returned {response.status_code}"
                    continue
            except Exception as e:
                last_error = f"Endpoint {endpoint} error: {str(e)}"
                continue
        
        return jsonify({'error': f'All endpoints failed. Last error: {last_error}'}), 500
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
