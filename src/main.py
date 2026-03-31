import shutil
from errorManager import ErrorManager
from runner import Runner
from imageManager import ImageManager
import os
import atexit

import signal

# TODO: agregar semáforo -> horas a las que no se pueden generar videos o semáforo para evitar que se 
#       lea el archivo mientras se está escribiendo

# TODO: agregar envío de problemas en tiempo real por mail

# TODO: terminar de definir el formato, tamaño y demás de los videos
# TODO: actualizar fondo
# TODO: agregar barra de tiempo (definir como va a ser)


def shutdown(runner: Runner) -> None:

    # Cierra todos los procesos en segundo plano (apshoudler)
    runner.shutdown()
    # Cierra el programa
    os.kill(os.getpid(), signal.SIGTERM)

def restartImages():
    # cambia el directorio de trabajo al directorio del programa
    separador = os.path.sep
    dir_actual = os.path.dirname(os.path.abspath(__file__))
    os.chdir(separador.join(dir_actual.split(separador)[:-1]))
    
    # si existe la carpeta buffer la vacía
    if os.path.exists("buffer"):
        shutil.rmtree("buffer")

    satelites = ["CEN", "ARG"]

    # descarga las primeras 24 imágenes de todos los satélites
    # print("Descargando primeras imágenes")
    #for satelite in satelites:
    #    w = ImageManager(satelite=satelite)
    #    w.updateBuffer()


def main():
    restartImages()
    
    runner = Runner()
    atexit.register(shutdown, runner=runner)
    # ejecuta el runner
    try:
        runner.run()
    except Exception as e:
        ErrorManager.fatalError(e)
    
    
if __name__ == "__main__":
    main()


