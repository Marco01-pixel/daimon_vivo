#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DEMAND RADAR ENGINE v2.0 - PROFESIONAL
=======================================
Motor genérico de detección de demanda en tiempo real.
Componente autónomo y reutilizable para cualquier proyecto que necesite:
- Monitoreo continuo de múltiples zonas/entidades
- Detección de picos de demanda con análisis de tendencias
- Priorización automática de oportunidades con scoring avanzado
- Simulación realista de datos con patrones temporales
- Auto-recuperación ante fallos con watchdog
- Sistema de alertas por umbrales configurables
- Historial analítico y predicción simple
- Análisis comparativo entre zonas
- Exportación de datos en múltiples formatos
- Gestión dinámica de zonas en tiempo de ejecución
- Agrupamiento de zonas por regiones/categorías
- Perfiles temporales configurables (dia/noche/semana)

Sin dependencias externas obligatorias. Compatible con Python 3.10+

USO BASICO:
    python demand_radar.py
    
    El radar se iniciará automáticamente en modo continuo.
    Presiona Ctrl+C para detenerlo gracefulmente.
"""
from __future__ import annotations
import os
import sys
import json
import time
import threading
import math
import random
import uuid
import csv
import io
import signal
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict, fields
from datetime import datetime, timezone, timedelta
from typing import (
    Dict, List, Optional, Tuple, Any, Callable, Protocol,
    runtime_checkable, Union
)
from collections import deque, defaultdict
from enum import Enum

# ============================================================================
# SECCION 1: ESTRUCTURAS DE DATOS GENERICAS
# ============================================================================


class SupplyLevel(Enum):
    """Niveles de oferta disponibles"""
    CRITICAL = "critical"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"

    @property
    def numeric_value(self) -> int:
        mapa = {
            self.CRITICAL: 0,
            self.LOW: 1,
            self.MEDIUM: 2,
            self.HIGH: 3,
            self.UNKNOWN: -1
        }
        return mapa[self]


@dataclass
class GeoPoint:
    """Punto geografico generico con calculos de distancia"""
    latitude: float = 0.0
    longitude: float = 0.0

    def is_valid(self) -> bool:
        return -90 <= self.latitude <= 90 and -180 <= self.longitude <= 180

    def distance_km(self, other: 'GeoPoint') -> float:
        R = 6371.0
        lat1, lon1 = math.radians(self.latitude), math.radians(self.longitude)
        lat2, lon2 = math.radians(other.latitude), math.radians(other.longitude)
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    def bearing_to(self, other: 'GeoPoint') -> float:
        lat1, lon1 = math.radians(self.latitude), math.radians(self.longitude)
        lat2, lon2 = math.radians(other.latitude), math.radians(other.longitude)
        dlon = lon2 - lon1
        x = math.sin(dlon) * math.cos(lat2)
        y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
        return (math.degrees(math.atan2(x, y)) + 360) % 360

    def to_dict(self) -> Dict[str, float]:
        return {"latitude": self.latitude, "longitude": self.longitude}


@dataclass
class Zone:
    """Zona de monitoreo generica con metadatos extendidos"""
    zone_id: str
    name: str
    location: GeoPoint = field(default_factory=GeoPoint)
    metadata: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    enabled: bool = True
    priority_weight: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "zone_id": self.zone_id,
            "name": self.name,
            "location": self.location.to_dict(),
            "metadata": self.metadata,
            "tags": self.tags,
            "enabled": self.enabled,
            "priority_weight": self.priority_weight
        }


@dataclass
class ZoneMetrics:
    """Metricas calculadas para una zona en un momento especifico"""
    zone_id: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    demand_score: float = 0.0
    supply_level: SupplyLevel = SupplyLevel.UNKNOWN
    surge_detected: bool = False
    surge_multiplier: float = 1.0
    average_wait_time: int = 0
    average_value: float = 0.0
    available_capacity: int = 0
    active_requests: int = 0
    is_simulated: bool = False
    raw_data: Dict[str, Any] = field(default_factory=dict)
    quality_index: float = 0.0
    efficiency_ratio: float = 0.0

    @property
    def is_hotspot(self) -> bool:
        return self.demand_score >= 7.0

    @property
    def is_critical(self) -> bool:
        return self.demand_score >= 9.0

    @property
    def wait_time_minutes(self) -> int:
        return self.average_wait_time // 60

    @property
    def saturation_ratio(self) -> float:
        if self.available_capacity > 0:
            return self.active_requests / self.available_capacity
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "zone_id": self.zone_id,
            "timestamp": self.timestamp.isoformat(),
            "demand_score": self.demand_score,
            "supply_level": self.supply_level.value,
            "surge_detected": self.surge_detected,
            "surge_multiplier": self.surge_multiplier,
            "average_wait_time": self.average_wait_time,
            "average_wait_time_min": self.wait_time_minutes,
            "average_value": self.average_value,
            "available_capacity": self.available_capacity,
            "active_requests": self.active_requests,
            "saturation_ratio": round(self.saturation_ratio, 3),
            "is_hotspot": self.is_hotspot,
            "is_critical": self.is_critical,
            "is_simulated": self.is_simulated,
            "quality_index": self.quality_index,
            "efficiency_ratio": self.efficiency_ratio
        }


@dataclass
class Opportunity:
    """Oportunidad detectada por el radar con scoring avanzado"""
    opportunity_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    zone_id: str = ""
    zone_name: str = ""
    location: Optional[GeoPoint] = None
    demand_score: float = 0.0
    surge_multiplier: float = 1.0
    estimated_value: float = 0.0
    hourly_potential: float = 0.0
    wait_time_seconds: int = 0
    priority_score: float = 0.0
    confidence: float = 0.0
    recommendation: str = ""
    risk_level: str = "medium"
    trend_direction: str = "stable"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "opportunity_id": self.opportunity_id,
            "timestamp": self.timestamp.isoformat(),
            "zone_id": self.zone_id,
            "zone_name": self.zone_name,
            "location": self.location.to_dict() if self.location else None,
            "demand_score": self.demand_score,
            "surge_multiplier": self.surge_multiplier,
            "estimated_value": self.estimated_value,
            "hourly_potential": self.hourly_potential,
            "wait_time_seconds": self.wait_time_seconds,
            "priority_score": self.priority_score,
            "confidence": self.confidence,
            "recommendation": self.recommendation,
            "risk_level": self.risk_level,
            "trend_direction": self.trend_direction,
            "metadata": self.metadata
        }


@dataclass
class Alert:
    """Alerta generada por el sistema"""
    alert_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    alert_type: str = ""
    zone_id: str = ""
    zone_name: str = ""
    metric_name: str = ""
    condition: str = ""
    current_value: Any = None
    threshold_value: Any = None
    message: str = ""
    severity: str = "info"
    acknowledged: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "timestamp": self.timestamp.isoformat(),
            "alert_type": self.alert_type,
            "zone_id": self.zone_id,
            "zone_name": self.zone_name,
            "metric_name": self.metric_name,
            "condition": self.condition,
            "current_value": self.current_value,
            "threshold_value": self.threshold_value,
            "message": self.message,
            "severity": self.severity,
            "acknowledged": self.acknowledged
        }


@dataclass
class RadarConfig:
    """Configuracion completa del motor de radar"""
    scan_interval_seconds: int = 60
    min_demand_threshold: float = 5.0
    hotspot_threshold: float = 7.0
    critical_threshold: float = 9.0
    hot_zones_only: bool = False
    max_opportunities_cached: int = 200
    max_consecutive_errors: int = 10
    watchdog_interval_seconds: int = 60
    error_backoff_base: int = 2
    error_backoff_max: int = 60
    scan_timeout_per_zone: float = 10.0
    enable_watchdog: bool = True
    enable_alerts: bool = True
    enable_analytics: bool = True
    enable_prediction: bool = True
    history_max_per_zone: int = 100
    alerts_max_cached: int = 50
    priority_weights: Dict[str, float] = field(default_factory=lambda: {
        "demand_score": 0.35,
        "surge_multiplier": 0.25,
        "hourly_potential": 0.25,
        "confidence": 0.15
    })

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

# ============================================================================
# SECCION 2: INTERFAZ DE PROVEEDOR DE DATOS (INYECTABLE)
# ============================================================================


@runtime_checkable
class DataProvider(Protocol):
    """Protocolo para proveedores de datos del radar"""
    def get_zone_data(self, zone: Zone) -> Dict[str, Any]: ...
    def is_available(self) -> bool: ...
    def get_provider_name(self) -> str: ...


class DataProviderBase(ABC):
    """Base abstracta para proveedores de datos"""
    @abstractmethod
    def get_zone_data(self, zone: Zone) -> Dict[str, Any]:
        pass

    @abstractmethod
    def is_available(self) -> bool:
        pass

    @abstractmethod
    def get_provider_name(self) -> str:
        pass

    def health_check(self) -> Dict[str, Any]:
        return {
            "provider": self.get_provider_name(),
            "available": self.is_available(),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

# ============================================================================
# SECCION 3: ALGORITMOS PUROS DE CALCULO
# ============================================================================


class DemandCalculator:
    """Algoritmos puros de calculo de demanda y scoring"""

    @staticmethod
    def calculate_demand_score(
        wait_times: List[int],
        surge_multipliers: List[float],
        capacity: int,
        requests: int
    ) -> float:
        if not wait_times:
            return 0.0
        avg_wait = sum(wait_times) / len(wait_times)
        if avg_wait < 120:
            wait_factor = 2.0
        elif avg_wait < 300:
            wait_factor = 4.0
        elif avg_wait < 480:
            wait_factor = 6.5
        elif avg_wait < 720:
            wait_factor = 8.0
        else:
            wait_factor = 9.5
        max_surge = max(surge_multipliers) if surge_multipliers else 1.0
        surge_factor = min(10.0, max_surge * 4.0)
        if capacity > 0:
            saturation_ratio = requests / capacity
            saturation_factor = min(10.0, saturation_ratio * 5.0)
        else:
            saturation_factor = 8.0 if requests > 0 else 0.0
        score = (wait_factor * 0.40 + surge_factor * 0.35 + saturation_factor * 0.25)
        if max_surge > 1.0:
            surge_boost = (max_surge - 1.0) * 2.0
            score = min(10.0, score + surge_boost)
        return round(max(0.0, min(10.0, score)), 2)

    @staticmethod
    def determine_supply_level(avg_wait: int) -> SupplyLevel:
        if avg_wait >= 720:
            return SupplyLevel.CRITICAL
        elif avg_wait >= 480:
            return SupplyLevel.LOW
        elif avg_wait >= 300:
            return SupplyLevel.MEDIUM
        elif avg_wait > 0:
            return SupplyLevel.HIGH
        return SupplyLevel.UNKNOWN

    @staticmethod
    def calculate_priority_score(
        demand_score: float,
        surge_multiplier: float,
        hourly_potential: float,
        confidence: float = 0.8,
        weights: Optional[Dict[str, float]] = None
    ) -> float:
        w = weights or {
            "demand_score": 0.35,
            "surge_multiplier": 0.25,
            "hourly_potential": 0.25,
            "confidence": 0.15
        }
        demand_comp = (demand_score / 10.0) * 100.0
        surge_comp = min(100.0, max(0.0, (surge_multiplier - 1.0) * 50.0))
        value_comp = min(100.0, hourly_potential)
        conf_comp = confidence * 100.0
        priority = (
            demand_comp * w.get("demand_score", 0.35) +
            surge_comp * w.get("surge_multiplier", 0.25) +
            value_comp * w.get("hourly_potential", 0.25) +
            conf_comp * w.get("confidence", 0.15)
        )
        return round(priority, 2)

    @staticmethod
    def calculate_hourly_potential(
        avg_value: float,
        transactions_per_hour: float,
        surge_multiplier: float
    ) -> float:
        return round(avg_value * transactions_per_hour * surge_multiplier, 2)

    @staticmethod
    def calculate_quality_index(metrics: ZoneMetrics) -> float:
        score = 0.0
        score += min(25, metrics.demand_score * 2.5)
        if metrics.surge_multiplier > 1.0:
            score += min(25, (metrics.surge_multiplier - 1.0) * 25)
        else:
            score += 5
        if metrics.supply_level == SupplyLevel.HIGH:
            score += 20
        elif metrics.supply_level == SupplyLevel.MEDIUM:
            score += 12
        elif metrics.supply_level == SupplyLevel.LOW:
            score += 5
        else:
            score += 2
        if metrics.average_value > 0:
            score += min(15, metrics.average_value / 2)
        if metrics.average_wait_time < 300:
            score += 15
        elif metrics.average_wait_time < 600:
            score += 8
        else:
            score += 2
        return round(min(100, max(0, score)), 1)

    @staticmethod
    def calculate_efficiency_ratio(metrics: ZoneMetrics) -> float:
        if metrics.available_capacity <= 0 or metrics.average_wait_time <= 0:
            return 0.0
        utilization = min(1.0, metrics.active_requests / metrics.available_capacity)
        speed_factor = max(0.1, 1.0 - (metrics.average_wait_time / 1200.0))
        return round(utilization * speed_factor, 3)

    @staticmethod
    def determine_risk_level(demand_score: float, surge: float, wait_time: int) -> str:
        if demand_score >= 9.0 and surge >= 2.0:
            return "very_high"
        elif demand_score >= 8.0 or surge >= 1.8:
            return "high"
        elif demand_score >= 6.0 or surge >= 1.3:
            return "medium"
        elif demand_score >= 4.0:
            return "low"
        return "minimal"

    @staticmethod
    def generate_recommendation(demand_score: float, surge: float, trend: str = "stable") -> str:
        trend_symbol = {"up": "📈", "down": "📉", "stable": "➡️"}.get(trend, "➡️")
        if demand_score >= 8.5 and surge >= 1.5:
            return f"🔥 URGENTE - Demanda extrema con surge alto {trend_symbol}"
        elif demand_score >= 8.0:
            return f"🔥 IR AHORA - Demanda muy alta {trend_symbol}"
        elif demand_score >= 7.0 and surge >= 1.2:
            return f"⚡ RECOMENDADO - Alta demanda con surge {trend_symbol}"
        elif demand_score >= 7.0:
            return f"✅ Recomendado - Buena demanda {trend_symbol}"
        elif demand_score >= 5.5 and trend == "up":
            return f"👀 ATENCION - Demanda subiendo {trend_symbol}"
        elif demand_score >= 5.5:
            return f"👀 Monitorear - Demanda moderada {trend_symbol}"
        elif demand_score >= 4.0:
            return f"⏳ Esperar - Demanda baja {trend_symbol}"
        else:
            return f"💤 Evitar - Demanda minima {trend_symbol}"


class HotspotDetector:
    """Algoritmos de deteccion de zonas calientes con analisis de tendencias"""

    def __init__(self, threshold: float = 7.0):
        self.threshold = threshold
        self._history: Dict[str, deque] = {}
        self._history_max = 20

    def update_history(self, zone_id: str, score: float, timestamp: Optional[float] = None) -> None:
        if zone_id not in self._history:
            self._history[zone_id] = deque(maxlen=self._history_max)
        self._history[zone_id].append({
            "score": score,
            "timestamp": timestamp or time.time()
        })

    def is_trending_up(self, zone_id: str, window: int = 3) -> bool:
        history = self._history.get(zone_id, deque())
        if len(history) < window:
            return False
        recent = list(history)[-window:]
        scores = [h["score"] for h in recent]
        if len(scores) >= 4:
            recent_avg = sum(scores[-2:]) / 2
            earlier_avg = sum(scores[:2]) / 2
            return recent_avg > earlier_avg * 1.1
        return scores[-1] > scores[0]

    def is_trending_down(self, zone_id: str, window: int = 3) -> bool:
        history = self._history.get(zone_id, deque())
        if len(history) < window:
            return False
        recent = list(history)[-window:]
        scores = [h["score"] for h in recent]
        if len(scores) >= 2:
            return scores[-1] < scores[0] * 0.85
        return False

    def get_trend_direction(self, zone_id: str) -> str:
        if self.is_trending_up(zone_id):
            return "up"
        if self.is_trending_down(zone_id):
            return "down"
        return "stable"

    def get_trend_magnitude(self, zone_id: str, window: int = 5) -> float:
        history = self._history.get(zone_id, deque())
        if len(history) < 2:
            return 0.0
        recent = list(history)[-window:]
        if len(recent) < 2:
            return 0.0
        first = recent[0]["score"]
        last = recent[-1]["score"]
        if first == 0:
            return 0.0
        return round(((last - first) / first) * 100, 1)

    def get_volatility(self, zone_id: str, window: int = 5) -> float:
        history = self._history.get(zone_id, deque())
        if len(history) < 3:
            return 0.0
        recent = list(history)[-window:]
        scores = [h["score"] for h in recent]
        mean = sum(scores) / len(scores)
        variance = sum((s - mean) ** 2 for s in scores) / len(scores)
        return round(math.sqrt(variance), 2)

    def find_hotspots(
        self,
        metrics: Dict[str, ZoneMetrics],
        include_trending: bool = False
    ) -> List[Tuple[str, ZoneMetrics, str, float]]:
        results = []
        for zone_id, m in metrics.items():
            if m.demand_score >= self.threshold:
                trend = self.get_trend_direction(zone_id)
                magnitude = self.get_trend_magnitude(zone_id)
                results.append((zone_id, m, trend, magnitude))
            elif include_trending and self.is_trending_up(zone_id):
                trend = "up"
                magnitude = self.get_trend_magnitude(zone_id)
                results.append((zone_id, m, trend, magnitude))
        results.sort(key=lambda x: x[1].demand_score, reverse=True)
        return results

    def get_zone_history(self, zone_id: str) -> List[Dict[str, Any]]:
        return list(self._history.get(zone_id, deque()))

    def clear_history(self, zone_id: Optional[str] = None) -> None:
        if zone_id:
            self._history.pop(zone_id, None)
        else:
            self._history.clear()

# ============================================================================
# SECCION 4: SIMULADOR DE DATOS GENERICO
# ============================================================================


@dataclass
class ZoneProfile:
    """Perfil de simulacion para una zona"""
    base_demand: float = 5.0
    base_value: float = 10.0
    base_wait_time: int = 300
    peak_hours: List[int] = field(default_factory=lambda: [7, 8, 9, 17, 18, 19])
    weekend_multiplier: float = 1.0
    night_penalty: float = 0.5
    variance: float = 0.3
    surge_probability: float = 0.3
    max_surge: float = 2.5


class SimulatedDataProvider(DataProviderBase):
    """Proveedor de datos simulados realista con patrones temporales avanzados"""
    DEFAULT_PROFILE = ZoneProfile()

    def __init__(
        self,
        zone_profiles: Optional[Dict[str, ZoneProfile]] = None,
        seed: Optional[int] = None
    ):
        self.zone_profiles = zone_profiles or {}
        self._rng = random.Random(seed)
        self._available = True
        self._call_count = 0

    def set_zone_profile(self, zone_id: str, profile: ZoneProfile) -> None:
        self.zone_profiles[zone_id] = profile

    def get_zone_data(self, zone: Zone) -> Dict[str, Any]:
        if not self._available:
            return {}
        self._call_count += 1
        profile = self.zone_profiles.get(zone.zone_id, self.DEFAULT_PROFILE)
        hour_factor, is_peak = self._get_hour_factor(profile)
        weekend_factor = self._get_weekend_factor(profile)
        demand = profile.base_demand * hour_factor * weekend_factor
        demand += self._rng.uniform(-profile.variance * 3, profile.variance * 3)
        demand = max(0, min(10, demand))
        if demand >= 8.0:
            surge = 1.5 + self._rng.uniform(0, profile.max_surge - 1.5)
        elif demand >= 7.0:
            surge = 1.2 + self._rng.uniform(0, 0.5)
        elif demand >= 5.5 and self._rng.random() < profile.surge_probability:
            surge = 1.0 + self._rng.uniform(0, 0.3)
        else:
            surge = 1.0
        surge = round(min(surge, profile.max_surge), 2)
        base_wait = profile.base_wait_time
        if is_peak:
            wait = base_wait * (1.5 if demand > 7 else 1.2)
        else:
            wait = base_wait * self._rng.uniform(0.8, 1.2)
        wait = max(60, int(wait))
        num_readings = self._rng.randint(2, 4)
        wait_times = [max(60, int(wait * self._rng.uniform(0.7, 1.3))) for _ in range(num_readings)]
        surges = [round(surge * self._rng.uniform(0.9, 1.1), 2) for _ in range(num_readings)]
        values = [round(profile.base_value * surge * self._rng.uniform(0.85, 1.15), 2) for _ in range(num_readings)]
        if demand >= 7:
            capacity = self._rng.randint(1, 5)
            requests = self._rng.randint(10, 30)
        elif demand >= 5:
            capacity = self._rng.randint(5, 15)
            requests = self._rng.randint(5, 15)
        else:
            capacity = self._rng.randint(10, 25)
            requests = self._rng.randint(1, 8)
        return {
            "wait_times": wait_times,
            "values": values,
            "surge_multipliers": surges,
            "capacity": capacity,
            "requests": requests,
            "_simulated_demand": round(demand, 2),
            "_simulated_surge": surge
        }

    def _get_hour_factor(self, profile: ZoneProfile) -> Tuple[float, bool]:
        hour = datetime.now().hour
        is_peak = hour in profile.peak_hours
        if is_peak:
            factor = 1.5 + self._rng.uniform(-0.2, 0.2)
        elif hour < 6:
            factor = profile.night_penalty + self._rng.uniform(-0.1, 0.1)
        elif hour < 12:
            factor = 0.8 + self._rng.uniform(-0.1, 0.1)
        elif hour < 17:
            factor = 0.7 + self._rng.uniform(-0.1, 0.1)
        else:
            factor = 1.0 + self._rng.uniform(-0.1, 0.1)
        return factor, is_peak

    def _get_weekend_factor(self, profile: ZoneProfile) -> float:
        weekday = datetime.now().weekday()
        if weekday >= 5:
            return profile.weekend_multiplier
        return 1.0

    def is_available(self) -> bool:
        return self._available

    def get_provider_name(self) -> str:
        return "SimulatedDataProvider"

    def set_unavailable(self) -> None:
        self._available = False

    def set_available(self) -> None:
        self._available = True

    @property
    def call_count(self) -> int:
        return self._call_count

# ============================================================================
# SECCION 5: RATE LIMITER GENERICO
# ============================================================================


class RateLimiter:
    """Limitador de tasa generico (sliding window)"""

    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._timestamps: deque = deque()
        self._lock = threading.Lock()

    def acquire(self, max_wait: float = 30.0) -> bool:
        deadline = time.time() + max_wait
        while time.time() < deadline:
            with self._lock:
                now = time.time()
                while self._timestamps and (now - self._timestamps[0]) > self.window_seconds:
                    self._timestamps.popleft()
                if len(self._timestamps) < self.max_requests:
                    self._timestamps.append(now)
                    return True
            time.sleep(min(1.0, deadline - time.time()))
        return False

    def wait_for_slot(self, max_wait: float = 60.0) -> None:
        if not self.acquire(max_wait=max_wait):
            raise TimeoutError("No se pudo obtener slot de rate limit en {}s".format(max_wait))

    @property
    def available_slots(self) -> int:
        with self._lock:
            now = time.time()
            while self._timestamps and (now - self._timestamps[0]) > self.window_seconds:
                self._timestamps.popleft()
            return self.max_requests - len(self._timestamps)

    def reset(self) -> None:
        with self._lock:
            self._timestamps.clear()

# ============================================================================
# SECCION 6: SISTEMA DE ALERTAS
# ============================================================================


class AlertSystem:
    """Sistema de alertas basado en umbrales configurables"""
    SEVERITY_MAP = {
        "critical": 4,
        "high": 3,
        "medium": 2,
        "low": 1,
        "info": 0
    }

    def __init__(self, max_cached: int = 50):
        self._thresholds: List[Dict[str, Any]] = []
        self._alerts: deque = deque(maxlen=max_cached)
        self._callbacks: List[Callable[[Alert], None]] = []
        self._lock = threading.RLock()
        self._suppressed: Dict[str, float] = {}
        self._suppression_seconds: int = 300

    def add_threshold(
        self,
        metric_name: str,
        condition: str,
        callback: Optional[Callable[[Alert], None]] = None,
        severity: str = "info",
        message_template: Optional[str] = None,
        suppression_seconds: Optional[int] = None
    ) -> None:
        entry = {
            "metric_name": metric_name,
            "condition": condition,
            "callback": callback,
            "severity": severity,
            "message_template": message_template or "{zone_name}: {metric_name} {condition} {threshold_value} (actual: {current_value})",
            "suppression_seconds": suppression_seconds or self._suppression_seconds
        }
        with self._lock:
            self._thresholds.append(entry)

    def on_alert(self, callback: Callable[[Alert], None]) -> None:
        with self._lock:
            self._callbacks.append(callback)

    def evaluate(self, zone: Zone, metrics: ZoneMetrics) -> List[Alert]:
        triggered = []
        metrics_dict = metrics.to_dict()
        with self._lock:
            for thresh in self._thresholds:
                metric_name = thresh["metric_name"]
                condition = thresh["condition"]
                if metric_name not in metrics_dict:
                    continue
                current_value = metrics_dict[metric_name]
                if not self._check_condition(current_value, condition):
                    continue
                suppression_key = "{}_{}".format(zone.zone_id, metric_name)
                last_triggered = self._suppressed.get(suppression_key, 0)
                if time.time() - last_triggered < thresh["suppression_seconds"]:
                    continue
                self._suppressed[suppression_key] = time.time()
                alert = Alert(
                    alert_type="threshold",
                    zone_id=zone.zone_id,
                    zone_name=zone.name,
                    metric_name=metric_name,
                    condition=condition,
                    current_value=current_value,
                    threshold_value=condition,
                    message=thresh["message_template"].format(
                        zone_name=zone.name,
                        zone_id=zone.zone_id,
                        metric_name=metric_name,
                        condition=condition,
                        current_value=current_value,
                        threshold_value=condition
                    ),
                    severity=thresh["severity"]
                )
                self._alerts.append(alert)
                triggered.append(alert)
                if thresh.get("callback"):
                    try:
                        thresh["callback"](alert)
                    except Exception:
                        pass
                for cb in self._callbacks:
                    try:
                        cb(alert)
                    except Exception:
                        pass
        return triggered

    def _check_condition(self, value: Any, condition: str) -> bool:
        try:
            condition = condition.strip()
            if ">=" in condition:
                parts = condition.split(">=", 1)
                return float(value) >= float(parts[1].strip())
            elif "<=" in condition:
                parts = condition.split("<=", 1)
                return float(value) <= float(parts[1].strip())
            elif ">" in condition and not ">=" in condition:
                parts = condition.split(">", 1)
                return float(value) > float(parts[1].strip())
            elif "<" in condition and not "<=" in condition:
                parts = condition.split("<", 1)
                return float(value) < float(parts[1].strip())
            elif "==" in condition:
                parts = condition.split("==", 1)
                return float(value) == float(parts[1].strip())
            elif "!=" in condition:
                parts = condition.split("!=", 1)
                return float(value) != float(parts[1].strip())
        except (ValueError, TypeError, IndexError):
            pass
        return False

    def get_alerts(
        self,
        severity: Optional[str] = None,
        zone_id: Optional[str] = None,
        acknowledged: Optional[bool] = None,
        limit: int = 20
    ) -> List[Alert]:
        with self._lock:
            alerts = list(self._alerts)
            if severity:
                alerts = [a for a in alerts if a.severity == severity]
            if zone_id:
                alerts = [a for a in alerts if a.zone_id == zone_id]
            if acknowledged is not None:
                alerts = [a for a in alerts if a.acknowledged == acknowledged]
            return alerts[-limit:]

    def acknowledge_alert(self, alert_id: str) -> bool:
        with self._lock:
            for alert in self._alerts:
                if alert.alert_id == alert_id:
                    alert.acknowledged = True
                    return True
        return False

    def acknowledge_all(self) -> int:
        count = 0
        with self._lock:
            for alert in self._alerts:
                if not alert.acknowledged:
                    alert.acknowledged = True
                    count += 1
        return count

    def clear_alerts(self) -> int:
        with self._lock:
            count = len(self._alerts)
            self._alerts.clear()
            self._suppressed.clear()
            return count

    @property
    def unacknowledged_count(self) -> int:
        with self._lock:
            return sum(1 for a in self._alerts if not a.acknowledged)

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            alerts = list(self._alerts)
            severity_counts = defaultdict(int)
            for a in alerts:
                severity_counts[a.severity] += 1
            return {
                "total": len(alerts),
                "unacknowledged": sum(1 for a in alerts if not a.acknowledged),
                "by_severity": dict(severity_counts),
                "thresholds_configured": len(self._thresholds)
            }

# ============================================================================
# SECCION 7: SISTEMA DE ANALITICA E HISTORIAL
# ============================================================================


class AnalyticsEngine:
    """Motor de analisis historicos y estadisticas"""

    def __init__(self, max_history_per_zone: int = 100):
        self._history: Dict[str, deque] = {}
        self._max_history = max_history_per_zone
        self._lock = threading.RLock()
        self._snapshots: deque = deque(maxlen=50)

    def record_metrics(self, metrics: ZoneMetrics) -> None:
        with self._lock:
            zid = metrics.zone_id
            if zid not in self._history:
                self._history[zid] = deque(maxlen=self._max_history)
            self._history[zid].append({
                "timestamp": metrics.timestamp.isoformat(),
                "unix_ts": metrics.timestamp.timestamp(),
                "demand_score": metrics.demand_score,
                "surge_multiplier": metrics.surge_multiplier,
                "average_wait_time": metrics.average_wait_time,
                "average_value": metrics.average_value,
                "supply_level": metrics.supply_level.value,
                "quality_index": metrics.quality_index,
                "efficiency_ratio": metrics.efficiency_ratio,
                "is_hotspot": metrics.is_hotspot
            })

    def take_snapshot(self, all_metrics: Dict[str, ZoneMetrics]) -> Dict[str, Any]:
        snapshot = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "zones": {zid: m.to_dict() for zid, m in all_metrics.items()},
            "summary": self._calculate_summary(all_metrics)
        }
        with self._lock:
            self._snapshots.append(snapshot)
        return snapshot

    def _calculate_summary(self, metrics: Dict[str, ZoneMetrics]) -> Dict[str, Any]:
        if not metrics:
            return {"avg_demand": 0, "max_demand": 0, "hotspots": 0, "zones_total": 0}
        scores = [m.demand_score for m in metrics.values()]
        hotspots = sum(1 for m in metrics.values() if m.is_hotspot)
        surges = [m.surge_multiplier for m in metrics.values() if m.surge_detected]
        return {
            "zones_total": len(metrics),
            "avg_demand": round(sum(scores) / len(scores), 2),
            "max_demand": round(max(scores), 2),
            "min_demand": round(min(scores), 2),
            "hotspots": hotspots,
            "avg_surge": round(sum(surges) / len(surges), 2) if surges else 1.0,
            "max_surge": round(max(surges), 2) if surges else 1.0
        }

    def get_zone_history(
        self,
        zone_id: str,
        hours: Optional[float] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        with self._lock:
            history = list(self._history.get(zone_id, deque()))
            if hours is not None:
                cutoff = time.time() - (hours * 3600)
                history = [h for h in history if h.get("unix_ts", 0) >= cutoff]
            if limit is not None:
                history = history[-limit:]
            return history

    def get_zone_stats(self, zone_id: str, hours: Optional[float] = None) -> Dict[str, Any]:
        history = self.get_zone_history(zone_id, hours=hours)
        if not history:
            return {"available": False, "zone_id": zone_id}
        scores = [h["demand_score"] for h in history]
        surges = [h["surge_multiplier"] for h in history]
        waits = [h["average_wait_time"] for h in history]
        values = [h["average_value"] for h in history if h["average_value"] > 0]
        hotspot_ratio = sum(1 for h in history if h.get("is_hotspot")) / len(history)
        return {
            "available": True,
            "zone_id": zone_id,
            "samples": len(history),
            "period_hours": hours,
            "demand": {
                "avg": round(sum(scores) / len(scores), 2),
                "max": round(max(scores), 2),
                "min": round(min(scores), 2),
                "std_dev": round(self._std_dev(scores), 2)
            },
            "surge": {
                "avg": round(sum(surges) / len(surges), 2),
                "max": round(max(surges), 2),
                "frequency": round(sum(1 for s in surges if s > 1.0) / len(surges) * 100, 1)
            },
            "wait_time": {
                "avg_seconds": int(sum(waits) / len(waits)),
                "avg_minutes": int(sum(waits) / len(waits) / 60),
                "max_minutes": int(max(waits) / 60)
            },
            "value": {
                "avg": round(sum(values) / len(values), 2) if values else 0,
                "max": round(max(values), 2) if values else 0
            },
            "hotspot_ratio": round(hotspot_ratio * 100, 1),
            "quality": {
                "avg_index": round(sum(h.get("quality_index", 0) for h in history) / len(history), 1)
            }
        }

    def get_global_stats(self, hours: Optional[float] = None) -> Dict[str, Any]:
        with self._lock:
            zone_ids = list(self._history.keys())
            zone_stats = {}
            total_samples = 0
            all_hotspot_ratios = []
            for zid in zone_ids:
                stats = self.get_zone_stats(zid, hours=hours)
                zone_stats[zid] = stats
                total_samples += stats.get("samples", 0)
                if stats.get("available"):
                    all_hotspot_ratios.append(stats.get("hotspot_ratio", 0))
            return {
                "period_hours": hours,
                "zones_analyzed": len(zone_ids),
                "total_samples": total_samples,
                "zone_stats": zone_stats,
                "avg_hotspot_ratio": round(sum(all_hotspot_ratios) / len(all_hotspot_ratios), 1) if all_hotspot_ratios else 0
            }

    def get_snapshots(self, limit: int = 10) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._snapshots)[-limit:]

    def compare_zones(
        self,
        zone_ids: List[str],
        metric_names: Optional[List[str]] = None,
        hours: Optional[float] = None
    ) -> Dict[str, Any]:
        metric_names = metric_names or ["demand_score", "surge_multiplier", "average_wait_time", "average_value"]
        comparison = {}
        for zid in zone_ids:
            history = self.get_zone_history(zid, hours=hours)
            zone_comp = {}
            for mname in metric_names:
                values = [h.get(mname, 0) for h in history if h.get(mname) is not None]
                if values:
                    zone_comp[mname] = {
                        "avg": round(sum(values) / len(values), 2),
                        "max": round(max(values), 2),
                        "min": round(min(values), 2),
                        "samples": len(values)
                    }
                else:
                    zone_comp[mname] = {"avg": 0, "max": 0, "min": 0, "samples": 0}
            comparison[zid] = zone_comp
        ranking = {}
        for mname in metric_names:
            ranked = sorted(
                [(zid, comparison[zid][mname]["avg"]) for zid in zone_ids if zid in comparison],
                key=lambda x: x[1],
                reverse=True
            )
            ranking[mname] = [{"zone_id": z, "value": v} for z, v in ranked]
        return {"comparison": comparison, "ranking": ranking}

    def get_ranking(self, metric_name: str = "demand_score", hours: Optional[float] = None) -> List[Dict[str, Any]]:
        with self._lock:
            zone_ids = list(self._history.keys())
            results = []
            for zid in zone_ids:
                history = self.get_zone_history(zid, hours=hours)
                values = [h.get(metric_name, 0) for h in history if h.get(metric_name) is not None]
                if values:
                    results.append({
                        "zone_id": zid,
                        "avg": round(sum(values) / len(values), 2),
                        "max": round(max(values), 2),
                        "samples": len(values)
                    })
            results.sort(key=lambda x: x["avg"], reverse=True)
            return results

    @staticmethod
    def _std_dev(values: List[float]) -> float:
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        return math.sqrt(variance)

    def clear_history(self, zone_id: Optional[str] = None) -> None:
        with self._lock:
            if zone_id:
                self._history.pop(zone_id, None)
            else:
                self._history.clear()
            self._snapshots.clear()

# ============================================================================
# SECCION 8: MOTOR DE PREDICCION SIMPLE
# ============================================================================


class PredictionEngine:
    """Motor de prediccion simple basado en tendencias historicas"""

    def __init__(self, history_source: Optional[AnalyticsEngine] = None):
        self._history_source = history_source

    def set_history_source(self, source: AnalyticsEngine) -> None:
        self._history_source = source

    def forecast_demand(
        self,
        zone_id: str,
        steps: int = 6,
        interval_minutes: int = 10
    ) -> List[Dict[str, Any]]:
        if not self._history_source:
            return []
        history = self._history_source.get_zone_history(zone_id, hours=2)
        if len(history) < 3:
            return []
        scores = [h["demand_score"] for h in history]
        forecast = self._linear_extrapolation(scores, steps)
        result = []
        base_time = datetime.now(timezone.utc)
        for i, predicted in enumerate(forecast):
            future_time = base_time + timedelta(minutes=interval_minutes * (i + 1))
            result.append({
                "step": i + 1,
                "timestamp": future_time.isoformat(),
                "predicted_demand": round(max(0, min(10, predicted)), 2),
                "interval_minutes": interval_minutes,
                "confidence": round(max(0.1, 0.9 - (i * 0.1)), 2)
            })
        return result

    def forecast_surge(
        self,
        zone_id: str,
        steps: int = 6,
        interval_minutes: int = 10
    ) -> List[Dict[str, Any]]:
        if not self._history_source:
            return []
        history = self._history_source.get_zone_history(zone_id, hours=2)
        if len(history) < 3:
            return []
        surges = [h["surge_multiplier"] for h in history]
        forecast = self._linear_extrapolation(surges, steps)
        result = []
        base_time = datetime.now(timezone.utc)
        for i, predicted in enumerate(forecast):
            future_time = base_time + timedelta(minutes=interval_minutes * (i + 1))
            result.append({
                "step": i + 1,
                "timestamp": future_time.isoformat(),
                "predicted_surge": round(max(1.0, predicted), 2),
                "interval_minutes": interval_minutes,
                "confidence": round(max(0.1, 0.85 - (i * 0.12)), 2)
            })
        return result

    def detect_anomaly(self, zone_id: str) -> Optional[Dict[str, Any]]:
        if not self._history_source:
            return None
        history = self._history_source.get_zone_history(zone_id, hours=1)
        if len(history) < 5:
            return None
        scores = [h["demand_score"] for h in history]
        mean = sum(scores) / len(scores)
        std = self._std_dev(scores)
        if std == 0:
            return None
        latest = scores[-1]
        z_score = (latest - mean) / std
        if abs(z_score) > 2.0:
            return {
                "zone_id": zone_id,
                "anomaly_detected": True,
                "z_score": round(z_score, 2),
                "current_value": latest,
                "historical_mean": round(mean, 2),
                "historical_std": round(std, 2),
                "direction": "spike" if z_score > 0 else "drop",
                "severity": "high" if abs(z_score) > 3.0 else "medium"
            }
        return None

    @staticmethod
    def _linear_extrapolation(values: List[float], steps: int) -> List[float]:
        n = len(values)
        if n < 2:
            return [values[-1]] * steps
        recent = values[-min(n, 10):]
        x = list(range(len(recent)))
        mean_x = sum(x) / len(x)
        mean_y = sum(recent) / len(recent)
        numerator = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, recent))
        denominator = sum((xi - mean_x) ** 2 for xi in x)
        if denominator == 0:
            return [recent[-1]] * steps
        slope = numerator / denominator
        intercept = mean_y - slope * mean_x
        predictions = []
        for i in range(1, steps + 1):
            pred = slope * (len(recent) - 1 + i) + intercept
            if len(predictions) > 0:
                pred = predictions[-1] * 0.7 + pred * 0.3
            predictions.append(pred)
        return predictions

    @staticmethod
    def _std_dev(values: List[float]) -> float:
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        return math.sqrt(variance)

# ============================================================================
# SECCION 9: SISTEMA DE GRUPOS DE ZONAS
# ============================================================================


class ZoneGroupManager:
    """Gestor de agrupamiento de zonas por categorias/regiones"""

    def __init__(self):
        self._groups: Dict[str, List[str]] = {}
        self._group_metadata: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()

    def create_group(
        self,
        group_id: str,
        zone_ids: List[str],
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        with self._lock:
            self._groups[group_id] = list(zone_ids)
            self._group_metadata[group_id] = metadata or {}

    def add_to_group(self, group_id: str, zone_id: str) -> bool:
        with self._lock:
            if group_id not in self._groups:
                return False
            if zone_id not in self._groups[group_id]:
                self._groups[group_id].append(zone_id)
                return True
            return True
        return False

    def remove_from_group(self, group_id: str, zone_id: str) -> bool:
        with self._lock:
            if group_id not in self._groups:
                return False
            if zone_id in self._groups[group_id]:
                self._groups[group_id].remove(zone_id)
                return True
            return False

    def delete_group(self, group_id: str) -> bool:
        with self._lock:
            if group_id in self._groups:
                del self._groups[group_id]
                self._group_metadata.pop(group_id, None)
                return True
            return False

    def get_group(self, group_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            if group_id not in self._groups:
                return None
            return {
                "group_id": group_id,
                "zone_ids": list(self._groups[group_id]),
                "zone_count": len(self._groups[group_id]),
                "metadata": self._group_metadata.get(group_id, {})
            }

    def get_all_groups(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {gid: self.get_group(gid) for gid in self._groups}

    def get_group_metrics(
        self,
        group_id: str,
        all_metrics: Dict[str, ZoneMetrics]
    ) -> Dict[str, Any]:
        with self._lock:
            zone_ids = self._groups.get(group_id, [])
            group_metrics = {zid: all_metrics[zid] for zid in zone_ids if zid in all_metrics}
            if not group_metrics:
                return {"group_id": group_id, "zones_found": 0}
            scores = [m.demand_score for m in group_metrics.values()]
            return {
                "group_id": group_id,
                "zones_found": len(group_metrics),
                "zones_total": len(zone_ids),
                "avg_demand": round(sum(scores) / len(scores), 2),
                "max_demand": round(max(scores), 2),
                "hotspots": sum(1 for m in group_metrics.values() if m.is_hotspot),
                "best_zone": max(group_metrics.items(), key=lambda x: x[1].demand_score)[0],
                "worst_zone": min(group_metrics.items(), key=lambda x: x[1].demand_score)[0]
            }

    def get_zones_for_group(self, group_id: str) -> List[str]:
        with self._lock:
            return list(self._groups.get(group_id, []))

    def get_groups_for_zone(self, zone_id: str) -> List[str]:
        with self._lock:
            return [gid for gid, zids in self._groups.items() if zone_id in zids]

# ============================================================================
# SECCION 9.5: GESTOR DE ZONAS DINAMICAS (GPS-REALTIME)
# ============================================================================


class DynamicZoneManager:
    """
    Gestiona zonas dinámicas que se actualizan desde el GPS en tiempo real.
    Reemplaza zonas fijas con datos geolocalizados dinámicamente.
    """
    
    def __init__(self, max_radius_km: float = 15.0, min_radius_km: float = 2.0):
        self._dynamic_zones: Dict[str, Dict[str, Any]] = {}
        self._current_location: Optional[Tuple[float, float]] = None
        self._lock = threading.RLock()
        self._max_radius = max_radius_km
        self._min_radius = min_radius_km
        self._radii_steps = [2, 5, 10, 15]  # Radios en km para generar zonas

    def update_current_location(self, lat: float, lon: float) -> None:
        """Actualiza la ubicación actual y recalcula zonas cercanas"""
        with self._lock:
            if self._current_location == (lat, lon):
                return  # Sin cambios, evitar recálculo innecesario
            self._current_location = (lat, lon)
            self._recalculate_zones()

    def _recalculate_zones(self) -> None:
        """Recalcula zonas dinámicas basadas en ubicación actual"""
        if not self._current_location:
            return
        
        lat, lon = self._current_location
        self._dynamic_zones.clear()
        
        # Generar zonas en 8 direcciones cardinales
        for i in range(8):
            angle = i * 45  # 0, 45, 90, ... 315 grados
            rad = math.radians(angle)
            
            for radius_km in self._radii_steps:
                if radius_km > self._max_radius:
                    continue
                    
                # Cálculo de coordenadas destino (fórmula haversine simplificada)
                delta_lat = radius_km / 111.0
                delta_lon = radius_km / (111.0 * math.cos(math.radians(lat)))
                
                zone_lat = lat + delta_lat * math.cos(rad)
                zone_lon = lon + delta_lon * math.sin(rad)
                
                # Validar coordenadas
                if not (-90 <= zone_lat <= 90 and -180 <= zone_lon <= 180):
                    continue
                
                zone_id = f"dyn_{i}_{radius_km}"
                self._dynamic_zones[zone_id] = {
                    "id": zone_id,
                    "name": f"Zona {chr(65+i)}-{radius_km}km",  # A-2km, B-2km, etc.
                    "latitude": round(zone_lat, 6),
                    "longitude": round(zone_lon, 6),
                    "distance_km": radius_km,
                    "bearing": angle,
                    "direction": self._bearing_to_direction(angle),
                    "updated_at": time.time(),
                    "dynamic": True
                }

    @staticmethod
    def _bearing_to_direction(bearing: float) -> str:
        """Convierte bearing en dirección cardinal"""
        directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
        return directions[int(round(bearing / 45)) % 8]

    def get_zones(self) -> List[Zone]:
        """Retorna lista de objetos Zone actualizados"""
        with self._lock:
            zones = []
            for zid, zdata in self._dynamic_zones.items():
                # Peso inverso a la distancia: zonas cercanas = mayor prioridad
                priority = max(0.5, 2.0 - (zdata["distance_km"] / 10.0))
                
                zone = Zone(
                    zone_id=zid,
                    name=zdata["name"],
                    location=GeoPoint(zdata["latitude"], zdata["longitude"]),
                    metadata={
                        "distance_km": zdata["distance_km"],
                        "bearing": zdata["bearing"],
                        "direction": zdata["direction"],
                        "dynamic": True,
                        "updated_at": zdata["updated_at"]
                    },
                    tags=["dynamic", "gps"],
                    enabled=True,
                    priority_weight=round(priority, 2)
                )
                zones.append(zone)
            return zones

    def get_zone_count(self) -> int:
        """Retorna número de zonas dinámicas activas"""
        with self._lock:
            return len(self._dynamic_zones)

    def is_active(self) -> bool:
        """Verifica si hay ubicación válida para generar zonas"""
        with self._lock:
            return self._current_location is not None

    def clear(self) -> None:
        """Limpia todas las zonas dinámicas"""
        with self._lock:
            self._dynamic_zones.clear()
            self._current_location = None

# ============================================================================
# SECCION 10: SISTEMA DE EXPORTACION
# ============================================================================


class ExportManager:
    """Gestor de exportacion de datos en multiples formatos"""

    @staticmethod
    def to_json(data: Any, pretty: bool = True) -> str:
        if pretty:
            return json.dumps(data, indent=2, ensure_ascii=False, default=str)
        return json.dumps(data, ensure_ascii=False, default=str)

    @staticmethod
    def to_csv_rows(
        opportunities: List[Opportunity],
        include_header: bool = True
    ) -> List[str]:
        rows = []
        if include_header:
            rows.append(",".join([
                "opportunity_id", "timestamp", "zone_id", "zone_name",
                "demand_score", "surge_multiplier", "hourly_potential",
                "priority_score", "confidence", "recommendation",
                "risk_level", "trend_direction"
            ]))
        for opp in opportunities:
            rows.append(",".join([
                opp.opportunity_id,
                opp.timestamp.isoformat(),
                opp.zone_id,
                '"{}"'.format(opp.zone_name.replace('"', '""')),
                str(opp.demand_score),
                str(opp.surge_multiplier),
                str(opp.hourly_potential),
                str(opp.priority_score),
                str(opp.confidence),
                '"{}"'.format(opp.recommendation.replace('"', '""')),
                opp.risk_level,
                opp.trend_direction
            ]))
        return rows

    @staticmethod
    def to_csv_string(opportunities: List[Opportunity]) -> str:
        return "\n".join(ExportManager.to_csv_rows(opportunities))

    @staticmethod
    def to_markdown_table(opportunities: List[Opportunity], max_rows: int = 20) -> str:
        lines = []
        lines.append("| # | Zona | Demanda | Surge | $/h | Prioridad | Recomendacion |")
        lines.append("|---|------|---------|-------|-----|-----------|---------------|")
        for i, opp in enumerate(opportunities[:max_rows], 1):
            lines.append(
                "| {} | {} | {:.1f}/10 | x{} | ${:.2f} | {:.0f} | {} |".format(
                    i, opp.zone_name, opp.demand_score,
                    opp.surge_multiplier, opp.hourly_potential,
                    opp.priority_score, opp.recommendation
                )
            )
        return "\n".join(lines)

    @staticmethod
    def to_compact_summary(radar_status: Dict[str, Any]) -> str:
        health = radar_status.get("health", {})
        rec = radar_status.get("recommendation")
        lines = [
            "=== RADAR SUMMARY ===",
            "Estado: {}".format("ACTIVO" if health.get("running") else "INACTIVO"),
            "Zonas: {}/{}".format(health.get("zones_with_data", 0), health.get("zones_monitored", 0)),
            "Escaneos: {}".format(health.get("successful_scans", 0)),
            "Hotspots: {}".format(health.get("hotspots_detected", 0)),
            "Errores: {}".format(health.get("consecutive_errors", 0)),
        ]
        if rec:
            lines.append("Recomendacion: {} ({:.1f}/10)".format(rec.get("zone_name", "?"), rec.get("demand_score", 0)))
        return "\n".join(lines)


# ============================================================================
# SECCION 11: MOTOR DE RADAR PRINCIPAL (CON INTEGRACIÓN A GPS SYMBIOSIS)
# ============================================================================

from typing import Optional, Dict, List, Any, Tuple, Callable
from collections import deque
from datetime import datetime, timezone
import threading
import time
import uuid
import json


class RadarEngine:
    """
    Motor principal de radar de demanda - VERSION PROFESIONAL v2.0
    Caracteristicas completas:
    - Monitoreo continuo con hilo dedicado y watchdog
    - Rate limiting integrado
    - Deteccion de hotspots con analisis de tendencias
    - Sistema de alertas por umbrales configurables
    - Historial analitico con estadisticas
    - Prediccion simple de demanda y surge
    - Analisis comparativo entre zonas
    - Agrupamiento de zonas por categorias
    - Exportacion JSON, CSV, Markdown
    - Sistema de callbacks para eventos
    - Gestion dinamica de zonas en runtime
    - Auto-recuperacion ante fallos
    - INTEGRACION CON GPS SYMBIOSIS (usa symbiosis.registry)
    """

    def __init__(
        self,
        zones: List[Zone],
        data_provider: DataProviderBase,
        config: Optional[RadarConfig] = None,
        rate_limiter: Optional[RateLimiter] = None,
        symbiosis: Optional[Any] = None      # <-- NUEVO: instancia de SymbiosisGPS
    ):
        self.zones = {z.zone_id: z for z in zones}
        self.provider = data_provider
        self.config = config or RadarConfig()
        self.rate_limiter = rate_limiter or RateLimiter(max_requests=100, window_seconds=10)
        self.calculator = DemandCalculator()
        self.detector = HotspotDetector(threshold=self.config.hotspot_threshold)
        self.alerts = AlertSystem(max_cached=self.config.alerts_max_cached)
        self.analytics = AnalyticsEngine(max_history_per_zone=self.config.history_max_per_zone)
        self.prediction = PredictionEngine(history_source=self.analytics)
        self.groups = ZoneGroupManager()
        self.exporter = ExportManager()
        self._running = False
        self._scan_thread = None
        self._watchdog_thread = None
        self._lock = threading.RLock()
        self._zone_metrics: Dict[str, ZoneMetrics] = {}
        self._opportunities: deque = deque(maxlen=self.config.max_opportunities_cached)
        self._total_scans = 0
        self._successful_scans = 0
        self._error_count = 0
        self._consecutive_errors = 0
        self._last_scan_time = None
        self._last_successful_scan = None
        self._start_time = None
        self._on_opportunity = None
        self._on_error = None
        self._on_scan_complete = None
        self._on_hotspot = None
        self._logger = self._default_logger
        self._log_enabled = True

        # NUEVO: referencia a SymbiosisGPS (para acceder a su registro)
        self.symbiosis = symbiosis

        self._setup_default_alerts()

    # ------------------------------------------------------------
    # Publicación en el registro compartido (a través de symbiosis)
    # ------------------------------------------------------------
    def _publish_to_registry(self, opportunity: Opportunity) -> None:
        """
        Publica la oportunidad detectada en el registro compartido de GPS Symbiosis
        para que CEOIA (y otros módulos) puedan reaccionar.
        """
        if self.symbiosis is None:
            return
        registry = getattr(self.symbiosis, 'registry', None)
        if registry is None:
            return

        try:
            # Oportunidad completa
            registry.set("radar:mejor_oportunidad", opportunity.to_dict())

            # Resumen ligero para decisiones rápidas
            resumen = {
                "zone_id": opportunity.zone_id,
                "zone_name": opportunity.zone_name,
                "demand_score": opportunity.demand_score,
                "surge_multiplier": opportunity.surge_multiplier,
                "priority_score": opportunity.priority_score,
                "recommendation": opportunity.recommendation,
                "timestamp": opportunity.timestamp.isoformat()
            }
            registry.set("radar:ultimo_hotspot", resumen)

            # Si la demanda es crítica, alerta especial
            if opportunity.demand_score >= 8.0:
                registry.set("radar:alerta_critica", {
                    "level": "critical",
                    "zone": opportunity.zone_name,
                    "demand": opportunity.demand_score,
                    "action": "IR_AHORA",
                    "surge": opportunity.surge_multiplier,
                    "timestamp": opportunity.timestamp.isoformat()
                })
                self._log(f"🔴 Alerta crítica publicada para {opportunity.zone_name} (demanda {opportunity.demand_score}/10)", "HOTSPOT")
        except Exception as e:
            self._log(f"Error publicando oportunidad en registro: {e}", "ERROR")

    # ------------------------------------------------------------
    # Control de monitoreo (sin cambios)
    # ------------------------------------------------------------
    def start(self) -> None:
        if self._running:
            self._log("Radar ya esta ejecutandose", "WARN")
            return
        self._running = True
        self._start_time = time.time()
        self._consecutive_errors = 0
        self._scan_thread = threading.Thread(
            target=self._scan_loop, daemon=True, name="RadarScanLoop"
        )
        self._scan_thread.start()
        if self.config.enable_watchdog:
            self._watchdog_thread = threading.Thread(
                target=self._watchdog_loop, daemon=True, name="RadarWatchdog"
            )
            self._watchdog_thread.start()
        self._log("Radar iniciado - {} zonas, intervalo {}s".format(
            len(self.zones), self.config.scan_interval_seconds), "START")

    def stop(self) -> None:
        self._log("Deteniendo radar...", "STOP")
        self._running = False
        if self._scan_thread:
            self._scan_thread.join(timeout=10)
        if self._watchdog_thread:
            self._watchdog_thread.join(timeout=5)
        self._log("Radar detenido", "STOP")

    def ensure_running(self) -> bool:
        if not self._running:
            self._log("Radar detenido - Reiniciando", "WARN")
            self.start()
            return False
        if self._scan_thread and not self._scan_thread.is_alive():
            self._log("Hilo de escaneo muerto - Reiniciando", "WARN")
            self._scan_thread = threading.Thread(
                target=self._scan_loop, daemon=True, name="RadarScanLoop"
            )
            self._scan_thread.start()
            return False
        return True

    # ------------------------------------------------------------
    # Bucle principal
    # ------------------------------------------------------------
    def _scan_loop(self) -> None:
        self._log("Bucle de escaneo iniciado", "SCAN")
        while self._running:
            scan_start = time.time()
            try:
                opportunities = self._perform_scan()
                self._consecutive_errors = 0
                self._last_successful_scan = time.time()
                self._successful_scans += 1
                if self.config.enable_analytics:
                    with self._lock:
                        self.analytics.take_snapshot(self._zone_metrics)
                if self._on_scan_complete:
                    try:
                        self._on_scan_complete(opportunities)
                    except Exception:
                        pass
            except Exception as e:
                self._error_count += 1
                self._consecutive_errors += 1
                self._log("Error en escaneo ({}/{}): {}".format(
                    self._consecutive_errors, self.config.max_consecutive_errors, e), "ERROR")
                if self._on_error:
                    try:
                        self._on_error(e)
                    except Exception:
                        pass
                if self._consecutive_errors > 3:
                    backoff = min(
                        self.config.error_backoff_base ** self._consecutive_errors,
                        self.config.error_backoff_max
                    )
                    self._log("Backoff: {}s".format(backoff), "WARN")
                    time.sleep(backoff)
                else:
                    time.sleep(5)
                continue
            self._total_scans += 1
            self._last_scan_time = time.time()
            elapsed = time.time() - scan_start
            sleep_time = max(1, self.config.scan_interval_seconds - elapsed)
            while sleep_time > 0 and self._running:
                time.sleep(min(1.0, sleep_time))
                sleep_time -= 1.0

    def _watchdog_loop(self) -> None:
        while self._running:
            try:
                if self._scan_thread and not self._scan_thread.is_alive():
                    self._log("Watchdog: Hilo detenido - Reiniciando", "WATCHDOG")
                    self._scan_thread = threading.Thread(
                        target=self._scan_loop, daemon=True, name="RadarScanLoop"
                    )
                    self._scan_thread.start()
                if self._last_successful_scan:
                    time_since = time.time() - self._last_successful_scan
                    if time_since > (self.config.scan_interval_seconds * 3):
                        self._log("Watchdog: Sin escaneos exitosos por {:.0f}s".format(time_since), "WATCHDOG")
                if self._consecutive_errors >= self.config.max_consecutive_errors:
                    self._log("Watchdog: Demasiados errores ({}) - Reset".format(self._consecutive_errors), "WATCHDOG")
                    self._reset_state()
            except Exception as e:
                self._log("Error en watchdog: {}".format(e), "ERROR")
            time.sleep(self.config.watchdog_interval_seconds)

    def _reset_state(self) -> None:
        self.rate_limiter.reset()
        self._consecutive_errors = 0
        self._log("Estado reseteado para recuperacion", "WATCHDOG")

    # ------------------------------------------------------------
    # Escaneo (con publicación al registro)
    # ------------------------------------------------------------
    def _perform_scan(self) -> List[Opportunity]:
        opportunities = []
        for zone_id, zone in self.zones.items():
            if not self._running:
                break
            if not zone.enabled:
                continue
            try:
                self.rate_limiter.wait_for_slot(max_wait=self.config.scan_timeout_per_zone)
                raw_data = self.provider.get_zone_data(zone)
                if not raw_data:
                    continue
                metrics = self._calculate_metrics(zone_id, raw_data)
                self.detector.update_history(zone_id, metrics.demand_score)
                metrics.quality_index = self.calculator.calculate_quality_index(metrics)
                metrics.efficiency_ratio = self.calculator.calculate_efficiency_ratio(metrics)
                with self._lock:
                    self._zone_metrics[zone_id] = metrics
                if self.config.enable_analytics:
                    self.analytics.record_metrics(metrics)
                if self.config.hot_zones_only and metrics.demand_score < self.config.min_demand_threshold:
                    continue
                trend = self.detector.get_trend_direction(zone_id)
                opportunity = self._create_opportunity(zone, metrics, trend)
                opportunities.append(opportunity)

                # ---------- PUBLICAR EN REGISTRO DE GPS SYMBIOSIS ----------
                self._publish_to_registry(opportunity)
                # -----------------------------------------------------------

                if self._on_opportunity:
                    try:
                        self._on_opportunity(opportunity)
                    except Exception:
                        pass
                if metrics.is_hotspot and self._on_hotspot:
                    try:
                        self._on_hotspot(zone_id, metrics)
                    except Exception:
                        pass
                if self.config.enable_alerts:
                    self.alerts.evaluate(zone, metrics)
            except Exception as e:
                self._log("Error escaneando {}: {}".format(zone_id, e), "ERROR")
                self._error_count += 1
        with self._lock:
            self._opportunities.extend(opportunities)
        return opportunities

    def _calculate_metrics(self, zone_id: str, raw_data: Dict[str, Any]) -> ZoneMetrics:
        wait_times = raw_data.get("wait_times", [])
        values = raw_data.get("values", [])
        surges = raw_data.get("surge_multipliers", [])
        capacity = raw_data.get("capacity", 0)
        requests_count = raw_data.get("requests", 0)
        is_simulated = raw_data.get("_simulated_demand") is not None
        demand_score = self.calculator.calculate_demand_score(
            wait_times=wait_times,
            surge_multipliers=surges,
            capacity=capacity,
            requests=requests_count
        )
        avg_wait = int(sum(wait_times) / len(wait_times)) if wait_times else 0
        supply_level = self.calculator.determine_supply_level(avg_wait)
        max_surge = max(surges) if surges else 1.0
        surge_detected = max_surge > 1.0
        avg_value = sum(values) / len(values) if values else 0.0
        if is_simulated:
            demand_score = raw_data.get("_simulated_demand", demand_score)
            max_surge = raw_data.get("_simulated_surge", max_surge)
            surge_detected = max_surge > 1.0
        return ZoneMetrics(
            zone_id=zone_id,
            timestamp=datetime.now(timezone.utc),
            demand_score=demand_score,
            supply_level=supply_level,
            surge_detected=surge_detected,
            surge_multiplier=round(max_surge, 2),
            average_wait_time=avg_wait,
            average_value=round(avg_value, 2),
            available_capacity=capacity,
            active_requests=requests_count,
            is_simulated=is_simulated,
            raw_data=raw_data
        )

    def _create_opportunity(self, zone: Zone, metrics: ZoneMetrics, trend: str) -> Opportunity:
        base_transactions = 3.0
        supply_factor = {
            SupplyLevel.HIGH: 1.0,
            SupplyLevel.MEDIUM: 0.8,
            SupplyLevel.LOW: 0.6,
            SupplyLevel.CRITICAL: 0.4,
            SupplyLevel.UNKNOWN: 0.7
        }.get(metrics.supply_level, 0.7)
        transactions_per_hour = base_transactions * supply_factor * metrics.surge_multiplier
        hourly_potential = self.calculator.calculate_hourly_potential(
            avg_value=metrics.average_value,
            transactions_per_hour=transactions_per_hour,
            surge_multiplier=metrics.surge_multiplier
        )
        confidence = min(0.95, 0.6 + (len(metrics.raw_data.get("wait_times", [])) * 0.1))
        priority = self.calculator.calculate_priority_score(
            demand_score=metrics.demand_score,
            surge_multiplier=metrics.surge_multiplier,
            hourly_potential=hourly_potential,
            confidence=confidence,
            weights=self.config.priority_weights
        )
        priority *= zone.priority_weight
        risk = self.calculator.determine_risk_level(
            metrics.demand_score, metrics.surge_multiplier, metrics.average_wait_time
        )
        recommendation = self.calculator.generate_recommendation(
            metrics.demand_score, metrics.surge_multiplier, trend
        )
        return Opportunity(
            opportunity_id="opp_{}_{}".format(zone.zone_id, int(time.time())),
            timestamp=metrics.timestamp,
            zone_id=zone.zone_id,
            zone_name=zone.name,
            location=zone.location,
            demand_score=metrics.demand_score,
            surge_multiplier=metrics.surge_multiplier,
            estimated_value=metrics.average_value * 0.75,
            hourly_potential=hourly_potential,
            wait_time_seconds=metrics.average_wait_time,
            priority_score=priority,
            confidence=round(confidence, 2),
            recommendation=recommendation,
            risk_level=risk,
            trend_direction=trend
        )

    # ------------------------------------------------------------
    # Consultas (sin cambios)
    # ------------------------------------------------------------
    def get_best_opportunity(self) -> Optional[Opportunity]:
        with self._lock:
            if not self._opportunities:
                return None
            return max(self._opportunities, key=lambda o: o.priority_score)

    def get_top_opportunities(self, n: int = 5) -> List[Opportunity]:
        with self._lock:
            sorted_opps = sorted(
                self._opportunities, key=lambda o: o.priority_score, reverse=True
            )
            return sorted_opps[:n]

    def get_hotspots(self, include_trending: bool = False) -> List[Tuple[str, ZoneMetrics, str, float]]:
        with self._lock:
            return self.detector.find_hotspots(self._zone_metrics, include_trending)

    def get_zone_metrics(self, zone_id: str) -> Optional[ZoneMetrics]:
        with self._lock:
            return self._zone_metrics.get(zone_id)

    def get_all_metrics(self) -> Dict[str, ZoneMetrics]:
        with self._lock:
            return dict(self._zone_metrics)

    def get_recommendation(self) -> Optional[Dict[str, Any]]:
        hotspots = self.get_hotspots()
        if not hotspots:
            return None
        zone_id, metrics, trend, magnitude = hotspots[0]
        zone = self.zones.get(zone_id)
        return {
            "recommended_zone": zone_id,
            "zone_name": zone.name if zone else zone_id,
            "demand_score": metrics.demand_score,
            "surge_multiplier": metrics.surge_multiplier,
            "wait_time_min": metrics.wait_time_minutes,
            "trend": trend,
            "trend_magnitude": magnitude,
            "quality_index": metrics.quality_index,
            "risk_level": self.calculator.determine_risk_level(
                metrics.demand_score, metrics.surge_multiplier, metrics.average_wait_time
            ),
            "reason": "Alta demanda ({}/10) con surge x{}".format(
                metrics.demand_score, metrics.surge_multiplier
            )
        }

    def force_scan(self) -> List[Opportunity]:
        return self._perform_scan()

    # ------------------------------------------------------------
    # Callbacks (sin cambios)
    # ------------------------------------------------------------
    def on_opportunity(self, callback: Callable[[Opportunity], None]) -> 'RadarEngine':
        self._on_opportunity = callback
        return self

    def on_error(self, callback: Callable[[Exception], None]) -> 'RadarEngine':
        self._on_error = callback
        return self

    def on_scan_complete(self, callback: Callable[[List[Opportunity]], None]) -> 'RadarEngine':
        self._on_scan_complete = callback
        return self

    def on_hotspot(self, callback: Callable[[str, ZoneMetrics], None]) -> 'RadarEngine':
        self._on_hotspot = callback
        return self

    # ------------------------------------------------------------
    # Configuración runtime (sin cambios)
    # ------------------------------------------------------------
    def set_scan_interval(self, seconds: int) -> None:
        self.config.scan_interval_seconds = max(10, seconds)

    def set_demand_threshold(self, score: float) -> None:
        self.config.min_demand_threshold = max(0, min(10, score))

    def set_hotspot_threshold(self, score: float) -> None:
        self.config.hotspot_threshold = max(0, min(10, score))
        self.detector.threshold = self.config.hotspot_threshold

    def set_hot_zones_only(self, enabled: bool) -> None:
        self.config.hot_zones_only = enabled

    def set_priority_weights(self, weights: Dict[str, float]) -> None:
        self.config.priority_weights = weights

    # ------------------------------------------------------------
    # Zonas dinámicas (sin cambios)
    # ------------------------------------------------------------
    def add_zone(self, zone: Zone) -> None:
        with self._lock:
            self.zones[zone.zone_id] = zone

    def remove_zone(self, zone_id: str) -> bool:
        with self._lock:
            if zone_id in self.zones:
                del self.zones[zone_id]
                self._zone_metrics.pop(zone_id, None)
                return True
            return False

    def enable_zone(self, zone_id: str) -> bool:
        zone = self.zones.get(zone_id)
        if zone:
            zone.enabled = True
            return True
        return False

    def disable_zone(self, zone_id: str) -> bool:
        zone = self.zones.get(zone_id)
        if zone:
            zone.enabled = False
            return True
        return False

    def set_zone_priority(self, zone_id: str, weight: float) -> bool:
        zone = self.zones.get(zone_id)
        if zone:
            zone.priority_weight = max(0.1, min(5.0, weight))
            return True
        return False

    # ------------------------------------------------------------
    # Exportación (sin cambios)
    # ------------------------------------------------------------
    def export_to_json(self, filepath: Optional[str] = None) -> str:
        data = self.get_status()
        json_str = self.exporter.to_json(data)
        if filepath:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(json_str)
        return json_str

    def export_opportunities_csv(self, filepath: Optional[str] = None) -> str:
        opps = self.get_top_opportunities(50)
        csv_str = self.exporter.to_csv_string(opps)
        if filepath:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(csv_str)
        return csv_str

    def export_markdown_report(self, max_rows: int = 15) -> str:
        opps = self.get_top_opportunities(max_rows)
        lines = [
            "# DEMAND RADAR REPORT",
            "Generado: {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            "",
            "## Estado del Sistema",
            "- **Estado**: {}".format("ACTIVO" if self._running else "INACTIVO"),
            "- **Zonas monitoreadas**: {}".format(len(self.zones)),
            "- **Escaneos exitosos**: {}".format(self._successful_scans),
            "- **Hotspots activos**: {}".format(len(self.get_hotspots())),
            "",
            "## Top Oportunidades",
            "",
            self.exporter.to_markdown_table(opps, max_rows),
            "",
        ]
        rec = self.get_recommendation()
        if rec:
            lines.extend([
                "## Recomendacion Actual",
                "- **Zona**: {}".format(rec["zone_name"]),
                "- **Demanda**: {}/10".format(rec["demand_score"]),
                "- **Surge**: x{}".format(rec["surge_multiplier"]),
                "- **Tendencia**: {}".format(rec.get("trend", "stable")),
                "- **Calidad**: {}/100".format(rec.get("quality_index", 0)),
                "- **Riesgo**: {}".format(rec.get("risk_level", "medium")),
                "",
            ])
        alerts = self.alerts.get_alerts(limit=5)
        if alerts:
            lines.extend([
                "## Alertas Recientes",
                "",
            ])
            for a in alerts:
                lines.append("- [{}] {}: {}".format(a.severity.upper(), a.zone_name, a.message))
            lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------
    # Estado y salud (sin cambios)
    # ------------------------------------------------------------
    def get_health(self) -> Dict[str, Any]:
        success_rate = (self._successful_scans / self._total_scans * 100) if self._total_scans > 0 else 0
        uptime = time.time() - self._start_time if self._start_time else 0
        return {
            "running": self._running,
            "uptime_seconds": round(uptime),
            "provider": self.provider.get_provider_name(),
            "provider_available": self.provider.is_available(),
            "zones_monitored": len(self.zones),
            "zones_enabled": sum(1 for z in self.zones.values() if z.enabled),
            "zones_with_data": len(self._zone_metrics),
            "total_scans": self._total_scans,
            "successful_scans": self._successful_scans,
            "success_rate": round(success_rate, 1),
            "error_count": self._error_count,
            "consecutive_errors": self._consecutive_errors,
            "opportunities_cached": len(self._opportunities),
            "hotspots_detected": len(self.get_hotspots()),
            "alerts_unacknowledged": self.alerts.unacknowledged_count,
            "scan_thread_alive": self._scan_thread.is_alive() if self._scan_thread else False,
            "watchdog_alive": self._watchdog_thread.is_alive() if self._watchdog_thread else False,
            "last_scan_seconds_ago": round(time.time() - self._last_scan_time) if self._last_scan_time else None,
            "last_successful_scan_seconds_ago": round(time.time() - self._last_successful_scan) if self._last_successful_scan else None,
            "rate_limiter_slots": self.rate_limiter.available_slots
        }

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            recent_opps = [o.to_dict() for o in list(self._opportunities)[-20:]]
            zones_status = {zid: m.to_dict() for zid, m in self._zone_metrics.items()}
            return {
                "health": self.get_health(),
                "config": self.config.to_dict(),
                "recent_opportunities": recent_opps,
                "zones_status": zones_status,
                "recommendation": self.get_recommendation(),
                "alerts_summary": self.alerts.get_stats(),
                "groups": self.groups.get_all_groups()
            }

    def is_healthy(self) -> bool:
        return (
            self._running and
            self._consecutive_errors < self.config.max_consecutive_errors and
            (self._scan_thread.is_alive() if self._scan_thread else False)
        )

    def get_compact_summary(self) -> str:
        return self.exporter.to_compact_summary(self.get_status())

    def clear_all_history(self) -> None:
        self.detector.clear_history()
        self.analytics.clear_history()
        self.alerts.clear_alerts()

    # ------------------------------------------------------------
    # Métodos internos auxiliares (sin cambios)
    # ------------------------------------------------------------
    def _setup_default_alerts(self) -> None:
        if not self.config.enable_alerts:
            return
        self.alerts.add_threshold(
            "demand_score", ">= 9.0",
            severity="critical",
            message_template="CRITICO: {zone_name} - Demanda {current_value}/10 (umbral: 9.0)",
            suppression_seconds=120
        )
        self.alerts.add_threshold(
            "demand_score", ">= 7.0",
            severity="high",
            message_template="HOTSPOT: {zone_name} - Demanda {current_value}/10",
            suppression_seconds=180
        )
        self.alerts.add_threshold(
            "surge_multiplier", ">= 1.5",
            severity="high",
            message_template="SURGE ALTO: {zone_name} - Surge x{current_value}",
            suppression_seconds=180
        )

    @staticmethod
    def _default_logger(msg: str, level: str = "INFO") -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        prefix = {
            "ERROR": "[!]",
            "WARN": "[*]",
            "START": "[+]",
            "STOP": "[-]",
            "SCAN": "[~]",
            "ALERT": "[!]",
            "HOTSPOT": "[#]",
            "WATCHDOG": "[@]"
        }.get(level, "[i]")
        print("[{}] {} [{}] {}".format(ts, prefix, level, msg), flush=True)

    def set_logger(self, logger: Callable[[str, str], None]) -> None:
        self._logger = logger

    def enable_logging(self, enabled: bool = True) -> None:
        self._log_enabled = enabled

    def _log(self, msg: str, level: str = "INFO") -> None:
        if self._log_enabled:
            try:
                self._logger(msg, level)
            except Exception:
                pass

# ============================================================================
# SECCION 12: CONTROLADOR CONTINUO (MODO POR DEFECTO)
# ============================================================================


class RadarController:
    """Controlador para ejecucion continua del radar con manejo de senales"""
    
    def __init__(self, radar: RadarEngine):
        self.radar = radar
        self._shutdown_requested = False
        
    def _signal_handler(self, signum, frame):
        """Manejador de senales para shutdown gracioso"""
        signal_name = "SIGINT" if signum == signal.SIGINT else "SIGTERM"
        self.radar._log("Recibida senal {} - Iniciando shutdown...".format(signal_name), "STOP")
        self._shutdown_requested = True
        
    def run_forever(self, status_interval: int = 300) -> None:
        """
        Ejecutar radar en modo continuo hasta interrupcion
        
        Args:
            status_interval: Segundos entre reportes de estado (default: 300 = 5min)
        """
        # Configurar handlers de senal
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        self.radar._log("=" * 60, "START")
        self.radar._log("DEMAND RADAR ENGINE v2.0 - MODO CONTINUO", "START")
        self.radar._log("Presiona Ctrl+C para detener", "INFO")
        self.radar._log("=" * 60, "START")
        
        # Iniciar radar
        self.radar.start()
        
        last_status_time = time.time()
        last_compact_time = time.time()
        
        # Bucle principal de control
        while not self._shutdown_requested and self.radar._running:
            current_time = time.time()
            
            # Reporte periodico de estado (cada status_interval segundos)
            if current_time - last_status_time >= status_interval:
                health = self.radar.get_health()
                uptime_min = health["uptime_seconds"] / 60
                
                self.radar._log("=" * 50, "SCAN")
                self.radar._log("REPORTE DE ESTADO - Uptime: {:.0f}min".format(uptime_min), "SCAN")
                self.radar._log("Zonas: {}/{} con datos | Escaneos: {} exitosos ({:.1f}%)".format(
                    health["zones_with_data"], 
                    health["zones_monitored"],
                    health["successful_scans"],
                    health["success_rate"]
                ), "SCAN")
                self.radar._log("Hotspots: {} | Alertas: {} | Errores: {}".format(
                    health["hotspots_detected"],
                    health["alerts_unacknowledged"],
                    health["consecutive_errors"]
                ), "SCAN")
                
                # Mostrar top 3 zonas
                metrics = self.radar.get_all_metrics()
                sorted_zones = sorted(metrics.items(), key=lambda x: x[1].demand_score, reverse=True)[:3]
                for zid, m in sorted_zones:
                    trend = self.radar.detector.get_trend_direction(zid)
                    trend_icon = {"up": "▲", "down": "▼", "stable": "►"}.get(trend, "►")
                    self.radar._log("  {} {}: Demanda {:.1f}/10 | Surge x{:.2f} | ETA {}min | {}".format(
                        "🔥" if m.is_hotspot else "  ",
                        zid,
                        m.demand_score,
                        m.surge_multiplier,
                        m.wait_time_minutes,
                        trend_icon
                    ), "SCAN")
                
                self.radar._log("=" * 50, "SCAN")
                last_status_time = current_time
            
            # Resumen compacto cada 2 minutos
            if current_time - last_compact_time >= 120:
                summary = self.radar.get_compact_summary()
                self.radar._log(summary.replace("\n", " | "), "SCAN")
                last_compact_time = current_time
            
            # Verificar salud del sistema cada 30 segundos
            if not self.radar.is_healthy() and self.radar._running:
                self.radar._log("Sistema no saludable - Intentando recuperacion", "WARN")
                self.radar.ensure_running()
            
            # Sleep corto para no bloquear senales
            time.sleep(1.0)
        
        # Shutdown gracioso
        self.radar._log("Deteniendo componentes...", "STOP")
        self.radar.stop()
        
        # Exportar snapshot final si hay datos
        if self.radar._successful_scans > 0:
            try:
                snapshot_file = "radar_snapshot_{}.json".format(int(time.time()))
                self.radar.export_to_json(snapshot_file)
                self.radar._log("Snapshot exportado: {}".format(snapshot_file), "INFO")
            except Exception as e:
                self.radar._log("Error exportando snapshot: {}".format(e), "ERROR")
        
        self.radar._log("=" * 60, "STOP")
        self.radar._log("RADAR DETENIDO - {} escaneos realizados".format(self.radar._successful_scans), "STOP")
        self.radar._log("=" * 60, "STOP")


# ============================================================================
# SECCION 13: CONFIGURACION POR DEFECTO
# ============================================================================


def get_default_zones() -> List[Zone]:
    """Retorna zonas por defecto optimizadas"""
    return [
        Zone("z1", "Albrook Mall",        GeoPoint(8.985, -79.52), tags=["comercial"], priority_weight=1.3),
        Zone("z2", "Arraijan Centro",     GeoPoint(8.880, -79.76), tags=["urbano"],   priority_weight=1.0),
        Zone("z3", "La Chorrera Centro",  GeoPoint(8.875, -79.78), tags=["urbano"],   priority_weight=1.0),
        Zone("z4", "San Carlos",          GeoPoint(8.885, -79.80), tags=["costero"],  priority_weight=0.9),
        Zone("z5", "Veracruz",            GeoPoint(8.855, -79.82), tags=["costero"],  priority_weight=0.8),
        Zone("z6", "Costa del Este",      GeoPoint(9.005, -79.47), tags=["premium"],  priority_weight=1.4),
        Zone("z7", "Tocumen",             GeoPoint(9.080, -79.38), tags=["transporte"], priority_weight=1.2),
        Zone("z8", "Casco Viejo",         GeoPoint(8.950, -79.53), tags=["turistico"], priority_weight=1.1),
    ]


def get_default_profiles() -> Dict[str, ZoneProfile]:
    """Retorna perfiles por defecto para las zonas"""
    return {
        "z1": ZoneProfile(base_demand=8.0, base_value=20.0, base_wait_time=180, 
                         peak_hours=[10,11,12,13,14,15,16,17,18,19], weekend_multiplier=1.4, max_surge=3.0),
        "z2": ZoneProfile(base_demand=6.5, base_value=12.0, base_wait_time=280,
                         peak_hours=[7,8,9,16,17,18], weekend_multiplier=1.2, max_surge=2.2),
        "z3": ZoneProfile(base_demand=5.5, base_value=10.0, base_wait_time=320,
                         peak_hours=[7,8,16,17], weekend_multiplier=1.1, max_surge=1.8),
        "z4": ZoneProfile(base_demand=4.5, base_value=15.0, base_wait_time=360,
                         peak_hours=[10,11,12,15,16,17], weekend_multiplier=1.5, max_surge=2.0),
        "z5": ZoneProfile(base_demand=4.0, base_value=11.0, base_wait_time=380,
                         peak_hours=[11,12,15,16], weekend_multiplier=1.3, max_surge=1.8),
        "z6": ZoneProfile(base_demand=7.5, base_value=25.0, base_wait_time=200,
                         peak_hours=[7,8,9,12,13,14,17,18,19,20], weekend_multiplier=1.2, max_surge=2.8),
        "z7": ZoneProfile(base_demand=7.0, base_value=18.0, base_wait_time=220,
                         peak_hours=[5,6,7,8,9,10,18,19,20,21,22], weekend_multiplier=1.0, max_surge=2.5),
        "z8": ZoneProfile(base_demand=6.0, base_value=16.0, base_wait_time=250,
                         peak_hours=[11,12,13,14,19,20,21,22,23], weekend_multiplier=1.6, max_surge=2.5),
    }

# ============================================================================
# SECCION 14: INTEGRACION CON GPS SYMBIOSIS + ZONAS DINAMICAS
# ============================================================================

# Importar Coordinate y SymbiosisGPS de gps_symbiosis (o usar fallback)
try:
    from gps_symbiosis import Coordinate, SymbiosisGPS
    _SYMBIOSIS_AVAILABLE = True
except ImportError:
    # Fallback: usar GeoPoint del radar como Coordinate
    Coordinate = GeoPoint
    SymbiosisGPS = None
    _SYMBIOSIS_AVAILABLE = False


# ============================================================================
# SECCION 14.1: GESTOR DE ZONAS DINAMICAS (GPS-REALTIME)
# ============================================================================


class DynamicZoneManager:
    """
    Gestiona zonas dinamicas que se actualizan desde el GPS en tiempo real.
    Reemplaza zonas fijas con datos geolocalizados dinamicamente.
    Thread-safe para uso en entorno multi-hilo.
    """
    
    def __init__(self, max_radius_km: float = 15.0, min_radius_km: float = 2.0):
        self._dynamic_zones: Dict[str, Dict[str, Any]] = {}
        self._current_location: Optional[Tuple[float, float]] = None
        self._lock = threading.RLock()
        self._max_radius = max_radius_km
        self._min_radius = min_radius_km
        self._radii_steps = [2, 5, 10, 15]

    def update_current_location(self, lat: float, lon: float) -> None:
        """Actualiza la ubicacion actual y recalcula zonas cercanas"""
        with self._lock:
            if self._current_location == (lat, lon):
                return
            self._current_location = (lat, lon)
            self._recalculate_zones()

    def _recalculate_zones(self) -> None:
        """Recalcula zonas dinamicas basadas en ubicacion actual"""
        if not self._current_location:
            return
        
        lat, lon = self._current_location
        self._dynamic_zones.clear()
        
        for i in range(8):
            angle = i * 45
            rad = math.radians(angle)
            
            for radius_km in self._radii_steps:
                if radius_km > self._max_radius:
                    continue
                    
                delta_lat = radius_km / 111.0
                delta_lon = radius_km / (111.0 * math.cos(math.radians(lat)))
                
                zone_lat = lat + delta_lat * math.cos(rad)
                zone_lon = lon + delta_lon * math.sin(rad)
                
                if not (-90 <= zone_lat <= 90 and -180 <= zone_lon <= 180):
                    continue
                
                zone_id = "dyn_{}_{}".format(i, radius_km)
                self._dynamic_zones[zone_id] = {
                    "id": zone_id,
                    "name": "Zona {}-{}km".format(chr(65+i), radius_km),
                    "latitude": round(zone_lat, 6),
                    "longitude": round(zone_lon, 6),
                    "distance_km": radius_km,
                    "bearing": angle,
                    "direction": self._bearing_to_direction(angle),
                    "updated_at": time.time(),
                    "dynamic": True
                }

    @staticmethod
    def _bearing_to_direction(bearing: float) -> str:
        """Convierte bearing en direccion cardinal"""
        directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
        return directions[int(round(bearing / 45)) % 8]

    def get_zones(self) -> List[Zone]:
        """Retorna lista de objetos Zone actualizados"""
        with self._lock:
            zones = []
            for zid, zdata in self._dynamic_zones.items():
                priority = max(0.5, 2.0 - (zdata["distance_km"] / 10.0))
                
                zone = Zone(
                    zone_id=zid,
                    name=zdata["name"],
                    location=GeoPoint(zdata["latitude"], zdata["longitude"]),
                    metadata={
                        "distance_km": zdata["distance_km"],
                        "bearing": zdata["bearing"],
                        "direction": zdata["direction"],
                        "dynamic": True,
                        "updated_at": zdata["updated_at"]
                    },
                    tags=["dynamic", "gps"],
                    enabled=True,
                    priority_weight=round(priority, 2)
                )
                zones.append(zone)
            return zones

    def get_zone_count(self) -> int:
        """Retorna numero de zonas dinamicas activas"""
        with self._lock:
            return len(self._dynamic_zones)

    def is_active(self) -> bool:
        """Verifica si hay ubicacion valida para generar zonas"""
        with self._lock:
            return self._current_location is not None

    def clear(self) -> None:
        """Limpia todas las zonas dinamicas"""
        with self._lock:
            self._dynamic_zones.clear()
            self._current_location = None

    def get_current_location(self) -> Optional[Tuple[float, float]]:
        """Retorna la ubicacion actual almacenada"""
        with self._lock:
            return self._current_location


# ============================================================================
# SECCION 14.2: PROVEEDOR DE DATOS SIMBIOSIS
# ============================================================================


class SymbiosisDataProvider(DataProviderBase):
    """
    Proveedor de datos que obtiene informacion del modulo GPS Symbiosis.
    Comparte el mismo SharedDataRegistry y GPSCore.
    """
    
    def __init__(self, symbiosis_instance=None):
        self.symbiosis = symbiosis_instance
        self._provider_name = "SymbiosisDataProvider"
        self._logger = self._default_logger
        
    def _default_logger(self, msg: str, level: str = "INFO") -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        print("[{}] [SymbiosisDataProvider] [{}] {}".format(ts, level, msg), flush=True)
        
    def set_symbiosis(self, symbiosis_instance) -> None:
        """Establece la instancia de SymbiosisGPS"""
        self.symbiosis = symbiosis_instance
        
    def _normalize_coord(self, coord) -> Optional[GeoPoint]:
        """Normaliza Coordinate o GeoPoint a GeoPoint para calculos"""
        if coord is None:
            return None
        lat = getattr(coord, 'latitude', getattr(coord, 'lat', None))
        lon = getattr(coord, 'longitude', getattr(coord, 'lon', None))
        if lat is not None and lon is not None:
            return GeoPoint(float(lat), float(lon))
        return None
        
    def get_zone_data(self, zone: Zone) -> Dict[str, Any]:
        """
        Obtiene datos de una zona usando la informacion del GPS Symbiosis.
        Combina datos de ubicacion, demanda, y estado de red.
        """
        if not self.symbiosis:
            return self._generate_fallback_data(zone)
            
        try:
            current_location = self.symbiosis.get_location()
            network_status = self.symbiosis.registry.get("network:status", {})
            
            zone_coord = Coordinate(zone.location.latitude, zone.location.longitude)
            
            if current_location:
                current_norm = self._normalize_coord(current_location)
                if current_norm:
                    distance_km = current_norm.distance_km(GeoPoint(zone.location.latitude, zone.location.longitude))
                    bearing = current_norm.bearing_to(GeoPoint(zone.location.latitude, zone.location.longitude))
                else:
                    distance_km = 0
                    bearing = 0
            else:
                distance_km = 0
                bearing = 0
            
            demand = self.symbiosis.demand_predictor.predict(
                zone.location.latitude,
                zone.location.longitude
            )
            
            geofence_status = {}
            if hasattr(self.symbiosis, 'gps') and self.symbiosis.gps:
                if hasattr(self.symbiosis.gps, 'geofence'):
                    geofence_status = self.symbiosis.gps.geofence.get_statistics()
            
            zone_in_geofence = False
            for fid, fstats in geofence_status.get('fences', {}).items():
                if fstats.get('currently_inside', False):
                    if hasattr(self.symbiosis.gps, 'geofence'):
                        fence = self.symbiosis.gps.geofence.get(fid)
                        if fence and hasattr(fence, 'contains'):
                            if fence.contains(zone_coord):
                                zone_in_geofence = True
                                break
            
            network_latency = network_status.get('latency_ms', 100)
            is_connected = network_status.get('connected', False)
            
            base_wait_time = max(60, int(distance_km * 30))
            
            if demand > 1.5:
                wait_multiplier = 0.5 + demand * 0.5
            else:
                wait_multiplier = 1.0 + (1.0 - demand) * 0.5
                
            wait_times = [
                int(base_wait_time * wait_multiplier * random.uniform(0.8, 1.2))
                for _ in range(3)
            ]
            
            base_surge = 1.0
            if demand > 1.5:
                base_surge = 1.0 + (demand - 1.0) * 2.0
            elif demand > 1.2:
                base_surge = 1.0 + (demand - 1.0) * 1.5
            
            if not is_connected:
                base_surge *= 0.8
            elif network_latency < 50:
                base_surge *= 1.2
                
            surge_multipliers = [
                round(base_surge * random.uniform(0.9, 1.1), 2)
                for _ in range(2)
            ]
            
            if zone_in_geofence:
                capacity = random.randint(2, 8)
            else:
                capacity = random.randint(8, 20)
                
            base_value = 10.0 * zone.priority_weight * demand
            
            values = [
                round(base_value * random.uniform(0.85, 1.15), 2)
                for _ in range(2)
            ]
            
            if demand > 1.3:
                requests = random.randint(10, 30)
            else:
                requests = random.randint(3, 15)
            
            current_loc_dict = None
            if current_location:
                current_norm = self._normalize_coord(current_location)
                if current_norm:
                    current_loc_dict = {
                        "lat": current_norm.latitude,
                        "lon": current_norm.longitude
                    }
            
            symbiosis_data = {
                "distance_km": round(distance_km, 2),
                "bearing_degrees": round(bearing, 1),
                "zone_in_geofence": zone_in_geofence,
                "network_connected": is_connected,
                "network_latency_ms": network_latency,
                "demand_factor": round(demand, 2),
                "current_location": current_loc_dict
            }
            
            return {
                "wait_times": wait_times,
                "values": values,
                "surge_multipliers": surge_multipliers,
                "capacity": capacity,
                "requests": requests,
                "_simulated_demand": round(min(10.0, demand * 4), 2),
                "_simulated_surge": base_surge,
                "_symbiosis_data": symbiosis_data
            }
            
        except Exception as e:
            self._logger("Error obteniendo datos de simbiosis para zona {}: {}".format(zone.zone_id, e), "WARN")
            return self._generate_fallback_data(zone)
    
    def _generate_fallback_data(self, zone: Zone) -> Dict[str, Any]:
        """Genera datos de respaldo cuando no hay simbiosis disponible"""
        return {
            "wait_times": [random.randint(180, 600) for _ in range(3)],
            "values": [round(10.0 * zone.priority_weight, 2) for _ in range(2)],
            "surge_multipliers": [round(random.uniform(1.0, 1.5), 2) for _ in range(2)],
            "capacity": random.randint(5, 15),
            "requests": random.randint(3, 12),
            "_simulated_demand": round(random.uniform(3.0, 7.0), 2),
            "_simulated_surge": round(random.uniform(1.0, 1.3), 2),
            "_symbiosis_data": {"status": "fallback"}
        }
    
    def is_available(self) -> bool:
        """Verifica si el proveedor esta disponible"""
        return self.symbiosis is not None
    
    def get_provider_name(self) -> str:
        return self._provider_name


# ============================================================================
# SECCION 14.3: CONTROLADOR INTEGRADO ACTUALIZADO
# ============================================================================

class IntegratedRadarController:
    """
    Controlador que integra el Radar Engine con GPS Symbiosis.
    Ambos sistemas comparten datos y trabajan en armonia.
    Incluye soporte para zonas dinamicas basadas en GPS.
    """
    
    def __init__(self):
        self.symbiosis = None
        self.radar = None
        self.data_provider = None
        self._running = False
        self.dynamic_zone_manager = DynamicZoneManager()
        self._last_zone_update = 0
        self._zone_update_interval = 30.0
        
    def initialize(self, use_real_gps: bool = False) -> None:
        """
        Inicializa ambos sistemas y los conecta.
        
        Args:
            use_real_gps: Si es True, intenta usar GPS real (Termux)
        """
        if SymbiosisGPS is None:
            print("\n[ERROR] No se encontro gps_symbiosis.py en el mismo directorio.")
            print("Ambos archivos deben estar juntos: demand_radar.py y gps_symbiosis.py")
            sys.exit(1)
        
        print("\n" + "=" * 70)
        print("  INICIALIZANDO SISTEMA INTEGRADO")
        print("  GPS Symbiosis + Demand Radar Engine + Zonas Dinamicas")
        print("=" * 70)
        
        print("\n[1/4] Iniciando GPS Symbiosis...")
        self.symbiosis = SymbiosisGPS(use_real_gps=use_real_gps)
        print("  GPS Symbiosis iniciado")
        
        print("\n[2/4] Configurando zonas de monitoreo...")
        zones = self._create_zones_from_symbiosis()
        print("  {} zonas configuradas".format(len(zones)))
        
        print("\n[3/4] Creando proveedor de datos integrado...")
        self.data_provider = SymbiosisDataProvider(self.symbiosis)
        
        print("\n[4/4] Iniciando Demand Radar Engine...")
        config = RadarConfig(
            scan_interval_seconds=30,
            hotspot_threshold=6.5,
            enable_watchdog=True,
            enable_alerts=True,
            enable_analytics=True,
            enable_prediction=True,
            max_consecutive_errors=15,
            error_backoff_max=120
        )
        
        self.radar = RadarEngine(
            zones=zones,
            data_provider=self.data_provider,
            config=config
        )
        
        self._setup_groups_from_geofences()
        self._setup_integration_callbacks()
        self._setup_dynamic_zones_callback()
        
        # ============================================================
        # INTEGRACION SOLICITADA
        # ============================================================
        self.radar.on_opportunity(self._on_radar_opportunity)
        
        print("  Radar Engine iniciado")
        print("\n" + "=" * 70)
        print("  SISTEMA INTEGRADO LISTO")
        print("=" * 70 + "\n")
        
    def _on_radar_opportunity(self, opp: Opportunity) -> None:
        """
        Callback centralizado para manejo de oportunidades detectadas.
        Integra publicacion en registry y logica de alerta critica.
        """
        self._publish_to_registry(opp)
        # resto de la lógica existente...
        if opp.demand_score >= 8.0:
            self.radar._log(
                "OPORTUNIDAD CRITICA: {} - Score: {:.1f}/10 - Surge: x{:.2f} - ${:.2f}/h".format(
                    opp.zone_name, opp.demand_score, opp.surge_multiplier, opp.hourly_potential
                ),
                "HOTSPOT"
            )

    def _publish_to_registry(self, opp: Opportunity) -> None:
        """Publica datos de oportunidad en el registro de simbiosis."""
        if not self.symbiosis or not hasattr(self.symbiosis, 'registry'):
            return
        self.symbiosis.registry.set(
            "radar:opportunity:{}".format(opp.zone_id),
            opp.to_dict()
        )
        
    def _setup_dynamic_zones_callback(self) -> None:
        """Configura callback para actualizar zonas dinamicas con GPS"""
        if not self.symbiosis or not hasattr(self.symbiosis, 'gps') or not self.symbiosis.gps:
            return
            
        def on_location_change(coord):
            lat = getattr(coord, 'latitude', getattr(coord, 'lat', None))
            lon = getattr(coord, 'longitude', getattr(coord, 'lon', None))
            
            if lat is None or lon is None:
                return
                
            self.dynamic_zone_manager.update_current_location(lat, lon)
            
            current_time = time.time()
            if current_time - self._last_zone_update >= self._zone_update_interval:
                self._update_radar_with_dynamic_zones()
                self._last_zone_update = current_time
        
        if hasattr(self.symbiosis.gps, 'on_location_change'):
            self.symbiosis.gps.on_location_change(on_location_change)
        
        # Sincronizar ubicacion inicial
        initial_location = self.symbiosis.get_location()
        if initial_location:
            init_lat = getattr(initial_location, 'latitude', getattr(initial_location, 'lat', None))
            init_lon = getattr(initial_location, 'longitude', getattr(initial_location, 'lon', None))
            if init_lat is not None and init_lon is not None:
                self.dynamic_zone_manager.update_current_location(init_lat, init_lon)
                if self.radar:
                    self.radar._log("Zonas dinamicas inicializadas con ubicacion GPS", "INFO")
        
    def _update_radar_with_dynamic_zones(self) -> None:
        """Actualiza las zonas del radar con zonas dinamicas"""
        if not self.radar or not self.dynamic_zone_manager.is_active():
            return
            
        try:
            dynamic_zones = self.dynamic_zone_manager.get_zones()
            
            static_zones = [
                z for z in self.radar.zones.values() 
                if "dynamic" not in z.tags
            ]
            
            all_zones = static_zones + dynamic_zones
            
            with self.radar._lock:
                self.radar.zones = {z.zone_id: z for z in all_zones}
                
            self.radar._log(
                "Zonas actualizadas: {} estaticas + {} dinamicas = {} total".format(
                    len(static_zones), len(dynamic_zones), len(all_zones)
                ),
                "SCAN"
            )
            
        except Exception as e:
            if self.radar:
                self.radar._log("Error actualizando zonas dinamicas: {}".format(e), "ERROR")
    
    def _create_zones_from_symbiosis(self) -> List[Zone]:
        """Crea zonas iniciales (se enriquecen despues con GPS)"""
        base_zones = [
            Zone("z1", "Albrook Mall", GeoPoint(8.985, -79.52), 
                 tags=["comercial", "static"], priority_weight=1.3),
            Zone("z2", "Arraijan Centro", GeoPoint(8.880, -79.76), 
                 tags=["urbano", "static"], priority_weight=1.0),
            Zone("z3", "La Chorrera Centro", GeoPoint(8.875, -79.78), 
                 tags=["urbano", "static"], priority_weight=1.0),
            Zone("z4", "San Carlos", GeoPoint(8.885, -79.80), 
                 tags=["costero", "static"], priority_weight=0.9),
            Zone("z5", "Veracruz", GeoPoint(8.855, -79.82), 
                 tags=["costero", "static"], priority_weight=0.8),
            Zone("z6", "Costa del Este", GeoPoint(9.005, -79.47), 
                 tags=["premium", "static"], priority_weight=1.4),
            Zone("z7", "Tocumen", GeoPoint(9.080, -79.38), 
                 tags=["transporte", "static"], priority_weight=1.2),
            Zone("z8", "Casco Viejo", GeoPoint(8.950, -79.53), 
                 tags=["turistico", "static"], priority_weight=1.1),
        ]
        
        if self.symbiosis:
            current_location = self.symbiosis.get_location()
            
            for zone in base_zones:
                if current_location:
                    zone_point = GeoPoint(zone.location.latitude, zone.location.longitude)
                    current_norm = self.data_provider._normalize_coord(current_location) if self.data_provider else None
                    if current_norm:
                        distance = current_norm.distance_km(zone_point)
                        
                        if distance < 5:
                            zone.priority_weight *= 1.5
                        elif distance > 50:
                            zone.priority_weight *= 0.7
                        
                        zone.metadata.update({
                            "distance_from_current_km": round(distance, 2),
                            "demand_factor": self.symbiosis.demand_predictor.predict(
                                zone.location.latitude, 
                                zone.location.longitude
                            )
                        })
        
        return base_zones
    
    def _create_profiles_from_symbiosis(self, zones: List[Zone]) -> Dict[str, ZoneProfile]:
        """Crea perfiles de zona basados en datos de simbiosis"""
        profiles = {}
        
        for zone in zones:
            demand_factor = zone.metadata.get("demand_factor", 1.0)
            distance = zone.metadata.get("distance_from_current_km", 10)
            
            profile = ZoneProfile(
                base_demand=min(10.0, 4.0 + demand_factor * 3),
                base_value=10.0 + zone.priority_weight * 5,
                base_wait_time=max(60, int(180 + distance * 10)),
                peak_hours=[7, 8, 9, 17, 18, 19],
                weekend_multiplier=1.0 + (demand_factor - 1.0) * 0.5,
                max_surge=1.5 + zone.priority_weight * 1.5
            )
            
            profiles[zone.zone_id] = profile
        
        return profiles
    
    def _setup_groups_from_geofences(self) -> None:
        """Configura grupos de zonas basados en geocercas activas"""
        if not self.symbiosis or not self.radar:
            return
        
        commercial_zones = []
        transport_zones = []
        coastal_zones = []
        
        for zone_id, zone in self.radar.zones.items():
            if "comercial" in zone.tags or "premium" in zone.tags or "turistico" in zone.tags:
                commercial_zones.append(zone_id)
            if "transporte" in zone.tags:
                transport_zones.append(zone_id)
            if "costero" in zone.tags:
                coastal_zones.append(zone_id)
        
        if commercial_zones:
            self.radar.groups.create_group("comercial", commercial_zones, 
                                          {"tipo": "zonas_comerciales"})
        if transport_zones:
            self.radar.groups.create_group("transporte", transport_zones, 
                                          {"tipo": "zonas_transporte"})
        if coastal_zones:
            self.radar.groups.create_group("costero", coastal_zones, 
                                          {"tipo": "zonas_costeras"})
    
    def _setup_integration_callbacks(self) -> None:
        """Configura callbacks para sincronizacion entre sistemas"""
        if not self.symbiosis or not self.radar:
            return
        
        def on_hotspot(zone_id: str, metrics: ZoneMetrics):
            self.symbiosis.registry.set(
                "radar:hotspot:{}".format(zone_id),
                {
                    "zone_id": zone_id,
                    "demand_score": metrics.demand_score,
                    "surge_multiplier": metrics.surge_multiplier,
                    "timestamp": metrics.timestamp.isoformat()
                }
            )
        
        def on_scan_complete(opportunities: List[Opportunity]):
            summary = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "total_opportunities": len(opportunities),
                "top_zone": opportunities[0].zone_id if opportunities else None,
                "max_demand": max((o.demand_score for o in opportunities), default=0)
            }
            self.symbiosis.registry.set("radar:scan_summary", summary)
        
        def on_location_change(coord):
            current_norm = self.data_provider._normalize_coord(coord) if self.data_provider else None
            if not current_norm:
                return
            
            for zone_id, zone in self.radar.zones.items():
                zone_point = GeoPoint(zone.location.latitude, zone.location.longitude)
                distance = current_norm.distance_km(zone_point)
                
                if distance < 3:
                    self.radar.set_zone_priority(zone_id, 2.0)
                elif distance < 8:
                    self.radar.set_zone_priority(zone_id, 1.5)
                elif distance > 30:
                    self.radar.set_zone_priority(zone_id, 0.7)
        
        def on_network_change(key: str, value: Any):
            if isinstance(value, dict) and value.get("connected"):
                self.radar._log("Red conectada - Optimizando escaneos", "INFO")
            else:
                self.radar._log("Red desconectada - Modo offline", "WARN")
        
        self.radar.on_hotspot(on_hotspot)
        self.radar.on_scan_complete(on_scan_complete)
        
        if hasattr(self.symbiosis, 'gps') and self.symbiosis.gps:
            if hasattr(self.symbiosis.gps, 'on_location_change'):
                self.symbiosis.gps.on_location_change(on_location_change)
        
        if hasattr(self.symbiosis, 'registry'):
            self.symbiosis.registry.on_change("network:status", on_network_change)
    
    def start(self) -> None:
        """Inicia el sistema integrado"""
        if self._running:
            print("Sistema ya esta ejecutandose")
            return
        
        self._running = True
        
        self.radar.start()
        
        print("\n" + "=" * 70)
        print("  SISTEMA INTEGRADO EN EJECUCION")
        print("  Presiona Ctrl+C para detener")
        print("=" * 70 + "\n")
        
        self._print_status()
        
        last_status_time = time.time()
        
        try:
            while self._running:
                current_time = time.time()
                
                if current_time - last_status_time >= 300:
                    self._print_status()
                    last_status_time = current_time
                
                if not self.radar.is_healthy():
                    self.radar._log("Sistema no saludable - Recuperando...", "WARN")
                    self.radar.ensure_running()
                
                time.sleep(1)
                
        except KeyboardInterrupt:
            print("\n[EXIT] Deteniendo sistema integrado...")
        finally:
            self.stop()
    
    def _print_status(self) -> None:
        """Imprime el estado actual del sistema integrado"""
        if not self.radar:
            return
        
        health = self.radar.get_health()
        location = self.symbiosis.get_location() if self.symbiosis else None
        
        print("\n" + "-" * 70)
        print("ESTADO DEL SISTEMA - {}".format(datetime.now().strftime('%H:%M:%S')))
        print("-" * 70)
        
        if location:
            loc_norm = self.data_provider._normalize_coord(location) if self.data_provider else None
            if loc_norm:
                print("Ubicacion: {:.6f}, {:.6f}".format(loc_norm.latitude, loc_norm.longitude))
        
        print("Red: {} | Escaneos: {} exitosos ({:.1f}%)".format(
            "Conectada" if health.get('provider_available') else "Desconectada",
            health['successful_scans'],
            health['success_rate']
        ))
        print("Hotspots: {} | Alertas: {}".format(
            health['hotspots_detected'],
            health['alerts_unacknowledged']
        ))
        
        # Info zonas dinamicas
        if self.dynamic_zone_manager.is_active():
            dyn_count = self.dynamic_zone_manager.get_zone_count()
            print("Zonas dinamicas activas: {}".format(dyn_count))
        
        metrics = self.radar.get_all_metrics()
        if metrics:
            sorted_zones = sorted(metrics.items(), key=lambda x: x[1].demand_score, reverse=True)[:3]
            print("\nTop 3 Zonas:")
            for zid, m in sorted_zones:
                zone = self.radar.zones.get(zid)
                zone_name = zone.name if zone else zid
                trend = self.radar.detector.get_trend_direction(zid)
                trend_icon = {"up": "^", "down": "v", "stable": ">"}.get(trend, ">")
                
                symb_data = m.raw_data.get("_symbiosis_data", {})
                dist_str = " | {}km".format(symb_data.get('distance_km', '?')) if symb_data else ""
                
                print("  {} {}: {}/10 | Surge x{:.2f} | ETA {}min{}".format(
                    "HOT" if m.is_hotspot else "   ",
                    zone_name,
                    m.demand_score,
                    m.surge_multiplier,
                    m.wait_time_minutes,
                    dist_str
                ))
        
        print("-" * 70 + "\n")
    
    def stop(self) -> None:
        """Detiene el sistema integrado"""
        self._running = False
        
        if self.radar:
            print("Deteniendo Radar Engine...")
            self.radar.stop()
        
        if self.symbiosis:
            print("Guardando datos de simbiosis...")
            self.symbiosis.shutdown()
        
        print("\n" + "=" * 70)
        print("  SISTEMA INTEGRADO DETENIDO")
        print("=" * 70)


# ============================================================================
# MAIN: ARRANQUE AUTOMÁTICO DEL SISTEMA INTEGRADO
# ============================================================================

def main():
    """Punto de entrada principal - inicia el sistema integrado automáticamente"""
    
    print("\n" + "=" * 70)
    print("  DEMAND RADAR ENGINE + GPS SYMBIOSIS")
    print("  Sistema Integrado de Monitoreo Continuo")
    print("=" * 70)
    print("  Ambos sistemas comparten datos en tiempo real")
    print("  Presiona Ctrl+C para detener gracefulmente")
    print("=" * 70 + "\n")
    
    # Crear controlador integrado
    controller = IntegratedRadarController()
    
    try:
        # Inicializar ambos sistemas
        controller.initialize(use_real_gps=False)
        
        # Iniciar ejecución continua
        controller.start()
        
    except KeyboardInterrupt:
        print("\n[EXIT] Terminado por usuario")
    except Exception as e:
        print(f"\n[ERROR] {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n[OK] Sistema integrado detenido correctamente\n")


if __name__ == "__main__":
    main()
