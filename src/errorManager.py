import requests
from log import Log

class ErrorManager:

    def __init__(self):
        pass
    
    @staticmethod
    def manageDownloadError(link: str, request: requests.Response) -> str:
        
        # not found
        if request.status_code == 404:
            Log.imageNotFound(link)
        
        # forbidden
        if request.status_code == 403:
            Log.forbiddenAccess(link)
        
        # si empieza en 5 es un error del servidor del servicio meteorológico
        if str(request.status_code)[0] == "5":
            Log.externalServerError(link, request.status_code)

        # de lo contrario
        if request.status_code not in [404, 403, 500, 501, 502, 503, 504]:
            Log.unmanagedImageError(link, request.status_code)

        return None
    
    @staticmethod
    def fatalError(e: Exception):
        try:
            print(f"[FATAL ERROR] {e}")
            Log.write(str(e), 2)
        except Exception as log_error:
            print(f"[CRITICAL] Failed to log fatal error: {log_error}")
            print(f"[CRITICAL] Original fatal error: {e}")
        finally:
            exit(1) 