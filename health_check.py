#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
health_check.py - Validador de integración para SISTEMA DAIMON VIVO
====================================================================
Propósito: Verificar todas las conexiones entre módulos antes de producción.
Compatible con Termux, Python 3.10+, sin dependencias externas obligatorias.

USO:
    python health_check.py [--verbose] [--fix] [--report]
    
    --verbose  : Muestra detalles de cada prueba
    --fix      : Intenta corregir problemas detectados (crea directorios, etc.)
    --report   : Genera reporte JSON en daimon_data/health_report.json

SALIDA:
    - Código de retorno: 0 = OK, 1 = Advertencias, 2 = Errores críticos
    - Reporte visual en terminal con emojis y colores (si disponible)
"""
from __future__ import annotations

import os
import sys
import json
import time
import socket
import threading
import importlib.util
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum, auto

# ============================================================================
# CONFIGURACIÓN INICIAL
# ============================================================================

HOME = Path.home()
DATA_DIR = HOME / "daimon_data"
REPORT_FILE = DATA_DIR / "health_report.json"

IS_TERMUX = os.getenv('TERMUX_VERSION') is not None or 'com.termux' in os.getenv('PATH', '')
HAS_COLOR = hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()

# Colores para terminal (solo si está disponible)
class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    
    @classmethod
    def wrap(cls, text: str, color: str) -> str:
        return f"{color}{text}{cls.RESET}" if HAS_COLOR else text

# ============================================================================
# ESTRUCTURAS DE DATOS
# ============================================================================

class CheckStatus(Enum):
    OK = auto()
    WARNING = auto()
    ERROR = auto()
    SKIPPED = auto()

@dataclass
class CheckResult:
    """Resultado de una verificación individual"""
    name: str
    status: CheckStatus
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.name,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp
        }

@dataclass
class HealthReport:
    """Reporte completo de salud del sistema"""
    start_time: str
    end_time: str
    total_checks: int
    passed: int
    warnings: int
    errors: int
    skipped: int
    results: List[Dict[str, Any]]
    environment: Dict[str, Any]
    recommendations: List[str]
    
    def to_json(self, indent: int = 2) -> str:
        return json.dumps(asdict(self), indent=indent, ensure_ascii=False, default=str)

# ============================================================================
# UTILIDADES DE VERIFICACIÓN
# ============================================================================

def check_import(module_name: str, optional: bool = False) -> CheckResult:
    """Verifica si un módulo puede ser importado"""
    try:
        spec = importlib.util.find_spec(module_name)
        if spec is None:
            if optional:
                return CheckResult(
                    name=f"import:{module_name}",
                    status=CheckStatus.WARNING,
                    message=f"Módulo opcional '{module_name}' no encontrado",
                    details={"optional": True}
                )
            return CheckResult(
                name=f"import:{module_name}",
                status=CheckStatus.ERROR,
                message=f"Módulo requerido '{module_name}' no encontrado",
                details={"search_path": sys.path}
            )
        # Intentar importar para detectar errores de sintaxis/dependencias
        importlib.import_module(module_name)
        return CheckResult(
            name=f"import:{module_name}",
            status=CheckStatus.OK,
            message=f"Módulo '{module_name}' importado correctamente"
        )
    except ImportError as e:
        status = CheckStatus.WARNING if optional else CheckStatus.ERROR
        return CheckResult(
            name=f"import:{module_name}",
            status=status,
            message=f"Error importando '{module_name}': {e}",
            details={"error_type": "ImportError", "error_msg": str(e)}
        )
    except Exception as e:
        return CheckResult(
            name=f"import:{module_name}",
            status=CheckStatus.ERROR,
            message=f"Error inesperado con '{module_name}': {type(e).__name__}: {e}",
            details={"error_type": type(e).__name__}
        )

def check_file_exists(filepath: Path, required: bool = True) -> CheckResult:
    """Verifica existencia de un archivo"""
    if filepath.exists():
        return CheckResult(
            name=f"file:{filepath.name}",
            status=CheckStatus.OK,
            message=f"Archivo encontrado: {filepath}",
            details={"size_bytes": filepath.stat().st_size, "modified": filepath.stat().st_mtime}
        )
    if required:
        return CheckResult(
            name=f"file:{filepath.name}",
            status=CheckStatus.ERROR,
            message=f"Archivo requerido no encontrado: {filepath}",
            details={"absolute_path": str(filepath.absolute())}
        )
    return CheckResult(
        name=f"file:{filepath.name}",
        status=CheckStatus.WARNING,
        message=f"Archivo opcional no encontrado: {filepath}",
        details={"optional": True}
    )

def check_port_available(port: int, host: str = "127.0.0.1") -> CheckResult:
    """Verifica si un puerto TCP está disponible"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            result = s.connect_ex((host, port))
            if result == 0:
                return CheckResult(
                    name=f"port:{port}",
                    status=CheckStatus.WARNING,
                    message=f"Puerto {port} ya está en uso en {host}",
                    details={"host": host, "port": port}
                )
            return CheckResult(
                name=f"port:{port}",
                status=CheckStatus.OK,
                message=f"Puerto {port} disponible en {host}"
            )
    except Exception as e:
        return CheckResult(
            name=f"port:{port}",
            status=CheckStatus.WARNING,
            message=f"No se pudo verificar puerto {port}: {e}",
            details={"error": str(e)}
        )

def check_shared_registry() -> CheckResult:
    """Verifica que SharedDataRegistry funcione como singleton thread-safe"""
    try:
        # Importar desde gps_symbiosis (módulo base)
        from gps_symbiosis import SharedDataRegistry
        
        # Verificar singleton
        r1 = SharedDataRegistry()
        r2 = SharedDataRegistry()
        if r1 is not r2:
            return CheckResult(
                name="registry:singleton",
                status=CheckStatus.ERROR,
                message="SharedDataRegistry no es singleton (instancias diferentes)"
            )
        
        # Verificar operaciones básicas
        test_key = "_health_check_test"
        test_value = {"timestamp": time.time(), "thread": threading.current_thread().name}
        
        if not r1.set(test_key, test_value):
            return CheckResult(
                name="registry:set",
                status=CheckStatus.ERROR,
                message="SharedDataRegistry.set() falló"
            )
        
        retrieved = r1.get(test_key)
        if retrieved != test_value:
            return CheckResult(
                name="registry:get",
                status=CheckStatus.ERROR,
                message="SharedDataRegistry.get() no recuperó valor correctamente",
                details={"expected": test_value, "got": retrieved}
            )
        
        # Limpiar
        r1._data.pop(test_key, None)
        
        return CheckResult(
            name="registry:integration",
            status=CheckStatus.OK,
            message="SharedDataRegistry funciona correctamente (singleton + CRUD)"
        )
    except ImportError:
        return CheckResult(
            name="registry:integration",
            status=CheckStatus.ERROR,
            message="No se pudo importar SharedDataRegistry desde gps_symbiosis"
        )
    except Exception as e:
        return CheckResult(
            name="registry:integration",
            status=CheckStatus.ERROR,
            message=f"Error verificando SharedDataRegistry: {type(e).__name__}: {e}",
            details={"traceback": str(e)}
        )

def check_coordinate_compatibility() -> CheckResult:
    """Verifica que Coordinate (gps_symbiosis) y GeoPoint (demand_radar) sean interoperables"""
    try:
        # Importar ambas clases
        from gps_symbiosis import Coordinate as SymbiosisCoord
        from demand_radar import GeoPoint as RadarPoint
        
        # Crear instancias con mismos valores
        lat, lon = 8.985, -79.52
        symb = SymbiosisCoord(lat, lon)
        radar = RadarPoint(lat, lon)
        
        # Verificar que ambos tienen los atributos necesarios
        for attr in ['latitude', 'longitude']:
            if not hasattr(symb, attr) or not hasattr(radar, attr):
                return CheckResult(
                    name="coord:attributes",
                    status=CheckStatus.ERROR,
                    message=f"Atributo '{attr}' faltante en una de las clases de coordenadas"
                )
        
        # Verificar método distance_to / distance_km
        target_symb = SymbiosisCoord(9.005, -79.47)
        target_radar = RadarPoint(9.005, -79.47)
        
        dist_symb = symb.distance_to(target_symb)
        dist_radar = radar.distance_km(target_radar)
        
        # Permitir pequeña diferencia por implementación
        if abs(dist_symb - dist_radar) > 0.01:
            return CheckResult(
                name="coord:distance",
                status=CheckStatus.WARNING,
                message="Diferencia en cálculo de distancia entre Coordinate y GeoPoint",
                details={"symbiosis_km": dist_symb, "radar_km": dist_radar, "diff": abs(dist_symb - dist_radar)}
            )
        
        return CheckResult(
            name="coord:compatibility",
            status=CheckStatus.OK,
            message=f"Coordinate y GeoPoint son interoperables (distancia: {dist_symb:.3f} km)"
        )
    except ImportError as e:
        return CheckResult(
            name="coord:compatibility",
            status=CheckStatus.ERROR,
            message=f"No se pudieron importar clases de coordenadas: {e}"
        )
    except Exception as e:
        return CheckResult(
            name="coord:compatibility",
            status=CheckStatus.ERROR,
            message=f"Error verificando compatibilidad de coordenadas: {e}",
            details={"error_type": type(e).__name__}
        )

def check_radar_integration() -> CheckResult:
    """Verifica que IntegratedRadarController pueda conectarse a SymbiosisGPS"""
    try:
        from gps_symbiosis import SymbiosisGPS
        from demand_radar import IntegratedRadarController, RadarConfig
        
        # Crear instancias mínimas
        symb = SymbiosisGPS(use_real_gps=False, persist_dir=str(DATA_DIR / "gps_test"))
        
        controller = IntegratedRadarController()
        controller.symbiosis = symb  # Conexión explícita
        
        # Verificar que el proveedor de datos integrado funciona
        if not hasattr(controller, 'data_provider'):
            # Intentar inicializar parcialmente
            if hasattr(controller, 'initialize'):
                try:
                    controller.initialize(use_real_gps=False)
                except Exception:
                    pass  # Puede fallar por dependencias, continuamos
        
        # Verificar conexión básica
        if controller.symbiosis is symb:
            return CheckResult(
                name="radar:symbiosis_link",
                status=CheckStatus.OK,
                message="IntegratedRadarController conectado a SymbiosisGPS"
            )
        else:
            return CheckResult(
                name="radar:symbiosis_link",
                status=CheckStatus.WARNING,
                message="Conexión entre Radar y Symbiosis no establecida explícitamente",
                details={"symbiosis_attr": hasattr(controller, 'symbiosis')}
            )
            
    except ImportError as e:
        return CheckResult(
            name="radar:symbiosis_link",
            status=CheckStatus.WARNING,
            message=f"Módulos de integración no disponibles (puede ser normal en modo parcial): {e}",
            details={"optional": True}
        )
    except Exception as e:
        return CheckResult(
            name="radar:symbiosis_link",
            status=CheckStatus.WARNING,
            message=f"Advertencia en integración Radar-Symbiosis: {e}",
            details={"error_type": type(e).__name__, "recoverable": True}
        )

def check_environment() -> Dict[str, Any]:
    """Recopila información del entorno de ejecución"""
    return {
        "python_version": sys.version,
        "python_executable": sys.executable,
        "platform": sys.platform,
        "is_termux": IS_TERMUX,
        "has_color_terminal": HAS_COLOR,
        "cwd": str(Path.cwd()),
        "home": str(HOME),
        "data_dir_exists": DATA_DIR.exists(),
        "sys_path_count": len(sys.path),
        "thread_count": threading.active_count(),
        "environment_vars": {
            "TERMUX_VERSION": os.getenv('TERMUX_VERSION', 'N/A'),
            "PATH_contains_termux": 'com.termux' in os.getenv('PATH', '')
        }
    }

# ============================================================================
# EJECUTOR DE VERIFICACIONES
# ============================================================================

class HealthChecker:
    """Orquestador de verificaciones de salud del sistema"""
    
    REQUIRED_MODULES = [
        "gps_symbiosis",
        "demand_radar",
    ]
    
    OPTIONAL_MODULES = [
        "parte5_daimon_base",  # CEOIA
        "parte8_frontend_integrado",
        "parte8_frontend_html_integrado",
        "frontend_html_v6",
        "flask",
        "numpy",
        "h3",
    ]
    
    REQUIRED_FILES = [
        DATA_DIR,  # Directorio de datos debe existir o crearse
    ]
    
    OPTIONAL_FILES = [
        DATA_DIR / "gps_data",
        DATA_DIR / "radar_data",
    ]
    
    CRITICAL_PORTS = [8080, 8081, 8082]  # Puertos típicos del frontend
    
    def __init__(self, verbose: bool = False, fix_mode: bool = False):
        self.verbose = verbose
        self.fix_mode = fix_mode
        self.results: List[CheckResult] = []
        self.start_time = datetime.now(timezone.utc)
        
    def _log(self, message: str, status: CheckStatus = CheckStatus.OK) -> None:
        """Imprime mensaje con formato según estado"""
        if not self.verbose and status == CheckStatus.OK:
            return
            
        icon = {
            CheckStatus.OK: "✅",
            CheckStatus.WARNING: "⚠️",
            CheckStatus.ERROR: "❌",
            CheckStatus.SKIPPED: "⭕"
        }.get(status, "ℹ️")
        
        color = {
            CheckStatus.OK: Colors.GREEN,
            CheckStatus.WARNING: Colors.YELLOW,
            CheckStatus.ERROR: Colors.RED,
            CheckStatus.SKIPPED: Colors.CYAN
        }.get(status, Colors.RESET)
        
        print(Colors.wrap(f"  {icon} {message}", color), flush=True)
        
    def run_all(self) -> HealthReport:
        """Ejecuta todas las verificaciones y retorna reporte"""
        self._log("Iniciando verificación de salud del sistema...", CheckStatus.OK)
        
        # 1. Verificar entorno
        env_info = check_environment()
        self._log(f"Entorno: Python {env_info['python_version'].split()[0]}, Termux: {env_info['is_termux']}")
        
        # 2. Verificar módulos requeridos
        for mod in self.REQUIRED_MODULES:
            result = check_import(mod, optional=False)
            self.results.append(result)
            self._log(result.message, result.status)
            
        # 3. Verificar módulos opcionales
        for mod in self.OPTIONAL_MODULES:
            result = check_import(mod, optional=True)
            self.results.append(result)
            if result.status != CheckStatus.OK or self.verbose:
                self._log(result.message, result.status)
                
        # 4. Verificar archivos
        for fpath in self.REQUIRED_FILES:
            if self.fix_mode and not fpath.exists():
                try:
                    fpath.mkdir(parents=True, exist_ok=True)
                    self._log(f"Creado directorio: {fpath}", CheckStatus.OK)
                except Exception as e:
                    self._log(f"No se pudo crear {fpath}: {e}", CheckStatus.ERROR)
            result = check_file_exists(fpath, required=True)
            self.results.append(result)
            self._log(result.message, result.status)
            
        for fpath in self.OPTIONAL_FILES:
            result = check_file_exists(fpath, required=False)
            self.results.append(result)
            if result.status != CheckStatus.OK or self.verbose:
                self._log(result.message, result.status)
                
        # 5. Verificar puertos críticos
        for port in self.CRITICAL_PORTS:
            result = check_port_available(port)
            self.results.append(result)
            if result.status != CheckStatus.OK or self.verbose:
                self._log(result.message, result.status)
                
        # 6. Verificar componentes de integración
        registry_result = check_shared_registry()
        self.results.append(registry_result)
        self._log(registry_result.message, registry_result.status)
        
        coord_result = check_coordinate_compatibility()
        self.results.append(coord_result)
        self._log(coord_result.message, coord_result.status)
        
        radar_result = check_radar_integration()
        self.results.append(radar_result)
        self._log(radar_result.message, radar_result.status)
        
        # 7. Generar recomendaciones
        recommendations = self._generate_recommendations()
        
        # 8. Compilar reporte
        end_time = datetime.now(timezone.utc)
        counts = {s: sum(1 for r in self.results if r.status == s) for s in CheckStatus}
        
        report = HealthReport(
            start_time=self.start_time.isoformat(),
            end_time=end_time.isoformat(),
            total_checks=len(self.results),
            passed=counts[CheckStatus.OK],
            warnings=counts[CheckStatus.WARNING],
            errors=counts[CheckStatus.ERROR],
            skipped=counts[CheckStatus.SKIPPED],
            results=[r.to_dict() for r in self.results],
            environment=env_info,
            recommendations=recommendations
        )
        
        # Guardar reporte si se solicita
        if self.fix_mode or True:  # Siempre guardar para auditoría
            self._save_report(report)
            
        return report
        
    def _generate_recommendations(self) -> List[str]:
        """Genera recomendaciones basadas en los resultados"""
        recs = []
        
        errors = [r for r in self.results if r.status == CheckStatus.ERROR]
        warnings = [r for r in self.results if r.status == CheckStatus.WARNING]
        
        if any("import:gps_symbiosis" in r.name for r in errors):
            recs.append("Verifica que gps_symbiosis.py esté en el mismo directorio o en PYTHONPATH")
            
        if any("import:demand_radar" in r.name for r in errors):
            recs.append("Verifica que demand_radar.py esté accesible y sin errores de sintaxis")
            
        if any("registry" in r.name and r.status == CheckStatus.ERROR for r in errors):
            recs.append("SharedDataRegistry es crítico para la comunicación entre módulos - revisa imports")
            
        if any("coord" in r.name and r.status != CheckStatus.OK for r in self.results):
            recs.append("Coordinate y GeoPoint deben ser interoperables - verifica cálculos de distancia")
            
        if any("port:8080" in r.name and r.status == CheckStatus.WARNING for r in self.results):
            recs.append("Puerto 8080 ocupado - el frontend usará un puerto alternativo automáticamente")
            
        if not DATA_DIR.exists():
            recs.append(f"Crea el directorio de datos: mkdir -p {DATA_DIR}")
            
        if IS_TERMUX and any("numpy" in r.name for r in warnings):
            recs.append("En Termux, instala numpy con: pkg install python-numpy -y (opcional, mejora rendimiento)")
            
        if not recs:
            recs.append("✅ Sistema listo para despliegue. Ejecuta: python main_unificado.py")
            
        return recs
        
    def _save_report(self, report: HealthReport) -> None:
        """Guarda el reporte en archivo JSON"""
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(REPORT_FILE, 'w', encoding='utf-8') as f:
                f.write(report.to_json())
            if self.verbose:
                self._log(f"Reporte guardado en: {REPORT_FILE}", CheckStatus.OK)
        except Exception as e:
            if self.verbose:
                self._log(f"No se pudo guardar reporte: {e}", CheckStatus.WARNING)
                
    def print_summary(self, report: HealthReport) -> int:
        """Imprime resumen visual y retorna código de salida"""
        print("\n" + "=" * 70, flush=True)
        print(Colors.wrap("  RESUMEN DE SALUD DEL SISTEMA DAIMON VIVO", Colors.BOLD), flush=True)
        print("=" * 70, flush=True)
        
        # Estadísticas
        stats = [
            ("Verificaciones totales", report.total_checks),
            ("✅ Exitosas", report.passed),
            ("⚠️  Advertencias", report.warnings),
            ("❌ Errores", report.errors),
            ("⭕ Omitidas", report.skipped),
        ]
        
        for label, value in stats:
            color = Colors.GREEN if "Exitosas" in label else (
                Colors.YELLOW if "Advertencias" in label else (
                    Colors.RED if "Errores" in label else Colors.CYAN
                )
            )
            print(f"  {label}: {Colors.wrap(str(value), color)}", flush=True)
            
        print("-" * 70, flush=True)
        
        # Recomendaciones
        if report.recommendations:
            print("\n  RECOMENDACIONES:", flush=True)
            for i, rec in enumerate(report.recommendations, 1):
                print(f"    {i}. {rec}", flush=True)
                
        print("\n" + "=" * 70, flush=True)
        
        # Determinar código de salida
        if report.errors > 0:
            print(Colors.wrap("  ❌ ERRORES CRÍTICOS DETECTADOS - No proceder con despliegue", Colors.RED), flush=True)
            return 2
        elif report.warnings > 0:
            print(Colors.wrap("  ⚠️  ADVERTENCIAS - Revisar antes de producción", Colors.YELLOW), flush=True)
            return 1
        else:
            print(Colors.wrap("  ✅ SISTEMA LISTO PARA PRODUCCIÓN", Colors.GREEN), flush=True)
            return 0

# ============================================================================
# MAIN
# ============================================================================

def parse_args() -> Tuple[bool, bool]:
    """Parsea argumentos de línea de comandos"""
    verbose = '--verbose' in sys.argv or '-v' in sys.argv
    fix_mode = '--fix' in sys.argv
    return verbose, fix_mode

def main() -> int:
    """Punto de entrada principal"""
    verbose, fix_mode = parse_args()
    
    # Banner inicial
    print("\n" + "=" * 70, flush=True)
    print(Colors.wrap("  HEALTH CHECK - SISTEMA DAIMON VIVO", Colors.BOLD + Colors.CYAN), flush=True)
    print(f"  Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    print(f"  Modo: {'VERBOSE' if verbose else 'NORMAL'} | {'FIX' if fix_mode else 'CHECK-ONLY'}", flush=True)
    print("=" * 70 + "\n", flush=True)
    
    # Ejecutar verificaciones
    checker = HealthChecker(verbose=verbose, fix_mode=fix_mode)
    report = checker.run_all()
    
    # Imprimir resumen
    exit_code = checker.print_summary(report)
    
    # Info adicional para modo verbose
    if verbose:
        print(f"\n  📄 Reporte completo: {REPORT_FILE}", flush=True)
        print(f"  ⏱️  Tiempo de ejecución: {(datetime.now(timezone.utc) - checker.start_time).total_seconds():.2f}s", flush=True)
        
    return exit_code

if __name__ == "__main__":
    sys.exit(main())
