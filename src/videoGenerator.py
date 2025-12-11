import contextlib
import json
import os
import sys
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

    def joinSequences(self, video_list:List[ImageSequenceClip]) -> ImageSequenceClip:
        # sacando el método compose se modifica el tamaño de la segunda secuencia para igualarse
        return concatenate(video_list, method="compose") 

    def generateFinalVideo(self, sequence: ImageSequenceClip, total_frames: int):
        try:
            sequence.duration = total_frames # iguala la duración de la secuencia de imágenes con la cantidad de frames

            # crea el fondo como una secuencia de imágenes con la misma cantidad de frames que la secuencia de imágenes
            background_clip = ImageSequenceClip([self.background] * (total_frames + 1), durations=[1] * (total_frames), 
                                                fps=self.fps) # ni idea pq hay q agregar un frame de más pero si no lo hago queda mal
            
            # une el fondo con la secuencia de imágenes
            final_clip = CompositeVideoClip([background_clip, sequence], size=(self.width, self.height))

            Log.videoRenderingStarted()
            with suppress_stdout():
                # renderiza el video
                final_clip.write_videofile(self.path + self.fileName + self.extension, audio=False, codec=self.codec, 
                                        bitrate=self.bitrate, threads=self.threads)

            Log.videoUpdated()
        except Exception as e:
            print(f"[ERROR] Failed to generate final video: {e}")
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