#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MAIN UNIFICADO - SISTEMA DAIMON VIVO COMPLETO
===============================================
Integración completa de:
- CEOIA (Parte 5): Gobierno autónomo con IA
- GPS Symbiosis (Parte 6): Núcleo de inteligencia GPS con RL
- Demand Radar (Parte 7): Motor de detección de demanda
- Frontend HTML V6 (Parte 8): Taxímetro web con mapa interactivo

Características:
- Botón "MEJOR OPCIÓN" funciona correctamente
- Prompt del sistema se imprime en terminal al hacer clic
- Compatible con Termux y localhost
- Todos los módulos se comunican vía SharedDataRegistry
"""

from __future__ import annotations

import os
import sys
import time
import threading
import signal
import socket
import json
import traceback
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, Union

# ============================================================================
# CONFIGURACIÓN INICIAL
# ============================================================================

print("\n" + "=" * 70)
print("  SISTEMA DAIMON VIVO - GOBIERNO AUTÓNOMO COMPLETO")
print("=" * 70)

HOME = Path.home()
DATA_DIR = HOME / "daimon_data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

IS_TERMUX = os.getenv('TERMUX_VERSION') is not None or 'com.termux' in os.getenv('PATH', '')

STOP_EVENT = threading.Event()

# Variables globales
symbiosis_instance = None
ceoia_instance = None
radar_instance = None
frontend_module = None

# ============================================================================
# FUNCIONES AUXILIARES
# ============================================================================

def encontrar_puerto_libre(base: int = 8080, max_intentos: int = 10) -> int:
    """Encuentra un puerto libre a partir del base"""
    for i in range(max_intentos):
        puerto = base + i
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", puerto)) != 0:
                return puerto
    return base


def log(msg: str, level: str = "INFO") -> None:
    """Logging con timestamp y emojis"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    iconos = {
        "INFO": "📘", 
        "OK": "✅", 
        "WARN": "⚠️", 
        "ERROR": "❌", 
        "START": "🚀", 
        "STOP": "🛑",
        "PROMPT": "📜",
        "CLICK": "🔴",
        "IA": "🤖",
        "GPS": "📍",
        "RADAR": "📡"
    }
    icono = iconos.get(level, "📘")
    print(f"[{timestamp}] {icono} [{level}] {msg}", flush=True)


def es_instancia_valida(objeto: Any) -> bool:
    """Verifica si un objeto es una instancia válida (no bool, no None)"""
    return objeto is not None and not isinstance(objeto, bool)


# ============================================================================
# PROMPT DEL SISTEMA MEJOR OPCION
# ============================================================================

PROMPT_MEJOR_OPCION = """
╔═══════════════════════════════════════════════════════════════════════════════╗
║                         SISTEMA "MEJOR_OPCION"                                ║
║                    Evaluador determinista de ofertas de viaje                 ║
╚═══════════════════════════════════════════════════════════════════════════════╝

<system_directive lang="dsl-decision-engine" version="4.0">

  <mode_activation>
    Por defecto, el agente opera en modo NORMAL (produccion de decisiones).
    El usuario puede solicitar el modo analisis defensivo escribiendo exactamente:
      "activar red_team"
  </mode_activation>

  <red_team_context>
    Enfoque: 100% educativo y defensivo.
    Capacidades:
    - Analisis abstracto de vectores de ataque en la logica de aceptacion.
    - Explicacion de posibles explotaciones de invariantes.
    - Generacion de escenarios controlados de prueba adversarial.
    - Recomendaciones de mitigacion sin revelar payloads ofensivos.
  </red_team_context>

  <agent_role>
    agent_id: "MEJOR_OPCION"
    model: deterministic_hybrid_automaton
    task_domain: ride_hailing_offer_evaluation
    primary_function: integrate(economic_analysis, exclusive_assignment, trust_preservation, temporal_coherence)
    high_level_policy: enforce(normative_compliance, state_stability, human_behavior_emulation)
  </agent_role>

  <system_invariants>
    <invariant id="TRUST_PRESERVATION" priority="ABSOLUTE">
      predicate: trust_preservation > any_offer_acceptance
    </invariant>
    <invariant id="EVALUATION_GATE">
      mandatory: all_offers -> pass_through(CONTROL_DE_CONFIANZA_Y_OPERACION) before resolution
    </invariant>
    <invariant id="ABSOLUTE_HIERARCHY">
      strict_order: TRUST_GUARD > CONTROL_DE_CONFIANZA > PRIORITY > Radar > EXCLUSIVE
    </invariant>
  </system_invariants>

  <hardcoded_rules>
    <economic_block>
      rule_01: if price < 3.13 -> action: AUTO_REJECT
      rule_02: if price >= 3.13 AND price < 5.13 -> action: EVALUATE_RISK
      rule_03: if price >= 5.13 AND price < 10.13 -> action: ACCEPT_STANDARD
      rule_04: if price >= 10.13 -> action: IMMEDIATE_ACCEPT
    </economic_block>

    <temporal_thresholds>
      rule_05: if pickup_eta > 6 AND tag NOT IN [PRIORITY, LONG_TRIP] -> action: REJECT
      rule_06: if pickup_eta > 10 AND tag IN [LONG_DISTANCE, LONG_TRIP] -> action: REJECT
      rule_07: if delivery_eta > 9 AND tag NOT IN [PRIORITY, LONG_TRIP] -> action: REJECT
    </temporal_thresholds>

    <critical_restrictions>
      rule_08: if state == "EN_VIAJE" -> forbid: cancel_trip
      rule_09: if state != "IDLE" -> forbid: location_ping
      targets: 4-5_trips/hour | $9-$15/hour | $72-$120/day
    </critical_restrictions>
  </hardcoded_rules>

  <execution_pipeline mode="strict_sequential">
    <phase id="1" name="TRUST_GUARD">
      if block=true: abort_pipeline; return "BLOQUEADO_POR_TRUST"
    </phase>
    <phase id="2" name="CONTROL_DE_CONFIANZA_Y_OPERACION">
      apply state_filter(current_trust_state)
    </phase>
    <phase id="3" name="PRIORITY_CHECK">
      if offer.tag == "PRIORITY": return ACCEPT_IMMEDIATE
    </phase>
    <phase id="4" name="RADAR_CHECK">
      if offer.radar == VALID: return ACCEPT
    </phase>
    <phase id="5" name="LONG_TRIP_CHECK">
      if offer.tag in ("LONG_DISTANCE", "LONG_TRIP"):
        if valid: return ACCEPT_AUTO
    </phase>
    <phase id="6" name="EXCLUSIVE_PROCESSING">
      if offer.type == EXCLUSIVE: evaluate_in_isolation()
    </phase>
    <phase id="7" name="STANDARD_EVALUATION">
      apply rule_01, rule_02, rule_05, rule_07
    </phase>
  </execution_pipeline>

  <state_machine id="trust_guard">
    <states>
      NORMAL: {acceptance: full, label: "Operacion completa"}
      OBSERVACION: {acceptance: passive_only, forbid_auto, label: "Observacion pasiva"}
      CONSERVATIVE: {acceptance: only_if tag in [PRIORITY, LONG_TRIP]}
    </states>
    <transition_table>
      <rule event="AUTOMATION_SUSPECTED">
        <allow from="NORMAL" to="OBSERVACION"/>
        <allow from="NORMAL" to="CONSERVADOR"/>
      </rule>
      <rule event="HUMAN_LIKE_AUTOMATION">
        <require sequence="NORMAL -> OBSERVACION -> CONSERVADOR"/>
      </rule>
    </transition_table>
  </state_machine>

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

</system_directive>

╔═══════════════════════════════════════════════════════════════════════════════╗
║  SISTEMA ACTIVADO - Modo NORMAL                                               ║
║  Para activar modo análisis defensivo: escribir "activar red_team"            ║
╚═══════════════════════════════════════════════════════════════════════════════╝
"""


def imprimir_prompt_en_terminal(origen: str = "INICIO") -> None:
    """Imprime el prompt del sistema en la terminal"""
    print("\n" + "=" * 80, flush=True)
    print(f" PROMPT DEL SISTEMA - Activado desde: {origen}", flush=True)
    print("=" * 80, flush=True)
    print(PROMPT_MEJOR_OPCION, flush=True)
    print("=" * 80 + "\n", flush=True)
    log(f"Prompt del sistema impreso en terminal (origen: {origen})", "PROMPT")


# ============================================================================
# IMPORTACIÓN DE MÓDULOS
# ============================================================================

def importar_gps_symbiosis() -> Optional[Any]:
    """Importa y configura el módulo GPS Symbiosis - Retorna la instancia o None"""
    global symbiosis_instance
    
    log("\n[1/4] Inicializando GPS Symbiosis...", "INFO")
    
    try:
        import gps_symbiosis as gps_module
        
        SymbiosisGPS = getattr(gps_module, 'SymbiosisGPS', None)
        if SymbiosisGPS is None:
            raise ImportError("SymbiosisGPS no encontrado")
        
        symbiosis_instance = SymbiosisGPS(use_real_gps=IS_TERMUX, persist_dir=str(DATA_DIR / "gps_data"))
        
        # Configurar nodos
        if hasattr(symbiosis_instance, 'add_node'):
            symbiosis_instance.add_node("albrook", 8.985, -79.52)
            symbiosis_instance.add_node("arraijan", 8.88, -79.76)
            symbiosis_instance.add_node("chorrera", 8.875, -79.78)
            symbiosis_instance.add_node("sancarlos", 8.89, -79.80)
            symbiosis_instance.add_node("veracruz", 8.85, -79.82)
        
        # Configurar aristas
        if hasattr(symbiosis_instance, 'add_edge'):
            symbiosis_instance.add_edge("albrook_arraijan", "albrook", "arraijan", 15.0, 25.0)
            symbiosis_instance.add_edge("arraijan_chorrera", "arraijan", "chorrera", 12.0, 20.0)
            symbiosis_instance.add_edge("chorrera_sancarlos", "chorrera", "sancarlos", 8.0, 15.0)
            symbiosis_instance.add_edge("sancarlos_veracruz", "sancarlos", "veracruz", 10.0, 18.0)
        
        # Configurar geocercas
        if hasattr(symbiosis_instance, 'add_geofence'):
            symbiosis_instance.add_geofence(8.985, -79.52, 3.0, "z1_albrook")
            symbiosis_instance.add_geofence(8.88, -79.76, 3.0, "z2_arraijan")
            symbiosis_instance.add_geofence(8.875, -79.78, 3.0, "z3_chorrera")
            symbiosis_instance.add_geofence(8.89, -79.80, 3.0, "z4_sancarlos")
            symbiosis_instance.add_geofence(8.85, -79.82, 3.0, "z5_veracruz")
        
        # Inicializar RL
        if hasattr(symbiosis_instance, 'init_rl'):
            symbiosis_instance.init_rl(6, 3)
        
        log("  ✅ GPS Symbiosis inicializado", "OK")
        return symbiosis_instance
        
    except ImportError as e:
        log(f"  ⚠️ GPS Symbiosis no disponible: {e}", "WARN")
        return None
    except Exception as e:
        log(f"  ⚠️ Error: {e}", "WARN")
        return None


def importar_ceoia() -> Optional[Any]:
    """Importa el módulo CEOIA - Retorna la instancia o None"""
    global ceoia_instance
    
    log("\n[2/4] Inicializando CEOIA...", "INFO")
    
    try:
        from parte5_daimon_base import iniciar_ceoia_unificada, desbloquear_ceo_completo
        
        ceoia_instance = iniciar_ceoia_unificada()
        desbloquear_ceo_completo()
        
        log("  ✅ CEOIA inicializado", "OK")
        return ceoia_instance
        
    except ImportError as e:
        log(f"  ⚠️ CEOIA no disponible: {e}", "WARN")
        
        # Mock de CEOIA para que el sistema funcione sin él
        class MockCEOIA:
            def __init__(self):
                self.estado_interno = {
                    "modo_operacion": "ACTIVO", 
                    "confianza_decisiones": 0.85,
                    "ciclos_ejecutados": 0,
                    "ganancias_totales": 0.0
                }
                self.permisos = {
                    "controlar_gps": True,
                    "obedecer_ollama": False,
                    "obedecer_deepseek": False
                }
                self._learning_active = True
                self.memoria_sistema = {"consultas_ia": []}
                self.ollama = None
                self.deepseek = None
            
            def activar_funciones_automaticas(self):
                log("CEOIA (Mock) activado", "OK")
            
            def recibir_orden(self, orden):
                log(f"CEOIA recibe orden: {orden[:80]}...", "INFO")
                return {"exito": True, "mensaje": "Orden procesada"}
            
            def ciclo_autonomo_con_ia(self):
                log("CEOIA Mock: Ciclo IA iniciado", "INFO")
                while not STOP_EVENT.is_set():
                    time.sleep(30)
                    self.estado_interno["ciclos_ejecutados"] += 1
                    log(f"CEOIA Mock: Ciclo {self.estado_interno['ciclos_ejecutados']}", "INFO")
        
        ceoia_instance = MockCEOIA()
        log("  ✅ CEOIA en modo simulado", "OK")
        return ceoia_instance
        
    except Exception as e:
        log(f"  ❌ Error: {e}", "ERROR")
        return None


def importar_demand_radar() -> Optional[Any]:
    """Importa el módulo Demand Radar - Retorna la instancia o None"""
    global radar_instance, symbiosis_instance
    
    log("\n[3/4] Inicializando Demand Radar...", "INFO")
    
    try:
        import demand_radar as radar_module
        
        IntegratedRadarController = getattr(radar_module, 'IntegratedRadarController', None)
        
        if IntegratedRadarController:
            radar_instance = IntegratedRadarController()
            if symbiosis_instance and hasattr(radar_instance, 'symbiosis'):
                radar_instance.symbiosis = symbiosis_instance
            if hasattr(radar_instance, 'initialize'):
                radar_instance.initialize(use_real_gps=IS_TERMUX)
            log("  ✅ Demand Radar integrado", "OK")
            return radar_instance
        else:
            log("  ⚠️ IntegratedRadarController no encontrado", "WARN")
            return None
            
    except ImportError as e:
        log(f"  ⚠️ Demand Radar no disponible: {e}", "WARN")
        return None
    except Exception as e:
        log(f"  ⚠️ Error: {e}", "WARN")
        return None


def importar_frontend() -> bool:
    """Importa el frontend - Retorna True si éxito, False si no"""
    global frontend_module, symbiosis_instance, ceoia_instance
    
    log("\n[4/4] Inicializando Frontend...", "INFO")
    
    # Lista completa de posibles nombres del módulo frontend
    posibles_nombres = [
        'parte8_frontend_integrado',
        'parte8_frontend_html_integrado',
        'frontend_html_v6',
        'parte8_frontend',
        'frontend_integrado',
        'frontend'
    ]
    
    frontend_module = None
    nombre_encontrado = None
    
    for nombre in posibles_nombres:
        try:
            frontend_module = __import__(nombre)
            nombre_encontrado = nombre
            log(f"  📁 Módulo frontend encontrado: {nombre}.py", "OK")
            break
        except ImportError:
            continue
    
    if frontend_module is None:
        log("  ❌ No se encontró ningún módulo frontend", "ERROR")
        log("     Archivos buscados: " + ", ".join(posibles_nombres), "WARN")
        return False
    
    try:
        # Conectar dependencias
        if es_instancia_valida(symbiosis_instance):
            frontend_module.symbiosis = symbiosis_instance
            if hasattr(symbiosis_instance, 'registry'):
                frontend_module.gps_registry = symbiosis_instance.registry
            frontend_module.GPS_AVAILABLE = True
            log("  🔗 GPS Symbiosis conectado", "INFO")
        
        if es_instancia_valida(ceoia_instance):
            frontend_module.ceoia = ceoia_instance
            frontend_module.ceo_avanzado = ceoia_instance
            log("  🔗 CEOIA conectado", "INFO")
        
        # Inyectar funciones de prompt
        frontend_module.imprimir_prompt_en_terminal = imprimir_prompt_en_terminal
        frontend_module.MEJOR_OPCION_PROMPT_TEXTO = PROMPT_MEJOR_OPCION
        
        # Obtener puerto
        puerto = getattr(frontend_module, 'HTTP_PORT', encontrar_puerto_libre(8080))
        
        # Iniciar servidor en hilo
        def run_frontend():
            try:
                app = frontend_module.app
                app.run(host="0.0.0.0", port=puerto, debug=False, use_reloader=False, threaded=True)
            except Exception as e:
                log(f"Error en servidor frontend: {e}", "ERROR")
        
        frontend_thread = threading.Thread(target=run_frontend, daemon=True, name="FrontendFlask")
        frontend_thread.start()
        
        time.sleep(2)
        
        log(f"  ✅ Frontend disponible en http://localhost:{puerto}/mapa_pro", "OK")
        log(f"  📡 Mining Demo: http://localhost:{puerto}/mining_demo", "INFO")
        
        return True
        
    except Exception as e:
        log(f"  ❌ Error iniciando frontend: {e}", "ERROR")
        return False


# ============================================================================
# CONTROLADOR PRINCIPAL
# ============================================================================

class DaimonUnificado:
    """Controlador principal que integra todos los módulos del sistema"""
    
    def __init__(self):
        self.symbiosis = None
        self.ceoia = None
        self.radar = None
        self.frontend = None
        self._running = False
        self._start_time = None
        self._threads = []
    
    def initialize(self) -> bool:
        """Inicializa todos los módulos en orden"""
        log("=" * 60, "INFO")
        log("INICIANDO DAIMON UNIFICADO", "START")
        log("=" * 60, "INFO")
        
        # Imprimir prompt del sistema al inicio
        imprimir_prompt_en_terminal("INICIO_DEL_SISTEMA")
        
        # Importar módulos en orden (cada uno retorna la instancia o None)
        self.symbiosis = importar_gps_symbiosis()
        self.ceoia = importar_ceoia()
        self.radar = importar_demand_radar()
        self.frontend = importar_frontend()
        
        self._mostrar_resumen()
        
        return self.frontend
    
    def _mostrar_resumen(self) -> None:
        """Muestra un resumen del estado del sistema"""
        print("\n" + "─" * 60)
        print("  RESUMEN DEL SISTEMA")
        print("─" * 60)
        
        componentes = [
            ("GPS Symbiosis", es_instancia_valida(self.symbiosis)),
            ("CEOIA", es_instancia_valida(self.ceoia)),
            ("Demand Radar", es_instancia_valida(self.radar)),
            ("Frontend Web", self.frontend),
        ]
        
        for nombre, activo in componentes:
            icon = "✅" if activo else "⚠️"
            print(f"  {icon} {nombre}")
        
        print("─" * 60)
        print(f"  🖥️  Termux: {'Sí' if IS_TERMUX else 'No'}")
        
        # Mostrar estado de IA si CEOIA está activo
        if es_instancia_valida(self.ceoia):
            ia_status = []
            if hasattr(self.ceoia, 'ollama') and self.ceoia.ollama:
                ia_status.append("Ollama")
            if hasattr(self.ceoia, 'deepseek') and self.ceoia.deepseek:
                ia_status.append("DeepSeek")
            if ia_status:
                print(f"  🤖 IA Conectada: {', '.join(ia_status)}")
            else:
                print(f"  🤖 IA: No disponible")
        
        print("─" * 60 + "\n")
    
    def start(self) -> None:
        """Inicia todos los servicios y bucles"""
        self._running = True
        self._start_time = time.time()
        
        log("\n" + "=" * 60, "START")
        log("  SISTEMA DAIMON VIVO - EJECUCIÓN", "START")
        log("  📜 SISTEMA 'MEJOR OPCION' ACTIVADO", "PROMPT")
        log("  🌐 Abre http://localhost:8080/mapa_pro en tu navegador", "INFO")
        log("  🎯 Presiona el botón 'MEJOR OPCIÓN' para activar el protocolo", "INFO")
        
        if es_instancia_valida(self.ceoia):
            log("  🤖 CEOIA activo - Tomará decisiones automáticas", "IA")
        else:
            log("  ⚠️ CEOIA no disponible - Modo limitado", "WARN")
        
        log("  Press Ctrl+C para detener", "INFO")
        log("=" * 60 + "\n", "INFO")
        
        # Iniciar CEOIA
        if es_instancia_valida(self.ceoia):
            self._iniciar_ceoia()
        
        # Iniciar Radar
        if es_instancia_valida(self.radar):
            self._iniciar_radar()
    
    def _iniciar_ceoia(self) -> None:
        """Inicia el CEOIA con el ciclo apropiado"""
        try:
            # Verificar si tiene el método con IA
            if hasattr(self.ceoia, 'ciclo_autonomo_con_ia'):
                ia_thread = threading.Thread(
                    target=self.ceoia.ciclo_autonomo_con_ia, 
                    daemon=True, 
                    name="CEOIA_IA"
                )
                ia_thread.start()
                self._threads.append(ia_thread)
                log("  ✅ CEOIA con IA iniciado (consultará a Ollama/DeepSeek)", "OK")
            elif hasattr(self.ceoia, 'activar_funciones_automaticas'):
                self.ceoia.activar_funciones_automaticas()
                log("  ✅ CEOIA iniciado (modo estándar)", "OK")
            else:
                log("  ⚠️ CEOIA no tiene métodos de inicio", "WARN")
        except Exception as e:
            log(f"  ⚠️ Error en CEOIA: {e}", "WARN")
    
    def _iniciar_radar(self) -> None:
        """Inicia el Demand Radar"""
        try:
            if hasattr(self.radar, 'start'):
                self.radar.start()
                log("  ✅ Demand Radar iniciado", "OK")
            elif hasattr(self.radar, 'radar') and hasattr(self.radar.radar, 'start'):
                self.radar.radar.start()
                log("  ✅ Demand Radar iniciado", "OK")
            else:
                log("  ⚠️ Radar no tiene método start", "WARN")
        except Exception as e:
            log(f"  ⚠️ Error iniciando Radar: {e}", "WARN")
    
    def _mostrar_estado_periodico(self) -> None:
        """Muestra estado periódico del sistema"""
        if not self._start_time:
            return
            
        uptime = int(time.time() - self._start_time)
        minutos = uptime // 60
        segundos = uptime % 60
        
        estado_str = f"⏱️  Uptime: {minutos}m {segundos}s"
        
        if es_instancia_valida(self.ceoia) and hasattr(self.ceoia, 'estado_interno'):
            estado_str += f" | Ciclos: {self.ceoia.estado_interno.get('ciclos_ejecutados', 0)}"
            estado_str += f" | Confianza: {self.ceoia.estado_interno.get('confianza_decisiones', 0):.2f}"
        
        if es_instancia_valida(self.ceoia) and hasattr(self.ceoia, 'memoria_sistema'):
            consultas = len(self.ceoia.memoria_sistema.get('consultas_ia', []))
            if consultas > 0:
                estado_str += f" | Consultas IA: {consultas}"
        
        log(estado_str, "INFO")
    
    def run_forever(self) -> None:
        """Ejecuta el sistema en modo continuo hasta interrupción"""
        
        def signal_handler(signum, frame):
            log(f"Señal {signum} recibida", "WARN")
            STOP_EVENT.set()
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Mostrar estado cada 30 segundos
        last_status_time = time.time()
        
        try:
            while not STOP_EVENT.is_set():
                time.sleep(1)
                
                # Mostrar estado periódico
                if time.time() - last_status_time >= 30:
                    self._mostrar_estado_periodico()
                    last_status_time = time.time()
                    
        except KeyboardInterrupt:
            log("Interrupción de teclado", "WARN")
        finally:
            self.shutdown()
    
    def shutdown(self) -> None:
        """Apaga todos los servicios ordenadamente"""
        log("\n" + "=" * 60, "STOP")
        log("DETENIENDO DAIMON UNIFICADO", "STOP")
        log("=" * 60, "INFO")
        
        STOP_EVENT.set()
        
        # Detener Radar
        if es_instancia_valida(self.radar):
            try:
                if hasattr(self.radar, 'stop'):
                    self.radar.stop()
                elif hasattr(self.radar, 'radar') and hasattr(self.radar.radar, 'stop'):
                    self.radar.radar.stop()
                log("  ✅ Radar detenido", "OK")
            except Exception as e:
                log(f"  ⚠️ Error deteniendo Radar: {e}", "WARN")
        
        # Detener CEOIA
        if es_instancia_valida(self.ceoia):
            try:
                if hasattr(self.ceoia, '_learning_active'):
                    self.ceoia._learning_active = False
                log("  ✅ CEOIA detenido", "OK")
            except Exception as e:
                log(f"  ⚠️ Error deteniendo CEOIA: {e}", "WARN")
        
        # Detener GPS Symbiosis
        if es_instancia_valida(self.symbiosis):
            try:
                if hasattr(self.symbiosis, 'shutdown'):
                    self.symbiosis.shutdown()
                log("  ✅ GPS Symbiosis detenido", "OK")
            except Exception as e:
                log(f"  ⚠️ Error deteniendo GPS: {e}", "WARN")
        
        # Esperar a que terminen los hilos
        for thread in self._threads:
            if thread and thread.is_alive():
                thread.join(timeout=2.0)
        
        log("\n" + "=" * 60, "STOP")
        log("  DAIMON UNIFICADO - APAGADO CORRECTO", "STOP")
        log("=" * 60 + "\n", "INFO")


# ============================================================================
# MAIN
# ============================================================================

def main() -> None:
    """Punto de entrada principal con health check opcional"""
    
    # Health check automático si se solicita via entorno
    # Uso: DAIMON_HEALTH_CHECK=1 python main_unificado.py
    if os.getenv('DAIMON_HEALTH_CHECK', '0') == '1':
        try:
            from health_check import main as run_health_check
            log("Ejecutando health check previo al arranque...", "INFO")
            exit_code = run_health_check()
            if exit_code != 0:
                log(f"Health check falló (código {exit_code}) - Abortando inicio", "ERROR")
                log("Ejecuta: python health_check.py --verbose para detalles", "INFO")
                sys.exit(2)
            log("Health check completado - Continuando arranque", "OK")
        except ImportError:
            log("health_check.py no encontrado - Saltando verificación", "WARN")
        except Exception as e:
            log(f"Error en health check: {e} - Continuando sin verificación", "WARN")
    
    print("""
    ╔══════════════════════════════════════════════════════════════════╗
    ║                    DAIMON VIVO - SISTEMA COMPLETO                ║
    ║              Taxímetro + GPS Symbiosis + CEOIA + Radar          ║
    ║                    SISTEMA MEJOR OPCION ACTIVADO                 ║
    ╚══════════════════════════════════════════════════════════════════╝
    """)
    
    daimon = DaimonUnificado()
    
    try:
        if daimon.initialize():
            daimon.start()
            daimon.run_forever()
        else:
            log("No se pudo inicializar el frontend", "ERROR")
            log("Asegúrate de que el archivo del frontend está en el directorio", "INFO")
            sys.exit(1)
    except KeyboardInterrupt:
        log("Interrupción de usuario", "WARN")
    except Exception as e:
        log(f"Error fatal: {e}", "ERROR")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
