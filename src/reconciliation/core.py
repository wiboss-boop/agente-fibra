"""Lógica de conciliación: cruza altas vs anexos por nº de orden y clasifica discrepancias.

El contratista MASMOVIL certifica por período 21→20 (no por mes natural), así que una alta
de finales de mes se certifica en el anexo del mes siguiente. Para absorber ese desfase se
agrupan todos los anexos disponibles y se cruza por orden. El 'corte' (última fecha realmente
certificada) separa lo RECLAMABLE de lo que aún está PENDIENTE de un anexo futuro.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from collections import defaultdict

from src.reconciliation.extract import order_key, linea_of


@dataclass
class ReconResult:
    reclamables: list[dict]            # pagado al técnico, fecha <= corte, sin certificar
    pendientes: list[dict]            # pagado al técnico, fecha > corte (anexo futuro)
    sin_fecha: list[dict]            # pagado al técnico, sin certificar, sin fecha legible
    certificado_sin_alta: list[dict]  # certificado por contratista, sin alta registrada
    corte: date | None               # corte explícito si se forzó uno global; si no, None
    corte_por_linea: dict            # {linea: última fecha certificada}
    total_altas: int
    total_anexo: int
    coincidentes: int

    @property
    def total_reclamable_eur(self) -> float:
        return sum(a["precio"] or 0 for a in self.reclamables)


def reconcile(altas: list[dict], anexo: list[dict], corte: date | None = None) -> ReconResult:
    """Cruza altas vs anexo por número de orden.

    El corte (última fecha certificada) se calcula POR LÍNEA DE NEGOCIO, porque cada
    contratista cierra distinto: MASMOVIL por ciclo 21→20, ORANGE por mes natural. Una
    alta posterior al corte de SU línea se considera pendiente de un anexo futuro, no
    una discrepancia. Si se pasa `corte` explícito, se aplica igual a todas las líneas.
    Las líneas sin fechas en el anexo (p.ej. ALARMAS) no descartan nada por fecha.
    """
    altas_by_order: dict[str, list[dict]] = defaultdict(list)
    for alta in altas:
        altas_by_order[order_key(alta["orden"])].append(alta)

    anexo_by_order: dict[str, list[dict]] = defaultdict(list)
    for linea in anexo:
        anexo_by_order[order_key(linea["orden"])].append(linea)

    altas_orders = set(altas_by_order)
    anexo_orders = set(anexo_by_order)

    # Corte por línea de negocio = máxima fecha certificada de esa línea
    corte_por_linea: dict[str, date] = {}
    if corte is None:
        for linea in anexo:
            fecha = linea.get("fecha")
            if fecha:
                key = linea_of(linea["orden"])
                if key not in corte_por_linea or fecha > corte_por_linea[key]:
                    corte_por_linea[key] = fecha

    reclamables, pendientes, sin_fecha = [], [], []
    for key in sorted(altas_orders - anexo_orders):
        alta = altas_by_order[key][0]
        fecha = alta.get("fecha")
        corte_linea = corte if corte is not None else corte_por_linea.get(linea_of(alta["orden"]))
        if fecha is None:
            sin_fecha.append(alta)
        elif corte_linea is not None and fecha > corte_linea:
            pendientes.append(alta)
        else:
            reclamables.append(alta)

    reclamables.sort(key=lambda a: (linea_of(a["orden"]), a.get("fecha") or date.min))

    certificado_sin_alta = []
    for key in sorted(anexo_orders - altas_orders):
        linea = anexo_by_order[key][0]
        certificado_sin_alta.append(linea)

    return ReconResult(
        reclamables=reclamables,
        pendientes=pendientes,
        sin_fecha=sin_fecha,
        certificado_sin_alta=certificado_sin_alta,
        corte=corte,
        corte_por_linea=corte_por_linea,
        total_altas=len(altas_orders),
        total_anexo=len(anexo_orders),
        coincidentes=len(altas_orders & anexo_orders),
    )
