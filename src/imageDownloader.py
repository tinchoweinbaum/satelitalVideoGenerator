import requests
import subprocess
import os
import json
from typing import List, Dict, Optional
from log import Log
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import time

class ImageDownloader:
    BASE_URL = "https://api-test.smn.gob.ar/v1"
    STATIC_URL = "https://estaticos.smn.gob.ar/vmsr/satelite"
    
    # Credentials
    USERNAME = "canal79mdq"
    PASSWORD = "K6dmG52y"
    
    # Valid token provided by user (fallback)
    DEFAULT_TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJjYW5hbDc5bWRxIiwic2NvcGVzIjoiUk9MRV9VU0VSX0ZPUkVDQVNUX0xPQ0FUSU9OLFJPTEVfVVNFUl9HRU9SRUYsUk9MRV9VU0VSX0hJU1RPUllfV0VBVEhFUixST0xFX1VTRVJfSU1BR0VTLFJPTEVfVVNFUl9XRUFUSEVSIiwiaWF0IjoxNzY1MjExMjM0LCJleHAiOjE3NjUyOTc2MzR9.-8msEp0wls_gSoGrP_b-kzY2raAhjZLPxaP6OkcHprc"
    TOKEN_SERVER_URL = "https://admin.canal79tv.com.ar/server/getsmntoken.php"
    
    # Shared Chrome driver instance (persists during entire program execution)
    _driver = None

    def __init__(self, token=None, developer_mode=False):
        self.developer_mode = developer_mode
        if token:
            self.token = token
        else:
            # Fetch token once at startup as requested
            self.token = self.fetch_token_from_server("ImageDownloader initialization")
            if not self.token:
                Log.write("Initial token fetch failed, using default.", 1)
                self.token = self.DEFAULT_TOKEN

    def fetch_token_from_server(self, reason: str = "Unknown") -> Optional[str]:
        try:
            print(f"[TOKEN REFRESH] Reason: {reason}")
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

    def refresh_token(self, reason: str = "Unknown") -> bool:
        new_token = self.fetch_token_from_server(reason)
        if new_token:
            self.token = new_token
            return True
        return False

    def login(self):
        pass
    
    def _init_driver(self):
        """Initialize Chrome driver once and reuse for all downloads"""
        if ImageDownloader._driver is None:
            try:
                print("[INFO] Initializing Chrome driver for image downloads...")
                
                chrome_options = Options()
                
                # Headless mode based on developer_mode parameter
                if not self.developer_mode:
                    chrome_options.add_argument('--headless')
                    print("[INFO] Running in PRODUCTION mode (headless)")
                else:
                    print("[INFO] Running in DEVELOPER mode (browser visible)")
                
                chrome_options.add_argument('--no-sandbox')
                chrome_options.add_argument('--disable-dev-shm-usage')
                chrome_options.add_argument('--disable-gpu')
                chrome_options.add_argument('--disable-blink-features=AutomationControlled')
                chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
                chrome_options.add_experimental_option('excludeSwitches', ['enable-automation'])
                chrome_options.add_experimental_option('useAutomationExtension', False)
                
                ImageDownloader._driver = webdriver.Chrome(options=chrome_options)
                print("[INFO] Chrome driver initialized successfully")
            except Exception as e:
                print(f"[ERROR] Failed to initialize Chrome driver: {e}")
                Log.write(f"Failed to initialize Chrome driver: {e}", 2)
                raise
        return ImageDownloader._driver
    
    @staticmethod
    def close_driver():
        """Close the Chrome driver (optional, for manual cleanup during debugging)"""
        if ImageDownloader._driver:
            try:
                ImageDownloader._driver.quit()
                ImageDownloader._driver = None
                print("[INFO] Chrome driver closed")
            except Exception as e:
                print(f"[ERROR] Error closing driver: {e}")

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
                if self.refresh_token(f"Auth failed ({response.status_code}) in get_available_images for group {group_id}"):
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
        
        print(f"\n[DEBUG] ========== Starting download for {filename} ==========")

        for attempt in range(max_retries):
            print(f"[DEBUG] === Attempt {attempt+1}/{max_retries} ===")
            # Ensure temp_file is clean before each attempt
            if os.path.exists(temp_file):
                try: os.remove(temp_file)
                except: pass

            if not self._execute_download(url, temp_file, attempt):
                # Download failed (curl error or general exception during curl execution)
                if attempt == 0:
                    Log.write(f"Download failed on first attempt for {filename}. Refreshing token...", 1)
                    self.refresh_token(f"Download execution failed on first attempt for {filename}")
                # Wait before retrying to avoid Cloudflare rate limiting
                import time
                wait_time = 3 * (attempt + 1)  # 3s, 6s, 9s
                print(f"[DEBUG] Waiting {wait_time}s before retry...")
                time.sleep(wait_time)
                continue # Move to next attempt

            # Download successful, now validate and read
            content = self._validate_and_read(temp_file, filename, attempt)
            if content:
                # Validation successful, content returned, and temp_file removed by _validate_and_read
                return content
            
            # Validation failed
            if attempt == 0: 
                 Log.write(f"Validation failed on first attempt for {filename}. Refreshing token...", 1)
                 self.refresh_token(f"Image validation failed on first attempt for {filename}")
            
            # Cleanup temp file if it still exists after failed validation (it should be removed by _validate_and_read if successful)
            if os.path.exists(temp_file):
                 try: os.remove(temp_file)
                 except: pass
            
            # Wait before retrying to avoid Cloudflare rate limiting
            # Use exponential backoff with longer delays
            import time
            wait_time = 10 * (2 ** attempt)  # 10s, 20s, 40s (exponential backoff)
            print(f"[DEBUG] Cloudflare block detected. Waiting {wait_time}s before retry...")
            print(f"[INFO] If this persists, the IP might be temporarily blacklisted by Cloudflare")
            time.sleep(wait_time)

        Log.write(f"Failed to download {filename} after {max_retries} attempts", 2)
        return None

    def _execute_download(self, url: str, output_path: str, attempt: int) -> bool:
        """Download image using Selenium Chrome driver to bypass Cloudflare"""
        try:
            print(f"[DEBUG] Downloading {os.path.basename(output_path)} (attempt {attempt+1})")
            print(f"[DEBUG] URL: {url}")
            
            # Initialize driver if needed (only happens once)
            driver = self._init_driver()
            
            # Navigate to the image URL
            driver.get(url)
            
            # Wait for page to load and Cloudflare check if present
            initial_wait = 3 + attempt * 2  # Progressive wait: 3s, 5s, 7s
            time.sleep(initial_wait)
            
            # Check if we got Cloudflare challenge page
            page_source = driver.page_source.lower()
            if 'just a moment' in page_source or 'checking your browser' in page_source:
                print(f"[DEBUG] Cloudflare challenge detected, waiting for completion...")
                cloudflare_wait = 8 + attempt * 3  # Wait longer: 8s, 11s, 14s
                time.sleep(cloudflare_wait)
                page_source = driver.page_source.lower()
                
                # Check again if still blocked
                if 'just a moment' in page_source:
                    print(f"[DEBUG] Cloudflare still blocking, might need more time")
                    return False
            
            # Extract image directly from browser using screenshot method
            print(f"[DEBUG] Extracting image from browser...")
            
            try:
                # Find the img element
                img_element = driver.find_element("tag name", "img")
                print(f"[DEBUG] Found img element")
                
                # Get the natural dimensions of the image
                natural_width = driver.execute_script("return arguments[0].naturalWidth;", img_element)
                natural_height = driver.execute_script("return arguments[0].naturalHeight;", img_element)
                print(f"[DEBUG] Image dimensions: {natural_width}x{natural_height}")
                
                # Take a screenshot of just the image element
                print(f"[DEBUG] Taking screenshot of image element...")
                screenshot_png = img_element.screenshot_as_png
                print(f"[DEBUG] Screenshot captured: {len(screenshot_png)} bytes (PNG format)")
                
                # Save the screenshot as PNG (lossless)
                with open(output_path, 'wb') as f:
                    f.write(screenshot_png)
                print(f"[DEBUG] Image saved successfully: {len(screenshot_png)} bytes")
                
                return True
                
            except Exception as extract_err:
                print(f"[DEBUG] Screenshot method failed: {extract_err}")
                print(f"[DEBUG] Falling back to download via src with cookies...")
                
                # Fallback: download via requests with Cloudflare cookies
                try:
                    img_element = driver.find_element("tag name", "img")
                    img_src = img_element.get_attribute('src')
                    print(f"[DEBUG] Found image src: {img_src}")
                except:
                    print(f"[DEBUG] No img element found, using original URL")
                    img_src = url
                
                cookies = driver.get_cookies()
                session = requests.Session()
                for cookie in cookies:
                    session.cookies.set(cookie['name'], cookie['value'])
                
                headers = {
                    'User-Agent': driver.execute_script("return navigator.userAgent"),
                    'Referer': 'https://www.smn.gob.ar/',
                    'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
                    'Accept-Language': 'es-AR,es;q=0.9,en;q=0.8'
                }
                
                response = session.get(img_src, headers=headers, timeout=30)
                print(f"[DEBUG] Fallback response: {response.status_code}, {len(response.content)} bytes")
                
                if response.status_code == 200 and len(response.content) > 10000:
                    with open(output_path, 'wb') as f:
                        f.write(response.content)
                    print(f"[DEBUG] Downloaded via fallback: {len(response.content)} bytes")
                    return True
                else:
                    print(f"[DEBUG] Fallback download failed")
                    return False
                
        except Exception as e:
            print(f"[DEBUG] Selenium download exception: {e}")
            Log.write(f"Selenium download attempt {attempt+1} failed: {e}", 1)
            
            # Try to reinitialize driver if it crashed
            if "invalid session id" in str(e).lower() or "session deleted" in str(e).lower():
                print("[INFO] Driver session lost, reinitializing...")
                ImageDownloader._driver = None
            
            return False

    def _validate_and_read(self, file_path: str, filename: str, attempt: int) -> Optional[bytes]:
        print(f"[DEBUG] Validating {filename} (attempt {attempt+1})")
        
        if not os.path.exists(file_path):
            print(f"[DEBUG] File not found: {file_path}")
            Log.write(f"File {filename} not found after download attempt {attempt+1}", 1)
            return None
        
        file_size = os.path.getsize(file_path)
        print(f"[DEBUG] File size: {file_size} bytes")
        
        if file_size <= 0:
            print(f"[DEBUG] File is empty")
            Log.write(f"Downloaded empty file for {filename}", 1)
            return None

        # Read content
        try:
            with open(file_path, "rb") as f:
                content = f.read()
            print(f"[DEBUG] Successfully read {len(content)} bytes from file")
        except Exception as e:
            print(f"[DEBUG] Error reading file: {e}")
            Log.write(f"Error reading file {filename}: {e}", 1)
            return None

        # Basic size check for image validity (skip very small files which are usually errors)
        if file_size <= 1024:
            print(f"[DEBUG] File too small ({file_size} bytes), analyzing content...")
            try:
                preview = content.decode('utf-8', errors='ignore')[:300]
                print(f"[DEBUG] Content preview: {preview}")
                Log.write(f"File {filename} too small. Content: {preview}", 1)
            except:
                print(f"[DEBUG] Cannot decode content as text")
            return None

        # PIL Verification
        try:
            from PIL import Image
            import io
            print(f"[DEBUG] Verifying image format with PIL...")
            Image.open(io.BytesIO(content)).verify()
            print(f"[DEBUG] Image validation successful!")
            
            # Clean up successful file
            os.remove(file_path)
            return content
        except Exception as img_err:
            print(f"[DEBUG] PIL validation failed: {img_err}")
            print(f"[DEBUG] Checking if content is HTML/JSON...")
            try:
                preview = content[:500].decode('utf-8', errors='ignore')
                if '<html' in preview.lower() or '<HTML' in preview:
                    print(f"[DEBUG] Content is HTML! Preview:")
                    print(preview[:300])
                    Log.write(f"Server returned HTML for {filename}: {preview[:200]}", 1)
                elif preview.strip().startswith('{') or preview.strip().startswith('['):
                    print(f"[DEBUG] Content is JSON! Preview:")
                    print(preview[:300])
                    Log.write(f"Server returned JSON for {filename}: {preview[:200]}", 1)
                else:
                    print(f"[DEBUG] Content is neither valid image, HTML, nor JSON")
                    print(f"[DEBUG] First 100 bytes (hex): {content[:100].hex()}")
                    Log.write(f"Invalid image format for {filename}: {img_err}", 1)
            except:
                print(f"[DEBUG] Cannot decode content, showing hex dump of first 50 bytes:")
                print(f"[DEBUG] {content[:50].hex()}")
                Log.write(f"Invalid binary format for {filename}: {img_err}", 1)
            return None
