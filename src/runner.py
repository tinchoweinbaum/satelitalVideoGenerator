import os
from apscheduler.schedulers.blocking import BlockingScheduler as bs

from log import Log
from imageManager import ImageManager
from videoGenerator import VideoGenerator
import keyboard

class Runner:

    def __init__(self) -> None:
        Log.runnerStarted()
        self.sched = bs()
        pass

    def shutdown(self) -> None:
        Log.shutdown()
        print("Shutting down")
        # Cierra todos los procesos en segundo plano (apshoudler)
        self.sched.remove_all_jobs()
        self.sched.shutdown()
        # Cierra el programa
        exit()

    def run(self) -> None:

        # crea el imageManager para cada satélite
        satelites = ["ARG", "CEN"] # en el orden en el que estarán en el video
        imagers = [ImageManager(i) for i in satelites]

        generator = VideoGenerator()

        print("Running")

        job()

        for i in range(7, 58, 10):
            @self.sched.scheduled_job('cron', minute=str(i))
            def job():
                image_lists = []
                # actualiza todos los imagers y guarda sus listas de imágenes en una lista
                for imager in imagers:
                    imager.updateBuffer()
                    image_lists.append(imager.getImageList())

                # genera el video con las listas de imágenes
                try:
                    generator.imagesToVideo(image_lists, 2)
                except Exception as e:
                    Log.videoRenderingError(e)
                    pass

        self.sched.start()


# Runner().run()
