from gnomilestone.models import Asignacion, Dependencia, EstadoTablero, Proyecto, Recurso, Tarea


def test_proyecto_valores_por_defecto():
    proyecto = Proyecto(id=1, nombre="Proyecto")
    assert proyecto.descripcion == ""
    assert proyecto.github_repo_owner is None


def test_tarea_valores_por_defecto():
    tarea = Tarea(id=1, proyecto_id=1, titulo="Tarea")
    assert tarea.padre_id is None
    assert tarea.duracion_dias == 1
    assert tarea.porcentaje_completado == 0
    assert tarea.es_hito is False


def test_dependencia_tipo_por_defecto():
    dependencia = Dependencia(id=1, tarea_origen_id=1, tarea_destino_id=2)
    assert dependencia.tipo == "fin_a_inicio"


def test_estado_tablero_campos():
    estado = EstadoTablero(id=1, proyecto_id=1, nombre="Pendiente", orden=0)
    assert estado.color_hex is None


def test_recurso_y_asignacion_campos():
    recurso = Recurso(id=1, proyecto_id=1, nombre="Ana")
    asignacion = Asignacion(id=1, tarea_id=1, recurso_id=recurso.id)
    assert asignacion.porcentaje_dedicacion == 100
