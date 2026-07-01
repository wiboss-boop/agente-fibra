# Conciliación mensual — altas pagadas a técnicos vs anexos del contratista

Responde: **¿las altas que pagamos a los técnicos nos las certificó (pagó) el contratista?**

## Uso

```bash
# Dry-run (solo imprime el resumen):
venv/bin/python3 conciliar.py MAYO

# Escribe la pestaña 'Discrepancias MAYO 2026' en el Sheet del agente:
venv/bin/python3 conciliar.py MAYO --write

# Otro año / corte forzado / rutas explícitas:
venv/bin/python3 conciliar.py MAYO --anio 2026 --corte 2026-05-20
venv/bin/python3 conciliar.py MAYO --altas "/ruta/ALTAS.xlsx" --anexos "/a1.xlsx" "/a2.xlsx"
```

`mes` admite nombre (`MAYO`) o número (`5`). Sin `--altas/--anexos` descubre los archivos
en Google Drive automáticamente.

## Cómo cruza

- **Clave de cruce: número de orden** (normalizado: sin `.0` de floats, sin sufijo add-on
  tipo `_AGILETV`, mayúsculas).
- Resultado: una alta es **RECLAMABLE** si la pagamos al técnico y NO aparece en ningún
  anexo, con fecha ≤ corte de su línea.

## Gotchas del dominio (no obvios)

1. **MASMOVIL certifica por ciclo 21→20**, no por mes natural. Una alta de finales de mes
   se certifica en el anexo del mes siguiente. Por eso se cargan los anexos de DOS carpetas
   (`FACTURACION/<año>/<mes+1>` y `<mes+2>`) y el corte es **por línea de negocio**:
   MASMOVIL cierra el día 20, ORANGE por mes natural.
2. **La carpeta `FACTURACION/<año>/<MES>` contiene los anexos del mes de trabajo ANTERIOR**
   (carpeta MAYO → trabajo de ABRIL).
3. **Las altas posteriores al corte quedan PENDIENTES** (van en un anexo aún no emitido), no
   son discrepancias. Se reportan aparte y no se escriben en la pestaña.
4. **Algunos meses traen las altas de ALARMAS solo como resumen** (totales por categoría, sin
   órdenes itemizadas; p.ej. ABRIL). Esas no se pueden cruzar por orden — quedan fuera del
   cruce sin generar falsos reclamables.
5. **ALARMAS no trae fecha por línea** en el anexo → sus altas sin certificar se marcan
   reclamables sin filtro de fecha; revisar manualmente las de fin de mes.
6. Se ignoran los `.xlsx` de **"Factura Emitida"** en las carpetas de facturación (no son anexos).

## Reautenticación de Google

Si el token caduca/revoca, `auth.py` reautentica solo abriendo el navegador. Si no abre,
usar `scripts/get_token.py` (servidor en `localhost:8765`, imprime la URL para pegar).
