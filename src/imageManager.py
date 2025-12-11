import os
from typing import List
from log import Log
from imageDownloader import ImageDownloader


class ImageManager:

    satelite = ""

    def __init__(self, satelite: str):
        self.satelite = satelite
        self.downloader = ImageDownloader()
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
        for image_name in available_images:
            if image_name not in current_files:
                Log.write(f"Downloading new image: {image_name}", 0)
                content = self.downloader.download_image(image_name)
                if content:
                    self.saveImage(image_name, content)
        
        self.cleanBuffer()

    def downloadIntImages(self, amount: int):
        """
        Downloads initial images. 
        With the API, we just call updateBuffer which fetches the valid list (max 24).
        If 'amount' is just a placeholder for 'fill the buffer', updateBuffer does it.
        """
        self.updateBuffer()
