from flask import Flask, request, jsonify
from flask_cors import CORS
import os

app = Flask(__name__)
CORS(app, origins=['*'])

def build_prompt(data):
    # Эта функция пока просто возвращает тестовую строку
    return "Test prompt from simplified app"

@app.route('/', methods=['GET'])
def home():
    return "API de génération de gâteaux Victoria fonctionne (version simplifiée) !"

@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.json
        prompt = build_prompt(data)
        print(f"Prompt: {prompt}")

        # Возвращаем тестовую картинку (маленький прозрачный пиксель)
        test_image_base64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        data_url = f"data:image/png;base64,{test_image_base64}"

        return jsonify({'images': [data_url, data_url]})

    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
