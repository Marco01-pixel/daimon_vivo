# 🚀 DAIMON VIVO - Sistema Autónomo de IA

> **Sistema integral de inteligencia artificial para optimización de rutas, toma de decisiones autónomas y detección de demanda en tiempo real.**  
> *Desarrollado con arquitectura modular, compatible con entornos limitados (Termux/Android) y listo para producción.*

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![Termux](https://img.shields.io/badge/Compatible-Termux%20%2F%20Android-orange.svg)](https://termux.dev/)

---

## 📋 Descripción del Proyecto

**DAIMON VIVO** es un laboratorio de investigación en inteligencia artificial que integra múltiples algoritmos de **Reinforcement Learning (RL)**, lógica difusa (Fuzzy Logic) y sistemas multi-agente para resolver problemas complejos de logística y toma de decisiones en tiempo real. 

El sistema actúa como un "copiloto autónomo" que analiza coordenadas GPS, predice picos de demanda, evalúa ofertas económicas y toma decisiones deterministas protegiendo la integridad del usuario mediante un protocolo de confianza (*Trust Guard*).

---

## 🌟 Características Principales

- 🧠 **Ensemble Reinforcement Learning**: Integración de Double DQN, PPO, Actor-Critic, SARSA y MCTS con votación ponderada dinámica.
- 📍 **GPS Symbiosis**: Núcleo de inteligencia geoespacial con geocercas dinámicas, filtrado Kalman y optimización de rutas en grafos.
- 📡 **Demand Radar Engine**: Motor de detección de demanda en tiempo real con análisis de tendencias, alertas por umbrales y predicción simple.
- 🛡️ **Protocolo "MEJOR OPCIÓN"**: Evaluador determinista de ofertas con pipeline secuencial estricto, emulación de comportamiento humano y protección anti-detección.
- 🌐 **Frontend Web Interactivo**: Taxímetro en tiempo real con mapa Leaflet.js, calculadora de costos de vehículo y visualización de zonas de demanda.
- 🤝 **Sistema de Negociación Multi-Agente**: Orquestador de negociación con perfiles de utilidad, reputación y estrategias adaptativas.
- 📱 **100% Compatible con Termux**: Diseñado para funcionar sin root, con gestión de memoria optimizada y fallbacks elegantes.

---

## 🏗️ Arquitectura del Sistema

El proyecto sigue un diseño modular desacoplado, comunicándose a través de un `SharedDataRegistry` thread-safe:

| Módulo | Archivo | Responsabilidad |
|--------|---------|-----------------|
| **Orquestador Principal** | `main.py` | Inicializa, sincroniza y gestiona el ciclo de vida de todos los módulos. |
| **Gobierno Autónomo (CEOIA)** | `parte5_daimon_base.py` | Cerebro central. Integra RL, lógica fuzzy, conexión con LLMs y el sistema de negociación. |
| **Inteligencia GPS** | `gps_symbiosis.py` | Gestión de coordenadas, geocercas, enrutamiento y actualización de estados de ubicación. |
| **Radar de Demanda** | `demand_radar.py` | Escaneo continuo de zonas, cálculo de scores de demanda, detección de hotspots y alertas. |
| **Interfaz Web** | `parte8_frontend_integrado.py` | Servidor Flask + HTML/JS embebido. Expone APIs y renderiza el mapa interactivo. |
| **Diagnóstico** | `health_check.py` | Verificación de integridad del sistema, dependencias y estado de los hilos. |

---

## 🛠️ Stack Tecnológico

- **Lenguaje**: Python 3.10+
- **Backend**: Flask (API REST), Threading (concurrencia thread-safe)
- **Matemáticas/RL**: NumPy (cálculos matriciales), implementaciones nativas de RL y Fuzzy Logic
- **Frontend**: HTML5, CSS3, JavaScript, Leaflet.js (Mapas)
- **IA Externa**: Integración opcional con Ollama (local) y DeepSeek API
- **Entorno**: Optimizado para Termux (Android), Linux y macOS.

---

## ⚡ Instalación y Uso Rápido

### 1. Clonar el repositorio
```bash
git clone https://github.com/Marco01-pixel/daimon_vivo.git
cd daimon_vivo
