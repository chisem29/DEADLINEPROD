import os
import time

import requests
from dotenv import load_dotenv

class Task:
    def __init__(self):
        load_dotenv()
        self.folder_id = os.getenv("YANDEX_FOLDER_ID")
        self.api_key = os.getenv("YANDEX_API_KEY")
        self.gpt_model = 'yandexgpt-32k'
        self.system_prompt = """Представь, что ты профессионал по планированию времени. Твоя задача - это отвечать сколько времени уйдет на задачу по ее названию. В твоем ответе количество минут должно быть целым ровным числом, без никаких промежутков.Твой ответ должен быть в следующем формате: Данная задача займет какое-то количество минут. Хотите изменить?"""

    def get_answer(self, user_prompt, system_prompt="""Представь, что ты профессионал по планированию времени. Твоя задача - это отвечать сколько времени уйдет на задачу по ее названию. В твоем ответе количество минут должно быть целым ровным числом, без никаких промежутков.Твой ответ должен быть в следующем формате: Данная задача займет какое-то количество минут. Хотите изменить?"""):
        self.system_prompt = system_prompt
        body = {
            'modelUri': f'gpt://{self.folder_id}/{self.gpt_model}',
            'completionOptions': {'stream': False, 'temperature': 0.3, 'maxTokens': 2000},
            'messages': [
                {'role': 'system', 'text': self.system_prompt},
                {'role': 'user', 'text': user_prompt},
            ],
        }
        url = 'https://llm.api.cloud.yandex.net/foundationModels/v1/completionAsync'
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Api-Key {self.api_key}'
        }

        response = requests.post(url, headers=headers, json=body)
        operation_id = response.json().get('id')

        url = f"https://llm.api.cloud.yandex.net:443/operations/{operation_id}"
        headers = {"Authorization": f"Api-Key {self.api_key}"}

        while True:
            response = requests.get(url, headers=headers)
            done = response.json()["done"]
            if done:
                break
            time.sleep(2)

        data = response.json()
        answer = data['response']['alternatives'][0]['message']['text']
        return answer


