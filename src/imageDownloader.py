import requests
import subprocess
import os
from typing import List, Dict, Optional
from log import Log

class ImageDownloader:
    BASE_URL = "https://api-test.smn.gob.ar/v1"
    STATIC_URL = "https://estaticos.smn.gob.ar/vmsr/satelite"
    
    # Credentials
    USERNAME = "canal79mdq"
    PASSWORD = "K6dmG52y"
    
    # Valid token provided by user (fallback)
    DEFAULT_TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJjYW5hbDc5bWRxIiwic2NvcGVzIjoiUk9MRV9VU0VSX0ZPUkVDQVNUX0xPQ0FUSU9OLFJPTEVfVVNFUl9HRU9SRUYsUk9MRV9VU0VSX0hJU1RPUllfV0VBVEhFUixST0xFX1VTRVJfSU1BR0VTLFJPTEVfVVNFUl9XRUFUSEVSIiwiaWF0IjoxNzY1MjExMjM0LCJleHAiOjE3NjUyOTc2MzR9.-8msEp0wls_gSoGrP_b-kzY2raAhjZLPxaP6OkcHprc"
    TOKEN_SERVER_URL = "https://admin.canal79tv.com.ar/server/getsmntoken.php"

    def __init__(self, token=None):
        if token:
            self.token = token
        else:
            # Fetch token once at startup as requested
            self.token = self.fetch_token_from_server()
            if not self.token:
                Log.write("Initial token fetch failed, using default.", 1)
                self.token = self.DEFAULT_TOKEN

    def fetch_token_from_server(self) -> Optional[str]:
        try:
            print(f"Refreshing token from {self.TOKEN_SERVER_URL}...")
            # Add headers to mimic browser/client just in case server filters
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'application/json'
            }
            response = requests.get(self.TOKEN_SERVER_URL, headers=headers, timeout=10)
            
            if response.status_code == 200:
                # Handle potential BOM or strip whitespace
                text_content = response.text.strip()
                # If there's a BOM, python's json.loads usually handles it if decoded correctly, 
                # but r.json() relies on correct encoding detection.
                # response.encoding = 'utf-8-sig' might help if it's utf-8 with bom.
                if text_content.startswith('\ufeff'):
                    text_content = text_content[1:]
                
                try:
                    data = response.json()
                except:
                    import json
                    data = json.loads(text_content)

                if data.get("estado") == 1 and data.get("noticias"):
                    obtained_token = data["noticias"][0].get("token")
                    if obtained_token:
                        Log.write("Token refreshed successfully.", 0)
                        return obtained_token
            
            Log.write(f"Error parsing token from server response (Status {response.status_code}): {response.text[:100]}", 2)
            return None
        except Exception as e:
            Log.write(f"Exception fetching token from server: {e}", 2)
            return None

    def refresh_token(self) -> bool:
        new_token = self.fetch_token_from_server()
        if new_token:
            self.token = new_token
            return True
        return False

    def login(self):
        pass

    def get_api_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"JWT {self.token}"
        }

    def get_available_images(self, group_id: str) -> List[str]:
        try:
            url = f"{self.BASE_URL}/images/satellite/{group_id}"
            headers = self.get_api_headers()
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code in [401, 403]:
                Log.write(f"Auth failed ({response.status_code}) listing images. Refreshing token...", 1)
                if self.refresh_token():
                    # Retry once
                    headers = self.get_api_headers()
                    response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                return data.get("list", [])
            elif response.status_code == 404:
                Log.write(f"Group ID {group_id} not found", 1)
                return []
            else:
                Log.write(f"API Error: {response.status_code} fetching images for {group_id}", 2)
                return []
        except Exception as e:
            Log.write(f"Connection error fetching images: {e}", 2)
            return []

    def download_image(self, filename: str) -> Optional[bytes]:
        url = f"{self.STATIC_URL}/{filename}"
        temp_file = f"temp_{filename}"
        max_retries = 3

        for attempt in range(max_retries):
            # Ensure temp_file is clean before each attempt
            if os.path.exists(temp_file):
                try: os.remove(temp_file)
                except: pass

            if not self._execute_download(url, temp_file, attempt):
                # Download failed (curl error or general exception during curl execution)
                if attempt == 0:
                    Log.write(f"Download failed on first attempt for {filename}. Refreshing token...", 1)
                    self.refresh_token()
                continue # Move to next attempt

            # Download successful, now validate and read
            content = self._validate_and_read(temp_file, filename, attempt)
            if content:
                # Validation successful, content returned, and temp_file removed by _validate_and_read
                return content
            
            # Validation failed
            if attempt == 0: 
                 Log.write(f"Validation failed on first attempt for {filename}. Refreshing token...", 1)
                 self.refresh_token()
            
            # Cleanup temp file if it still exists after failed validation (it should be removed by _validate_and_read if successful)
            if os.path.exists(temp_file):
                 try: os.remove(temp_file)
                 except: pass

        Log.write(f"Failed to download {filename} after {max_retries} attempts", 2)
        return None

    def _execute_download(self, url: str, output_path: str, attempt: int) -> bool:
        try:
            command = [
                "curl.exe", "-s", "-L",
                "-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "-H", f"Authorization: JWT {self.token}", 
                "-o", output_path,
                url
            ]
            subprocess.run(command, check=True, timeout=60)
            return True
        except subprocess.CalledProcessError as e:
            Log.write(f"Curl attempt {attempt+1} failed: {e}", 1)
            return False
        except Exception as e:
            Log.write(f"Error executing curl attempt {attempt+1}: {e}", 1)
            return False

    def _validate_and_read(self, file_path: str, filename: str, attempt: int) -> Optional[bytes]:
        if not os.path.exists(file_path):
            Log.write(f"File {filename} not found after download attempt {attempt+1}", 1)
            return None
        
        file_size = os.path.getsize(file_path)
        if file_size <= 0:
            Log.write(f"Downloaded empty file for {filename}", 1)
            return None

        # Read content
        try:
            with open(file_path, "rb") as f:
                content = f.read()
        except Exception as e:
            Log.write(f"Error reading file {filename}: {e}", 1)
            return None

        # Basic size check for image validity (skip very small files which are usually errors)
        if file_size <= 1024:
             Log.write(f"File {filename} too small ({file_size} bytes), likely error page.", 1)
             return None

        # PIL Verification
        try:
            from PIL import Image
            import io
            Image.open(io.BytesIO(content)).verify()
            
            # Clean up successful file
            os.remove(file_path)
            return content
        except Exception as img_err:
            Log.write(f"Invalid image format for {filename}: {img_err}", 1)
            return None
