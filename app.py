from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import base64
import os

app = Flask(__name__)
CORS(app, origins=['*'])

def build_prompt(data):
    print("=== BUILDING PROMPT ===")
    print(f"Input data: {data}")
    
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
    
    print(f"Final prompt: {prompt}")
    return prompt

@app.route('/', methods=['GET'])
def home():
    print("=== HOME PAGE ACCESSED ===")
    return "API de génération de gâteaux Victoria fonctionne !"

@app.route('/generate', methods=['POST'])
def generate():
    print("=== GENERATE ENDPOINT CALLED ===")
    try:
        # Шаг 1: Получаем данные
        print("Step 1: Getting JSON data")
        data = request.json
        print(f"Received data: {data}")
        
        # Шаг 2: Строим промпт
        print("Step 2: Building prompt")
        prompt = build_prompt(data)
        
        # Шаг 3: Проверяем API ключ
        print("Step 3: Checking API key")
        api_key = os.environ.get('WAVESPEED_API_KEY')
        print(f"API key present: {'Yes' if api_key else 'No'}")
        if not api_key:
            print("ERROR: API key not configured")
            return jsonify({'error': 'API key not configured'}), 500
        
        # Шаг 4: Отправляем запрос к WaveSpeed
        print("Step 4: Sending request to WaveSpeed")
        print(f"Using endpoint: https://api.wavespeed.ai/v1/z-image-turbo/generate")
        
        response = requests.post(
            'https://api.wavespeed.ai/v1/z-image-turbo/generate',
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
            timeout=30
        )
        
        print(f"WaveSpeed response status: {response.status_code}")
        print(f"WaveSpeed response headers: {dict(response.headers)}")
        
        if response.status_code != 200:
            print(f"WaveSpeed error response: {response.text[:200]}")
            return jsonify({'error': f'WaveSpeed error: {response.text}'}), response.status_code
        
        # Шаг 5: Обрабатываем ответ
        print("Step 5: Processing WaveSpeed response")
        print(f"Response content type: {response.headers.get('content-type')}")
        print(f"Response size: {len(response.content)} bytes")
        
        image_data = response.content
        base64_image = base64.b64encode(image_data).decode('utf-8')
        data_url = f"data:image/png;base64,{base64_image}"
        
        print("Step 6: Success! Returning images")
        return jsonify({'images': [data_url, data_url]})
        
    except requests.exceptions.Timeout:
        print("ERROR: Request to WaveSpeed timed out")
        return jsonify({'error': 'Request to WaveSpeed timed out'}), 504
    except requests.exceptions.ConnectionError as e:
        print(f"ERROR: Connection error: {str(e)}")
        return jsonify({'error': f'Connection error: {str(e)}'}), 502
    except Exception as e:
        print(f"ERROR: Unexpected error: {str(e)}")
        print(f"Error type: {type(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting server on port {port}")
    app.run(host='0.0.0.0', port=port)
