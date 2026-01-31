#!/usr/bin/env python3
"""
LUMINA Media Downloader - Local Server with yt-dlp Backend
Использует yt-dlp для скачивания видео вместо Cobalt API
"""

import os
import json
import subprocess
import re
import uuid
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import threading
import webbrowser
import time
import sys

# Папка для скачивания видео
DOWNLOADS_DIR = Path(__file__).parent / 'downloads'
DOWNLOADS_DIR.mkdir(exist_ok=True)


def check_yt_dlp():
    """Проверка наличия yt-dlp, установка/обновление если необходимо"""
    try:
        result = subprocess.run(['yt-dlp', '--version'], capture_output=True, check=True, text=True)
        version = result.stdout.strip()
        print(f"[INFO] yt-dlp уже установлен: {version}")
        
        # Обновляем yt-dlp до последней версии (YouTube часто требует свежую версию)
        print("[INFO] Обновляем yt-dlp до последней версии...")
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--upgrade', 'yt-dlp', '-q'], check=False)
        
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("[INFO] Установка yt-dlp...")
        try:
            subprocess.run([sys.executable, '-m', 'pip', 'install', 'yt-dlp', '-q'], check=True)
            print("[SUCCESS] yt-dlp успешно установлен")
            return True
        except subprocess.CalledProcessError:
            print("[ERROR] Не удалось установить yt-dlp")
            return False


class LUMINARequestHandler(SimpleHTTPRequestHandler):
    """Обработчик HTTP запросов с поддержкой yt-dlp скачивания"""

    def do_GET(self):
        """Обработка GET запросов"""
        if self.path == '/':
            self.path = '/index.html'
        elif self.path.startswith('/downloads/'):
            # Скачивание файла из папки downloads
            filename = self.path.replace('/downloads/', '')
            filepath = DOWNLOADS_DIR / filename
            
            if filepath.exists() and filepath.is_file():
                self.send_response(200)
                self.send_header('Content-type', 'video/mp4')
                self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
                self.send_header('Content-Length', os.path.getsize(filepath))
                self.end_headers()
                
                with open(filepath, 'rb') as f:
                    self.wfile.write(f.read())
                
                # Удаляем файл после скачивания
                try:
                    os.remove(filepath)
                    print(f"[CLEANUP] Удален файл: {filename}")
                except Exception as e:
                    print(f"[CLEANUP] Ошибка при удалении: {e}")
                return
            else:
                self.send_error(404)
                return
        
        return super().do_GET()

    def do_POST(self):
        """Обработка POST запросов к API"""
        if self.path == '/api/download':
            self.handle_yt_dlp_download()
        else:
            self.send_error(404)

    def handle_yt_dlp_download(self):
        """Скачивание видео через yt-dlp"""
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        
        try:
            # Парсим JSON тело запроса
            data = json.loads(body.decode('utf-8'))
            url = data.get('url')
            
            if not url:
                self.send_json_response({'error': 'URL not provided'}, 400)
                return

            print(f"[YT-DLP] Processing: {url}")
            
            # Сначала получаем информацию о видео
            try:
                info_result = subprocess.run(
                    ['yt-dlp', '-j', '--no-warnings', url],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if info_result.returncode != 0:
                    error_msg = info_result.stderr or 'Failed to get video info'
                    print(f"[YT-DLP] Error: {error_msg}")
                    self.send_json_response({
                        'status': 'error',
                        'error': error_msg
                    }, 400)
                    return
                
                video_info = json.loads(info_result.stdout)
                
                # Подготовляем метаданные
                title = video_info.get('title', 'video')
                duration = video_info.get('duration', 0)
                thumbnail = video_info.get('thumbnail', '')
                ext = video_info.get('ext', 'mp4')
                
                # Генерируем безопасное имя файла (UUID + расширение)
                # Используем UUID чтобы избежать проблем с кириллицей и спецсимволами
                safe_filename = f"{uuid.uuid4().hex}.{ext}"
                filename = safe_filename  # Это имя для ответа клиенту
                filepath = DOWNLOADS_DIR / safe_filename
                
                print(f"[YT-DLP] Title: {title}")
                print(f"[YT-DLP] Duration: {duration}s")
                print(f"[YT-DLP] Downloading to: {filepath}")
                
                # Скачиваем видео с лучшими опциями для YouTube
                # Формат: bestvideo + bestaudio = наилучшее качество
                download_result = subprocess.run(
                    [
                        'yt-dlp',
                        '-f', 'bestvideo+bestaudio/best',  # Лучшее видео + аудио, в текение best
                        '-o', str(filepath),
                        '--no-warnings',
                        '--socket-timeout', '30',
                        '--no-part',  # Не создавать .part файлы
                        '--quiet',  # Меньше вывода
                        '--merge-output-format', 'mp4',  # Объединяем в mp4
                        url
                    ],
                    capture_output=True,
                    text=True,
                    timeout=600  # 10 минут для скачивания
                )
                
                print(f"[YT-DLP] Return code: {download_result.returncode}")
                if download_result.stderr:
                    print(f"[YT-DLP] STDERR: {download_result.stderr[:200]}")
                if download_result.stdout:
                    print(f"[YT-DLP] STDOUT: {download_result.stdout[:200]}")
                
                if download_result.returncode != 0:
                    error_msg = download_result.stderr or download_result.stdout or 'Download failed'
                    print(f"[YT-DLP] Download error: {error_msg}")
                    self.send_json_response({
                        'status': 'error',
                        'error': error_msg
                    }, 400)
                    return
                
                # Даем небольшую задержку чтобы файл полностью записался
                time.sleep(1)
                
                # Проверяем что файл существует
                if not filepath.exists():
                    print(f"[YT-DLP] File not found after download: {filepath}")
                    self.send_json_response({
                        'status': 'error',
                        'error': 'File was not created'
                    }, 400)
                    return
                
                # Проверяем размер несколько раз (может быть задержка записи)
                file_size = os.path.getsize(filepath)
                for attempt in range(3):
                    if file_size > 0:
                        break
                    print(f"[YT-DLP] File size check attempt {attempt + 1}: {file_size} bytes, retrying...")
                    time.sleep(0.5)
                    file_size = os.path.getsize(filepath)
                
                # Проверяем что файл не пустой
                if file_size == 0:
                    try:
                        filepath.unlink()  # Удаляем пустой файл
                    except:
                        pass
                    print(f"[YT-DLP] Download failed: file is empty")
                    self.send_json_response({
                        'status': 'error',
                        'error': 'Downloaded file is empty. The video might be restricted or unavailable. Try another link.'
                    }, 400)
                    return
                
                print(f"[YT-DLP] Download complete! Size: {file_size} bytes")
                
                # Формируем ответ с информацией о видео и ссылкой на скачивание
                response_data = {
                    'status': 'success',
                    'title': title,
                    'duration': duration,
                    'thumbnail': thumbnail,
                    'filesize': file_size,
                    'filename': filename,
                    'url': f'/downloads/{filename}',
                    'desc': f'Duration: {self.format_time(duration)}'
                }
                
                self.send_json_response(response_data, 200)
                
            except subprocess.TimeoutExpired:
                error_msg = 'Download timeout (file too large?)'
                print(f"[YT-DLP] Error: {error_msg}")
                self.send_json_response({
                    'status': 'error',
                    'error': error_msg
                }, 504)
            except json.JSONDecodeError:
                error_msg = 'Invalid video info response'
                print(f"[YT-DLP] Error: {error_msg}")
                self.send_json_response({
                    'status': 'error',
                    'error': error_msg
                }, 400)
                
        except json.JSONDecodeError:
            error_msg = 'Invalid JSON in request'
            print(f"[YT-DLP] Error: {error_msg}")
            self.send_json_response({
                'status': 'error',
                'error': error_msg
            }, 400)
        except Exception as e:
            error_msg = f'Server error: {str(e)}'
            print(f"[YT-DLP] Error: {error_msg}")
            self.send_json_response({
                'status': 'error',
                'error': error_msg
            }, 500)

    @staticmethod
    def format_time(seconds):
        """Форматирование времени в HH:MM:SS"""
        if not seconds:
            return '--:--'
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes}:{secs:02d}"

    def send_json_response(self, data, status_code=200):
        """Отправить JSON ответ"""
        response = json.dumps(data).encode('utf-8')
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(response))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(response)

    def end_headers(self):
        """Добавить CORS заголовки"""
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()

    def do_OPTIONS(self):
        """Обработка CORS preflight запросов"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def log_message(self, format, *args):
        """Логирование запросов"""
        print(f"[HTTP] {format % args}")


def start_server(port=8000):
    """Запуск HTTP сервера"""
    # Переходим в директорию скрипта
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    
    # Проверяем yt-dlp
    if not check_yt_dlp():
        print("\n[ERROR] yt-dlp не установлен. Установите его: pip install yt-dlp")
        input("Нажмите Enter для выхода...")
        sys.exit(1)
    
    server_address = ('', port)
    httpd = HTTPServer(server_address, LUMINARequestHandler)
    
    print("\n" + "=" * 70)
    print("🚀 LUMINA Media Downloader Server (yt-dlp powered)")
    print("=" * 70)
    print(f"📍 Server running at: http://localhost:{port}")
    print(f"📂 Working directory: {script_dir}")
    print(f"📥 Downloads folder: {DOWNLOADS_DIR}")
    print(f"🔌 API Endpoint: http://localhost:{port}/api/download")
    print("=" * 70)
    print("📝 Поддерживаемые сайты: YouTube, TikTok, Instagram, Pinterest и др.")
    print("⏸️  Press CTRL+C to stop the server\n")
    
    # Открываем браузер автоматически через 1 секунду
    threading.Timer(1.0, lambda: webbrowser.open(f'http://localhost:{port}')).start()
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n\n🛑 Server stopped")
        httpd.server_close()


if __name__ == '__main__':
    # Порт можно изменить аргументом командной строки
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    start_server(port)
    """Обработчик HTTP запросов с поддержкой API proxy"""

    def do_GET(self):
        """Обработка GET запросов"""
        if self.path == '/':
            self.path = '/index.html'
        return super().do_GET()

    def do_POST(self):
        """Обработка POST запросов к API"""
        if self.path == '/api/download':
            self.handle_yt_dlp_download()
        else:
            self.send_error(404)

    def handle_cobalt_proxy(self):
        """Proxy запрос к Cobalt API"""
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        
        try:
            # Парсим JSON тело запроса
            data = json.loads(body.decode('utf-8'))
            url = data.get('url')
            
            if not url:
                self.send_json_response({'error': 'URL not provided'}, 400)
                return

            print(f"[PROXY] Fetching: {url}")
            
            # Запрос к Cobalt API
            cobalt_url = 'https://api.cobalt.tools/api/json'
            payload = {
                'url': url,
                'vQuality': 'max',
                'aFormat': 'mp3',
                'downloadMode': 'auto'
            }
            
            # Заголовки для обхода блокировки
            headers = {
                'Content-Type': 'application/json',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'application/json',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': 'https://cobalt.tools/',
                'Origin': 'https://cobalt.tools'
            }
            
            req = urllib.request.Request(
                cobalt_url,
                data=json.dumps(payload).encode('utf-8'),
                headers=headers,
                method='POST'
            )
            
            # Отправляем запрос
            with urllib.request.urlopen(req, timeout=15) as response:
                response_data = response.read().decode('utf-8')
                result = json.loads(response_data)
                
                print(f"[PROXY] Success: {result.get('status')}")
                self.send_json_response(result)
                
        except urllib.error.HTTPError as e:
            error_msg = f'HTTP Error {e.code}'
            if e.code == 403:
                error_msg = 'API rejected request (403). Try another URL or wait a moment.'
            elif e.code == 429:
                error_msg = 'Too many requests (429). Please wait a moment.'
            print(f"[PROXY] Error: {error_msg}")
            self.send_json_response({'error': error_msg, 'status': 'error'}, e.code if e.code < 500 else 503)
        except urllib.error.URLError as e:
            error_msg = f'Connection error: {str(e.reason)}'
            print(f"[PROXY] Error: {error_msg}")
            self.send_json_response({'error': error_msg, 'status': 'error'}, 503)
        except json.JSONDecodeError as e:
            error_msg = 'Invalid JSON in response'
            print(f"[PROXY] Error: {error_msg}")
            self.send_json_response({'error': error_msg, 'status': 'error'}, 500)
        except Exception as e:
            error_msg = f'Server error: {str(e)}'
            print(f"[PROXY] Error: {error_msg}")
            self.send_json_response({'error': error_msg, 'status': 'error'}, 500)

    def send_json_response(self, data, status_code=200):
        """Отправить JSON ответ"""
        response = json.dumps(data).encode('utf-8')
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(response))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(response)

    def end_headers(self):
        """Добавить CORS заголовки"""
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()

    def do_OPTIONS(self):
        """Обработка CORS preflight запросов"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def log_message(self, format, *args):
        """Логирование запросов"""
        print(f"[{self.client_address[0]}] {format % args}")


def start_server(port=8000):
    """Запуск HTTP сервера"""
    # Переходим в директорию скрипта
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    
    server_address = ('', port)
    httpd = HTTPServer(server_address, LUMINARequestHandler)
    
    print("=" * 60)
    print("🚀 LUMINA Media Downloader Server")
    print("=" * 60)
    print(f"📍 Server running at: http://localhost:{port}")
    print(f"📂 Working directory: {script_dir}")
    print(f"🔌 API Proxy: http://localhost:{port}/api/download")
    print("=" * 60)
    print("Press CTRL+C to stop the server\n")
    
    # Открываем браузер автоматически через 1 секунду
    threading.Timer(1.0, lambda: webbrowser.open(f'http://localhost:{port}')).start()
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n\n🛑 Server stopped")
        httpd.server_close()


if __name__ == '__main__':
    # Порт можно изменить аргументом командной строки
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    start_server(port)
