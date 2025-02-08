import logging
import os
import subprocess
import speech_recognition as sr


def convert_ogg_to_wav(input_filename: str, output_filename: str):
    command = [r"C:\Users\gladk_cegft4n\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg.Essentials_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-7.1-essentials_build\bin\ffmpeg.exe", "-y", "-i", input_filename, output_filename]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        err = result.stderr.decode()
        logging.error(f"Ошибка конвертации: {err}")
        raise Exception("Конвертация файла не удалась")
    else:
        logging.info("Конвертация завершена успешно.")

def recognize_voice(input_filename: str) -> str:
    base, ext = os.path.splitext(input_filename)
    if ext.lower() == ".ogg":
        wav_filename = base + ".wav"
        convert_ogg_to_wav(input_filename, wav_filename)
    else:
        wav_filename = input_filename

    recognizer = sr.Recognizer()
    try:
        with sr.AudioFile(wav_filename) as source:
            audio_data = recognizer.record(source)
    except Exception as e:
        logging.error(f"Ошибка чтения аудиофайла: {e}")
        return None

    try:
        recognized_text = recognizer.recognize_google(audio_data, language="ru-RU")
        return recognized_text
    except sr.UnknownValueError:
        logging.error("Речь не распознана.")
    except sr.RequestError as e:
        logging.error(f"Ошибка запроса к сервису распознавания: {e}")
    return None