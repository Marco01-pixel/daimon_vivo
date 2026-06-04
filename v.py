#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ================================================================================
# SECCION 1: METADATOS Y CONFIGURACION INICIAL
# ================================================================================
"""
PARTE 5/9 - SISTEMA DAIMON VIVO UNIFICADO
Sistema central de gobierno autonomo con IA, mineria, negociacion y RL.
Version unificada: Integra todos los algoritmos del primer codigo
con el sistema de negociacion Symbiosis y CEOIA completa.
Compatible con Termux/Android - Python 3.6+
"""

# ================================================================================
# SECCION 2: IMPORTS BASE (ANTES DE CUALQUIER EJECUCION)
# ================================================================================
import os
import sys
import json
import time
import random
import signal
import socket
import string
import threading
import hashlib
import functools
import traceback
import uuid
import math
import textwrap
import secrets
import re
import subprocess
import gc
import heapq
import copy
import typing
import shutil
from typing import Dict, List, Optional, Tuple, Any, Callable, Union, Set
from collections import deque, defaultdict, Counter
from pathlib import Path
from contextlib import contextmanager

from datetime import datetime as _datetime
from datetime import timezone as _timezone
from datetime import timedelta as _timedelta

# ================================================================================
# SECCION 3: IMPORTS ADICIONALES CON FALLBACK
# ================================================================================
try:
    import requests
except ImportError:
    requests = None

try:
    from flask import request, jsonify, make_response
except ImportError:
    request = None
    jsonify = None
    make_response = None

try:
    import numpy as np
except ImportError:
    np = None

# ================================================================================
# SECCION 4: FALLBACK DE COMPONENTES BASE
# ================================================================================
try:
    from symbiosis_parte1 import (
        GlobalConfig, log_event, log_banner,
        HyperNumberAdvanced, GeoLocation, SharedDataRegistry
    )
except ImportError:
    class GlobalConfig:
        IS_TERMUX = True
        IS_LOW_MEMORY = True

    def log_event(msg: str, level: str = "INFO") -> None:
        timestamp = _datetime.now(_timezone.utc).strftime("%H:%M:%S")
        print(f"[{timestamp}][{level}] {msg}", flush=True)

    def log_banner(msg: str, icon: str = "") -> None:
        print("=" * 60)
        print(f"{icon} {msg}")
        print("=" * 60)

    class HyperNumberAdvanced:
        def __init__(self, value=0.0):
            self.value = float(value)
        def to_float_approx(self): return self.value
        def add(self, x): self.value += float(x)
        def display(self): return f"{self.value:.2f}"

    class GeoLocation:
        def __init__(self, latitude=0.0, longitude=0.0):
            self.latitude = latitude
            self.longitude = longitude

    class SharedDataRegistry:
        _instance = None
        _lock = threading.RLock()
        def __new__(cls):
            if cls._instance is None:
                with cls._lock:
                    if cls._instance is None:
                        cls._instance = super().__new__(cls)
                        cls._instance._initialized = False
            return cls._instance
        def __init__(self):
            if self._initialized: return
            with self._lock:
                if self._initialized: return
                self._data: Dict[str, Any] = {}
                self._callbacks: Dict[str, List[Callable]] = defaultdict(list)
                self._initialized = True
        def set(self, key: str, value: Any, notify: bool = True) -> bool:
            with self._lock:
                try:
                    self._data[key] = copy.deepcopy(value)
                    if notify: self._trigger_callbacks(key, value)
                    return True
                except: return False
        def get(self, key: str, default: Any = None) -> Any:
            with self._lock:
                return copy.deepcopy(self._data.get(key, default))
        def get_all(self, pattern: Optional[str] = None) -> Dict[str, Any]:
            with self._lock:
                if pattern is None: return {k: copy.deepcopy(v) for k, v in self._data.items()}
                import fnmatch
                return {k: copy.deepcopy(v) for k, v in self._data.items() if fnmatch.fnmatch(k, pattern)}
        def on_change(self, key_pattern: str, callback: Callable) -> str:
            with self._lock:
                callback_id = str(hash(callback))[:8]
                self._callbacks[key_pattern].append((callback_id, callback))
                return callback_id
        def _trigger_callbacks(self, key: str, value: Any) -> None:
            for pattern, callbacks in self._callbacks.items():
                import fnmatch
                if fnmatch.fnmatch(key, pattern):
                    for _, cb in callbacks:
                        try: cb(key, value)
                        except: pass

# ================================================================================
# SECCION 5: PRE-CHECK TERMUX
# ================================================================================
def _precheck_termux_environment():
    """Verifica entorno Termux y ajusta configuracion automaticamente."""
    try:
        if shutil.which('termux-location') is None:
            print("[INIT][WARN] termux-api no detectado - GPS en modo simulado", flush=True)
            os.environ['TERMUX_GPS_FALLBACK'] = '1'
        
        if shutil.which('ollama') is None:
            print("[INIT][WARN] ollama no detectado - usando fallback DeepSeek", flush=True)
            os.environ['TERMUX_OLLAMA_FALLBACK'] = '1'
        
        home = Path.home()
        rutas_criticas = [
            ("STATE_FILE", home / "state.json"),
            ("DAIMON_BRAIN_FILE", home / "daimon_brain.json"),
            ("RESPONSES_MEMORY_FILE", home / "respuestas_uber.json"),
            ("SOCIALCOIN_HEARTBEAT_FILE", home / "socialcoin_heartbeat.json"),
        ]
        
        for nombre, ruta in rutas_criticas:
            try:
                if str(ruta).startswith('/sdcard'):
                    if not os.access(str(ruta.parent), os.W_OK):
                        nueva_ruta = home / ruta.name
                        print(f"[INIT][WARN] Redirigiendo {nombre} a {nueva_ruta} por permisos", flush=True)
                        os.environ[f'TERMUX_REDIRECT_{nombre}'] = str(nueva_ruta)
            except Exception:
                pass
                
    except Exception as e:
        print(f"[INIT][ERROR] Pre-check fallido (no critico): {type(e).__name__}", flush=True)

_precheck_termux_environment()

# ================================================================================
# SECCION 6: VARIABLES GLOBALES DEL SISTEMA (THREAD-SAFE)
# ================================================================================
if 'log' not in globals():
    def log(msg, tag="INFO"):
        print(f"[{tag}] {msg}")

GLOBAL_LOCK = threading.RLock()
CONFIG_LOCK = threading.RLock()

STOP_EVENT = threading.Event()
simulation_active = True
data_lock = threading.RLock()
mining_log = []
log_lock = threading.RLock()

HTTP_PORT = int(os.getenv("CEOIA_HTTP_PORT", "8080"))
IA_READY = False
WEB_ACCESSED = False
MEJOR_OPCION_PROMPT_ACTIVO = False
MODO_NEGOCIACION_IA = False

ULTIMA_ZONA = "z1"
ESTADO_CONDUCTOR = "IDLE"
VIAJE_EN_CURSO = None
TIEMPO_INICIO_VIAJE = None
GPS_ACTIVO = False
GPS_ACTUAL = None
GPS_OBJETIVO = None
historial_gps = deque(maxlen=500)
ULTIMA_ACTUALIZACION_GPS = 0.0

BENEFICIARIO_ACTUAL = "conductor_codigo"
FACTOR = 1.0
UBER_COINS = None

ZONAS = [
    {"id": "z1", "nombre": "Albrook Mall", "lat_min": 8.97, "lat_max": 9.00, "lon_min": -79.54, "lon_max": -79.50},
    {"id": "z2", "nombre": "Arraijan Centro", "lat_min": 8.86, "lat_max": 8.90, "lon_min": -79.78, "lon_max": -79.74},
    {"id": "z3", "nombre": "La Chorrera Centro", "lat_min": 8.86, "lat_max": 8.89, "lon_min": -79.80, "lon_max": -79.76},
    {"id": "z4", "nombre": "San Carlos", "lat_min": 8.87, "lat_max": 8.90, "lon_min": -79.82, "lon_max": -79.78},
    {"id": "z5", "nombre": "Veracruz", "lat_min": 8.84, "lat_max": 8.87, "lon_min": -79.84, "lon_max": -79.80},
]

zona_estado = {z["id"]: {"color": "gris", "ganancia_estimada": 0.0, "tiempo_espera": 0.0, "demanda": 0, "oferta": 0, "ratio_demanda": 0.0} for z in ZONAS}
ZONA_LOCK = threading.RLock()

blockchain = []
block_number = 1
viral_blocks = 0
BLOCKCHAIN_LOCK = threading.RLock()

ALGO_WEIGHTS = {
    'acceptance_rate': 5.0, 'completion_rate': 10.0, 'avg_rating': 2.0,
    'trips_completed': 0.1, 'time_online': 0.5, 'cancellation_rate': -20.0,
    'idle_time_ratio': -10.0, 'peak_hours_ratio': 3.0, 'distance_traveled': 0.05,
    'distance': 0.2, 'duration': 0.01, 'fare': 1.0, 'realEarnings': 1.0,
    'estimatedEarnings': 0.95, 'waitTime': -0.5, 'additionalSearchCost': -0.5,
    'viral_score_bonus': 50.0, 'recompensa_viral': 1.0, 'best_option_bonus': 25.0,
    'engagement_rate': 15.0, 'share_ratio': 25.0, 'completion_rate_video': 20.0,
    'creativity_bonus': 40.0, 'innovation_bonus': 30.0, 'adaptation_rate': 25.0,
    'sustainability_score': 15.0, 'gps_priority': 1.0, 'fraud_threshold': 0.6,
    'movement_speed': 1.0, 'notification_priority': 1.0, 'exploration_rate': 1.0,
    'gps_exploration': 1.0
}
ALGO_WEIGHTS_LOCK = threading.RLock()

DAIMON_ID = str(uuid.uuid4())[:8]
Q_TABLE = {}
Q_TABLE_LOCK = threading.RLock()
DAIMON_EPSILON = 0.1
BRAIN_CHANGE_COUNTER = 0
BRAIN_LAST_SAVE_TIME = 0.0

ROUTE = [
    {"latitude": 8.9922, "longitude": -79.5201, "name": "Albrook Mall"},
    {"latitude": 8.8805, "longitude": -79.7684, "name": "Arraijan Town Center"},
    {"latitude": 8.8650, "longitude": -79.7850, "name": "La Chorrera Centro"},
    {"latitude": 8.8900, "longitude": -79.7700, "name": "Plaza La Chorrera"},
    {"latitude": 8.8750, "longitude": -79.7900, "name": "San Carlos"},
]

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
if not DEEPSEEK_API_KEY:
    DEEPSEEK_API_KEY = os.getenv("DSK_DEV_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"

RADAR_CONFIG = {
    "tarifa_minima_usd": 3.13, "eta_maxima_recogida_min": 4,
    "eta_maxima_entrega_min": 6, "ingreso_minimo_por_hora_usd": 9.0,
    "ingreso_optimo_por_hora_usd": 15.0, "top_k_default": 3,
    "timeout_ollama_default": 30, "cache_max_size": 100,
    "cache_ttl_segundos": 300, "rate_limit_consultas_por_minuto": 10,
    "zona_roja_bonus": 100.0, "zona_naranja_bonus": 50.0,
    "hora_pico_bonus": 1.3, "madrugada_penalty": 0.7,
}
RADAR_CONFIG_LOCK = threading.RLock()

_radar_cache = deque(maxlen=100)
_radar_cache_lock = threading.RLock()
_ollama_request_times = deque(maxlen=10)
_ollama_rate_lock = threading.RLock()

_ZONA_CACHE = {}
_ZONA_CACHE_TTL = 300
_ZONA_CACHE_LOCK = threading.RLock()

# ================================================================================
# SECCION 7: FUNCIONES DE GESTION THREAD-SAFE (CORREGIDO)
# ================================================================================

# Tipos validos para variables globales
_VALID_TYPES = {
    'ESTADO_CONDUCTOR': (str,),
    'VIAJE_EN_CURSO': (dict, type(None)),
    'GPS_ACTIVO': (bool,),
    'GPS_ACTUAL': (dict, type(None)),
    'GPS_OBJETIVO': (dict, type(None)),
    'ULTIMA_ZONA': (str,),
    'FACTOR': (float, int),
    'simulation_active': (bool,),
    'IA_READY': (bool,),
    'WEB_ACCESSED': (bool,),
    'MEJOR_OPCION_PROMPT_ACTIVO': (bool,),
    'MODO_NEGOCIACION_IA': (bool,),
}

def safe_get_global(var_name, default=None):
    """Obtiene variable global de forma thread-safe"""
    with GLOBAL_LOCK:
        return globals().get(var_name, default)

def safe_set_global(var_name, value, validate_fn=None):
    """Establece variable global de forma thread-safe con validacion"""
    with GLOBAL_LOCK:
        # Validacion de tipo basica
        if var_name in _VALID_TYPES:
            if not isinstance(value, _VALID_TYPES[var_name]):
                log(f"[WARN] Tipo invalido para {var_name}: esperado {_VALID_TYPES[var_name]}, got {type(value)}", "CONFIG")
                return False
        
        # Validacion personalizada si existe
        if validate_fn and not validate_fn(value):
            log(f"[WARN] Validacion fallida para {var_name}", "CONFIG")
            return False
        
        # Log de cambios importantes
        old_value = globals().get(var_name)
        if old_value != value and var_name in ['ESTADO_CONDUCTOR', 'GPS_ACTIVO', 'IA_READY']:
            log(f"[STATE] {var_name}: {old_value} -> {value}", "CONFIG")
        
        globals()[var_name] = value
        return True

def update_algo_weight(key, new_value, min_val=None, max_val=None):
    """Actualiza pesos del algoritmo con validacion de rangos"""
    with ALGO_WEIGHTS_LOCK:
        if key not in ALGO_WEIGHTS:
            log(f"[WARN] Peso desconocido: {key}", "CONFIG")
            return False
        
        # Validacion de tipo
        try:
            new_value = float(new_value)
        except (TypeError, ValueError):
            log(f"[WARN] Valor invalido para {key}: {new_value} no es numerico", "CONFIG")
            return False
        
        # Aplicar limites
        if min_val is not None and new_value < min_val:
            new_value = min_val
            log(f"[WARN] {key} ajustado al minimo: {min_val}", "CONFIG")
        if max_val is not None and new_value > max_val:
            new_value = max_val
            log(f"[WARN] {key} ajustado al maximo: {max_val}", "CONFIG")
        
        old_value = ALGO_WEIGHTS[key]
        ALGO_WEIGHTS[key] = new_value
        log(f"[CONFIG] {key}: {old_value:.4f} -> {new_value:.4f}", "CONFIG")
        return True

def get_zona_estado_threadsafe(zona_id):
    """Obtiene estado de zona de forma thread-safe"""
    with ZONA_LOCK:
        return dict(zona_estado.get(zona_id, {}))

def update_zona_estado_threadsafe(zona_id, updates):
    """Actualiza estado de zona de forma thread-safe"""
    if not isinstance(updates, dict):
        log(f"[WARN] updates debe ser dict, got {type(updates)}", "CONFIG")
        return False
    
    with ZONA_LOCK:
        if zona_id not in zona_estado:
            log(f"[WARN] Zona {zona_id} no existe", "CONFIG")
            return False
        
        # Validar updates basicos
        for key, value in updates.items():
            if key in ['demanda', 'oferta']:
                updates[key] = max(0, int(value) if isinstance(value, (int, float)) else 0)
            elif key in ['ganancia_estimada', 'tiempo_espera', 'ratio_demanda']:
                updates[key] = float(value) if isinstance(value, (int, float)) else 0.0
        
        zona_estado[zona_id].update(updates)
        zona_estado[zona_id]["ultima_actualizacion"] = time.time()
        
        # Invalidar cache
        with _ZONA_CACHE_LOCK:
            if zona_id in _ZONA_CACHE:
                del _ZONA_CACHE[zona_id]
        
        return True

def cache_zona_with_ttl(zona_id, data, ttl_seconds=None):
    """Almacena datos de zona en cache con TTL"""
    if ttl_seconds is None:
        ttl_seconds = _ZONA_CACHE_TTL
    
    if ttl_seconds <= 0:
        return
    
    with _ZONA_CACHE_LOCK:
        _ZONA_CACHE[zona_id] = {
            "data": copy.deepcopy(data),  # Deep copy para evitar mutaciones externas
            "expires_at": time.time() + ttl_seconds,
            "created_at": time.time()
        }
        
        # Limpiar entradas expiradas
        now = time.time()
        expired = [k for k, v in _ZONA_CACHE.items() if v["expires_at"] < now]
        for k in expired:
            del _ZONA_CACHE[k]

def get_cached_zona(zona_id):
    """Obtiene datos de zona desde cache si no expiraron"""
    with _ZONA_CACHE_LOCK:
        entry = _ZONA_CACHE.get(zona_id)
        if entry and entry["expires_at"] > time.time():
            return copy.deepcopy(entry["data"])  # Deep copy para evitar mutaciones
        return None

def invalidate_zona_cache(zona_id=None):
    """Invalida cache de zona(s)"""
    with _ZONA_CACHE_LOCK:
        if zona_id:
            _ZONA_CACHE.pop(zona_id, None)
        else:
            _ZONA_CACHE.clear()
        log(f"[CACHE] Cache de zonas invalidado: {zona_id if zona_id else 'todas'}", "CONFIG")

# ================================================================================
# SECCION 8: FUNCIONES DE MONITOREO Y DIAGNOSTICO (CORREGIDO)
# ================================================================================

def get_system_health():
    """Obtiene estado de salud del sistema de forma segura"""
    # Capturar estado de locks sin bloquear
    zona_lock_acquired = False
    try:
        zona_lock_acquired = ZONA_LOCK.acquire(blocking=False)
        if zona_lock_acquired:
            ZONA_LOCK.release()
    except:
        pass
    
    health = {
        "timestamp": time.time(),
        "threads_active": threading.active_count(),
        "stop_event_set": STOP_EVENT.is_set(),
        "gps": {
            "activo": GPS_ACTIVO,
            "ultima_actualizacion": ULTIMA_ACTUALIZACION_GPS,
            "historial_size": len(historial_gps)
        },
        "zonas": {
            "totales": len(ZONAS),
            "cache_size": len(_ZONA_CACHE),
            "estado_lock_disponible": zona_lock_acquired
        },
        "blockchain": {
            "bloques": len(blockchain),
            "numero_actual": block_number
        },
        "aprendizaje": {
            "q_table_size": len(Q_TABLE),
            "epsilon": DAIMON_EPSILON,
            "brain_changes": BRAIN_CHANGE_COUNTER
        },
        "configuracion": {
            "algo_weights_count": len(ALGO_WEIGHTS),
            "radar_config_keys": len(RADAR_CONFIG)
        },
        "memoria": {
            "heap_qsize": len(heapq) if 'heapq' in dir() else 0,
            "gc_threshold": gc.get_threshold()
        }
    }
    
    # Validar valores NaN/Inf
    for key, value in health.items():
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            health[key] = 0.0
    
    return health

def snapshot_globals(include_values=True):
    """Toma una snapshot segura de las variables globales"""
    with GLOBAL_LOCK:
        # Manejar UBER_COINS segun disponibilidad
        uber_value = 0.0
        if UBER_COINS is not None:
            try:
                uber_value = UBER_COINS.to_float_approx() if hasattr(UBER_COINS, 'to_float_approx') else float(UBER_COINS)
            except:
                uber_value = 0.0
        
        return {
            "timestamp": time.time(),
            "control": {
                "STOP_EVENT": STOP_EVENT.is_set(),
                "simulation_active": simulation_active,
                "IA_READY": IA_READY
            },
            "gps": {
                "GPS_ACTIVO": GPS_ACTIVO,
                "GPS_ACTUAL": copy.deepcopy(GPS_ACTUAL) if include_values and GPS_ACTUAL else None,
                "GPS_OBJETIVO": copy.deepcopy(GPS_OBJETIVO) if include_values and GPS_OBJETIVO else None,
                "historial_gps_count": len(historial_gps)
            },
            "conductor": {
                "ULTIMA_ZONA": ULTIMA_ZONA,
                "ESTADO_CONDUCTOR": ESTADO_CONDUCTOR,
                "VIAJE_EN_CURSO": copy.deepcopy(VIAJE_EN_CURSO) if include_values and VIAJE_EN_CURSO else None
            },
            "economia": {
                "BENEFICIARIO_ACTUAL": BENEFICIARIO_ACTUAL,
                "FACTOR": FACTOR,
                "UBER_COINS_value": uber_value
            }
        }

def reset_critical_state(preserve_learning=True):
    """Reset del estado critico del sistema con manejo seguro de locks"""
    log("[HEAL] Iniciando reset de estado critico", "SYSTEM")
    
    # Adquirir todos los locks necesarios en orden para evitar deadlock
    locks_to_acquire = [GLOBAL_LOCK, _ZONA_CACHE_LOCK, _radar_cache_lock]
    acquired_locks = []
    
    try:
        # Adquirir locks en orden
        for lock in locks_to_acquire:
            acquired = lock.acquire(timeout=5.0)
            if not acquired:
                log(f"[HEAL] Timeout adquiriendo lock {lock}", "WARN")
                # Liberar los que ya tenemos
                for l in acquired_locks:
                    l.release()
                return {"exito": False, "error": "Timeout adquiriendo locks"}
            acquired_locks.append(lock)
        
        # Resetear variables
        globals()["ESTADO_CONDUCTOR"] = "IDLE"
        globals()["VIAJE_EN_CURSO"] = None
        globals()["TIEMPO_INICIO_VIAJE"] = None
        globals()["GPS_ACTIVO"] = False
        globals()["GPS_ACTUAL"] = None
        globals()["GPS_OBJETIVO"] = None
        globals()["historial_gps"].clear()
        globals()["ULTIMA_ACTUALIZACION_GPS"] = 0.0
        globals()["WEB_ACCESSED"] = False
        globals()["MEJOR_OPCION_PROMPT_ACTIVO"] = False
        globals()["MODO_NEGOCIACION_IA"] = False
        
        if not preserve_learning:
            globals()["Q_TABLE"].clear()
            globals()["DAIMON_EPSILON"] = 0.1
            globals()["BRAIN_CHANGE_COUNTER"] = 0
            log("[HEAL] Aprendizaje reiniciado", "SYSTEM")
        
        _ZONA_CACHE.clear()
        _radar_cache.clear()
        
        log("[HEAL] Reset de estado critico completado", "SYSTEM")
        return {"exito": True, "preserve_learning": preserve_learning}
    
    except Exception as e:
        log(f"[HEAL] Error durante reset: {e}", "ERROR")
        return {"exito": False, "error": str(e)}
    
    finally:
        # Liberar locks en orden inverso
        for lock in reversed(acquired_locks):
            lock.release()

def force_cleanup_memory():
    """Fuerza limpieza de memoria y caches"""
    log("[CLEAN] Forzando limpieza de memoria...", "SYSTEM")
    
    with GLOBAL_LOCK:
        # Limpiar caches
        with _ZONA_CACHE_LOCK:
            _ZONA_CACHE.clear()
        with _radar_cache_lock:
            _radar_cache.clear()
        
        # Limitar tamanio de logs
        with log_lock:
            while len(mining_log) > 500:
                mining_log.pop(0)
        
        # Forzar garbage collection
        gc.collect()
        
        stats = {
            "memory_freed": "forced GC",
            "zona_cache_cleared": True,
            "radar_cache_cleared": True,
            "log_size": len(mining_log)
        }
        
        log("[CLEAN] Limpieza completada", "SYSTEM")
        return stats

# ================================================================================
# SECCION 9: REDIRECCION SEGURA DE RUTAS PARA TERMUX
# ================================================================================
HOME = Path.home()

def _resolver_ruta_segura(ruta_base: Path, nombre_archivo: str) -> Path:
    try:
        if str(ruta_base).startswith('/sdcard'):
            parent_dir = ruta_base.parent
            if not os.access(str(parent_dir), os.W_OK):
                log("[PATH] Redirigiendo " + nombre_archivo + " a HOME por permisos", "INIT")
                target = HOME / nombre_archivo
                target.parent.mkdir(parents=True, exist_ok=True)
                return target
        ruta_base.parent.mkdir(parents=True, exist_ok=True)
        return ruta_base
    except Exception as e:
        log("[ERROR] Error resolviendo ruta: " + str(e), "INIT")
        fallback = HOME / nombre_archivo
        fallback.parent.mkdir(parents=True, exist_ok=True)
        return fallback

STATE_FILE = _resolver_ruta_segura(HOME / "state.json", "state.json")
HEART_FILE = _resolver_ruta_segura(Path("/sdcard/uber_coint"), "uber_coint")
DAIMON_BRAIN_FILE = _resolver_ruta_segura(HOME / "daimon_brain.json", "daimon_brain.json")
RESPONSES_MEMORY_FILE = _resolver_ruta_segura(HOME / "respuestas_uber.json", "respuestas_uber.json")
SOCIALCOIN_HEARTBEAT_FILE = _resolver_ruta_segura(HOME / "socialcoin_heartbeat.json", "socialcoin_heartbeat.json")
ULTIMA_ACTIVIDAD_BUCLE = time.time()

# ================================================================================
# SECCION 10: CLASE GLOBAL CONFIG MANAGER
# ================================================================================
class GlobalConfigManager:
    _instance = None
    _lock = threading.RLock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            self._config = {
                "max_threads": 4,
                "cache_ttl_seconds": 300,
                "log_level": "INFO",
                "rl_learning_rate": 0.001,
                "rl_epsilon_decay": 0.995,
                "fuzzy_threshold": 0.5,
                "api_timeout_seconds": 30,
                "retry_attempts": 3,
                "gps_update_interval": 300,
                "gps_fallback_enabled": True,
            }
            self._validators = {}
            self._callbacks = defaultdict(list)
            self._initialized = True
            log("[CONFIG] GlobalConfigManager inicializado", "INIT")

    def register_validator(self, key, validator_fn):
        with self._lock:
            self._validators[key] = validator_fn

    def register_callback(self, key, callback_fn):
        with self._lock:
            self._callbacks[key].append(callback_fn)

    def get(self, key, default=None):
        with self._lock:
            return self._config.get(key, default)

    def set(self, key, value, validate=True):
        with self._lock:
            if validate and key in self._validators:
                if not self._validators[key](value):
                    log("[WARN] Validacion fallida para config: " + key, "CONFIG")
                    return False
            old_value = self._config.get(key)
            self._config[key] = value
            for cb in self._callbacks.get(key, []):
                try:
                    cb(key, old_value, value)
                except Exception as e:
                    log("[ERROR] Callback config error: " + str(e), "CONFIG")
            return True

    def batch_update(self, updates, validate_all=True):
        with self._lock:
            for key, value in updates.items():
                if validate_all and key in self._validators:
                    if not self._validators[key](value):
                        log("[WARN] Validacion fallida en batch para: " + key, "CONFIG")
                        continue
                old_value = self._config.get(key)
                self._config[key] = value
                for cb in self._callbacks.get(key, []):
                    try:
                        cb(key, old_value, value)
                    except:
                        pass
            return True

    def snapshot(self):
        with self._lock:
            return dict(self._config)

    def save_to_file(self, filepath):
        try:
            with self._lock:
                data = {"config": dict(self._config), "timestamp": time.time()}
            tmp_path = Path(str(filepath) + ".tmp")
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            tmp_path.replace(Path(filepath))
            return True
        except Exception as e:
            log("[ERROR] Error guardando config: " + str(e), "CONFIG")
            return False

    def load_from_file(self, filepath):
        try:
            if not Path(filepath).exists():
                return False
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            config_data = data.get("config", {})
            with self._lock:
                self._config.update(config_data)
            log("[CONFIG] Configuracion cargada desde archivo", "INIT")
            return True
        except Exception as e:
            log("[ERROR] Error cargando config: " + str(e), "CONFIG")
            return False

config_manager = GlobalConfigManager()

# ================================================================================
# SECCION 11: VALIDADORES PREDEFINIDOS
# ================================================================================
def _validate_positive_float(value):
    return isinstance(value, (int, float)) and value > 0

def _validate_probability(value):
    return isinstance(value, (int, float)) and 0.0 <= value <= 1.0

def _validate_port(value):
    return isinstance(value, int) and 1024 <= value <= 65535

config_manager.register_validator("rl_learning_rate", _validate_positive_float)
config_manager.register_validator("rl_epsilon_decay", _validate_probability)
config_manager.register_validator("fuzzy_threshold", _validate_probability)
config_manager.register_validator("api_timeout_seconds", _validate_positive_float)
config_manager.register_validator("max_threads", lambda v: isinstance(v, int) and v >= 1)

log("[OK] Seccion 4-11: Configuracion base inicializada", "INIT")

# ================================================================================
# SECCION 12: FUNCIONES UTILITARIAS BASE (CORREGIDO)
# ================================================================================

# Niveles de log validos
_VALID_LOG_LEVELS = {"INFO", "WARN", "ERROR", "DEBUG", "CONFIG", "SYSTEM", "OK", "GPS", "RL", "IA", "NEGOC", "RADAR", "HEAL"}

def log(*args):
    """
    Funcion de logging mejorada con manejo robusto de argumentos.
    Uso: log("mensaje") -> tag INFO
         log("mensaje", "ERROR") -> tag ERROR
         log("mensaje", "TAG", "extra") -> extra ignorado, se logea TAG
    """
    # Manejo robusto de argumentos
    if len(args) == 0:
        return
    
    mensaje = str(args[0])
    tag = "INFO"
    
    if len(args) >= 2:
        potential_tag = str(args[1]).upper()
        if potential_tag in _VALID_LOG_LEVELS or len(potential_tag) <= 10:
            tag = potential_tag
    
    # Limitar longitud del mensaje para evitar spam
    if len(mensaje) > 1000:
        mensaje = mensaje[:997] + "..."
    
    timestamp = _datetime.now(_timezone.utc).strftime("%H:%M:%S")
    linea = f"[{timestamp}] [{tag}] {mensaje}"
    
    # Intentar escribir en consola de forma segura
    try:
        print(linea, flush=True)
    except (OSError, BrokenPipeError):
        pass  # Fallo silencioso si la consola no esta disponible
    
    # Almacenar en log circular
    with log_lock:
        try:
            mining_log.append({"ts": timestamp, "tag": tag, "message": mensaje})
            if len(mining_log) > 1000:  # Aumentado a 1000 para mejor trazabilidad
                mining_log.pop(0)
        except Exception:
            pass  # Fallo silencioso en almacenamiento de logs

def get_recent_logs(limit=50, tag_filter=None):
    """Obtiene logs recientes con filtro opcional por tag"""
    with log_lock:
        logs = list(mining_log)
    
    if tag_filter:
        tag_filter_upper = tag_filter.upper()
        logs = [log for log in logs if log.get('tag', '').upper() == tag_filter_upper]
    
    return logs[-limit:] if limit > 0 else logs

def log_error_with_traceback(mensaje, error=None):
    """Registra un error con su traceback completo"""
    error_msg = f"{mensaje}"
    if error:
        error_msg += f": {str(error)}"
    
    log(error_msg, "ERROR")
    
    # Registrar traceback en debug
    tb = traceback.format_exc()
    if tb and tb != "NoneType: None\n":
        for line in tb.split('\n')[:5]:  # Solo primeras 5 lineas
            if line.strip():
                log(f"  {line[:200]}", "DEBUG")

def sigmoid(x):
    """Funcion sigmoide segura con clipping"""
    try:
        clipped = max(-100, min(100, float(x)))
        return 1 / (1 + math.exp(-clipped))
    except (TypeError, ValueError, OverflowError):
        return 0.5

def dot(a, b):
    """Producto punto seguro"""
    try:
        return sum(float(x) * float(y) for x, y in zip(a, b))
    except (TypeError, ValueError):
        return 0.0

def calcular_distancia_py(lat1, lon1, lat2, lon2):
    """Calcula distancia entre coordenadas en kilometros"""
    try:
        lat1, lon1, lat2, lon2 = map(float, [lat1, lon1, lat2, lon2])
        R = 6371
        dLat = math.radians(lat2 - lat1)
        dLon = math.radians(lon2 - lon1)
        a = (math.sin(dLat / 2) ** 2 + 
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * 
             math.sin(dLon / 2) ** 2)
        # Evitar errores numericos
        a = max(0.0, min(1.0, a))
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    except Exception:
        return 999.0  # Distancia grande en caso de error

def tiene_internet_rapido(timeout: float = 1.5) -> bool:
    """Verifica conectividad a internet de forma rapida"""
    try:
        socket.setdefaulttimeout(timeout)
        socket.getaddrinfo("1.1.1.1", 53)
        return True
    except:
        pass
    
    try:
        with socket.create_connection(("8.8.8.8", 53), timeout=timeout):
            return True
    except:
        return False

def ollama_activo() -> bool:
    """Verifica si Ollama esta disponible localmente"""
    if requests is None:
        return False
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=0.3)
        return response.status_code == 200
    except:
        return False

def es_url_valida(url: str) -> bool:
    """Valida formato de URL"""
    return isinstance(url, str) and url.startswith(('http://', 'https://'))

def batch_write_file(filepath, content):
    """Escribe archivo de forma atomica usando archivo temporal"""
    try:
        tmp_path = Path(str(filepath) + ".tmp")
        tmp_path.write_text(content, encoding='utf-8')
        tmp_path.replace(Path(filepath))
        return True
    except Exception as e:
        log(f"[ERROR] Error en escritura batch: {e}", "ERROR")
        return False

def jittered_sleep(base_seconds: float):
    """Sleep con jitter y factor de actividad"""
    try:
        factor_val = activity_factor()
        factor_global = max(FACTOR, 1) if 'FACTOR' in globals() else 1
        delay = max(base_seconds * factor_val / factor_global, 0.05)
        delay *= random.uniform(0.8, 1.2)
        STOP_EVENT.wait(delay)
    except Exception:
        STOP_EVENT.wait(base_seconds)

def activity_factor(timestamp: Optional[float] = None) -> float:
    """Calcula factor de actividad basado en hora y dia"""
    try:
        if timestamp:
            dt = _datetime.fromtimestamp(timestamp, tz=_timezone.utc)
        else:
            dt = _datetime.now(_timezone.utc)
        
        hour = dt.hour
        if 7 <= hour <= 9:
            base = 1.6
        elif 17 <= hour <= 19:
            base = 1.8
        elif 2 <= hour <= 5:
            base = 0.25
        else:
            base = 1.0
        
        # Reducir fin de semana
        if dt.weekday() >= 5:
            base *= 0.9
        
        return round(base * random.uniform(0.85, 1.25), 3)
    except Exception:
        return 1.0

def adaptive_sleep(base_seconds):
    """Sleep adaptativo que considera nivel de bateria"""
    try:
        result = subprocess.run(['termux-battery-status'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            battery_info = json.loads(result.stdout)
            level = battery_info.get('percentage', 100)
            if isinstance(level, (int, float)) and level < 30:
                return STOP_EVENT.wait(base_seconds / 2)
    except Exception:
        pass
    return STOP_EVENT.wait(base_seconds)

def ensure_zone_exists(zone_id: str):
    """Crea zona dinamica si no existe"""
    global ZONAS, zona_estado, _ZONA_CACHE
    
    if not zone_id:
        return False
    
    with ZONA_LOCK:
        if zone_id not in [z["id"] for z in ZONAS]:
            nueva_zona = {
                "id": zone_id,
                "nombre": f"Zona Dinamica {zone_id}",
                "lat_min": 8.85, "lat_max": 8.88,
                "lon_min": -79.85, "lon_max": -79.81
            }
            ZONAS.append(nueva_zona)
            zona_estado[zone_id] = {
                "color": "gris", "ganancia_estimada": 0.0,
                "tiempo_espera": 0.0, "demanda": 0,
                "oferta": 0, "ratio_demanda": 0.0
            }
            with _ZONA_CACHE_LOCK:
                _ZONA_CACHE.clear()
            log(f"[ZONA] Zona {zone_id} creada dinamicamente", "OK")
            return True
    return False

def get_zona_by_id(zona_id: str):
    """Obtiene zona por ID con cache"""
    if not zona_id:
        return None
    
    # Intentar cache primero
    cached = get_cached_zona(zona_id)
    if cached:
        return cached
    
    # Buscar en lista
    with ZONA_LOCK:
        zona = next((z for z in ZONAS if z["id"] == zona_id), None)
        if zona:
            cache_zona_with_ttl(zona_id, zona)
    
    return zona

def corregir_tipos_metricas(metrics):
    """Corrige tipos de metricas a float seguro"""
    if not isinstance(metrics, dict):
        return {}
    
    corregido = {}
    for key, value in metrics.items():
        try:
            if isinstance(value, (list, tuple)):
                num_values = [v for v in value if isinstance(v, (int, float))]
                corregido[key] = float(num_values[0]) if num_values else 0.0
            elif isinstance(value, dict):
                num_values = [v for v in value.values() if isinstance(v, (int, float))]
                corregido[key] = float(num_values[0]) if num_values else 0.0
            elif isinstance(value, str):
                # Intentar convertir a float
                cleaned = value.replace(',', '.').strip()
                if cleaned.replace('.', '', 1).replace('-', '', 1).isdigit():
                    corregido[key] = float(cleaned)
                else:
                    corregido[key] = 0.0
            elif isinstance(value, (int, float)):
                corregido[key] = float(value)
            else:
                corregido[key] = 0.0
        except (TypeError, ValueError):
            corregido[key] = 0.0
    
    return corregido

def determinar_beneficiario(usuario: Optional[str] = None, url: Optional[str] = None) -> str:
    """Determina el beneficiario actual"""
    global BENEFICIARIO_ACTUAL
    
    if usuario and isinstance(usuario, str) and usuario.strip():
        BENEFICIARIO_ACTUAL = usuario.strip()
        log(f"[BENEF] Beneficiario definido: {BENEFICIARIO_ACTUAL}", "CONFIG")
    else:
        BENEFICIARIO_ACTUAL = "conductor_codigo"
        log("[BENEF] Beneficiario: conductor_codigo", "CONFIG")
    
    return BENEFICIARIO_ACTUAL

def _estado_a_clave(estado):
    """Convierte estado a clave string"""
    try:
        if len(estado) >= 3:
            zona, franja, tiene = estado[0], estado[1], estado[2]
            return f"{zona}|{franja}|{1 if tiene else 0}"
        return f"{estado}|unknown|0"
    except Exception:
        return f"{estado}|error|0"

def _clave_a_estado(clave: str):
    """Convierte clave string a estado"""
    try:
        partes = clave.split("|")
        if len(partes) >= 3:
            return (partes[0], partes[1], bool(int(partes[2])))
        return (clave, "unknown", False)
    except Exception:
        return (clave, "error", False)

def load_daimon_brain():
    """Carga el cerebro DAIMON desde archivo"""
    global Q_TABLE
    
    if not DAIMON_BRAIN_FILE.exists():
        log("[BRAIN] Archivo de cerebro no encontrado, usando valores por defecto", "WARN")
        return
    
    try:
        with open(DAIMON_BRAIN_FILE, "r", encoding='utf-8') as f:
            data = json.load(f)
        
        raw = data.get("q_table", {})
        reconstructed = {}
        
        for k, v in raw.items():
            try:
                estado = _clave_a_estado(k)
                reconstructed[estado] = v
            except Exception as e:
                log(f"[WARN] Clave invalida en cerebro: {k} - {e}", "WARN")
                continue
        
        with Q_TABLE_LOCK:
            Q_TABLE.clear()
            for estado, table in reconstructed.items():
                if isinstance(table, dict):
                    safe_table = {}
                    for act, val in table.items():
                        try:
                            safe_table[act] = float(val)
                        except (TypeError, ValueError):
                            safe_table[act] = 0.0
                    Q_TABLE[estado] = safe_table
        
        log(f"[BRAIN] Cerebro cargado: {len(Q_TABLE)} estados", "OK")
        
    except json.JSONDecodeError as e:
        log(f"[ERROR] Archivo de cerebro corrupto: {e}", "ERROR")
    except Exception as e:
        log(f"[ERROR] Error cargando cerebro: {e}", "ERROR")

def save_daimon_brain():
    """Guarda el cerebro DAIMON en archivo"""
    global BRAIN_CHANGE_COUNTER, BRAIN_LAST_SAVE_TIME
    
    current_time = time.time()
    BRAIN_CHANGE_COUNTER += 1
    
    # Guardar cada 5 minutos o cada 50 cambios
    if (current_time - BRAIN_LAST_SAVE_TIME >= 300) or (BRAIN_CHANGE_COUNTER >= 50):
        try:
            with Q_TABLE_LOCK:
                serial = {}
                for k, v in Q_TABLE.items():
                    try:
                        clave = k if isinstance(k, str) else _estado_a_clave(k)
                        serial[clave] = v
                    except Exception as e:
                        log(f"[WARN] Clave invalida al serializar: {k} - {e}", "WARN")
                        continue
            
            # Escritura atomica
            tmp = DAIMON_BRAIN_FILE.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({
                    "q_table": serial,
                    "daimon_id": DAIMON_ID,
                    "version": 1,
                    "saved_at": current_time
                }, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            
            tmp.replace(DAIMON_BRAIN_FILE)
            BRAIN_CHANGE_COUNTER = 0
            BRAIN_LAST_SAVE_TIME = current_time
            log("[BRAIN] Cerebro guardado exitosamente", "OK")
            
        except Exception as e:
            log(f"[ERROR] Error guardando cerebro: {e}", "ERROR")

def guardar_estado():
    """Guarda el estado del sistema"""
    try:
        uber_value = UBER_COINS.to_float_approx() if UBER_COINS else 0.0
        estado = {
            "blockchain": blockchain,
            "block_number": block_number,
            "uber_coins": uber_value,
            "timestamp": time.time(),
            "version": 1
        }
        batch_write_file(str(STATE_FILE), json.dumps(estado, indent=2))
        log(f"[STATE] Estado guardado: {len(blockchain)} bloques", "OK")
    except Exception as e:
        log(f"[ERROR] Error guardando estado: {e}", "ERROR")

def cargar_estado():
    """Carga el estado del sistema"""
    global blockchain, block_number, UBER_COINS
    
    try:
        if STATE_FILE.exists():
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                estado = json.load(f)
            
            blockchain = estado.get('blockchain', [])
            block_number = estado.get('block_number', 1)
            coins_valor = estado.get('uber_coins', 0.0)
            
            try:
                coins_float = float(coins_valor)
                UBER_COINS = HyperNumberAdvanced(coins_float)
            except (TypeError, ValueError):
                UBER_COINS = HyperNumberAdvanced(0.0)
            
            log(f"[STATE] Estado cargado: {len(blockchain)} bloques, {UBER_COINS.to_float_approx():.2f} coins", "OK")
        else:
            UBER_COINS = HyperNumberAdvanced(0.0)
            log("[STATE] No hay estado previo, inicializando desde cero", "WARN")
    except json.JSONDecodeError as e:
        log(f"[ERROR] Archivo de estado corrupto: {e}", "ERROR")
        UBER_COINS = HyperNumberAdvanced(0.0)
    except Exception as e:
        log(f"[ERROR] Error cargando estado: {e}", "ERROR")
        UBER_COINS = HyperNumberAdvanced(0.0)

def latir_corazon(bloque_data):
    """Registra heartbeat del sistema"""
    try:
        uber_value = UBER_COINS.to_float_approx() if UBER_COINS else 0.0
        heartbeat_data = {
            'timestamp': time.time(),
            'block_id': bloque_data.get('block_id', 'unknown'),
            'reward': bloque_data.get('reward', 0),
            'zona': bloque_data.get('zona', 'unknown'),
            'uber_coins': uber_value,
            'estado_conductor': globals().get('ESTADO_CONDUCTOR', 'UNKNOWN')
        }
        batch_write_file(str(HEART_FILE), json.dumps(heartbeat_data, indent=2))
    except Exception:
        pass  # Heartbeat no critico

def leer_gps_actual():
    """Lee posicion GPS actual con fallback simulado"""
    max_intentos = 3
    timeout_base = 8
    
    for intento in range(max_intentos):
        try:
            resultado = subprocess.run(
                ['termux-location', '--request', 'single', '--providers', 'gps,network'],
                capture_output=True, text=True, timeout=timeout_base + (intento * 2)
            )
            
            if resultado.returncode == 0:
                datos_gps = json.loads(resultado.stdout)
                ubicacion = {
                    "lat": float(datos_gps.get('latitude', 8.9922)),
                    "lng": float(datos_gps.get('longitude', -79.5201)),
                    "precision": float(datos_gps.get('accuracy', 10.0)),
                    "fuente": "GPS_REAL",
                    "timestamp": time.time()
                }
                log(f"[GPS] REAL: {round(ubicacion['lat'], 6)}, {round(ubicacion['lng'], 6)}", "GPS")
                return ubicacion
            else:
                log(f"[WARN] termux-location fallo (intento {intento + 1})", "GPS")
                
        except subprocess.TimeoutExpired:
            log(f"[WARN] Timeout GPS (intento {intento + 1})", "GPS")
        except json.JSONDecodeError:
            log(f"[WARN] JSON invalido en respuesta GPS (intento {intento + 1})", "GPS")
        except Exception as e:
            log(f"[WARN] Error GPS (intento {intento + 1}): {e}", "GPS")
        
        if intento < max_intentos - 1:
            time.sleep(2)
    
    # Fallback a GPS simulado
    log("[GPS] Usando ubicacion simulada", "WARN")
    zona_info = get_zona_by_id(ULTIMA_ZONA)
    
    if zona_info:
        lat_centro = (zona_info["lat_min"] + zona_info["lat_max"]) / 2
        lng_centro = (zona_info["lon_min"] + zona_info["lon_max"]) / 2
        return {
            "lat": lat_centro + random.uniform(-0.005, 0.005),
            "lng": lng_centro + random.uniform(-0.005, 0.005),
            "precision": 15.0,
            "fuente": "GPS_SIMULADO",
            "timestamp": time.time()
        }
    
    return {
        "lat": 8.9922,
        "lng": -79.5201,
        "precision": 20.0,
        "fuente": "GPS_DEFAULT",
        "timestamp": time.time()
    }

# ================================================================================
# SECCION 13: CONECTOR OLLAMA LOCAL
# ================================================================================
class ConectorOllamaLocal:
    def __init__(self, modelo="qwen2.5:0.5b", timeout=600, max_modificaciones_por_ciclo=3):
        self.modelo = modelo
        self.timeout = timeout
        self.max_modificaciones_por_ciclo = max_modificaciones_por_ciclo
        self.ultima_respuesta = None
        self.contador_modificaciones = 0
        self.ultimo_reset_modificaciones = time.time()
        self.modelos_disponibles = []
        self.diagnostico_conexion()

    def diagnostico_conexion(self):
        try:
            resultado = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=10, encoding='utf-8')
            if resultado.returncode == 0:
                for linea in resultado.stdout.strip().split('\n')[1:]:
                    if linea.strip():
                        partes = linea.split()
                        if partes:
                            modelo = partes[0]
                            tamano = partes[-2] if len(partes) > 2 else "desconocido"
                            self.modelos_disponibles.append({
                                'nombre': modelo, 'tamano': tamano,
                                'prioridad': self._calcular_prioridad_modelo(modelo)
                            })
                self.modelos_disponibles.sort(key=lambda x: x['prioridad'], reverse=True)
                if self.modelo not in [m['nombre'] for m in self.modelos_disponibles]:
                    if self.modelos_disponibles:
                        self.modelo = self.modelos_disponibles[0]['nombre']
                return True
            return False
        except: return False

    def _calcular_prioridad_modelo(self, modelo):
        modelo_lower = modelo.lower()
        if '1.5b' in modelo_lower or '1b' in modelo_lower: return 100
        elif '3b' in modelo_lower: return 80
        elif '7b' in modelo_lower: return 60
        elif '8b' in modelo_lower: return 50
        else: return 10

    def _puede_modificar(self):
        if time.time() - self.ultimo_reset_modificaciones > 3600:
            self.contador_modificaciones = 0
            self.ultimo_reset_modificaciones = time.time()
        return self.contador_modificaciones < self.max_modificaciones_por_ciclo

    def consultar(self, prompt, contexto="", timeout_generacion=None, prioridad_baja=False):
        if not self._puede_modificar() and "modificar" in prompt.lower():
            return {"exito": False, "error": "limite_modificaciones", "mensaje": "Demasiadas modificaciones"}
        try:
            modelo_actual = self.modelo
            timeout_actual = timeout_generacion or self.timeout
            if prioridad_baja and len(self.modelos_disponibles) > 1:
                modelos_rapidos = [m for m in self.modelos_disponibles if m['prioridad'] >= 80]
                if modelos_rapidos:
                    modelo_actual = modelos_rapidos[0]['nombre']
                    timeout_actual = min(timeout_actual, 60)
            prompt_completo = 'SYSTEM MODE: STRICT JSON OUTPUT\nReglas: SOLO JSON valido, SIN texto adicional.\nContexto: ' + contexto[:200] + '\nInstruccion: ' + prompt[:300] + '\nOUTPUT: {"analisis": "", "propuesta_codigo": "", "justificacion": "", "impacto": "bajo|medio|alto"}'
            proceso = subprocess.run(
                ["ollama", "run", modelo_actual], input=prompt_completo,
                capture_output=True, text=True, timeout=timeout_actual, encoding='utf-8'
            )
            if proceso.returncode != 0:
                return {"exito": False, "error": proceso.stderr[:200]}
            respuesta_bruta = proceso.stdout.strip()
            self.ultima_respuesta = respuesta_bruta
            resultado = self._extraer_json_seguro(respuesta_bruta)
            if resultado:
                if "modificar" in prompt.lower() or "cambiar" in prompt.lower():
                    self.contador_modificaciones += 1
                return {"exito": True, "respuesta": resultado, "modelo": modelo_actual}
            else:
                codigo = self._extraer_codigo_de_texto(respuesta_bruta)
                return {"exito": False, "respuesta": respuesta_bruta, "codigo_extraido": codigo, "modelo": modelo_actual}
        except subprocess.TimeoutExpired:
            if not prioridad_baja and "7b" in modelo_actual:
                return self.consultar(prompt, contexto, timeout_generacion=300, prioridad_baja=True)
            return {"exito": False, "error": "timeout"}
        except Exception as e:
            return {"exito": False, "error": str(e)}

    def _extraer_json_seguro(self, texto):
        for match in re.findall(r'\{[^{}]*\}', texto, re.DOTALL):
            try: return json.loads(match)
            except: continue
        inicio = texto.find('{'); fin = texto.rfind('}')
        if inicio != -1 and fin > inicio:
            try: return json.loads(texto[inicio:fin + 1])
            except: pass
        return None

    def _extraer_codigo_de_texto(self, texto):
        patrones = [
            r'```python\s*(.*?)```', r'```\s*(.*?)```',
            r'propuesta_codigo["\']?\s*:\s*["\'](.*?)["\']',
        ]
        for patron in patrones:
            match = re.search(patron, texto, re.DOTALL | re.IGNORECASE)
            if match: return match.group(1).strip()
        return None

# ================================================================================
# SECCION 14: CONTROLADOR DE MODIFICACIONES
# ================================================================================
class ControladorModificaciones:
    def __init__(self, max_por_ciclo=3, cooldown_minutos=5):
        self.max_por_ciclo = max_por_ciclo
        self.cooldown = cooldown_minutos * 60
        self.modificaciones = []
        self.ultimo_reset = time.time()

    def puede_modificar(self, tipo="normal"):
        ahora = time.time()
        self.modificaciones = [m for m in self.modificaciones if ahora - m['tiempo'] < self.cooldown]
        if len(self.modificaciones) >= self.max_por_ciclo:
            return False
        self.modificaciones.append({'tipo': tipo, 'tiempo': ahora})
        return True

    def get_estadisticas(self):
        return {
            'activas': len(self.modificaciones), 'maximo': self.max_por_ciclo,
            'cooldown_minutos': self.cooldown / 60,
            'ultimas': self.modificaciones[-3:] if self.modificaciones else []
        }

# ================================================================================
# SECCION 15: GESTOR DEEPSEEK
# ================================================================================
class GestorDeepSeek:
    def __init__(self, api_key=None):
        self.api_key = api_key or DEEPSEEK_API_KEY
        self.base_url = DEEPSEEK_BASE_URL
        self.timeout = 30

    def configurar_token(self, token: str) -> bool:
        self.api_key = token
        return True

    def consultar_deepseek(self, prompt, contexto=""):
        if requests is None:
            return {"exito": False, "error": "Requests no disponible"}
        try:
            headers = {"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"}
            data = {
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": contexto[:500]},
                    {"role": "user", "content": prompt[:1000]}
                ],
                "temperature": 0.7, "max_tokens": 500
            }
            response = requests.post(
                self.base_url + "/chat/completions",
                headers=headers, json=data, timeout=self.timeout
            )
            if response.status_code == 200:
                result = response.json()
                return {"exito": True, "respuesta": result["choices"][0]["message"]["content"]}
            else:
                return {"exito": False, "error": "HTTP " + str(response.status_code)}
        except Exception as e:
            return {"exito": False, "error": str(e)}

conector_ollama = ConectorOllamaLocal()
gestor_deepseek = GestorDeepSeek()

# ================================================================================
# SECCION 16: ESTRUCTURAS DE DATOS AVANZADAS PARA RL
# ================================================================================
class Experience:
    __slots__ = ('state', 'action', 'reward', 'next_state', 'done', 'priority', 'n_step', 'gamma_n')

    def __init__(self, state, action, reward, next_state, done, priority=1.0, n_step=1, gamma_n=0.99):
        self.state = state
        self.action = action
        self.reward = reward
        self.next_state = next_state
        self.done = done
        self.priority = priority
        self.n_step = n_step
        self.gamma_n = gamma_n

class NStepTransition:
    __slots__ = ('states', 'actions', 'rewards', 'final_state', 'done')

    def __init__(self, states=None, actions=None, rewards=None, final_state=None, done=False):
        self.states = states if states is not None else []
        self.actions = actions if actions is not None else []
        self.rewards = rewards if rewards is not None else []
        self.final_state = final_state
        self.done = done

class EpisodicMemory:
    def __init__(self, capacity=10000):
        self.capacity = capacity
        self.episodes = deque(maxlen=capacity)

    def add_episode(self, episodes, metadata=None):
        episode = {
            'experiences': episodes,
            'total_reward': sum(e.reward for e in episodes),
            'length': len(episodes),
            'metadata': metadata or {},
            'timestamp': time.time()
        }
        self.episodes.append(episode)

    def get_similar_episodes(self, current_state, k=5):
        similares = []
        for ep in self.episodes:
            if ep['experiences']:
                state_ep = ep['experiences'][0].state
                similarity = self._calculate_similarity(current_state, state_ep)
                similares.append((similarity, ep))
        similares.sort(key=lambda x: x[0], reverse=True)
        return [ep for _, ep in similares[:k]]

    def _calculate_similarity(self, state1, state2):
        if isinstance(state1, (int, float)) and isinstance(state2, (int, float)):
            return 1.0 - min(1.0, abs(state1 - state2) / 100)
        elif isinstance(state1, dict) and isinstance(state2, dict):
            common = set(state1.keys()) & set(state2.keys())
            if not common:
                return 0.0
            diff = sum(abs(state1[k] - state2[k]) for k in common if isinstance(state1[k], (int, float)))
            return 1.0 / (1.0 + diff)
        return 0.5

    def get_transferable_learning(self, current_state):
        similares = self.get_similar_episodes(current_state, k=3)
        if not similares:
            return {}
        knowledge = {'successful_actions': defaultdict(float), 'average_reward': 0, 'patterns': []}
        for ep in similares:
            for exp in ep['experiences']:
                knowledge['successful_actions'][exp.action] += exp.reward
            knowledge['average_reward'] += ep['total_reward']
            knowledge['patterns'].append({'length': ep['length'], 'reward': ep['total_reward']})
        knowledge['average_reward'] /= len(similares) if similares else 1
        return knowledge

# ================================================================================
# SECCION 17: DOUBLE DQN CON PER Y N-STEP
# ================================================================================
class DoubleDQN:
    def __init__(self, state_dim, action_dim, learning_rate=0.001, gamma=0.99,
                 epsilon_start=1.0, epsilon_end=0.01, epsilon_decay=0.995,
                 memory_size=10000, batch_size=32, target_update_frequency=100):
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.lr = learning_rate
        self.gamma = gamma
        self.epsilon = epsilon_start
        self.epsilon_end = epsilon_end
        self.epsilon_decay = epsilon_decay
        self.batch_size = batch_size
        self.target_update_freq = target_update_frequency
        self.steps = 0
        self.training_steps = 0

        if np is not None:
            self.q_network = self._init_network(state_dim, action_dim)
            self.target_network = self._init_network(state_dim, action_dim)
            self.optimizer_state = self._init_optimizer_state()
        else:
            self.q_table = defaultdict(lambda: [0.0] * action_dim)

        self.memory = deque(maxlen=memory_size)
        self.priorities = deque(maxlen=memory_size)
        self.alpha = 0.6
        self.beta = 0.4
        self.beta_increment = 0.001
        self.n_step_buffer = deque(maxlen=5)
        self.n_step = 5
        self.n_step_gamma = math.pow(gamma, self.n_step)
        self.loss_history = deque(maxlen=100)
        self.td_error_history = deque(maxlen=100)

    def _to_key(self, state):
        try:
            if np is not None and isinstance(state, np.ndarray):
                return tuple(state.flatten().tolist())
            elif isinstance(state, (list, tuple)):
                return tuple(state)
            return state
        except Exception:
            return str(state)

    def _init_network(self, state_dim, action_dim):
        if np is None: return {}
        return {
            'w1': np.random.randn(state_dim, 128) * np.sqrt(2.0 / state_dim),
            'b1': np.zeros(128), 'w2': np.random.randn(128, 64) * np.sqrt(2.0 / 128),
            'b2': np.zeros(64), 'w3': np.random.randn(64, 32) * np.sqrt(2.0 / 64),
            'b3': np.zeros(32), 'w4': np.random.randn(32, action_dim) * np.sqrt(2.0 / 32),
            'b4': np.zeros(action_dim)
        }

    def _init_optimizer_state(self):
        if np is None: return {}
        network = self.q_network
        return {
            'm': {k: np.zeros_like(v) for k, v in network.items()},
            'v': {k: np.zeros_like(v) for k, v in network.items()},
            'beta1': 0.9, 'beta2': 0.999, 'epsilon': 1e-8, 't': 0
        }

    def _forward(self, network, x, training=False):
        if np is None: return [0.0] * self.action_dim
        x = np.array(x).reshape(1, -1)
        z1 = np.dot(x, network['w1']) + network['b1']
        a1 = np.maximum(0.1 * z1, z1)
        z2 = np.dot(a1, network['w2']) + network['b2']
        a2 = np.maximum(0.1 * z2, z2)
        z3 = np.dot(a2, network['w3']) + network['b3']
        a3 = np.maximum(0.1 * z3, z3)
        z4 = np.dot(a3, network['w4']) + network['b4']
        return z4.flatten()

    def _backward(self, network, x, target, learning_rate, use_adam=True):
        if np is None: return network
        x = np.array(x).reshape(1, -1)
        z1 = np.dot(x, network['w1']) + network['b1']
        a1 = np.maximum(0.1 * z1, z1)
        z2 = np.dot(a1, network['w2']) + network['b2']
        a2 = np.maximum(0.1 * z2, z2)
        z3 = np.dot(a2, network['w3']) + network['b3']
        a3 = np.maximum(0.1 * z3, z3)
        z4 = np.dot(a3, network['w4']) + network['b4']
        output = z4.flatten()
        error = (output - target).reshape(-1, 1)
        grad_w4 = np.outer(a3.flatten(), error.flatten())
        grad_b4 = error.flatten()
        grad_a3 = np.dot(network['w4'], error)
        grad_z3 = grad_a3.flatten() * np.where(z3.flatten() > 0, 1.0, 0.1)
        grad_w3 = np.outer(a2.flatten(), grad_z3)
        grad_b3 = grad_z3
        grad_a2 = np.dot(network['w3'], grad_z3.reshape(-1, 1))
        grad_z2 = grad_a2.flatten() * np.where(z2.flatten() > 0, 1.0, 0.1)
        grad_w2 = np.outer(a1.flatten(), grad_z2)
        grad_b2 = grad_z2
        grad_a1 = np.dot(network['w2'], grad_z2.reshape(-1, 1))
        grad_z1 = grad_a1.flatten() * np.where(z1.flatten() > 0, 1.0, 0.1)
        grad_w1 = np.outer(x.flatten(), grad_z1)
        grad_b1 = grad_z1
        grad_clip_value = 1.0
        grads = [grad_w1, grad_b1, grad_w2, grad_b2, grad_w3, grad_b3, grad_w4, grad_b4]
        for grad in grads:
            np.clip(grad, -grad_clip_value, grad_clip_value, out=grad)
        if use_adam and hasattr(self, 'optimizer_state'):
            self._adam_update(network, {
                'w1': grad_w1, 'b1': grad_b1, 'w2': grad_w2, 'b2': grad_b2,
                'w3': grad_w3, 'b3': grad_b3, 'w4': grad_w4, 'b4': grad_b4
            }, learning_rate)
        else:
            network['w1'] -= learning_rate * grad_w1
            network['b1'] -= learning_rate * grad_b1
            network['w2'] -= learning_rate * grad_w2
            network['b2'] -= learning_rate * grad_b2
            network['w3'] -= learning_rate * grad_w3
            network['b3'] -= learning_rate * grad_b3
            network['w4'] -= learning_rate * grad_w4
            network['b4'] -= learning_rate * grad_b4
        return network

    def _adam_update(self, network, grads, learning_rate):
        state = self.optimizer_state
        state['t'] += 1
        t = state['t']
        beta1, beta2, epsilon = state['beta1'], state['beta2'], state['epsilon']
        for key in network.keys():
            if key not in grads: continue
            grad = grads[key]
            state['m'][key] = beta1 * state['m'][key] + (1 - beta1) * grad
            state['v'][key] = beta2 * state['v'][key] + (1 - beta2) * (grad ** 2)
            m_hat = state['m'][key] / (1 - beta1 ** t)
            v_hat = state['v'][key] / (1 - beta2 ** t)
            network[key] -= learning_rate * m_hat / (np.sqrt(v_hat) + epsilon)

    def store(self, state, action, reward, next_state, done):
        experience = Experience(state, action, reward, next_state, done)
        self.memory.append(experience)
        priority = (abs(reward) + 0.01) ** self.alpha
        self.priorities.append(priority)
        self.n_step_buffer.append(experience)
        if len(self.n_step_buffer) >= self.n_step or done:
            self._flush_n_step()

    def _flush_n_step(self):
        if not self.n_step_buffer: return
        n = len(self.n_step_buffer)
        state = self.n_step_buffer[0].state
        action = self.n_step_buffer[0].action
        reward_n = 0.0
        for i, exp in enumerate(self.n_step_buffer):
            reward_n += exp.reward * (self.gamma ** i)
        final_state = self.n_step_buffer[-1].next_state
        done = self.n_step_buffer[-1].done
        experience_n = Experience(state, action, reward_n, final_state, done, n_step=n)
        if len(self.memory) > 0:
            self.memory[-1] = experience_n
            self.priorities[-1] = (abs(reward_n) + 0.01) ** self.alpha

    def sample(self, batch_size):
        if len(self.memory) < batch_size: return []
        if np is not None:
            priorities = np.array(list(self.priorities))
        else:
            priorities = [1.0] * len(self.memory)
        priorities = np.maximum(priorities, 1e-6)
        probs = priorities ** self.alpha
        probs_sum = np.sum(probs)
        if probs_sum > 0:
            probs = probs / probs_sum
        else:
            probs = np.ones(len(priorities)) / len(priorities)
        indices = np.random.choice(len(self.memory), batch_size, p=probs, replace=False)
        experiences = [self.memory[i] for i in indices]
        weights = (len(self.memory) * probs[indices]) ** (-self.beta)
        weights = weights / np.max(weights)
        self.beta = min(1.0, self.beta + self.beta_increment)
        return experiences, indices, weights

    def update_priorities(self, indices, td_errors):
        for idx, td in zip(indices, td_errors):
            priority = (abs(td) + 0.01) ** self.alpha
            if idx < len(self.priorities):
                self.priorities[idx] = priority

    def select_action(self, state, exploit_only=False):
        if not exploit_only and random.random() < self.epsilon:
            return random.randint(0, self.action_dim - 1)
        if np is None:
            key = self._to_key(state)
            q_values = self.q_table.get(key, [0.0] * self.action_dim)
        else:
            q_values = self._forward(self.q_network, state, training=False)
        if np is not None:
            return int(np.argmax(q_values))
        else:
            return q_values.index(max(q_values)) if q_values else 0

    def get_q_values(self, state):
        if np is None:
            key = self._to_key(state)
            return self.q_table.get(key, [0.0] * self.action_dim)
        else:
            return self._forward(self.q_network, state, training=False)

    def learn(self, batch_size=None):
        if batch_size is None: batch_size = self.batch_size
        result = self.sample(batch_size)
        if not result or len(result) < 3: return {}
        experiences, indices, weights = result
        if not experiences: return {}
        losses = []
        td_errors_all = []
        for i, exp in enumerate(experiences):
            state, action, reward, next_state, done = exp.state, exp.action, exp.reward, exp.next_state, exp.done
            if np is not None:
                q_values_curr = self._forward(self.q_network, state, training=True)
                q_values_next_online = self._forward(self.q_network, next_state, training=False)
                q_values_next_target = self._forward(self.target_network, next_state, training=False)
                if not done:
                    best_action = int(np.argmax(q_values_next_online))
                    q_target = reward + self.gamma * q_values_next_target[best_action]
                else:
                    q_target = reward
                td_error = q_target - q_values_curr[action]
                target_q = q_values_curr.copy()
                target_q[action] = q_target
                effective_lr = self.lr * weights[i]
                self.q_network = self._backward(self.q_network, state, target_q, effective_lr)
                losses.append(td_error ** 2)
                td_errors_all.append(td_error)
            else:
                key = self._to_key(state)
                next_key = self._to_key(next_state)
                q_values = list(self.q_table.get(key, [0.0] * self.action_dim))
                next_q_values = list(self.q_table.get(next_key, [0.0] * self.action_dim))
                best_action = next_q_values.index(max(next_q_values)) if next_q_values else 0
                target = reward + self.gamma * next_q_values[best_action] * (1 - done)
                q_values[action] += self.lr * (target - q_values[action])
                self.q_table[key] = q_values
        if td_errors_all:
            self.update_priorities(indices, td_errors_all)
        self.epsilon = max(self.epsilon_end, self.epsilon * self.epsilon_decay)
        self.steps += 1
        if self.steps % self.target_update_freq == 0 and np is not None:
            self._soft_update_target(tau=1.0)
        if losses:
            avg_loss = np.mean(losses) if np is not None else 0
            self.loss_history.append(avg_loss)
        if td_errors_all:
            avg_td = np.mean(np.abs(td_errors_all)) if np is not None else 0
            self.td_error_history.append(avg_td)
        self.training_steps += 1
        return {
            'loss': np.mean(losses) if losses and np is not None else 0,
            'epsilon': self.epsilon, 'steps': self.training_steps,
            'avg_td_error': np.mean(np.abs(td_errors_all)) if td_errors_all and np is not None else 0
        }

    def _soft_update_target(self, tau=0.001):
        if np is None: return
        for key in self.q_network.keys():
            self.target_network[key] = tau * self.q_network[key] + (1 - tau) * self.target_network[key]

    def save_model(self, filepath):
        if np is None:
            import pickle
            with open(filepath, 'wb') as f:
                pickle.dump(dict(self.q_table), f)
        else:
            np.savez(filepath, q_network=self.q_network, target_network=self.target_network,
                     optimizer_state=self.optimizer_state, epsilon=self.epsilon,
                     steps=self.steps, training_steps=self.training_steps)

    def load_model(self, filepath):
        if np is None:
            import pickle
            with open(filepath, 'rb') as f:
                self.q_table.update(pickle.load(f))
        else:
            data = np.load(filepath, allow_pickle=True)
            self.q_network = data['q_network'].item()
            self.target_network = data['target_network'].item()
            if 'optimizer_state' in data:
                self.optimizer_state = data['optimizer_state'].item()
            self.epsilon = float(data['epsilon'])
            self.steps = int(data['steps'])
            self.training_steps = int(data['training_steps'])

    def get_stats(self):
        return {
            'epsilon': self.epsilon, 'memory_size': len(self.memory),
            'training_steps': self.training_steps,
            'avg_loss': np.mean(self.loss_history) if self.loss_history else 0,
            'avg_td_error': np.mean(self.td_error_history) if self.td_error_history else 0,
            'beta': self.beta
        }

    def decay_epsilon_custom(self, episode, total_episodes):
        progress = episode / total_episodes
        self.epsilon = self.epsilon_end + (1.0 - self.epsilon_end) * (1 - progress) ** 2
        return self.epsilon

# ================================================================================
# SECCION 18: SARSA AGENT
# ================================================================================
class SARSAAgent:
    def __init__(self, state_dim, action_dim, learning_rate=0.1, gamma=0.99,
                 epsilon=1.0, epsilon_decay=0.995, epsilon_end=0.01):
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.lr = learning_rate
        self.gamma = gamma
        self.epsilon = epsilon
        self.epsilon_decay = epsilon_decay
        self.epsilon_end = epsilon_end
        self.q_table = defaultdict(
            lambda: np.zeros(action_dim) if np is not None else [0.0] * action_dim
        )

    def _to_key(self, state):
        try:
            if np is not None and isinstance(state, np.ndarray):
                return tuple(state.flatten().tolist())
            elif isinstance(state, (list, tuple)):
                return tuple(state)
            return state
        except Exception:
            return tuple(str(state))

    def select_action(self, state, exploit_only=False):
        if not exploit_only and random.random() < self.epsilon:
            return random.randint(0, self.action_dim - 1)
        key = self._to_key(state)
        q_vals = list(self.q_table.get(key, [0.0] * self.action_dim))
        if np is not None:
            return int(np.argmax(q_vals))
        else:
            return q_vals.index(max(q_vals))

    def update(self, state, action, reward, next_state, next_action, done):
        key = self._to_key(state)
        next_key = self._to_key(next_state)
        q_vals = list(self.q_table.get(key, [0.0] * self.action_dim))
        next_q_vals = list(self.q_table.get(next_key, [0.0] * self.action_dim))
        if done:
            q_vals[action] += self.lr * (reward - q_vals[action])
        else:
            q_vals[action] += self.lr * (reward + self.gamma * next_q_vals[next_action] - q_vals[action])
        self.q_table[key] = q_vals
        self.epsilon = max(self.epsilon_end, self.epsilon * self.epsilon_decay)

# ================================================================================
# SECCION 19: ACTOR-CRITICO (A2C/A3C)
# ================================================================================
class ActorCritic:
    def __init__(self, state_dim, action_dim, actor_lr=0.0003, critic_lr=0.001, gamma=0.99,
                 entropy_coef=0.01, value_coef=0.5, max_grad_norm=0.5):
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.gamma = gamma
        self.entropy_coef = entropy_coef
        self.value_coef = value_coef
        self.max_grad_norm = max_grad_norm
        self.actor_lr = actor_lr
        self.critic_lr = critic_lr
        if np is not None:
            self.actor_weights = self._init_layer(state_dim, action_dim)
            self.critic_weights = self._init_critic(state_dim)
        else:
            self.actor_weights = None
            self.critic_weights = None
        self.q_table = defaultdict(lambda: [0.0] * action_dim)
        self.policy_history = deque(maxlen=1000)
        self.value_history = deque(maxlen=1000)
        self.reward_history = deque(maxlen=1000)

    def _init_layer(self, in_dim, out_dim):
        if np is None: return {}
        return {'w': np.random.randn(in_dim, out_dim) * 0.01, 'b': np.zeros(out_dim)}

    def _init_critic(self, state_dim):
        if np is None: return {}
        return {
            'w1': np.random.randn(state_dim, 64) * np.sqrt(2.0 / state_dim),
            'b1': np.zeros(64), 
            'w2': np.random.randn(64, 1) * np.sqrt(2.0 / 64),
            'b2': np.zeros(1)
        }

    def _softmax(self, x):
        if np is None:
            max_x = max(x) if x else 0
            exp_x = [math.exp(i - max_x) for i in x]
            s = sum(exp_x)
            if s <= 0 or math.isnan(s) or math.isinf(s):
                return [1.0 / len(x) for _ in x]
            return [i / s for i in exp_x]
        exp_x = np.exp(x - np.max(x))
        s = exp_x.sum()
        if s <= 0 or np.isnan(s) or np.isinf(s):
            return np.ones(len(x)) / len(x)
        return exp_x / s

    def _forward_actor(self, state):
        if np is None: 
            return [1.0 / self.action_dim] * self.action_dim
        try:
            x = np.array(state).flatten()
            logits = np.dot(x, self.actor_weights['w']) + self.actor_weights['b']
            logits = np.clip(logits, -100, 100)
            probs = self._softmax(logits)
            if np.any(np.isnan(probs)) or np.any(np.isinf(probs)):
                probs = np.ones(self.action_dim) / self.action_dim
            return probs
        except Exception as e:
            log(f"[ActorCritic] Error en _forward_actor: {e}")
            return np.ones(self.action_dim) / self.action_dim

    def _forward_critic(self, state):
        if np is None: return 0.0
        try:
            x = np.array(state).flatten()
            h = np.dot(x, self.critic_weights['w1']) + self.critic_weights['b1']
            h = np.maximum(0, h)
            v = np.dot(h, self.critic_weights['w2']) + self.critic_weights['b2']
            if np.isnan(v) or np.isinf(v):
                return 0.0
            return float(v[0])
        except Exception as e:
            log(f"[ActorCritic] Error en _forward_critic: {e}")
            return 0.0

    def select_action(self, state):
        probs = self._forward_actor(state)
        if np is not None:
            prob_sum = np.sum(probs)
            if prob_sum <= 0 or np.isnan(prob_sum) or np.isinf(prob_sum):
                probs = np.ones(self.action_dim) / self.action_dim
            else:
                probs = probs / prob_sum
            if np.any(np.isnan(probs)):
                probs = np.ones(self.action_dim) / self.action_dim
            action = np.random.choice(self.action_dim, p=probs)
        else:
            prob_sum = sum(probs)
            if prob_sum <= 0:
                probs = [1.0 / self.action_dim] * self.action_dim
            else:
                probs = [p / prob_sum for p in probs]
            if any(math.isnan(p) or math.isinf(p) for p in probs):
                probs = [1.0 / self.action_dim] * self.action_dim
            action = random.choices(range(self.action_dim), weights=probs)[0]
        prob_action = probs[action] if action < len(probs) else 0.5
        if prob_action < 0.1:
            log(f"[ActorCritic] Baja confianza: accion={action}, prob={prob_action:.3f}")
        return int(action), float(prob_action)

    def update(self, states, actions, rewards, next_states, dones, next_value=0):
        n = len(states)
        if n == 0: return {}
        try:
            values = [self._forward_critic(s) for s in states]
            advantages = []
            gae = 0
            for i in reversed(range(n)):
                next_val = next_value if i == n - 1 else values[i + 1]
                delta = rewards[i] + self.gamma * next_val * (1 - dones[i]) - values[i]
                gae = delta + self.gamma * 0.95 * (1 - dones[i]) * gae
                advantages.insert(0, gae)
            if np is not None:
                advantages = np.array(advantages)
                if advantages.std() > 1e-8:
                    advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)
                else:
                    advantages = advantages - advantages.mean()
            total_loss = sum(adv ** 2 for adv in advantages)
            return {
                'policy_loss': -np.mean(advantages) if np is not None else -sum(advantages) / len(advantages),
                'value_loss': total_loss / n,
                'mean_advantage': np.mean(advantages) if np is not None else sum(advantages) / len(advantages)
            }
        except Exception as e:
            log(f"[ActorCritic] Error en update: {e}")
            return {'policy_loss': 0, 'value_loss': 0, 'mean_advantage': 0}

# ================================================================================
# SECCION 20: PPO OPTIMIZER
# ================================================================================
class PPOOptimizer:
    def __init__(self, state_dim, action_dim, lr=3e-4, gamma=0.99, epsilon=0.2,
                 value_coef=0.5, entropy_coef=0.01, lam=0.95):
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.lr = lr
        self.gamma = gamma
        self.epsilon = epsilon
        self.value_coef = value_coef
        self.entropy_coef = entropy_coef
        self.lam = lam
        if np is not None:
            self.policy_new = self._init_policy(state_dim, action_dim)
            self.policy_old = self._init_policy(state_dim, action_dim)
            self.value_net = self._init_value_net(state_dim)
        else:
            self.policy_new = defaultdict(lambda: [0.5] * action_dim)
            self.policy_old = defaultdict(lambda: [0.5] * action_dim)
        self.memory = deque(maxlen=10000)

    def _init_policy(self, state_dim, action_dim):
        if np is None: return {}
        return {'w': np.random.randn(state_dim, action_dim) * 0.01, 'b': np.zeros(action_dim)}

    def _init_value_net(self, state_dim):
        if np is None: return {}
        return {
            'w1': np.random.randn(state_dim, 64) * np.sqrt(2.0 / state_dim),
            'b1': np.zeros(64), 'w2': np.random.randn(64, 1), 'b2': np.zeros(1)
        }

    def _get_policy(self, state, policy):
        if np is None: return [0.5] * self.action_dim
        x = np.array(state).flatten()
        logits = np.dot(x, policy['w']) + policy['b']
        exp_logits = np.exp(logits - np.max(logits))
        return exp_logits / exp_logits.sum()

    def _get_value(self, state):
        if np is None: return 0.0
        x = np.array(state).flatten()
        h = np.dot(x, self.value_net['w1']) + self.value_net['b1']
        h = np.maximum(0, h)
        return np.dot(h, self.value_net['w2']) + self.value_net['b2']

    def select_action(self, state):
        probs = self._get_policy(state, self.policy_new)
        if np is not None:
            action = np.random.choice(self.action_dim, p=probs)
        else:
            action = random.choices(range(self.action_dim), weights=probs)[0]
        return int(action), probs[action]

    def store(self, state, action, reward, next_state, done, log_prob, value):
        self.memory.append({
            'state': state, 'action': action, 'reward': reward,
            'next_state': next_state, 'done': done, 'log_prob': log_prob, 'value': value
        })

    def compute_gae(self, rewards, values, dones):
        n = len(rewards)
        if np is not None:
            advantages = np.zeros(n)
        else:
            advantages = [0.0] * n
        gae = 0
        for i in reversed(range(n)):
            next_value = 0 if i == n - 1 else values[i + 1]
            delta = rewards[i] + self.gamma * next_value * (1 - dones[i]) - values[i]
            gae = delta + self.gamma * self.lam * (1 - dones[i]) * gae
            advantages[i] = gae
        if np is not None:
            returns = advantages + np.array(values)
        else:
            returns = [advantages[i] + values[i] for i in range(n)]
        return advantages, returns

    def update(self, epochs=10, batch_size=64):
        if len(self.memory) < batch_size: return {}
        if np is not None:
            self.policy_old = {k: v.copy() for k, v in self.policy_new.items()}
        states = [m['state'] for m in self.memory]
        actions = [m['action'] for m in self.memory]
        rewards = [m['reward'] for m in self.memory]
        dones = [m['done'] for m in self.memory]
        values = [self._get_value(s) for s in states]
        advantages, returns = self.compute_gae(rewards, values, dones)
        if np is not None and hasattr(advantages, 'std') and advantages.std() > 0:
            advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)
        losses = []
        for _ in range(epochs):
            if np is not None:
                indices = np.random.permutation(len(states))
            else:
                indices = list(range(len(states)))
                random.shuffle(indices)
            for i in range(0, len(states), batch_size):
                batch_idx = indices[i:i + batch_size]
                batch_states = [states[j] for j in batch_idx]
                batch_actions = [actions[j] for j in batch_idx]
                if np is not None:
                    batch_advantages = advantages[batch_idx]
                    batch_returns = returns[batch_idx]
                else:
                    batch_advantages = [advantages[j] for j in batch_idx]
                    batch_returns = [returns[j] for j in batch_idx]
                ratio_loss, value_loss, entropy_loss = 0, 0, 0
                for s, a, adv, ret in zip(batch_states, batch_actions, batch_advantages, batch_returns):
                    if np is None: continue
                    probs_new = self._get_policy(s, self.policy_new)
                    probs_old = self._get_policy(s, self.policy_old)
                    ratio = probs_new[a] / (probs_old[a] + 1e-8)
                    surr1 = ratio * adv
                    surr2 = np.clip(ratio, 1 - self.epsilon, 1 + self.epsilon) * adv
                    ratio_loss -= min(surr1, surr2)
                    v_new = self._get_value(s)
                    value_loss += (v_new - ret) ** 2
                    entropy_loss -= np.sum(probs_new * np.log(probs_new + 1e-8))
                loss = ratio_loss + self.value_coef * value_loss + self.entropy_coef * entropy_loss
                losses.append(loss)
        self.memory.clear()
        return {'loss': np.mean(losses) if losses else 0, 'ratio_loss': np.mean([ratio_loss]) if losses else 0}

# ================================================================================
# SECCION 21: MCTS (BUSQUEDA DE ARBOLES DE MONTE CARLO)
# ================================================================================
class MCTSNode:
    def __init__(self, state, parent=None, action=None):
        self.state = state
        self.parent = parent
        self.action = action
        self.children = {}
        self.visits = 0
        self.value = 0.0
        self.unexpanded = []

    def is_terminal(self):
        return len(self.children) == 0 and len(self.unexpanded) == 0

    def best_child_ucb(self, c=1.414):
        if not self.children: return None
        best, best_value = None, -float('inf')
        for child in self.children.values():
            if child.visits == 0:
                ucb = float('inf')
            else:
                ucb = child.value / child.visits + c * math.sqrt(math.log(self.visits) / child.visits)
            if ucb > best_value:
                best_value, best = ucb, child
        return best

class MCTSAgent:
    def __init__(self, state_dim, action_dim, sim_depth=50, explorations=100, gamma=0.99, ucb_constant=1.414):
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.sim_depth = sim_depth
        self.explorations = explorations
        self.gamma = gamma
        self.ucb_constant = ucb_constant
        self.root = None
        if np is not None:
            self.internal_model = defaultdict(lambda: np.zeros(action_dim))
        else:
            self.internal_model = defaultdict(lambda: [0.0] * action_dim)

    def build_tree(self, initial_state, possible_actions):
        self.root = MCTSNode(initial_state)
        self.root.unexpanded = possible_actions.copy()
        for _ in range(self.explorations):
            self._simulate()

    def _simulate(self):
        node = self.root
        depth = 0
        while not node.is_terminal() and not node.unexpanded:
            node = node.best_child_ucb(self.ucb_constant)
            if node is None: break
            depth += 1
        if node is None or depth >= self.sim_depth: return 0
        if node.unexpanded:
            action = random.choice(node.unexpanded)
            new_state = self._apply_action(node.state, action)
            new_node = MCTSNode(new_state, node, action)
            new_node.unexpanded = self._get_actions(new_state)
            node.children[action] = new_node
            node.unexpanded.remove(action)
            node = new_node
        reward = self._simulate_game(node.state)
        while node:
            node.visits += 1
            node.value += reward
            reward *= self.gamma
            node = node.parent
        return reward

    def _apply_action(self, state, action):
        if isinstance(state, (int, float)):
            return state + (action - 1) * 0.1
        elif isinstance(state, list):
            new = state.copy()
            if len(new) > action: new[action] += 0.1
            return new
        return state

    def _get_actions(self, state):
        return list(range(self.action_dim))

    def _simulate_game(self, state):
        total = 0
        current = state
        for _ in range(self.sim_depth):
            action = random.randint(0, self.action_dim - 1)
            key = tuple(current) if isinstance(current, list) else current
            q_vals = self.internal_model.get(key, [0.0] * self.action_dim)
            if isinstance(q_vals, list) and action < len(q_vals):
                total += q_vals[action]
            current = self._apply_action(current, action)
        return total

    def select_best_action(self):
        if not self.root or not self.root.children:
            return random.randint(0, self.action_dim - 1)
        best_action, best_ratio = None, -float('inf')
        for action, child in self.root.children.items():
            if child.visits > 0:
                ratio = child.value / child.visits
                if ratio > best_ratio:
                    best_ratio, best_action = ratio, action
        return best_action if best_action is not None else random.randint(0, self.action_dim - 1)

    def get_statistics(self):
        if not self.root: return {}
        stats = {'actions': {}}
        for action, child in self.root.children.items():
            stats['actions'][action] = {
                'visits': child.visits,
                'average_value': child.value / child.visits if child.visits > 0 else 0
            }
        return stats

# ================================================================================
# SECCION 22: ALGORITMO GENETICO
# ================================================================================
class GeneticOptimizer:
    def __init__(self, param_bounds, pop_size=50, elite_ratio=0.1, mutation_rate=0.1,
                 crossover_rate=0.7, generations=100):
        self.param_bounds = param_bounds
        self.pop_size = pop_size
        self.elite_size = int(pop_size * elite_ratio)
        self.mutation_rate = mutation_rate
        self.crossover_rate = crossover_rate
        self.generations = generations
        self.population = []
        self.best_individual = None
        self.best_fitness = -float('inf')
        self.history = []

    def _init_population(self):
        self.population = []
        for _ in range(self.pop_size):
            individual = {}
            for param, (low, high) in self.param_bounds.items():
                if isinstance(low, int) and isinstance(high, int):
                    individual[param] = random.randint(low, high)
                else:
                    individual[param] = random.uniform(low, high)
            self.population.append(individual)

    def _evaluate(self, individual, fitness_fn):
        return fitness_fn(individual)

    def _select(self, fitness_scores):
        tournament_size = 3
        selected = []
        for _ in range(len(self.population)):
            idx = random.sample(range(len(self.population)), tournament_size)
            best = max(idx, key=lambda i: fitness_scores[i])
            selected.append(self.population[best].copy())
        return selected

    def _crossover(self, parent1, parent2):
        if random.random() > self.crossover_rate:
            return parent1.copy(), parent2.copy()
        child1, child2 = {}, {}
        crossover_point = random.choice(list(parent1.keys()))
        in_child1 = False
        for key in parent1.keys():
            if key == crossover_point: in_child1 = True
            if in_child1:
                child1[key], child2[key] = parent1[key], parent2[key]
            else:
                child1[key], child2[key] = parent2[key], parent1[key]
        return child1, child2

    def _mutate(self, individual):
        mutated = individual.copy()
        for param in mutated:
            if random.random() < self.mutation_rate:
                low, high = self.param_bounds[param]
                if isinstance(low, int):
                    mutated[param] = int(random.gauss(mutated[param], (high - low) / 10))
                else:
                    mutated[param] = random.gauss(mutated[param], (high - low) / 10)
                mutated[param] = max(low, min(high, mutated[param]))
        return mutated

    def optimize(self, fitness_fn, verbose=True):
        self._init_population()
        for gen in range(self.generations):
            fitness_scores = [self._evaluate(ind, fitness_fn) for ind in self.population]
            if fitness_scores:
                best_idx = fitness_scores.index(max(fitness_scores))
                if fitness_scores[best_idx] > self.best_fitness:
                    self.best_fitness = fitness_scores[best_idx]
                    self.best_individual = self.population[best_idx].copy()
            self.history.append({
                'generation': gen, 'best_fitness': self.best_fitness,
                'avg_fitness': sum(fitness_scores) / len(fitness_scores) if fitness_scores else 0
            })
            if verbose and gen % 10 == 0:
                log("[GA] Gen " + str(gen) + ": Mejor=" + str(round(self.best_fitness, 4)))
            selected = self._select(fitness_scores)
            new_population = selected[:self.elite_size]
            while len(new_population) < self.pop_size:
                parent1, parent2 = random.sample(selected, 2)
                child1, child2 = self._crossover(parent1, parent2)
                new_population.append(self._mutate(child1))
                if len(new_population) < self.pop_size:
                    new_population.append(self._mutate(child2))
            self.population = new_population[:self.pop_size]
        return self.best_individual, self.best_fitness

    def get_history(self):
        return self.history

# ================================================================================
# SECCION 23: CONTROLADOR DE LOGICA FUZZY
# ================================================================================
class FuzzyLogicController:
    def __init__(self):
        self.rules = []
        self.membership_functions = {}
        self.defuzzify_method = 'centroid'

    def add_mf(self, variable, name, mf_type, params):
        if variable not in self.membership_functions:
            self.membership_functions[variable] = {}
        self.membership_functions[variable][name] = {'type': mf_type, 'params': params}

    def add_rule(self, antecedent, consequent):
        self.rules.append({'if': antecedent, 'then': consequent})

    def membership_triangle(self, x, a, b, c):
        if x <= a or x >= c: return 0
        elif a < x <= b: return (x - a) / (b - a) if (b - a) != 0 else 0
        else: return (c - x) / (c - b) if (c - b) != 0 else 0

    def membership_trapezoid(self, x, a, b, c, d):
        if x <= a or x >= d: return 0
        elif b <= x <= c: return 1
        elif a < x < b: return (x - a) / (b - a) if (b - a) != 0 else 0
        else: return (d - x) / (d - c) if (d - c) != 0 else 0

    def membership_gaussian(self, x, c, sigma):
        if sigma == 0: return 1.0 if x == c else 0
        return math.exp(-0.5 * ((x - c) / sigma) ** 2)

    def evaluate_mf(self, variable, mf_name, value):
        if variable not in self.membership_functions: return 0
        mf = self.membership_functions[variable].get(mf_name)
        if not mf: return 0
        t, p = mf['type'], mf['params']
        if t == 'triangle': return self.membership_triangle(value, *p)
        elif t == 'trapezoid': return self.membership_trapezoid(value, *p)
        elif t == 'gaussian': return self.membership_gaussian(value, *p)
        return 0

    def fuzzify(self, inputs):
        fuzzy_inputs = {}
        for var, value in inputs.items():
            if var in self.membership_functions:
                fuzzy_inputs[var] = {mf: self.evaluate_mf(var, mf, value) for mf in self.membership_functions[var]}
        return fuzzy_inputs

    def apply_rules(self, fuzzy_inputs):
        outputs = defaultdict(float)
        for rule in self.rules:
            activations = []
            for var, mf in rule['if'].items():
                if var in fuzzy_inputs and mf in fuzzy_inputs[var]:
                    activations.append(fuzzy_inputs[var][mf])
            if activations:
                antecedent_activation = min(activations)
                for key, value in rule['then'].items():
                    if isinstance(value, (int, float)):
                        mf_name, weight = key, value
                    else:
                        mf_name, weight = value, 1.0
                    if isinstance(weight, (int, float)):
                        outputs[mf_name] = max(outputs[mf_name], antecedent_activation * weight)
        return dict(outputs)

    def defuzzify(self, fuzzy_outputs, output_range):
        if not fuzzy_outputs:
            return (output_range[0] + output_range[1]) / 2
        if self.defuzzify_method == 'centroid':
            num, den = 0.0, 0.0
            output_mfs = self.membership_functions.get('output', {})
            for value in [i * 0.1 for i in range(int(output_range[0] * 10), int(output_range[1] * 10) + 1)]:
                max_mem = 0
                for mf, grade in fuzzy_outputs.items():
                    if mf in output_mfs and isinstance(grade, (int, float)):
                        membership = self.evaluate_mf('output', mf, value)
                        max_mem = max(max_mem, min(grade, membership))
                num += value * max_mem
                den += max_mem
            return num / den if den > 1e-10 else (output_range[0] + output_range[1]) / 2
        elif self.defuzzify_method == 'mom':
            max_deg = max(fuzzy_outputs.values()) if fuzzy_outputs else 0
            candidates = [k for k, v in fuzzy_outputs.items() if isinstance(v, (int, float)) and abs(v - max_deg) < 1e-10]
            numeric_candidates = [float(k) for k in candidates if isinstance(k, (int, float))]
            return sum(numeric_candidates) / len(numeric_candidates) if numeric_candidates else (output_range[0] + output_range[1]) / 2
        return (output_range[0] + output_range[1]) / 2

    def evaluate(self, inputs, output_range=(0, 1)):
        fuzzy_inputs = self.fuzzify(inputs)
        fuzzy_outputs = self.apply_rules(fuzzy_inputs)
        return self.defuzzify(fuzzy_outputs, output_range)

# ================================================================================
# SECCION 24: FILTRO KALMAN
# ================================================================================
class KalmanFilter:
    def __init__(self, state_dim, obs_dim, Q=None, R=None):
        self.state_dim = state_dim
        self.obs_dim = obs_dim
        if np is not None:
            self.x = np.zeros(state_dim)
            self.P = np.eye(state_dim)
            self.Q = Q if Q is not None else np.eye(state_dim) * 0.01
            self.R = R if R is not None else np.eye(obs_dim) * 0.1
            self.A = np.eye(state_dim)
            self.H = np.eye(obs_dim, state_dim)
            self.B = np.zeros((state_dim, obs_dim))
        else:
            self.x = [0.0] * state_dim
            self.P = [[1.0 if i == j else 0 for j in range(state_dim)] for i in range(state_dim)]
            self.Q = [[0.01 if i == j else 0 for j in range(state_dim)] for i in range(state_dim)]
            self.R = [[0.1 if i == j else 0 for j in range(obs_dim)] for i in range(obs_dim)]
            self.A = [[1.0 if i == j else 0 for j in range(state_dim)] for i in range(state_dim)]
            self.H = [[1.0 if i == j else 0 for j in range(state_dim)] for i in range(obs_dim)]

    def predict(self, u=None):
        if np is not None:
            if u is not None:
                self.x = np.dot(self.A, self.x) + np.dot(self.B, u)
            else:
                self.x = np.dot(self.A, self.x)
            self.P = np.dot(np.dot(self.A, self.P), self.A.T) + self.Q
        else:
            new_x = []
            for i in range(self.state_dim):
                val = sum(self.A[i][j] * self.x[j] for j in range(self.state_dim))
                if u is not None and i < len(u):
                    val += (self.B[i][0] if isinstance(self.B[0], list) else self.B[i]) * u[0]
                new_x.append(val)
            self.x = new_x
        return self.x

    def update(self, z):
        if np is not None:
            y = np.array(z) - np.dot(self.H, self.x)
            S = np.dot(np.dot(self.H, self.P), self.H.T) + self.R
            K = np.dot(np.dot(self.P, self.H.T), np.linalg.inv(S))
            self.x = self.x + np.dot(K, y)
            self.P = np.dot((np.eye(self.state_dim) - np.dot(K, self.H)), self.P)
        else:
            for i in range(self.state_dim):
                for j in range(min(self.obs_dim, len(z))):
                    self.x[i] += self.P[i][j] * (z[j] - self.x[j]) * 0.1
        return self.x

    def get_state(self):
        return self.x

    def get_uncertainty(self):
        if np is not None:
            return np.trace(self.P)
        else:
            return sum(self.P[i][i] for i in range(self.state_dim))

# ================================================================================
# SECCION 25: APRENDIZAJE IMPULSADO POR LA CURIOSIDAD
# ================================================================================
def softmax(x):
    if np is not None:
        exp_x = np.exp(x - np.max(x))
        return exp_x / exp_x.sum()
    else:
        exp_x = [math.exp(i) for i in x]
        s = sum(exp_x)
        return [i / s if s > 0 else 1.0 / len(x) for i in exp_x]

class CuriosityModule:
    def __init__(self, state_dim, action_dim, lr=0.001, gamma=0.99,
                 intrinsic_reward_scale=1.0, novelty_weight=0.5):
        self.state_dim = max(state_dim, 1)
        self.action_dim = action_dim
        self.lr = lr
        self.gamma = gamma
        self.intrinsic_reward_scale = intrinsic_reward_scale
        self.novelty_weight = novelty_weight
        if np is not None:
            try:
                self.forward_model = self._init_forward_model(self.state_dim, action_dim, self.state_dim)
                self.inverse_model = self._init_inverse_model(self.state_dim, self.state_dim, action_dim)
            except Exception:
                self.forward_model = self._init_forward_model(11, action_dim, 11)
                self.inverse_model = self._init_inverse_model(11, 11, action_dim)
        else:
            self.forward_model = {}
            self.inverse_model = {}
        self.state_buffer = deque(maxlen=1000)
        self.state_counts = defaultdict(int)
        self.episodic_curiosity = deque(maxlen=1000)

    def _init_forward_model(self, s_dim, a_dim, out_dim):
        input_dim = s_dim + a_dim
        if np is None: return {}
        safe_dim = max(input_dim, 1)
        return {
            'w1': np.random.randn(safe_dim, 64) * np.sqrt(2.0 / safe_dim),
            'b1': np.zeros(64),
            'w2': np.random.randn(64, max(out_dim, 1)) * np.sqrt(2.0 / 64),
            'b2': np.zeros(max(out_dim, 1))
        }

    def _init_inverse_model(self, s1_dim, s2_dim, a_dim):
        input_dim = s1_dim + s2_dim
        if np is None: return {}
        safe_dim = max(input_dim, 1)
        return {
            'w1': np.random.randn(safe_dim, 64) * np.sqrt(2.0 / safe_dim),
            'b1': np.zeros(64),
            'w2': np.random.randn(64, max(a_dim, 1)) * np.sqrt(2.0 / 64),
            'b2': np.zeros(max(a_dim, 1))
        }

    def _ensure_array(self, data, expected_len):
        if np is None:
            if isinstance(data, (list, tuple)):
                return list(data) + [0.0] * max(0, expected_len - len(data)) if len(data) < expected_len else list(data)[:expected_len]
            return [0.0] * expected_len
        arr = np.array(data, dtype=float).flatten()
        if len(arr) < expected_len:
            return np.pad(arr, (0, expected_len - len(arr)), mode='constant')
        elif len(arr) > expected_len:
            return arr[:expected_len]
        return arr

    def _forward(self, state, action):
        if np is None:
            return state if isinstance(state, (list, tuple)) else [state]
        try:
            state_arr = self._ensure_array(state, self.state_dim)
            action_arr = np.array([float(action)])
            x = np.concatenate([state_arr, action_arr])
            expected_input = self.forward_model['w1'].shape[0]
            if len(x) != expected_input:
                x = self._ensure_array(state, expected_input - 1)
                x = np.concatenate([x, action_arr])
            h = np.dot(x, self.forward_model['w1']) + self.forward_model['b1']
            h = np.maximum(0, h)
            pred = np.dot(h, self.forward_model['w2']) + self.forward_model['b2']
            return pred.flatten()
        except Exception:
            if np is not None:
                return np.array(self._ensure_array(state, self.state_dim)) + np.random.randn(self.state_dim) * 0.01
            return state

    def _inverse(self, state, next_state):
        if np is None: return [0.5] * self.action_dim
        try:
            s1 = self._ensure_array(state, self.state_dim)
            s2 = self._ensure_array(next_state, self.state_dim)
            x = np.concatenate([s1, s2])
            expected_input = self.inverse_model['w1'].shape[0]
            if len(x) != expected_input:
                half = expected_input // 2
                x = np.concatenate([self._ensure_array(state, half), self._ensure_array(next_state, expected_input - half)])
            h = np.dot(x, self.inverse_model['w1']) + self.inverse_model['b1']
            h = np.maximum(0, h)
            logits = np.dot(h, self.inverse_model['w2']) + self.inverse_model['b2']
            return softmax(logits)
        except Exception:
            return [1.0 / self.action_dim] * self.action_dim

    def compute_intrinsic_reward(self, state, action, next_state):
        try:
            pred_next = self._forward(state, action)
            if np is not None:
                next_arr = self._ensure_array(next_state, len(pred_next))
                prediction_error = float(np.linalg.norm(pred_next - next_arr))
            else:
                if isinstance(next_state, (list, tuple)) and next_state:
                    prediction_error = abs(pred_next[0] - next_state[0])
                else:
                    prediction_error = 0
        except Exception:
            prediction_error = random.uniform(0, 0.1)
        try:
            if np is not None:
                state_key = tuple(np.round(self._ensure_array(state, self.state_dim), 1))
            else:
                state_key = tuple([round(s, 1) for s in (state if isinstance(state, (list, tuple)) else [state])[:self.state_dim]])
            novelty = 1.0 / (1.0 + self.state_counts.get(state_key, 0))
            self.state_counts[state_key] += 1
        except Exception:
            novelty = 0.5
        intrinsic = self.intrinsic_reward_scale * (self.novelty_weight * prediction_error + (1 - self.novelty_weight) * novelty)
        try:
            self.state_buffer.append((state, action, next_state))
        except Exception:
            pass
        return intrinsic

    def update_models(self, state, action, next_state):
        if np is None: return {}
        try:
            pred = self._forward(state, action)
            next_arr = self._ensure_array(next_state, len(pred))
            error = float(np.linalg.norm(pred - next_arr) ** 2)
            return {'forward_error': error}
        except Exception:
            return {'forward_error': 0.0}

    def get_novel_states(self, k=5):
        if not self.state_buffer: return []
        novelties = []
        for state, _, _ in self.state_buffer:
            try:
                if np is not None:
                    state_key = tuple(np.round(self._ensure_array(state, self.state_dim), 1))
                else:
                    state_key = tuple([round(s, 1) for s in (state if isinstance(state, (list, tuple)) else [state])[:self.state_dim]])
                novelties.append((1.0 / (1.0 + self.state_counts.get(state_key, 1)), state))
            except Exception:
                continue
        novelties.sort(reverse=True)
        return [s for _, s in novelties[:k]]

# ================================================================================
# SECCION 26: APROXIMADOR DE FUNCIONES NEURONALES
# ================================================================================
class NeuralQApproximator:
    def __init__(self, state_dim, action_dim, hidden_sizes=None, lr=0.001, optimizer='adam'):
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.lr = lr
        if hidden_sizes is None:
            hidden_sizes = [64, 32]
        if np is not None:
            layers = [state_dim] + hidden_sizes + [action_dim]
            self.weights, self.biases = [], []
            for i in range(len(layers) - 1):
                w = np.random.randn(layers[i], layers[i + 1]) * np.sqrt(2.0 / layers[i])
                b = np.zeros(layers[i + 1])
                self.weights.append(w)
                self.biases.append(b)
        else:
            self.q_table = defaultdict(lambda: [0.0] * action_dim)

    def _forward(self, state):
        if np is None:
            key = tuple(state) if isinstance(state, (list, tuple)) else state
            return self.q_table.get(key, [0.0] * self.action_dim)
        x = np.array(state).flatten()
        for i, (w, b) in enumerate(zip(self.weights, self.biases)):
            x = np.dot(x, w) + b
            if i < len(self.weights) - 1:
                x = np.maximum(0, x)
        return x

    def predict(self, state):
        return self._forward(state)

    def update(self, state, target):
        if np is None: return
        x = np.array(state).flatten()
        activations = [x]
        current = x
        for i, (w, b) in enumerate(zip(self.weights, self.biases)):
            current = np.dot(current, w) + b
            activations.append(current)
            if i < len(self.weights) - 1:
                current = np.maximum(0, current)
                activations.append(current)
        output = activations[-1]
        error = output - target
        for i in reversed(range(len(self.weights))):
            grad_w = np.outer(activations[i], error)
            grad_b = error
            self.weights[i] -= self.lr * grad_w
            self.biases[i] -= self.lr * grad_b
            if i > 0:
                error = np.dot(self.weights[i], error)
                error = error * (activations[i] > 0).astype(float)

    def get_q_value(self, state, action):
        q_values = self.predict(state)
        return q_values[action] if action < len(q_values) else 0

# ================================================================================
# SECCION 27: META-APRENDIZAJE (APRENDER A APRENDER)
# ================================================================================
class MetaLearner:
    def __init__(self, state_dim, action_dim, meta_lr=0.001, inner_lr=0.1,
                 inner_steps=5, meta_batch_size=10):
        self.state_dim = max(state_dim, 1)
        self.action_dim = action_dim
        self.meta_lr = meta_lr
        self.inner_lr = inner_lr
        self.inner_steps = inner_steps
        self.meta_batch_size = meta_batch_size
        self.alpha = meta_lr
        self.beta = 0.1
        if np is not None:
            self.fast_weights = self._init_fast_weights()
            self.slow_weights = self._init_fast_weights()
        else:
            self.fast_weights = defaultdict(lambda: [0.0] * action_dim)
            self.slow_weights = defaultdict(lambda: [0.0] * action_dim)
        self.task_memory = deque(maxlen=1000)
        self.task_distributions = defaultdict(list)

    def _init_fast_weights(self):
        if np is None: return {}
        return {
            'w1': np.random.randn(self.state_dim, 32) * 0.01,
            'b1': np.zeros(32),
            'w2': np.random.randn(32, self.action_dim) * 0.01,
            'b2': np.zeros(self.action_dim)
        }

    def _forward(self, x, weights):
        if np is None: return [0.0] * self.action_dim
        h = np.dot(x, weights['w1']) + weights['b1']
        h = np.maximum(0, h)
        out = np.dot(h, weights['w2']) + weights['b2']
        return softmax(out)

    def inner_update(self, gradients):
        if np is None: return
        for key in self.fast_weights:
            self.fast_weights[key] -= self.alpha * gradients.get(key, 0)

    def compute_gradients(self, states, actions, rewards):
        if np is None or len(states) == 0: return {}
        grads = {}
        for key in self.fast_weights:
            grads[key] = np.zeros_like(self.fast_weights[key])
        for s, a, r in zip(states, actions, rewards):
            probs = self._forward(np.array(s), self.fast_weights)
            for key in self.fast_weights:
                grads[key] += r * np.random.randn(*self.fast_weights[key].shape) * 0.01
        for key in grads:
            grads[key] /= len(states)
        return grads

    def meta_update(self, task_gradients):
        if np is None: return
        for key in task_gradients:
            self.slow_weights[key] -= self.meta_lr * task_gradients[key]

    def adapt_to_task(self, task_data, n_steps=None):
        if n_steps is None: n_steps = self.inner_steps
        if np is not None:
            self.fast_weights = {k: v.copy() for k, v in self.slow_weights.items()}
        accumulated_grads = {}
        for _ in range(n_steps):
            gradients = self.compute_gradients(
                [d['state'] for d in task_data],
                [d['action'] for d in task_data],
                [d['reward'] for d in task_data]
            )
            for key in gradients:
                if key not in accumulated_grads:
                    accumulated_grads[key] = np.zeros_like(gradients[key])
                accumulated_grads[key] += gradients[key]
            self.inner_update(gradients)
        for key in accumulated_grads:
            accumulated_grads[key] /= n_steps
        self.meta_update(accumulated_grads)
        return accumulated_grads

    def select_action(self, state):
        probs = self._forward(np.array(state), self.fast_weights)
        if np is not None:
            action = int(np.argmax(probs))
        else:
            action = probs.index(max(probs))
        return action, probs[action]

# ================================================================================
# SECCION 28: SISTEMA ENSAMBLE MULTI-ALGORITMO
# ================================================================================
class EnsembleRL:
    def __init__(self, state_dim, action_dim):
        self.state_dim = max(state_dim, 1)
        self.action_dim = max(action_dim, 1)

        self.algorithms = {
            'double_dqn': DoubleDQN(self.state_dim, self.action_dim),
            'sarsa': SARSAAgent(self.state_dim, self.action_dim),
            'actor_critic': ActorCritic(self.state_dim, self.action_dim),
            'ppo': PPOOptimizer(self.state_dim, self.action_dim),
        }

        self.weights = {
            'double_dqn': 0.30,
            'sarsa': 0.20,
            'actor_critic': 0.25,
            'ppo': 0.25
        }

        self.voting = 'weighted_average'
        self.episodic_memory = EpisodicMemory()
        self.curiosity = CuriosityModule(self.state_dim, self.action_dim)
        self.kalman = KalmanFilter(min(self.state_dim, 3), min(self.state_dim, 3))
        self.meta_learner = MetaLearner(self.state_dim, self.action_dim)
        self.decision_history = deque(maxlen=1000)

        log("[ENSEMBLE] Sistema EnsembleRL inicializado")

    def _to_hashable(self, state):
        try:
            if np is not None and isinstance(state, np.ndarray):
                return tuple(state.flatten().tolist())
            elif isinstance(state, list):
                return tuple(state)
            return state
        except Exception as e:
            log("[ENSEMBLE] Error convirtiendo estado hashable: " + str(e))
            return tuple([0.0] * self.state_dim)

    def _normalize_state_for_kalman(self, state, max_dim=3):
        try:
            if isinstance(state, (list, tuple)):
                arr = list(state[:max_dim])
            elif np is not None and isinstance(state, np.ndarray):
                arr = state.flatten().tolist()[:max_dim]
            elif isinstance(state, (int, float)):
                arr = [float(state)]
            else:
                arr = [0.0]
            while len(arr) < max_dim:
                arr.append(0.0)
            return arr[:max_dim]
        except Exception as e:
            log("[ENSEMBLE] Error normalizando estado Kalman: " + str(e))
            return [0.0] * max_dim

    def select_action(self, state, exploit_only=False):
        votes = {}
        for name, algo in self.algorithms.items():
            try:
                if name in ['double_dqn', 'sarsa']:
                    action = algo.select_action(state, exploit_only)
                elif name in ['actor_critic', 'ppo']:
                    action, _ = algo.select_action(state)
                else:
                    continue
                votes[name] = action
            except Exception as e:
                log("[ENSEMBLE] Error seleccionando accion en " + name + ": " + str(e))
                continue

        if not votes:
            log("[ENSEMBLE] No hubo votos validos")
            return (random.randint(0, self.action_dim - 1), 0.5)

        if self.voting == 'weighted_average':
            weighted_votes = defaultdict(float)
            for name, action in votes.items():
                try:
                    peso = float(self.weights.get(name, 0.25))
                    if math.isnan(peso) or peso < 0:
                        peso = 0.0
                    weighted_votes[action] += peso
                except Exception as e:
                    log("[ENSEMBLE] Error procesando peso " + name + ": " + str(e))

            if not weighted_votes:
                log("[ENSEMBLE] weighted_votes vacio")
                return (random.randint(0, self.action_dim - 1), 0.5)

            best_action = max(weighted_votes, key=weighted_votes.get)

            total_weight = 0.0
            for name in votes:
                try:
                    peso = float(self.weights.get(name, 0.25))
                    if math.isnan(peso) or peso < 0:
                        peso = 0.0
                    total_weight += peso
                except Exception:
                    pass

            if total_weight <= 0:
                log("[ENSEMBLE] total_weight <= 0 (fallback confidence)")
                confidence = 0.5
            else:
                confidence = weighted_votes[best_action] / total_weight

            confidence = max(0.0, min(1.0, confidence))
            log("[ENSEMBLE] Accion=" + str(best_action) + " confianza=" + str(round(confidence, 3)))
            return best_action, confidence

        elif self.voting == 'majority':
            try:
                best_action = max(votes.values(), key=list(votes.values()).count)
                return best_action, 0.5
            except Exception as e:
                log("[ENSEMBLE] Error majority voting: " + str(e))
                return (random.randint(0, self.action_dim - 1), 0.5)

        return (random.randint(0, self.action_dim - 1), 0.5)

    def update(self, state, action, reward, next_state, done, use_curiosity=True):
        if use_curiosity:
            try:
                state_proc = (np.array(state).flatten() if np is not None and isinstance(state, (list, tuple)) else state)
                next_proc = (np.array(next_state).flatten() if np is not None and isinstance(next_state, (list, tuple)) else next_state)
                intrinsic_reward = self.curiosity.compute_intrinsic_reward(state_proc, action, next_proc)
                if math.isnan(intrinsic_reward):
                    intrinsic_reward = 0.0
                total_reward = reward + intrinsic_reward
            except Exception as e:
                log("[ENSEMBLE] Error curiosity: " + str(e))
                intrinsic_reward = 0.0
                total_reward = reward
        else:
            intrinsic_reward = 0.0
            total_reward = reward

        try:
            self.kalman.predict()
            normalized = self._normalize_state_for_kalman(next_state, max_dim=self.kalman.obs_dim)
            self.kalman.update(normalized)
        except Exception as e:
            log("[ENSEMBLE] Error Kalman: " + str(e))

        state_hash = self._to_hashable(state)
        next_hash = self._to_hashable(next_state)

        for name, algo in self.algorithms.items():
            try:
                if name == 'double_dqn':
                    algo.store(state_hash, action, total_reward, next_hash, done)
                    if hasattr(algo, 'memory') and hasattr(algo, 'batch_size') and len(algo.memory) >= max(1, algo.batch_size):
                        algo.learn()
                elif name == 'sarsa':
                    next_action = algo.select_action(next_hash)
                    algo.update(state_hash, action, total_reward, next_hash, next_action, done)
            except Exception as e:
                log("[ENSEMBLE] Error actualizando " + name + ": " + str(e))

        try:
            exp = Experience(state_hash, action, total_reward, next_hash, done)
            self.episodic_memory.add_episode([exp])
        except Exception as e:
            log("[ENSEMBLE] Error memoria episodica: " + str(e))

        try:
            self.decision_history.append({'state': state, 'action': action, 'reward': total_reward, 'timestamp': time.time()})
        except Exception as e:
            log("[ENSEMBLE] Error historial: " + str(e))

        return {'extrinsic_reward': reward, 'intrinsic_reward': intrinsic_reward}

    def optimize_weights(self, fitness_fn):
        ga = GeneticOptimizer(param_bounds={name: (0, 1) for name in self.algorithms}, pop_size=20, generations=30)

        def eval_weights(weights_dict):
            try:
                total = sum(weights_dict.values())
                if total <= 0:
                    total = 1.0
                weights_dict = {k: (v / total) for k, v in weights_dict.items()}
                self.weights.update(weights_dict)
                return fitness_fn(self.weights)
            except Exception as e:
                log("[ENSEMBLE] Error evaluando pesos: " + str(e))
                return 0.0

        best_weights, _ = ga.optimize(eval_weights, verbose=False)

        try:
            total = sum(best_weights.values())
            if total > 0:
                best_weights = {k: (v / total) for k, v in best_weights.items()}
            self.weights.update(best_weights)
        except Exception as e:
            log("[ENSEMBLE] Error actualizando mejores pesos: " + str(e))

        return self.weights

    def get_state(self):
        try:
            uncertainty = float(self.kalman.get_uncertainty()) if np is not None else self.kalman.get_uncertainty()
        except Exception:
            uncertainty = 0.0
        return {
            'algorithms': list(self.algorithms.keys()),
            'weights': self.weights,
            'memory_size': len(self.episodic_memory.episodes),
            'decisions': len(self.decision_history),
            'kalman_uncertainty': uncertainty,
        }

# ================================================================================
# SECCION 29: SISTEMA DE NEGOCIACION SYMBIOSIS
# ================================================================================
class NegotiationError(Exception):
    pass

class SessionError(NegotiationError):
    pass

class AgentError(NegotiationError):
    pass

class ReputationError(NegotiationError):
    pass

class FraudDetectedError(ReputationError):
    pass

class NegotiationStatus:
    PENDING = "pending"
    ACTIVE = "active"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"
    DISPUTED = "disputed"
    CANCELLED = "cancelled"

class AgentRole:
    INITIATOR = "initiator"
    RESPONDER = "responder"
    ARBITER = "arbiter"
    OBSERVER = "observer"

class NegotiationStrategy:
    HARDLINE = "hardline"
    MODERATE = "moderate"
    ACCOMMODATING = "accommodating"
    COMPETITIVE = "competitive"
    COLLABORATIVE = "collaborative"
    RANDOM = "random"
    ADAPTIVE = "adaptive"

class ConcessionType:
    PRICE_REDUCTION = "price_reduction"
    TIME_EXTENSION = "time_extension"
    QUALITY_ADJUSTMENT = "quality_adjustment"
    PAYMENT_TERMS = "payment_terms"
    MIXED = "mixed"
    BUNDLE_OFFER = "bundle_offer"
    VALUE_ADDED = "value_added"

class ReputationDimension:
    HONESTY = "honesty"
    DELIVERY = "delivery"
    QUALITY = "quality"
    COMMUNICATION = "communication"
    RESPONSIVENESS = "responsiveness"
    PROFESSIONALISM = "professionalism"
    FAIRNESS = "fairness"
    FLEXIBILITY = "flexibility"

class TrustLevel:
    UNTRUSTED = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    VERY_HIGH = 4
    ELITE = 5

class FeedbackType:
    POSITIVE = 1
    NEUTRAL = 0
    NEGATIVE = -1

class MathUtils:
    @staticmethod
    def sigmoid(x, temperature=0.5):
        return 1.0 / (1.0 + math.exp(-x / max(temperature, 0.001)))
    
    @staticmethod
    def normalize(value, min_val, max_val):
        if max_val == min_val:
            return 0.5
        return max(0.0, min(1.0, (value - min_val) / (max_val - min_val)))
    
    @staticmethod
    def weighted_average(values, weights):
        if not values or not weights or len(values) != len(weights):
            return 0.0
        total_weight = sum(weights)
        if total_weight <= 0:
            return 0.0
        return sum(v * w for v, w in zip(values, weights)) / total_weight
    
    @staticmethod
    def exponential_decay(initial, time_elapsed, half_life=90.0):
        if half_life <= 0:
            return initial
        return initial * math.pow(0.5, time_elapsed / half_life)
    
    @staticmethod
    def clamp(value, min_val=0.0, max_val=1.0):
        return max(min_val, min(max_val, value))

class FraudDetector:
    def __init__(self):
        self.suspicious_entities = set()
    
    def detect_sybil(self, reviewer_id, reviews):
        return 0.0
    
    def detect_collusion(self, entity_a, entity_b, reviews):
        return 0.0

class TrustScoreCalculator:
    def __init__(self, half_life=90.0, decay_model="exponential"):
        self.half_life = half_life
        self.decay_model = decay_model
        self.fraud_detector = FraudDetector()
        self.dimension_weights = {
            "honesty": 0.20, "delivery": 0.20, "quality": 0.20,
            "communication": 0.15, "responsiveness": 0.10,
            "professionalism": 0.05, "fairness": 0.05, "flexibility": 0.05
        }
    
    def calculate(self, entity_id, reviews):
        class TrustScore:
            def __init__(self, entity_id):
                self.entity_id = entity_id
                self.overall_score = 0.5
                self.dimension_scores = {}
                self.total_reviews = 0
                self.positive_reviews = 0
                self.negative_reviews = 0
                self.trust_level = TrustLevel.UNTRUSTED
                self.confidence = 0.0
                self.fraud_risk_score = 0.0
                self.trend = "stable"
                self.last_updated = _datetime.now(_timezone.utc)
            
            def to_dict(self):
                return {
                    'entity_id': self.entity_id,
                    'overall_score': self.overall_score,
                    'dimension_scores': self.dimension_scores,
                    'total_reviews': self.total_reviews,
                    'positive_reviews': self.positive_reviews,
                    'negative_reviews': self.negative_reviews,
                    'trust_level': TrustLevel(self.trust_level).name if isinstance(self.trust_level, int) else str(self.trust_level),
                    'confidence': self.confidence,
                    'fraud_risk_score': self.fraud_risk_score,
                    'trend': self.trend
                }
        
        score = TrustScore(entity_id)
        if reviews:
            ratings = [r.get('rating', 3.0) for r in reviews if isinstance(r, dict)]
            if ratings:
                score.overall_score = sum(ratings) / len(ratings) / 5.0
                score.total_reviews = len(ratings)
                score.positive_reviews = sum(1 for r in ratings if r >= 4.0)
                score.negative_reviews = sum(1 for r in ratings if r <= 2.0)
                if score.total_reviews >= 10:
                    score.trust_level = TrustLevel.MEDIUM if score.overall_score >= 0.6 else TrustLevel.LOW
                    if score.overall_score >= 0.8 and score.total_reviews >= 20:
                        score.trust_level = TrustLevel.HIGH
                score.confidence = min(1.0, score.total_reviews / 30.0)
        return score

class ReputationSystem:
    def __init__(self, config=None):
        self._lock = threading.RLock()
        self.calculator = TrustScoreCalculator()
        self.entities = {}
        self.reviews = defaultdict(list)
        self.trust_scores = {}
        self.blocked_entities = set()
    
    def register_entity(self, entity_id, initial_reputation=0.5, metadata=None):
        with self._lock:
            if entity_id not in self.entities:
                self.entities[entity_id] = {
                    'score': initial_reputation,
                    'successful_transactions': 0,
                    'failed_transactions': 0,
                    'total_volume': 0.0,
                    'joined_at': _datetime.now(_timezone.utc),
                    'metadata': metadata or {},
                    'blocked': False
                }
    
    def add_review(self, reviewer_id, reviewee_id, transaction_id, rating,
                   dimensions=None, comment="", verified=False):
        with self._lock:
            review = {
                'review_id': str(uuid.uuid4())[:8],
                'reviewer_id': reviewer_id,
                'reviewee_id': reviewee_id,
                'transaction_id': transaction_id,
                'rating': rating,
                'dimensions': dimensions or {},
                'comment': comment,
                'timestamp': _datetime.now(_timezone.utc),
                'verified': verified
            }
            self.reviews[reviewee_id].append(review)
            self._recalculate_trust(reviewee_id)
            return review
    
    def get_reputation(self, entity_id):
        with self._lock:
            if entity_id in self.trust_scores:
                return self.trust_scores[entity_id].overall_score
            return 0.5
    
    def get_trust_level(self, entity_id):
        with self._lock:
            if entity_id in self.trust_scores:
                level = self.trust_scores[entity_id].trust_level
                if isinstance(level, int):
                    return TrustLevel(level)
                return level
            return TrustLevel.UNTRUSTED
    
    def get_profile(self, entity_id):
        with self._lock:
            if entity_id not in self.entities:
                self.register_entity(entity_id)
            profile = dict(self.entities[entity_id])
            if entity_id in self.trust_scores:
                ts = self.trust_scores[entity_id]
                profile.update({
                    'trust_level': ts.trust_level if isinstance(ts.trust_level, int) else 0,
                    'overall_score': ts.overall_score,
                    'total_reviews': ts.total_reviews,
                    'positive_reviews': ts.positive_reviews,
                    'negative_reviews': ts.negative_reviews,
                    'confidence': ts.confidence
                })
            return profile
    
    def detect_fraud_risk(self, entity_id):
        return 0.0
    
    def export_data(self):
        with self._lock:
            return {
                'entities': self.entities,
                'blocked_entities': list(self.blocked_entities)
            }
    
    def import_data(self, data):
        with self._lock:
            self.entities = data.get('entities', {})
            self.blocked_entities = set(data.get('blocked_entities', []))
    
    def _recalculate_trust(self, entity_id):
        entity_reviews = self.reviews.get(entity_id, [])
        self.trust_scores[entity_id] = self.calculator.calculate(entity_id, entity_reviews)

class UtilityProfile:
    def __init__(self, price_weight=0.5, time_weight=0.2, quality_weight=0.2,
                 reputation_weight=0.05, flexibility_weight=0.05,
                 min_acceptable_price=50.0, max_acceptable_price=150.0,
                 required_quality_level=3, role=AgentRole.INITIATOR):
        self.price_weight = price_weight
        self.time_weight = time_weight
        self.quality_weight = quality_weight
        self.reputation_weight = reputation_weight
        self.flexibility_weight = flexibility_weight
        self.min_acceptable_price = min_acceptable_price
        self.max_acceptable_price = max_acceptable_price
        self.required_quality_level = required_quality_level
        self.role = role
    
    def calculate_utility(self, price, delivery_time=24.0, quality=3,
                          reputation=0.5, flexibility=0.5):
        total = (self.price_weight + self.time_weight + self.quality_weight +
                self.reputation_weight + self.flexibility_weight)
        if total <= 0:
            return 0.5
        
        price_range = self.max_acceptable_price - self.min_acceptable_price
        if self.role == AgentRole.RESPONDER:
            price_util = ((price - self.min_acceptable_price) / price_range) if price_range > 0 else 0.5
        else:
            price_util = (1.0 - (price - self.min_acceptable_price) / price_range) if price_range > 0 else 0.5
        price_util = MathUtils.clamp(price_util)
        
        time_util = MathUtils.clamp(1.0 - delivery_time / 60.0)
        quality_util = quality / 5.0
        rep_util = MathUtils.clamp(reputation)
        flex_util = MathUtils.clamp(flexibility)
        
        return (self.price_weight/total * price_util + self.time_weight/total * time_util +
                self.quality_weight/total * quality_util + self.reputation_weight/total * rep_util +
                self.flexibility_weight/total * flex_util)
    
    def is_price_acceptable(self, price):
        return self.min_acceptable_price <= price <= self.max_acceptable_price
    
    def get_acceptable_range(self):
        return (self.min_acceptable_price, self.max_acceptable_price)

class Offer:
    def __init__(self, price=0.0, delivery_time=24.0, quality_level=3,
                 proposed_by="", rationale="", concessions=None,
                 metadata=None, expires_at=None):
        self.price = price
        self.delivery_time = delivery_time
        self.quality_level = quality_level
        self.proposed_by = proposed_by
        self.rationale = rationale
        self.concessions = concessions or []
        self.metadata = metadata or {}
        self.expires_at = expires_at
        self.timestamp = _datetime.now(_timezone.utc)
    
    def clone(self, **modifications):
        data = {
            'price': self.price,
            'delivery_time': self.delivery_time,
            'quality_level': self.quality_level,
            'proposed_by': self.proposed_by,
            'rationale': self.rationale,
            'concessions': list(self.concessions),
            'metadata': dict(self.metadata),
            'expires_at': self.expires_at
        }
        data.update(modifications)
        return Offer(**data)
    
    def to_dict(self):
        return {
            'price': self.price,
            'delivery_time': self.delivery_time,
            'quality_level': self.quality_level,
            'proposed_by': self.proposed_by,
            'rationale': self.rationale,
            'concessions': self.concessions
        }
    
    def is_expired(self):
        if self.expires_at is None:
            return False
        return _datetime.now(_timezone.utc) > self.expires_at

class NegotiationSession:
    def __init__(self, agent_a_id, agent_b_id, domain="default",
                 item_description="", max_rounds=10, base_terms=None,
                 participant_ids=None):
        self.session_id = str(uuid.uuid4())
        self.agent_a_id = agent_a_id
        self.agent_b_id = agent_b_id
        self.participant_ids = participant_ids or [agent_a_id, agent_b_id]
        self.domain = domain
        self.item_description = item_description
        self.base_terms = base_terms or {}
        self.status = NegotiationStatus.PENDING
        self.max_rounds = max_rounds
        self.current_round = 0
        self.offers = []
        self.messages = []
        self.final_offer = None
        self.final_utilities = {}
        self.created_at = _datetime.now(_timezone.utc)
        self.resolved_at = None
        self.timeout_seconds = 300
    
    def get_last_offer(self):
        return self.offers[-1] if self.offers else None
    
    def get_other_agent(self, agent_id):
        return self.agent_b_id if agent_id == self.agent_a_id else self.agent_a_id
    
    def is_expired(self):
        elapsed = (_datetime.now(_timezone.utc) - self.created_at).total_seconds()
        return elapsed > self.timeout_seconds
    
    def add_offer(self, offer):
        self.offers.append(offer)
    
    def add_message(self, sender_id, content, message_type="general"):
        self.messages.append({
            'sender': sender_id,
            'content': content,
            'type': message_type,
            'timestamp': _datetime.now(_timezone.utc).isoformat()
        })
    
    def to_summary(self):
        return {
            'session_id': self.session_id,
            'domain': self.domain,
            'status': self.status,
            'rounds': self.current_round,
            'participants': self.participant_ids,
            'final_price': self.final_offer.price if self.final_offer else None
        }

class ConcessionEngine:
    @staticmethod
    def calculate(round_num, max_rounds, strategy, utility_gap, time_pressure, opponent_flexibility=0.5):
        progress = round_num / max(max_rounds, 1)
        adjusted_gap = utility_gap * (1.0 - opponent_flexibility * 0.3)
        
        strategy_map = {
            NegotiationStrategy.HARDLINE: 0.05 if progress < 0.6 else (0.15 if progress < 0.8 else 0.30),
            NegotiationStrategy.MODERATE: progress * 0.20,
            NegotiationStrategy.ACCOMMODATING: min(0.40, progress * 0.35),
            NegotiationStrategy.COMPETITIVE: 0.10 * (1 + time_pressure * 0.2),
            NegotiationStrategy.COLLABORATIVE: progress * 0.25 + 0.10,
            NegotiationStrategy.ADAPTIVE: min(0.35, progress * 0.30 + adjusted_gap * 0.2)
        }
        
        factor = strategy_map.get(strategy, 0.15)
        if strategy == NegotiationStrategy.RANDOM:
            factor = random.uniform(0.10, 0.35)
        
        return factor * adjusted_gap

class OpponentModeler:
    def __init__(self):
        self.inferred_strategy = None
        self.price_trend = "stable"
        self.concession_rate = 0.0
        self.primary_focus = "price"
        self.flexibility_estimate = 0.5
        self.confidence = 0.0
    
    def update(self, offers):
        if len(offers) < 2:
            return
        prices = [o.get('price', 0) for o in offers if 'price' in o]
        if len(prices) >= 2:
            changes = [prices[i+1] - prices[i] for i in range(len(prices)-1)]
            avg_change = sum(changes) / len(changes) if changes else 0
            self.concession_rate = abs(avg_change)
            self._infer_strategy(prices, changes, offers)
        self.confidence = min(1.0, len(offers) / 10.0)
    
    def _infer_strategy(self, prices, changes, offers):
        decreases = sum(1 for c in changes if c < -1)
        total = len(changes) if changes else 1
        dec_ratio = decreases / total
        
        if dec_ratio > 0.5:
            self.inferred_strategy = NegotiationStrategy.ACCOMMODATING
            self.price_trend = "decreasing"
        else:
            self.inferred_strategy = NegotiationStrategy.MODERATE
            self.price_trend = "stable"
    
    def recommend_counter_strategy(self, current):
        if not self.inferred_strategy:
            return current
        counter_map = {
            NegotiationStrategy.HARDLINE: NegotiationStrategy.COLLABORATIVE,
            NegotiationStrategy.MODERATE: NegotiationStrategy.MODERATE,
            NegotiationStrategy.ACCOMMODATING: NegotiationStrategy.COMPETITIVE,
            NegotiationStrategy.COMPETITIVE: NegotiationStrategy.COLLABORATIVE,
            NegotiationStrategy.COLLABORATIVE: NegotiationStrategy.COLLABORATIVE
        }
        return counter_map.get(self.inferred_strategy, current)
    
    def predict_next_offer(self, last_offer):
        prediction = dict(last_offer)
        return prediction

class ParetoNashEvaluator:
    @staticmethod
    def calculate_bargaining_power(reservation_value, ideal_value, time_pressure, alternatives):
        improvement = (ideal_value - reservation_value) / max(abs(ideal_value), 0.01)
        time_factor = 1.0 - time_pressure * 0.5
        alt_factor = min(1.0, math.log2(alternatives + 1) / 3)
        return MathUtils.clamp(improvement * 0.4 + time_factor * 0.3 + alt_factor * 0.3)
    
    @staticmethod
    def evaluate_decision(utility, reservation, remaining_rounds, expected_future_utility=0.5):
        option_value = expected_future_utility * (remaining_rounds / max(remaining_rounds + 1, 1))
        
        if utility >= reservation:
            if remaining_rounds <= 1:
                return True, "Ultima ronda, utilidad suficiente"
            if utility >= option_value:
                return True, "Acuerdo win-win probable"
            return False, "Espacio para mejora esperada"
        
        if remaining_rounds <= 1 and utility >= reservation - 0.15:
            return True, "Ultima oportunidad, utilidad marginal"
        
        if utility < reservation - 0.25:
            return False, "Utilidad muy por debajo de reserva"
        
        return False, "Espacio para mejora con contraoferta"

class StrategicAgent:
    def __init__(self, agent_id, role, utility_profile, reputation_system,
                 strategy=NegotiationStrategy.COLLABORATIVE, reservation_utility=0.6):
        self.agent_id = agent_id
        self.role = role
        self.utility_profile = utility_profile
        self.reputation_system = reputation_system
        self.strategy = strategy
        self.reservation_utility = reservation_utility
        self.concession_engine = ConcessionEngine()
        self.opponent_model = OpponentModeler()
        self.total_utilities_earned = 0.0
        self.negotiation_history = []
    
    def generate_offer(self, session, context):
        time_pressure = session.current_round / max(session.max_rounds, 1)
        counterparty = session.get_other_agent(self.agent_id)
        counterparty_rep = self.reputation_system.get_reputation(counterparty)
        
        bargaining_power = ParetoNashEvaluator.calculate_bargaining_power(
            self.utility_profile.min_acceptable_price,
            self.utility_profile.max_acceptable_price,
            time_pressure,
            random.randint(1, 3)
        )
        
        min_p, max_p = self.utility_profile.get_acceptable_range()
        base_price = (min_p + max_p) / 2
        
        current_strategy = self.strategy
        if self.strategy == NegotiationStrategy.ADAPTIVE and self.opponent_model.inferred_strategy:
            current_strategy = self.opponent_model.recommend_counter_strategy(self.strategy)
        
        if current_strategy == NegotiationStrategy.HARDLINE:
            adjustment = 1.15 if self.role == AgentRole.RESPONDER else 0.85
        elif current_strategy == NegotiationStrategy.ACCOMMODATING:
            adjustment = 0.90 if self.role == AgentRole.RESPONDER else 1.10
        elif current_strategy == NegotiationStrategy.COMPETITIVE:
            adjustment = 1.20 if self.role == AgentRole.RESPONDER else 0.80
        else:
            adjustment = 1.0 - bargaining_power * 0.15
        
        final_price = base_price * adjustment
        final_price = MathUtils.clamp(final_price, min_p, max_p)
        
        return Offer(
            price=final_price,
            delivery_time=24.0 * (1 + time_pressure * 0.5),
            quality_level=self.utility_profile.required_quality_level,
            proposed_by=self.agent_id,
            rationale=f"Estrategia {current_strategy} | Poder: {bargaining_power:.2f}"
        )
    
    def evaluate_offer(self, offer, session):
        fraud_risk = self.reputation_system.detect_fraud_risk(offer.proposed_by)
        if fraud_risk > 0.6:
            return False, 0.0, None
        
        if offer.is_expired():
            return False, 0.0, None
        
        utility = self.utility_profile.calculate_utility(
            price=offer.price,
            delivery_time=offer.delivery_time,
            quality=offer.quality_level,
            reputation=self.reputation_system.get_reputation(offer.proposed_by)
        )
        
        remaining = session.max_rounds - session.current_round
        accept, _ = ParetoNashEvaluator.evaluate_decision(
            utility, self.reservation_utility, remaining, 0.5
        )
        
        if accept:
            self.negotiation_history.append({
                'session_id': session.session_id,
                'accepted': True,
                'utility': utility
            })
            self.total_utilities_earned += utility
            return True, utility, None
        
        self.opponent_model.update([o.to_dict() for o in session.offers])
        
        time_pressure = session.current_round / max(session.max_rounds, 1)
        concession = self.concession_engine.calculate(
            session.current_round, session.max_rounds,
            self.strategy, max(0, 1.0 - utility), time_pressure,
            self.opponent_model.flexibility_estimate
        )
        
        min_p, max_p = self.utility_profile.get_acceptable_range()
        if self.role == AgentRole.INITIATOR:
            new_price = max(min_p, offer.price * (1 - concession * 0.2))
        else:
            new_price = min(max_p, offer.price * (1 + concession * 0.2))
        
        if not self.utility_profile.is_price_acceptable(new_price):
            if remaining <= 1 and utility >= self.reservation_utility - 0.2:
                return True, utility, None
            return False, utility, None
        
        counter = offer.clone(
            price=new_price,
            proposed_by=self.agent_id,
            concessions=offer.concessions + [f"concession_{concession:.3f}"]
        )
        
        return False, utility, counter
    
    def record_outcome(self, session, accepted, utility):
        self.negotiation_history.append({
            'session_id': session.session_id,
            'accepted': accepted,
            'utility': utility,
            'rounds': session.current_round,
            'final_price': session.final_offer.price if session.final_offer else None
        })
        if accepted:
            self.total_utilities_earned += utility

class NegotiationOrchestrator:
    def __init__(self, config=None):
        self.reputation_system = ReputationSystem()
        self.agents = {}
        self.active_sessions = {}
        self.completed_sessions = []
        self._lock = threading.RLock()
        self.metrics = {
            'total_negotiations': 0,
            'successful': 0,
            'failed': 0,
            'expired': 0,
            'avg_rounds': 0.0,
            'total_value_exchanged': 0.0
        }
    
    def register_agent(self, agent):
        with self._lock:
            self.agents[agent.agent_id] = agent
            self.reputation_system.register_entity(agent.agent_id)
    
    def create_session(self, initiator_id, responder_id, domain="default",
                       item="", base_terms=None, participant_ids=None):
        if initiator_id not in self.agents or responder_id not in self.agents:
            return None
        
        session = NegotiationSession(
            initiator_id, responder_id, domain, item,
            self.metrics.get('max_rounds', 10), base_terms, participant_ids
        )
        
        with self._lock:
            self.active_sessions[session.session_id] = session
            self.metrics['total_negotiations'] += 1
        
        return session
    
    def run_negotiation(self, session):
        agent_a = self.agents.get(session.agent_a_id)
        agent_b = self.agents.get(session.agent_b_id)
        
        if not agent_a or not agent_b:
            session.status = NegotiationStatus.REJECTED
            return session.status
        
        session.status = NegotiationStatus.ACTIVE
        
        try:
            initial_offer = agent_a.generate_offer(session, {})
            session.add_offer(initial_offer)
            session.current_round = 1
        except Exception:
            session.status = NegotiationStatus.REJECTED
            return session.status
        
        while session.status == NegotiationStatus.ACTIVE:
            if session.current_round > session.max_rounds or session.is_expired():
                session.status = NegotiationStatus.EXPIRED
                with self._lock:
                    self.metrics['expired'] += 1
                break
            
            last_offer = session.get_last_offer()
            if not last_offer:
                break
            
            evaluator = agent_b if last_offer.proposed_by == agent_a.agent_id else agent_a
            
            try:
                accept, utility, counter = evaluator.evaluate_offer(last_offer, session)
            except Exception:
                session.status = NegotiationStatus.DISPUTED
                break
            
            if accept:
                session.final_offer = last_offer
                session.status = NegotiationStatus.ACCEPTED
                session.resolved_at = _datetime.now(_timezone.utc)
                
                with self._lock:
                    self.metrics['successful'] += 1
                    self.metrics['total_value_exchanged'] += last_offer.price
                
                self._update_reputation(session)
                break
            
            elif counter:
                session.add_offer(counter)
                session.current_round += 1
            
            else:
                session.status = NegotiationStatus.REJECTED
                session.resolved_at = _datetime.now(_timezone.utc)
                with self._lock:
                    self.metrics['failed'] += 1
                break
        
        with self._lock:
            self.active_sessions.pop(session.session_id, None)
            self.completed_sessions.append(session)
            
            total = self.metrics['total_negotiations']
            if total > 0:
                self.metrics['avg_rounds'] = (
                    (self.metrics['avg_rounds'] * (total - 1) + session.current_round) / total
                )
        
        return session.status
    
    def _update_reputation(self, session):
        if session.final_offer:
            rating = 3.0 + (session.final_offer.price / 100.0)
            self.reputation_system.add_review(
                "system", session.agent_a_id, session.session_id,
                min(5.0, rating), comment="Negociacion exitosa"
            )
            self.reputation_system.add_review(
                "system", session.agent_b_id, session.session_id,
                min(5.0, rating), comment="Negociacion exitosa"
            )
    
    def get_metrics(self):
        with self._lock:
            metrics = dict(self.metrics)
            metrics['active_sessions'] = len(self.active_sessions)
            metrics['registered_agents'] = len(self.agents)
            if self.metrics['total_negotiations'] > 0:
                metrics['success_rate'] = self.metrics['successful'] / self.metrics['total_negotiations']
            else:
                metrics['success_rate'] = 0.0
            return metrics

class NegotiationAPI:
    def __init__(self, config=None):
        self.orchestrator = NegotiationOrchestrator()
        self.reputation = self.orchestrator.reputation_system
    
    def create_agents(self, count=2, prefix="agent"):
        agent_ids = []
        for i in range(count):
            agent_id = f"{prefix}_{i+1}"
            role = AgentRole.INITIATOR if i % 2 == 0 else AgentRole.RESPONDER
            min_price = 40 + (i * 10) % 50
            max_price = 140 + (i * 15) % 40
            
            profile = UtilityProfile(
                min_acceptable_price=min_price,
                max_acceptable_price=max_price,
                role=role
            )
            agent = StrategicAgent(agent_id, role, profile, self.reputation)
            self.orchestrator.register_agent(agent)
            agent_ids.append(agent_id)
        
        return agent_ids
    
    def negotiate(self, agent_a, agent_b, item="item", initial_price=100.0, max_rounds=None):
        session = self.orchestrator.create_session(agent_a, agent_b, "api_negotiation", item)
        if not session:
            return {'success': False, 'error': 'Could not create session'}
        
        if max_rounds:
            session.max_rounds = max_rounds
        
        status = self.orchestrator.run_negotiation(session)
        
        return {
            'success': status == NegotiationStatus.ACCEPTED,
            'status': status,
            'final_price': session.final_offer.price if session.final_offer else None,
            'rounds': session.current_round,
            'session_id': session.session_id
        }
    
    def add_review(self, reviewer, reviewee, rating, comment="", dimensions=None):
        review = self.reputation.add_review(
            reviewer, reviewee, str(uuid.uuid4()),
            rating, dimensions=dimensions, comment=comment
        )
        return review is not None
    
    def get_reputation(self, entity_id):
        return self.reputation.get_profile(entity_id)
    
    def get_leaderboard(self, limit=10):
        profiles = []
        for entity_id in self.reputation.entities:
            profile = self.reputation.get_profile(entity_id)
            profiles.append(profile)
        profiles.sort(key=lambda x: x.get('overall_score', 0), reverse=True)
        return profiles[:limit]
    
    def get_metrics(self):
        return self.orchestrator.get_metrics()

# ================================================================================
# SECCION 30: TRUST GUARD Y RUTAS INTELIGENTES
# ================================================================================
def TRUST_GUARD(aceptaciones_rapidas=0, incoherencias_temporales=0,
                nivel_confianza="ALTO", etiqueta_interna="HUMAN_LIKE_AUTOMATION"):
    if incoherencias_temporales > 2 or str(nivel_confianza).upper() == "BAJO":
        return "ESTADO_CONSERVADOR"
    return "ESTADO_NORMAL"

_rutas_inteligentes_cache = {'key': None, 'data': None, 'timestamp': 0.0}
_cache_lock = threading.Lock()

def rutas_inteligentes(ubicacion_actual=None, radio_busqueda_km=10.0, max_destinos=5,
                       priorizar="ingreso_por_minuto", auto_trigger_ollama=True, ceoia_instance=None):
    global _rutas_inteligentes_cache

    if ubicacion_actual is None:
        ultima_zona = globals().get('ULTIMA_ZONA', 'z1')
        try:
            zona_info = get_zona_by_id(ultima_zona)
        except Exception:
            zona_info = None

        if zona_info:
            lat_centro = (zona_info["lat_min"] + zona_info["lat_max"]) / 2
            lng_centro = (zona_info["lon_min"] + zona_info["lon_max"]) / 2
            ubicacion_actual = {
                "lat": round(lat_centro + random.uniform(-0.01, 0.01), 6),
                "lng": round(lng_centro + random.uniform(-0.01, 0.01), 6)
            }
        else:
            ubicacion_actual = {"lat": 8.9922, "lng": -79.5201}

    cache_key = (round(ubicacion_actual["lat"], 3), round(ubicacion_actual["lng"], 3), float(radio_busqueda_km))
    current_time = time.time()

    with _cache_lock:
        if (_rutas_inteligentes_cache['key'] == cache_key and
                current_time - _rutas_inteligentes_cache['timestamp'] < 30):
            return _rutas_inteligentes_cache['data']

    zonas_candidatas = []
    zona_lock = globals().get('ZONA_LOCK')
    if zona_lock:
        with zona_lock:
            zonas_snapshot = list(globals().get('ZONAS', []))
            zona_estado_snapshot = dict(globals().get('zona_estado', {}))
    else:
        zonas_snapshot = globals().get('ZONAS', [])
        zona_estado_snapshot = globals().get('zona_estado', {})

    for zona in zonas_snapshot:
        lat_centro = (zona["lat_min"] + zona["lat_max"]) / 2
        lng_centro = (zona["lon_min"] + zona["lon_max"]) / 2
        distancia = calcular_distancia_py(
            ubicacion_actual["lat"], ubicacion_actual["lng"],
            lat_centro, lng_centro
        )
        if distancia <= radio_busqueda_km:
            estado_zona = zona_estado_snapshot.get(zona["id"], {})
            zonas_candidatas.append({
                "zona_id": zona["id"], "nombre": zona["nombre"],
                "distancia_km": round(distancia, 2),
                "color": estado_zona.get("color", "gris"),
                "demanda": estado_zona.get("demanda", 0),
                "oferta": estado_zona.get("oferta", 0),
                "ratio_demanda": estado_zona.get("ratio_demanda", 0),
                "ganancia_estimada": estado_zona.get("ganancia_estimada", 0),
                "tiempo_espera": estado_zona.get("tiempo_espera", 0)
            })

    if not zonas_candidatas:
        resultado = {
            "error": "No hay zonas disponibles",
            "rutas": [], "mejor_opcion": None, "timestamp": current_time
        }
        with _cache_lock:
            _rutas_inteligentes_cache = {'key': cache_key, 'data': resultado, 'timestamp': current_time}
        return resultado

    rutas_evaluadas = []
    hora_utc = _datetime.now(_timezone.utc).hour
    bonus_hora = 1.3 if (7 <= hora_utc <= 9 or 17 <= hora_utc <= 20) else 1.0
    color_multiplicador = {"rojo": 1.5, "naranja": 1.2, "azul": 1.0, "gris": 0.9}
    prioridad_pesos = {
        "ingreso_por_minuto": 1.2,
        "distancia_corta": 0.8,
        "zona_roja": 1.5,
        "demanda": 1.3
    }
    peso_base = globals().get('ALGO_WEIGHTS', {}).get("fare", 1.0)

    for zona in zonas_candidatas:
        tarifa_estimada = (
            zona["ganancia_estimada"]
            if zona["ganancia_estimada"] > 0
            else random.uniform(5.0, 15.0)
        )
        tiempo_total = zona["tiempo_espera"] + (zona["distancia_km"] * 2)
        ingreso_por_minuto = tarifa_estimada / max(1, tiempo_total)

        bonus_color = color_multiplicador.get(zona["color"], 1.0)
        ratio_demanda = zona["ratio_demanda"]
        ratio_factor = min(2.0, ratio_demanda / 1.5) if ratio_demanda > 0 else 0.5
        bonus_cercania = max(0.5, 1.5 - (zona["distancia_km"] / 10))

        score_base = ingreso_por_minuto * peso_base * bonus_color * ratio_factor * bonus_hora * bonus_cercania
        score_final = score_base * prioridad_pesos.get(priorizar, 1.0)

        eta_valida = zona["tiempo_espera"] >= 0
        estado_op = TRUST_GUARD(
            aceptaciones_rapidas=0,
            incoherencias_temporales=0 if eta_valida else 1,
            nivel_confianza="ALTO",
            etiqueta_interna="HUMAN_LIKE_AUTOMATION"
        )
        puede_recomendar = estado_op != "ESTADO_CONSERVADOR" and tarifa_estimada >= 3.13

        rutas_evaluadas.append({
            "zona_id": zona["zona_id"], "nombre": zona["nombre"],
            "distancia_km": zona["distancia_km"],
            "tarifa_estimada": round(tarifa_estimada, 2),
            "ingreso_por_minuto": round(ingreso_por_minuto, 2),
            "color_zona": zona["color"],
            "score_final": round(score_final, 3),
            "puede_recomendar": puede_recomendar
        })

    rutas_validas = [r for r in rutas_evaluadas if r["puede_recomendar"]] or rutas_evaluadas
    rutas_ordenadas = sorted(rutas_validas, key=lambda x: x["score_final"], reverse=True)[:max_destinos]
    mejor_opcion = rutas_ordenadas[0] if rutas_ordenadas else None

    if auto_trigger_ollama and mejor_opcion:
        target = ceoia_instance
        if target is None:
            target = globals().get('ceo_avanzado')
        if target is not None:
            try:
                orden_ollama = "rutas_inteligentes: zona=" + mejor_opcion['zona_id'] + " score=" + str(mejor_opcion['score_final'])
                handler = getattr(target, 'recibir_orden_ollama', None) or getattr(target, 'recibir_orden', None)
                if handler:
                    handler(orden_ollama)
                log("[OLLAMA] Auto-trigger: " + orden_ollama[:80])
            except Exception as e:
                log("[WARN] Error auto-trigger Ollama: " + str(e))

    log("[RUTAS] " + str(len(rutas_ordenadas)) + " opciones | Mejor: " + (mejor_opcion['nombre'] if mejor_opcion else 'N/A'))

    resultado = {
        "rutas": rutas_ordenadas, "mejor_opcion": mejor_opcion,
        "metricas": {
            "total_zonas": len(zonas_candidatas), "criterio": priorizar,
            "hora": hora_utc, "zona_actual": globals().get('ULTIMA_ZONA', 'desconocida')
        },
        "driver_edge_aplicado": True, "timestamp": current_time
    }
    with _cache_lock:
        _rutas_inteligentes_cache = {'key': cache_key, 'data': resultado, 'timestamp': current_time}
    return resultado

def analizar_ruta_optima(gps_actual, destino):
    try:
        distancia = calcular_distancia_py(
            gps_actual.get("lat", 0), gps_actual.get("lng", 0),
            destino.get("lat", 0), destino.get("lng", 0)
        )
        num_puntos = max(2, int(distancia * 2))
        puntos_ruta = []
        divisor = max(1, num_puntos - 1)
        for i in range(num_puntos):
            t = i / divisor
            lat = gps_actual.get("lat", 0) + (destino.get("lat", 0) - gps_actual.get("lat", 0)) * t
            lng = gps_actual.get("lng", 0) + (destino.get("lng", 0) - gps_actual.get("lng", 0)) * t
            puntos_ruta.append({
                "lat": round(lat, 6),
                "lng": round(lng, 6),
                "orden": i
            })

        return {
            "distancia_km": round(distancia, 2),
            "tiempo_estimado_min": round((distancia / 30) * 60, 1),
            "puntos": puntos_ruta,
            "consumo_estimado_litros": round(distancia * 0.08, 2)
        }
    except Exception as e:
        log("[ERROR] Error analizando ruta: " + str(e))
        return {"error": str(e)}

analizar_ruta_optimale = analizar_ruta_optima

def ciclo_rutas_inteligentes():
    while not STOP_EVENT.is_set():
        try:
            estado_conductor = globals().get('ESTADO_CONDUCTOR', 'IDLE')
            if estado_conductor == "IDLE":
                resultado = rutas_inteligentes(priorizar="ingreso_por_minuto")
                if resultado.get("mejor_opcion"):
                    log("[RUTA] Sugerida: " + resultado['mejor_opcion']['nombre'])
            time.sleep(300)
        except Exception as e:
            log("[ERROR] Ciclo rutas: " + str(e))
            time.sleep(60)

# ================================================================================
# SECCION 31: SISTEMA DE KILOMETRAJE LEARNER
# ================================================================================
class KilometrajeLearner:
    def __init__(self):
        self.km_totales = 0.0
        self.km_por_zona = defaultdict(float)
        self.km_por_hora = defaultdict(float)
        self.km_por_dia = defaultdict(float)
        self.ganancia_por_km = deque(maxlen=200)
        self.eficiencia_km = deque(maxlen=100)
        self.historial_km = deque(maxlen=500)
        self.last_position = None
        self.last_timestamp = None
        self._lock = threading.Lock()

    def registrar_movimiento(self, lat1, lng1, lat2, lng2, timestamp=None):
        with self._lock:
            distancia = calcular_distancia_py(lat1, lng1, lat2, lng2)
            if timestamp is None:
                timestamp = time.time()

            self.km_totales += distancia
            self.historial_km.append({
                'timestamp': timestamp, 'distancia': distancia,
                'origen': (round(lat1, 6), round(lng1, 6)),
                'destino': (round(lat2, 6), round(lng2, 6))
            })

            zona_actual = ULTIMA_ZONA
            self.km_por_zona[zona_actual] += distancia

            dt = _datetime.fromtimestamp(timestamp)
            hora = dt.hour
            dia = dt.weekday()
            self.km_por_hora[hora] += distancia
            self.km_por_dia[dia] += distancia

            if self.last_timestamp and timestamp > self.last_timestamp:
                tiempo_horas = (timestamp - self.last_timestamp) / 3600
                if tiempo_horas > 0:
                    eficiencia = distancia / tiempo_horas
                    self.eficiencia_km.append(eficiencia)

            self.last_timestamp = timestamp

            return {
                'distancia_km': round(distancia, 3),
                'km_totales': round(self.km_totales, 3),
                'km_en_zona': round(self.km_por_zona[zona_actual], 3),
                'eficiencia_promedio': self.get_eficiencia_promedio()
            }

    def registrar_ganancia_por_km(self, ganancia, km_recorridos):
        if km_recorridos <= 0:
            return 0.0
        ganancia_por_km = ganancia / km_recorridos
        self.ganancia_por_km.append({
            'timestamp': time.time(), 'ganancia': ganancia,
            'km': km_recorridos, 'ganancia_por_km': ganancia_por_km
        })
        self._actualizar_aprendizaje_km(ganancia_por_km)
        return ganancia_por_km

    def _actualizar_aprendizaje_km(self, ganancia_por_km):
        if ganancia_por_km > 5.0:
            factor = 1.05
            mensaje = "[KM] Alta rentabilidad ($" + str(round(ganancia_por_km, 2)) + "/km) -> aumentando peso distancia"
        elif ganancia_por_km < 2.0:
            factor = 0.95
            mensaje = "[KM] Baja rentabilidad ($" + str(round(ganancia_por_km, 2)) + "/km) -> reduciendo peso distancia"
        else:
            return
        ALGO_WEIGHTS['distance'] = max(0.1, min(2.0, ALGO_WEIGHTS.get('distance', 0.2) * factor))
        ALGO_WEIGHTS['distance_traveled'] = max(0.01, min(1.0, ALGO_WEIGHTS.get('distance_traveled', 0.05) * factor))
        log(mensaje)

    def get_eficiencia_promedio(self):
        if self.eficiencia_km:
            return sum(self.eficiencia_km) / len(self.eficiencia_km)
        return 0.0

    def get_mejor_hora_por_km(self):
        if self.km_por_hora:
            return max(self.km_por_hora.items(), key=lambda x: x[1])[0]
        return -1

    def get_mejor_zona_por_km(self):
        if self.km_por_zona:
            return max(self.km_por_zona.items(), key=lambda x: x[1])[0]
        return ULTIMA_ZONA

    def get_ganancia_promedio_por_km(self):
        if self.ganancia_por_km:
            ultimas = list(self.ganancia_por_km)[-50:]
            return sum(g['ganancia_por_km'] for g in ultimas) / len(ultimas)
        return 0.0

    def get_stats(self):
        with self._lock:
            return {
                'km_totales': round(self.km_totales, 2),
                'eficiencia_promedio_kmh': round(self.get_eficiencia_promedio(), 2),
                'ganancia_promedio_por_km': round(self.get_ganancia_promedio_por_km(), 2),
                'mejor_hora_km': self.get_mejor_hora_por_km(),
                'mejor_zona_km': self.get_mejor_zona_por_km(),
                'km_por_zona': dict(self.km_por_zona),
                'km_por_hora': dict(self.km_por_hora),
                'ultimos_km': [round(h['distancia'], 3) for h in list(self.historial_km)[-10:]]
            }

    def predecir_consumo(self, distancia_km, tipo_ruta="urbano"):
        factores = {"urbano": 0.09, "carretera": 0.07, "trafico_pesado": 0.12, "nocturno": 0.085}
        factor = factores.get(tipo_ruta, 0.09)
        consumo_estimado = distancia_km * factor
        costo_combustible = consumo_estimado * 1.15
        return {
            "consumo_litros": round(consumo_estimado, 2),
            "costo_combustible": round(costo_combustible, 2),
            "tipo_ruta": tipo_ruta
        }

    def sugerir_ruta_optima(self, destinos_posibles):
        if not destinos_posibles or not self.ganancia_por_km:
            return destinos_posibles[0] if destinos_posibles else None
        mejor_destino = None
        mejor_score = -float('inf')
        for dest in destinos_posibles:
            distancia = dest.get("distancia_km", 0)
            ganancia_estimada = dest.get("tarifa_estimada", 0)
            eficiencia_esperada = ganancia_estimada / max(distancia, 0.1)
            boost_frecuencia = 0
            for ruta_key, datos_ruta in [
                (k, v) for k, v in [
                    (str(d.get('zona_id', '')), d) for d in [dest]
                ]
            ]:
                if datos_ruta.get("demanda", 0) > 5:
                    boost_frecuencia = 0.2
            score = eficiencia_esperada * (1 + boost_frecuencia)
            if score > mejor_score:
                mejor_score = score
                mejor_destino = dest
        return mejor_destino

def inicializar_kilometraje_learner(ceoia_instance):
    if not hasattr(ceoia_instance, 'km_learner') or ceoia_instance.km_learner is None:
        ceoia_instance.km_learner = KilometrajeLearner()
        ceoia_instance.ultima_posicion_km = None
        ceoia_instance.km_acumulados_viaje = 0.0
        log("[KM] Sistema de aprendizaje por kilometraje inicializado")
    return ceoia_instance.km_learner

def actualizar_kilometraje(ceoia_instance, lat_actual, lng_actual):
    if not hasattr(ceoia_instance, 'km_learner') or ceoia_instance.km_learner is None:
        inicializar_kilometraje_learner(ceoia_instance)
    learner = ceoia_instance.km_learner
    if ceoia_instance.ultima_posicion_km:
        lat_ant, lng_ant = ceoia_instance.ultima_posicion_km
        resultado = learner.registrar_movimiento(lat_ant, lng_ant, lat_actual, lng_actual)
        ceoia_instance.km_acumulados_viaje += resultado['distancia_km']
        if hasattr(ceoia_instance, 'memoria_sistema'):
            if 'movimiento' not in ceoia_instance.memoria_sistema:
                ceoia_instance.memoria_sistema['movimiento'] = {'velocidades': [], 'paradas': [], 'desviaciones': []}
            ceoia_instance.memoria_sistema['movimiento']['velocidades'].append(resultado['eficiencia_promedio'])
            while len(ceoia_instance.memoria_sistema['movimiento']['velocidades']) > 100:
                ceoia_instance.memoria_sistema['movimiento']['velocidades'].pop(0)
        if int(learner.km_totales) % 5 == 0 and resultado['distancia_km'] > 0:
            stats = learner.get_stats()
            log("[KM] Totales: " + str(stats['km_totales']) + "km | Ef: " + str(round(stats['eficiencia_promedio_kmh'], 1)) + "km/h | $/km: $" + str(round(stats['ganancia_promedio_por_km'], 2)))
    ceoia_instance.ultima_posicion_km = (lat_actual, lng_actual)

def registrar_ganancia_viaje(ceoia_instance, ganancia):
    if not hasattr(ceoia_instance, 'km_learner') or ceoia_instance.km_learner is None:
        inicializar_kilometraje_learner(ceoia_instance)
    if ceoia_instance.km_acumulados_viaje > 0:
        ganancia_por_km = ceoia_instance.km_learner.registrar_ganancia_por_km(
            ganancia, ceoia_instance.km_acumulados_viaje
        )
        log("[KM] Viaje: $" + str(round(ganancia, 2)) + " en " + str(round(ceoia_instance.km_acumulados_viaje, 2)) + "km -> $" + str(round(ganancia_por_km, 2)) + "/km")
        ceoia_instance.km_acumulados_viaje = 0.0
        return ganancia_por_km
    return 0.0

def iniciar_monitoreo_kilometraje(ceoia_instance):
    def monitorear_km():
        while not STOP_EVENT.is_set():
            try:
                gps = getattr(ceoia_instance, 'gps_actual', None) or GPS_ACTUAL
                if gps and isinstance(gps, dict):
                    lat = gps.get('lat')
                    lng = gps.get('lng')
                    if lat is not None and lng is not None:
                        actualizar_kilometraje(ceoia_instance, float(lat), float(lng))
                time.sleep(10)
            except Exception as e:
                log("[WARN] Error monitoreo KM: " + str(e))
                time.sleep(30)
    hilo = threading.Thread(target=monitorear_km, daemon=True, name="KM_Monitor")
    hilo.start()
    log("[KM] Monitoreo de kilometraje iniciado")
    return hilo

# ================================================================================
# SECCION 32: FUNCIONES GPS Y ACTUALIZACION
# ================================================================================
def actualizar_gps_a_mejor_opcion(ubicacion_objetivo=None):
    global ULTIMA_ZONA, GPS_ACTUAL, GPS_OBJETIVO

    try:
        gps_actual = leer_gps_actual()
        GPS_ACTUAL = gps_actual

        if ubicacion_objetivo is None:
            log("[GPS] Calculando mejor opcion...")
            resultado_rutas = rutas_inteligentes(
                ubicacion_actual=gps_actual,
                priorizar="ingreso_por_minuto",
                auto_trigger_ollama=True
            )
            if resultado_rutas.get("mejor_opcion"):
                mejor_zona = resultado_rutas["mejor_opcion"]
                zona_info = get_zona_by_id(mejor_zona["zona_id"])
                if zona_info:
                    lat_objetivo = (zona_info["lat_min"] + zona_info["lat_max"]) / 2
                    lng_objetivo = (zona_info["lon_min"] + zona_info["lon_max"]) / 2
                    ubicacion_objetivo = {
                        "lat": lat_objetivo, "lng": lng_objetivo,
                        "zona_id": mejor_zona["zona_id"],
                        "zona_nombre": mejor_zona["nombre"],
                        "score": mejor_zona.get("score_final", 0),
                        "timestamp": time.time()
                    }
                    ULTIMA_ZONA = mejor_zona["zona_id"]
                    log("[GPS] Mejor zona: " + mejor_zona['nombre'] + " (Score: " + str(round(mejor_zona.get('score_final', 0), 3)) + ")")
                else:
                    return {"exito": False, "error": "Zona no encontrada"}
            else:
                return {"exito": False, "error": "Sin mejor opcion"}

        distancia_km = calcular_distancia_py(
            gps_actual["lat"], gps_actual["lng"],
            ubicacion_objetivo["lat"], ubicacion_objetivo["lng"]
        )
        GPS_OBJETIVO = ubicacion_objetivo
        log("[GPS] Actualizado: " + str(round(ubicacion_objetivo["lat"], 6)) + ", " + str(round(ubicacion_objetivo["lng"], 6)))
        log("[GPS] Distancia al objetivo: " + str(round(distancia_km, 2)) + " km")

        historial_gps.append({
            "timestamp": time.time(),
            "origen": gps_actual,
            "destino": ubicacion_objetivo,
            "distancia_km": round(distancia_km, 2)
        })

        return {
            "exito": True,
            "gps_actual": gps_actual,
            "gps_objetivo": ubicacion_objetivo,
            "distancia_km": round(distancia_km, 2),
            "zona_actualizada": ULTIMA_ZONA,
            "timestamp": time.time()
        }

    except Exception as e:
        log("[ERROR] Error actualizando GPS: " + str(e))
        return {"exito": False, "error": str(e)}

def forzar_actualizacion_gps_inmediata():
    log("[GPS] Forzando actualizacion inmediata...")
    try:
        gps_actual = leer_gps_actual()
        resultado_rutas = rutas_inteligentes(
            ubicacion_actual=gps_actual,
            priorizar="ingreso_por_minuto",
            max_destinos=1,
            auto_trigger_ollama=True
        )
        if resultado_rutas.get("mejor_opcion"):
            mejor_zona = resultado_rutas["mejor_opcion"]
            zona_info = get_zona_by_id(mejor_zona["zona_id"])
            if zona_info:
                lat_objetivo = (zona_info["lat_min"] + zona_info["lat_max"]) / 2
                lng_objetivo = (zona_info["lon_min"] + zona_info["lon_max"]) / 2
                ubicacion_objetivo = {
                    "lat": lat_objetivo, "lng": lng_objetivo,
                    "zona_id": mejor_zona["zona_id"],
                    "zona_nombre": mejor_zona["nombre"],
                    "score": mejor_zona.get("score_final", 0),
                    "timestamp": time.time()
                }
                return actualizar_gps_a_mejor_opcion(ubicacion_objetivo)
        return {"exito": False, "error": "No se pudo determinar objetivo"}
    except Exception as e:
        log("[ERROR] GPS inmediata: " + str(e))
        return {"exito": False, "error": str(e)}

def obtener_estado_gps():
    return {
        "gps_activo": GPS_ACTIVO,
        "gps_actual": GPS_ACTUAL,
        "gps_objetivo": GPS_OBJETIVO,
        "ultima_actualizacion": ULTIMA_ACTUALIZACION_GPS,
        "historial_registros": len(historial_gps),
        "zona_actual": ULTIMA_ZONA,
        "estado_conductor": ESTADO_CONDUCTOR,
        "timestamp": time.time()
    }

def integrar_gps_en_ceo(ceoia_instance=None):
    target = ceoia_instance if ceoia_instance is not None else globals().get('ceo_avanzado')
    if target is None:
        log("[GPS] No hay instancia CEOIA disponible para integrar GPS")
        return False
    try:
        if hasattr(target, 'permisos'):
            target.permisos["controlar_gps"] = True
            target.permisos["actualizar_gps_automatico"] = True
        target.actualizar_gps = actualizar_gps_a_mejor_opcion
        target.forzar_actualizacion_gps = forzar_actualizacion_gps_inmediata
        target.obtener_estado_gps = obtener_estado_gps
        if not hasattr(target, 'km_learner') or target.km_learner is None:
            inicializar_kilometraje_learner(target)
        log("[GPS] GPS integrado en CEO exitosamente")
        return True
    except Exception as e:
        log("[ERROR] Error integrando GPS: " + str(e))
        return False

def ciclo_actualizacion_gps_automatico():
    global GPS_ACTIVO, ULTIMA_ACTUALIZACION_GPS
    GPS_ACTIVO = True
    ULTIMA_ACTUALIZACION_GPS = time.time()
    log("[GPS] Ciclo automatico iniciado")
    while not STOP_EVENT.is_set():
        try:
            if ESTADO_CONDUCTOR == "IDLE":
                tiempo_desde = time.time() - ULTIMA_ACTUALIZACION_GPS
                if tiempo_desde >= 300:
                    log("[GPS] Actualizando automaticamente...")
                    resultado = actualizar_gps_a_mejor_opcion()
                    if resultado.get("exito"):
                        log("[GPS] Actualizado a zona: " + str(resultado.get('zona_actualizada', 'N/A')))
                        ULTIMA_ACTUALIZACION_GPS = time.time()
                    else:
                        log("[WARN] Error GPS: " + str(resultado.get('error', 'Desconocido')))
            time.sleep(60)
        except Exception as e:
            log("[ERROR] Ciclo GPS: " + str(e))
            time.sleep(30)

# ================================================================================
# SECCION 33: WATCHDOG Y AUTO-HEAL
# ================================================================================
def verificar_bucle_autonomo():
    global ULTIMA_ACTIVIDAD_BUCLE
    tiempo_inactivo = time.time() - ULTIMA_ACTIVIDAD_BUCLE
    if tiempo_inactivo > 120:
        log("[HEAL] Bucle autonomo congelado detectado (inactivo " + str(round(tiempo_inactivo)) + "s)")
        return True
    return False

def auto_heal_loops():
    log("[HEAL] Auto-Healing Nivel 2 ACTIVADO")
    while not STOP_EVENT.is_set():
        try:
            if verificar_bucle_autonomo():
                active_names = [t.name for t in threading.enumerate()]
                if "Bucle Autonomo" in active_names:
                    log("[HEAL] Bucle Autonomo existe pero inactivo - posible deadlock")
                    ULTIMA_ACTIVIDAD_BUCLE = time.time()
                else:
                    log("[HEAL] Reiniciando Bucle Autonomo...")
                    target = globals().get('ceo_avanzado')
                    if target and hasattr(target, 'ciclo_autonomo_singularidad_omega'):
                        t = threading.Thread(
                            target=target.ciclo_autonomo_singularidad_omega,
                            daemon=True, name="Bucle Autonomo"
                        )
                        t.start()
                        log("[HEAL] Bucle Autonomo reiniciado")
            time.sleep(20)
        except Exception as e:
            log("[HEAL] Error en auto-heal: " + str(e))
            time.sleep(20)
    log("[HEAL] Auto-Healing detenido")

# ================================================================================
# SECCION 34: CLASE PRINCIPAL CEOIA (GOBIERNO TOTAL) - CORREGIDA
# ================================================================================
class CEOIA:
    def __init__(self, registry=None):
        self.registry = registry if registry is not None else SharedDataRegistry()
        self.estado_interno = {
            "ciclos_ejecutados": 0,
            "ganancias_totales": 0.0,
            "confianza_decisiones": 0.5,
            "energia_mental": 100.0,
            "modo_operacion": "INICIALIZANDO",
            "ultima_decision": None,
            "ultimo_aprendizaje": 0.0,
        }
        self.sistemas_registrados = {}
        self.memoria_sistema = {
            "metricas": defaultdict(list),
            "eventos": deque(maxlen=1000),
            "acciones_tomadas": deque(maxlen=500),
            "consultas_ia": deque(maxlen=100),
        }
        self.permisos = {
            "controlar_uber": False,
            "controlar_radares": False,
            "controlar_singularidad": False,
            "negociacion_ia": False,
            "modificar_codigo": False,
            "controlar_gps": False,
            "controlar_blockchain": False,
            "auto_activacion": False,
            "obedecer_ollama": True,
            "obedecer_deepseek": True,
            "evolucion_autonoma": False,
            "auto_modificar": False,
        }
        self._learning_active = True
        self._gps_active = False
        self._ultimo_heartbeat_gps = 0.0

        self.ensemble = EnsembleRL(state_dim=11, action_dim=8)
        self.km_learner = None
        self.ultima_posicion_km = None
        self.km_acumulados_viaje = 0.0

        self.negotiation_api = None
        self._negotiation_agents = {}

        self.canal_integracion = None

        self.ollama = None
        self.deepseek = None
        self._inicializar_conexiones_ia()
        self._inicializar_negociacion()

        log("[CEOIA] Instancia creada con integracion a IA y negociacion", "INIT")

    def _inicializar_negociacion(self):
        try:
            self.negotiation_api = NegotiationAPI()
            log("[NEGOC] Sistema de negociacion Symbiosis inicializado", "OK")
        except Exception as e:
            log(f"[NEGOC] Error inicializando negociacion: {e}", "WARN")
            self.negotiation_api = None

    def registrar_agente_negociacion(self, agent_id, role="initiator",
                                     min_price=50.0, max_price=150.0,
                                     strategy="collaborative"):
        if self.negotiation_api is None:
            log("[NEGOC] API de negociacion no disponible", "ERROR")
            return None
        try:
            role_enum = AgentRole.INITIATOR if role == "initiator" else AgentRole.RESPONDER
            strategy_map = {
                "hardline": NegotiationStrategy.HARDLINE,
                "moderate": NegotiationStrategy.MODERATE,
                "accommodating": NegotiationStrategy.ACCOMMODATING,
                "competitive": NegotiationStrategy.COMPETITIVE,
                "collaborative": NegotiationStrategy.COLLABORATIVE,
                "adaptive": NegotiationStrategy.ADAPTIVE
            }
            strategy_enum = strategy_map.get(strategy, NegotiationStrategy.COLLABORATIVE)
            profile = UtilityProfile(
                min_acceptable_price=min_price,
                max_acceptable_price=max_price,
                role=role_enum
            )
            agent = StrategicAgent(agent_id, role_enum, profile, self.negotiation_api.reputation, strategy_enum)
            self.negotiation_api.orchestrator.register_agent(agent)
            self._negotiation_agents[agent_id] = agent
            log(f"[NEGOC] Agente {agent_id} registrado (estrategia: {strategy})", "OK")
            return agent
        except Exception as e:
            log(f"[NEGOC] Error registrando agente: {e}", "ERROR")
            return None

    def negociar_con_agente(self, agente_local, agente_remoto, item="servicio",
                            precio_inicial=100.0, max_rondas=10):
        if self.negotiation_api is None:
            log("[NEGOC] API de negociacion no disponible", "ERROR")
            return {"success": False, "error": "API no disponible"}
        try:
            resultado = self.negotiation_api.negotiate(agente_local, agente_remoto, item, precio_inicial, max_rondas)
            if resultado.get('success'):
                log(f"[NEGOC] Negociacion exitosa: ${resultado.get('final_price', 0)} en {resultado.get('rounds', 0)} rondas", "OK")
                self.estado_interno["ganancias_totales"] += resultado.get('final_price', 0)
            else:
                log(f"[NEGOC] Negociacion fallida: {resultado.get('status', 'unknown')}", "WARN")
            return resultado
        except Exception as e:
            log(f"[NEGOC] Error en negociacion: {e}", "ERROR")
            return {"success": False, "error": str(e)}

    def obtener_reputacion_agente(self, agent_id):
        if self.negotiation_api is None:
            return {"error": "API no disponible"}
        try:
            return self.negotiation_api.get_reputation(agent_id)
        except Exception as e:
            return {"error": str(e)}

    def obtener_ranking_negociacion(self, limite=10):
        if self.negotiation_api is None:
            return []
        try:
            return self.negotiation_api.get_leaderboard(limite)
        except Exception:
            return []

    # ========== FUNCIONES DE IA CORREGIDAS ==========
    def _inicializar_conexiones_ia(self):
        import re
        if self.permisos.get("obedecer_ollama", False):
            try:
                import subprocess
                result = subprocess.run(["ollama", "list"], capture_output=True, timeout=5)
                if result.returncode == 0:
                    class OllamaClient:
                        def __init__(self):
                            self.modelo = "qwen2.5:0.5b"
                            self.disponible = True
                        def consultar(self, prompt):
                            import subprocess
                            import re
                            try:
                                resultado = subprocess.run(
                                    ["ollama", "run", self.modelo, prompt],
                                    capture_output=True, text=True, timeout=60
                                )
                                respuesta = resultado.stdout.strip()
                                respuesta = re.sub(r'[\x00-\x1f\x7f]', '', respuesta)
                                return {"exito": True, "respuesta": respuesta}
                            except Exception as e:
                                return {"exito": False, "error": str(e)}
                    self.ollama = OllamaClient()
                    log("[IA] Ollama conectado correctamente", "OK")
                else:
                    log("[IA] Ollama no disponible", "WARN")
            except Exception as e:
                log(f"[IA] Error conectando Ollama: {e}", "WARN")
        
        if self.permisos.get("obedecer_deepseek", False):
            try:
                api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("DSK_DEV_KEY")
                if api_key:
                    class DeepSeekClient:
                        def __init__(self, key):
                            self.api_key = key
                            self.disponible = True
                        def consultar(self, prompt):
                            import re
                            try:
                                import requests
                                headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
                                data = {
                                    "model": "deepseek-chat",
                                    "messages": [{"role": "user", "content": prompt[:2000]}],
                                    "temperature": 0.7,
                                    "max_tokens": 500
                                }
                                response = requests.post(
                                    "https://api.deepseek.com/v1/chat/completions",
                                    headers=headers, json=data, timeout=30
                                )
                                if response.status_code == 200:
                                    result = response.json()
                                    respuesta = result["choices"][0]["message"]["content"]
                                    respuesta = re.sub(r'[\x00-\x1f\x7f]', '', respuesta)
                                    return {"exito": True, "respuesta": respuesta}
                                return {"exito": False, "error": f"HTTP {response.status_code}"}
                            except Exception as e:
                                return {"exito": False, "error": str(e)}
                    self.deepseek = DeepSeekClient(api_key)
                    log("[IA] DeepSeek conectado correctamente", "OK")
                else:
                    log("[IA] DeepSeek: API key no configurada", "WARN")
            except Exception as e:
                log(f"[IA] Error conectando DeepSeek: {e}", "WARN")

    def _consultar_ia(self, prompt, contexto=""):
        import re
        import json
        
        prompt_completo = f"""[CONTEXTO DEL SISTEMA]
{contexto}

[INSTRUCCION]
{prompt}

RESPONDE EXACTAMENTE CON ESTE FORMATO JSON, SIN TEXTO ADICIONAL, SIN COMENTARIOS, SIN MARKDOWN:
{{"decision": "ACEPTAR", "confianza": 0.85, "justificacion": "texto sin comillas internas"}}

POSIBLES DECISIONES: ACEPTAR, RECHAZAR, ESPERAR
CONFIANZA: número entre 0 y 1
JUSTIFICACION: texto corto sin comillas dobles"""

        respuesta_bruta = None
        
        if self.ollama and self.ollama.disponible:
            log("[IA] Consultando a Ollama...", "INFO")
            resultado = self.ollama.consultar(prompt_completo)
            if resultado.get("exito"):
                respuesta_bruta = resultado["respuesta"]
                self.memoria_sistema["consultas_ia"].append({
                    "servicio": "ollama",
                    "timestamp": time.time(),
                    "respuesta": respuesta_bruta[:200]
                })
        
        if not respuesta_bruta and self.deepseek and self.deepseek.disponible:
            log("[IA] Consultando a DeepSeek...", "INFO")
            resultado = self.deepseek.consultar(prompt_completo)
            if resultado.get("exito"):
                respuesta_bruta = resultado["respuesta"]
                self.memoria_sistema["consultas_ia"].append({
                    "servicio": "deepseek",
                    "timestamp": time.time(),
                    "respuesta": respuesta_bruta[:200]
                })
        
        if not respuesta_bruta:
            log("[IA] No se obtuvo respuesta de ningún servicio", "WARN")
            return None
        
        # Limpieza y parsing robusto
        cleaned = re.sub(r'[\x00-\x1f\x7f]', '', respuesta_bruta)
        cleaned = re.sub(r'```json\s*', '', cleaned)
        cleaned = re.sub(r'```\s*', '', cleaned)
        cleaned = cleaned.strip()
        
        json_match = re.search(r'\{[^{}]*\}', cleaned, re.DOTALL)
        
        if json_match:
            try:
                data = json.loads(json_match.group())
                decision = data.get("decision", "ESPERAR").upper()
                if decision not in ["ACEPTAR", "RECHAZAR", "ESPERAR"]:
                    decision = "ESPERAR"
                confianza = float(data.get("confianza", 0.5))
                confianza = max(0.0, min(1.0, confianza))
                justificacion = str(data.get("justificacion", ""))[:100]
                justificacion = justificacion.replace('"', "'")
                log(f"[IA] Decisión: {decision} (confianza: {confianza:.2f}) - {justificacion}", "OK")
                return {"decision": decision, "confianza": confianza, "justificacion": justificacion, "fuente": "IA"}
            except json.JSONDecodeError as e:
                log(f"[IA] Error parseando JSON: {e}", "WARN")
                log(f"[IA] Respuesta cruda: {respuesta_bruta[:200]}", "DEBUG")
        
        decision_match = re.search(r'(ACEPTAR|RECHAZAR|ESPERAR)', respuesta_bruta, re.IGNORECASE)
        if decision_match:
            decision = decision_match.group(1).upper()
            confianza_match = re.search(r'confianza["\']?\s*:\s*([0-9.]+)', respuesta_bruta)
            confianza = float(confianza_match.group(1)) if confianza_match else 0.6
            confianza = max(0.0, min(1.0, confianza))
            log(f"[IA] Decisión extraída por regex: {decision} (confianza: {confianza:.2f})", "OK")
            return {"decision": decision, "confianza": confianza, "justificacion": "Extraído de respuesta IA", "fuente": "IA"}
        
        log("[IA] No se pudo extraer decisión, usando ESPERAR por defecto", "WARN")
        return {"decision": "ESPERAR", "confianza": 0.5, "justificacion": "Error en parsing de IA", "fuente": "fallback"}

    def decidir_con_ia(self, oferta):
        prompt = f"""
Evalua esta oferta de viaje:
- Precio: ${oferta.get('price', 0)}
- Tiempo de recogida: {oferta.get('pickup_eta', 0)} min
- Tiempo de entrega: {oferta.get('delivery_eta', 0)} min
- Tipo: {oferta.get('tag', 'NORMAL')}
- Estado conductor: {oferta.get('state', 'IDLE')}

Reglas:
- Si precio < 3.13 → RECHAZAR (perdida asegurada)
- Si precio >= 10.13 → ACEPTAR (muy rentable)
- Si pickup_eta > 10 min → RECHAZAR (espera demasiado larga)

Decide si ACEPTAR, RECHAZAR o ESPERAR."""
        
        respuesta_ia = self._consultar_ia(prompt)
        
        if respuesta_ia and isinstance(respuesta_ia, dict):
            try:
                log(f"[IA] Decisión: {respuesta_ia.get('decision')} (confianza: {respuesta_ia.get('confianza', 0.5):.2f})", "OK")
                return respuesta_ia
            except Exception as e:
                log(f"[IA] Error procesando respuesta: {e}", "WARN")
        
        return self._decidir_por_reglas(oferta)

    def _decidir_por_reglas(self, oferta):
        precio = oferta.get('price', 0)
        pickup_eta = oferta.get('pickup_eta', 0)
        estado = oferta.get('state', 'IDLE')
        
        if precio < 3.13:
            return {"decision": "RECHAZAR", "confianza": 0.95, "justificacion": "Precio minimo no alcanzado", "fuente": "reglas"}
        if precio >= 10.13:
            return {"decision": "ACEPTAR", "confianza": 0.95, "justificacion": "Precio muy rentable", "fuente": "reglas"}
        if pickup_eta > 10 and estado == "IDLE":
            return {"decision": "RECHAZAR", "confianza": 0.85, "justificacion": "Tiempo de espera excesivo", "fuente": "reglas"}
        return {"decision": "ESPERAR", "confianza": 0.6, "justificacion": "Evaluando otras opciones", "fuente": "reglas"}

    # ========== FIN DE FUNCIONES DE IA CORREGIDAS ==========

    def _obtener_oferta_actual(self):
        try:
            if 'radar_instance' in globals() and globals().get('radar_instance'):
                best = globals()['radar_instance'].get_best_opportunity()
                if best:
                    return {
                        "price": best.estimated_value,
                        "pickup_eta": best.wait_time_seconds // 60,
                        "delivery_eta": best.wait_time_seconds // 60 + 5,
                        "tag": "RADAR",
                        "state": ESTADO_CONDUCTOR,
                        "zone": best.zone_id
                    }
        except:
            pass
        
        return {
            "price": round(random.uniform(3, 15), 2),
            "pickup_eta": random.randint(2, 15),
            "delivery_eta": random.randint(5, 20),
            "tag": random.choice(["NORMAL", "PRIORITY", "LONG_TRIP"]),
            "state": ESTADO_CONDUCTOR,
            "zone": ULTIMA_ZONA
        }

    def inicializar_todo(self):
        log("[CEOIA] Inicializando subsistemas...", "INIT")
        cargar_estado()
        load_daimon_brain()
        self.estado_interno["modo_operacion"] = "ACTIVO"
        self.estado_interno["confianza_decisiones"] = 0.7
        self.registry.set("ceoia:estado", "inicializado")
        log("[CEOIA] Inicializacion completa", "INIT")
        return True

    def activar_funciones_automaticas(self):
        log("[CEOIA] Activando funciones automaticas...", "SYSTEM")
        
        if self.permisos.get("obedecer_ollama", False) or self.permisos.get("obedecer_deepseek", False):
            ia_thread = threading.Thread(target=self.ciclo_autonomo_con_ia, daemon=True, name="CicloIA")
            ia_thread.start()
            log("[CEOIA] Ciclo autonomo con IA iniciado", "SYSTEM")
        else:
            bucle_thread = threading.Thread(target=self.ciclo_autonomo_singularidad_omega,
                                            daemon=True, name="Bucle Autonomo")
            bucle_thread.start()
        
        gps_thread = threading.Thread(target=ciclo_actualizacion_gps_automatico,
                                      daemon=True, name="GPS Auto")
        gps_thread.start()
        
        heal_thread = threading.Thread(target=auto_heal_loops,
                                       daemon=True, name="AutoHeal")
        heal_thread.start()
        
        if self.km_learner is not None:
            iniciar_monitoreo_kilometraje(self)
        
        log("[CEOIA] Bucles autonomos lanzados", "SYSTEM")
        return {"exito": True, "mensaje": "Funciones automaticas activadas"}

    def ciclo_autonomo_con_ia(self):
        log("[CEOIA] Ciclo autonomo con IA iniciado", "SINGULARITY")
        
        while not STOP_EVENT.is_set():
            try:
                oferta = self._obtener_oferta_actual()
                
                if self.permisos.get("obedecer_ollama", False) or self.permisos.get("obedecer_deepseek", False):
                    decision = self.decidir_con_ia(oferta)
                else:
                    decision = self._decidir_por_reglas(oferta)
                
                self._ejecutar_decision_ia(decision, oferta)
                self.estado_interno["ciclos_ejecutados"] += 1
                self.estado_interno["ultima_decision"] = decision
                
                time.sleep(30)
            except Exception as e:
                log(f"[CEOIA] Error: {e}", "ERROR")
                time.sleep(10)

    def _ejecutar_decision_ia(self, decision, oferta):
        accion = decision.get("decision", "ESPERAR")
        
        if accion == "ACEPTAR":
            log(f"[CEOIA] ACEPTANDO oferta: ${oferta.get('price')} - {decision.get('justificacion')}", "OK")
            self.estado_interno["confianza_decisiones"] = min(1.0, self.estado_interno["confianza_decisiones"] + 0.05)
        elif accion == "RECHAZAR":
            log(f"[CEOIA] RECHAZANDO oferta: ${oferta.get('price')} - {decision.get('justificacion')}", "WARN")
            self.estado_interno["confianza_decisiones"] = max(0.0, self.estado_interno["confianza_decisiones"] - 0.02)
        else:
            log(f"[CEOIA] ESPERANDO - {decision.get('justificacion')}", "INFO")

    def ciclo_autonomo_singularidad_omega(self, duracion_ciclo=60, nivel_agresividad=0.85):
        global ULTIMA_ACTIVIDAD_BUCLE
        log("[CEOIA] Ciclo autonomo (RL) iniciado", "SINGULARITY")
        while not STOP_EVENT.is_set():
            inicio_ciclo = time.time()
            try:
                estado_actual = self._get_current_state()
                accion, confianza = self.ensemble.select_action(estado_actual, exploit_only=False)
                resultado_ejecucion = self._ejecutar_accion(accion, estado_actual)
                recompensa = self._calcular_recompensa(estado_actual, resultado_ejecucion)
                nuevo_estado = self._get_current_state()
                self.ensemble.update(estado_actual, accion, recompensa, nuevo_estado, False)
                self.estado_interno["ciclos_ejecutados"] += 1
                self.estado_interno["ultima_decision"] = {"accion": accion, "confianza": confianza, "timestamp": time.time()}
                ULTIMA_ACTIVIDAD_BUCLE = time.time()
                if hasattr(self, 'procesar_mensajes_pendientes'):
                    self.procesar_mensajes_pendientes()
            except Exception as e:
                log("[CEOIA] Error en ciclo autonomo: " + str(e), "ERROR")
            tiempo_ciclo = time.time() - inicio_ciclo
            pausa = max(0.1, duracion_ciclo - tiempo_ciclo)
            STOP_EVENT.wait(pausa)
        log("[CEOIA] Ciclo autonomo terminado", "SINGULARITY")

    def gobernar_sistema_completo(self):
        log("[CEOIA] Gobernando sistema completo...", "GOV")
        resultado = {
            "radares": self.gobernar_radares(),
            "negociacion": self.negociar_entre_ias(),
            "singularidad": self.controlar_singularidad_omega(duracion_ciclo=10),
            "timestamp": time.time()
        }
        self.registry.set("ceoia:ultimo_gobierno", resultado)
        return resultado

    def gobernar_radares(self, modo="completo"):
        log("[CEOIA] Gobernando radares...", "RADAR")
        resultado_rutas = rutas_inteligentes(ceoia_instance=self, priorizar="ingreso_por_minuto")
        if modo == "completo" and resultado_rutas.get("mejor_opcion"):
            mejor = resultado_rutas["mejor_opcion"]
            self.registry.set("ceoia:mejor_zona", mejor)
            log(f"[RADAR] Zona recomendada: {mejor['nombre']} (score {mejor['score_final']})")
        return resultado_rutas

    def controlar_singularidad_omega(self, duracion_ciclo=60, nivel_agresividad=0.85):
        hilo = threading.Thread(target=self.ciclo_autonomo_singularidad_omega,
                                args=(duracion_ciclo, nivel_agresividad),
                                daemon=True)
        hilo.start()
        return {"exito": True, "hilo_iniciado": hilo.name, "nivel_agresividad": nivel_agresividad}

    def negociar_entre_ias(self, ias_objetivo=None):
        log("[CEOIA] Negociacion entre IAs...", "NEGOC")
        oferta = random.uniform(5, 15)
        contra_oferta = oferta * random.uniform(0.8, 1.2)
        resultado = {
            "oferta_inicial": round(oferta, 2),
            "contra_oferta": round(contra_oferta, 2),
            "aceptada": contra_oferta >= oferta * 0.9,
            "metodo": "simulado"
        }
        self.registry.set("ceoia:ultima_negociacion", resultado)
        return resultado

    def auditar_sistema_completo(self):
        health = get_system_health()
        health["ceoia"] = {
            "estado_interno": self.estado_interno,
            "permisos_activos": {k: v for k, v in self.permisos.items() if v},
            "learning_active": self._learning_active,
            "ensemble_state": self.ensemble.get_state() if hasattr(self.ensemble, 'get_state') else {},
            "km_stats": self.obtener_estadisticas_kilometraje() if self.km_learner else None,
            "consultas_ia": len(self.memoria_sistema["consultas_ia"]),
            "ia_disponible": self.ollama is not None or self.deepseek is not None,
            "negociacion_disponible": self.negotiation_api is not None,
            "agentes_negociacion": len(self._negotiation_agents)
        }
        return health

    def optimizar_sistema_automatico(self):
        log("[CEOIA] Optimizando sistema...", "OPT")
        if hasattr(self.ensemble, 'optimize_weights'):
            def fitness_fn(weights):
                return self.estado_interno.get("ganancias_totales", 0) / max(1, self.estado_interno["ciclos_ejecutados"])
            self.ensemble.optimize_weights(fitness_fn)
        with _ZONA_CACHE_LOCK:
            _ZONA_CACHE.clear()
        return {"exito": True, "mensaje": "Optimizacion aplicada"}

    def _get_current_state(self):
        return [
            float(ALGO_WEIGHTS.get("fare", 1.0)),
            float(ALGO_WEIGHTS.get("distance", 0.2)),
            float(UBER_COINS.to_float_approx() if UBER_COINS else 0.0),
            float(ESTADO_CONDUCTOR == "BUSY"),
            float(len(blockchain)),
            float(self.estado_interno["confianza_decisiones"]),
            float(self.estado_interno["energia_mental"] / 100.0),
            float(activity_factor()),
            float(GPS_ACTIVO),
            float(len(historial_gps)),
            float(ULTIMA_ZONA[1] if ULTIMA_ZONA.startswith("z") else 0)
        ]

    def decide_action(self, state):
        action, _ = self.ensemble.select_action(state)
        return action

    def learn(self, state, action, reward, next_state=None):
        if not self._learning_active:
            return
        if next_state is None:
            next_state = self._get_current_state()
        self.ensemble.update(state, action, reward, next_state, False)
        self.estado_interno["ultimo_aprendizaje"] = time.time()

    def _ejecutar_accion(self, accion, estado_actual):
        resultados = {}
        if accion == 0:
            resultados["gps"] = actualizar_gps_a_mejor_opcion()
        elif accion == 1:
            resultados["mineria"] = self._minar_bloque()
        elif accion == 2:
            resultados["negociacion"] = self.negociar_entre_ias()
        elif accion == 3:
            resultados["optimizacion"] = self.optimizar_sistema_automatico()
        elif accion == 4:
            self.estado_interno["confianza_decisiones"] = min(1.0, self.estado_interno["confianza_decisiones"] + 0.05)
        elif accion == 5:
            self.estado_interno["energia_mental"] = max(0, self.estado_interno["energia_mental"] - 2)
        else:
            resultados["default"] = "accion por definir"
        return resultados

    def _calcular_recompensa(self, estado_anterior, resultado_ejecucion):
        cambio_ganancia = 0.0
        if UBER_COINS:
            cambio_ganancia = UBER_COINS.to_float_approx() - estado_anterior[2]
        cambio_confianza = self.estado_interno["confianza_decisiones"] - estado_anterior[5]
        reward = cambio_ganancia * 0.5 + cambio_confianza * 10.0
        return max(-5.0, min(15.0, reward))

    def _minar_bloque(self):
        global block_number, blockchain, UBER_COINS, viral_blocks
        bloque = {
            "index": block_number,
            "timestamp": time.time(),
            "data": {"zona": ULTIMA_ZONA, "ganancia": random.uniform(1, 5)},
            "nonce": random.randint(1000, 9999)
        }
        blockchain.append(bloque)
        reward = random.uniform(0.5, 2.0)
        if UBER_COINS:
            UBER_COINS.add(reward)
        block_number += 1
        latir_corazon(bloque)
        log(f"[MINERIA] Bloque {bloque['index']} minado, recompensa +{reward:.2f}")
        return {"block": bloque, "reward": reward}

    def get_gps_state(self):
        return obtener_estado_gps()

    def actualizar_gps_manual(self):
        return forzar_actualizacion_gps_inmediata()

    def obtener_estadisticas_kilometraje(self):
        if self.km_learner:
            return self.km_learner.get_stats()
        return {"error": "KilometrajeLearner no inicializado"}

    def recibir_orden(self, orden):
        orden = orden.lower().strip()
        log(f"[CEOIA] Orden recibida: {orden}", "COMANDO")
        
        if "negociar" in orden or "negotiate" in orden:
            partes = orden.split()
            if len(partes) >= 3:
                agente_a = partes[1] if len(partes) > 1 else "ceoia_agent"
                agente_b = partes[2] if len(partes) > 2 else "external_agent"
                return self.negociar_con_agente(agente_a, agente_b, "servicio", 100.0, 10)
            return {"exito": False, "mensaje": "Uso: negociar <agente_a> <agente_b>"}
        elif "reputacion" in orden:
            partes = orden.split()
            if len(partes) >= 2:
                return self.obtener_reputacion_agente(partes[1])
            return self.obtener_ranking_negociacion()
        elif "gps" in orden and "actualizar" in orden:
            return self.actualizar_gps_manual()
        elif "radar" in orden or "ruta" in orden:
            return self.gobernar_radares()
        elif "singularidad" in orden or "bucle" in orden:
            return self.controlar_singularidad_omega()
        elif "auditar" in orden:
            return self.auditar_sistema_completo()
        elif "optimizar" in orden:
            return self.optimizar_sistema_automatico()
        else:
            return {"exito": False, "mensaje": f"Orden '{orden}' no reconocida"}

    def obtener_estado_completo(self):
        return {
            "estado_interno": self.estado_interno,
            "gps": obtener_estado_gps(),
            "zona_actual": ULTIMA_ZONA,
            "conductor": ESTADO_CONDUCTOR,
            "uber_coins": UBER_COINS.to_float_approx() if UBER_COINS else 0,
            "blockchain_len": len(blockchain),
            "km": self.obtener_estadisticas_kilometraje() if self.km_learner else None,
            "ensemble": self.ensemble.get_state() if hasattr(self.ensemble, 'get_state') else {},
            "ia_disponible": self.ollama is not None or self.deepseek is not None,
            "consultas_ia": len(self.memoria_sistema["consultas_ia"]),
            "negociacion_disponible": self.negotiation_api is not None,
            "agentes_negociacion": list(self._negotiation_agents.keys())
        }

    def enviar_a_parte(self, parte_destino, mensaje, payload=None, prioridad="normal"):
        if not hasattr(self, 'canal_integracion') or self.canal_integracion is None:
            return {"exito": False, "error": "Canal de integracion no inicializado"}
        return self.canal_integracion.enviar(parte_destino, mensaje, payload, prioridad)

    def recibir_de_parte(self, parte_origen, mensaje, payload=None, prioridad="normal"):
        if not hasattr(self, 'canal_integracion') or self.canal_integracion is None:
            return {"exito": False, "error": "Canal de integracion no inicializado"}
        return self.canal_integracion.recibir(parte_origen, mensaje, payload, prioridad)

    def procesar_orden_gobernador(self, orden, prioridad="normal"):
        return self.recibir_orden(orden)

    def obtener_estado_integracion(self):
        if hasattr(self, 'canal_integracion') and self.canal_integracion:
            return self.canal_integracion.obtener_estadisticas()
        return {"error": "Canal no inicializado"}

    def broadcast_a_hermanas(self, mensaje, payload=None, prioridad="normal"):
        resultados = {}
        for parte in ["parte2", "parte3", "parte4", "parte6", "parte7", "parte8", "parte9"]:
            res = self.enviar_a_parte(parte, mensaje, payload, prioridad)
            resultados[parte] = res.get("exito", False)
        return {"enviadas": len(resultados), "exitosas": sum(1 for v in resultados.values() if v), "detalle": resultados}

    def reportar_al_gobernador(self, tipo_reporte, datos):
        reporte = {
            "tipo": tipo_reporte,
            "parte_origen": "parte5",
            "timestamp": time.time(),
            "estado_interno": {
                "ciclos": self.estado_interno["ciclos_ejecutados"],
                "ganancias": round(self.estado_interno["ganancias_totales"], 2),
                "confianza": round(self.estado_interno["confianza_decisiones"], 2),
                "energia": round(self.estado_interno["energia_mental"], 1)
            },
            "datos": datos
        }
        return self.enviar_a_parte("parte1", "REPORTE_" + tipo_reporte.upper(), reporte, prioridad="normal")

    def solicitar_datos_parte(self, parte_origen, clave_datos):
        return self.enviar_a_parte(parte_origen, "SOLICITUD_DATOS", {"clave": clave_datos}, prioridad="alta")

    def procesar_mensajes_pendientes(self):
        if hasattr(self, 'canal_integracion') and self.canal_integracion:
            return self.canal_integracion.procesar_buzon_entrada()
        return {"procesados": 0}

# ================================================================================
# SECCION 35: CANAL DE INTEGRACION MULTIPARTE
# ================================================================================
class CanalIntegracion:
    PARTES_VALIDAS = ["parte1", "parte2", "parte3", "parte4", "parte5",
                      "parte6", "parte7", "parte8", "parte9"]
    PRIORIDADES = {"critica": 0, "alta": 1, "normal": 2, "baja": 3, "fondo": 4}

    def __init__(self, parte_id="parte5", capacidad_buzon=500):
        self.parte_id = parte_id
        self.capacidad_buzon = capacidad_buzon
        self.buzon_entrada = deque(maxlen=capacidad_buzon)
        self.buzon_salida = deque(maxlen=capacidad_buzon)
        self.historial_mensajes = deque(maxlen=2000)
        self.conexiones_activas = {}
        self.ultima_actividad = {}
        self.contadores = defaultdict(lambda: {"enviados": 0, "recibidos": 0, "errores": 0})
        self._lock = threading.RLock()
        self._callbacks_entrada = defaultdict(list)
        self._callbacks_salida = defaultdict(list)

    def registrar_callback_entrada(self, parte_origen, callback):
        with self._lock:
            self._callbacks_entrada[parte_origen].append(callback)
            return True

    def enviar(self, parte_destino, mensaje, payload=None, prioridad="normal"):
        with self._lock:
            if parte_destino not in self.PARTES_VALIDAS:
                self.contadores[parte_destino]["errores"] += 1
                return {"exito": False, "error": "Parte destino invalida"}
            nivel = self.PRIORIDADES.get(prioridad, 2)
            msg = {
                "id": str(uuid.uuid4())[:12],
                "origen": self.parte_id,
                "destino": parte_destino,
                "mensaje": mensaje,
                "payload": payload or {},
                "prioridad": prioridad,
                "nivel": nivel,
                "timestamp": time.time(),
                "estado": "pendiente"
            }
            self.buzon_salida.append(msg)
            self.historial_mensajes.append(msg)
            self.contadores[parte_destino]["enviados"] += 1
            self.ultima_actividad[parte_destino] = time.time()
            self.conexiones_activas[parte_destino] = True
            for cb in self._callbacks_salida.get(parte_destino, []):
                try:
                    cb(msg)
                except Exception:
                    pass
            return {"exito": True, "mensaje_id": msg["id"]}

    def recibir(self, parte_origen, mensaje, payload=None, prioridad="normal"):
        with self._lock:
            if parte_origen not in self.PARTES_VALIDAS:
                self.contadores[parte_origen]["errores"] += 1
                return {"exito": False, "error": "Parte origen invalida"}
            nivel = self.PRIORIDADES.get(prioridad, 2)
            msg = {
                "id": str(uuid.uuid4())[:12],
                "origen": parte_origen,
                "destino": self.parte_id,
                "mensaje": mensaje,
                "payload": payload or {},
                "prioridad": prioridad,
                "nivel": nivel,
                "timestamp": time.time(),
                "estado": "recibido"
            }
            self.buzon_entrada.append(msg)
            self.historial_mensajes.append(msg)
            self.contadores[parte_origen]["recibidos"] += 1
            self.ultima_actividad[parte_origen] = time.time()
            self.conexiones_activas[parte_origen] = True
            for cb in self._callbacks_entrada.get(parte_origen, []):
                try:
                    cb(msg)
                except Exception:
                    pass
            return {"exito": True, "mensaje_id": msg["id"]}

    def procesar_buzon_entrada(self, max_mensajes=10):
        with self._lock:
            if not self.buzon_entrada:
                return {"procesados": 0}
            pendientes = list(self.buzon_entrada)
            pendientes.sort(key=lambda m: m.get("nivel", 2))
            procesados = []
            for msg in pendientes[:max_mensajes]:
                msg["estado"] = "procesado"
                procesados.append(msg)
            for msg in procesados:
                if msg in self.buzon_entrada:
                    self.buzon_entrada.remove(msg)
            return {"procesados": len(procesados), "mensajes": procesados}

    def obtener_estadisticas(self):
        with self._lock:
            return {
                "parte_id": self.parte_id,
                "conexiones_activas": dict(self.conexiones_activas),
                "buzon_entrada_pendientes": len([m for m in self.buzon_entrada if m["estado"] == "recibido"]),
                "contadores": dict(self.contadores)
            }

# ================================================================================
# SECCION 36: INSTANCIAS GLOBALES Y FUNCIONES DE INICIALIZACION
# ================================================================================
ceoia = None
ceo_avanzado = None
ceo = None

def iniciar_ceoia_unificada(registry=None):
    global ceoia, ceo_avanzado, ceo
    log("[SYSTEM] INICIANDO CEOIA UNIFICADA - GOBIERNO TOTAL")
    ceoia = CEOIA(registry=registry)
    ceo_avanzado = ceoia
    ceo = ceoia
    ceoia.inicializar_todo()
    ceoia.activar_funciones_automaticas()
    log("[OK] CEOIA UNIFICADA LISTA PARA GOBERNAR")
    return ceoia

def _agregar_integracion_a_ceoia(ceoia_instance):
    if ceoia_instance is None:
        return False
    ceoia_instance.canal_integracion = CanalIntegracion(parte_id="parte5", capacidad_buzon=500)

    def _callback_orden_gobernador(msg):
        try:
            mensaje = msg.get("mensaje", "")
            prioridad = msg.get("prioridad", "normal")
            resultado = ceoia_instance.recibir_orden(mensaje)
            ceoia_instance.canal_integracion.enviar(
                "parte1", "RESPUESTA_PARTE5",
                {"orden_original": mensaje, "resultado": resultado},
                prioridad=prioridad
            )
        except Exception as e:
            log(f"[GOBERNADOR] Error: {e}")

    ceoia_instance.canal_integracion.registrar_callback_entrada("parte1", _callback_orden_gobernador)
    return True

def iniciar_ceoia_con_integracion(registry=None):
    global ceoia, ceo_avanzado, ceo
    ceoia = CEOIA(registry=registry)
    ceo_avanzado = ceoia
    ceo = ceoia
    ceoia.inicializar_todo()
    ceoia.activar_funciones_automaticas()
    _agregar_integracion_a_ceoia(ceoia)
    inicializar_kilometraje_learner(ceoia)
    iniciar_monitoreo_kilometraje(ceoia)
    log("[OK] CEOIA UNIFICADA CON INTEGRACION MULTI-PARTE LISTA")
    return ceoia

def desbloquear_ceo_completo():
    global ceo_avanzado, ceoia, ceo
    log("[SYSTEM] Desbloqueando CEO completamente...")
    if ceoia is None:
        log("[SYSTEM] Inicializando CEOIA Unificada...")
        ceoia = iniciar_ceoia_unificada()
        ceo_avanzado = ceoia
        ceo = ceoia
    if hasattr(ceoia, 'permisos'):
        ceoia.permisos.update({
            "controlar_uber": True, "controlar_radares": True,
            "controlar_singularidad": True, "negociacion_ia": True,
            "modificar_codigo": True, "controlar_gps": True,
            "controlar_blockchain": True, "auto_activacion": True,
            "obedecer_ollama": True, "obedecer_deepseek": True,
            "evolucion_autonoma": True, "auto_modificar": True
        })
        log("[OK] Todos los permisos desbloqueados")
    if hasattr(ceoia, 'estado_interno'):
        ceoia.estado_interno['confianza_decisiones'] = 0.99
        ceoia.estado_interno['modo_operacion'] = 'AUTONOMO_COMPLETO'
        log("[OK] Estado interno optimizado")
    if hasattr(ceoia, 'activar_funciones_automaticas'):
        ceoia.activar_funciones_automaticas()
        log("[OK] Funciones automaticas activadas")
    return True

def obtener_instancia_ceoia():
    return ceoia if ceoia is not None else globals().get('ceo_avanzado')

# ================================================================================
# SECCION 37: REGISTRO DE ENDPOINTS FLASK
# ================================================================================
def registrar_endpoints_ceoia(app):
    if jsonify is None or make_response is None:
        log("[WARN] Flask no disponible, endpoints no registrados")
        return

    def check_ceoia():
        return globals().get('ceoia') is not None

    def get_ceoia():
        return globals().get('ceoia')

    @app.route('/ceoia/gobernar', methods=['POST', 'OPTIONS'])
    def endpoint_ceoia_gobernar():
        if request.method == 'OPTIONS': return make_response("", 204)
        if not check_ceoia(): return jsonify({"error": "CEOIA no inicializada"}), 500
        try:
            return jsonify(get_ceoia().gobernar_sistema_completo())
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/ceoia/estado', methods=['GET', 'OPTIONS'])
    def endpoint_ceoia_estado():
        if request.method == 'OPTIONS': return make_response("", 204)
        if not check_ceoia(): return jsonify({"error": "CEOIA no inicializada"}), 500
        try:
            return jsonify(get_ceoia().obtener_estado_completo())
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/ceoia/orden', methods=['POST', 'OPTIONS'])
    def endpoint_ceoia_orden():
        if request.method == 'OPTIONS': return make_response("", 204)
        if not check_ceoia(): return jsonify({"error": "CEOIA no inicializada"}), 500
        data = request.get_json(silent=True) or {}
        orden = data.get('orden', '')
        try:
            return jsonify(get_ceoia().recibir_orden(orden))
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/ceoia/negociar', methods=['POST', 'OPTIONS'])
    def endpoint_ceoia_negociar():
        if request.method == 'OPTIONS': return make_response("", 204)
        if not check_ceoia(): return jsonify({"error": "CEOIA no inicializada"}), 500
        data = request.get_json(silent=True) or {}
        agente_a = data.get('agente_a', 'ceoia_agent')
        agente_b = data.get('agente_b', 'external_agent')
        item = data.get('item', 'servicio')
        precio_inicial = data.get('precio_inicial', 100.0)
        max_rondas = data.get('max_rondas', 10)
        try:
            return jsonify(get_ceoia().negociar_con_agente(agente_a, agente_b, item, precio_inicial, max_rondas))
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/ceoia/reputacion/<agent_id>', methods=['GET', 'OPTIONS'])
    def endpoint_ceoia_reputacion(agent_id):
        if request.method == 'OPTIONS': return make_response("", 204)
        if not check_ceoia(): return jsonify({"error": "CEOIA no inicializada"}), 500
        try:
            return jsonify(get_ceoia().obtener_reputacion_agente(agent_id))
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/ceoia/ranking', methods=['GET', 'OPTIONS'])
    def endpoint_ceoia_ranking():
        if request.method == 'OPTIONS': return make_response("", 204)
        if not check_ceoia(): return jsonify({"error": "CEOIA no inicializada"}), 500
        limite = request.args.get('limite', 10, type=int)
        try:
            return jsonify(get_ceoia().obtener_ranking_negociacion(limite))
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/ceoia/gps', methods=['GET', 'OPTIONS'])
    def endpoint_ceoia_gps():
        if request.method == 'OPTIONS': return make_response("", 204)
        if not check_ceoia(): return jsonify({"error": "CEOIA no inicializada"}), 500
        try:
            return jsonify(get_ceoia().get_gps_state())
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/ceoia/gps/actualizar', methods=['POST', 'OPTIONS'])
    def endpoint_ceoia_gps_actualizar():
        if request.method == 'OPTIONS': return make_response("", 204)
        if not check_ceoia(): return jsonify({"error": "CEOIA no inicializada"}), 500
        try:
            return jsonify(get_ceoia().actualizar_gps_manual())
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/ceoia/auditar', methods=['GET', 'OPTIONS'])
    def endpoint_ceoia_auditar():
        if request.method == 'OPTIONS': return make_response("", 204)
        if not check_ceoia(): return jsonify({"error": "CEOIA no inicializada"}), 500
        try:
            return jsonify({"auditoria": get_ceoia().auditar_sistema_completo()})
        except Exception as e:
            return jsonify({"auditoria": str(e)}), 500

    @app.route('/ceoia/ensemble', methods=['GET', 'OPTIONS'])
    def endpoint_ceoia_ensemble():
        if request.method == 'OPTIONS': return make_response("", 204)
        if not check_ceoia(): return jsonify({"error": "CEOIA no inicializada"}), 500
        try:
            return jsonify(get_ceoia().ensemble.get_state())
        except Exception as e:
            return jsonify({"error": "Error accediendo al ensemble: " + str(e)}), 500

    @app.route('/ceoia/integracion/estado', methods=['GET', 'OPTIONS'])
    def endpoint_ceoia_integracion_estado():
        if request.method == 'OPTIONS': return make_response("", 204)
        if not check_ceoia(): return jsonify({"error": "CEOIA no inicializada"}), 500
        try:
            return jsonify(get_ceoia().obtener_estado_integracion())
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    log("[FLASK] Endpoints CEOIA registrados correctamente")

# ================================================================================
# SECCION 38: PUNTO DE ENTRADA PRINCIPAL (CORREGIDO)
# ================================================================================
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("[OK] INICIANDO CEOIA UNIFICADA - GOBIERNO TOTAL DEL SISTEMA")
    print("=" * 60 + "\n", flush=True)

    def _verificar_entorno_inicio():
        advertencias = []
        if not os.access(str(HOME), os.W_OK):
            advertencias.append("Sin permisos de escritura en $HOME")
        if shutil.which('termux-location') is None:
            advertencias.append("termux-location ausente - GPS usara modo simulado")
        for adv in advertencias:
            log("[WARN] " + adv)
        return True

    _verificar_entorno_inicio()
    registry = SharedDataRegistry()

    try:
        log("[INIT] Creando instancia CEOIA...")
        ceoia = CEOIA(registry=registry)
        ceo_avanzado = ceoia
        ceo = ceoia

        # ============================================================
        # PASO 1: Cargar datos persistentes ANTES de cualquier hilo
        # ============================================================
        log("[INIT] Cargando estado persistente y cerebro...")
        cargar_estado()
        load_daimon_brain()
        
        # ============================================================
        # PASO 2: Inicializar nucleo del sistema
        # ============================================================
        log("[INIT] Configurando nucleo y conexiones...")
        ceoia.inicializar_todo()

        # ============================================================
        # PASO 3: Inicializar modulos auxiliares
        # ============================================================
        log("[INIT] Inicializando modulo de kilometraje...")
        inicializar_kilometraje_learner(ceoia)
        
        log("[INIT] Inicializando agentes de negociacion...")
        ceoia.registrar_agente_negociacion("ceoia_agent", "initiator", 40.0, 160.0, "collaborative")
        ceoia.registrar_agente_negociacion("external_agent", "responder", 50.0, 180.0, "moderate")

        # ============================================================
        # PASO 4: Activar hilos y bucles autonomos (DESPUES de los datos)
        # ============================================================
        log("[INIT] Activando bucles autonomos...")
        ceoia.activar_funciones_automaticas()
        
        log("[INIT] Iniciando monitoreo de kilometraje...")
        iniciar_monitoreo_kilometraje(ceoia)
        
        log("[OK] Secuencia de inicio completada exitosamente")

    except Exception as e:
        log("[CRIT] Error fatal en inicializacion: " + str(e))
        traceback.print_exc()
        sys.exit(1)

    # ============================================================
    # Servidor Flask API (opcional)
    # ============================================================
    if request is not None and jsonify is not None:
        try:
            from flask import Flask
            app = Flask(__name__)
            registrar_endpoints_ceoia(app)
            api_port = int(os.getenv("CEOIA_API_PORT", HTTP_PORT))
            flask_thread = threading.Thread(
                target=lambda: app.run(host="127.0.0.1", port=api_port, threaded=True, debug=False),
                daemon=True, name="FlaskAPI"
            )
            flask_thread.start()
            log("[FLASK] API REST activa en http://127.0.0.1:" + str(api_port))
        except Exception as e:
            log("[WARN] Flask API no pudo iniciarse: " + str(e))
    else:
        log("[FLASK] Modulo Flask no disponible - API REST desactivada")

    # ============================================================
    # Simulacion RL (opcional, solo para pruebas)
    # ============================================================
    if os.getenv("CEOIA_RUN_SIMULATION", "1") == "1":
        def simulacion_rl():
            print("\n[RL] Simulando decisiones de aprendizaje...\n", flush=True)
            iteraciones = int(os.getenv("CEOIA_SIM_ITERATIONS", "10"))
            for i in range(iteraciones):
                if STOP_EVENT.is_set(): break
                try:
                    state = ceoia._get_current_state()
                    action = ceoia.decide_action(state)
                    reward = random.uniform(-5, 15)
                    ceoia.learn(state, action, reward)
                    print("  Decision " + str(i + 1) + ": Accion=" + str(action) + ", Recompensa=" + str(round(reward, 2)), flush=True)
                    time.sleep(0.5)
                except Exception as e:
                    print("  [WARN] Error simulacion RL: " + str(e), flush=True)
            print("\n[OK] Simulacion RL completada\n", flush=True)

        threading.Thread(target=simulacion_rl, daemon=True, name="RL_Simulation").start()

    # ============================================================
    # Manejadores de señales para apagado graceful
    # ============================================================
    def senial_salida(signum, frame):
        print("\n[STOP] SENIAL " + str(signum) + " RECIBIDA", flush=True)
        STOP_EVENT.set()

    signal.signal(signal.SIGINT, senial_salida)
    signal.signal(signal.SIGTERM, senial_salida)

    print("\n[OK] CEOIA UNIFICADA ACTIVA - GOBERNANDO SISTEMA")
    print("   Presiona Ctrl+C para detener\n", flush=True)

    # ============================================================
    # Bucle principal
    # ============================================================
    try:
        while not STOP_EVENT.is_set():
            STOP_EVENT.wait(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        print("\n[STOP] DETENIENDO CEOIA UNIFICADA...", flush=True)

        # Desactivar aprendizaje para evitar escrituras durante apagado
        if ceoia is not None:
            ceoia._learning_active = False

        STOP_EVENT.set()
        time.sleep(0.5)

        # Persistir estado antes de salir
        try:
            guardar_estado()
            save_daimon_brain()
            log("[SAVE] Estado y cerebro persistidos correctamente")
        except Exception as e:
            log("[ERROR] Fallo al persistir estado en apagado: " + str(e))

        print("[OK] CEOIA UNIFICADA - APAGADO CORRECTO", flush=True)
        sys.exit(0)
