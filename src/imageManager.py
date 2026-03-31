import os
import json
from typing import List
from log import Log
from imageDownloader import ImageDownloader


class ImageManager:

    satelite = ""
    # Shared downloader instance across all ImageManagers to avoid multiple token refreshes
    _shared_downloader = None

    def __init__(self, satelite: str):
        self.satelite = satelite
        # Use shared downloader instance
        if ImageManager._shared_downloader is None:
            print("[INFO] Creating shared ImageDownloader instance")
            # Load configuration to get developer mode
            developer_mode = False
            try:
                with open('configuration.json', 'r') as f:
                    config = json.load(f)
                    developer_mode = config.get('developerMode', False)
                    print(f"[INFO] Configuration loaded: developerMode = {developer_mode}")
            except Exception as config_err:
                print(f"[WARNING] Could not read configuration.json: {config_err}")
                print("[INFO] Using default: developerMode = False")
            
            ImageManager._shared_downloader = ImageDownloader(developer_mode=developer_mode)
        self.downloader = ImageManager._shared_downloader
        self.groupId = ""
        if satelite == "ARG":
            self.groupId = "TOP_C13_ARG_ALTA"
        elif satelite == "CEN":
            self.groupId = "TOP_C13_CEN_ALTA"
    
    def checkBuffer(self) -> bool:
        # se verifica que exista el directorio buffer
        if not os.path.exists("buffer"):
            os.makedirs("buffer")
            os.makedirs("buffer/ARG")
            os.makedirs("buffer/CEN")
            return False
        
        if not os.path.exists("buffer/ARG"):
            os.makedirs("buffer/ARG")
            return False
        
        if not os.path.exists("buffer/CEN"):
            os.makedirs("buffer/CEN")
            return False
        
        return True

    # devuelve una lista de imágenes con las imágenes que se encuentran en el buffer
    def getImageList(self) -> List[str]:
        if not self.checkBuffer():
            return []
        # Sort to ensure order
        return sorted([os.path.join("buffer/" + self.satelite + "/" + archivo) for archivo in os.listdir("buffer/" + self.satelite)])

    def saveImage(self, filename: str, content: bytes) -> str:
        self.checkBuffer()
        
        # se guarda la imagen en el buffer
        path = "buffer/" + self.satelite + "/" + filename
        with open(path, 'wb') as f:
            f.write(content)
        
        Log.imageDownloaded(path) 
        
        # Limpieza: si hay más de 24 imágenes, borra la más vieja
        self.cleanBuffer()
        return filename

    def cleanBuffer(self):
        # si existen mas de 24 imagenes en el buffer, borra la mas vieja
        files = sorted(os.listdir("buffer/" + self.satelite))
        while len(files) > 24:
            toRemove = self.satelite + "/" + files[0]
            os.remove("buffer/" + toRemove)
            Log.imageDeleted("buffer/" + toRemove)
            files = sorted(os.listdir("buffer/" + self.satelite))

    def updateBuffer(self):
        """
        Consults the API for the latest images and downloads any that are missing.
        """
        if not self.groupId:
            Log.write(f"No Group ID for satellite {self.satelite}", 2)
            return

        available_images = self.downloader.get_available_images(self.groupId)
        if not available_images:
            return
        
        # Ensure they are sorted so we process chronologically
        available_images.sort()

        self.checkBuffer()
        current_files = os.listdir(f"buffer/{self.satelite}")
        
        # Download missing images
        # We focus on the latest ones. The API returns the last 24.
        import time
        import random
        
        # Initial delay to avoid immediate rate limiting
        time.sleep(2)
        
        for i, image_name in enumerate(available_images):
            if image_name not in current_files:
                Log.write(f"Downloading new image: {image_name}", 0)
                content = self.downloader.download_image(image_name)
                if content:
                    self.saveImage(image_name, content)
                # Progressive delay between downloads with randomness to avoid Cloudflare rate limiting
                # Longer delays for IPs that might be flagged
                base_delay = 2.5 + (i * 0.1)  # Increases with each download
                random_delay = random.uniform(0.5, 1.5)
                total_delay = base_delay + random_delay
                print(f"[DEBUG] Waiting {total_delay:.1f}s before next download...")
                time.sleep(total_delay)
        
        self.cleanBuffer()

    def downloadIntImages(self, amount: int):
        """
        Downloads initial images. 
        With the API, we just call updateBuffer which fetches the valid list (max 24).
        If 'amount' is just a placeholder for 'fill the buffer', updateBuffer does it.
        """
        self.updateBuffer()
