from datetime import datetime
from typing import List
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import json

def getDate() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def enviar_emails(contenido: str):
    try:
        with open("emails.json", "r") as file:
            destinatarios = json.load(file)
            for destinatario in destinatarios:
                enviar_email(destinatario, contenido)
    except FileNotFoundError:
        print("[ERROR] emails.json file not found, cannot send error notifications")
    except json.JSONDecodeError:
        print("[ERROR] emails.json has invalid format")
    except Exception as e:
        print(f"[ERROR] Failed to process emails.json: {e}")

def enviar_email(destinatario, contenido):
    # Configurar los detalles del servidor SMTP de Gmail
    try:
        servidor_smtp = "smtp.gmail.com"
        puerto_smtp = 587
        correo_emisor = "santicepeda03@gmail.com"
        contraseña_emisor = "wzwmnjvfjywojewy"

        # Crear el mensaje
        mensaje = MIMEMultipart()
        mensaje["From"] = correo_emisor
        mensaje["To"] = destinatario
        mensaje["Subject"] = "ERROR EN EL SISTEMA DE GENERACION DE VIDEOS DE MAPAS SATELITALES"

        # Agregar el contenido del mensaje
        mensaje.attach(MIMEText(contenido, "plain"))

        # Establecer la conexión con el servidor SMTP
        servidor = smtplib.SMTP(servidor_smtp, puerto_smtp)
        servidor.starttls()

        # Iniciar sesión en la cuenta de correo emisor
        servidor.login(correo_emisor, contraseña_emisor)

        # Enviar el mensaje
        servidor.sendmail(correo_emisor, destinatario, mensaje.as_string())

        # Cerrar la conexión con el servidor SMTP
        servidor.quit()
        print(f"[INFO] Error email sent successfully to {destinatario}")
    except Exception as e:
        print(f"[ERROR] Failed to send error email to {destinatario}: {e}")
        print(f"[ERROR] Original error message: {contenido}")

class Log:

    codes = {0: "success", 1: "warning", 2: "error"}
    log_file = "log.txt"

    def __init__(self):
        pass

    @staticmethod
    def write(message: str, code: int):
        try:
            with open(Log.log_file, 'a') as file:
                file.write(f"{getDate()} [{Log.codes[code]}] {message}\n")
            if code == 2:
                # envia un mail
                print(f"[ERROR] {message}")
                enviar_emails(message)
        except Exception as e:
            print(f"[CRITICAL] Failed to write log: {e}")
            print(f"[CRITICAL] Original message: {message}")

    @staticmethod
    def runnerStarted():
        Log.write("Runner started", 0)


    @staticmethod
    def imageDownloaded(file: str):
        Log.write(f"Image \"{file}\" downloaded", 0)

    @staticmethod
    def imageDeleted(file: str):
        Log.write(f"Image \"{file}\" deleted", 0)

    @staticmethod
    def imageNotFound(file: str):
        print(f"[WARNING] Image \"{file}\" not found")
        Log.write(f"Image \"{file}\" not found", 1)

    @staticmethod
    def forbiddenAccess(link: str):
        print(f"[ERROR] Forbidden access to image {link}")
        Log.write(f"Forbidden access to image {link}", 2)

    @staticmethod
    def externalServerError(link: str, code: int):
        print(f"[ERROR] External server error in image \"{link}\" with code {code}")
        Log.write(f"External server error in image \"{link}\" with code {code}", 2)

    @staticmethod
    def unmanagedImageError(file: str, code: int):
        print(f"[ERROR] Unmanaged image error in image \"{file}\" with code {code}")
        Log.write(f"Unmanaged image error in image \"{file}\" with code {code}", 2)



    @staticmethod
    def bufferUpdated(newFile: str, oldFile: str):
        Log.write(f"Buffer updated. New file: \"{newFile}\". Old file: \"{oldFile}\"", 0)

    @staticmethod
    def bufferFailedDownloadTry(tryNumber: int):
        print(f"[WARNING] Image download try number {tryNumber} failed")
        Log.write(f"Image download try number {tryNumber} failed", 1)

    @staticmethod
    def bufferGaveUp(image: str):
        print(f"[ERROR] Buffer gave up, image \"{image}\" is missing")
        Log.write(f"Buffer gave up, image \"{image}\" is missing", 2)


    @staticmethod
    def videoRenderingStarted():
        Log.write("Rendering started", 0)
    
    @staticmethod
    def videoUpdated():
        Log.write("Video updated", 0)

    @staticmethod
    def videoRenderingError(e: Exception):
        print(f"[ERROR] Video rendering error: {e}")
        Log.write(f"Video rendering error: {e}", 2)

    @staticmethod
    def shutdown():
        Log.write("Runner shutdown", 0)

