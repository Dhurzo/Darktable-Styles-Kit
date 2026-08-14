# PLAN: Capturar el grading global cálido/frío de las referencias

**Contexto**: La prueba con referencias de Enric Ramirez (r4s) reveló que el
sistema converge siempre a estilos neutrales (colorbalancergb = 0, solo
filmicrgb+vibrance). Verificación con datos (5 refs r4s, análisis por zona):

- **Altas**: naranja 21°–45° en 5/5 refs (consistente).
- **Medios**: cálidos 4/5 (una verde 88°).
- **Sombras**: rojas 0°–15° en 4/5 (una azul 273°). NO hay teal (160°–230°)
  en ninguna zona — el "teal" percibido es contraste simultáneo.
- El grading real es **cálido global** (hues cercanos 0°–45° en las 3 zonas),
  no split-tone teal/orange.

**Síntoma**: los 5 estilos generados (Palander, Mou, r4s) son indistinguibles
(MAE ≤ 4/255). Todas las confianzas de hue < 0.7 → prompt ordena NEUTRAL →
validator no puede dejar pasar nada.

---

## Causas raíz confirmadas

| # | Causa | Evidencia |
|---|-------|-----------|
| A | **Agregación por media**: 1 ref discrepante veta el consenso de las demás | ref 728 (sombras azules 273°) + ref 686 (sat sombras 0.103) hunden la confianza media a 0.11/0.00/0.36 |
| B | **Umbral `MIN_SATURATION_FOR_HUE=0.15`** descarta zonas con volumen real | sombras de la 686: 550k píxeles con sat 0.103 → zona marcada neutral sin analizar hue |
| C | **Sin categoría "grading global"**: el modelo solo emite neutral/mono/bi por zona | un tinte cálido coherente (15°/38°/33°) no se declara; el prompt ordena NEUTRAL |
| D | **Excepción del validator 2.3 demasiado estrecha**: exige mismo hue ±15° en las 3 zonas para "mono intencional" | hues 15°/38°/33° (23° de spread) no pasan → halving aunque la ref sea claramente cálida |

---

## Solución propuesta (Hitos 6A–6E, solo análisis → después implementación)

### Hito 6A — Agregación robusta por consenso (arregla causa A)
En `analyze_reference_hues._zone_combine`, sustituir la media de confianzas
por un **voto circular**:
1. Calcular el hue consenso = circular mean ponderado de los hues
   individuales (ya existe `_circular_mean`).
2. `agree = fracción de refs cuyo hue individual cae dentro de ±30° del
   consenso`.
3. `conf = max(conf_media, agree)` (o `max(conf_media, mediana de confs)`).
4. Si `agree >= 0.6` → hue válido aunque una ref discrepe (la discrepante
   deja de vetar).
- **Test**: 4 refs a 200° + 1 a 90° → hue=200°, conf ≥ 0.6 (hoy: neutral).
  2 refs a 200° + 3 a 90° → neutral (sigue siendo correcto).

### Hito 6B — Umbral de saturación adaptativo (arregla causa B)
- Bajar `MIN_SATURATION_FOR_HUE` de 0.15 → 0.10.
- Regla de volumen: si `valid_count >= MIN_VALID_PIXELS` (200) con
  `delta > 0.05`, analizar hue aunque la sat media de la zona < umbral.
- Escala de confianza individual más suave: `min(1, mean_sat / 0.20)` en vez
  de `/ 0.30`.
- **Test**: zona oscura con sat 0.10–0.14 y >200 px saturados → ya emite hue
  (hoy: neutral con conf 0).

### Hito 6C — Nuevo modo "global grade" (arregla causa C)
En el empaquetado por referencia (`_pack`):
- Si las 3 zonas tienen hue válido y los 3 hues caen dentro de ±45° del
  circular mean conjunto → la ref declara `zone_hue_mode='global'` (nuevo
  valor) y el hue de zona se conserva por zona.
- Si `global` en ≥60% de refs con consenso ±30° → el agregado emite los 3
  hues por zona con conf = voto (≥0.7 permitido).
- El agregado conserva `hue_mode='mono'` solo cuando el consenso es un hue
  único; `global` indica "tinte coherente en todo el rango tonal".
- **Test**: refs con sombras 15°, medios 38°, altas 33° → `global`, hues
  emitidos, conf alta.

### Hito 6D — Validator: aceptar "global grade" intencional (arregla causa D)
En `validator.py` 2.3:
- La excepción "mono intencional" se amplía: además de `hue_mode='mono'` en
  las 3 zonas con hues ±15°, aceptar `hue_mode='global'` (o 'mono') con
  hues dentro de ±45° entre sí.
- Con eso, un VLM que aplique sombras 15°, medios 30°, altas 35° (cálido
  global) NO recibe halving.
- **Test**: ref global + spec cálido (15/30/35 con chroma>0.05) → sin
  halving, warnings limpios.

### Hito 6E — Prompt: instrucción GLOBAL WARM/COOL GRADE
En `prompt_builder.py`:
- Si el agregado emite `global` con conf ≥0.7: nueva instrucción en
  `reference_note`:
  "[GLOBAL WARM/COOL GRADE] Reference is consistently warm/cool across the
  tonal range: shadows_H=X°, midtones_H=Y°, highlights_H=Z°. Apply these
  hues with MODEST chroma (soft caps); keep global_C=0."
- El bloque `_chroma_caps_block` ya escala por confianza (0.10/0.08/0.05
  soft / 0.15/0.15/0.10 high) — coherente.
- **Test**: ref global cálida → prompt contiene los 3 hues y la instrucción.

---

## Criterio de éxito (prueba de regresión con r4s)

1. `analyze_reference_hues(5 refs r4s)` → NUEVO resultado esperado:
   - shadows_hue ≈ 0–15°, midtones_hue ≈ 25–40°, highlights_hue ≈ 25–45°,
   - `*_hue_confidence >= 0.7` (voto 4/5 o 5/5),
   - `*_hue_mode = 'global'`.
2. Re-generar estilo con las mismas refs → el `.dtstyle` debe contener
   colorbalancergb con hue cálido en sombras/altas y chroma > 0 (no neutral).
3. Render en los 11 RAWs → MAE vs estilo anterior > 4/255 (diferencias
   visibles) y paleta cálida (R>B en medios/altas).
4. Suite completa de tests existentes sigue verde (317 tests).
5. Los demás estilos (Palander, Mou) también deben capturar su grading si
   existe; si sus refs son genuinamente neutras, siguen saliendo neutrales
   (comportamiento correcto).

## Estado de implementación (2026-08-14)

**Hitos 6A–6E: IMPLEMENTADOS y commiteados en `develop`.**

| Hito | Commit | Verificación |
|------|--------|--------------|
| 6A voto circular + 6B umbral adaptativo + 6C modo `global` | `366793f` | `analyze_reference_hues(5 refs r4s)` → shadows 1.0° conf 0.80 / midtones 29.4° conf 0.86 / highlights 33.0° conf 1.00, mode=`global` en las 3 (criterio ✓) |
| 6D validator excepción global (±45°, match con hue del spec) | `b84f58b` | `TestValidateGlobalGrade` 3/3 + regresión 11/11 anti-tint |
| 6E prompt `[GLOBAL WARM/COOL GRADE]` | `441ab01` | `TestPromptAntiTintRules` 12/12 (4 nuevos) |

Suite completa: **366 passed, 8 skipped** (skips preexistentes).

**PENDIENTE (prueba de integración, criterios 2 y 3 del plan)** — abortado el
2026-08-14 porque la GPU estaba ocupada; el proceso se detuvo con el log en
`/tmp/r4s_run2.log` (llegó a "Calling VLM..." con los hues ya corregidos en el
análisis Python: 1.0/29.4/33.0 conf 0.80/0.86/1.00):

1. Re-lanzar la generación (cuando la gráfica esté libre):
   ```
   dtstylekit generate /tmp/r4s_target_preview.jpg \
     --references "/home/juan/Documentos/Pruebas DT Style Kit/References/"*.jpg \
     --output "/home/juan/Documentos/Pruebas DT Style Kit/Estilo_Generado" \
     --direction "Match the color grading of the reference photos (Enric Ramirez r4s look): ..."
   ```
   (target preview ya renderizado: `/tmp/r4s_target_preview.jpg` desde `DSC05838.ARW`)
2. Verificar el `.dtstyle` nuevo: colorbalancergb con hues cálidos (≈1°/29°/33°)
   y chroma > 0 (NO neutral) — decodificar con `unpack_params`.
3. Render en los 11 RAWs (`Renders_R4S_v2/`) → MAE vs `Renders_R4S/` (estilo
   viejo) > 4/255 y paleta cálida (R>B en medios/altas).
4. Verificación visual VLM manual del usuario.

## Fuera de alcance (opcional, discutir)
- Parámetro de producto `--grading-strength` (0=neutral, 1=fiel) para que el
  usuario controle la intensidad del grading cuando la ref es ambigua.
- Soporte de "split-tone explícito" (teal shadows + orange highlights) como
  categoría propia si el usuario aporta refs que sí lo tengan (hoy las r4s
  no lo tienen según los datos).