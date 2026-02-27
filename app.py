from flask import Flask, request, jsonify
from flask_cors import CORS
import wavespeed
import requests
import base64
import os

app = Flask(__name__)
CORS(app, origins=['*'])

def build_prompt(data):
    # ... (функция build_prompt, она у тебя уже есть, можешь оставить как есть)
    # (я не буду копировать её целиком, чтобы не загромождать, но она должна быть)
    # Важно: в функции должны быть поля etages, style, event, guests, hasCustomTopper, inscription, wishes, date
    # и возвращать prompt
    # Убедись, что у тебя есть обработка поля date

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
        
        client = wavespeed.Client(api_key=api_key)
        result = client.run(
            model="wavespeed-ai/z-image-turbo",
            inputs={"prompt": prompt}
        )
        
        # result может быть URL или base64
        if isinstance(result, str) and result.startswith('http'):
            img_response = requests.get(result)
            img_response.raise_for_status()
            image_data = img_response.content
        elif isinstance(result, bytes):
            image_data = result
        else:
            image_data = str(result).encode()
        
        base64_image = base64.b64encode(image_data).decode('utf-8')
        data_url = f"data:image/png;base64,{base64_image}"
        return jsonify({'images': [data_url, data_url]})
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
