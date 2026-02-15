# services/cache_service.py
from flask_caching import Cache
from functools import wraps
import hashlib
import time
import logging

logger = logging.getLogger(__name__)

# Configuration du cache pour Render
cache = Cache(config={
    'CACHE_TYPE': 'SimpleCache',  # SimpleCache fonctionne partout
    'CACHE_DEFAULT_TIMEOUT': 300,  # 5 minutes
    'CACHE_THRESHOLD': 100,  # Nombre max d'éléments en cache
    'CACHE_IGNORE_ERRORS': True  # Ignorer les erreurs de cache
})

def cache_key(*args, **kwargs):
    """Génère une clé de cache unique"""
    key = hashlib.md5(
        str(args).encode() + str(kwargs).encode()
    ).hexdigest()
    return key

def timed_cache(timeout=300):
    """Décorateur pour mettre en cache les résultats"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Créer une clé de cache unique
            cache_key = f"dashboard_{f.__name__}_{hashlib.md5(str(args).encode() + str(kwargs).encode()).hexdigest()}"
            
            # Essayer de récupérer du cache
            cached_value = cache.get(cache_key)
            if cached_value is not None:
                logger.info(f"✅ Cache HIT: {f.__name__}")
                return cached_value
            
            # Exécuter la fonction
            logger.info(f"🔄 Cache MISS: {f.__name__}")
            result = f(*args, **kwargs)
            
            # Sauvegarder dans le cache
            cache.set(cache_key, result, timeout=timeout)
            return result
        return decorated_function
    return decorator
