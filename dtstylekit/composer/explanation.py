"""Generate natural-language explanation documents for generated styles.

This module produces a *narrative* companion to the technical markdown
report: it walks through the reference photographs (what they look like,
how they are graded, per-tonal-zone hue analysis) and then explains —
in plain language — why each module/parameter of the generated style was
chosen, tracing every decision back to the measured data.

Languages: ``es`` (Spanish, default) and ``en`` (English).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from dtstylekit.analyzer.models import ImageAnalysis
from dtstylekit.vlm.models import StyleSpec

# ---------------------------------------------------------------------------
# Small interpretation helpers
# ---------------------------------------------------------------------------


def _clave(mean: float) -> str:
    """Tonal key of an image from its mean luminance (0-1)."""
    if mean < 0.3:
        return "low"  # clave baja
    if mean < 0.6:
        return "mid"  # clave media
    return "high"  # clave alta


def _contrast_band(std: float) -> str:
    if std < 0.15:
        return "low"
    if std < 0.25:
        return "mid"
    return "high"


def _sat_band(sat: float) -> str:
    if sat < 0.15:
        return "low"
    if sat < 0.35:
        return "mid"
    return "high"


def _wb_band(wb: float) -> str:
    if 0.95 <= wb <= 1.05:
        return "neutral"
    if wb > 1.05:
        return "warm"
    return "cool"


def hue_name(deg: float) -> str:
    """Map a hue angle (0-360) to a human-readable colour family name."""
    h = float(deg) % 360.0
    if h < 20 or h >= 340:
        return "red"
    if h < 45:
        return "orange"
    if h < 70:
        return "yellow"
    if h < 160:
        return "green"
    if h < 205:
        return "teal"
    if h < 250:
        return "blue"
    if h < 290:
        return "violet"
    return "magenta"


# ---------------------------------------------------------------------------
# Text dictionaries (es / en)
# ---------------------------------------------------------------------------

_TEXT: dict[str, dict[str, str | list[str]]] = {
    "es": {
        "title": "Explicación del estilo: {name}",
        "auto": "*Documento generado automáticamente por dtstylekit el {date}*",
        "desc": "**Descripción**: {desc}",
        "no_desc": "*(sin descripción)*",
        "s1_title": "## 1. Análisis de las fotografías de referencia",
        "s1_intro": "Se analizaron {n} imagen(es) de referencia para derivar el look objetivo:",
        "s1_table_header": "| Imagen | Lum. media | Contraste (σ) | Saturación | Sombras | Medios | Altas | WB R/B |",
        "s1_table_sep": "|--------|-----------|--------------|------------|---------|--------|-------|--------|",
        "s1_synth": "### Síntesis del look de las referencias",
        "s1_tonal": "- **Tonalidad**: las referencias son de clave {clave} (luminancia media entre {lo:.2f} y {hi:.2f}), con contraste {contrast}.",
        "s1_color": "- **Color**: balance de blancos {wb} (R/B entre {wblo:.2f} y {wbhi:.2f}) y saturación {sat} ({satlo:.2f}–{sathi:.2f}).",
        "s1_dist": "- **Distribución tonal**: dominan {dom}.",
        "s1_no_refs": "No se proporcionaron imágenes de referencia; el estilo se deriva de la imagen objetivo y de la dirección indicada.",
        "s2_title": "## 2. Cómo están editadas las referencias",
        "s2_intro": "Se analizó el matiz (hue) y la saturación en tres zonas tonales (sombras <0.25, medios 0.25–0.75, altas ≥0.75 en luminancia). Una confianza ≥0.7 indica una gradación de color clara y consistente entre las referencias; por debajo, el sistema respeta los colores originales de la foto.",
        "s2_shadows": "### Sombras",
        "s2_midtones": "### Medios",
        "s2_highlights": "### Altas",
        "zone_neutral": "- **Neutras** (confianza {conf:.2f}): no hay una gradación de color clara; se respeta el color original de la fotografía.",
        "zone_mono": "- **Matiz dominante**: {color} ({hue:.0f}°), saturación media {sat:.3f} (confianza {conf:.2f}).",
        "zone_bi": "- **Gradación bimodal**: predominante {color1} ({hue1:.0f}°) y secundaria {color2} ({hue2:.0f}°), saturación media {sat:.3f} (confianza {conf:.2f}).",
        "zone_nodata": "- *(sin datos suficientes)*",
        "s2_interp": "### Interpretación",
        "s2_interp_neutral": "Las referencias no muestran una gradación de color dominante, por lo que el estilo se centra en el tono y el contraste, manteniendo los colores naturales de la fotografía.",
        "s2_interp_bi": "Las referencias combinan dos familias de color ({c1} y {c2}), típico de una gradación sutil tipo *teal & orange*: sombras frías y pieles/altas cálidas. El sistema no impone el matiz porque la confianza no alcanza el umbral, evitando teñir fotografías con contenido variado.",
        "s2_interp_mono": "Las referencias comparten un matiz dominante ({color}), indicando una gradación coherente. El validador aplica este matiz en la zona correspondiente con una croma limitada para mantener la naturalidad.",
        "s3_title": "## 3. Por qué se ha generado así el preset",
        "s3_intro": "El estilo generado combina módulos de darktable con parámetros seguros (validados contra los rangos reales de cada módulo). Cada decisión se justifica a continuación.",
        "s3_modules": "### {op}",
        "s3_presets": "### Presets base",
        "s3_presets_none": "No se seleccionó ningún preset de la librería (534 estilos): la búsqueda semántica no encontró una base que aportara valor al look deseado, así que el estilo se construye por completo con ajustes escalares.",
        "s3_presets_list": "Se seleccionaron {n} presets de la librería como base, sobre los que se aplican los ajustes escalares:",
        "s3_guards": "### Decisiones de pipeline y guardas aplicadas",
        "s3_guards_body": [
            "- **filmicrgb en lugar de sigmoid**: el estilo está pensado para archivos RAW, donde darktable añade un filmicrgb por defecto; usar sigmoid apilaría dos mapeos tonales y aplastaría la imagen.",
            "- **Límites de croma por zona**: el validador ajusta la saturación de cada zona tonal (sombras/medios/altas) según la confianza del análisis de las referencias, evitando teñidos excesivos.",
            "- **Sin tinte aditivo global** (global_C=0): evita el fallo clásico de teñir toda la imagen de rojo.",
            "- **Protección de pieles**: la croma de medios se limita cuando la imagen objetivo parece un retrato (R≈G>B), para no teñir la piel.",
            "- **Monocromía**: si las referencias no declaran una gradación monocroma intencional, el validador reduce a la mitad la croma cuando las tres zonas comparten matiz (evita un tinte global oculto).",
        ],
        "s3_rationale": "### Racional del modelo",
        "s3_rationale_body": "El modelo VLM razonó así: *{rationale}*",
        "s4_title": "## 4. Resultado esperado",
        "s4_expected": "Al aplicar el estilo a un RAW, el resultado será: {exp_tonal}, {exp_color}, con {exp_finish}.",
        "s5_title": "## 5. Cómo se usa",
        "s5_body": [
            '1. Importa el archivo `.dtstyle` en darktable (Módulos → Estilos → Importar) o aplícalo desde la línea de comandos con `darktable-cli imagen.ARW salida.jpg --style "{name}"`.',
            "2. Ajusta la cantidad aplicando el estilo con `Ctrl+Shift+S` y moviendo la opacidad del estilo.",
        ],
        "s6_title": "## 6. Limitaciones y siguientes pasos",
        "s6_body": "El estilo se genera para funcionar en un rango amplio de exposiciones y contenidos, por lo que la fidelidad al look exacto de las referencias puede variar. Para acercarlo más, se puede ejecutar con refinamiento iterativo: `dtstylekit generate ... --refine-iterations 3 --refine-raw imagen.ARW`, que renderiza el estilo, mide el resultado y re-pregunta al modelo visualmente hasta acercarse al objetivo.",
        # --- Parameter explanations ---
        "filmic_contrast_hi": "**contrast = {v}**: sube el contraste del mapeo tonal por encima del valor neutro (1.0), dando cuerpo y presencia a la imagen sin llegar a extremos.",
        "filmic_contrast_lo": "**contrast = {v}**: suaviza el contraste del mapeo tonal, coherente con un look delicado y luminoso.",
        "filmic_contrast_neutral": "**contrast = {v}**: contraste tonal neutro, fiel al contraste capturado por el sensor.",
        "filmic_latitude": "**latitude = {v}**: controla la suavidad de la transición entre luces y sombras; con este valor el roll-off es suave y cinematográfico, protegiendo las altas luces de recortes duros.",
        "filmic_sat_neg": "**saturation = {v}**: desaturación {amt} que acerca la imagen a un acabado de película clásica, reduciendo la intensidad de los colores.",
        "filmic_sat_pos": "**saturation = {v}**: refuerza ligeramente la saturación para dar vida a los colores.",
        "filmic_sat_neutral": "**saturation = {v}**: saturación neutra, se mantienen los colores originales.",
        "filmic_balance": "**balance = {v}**: sin desplazamiento del balance tonal entre sombras y altas (los valores muy negativos oscurecerían toda la imagen).",
        "exposure_ev": "**exposure = {ev:+.2f} EV**: compensación {dir} de exposición para ajustar el brillo general sin arriesgar las altas luces.",
        "exposure_black": "**black = {v:+.2f}**: los negros se mantienen sin aplastar, conservando el detalle de las sombras.",
        "cbr_vibrance": "**vibrance = {v}**: aumenta la vivacidad de los colores de forma inteligente, protegiendo los tonos de piel.",
        "cbr_contrast": "**contrast = {v}**: separación sutil de los tonos tras el etalonaje, refuerza la profundidad sin alterar el color.",
        "cbr_zone": "**{zone}** (H={hue:.0f}°, C={chroma:.3f}): se {action} el matiz {color} extraído de las referencias en esta zona tonal.",
        "cbr_zone_neutral": "**{zone}** (H=0°, C=0): neutro — las referencias no mostraban una gradación fiable en esta zona (confianza {conf:.2f} < 0.7), así que se respeta el color original.",
        "cbr_chroma_global": "**chroma_global = {v}**: desaturación global suave (multiplicativa, sin desplazar el matiz), acabado film.",
        "cbr_global_c": "**global_C = {v}**: sin offset aditivo global de color (un valor >0 con matiz 0° teñiría toda la imagen de rojo).",
        "temp_warm": "**red = {red} / blue = {blue}**: coeficientes de balance de blancos cálido — el estilo calienta deliberadamente la imagen subiendo el rojo y bajando el azul (sustituye al WB as-shot de la cámara).",
        "temp_cool": "**red = {red} / blue = {blue}**: coeficientes de balance de blancos frío — el estilo enfría deliberadamente la imagen bajando el rojo y subiendo el azul (sustituye al WB as-shot de la cámara).",
        "temp_custom": "**red = {red} / green = {green} / blue = {blue}**: coeficientes de balance de blancos personalizados elegidos para igualar el look de las referencias (sustituyen al WB as-shot de la cámara).",
        "temp_d65": "**preset = D65**: balance de blancos estándar de luz de día, aplicado como corrección tardía sobre el WB de cámara.",
        "temp_identity_warn": "*(un WB de identidad eliminaría el balance de blancos de la cámara — omitido por seguridad)*",
        "badj_exposure": "**exposure = {v:+.2f} EV**: compensación de exposición scene-referred aplicada antes del mapeo tonal.",
        "badj_black": "**black_point = {v:+.2f}**: ajuste del punto negro (negativo eleva los negros, positivo los aplasta).",
        "badj_contrast": "**contrast = {v}**: aumento de contraste scene-referred antes del mapeo tonal.",
        "badj_vibrance": "**vibrance = {v}**: aumento inteligente de saturación protegiendo los tonos de piel, aplicado antes del etalonaje.",
        "badj_saturation": "**saturation = {v}**: ajuste global de saturación en el módulo de básicos.",
        "badj_brightness": "**brightness = {v}**: desplazamiento global de brillo.",
        "badj_hlcompr": "**hlcompr = {v}**: compresión de altas luces — protege las altas de recortes.",
        "badj_midgrey": "**middle_grey = {v}**: desplaza el pivote de gris medio del mapeo tonal.",
        "teq_bands": "**Bandas**: {bands} — el ecualizador tonal eleva/compacta rangos específicos de luminancia (de ruido a especulares) fundiendo los bordes suavemente.",
        "teq_contrast_boost": "**contrast_boost = {v}**: énfasis de contraste local en las zonas ecualizadas.",
        "teq_exposure_boost": "**exposure_boost = {v}**: énfasis de exposición local en las zonas ecualizadas.",
        "teq_feathering": "**feathering = {v}**: suaviza la transición entre zonas ecualizadas.",
        "teq_iterations": "**iterations = {v}**: pasadas de refinamiento del filtro edge-aware.",
        "teq_neutral": "*(todas las bandas neutras — sin cambios del ecualizador tonal)*",
        "ceq_sat": "sat {v:.2f}",
        "ceq_hue": "hue {v:+.0f}°",
        "ceq_bright": "bright {v:.2f}",
        "ceq_channel": "**{ch}**: {detail} — ajuste por matiz de saturación/matiz/brillo para este rango de color.",
        "ceq_hue_shift": "**hue_shift = {v:+.0f}°**: rotación global de matiz aplicada tras el etalonaje.",
        "ceq_neutral": "*(todos los canales de color neutros — sin cambios del ecualizador por matiz)*",
        "harm_rule": "**rule = {v}**: regla armónica de color aplicada por colorharmonizer (0 monocromática … 9 personalizada, 3 = complementaria).",
        "harm_anchor": "**anchor_hue = {v}**: matiz ancla de la regla armónica, derivado del tono dominante de las referencias.",
        "harm_strength": "**pull_strength = {v}**: intensidad con la que los colores se desplazan hacia el esquema armónico.",
        "harm_neutral_prot": "**neutral_protection = {v}**: protección de los tonos neutros frente al desplazamiento armónico.",
        "harm_width": "**pull_width = {v}**: anchura del rango de matices atraídos por la regla armónica.",
        "harm_smoothing": "**smoothing = {v}**: suavizado de las transiciones de la regla armónica.",
        "harm_neutral": "*(sin cambios de colorharmonizer — regla por defecto y matices neutros)*",
        "exp_tonal_bright": "ligeramente más brillante",
        "exp_tonal_dark": "ligeramente más oscura",
        "exp_tonal_same": "con un brillo similar",
        "exp_color_desat": "colores suavizados con un tinte cálido sutil",
        "exp_color_sat": "colores ligeramente más vivos",
        "exp_color_neutral": "colores naturales preservados",
        "exp_finish_soft": "un acabado suave y cinematográfico, tipo película",
        "exp_finish_punchy": "más contraste y presencia",
        "exp_finish_balanced": "un acabado equilibrado",
    },
    "en": {
        "title": "Style explanation: {name}",
        "auto": "*Document auto-generated by dtstylekit on {date}*",
        "desc": "**Description**: {desc}",
        "no_desc": "*(no description)*",
        "s1_title": "## 1. Reference photograph analysis",
        "s1_intro": "{n} reference image(s) were analysed to derive the target look:",
        "s1_table_header": "| Image | Mean lum. | Contrast (σ) | Saturation | Shadows | Midtones | Highlights | WB R/B |",
        "s1_table_sep": "|-------|-----------|--------------|------------|---------|----------|------------|--------|",
        "s1_synth": "### Look summary of the references",
        "s1_tonal": "- **Tonal key**: the references are {clave} key (mean luminance between {lo:.2f} and {hi:.2f}), with {contrast} contrast.",
        "s1_color": "- **Colour**: white balance {wb} (R/B between {wblo:.2f} and {wbhi:.2f}) and {sat} saturation ({satlo:.2f}–{sathi:.2f}).",
        "s1_dist": "- **Tonal distribution**: dominated by {dom}.",
        "s1_no_refs": "No reference images were provided; the style is derived from the target image and the given direction.",
        "s2_title": "## 2. How the references are graded",
        "s2_intro": "Hue and saturation were analysed in three tonal zones (shadows <0.25, midtones 0.25–0.75, highlights ≥0.75 in luminance). A confidence ≥0.7 indicates a clear, consistent colour grade across references; below that, the system respects the photo's original colours.",
        "s2_shadows": "### Shadows",
        "s2_midtones": "### Midtones",
        "s2_highlights": "### Highlights",
        "zone_neutral": "- **Neutral** (confidence {conf:.2f}): no clear colour grade; the photograph's original colour is preserved.",
        "zone_mono": "- **Dominant hue**: {color} ({hue:.0f}°), mean saturation {sat:.3f} (confidence {conf:.2f}).",
        "zone_bi": "- **Bimodal grade**: dominant {color1} ({hue1:.0f}°) and secondary {color2} ({hue2:.0f}°), mean saturation {sat:.3f} (confidence {conf:.2f}).",
        "zone_nodata": "- *(insufficient data)*",
        "s2_interp": "### Interpretation",
        "s2_interp_neutral": "The references show no dominant colour grade, so the style focuses on tone and contrast while keeping the photograph's natural colours.",
        "s2_interp_bi": "The references combine two colour families ({c1} and {c2}), typical of a subtle *teal & orange* grade: cool shadows and warm skin/highlights. The system does not force the hue because confidence stays below the threshold, avoiding tinting photographs with varied content.",
        "s2_interp_mono": "The references share a dominant hue ({color}), indicating a coherent grade. The validator applies this hue in the corresponding zone with limited chroma to keep it natural.",
        "s3_title": "## 3. Why the preset was generated this way",
        "s3_intro": "The generated style combines darktable modules with safe parameters (validated against the real ranges of each module). Each decision is justified below.",
        "s3_modules": "### {op}",
        "s3_presets": "### Base presets",
        "s3_presets_none": "No preset from the library (534 styles) was selected: the semantic search found no base that added value to the desired look, so the style is built entirely from scalar adjustments.",
        "s3_presets_list": "{n} presets from the library were selected as a base, with scalar adjustments applied on top:",
        "s3_guards": "### Pipeline decisions and applied guardrails",
        "s3_guards_body": [
            "- **filmicrgb instead of sigmoid**: the style targets RAW files, where darktable adds a default filmicrgb; using sigmoid would stack two tone mappings and crush the image.",
            "- **Per-zone chroma caps**: the validator limits each tonal zone's saturation (shadows/midtones/highlights) according to the confidence of the reference analysis, avoiding excessive tinting.",
            "- **No additive global tint** (global_C=0): avoids the classic failure of tinting the whole image red.",
            "- **Skin protection**: midtone chroma is capped when the target image looks like a portrait (R≈G>B), to avoid tinting skin.",
            "- **Monochrome guard**: unless the references declare an intentional monochrome grade, the validator halves chroma when all three zones share a hue (prevents a hidden global tint).",
        ],
        "s3_rationale": "### Model rationale",
        "s3_rationale_body": "The VLM reasoned: *{rationale}*",
        "s4_title": "## 4. Expected result",
        "s4_expected": "When applied to a RAW, the result will be: {exp_tonal}, {exp_color}, with {exp_finish}.",
        "s5_title": "## 5. How to use it",
        "s5_body": [
            '1. Import the `.dtstyle` file into darktable (Modules → Styles → Import) or apply it from the command line with `darktable-cli image.ARW output.jpg --style "{name}"`.',
            "2. Fine-tune the amount by applying the style with `Ctrl+Shift+S` and moving the style opacity.",
        ],
        "s6_title": "## 6. Limitations and next steps",
        "s6_body": "The style is generated to work across a wide range of exposures and content, so fidelity to the exact reference look may vary. To get closer, run with iterative refinement: `dtstylekit generate ... --refine-iterations 3 --refine-raw image.ARW`, which renders the style, measures the result and re-asks the model with visual feedback until it approaches the target.",
        "filmic_contrast_hi": "**contrast = {v}**: raises the tone-mapping contrast above neutral (1.0), giving the image body and presence without going to extremes.",
        "filmic_contrast_lo": "**contrast = {v}**: softens the tone-mapping contrast, consistent with a delicate, bright look.",
        "filmic_contrast_neutral": "**contrast = {v}**: neutral tonal contrast, faithful to what the sensor captured.",
        "filmic_latitude": "**latitude = {v}**: controls how softly lights roll off into shadows; at this value the roll-off is smooth and cinematic, protecting highlights from harsh clipping.",
        "filmic_sat_neg": "**saturation = {v}**: {amt} desaturation that brings the image closer to a classic film finish by reducing colour intensity.",
        "filmic_sat_pos": "**saturation = {v}**: slightly boosts saturation to bring colours to life.",
        "filmic_sat_neutral": "**saturation = {v}**: neutral saturation, original colours are kept.",
        "filmic_balance": "**balance = {v}**: no tonal balance shift between shadows and highlights (strongly negative values would darken the whole image).",
        "exposure_ev": "**exposure = {ev:+.2f} EV**: {dir} exposure compensation to fine-tune overall brightness without risking highlights.",
        "exposure_black": "**black = {v:+.2f}**: blacks are kept uncrushed, preserving shadow detail.",
        "cbr_vibrance": "**vibrance = {v}**: intelligently boosts colour liveliness while protecting skin tones.",
        "cbr_contrast": "**contrast = {v}**: subtle tone separation after grading, reinforcing depth without shifting colour.",
        "cbr_zone": "**{zone}** (H={hue:.0f}°, C={chroma:.3f}): the {color} hue extracted from the references is {action} in this tonal zone.",
        "cbr_zone_neutral": "**{zone}** (H=0°, C=0): neutral — the references showed no reliable grade in this zone (confidence {conf:.2f} < 0.7), so the original colour is respected.",
        "cbr_chroma_global": "**chroma_global = {v}**: gentle global desaturation (multiplicative, no hue shift), film finish.",
        "cbr_global_c": "**global_C = {v}**: no additive global colour offset (a value >0 with hue 0° would tint the whole image red).",
        "temp_warm": "**red = {red} / blue = {blue}**: warm white-balance coefficients — the style deliberately warms the image by boosting red and cutting blue (replaces the camera's as-shot WB).",
        "temp_cool": "**red = {red} / blue = {blue}**: cool white-balance coefficients — the style deliberately cools the image by cutting red and boosting blue (replaces the camera's as-shot WB).",
        "temp_custom": "**red = {red} / green = {green} / blue = {blue}**: custom white-balance coefficients chosen to match the reference look (replaces the camera's as-shot WB).",
        "temp_d65": "**preset = D65**: standard daylight white balance, applied as a late correction over the camera WB.",
        "temp_identity_warn": "*(identity WB would strip the camera's white balance — omitted for safety)*",
        "badj_exposure": "**exposure = {v:+.2f} EV**: scene-referred exposure compensation applied before tone mapping.",
        "badj_black": "**black_point = {v:+.2f}**: black-point adjustment (negative lifts blacks, positive crushes them).",
        "badj_contrast": "**contrast = {v}**: scene-referred contrast boost before tone mapping.",
        "badj_vibrance": "**vibrance = {v}**: smart saturation boost protecting skin tones, applied before grading.",
        "badj_saturation": "**saturation = {v}**: global saturation adjustment in the basics module.",
        "badj_brightness": "**brightness = {v}**: overall brightness offset.",
        "badj_hlcompr": "**hlcompr = {v}**: highlight compression — protects highlights from clipping.",
        "badj_midgrey": "**middle_grey = {v}**: shifts the middle-grey pivot of the tone mapping.",
        "teq_bands": "**Bands**: {bands} — the tonal equalizer lifts/crushes specific luminance ranges (noise→speculars) while blending edges smoothly.",
        "teq_contrast_boost": "**contrast_boost = {v}**: local contrast emphasis on the equalized zones.",
        "teq_exposure_boost": "**exposure_boost = {v}**: local exposure emphasis on the equalized zones.",
        "teq_feathering": "**feathering = {v}**: softens the transition between equalized zones.",
        "teq_iterations": "**iterations = {v}**: refinement passes of the edge-aware filter.",
        "teq_neutral": "*(all bands neutral — no tonal equalizer change)*",
        "ceq_sat": "sat {v:.2f}",
        "ceq_hue": "hue {v:+.0f}°",
        "ceq_bright": "bright {v:.2f}",
        "ceq_channel": "**{ch}**: {detail} — per-hue saturation/hue/brightness tuning for this colour range.",
        "ceq_hue_shift": "**hue_shift = {v:+.0f}°**: global hue rotation applied after grading.",
        "ceq_neutral": "*(all colour channels neutral — no per-hue equalizer change)*",
        "harm_rule": "**rule = {v}**: harmonic colour rule applied by colorharmonizer (0 monochromatic … 9 custom, 3 = complementary).",
        "harm_anchor": "**anchor_hue = {v}**: anchor hue of the harmonic rule, derived from the dominant tone of the references.",
        "harm_strength": "**pull_strength = {v}**: how strongly colours are pulled toward the harmonic scheme.",
        "harm_neutral_prot": "**neutral_protection = {v}**: protection of neutral tones against the harmonic shift.",
        "harm_width": "**pull_width = {v}**: width of the hue range attracted by the harmonic rule.",
        "harm_smoothing": "**smoothing = {v}**: smooths the transitions of the harmonic rule.",
        "harm_neutral": "*(no colorharmonizer change — default rule and neutral hues)*",
        "exp_tonal_bright": "slightly brighter",
        "exp_tonal_dark": "slightly darker",
        "exp_tonal_same": "similar brightness",
        "exp_color_desat": "softened colours with a subtle warm tint",
        "exp_color_sat": "slightly more vivid colours",
        "exp_color_neutral": "natural colours preserved",
        "exp_finish_soft": "a soft, cinematic, film-like finish",
        "exp_finish_punchy": "more contrast and presence",
        "exp_finish_balanced": "a balanced finish",
    },
}

_ADJ = {
    "es": {
        "hi": "fuerte",
        "lo": "suave",
        "neutral": "neutra",
        "mid": "moderada",
        "applied": "aplica",
        "not_applied": "no aplica",
    },
    "en": {
        "hi": "strong",
        "lo": "gentle",
        "neutral": "neutral",
        "mid": "moderate",
        "applied": "applied",
        "not_applied": "not applied",
    },
}

_CLAVE_WORD = {
    "es": {"low": "baja", "mid": "media", "high": "alta"},
    "en": {"low": "low", "mid": "middle", "high": "high"},
}

_CONTRAST_WORD = {
    "es": {"low": "bajo", "mid": "medio", "high": "alto"},
    "en": {"low": "low", "mid": "medium", "high": "high"},
}

_SAT_WORD = {
    "es": {"low": "baja", "mid": "media", "high": "alta"},
    "en": {"low": "low", "mid": "medium", "high": "high"},
}

_WB_WORD = {
    "es": {"neutral": "neutro", "warm": "cálido", "cool": "frío"},
    "en": {"neutral": "neutral", "warm": "warm", "cool": "cool"},
}

_HUE_NAME = {
    "es": {
        "red": "rojo",
        "orange": "naranja/cálido",
        "yellow": "amarillo",
        "green": "verde",
        "teal": "cian/teal",
        "blue": "azul",
        "violet": "violeta",
        "magenta": "magenta",
    },
    "en": {
        "red": "red",
        "orange": "orange",
        "yellow": "yellow",
        "green": "green",
        "teal": "teal",
        "blue": "blue",
        "violet": "violet",
        "magenta": "magenta",
    },
}

_ZONE_NAME = {
    "es": {"shadows": "Sombras", "midtones": "Medios", "highlights": "Altas"},
    "en": {"shadows": "Shadows", "midtones": "Midtones", "highlights": "Highlights"},
}


def _t(lang: str, key: str) -> str:
    return _TEXT[lang][key]  # type: ignore[return-value]


def _color(lang: str, deg: float) -> str:
    return _HUE_NAME[lang][hue_name(deg)]


# ---------------------------------------------------------------------------
# Reference analysis
# ---------------------------------------------------------------------------


def _analyze_reference_stats(paths: list[Path]) -> list[dict]:
    """Per-reference stats via the dtstylekit analyzer (JPEG/TIFF only)."""
    from dtstylekit.analyzer.pipeline import analyze_image

    stats: list[dict] = []
    for p in paths:
        try:
            a = analyze_image(p)
            lum = getattr(a, "luminance", None)
            if lum is None or lum.mean is None:
                continue
            stats.append(
                {
                    "name": Path(p).name,
                    "mean": float(lum.mean),
                    "std": float(lum.std or 0.0),
                    "sat": float(lum.saturation_mean or 0.0),
                    "tonal": [
                        float(lum.shadows_pct or 0.0),
                        float(lum.midtones_pct or 0.0),
                        float(lum.highlights_pct or 0.0),
                    ],
                    "wb": float(lum.white_balance_ratio_rb or 1.0),
                }
            )
        except Exception:
            continue
    return stats


def _zone_line(lang: str, zone: str, ref_analysis: dict | None) -> str:
    """One bullet describing the reference hue analysis for a tonal zone."""
    if not ref_analysis:
        return _t(lang, "zone_nodata")
    hue = ref_analysis.get(f"{zone}_hue")
    conf = float(ref_analysis.get(f"{zone}_hue_confidence") or 0.0)
    sat = float(ref_analysis.get(f"{zone}_sat") or 0.0)
    mode = ref_analysis.get(f"{zone}_hue_mode", "neutral")
    if hue is None or mode == "neutral":
        return _t(lang, "zone_neutral").format(conf=conf)
    if mode == "bi":
        sec = ref_analysis.get(f"{zone}_hue_secondary")
        if sec is None:
            return _t(lang, "zone_mono").format(
                color=_color(lang, hue), hue=hue, sat=sat, conf=conf
            )
        return _t(lang, "zone_bi").format(
            color1=_color(lang, hue),
            hue1=hue,
            color2=_color(lang, sec),
            hue2=sec,
            sat=sat,
            conf=conf,
        )
    return _t(lang, "zone_mono").format(color=_color(lang, hue), hue=hue, sat=sat, conf=conf)


# ---------------------------------------------------------------------------
# Parameter explanations
# ---------------------------------------------------------------------------


def _explain_filmic(lang: str, params: dict) -> list[str]:
    out: list[str] = []
    if "contrast" in params:
        v = float(params["contrast"])
        if v > 1.1:
            out.append(_t(lang, "filmic_contrast_hi").format(v=v))
        elif v < 0.9:
            out.append(_t(lang, "filmic_contrast_lo").format(v=v))
        else:
            out.append(_t(lang, "filmic_contrast_neutral").format(v=v))
    if "latitude" in params:
        v = float(params["latitude"])
        if abs(v - 0.01) > 0.001:
            out.append(_t(lang, "filmic_latitude").format(v=v))
    if "saturation" in params:
        v = float(params["saturation"])
        if v < -0.5:
            out.append(
                _t(lang, "filmic_sat_neg").format(
                    v=v, amt=_ADJ[lang]["hi"] if v <= -30 else _ADJ[lang]["lo"]
                )
            )
        elif v > 0.5:
            out.append(_t(lang, "filmic_sat_pos").format(v=v))
        else:
            out.append(_t(lang, "filmic_sat_neutral").format(v=v))
    if "balance" in params:
        v = float(params["balance"])
        if v != 0:
            out.append(_t(lang, "filmic_balance").format(v=v))
    return out


def _explain_exposure(lang: str, params: dict) -> list[str]:
    out: list[str] = []
    if "exposure" in params:
        ev = float(params["exposure"])
        if abs(ev) > 0.001:
            out.append(
                _t(lang, "exposure_ev").format(
                    ev=ev, dir=_ADJ[lang]["hi"] if abs(ev) >= 0.5 else _ADJ[lang]["lo"]
                )
            )
    if "black" in params:
        b = float(params["black"])
        if b != 0:
            out.append(_t(lang, "exposure_black").format(v=b))
    return out


def _explain_colorbalance(lang: str, params: dict, ref_analysis: dict | None) -> list[str]:
    out: list[str] = []
    if "vibrance" in params and abs(float(params["vibrance"])) > 0.001:
        out.append(_t(lang, "cbr_vibrance").format(v=params["vibrance"]))
    if "contrast" in params and abs(float(params["contrast"])) > 0.001:
        out.append(_t(lang, "cbr_contrast").format(v=params["contrast"]))
    if "chroma_global" in params and abs(float(params["chroma_global"])) > 0.001:
        out.append(_t(lang, "cbr_chroma_global").format(v=params["chroma_global"]))
    if "global_C" in params:
        out.append(_t(lang, "cbr_global_c").format(v=params["global_C"]))
    # Per-zone grading
    for zone in ("shadows", "midtones", "highlights"):
        c_key, h_key = f"{zone}_C", f"{zone}_H"
        if c_key not in params:
            continue
        chroma = float(params[c_key])
        hue = float(params.get(h_key) or 0.0)
        zname = _ZONE_NAME[lang][zone]
        if chroma > 0.001:
            out.append(
                _t(lang, "cbr_zone").format(
                    zone=zname,
                    hue=hue,
                    chroma=chroma,
                    color=_color(lang, hue),
                    action=_ADJ[lang]["applied"],
                )
            )
        else:
            conf = 0.0
            if ref_analysis:
                conf = float(ref_analysis.get(f"{zone}_hue_confidence") or 0.0)
            out.append(_t(lang, "cbr_zone_neutral").format(zone=zname, conf=conf))
    return out


def _explain_curve(_lang: str, _operation: str, params: dict) -> list[str]:
    out: list[str] = []
    preset = params.get("curve_preset")
    if preset and preset != "identity":
        out.append(f"**curve_preset = `{preset}`**: plantilla de curva {preset.replace('_', ' ')}.")
    return out


def _explain_temperature(lang: str, params: dict) -> list[str]:
    """temperature replaces the camera WB — explain the intentional coeffs."""
    out: list[str] = []
    red = float(params.get("red") or 1.0)
    blue = float(params.get("blue") or 1.0)
    green = float(params.get("green") or 1.0)
    preset = int(params.get("preset") or 0)
    if abs(red - 1.0) > 0.05 or abs(blue - 1.0) > 0.05:
        warm = red > 1.15 and blue < 1.05
        cool = blue > 1.15 and red < 1.05
        if warm:
            out.append(_t(lang, "temp_warm").format(red=red, blue=blue))
        elif cool:
            out.append(_t(lang, "temp_cool").format(red=red, blue=blue))
        else:
            out.append(_t(lang, "temp_custom").format(red=red, green=green, blue=blue))
    elif preset == 3:
        out.append(_t(lang, "temp_d65"))
    else:
        out.append(_t(lang, "temp_identity_warn"))
    return out


def _explain_basicadj(lang: str, params: dict) -> list[str]:
    out: list[str] = []
    if "exposure" in params and abs(float(params["exposure"])) > 0.01:
        out.append(_t(lang, "badj_exposure").format(v=params["exposure"]))
    if "black_point" in params and abs(float(params["black_point"])) > 0.001:
        out.append(_t(lang, "badj_black").format(v=params["black_point"]))
    if "contrast" in params and abs(float(params["contrast"])) > 0.01:
        out.append(_t(lang, "badj_contrast").format(v=params["contrast"]))
    if "vibrance" in params and abs(float(params["vibrance"])) > 0.01:
        out.append(_t(lang, "badj_vibrance").format(v=params["vibrance"]))
    if "saturation" in params and abs(float(params["saturation"])) > 0.01:
        out.append(_t(lang, "badj_saturation").format(v=params["saturation"]))
    if "brightness" in params and abs(float(params["brightness"])) > 0.01:
        out.append(_t(lang, "badj_brightness").format(v=params["brightness"]))
    if "hlcompr" in params and float(params["hlcompr"]) > 1.0:
        out.append(_t(lang, "badj_hlcompr").format(v=params["hlcompr"]))
    if "middle_grey" in params and abs(float(params["middle_grey"]) - 18.42) > 0.5:
        out.append(_t(lang, "badj_midgrey").format(v=params["middle_grey"]))
    return out


def _explain_toneequal(lang: str, params: dict) -> list[str]:
    out: list[str] = []
    _BANDS = (
        "noise",
        "ultra_deep_blacks",
        "deep_blacks",
        "blacks",
        "shadows",
        "midtones",
        "highlights",
        "whites",
        "speculars",
    )
    changed = [
        (b, float(params[b])) for b in _BANDS if b in params and abs(float(params[b])) > 0.01
    ]
    if changed:
        parts = ", ".join(f"{b} {v:+.2f}" for b, v in changed)
        out.append(_t(lang, "teq_bands").format(bands=parts))
    if "contrast_boost" in params and abs(float(params["contrast_boost"])) > 0.05:
        out.append(_t(lang, "teq_contrast_boost").format(v=params["contrast_boost"]))
    if "exposure_boost" in params and abs(float(params["exposure_boost"])) > 0.05:
        out.append(_t(lang, "teq_exposure_boost").format(v=params["exposure_boost"]))
    if "feathering" in params and abs(float(params["feathering"]) - 1.0) > 0.01:
        out.append(_t(lang, "teq_feathering").format(v=params["feathering"]))
    if "iterations" in params and int(params["iterations"]) > 1:
        out.append(_t(lang, "teq_iterations").format(v=params["iterations"]))
    if not out:
        out.append(_t(lang, "teq_neutral"))
    return out


def _explain_colorequal(lang: str, params: dict) -> list[str]:
    out: list[str] = []
    _CHANNELS = ("red", "orange", "yellow", "green", "cyan", "blue", "lavender", "magenta")
    for ch in _CHANNELS:
        sk, hk, bk = f"sat_{ch}", f"hue_{ch}", f"bright_{ch}"
        parts: list[str] = []
        if sk in params and abs(float(params[sk]) - 1.0) > 0.03:
            parts.append(_t(lang, "ceq_sat").format(v=params[sk]))
        if hk in params and abs(float(params[hk])) > 1.0:
            parts.append(_t(lang, "ceq_hue").format(v=params[hk]))
        if bk in params and abs(float(params[bk]) - 1.0) > 0.03:
            parts.append(_t(lang, "ceq_bright").format(v=params[bk]))
        if parts:
            out.append(_t(lang, "ceq_channel").format(ch=ch, detail=", ".join(parts)))
    if "hue_shift" in params and abs(float(params["hue_shift"])) > 1.0:
        out.append(_t(lang, "ceq_hue_shift").format(v=params["hue_shift"]))
    if not out:
        out.append(_t(lang, "ceq_neutral"))
    return out


def _explain_colorharmonizer(lang: str, params: dict) -> list[str]:
    out: list[str] = []
    if "rule" in params and int(params["rule"]) != 3:
        out.append(_t(lang, "harm_rule").format(v=params["rule"]))
    if "anchor_hue" in params and abs(float(params["anchor_hue"]) - 0.1) > 0.01:
        out.append(_t(lang, "harm_anchor").format(v=params["anchor_hue"]))
    if "pull_strength" in params and abs(float(params["pull_strength"])) > 0.01:
        out.append(_t(lang, "harm_strength").format(v=params["pull_strength"]))
    if "neutral_protection" in params and abs(float(params["neutral_protection"]) - 0.5) > 0.05:
        out.append(_t(lang, "harm_neutral_prot").format(v=params["neutral_protection"]))
    if "pull_width" in params and abs(float(params["pull_width"]) - 1.0) > 0.05:
        out.append(_t(lang, "harm_width").format(v=params["pull_width"]))
    if "smoothing" in params and abs(float(params["smoothing"])) > 0.01:
        out.append(_t(lang, "harm_smoothing").format(v=params["smoothing"]))
    if not out:
        out.append(_t(lang, "harm_neutral"))
    return out


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def generate_explanation(
    spec: StyleSpec,
    presets: list,
    _analysis: ImageAnalysis | None,
    reference_analysis: dict | None,
    reference_paths: list[Path],
    output_path: Path,
    lang: str = "es",
) -> Path:
    """Write the natural-language explanation document.

    Args:
        spec: Validated StyleSpec.
        presets: Selected base presets.
        analysis: ImageAnalysis of the target image (may be None).
        reference_analysis: Per-zone hue analysis dict from
            ``analyze_reference_hues`` (may be None).
        reference_paths: Paths of the reference images.
        output_path: Destination .md path.
        lang: Document language, ``"es"`` (default) or ``"en"``.

    Returns:
        Path to the written document.
    """
    if lang not in _TEXT:
        lang = "es"
    L = _TEXT[lang]

    lines: list[str] = []
    lines.append(L["title"].format(name=spec.style_name or "Untitled"))  # type: ignore[union-attr]
    lines.append("")
    lines.append(L["auto"].format(date=datetime.now().strftime("%Y-%m-%d %H:%M")))  # type: ignore[union-attr]
    lines.append("")
    if spec.style_description:
        lines.append(L["desc"].format(desc=spec.style_description))  # type: ignore[union-attr]
    else:
        lines.append(L["no_desc"])  # type: ignore[arg-type]
    lines.append("")

    # -- 1. Reference analysis -------------------------------------------
    lines.append(L["s1_title"])  # type: ignore[arg-type]
    lines.append("")
    ref_stats = _analyze_reference_stats([Path(p) for p in (reference_paths or [])])

    if ref_stats:
        lines.append(L["s1_intro"].format(n=len(ref_stats)))  # type: ignore[union-attr]
        lines.append("")
        lines.append(L["s1_table_header"])  # type: ignore[arg-type]
        lines.append(L["s1_table_sep"])  # type: ignore[arg-type]
        for s in ref_stats:
            t = s["tonal"]
            lines.append(
                f"| {s['name']} | {s['mean']:.2f} | {s['std']:.2f} | {s['sat']:.2f} "
                f"| {t[0]:.0%} | {t[1]:.0%} | {t[2]:.0%} | {s['wb']:.2f} |"
            )
        lines.append("")
        lines.append(L["s1_synth"])  # type: ignore[arg-type]
        lines.append("")
        means = [s["mean"] for s in ref_stats]
        stds = [s["std"] for s in ref_stats]
        sats = [s["sat"] for s in ref_stats]
        wbs = [s["wb"] for s in ref_stats]
        lines.append(
            L["s1_tonal"].format(  # type: ignore[union-attr]
                clave=_CLAVE_WORD[lang][_clave(sum(means) / len(means))],
                lo=min(means),
                hi=max(means),
                contrast=_CONTRAST_WORD[lang][_contrast_band(sum(stds) / len(stds))],
            )
        )
        lines.append(
            L["s1_color"].format(  # type: ignore[union-attr]
                wb=_WB_WORD[lang][_wb_band(sum(wbs) / len(wbs))],
                wblo=min(wbs),
                wbhi=max(wbs),
                sat=_SAT_WORD[lang][_sat_band(sum(sats) / len(sats))],
                satlo=min(sats),
                sathi=max(sats),
            )
        )
        # Dominant tonal zone
        avg_tonal = [sum(s["tonal"][i] for s in ref_stats) / len(ref_stats) for i in range(3)]
        dom_idx = max(range(3), key=lambda i: avg_tonal[i])
        dom_word = (
            ("sombras" if dom_idx == 0 else "medios" if dom_idx == 1 else "altas")
            if lang == "es"
            else ("shadows" if dom_idx == 0 else "midtones" if dom_idx == 1 else "highlights")
        )
        lines.append(L["s1_dist"].format(dom=dom_word))  # type: ignore[union-attr]
    else:
        lines.append(L["s1_no_refs"])  # type: ignore[arg-type]
    lines.append("")

    # -- 2. How the references are graded ---------------------------------
    lines.append(L["s2_title"])  # type: ignore[arg-type]
    lines.append("")
    lines.append(L["s2_intro"])  # type: ignore[arg-type]
    lines.append("")
    for zone in ("shadows", "midtones", "highlights"):
        lines.append(L[f"s2_{zone}"])  # type: ignore[arg-type]
        lines.append("")
        lines.append(_zone_line(lang, zone, reference_analysis))
        lines.append("")
    lines.append(L["s2_interp"])  # type: ignore[arg-type]
    lines.append("")
    if reference_analysis:
        modes = [
            reference_analysis.get(f"{z}_hue_mode") for z in ("shadows", "midtones", "highlights")
        ]
        if all(m == "mono" for m in modes):
            hue = reference_analysis.get("shadows_hue") or 0.0
            lines.append(L["s2_interp_mono"].format(color=_color(lang, hue)))  # type: ignore[union-attr]
        elif "bi" in modes:
            z = "shadows" if modes[0] == "bi" else "midtones" if modes[1] == "bi" else "highlights"
            p = float(reference_analysis.get(f"{z}_hue") or 0.0)
            s_sec = float(reference_analysis.get(f"{z}_hue_secondary") or 0.0)
            lines.append(L["s2_interp_bi"].format(c1=_color(lang, p), c2=_color(lang, s_sec)))  # type: ignore[union-attr]
        else:
            lines.append(L["s2_interp_neutral"])  # type: ignore[arg-type]
    else:
        lines.append(L["s2_interp_neutral"])  # type: ignore[arg-type]
    lines.append("")

    # -- 3. Why the preset was generated this way --------------------------
    lines.append(L["s3_title"])  # type: ignore[arg-type]
    lines.append("")
    lines.append(L["s3_intro"])  # type: ignore[arg-type]
    lines.append("")

    for plg in spec.plugins:
        if not plg.enabled:
            continue
        lines.append(L["s3_modules"].format(op=plg.operation))  # type: ignore[union-attr]
        lines.append("")
        if plg.operation == "filmicrgb":
            explains = _explain_filmic(lang, plg.params)
        elif plg.operation == "exposure":
            explains = _explain_exposure(lang, plg.params)
        elif plg.operation == "colorbalancergb":
            explains = _explain_colorbalance(lang, plg.params, reference_analysis)
        elif plg.operation == "temperature":
            explains = _explain_temperature(lang, plg.params)
        elif plg.operation == "basicadj":
            explains = _explain_basicadj(lang, plg.params)
        elif plg.operation == "toneequal":
            explains = _explain_toneequal(lang, plg.params)
        elif plg.operation == "colorequal":
            explains = _explain_colorequal(lang, plg.params)
        elif plg.operation == "colorharmonizer":
            explains = _explain_colorharmonizer(lang, plg.params)
        elif plg.operation in ("tonecurve", "rgbcurve", "colorzones"):
            explains = _explain_curve(lang, plg.operation, plg.params)
        else:
            explains = [f"**{k} = {v}**" for k, v in plg.params.items() if v not in (0, 0.0)]
        if explains:
            lines.extend(explains)
        else:
            lines.append(
                "*(sin cambios relevantes respecto al valor por defecto)*"
                if lang == "es"
                else "*(no relevant changes from default)*"
            )
        lines.append("")

    lines.append(L["s3_presets"])  # type: ignore[arg-type]
    lines.append("")
    if presets:
        lines.append(L["s3_presets_list"].format(n=len(presets)))  # type: ignore[union-attr]
        for p in presets:
            try:
                label = p.file_path.name if p.file_path else ""
            except AttributeError:
                label = ""
            lines.append(f"- **{label or p.name}**")
        lines.append("")
    else:
        lines.append(L["s3_presets_none"])  # type: ignore[arg-type]
        lines.append("")

    lines.append(L["s3_guards"])  # type: ignore[arg-type]
    lines.append("")
    lines.extend(L["s3_guards_body"])
    lines.append("")

    rationale = getattr(spec, "rationale", "") or ""
    if rationale:
        lines.append(L["s3_rationale"])  # type: ignore[arg-type]
        lines.append("")
        lines.append(L["s3_rationale_body"].format(rationale=rationale))  # type: ignore[union-attr]
        lines.append("")

    # -- 4. Expected result ------------------------------------------------
    lines.append(L["s4_title"])  # type: ignore[arg-type]
    lines.append("")
    # Synthesise the expected effect from the active modules
    params_by_op = {plg.operation: plg.params for plg in spec.plugins if plg.enabled}
    filmic = params_by_op.get("filmicrgb", {})
    exposure = params_by_op.get("exposure", {})
    cbr = params_by_op.get("colorbalancergb", {})
    ev = float(exposure.get("exposure") or 0.0)
    filmic_sat = float(filmic.get("saturation") or 0.0)
    has_zone_chroma = any(
        float(cbr.get(f"{z}_C") or 0.0) > 0.001 for z in ("shadows", "midtones", "highlights")
    )
    if ev > 0.05:
        exp_tonal = L["exp_tonal_bright"]
    elif ev < -0.05:
        exp_tonal = L["exp_tonal_dark"]
    else:
        exp_tonal = L["exp_tonal_same"]
    if filmic_sat < -0.5 or float(cbr.get("chroma_global") or 0.0) < -0.01:
        exp_color = L["exp_color_desat"]
    elif filmic_sat > 0.5 or float(cbr.get("vibrance") or 0.0) > 0.1 or has_zone_chroma:
        exp_color = L["exp_color_sat"]
    else:
        exp_color = L["exp_color_neutral"]
    filmic_contrast = float(filmic.get("contrast") or 1.0)
    if filmic_contrast > 1.1:
        exp_finish = L["exp_finish_punchy"] if filmic_contrast >= 1.6 else L["exp_finish_soft"]
    elif filmic_contrast < 0.9:
        exp_finish = L["exp_finish_soft"]
    else:
        exp_finish = L["exp_finish_balanced"]
    lines.append(
        (L["s4_expected"] if isinstance(L["s4_expected"], str) else L["s4_expected"][0]).format(
            exp_tonal=exp_tonal, exp_color=exp_color, exp_finish=exp_finish
        )
    )  # type: ignore[union-attr]
    lines.append("")

    # -- 5. How to use it ---------------------------------------------------
    lines.append(L["s5_title"])  # type: ignore[arg-type]
    lines.append("")
    lines.extend(line.format(name=spec.style_name) for line in L["s5_body"])
    lines.append("")

    # -- 6. Limitations ------------------------------------------------------
    lines.append(L["s6_title"])  # type: ignore[arg-type]
    lines.append("")
    lines.append(L["s6_body"])  # type: ignore[arg-type]
    lines.append("")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path
