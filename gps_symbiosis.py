#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gps_symbiosis.py - Módulo monolítico de inteligencia autónoma con GPS como núcleo.
Incluye: GPS real/simulado, enrutamiento, matching, aprendizaje por refuerzo (RL),
lógica difusa, filtro de Kalman, meta‑aprendizaje, curiosidad, monitor de red,
persistencia y pruebas integradas. Compatible con Windows, Linux, Android/Termux,
Raspberry Pi. No requiere numpy ni requests, pero los aprovecha si están instalados.
"""

import os
import sys
import json
import time
import uuid
import math
import random
import heapq
import threading
import copy
import traceback
import pickle
import atexit
import logging
from collections import deque, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum, auto
from typing import Dict, List, Optional, Tuple, Any, Callable, Set, Union
from pathlib import Path
from fnmatch import fnmatch
from functools import lru_cache

# ============================================================================
# CONFIGURACIÓN DE LOGGING
# ============================================================================
LOG_LEVEL = logging.INFO if not os.getenv('DEBUG') else logging.DEBUG
logging.basicConfig(
    level=LOG_LEVEL,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger(__name__)

# ============================================================================
# INTENTAR IMPORTAR DEPENDENCIAS OPCIONALES
# ============================================================================
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    np = None

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

IS_TERMUX = os.getenv('TERMUX_VERSION') is not None or 'com.termux' in os.getenv('PATH', '')
DEBUG = False

# ============================================================================
# 1. REGISTRO COMPARTIDO DE DATOS (Singleton Thread‑safe)
# ============================================================================
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
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            self._data: Dict[str, Any] = {}
            self._callbacks: Dict[str, List[Tuple[str, Callable]]] = defaultdict(list)
            self._initialized = True
    def set(self, key: str, value: Any, notify: bool = True) -> bool:
        with self._lock:
            try:
                self._data[key] = copy.deepcopy(value)
                if notify:
                    self._trigger_callbacks(key, value)
                return True
            except Exception:
                return False
    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return copy.deepcopy(self._data.get(key, default))
    def on_change(self, key_pattern: str, callback: Callable) -> str:
        with self._lock:
            cid = str(hash(callback))[:8]
            self._callbacks[key_pattern].append((cid, callback))
            return cid
    def _trigger_callbacks(self, key: str, value: Any):
        for pattern, cbs in self._callbacks.items():
            if fnmatch(key, pattern):
                for _, cb in cbs:
                    try:
                        cb(key, value)
                    except Exception:
                        pass

# ============================================================================
# SECCION 2: COORDENADAS Y UTILIDADES GEOGRAFICAS
# ============================================================================

@dataclass
class Coordinate:
    latitude: float
    longitude: float
    altitude: float = 0.0
    accuracy: float = 0.0
    timestamp: Optional[datetime] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)

    def distance_to(self, other: 'Coordinate') -> float:
        R = 6371.0
        lat1, lon1 = math.radians(self.latitude), math.radians(self.longitude)
        lat2, lon2 = math.radians(other.latitude), math.radians(other.longitude)
        dlat, dlon = lat2 - lat1, lon2 - lon1
        a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

    def bearing_to(self, other: 'Coordinate') -> float:
        """
        Calcula el rumbo (bearing) desde esta coordenada hacia otra.
        Retorna grados (0-360), donde:
        0   = Norte
        90  = Este
        180 = Sur
        270 = Oeste
        """
        lat1 = math.radians(self.latitude)
        lon1 = math.radians(self.longitude)
        lat2 = math.radians(other.latitude)
        lon2 = math.radians(other.longitude)
        
        dlon = lon2 - lon1
        
        x = math.sin(dlon) * math.cos(lat2)
        y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
        
        bearing = math.degrees(math.atan2(x, y))
        return (bearing + 360) % 360

    def to_dict(self) -> Dict[str, float]:
        return {"lat": self.latitude, "lon": self.longitude, "alt": self.altitude}

    @classmethod
    def from_dict(cls, d: Dict[str, float]) -> 'Coordinate':
        return cls(d.get("lat",0), d.get("lon",0), d.get("alt",0))

# Funcion auxiliar (sin cambiar)
def haversine(lat1, lon1, lat2, lon2) -> float:
    return Coordinate(lat1, lon1).distance_to(Coordinate(lat2, lon2))

# ============================================================================
# 3. PROVEEDORES DE GPS (real / simulado)
# ============================================================================
class GPSProvider:
    def get_location(self) -> Optional[Coordinate]:
        raise NotImplementedError
    def get_speed_kmh(self) -> float:
        return 0.0

class SimulatedGPS(GPSProvider):
    def __init__(self, initial: Optional[Coordinate] = None, radius_km: float = 10.0, seed: int = None):
        if seed is not None:
            random.seed(seed)
        self.current = initial or Coordinate(0.0, 0.0)
        self.radius = radius_km
        self.last_update = time.time()
        self._speed = 0.0

    def get_location(self) -> Coordinate:
        now = time.time()
        dt = min(1.0, now - self.last_update)
        self.last_update = now
        angle = random.uniform(0, 2*math.pi)
        dist = random.uniform(0, self.radius * dt)
        new_lat = self.current.latitude + (dist * math.cos(angle)) / 111.0
        new_lon = self.current.longitude + (dist * math.sin(angle)) / (111.0 * math.cos(math.radians(self.current.latitude)))
        self.current = Coordinate(new_lat, new_lon, self.current.altitude)
        self._speed = dist / dt if dt > 0 else 0.0
        return self.current

    def get_speed_kmh(self) -> float:
        return self._speed * 3600.0

class TermuxGPS(GPSProvider):
    def __init__(self):
        self._available = self._check_termux()
        self.last_location: Optional[Coordinate] = None
        self.history = deque(maxlen=100)

    def _check_termux(self) -> bool:
        if not IS_TERMUX:
            return False
        try:
            import subprocess
            r = subprocess.run(['which', 'termux-location'], capture_output=True, timeout=2)
            return r.returncode == 0
        except Exception:
            return False

    def get_location(self) -> Optional[Coordinate]:
        if not self._available:
            return None
        try:
            import subprocess, json
            result = subprocess.run(['termux-location', '-p', 'gps'], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                lat, lon = data.get('latitude'), data.get('longitude')
                if lat is not None and lon is not None:
                    coord = Coordinate(float(lat), float(lon))
                    self.last_location = coord
                    self.history.append(coord)
                    return coord
        except Exception:
            pass
        return None

    def get_speed_kmh(self) -> float:
        if len(self.history) < 2:
            return 0.0
        d = self.history[-1].distance_to(self.history[-2])
        dt = 5.0
        return (d / dt) * 3600.0 if dt>0 else 0.0

def create_gps_provider(use_real: bool = False, fallback_to_sim: bool = True) -> GPSProvider:
    if use_real:
        real = TermuxGPS()
        if real.get_location() is not None:
            return real
        if not fallback_to_sim:
            raise RuntimeError("No se pudo obtener GPS real")
    return SimulatedGPS()

# ============================================================================
# 4. GEOCERCAS (Zonas de interés) con persistencia
# ============================================================================
class Geofence:
    def __init__(self, fence_id: str, center: Coordinate, radius_km: float):
        self.id = fence_id
        self.center = center
        self.radius = radius_km
        self.created_at = datetime.now(timezone.utc)
        self.last_triggered: Optional[datetime] = None
        self.trigger_count = 0
        self.metadata: Dict[str, Any] = {}
    
    def contains(self, coord: Coordinate) -> bool:
        """Verifica si una coordenada está dentro de la geocerca"""
        return coord.distance_to(self.center) <= self.radius
    
    def get_area_km2(self) -> float:
        """Calcula el área de la geocerca en km²"""
        return math.pi * (self.radius ** 2)
    
    def get_perimeter_km(self) -> float:
        """Calcula el perímetro de la geocerca en km"""
        return 2 * math.pi * self.radius
    
    def set_metadata(self, key: str, value: Any):
        """Establece metadatos personalizados"""
        self.metadata[key] = value
    
    def get_metadata(self, key: str, default: Any = None) -> Any:
        """Obtiene metadatos personalizados"""
        return self.metadata.get(key, default)
    
    def to_dict(self) -> dict:
        """Convierte la geocerca a diccionario para serialización"""
        return {
            "id": self.id,
            "center": self.center.to_dict(),
            "radius_km": self.radius,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Geofence':
        """Crea una geocerca desde un diccionario"""
        fence = cls(
            data["id"],
            Coordinate.from_dict(data["center"]),
            data["radius_km"]
        )
        if "created_at" in data:
            try:
                fence.created_at = datetime.fromisoformat(data["created_at"])
            except (ValueError, TypeError):
                pass
        if "metadata" in data:
            fence.metadata = data["metadata"]
        return fence
    
    def __repr__(self) -> str:
        return f"Geofence(id='{self.id}', center=({self.center.latitude:.4f}, {self.center.longitude:.4f}), radius={self.radius}km)"

class GeofenceManager:
    def __init__(self):
        self.fences: Dict[str, Geofence] = {}
        self._listeners: Dict[str, List[Callable[[str, bool], None]]] = {}
        self._enter_exit_listeners: Dict[str, List[Callable[[str, bool], None]]] = {}
        self._previous_states: Dict[str, bool] = {}
        self._lock = threading.RLock()
    
    def add(self, fence: Geofence):
        """Agrega una geocerca al manager"""
        with self._lock:
            self.fences[fence.id] = fence
            self._listeners.setdefault(fence.id, [])
            self._enter_exit_listeners.setdefault(fence.id, [])
            self._previous_states[fence.id] = False
    
    def remove(self, fence_id: str):
        """Elimina una geocerca del manager"""
        with self._lock:
            self.fences.pop(fence_id, None)
            self._listeners.pop(fence_id, None)
            self._enter_exit_listeners.pop(fence_id, None)
            self._previous_states.pop(fence_id, None)
    
    def get(self, fence_id: str) -> Optional[Geofence]:
        """Obtiene una geocerca por ID"""
        return self.fences.get(fence_id)
    
    def get_all(self) -> List[Geofence]:
        """Obtiene todas las geocercas"""
        return list(self.fences.values())
    
    def get_active_fences(self, coord: Coordinate) -> List[Geofence]:
        """Obtiene todas las geocercas que contienen una coordenada"""
        return [f for f in self.fences.values() if f.contains(coord)]
    
    def on_change(self, fence_id: str, callback: Callable[[str, bool], None]):
        """Registra callback para cualquier cambio de estado (entrada o salida)"""
        self._listeners.setdefault(fence_id, []).append(callback)
    
    def on_enter_exit(self, fence_id: str, callback: Callable[[str, bool], None]):
        """
        Registra callback específico para eventos de entrada/salida.
        El callback recibe (fence_id, is_inside).
        Se dispara solo cuando hay un cambio de estado.
        """
        self._enter_exit_listeners.setdefault(fence_id, []).append(callback)
    
    def on_enter(self, fence_id: str, callback: Callable[[str], None]):
        """Registra callback para cuando se entra a una geocerca"""
        def wrapper(fid: str, inside: bool):
            if inside:
                callback(fid)
        self._enter_exit_listeners.setdefault(fence_id, []).append(wrapper)
    
    def on_exit(self, fence_id: str, callback: Callable[[str], None]):
        """Registra callback para cuando se sale de una geocerca"""
        def wrapper(fid: str, inside: bool):
            if not inside:
                callback(fid)
        self._enter_exit_listeners.setdefault(fence_id, []).append(wrapper)
    
    def update(self, coord: Coordinate) -> Dict[str, bool]:
        """
        Actualiza el estado de todas las geocercas con una coordenada.
        Retorna un diccionario con el estado de cada geocerca.
        """
        states = {}
        with self._lock:
            for fid, fence in self.fences.items():
                inside = fence.contains(coord)
                states[fid] = inside
                
                # Actualizar contador si está dentro
                if inside:
                    fence.trigger_count += 1
                    fence.last_triggered = datetime.now(timezone.utc)
                
                # Notificar cambio de estado (entrada/salida)
                prev_state = self._previous_states.get(fid, False)
                if inside != prev_state:
                    for cb in self._enter_exit_listeners.get(fid, []):
                        try:
                            cb(fid, inside)
                        except Exception as e:
                            log.debug(f"Error en callback enter/exit de geocerca {fid}: {e}")
                
                # Notificar cualquier cambio
                for cb in self._listeners.get(fid, []):
                    try:
                        cb(fid, inside)
                    except Exception as e:
                        log.debug(f"Error en callback de geocerca {fid}: {e}")
                
                self._previous_states[fid] = inside
        
        return states
    
    def get_state(self, fence_id: str) -> Optional[bool]:
        """Obtiene el último estado conocido de una geocerca"""
        return self._previous_states.get(fence_id)
    
    def get_statistics(self) -> Dict[str, Any]:
        """Obtiene estadísticas de todas las geocercas"""
        stats = {
            'total_fences': len(self.fences),
            'active_listeners': sum(len(v) for v in self._listeners.values()),
            'fences': {}
        }
        for fid, fence in self.fences.items():
            stats['fences'][fid] = {
                'radius_km': fence.radius,
                'area_km2': fence.get_area_km2(),
                'trigger_count': fence.trigger_count,
                'last_triggered': fence.last_triggered.isoformat() if fence.last_triggered else None,
                'currently_inside': self._previous_states.get(fid, False)
            }
        return stats
    
    def save(self, path: str):
        """Guarda todas las geocercas a un archivo JSON"""
        try:
            data = [f.to_dict() for f in self.fences.values()]
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
            log.info(f"Geocercas guardadas en {path}: {len(data)} geocercas")
        except Exception as e:
            log.error(f"Error guardando geocercas: {e}")
    
    def load(self, path: str):
        """Carga geocercas desde un archivo JSON"""
        if not os.path.exists(path):
            log.info(f"Archivo de geocercas no encontrado: {path}")
            return
        try:
            with open(path, 'r') as f:
                data = json.load(f)
            count = 0
            for item in data:
                fence = Geofence.from_dict(item)
                self.add(fence)
                count += 1
            log.info(f"Geocercas cargadas desde {path}: {count} geocercas")
        except json.JSONDecodeError as e:
            log.error(f"Error decodificando JSON de geocercas: {e}")
        except Exception as e:
            log.error(f"Error cargando geocercas: {e}")
    
    def clear(self):
        """Elimina todas las geocercas y listeners"""
        with self._lock:
            self.fences.clear()
            self._listeners.clear()
            self._enter_exit_listeners.clear()
            self._previous_states.clear()
    
    def __len__(self) -> int:
        return len(self.fences)
    
    def __contains__(self, fence_id: str) -> bool:
        return fence_id in self.fences
    
    def __repr__(self) -> str:
        return f"GeofenceManager(fences={len(self.fences)}, listeners={sum(len(v) for v in self._listeners.values())})"

# ============================================================================
# 5. NÚCLEO GPS (Singleton con hilo de actualización y filtro Kalman)
# ============================================================================

class GPSCore:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, provider: Optional[GPSProvider] = None, use_kalman: bool = True):
        if self._initialized:
            return

        with self._lock:
            if self._initialized:
                return

            self.provider = provider or create_gps_provider(
                use_real=False,
                fallback_to_sim=True
            )

            self.geofence = GeofenceManager()

            self.use_kalman = use_kalman

            if use_kalman:
                self.kalman = KalmanFilter(
                    state_dim=2,
                    obs_dim=2
                )
            else:
                self.kalman = None

            self._last_coord: Optional[Coordinate] = None

            self._running = False
            self._stop_event = threading.Event()
            self._thread: Optional[threading.Thread] = None

            self._interval = 1.0

            self._listeners: List[Callable[[Coordinate], None]] = []

            self._initialized = True

            atexit.register(self.stop)

    # ----------------------------------------------------------------------
    # Iniciar núcleo GPS
    # ----------------------------------------------------------------------
    def start(self, interval_seconds: float = 1.0):

        if self._running:
            return

        self._interval = interval_seconds

        self._running = True

        self._stop_event.clear()

        self._thread = threading.Thread(
            target=self._update_loop,
            daemon=True
        )

        self._thread.start()

    # ----------------------------------------------------------------------
    # Detener núcleo GPS
    # ----------------------------------------------------------------------
    def stop(self):

        self._running = False

        self._stop_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    # ----------------------------------------------------------------------
    # Loop de actualización
    # ----------------------------------------------------------------------
    def _update_loop(self):

        while not self._stop_event.is_set():

            coord = self.provider.get_location()

            if coord is not None:

                if self.use_kalman and self.kalman:

                    self.kalman.predict()

                    self.kalman.update([
                        coord.latitude,
                        coord.longitude
                    ])

                    filtered = self.kalman.get_state()

                    coord = Coordinate(
                        filtered[0],
                        filtered[1],
                        coord.altitude,
                        coord.accuracy
                    )

                self._last_coord = coord

                self.geofence.update(coord)

                for cb in self._listeners:
                    try:
                        cb(coord)
                    except Exception:
                        pass

            time.sleep(self._interval)

    # ----------------------------------------------------------------------
    # Obtener ubicación
    # ----------------------------------------------------------------------
    def get_location(self) -> Optional[Coordinate]:
        return self._last_coord

    # ----------------------------------------------------------------------
    # Obtener velocidad
    # ----------------------------------------------------------------------
    def get_speed(self) -> float:
        return self.provider.get_speed_kmh()

    # ----------------------------------------------------------------------
    # Registrar listener
    # ----------------------------------------------------------------------
    def on_location_change(self, callback: Callable[[Coordinate], None]):
        self._listeners.append(callback)

    # ----------------------------------------------------------------------
    # Agregar geofence
    # ----------------------------------------------------------------------
    def add_geofence(self, fence: Geofence):
        self.geofence.add(fence)

    # ----------------------------------------------------------------------
    # Distancia a objetivo
    # ----------------------------------------------------------------------
    def distance_to(self, target: Coordinate) -> float:

        loc = self.get_location()

        if loc is None:
            return float('inf')

        return loc.distance_to(target)

    # ----------------------------------------------------------------------
    # Bearing / rumbo hacia otra coordenada
    # ----------------------------------------------------------------------
    def bearing_to(self, other: 'Coordinate') -> float:
        """
        Calcula el rumbo (bearing) desde esta coordenada hacia otra.

        Retorna:
            0   = Norte
            90  = Este
            180 = Sur
            270 = Oeste
        """

        loc = self.get_location()

        if loc is None:
            return 0.0

        lat1 = math.radians(loc.latitude)
        lon1 = math.radians(loc.longitude)

        lat2 = math.radians(other.latitude)
        lon2 = math.radians(other.longitude)

        dlon = lon2 - lon1

        x = math.sin(dlon) * math.cos(lat2)

        y = (
            math.cos(lat1) * math.sin(lat2)
            - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
        )

        bearing = math.degrees(math.atan2(x, y))

        return (bearing + 360) % 360

# ============================================================================
# 6. ENRUTAMIENTO (Grafos, Dijkstra, A*, caché LRU)
# ============================================================================
@dataclass
class Node:
    id: str
    lat: float
    lon: float
    name: str = ""

@dataclass
class Edge:
    id: str
    from_node: str
    to_node: str
    distance_km: float
    base_time_min: float
    road_type: str = "local"
    toll_cost: float = 0.0
    traffic_multiplier: float = 1.0

class RouteGraph:
    def __init__(self):
        self.nodes: Dict[str, Node] = {}
        self.edges: Dict[str, Edge] = {}
        self.adj: Dict[str, List[str]] = defaultdict(list)
        self.cache_hits = 0
        self.cache_misses = 0
    def add_node(self, node: Node):
        self.nodes[node.id] = node
    def add_edge(self, edge: Edge, bidirectional: bool = True):
        self.edges[edge.id] = edge
        self.adj[edge.from_node].append(edge.id)
        if bidirectional:
            rev_id = f"{edge.id}_rev"
            rev = Edge(rev_id, edge.to_node, edge.from_node,
                       edge.distance_km, edge.base_time_min,
                       edge.road_type, edge.toll_cost, edge.traffic_multiplier)
            self.edges[rev_id] = rev
            self.adj[edge.to_node].append(rev_id)
    def get_edges_from(self, node_id: str) -> List[Edge]:
        return [self.edges[eid] for eid in self.adj.get(node_id, []) if eid in self.edges]

class RoutingEngine:
    def __init__(self, graph: RouteGraph, traffic_enabled: bool = False):
        self.graph = graph
        self.traffic_enabled = traffic_enabled
        self.cache_hits = 0
        self.cache_misses = 0
    def _edge_cost(self, edge: Edge, objective: str = "time") -> float:
        mult = edge.traffic_multiplier if self.traffic_enabled else 1.0
        if objective == "time":
            return edge.base_time_min * mult
        else:
            return edge.distance_km
    @lru_cache(maxsize=1024)
    def _cached_shortest_path(self, from_id: str, to_id: str, objective: str, algorithm: str):
        # Este método interno es cacheado; los argumentos deben ser hashables (str)
        if algorithm == "dijkstra":
            return self._dijkstra(from_id, to_id, objective)
        else:
            return self._a_star(from_id, to_id, objective)
    def shortest_path(self, from_id: str, to_id: str, objective: str = "time",
                     algorithm: str = "a_star", use_cache: bool = True) -> Tuple[List[str], List[str], float]:
        if not use_cache:
            if algorithm == "dijkstra":
                return self._dijkstra(from_id, to_id, objective)
            else:
                return self._a_star(from_id, to_id, objective)
        # Con caché
        nodes, edges, cost = self._cached_shortest_path(from_id, to_id, objective, algorithm)
        # Actualizar estadísticas
        if cost < float('inf'):
            self.cache_hits = self._cached_shortest_path.cache_info().hits
            self.cache_misses = self._cached_shortest_path.cache_info().misses
        return list(nodes), list(edges), cost
    def _dijkstra(self, src, dst, objective):
        if src not in self.graph.nodes or dst not in self.graph.nodes:
            return [], [], float('inf')
        dist = {src: 0.0}
        prev_node = {}
        prev_edge = {}
        pq = [(0.0, src)]
        visited = set()
        while pq:
            d,u = heapq.heappop(pq)
            if u in visited:
                continue
            visited.add(u)
            if u == dst:
                break
            for e in self.graph.get_edges_from(u):
                v = e.to_node
                w = self._edge_cost(e, objective)
                nd = d + w
                if v not in dist or nd < dist[v]:
                    dist[v] = nd
                    prev_node[v] = u
                    prev_edge[v] = e.id
                    heapq.heappush(pq, (nd, v))
        if dst not in prev_node and src != dst:
            return [], [], float('inf')
        path_nodes, path_edges = [], []
        cur = dst
        while cur != src:
            path_nodes.append(cur)
            eid = prev_edge.get(cur)
            if eid is None:
                break
            path_edges.append(eid)
            cur = prev_node.get(cur)
            if cur is None:
                break
        path_nodes.append(src)
        path_nodes.reverse()
        path_edges.reverse()
        return tuple(path_nodes), tuple(path_edges), dist.get(dst, float('inf'))
    def _heuristic(self, node_id, target_lat, target_lon):
        n = self.graph.nodes.get(node_id)
        if not n:
            return 0.0
        return haversine(n.lat, n.lon, target_lat, target_lon)
    def _a_star(self, src, dst, objective):
        if src not in self.graph.nodes or dst not in self.graph.nodes:
            return [], [], float('inf')
        target = self.graph.nodes[dst]
        open_set = [(0.0, src)]
        g_score = {src: 0.0}
        f_score = {src: self._heuristic(src, target.lat, target.lon)}
        came_from = {}
        visited = set()
        while open_set:
            _, cur = heapq.heappop(open_set)
            if cur == dst:
                break
            if cur in visited:
                continue
            visited.add(cur)
            for e in self.graph.get_edges_from(cur):
                nxt = e.to_node
                if nxt in visited:
                    continue
                tentative_g = g_score[cur] + self._edge_cost(e, objective)
                if nxt not in g_score or tentative_g < g_score[nxt]:
                    came_from[nxt] = (cur, e.id)
                    g_score[nxt] = tentative_g
                    f = tentative_g + self._heuristic(nxt, target.lat, target.lon)
                    f_score[nxt] = f
                    heapq.heappush(open_set, (f, nxt))
        if dst not in came_from and src != dst:
            return [], [], float('inf')
        path_nodes, path_edges = [], []
        cur = dst
        while cur != src:
            path_nodes.append(cur)
            _, eid = came_from.get(cur, (None,None))
            if eid is None:
                break
            path_edges.append(eid)
            cur, _ = came_from.get(cur, (None,None))
            if cur is None:
                break
        path_nodes.append(src)
        path_nodes.reverse()
        path_edges.reverse()
        return tuple(path_nodes), tuple(path_edges), g_score.get(dst, float('inf'))

# ============================================================================
# 7. MÓDULO DE MATCHING (Hungarian, Gale‑Shapley, Top‑K, GeoMatcher)
# ============================================================================
class SimilarityMetrics:
    @staticmethod
    def cosine(vec_a, vec_b):
        if not vec_a or not vec_b or len(vec_a)!=len(vec_b):
            return 0.0
        dot = sum(a*b for a,b in zip(vec_a,vec_b))
        na = math.sqrt(sum(a*a for a in vec_a))
        nb = math.sqrt(sum(b*b for b in vec_b))
        if na==0 or nb==0: return 0.0
        return (dot/(na*nb)+1)/2
    @staticmethod
    def euclidean(vec_a, vec_b):
        if not vec_a or not vec_b: return 1.0
        d = math.sqrt(sum((a-b)**2 for a,b in zip(vec_a,vec_b)))
        maxd = math.sqrt(len(vec_a))
        return min(1.0, d/maxd) if maxd>0 else 0.0
    @staticmethod
    def jaccard(set_a, set_b):
        if not set_a and not set_b: return 1.0
        inter = len(set_a & set_b)
        union = len(set_a | set_b)
        return inter/union if union>0 else 0.0
    @staticmethod
    def weighted(feats_a, feats_b, weights):
        total_w = 0.0
        wsum = 0.0
        for f,w in weights.items():
            if f in feats_a and f in feats_b:
                diff = abs(feats_a[f] - feats_b[f])
                sim = 1.0 - min(1.0, diff)
                wsum += w * sim
                total_w += w
        return wsum/total_w if total_w>0 else 0.0
    @staticmethod
    def geographic(coord_a, coord_b, max_km=100.0):
        if coord_a is None or coord_b is None:
            return 0.5
        dist = haversine(coord_a[0], coord_a[1], coord_b[0], coord_b[1])
        return max(0.0, 1.0 - (dist/max_km))

class TopKCandidates:
    def __init__(self, k=10):
        self.k = k
    def find(self, query: Dict[str,float], candidates: List[Tuple[str,Dict[str,float]]],
             weights: Optional[Dict[str,float]]=None) -> List[Tuple[str,float]]:
        if weights is None:
            weights = {k:1.0 for k in query}
        heap = []
        for cid, feats in candidates:
            score = self._score(query, feats, weights)
            if len(heap) < self.k:
                heapq.heappush(heap, (-score, cid))
            elif score > -heap[0][0]:
                heapq.heappushpop(heap, (-score, cid))
        res = [(cid, -s) for s,cid in heap]
        res.sort(key=lambda x: x[1], reverse=True)
        return res
    def _score(self, q, f, w):
        total = 0.0
        wsum = 0.0
        for key, qv in q.items():
            if key in f:
                weight = w.get(key,1.0)
                sim = 1.0 - min(1.0, abs(qv - f[key]))
                total += weight * sim
                wsum += weight
        return total/wsum if wsum>0 else 0.0

class HungarianAlgorithm:
    def solve(self, similarity_matrix, maximize=True):
        if not similarity_matrix or not similarity_matrix[0]:
            return [], 0.0
        n,m = len(similarity_matrix), len(similarity_matrix[0])
        if maximize:
            max_val = max(max(row) for row in similarity_matrix)
            cost = [[max_val - v for v in row] for row in similarity_matrix]
        else:
            cost = [row[:] for row in similarity_matrix]
        size = max(n,m)
        for i in range(size):
            if i < len(cost):
                while len(cost[i]) < size:
                    cost[i].append(float('inf'))
            else:
                cost.append([float('inf')]*size)
        u = [0.0]*(size+1)
        v = [0.0]*(size+1)
        p = [0]*(size+1)
        way = [0]*(size+1)
        for i in range(1, size+1):
            p[0] = i
            j0 = 0
            minv = [float('inf')]*(size+1)
            used = [False]*(size+1)
            while True:
                used[j0] = True
                i0 = p[j0]
                delta = float('inf')
                j1 = 0
                for j in range(1, size+1):
                    if not used[j]:
                        cur = cost[i0-1][j-1] - u[i0] - v[j]
                        if cur < minv[j]:
                            minv[j] = cur
                            way[j] = j0
                        if minv[j] < delta:
                            delta = minv[j]
                            j1 = j
                for j in range(size+1):
                    if used[j]:
                        u[p[j]] += delta
                        v[j] -= delta
                    else:
                        minv[j] -= delta
                j0 = j1
                if p[j0] == 0:
                    break
            while True:
                j1 = way[j0]
                p[j0] = p[j1]
                j0 = j1
                if j0 == 0:
                    break
        assignment = [p[j]-1 for j in range(1, size+1)]
        matches = [(i, assignment[i]) for i in range(n) if assignment[i] < m]
        total = sum(similarity_matrix[i][j] for i,j in matches)
        return matches, total if maximize else -total

class GaleShapley:
    def solve(self, men, women, men_prefs, women_prefs):
        women_rank = {w: {m: r for r,m in enumerate(prefs)} for w,prefs in women_prefs.items()}
        engaged_w = {w: None for w in women}
        engaged_m = {m: None for m in men}
        free_men = deque(men)
        next_prop = {m:0 for m in men}
        while free_men:
            m = free_men.popleft()
            if next_prop[m] >= len(men_prefs[m]):
                continue
            w = men_prefs[m][next_prop[m]]
            next_prop[m] += 1
            if engaged_w[w] is None:
                engaged_w[w] = m
                engaged_m[m] = w
            else:
                cur = engaged_w[w]
                if women_rank[w][m] < women_rank[w][cur]:
                    engaged_w[w] = m
                    engaged_m[m] = w
                    engaged_m[cur] = None
                    free_men.append(cur)
                else:
                    free_men.append(m)
        return {m:w for m,w in engaged_m.items() if w is not None}

class GeoMatcher:
    def __init__(self, cell_size_km=10.0):
        self.cell_deg = cell_size_km / 111.0
    def _cell(self, lat, lon):
        return (int(lat/self.cell_deg), int(lon/self.cell_deg))
    def cluster(self, agents: List[Tuple[str,float,float]]) -> Dict[Tuple[int,int], List[str]]:
        clusters = defaultdict(list)
        for aid, lat, lon in agents:
            clusters[self._cell(lat,lon)].append(aid)
        return clusters
    def nearby(self, lat, lon, all_agents: Dict[str,Tuple[float,float]], radius_km=20.0):
        res = []
        for aid, (alat, alon) in all_agents.items():
            d = haversine(lat, lon, alat, alon)
            if d <= radius_km:
                res.append((aid, d))
        res.sort(key=lambda x: x[1])
        return res

class MatchingEngine:
    def __init__(self):
        self.hungarian = HungarianAlgorithm()
        self.gale = GaleShapley()
        self.topk = TopKCandidates()
        self.geo = GeoMatcher()
        self.agent_features: Dict[str, Dict[str,float]] = {}
    def compute_similarity(self, agent_a, agent_b, weights=None):
        if weights is None:
            weights = {"pref":0.4, "rating":0.3, "loc":0.3}
        breakdown = {}
        if agent_a.get("preferences") and agent_b.get("preferences"):
            breakdown["pref"] = SimilarityMetrics.weighted(
                agent_a["preferences"], agent_b["preferences"],
                {k:1.0 for k in agent_a["preferences"]}
            )
        breakdown["rating"] = 1.0 - abs(agent_a.get("rating",0.5)-agent_b.get("rating",0.5))
        if agent_a.get("location") and agent_b.get("location"):
            breakdown["loc"] = SimilarityMetrics.geographic(
                agent_a["location"], agent_b["location"], max_km=50.0
            )
        total = sum(weights.get(k,0)*v for k,v in breakdown.items())
        return total, breakdown
    def update_features(self, agent_id, features):
        self.agent_features[agent_id] = features
    def get_recommendations(self, agent_id, top_k=5):
        if agent_id not in self.agent_features:
            return []
        query = self.agent_features[agent_id]
        candidates = [(aid, f) for aid,f in self.agent_features.items() if aid != agent_id]
        return self.topk.find(query, candidates)

# ============================================================================
# 8. MONITOR DE RED (sin dependencias externas)
# ============================================================================
class NetworkMonitor:
    def __init__(self):
        self.registry = SharedDataRegistry()
        self._running = False
        self._thread = None
        self._stop_event = threading.Event()
        self.servers = ["8.8.8.8", "1.1.1.1", "google.com"]
        self.status = {"connected": False, "latency_ms": None, "last_check": None}
    def start(self, interval=5.0):
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, args=(interval,))
        self._thread.start()
    def stop(self):
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
    def _loop(self, interval):
        while not self._stop_event.is_set():
            self._check()
            time.sleep(interval)
    def _check(self):
        best = None
        best_lat = float('inf')
        for server in self.servers:
            lat = self._ping(server)
            if lat is not None and lat < best_lat:
                best_lat = lat
                best = server
        if best:
            self.status = {"connected": True, "latency_ms": best_lat, "server": best, "last_check": time.time()}
        else:
            self.status = {"connected": False, "latency_ms": None, "last_check": time.time()}
        self.registry.set("network:status", self.status)
    def _ping(self, host):
        try:
            import subprocess
            ping_cmd = 'ping'
            param = '-n' if os.name == 'nt' else '-c'
            timeout = 2
            start = time.time()
            subprocess.run([ping_cmd, param, '1', host], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)
            return (time.time() - start) * 1000
        except:
            return None

# ============================================================================
# 9. APRENDIZAJE POR REFUERZO (Double DQN, SARSA, Actor‑Critic, PPO, Curiosity, Meta, Ensemble)
# ============================================================================
@dataclass
class Experience:
    state: Any
    action: int
    reward: float
    next_state: Any
    done: bool
    priority: float = 1.0

class DoubleDQN:
    def __init__(self, state_dim, action_dim, lr=0.001, gamma=0.99,
                 epsilon=1.0, epsilon_end=0.01, epsilon_decay=0.995,
                 memory_size=10000, batch_size=32, target_update=100):
        self.s_dim = state_dim
        self.a_dim = action_dim
        self.lr = lr
        self.gamma = gamma
        self.epsilon = epsilon
        self.epsilon_end = epsilon_end
        self.epsilon_decay = epsilon_decay
        self.batch = batch_size
        self.target_update_freq = target_update
        self.steps = 0
        self.training_steps = 0
        self._action_dim = action_dim  # Guardar para método helper serializable
        if HAS_NUMPY:
            self.q_net = self._init_net()
            self.target_net = self._init_net()
            self.optim = self._init_adam()
        else:
            # CORREGIDO: Usar método helper en lugar de lambda para permitir serialización pickle
            self.q_table = defaultdict(self._default_q_values)
        self.memory = deque(maxlen=memory_size)
        self.priorities = deque(maxlen=memory_size)
        self.alpha = 0.6
        self.beta = 0.4
        self.beta_inc = 0.001
    
    def _default_q_values(self):
        """Función helper serializable para defaultdict (reemplaza lambda)"""
        return [0.0] * self._action_dim
    
    def _init_net(self):
        return {
            'w1': np.random.randn(self.s_dim,128)*np.sqrt(2/self.s_dim),
            'b1': np.zeros(128),
            'w2': np.random.randn(128,64)*np.sqrt(2/128),
            'b2': np.zeros(64),
            'w3': np.random.randn(64,32)*np.sqrt(2/64),
            'b3': np.zeros(32),
            'w4': np.random.randn(32,self.a_dim)*np.sqrt(2/32),
            'b4': np.zeros(self.a_dim)
        }
    
    def _init_adam(self):
        return {'m':{k:np.zeros_like(v) for k,v in self.q_net.items()},
                'v':{k:np.zeros_like(v) for k,v in self.q_net.items()},
                't':0, 'beta1':0.9, 'beta2':0.999, 'eps':1e-8}
    
    def _forward(self, net, x):
        x = np.array(x).flatten()
        z1 = np.dot(x, net['w1'])+net['b1']; a1 = np.maximum(0.1*z1,z1)
        z2 = np.dot(a1, net['w2'])+net['b2']; a2 = np.maximum(0.1*z2,z2)
        z3 = np.dot(a2, net['w3'])+net['b3']; a3 = np.maximum(0.1*z3,z3)
        return np.dot(a3, net['w4'])+net['b4']
    
    def select_action(self, state, exploit_only=False):
        if not exploit_only and random.random() < self.epsilon:
            return random.randint(0, self.a_dim-1)
        if HAS_NUMPY:
            q = self._forward(self.q_net, state)
            return int(np.argmax(q))
        else:
            key = tuple(state) if isinstance(state,(list,tuple)) else state
            q = self.q_table.get(key, [0.0]*self.a_dim)
            return q.index(max(q))
    
    def store(self, state, action, reward, next_state, done):
        exp = Experience(state,action,reward,next_state,done)
        self.memory.append(exp)
        priority = (abs(reward)+0.01)**self.alpha
        self.priorities.append(priority)
    
    def sample(self):
        if len(self.memory) < self.batch:
            return None,None,None
        if HAS_NUMPY:
            probs = np.array(self.priorities)**self.alpha
            probs /= probs.sum()
            idx = np.random.choice(len(self.memory), self.batch, p=probs, replace=False)
            weights = (len(self.memory)*probs[idx])**(-self.beta)
            weights /= weights.max()
            self.beta = min(1.0, self.beta+self.beta_inc)
            return [self.memory[i] for i in idx], idx, weights
        else:
            return random.sample(self.memory, self.batch), None, None
    
    def _safe_scalar(self, value):
        """Convierte de forma segura cualquier valor numpy a escalar Python"""
        if HAS_NUMPY:
            if isinstance(value, np.ndarray):
                return float(value.flatten()[0]) if value.size > 0 else 0.0
            return float(value)
        return float(value)
    
    def _backward(self, states, targets, weights):
        # Acumula gradientes sobre el batch y aplica Adam
        if not HAS_NUMPY:
            return 0.0
        # Reiniciar gradientes a cero
        grads = {k: np.zeros_like(v) for k,v in self.q_net.items()}
        batch_loss = 0.0
        for s, target, w in zip(states, targets, weights):
            x = np.array(s).flatten()
            # Forward pass completo
            z1 = np.dot(x, self.q_net['w1'])+self.q_net['b1']; a1 = np.maximum(0.1*z1,z1)
            z2 = np.dot(a1, self.q_net['w2'])+self.q_net['b2']; a2 = np.maximum(0.1*z2,z2)
            z3 = np.dot(a2, self.q_net['w3'])+self.q_net['b3']; a3 = np.maximum(0.1*z3,z3)
            output = np.dot(a3, self.q_net['w4'])+self.q_net['b4']
            target_arr = np.array(target).flatten()
            error = (output - target_arr) * w  # ponderado por importancia
            batch_loss += np.mean(error**2)
            # Gradientes (backprop manual)
            grad_w4 = np.outer(a3, error)
            grad_b4 = error
            grad_a3 = np.dot(self.q_net['w4'], error)
            grad_z3 = grad_a3 * (z3 > 0).astype(float)
            grad_w3 = np.outer(a2, grad_z3)
            grad_b3 = grad_z3
            grad_a2 = np.dot(self.q_net['w3'], grad_z3)
            grad_z2 = grad_a2 * (z2 > 0).astype(float)
            grad_w2 = np.outer(a1, grad_z2)
            grad_b2 = grad_z2
            grad_a1 = np.dot(self.q_net['w2'], grad_z2)
            grad_z1 = grad_a1 * (z1 > 0).astype(float)
            grad_w1 = np.outer(x, grad_z1)
            grad_b1 = grad_z1
            # Acumular
            grads['w1'] += grad_w1; grads['b1'] += grad_b1
            grads['w2'] += grad_w2; grads['b2'] += grad_b2
            grads['w3'] += grad_w3; grads['b3'] += grad_b3
            grads['w4'] += grad_w4; grads['b4'] += grad_b4
        # Promediar gradientes
        n = len(states)
        for k in grads:
            grads[k] /= n
        # Actualizar con Adam
        self._adam_update(grads)
        return batch_loss / n
    
    def _adam_update(self, grads):
        self.optim['t'] += 1
        t = self.optim['t']
        for key in self.q_net:
            g = grads[key]
            m = self.optim['m'][key]
            v = self.optim['v'][key]
            m = self.optim['beta1']*m + (1-self.optim['beta1'])*g
            v = self.optim['beta2']*v + (1-self.optim['beta2'])*(g**2)
            self.optim['m'][key] = m
            self.optim['v'][key] = v
            m_hat = m / (1 - self.optim['beta1']**t)
            v_hat = v / (1 - self.optim['beta2']**t)
            self.q_net[key] -= self.lr * m_hat / (np.sqrt(v_hat) + self.optim['eps'])
    
    def learn(self):
        batch, indices, weights = self.sample()
        if not batch:
            return {}
        if HAS_NUMPY:
            states = []
            targets = []
            td_errors = []
            for exp in batch:
                q_curr = self._forward(self.q_net, exp.state)
                q_next_online = self._forward(self.q_net, exp.next_state)
                q_next_target = self._forward(self.target_net, exp.next_state)
                best_a = int(np.argmax(q_next_online))
                target = exp.reward + self.gamma * q_next_target[best_a] * (1-exp.done)
                td = target - q_curr[exp.action]
                target_q = q_curr.copy()
                target_q[exp.action] = target
                states.append(exp.state)
                targets.append(target_q)
                td_errors.append(abs(td))
            loss = self._backward(states, targets, weights)
            if indices is not None:
                for idx, td in zip(indices, td_errors):
                    self.priorities[idx] = (td+0.01)**self.alpha
        else:
            # Versión tabla Q
            loss = 0.0
            for exp in batch:
                key = tuple(exp.state) if isinstance(exp.state,(list,tuple)) else exp.state
                nkey = tuple(exp.next_state) if isinstance(exp.next_state,(list,tuple)) else exp.next_state
                q = list(self.q_table.get(key, [0.0]*self.a_dim))
                nq = list(self.q_table.get(nkey, [0.0]*self.a_dim))
                best_a = nq.index(max(nq)) if nq else 0
                target = exp.reward + self.gamma * nq[best_a] * (1-exp.done)
                q[exp.action] += self.lr * (target - q[exp.action])
                self.q_table[key] = q
        self.epsilon = max(self.epsilon_end, self.epsilon * self.epsilon_decay)
        self.steps += 1
        if self.steps % self.target_update_freq == 0 and HAS_NUMPY:
            for k in self.q_net:
                self.target_net[k] = self.q_net[k].copy()
        self.training_steps += 1
        return {'loss': loss if loss is not None else 0, 'epsilon': self.epsilon}
    
    def get_epsilon(self):
        """Retorna el valor actual de epsilon para exploración"""
        return self.epsilon
    
    def get_training_progress(self):
        """Retorna el progreso de entrenamiento"""
        return {
            'steps': self.steps,
            'training_steps': self.training_steps,
            'epsilon': self.epsilon,
            'memory_size': len(self.memory)
        }
    
    def save(self, path):
        data = {'epsilon': self.epsilon, 'steps': self.steps, 'training_steps': self.training_steps}
        if HAS_NUMPY:
            data['q_net'] = {k: v.tolist() for k,v in self.q_net.items()}
            data['target_net'] = {k: v.tolist() for k,v in self.target_net.items()}
            with open(path, 'wb') as f:
                pickle.dump(data, f)
        else:
            data['q_table'] = dict(self.q_table)
            with open(path, 'wb') as f:
                pickle.dump(data, f)
    
    def load(self, path):
        with open(path, 'rb') as f:
            data = pickle.load(f)
        self.epsilon = data.get('epsilon', self.epsilon)
        self.steps = data.get('steps', 0)
        self.training_steps = data.get('training_steps', 0)
        if HAS_NUMPY and 'q_net' in data:
            for k in self.q_net:
                self.q_net[k] = np.array(data['q_net'][k])
                self.target_net[k] = np.array(data['target_net'][k])
        elif not HAS_NUMPY and 'q_table' in data:
            # CORREGIDO: Usar método helper serializable en lugar de lambda
            self.q_table = defaultdict(self._default_q_values, data['q_table'])
    
    def __getstate__(self):
        """Prepara el objeto para serialización pickle"""
        state = self.__dict__.copy()
        # defaultdict con método helper ya es serializable
        return state
    
    def __setstate__(self, state):
        """Restaura el objeto desde serialización pickle"""
        self.__dict__.update(state)
        # Asegurar que _action_dim existe para _default_q_values
        if not hasattr(self, '_action_dim'):
            self._action_dim = self.a_dim

class SARSAAgent:
    def __init__(self, state_dim, action_dim, lr=0.1, gamma=0.99,
                 epsilon=1.0, epsilon_decay=0.995, epsilon_end=0.01):
        self.s_dim = state_dim
        self.a_dim = action_dim
        self.lr = lr
        self.gamma = gamma
        self.epsilon = epsilon
        self.eps_decay = epsilon_decay
        self.eps_end = epsilon_end
        # CORREGIDO: Reemplazar lambda por función helper serializable
        self.q_table = defaultdict(self._default_q_values)
        self._action_dim = action_dim  # Guardar para la función helper
    def _default_q_values(self):
        """Función helper serializable para defaultdict"""
        return [0.0] * self._action_dim
    def _key(self, state):
        if isinstance(state, (list,tuple)):
            return tuple(state)
        return state
    def select_action(self, state, exploit_only=False):
        if not exploit_only and random.random() < self.epsilon:
            return random.randint(0, self.a_dim-1)
        key = self._key(state)
        q = self.q_table[key]
        return q.index(max(q))
    def update(self, state, action, reward, next_state, next_action, done):
        key = self._key(state)
        nkey = self._key(next_state)
        q = list(self.q_table[key])
        nq = list(self.q_table[nkey])
        if done:
            q[action] += self.lr * (reward - q[action])
        else:
            q[action] += self.lr * (reward + self.gamma * nq[next_action] - q[action])
        self.q_table[key] = q
        self.epsilon = max(self.eps_end, self.epsilon * self.eps_decay)
    def save(self, path):
        with open(path, 'wb') as f:
            pickle.dump(dict(self.q_table), f)
    def load(self, path):
        with open(path, 'rb') as f:
            data = pickle.load(f)
        self.q_table = defaultdict(self._default_q_values, data)

class ActorCritic:
    def __init__(self, state_dim, action_dim, actor_lr=0.0003, critic_lr=0.001,
                 gamma=0.99, entropy_coef=0.01):
        self.s_dim = state_dim
        self.a_dim = action_dim
        self.actor_lr = actor_lr
        self.critic_lr = critic_lr
        self.gamma = gamma
        self.entropy_coef = entropy_coef
        self.buffer = []
        if HAS_NUMPY:
            self.actor_w = np.random.randn(state_dim, action_dim) * 0.01
            self.actor_b = np.zeros(action_dim)
            self.critic_w1 = np.random.randn(state_dim, 64) * np.sqrt(2.0 / max(state_dim, 1))
            self.critic_b1 = np.zeros(64)
            self.critic_w2 = np.random.randn(64, 1) * np.sqrt(2.0 / 64)
            self.critic_b2 = np.zeros(1)
            # Estadísticas para monitoreo
            self.grad_norm_actor = 0.0
            self.grad_norm_critic = 0.0
        else:
            self.actor_table = defaultdict(lambda: [1.0/action_dim]*action_dim)
            self.critic_table = defaultdict(float)
    
    def _safe_scalar(self, value):
        """Convierte de forma segura cualquier valor numpy a escalar Python"""
        if HAS_NUMPY:
            if isinstance(value, np.ndarray):
                return float(value.flatten()[0]) if value.size > 0 else 0.0
            return float(value)
        return float(value)
    
    def _clip_gradients(self, grad, max_norm=1.0):
        """Recorta gradientes para evitar explosión"""
        if HAS_NUMPY:
            grad_norm = np.linalg.norm(grad)
            if grad_norm > max_norm and grad_norm > 0:
                grad = grad * (max_norm / grad_norm)
        return grad
    
    def _softmax(self, logits):
        # Estabilidad numérica mejorada
        logits = np.clip(logits, -50, 50)  # Prevenir overflow en exp
        max_l = max(logits)
        exps = [math.exp(min(l - max_l, 50)) for l in logits]  # Prevenir overflow
        s = sum(exps)
        if s < 1e-10:
            return [1.0 / len(logits)] * len(logits)
        return [e/s for e in exps]
    
    def _actor_probs(self, state):
        if HAS_NUMPY:
            x = np.array(state).flatten()
            logits = np.dot(x, self.actor_w) + self.actor_b
            logits = np.clip(logits, -50, 50)  # Prevenir overflow
            exps = np.exp(logits - np.max(logits))
            s = exps.sum()
            if s < 1e-10:
                return np.ones(self.a_dim) / self.a_dim
            return exps / s
        else:
            key = tuple(state) if isinstance(state,(list,tuple)) else state
            return self.actor_table.get(key, [1.0/self.a_dim]*self.a_dim)
    
    def _critic_value(self, state):
        if HAS_NUMPY:
            x = np.array(state).flatten()
            h = np.maximum(0, np.dot(x, self.critic_w1) + self.critic_b1)
            # Recortar h para prevenir overflow
            h = np.clip(h, 0, 100)
            result = np.dot(h, self.critic_w2) + self.critic_b2
            return self._safe_scalar(result)
        else:
            key = tuple(state) if isinstance(state,(list,tuple)) else state
            return self.critic_table.get(key, 0.0)
    
    def select_action(self, state):
        probs = self._actor_probs(state)
        if HAS_NUMPY:
            # Asegurar que las probabilidades sumen 1
            probs = np.clip(probs, 0, None)
            s = probs.sum()
            if s > 0:
                probs = probs / s
            else:
                probs = np.ones(self.a_dim) / self.a_dim
            action = np.random.choice(self.a_dim, p=probs)
            log_prob = math.log(max(probs[action], 1e-8))
        else:
            r = random.random()
            cum = 0.0
            for i,p in enumerate(probs):
                cum += p
                if r <= cum:
                    action = i
                    break
            else:
                action = 0
            log_prob = math.log(max(probs[action],1e-8))
        value = self._critic_value(state)
        return action, log_prob, value
    
    def store(self, state, action, reward, next_state, done, log_prob, value):
        self.buffer.append((state,action,reward,next_state,done,log_prob,value))
    
    def compute_gae(self, rewards, values, dones, gamma=0.99, lam=0.95):
        advantages = []
        gae = 0
        for i in reversed(range(len(rewards))):
            next_val = 0 if i==len(rewards)-1 else values[i+1]
            delta = rewards[i] + gamma * next_val * (1-dones[i]) - values[i]
            gae = delta + gamma * lam * (1-dones[i]) * gae
            advantages.insert(0, gae)
        returns = [adv + val for adv, val in zip(advantages, values)]
        return advantages, returns
    
    def update(self, done, next_value=0):
        if not self.buffer or not HAS_NUMPY:
            self.buffer.clear()
            return {}
        states, actions, rewards, next_states, dones, log_probs, values = zip(*self.buffer)
        advantages, returns = self.compute_gae(rewards, values, dones, self.gamma)
        
        # Normalizar advantages con estabilidad numérica
        adv_arr = np.array(advantages)
        adv_std = adv_arr.std()
        if adv_std > 1e-8:
            adv_arr = (adv_arr - adv_arr.mean()) / (adv_std + 1e-8)
        # Recortar advantages para estabilidad
        adv_arr = np.clip(adv_arr, -5, 5)
        
        total_actor_loss = 0.0
        total_critic_loss = 0.0
        n_updates = 0
        
        # Actualizar actor y crítico
        for s, a, adv, ret in zip(states, actions, adv_arr, returns):
            x = np.array(s).flatten()
            adv_val = self._safe_scalar(adv)
            ret_val = self._safe_scalar(ret)
            
            # Actor update
            probs = self._actor_probs(s)
            grad_logits = np.array([-p for p in probs])
            grad_logits[a] += 1.0
            grad_logits = grad_logits * adv_val
            
            # Clip gradientes del actor
            grad_logits = self._clip_gradients(grad_logits, max_norm=5.0)
            
            self.actor_w += self.actor_lr * np.outer(x, grad_logits)
            self.actor_b += self.actor_lr * grad_logits
            
            # Recortar pesos para prevenir overflow
            self.actor_w = np.clip(self.actor_w, -10, 10)
            self.actor_b = np.clip(self.actor_b, -10, 10)
            
            # Crítico update
            v_pred = self._critic_value(s)
            error = ret_val - v_pred
            error = max(-10, min(10, error))  # Recortar error
            
            h = np.maximum(0, np.dot(x, self.critic_w1) + self.critic_b1)
            h = np.clip(h, 0, 100)  # Recortar activaciones
            
            grad_w2 = np.outer(h, error)
            grad_b2 = np.array([error])
            
            self.critic_w2 += self.critic_lr * grad_w2
            self.critic_b2 += self.critic_lr * grad_b2
            
            grad_h = np.dot(self.critic_w2, error).flatten() * (h > 0)
            grad_h = self._clip_gradients(grad_h, max_norm=5.0)
            
            grad_w1 = np.outer(x, grad_h)
            grad_b1 = grad_h
            
            self.critic_w1 += self.critic_lr * grad_w1
            self.critic_b1 += self.critic_lr * grad_b1
            
            # Recortar pesos del crítico
            self.critic_w1 = np.clip(self.critic_w1, -10, 10)
            self.critic_b1 = np.clip(self.critic_b1, -10, 10)
            self.critic_w2 = np.clip(self.critic_w2, -10, 10)
            self.critic_b2 = np.clip(self.critic_b2, -10, 10)
            
            total_actor_loss += adv_val
            total_critic_loss += error ** 2
            n_updates += 1
        
        self.buffer.clear()
        return {
            'actor_loss': total_actor_loss / max(n_updates, 1),
            'critic_loss': total_critic_loss / max(n_updates, 1)
        }

class PPO:
    def __init__(self, state_dim, action_dim, lr=3e-4, gamma=0.99, epsilon=0.2,
                 value_coef=0.5, entropy_coef=0.01, epochs=4, batch_size=64):
        self.s_dim = state_dim
        self.a_dim = action_dim
        self.lr = lr
        self.gamma = gamma
        self.eps_clip = epsilon
        self.v_coef = value_coef
        self.ent_coef = entropy_coef
        self.epochs = epochs
        self.batch_size = batch_size
        self.buffer = []
        if HAS_NUMPY:
            self.policy = {'w': np.random.randn(state_dim, action_dim)*0.01, 'b': np.zeros(action_dim)}
            self.value = {
                'w1': np.random.randn(state_dim,64)*np.sqrt(2/state_dim), 'b1': np.zeros(64),
                'w2': np.random.randn(64,1)*np.sqrt(2/64), 'b2': np.zeros(1)
            }
        else:
            self.policy_table = defaultdict(lambda: [1.0/action_dim]*action_dim)
            self.value_table = defaultdict(float)
    def _safe_scalar(self, value):
        """Convierte de forma segura cualquier valor numpy a escalar Python"""
        if HAS_NUMPY:
            if isinstance(value, np.ndarray):
                return float(value.flatten()[0]) if value.size > 0 else 0.0
            return float(value)
        return float(value)
    def _policy_probs(self, state):
        if HAS_NUMPY:
            x = np.array(state).flatten()
            logits = np.dot(x, self.policy['w']) + self.policy['b']
            exps = np.exp(logits - np.max(logits))
            return exps / exps.sum()
        else:
            key = tuple(state) if isinstance(state,(list,tuple)) else state
            return self.policy_table.get(key, [1.0/self.a_dim]*self.a_dim)
    def _value(self, state):
        if HAS_NUMPY:
            x = np.array(state).flatten()
            h = np.maximum(0, np.dot(x, self.value['w1']) + self.value['b1'])
            result = np.dot(h, self.value['w2']) + self.value['b2']
            return self._safe_scalar(result)
        else:
            key = tuple(state) if isinstance(state,(list,tuple)) else state
            return self.value_table.get(key, 0.0)
    def select_action(self, state):
        probs = self._policy_probs(state)
        if HAS_NUMPY:
            action = np.random.choice(self.a_dim, p=probs)
            logp = math.log(max(probs[action],1e-8))
        else:
            r = random.random()
            cum = 0.0
            for i,p in enumerate(probs):
                cum += p
                if r <= cum:
                    action = i
                    break
            else:
                action = 0
            logp = math.log(max(probs[action],1e-8))
        val = self._value(state)
        return action, logp, val
    def store(self, state, action, reward, next_state, done, logp, val):
        self.buffer.append((state,action,reward,next_state,done,logp,val))
    def compute_gae(self, rewards, values, dones):
        advantages = []
        gae = 0
        for i in reversed(range(len(rewards))):
            next_val = 0 if i==len(rewards)-1 else values[i+1]
            delta = rewards[i] + self.gamma * next_val * (1-dones[i]) - values[i]
            gae = delta + self.gamma * 0.95 * (1-dones[i]) * gae
            advantages.insert(0, gae)
        returns = [adv + val for adv, val in zip(advantages, values)]
        return advantages, returns
    def update(self):
        if not self.buffer or not HAS_NUMPY:
            self.buffer.clear()
            return {}
        states, actions, rewards, next_states, dones, old_log_probs, old_values = zip(*self.buffer)
        advantages, returns = self.compute_gae(rewards, old_values, dones)
        adv_arr = np.array(advantages)
        if adv_arr.std() > 1e-8:
            adv_arr = (adv_arr - adv_arr.mean()) / (adv_arr.std() + 1e-8)
        # Convertir a numpy arrays
        states = np.array(states)
        actions = np.array(actions)
        old_log_probs = np.array(old_log_probs)
        returns = np.array(returns)
        # Múltiples épocas
        total_loss = 0.0
        n_updates = 0
        for _ in range(self.epochs):
            indices = np.random.permutation(len(states))
            for start in range(0, len(states), self.batch_size):
                idx = indices[start:start+self.batch_size]
                batch_states = states[idx]
                batch_actions = actions[idx]
                batch_adv = adv_arr[idx]
                batch_returns = returns[idx]
                batch_old_logp = old_log_probs[idx]
                # Forward policy
                logits = np.dot(batch_states, self.policy['w']) + self.policy['b']
                # Log softmax
                log_probs = logits - np.log(np.exp(logits).sum(axis=1, keepdims=True))
                new_log_probs = np.choose(batch_actions, log_probs.T)
                ratio = np.exp(new_log_probs - batch_old_logp)
                surr1 = ratio * batch_adv
                surr2 = np.clip(ratio, 1-self.eps_clip, 1+self.eps_clip) * batch_adv
                policy_loss = -np.mean(np.minimum(surr1, surr2))
                # Value loss
                h = np.maximum(0, np.dot(batch_states, self.value['w1']) + self.value['b1'])
                v_pred = np.dot(h, self.value['w2']) + self.value['b2']
                value_loss = np.mean((batch_returns - v_pred.flatten())**2)
                # Entropy
                entropy = -np.mean(np.exp(log_probs) * log_probs)
                loss = policy_loss + self.v_coef * value_loss - self.ent_coef * entropy
                total_loss += self._safe_scalar(loss)
                # Gradientes (simplificado, para no alargar, actualización con SGD)
                grad_logits = np.exp(logits) / np.exp(logits).sum(axis=1, keepdims=True)
                grad_logits[np.arange(len(batch_actions)), batch_actions] -= 1.0
                grad_logits = grad_logits * batch_adv[:, None]
                self.policy['w'] -= self.lr * np.dot(batch_states.T, grad_logits) / len(batch_states)
                self.policy['b'] -= self.lr * grad_logits.mean(axis=0)
                # Value gradients
                grad_v = 2 * (v_pred.flatten() - batch_returns) / len(batch_states)
                grad_w2 = np.outer(h.mean(axis=0), grad_v)
                grad_b2 = grad_v.mean()
                self.value['w2'] -= self.lr * grad_w2
                self.value['b2'] -= self.lr * grad_b2
                grad_h = np.dot(self.value['w2'], grad_v) * (h > 0)
                grad_w1 = np.dot(batch_states.T, grad_h) / len(batch_states)
                grad_b1 = grad_h.mean(axis=0)
                self.value['w1'] -= self.lr * grad_w1
                self.value['b1'] -= self.lr * grad_b1
                n_updates += 1
        self.buffer.clear()
        return {'loss': total_loss / n_updates if n_updates>0 else 0}
    def save(self, path):
        if HAS_NUMPY:
            data = {'policy_w': self.policy['w'], 'policy_b': self.policy['b'],
                    'value_w1': self.value['w1'], 'value_b1': self.value['b1'],
                    'value_w2': self.value['w2'], 'value_b2': self.value['b2']}
            with open(path, 'wb') as f:
                pickle.dump(data, f)
    def load(self, path):
        if HAS_NUMPY:
            with open(path, 'rb') as f:
                data = pickle.load(f)
            self.policy['w'] = data['policy_w']
            self.policy['b'] = data['policy_b']
            self.value['w1'] = data['value_w1']
            self.value['b1'] = data['value_b1']
            self.value['w2'] = data['value_w2']
            self.value['b2'] = data['value_b2']

class CuriosityModule:
    def __init__(self, state_dim, action_dim, lr=0.001, intrinsic_scale=1.0, hidden=128):
        self.s_dim = state_dim
        self.a_dim = action_dim
        self.lr = lr
        self.scale = intrinsic_scale
        self.hidden = hidden
        self.state_buffer = deque(maxlen=2000)
        self.state_counts = defaultdict(int)
        if HAS_NUMPY:
            self.forward = {
                'w1': np.random.randn(state_dim+action_dim, hidden)*0.01,
                'b1': np.zeros(hidden),
                'w2': np.random.randn(hidden, state_dim)*0.01,
                'b2': np.zeros(state_dim)
            }
        else:
            self.forward_table = defaultdict(lambda: [0.0]*state_dim)
    def _onehot(self, action):
        vec = [0.0]*self.a_dim
        vec[int(action)] = 1.0
        return vec
    def _forward_pred(self, state, action):
        if HAS_NUMPY:
            s = np.array(state).flatten()
            a = np.array(self._onehot(action))
            x = np.concatenate([s, a])
            h = np.maximum(0, np.dot(x, self.forward['w1']) + self.forward['b1'])
            pred = np.dot(h, self.forward['w2']) + self.forward['b2']
            return pred
        else:
            key = (tuple(state), action)
            return self.forward_table.get(key, state)
    def compute_intrinsic_reward(self, state, action, next_state):
        pred = self._forward_pred(state, action)
        if HAS_NUMPY:
            next_arr = np.array(next_state).flatten()
            pred_arr = np.array(pred).flatten()
            # Asegurar misma longitud
            min_len = min(len(pred_arr), len(next_arr))
            err = np.linalg.norm(pred_arr[:min_len] - next_arr[:min_len]) / math.sqrt(max(1, min_len))
        else:
            err = sum(abs(p - n) for p,n in zip(pred, next_state)) / max(1, len(pred))
        key = tuple(state) if isinstance(state,(list,tuple)) else state
        cnt = self.state_counts[key] + 1
        self.state_counts[key] = cnt
        novelty = 1.0 / math.sqrt(1.0 + cnt)
        return self.scale * (0.5*err + 0.5*novelty)
    def update_models(self, state, action, next_state):
        if HAS_NUMPY:
            s = np.array(state).flatten()
            a = np.array(self._onehot(action))
            x = np.concatenate([s, a])
            h = np.maximum(0, np.dot(x, self.forward['w1']) + self.forward['b1'])
            pred = np.dot(h, self.forward['w2']) + self.forward['b2']
            target = np.array(next_state).flatten()
            # Asegurar misma longitud
            min_len = min(len(pred), len(target))
            pred = pred[:min_len]
            target = target[:min_len]
            error = pred - target
            grad_w2 = np.outer(h, error)
            grad_b2 = error
            grad_h = np.dot(self.forward['w2'][:,:min_len], error)
            grad_h = grad_h * (h>0).astype(float)
            grad_w1 = np.outer(x, grad_h)
            grad_b1 = grad_h
            self.forward['w2'][:,:min_len] -= self.lr * grad_w2
            self.forward['b2'][:min_len] -= self.lr * grad_b2
            self.forward['w1'] -= self.lr * grad_w1
            self.forward['b1'] -= self.lr * grad_b1
        else:
            key = (tuple(state), action)
            self.forward_table[key] = next_state
    def save(self, path):
        if HAS_NUMPY:
            with open(path, 'wb') as f:
                pickle.dump(self.forward, f)
    def load(self, path):
        if HAS_NUMPY:
            with open(path, 'rb') as f:
                self.forward = pickle.load(f)

class EpisodicMemory:
    def __init__(self, capacity=10000):
        self.capacity = capacity
        self.episodes = deque(maxlen=capacity)
        self.state_index = defaultdict(list)
        self.access = 0
        self.hits = 0
    def _hash(self, state):
        if isinstance(state, (list,tuple)):
            return tuple(state[:4])
        return (state,)
    def add_episode(self, experiences):
        ep = {
            'exps': experiences,
            'total_reward': sum(r for _,_,r,_ in experiences),
            'length': len(experiences),
            'timestamp': time.time()
        }
        self.episodes.append(ep)
        if experiences:
            self.state_index[self._hash(experiences[0][0])].append(len(self.episodes)-1)
    def find_similar(self, state, k=5, min_sim=0.5):
        self.access += 1
        key = self._hash(state)
        candidates = set(self.state_index.get(key, []))
        results = []
        for idx in candidates:
            if idx >= len(self.episodes):
                continue
            ep = self.episodes[idx]
            if ep['exps']:
                sim = self._similarity(state, ep['exps'][0][0])
                if sim >= min_sim:
                    results.append((sim, ep))
        results.sort(key=lambda x: x[0], reverse=True)
        if results:
            self.hits += 1
        return results[:k]
    def _similarity(self, s1, s2):
        try:
            v1 = s1 if isinstance(s1,(list,tuple)) else [s1]
            v2 = s2 if isinstance(s2,(list,tuple)) else [s2]
            n = min(len(v1), len(v2))
            if n==0: return 0.5
            dot = sum(v1[i]*v2[i] for i in range(n))
            n1 = math.sqrt(sum(v1[i]**2 for i in range(n)))
            n2 = math.sqrt(sum(v2[i]**2 for i in range(n)))
            if n1==0 or n2==0: return 0.5
            return (dot/(n1*n2)+1)/2
        except:
            return 0.5
    def get_best_action(self, state, k=3):
        similar = self.find_similar(state, k=k, min_sim=0.6)
        scores = defaultdict(float)
        counts = defaultdict(int)
        for sim, ep in similar:
            for s,a,r,_ in ep['exps']:
                if r>0:
                    scores[a] += sim * r
                    counts[a] += 1
        if not scores:
            return None, 0.0
        best = max(scores, key=lambda a: scores[a]/counts[a])
        total = sum(counts.values())
        return best, counts[best]/total if total>0 else 0.0
    def save(self, path):
        with open(path, 'wb') as f:
            pickle.dump({'episodes': list(self.episodes), 'state_index': dict(self.state_index)}, f)
    def load(self, path):
        with open(path, 'rb') as f:
            data = pickle.load(f)
        self.episodes = deque(data['episodes'], maxlen=self.capacity)
        self.state_index = defaultdict(list, data['state_index'])

class MetaLearner:
    def __init__(self, state_dim, action_dim, meta_lr=0.001, inner_lr=0.1, inner_steps=5):
        self.s_dim = state_dim
        self.a_dim = action_dim
        self.meta_lr = meta_lr
        self.inner_lr = inner_lr
        self.inner_steps = inner_steps
        if HAS_NUMPY:
            self.weights = {
                'w': np.random.randn(state_dim, action_dim)*0.01,
                'b': np.zeros(action_dim)
            }
        else:
            self.weights = {'w': [[random.uniform(-0.1,0.1) for _ in range(action_dim)] for _ in range(state_dim)],
                            'b': [0.0]*action_dim}
    def _safe_scalar(self, value):
        """Convierte de forma segura cualquier valor numpy a escalar Python"""
        if HAS_NUMPY:
            if isinstance(value, np.ndarray):
                return float(value.flatten()[0]) if value.size > 0 else 0.0
            return float(value)
        return float(value)
    def _forward(self, state, w):
        if HAS_NUMPY:
            x = np.array(state).flatten()
            logits = np.dot(x, w['w']) + w['b']
            exps = np.exp(logits - np.max(logits))
            probs = exps / exps.sum()
            return probs
        else:
            logits = [sum(state[j]*w['w'][j][i] for j in range(self.s_dim)) + w['b'][i] for i in range(self.a_dim)]
            max_l = max(logits)
            exps = [math.exp(l-max_l) for l in logits]
            s = sum(exps)
            return [e/s for e in exps]
    def adapt(self, task_data, n_steps=None):
        if n_steps is None: n_steps = self.inner_steps
        w = copy.deepcopy(self.weights)
        for _ in range(n_steps):
            for sample in task_data:
                s = sample['state']
                a = sample['action']
                r = self._safe_scalar(sample['reward'])
                probs = self._forward(s, w)
                grad_logits = [-p for p in probs]
                grad_logits[a] += 1.0
                grad_logits = [g * r for g in grad_logits]
                if HAS_NUMPY:
                    x = np.array(s).flatten()
                    w['w'] += self.inner_lr * np.outer(x, grad_logits)
                    w['b'] += self.inner_lr * np.array(grad_logits)
                else:
                    for i in range(self.a_dim):
                        for j in range(self.s_dim):
                            w['w'][j][i] += self.inner_lr * s[j] * grad_logits[i]
                        w['b'][i] += self.inner_lr * grad_logits[i]
        return w
    def meta_update(self, tasks_grads):
        avg_grad_w = None
        avg_grad_b = None
        for gw, gb in tasks_grads:
            if avg_grad_w is None:
                avg_grad_w = gw.copy()
                avg_grad_b = gb.copy()
            else:
                avg_grad_w += gw
                avg_grad_b += gb
        n = len(tasks_grads)
        avg_grad_w /= n
        avg_grad_b /= n
        if HAS_NUMPY:
            self.weights['w'] -= self.meta_lr * avg_grad_w
            self.weights['b'] -= self.meta_lr * avg_grad_b
        else:
            for i in range(self.a_dim):
                for j in range(self.s_dim):
                    self.weights['w'][j][i] -= self.meta_lr * avg_grad_w[j][i]
                self.weights['b'][i] -= self.meta_lr * avg_grad_b[i]
    def select_action(self, state, weights=None):
        if weights is None: weights = self.weights
        probs = self._forward(state, weights)
        r = random.random()
        cum = 0.0
        for i,p in enumerate(probs):
            cum += p
            if r <= cum:
                return i
        return 0
    def save(self, path):
        with open(path, 'wb') as f:
            pickle.dump(self.weights, f)
    def load(self, path):
        with open(path, 'rb') as f:
            self.weights = pickle.load(f)

class EnsembleRL:
    def __init__(self, state_dim, action_dim, use_curiosity=True, use_episodic=True, use_meta=True,
                 weight_opt_freq=100):
        self.s_dim = state_dim
        self.a_dim = action_dim
        self.algorithms = {
            'dqn': DoubleDQN(state_dim, action_dim),
            'sarsa': SARSAAgent(state_dim, action_dim),
            'ac': ActorCritic(state_dim, action_dim),
            'ppo': PPO(state_dim, action_dim)
        }
        self.weights = {k:0.25 for k in self.algorithms}
        self.perf = {k:0.0 for k in self.algorithms}
        self.recent_rewards = {k: deque(maxlen=50) for k in self.algorithms}
        self.use_curiosity = use_curiosity
        self.use_episodic = use_episodic
        self.use_meta = use_meta
        if use_curiosity:
            self.curiosity = CuriosityModule(state_dim, action_dim)
        if use_episodic:
            self.episodic = EpisodicMemory()
        if use_meta:
            self.meta = MetaLearner(state_dim, action_dim)
        self.step = 0
        self.weight_opt_freq = weight_opt_freq
        self.genetic_opt = None
    def _safe_scalar(self, value):
        """Convierte de forma segura cualquier valor numpy a escalar Python"""
        if HAS_NUMPY:
            if isinstance(value, np.ndarray):
                return float(value.flatten()[0]) if value.size > 0 else 0.0
            return float(value)
        return float(value)
    def select_action(self, state, exploit_only=False):
        if self.use_meta and random.random() < 0.15:
            try:
                action = self.meta.select_action(state)
                return action
            except:
                pass
        if self.use_episodic and not exploit_only:
            best, conf = self.episodic.get_best_action(state)
            if best is not None and conf > 0.6:
                return best
        votes = {}
        for name, algo in self.algorithms.items():
            try:
                a = algo.select_action(state, exploit_only)
                votes[name] = a
            except:
                continue
        if not votes:
            return random.randint(0, self.a_dim-1)
        wsum = defaultdict(float)
        for name, a in votes.items():
            wsum[a] += self.weights.get(name, 0.25)
        return max(wsum, key=wsum.get)
    def update_weights_by_performance(self):
        avg_rewards = {}
        for name, dq in self.recent_rewards.items():
            if dq:
                avg_rewards[name] = sum(dq)/len(dq)
            else:
                avg_rewards[name] = 0.0
        # Actualizar rendimiento con suavizado
        for name, r in avg_rewards.items():
            self.perf[name] = 0.9 * self.perf.get(name, 0) + 0.1 * r
        # Softmax sobre rendimiento
        perf_vals = np.array(list(self.perf.values())) if HAS_NUMPY else list(self.perf.values())
        if HAS_NUMPY:
            perf_vals = perf_vals - np.max(perf_vals)
            exp_vals = np.exp(perf_vals)
            new_weights = exp_vals / exp_vals.sum()
        else:
            max_p = max(perf_vals)
            exp_vals = [math.exp(p - max_p) for p in perf_vals]
            s = sum(exp_vals)
            new_weights = [e/s if s>0 else 1.0/len(exp_vals) for e in exp_vals]
        for i, name in enumerate(self.algorithms):
            self.weights[name] = float(new_weights[i])
    def optimize_weights_genetic(self, fitness_fn, generations=20):
        bounds = {name: (0.01, 1.0) for name in self.algorithms}
        ga = GeneticOptimizer(bounds, pop_size=20, gens=generations)
        best_weights, _ = ga.optimize(fitness_fn, verbose=False)
        total = sum(best_weights.values())
        if total > 0:
            best_weights = {k: v/total for k,v in best_weights.items()}
        self.weights.update(best_weights)
    def update(self, state, action, reward, next_state, done):
        total_reward = self._safe_scalar(reward)
        intr = 0.0
        if self.use_curiosity:
            intr = self.curiosity.compute_intrinsic_reward(state, action, next_state)
            self.curiosity.update_models(state, action, next_state)
            total_reward += 0.01 * intr
        # Almacenar recompensa para cada algoritmo
        for name in self.algorithms:
            self.recent_rewards[name].append(total_reward)
        # Actualizar cada algoritmo
        for name, algo in self.algorithms.items():
            try:
                if name == 'dqn':
                    algo.store(state, action, total_reward, next_state, done)
                    if len(algo.memory) >= algo.batch:
                        algo.learn()
                elif name == 'sarsa':
                    next_a = algo.select_action(next_state, exploit_only=False)
                    algo.update(state, action, total_reward, next_state, next_a, done)
                elif name == 'ac':
                    # ActorCritic requiere almacenar y luego actualizar en batch
                    ac_action, logp, val = algo.select_action(state)
                    algo.store(state, ac_action, total_reward, next_state, done, logp, val)
                    if done or len(algo.buffer) >= 32:
                        algo.update(done)
                elif name == 'ppo':
                    ppo_action, logp, val = algo.select_action(state)
                    algo.store(state, ppo_action, total_reward, next_state, done, logp, val)
                    if len(algo.buffer) >= 2048 or done:
                        algo.update()
            except Exception as e:
                log.debug(f"Error actualizando {name}: {e}")
                continue
        if self.use_episodic:
            self.episodic.add_episode([(state, action, total_reward, done)])
        if self.use_meta:
            self.meta.adapt([{'state':state, 'action':action, 'reward':total_reward}], n_steps=1)
        self.step += 1
        # Actualizar pesos periódicamente
        if self.step % self.weight_opt_freq == 0:
            self.update_weights_by_performance()
        return {'total_reward': total_reward, 'intrinsic': intr}
    def save(self, path):
        data = {'weights': self.weights, 'perf': self.perf, 'step': self.step}
        with open(path, 'wb') as f:
            pickle.dump(data, f)
    def load(self, path):
        with open(path, 'rb') as f:
            data = pickle.load(f)
        self.weights = data.get('weights', self.weights)
        self.perf = data.get('perf', self.perf)
        self.step = data.get('step', 0)

# ============================================================================
# 10. UTILIDADES ADICIONALES (Fuzzy, Kalman, Genetic, HyperNumber)
# ============================================================================
class FuzzyLogicController:
    def __init__(self):
        self.rules = []
        self.mfs = {}
        self.outputs = {}  # Registro de variables de salida y sus rangos
    
    def add_mf(self, var, name, mf_type, params):
        """Agrega una función de membresía a una variable"""
        self.mfs.setdefault(var, {})[name] = (mf_type, params)
    
    def add_output(self, var, output_range=(0, 1)):
        """Registra una variable de salida con su rango"""
        self.outputs[var] = output_range
    
    def add_rule(self, antecedent, consequent):
        """Agrega una regla difusa. antecedent: dict {var: mf_name}, consequent: dict {var: value}"""
        self.rules.append((antecedent, consequent))
        # Registrar automáticamente variables de salida
        for outvar in consequent:
            if outvar not in self.outputs:
                self.outputs[outvar] = (0, 1)
    
    def _triangle(self, x, a, b, c):
        """Función de membresía triangular"""
        if x <= a or x >= c:
            return 0.0
        elif a < x <= b:
            return (x - a) / (b - a) if b != a else 0.0
        else:
            return (c - x) / (c - b) if c != b else 0.0
    
    def _trapezoid(self, x, a, b, c, d):
        """Función de membresía trapezoidal"""
        if x <= a or x >= d:
            return 0.0
        elif b <= x <= c:
            return 1.0
        elif a < x < b:
            return (x - a) / (b - a) if b != a else 0.0
        else:
            return (d - x) / (d - c) if d != c else 0.0
    
    def _gauss(self, x, c, sigma):
        """Función de membresía gaussiana"""
        if sigma == 0:
            return 1.0 if x == c else 0.0
        return math.exp(-0.5 * ((x - c) / sigma) ** 2)
    
    def _eval_mf(self, var, name, val):
        """Evalúa una función de membresía específica"""
        if var not in self.mfs or name not in self.mfs[var]:
            return 0.0
        mf_type, params = self.mfs[var][name]
        if mf_type == 'triangle':
            return self._triangle(val, *params)
        elif mf_type == 'trapezoid':
            return self._trapezoid(val, *params)
        elif mf_type == 'gaussian':
            return self._gauss(val, *params)
        return 0.0
    
    def fuzzify(self, inputs):
        """Convierte valores crisp a valores difusos"""
        fuzzy = {}
        for var, val in inputs.items():
            if var in self.mfs:
                fuzzy[var] = {}
                for name in self.mfs[var]:
                    fuzzy[var][name] = self._eval_mf(var, name, val)
        return fuzzy
    
    def evaluate(self, inputs, output_range=(0, 1)):
        """
        Evalúa el sistema difuso usando el método del centroide.
        Soporta tanto reglas con consecuentes singleton como con MFs de salida.
        """
        # Paso 1: Fuzzificar entradas
        fuzzy = {}
        for var, val in inputs.items():
            if var in self.mfs:
                fuzzy[var] = {name: self._eval_mf(var, name, val) for name in self.mfs[var]}
        
        # Paso 2: Evaluar reglas y acumular salidas
        outputs = defaultdict(float)
        rule_activations = {}  # Guardar activaciones por nombre de MF de salida
        
        for ant, cons in self.rules:
            # Calcular grado de activación (AND = min)
            activations = []
            valid = True
            for v, mf in ant.items():
                if v in fuzzy and mf in fuzzy[v]:
                    activations.append(fuzzy[v][mf])
                else:
                    valid = False
                    break
            
            if not valid or not activations:
                continue
            
            act = min(activations)
            if act <= 0.0:
                continue
            
            # Aplicar consecuente
            for outvar, outval in cons.items():
                if isinstance(outval, (int, float)):
                    # Consecuente singleton
                    outputs[outvar] = max(outputs[outvar], act * outval)
                else:
                    # Consecuente con nombre de MF
                    rule_activations[outval] = max(rule_activations.get(outval, 0.0), act)
        
        # Si no hay salidas, retornar valor medio
        if not outputs and not rule_activations:
            return (output_range[0] + output_range[1]) / 2
        
        # Paso 3: Defuzzificar por centroide
        num = 0.0
        den = 0.0
        step = (output_range[1] - output_range[0]) / 100.0
        if step <= 0:
            step = 0.01
        
        x = output_range[0]
        while x <= output_range[1]:
            # Calcular membresía en el punto x
            max_mem = 0.0
            
            # Contribución de reglas singleton (usar el valor directamente)
            for outvar, val in outputs.items():
                if isinstance(val, (int, float)):
                    # La membresía es el valor singleton * un factor de cercanía
                    closeness = 1.0 - min(1.0, abs(x - val * (output_range[1] - output_range[0]) - output_range[0]) / (output_range[1] - output_range[0] + 0.001))
                    max_mem = max(max_mem, closeness * val)
            
            # Contribución de MFs de salida
            for mf_name, activation in rule_activations.items():
                if 'output' in self.mfs and mf_name in self.mfs.get('output', {}):
                    mf_val = self._eval_mf('output', mf_name, x)
                    max_mem = max(max_mem, min(mf_val, activation))
            
            num += x * max_mem
            den += max_mem
            x += step
        
        if den > 0:
            return num / den
        else:
            return (output_range[0] + output_range[1]) / 2
    
    def evaluate_simple(self, inputs, output_range=(0, 1)):
        """
        Método simplificado para reglas con consecuentes singleton.
        Más rápido y no requiere MFs de salida.
        """
        fuzzy = self.fuzzify(inputs)
        
        total_weight = 0.0
        weighted_sum = 0.0
        
        for antecedent, consequent in self.rules:
            # Calcular grado de activación (AND = min)
            activation = 1.0
            valid = True
            for var, mf_name in antecedent.items():
                if var in fuzzy and mf_name in fuzzy[var]:
                    activation = min(activation, fuzzy[var][mf_name])
                else:
                    valid = False
                    break
            
            if not valid or activation <= 0.0:
                continue
            
            # Acumular para defuzzificación por media ponderada
            for outvar, outval in consequent.items():
                if isinstance(outval, (int, float)):
                    # Mapear outval (0-1) al rango de salida
                    mapped_value = output_range[0] + outval * (output_range[1] - output_range[0])
                    weighted_sum += activation * mapped_value
                    total_weight += activation
        
        if total_weight > 0:
            return weighted_sum / total_weight
        else:
            return (output_range[0] + output_range[1]) / 2
    
    def clear_rules(self):
        """Elimina todas las reglas"""
        self.rules.clear()
    
    def clear_mfs(self):
        """Elimina todas las funciones de membresía"""
        self.mfs.clear()
        self.outputs.clear()
    
    def get_info(self):
        """Obtiene información del controlador difuso"""
        return {
            'variables': list(self.mfs.keys()),
            'rules_count': len(self.rules),
            'outputs': list(self.outputs.keys()),
            'mfs_per_variable': {k: len(v) for k, v in self.mfs.items()}
        }

class KalmanFilter:
    def __init__(self, state_dim, obs_dim):
        self.n = state_dim
        self.m = obs_dim
        if HAS_NUMPY:
            self.x = np.zeros(state_dim)
            self.P = np.eye(state_dim)
            self.Q = np.eye(state_dim) * 0.01
            self.R = np.eye(obs_dim) * 0.1
            self.A = np.eye(state_dim)
            self.H = np.eye(obs_dim, state_dim)
        else:
            self.x = [0.0] * state_dim
            self.P = [[1.0 if i == j else 0.0 for j in range(state_dim)] for i in range(state_dim)]
            self.Q = [[0.01 if i == j else 0.0 for j in range(state_dim)] for i in range(state_dim)]
            self.R = [[0.1 if i == j else 0.0 for j in range(obs_dim)] for i in range(obs_dim)]
            self.A = [[1.0 if i == j else 0.0 for j in range(state_dim)] for i in range(state_dim)]
            self.H = [[1.0 if i == j else 0.0 for j in range(state_dim)] for i in range(obs_dim)]
    
    def predict(self):
        """Predice el siguiente estado"""
        if HAS_NUMPY:
            self.x = self.A @ self.x
            self.P = self.A @ self.P @ self.A.T + self.Q
        else:
            new_x = [sum(self.A[i][j] * self.x[j] for j in range(self.n)) for i in range(self.n)]
            self.x = new_x
            # Actualización simplificada de P
            for i in range(self.n):
                for j in range(self.n):
                    self.P[i][j] = sum(self.A[i][k] * sum(self.P[k][l] * self.A[j][l] for l in range(self.n)) for k in range(self.n)) + self.Q[i][j]
    
    def update(self, z):
        """Actualiza el estado con una observación"""
        if HAS_NUMPY:
            y = np.array(z) - self.H @ self.x
            S = self.H @ self.P @ self.H.T + self.R
            K = self.P @ self.H.T @ np.linalg.inv(S)
            self.x = self.x + K @ y
            self.P = (np.eye(self.n) - K @ self.H) @ self.P
        else:
            # Actualización simplificada
            for i in range(min(self.n, len(z))):
                innovation = z[i] - sum(self.H[i][j] * self.x[j] for j in range(self.n))
                self.x[i] += 0.1 * innovation
    
    def get_state(self):
        """Obtiene el estado actual"""
        return self.x
    
    def get_covariance(self):
        """Obtiene la matriz de covarianza"""
        return self.P
    
    def reset(self):
        """Reinicia el filtro"""
        if HAS_NUMPY:
            self.x = np.zeros(self.n)
            self.P = np.eye(self.n)
        else:
            self.x = [0.0] * self.n
            self.P = [[1.0 if i == j else 0.0 for j in range(self.n)] for i in range(self.n)]
    
    def save(self, path):
        """Guarda el estado del filtro"""
        data = {'x': self.x, 'P': self.P, 'n': self.n, 'm': self.m}
        with open(path, 'wb') as f:
            pickle.dump(data, f)
    
    def load(self, path):
        """Carga el estado del filtro"""
        with open(path, 'rb') as f:
            data = pickle.load(f)
        self.x = data['x']
        self.P = data['P']
        self.n = data.get('n', self.n)
        self.m = data.get('m', self.m)

class GeneticOptimizer:
    def __init__(self, param_bounds, pop_size=50, elite_ratio=0.1, mut_rate=0.1, cross_rate=0.7, gens=100):
        self.bounds = param_bounds
        self.pop_size = pop_size
        self.elite = int(pop_size * elite_ratio)
        self.mut = mut_rate
        self.cross = cross_rate
        self.gens = gens
        self.best_fitness_history = []
        self.avg_fitness_history = []
    
    def _create_individual(self):
        """Crea un individuo aleatorio"""
        ind = {}
        for p, (lo, hi) in self.bounds.items():
            if isinstance(lo, int) and isinstance(hi, int):
                ind[p] = random.randint(lo, hi)
            else:
                ind[p] = random.uniform(lo, hi)
        return ind
    
    def _mutate(self, ind):
        """Aplica mutación a un individuo"""
        for p in ind:
            if random.random() < self.mut:
                lo, hi = self.bounds[p]
                if isinstance(lo, int) and isinstance(hi, int):
                    ind[p] = int(random.gauss(ind[p], (hi - lo) / 10))
                    ind[p] = max(lo, min(hi, ind[p]))
                else:
                    ind[p] = random.gauss(ind[p], (hi - lo) / 10)
                    ind[p] = max(lo, min(hi, ind[p]))
        return ind
    
    def _crossover(self, p1, p2):
        """Aplica cruce entre dos padres"""
        if random.random() < self.cross:
            c1, c2 = p1.copy(), p2.copy()
            point = random.choice(list(p1.keys()))
            crossed = False
            for k in p1:
                if k == point:
                    crossed = True
                if crossed:
                    c1[k], c2[k] = p2[k], p1[k]
            return c1, c2
        else:
            return p1.copy(), p2.copy()
    
    def _tournament_selection(self, pop, fits, k=3):
        """Selecciona un individuo por torneo"""
        selected = []
        for _ in range(len(pop)):
            idx = random.sample(range(len(pop)), k)
            best_idx = max(idx, key=lambda i: fits[i])
            selected.append(pop[best_idx].copy())
        return selected
    
    def optimize(self, fitness_fn, verbose=False):
        """Ejecuta la optimización genética"""
        # Inicializar población
        pop = [self._create_individual() for _ in range(self.pop_size)]
        
        best_ind = None
        best_fit = -float('inf')
        self.best_fitness_history = []
        self.avg_fitness_history = []
        
        for gen in range(self.gens):
            # Evaluar fitness
            fits = [fitness_fn(ind) for ind in pop]
            
            # Registrar estadísticas
            gen_best = max(fits)
            gen_avg = sum(fits) / len(fits)
            self.best_fitness_history.append(gen_best)
            self.avg_fitness_history.append(gen_avg)
            
            # Actualizar mejor global
            for i, f in enumerate(fits):
                if f > best_fit:
                    best_fit = f
                    best_ind = pop[i].copy()
            
            # Selección por torneo
            selected = self._tournament_selection(pop, fits, k=3)
            
            # Elitismo
            new_pop = selected[:self.elite]
            
            # Generar nueva población
            while len(new_pop) < self.pop_size:
                p1, p2 = random.sample(selected, 2)
                c1, c2 = self._crossover(p1, p2)
                c1 = self._mutate(c1)
                c2 = self._mutate(c2)
                new_pop.append(c1)
                if len(new_pop) < self.pop_size:
                    new_pop.append(c2)
            
            pop = new_pop[:self.pop_size]
            
            if verbose and gen % max(1, self.gens // 10) == 0:
                log.info(f"Gen {gen}: best={best_fit:.4f}, avg={gen_avg:.4f}")
        
        return best_ind, best_fit
    
    def get_history(self):
        """Retorna el historial de fitness"""
        return {
            'best': self.best_fitness_history,
            'avg': self.avg_fitness_history
        }

class HyperNumberAdvanced:
    def __init__(self, val=0.0):
        self.sign = 1 if val >= 0 else -1
        self.val = abs(float(val))
        self.mode = "real"
        self.log10 = 0.0
    
    def add(self, x):
        """Suma un valor al HyperNumber"""
        if isinstance(x, HyperNumberAdvanced):
            x = x.to_float()
        xs = 1 if x >= 0 else -1
        x = abs(x)
        if self.mode == "real":
            new = self.sign * self.val + xs * x
            self.sign = 1 if new >= 0 else -1
            self.val = abs(new)
        else:
            self.val += x
    
    def subtract(self, x):
        """Resta un valor al HyperNumber"""
        if isinstance(x, HyperNumberAdvanced):
            x = x.to_float()
        self.add(-x)
    
    def multiply(self, x):
        """Multiplica el HyperNumber por un valor"""
        if isinstance(x, HyperNumberAdvanced):
            x = x.to_float()
        if x < 0:
            self.sign *= -1
            x = abs(x)
        if self.mode == "real":
            self.val *= x
        else:
            self.log10 += math.log10(x) if x > 0 else 0
    
    def divide(self, x):
        """Divide el HyperNumber por un valor"""
        if isinstance(x, HyperNumberAdvanced):
            x = x.to_float()
        if x == 0:
            raise ZeroDivisionError("No se puede dividir por cero")
        self.multiply(1.0 / x)
    
    def power(self, exp):
        """Eleva el HyperNumber a una potencia"""
        val = self.to_float()
        result = val ** exp
        self.sign = 1 if result >= 0 else -1
        self.val = abs(result)
    
    def to_float(self):
        """Convierte a float estándar"""
        if self.mode == "real":
            return self.sign * self.val
        else:
            return self.sign * (10 ** self.log10)
    
    def to_int(self):
        """Convierte a entero"""
        return int(self.to_float())
    
    def display(self):
        """Representación legible"""
        if self.mode == "real":
            return f"{self.sign * self.val:.6g}"
        else:
            return f"{'-' if self.sign < 0 else ''}~10^{self.log10:.6f}"
    
    def copy(self):
        """Crea una copia del HyperNumber"""
        new = HyperNumberAdvanced()
        new.sign = self.sign
        new.val = self.val
        new.mode = self.mode
        new.log10 = self.log10
        return new
    
    def __repr__(self):
        return f"HyperNumberAdvanced({self.display()})"
    
    def __add__(self, other):
        result = self.copy()
        result.add(other)
        return result
    
    def __sub__(self, other):
        result = self.copy()
        result.subtract(other)
        return result
    
    def __mul__(self, other):
        result = self.copy()
        result.multiply(other)
        return result
    
    def __truediv__(self, other):
        result = self.copy()
        result.divide(other)
        return result
    
    def __neg__(self):
        result = self.copy()
        result.sign *= -1
        return result
    
    def __abs__(self):
        result = self.copy()
        result.sign = 1
        return result
    
    def __eq__(self, other):
        if isinstance(other, HyperNumberAdvanced):
            return abs(self.to_float() - other.to_float()) < 1e-10
        return abs(self.to_float() - float(other)) < 1e-10
    
    def __lt__(self, other):
        if isinstance(other, HyperNumberAdvanced):
            return self.to_float() < other.to_float()
        return self.to_float() < float(other)
    
    def __gt__(self, other):
        if isinstance(other, HyperNumberAdvanced):
            return self.to_float() > other.to_float()
        return self.to_float() > float(other)

# ============================================================================
# 11. DEMAND PREDICTOR (simple basado en hora y ubicación)
# ============================================================================
class DemandPredictor:
    def __init__(self):
        self.hourly_weights = [1.0]*24
        # Patrón típico de demanda: picos en 8-9 y 17-19
        for h in range(7,10): self.hourly_weights[h] = 1.5
        for h in range(17,20): self.hourly_weights[h] = 1.8
        for h in range(0,5): self.hourly_weights[h] = 0.3
        self.location_multipliers = defaultdict(lambda: 1.0)
    def set_location_multiplier(self, lat_lon_key, multiplier):
        self.location_multipliers[lat_lon_key] = multiplier
    def predict(self, lat, lon):
        now = datetime.now()
        hour = now.hour
        base = self.hourly_weights[hour]
        # discretizar ubicación en celdas de 0.1 grados
        key = (round(lat,1), round(lon,1))
        loc_factor = self.location_multipliers.get(key, 1.0)
        return base * loc_factor

# ============================================================================
# 12. CLASE PRINCIPAL (SymbiosisGPS) con todas las integraciones
# ============================================================================
class SymbiosisGPS:
    def __init__(self, use_real_gps=False, persist_dir="./gps_symbiosis_data"):
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.registry = SharedDataRegistry()
        self.gps = GPSCore(create_gps_provider(use_real=use_real_gps), use_kalman=True)
        self.gps.start()
        self.routing_graph = RouteGraph()
        self.routing = RoutingEngine(self.routing_graph)
        self.matching = MatchingEngine()
        self.network_monitor = NetworkMonitor()
        self.network_monitor.start()
        self.demand_predictor = DemandPredictor()
        self.fuzzy = FuzzyLogicController()
        self._setup_fuzzy()
        self.rl = None  # se inicializará con dimensiones cuando se conozca el estado
        self.last_state = None
        # Cargar datos persistentes
        self._load_all()
        atexit.register(self.shutdown)
    
    def _setup_fuzzy(self):
        self.fuzzy.add_mf('demand', 'low', 'triangle', (0, 0.3, 0.5))
        self.fuzzy.add_mf('demand', 'high', 'triangle', (0.5, 0.7, 1))
        self.fuzzy.add_rule({'demand': 'high'}, {'decision': 1.0})
        self.fuzzy.add_rule({'demand': 'low'}, {'decision': 0.0})
    
    def _ensure_persist_dir(self):
        """Asegura que el directorio de persistencia existe"""
        if not self.persist_dir.exists():
            self.persist_dir.mkdir(parents=True, exist_ok=True)
    
    def _load_all(self):
        """Carga todos los datos persistentes"""
        # Cargar geocercas
        geofence_file = self.persist_dir / "geofences.json"
        if geofence_file.exists():
            try:
                self.gps.geofence.load(str(geofence_file))
                log.info(f"Geocercas cargadas desde {geofence_file}")
            except Exception as e:
                log.warning(f"No se pudieron cargar geocercas: {e}")
    
    def _save_all(self):
        """Guarda todos los datos persistentes"""
        self._ensure_persist_dir()
        
        # Guardar geocercas
        try:
            geofence_file = self.persist_dir / "geofences.json"
            self.gps.geofence.save(str(geofence_file))
        except Exception as e:
            log.warning(f"No se pudieron guardar geocercas: {e}")
        
        # Guardar modelo RL
        if self.rl:
            try:
                rl_file = self.persist_dir / "ensemble_rl.pkl"
                self.rl.save(str(rl_file))
                log.info(f"Modelo RL guardado en {rl_file}")
            except Exception as e:
                log.warning(f"No se pudo guardar modelo RL: {e}")
    
    def get_location(self):
        """Obtiene la ubicación actual"""
        return self.gps.get_location()
    
    def update_external_location(self, lat: float, lon: float) -> bool:
        """
        Actualiza la ubicación desde una fuente externa (ej: frontend).
        Esto permite que el GPS Symbiosis use las mismas coordenadas que el frontend.
        
        Args:
            lat: Latitud en grados decimales
            lon: Longitud en grados decimales
        
        Returns:
            bool: True si se actualizó correctamente, False en caso contrario
        """
        try:
            # Validar coordenadas
            if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
                log.error(f"[GPS] Coordenadas inválidas: lat={lat}, lon={lon}", "ERROR")
                return False
            
            if lat < -90 or lat > 90 or lon < -180 or lon > 180:
                log.error(f"[GPS] Coordenadas fuera de rango: lat={lat}, lon={lon}", "ERROR")
                return False
            
            # Crear objeto Coordinate
            coord = Coordinate(lat, lon)
            
            # Actualizar la última coordenada del GPS Core
            if hasattr(self.gps, '_last_coord'):
                self.gps._last_coord = coord
            else:
                # Si GPSCore no tiene _last_coord, intentar con el provider
                if hasattr(self.gps, 'provider') and hasattr(self.gps.provider, 'current'):
                    self.gps.provider.current = coord
            
            # Actualizar geocercas
            if hasattr(self.gps, 'geofence') and self.gps.geofence:
                self.gps.geofence.update(coord)
            
            # Notificar a los listeners registrados
            if hasattr(self.gps, '_listeners') and self.gps._listeners:
                for cb in self.gps._listeners:
                    try:
                        cb(coord)
                    except Exception as e:
                        log.debug(f"Error en callback de ubicación: {e}")
            
            # Actualizar el registro compartido
            if hasattr(self, 'registry') and self.registry:
                self.registry.set("gps:ubicacion_externa", {
                    "latitude": lat,
                    "longitude": lon,
                    "timestamp": time.time(),
                    "source": "external"
                })
            
            log.info(f"[GPS] Ubicación externa actualizada: {lat:.6f}, {lon:.6f}", "GPS")
            return True
            
        except Exception as e:
            log.error(f"[GPS] Error actualizando ubicación externa: {e}", "ERROR")
            traceback.print_exc()
            return False
    
    def add_node(self, node_id, lat, lon):
        """Agrega un nodo al grafo de enrutamiento"""
        self.routing_graph.add_node(Node(node_id, lat, lon))
    
    def add_edge(self, edge_id, from_node, to_node, dist_km, time_min):
        """Agrega una arista al grafo de enrutamiento"""
        self.routing_graph.add_edge(Edge(edge_id, from_node, to_node, dist_km, time_min))
    
    def route(self, from_node, to_node, objective="time"):
        """Calcula la ruta más corta entre dos nodos"""
        nodes, edges, cost = self.routing.shortest_path(from_node, to_node, objective)
        return nodes, edges, cost
    
    def init_rl(self, state_dim, action_dim):
        """Inicializa el módulo de aprendizaje por refuerzo"""
        self.rl = EnsembleRL(state_dim, action_dim, use_curiosity=True, use_episodic=True, use_meta=True)
        # Intentar cargar modelo existente
        rl_file = self.persist_dir / "ensemble_rl.pkl"
        if rl_file.exists() and rl_file.stat().st_size > 0:
            try:
                self.rl.load(str(rl_file))
                log.info("Modelo RL cargado exitosamente")
            except Exception as e:
                log.warning(f"No se pudo cargar modelo RL: {e}. Se usará modelo nuevo.")
        else:
            log.info("No se encontró modelo RL guardado. Se usará modelo nuevo.")
    
    def get_current_state_vector(self) -> List[float]:
        """Construye el vector de estado actual para RL"""
        loc = self.gps.get_location()
        net = self.registry.get("network:status", {})
        demand = self.demand_predictor.predict(
            loc.latitude if loc else 0, 
            loc.longitude if loc else 0
        )
        state = [
            loc.latitude / 180.0 if loc else 0,
            loc.longitude / 360.0 if loc else 0,
            self.gps.get_speed() / 120.0,
            demand,
            float(net.get("connected", 0)),
            float(net.get("latency_ms", 0)) / 1000.0
        ]
        return state[:6]
    
    def rl_action(self, state=None):
        """Selecciona una acción usando RL"""
        if self.rl is None:
            return 0
        if state is None:
            state = self.get_current_state_vector()
        return self.rl.select_action(state)
    
    def rl_update(self, state, action, reward, next_state, done):
        """Actualiza el modelo RL con una experiencia"""
        if self.rl is None:
            return
        self.rl.update(state, action, reward, next_state, done)
    
    def save_rl_model(self):
        """Guarda explícitamente el modelo RL"""
        self._ensure_persist_dir()
        if self.rl:
            rl_file = self.persist_dir / "ensemble_rl.pkl"
            self.rl.save(str(rl_file))
            log.info(f"Modelo RL guardado en {rl_file}")
    
    def add_geofence(self, center_lat, center_lon, radius_km, fence_id=None):
        """Agrega una geocerca al sistema GPS"""
        if fence_id is None:
            fence_id = str(uuid.uuid4())[:8]
        center = Coordinate(center_lat, center_lon)
        fence = Geofence(fence_id, center, radius_km)
        self.gps.add_geofence(fence)
        return fence_id
    
    def get_system_status(self) -> Dict[str, Any]:
        """Obtiene el estado completo del sistema"""
        loc = self.gps.get_location()
        net = self.registry.get("network:status", {})
        external_loc = self.registry.get("gps:ubicacion_externa", {})
        
        return {
            "location": {
                "latitude": loc.latitude if loc else None,
                "longitude": loc.longitude if loc else None,
                "speed_kmh": self.gps.get_speed()
            },
            "external_location": external_loc,
            "network": net,
            "geofences": self.gps.geofence.get_statistics(),
            "rl_initialized": self.rl is not None,
            "rl_step": self.rl.step if self.rl else 0
        }
    
    def force_gps_update(self) -> bool:
        """
        Fuerza una actualización inmediata del GPS.
        Útil cuando se reciben coordenadas externas y queremos sincronizar.
        """
        try:
            # Obtener ubicación actual del provider
            loc = self.gps.provider.get_location()
            if loc:
                self.update_external_location(loc.latitude, loc.longitude)
                return True
            return False
        except Exception as e:
            log.error(f"Error forzando actualización GPS: {e}", "ERROR")
            return False
    
    def shutdown(self):
        """Apaga el sistema y guarda datos persistentes"""
        log.info("Iniciando apagado de SymbiosisGPS...")
        self.gps.stop()
        self.network_monitor.stop()
        self._save_all()
        log.info("SymbiosisGPS shut down.")

# ============================================================================
# 13. RADAR PROFESIONAL – VISUALIZACIÓN EN TIEMPO REAL
# ============================================================================
class RadarDisplay:
    """
    Radar circular profesional en terminal.
    Muestra la posición del usuario (centro) y los objetivos cercanos
    en coordenadas polares (distancia + rumbo).
    """
    def __init__(
        self,
        gps_core: 'GPSCore',
        targets: List[Coordinate] = None,
        max_range_km: float = 20.0,
        update_interval: float = 1.0,
        radius_chars: int = 20,          # radio del círculo en caracteres
        use_unicode: bool = True,
        show_compass: bool = True
    ):
        self.gps = gps_core
        self.targets = targets or []
        self.max_range = max_range_km
        self.interval = update_interval
        self.radius = radius_chars
        self.unicode = use_unicode
        self.show_compass = show_compass

        self._running = False
        self._stop_event = threading.Event()
        self._thread = None
        self.heading = 0.0  # grados desde el norte, 0=N, 90=E

        # Símbolos gráficos
        self.SYM_CENTER = "⊕" if use_unicode else "+"
        self.SYM_TARGET = "●" if use_unicode else "o"
        self.SYM_BEAM = "█" if use_unicode else "#"
        self.SYM_RING = "·" if use_unicode else "."
        self.SYM_COMPASS_N = "N"
        self.SYM_COMPASS_S = "S"
        self.SYM_COMPASS_E = "E"
        self.SYM_COMPASS_W = "W"

    def _clear_screen(self):
        """Limpia la pantalla con códigos ANSI."""
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()

    def _move_cursor(self, row: int, col: int):
        """Mueve el cursor a una posición (fila, columna)."""
        sys.stdout.write(f"\033[{row};{col}H")
        sys.stdout.flush()

    def set_heading(self, heading_degrees: float):
        """Establece el rumbo manualmente (0=N, 90=E)."""
        self.heading = heading_degrees % 360

    def update_heading_from_gps(self):
        """Calcula el rumbo aproximado usando dos últimas ubicaciones (requiere historial)."""
        # GPSCore no almacena historial; se podría añadir en get_location().
        # Por simplicidad, aquí asumimos que el rumbo se actualiza externamente.
        pass

    def add_target(self, coord: Coordinate):
        """Añade un punto al radar."""
        self.targets.append(coord)

    def remove_target(self, coord: Coordinate):
        """Elimina un punto del radar."""
        self.targets = [t for t in self.targets if t != coord]

    def set_targets(self, coords: List[Coordinate]):
        """Reemplaza todos los objetivos."""
        self.targets = coords.copy()

    def _world_to_screen(self, distance_km: float, bearing_deg: float) -> Tuple[int, int]:
        """
        Convierte distancia y rumbo (desde el centro) a coordenadas de caracteres.
        Retorna (columna, fila) en la cuadrícula del radar.
        """
        # Mapear distancia a radio de la pantalla
        ratio = distance_km / self.max_range if self.max_range > 0 else 0
        if ratio > 1.0:
            return None  # fuera de rango
        screen_dist = ratio * self.radius

        # Calcular ángulo respecto al norte (0=N, en el sentido de las agujas del reloj)
        # En pantalla: 0° = arriba (N), 90° = derecha (E)
        angle_rad = math.radians(90 - bearing_deg)  # convertir a coordenadas matemáticas
        col = int(screen_dist * math.cos(angle_rad))
        fila = int(-screen_dist * math.sin(angle_rad))  # negativo porque las filas van hacia abajo
        return col, fila

    def _build_frame(self, user_coord: Coordinate) -> str:
        """Construye una cadena con el dibujo completo del radar."""
        size = self.radius * 2 + 1
        # Inicializar cuadrícula con espacios
        grid = [[' ' for _ in range(size)] for _ in range(size)]
        # Centro del radar
        center = self.radius

        # Dibujar círculos concéntricos (anillos)
        for r_pct in [0.25, 0.5, 0.75, 1.0]:
            r = int(self.radius * r_pct)
            if r == 0:
                continue
            for angle in range(0, 360, max(1, int(360 / (2 * math.pi * r * 2)))):
                ang_rad = math.radians(angle)
                col = center + int(r * math.cos(ang_rad))
                fila = center + int(r * math.sin(ang_rad))
                if 0 <= fila < size and 0 <= col < size:
                    grid[fila][col] = self.SYM_RING

        # Dibujar líneas cardinales (N, S, E, W) si se muestra brújula
        if self.show_compass:
            # N
            grid[center][center] = self.SYM_CENTER
            grid[0][center] = self.SYM_COMPASS_N
            grid[-1][center] = self.SYM_COMPASS_S
            grid[center][0] = self.SYM_COMPASS_W
            grid[center][-1] = self.SYM_COMPASS_E

        # Dibujar haz del rumbo (opcional, se puede omitir si no hay heading)
        if self.heading is not None:
            # Línea desde el centro en dirección del heading
            for step in range(1, self.radius + 1):
                ratio = step / self.radius
                ang_rad = math.radians(90 - self.heading)  # convertir
                col = center + int(step * math.cos(ang_rad))
                fila = center + int(-step * math.sin(ang_rad))
                if 0 <= fila < size and 0 <= col < size:
                    if grid[fila][col] in (' ', self.SYM_RING):
                        grid[fila][col] = self.SYM_BEAM

        # Dibujar objetivos
        for target in self.targets:
            dist = user_coord.distance_to(target)
            bearing = user_coord.bearing_to(target)
            pos = self._world_to_screen(dist, bearing)
            if pos is not None:
                col, fila = center + pos[0], center + pos[1]
                if 0 <= fila < size and 0 <= col < size:
                    grid[fila][col] = self.SYM_TARGET

        # Colocar el centro del radar sobre el centro (si no se dibujó ya)
        if grid[center][center] == ' ':
            grid[center][center] = self.SYM_CENTER

        # Convertir cuadrícula a string
        frame_lines = [''.join(row) for row in grid]

        # Añadir información textual (encabezado y pie)
        lat = user_coord.latitude
        lon = user_coord.longitude
        speed = self.gps.get_speed()
        header = f" RADAR PROFESIONAL  |  Lat: {lat:.6f}  |  Lon: {lon:.6f}  |  Vel: {speed:.1f} km/h  |  Objetivos: {len(self.targets)}"
        footer = f" Rango: {self.max_range} km  |  Heading: {self.heading:.0f}°  |  Presiona Ctrl+C para salir"
        bar = "─" * len(header) if self.unicode else "-" * len(header)

        output = f"{bar}\n{header}\n{bar}\n"
        for line in frame_lines:
            output += f" {line}\n"
        output += f"{bar}\n{footer}\n{bar}"

        return output

    def _draw_loop(self):
        """Bucle principal que actualiza el radar en la terminal."""
        while not self._stop_event.is_set():
            loc = self.gps.get_location()
            if loc is None:
                time.sleep(0.5)
                continue
            frame = self._build_frame(loc)
            self._clear_screen()
            sys.stdout.write(frame)
            sys.stdout.flush()
            time.sleep(self.interval)

    def start(self):
        """Inicia el radar en un hilo aparte (la terminal se limpia automáticamente)."""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._draw_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Detiene el radar."""
        self._running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        # Limpiar pantalla al salir
        self._clear_screen()
# ============================================================================
# PRUEBAS INTEGRADAS (solo se ejecutan si el módulo se corre directamente)
# ============================================================================
if __name__ == "__main__":
    import shutil
    
    logging.basicConfig(level=logging.INFO)
    log.info("=" * 60)
    log.info("=== INICIANDO PRUEBAS DE GPS SYMBIOSIS ===")
    log.info("=" * 60)
    
    # Limpiar datos persistentes de pruebas anteriores
    persist_dir = Path("./gps_symbiosis_data")
    if persist_dir.exists():
        try:
            shutil.rmtree(str(persist_dir))
            log.info("Directorio de pruebas anterior eliminado")
        except Exception as e:
            log.warning(f"No se pudo eliminar directorio anterior: {e}")
    
    # Contadores para resumen final
    pruebas_ok = 0
    pruebas_fallo = 0
    resultados = {}
    
    # ================================================================
    # 1. PRUEBA DE GPS
    # ================================================================
    log.info("--- Prueba 1: GPS ---")
    try:
        gps = GPSCore()
        gps.start()
        time.sleep(2)
        loc = gps.get_location()
        log.info(f"  Ubicación GPS: {loc}")
        if loc:
            log.info(f"  Latitud: {loc.latitude:.6f}")
            log.info(f"  Longitud: {loc.longitude:.6f}")
            log.info(f"  Velocidad: {gps.get_speed():.2f} km/h")
            # Probar distancia a un punto conocido
            target = Coordinate(0.1, 0.1)
            dist = gps.distance_to(target)
            log.info(f"  Distancia a (0.1, 0.1): {dist:.4f} km")
            # Probar bearing
            bearing = gps.bearing_to(target)
            log.info(f"  Rumbo a (0.1, 0.1): {bearing:.1f}°")
        gps.stop()
        log.info("  Prueba GPS: OK")
        pruebas_ok += 1
        resultados['GPS'] = 'OK'
    except Exception as e:
        log.error(f"  Prueba GPS fallida: {e}")
        traceback.print_exc()
        pruebas_fallo += 1
        resultados['GPS'] = f'FALLO: {e}'
    
    # ================================================================
    # 2. PRUEBA DE GEOCERCA
    # ================================================================
    log.info("--- Prueba 2: Geocercas ---")
    try:
        # Crear directorio para pruebas si no existe
        persist_dir.mkdir(exist_ok=True)
        
        gps2 = GPSCore()
        gps2.start()
        time.sleep(2)
        
        # Crear geocerca
        center = Coordinate(0, 0)
        fence = Geofence("test_fence", center, 10)
        gps2.geofence.add(fence)
        log.info(f"  Geocerca creada: {fence}")
        
        # Verificar área y perímetro
        log.info(f"  Área: {fence.get_area_km2():.2f} km²")
        log.info(f"  Perímetro: {fence.get_perimeter_km():.2f} km")
        
        # Probar metadatos
        fence.set_metadata("color", "red")
        fence.set_metadata("priority", 1)
        log.info(f"  Metadatos: color={fence.get_metadata('color')}, priority={fence.get_metadata('priority')}")
        
        # Registrar callbacks con contador de eventos
        event_count = {'enter': 0, 'exit': 0}
        
        def on_enter_exit_callback(fid, inside):
            log.info(f"  Geocerca {fid}: {'DENTRO' if inside else 'FUERA'}")
        
        def on_enter_callback(fid):
            event_count['enter'] += 1
            log.info(f"  [EVENTO] Entrada a geocerca {fid} (count={event_count['enter']})")
        
        def on_exit_callback(fid):
            event_count['exit'] += 1
            log.info(f"  [EVENTO] Salida de geocerca {fid} (count={event_count['exit']})")
        
        gps2.geofence.on_enter_exit("test_fence", on_enter_exit_callback)
        gps2.geofence.on_enter("test_fence", on_enter_callback)
        gps2.geofence.on_exit("test_fence", on_exit_callback)
        
        # Actualizar múltiples veces para probar cambios de estado
        for i in range(5):
            loc = gps2.get_location()
            if loc:
                states = gps2.geofence.update(loc)
                inside = states.get('test_fence', False)
                log.info(f"  Update {i+1}: ({loc.latitude:.6f}, {loc.longitude:.6f}) -> {'DENTRO' if inside else 'FUERA'}")
            time.sleep(0.5)
        
        # Probar estadísticas
        stats = gps2.geofence.get_statistics()
        log.info(f"  Estadísticas: {stats['total_fences']} geocercas, "
                 f"{stats['active_listeners']} listeners")
        if 'test_fence' in stats['fences']:
            fstats = stats['fences']['test_fence']
            log.info(f"  Trigger count: {fstats['trigger_count']}")
            log.info(f"  Currently inside: {fstats['currently_inside']}")
        
        # Probar guardado y carga
        test_path = str(persist_dir / "test_geofences.json")
        gps2.geofence.save(test_path)
        log.info(f"  Geocercas guardadas en {test_path}")
        
        # Verificar que el archivo existe
        if os.path.exists(test_path):
            file_size = os.path.getsize(test_path)
            log.info(f"  Archivo guardado: {file_size} bytes")
        
        # Crear nuevo manager y cargar
        new_manager = GeofenceManager()
        new_manager.load(test_path)
        log.info(f"  Geocercas cargadas: {len(new_manager)}")
        
        # Verificar que la geocerca cargada funciona
        test_coord = Coordinate(0.05, 0.05)
        active = new_manager.get_active_fences(test_coord)
        log.info(f"  Geocercas activas en (0.05, 0.05): {len(active)}")
        
        gps2.stop()
        log.info("  Prueba Geocercas: OK")
        pruebas_ok += 1
        resultados['Geocercas'] = 'OK'
    except Exception as e:
        log.error(f"  Prueba Geocercas fallida: {e}")
        traceback.print_exc()
        pruebas_fallo += 1
        resultados['Geocercas'] = f'FALLO: {e}'
    
    # ================================================================
    # 3. PRUEBA DE ENRUTAMIENTO
    # ================================================================
    log.info("--- Prueba 3: Enrutamiento ---")
    try:
        graph = RouteGraph()
        graph.add_node(Node("A", 0, 0))
        graph.add_node(Node("B", 1, 0))
        graph.add_node(Node("C", 2, 1))
        graph.add_node(Node("D", 1, 2))
        
        graph.add_edge(Edge("AB", "A", "B", 111.0, 60.0))
        graph.add_edge(Edge("BC", "B", "C", 150.0, 90.0))
        graph.add_edge(Edge("BD", "B", "D", 130.0, 75.0))
        graph.add_edge(Edge("CD", "C", "D", 120.0, 70.0))
        graph.add_edge(Edge("AD", "A", "D", 200.0, 120.0))
        
        engine = RoutingEngine(graph)
        
        # Ruta A -> C (debería ser A->B->C)
        nodes, edges, cost = engine.shortest_path("A", "C", objective="time")
        log.info(f"  Ruta A->C (tiempo): {nodes}, costo={cost:.1f} min")
        
        # Ruta A -> D por distancia
        nodes, edges, cost = engine.shortest_path("A", "D", objective="distance")
        log.info(f"  Ruta A->D (distancia): {nodes}, costo={cost:.1f} km")
        
        # Ruta con Dijkstra
        nodes, edges, cost = engine.shortest_path("A", "C", algorithm="dijkstra")
        log.info(f"  Ruta A->C (Dijkstra): {nodes}, costo={cost:.1f} min")
        
        # Ruta A* sin caché
        nodes, edges, cost = engine.shortest_path("A", "D", use_cache=False)
        log.info(f"  Ruta A->D (A* sin caché): {nodes}, costo={cost:.1f}")
        
        # Ruta inválida
        nodes, edges, cost = engine.shortest_path("A", "Z")
        log.info(f"  Ruta A->Z (inválida): nodos={nodes}, costo={cost}")
        assert nodes == [], "Ruta inválida debería retornar lista vacía"
        
        # Estadísticas de caché
        log.info(f"  Cache hits: {engine.cache_hits}, misses: {engine.cache_misses}")
        
        log.info("  Prueba Enrutamiento: OK")
        pruebas_ok += 1
        resultados['Enrutamiento'] = 'OK'
    except Exception as e:
        log.error(f"  Prueba Enrutamiento fallida: {e}")
        traceback.print_exc()
        pruebas_fallo += 1
        resultados['Enrutamiento'] = f'FALLO: {e}'
    
    # ================================================================
    # 4. PRUEBA DE MATCHING
    # ================================================================
    log.info("--- Prueba 4: Matching ---")
    try:
        match_eng = MatchingEngine()
        
        # Calcular similitud entre agentes
        agent_a = {"id": "a", "preferences": {"price": 0.8, "quality": 0.9}, 
                   "rating": 0.9, "location": (0, 0)}
        agent_b = {"id": "b", "preferences": {"price": 0.7, "quality": 0.8}, 
                   "rating": 0.8, "location": (0.1, 0.1)}
        agent_c = {"id": "c", "preferences": {"price": 0.2, "quality": 0.3}, 
                   "rating": 0.3, "location": (10, 10)}
        
        sim_ab, breakdown_ab = match_eng.compute_similarity(agent_a, agent_b)
        log.info(f"  Similitud A-B: {sim_ab:.3f}")
        log.info(f"    Desglose: {breakdown_ab}")
        
        sim_ac, breakdown_ac = match_eng.compute_similarity(agent_a, agent_c)
        log.info(f"  Similitud A-C (lejano): {sim_ac:.3f}")
        log.info(f"    Desglose: {breakdown_ac}")
        
        # Agregar agentes al motor
        match_eng.update_features("a", {"price": 0.8, "quality": 0.9, "rating": 0.9})
        match_eng.update_features("b", {"price": 0.7, "quality": 0.8, "rating": 0.8})
        match_eng.update_features("c", {"price": 0.6, "quality": 0.7, "rating": 0.7})
        match_eng.update_features("d", {"price": 0.9, "quality": 0.95, "rating": 0.95})
        match_eng.update_features("e", {"price": 0.5, "quality": 0.5, "rating": 0.5})
        
        # Obtener recomendaciones
        recommendations = match_eng.get_recommendations("a", top_k=4)
        log.info(f"  Recomendaciones para 'a' (top 4):")
        for agent_id, score in recommendations:
            log.info(f"    {agent_id}: {score:.4f}")
        
        # Probar Top-K con diferentes pesos
        topk = TopKCandidates(k=3)
        candidates = [
            ("x", {"a": 0.8, "b": 0.5}),
            ("y", {"a": 0.9, "b": 0.3}),
            ("z", {"a": 0.7, "b": 0.8}),
            ("w", {"a": 0.85, "b": 0.6}),
            ("v", {"a": 0.95, "b": 0.1})
        ]
        query = {"a": 0.85, "b": 0.5}
        weights = {"a": 0.7, "b": 0.3}
        results = topk.find(query, candidates, weights=weights)
        log.info(f"  Top-K con pesos {weights}:")
        for cid, score in results:
            log.info(f"    {cid}: {score:.4f}")
        
        # Probar GeoMatcher
        geo = GeoMatcher(cell_size_km=10.0)
        agents_coords = {
            "agent1": (0.1, 0.1),
            "agent2": (0.2, 0.2),
            "agent3": (5.0, 5.0),
            "agent4": (0.05, 0.05)
        }
        nearby = geo.nearby(0.0, 0.0, agents_coords, radius_km=30.0)
        log.info(f"  Agentes cercanos a (0,0) en 30km: {[a for a,d in nearby]}")
        
        log.info("  Prueba Matching: OK")
        pruebas_ok += 1
        resultados['Matching'] = 'OK'
    except Exception as e:
        log.error(f"  Prueba Matching fallida: {e}")
        traceback.print_exc()
        pruebas_fallo += 1
        resultados['Matching'] = f'FALLO: {e}'
    
    # ================================================================
    # 5. PRUEBA DE DOUBLE DQN
    # ================================================================
    log.info("--- Prueba 5: Double DQN ---")
    if HAS_NUMPY:
        try:
            dqn = DoubleDQN(4, 2)
            log.info(f"  Épsilon inicial: {dqn.get_epsilon():.4f}")
            
            # Entrenar por 100 pasos
            for i in range(100):
                state = [random.random() for _ in range(4)]
                action = dqn.select_action(state)
                reward = 1.0 if action == 0 else -0.5
                next_state = [random.random() for _ in range(4)]
                dqn.store(state, action, reward, next_state, False)
                if i % 10 == 0:
                    dqn.learn()
            
            progress = dqn.get_training_progress()
            log.info(f"  Progreso final:")
            log.info(f"    Steps: {progress['steps']}")
            log.info(f"    Training steps: {progress['training_steps']}")
            log.info(f"    Épsilon: {progress['epsilon']:.4f}")
            log.info(f"    Memory size: {progress['memory_size']}")
            
            # Probar guardado y carga
            dqn_path = str(persist_dir / "test_dqn.pkl")
            dqn.save(dqn_path)
            
            dqn2 = DoubleDQN(4, 2)
            dqn2.load(dqn_path)
            log.info(f"  DQN cargado - Épsilon: {dqn2.get_epsilon():.4f}")
            
            # Verificar que las predicciones son consistentes
            test_state = [0.5, 0.5, 0.5, 0.5]
            action1 = dqn.select_action(test_state, exploit_only=True)
            action2 = dqn2.select_action(test_state, exploit_only=True)
            log.info(f"  Acción exploit (original): {action1}")
            log.info(f"  Acción exploit (cargado): {action2}")
            
            log.info("  Prueba Double DQN: OK")
            pruebas_ok += 1
            resultados['Double DQN'] = 'OK'
        except Exception as e:
            log.error(f"  Prueba Double DQN fallida: {e}")
            traceback.print_exc()
            pruebas_fallo += 1
            resultados['Double DQN'] = f'FALLO: {e}'
    else:
        log.info("  Double DQN sin numpy: omitido (requiere numpy)")
        resultados['Double DQN'] = 'OMITIDO (sin numpy)'
    
    # ================================================================
    # 6. PRUEBA DE ENSEMBLE RL
    # ================================================================
    log.info("--- Prueba 6: Ensemble RL ---")
    try:
        ensemble = EnsembleRL(4, 2, use_curiosity=True, use_episodic=True, use_meta=True)
        state = [0.1, 0.2, 0.3, 0.4]
        
        # Probar selección de acción (20 veces)
        actions_selected = []
        for _ in range(20):
            action = ensemble.select_action(state)
            actions_selected.append(action)
        log.info(f"  Acciones seleccionadas (20 intentos): {actions_selected}")
        log.info(f"  Distribución: 0={actions_selected.count(0)}, 1={actions_selected.count(1)}")
        
        # Probar modo exploit
        exploit_action = ensemble.select_action(state, exploit_only=True)
        log.info(f"  Acción exploit: {exploit_action}")
        
        # Probar actualización por 10 pasos
        update_results = []
        for i in range(10):
            state = [random.random() for _ in range(4)]
            action = ensemble.select_action(state)
            reward = random.random()
            next_state = [random.random() for _ in range(4)]
            result = ensemble.update(state, action, reward, next_state, i == 9)
            update_results.append(result)
        
        log.info(f"  Pesos de algoritmos: {ensemble.weights}")
        log.info(f"  Rendimiento: {ensemble.perf}")
        if update_results:
            last_result = update_results[-1]
            log.info(f"  Última actualización: reward={last_result.get('total_reward', 0):.4f}, "
                     f"intrinsic={last_result.get('intrinsic', 0):.4f}")
        
        # Probar guardado y carga
        ensemble_path = str(persist_dir / "test_ensemble.pkl")
        ensemble.save(ensemble_path)
        
        ensemble2 = EnsembleRL(4, 2)
        ensemble2.load(ensemble_path)
        log.info(f"  Ensemble cargado:")
        log.info(f"    Step: {ensemble2.step}")
        log.info(f"    Weights: {ensemble2.weights}")
        
        log.info("  Prueba Ensemble RL: OK")
        pruebas_ok += 1
        resultados['Ensemble RL'] = 'OK'
    except Exception as e:
        log.error(f"  Prueba Ensemble RL fallida: {e}")
        traceback.print_exc()
        pruebas_fallo += 1
        resultados['Ensemble RL'] = f'FALLO: {e}'
    
    # ================================================================
    # 7. PRUEBA DE MÓDULOS ADICIONALES
    # ================================================================
    log.info("--- Prueba 7: Módulos Adicionales ---")
    try:
        # Probar Fuzzy Logic Simple (singleton)
        fuzzy = FuzzyLogicController()
        fuzzy.add_mf('temp', 'cold', 'triangle', (0, 10, 20))
        fuzzy.add_mf('temp', 'warm', 'triangle', (15, 25, 35))
        fuzzy.add_mf('temp', 'hot', 'triangle', (30, 40, 50))
        fuzzy.add_rule({'temp': 'cold'}, {'output': 0.2})
        fuzzy.add_rule({'temp': 'warm'}, {'output': 0.6})
        fuzzy.add_rule({'temp': 'hot'}, {'output': 0.9})
        
        # Usar evaluate_simple para reglas singleton
        result_cold = fuzzy.evaluate_simple({'temp': 5})
        result_warm = fuzzy.evaluate_simple({'temp': 25})
        result_hot = fuzzy.evaluate_simple({'temp': 45})
        log.info(f"  Fuzzy Logic Simple:")
        log.info(f"    cold(5°)={result_cold:.4f}, warm(25°)={result_warm:.4f}, hot(45°)={result_hot:.4f}")
        
        # Probar Fuzzy Logic con MFs de salida
        fuzzy2 = FuzzyLogicController()
        fuzzy2.add_mf('speed', 'slow', 'triangle', (0, 30, 60))
        fuzzy2.add_mf('speed', 'medium', 'triangle', (40, 70, 100))
        fuzzy2.add_mf('speed', 'fast', 'triangle', (80, 120, 150))
        fuzzy2.add_mf('output', 'low', 'triangle', (0, 0.2, 0.4))
        fuzzy2.add_mf('output', 'medium', 'triangle', (0.3, 0.5, 0.7))
        fuzzy2.add_mf('output', 'high', 'triangle', (0.6, 0.8, 1.0))
        fuzzy2.add_rule({'speed': 'slow'}, {'output': 'low'})
        fuzzy2.add_rule({'speed': 'medium'}, {'output': 'medium'})
        fuzzy2.add_rule({'speed': 'fast'}, {'output': 'high'})
        
        risk_slow = fuzzy2.evaluate({'speed': 20})
        risk_medium = fuzzy2.evaluate({'speed': 65})
        risk_fast = fuzzy2.evaluate({'speed': 120})
        log.info(f"  Fuzzy Logic con MFs de salida:")
        log.info(f"    speed=20 -> {risk_slow:.4f}, speed=65 -> {risk_medium:.4f}, speed=120 -> {risk_fast:.4f}")
        
        # Información del controlador
        info = fuzzy2.get_info()
        log.info(f"  Info Fuzzy2: {info['rules_count']} reglas, variables: {info['variables']}")
        
        # Probar Kalman Filter
        kf = KalmanFilter(2, 2)
        initial_state = kf.get_state()
        log.info(f"  Kalman estado inicial: {initial_state}")
        
        # Varias iteraciones de predict/update
        for i in range(5):
            kf.predict()
            kf.update([1.0 + i * 0.1, 2.0 + i * 0.1])
        
        updated_state = kf.get_state()
        log.info(f"  Kalman estado tras 5 actualizaciones: {updated_state}")
        
        # Probar reset
        kf.reset()
        reset_state = kf.get_state()
        log.info(f"  Kalman tras reset: {reset_state}")
        
        # Probar guardado y carga del Kalman
        kf_path = str(persist_dir / "test_kalman.pkl")
        kf.predict()
        kf.update([3.0, 4.0])
        kf.save(kf_path)
        
        kf2 = KalmanFilter(2, 2)
        kf2.load(kf_path)
        loaded_state = kf2.get_state()
        log.info(f"  Kalman cargado: {loaded_state}")
        
        # Probar Genetic Optimizer
        bounds = {'x': (-10, 10), 'y': (-10, 10)}
        ga = GeneticOptimizer(bounds, pop_size=30, gens=50, mut_rate=0.15, cross_rate=0.8)
        
        def fitness(ind):
            return -(ind['x']**2 + ind['y']**2) + 10
        
        best, fit = ga.optimize(fitness, verbose=False)
        log.info(f"  Genetic Optimizer:")
        log.info(f"    Mejor: x={best.get('x', 0):.4f}, y={best.get('y', 0):.4f}, fitness={fit:.4f}")
        
        # Probar historial
        history = ga.get_history()
        log.info(f"    Fitness inicial: {history['best'][0]:.4f}")
        log.info(f"    Fitness final: {history['best'][-1]:.4f}")
        log.info(f"    Mejora: {history['best'][-1] - history['best'][0]:.4f}")
        
        # Probar con parámetros enteros
        int_bounds = {'a': (1, 10), 'b': (1, 10)}
        ga_int = GeneticOptimizer(int_bounds, pop_size=20, gens=30)
        
        def int_fitness(ind):
            return -(ind['a'] - 5)**2 - (ind['b'] - 5)**2 + 25
        
        best_int, fit_int = ga_int.optimize(int_fitness, verbose=False)
        log.info(f"  Genetic Optimizer (enteros):")
        log.info(f"    Mejor: a={best_int.get('a')}, b={best_int.get('b')}, fitness={fit_int:.4f}")
        
        # Probar HyperNumber
        hn = HyperNumberAdvanced(3.5)
        log.info(f"  HyperNumber:")
        log.info(f"    Inicial: {hn.display()} = {hn.to_float():.4f}")
        
        hn.add(2.0)
        log.info(f"    add(2.0): {hn.display()} = {hn.to_float():.4f}")
        
        hn.multiply(1.5)
        log.info(f"    multiply(1.5): {hn.display()} = {hn.to_float():.4f}")
        
        hn.subtract(1.0)
        log.info(f"    subtract(1.0): {hn.display()} = {hn.to_float():.4f}")
        
        hn.divide(2.0)
        log.info(f"    divide(2.0): {hn.display()} = {hn.to_float():.4f}")
        
        # Probar operadores sobrecargados
        hn2 = HyperNumberAdvanced(2.0)
        hn3 = hn2 + 3.0
        log.info(f"    hn2 + 3.0 = {hn3.display()}")
        
        hn4 = hn3 * 2.0
        log.info(f"    hn3 * 2.0 = {hn4.display()}")
        
        hn5 = -hn4
        log.info(f"    -hn4 = {hn5.display()}")
        
        log.info(f"    hn2 < hn3: {hn2 < hn3}")
        log.info(f"    hn2 == HyperNumberAdvanced(2.0): {hn2 == HyperNumberAdvanced(2.0)}")
        
        # Probar Demand Predictor
        dp = DemandPredictor()
        demand1 = dp.predict(19.43, -99.13)  # CDMX
        demand2 = dp.predict(40.71, -74.01)  # NYC
        demand3 = dp.predict(51.51, -0.13)   # Londres
        demand4 = dp.predict(-33.87, 151.21) # Sydney
        log.info(f"  Demand Predictor:")
        log.info(f"    CDMX: {demand1:.4f}")
        log.info(f"    NYC: {demand2:.4f}")
        log.info(f"    Londres: {demand3:.4f}")
        log.info(f"    Sydney: {demand4:.4f}")
        
        # Probar con multiplicador de ubicación
        dp.set_location_multiplier((19.4, -99.1), 2.0)
        dp.set_location_multiplier((40.7, -74.0), 0.5)
        demand_boosted = dp.predict(19.43, -99.13)
        demand_reduced = dp.predict(40.71, -74.01)
        log.info(f"    CDMX con boost x2: {demand_boosted:.4f}")
        log.info(f"    NYC con reducción x0.5: {demand_reduced:.4f}")
        
        log.info("  Prueba Módulos Adicionales: OK")
        pruebas_ok += 1
        resultados['Modulos Adicionales'] = 'OK'
    except Exception as e:
        log.error(f"  Prueba Módulos Adicionales fallida: {e}")
        traceback.print_exc()
        pruebas_fallo += 1
        resultados['Modulos Adicionales'] = f'FALLO: {e}'
    
    # ================================================================
    # 8. PRUEBA DE SYMBIOSIS GPS COMPLETO
    # ================================================================
    log.info("--- Prueba 8: SymbiosisGPS Completo ---")
    try:
        # NOTA: SymbiosisGPS crea el directorio en __init__ si no existe
        symb = SymbiosisGPS(use_real_gps=False)
        
        # Configurar grafo de prueba
        symb.add_node("start", 0, 0)
        symb.add_node("mid", 0.5, 0.3)
        symb.add_node("end", 1, 0)
        symb.add_node("alt", 0.5, -0.3)
        symb.add_edge("start_mid", "start", "mid", 80.0, 45.0)
        symb.add_edge("mid_end", "mid", "end", 70.0, 40.0)
        symb.add_edge("start_end", "start", "end", 111.0, 60.0)
        symb.add_edge("start_alt", "start", "alt", 90.0, 50.0)
        symb.add_edge("alt_end", "alt", "end", 85.0, 48.0)
        
        # Probar rutas
        path1, edges1, cost1 = symb.route("start", "end")
        log.info(f"  Ruta start->end: {path1}, costo={cost1:.1f}")
        
        path2, edges2, cost2 = symb.route("start", "end", objective="distance")
        log.info(f"  Ruta start->end (distancia): {path2}, costo={cost2:.1f} km")
        
        # Probar ubicación
        loc = symb.get_location()
        log.info(f"  Ubicación inicial: {loc}")
        
        # Probar geocerca desde SymbiosisGPS
        fid1 = symb.add_geofence(0, 0, 5.0, "centro")
        fid2 = symb.add_geofence(1, 0, 3.0, "destino")
        log.info(f"  Geocercas agregadas: {fid1}, {fid2}")
        
        # Inicializar RL
        symb.init_rl(6, 3)
        log.info(f"  RL inicializado: {symb.rl is not None}")
        
        # Ejecutar episodios de entrenamiento
        total_reward = 0.0
        for episode in range(5):
            episode_reward = 0.0
            for step in range(10):
                state = symb.get_current_state_vector()
                action = symb.rl_action(state)
                reward = random.random() * 2 - 1  # Recompensa entre -1 y 1
                next_state = symb.get_current_state_vector()
                symb.rl_update(state, action, reward, next_state, step == 9)
                episode_reward += reward
            total_reward += episode_reward
            log.info(f"  Episodio {episode + 1}: recompensa={episode_reward:.3f}")
        
        log.info(f"  Recompensa total: {total_reward:.3f}")
        log.info(f"  Recompensa promedio: {total_reward/5:.3f}")
        
        # Probar estado del sistema
        status = symb.get_system_status()
        log.info(f"  Estado del sistema:")
        log.info(f"    Ubicación: ({status['location']['latitude']:.6f}, {status['location']['longitude']:.6f})" 
                 if status['location']['latitude'] else "    Ubicación: None")
        log.info(f"    Velocidad: {status['location']['speed_kmh']:.2f} km/h")
        log.info(f"    RL step: {status['rl_step']}")
        log.info(f"    Geocercas: {status['geofences']['total_fences']}")
        
        # Guardar modelo RL
        symb.save_rl_model()
        
        # Apagar sistema
        symb.shutdown()
        log.info("  Prueba SymbiosisGPS Completo: OK")
        pruebas_ok += 1
        resultados['SymbiosisGPS Completo'] = 'OK'
    except Exception as e:
        log.error(f"  Prueba SymbiosisGPS Completo fallida: {e}")
        traceback.print_exc()
        pruebas_fallo += 1
        resultados['SymbiosisGPS Completo'] = f'FALLO: {e}'
    
    # ================================================================
    # RESUMEN FINAL DE PRUEBAS
    # ================================================================
    log.info("")
    log.info("=" * 60)
    log.info("=== RESUMEN DE PRUEBAS ===")
    log.info("=" * 60)
    total_pruebas = pruebas_ok + pruebas_fallo
    for nombre, resultado in resultados.items():
        icono = "✓" if resultado == 'OK' else "✗" if 'FALLO' in str(resultado) else "○"
        log.info(f"  {icono} {nombre}: {resultado}")
    
    log.info("-" * 60)
    log.info(f"  Total: {total_pruebas} pruebas")
    log.info(f"  Exitosas: {pruebas_ok}")
    log.info(f"  Fallidas: {pruebas_fallo}")
    
    if pruebas_fallo == 0:
        log.info("  ¡Todas las pruebas pasaron correctamente!")
    else:
        log.warning(f"  Hay {pruebas_fallo} prueba(s) fallida(s)")
    
    log.info("=" * 60)
    log.info("=== PRUEBAS COMPLETADAS ===")
    log.info("=" * 60)
    
    # Limpiar archivos de prueba
    if persist_dir.exists():
        try:
            shutil.rmtree(str(persist_dir))
            log.info("Archivos de prueba eliminados")
        except Exception as e:
            log.debug(f"No se pudieron eliminar archivos de prueba: {e}")

    print("\n" + "="*60)
    print(" INICIANDO RADAR PROFESIONAL (pulsa Ctrl+C para salir)")
    print("="*60)

    # Crear sistema con GPS real (si no funciona, caerá en simulado)
    symb = SymbiosisGPS(use_real_gps=True)

    # Añadir algunos puntos de interés (coordenadas reales de Panamá)
    albrook_mall = Coordinate(8.985, -79.52)         # Albrook Mall, Panamá
    arraijan_centro = Coordinate(8.88, -79.76)       # Arraiján Centro
    la_chorrera_centro = Coordinate(8.875, -79.78)   # La Chorrera Centro

    # Crear radar
    radar = RadarDisplay(
        gps_core=symb.gps,
        targets=[albrook_mall, arraijan_centro, la_chorrera_centro],
        max_range_km=100,   # para ver puntos muy lejanos
        update_interval=1.0,
        radius_chars=25,
        use_unicode=True
    )

    # Simular un rumbo (por ejemplo, mirando al norte)
    radar.set_heading(0)

    # Iniciar radar
    radar.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nDeteniendo radar...")
    finally:
        radar.stop()
        symb.shutdown()
