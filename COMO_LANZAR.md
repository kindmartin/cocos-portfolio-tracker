# 🚀 COMO LANZAR EL PORTAL — Portfolio Manager

## OPCIÓN 1: QUICKSTART (Recomendado para Principiantes)

```bash
cd E:\Portfolio Manager
python QUICKSTART.py
```

✅ **Verificación automática** del sistema  
✅ **Menú interactivo** (7 opciones)  
✅ **Setup completo** en primera ejecución  

---

## OPCIÓN 2: LAUNCHER MAESTRO (Recomendado para Usuarios Avanzados)

```bash
cd E:\Portfolio Manager\code
python launcher_main.py
```

✅ **Menú maestro** con todas las operaciones  
✅ **Submenús** para cada componente  
✅ **Herramientas avanzadas** (reset, export, logs, cleanup)  

---

## OPCIÓN 3: LAUNCHER DEL DASHBOARD

```bash
cd E:\Portfolio Manager\code
python launcher_dashboard.py
```

✅ **Específico para el dashboard**  
✅ **Opciones de puerto y navegador**  
✅ **Información de la BD**  

---

## OPCIÓN 4: LANZAMIENTO DIRECTO

### Dashboard
```bash
cd E:\Portfolio Manager\code
python portfolio_dashboard.py
```
- Puerto 8050 (default)  
- Abre navegador automáticamente  

**Con opciones:**
```bash
python portfolio_dashboard.py --port 8080           # Puerto custom
python portfolio_dashboard.py --no-browser          # Sin navegador
python portfolio_dashboard.py --port 8080 --no-browser
```

### ETL Manual
```bash
cd E:\Portfolio Manager\code
python etl.py                    # Todo
python etl.py --snapshots        # Solo snapshots
python etl.py --transactions     # Solo transactions
python etl.py --force            # Reprocesar todo
python etl.py --reset            # Limpiar BD
```

### Monitor Automático
```bash
python ingest_monitor.py                  # Monitoreo infinito
python ingest_monitor.py --once           # Una sola ejecución
python ingest_monitor.py --interval 60    # Intervalo custom (segundos)
```

### API + UI Web
```bash
python ingest_api.py                      # Inicia en puerto 5000
```
- URL: http://localhost:5000/api/ingest/status
- UI: http://localhost:5000/ingest_ui.html

---

## 📋 FLUJO TÍPICO

### Primera Vez:
```
1. python QUICKSTART.py
2. Selecciona opción 6: "Setup Completo"
3. Selecciona opción 1: "Lanzar Portal"
```

### Uso Regular:
```
1. Copia CSVs a: E:\Portfolio Manager\csv for ingest\
2. Selecciona opción 2 en QUICKSTART: "Cargar CSVs (ETL Manual)"
   O
   Usa opción 3: "Monitorear" para vigilancia automática
3. El Portal se actualiza automáticamente
```

---

## 🔧 TROUBLESHOOTING

### ❌ "Port 8050 already in use"
```bash
# Puerto 8050 ocupado, usa otro
python portfolio_dashboard.py --port 8080
```

### ❌ "Module not found" / "No module named..."
```bash
cd E:\Portfolio Manager\code
pip install -r requirements.txt
```

### ❌ "DuckDB not found"
La BD no existe todavía. Ejecutá setup:
```bash
python QUICKSTART.py
Opción 6: Setup Completo
```

### ❌ "No files in 'csv for ingest/'"
Copia tus CSVs a: `E:\Portfolio Manager\csv for ingest\`

---

## 📚 DOCUMENTACIÓN COMPLETA
Ver: `E:\Portfolio Manager\docs\README.md`
