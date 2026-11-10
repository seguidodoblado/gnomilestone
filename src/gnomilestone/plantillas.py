"""Plantillas con las que se puede empezar una nota de documentación (sin GTK).

Son funciones y no constantes para que los textos se traduzcan con el idioma ya instalado.
"""

from __future__ import annotations

from dataclasses import dataclass

from gnomilestone.i18n import _


@dataclass(frozen=True)
class Plantilla:
    clave: str
    nombre: str
    descripcion: str
    titulo: str  # título inicial de la nota
    contenido: str  # Markdown inicial


def _plantillas_vision_general() -> list[Plantilla]:
    """Documentos habituales de contexto de un repositorio (README, conducta, etc.)."""
    return [
        Plantilla(
            "readme",
            _("README"),
            _("Presentación del proyecto: qué es, instalación y uso"),
            _("README"),
            _(
                "## Descripción\nQué es el proyecto y qué problema resuelve.\n\n"
                "## Características\n- \n- \n\n"
                "## Instalación\n```bash\n\n```\n\n"
                "## Uso\nCómo empezar a usarlo.\n\n"
                "## Contribuir y licencia\nEnlaces a «Contribuyendo» y «Licencia».\n"
            ),
        ),
        Plantilla(
            "codigo_conducta",
            _("Código de conducta"),
            _("Compromiso, comportamiento esperado y cómo informar"),
            _("Código de conducta"),
            _(
                "## Nuestro compromiso\nQueremos una comunidad abierta, respetuosa y libre de acoso.\n\n"
                "## Comportamiento esperado\n- Tratar a las demás personas con respeto.\n"
                "- Aceptar las críticas constructivas.\n\n"
                "## Comportamiento inaceptable\n- Acoso, insultos o discriminación.\n\n"
                "## Cómo informar\nContacto al que dirigir los incidentes.\n"
            ),
        ),
        Plantilla(
            "contribuyendo",
            _("Contribuyendo"),
            _("Cómo proponer cambios: entorno, pruebas y revisión"),
            _("Contribuyendo"),
            _(
                "## Antes de empezar\nAbre una incidencia para comentar el cambio.\n\n"
                "## Entorno de desarrollo\nCómo preparar el proyecto en local.\n\n"
                "## Pruebas y estilo\n- [ ] Los tests pasan\n- [ ] El linter no avisa\n\n"
                "## Enviar el cambio\nRama, mensaje de commit y petición de integración.\n"
            ),
        ),
        Plantilla(
            "licencia",
            _("Licencia"),
            _("Licencia del proyecto y su alcance"),
            _("Licencia"),
            _(
                "## Licencia\nEste proyecto se distribuye bajo la licencia **GPL-3.0 o posterior**.\n\n"
                "## Qué permite\n- Usar, estudiar y modificar el software.\n"
                "- Redistribuirlo, con las mismas condiciones.\n\n"
                "## Terceros\nDependencias y recursos con licencia propia.\n"
            ),
        ),
        Plantilla(
            "seguridad",
            _("Seguridad"),
            _("Versiones con soporte y cómo informar de una vulnerabilidad"),
            _("Seguridad"),
            _(
                "## Versiones con soporte\n| Versión | Soporte |\n| --- | --- |\n| última | sí |\n\n"
                "## Cómo informar de una vulnerabilidad\n"
                "No abras una incidencia pública: escribe al contacto indicado aquí.\n\n"
                "## Qué esperar\nPlazo de respuesta y proceso de corrección.\n"
            ),
        ),
    ]


def _plantillas_especificaciones() -> list[Plantilla]:
    """Especificaciones: la genérica y una por cada tipo habitual de subsección."""
    return [
        Plantilla(
            "especificacion",
            _("Especificación"),
            _("Objetivo, requisitos y criterios de aceptación"),
            _("Especificación: "),
            _(
                "## Objetivo\nQué debe conseguir.\n\n"
                "## Requisitos\n- [ ] \n- [ ] \n\n"
                "## Criterios de aceptación\n- \n\n"
                "## Fuera de alcance\n- \n"
            ),
        ),
        Plantilla(
            "funcionalidad",
            _("Funcionalidad"),
            _("Historia de usuario con flujo y criterios de aceptación"),
            _("Funcionalidad: "),
            _(
                "## Historia\nComo [persona], quiero [objetivo] para [beneficio].\n\n"
                "## Flujo\n1. \n2. \n\n"
                "## Criterios de aceptación\n- [ ] \n\n"
                "## Casos límite\n- \n"
            ),
        ),
        Plantilla(
            "modelo_datos",
            _("Modelo de datos"),
            _("Entidades, atributos, relaciones y reglas de integridad"),
            _("Modelo de datos: "),
            _(
                "## Entidades\n| Entidad | Descripción |\n| --- | --- |\n| | |\n\n"
                "## Atributos y relaciones\n- \n\n"
                "## Reglas de integridad\n- \n\n"
                "## Migraciones\nCómo evoluciona el esquema.\n"
            ),
        ),
        Plantilla(
            "datos_usuario",
            _("Datos de usuario"),
            _("Qué se guarda del usuario, dónde y con qué privacidad"),
            _("Datos de usuario: "),
            _(
                "## Datos que se guardan\n- \n\n"
                "## Dónde se almacenan\n- \n\n"
                "## Privacidad\nQué se envía a terceros y qué no.\n\n"
                "## Eliminación\nCómo puede borrarlos el usuario.\n"
            ),
        ),
        Plantilla(
            "interfaz",
            _("Interfaz"),
            _("Pantallas, navegación, usabilidad y accesibilidad"),
            _("Interfaz: "),
            _(
                "## Pantallas\n- \n\n"
                "## Navegación\nCómo se pasa de una a otra.\n\n"
                "## Criterios de usabilidad\n- \n\n"
                "## Accesibilidad\nTeclado, contraste y lectores de pantalla.\n"
            ),
        ),
        Plantilla(
            "integracion",
            _("Integración externa"),
            _("Servicio externo, datos intercambiados y manejo de errores"),
            _("Integración: "),
            _(
                "## Servicio\nQué servicio es y para qué se usa.\n\n"
                "## Autenticación\n- \n\n"
                "## Datos intercambiados\n| Dirección | Dato |\n| --- | --- |\n| | |\n\n"
                "## Errores y límites\nLímites de uso y reintentos.\n"
            ),
        ),
    ]


def _plantillas_arquitectura() -> list[Plantilla]:
    """Arquitectura: el componente y las notas habituales de diseño, pila y entrega."""
    return [
        Plantilla(
            "componente",
            _("Componente"),
            _("Responsabilidad, interfaz y dependencias"),
            _("Componente: "),
            _(
                "## Responsabilidad\nQué hace y qué no.\n\n"
                "## Interfaz pública\n- \n\n"
                "## Dependencias\n- \n\n"
                "## Notas de diseño\n"
            ),
        ),
        Plantilla(
            "capas",
            _("Capas"),
            _("Capas del sistema y sus reglas de dependencia"),
            _("Capas"),
            _(
                "## Visión general\nCómo se organiza el sistema en capas.\n\n"
                "## Capas\n| Capa | Responsabilidad | Ubicación |\n| --- | --- | --- |\n| | | |\n\n"
                "## Reglas de dependencia\n- Cada capa solo depende de la inferior.\n\n"
                "## Excepciones\n- \n"
            ),
        ),
        Plantilla(
            "estructura",
            _("Estructura del proyecto"),
            _("Árbol de carpetas y qué contiene cada una"),
            _("Estructura del proyecto"),
            _(
                "## Árbol de directorios\n```text\nsrc/\ntests/\n```\n\n"
                "## Qué contiene cada carpeta\n- `src/`: \n- `tests/`: \n\n"
                "## Convenciones\nDónde va un fichero nuevo y cómo se nombra.\n"
            ),
        ),
        Plantilla(
            "pila",
            _("Pila tecnológica"),
            _("Lenguajes, bibliotecas y herramientas, con su motivo"),
            _("Pila tecnológica"),
            _(
                "## Lenguajes y plataformas\n- \n\n"
                "## Bibliotecas principales\n| Biblioteca | Versión | Para qué |\n| --- | --- | --- |\n| | | |\n\n"
                "## Herramientas de desarrollo\n- \n\n"
                "## Motivos de la elección\nPor qué esta pila y no otra.\n"
            ),
        ),
        Plantilla(
            "empaquetado",
            _("Empaquetado"),
            _("Cómo se construye y se distribuye el software"),
            _("Empaquetado"),
            _(
                "## Formatos de distribución\n- \n\n"
                "## Construcción\n```bash\n\n```\n\n"
                "## Versionado\nEsquema de versiones y etiquetas.\n\n"
                "## Instalación\nCómo lo instala quien lo usa.\n"
            ),
        ),
        Plantilla(
            "pruebas",
            _("Estrategia de pruebas"),
            _("Qué se prueba, con qué herramientas y qué debe pasar"),
            _("Pruebas"),
            _(
                "## Qué se prueba\n- [ ] Lógica de negocio\n- [ ] Interfaz\n\n"
                "## Herramientas\n- \n\n"
                "## Cómo ejecutarlas\n```bash\n\n```\n\n"
                "## Criterios para integrar\n- Los tests pasan.\n- El linter no avisa.\n"
            ),
        ),
        Plantilla(
            "integracion_continua",
            _("Integración continua"),
            _("Comprobaciones automáticas en cada cambio"),
            _("Integración continua"),
            _(
                "## Cuándo se ejecuta\nEn cada push y pull request.\n\n"
                "## Pasos\n1. Instalar dependencias\n2. Linter\n3. Tests\n\n"
                "## Fichero del flujo\n`.github/workflows/ci.yml`\n\n"
                "## Si falla\nQué comprobar primero.\n"
            ),
        ),
        Plantilla(
            "despliegue_continuo",
            _("Despliegue continuo"),
            _("Cómo se publica automáticamente una versión"),
            _("Despliegue continuo"),
            _(
                "## Disparador\nEtiqueta `vX.Y.Z`.\n\n"
                "## Pasos\n1. Construir\n2. Publicar\n3. Verificar\n\n"
                "## Fichero del flujo\n`.github/workflows/cd.yml`\n\n"
                "## Reversión\nCómo deshacer una publicación errónea.\n"
            ),
        ),
    ]


def plantillas_para(seccion: str) -> list[Plantilla]:
    """Plantillas disponibles en una sección; la nota en blanco va siempre primera."""
    plantillas = [Plantilla("en_blanco", _("Nota en blanco"), _("Empezar desde cero"), "", "")]
    if seccion == "vision_general":
        plantillas.extend(_plantillas_vision_general())
    if seccion == "decisiones_tecnicas":
        plantillas.append(
            Plantilla(
                "adr",
                _("Decisión técnica (ADR)"),
                _("Contexto, decisión, alternativas y consecuencias"),
                _("Decisión: "),
                _(
                    "## Contexto\n¿Qué problema o necesidad motiva la decisión?\n\n"
                    "## Decisión\nQué se ha decidido y por qué.\n\n"
                    "## Alternativas consideradas\n- Alternativa A:\n- Alternativa B:\n\n"
                    "## Consecuencias\n- Positivas:\n- Negativas:\n"
                ),
            )
        )
    if seccion == "especificaciones":
        plantillas.extend(_plantillas_especificaciones())
    if seccion == "arquitectura":
        plantillas.extend(_plantillas_arquitectura())
    return plantillas
