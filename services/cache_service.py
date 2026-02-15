from flask_caching import Cache
from functools import wraps
import hashlib
import logging

logger = logging.getLogger(__name__)

# Créer l'instance de cache
cache = Cache()

def init_cache(app):
    """Initialise le cache avec l'application Flask"""
    app.config['CACHE_TYPE'] = 'SimpleCache'
    app.config['CACHE_DEFAULT_TIMEOUT'] = 300
    app.config['CACHE_THRESHOLD'] = 100
    app.config['CACHE_IGNORE_ERRORS'] = True
    
    cache.init_app(app)
    logger.info("✅ Cache initialisé avec succès")
    return cache
