# SETUP.md — Configuración rápida para nuevos usuarios

> **tl;dr** Lo mínimo que necesitas para que `dtstylekit` funcione.

---

## ✅ Requisitos previos (obligatorios)

| Componente | Versión mínima | Verificación |
|------------|----------------|--------------|
| **Python** | 3.11+ | `python3 --version` |
| **Ollama** | — | `ollama list` |
| **Darktable** | 5.6+ | `darktable-cli --version` |
| **Checkout de darktable** | master / 5.6+ | `git clone https://github.com/darktable-org/darktable` |

---

## 🚀 Inicio rápido (3 pasos)

```bash
# 1. Clona el repo
git clone https://github.com/tu-usuario/dtstylekit
cd dtstylekit

# 2. Instala dependencias (Python 3.11+)
pip install -e .[dev]

# 3. Ollama + modelo por defecto
ollama serve &            # en otra terminal
ollama pull gemma3:27b    # modelo por defecto

# 4. Presets de darktable (OBLIGATORIO)
./setup.sh
#   → Busca darktable automáticamente, crea symlink data/presets,
#   construye índice de búsqueda (puede tardar unos minutos)

# 5. ¡Listo!
dtstylekit generate foto.jpg -o mi_estilo.dtstyle
```

---

## 🔧 Variables de entorno opcionales

| Variable | Por defecto | Para qué sirve |
|----------|-------------|----------------|
| `DTSTYLEKIT_PRESETS_DIR` | Auto-detect | Fuerza ruta a `.dtstyle` si no usa symlink |
| `DTSTYLEKIT_OUTPUTS_DIR` | `./outputs` | Carpeta de salidas (estilos, reports) |
| `OLLAMA_HOST` | `http://localhost:11434` | Si Ollama corre en otra máquina/puerto |
| `DTSTYLEKIT_PRESETS_DIR` | Auto-detect | Fuerza ruta a `.dtstyle` si no usa symlink |

```bash
# Ejemplos
export DTSTYLEKIT_PRESETS_DIR=/home/usuario/darktable/data/styles
export OLLAMA_HOST=http://192.168.1.50:11434   # Ollama en otra máquina
```

---

## ⚡ Quickstart (3 comandos)

```bash
# 1. Clona e instala
git clone https://github.com/tu-usuario/dtstylekit
cd dtstylekit
pip install -e .[dev]

# 2. Ollama + modelo
ollama serve &           # terminal aparte
ollama pull gemma3:27b

# 3. Presets (necesario una sola vez)
./setup.sh

# 5. ¡Genera tu primer estilo!
dtstylekit generate foto.jpg -o mi_estilo.dtstyle
```

---

## 📦 Qué necesitas tener instalado ANTES de empezar

| Componente | Mínimo | Comando de verificación |
|------------|--------|-------------------------|
| **Python** | 3.11+ | `python3 --version` |
| **Ollama** | — | `ollama list` |
| **Darktable** | 5.6+ | `darktable-cli --version` |
| **Git** | — | `git --version` |
| **Python** | 3.11+ | `python3 --version` |

---

## 🔧 Variables de entorno útiles

```bash
# Si tu darktable NO está en el layout estándar (dtstylekit dentro del checkout):
export DTSTYLEKIT_PRESETS_DIR=/ruta/a/darktable/data/styles

# Si Ollama corre en otra máquina/puerto
export OLLAMA_HOST=http://192.168.1.50:11434

# Carpeta de salida personalizada
export DTSTYLEKIT_OUTPUTS_DIR=/ruta/a/salida
```

---

## 🧪 Verificación rápida

```bash
# 1. ¿Ollama responde?
curl -s http://localhost:11434/api/tags | jq '.models[].name'

# 2. ¿Darktable CLI funciona?
darktable-cli --version

# 3. ¿Índice de presets construido?
dtstylekit preset index --force

# 5. ¡Primer estilo!
dtstylekit generate foto.jpg -o test.dtstyle
```

---

## 🐛 Problemas comunes

| Síntoma | Causa probable | Solución |
|---------|----------------|----------|
| `dtstylekit: command not found` | No activaste venv / no instalaste en editable | `source .venv/bin/activate && pip install -e .[dev]` |
| `ollama: connection refused` | Ollama no corriendo | `ollama serve &` |
| `No .dtstyle files found` | Falta symlink `data/presets` | Ejecuta `./setup.sh` |
| `fts5: syntax error near ","` | Comas en `--direction` | Usa palabras separadas por espacio |
| `VLM call failed: Failed to load image` | Imagen no es JPEG | Usa JPEG, no WebP |
| `VLM call failed: Failed to load image` | Ruta relativa | Usa ruta absoluta |

---

## 📋 Checklist pre-vuelo

- [ ] Python 3.11+ instalado
- [ ] `ollama serve` corriendo en background
- [ ] `ollama pull gemma3:27b` (o tu modelo preferido)
- [ ] `darktable-cli --version` ≥ 5.6
- [ ] `./setup.sh` ejecutado sin errores (ve "Found 534 preset(s)")
- [ ] `dtstylekit generate test.jpg -o test.dtstyle` funciona

---

## 🔗 Enlaces útiles

- **Ollama**: https://ollama.ai/
- **Darktable**: https://www.darktable.org/
- **Modelos recomendados**: `gemma3:27b` (default), `llama3.2-vision:11b` (mejor calidad), `gemma3:4b` (ligero)

---

> **Nota**: El proyecto asume que tienes un checkout de darktable accesible (el repo padre de dtstylekit o una variable `DTSTYLEKIT_PRESETS_DIR`). Los 534 estilos `.dtstyle` oficiales de darktable **no se incluyen** en este repo — se enlazan vía symlink `data/presets → darktable/data/styles`.
