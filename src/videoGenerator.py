import contextlib
import json
import os
import sys
import subprocess

from PIL import Image

from moviepy.editor import ImageSequenceClip, CompositeVideoClip, concatenate
from moviepy.video import fx

from typing import List

from log import Log

@contextlib.contextmanager
def suppress_stdout():
    with open(os.devnull, "w") as devnull:
        old_stdout = sys.stdout
        sys.stdout = devnull
        try:
            yield
        finally:
            sys.stdout = old_stdout

class VideoGenerator:

    def __init__(self):
        config = {}
        with open("configuration.json", "r") as file:
            config = json.load(file)

        self.fps = config['fps']
        self.bitrate = config['bitrate']
        self.codec = config['codec']
        self.width = config['width']
        self.height = config['height']
        self.mapResizeRatio = config['mapResizeRatio']
        self.threads = config['threads']

        self.background = "src/resources/background.jpg"
        self.duration = 1
        self.path = config['path']
        self.fileName = config['fileName']
        self.extension = config['extension']
        
        # Validate output directory
        self._validate_output_path()
    
        self.imagesLen = 24
        self.imageCount = 24
        self.viewsCount = 2
        self.lastImageRepeats = 5
    # def addProgressBar(self, sequence: ImageSequenceClip) -> ImageSequenceClip:
    #     return fx.all.sequence(sequence, [fx.all.time_mirror, fx.all.time_symmetrize])

    def generateImageSequence(self, image_list:List[str]) -> ImageSequenceClip:
        duration = 1 # TODO: ver como implementar esto

        # agrega la última imagen al final de la lista una x cantidad de veces
        for _ in range(self.lastImageRepeats):
            image_list.append(image_list[-1])
        
        sequence = None
        try:
            sequence = ImageSequenceClip(image_list, fps=self.fps, durations=[duration] * self.imagesLen)
        # si una imagen está en escala de grises el método ImageSequenceClip lanza un IndexError
        except IndexError:
            # Procesa cada imagen y la guarda con formato RGB
            [Image.open(image).convert("RGB").save(image) for image in image_list]
            sequence = ImageSequenceClip(image_list, fps=self.fps, durations=[duration] * self.imagesLen)
        except Exception: # maneja el error de imágenes de distinto tamaño
            # TODO: manejar mejor el error
            [Image.open(image).convert("RGB").save(image) for image in image_list]
            size = Image.open(image_list[0]).size
            [Image.open(image).resize(size).save(image) for image in image_list]
            sequence = ImageSequenceClip(image_list, fps=self.fps, durations=[duration] * self.imagesLen)

        # sequence = self.addProgressBar(sequence) TODO
        return sequence

    def _validate_output_path(self):
        """Validate that output directory exists and is writable"""
        try:
            # Check if directory exists
            if not os.path.exists(self.path):
                print(f"[WARNING] Output directory does not exist: {self.path}")
                print(f"[INFO] Creating directory: {self.path}")
                os.makedirs(self.path, exist_ok=True)
                Log.write(f"Created output directory: {self.path}", 0)
            
            # Check if directory is writable
            test_file = os.path.join(self.path, ".write_test_temp")
            try:
                with open(test_file, 'w') as f:
                    f.write("test")
                os.remove(test_file)
                print(f"[INFO] Output directory is writable: {self.path}")
            except PermissionError as pe:
                error_msg = f"No write permission in output directory: {self.path}"
                print(f"[ERROR] {error_msg}")
                Log.write(error_msg, 2)
                raise PermissionError(error_msg) from pe
            except Exception as e:
                error_msg = f"Cannot write to output directory {self.path}: {e}"
                print(f"[ERROR] {error_msg}")
                Log.write(error_msg, 2)
                raise
        except Exception as e:
            print(f"[ERROR] Error validating output path: {e}")
            Log.write(f"Error validating output path: {e}", 2)
            raise
    
    def joinSequences(self, video_list:List[ImageSequenceClip]) -> ImageSequenceClip:
        # sacando el método compose se modifica el tamaño de la segunda secuencia para igualarse
        return concatenate(video_list, method="compose") 

    def generateFinalVideo(self, sequence: ImageSequenceClip, total_frames: int):
        try:
            success = False
            sequence.duration = total_frames # iguala la duración de la secuencia de imágenes con la cantidad de frames

            # crea el fondo como una secuencia de imágenes con la misma cantidad de frames que la secuencia de imágenes
            background_clip = ImageSequenceClip([self.background] * (total_frames + 1), durations=[1] * (total_frames), 
                                                fps=self.fps) # ni idea pq hay q agregar un frame de más pero si no lo hago queda mal
            
            # une el fondo con la secuencia de imágenes
            final_clip = CompositeVideoClip([background_clip, sequence], size=(self.width, self.height))

            output_file = os.path.join(self.path, self.fileName + self.extension)
            temp_output = os.path.join(self.path, "TEMP_" + self.fileName + self.extension)
            print(f"[INFO] Rendering video to: {temp_output}")
            
            # Check if file exists and is writable
            if os.path.exists(output_file):
                try:
                    # Try to open in append mode to check write permission
                    with open(output_file, 'a'):
                        pass
                    print(f"[INFO] Existing file is writable, will be overwritten")
                except PermissionError:
                    error_msg = f"Cannot overwrite existing file (permission denied): {output_file}"
                    print(f"[ERROR] {error_msg}")
                    Log.write(error_msg, 2)
                    raise

            Log.videoRenderingStarted()
            # with suppress_stdout():
                # renderiza el video
            final_clip.write_videofile(temp_output, audio=False, codec=self.codec, 
                                        bitrate=self.bitrate, threads=self.threads)
            success = True
                
            # --- Corro ffmpeg para llevar el video a 30fps para que el puto de vMix lo corra bien ---

            if success:
            
                print(f"[INFO] Iniciando adaptación local a 30fps para vMix...")
                
                # Comando de FFmpeg para inflar a 30fps
                comando_ffmpeg = [
                    'ffmpeg', '-y', 
                    '-i', temp_output,          # El archivo de 4.2 fps recién creado
                    '-vf', 'fps=30',             # Forzamos los 30 cuadros por segundo
                    '-c:v', 'libx264',           # Codec H.264
                    '-pix_fmt', 'yuv420p',       # Formato de color compatible
                    '-preset', 'ultrafast',      # Máxima velocidad en el server
                    output_file
                ]
                
                subprocess.run(comando_ffmpeg, check=True)
            
            else:
                print("[ERROR]: Error en la creación del video.")

            if os.path.exists(temp_output):
                    os.remove(temp_output)
            


            print(f"[INFO] Video rendered successfully: {output_file}")
            print(f"[INFO] File size: {os.path.getsize(output_file) / (1024*1024):.2f} MB")
            Log.videoUpdated()
        except PermissionError as pe:
            error_msg = f"Permission denied writing video file: {pe}"
            print(f"[ERROR] {error_msg}")
            Log.write(error_msg, 2)
            raise
        except OSError as oe:
            error_msg = f"OS error writing video file: {oe}"
            print(f"[ERROR] {error_msg}")
            Log.write(error_msg, 2)
            raise
        except Exception as e:
            error_msg = f"Failed to generate final video: {e}"
            print(f"[ERROR] {error_msg}")
            Log.write(error_msg, 2)
            raise

    # globaliza todas las funciones
    def imagesToVideo(self, image_lists: List[List[str]], repeats: int):
        # devuelve la cantidad de frames totales sumando la cantidad de imágenes
        sequences = []
        # genera una secuencia de imágenes para cada satélite y las guarda en una lista
        for image_list in image_lists:
            # si la cantidad de imagenes es menor a 24, duplica la última imágen # TODO: arreglar lógica o no?
            if len(image_list) < 24:
                for _ in range(24 - len(image_list)):
                    image_list.append(image_list[-1])

            image_sequence = self.generateImageSequence(image_list)
            for _ in range(repeats):
                sequences.append(image_sequence)

            total_frames = (self.imageCount + self.lastImageRepeats) * repeats * self.viewsCount
        # une todas las secuencias de imágenes de los distintos satélites
        final_sequence = self.joinSequences(sequences)

        # centra la secuencia de imágenes y lo hace mas chico
        final_sequence = final_sequence.set_position(("center", "center"))
        final_sequence = final_sequence.resize(self.mapResizeRatio)
        
        self.generateFinalVideo(final_sequence, total_frames)



# from imageManager import ImageManager

# v = VideoGenerator()
# iARG = ImageManager(satelite="ARG")
# iCEN = ImageManager(satelite="CEN")

# v.imagesToVideo([iARG.getImageList(), iCEN.getImageList()], 2)