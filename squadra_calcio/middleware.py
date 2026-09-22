from .models import LogConnessione

class TracciamentoAccessiMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Esegue la chiamata API normalmente e ottiene la risposta
        response = self.get_response(request)
        
        # Cerca l'header che invia l'app Flutter
        utente = request.headers.get('X-Utente-App')
        
        # Se c'è un utente, significa che la chiamata viene dall'app. Salviamola!
        if utente:
            categoria = request.headers.get('X-Categoria-App', 'Nessuna')
            # Ignora la rotta periodica check_update per non intasare i log
            if 'check_update' not in request.path:
                LogConnessione.objects.create(
                    utente=utente,
                    categoria=categoria,
                    endpoint=request.path,
                    metodo=request.method,
                    status_code=response.status_code
                )
                
        return response