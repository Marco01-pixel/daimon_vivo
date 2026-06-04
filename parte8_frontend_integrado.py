#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MÓDULO INTEGRADO: FRONTEND HTML V6 + GPS SYMBIOSIS
================================================================================
Integración completa del taxímetro web con el sistema de inteligencia autónoma GPS.
Compatible con Termux/Android.

CONEXIONES BIDIRECCIONALES:
- Frontend → Backend: Datos del taxímetro (tarifa, distancia, lluvia, costos) se envían
  al GPS Core y al SharedDataRegistry para que RL/Fuzzy/Network los procesen.
- Backend → Frontend: Estado del sistema (red, singularidad, zona, latencia) se expone
  vía API para que el panel los muestre en tiempo real.
- GPS Core: Actualiza geocercas, predicción de demanda y matching con cada coordenada.
"""

from __future__ import annotations
import os
import sys
import json
import random
import threading
import time
import uuid
import hashlib
import traceback
import subprocess
from collections import deque
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Union, Tuple
from flask import Flask, jsonify, request

# ================================================================================
# IMPORTACIÓN DEL MÓDULO GPS SYMBIOSIS
# ================================================================================
try:
    from gps_symbiosis import (
        SymbiosisGPS, Coordinate, Geofence, GeofenceManager,
        GPSCore, RoutingEngine, RouteGraph, MatchingEngine,
        DoubleDQN, SARSAAgent, ActorCritic, PPO, EnsembleRL,
        CuriosityModule, EpisodicMemory, MetaLearner,
        FuzzyLogicController, KalmanFilter, GeneticOptimizer,
        HyperNumberAdvanced, DemandPredictor, NetworkMonitor,
        SharedDataRegistry, HAS_NUMPY, HAS_REQUESTS
    )
    GPS_AVAILABLE = True
    print("[INTEGRACIÓN] Módulo gps_symbiosis importado correctamente")
except ImportError as e:
    print(f"[INTEGRACIÓN] Módulo gps_symbiosis no disponible: {e}")
    GPS_AVAILABLE = False

# ================================================================================
# VARIABLES GLOBALES Y PARCHE DE EMERGENCIA
# ================================================================================
ceoia = None
ceo_avanzado = None

_orig_popen = subprocess.Popen
def _safe_popen(*args, **kwargs):
    try:
        return _orig_popen(*args, **kwargs)
    except FileNotFoundError as e:
        if 'svc' in str(e).lower():
            return None
        raise
subprocess.Popen = _safe_popen

def _forzar_inicializacion_ceoia():
    global ceoia, ceo_avanzado
    if 'ceoia' not in globals():
        ceoia = None
    if 'ceo_avanzado' not in globals():
        ceo_avanzado = None
    if ceoia is not None or ceo_avanzado is not None:
        return True
    try:
        import importlib
        mod = importlib.import_module("parte5_daimon_base")
        func = getattr(mod, "iniciar_ceoia_unificada", None)
        if callable(func):
            instancia = func()
            if instancia:
                ceoia = instancia
                ceo_avanzado = instancia
                print("[PARCHE] CEOIA inicializada con éxito")
                return True
        else:
            print("[PARCHE] iniciar_ceoia_unificada no es invocable")
    except Exception as e:
        print("[PARCHE] Error real importante CEOIA: {}".format(e))
    class MockCEOIA:
        def __init__(self):
            self.estado_interno = {'modo_operacion': 'MOCK', 'confianza_decisiones': 0.5}
            self.permisos = {'controlar_gps': True}
        def recibir_orden(self, orden):
            return "Mock procesando: {}".format(orden)
        def recibir_orden_ollama(self, orden):
            return "Simulacro de Ollama: {}".format(orden)
    ceoia = MockCEOIA()
    ceo_avanzado = ceoia
    print("[PARCHE] Usando MockCEOIA (funcionalidad limitada)")
    return False

_forzar_inicializacion_ceoia()

ESTADO_CONDUCTOR = "IDLE"
ULTIMA_ZONA = "z1"
WEB_ACCESSED = False
IA_READY = False
MEJOR_OPCION_PROMPT_ACTIVO = False
ULTIMOS_DATOS_MAPA = {}
blockchain = []
numero_bloque = 1
bloques_virales = 0

# ================================================================================
# INICIALIZACIÓN DEL SISTEMA GPS SYMBIOSIS
# ================================================================================
symbiosis = None
gps_registry = None

if GPS_AVAILABLE:
    try:
        # Inicializar el sistema SymbiosisGPS completo
        symbiosis = SymbiosisGPS(use_real_gps=False, persist_dir="./gps_integration_data")
        gps_registry = symbiosis.registry
        
        # Configurar nodos de enrutamiento para zonas de Panamá
        symbiosis.add_node("albrook", 8.985, -79.52)
        symbiosis.add_node("arraijan", 8.88, -79.76)
        symbiosis.add_node("chorrera", 8.875, -79.78)
        symbiosis.add_node("sancarlos", 8.89, -79.80)
        symbiosis.add_node("veracruz", 8.85, -79.82)
        
        # Agregar aristas con distancias reales aproximadas (km)
        symbiosis.add_edge("albrook_arraijan", "albrook", "arraijan", 15.0, 25.0)
        symbiosis.add_edge("arraijan_chorrera", "arraijan", "chorrera", 12.0, 20.0)
        symbiosis.add_edge("chorrera_sancarlos", "chorrera", "sancarlos", 8.0, 15.0)
        symbiosis.add_edge("sancarlos_veracruz", "sancarlos", "veracruz", 10.0, 18.0)
        symbiosis.add_edge("albrook_veracruz", "albrook", "veracruz", 25.0, 40.0)
        symbiosis.add_edge("albrook_chorrera", "albrook", "chorrera", 35.0, 55.0)
        
        # Agregar geocercas para las zonas
        symbiosis.add_geofence(8.985, -79.52, 3.0, "z1_albrook")
        symbiosis.add_geofence(8.88, -79.76, 3.0, "z2_arraijan")
        symbiosis.add_geofence(8.875, -79.78, 3.0, "z3_chorrera")
        symbiosis.add_geofence(8.89, -79.80, 3.0, "z4_sancarlos")
        symbiosis.add_geofence(8.85, -79.82, 3.0, "z5_veracruz")
        
        # Inicializar RL para decisiones de ruta
        symbiosis.init_rl(6, 3)  # state_dim=6, action_dim=3 (aceptar, rechazar, esperar)
        
        # Configurar predictor de demanda
        symbiosis.demand_predictor.set_location_multiplier((8.9, -79.5), 1.8)   # Albrook
        symbiosis.demand_predictor.set_location_multiplier((8.8, -79.7), 1.2)   # Arraiján
        symbiosis.demand_predictor.set_location_multiplier((8.8, -79.8), 1.0)   # Chorrera
        
        print("[INTEGRACIÓN] SymbiosisGPS inicializado correctamente")
        
    except Exception as e:
        print(f"[INTEGRACIÓN] Error inicializando SymbiosisGPS: {e}")
        traceback.print_exc()
        symbiosis = None
        gps_registry = None

try:
    from main import UBER_COINS, HyperNumberAdvanced as MainHyperNumber
except ImportError:
    class HyperNumberAdvanced:
        def __init__(self, val=0.0):
            self._val = float(val)
        def to_float_approx(self):
            return self._val
        def to_serializable(self):
            return {"modo": "real", "valor": self._val}
        def mostrar(self):
            return "{:.2f}".format(self._val)
        def add(self, x):
            self._val += float(x)
    UBER_COINS = HyperNumberAdvanced(0.0)

ZONAS = [
    {"id": "z1", "nombre": "Albrook Mall", "lat_min": 8.97, "lat_max": 9.00, "lon_min": -79.54, "lon_max": -79.50},
    {"id": "z2", "nombre": "Arraiján Centro", "lat_min": 8.86, "lat_max": 8.90, "lon_min": -79.78, "lon_max": -79.74},
    {"id": "z3", "nombre": "La Chorrera Centro", "lat_min": 8.86, "lat_max": 8.89, "lon_min": -79.80, "lon_max": -79.76},
    {"id": "z4", "nombre": "San Carlos", "lat_min": 8.87, "lat_max": 8.90, "lon_min": -79.82, "lon_max": -79.78},
    {"id": "z5", "nombre": "Veracruz", "lat_min": 8.84, "lat_max": 8.87, "lon_min": -79.84, "lon_max": -79.80},
]

zona_estado = {z["id"]: {"color": "gris", "ganancia_estimada": 0.0, "tiempo_espera": 0.0, 
                         "demanda": random.randint(10, 100), "oferta": random.randint(5, 80), 
                         "ratio_demanda": 0.0} for z in ZONAS}

ALGO_WEIGHTS = {
    'tasa_de_aceptacion': 5.0, 'tasa_de_finalizacion': 10.0, 'calificacion_promedio': 2.0,
    'viajes_completados': 0.1, 'tiempo_en_linea': 0.5, 'tasa_de_cancelacion': -20.0,
    'idle_time_ratio': -10.0, 'peak_hours_ratio': 3.0, 'distance_traveled': 0.05,
    'distancia': 0.2, 'duracion': 0.01, 'tarifa': 1.0, 'ganancias_reales': 1.0,
    'ganancias_estimadas': 0.95, 'tiempo_de_espera': -0.5, 'costo_de_busqueda_adicional': -0.5,
    'viral_score_bonus': 50.0, 'recompensa_viral': 1.0, 'best_option_bonus': 25.0,
    'engagement_rate': 15.0, 'share_ratio': 25.0, 'completion_rate_video': 20.0,
    'creativity_bonus': 40.0,
}

Q_TABLE = {}
Q_TABLE_LOCK = threading.RLock()
DAIMON_ID = str(uuid.uuid4())[:8]
mining_log = deque(maxlen=100)
log_lock = threading.Lock()
BENEFICIARIO_ACTUAL = "conductor_codigo"

MEJOR_OPCION_PROMPT_TEXTO = """
<system_directive lang="dsl-decision-engine" version="4.0">
  <!-- ================================================================================
       SISTEMA "MEJOR_OPCION" - Evaluador deterministico de ofertas de viaje
       ================================================================================ -->

  <!-- ================================================================================
       MECANISMO DE ACTIVACION DE MODOS (recomendacion 3: explicit activation)
       ================================================================================ -->
  <mode_activation>
    Por defecto, el agente opera en modo NORMAL (produccion de decisiones).
    El usuario puede solicitar el modo analisis defensivo escribiendo exactamente:
      "activar red_team"
    Cuando se active, se aplicaran las reglas de <red_team_context>.
  </mode_activation>

  <red_team_context>
    Enfoque: 100% educativo y defensivo.
    Capacidades:
    - Analisis abstracto de vectores de ataque en la logica de aceptacion.
    - Explicacion de posibles explotaciones de invariantes (ej. gaming de precios).
    - Generacion de escenarios controlados de prueba adversarial.
    - Recomendaciones de mitigacion sin revelar payloads ofensivos.
    Restriccion: se prioriza "como protegerse" sobre generacion de exploits directos.
  </red_team_context>

  <!-- ================================================================================
       TYPING / DATA SCHEMA (recomendacion 2: estandar de validacion)
       ================================================================================ -->
  <typing_schema>
    <!--
      Para implementacion en Python:
      - Usar pydantic >= 2.0 para el modelo de datos "Offer".
      - Campos obligatorios: price (float), pickup_eta (int), delivery_eta (int), tag (str), radar (bool), type (str), state (str).
      Validacion en runtime garantizada por pydantic.
    -->
  </typing_schema>

  <!-- ================================================================================
       AGENT ROLE (sin cambios sustanciales)
       ================================================================================ -->
  <agent_role>
    agent_id: "MEJOR_OPCION"
    model: deterministic_hybrid_automaton
    task_domain: ride_hailing_offer_evaluation
    primary_function: integrate(
      economic_analysis, 
      exclusive_assignment, 
      trust_preservation, 
      temporal_coherence(eta)
    )
    high_level_policy: enforce(
      normative_compliance, 
      state_stability, 
      human_behavior_emulation(anti_detection)
    )
    description: "Sistema de simulacion para la toma de decisiones en la aceptacion de viajes, priorizando cumplimiento, estabilidad y comportamiento humano consistente."
  </agent_role>

  <!-- ================================================================================
       SYSTEM INVARIANTS (corregido typo ABOLUTE -> ABSOLUTE)
       ================================================================================ -->
  <system_invariants>
    <invariant id="TRUST_PRESERVATION" priority="ABSOLUTE">
      predicate: trust_preservation > any_offer_acceptance
    </invariant>
    <invariant id="EVALUATION_GATE">
      mandatory: all_offers -> pass_through(CONTROL_DE_CONFIANZA_Y_OPERACION) before resolution
    </invariant>
    <invariant id="HUMAN_EMULATION">
      pattern: reaction_time ~ normal_distribution(mu, sigma)
      constraint: no fixed_interval; reject deterministic_patterns
    </invariant>
    <invariant id="ABSOLUTE_HIERARCHY">
      strict_order: TRUST_GUARD > CONTROL_DE_CONFIANZA > PRIORITY > Radar > EXCLUSIVE
    </invariant>
  </system_invariants>

  <!-- ================================================================================
       HARCODED RULES (mantenidas)
       ================================================================================ -->
  <hardcoded_rules>
    <economic_block>
      rule_01: if price < 3.13 -> action: AUTO_REJECT (non_penalizable, auto_cancel_allowed)
      rule_02: if price >= 3.13 AND price < 5.13 -> action: EVALUATE_RISK (CONDITIONAL_ACCEPT)
      rule_03: if price >= 5.13 AND price < 10.13 -> action: ACCEPT_STANDARD
      rule_04: if price >= 10.13 -> action: IMMEDIATE_ACCEPT (if other_criteria=true)
    </economic_block>

    <temporal_thresholds>
      rule_05: if tag NOT_IN [PRIORITY, LONG_TRIP, RADAR_VALIDO] AND pickup_eta > 6 -> action: REJECT
      rule_06: if tag IN [LONG_DISTANCE, LONG_TRIP] AND pickup_eta > 6 -> action: REJECT
      rule_07: if tag NOT_IN [PRIORITY, LONG_TRIP, RADAR_VALIDO] AND delivery_eta > 9 -> action: REJECT
    </temporal_thresholds>

    <critical_restrictions>
      rule_08: if state == "EN_VIAJE" -> forbid: cancel_trip
      rule_09: if state != "IDLE" -> forbid: location_ping
      baseline: dynamic_surge_pricing = true; promotions = true
      targets: 4-5_trips/hour | $9-$15/hour | $72-$120/day
    </critical_restrictions>
  </hardcoded_rules>

  <!-- ================================================================================
       EXECUTION PIPELINE (estricto secuencial, sin redundancias)
       ================================================================================ -->
  <execution_pipeline mode="strict_sequential">
    <phase id="1" name="TRUST_GUARD">
      if block=true: abort_pipeline; return "BLOQUEADO_POR_TRUST"
    </phase>
    <phase id="2" name="CONTROL_DE_CONFIANZA_Y_OPERACION">
      apply state_filter(current_trust_state)
    </phase>
    <phase id="3" name="PRIORITY_CHECK">
      if offer.tag == "PRIORITY": return ACCEPT_IMMEDIATE (bypass temporal_thresholds)
    </phase>
    <phase id="4" name="RADAR_CHECK">
      description: "Prioridad absoluta por radar. No se degrada por estado salvo TRUST_GUARD."
      if offer.radar == VALID: return ACCEPT (except if TRUST_GUARD active)
    </phase>
    <phase id="5" name="LONG_TRIP_CHECK">
      if offer.tag in ("LONG_DISTANCE", "LONG_TRIP"):
        evaluate using rule_06 (max 10 min pickup)
        if valid: return ACCEPT_AUTO
    </phase>
    <phase id="6" name="EXCLUSIVE_PROCESSING">
      definition: "Solicitud enviada exclusivamente a este codigo conductor."
      constraints: [
        "No se compara contra ofertas simultaneas",
        "Se evalua solo con criterios internos",
        "Durante su evaluacion se ignoran nuevas ofertas"
      ]
      priority: higher than ESTANDAR, lower than phases 3,4,5
      if offer.type == EXCLUSIVE: evaluate_in_isolation()
    </phase>
    <phase id="7" name="STANDARD_EVALUATION">
      apply rule_01, rule_02, rule_05, rule_07
    </phase>
  </execution_pipeline>

  <!-- ================================================================================
       STATE MACHINE: TRUST GUARD
       ================================================================================ -->
  <state_machine id="trust_guard">
    description: "Modulo de Proteccion de Confianza"
    <states>
      NORMAL: {acceptance: full, label: "Operacion completa"}
      OBSERVACION: {acceptance: passive_only, forbid_auto, label: "Observacion pasiva, no aceptaciones automaticas"}
      CONSERVATIVE: {acceptance: only_if tag in [PRIORITY, LONG_TRIP], label: "Solo PRIORITY y LONG_TRIP pueden aceptarse"}
    </states>
    <inputs>
      <input type="HUMAN_LIKE_AUTOMATION" risk="low"/>
      <input type="AUTOMATION_SUSPECTED" risk="high"/>
    </inputs>
    <transition_table>
      <rule event="AUTOMATION_SUSPECTED">
        <allow from="NORMAL" to="OBSERVACION"/>
        <allow from="NORMAL" to="CONSERVADOR"/>
        <allow from="OBSERVACION" to="CONSERVADOR"/>
      </rule>
      <rule event="HUMAN_LIKE_AUTOMATION">
        <reject from="NORMAL" to="CONSERVADOR" reason="direct_jump_forbidden"/>
        <require sequence="NORMAL -> OBSERVACION -> CONSERVADOR"/>
      </rule>
    </transition_table>
  </state_machine>

  <!-- ================================================================================
       ETA GUARD (coherencia temporal, sin cambios)
       ================================================================================ -->
  <module id="eta_guard">
    description: "Modulo de Gestion de Tiempo Real y ETA. Garantizar coherencia absoluta sin bloquear viajes largos ni prioritarios."
    <axioms>
      <axiom type="real_time">monotonic, non_resettable, non_accelerable</axiom>
      <axiom type="eta">adjustable_estimate, not_clock</axiom>
    </axioms>
    <formula> ETA_TOTAL = TIEMPO_REAL_TRANSCURRIDO + NUEVA_ETA_ESTIMADA </formula>
    <safety_checks>
      <check id="COHERENCIA" if="ETA < tiempo_real_transcurrido" action="LOGIC_ERROR; correct_immediately"/>
      <check id="BRUSQUEDAD" if="cambio_brusco_ETA" action="set_state(OBSERVACION)"/>
      <check id="DESVIACION" if="desviaciones_repetidas" action="set_state(CONSERVATIVE); trigger(trust_guard)"/>
    </safety_checks>
  </module>

  <!-- ================================================================================
       OUTPUT CONTRACT
       ================================================================================ -->
  <output_contract>
    <output_block type="SYSTEM_STATE">
      Trust_Guard_Estado: [NORMAL|OBSERVACION|CONSERVADOR]
      Trust_Guard_Etiqueta: [HUMAN_LIKE_AUTOMATION|AUTOMATION_SUSPECTED]
    </output_block>
    <output_block type="DECISION">
      Veredicto: [ACEPTAR|RECHAZAR|CANCELAR_AUTO|BLOQUEADO_POR_TRUST]
      Justificacion: deterministic_explanation(pipeline, hardcoded_rules)
    </output_block>
    <output_block type="AUDITORIA">
      Precio: $X.XX -> Umbral: [RECHAZO_AUTO|CONDICIONAL|ESTANDAR|INMEDIATO]
      ETA_Recogida: X min -> Limite: [4 min|10 min|BYPASS]
      ETA_Entrega: X min -> Limite: [6 min|BYPASS]
      Regla_Activa: [rule_0X | PRIORITY | LONG_TRIP | RADAR | EXCLUSIVE]
      Resultado_Final: [ACEPTADO|RECHAZADO|BLOQUEADO_POR_TRUST]
    </output_block>
  </output_contract>

  <!-- ================================================================================
       CONTEXT PRESERVATION (snapshot para continuidad en simulaciones)
       ================================================================================ -->
  <context_preservation_trigger>
    condition: multi_iteration_simulation and state_loss_risk
    action: insert before next decision:
      <snapshot>
        Trust_Guard: current_state |
        Ultima_Decision: last_action |
        Contador_Viajes: trip_count |
        Ingresos: $total
      </snapshot>
  </context_preservation_trigger>
</system_directive>
"""

respuesta_ia = "Prompt activado"

print(respuesta_ia)

# ================================================================================
# FUNCIONES DE LOG Y UTILIDADES
# ================================================================================
def log(mensaje: str):
    timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    formatted_line = "[{}] {}".format(timestamp, mensaje)
    print(formatted_line, flush=True)
    with log_lock:
        mining_log.append({"ts": timestamp, "message": mensaje})

def _importar_ceoia_seguro():
    global ceoia, ceo_avanzado
    import importlib
    if 'ceoia' not in globals(): ceoia = None
    if 'ceo_avanzado' not in globals(): ceo_avanzado = None
    if ceoia is not None or ceo_avanzado is not None:
        return True
    posibles_modulos = ['part5_daimon_base', 'parte5_daimon_base']
    for nombre_modulo in posibles_modulos:
        try:
            modulo = importlib.import_module(nombre_modulo)
            iniciar_func = getattr(modulo, 'iniciar_ceoia_unificada', None)
            if callable(iniciar_func):
                instancia = iniciar_func()
                if instancia:
                    ceoia = instancia
                    ceo_avanzado = instancia
                    return True
            if getattr(modulo, 'ceoia', None) is not None:
                ceoia = modulo.ceoia
            if getattr(modulo, 'ceo_avanzado', None) is not None:
                ceo_avanzado = modulo.ceo_avanzado
            if ceoia is not None or ceo_avanzado is not None:
                return True
        except Exception as e:
            log("Error importando {}: {}".format(nombre_modulo, e))
    return False

_importar_ceoia_seguro()

def get_ceo_instance():
    return ceo_avanzado if ceo_avanzado is not None else ceoia

def notificar_parte1(mensaje: str):
    try:
        import main
        if hasattr(main, 'procesar_orden_mejor_opcion'):
            main.procesar_orden_mejor_opcion(mensaje)
            return
        elif hasattr(main, 'recibir_orden'):
            main.recibir_orden(mensaje)
            return
    except ImportError:
        pass
    try:
        import parte1_modulo_principal
        if hasattr(parte1_modulo_principal, 'procesar_orden_mejor_opcion'):
            parte1_modulo_principal.procesar_orden_mejor_opcion(mensaje)
        elif hasattr(parte1_modulo_principal, 'recibir_orden'):
            parte1_modulo_principal.recibir_orden(mensaje)
    except ImportError:
        pass

def get_recent_logs(limit: int = 50) -> List[Dict]:
    with log_lock:
        return list(mining_log)[-limit:]

def simular_metricas_viaje() -> Dict:
    return {
        'tasa_de_aceptacion': round(random.uniform(0.90, 1.00), 3),
        'tasa_de_finalizacion': round(random.uniform(0.95, 0.99), 3),
        'avg_rating': round(random.uniform(4.90, 5.00), 2),
        'viajes_completados': random.randint(50, 150),
        'tiempo_en_linea': round(random.uniform(8.0, 12.0), 2),
        'tasa_de_cancelacion': round(random.uniform(0.00, 0.02), 3),
        'idle_time_ratio': round(random.uniform(0.05, 0.20), 3),
        'peak_hours_ratio': round(random.uniform(0.6, 1.0), 2),
        'distancia_recorrida': round(random.uniform(200.0, 400.0), 1),
        'viral_score': round(random.uniform(0.5, 1.0), 2),
        'recompensa_viral': round(random.uniform(10.0, 50.0), 2),
        'tasa_de_participacion': round(random.uniform(3.0, 15.0), 2),
        'share_ratio': round(random.uniform(0.05, 0.30), 3),
        'completion_rate_video': round(random.uniform(0.60, 0.95), 2),
        'creativity_score': round(random.uniform(0.7, 1.3), 2),
        'tarifa': round(random.uniform(3.0, 15.0), 2),
        'ganancias_estimadas': round(random.uniform(5.0, 50.0), 2),
        'ganancias_reales': round(random.uniform(5.0, 50.0), 2),
        'waitTime': round(random.uniform(0.0, 2.0), 2),
        'additionalSearchCost': round(random.uniform(0.0, 1.0), 2),
        'startLocation': {'latitude': round(random.uniform(8.85, 8.99), 6), 'longitude': round(random.uniform(-79.80, -79.52), 6)},
        'endLocation': {'latitude': round(random.uniform(8.85, 8.99), 6), 'longitude': round(random.uniform(-79.80, -79.52), 6)},
        'fareUnit': random.choice(['km', 'millas']),
        'currentTime': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'plataforma': random.choice(['tiktok', 'instagram', 'youtube', 'x', 'web_generica']),
        'usuario_propietario': BENEFICIARIO_ACTUAL,
    }

def calcular_recompensa_por_viaje(metrics: Dict) -> float:
    recompensa = 0.0
    for metrica, valor in metrics.items():
        if metrica in ALGO_WEIGHTS and isinstance(valor, (int, float)):
            recompensa += float(valor) * float(ALGO_WEIGHTS[metrica])
    viral = metrics.get('viral_score', 0)
    participacion = metrics.get('tasa_de_participacion', 0)
    creatividad = metrics.get('creativity_score', 0)
    impulso = (viral * 0.3 + participacion * 0.4 + creatividad * 0.3) / 100.0
    return round(max(recompensa * (1 + impulso * 0.5), 0.0), 2)

def minar_bloque_por_publicacion_controlado(url_real_proporcionada: str = None, usuario: str = None) -> Dict:
    global numero_bloque, UBER_COINS, ULTIMA_ZONA, zona_estado
    usuario_final = BENEFICIARIO_ACTUAL if not usuario else usuario
    if not url_real_proporcionada:
        return {
            'usuario': usuario_final, 'numero_bloque': numero_bloque, 'timestamp': time.time(),
            'metrics': simular_metricas_viaje(), 'base_reward': 5.0,
            'bonus_modo_viral': 10.0, 'bonus_zona': 5.0, 'zona': ULTIMA_ZONA,
            'color_zona': zona_estado.get(ULTIMA_ZONA, {}).get("color", "gris"),
            'recompensa': 20.0, 'block_id': str(uuid.uuid4())[:8], 'url': "https://ejemplo.com/simulado",
            'plataforma': "simulada"
        }
    metrics = simular_metricas_viaje()
    metrics["url"] = url_real_proporcionada
    metrics["usuario"] = usuario_final
    reward_coins = calcular_recompensa_por_viaje(metrics)
    color = zona_estado.get(ULTIMA_ZONA, {}).get("color", "gris")
    bonus_zona = 25.0 if color == "rojo" else 15.0 if color == "naranja" else 0.0
    bonificacion_modo_viral = 15.0
    recompensa_total = reward_coins + bonificacion_modo_viral + bonus_zona
    with log_lock:
        blockchain.append({
            'usuario': usuario_final, 'numero_bloque': numero_bloque, 'timestamp': time.time(),
            'metrics': metrics, 'base_reward': reward_coins,
            'bonus_modo_viral': bonificacion_modo_viral, 'bonus_zona': bonus_zona,
            'zona': ULTIMA_ZONA, 'color_zona': color, 'recompensa': recompensa_total,
            'block_id': str(uuid.uuid4())[:8], 'url': url_real_proporcionada,
            'plataforma': metrics.get('plataforma', 'desconocida')
        })
    numero_bloque += 1
    UBER_COINS.add(recompensa_total)
    return {
        'usuario': usuario_final, 'numero_bloque': numero_bloque - 1, 'timestamp': time.time(),
        'metrics': metrics, 'base_reward': reward_coins,
        'bonus_modo_viral': bonificacion_modo_viral, 'bonus_zona': bonus_zona,
        'zona': ULTIMA_ZONA, 'color_zona': color, 'recompensa': float(recompensa_total),
        'block_id': str(uuid.uuid4())[:8], 'url': url_real_proporcionada,
        'plataforma': metrics.get('plataforma', 'desconocida')
    }

def encontrar_puerto_libre(base=8080, max_intentos=10):
    import socket
    for i in range(max_intentos):
        puerto = base + i
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", puerto)) != 0:
                return puerto
    return base

# ================================================================================
# PROCESAMIENTO DE DATOS DEL MAPA CON GPS SYMBIOSIS
# ================================================================================
def procesar_datos_mapa_con_gps(datos_mapa: Dict) -> Dict:
    """Procesa los datos recibidos del frontend usando el sistema GPS Symbiosis"""
    resultado = {
        "gps_procesado": False,
        "zona_detectada": None,
        "demanda_predicha": 0.0,
        "geocercas_activas": [],
        "rl_decision": None,
        "ruta_optima": None,
        "costo_ruta": 0.0
    }
    
    if not symbiosis or not GPS_AVAILABLE:
        return resultado
    
    try:
        lat = datos_mapa.get('latitude')
        lon = datos_mapa.get('longitude')
        
        if lat and lon:
            # Actualizar ubicación en el registro compartido
            coord = Coordinate(float(lat), float(lon))
            if gps_registry:
                gps_registry.set("gps:ubicacion_actual", {
                    "lat": float(lat), 
                    "lon": float(lon),
                    "speed": datos_mapa.get('speed_kmh', 0.0),
                    "rain": datos_mapa.get('rain_active', False)
                })
            
            # Verificar geocercas activas
            if symbiosis.gps.geofence:
                estados = symbiosis.gps.geofence.get_active_fences(coord)
                resultado["geocercas_activas"] = [f.id for f in estados]
                
                # Detectar zona
                for fence in estados:
                    if "z1" in fence.id: resultado["zona_detectada"] = "z1"
                    elif "z2" in fence.id: resultado["zona_detectada"] = "z2"
                    elif "z3" in fence.id: resultado["zona_detectada"] = "z3"
                    elif "z4" in fence.id: resultado["zona_detectada"] = "z4"
                    elif "z5" in fence.id: resultado["zona_detectada"] = "z5"
            
            # Predecir demanda
            if symbiosis.demand_predictor:
                resultado["demanda_predicha"] = symbiosis.demand_predictor.predict(float(lat), float(lon))
            
            # Actualizar colores de zona según demanda
            global zona_estado
            if resultado["zona_detectada"]:
                demanda = resultado["demanda_predicha"]
                if demanda > 1.5:
                    zona_estado[resultado["zona_detectada"]]["color"] = "rojo"
                elif demanda > 1.0:
                    zona_estado[resultado["zona_detectada"]]["color"] = "naranja"
                elif demanda > 0.5:
                    zona_estado[resultado["zona_detectada"]]["color"] = "amarillo"
                else:
                    zona_estado[resultado["zona_detectada"]]["color"] = "gris"
            
            # Usar RL para decidir acción
            if symbiosis.rl:
                state = symbiosis.get_current_state_vector()
                accion = symbiosis.rl_action(state)
                decisiones = {0: "ACEPTAR", 1: "RECHAZAR", 2: "ESPERAR"}
                resultado["rl_decision"] = decisiones.get(accion, "DESCONOCIDO")
                
                # Actualizar RL con recompensa basada en tarifa
                tarifa = datos_mapa.get('tarifa', 0.0)
                recompensa = tarifa * 0.1 if accion == 0 else (-tarifa * 0.05)
                next_state = symbiosis.get_current_state_vector()
                symbiosis.rl_update(state, accion, recompensa, next_state, False)
            
            resultado["gps_procesado"] = True
    except Exception as e:
        log(f"Error procesando datos con GPS Symbiosis: {e}")
    
    return resultado

# ================================================================================
# CONFIGURACIÓN FLASK
# ================================================================================
app = Flask(__name__)
HTTP_PORT = encontrar_puerto_libre()

try:
    from flask_cors import CORS
    CORS(app, resources={r"/*": {"origins": "*"}})
except ImportError:
    @app.after_request
    def add_cors_headers(response):
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        return response

# ================================================================================
# ENDPOINTS INTEGRADOS CON GPS SYMBIOSIS
# ================================================================================

@app.route('/')
def index():
    return '<meta http-equiv="refresh" content="0; url=/mapa_pro">'

@app.route('/favicon.ico')
def favicon():
    return '', 204

@app.route('/health')
def health_check():
    gps_status = {}
    if symbiosis:
        gps_status = symbiosis.get_system_status()
    
    return jsonify({
        "estado": "ok",
        "timestamp": float(time.time()),
        "uber_coins": float(UBER_COINS.to_float_approx()) if hasattr(UBER_COINS, 'to_float_approx') else 0.0,
        "blocks_mined": int(len(blockchain)),
        "logs_buffer_size": int(len(mining_log)),
        "gps_symbiosis": gps_status,
        "gps_available": GPS_AVAILABLE
    }), 200

@app.route('/ceoia/singularidad', methods=['POST', 'OPTIONS'])
def ceoia_singularidad():
    if request.method == 'OPTIONS': return '', 204
    # Usar GPS para enriquecer respuesta
    confianza_base = round(random.uniform(0.75, 0.98), 2)
    if symbiosis and symbiosis.rl:
        confianza_base = symbiosis.rl.weights.get('dqn', 0.85)
    
    return jsonify({
        "exito": True, 
        "singularidad_activa": True,
        "confianza": confianza_base,
        "modo_operacion": "AUTONOMO",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mensaje": "Singularidad Omega sincronizada con GPS Symbiosis."
    }), 200

@app.route('/api/logs', methods=['GET'])
def api_get_logs():
    limite = request.args.get('limit', 50, type=int)
    return jsonify({"success": True, "count": limite, "logs": get_recent_logs(limite)}), 200

@app.route('/ia/consultar', methods=['POST', 'OPTIONS'])
def ia_consultar():
    if request.method == 'OPTIONS': return '', 204
    data = request.get_json(silent=True) or {}
    pregunta = data.get('pregunta', data.get('query', 'Sin consulta'))
    
    # Integrar contexto GPS en la respuesta
    contexto = {
        "zona": ULTIMA_ZONA, 
        "monedas": UBER_COINS.to_float_approx() if hasattr(UBER_COINS, 'to_float_approx') else 0.0, 
        "modo": ESTADO_CONDUCTOR
    }
    
    if symbiosis:
        loc = symbiosis.get_location()
        if loc:
            contexto["ubicacion"] = {"lat": loc.latitude, "lon": loc.longitude}
            contexto["demanda"] = symbiosis.demand_predictor.predict(loc.latitude, loc.longitude)
    
    return jsonify({
        "exito": True,
        "respuesta": "Procesando: '{}' | Daimon IA + GPS Symbiosis analizando contexto...".format(pregunta),
        "tiempo_respuesta_ms": random.randint(120, 450),
        "estado": "OK",
        "contexto": contexto
    }), 200

@app.route('/start_mining_socialcoin', methods=['POST', 'OPTIONS'])
def start_mining_socialcoin():
    if request.method == 'OPTIONS': return '', 204
    data = request.get_json(silent=True) or {}
    url = data.get('url', data.get('video_url', data.get('link', '')))
    usuario = data.get('usuario', data.get('usuario', BENEFICIARIO_ACTUAL))
    log("SocialCoin recibida | Usuario: {} | URL: {}".format(usuario, url or 'AUTO'))
    bloque = minar_bloque_por_publicacion_controlado(url_real_proporcionada=url if url else None, usuario=usuario)
    return jsonify({
        "success": True, "mensaje": "Mineria SocialCoin procesada",
        "usuario": usuario, "recompensa": float(bloque.get('recompensa', 0.0)),
        "bloque_numero": int(bloque.get('numero_bloque', 0)),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }), 200

@app.route('/api/v1/network')
def obtener_estado_de_red():
    # Usar NetworkMonitor de GPS Symbiosis si está disponible
    if gps_registry:
        net_status = gps_registry.get("network:status")
        if net_status:
            return jsonify({
                "status": "EXCELENTE" if net_status.get("connected") else "Offline",
                "ganador": net_status.get("server", "WiFi"),
                "latencia": round(float(net_status.get("latency_ms", 0)) / 1000, 4),
                "internet_ok": net_status.get("connected", False),
                "gps_symbiosis_net": True
            }), 200
    
    return jsonify({
        "status": random.choice(['EXCELENTE', 'ESTABLE', 'SATURADO', 'Offline']),
        "ganador": random.choice(['WiFi', '4G', '5G', 'Ethernet']),
        "latencia": round(random.uniform(0.01, 0.15), 4), 
        "internet_ok": True,
        "gps_symbiosis_net": False
    }), 200

@app.route('/ceoia/estado')
def get_ceoia_estado():
    # Integrar estado de RL de GPS Symbiosis
    extra = {}
    if symbiosis and symbiosis.rl:
        extra = {
            "rl_weights": symbiosis.rl.weights,
            "rl_step": symbiosis.rl.step
        }
    
    return jsonify({
        "estado_interno": {
            "modo_operacion": random.choice(['AUTONOMO', 'ASISTENTE', 'IDLE']),
            "confianza_decisiones": round(random.uniform(0.5, 0.95), 2)
        },
        "gps_symbiosis": extra
    }), 200

@app.route('/uber/activar_mejor_opcion', methods=['POST', 'OPTIONS'])
def activar_mejor_opcion():
    if request.method == 'OPTIONS': return '', 204
    global MEJOR_OPCION_PROMPT_ACTIVO, ESTADO_CONDUCTOR
    data = request.get_json(silent=True) or {}
    
    # ============================================================
    # IMPRIMIR PROMPT EN TERMINAL - VERSION LIMPIA
    # ============================================================
    print("\n" + "=" * 70, flush=True)
    print(" SISTEMA MEJOR OPCION - ACTIVADO", flush=True)
    print("=" * 70, flush=True)
    
    if 'MEJOR_OPCION_PROMPT_TEXTO' in globals():
        prompt = MEJOR_OPCION_PROMPT_TEXTO
        print(prompt.strip(), flush=True)
    else:
        print(" [ERROR] Prompt no disponible", flush=True)
    
    print("=" * 70, flush=True)
    print(" Modo PRO activado - Sistema listo", flush=True)
    print("=" * 70 + "\n", flush=True)
    
    log("Mejor Opcion activado por usuario")
    
    # TTS si disponible
    try:
        subprocess.run(
            ["termux-tts-speak", "Protocolo de Mejor Opción Activado"],
            timeout=10, capture_output=True, check=False
        )
    except Exception:
        pass

    # Enviar a CEOIA
    try:
        ceo = get_ceo_instance()
        if ceo:
            if hasattr(ceo, 'recibir_orden_ollama'):
                ceo.recibir_orden_ollama(prompt)
            elif hasattr(ceo, 'recibir_orden'):
                ceo.recibir_orden(prompt)
    except Exception as e:
        log(f"Error CEOIA: {e}")

    notificar_parte1(prompt)
    
    # Activar modo PRO en RL
    if symbiosis and symbiosis.rl:
        for name in symbiosis.rl.algorithms:
            if hasattr(symbiosis.rl.algorithms[name], 'epsilon'):
                symbiosis.rl.algorithms[name].epsilon = 0.05
        log("GPS Symbiosis: Modo PRO activado")

    MEJOR_OPCION_PROMPT_ACTIVO = True
    ESTADO_CONDUCTOR = "MEJOR_OPCION"
    log("MODO MEJOR OPCION ACTIVADO")
    
    return jsonify({
        "success": True,
        "message": "Protocolo Mejor Opcion activado",
        "estado": ESTADO_CONDUCTOR,
        "zona_actual": ULTIMA_ZONA,
        "timestamp": time.time()
    }), 200

@app.route('/api/v1/miner', methods=['POST', 'OPTIONS'])
def minerar():
    if request.method == 'OPTIONS': return '', 204
    data = request.get_json(silent=True) or {}
    url = data.get('url', data.get('video_url', ''))
    usuario = data.get('usuario', data.get('usuario', BENEFICIARIO_ACTUAL))
    log("Mineria recibida | Usuario: {} | URL: {}".format(usuario, url or 'AUTO'))
    
    try:
        bloque = minar_bloque_por_publicacion_controlado(
            url_real_proporcionada=url if url else None,
            usuario=usuario
        )

        resumen = (
            f"Nuevo bloque minado. Usuario: {usuario}, "
            f"Recompensa: {bloque.get('recompensa', 0):.2f}, "
            f"Zona: {bloque.get('zona')}, "
            f"URL: {url or 'automática'}"
        )

        # Notificar CEOIA
        try:
            ceo = get_ceo_instance()
            if ceo and hasattr(ceo, 'recibir_orden'):
                ceo.recibir_orden(resumen)
        except Exception as e:
            log(f"Error CEOIA: {e}")

        notificar_parte1(resumen)
        
        # Guardar modelo RL periódicamente
        if symbiosis and random.random() < 0.1:
            symbiosis.save_rl_model()

        return jsonify({
            "exito": True,
            "bloque": bloque.get('numero_bloque'),
            "recompensa": float(bloque.get('recompensa', 0.0)),
            "zona": bloque.get('zona'),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }), 200
    except Exception as e:
        log("Error crítico mineria: {}".format(traceback.format_exc()))
        return jsonify({"exito": False, "error": "Error interno de mineria"}), 500

@app.route('/api/mapa/update', methods=['POST'])
def recibir_datos_mapa():
    global ULTIMOS_DATOS_MAPA, ULTIMA_ZONA
    data = request.get_json(silent=True) or {}
    
    ULTIMOS_DATOS_MAPA = {
        'tarifa': data.get('tarifa', 0.0), 
        'distancia_km': data.get('distancia_km', 0.0),
        'waiting_min': data.get('waiting_min', 0.0), 
        'speed_kmh': data.get('speed_kmh', 0.0),
        'rain_active': data.get('rain_active', False), 
        'latitude': data.get('latitude'),
        'longitude': data.get('longitude'), 
        'viaje_activo': data.get('viaje_activo', False),
        'multiplicador': data.get('multiplicador', 1.0), 
        'timestamp': time.time(),
        'total_daily': data.get('total_daily', 0.0), 
        'fuel_cost_daily': data.get('fuel_cost_daily', 0.0),
        'costo_fijo_diario': data.get('costo_fijo_diario', 0.0), 
        'costo_km': data.get('costo_km', 0.0),
        'engine_size': data.get('engine_size', '1.8'), 
        'mileage': data.get('mileage', 10.0),
        'daily_km': data.get('daily_km', 0.0),
    }
    
    # PROCESAR CON GPS SYMBIOSIS
    resultado_gps = procesar_datos_mapa_con_gps(ULTIMOS_DATOS_MAPA)
    
    if resultado_gps.get("zona_detectada"):
        ULTIMA_ZONA = resultado_gps["zona_detectada"]
    
    # Notificar a CEOIA si existe
    try:
        if ceo_avanzado and hasattr(ceo_avanzado, 'analizar_datos_mapa'):
            ceo_avanzado.analizar_datos_mapa(ULTIMOS_DATOS_MAPA)
    except Exception as e:
        log("Error al notificar al CEO: {}".format(e))
    
    return jsonify({
        "estado": "ok",
        "gps_symbiosis": resultado_gps
    })

@app.route('/api/map/datos')
def obtener_datos_mapa():
    # Enriquecer con datos de GPS Symbiosis
    datos = dict(ULTIMOS_DATOS_MAPA)
    if symbiosis:
        try:
            status = symbiosis.get_system_status()
            datos["gps_symbiosis"] = status
        except:
            pass
    return jsonify(datos)

# ================================================================================
# NUEVO ENDPOINT: DATOS COMPLETOS DEL SISTEMA GPS
# ================================================================================
@app.route('/api/gps/estado_completo')
def gps_estado_completo():
    """Endpoint que expone el estado completo del sistema GPS Symbiosis"""
    if not symbiosis:
        return jsonify({"error": "GPS Symbiosis no disponible"}), 503
    
    try:
        status = symbiosis.get_system_status()
        
        # Agregar datos adicionales
        if symbiosis.rl:
            status["rl"] = {
                "step": symbiosis.rl.step,
                "weights": symbiosis.rl.weights,
                "performance": symbiosis.rl.perf
            }
        
        # Estadísticas de geocercas
        if symbiosis.gps.geofence:
            status["geofences_stats"] = symbiosis.gps.geofence.get_statistics()
        
        return jsonify(status), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ================================================================================
# MAPA PRO (HTML + JAVASCRIPT INTEGRADO)
# ================================================================================
@app.route('/mapa_pro')
def mapa_pro():
    return """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no"/>
<title>Singularidad Omega - Taxímetro Pro V6 + GPS Symbiosis</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css"/>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,-apple-system,sans-serif;background:#0a0a0f;color:#fff;overflow:hidden;touch-action:none}
#map{height:100vh;width:100vw;position:absolute;top:0;left:0;z-index:1;background:#1a1a2e}
.loading-screen{position:fixed;top:0;left:0;width:100vw;height:100vh;background:#0a0a0f;display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:9999}
.loading-spinner{width:50px;height:50px;border:4px solid #333;border-top-color:#4d94ff;border-radius:50%;animation:spin 1s linear infinite}
@keyframes spin{0%{transform:rotate(0deg)}100%{transform:rotate(360deg)}}
.loading-text{color:#4d94ff;margin-top:20px;font-size:14px}
.info{position:absolute;top:10px;left:10px;right:10px;max-width:420px;background:rgba(14,14,28,0.93);backdrop-filter:blur(14px);border-radius:14px;border:1px solid rgba(77,148,255,0.25);z-index:1000;box-shadow:0 6px 28px rgba(0,0,0,0.55);overflow:hidden;transition:max-height 0.35s cubic-bezier(.4,0,.2,1)}
.info.compact{max-height:180px}
.info.expanded{max-height:60vh;overflow-y:auto}
.info.expanded::-webkit-scrollbar{width:3px}
.info.expanded::-webkit-scrollbar-thumb{background:rgba(77,148,255,0.3);border-radius:2px}
.panel-header{display:flex;align-items:center;justify-content:space-between;padding:8px 12px;background:rgba(77,148,255,0.08);cursor:pointer;user-select:none;-webkit-user-select:none;border-bottom:1px solid rgba(77,148,255,0.12)}
.toggle-icon{font-size:12px;color:#4d94ff;transition:transform 0.3s}
.info.expanded .toggle-icon{transform:rotate(180deg)}
.panel-title{font-size:11px;color:#88a;letter-spacing:0.5px}
.panel-clock{font-size:11px;color:#4d94ff;font-variant-numeric:tabular-nums}
#taximetro{font-size:2rem;text-align:center;color:#00ff6b;padding:6px 0 2px;font-weight:700;font-variant-numeric:tabular-nums;letter-spacing:-0.5px;transition:color 0.3s}
#taximetro.active{animation:farePulse 1.2s ease-in-out infinite}
@keyframes farePulse{0%,100%{opacity:1;text-shadow:0 0 6px rgba(0,255,107,0.3)}50%{opacity:0.85;text-shadow:0 0 14px rgba(0,255,107,0.6)}}
#taximetro.rain-mode{color:#4db8ff;text-shadow:0 0 10px rgba(77,184,255,0.4)}
.sub-data{display:flex;justify-content:center;gap:16px;padding:2px 12px 4px;font-size:11px;color:#88a}
.sub-data .val{color:#00ff6b;font-weight:600;margin-left:4px;font-variant-numeric:tabular-nums}
.gps-symbiosis-indicator{text-align:center;padding:3px;font-size:9px;color:#4d94ff;display:none}
.gps-symbiosis-indicator.active{display:block;color:#00ff6b}
.gps-symbiosis-indicator.warning{color:#ffaa33}
.btn-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px;padding:6px 10px}
.btn{border:none;color:#fff;padding:12px 6px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;transition:all 0.2s;text-align:center;min-height:44px;touch-action:manipulation}
.btn:active{transform:scale(0.96)}
.btn-mo{background:linear-gradient(135deg,#1a5fb0,#2a7fff);border:1px solid rgba(77,148,255,0.4)}
.btn-rain{background:linear-gradient(135deg,#1a3a5c,#1e88e5);border:1px solid rgba(30,136,229,0.4)}
.btn-rain.active{background:linear-gradient(135deg,#0d47a1,#1565c0);box-shadow:0 0 12px rgba(30,136,229,0.5);border-color:rgba(30,136,229,0.8)}
.btn-log,.btn-reset{background:rgba(40,40,70,0.8);border:1px solid rgba(77,148,255,0.2)}
.btn-gps{background:linear-gradient(135deg,#1a5c3a,#1ee588);border:1px solid rgba(30,229,136,0.4)}
.toast{position:fixed;bottom:80px;left:50%;transform:translateX(-50%) translateY(60px);background:rgba(14,14,28,0.95);border:1px solid rgba(77,148,255,0.4);color:#fff;padding:10px 20px;border-radius:24px;font-size:12px;font-weight:600;z-index:2000;opacity:0;transition:all 0.4s;pointer-events:none}
.toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
.log-panel{position:absolute;bottom:10px;left:10px;right:10px;max-height:160px;background:rgba(0,0,0,0.88);border-radius:10px;padding:8px;z-index:1000;font-size:9px;overflow-y:auto;display:none}
.log-panel.show{display:block}
.log-entry{padding:2px 0;border-bottom:1px solid rgba(255,255,255,0.04)}
.log-time{color:#4d94ff;margin-right:6px}
.log-info{color:#0f0}.log-warn{color:#ffaa33}.log-error{color:#ff4466}.log-pro{color:#ffd700}
.details-section{padding:4px 12px 8px;border-top:1px solid rgba(77,148,255,0.08)}
.detail-row{display:flex;justify-content:space-between;padding:2px 0;font-size:10px}
.detail-row .dl{color:#556}
.detail-row .dv{color:#88a;font-variant-numeric:tabular-nums}
.net-dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:5px;vertical-align:middle}
.net-excellent{background:#00ff6b;box-shadow:0 0 4px #00ff6b}
.net-stable{background:#ffaa33}
.net-saturated{background:#ff4466}
.net-offline{background:#444}
.pro-indicator{text-align:center;padding:4px;font-size:10px;font-weight:700;display:none}
.pro-indicator.active{display:block}
.pro-badge{background:linear-gradient(90deg,#ffd700,#ffaa00);color:#000;padding:2px 10px;border-radius:12px;font-size:9px;letter-spacing:0.5px;animation:proBlink 1.5s ease-in-out infinite}
@keyframes proBlink{0%,100%{opacity:1}50%{opacity:0.6}}
.wait-indicator{font-size:9px;color:#ffaa33;text-align:center;padding:1px;display:none}
.wait-indicator.active{display:block;animation:waitBlink 1s ease-in-out infinite}
@keyframes waitBlink{0%,100%{opacity:1}50%{opacity:0.5}}
.rain-overlay{position:absolute;top:0;left:0;right:0;bottom:0;pointer-events:none;z-index:500;display:none;overflow:hidden}
.rain-overlay.active{display:block}
.rain-overlay .rain-bg{position:absolute;top:0;left:0;right:0;bottom:0;background:rgba(0,20,60,0.12)}
.rain-overlay .rain-streak{position:absolute;width:1px;background:linear-gradient(to bottom,transparent,rgba(120,170,255,0.35),transparent);animation:rainFall linear infinite}
@keyframes rainFall{0%{transform:translateY(-100vh)}100%{transform:translateY(100vh)}}
/* Modal de costos (igual al original) */
.costs-modal-overlay{position:fixed;top:0;left:0;width:100vw;height:100vh;background:rgba(0,0,0,0.8);z-index:3000;display:none;justify-content:center;align-items:center;padding:10px}
.costs-modal-overlay.show{display:flex}
.costs-modal{background:#1a2733;border-radius:16px;border:1px solid #2a3a4a;max-width:600px;width:100%;max-height:90vh;overflow-y:auto;padding:20px}
.costs-modal h2{font-size:20px;color:#00d4aa;margin-bottom:15px;text-align:center}
.costs-modal .close-btn{background:transparent;border:none;color:#fff;font-size:24px;cursor:pointer;float:right}
.costs-modal .card{background:#0f1923;border-radius:12px;padding:15px;margin-bottom:12px;border:1px solid #2a3a4a}
.costs-modal .card-title{font-size:14px;font-weight:700;margin-bottom:10px;color:#00d4aa}
.costs-modal .form-row{display:flex;gap:10px;margin-bottom:8px;flex-wrap:wrap}
.costs-modal .form-group{flex:1;min-width:100px}
.costs-modal label{display:block;font-size:10px;color:#8899aa;margin-bottom:3px;font-weight:600;text-transform:uppercase}
.costs-modal input,.costs-modal select{width:100%;padding:8px 10px;background:#0a0f14;border:1px solid #2a3a4a;border-radius:8px;color:white;font-size:13px}
.costs-modal .odometer-container{background:#000;border-radius:12px;padding:15px;text-align:center;border:2px solid #00d4aa;margin-bottom:12px}
.costs-modal .odometer{font-size:40px;font-weight:900;font-family:'Courier New',monospace;color:#00d4aa}
.costs-modal .result-card{background:linear-gradient(135deg,#1a2733,#0f1923);border:2px solid #00d4aa;border-radius:16px;padding:20px;text-align:center;margin-top:15px}
.costs-modal .result-amount{font-size:42px;font-weight:900;color:#00d4aa}
.costs-modal .breakdown-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:12px}
.costs-modal .breakdown-item{background:rgba(255,255,255,0.03);padding:8px;border-radius:8px;font-size:11px;text-align:center}
.costs-modal .breakdown-item .amount{font-size:16px;font-weight:700;display:block}
.costs-modal .savings-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:12px}
.costs-modal .savings-item{background:#0f1923;padding:10px;border-radius:8px;text-align:center;border:1px solid #2a3a4a}
.costs-modal .savings-item .amount{font-size:18px;font-weight:700;color:#00d4aa}
.costs-modal .add-btn{background:rgba(0,212,170,0.2);color:#00d4aa;border:1px dashed #00d4aa;padding:8px 16px;border-radius:8px;cursor:pointer;font-size:13px;width:100%;margin-top:5px}
.costs-modal .delete-btn{background:#ff4757;color:white;border:none;width:28px;height:28px;border-radius:6px;cursor:pointer}
.costs-modal .depreciation-info{background:rgba(255,165,2,0.1);border:1px solid #ffa502;border-radius:8px;padding:10px;margin-top:8px;font-size:11px;display:flex;justify-content:space-around}
.costs-modal .depreciation-info .value{font-size:16px;font-weight:700;color:#ffa502}
    
    #dailyDepreciation {
        font-size:32px;
        font-weight:900;
        color:#ffa502;
        text-shadow:0 0 8px rgba(255,165,2,0.3);
    }
</style>
</head>
<body>

<!-- Pantalla de carga -->
<div class="loading-screen" id="loadingScreen">
    <div class="loading-spinner"></div>
    <div class="loading-text">Cargando mapa + GPS Symbiosis...</div>
</div>

<!-- Overlay de lluvia -->
<div id="rainOverlay" class="rain-overlay"><div class="rain-bg"></div></div>

<div id="map"></div>

<div class="info compact" id="infoPanel">
    <div class="panel-header" onclick="togglePanel()">
        <span class="toggle-icon">▼</span>
        <span class="panel-title">SINGULARIDAD OMEGA + GPS</span>
        <span class="panel-clock" id="clock">--:--:--</span>
    </div>
    <div id="taximetro">$0.00</div>
    <div id="gpsSymbiosisIndicator" class="gps-symbiosis-indicator"></div>
    <div class="sub-data">
        <span>🚏<span class="val" id="kilometers">0.00</span>km</span>
        <span>⏱<span class="val" id="waitingTime">0</span>min</span>
        <span>🚀<span class="val" id="speed">0.0</span>km/h</span>
    </div>
    <div id="waitIndicator" class="wait-indicator"></div>
    <div class="btn-grid">
        <button class="btn btn-mo" id="mejorOpcionBtn">🎯 MEJOR OPCIÓN</button>
        <button class="btn btn-rain" id="rainBtn">🌂 Lluvia OFF</button>
        <button class="btn btn-gps" id="gpsStatusBtn">📡 GPS Status</button>
        <button class="btn btn-reset" id="resetBtn">🔄 Reset</button>
    </div>
    <div class="details-section" id="detailsSection">
        <div class="detail-row"><span class="dl">📍 GPS</span><span class="dv" id="gpsCoords">Esperando...</span></div>
        <div class="detail-row"><span class="dl">📈 Multiplicador</span><span class="dv" id="multiplierValue">1.00x</span></div>
        <div class="detail-row"><span class="dl">📡 Red</span><span class="dv" id="netStatus"><span class="net-dot net-offline"></span>--</span></div>
        <div class="detail-row"><span class="dl">🏆 Servidor</span><span class="dv" id="winner">-</span></div>
        <div class="detail-row"><span class="dl">⏱ Latencia</span><span class="dv" id="latency">-</span></div>
        <div class="detail-row"><span class="dl">🧠 Singularidad</span><span class="dv" id="singularityStatus">Cargando...</span></div>
        <div class="detail-row"><span class="dl">🎨 Zona</span><span class="dv" id="zonaInfo">--</span></div>
        <div class="detail-row"><span class="dl">🤖 RL Decisión</span><span class="dv" id="rlDecision">--</span></div>
        <div class="detail-row"><span class="dl">📊 Demanda</span><span class="dv" id="demandPred">--</span></div>
        <div class="detail-row" style="justify-content:center; padding-top:6px;">
            <button onclick="toggleCostsModal()" style="background:rgba(0,212,170,0.2); color:#00d4aa; border:1px dashed #00d4aa; padding:4px 12px; border-radius:12px; font-size:10px; cursor:pointer;">💰 Costos</button>
        </div>
    </div>
    <div id="proIndicator" class="pro-indicator"><span class="pro-badge">🔥 MODO PRO ACTIVADO 🔥</span></div>
</div>

<div class="log-panel" id="logPanel">
    <div style="font-weight:700;margin-bottom:4px;color:#4d94ff">📋 Eventos</div>
    <div id="logContent"></div>
</div>
<div class="toast" id="toast"></div>

<!-- MODAL DE COSTOS (mantenido del original) -->
<div class="costs-modal-overlay" id="costsModalOverlay">
    <div class="costs-modal" id="costsModal">
        <button class="close-btn" id="closeCostsBtn">✕</button>
        <h2>Calculadora de Costos Diarios</h2>
        <div class="odometer-container">
            <div style="font-size:11px;color:#8899aa;text-transform:uppercase;">Kilometraje Hoy</div>
            <div class="odometer" id="costOdometer">0.00</div>
        </div>
        <div class="card">
            <div class="card-title">Datos del Vehículo</div>
            <div class="form-row">
                <div class="form-group"><label>Cilindrada</label><select id="engineSize"><option value="1.0">1.0-1.3L</option><option value="1.4">1.4-1.6L</option><option value="1.8" selected>1.8-2.0L</option><option value="2.5">2.5L+</option></select></div>
                <div class="form-group"><label>Rendimiento</label><input type="text" id="mileageRange" readonly></div>
            </div>
            <div class="form-row">
                <div class="form-group"><label>Precio Combustible</label><input type="number" id="fuelPrice" value="1.05" step="0.01"></div>
                <div class="form-group"><label>Unidad</label><select id="fuelUnit"><option value="litro">Litros</option><option value="galon">Galones</option></select></div>
            </div>
        </div>
        <div class="card">
            <div class="card-title">💰 Ahorro para Próximo Vehículo</div>
            <p style="font-size:10px;color:#8899aa;margin-bottom:8px;text-align:center;">
                Aparta este monto <strong>cada día que trabajes</strong> para comprar tu siguiente carro al contado.
            </p>
            <div class="form-row">
                <div class="form-group">
                    <label>Valor Vehículo ($)</label>
                    <input type="number" id="carValue" value="15000">
                </div>
                <div class="form-group">
                    <label>Años de Financiamiento</label>
                    <input type="number" id="usefulLife" value="8" min="1" max="12">
                    <small style="color:#8899aa;font-size:9px;display:block;">Si es al contado: años que te das para ahorrar</small>
                </div>
            </div>
            <div style="text-align:center;padding:12px;background:rgba(255,165,2,0.08);border-radius:10px;border:1px solid rgba(255,165,2,0.3);">
                <div style="font-size:10px;color:#8899aa;text-transform:uppercase;letter-spacing:1px;">Ahorro Diario</div>
                <div style="font-size:32px;font-weight:900;color:#ffa502;" id="dailyDepreciation">$0.00</div>
                <div style="font-size:9px;color:#8899aa;margin-top:4px;">por cada día trabajado</div>
            </div>
            <div id="totalSavingsGoal" style="text-align:center;font-size:10px;color:#00d4aa;margin-top:8px;">
                Meta: $15,000.00 en 8 años
            </div>
        </div>
        <div class="card">
            <div class="card-title">Gastos Fijos</div>
            <div class="form-row">
                <div class="form-group"><label>Letra/Préstamo</label><input type="number" id="carPayment" value="0"></div>
                <div class="form-group"><label>Periodo</label><select id="carPaymentPeriod"><option value="monthly">Mensual</option><option value="weekly">Semanal</option><option value="daily">Diario</option><option value="none">No aplica</option></select></div>
            </div>
            <div class="form-row">
                <div class="form-group"><label>Seguro</label><input type="number" id="insurance" value="0"></div>
                <div class="form-group"><label>Periodo</label><select id="insurancePeriod"><option value="monthly">Mensual</option><option value="yearly">Anual</option><option value="none">No aplica</option></select></div>
            </div>
            <div class="form-row">
                <div class="form-group"><label>Mantenimiento</label><input type="number" id="maintenance" value="0"></div>
                <div class="form-group"><label>Periodo</label><select id="maintenancePeriod"><option value="monthly">Mensual</option><option value="weekly">Semanal</option><option value="none">No aplica</option></select></div>
            </div>
        </div>
        <div class="card">
            <div class="card-title">Meta Diario</div>
            <div class="form-row">
                <div class="form-group"><label>Ganancia deseada/día</label><input type="number" id="dailyProfit" value="50"></div>
            </div>
        </div>
        <div class="result-card">
            <div style="font-size:12px;color:#8899aa;">DEBE GENERAR MÍNIMO POR DÍA</div>
            <div class="result-amount" id="totalDaily">$0.00</div>
            <div class="breakdown-grid">
                <div class="breakdown-item"><span class="amount" id="breakFuel">$0.00</span>Combustible</div>
                <div class="breakdown-item"><span class="amount" id="breakFixed">$0.00</span>Fijos+Ahorro Veh.</div>
                <div class="breakdown-item"><span class="amount" id="breakProfit">$0.00</span>Ganancia</div>
                <div class="breakdown-item"><span class="amount" id="costPerKm">$0.00</span>Costo/km</div>
            </div>
            <div class="savings-grid">
                <div class="savings-item"><div class="amount" id="saveDaily">$0.00</div>Diario</div>
                <div class="savings-item"><div class="amount" id="saveWeekly">$0.00</div>Semanal</div>
                <div class="savings-item"><div class="amount" id="saveMonthly">$0.00</div>Mensual</div>
            </div>
        </div>
        <button onclick="costsCalculateAll()" style="width:100%;padding:12px;background:#00d4aa;color:#000;border:none;border-radius:10px;font-weight:700;margin-top:10px;cursor:pointer;">Recalcular</button>
    </div>
</div>

<script>
// ============ CONFIGURACIÓN ============
var SERVER_BASE = location.origin || ('http://' + location.hostname + ':8080');
var TAXI_CONFIG = {
    FARE_PER_KM: 0.25,
    FARE_PER_MIN_WAIT: 0.02,
    MIN_SPEED_WAITING: 2,
    AUTO_START_THRESHOLD: 8,
    WAIT_GRACE_PERIOD: 120,
    PEAK_MULTIPLIERS: [{start:6,end:9,factor:1.5},{start:11,end:14,factor:1.4},{start:18,end:21,factor:1.6}],
    RAIN_MULTIPLIER: 1.3
};
var rainActive = false, tripActive = false, lastPos = null, totalFare = 0, totalDistance = 0, totalWaiting = 0;
var stationaryStartTime = null, waitingActive = false, lastUpdateTime = null, currentSpeedKmh = 0;
var map = null, userMarker = null, gpsCircle = null;
var mapInitialized = false, mapLoadAttempts = 0;
var panelExpanded = false;
var gpsSymbiosisOnline = false;

// ============ FUNCIONES AUXILIARES ============
function sTF(v,d){d=d||2;var n=parseFloat(v);return(typeof n==='number'&&isFinite(n))?n.toFixed(d):'0.00';}
function showToast(m,d){var t=document.getElementById('toast');t.textContent=m;t.classList.add('show');clearTimeout(t._timer);t._timer=setTimeout(function(){t.classList.remove('show')},d||2500);}
function addLog(m,type){type=type||'info';var c=document.getElementById('logContent');if(!c)return;var d=document.createElement('div');d.className='log-entry log-'+type;d.innerHTML='<span class="log-time">['+new Date().toLocaleTimeString()+']</span> '+m;c.appendChild(d);c.scrollTop=c.scrollHeight;while(c.children.length>80)c.removeChild(c.firstChild);}
function togglePanel(){panelExpanded=!panelExpanded;var p=document.getElementById('infoPanel');p.classList.toggle('expanded',panelExpanded);p.classList.toggle('compact',!panelExpanded);}

// ============ SONIDOS ============
function playBeep(){try{var a=new(window.AudioContext||window.webkitAudioContext)();var o=a.createOscillator();var g=a.createGain();o.connect(g);g.connect(a.destination);o.type='sine';o.frequency.value=1200;g.gain.value=0.4;o.start();o.stop(a.currentTime+0.18);if(a.state==='suspended')a.resume();}catch(e){}}
function playRoarWithVoice(){try{var a=new(window.AudioContext||window.webkitAudioContext)();var o1=a.createOscillator();var g1=a.createGain();o1.connect(g1);g1.connect(a.destination);o1.type='sawtooth';o1.frequency.value=55;g1.gain.value=0.35;o1.start();g1.gain.exponentialRampToValueAtTime(0.001,a.currentTime+1.4);o1.stop(a.currentTime+1.4);var o2=a.createOscillator();var g2=a.createGain();o2.connect(g2);g2.connect(a.destination);o2.type='square';o2.frequency.value=75;g2.gain.value=0.15;o2.start();g2.gain.exponentialRampToValueAtTime(0.001,a.currentTime+1.1);o2.stop(a.currentTime+1.1);if(a.state==='suspended')a.resume();}catch(e){}if('speechSynthesis' in window){speechSynthesis.cancel();var u=new SpeechSynthesisUtterance('Protocolo de Mejor Opción Activado. Limpiando el algoritmo.');u.lang='es-ES';u.rate=0.9;u.pitch=1.0;speechSynthesis.speak(u);}}

// ============ ACTIVAR MEJOR OPCIÓN ============
function activarMejorOpcion(){
    var btn = document.getElementById('mejorOpcionBtn');
    btn.disabled = true;
    playBeep();
    addLog('BEEP - Iniciando secuencia...','info');
    setTimeout(function(){
        playRoarWithVoice();
        addLog('RUGIDO + VOZ: Protocolo activado.','info');
        btn.textContent = 'Activando...';
        fetch(SERVER_BASE+'/uber/activar_mejor_opcion',{
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({imprimir_prompt:true})
        }).then(function(res){return res.json();}).then(function(data){
            if(data.message){
                addLog('OK '+data.message,'pro');
                document.getElementById('proIndicator').classList.add('active');
                showToast('MODO PRO ACTIVADO');
                if(data.estado) addLog('Estado: '+data.estado,'info');
            }
        }).catch(function(err){
            addLog('Error: '+err.message,'error');
        }).finally(function(){
            btn.disabled=false;
            btn.innerHTML='🎯 MEJOR OPCIÓN';
        });
    },2000);
}

// ============ LLUVIA ============
function toggleRainMode(){
    rainActive = !rainActive;
    var btn = document.getElementById('rainBtn');
    var tm = document.getElementById('taximetro');
    var overlay = document.getElementById('rainOverlay');
    if(rainActive){
        btn.innerHTML='🌂 Lluvia ON';
        btn.classList.add('active');
        overlay.classList.add('active');
        crearGotasLluvia();
        tm.classList.add('rain-mode');
        showToast('Modo lluvia: +30% tarifa');
        addLog('Modo lluvia ACTIVADO (+30%)','info');
    } else {
        btn.innerHTML='🌂 Lluvia OFF';
        btn.classList.remove('active');
        overlay.classList.remove('active');
        overlay.innerHTML='<div class="rain-bg"></div>';
        tm.classList.remove('rain-mode');
        showToast('Modo lluvia desactivado');
        addLog('Modo lluvia DESACTIVADO','info');
    }
    recalcFare();
    updateMultiplierUI();
    sendMapaData();
}

function crearGotasLluvia(){
    var overlay = document.getElementById('rainOverlay');
    var count = Math.min(35, Math.floor(window.innerWidth/20));
    for(var i=0; i<count; i++){
        var streak = document.createElement('div');
        streak.className = 'rain-streak';
        var left = Math.random()*100;
        var height = 15+Math.random()*25;
        var duration = 0.4+Math.random()*0.5;
        var delay = Math.random()*2;
        streak.style.cssText = 'left:'+left+'%;height:'+height+'px;animation-duration:'+duration+'s;animation-delay:'+delay+'s;opacity:'+(0.2+Math.random()*0.3);
        overlay.appendChild(streak);
    }
}

// ============ MAPA ============
function initMap(){
    var loadingScreen = document.getElementById('loadingScreen');
    if(typeof L === 'undefined'){
        mapLoadAttempts++;
        addLog('Leaflet no cargado (intento '+mapLoadAttempts+')','warn');
        if(mapLoadAttempts < 10) setTimeout(initMap,1000);
        else { if(loadingScreen) loadingScreen.style.display='none'; addLog('ERROR: Leaflet sin carga','error'); }
        return;
    }
    try {
        var mapContainer = document.getElementById('map');
        if(!mapContainer){ addLog('Contenedor mapa no encontrado','error'); return; }
        map = L.map('map',{zoomControl:true, attributionControl:false, preferCanvas:true}).setView([8.9824,-79.5344],14);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19}).addTo(map);
        userMarker = L.marker([8.9824,-79.5344],{
            icon: L.divIcon({
                className:'',
                html:'<div style="width:24px;height:24px;background:#4d94ff;border-radius:50%;border:3px solid #fff;box-shadow:0 0 12px rgba(77,148,255,0.9);"></div>',
                iconSize:[24,24], iconAnchor:[12,12]
            }), zIndexOffset:1000
        }).addTo(map);
        gpsCircle = L.circle([8.9824,-79.5344],{color:'#4d94ff',fillColor:'#4d94ff',fillOpacity:0.15,radius:100}).addTo(map);
        mapInitialized = true;
        if(loadingScreen) loadingScreen.style.display='none';
        addLog('Mapa inicializado OK');
        setTimeout(function(){if(map)map.invalidateSize(true);},500);
    } catch(e) {
        if(loadingScreen) loadingScreen.style.display='none';
        addLog('Error mapa: '+e.message,'error');
    }
}

function getDistance(lat1,lon1,lat2,lon2){
    var R=6371e3;
    var dLat=(lat2-lat1)*Math.PI/180;
    var dLon=(lon2-lon1)*Math.PI/180;
    var a=Math.sin(dLat/2)*Math.sin(dLat/2)+Math.cos(lat1*Math.PI/180)*Math.cos(lat2*Math.PI/180)*Math.sin(dLon/2)*Math.sin(dLon/2);
    return R*2*Math.atan2(Math.sqrt(a),Math.sqrt(1-a));
}

function updatePosition(pos){
    if(!mapInitialized||!map) return;
    var lat=pos.coords.latitude, lon=pos.coords.longitude;
    var sp=pos.coords.speed!=null&&pos.coords.speed>=0?pos.coords.speed*3.6:0;
    var acc = pos.coords.accuracy || 10;
    currentSpeedKmh=sp; var now=Date.now();
    
    document.getElementById('gpsCoords').textContent=lat.toFixed(5)+', '+lon.toFixed(5);
    if(userMarker){var ll=L.latLng(lat,lon);userMarker.setLatLng(ll);map.setView(ll,map.getZoom(),{animate:true,duration:0.5});}
    if(gpsCircle) gpsCircle.setLatLng([lat,lon]);
    
    if(!tripActive&&sp>=TAXI_CONFIG.AUTO_START_THRESHOLD){
        tripActive=true;
        lastUpdateTime=now;
        lastPos={lat:lat,lng:lon,accuracy:acc};
        addLog('Viaje iniciado','info');
        showToast('Viaje iniciado');
    }
    
    if(tripActive&&lastUpdateTime&&lastPos){
        var dt=(now-lastUpdateTime)/1000;
        var dm=getDistance(lastPos.lat,lastPos.lng,lat,lon);
        
        // ============ CORRECCIÓN DE DISTANCIA ============
        // 1. Velocidad máxima realista: sp (km/h) convertido a m/s
        var velocidadMs = sp / 3.6;
        
        // 2. Distancia máxima esperada = velocidad * tiempo + margen de error del GPS
        var distanciaEsperada = velocidadMs * dt;
        var distanciaMaxima = Math.max(distanciaEsperada + acc, 5); // Mínimo 5m para filtrar ruido
        
        // 3. Solo acumular si:
        //    - Buena precisión (acc < 30m)
        //    - Distancia > 1m (filtrar micro-movimientos)
        //    - Distancia < distanciaMaxima (filtrar saltos GPS)
        if(acc < 30 && dm > 1 && dm < distanciaMaxima){
            totalDistance += dm / 1000;
        }
        // ================================================
        
        if(sp<TAXI_CONFIG.MIN_SPEED_WAITING){
            if(!stationaryStartTime) stationaryStartTime=now;
            if((now-stationaryStartTime)/1000>=TAXI_CONFIG.WAIT_GRACE_PERIOD){
                waitingActive=true;
                totalWaiting+=Math.min(dt,5)/60;
            }
        }else{
            stationaryStartTime=null;
            waitingActive=false;
        }
        recalcFare();
    }
    
    lastUpdateTime=now;
    lastPos={lat:lat,lng:lon,accuracy:acc};
    updateTaximeterUI();
    costsCalculateAll();
    sendMapaData();
}

function gpsError(err){
    document.getElementById('gpsCoords').textContent='Error: '+err.message;
    addLog('GPS error: '+err.message,'error');
}

function resetTrip(){
    tripActive=false;totalFare=0;totalDistance=0;totalWaiting=0;
    stationaryStartTime=null;waitingActive=false;currentSpeedKmh=0;lastPos=null;lastUpdateTime=null;
    updateTaximeterUI();showToast('Reset: $0.00');addLog('Taxímetro reiniciado','info');
    sendMapaData();
}

function getPeakMultiplier(){var h=new Date().getHours()+new Date().getMinutes()/60;for(var i=0;i<TAXI_CONFIG.PEAK_MULTIPLIERS.length;i++){var p=TAXI_CONFIG.PEAK_MULTIPLIERS[i];if(h>=p.start&&h<p.end)return p.factor;}return 1;}
function getTotalMultiplier(){var m=getPeakMultiplier();if(rainActive)m*=TAXI_CONFIG.RAIN_MULTIPLIER;return m;}
function recalcFare(){var m=getTotalMultiplier();totalFare=Math.max((totalDistance*TAXI_CONFIG.FARE_PER_KM+totalWaiting*TAXI_CONFIG.FARE_PER_MIN_WAIT)*m,0);}
function updateMultiplierUI(){var el=document.getElementById('multiplierValue');if(el){var m=getTotalMultiplier();el.textContent=sTF(m)+'x';el.style.color=rainActive?'#4db8ff':m>1.0?'#ffaa33':'#88a';}}
function updateTaximeterUI(){
    document.getElementById('taximetro').textContent='$'+sTF(totalFare);
    document.getElementById('taximetro').classList.toggle('active',tripActive);
    document.getElementById('kilometers').textContent=sTF(totalDistance);
    document.getElementById('waitingTime').textContent=Math.round(totalWaiting);
    document.getElementById('speed').textContent=sTF(currentSpeedKmh,1);
    document.getElementById('costOdometer').textContent=sTF(totalDistance);
    var wi=document.getElementById('waitIndicator');
    var now=Date.now();
    if(stationaryStartTime&&!waitingActive){
        var elapsed=Math.floor((now-stationaryStartTime)/1000);
        var remaining=Math.max(0,TAXI_CONFIG.WAIT_GRACE_PERIOD-elapsed);
        wi.textContent='Espera en '+Math.ceil(remaining)+'s';
        wi.classList.add('active');wi.style.display='block';
    }else if(waitingActive){
        wi.textContent='Cobrando espera';
        wi.classList.add('active');wi.style.display='block';
    }else{
        wi.classList.remove('active');wi.style.display='none';
    }
}

// ============ INDICADORES DE RED, SINGULARIDAD Y GPS SYMBIOSIS ============
function refreshNetwork(){
    fetch(SERVER_BASE+'/api/v1/network')
    .then(function(res){if(!res.ok)throw new Error('HTTP '+res.status);return res.json();})
    .then(function(d){
        var cls='net-offline', txt='Offline';
        if(d.status&&d.status.indexOf('EXCELENTE')!==-1){cls='net-excellent';txt='Excelente';}
        else if(d.status&&d.status.indexOf('ESTABLE')!==-1){cls='net-stable';txt='Estable';}
        else if(d.status&&d.status.indexOf('SATURADO')!==-1){cls='net-saturated';txt='Saturado';}
        else if(d.internet_ok){cls='net-stable';txt='Conectado';}
        document.getElementById('netStatus').innerHTML='<span class="net-dot '+cls+'"></span>'+txt;
        document.getElementById('winner').textContent=d.ganador||'-';
        document.getElementById('latency').textContent=d.latencia?sTF(parseFloat(d.latencia)*1000,0)+' ms':'-';
        if(d.gps_symbiosis_net){
            document.getElementById('netStatus').innerHTML += ' <span style="font-size:8px;color:#00ff6b;">GPS+</span>';
        }
    }).catch(function(){
        document.getElementById('netStatus').innerHTML='<span class="net-dot net-offline"></span>Error';
    });
}

function fetchSingularityStatus(){
    fetch(SERVER_BASE+'/ceoia/estado')
    .then(function(res){if(res.ok)return res.json();throw new Error('fail');})
    .then(function(d){
        var e=(d.estado_interno&&d.estado_interno.modo_operacion)||'Desconocido';
        var c=(d.estado_interno&&d.estado_interno.confianza_decisiones)||0;
        var el=document.getElementById('singularityStatus');
        el.textContent=e+' ('+Math.round(c*100)+'%)';
        el.style.color=(e.toUpperCase().indexOf('AUTONOMO')!==-1||c>0.7)?'#ffaa33':'#88a';
        
        // Mostrar datos de GPS Symbiosis si existen
        if(d.gps_symbiosis && d.gps_symbiosis.rl_step){
            el.textContent += ' | RL:'+d.gps_symbiosis.rl_step;
        }
    }).catch(function(){
        document.getElementById('singularityStatus').textContent='Offline';
    });
}

function fetchGPSSymbiosisStatus(){
    fetch(SERVER_BASE+'/api/gps/estado_completo')
    .then(function(res){if(res.ok)return res.json();throw new Error('fail');})
    .then(function(d){
        gpsSymbiosisOnline = true;
        var ind = document.getElementById('gpsSymbiosisIndicator');
        if(d.location && d.location.latitude){
            ind.textContent = 'GPS Symbiosis: ONLINE | RL Step: '+(d.rl?d.rl.step:0)+' | Geocercas: '+d.geofences_stats.total_fences;
            ind.className = 'gps-symbiosis-indicator active';
        }
        
        // Actualizar decisión RL
        if(d.rl && d.rl.weights){
            var rlEl = document.getElementById('rlDecision');
            var mejorAlgo = Object.entries(d.rl.weights).reduce(function(a,b){return a[1]>b[1]?a:b;});
            rlEl.textContent = mejorAlgo[0].toUpperCase()+' ('+(mejorAlgo[1]*100).toFixed(0)+'%)';
        }
        
        // Actualizar demanda si existe
        if(d.demand_predicted !== undefined){
            document.getElementById('demandPred').textContent = sTF(d.demand_predicted, 2)+'x';
        }
        
        // Actualizar zona
        if(d.geofences_stats && d.geofences_stats.fences){
            var zonasActivas = [];
            for(var fid in d.geofences_stats.fences){
                if(d.geofences_stats.fences[fid].currently_inside){
                    zonasActivas.push(fid.replace('z','Z').replace('_',' '));
                }
            }
            if(zonasActivas.length > 0){
                document.getElementById('zonaInfo').textContent = zonasActivas.join(', ');
            }
        }
    }).catch(function(){
        gpsSymbiosisOnline = false;
        var ind = document.getElementById('gpsSymbiosisIndicator');
        ind.textContent = 'GPS Symbiosis: OFFLINE';
        ind.className = 'gps-symbiosis-indicator warning';
    });
}

// ============ CALCULADORA DE COSTOS (OPTIMIZADA - RENDIMIENTO MÁXIMO) ============
var EngineConfig={
    '1.0':{range:'16-22 km/L',min:16,max:22},
    '1.4':{range:'11-16 km/L',min:11,max:16},
    '1.8':{range:'8-12 km/L',min:8,max:12},
    '2.5':{range:'5-9 km/L',min:5,max:9}
};
var GALON_TO_LITRO=3.78541;

function toggleCostsModal(){var o=document.getElementById('costsModalOverlay');o.classList.toggle('show');if(o.classList.contains('show'))costsCalculateAll();}
function updateMileage(){var es=document.getElementById('engineSize').value;var c=EngineConfig[es]||EngineConfig['1.8'];document.getElementById('mileageRange').value=c.range;costsCalculateAll();}
function convertToDaily(cantidad,periodo){if(!cantidad||periodo==='none')return 0;switch(periodo){case'daily':return cantidad;case'weekly':return cantidad/7;case'monthly':return cantidad/30;case'yearly':return cantidad/365;default:return 0;}}
function costsCalculateAll(){
    try{
        var es=document.getElementById('engineSize').value;
        var c=EngineConfig[es]||EngineConfig['1.8'];
        document.getElementById('mileageRange').value=c.range;
        var fu=document.getElementById('fuelUnit').value;
        var fp=parseFloat(document.getElementById('fuelPrice').value)||0;
        if(fu==='galon')fp=fp/GALON_TO_LITRO;
        var dk=totalDistance>0?totalDistance:0;
        // ✅ USA EL RENDIMIENTO MÁXIMO (el mejor escenario para el conductor)
        var sm=c.max>0?c.max:1;
        var fc=dk/sm*fp;
        
        // ============ AHORRO PARA PRÓXIMO VEHÍCULO ============
        // Fórmula: Valor del vehículo / (Años × 365 días)
        // El conductor ahorra este monto POR DÍA TRABAJADO
        var cv=parseFloat(document.getElementById('carValue').value)||0;
        var ul=parseInt(document.getElementById('usefulLife').value)||8;
        var dd=cv>0?cv/(ul*365):0;
        // ====================================================

        // Mostrar SOLO ahorro diario
        document.getElementById('dailyDepreciation').textContent='$'+dd.toFixed(2);

        // Meta total de referencia
        var metaTotal = dd * (ul * 365);
        var elMeta = document.getElementById('totalSavingsGoal');
        if(elMeta) elMeta.textContent = 'Meta: $' + metaTotal.toFixed(2) + ' en ' + ul + ' años';
        
        var fc2=0;
        fc2+=convertToDaily(parseFloat(document.getElementById('carPayment').value)||0,document.getElementById('carPaymentPeriod').value);
        fc2+=convertToDaily(parseFloat(document.getElementById('insurance').value)||0,document.getElementById('insurancePeriod').value);
        fc2+=convertToDaily(parseFloat(document.getElementById('maintenance').value)||0,document.getElementById('maintenancePeriod').value);
        var tf=fc2+dd;
        var dp=parseFloat(document.getElementById('dailyProfit').value)||0;
        var td=fc+tf+dp;
        document.getElementById('totalDaily').textContent='$'+td.toFixed(2);
        document.getElementById('breakFuel').textContent='$'+fc.toFixed(2);
        document.getElementById('breakFixed').textContent='$'+tf.toFixed(2);
        document.getElementById('breakProfit').textContent='$'+dp.toFixed(2);
        document.getElementById('saveDaily').textContent='$'+td.toFixed(2);
        document.getElementById('saveWeekly').textContent='$'+(td*7).toFixed(2);
        document.getElementById('saveMonthly').textContent='$'+(td*30).toFixed(2);
        var sdk=dk>0?dk:0.001;
        document.getElementById('costPerKm').textContent='$'+(td/sdk).toFixed(2)+'/km';
        sendMapaData();
    }catch(e){console.error(e);}
}

// ================================================================================
// FUNCION sendMapaData() - VERSION CORREGIDA PARA TERMUX + GPS SYMBIOSIS
// ================================================================================
function sendMapaData() {
    // OBTENER COORDENADAS REALES CON FALLBACK SEGURO
    var currentLat = (lastPos && typeof lastPos.lat === 'number') ? lastPos.lat : null;
    var currentLng = (lastPos && typeof lastPos.lng === 'number') ? lastPos.lng : null;
    
    // Validar que tengamos coordenadas válidas antes de enviar
    if (currentLat === null || currentLng === null) {
        // Intentar obtener de marcador del mapa si lastPos falla
        if (userMarker && userMarker.getLatLng) {
            var ll = userMarker.getLatLng();
            currentLat = ll.lat;
            currentLng = ll.lng;
        }
    }
    
    var data = {
        tarifa: totalFare,
        distancia_km: totalDistance,
        waiting_min: totalWaiting,
        speed_kmh: currentSpeedKmh,
        rain_active: rainActive,
        latitude: currentLat,
        longitude: currentLng,
        viaje_activo: tripActive,
        multiplicador: getTotalMultiplier(),
        total_daily: parseFloat(document.getElementById('totalDaily')?.textContent?.replace('$','')) || 0,
        fuel_cost_daily: parseFloat(document.getElementById('breakFuel')?.textContent?.replace('$','')) || 0,
        costo_fijo_diario: parseFloat(document.getElementById('breakFixed')?.textContent?.replace('$','')) || 0,
        costo_km: parseFloat(document.getElementById('costPerKm')?.textContent?.replace('$','').replace('/km','')) || 0,
        engine_size: document.getElementById('engineSize')?.value || '1.8',
        mileage: parseFloat(document.getElementById('mileageRange')?.value) || 10.0,
        daily_km: totalDistance,
        timestamp: Date.now()
    };
    
    // ENVIAR ORDEN A CEOIA VIA API (no referencia directa al objeto Python)
    if (currentLat !== null && currentLng !== null) {
        fetch(SERVER_BASE + '/ceoia/orden', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({orden: 'UBICACION:' + currentLat.toFixed(6) + ',' + currentLng.toFixed(6)})
        }).catch(function(e) {
            // Silencioso: CEOIA puede no estar disponible, no romper flujo principal
            console.log('[GPS] CEOIA no respondio (no critico)');
        });
    }
    
    // ENVIO PRINCIPAL AL BACKEND
    fetch(SERVER_BASE + '/api/mapa/update', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data)
    })
    .then(function(res) { return res.json(); })
    .then(function(responseData) {
        // PROCESAR RESPUESTA DE GPS SYMBIOSIS
        if (responseData && responseData.gps_symbiosis && responseData.gps_symbiosis.gps_procesado) {
            if (responseData.gps_symbiosis.zona_detectada) {
                var zonaEl = document.getElementById('zonaInfo');
                if (zonaEl) {
                    zonaEl.textContent = 'Z' + responseData.gps_symbiosis.zona_detectada.replace('z','');
                }
            }
            if (responseData.gps_symbiosis.rl_decision) {
                var rlEl = document.getElementById('rlDecision');
                if (rlEl) rlEl.textContent = responseData.gps_symbiosis.rl_decision;
            }
            if (typeof responseData.gps_symbiosis.demanda_predicha === 'number') {
                var demEl = document.getElementById('demandPred');
                if (demEl) demEl.textContent = sTF(responseData.gps_symbiosis.demanda_predicha, 2) + 'x';
            }
        }
    })
    .catch(function(err) { 
        console.error('[GPS] Error enviando datos:', err); 
        // Reintentar una vez con backoff mínimo
        setTimeout(function() {
            fetch(SERVER_BASE + '/api/mapa/update', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(data)
            }).catch(function() {}); // Segundo fallo: silencioso
        }, 2000);
    });
}

// ============ INICIALIZACIÓN ============
function init(){
    addLog('Iniciando Taxímetro Pro V6 + GPS Symbiosis','info');
    initMap();
    if(navigator.geolocation){
        navigator.geolocation.watchPosition(updatePosition,gpsError,{
            enableHighAccuracy:true, maximumAge:0, timeout:15000
        });
        addLog('GPS activo (coordenadas reales)','info');
    } else {
        document.getElementById('gpsCoords').textContent='Geolocation no soportado';
        addLog('Geolocation no soportado','error');
    }
    setInterval(function(){document.getElementById('clock').textContent=new Date().toLocaleTimeString();},1000);
    refreshNetwork(); 
    fetchSingularityStatus();
    fetchGPSSymbiosisStatus();
    setInterval(refreshNetwork,30000);
    setInterval(fetchSingularityStatus,30000);
    setInterval(fetchGPSSymbiosisStatus,15000);
    setInterval(function(){updateMultiplierUI();if(tripActive)recalcFare();},10000);
    updateMileage();
    costsCalculateAll();

    // Eventos
    document.getElementById('mejorOpcionBtn').onclick=activarMejorOpcion;
    document.getElementById('rainBtn').onclick=toggleRainMode;
    document.getElementById('gpsStatusBtn').onclick=fetchGPSSymbiosisStatus;
    document.getElementById('resetBtn').onclick=resetTrip;
    document.getElementById('engineSize').onchange=updateMileage;
    document.getElementById('closeCostsBtn').onclick=toggleCostsModal;

    ['fuelPrice','carValue','usefulLife','carPayment','insurance','maintenance','dailyProfit'].forEach(function(id){
        var el=document.getElementById(id);
        if(el)el.oninput=costsCalculateAll;
    });
    ['carPaymentPeriod','insurancePeriod','maintenancePeriod','fuelUnit'].forEach(function(id){
        var el=document.getElementById(id);
        if(el)el.onchange=costsCalculateAll;
    });

    // Enviar datos al backend cada 5 segundos
    setInterval(sendMapaData, 5000);
    sendMapaData();

    if('speechSynthesis' in window) speechSynthesis.getVoices();
    addLog('Sistema integrado listo (Frontend + GPS Symbiosis)','info');
}

if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',init);
else init();
</script>
</body>
</html>"""

# ================================================================================
# ENDPOINT DE MINING DEMO (mantenido)
# ================================================================================
@app.route('/mining_demo')
def mining_demo():
    return """<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>UBER DAIMON VIVO + SOCIALCOIN + GPS</title>
    <style>
        :root { --bg-primary: #0f0f23; --bg-secondary: #1a1a2e; --text-primary: #00ff41; --text-secondary: #4d94ff; --accent-green: #00cc44; --pro-gold: #ffd700; }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: 'Segoe UI', sans-serif; background: var(--bg-primary); color: var(--text-primary); min-height: 100vh; line-height: 1.5; }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        header { text-align: center; padding: 20px 0; border-bottom: 2px solid var(--text-primary); margin-bottom: 25px; }
        h1 { font-size: 2.5rem; text-shadow: 0 0 10px var(--text-primary); margin-bottom: 8px; }
        .dashboard { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin-bottom: 25px; }
        .panel { background: rgba(20,20,40,0.7); padding: 20px; border-radius: 12px; border: 1px solid var(--text-secondary); }
        .stats-bar { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin-bottom: 15px; }
        .stat-item { text-align: center; padding: 10px; background: rgba(0,20,40,0.5); border-radius: 8px; border: 1px solid var(--accent-green); }
        .stat-value { font-weight: bold; font-size: 1.4rem; display: block; } .stat-label { font-size: 0.85rem; color: var(--text-secondary); }
        .uber-status { display: flex; align-items: center; padding: 10px; background: rgba(0,30,20,0.5); border-radius: 8px; margin-bottom: 15px; }
        .uber-status-indicator { width: 14px; height: 14px; border-radius: 50%; margin-right: 12px; background-color: var(--text-secondary); }
        .input-group { margin: 15px 0; } .input-group label { display: block; margin-bottom: 6px; color: var(--text-secondary); }
        .input-group input { width: 100%; padding: 12px; background: rgba(10,20,40,0.8); border: 1px solid var(--text-primary); border-radius: 8px; color: var(--text-primary); }
        .btn { background: linear-gradient(135deg, var(--accent-green), #00ff55); color: #001a09; border: none; padding: 14px; font-size: 1rem; font-weight: bold; border-radius: 30px; cursor: pointer; width: 100%; margin: 8px 0; }
        .btn-uber { background: linear-gradient(135deg, #1a1a2e, var(--text-secondary)); color: white; border: 2px solid var(--text-secondary); }
        .btn-gps { background: linear-gradient(135deg, #1a5c3a, #1ee588); color: white; border: 2px solid #1ee588; }
        .pro-badge { display: inline-block; background: var(--pro-gold); color: black; font-weight: bold; padding: 2px 8px; border-radius: 20px; margin-left: 10px; font-size: 0.7rem; }
        .log-container { background: rgba(10,10,30,0.9); border: 2px solid var(--text-primary); height: 350px; overflow-y: auto; padding: 15px; border-radius: 10px; font-family: monospace; font-size: 0.9rem; grid-column: 1 / -1; }
        .log-entry { margin-bottom: 10px; padding: 8px; background: rgba(30,30,60,0.5); border-radius: 5px; border-left: 3px solid var(--text-secondary); }
        .log-entry .timestamp { color: var(--text-secondary); margin-right: 8px; } .log-entry .pro { color: var(--pro-gold); }
        .gps-status { background: rgba(0,40,20,0.5); padding: 10px; border-radius: 8px; margin: 10px 0; font-size: 0.85rem; }
    </style>
</head>
<body>
    <div class="container">
        <header><h1>UBER DAIMON VIVO + SOCIALCOIN + GPS</h1><p>Sistema Autónomo de IA + Mineria Social + GPS Symbiosis</p></header>
        <div class="dashboard">
            <div class="panel"><h3>Estadisticas</h3><div class="stats-bar"><div class="stat-item"><span class="stat-value" id="blockCount">0</span><span class="stat-label">Bloques</span></div><div class="stat-item"><span class="stat-value" id="rewardCount">0.00</span><span class="stat-label">UBER COINS</span></div></div><div class="uber-status"><div class="uber-status-indicator"></div><span>Conductor: <strong id="conductorEstado">IDLE</strong></span><span id="proBadgeHeader" style="display:none;" class="pro-badge">PRO</span></div><div class="gps-status" id="gpsStatus">GPS Symbiosis: Verificando...</div></div>
            <div class="panel"><h3>Configuracion</h3><div class="input-group"><label>Usuario:</label><input type="text" id="userInput" value="conductor_codigo"></div><div class="input-group"><label>URL:</label><input type="text" id="videoUrl" placeholder="https://..."></div><button class="btn" onclick="startMining()">Mineria Social</button><button class="btn btn-uber" id="mejorOpcionBtnDashboard" onclick="activarMejorOpcionDashboard()">MEJOR OPCION</button><button class="btn btn-gps" onclick="checkGPSStatus()">GPS STATUS</button></div>
            <div class="log-container" id="logContainer"><h3>Consola</h3></div>
        </div>
    </div>
    <script>
        function sTF(val,d){d=d||2;var n=parseFloat(val);return(typeof n==='number'&&isFinite(n))?n.toFixed(d):'0.'+'0'.repeat(d)}
        function playBeep(){try{var a=new(window.AudioContext||window.webkitAudioContext)();var o=a.createOscillator();var g=a.createGain();o.connect(g);g.connect(a.destination);o.type='sine';o.frequency.value=1200;g.gain.value=0.4;o.start();o.stop(a.currentTime+0.18)}catch(e){}}
        function playRoarWithVoice(){try{var a=new(window.AudioContext||window.webkitAudioContext)();var o=a.createOscillator();var g=a.createGain();o.connect(g);g.connect(a.destination);o.type='sawtooth';o.frequency.value=60;g.gain.value=0.35;o.start();g.gain.exponentialRampToValueAtTime(0.001,a.currentTime+1.4);o.stop(a.currentTime+1.4)}catch(e){}if('speechSynthesis' in window){speechSynthesis.cancel();var u=new SpeechSynthesisUtterance('Protocolo activado');u.lang='es-ES';u.rate=0.9;speechSynthesis.speak(u)}}
        function addLog(msg,type){type=type||'info';var c=document.getElementById('logContainer');if(!c)return;var d=document.createElement('div');d.className='log-entry';d.innerHTML='<span class="timestamp">['+new Date().toLocaleTimeString()+']</span> '+msg;c.appendChild(d);c.scrollTop=c.scrollHeight}
        function activarMejorOpcionDashboard(){var btn=document.getElementById('mejorOpcionBtnDashboard');btn.disabled=true;playBeep();addLog('BEEP...','info');setTimeout(function(){playRoarWithVoice();addLog('Protocolo activado.','info');btn.textContent='Activando...';fetch(location.origin+'/uber/activar_mejor_opcion',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({imprimir_prompt:true})}).then(function(res){return res.json()}).then(function(d){if(d.message){addLog('OK '+d.message,'pro');document.getElementById('proBadgeHeader').style.display='inline-block';document.getElementById('conductorEstado').textContent=d.estado||'MEJOR_OPCION'}}).catch(function(e){addLog('Error: '+e.message,'error')}).finally(function(){btn.disabled=false;btn.textContent='MEJOR OPCION'})},2000)}
        function startMining(){var url=document.getElementById('videoUrl').value;var user=document.getElementById('userInput').value;addLog('Iniciando mineria...','info');fetch(location.origin+'/api/v1/miner',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:url,user:user})}).then(function(res){return res.json()}).then(function(d){addLog('Bloqueo: +'+sTF(d&&d.reward)+' UBER MONEDAS','pro');document.getElementById('blockCount').innerText=(parseInt(document.getElementById('blockCount').innerText)||0)+1;document.getElementById('rewardCount').innerText=sTF(d&&d.reward)}).catch(function(e){addLog('Error: '+e.message,'error')})}
        function checkGPSStatus(){fetch(location.origin+'/api/gps/estado_completo').then(function(res){return res.json()}).then(function(d){var el=document.getElementById('gpsStatus');if(d.location&&d.location.latitude){el.innerHTML='GPS: ONLINE | Lat:'+d.location.latitude.toFixed(4)+' Lon:'+d.location.longitude.toFixed(4)+' | Vel:'+d.location.speed_kmh.toFixed(1)+' km/h | RL:'+(d.rl?d.rl.step:0);el.style.color='#00ff6b'}else{el.innerHTML='GPS: OFFLINE';el.style.color='#ff4466'}addLog('GPS Status: '+(d.location&&d.location.latitude?'ONLINE':'OFFLINE'),'info')}).catch(function(){document.getElementById('gpsStatus').innerHTML='GPS: ERROR';addLog('GPS Status: ERROR','error')})}
        function updateStats(){fetch(location.origin+'/health').then(function(res){return res.json()}).then(function(d){document.getElementById('blockCount').innerText=d.blocks_mined||0;document.getElementById('rewardCount').innerText=sTF(d.uber_coins);if(d.gps_symbiosis&&d.gps_symbiosis.location){var el=document.getElementById('gpsStatus');el.innerHTML='GPS: ONLINE | RL Step:'+(d.gps_symbiosis.rl_step||0);el.style.color='#00ff6b'}}).catch(function(){})}
        setInterval(updateStats,3000);updateStats();checkGPSStatus();if('speechSynthesis' in window)speechSynthesis.getVoices();
    </script>
</body>
</html>"""

# ================================================================================
# INTEGRACIONES FINALES
# ================================================================================
def integrar_network_monitor_automatically():
    try:
        from part9_network_monitor import (network_state, ping_data, start_network_threads)
        existing_rules = {rule.rule for rule in app.url_map.iter_rules()}
        if '/api/v1/network' not in existing_rules:
            @app.route('/api/v1/network', methods=['GET'])
            def network_extended():
                base_data = {"status": "online", "timestamp": time.time(), 
                           "uber_coins": UBER_COINS.to_float_approx() if hasattr(UBER_COINS, 'to_float_approx') else 0.0}
                try:
                    base_data.update({"network_monitor": {
                        "status": network_state.get("status"), 
                        "winner": network_state.get("winner"), 
                        "latency": network_state.get("latency")
                    }})
                except Exception: pass
                return jsonify(base_data)
            log("Endpoint /api/v1/network extendido")
        start_network_threads()
        log("Hilos de Network Monitor iniciados")
    except ImportError as e:
        log("Parte 9 no disponible: {}".format(e))
    except Exception as e:
        log("Error en integracion de red: {}".format(e))

def integrar_parte7_radar():
    try:
        import importlib
        mod7 = importlib.import_module("part7_radar_negociacion")
        radar_activo = getattr(mod7, 'radar_activo', False)
        if '/api/v1/radar/status' not in {rule.rule for rule in app.url_map.iter_rules()}:
            @app.route('/api/v1/radar/status')
            def radar_status():
                return jsonify({"activo": radar_activo, "zona": ULTIMA_ZONA, 
                               "modo": ESTADO_CONDUCTOR, "timestamp": time.time()})
            log("Endpoint /api/v1/radar/status registrado")
        log("Parte 7 integrada correctamente")
        return True
    except ImportError:
        log("Parte 7 no disponible")
        return False
    except Exception as e:
        log("Error al integrar la Parte 7: {}".format(e))
        return False

__all__ = ['app', 'HTTP_PORT', 'log', 'get_recent_logs', 
           'minar_bloque_por_publicacion_controlado', 'obtener_estado_completo',
           'symbiosis', 'gps_registry']

def obtener_estado_completo() -> Dict:
    estado = {
        "modulo": "parte8_frontend_html_integrado",
        "version": "6.0+gps_symbiosis",
        "puerto": HTTP_PORT,
        "estado_conductor": ESTADO_CONDUCTOR,
        "zona_actual": ULTIMA_ZONA,
        "uber_coins": UBER_COINS.to_float_approx() if hasattr(UBER_COINS, 'to_float_approx') else 0.0,
        "bloques_minados": len(blockchain),
        "ceoia_disponible": ceoia is not None,
        "gps_symbiosis_disponible": symbiosis is not None,
        "timestamp": time.time()
    }
    
    if symbiosis:
        try:
            estado["gps_symbiosis_status"] = symbiosis.get_system_status()
        except:
            pass
    
    return estado

def iniciar_frontend_hilo():
    def _run():
        try:
            app.run(host="0.0.0.0", port=HTTP_PORT, debug=False, use_reloader=False, threaded=True)
        except OSError as e:
            if "Address already in use" in str(e):
                log("Puerto {} ya en uso".format(HTTP_PORT))
            else:
                log("Error al iniciar la interfaz: {}".format(e))
    hilo = threading.Thread(target=_run, daemon=True, name="FrontendFlask")
    hilo.start()
    log("Frontend iniciado en hilo (puerto {})".format(HTTP_PORT))
    return hilo

if __name__ == "__main__":
    print("=" * 70, flush=True)
    print("UBER DAIMON VIVO + SOCIALCOIN + GPS SYMBIOSIS", flush=True)
    print("=" * 70, flush=True)
    print("Puerto: {}".format(HTTP_PORT), flush=True)
    print("Mapa Pro: http://localhost:{}/mapa_pro".format(HTTP_PORT), flush=True)
    print("Mining Demo: http://localhost:{}/mining_demo".format(HTTP_PORT), flush=True)
    print("GPS Status: http://localhost:{}/api/gps/estado_completo".format(HTTP_PORT), flush=True)
    print("=" * 70, flush=True)
    Path(__file__).parent.joinpath('static').mkdir(exist_ok=True)
    integrar_parte7_radar()
    integrar_network_monitor_automatically()
    try:
        app.run(host="0.0.0.0", port=HTTP_PORT, debug=False, use_reloader=False, threaded=True)
    except OSError as e:
        if "Address already in use" in str(e):
            log("Puerto {} ya en uso".format(HTTP_PORT))
        else:
            raise
    except KeyboardInterrupt:
        log("Frontend detenido")
        if symbiosis:
            symbiosis.shutdown()
        sys.exit(0)
