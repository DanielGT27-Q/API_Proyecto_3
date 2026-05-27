from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from datetime import datetime
from typing import Optional
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Dann-Alpes Reviews API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

client = MongoClient(os.environ["MONGODB_URI"])
db = client["ISIS2304E01202610"]

resenas = db["resenas"]

# ─────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────
@app.get("/")
def inicio():
    return {"estado": "Dann-Alpes API funcionando correctamente"}


# ─────────────────────────────────────────
# RF1 – CREAR RESEÑA
# ─────────────────────────────────────────
@app.post("/hoteles/{hotel_id}/resenas")
def crear_resena(hotel_id: int, datos: dict):
    reserva_id  = datos.get("reserva_id")
    cliente_id  = datos.get("cliente_id")
    calificacion = datos.get("calificacion")
    texto       = datos.get("texto")

    if not all([reserva_id, cliente_id, calificacion, texto]):
        raise HTTPException(status_code=400, detail="Faltan campos obligatorios: reserva_id, cliente_id, calificacion, texto")

    if not (1 <= int(calificacion) <= 5):
        raise HTTPException(status_code=400, detail="La calificacion debe estar entre 1 y 5")

    # Verificar que no exista ya una reseña para esa reserva
    existente = resenas.find_one({"id_reserva": reserva_id, "id_cliente": cliente_id})
    if existente:
        raise HTTPException(status_code=409, detail="Ya existe una reseña para esta reserva")

    doc = {
        "id_hotel": hotel_id,
        "id_cliente": cliente_id,
        "id_reserva": reserva_id,
        "calificación": int(calificacion),
        "texto": texto,
        "fecha_creacion": datetime.now(),
        "fecha_edicion": None,
        "estado": "publicada",
        "destacada": False,
        "votos_util": 0,
        "votantes": [],
        "respuesta": None
    }

    resenas.insert_one(doc)
    return {"mensaje": "Reseña creada correctamente"}


# ─────────────────────────────────────────
# RF2 – EDITAR RESEÑA
# ─────────────────────────────────────────
@app.put("/resenas/{reserva_id}")
def editar_resena(reserva_id: int, datos: dict):
    cliente_id  = datos.get("cliente_id")
    calificacion = datos.get("calificacion")
    texto       = datos.get("texto")

    resena = resenas.find_one({"id_reserva": reserva_id, "id_cliente": cliente_id, "estado": "publicada"})
    if not resena:
        raise HTTPException(status_code=404, detail="Reseña no encontrada")

    cambios = {"fecha_edicion": datetime.now()}
    if calificacion:
        if not (1 <= int(calificacion) <= 5):
            raise HTTPException(status_code=400, detail="La calificacion debe estar entre 1 y 5")
        cambios["calificación"] = int(calificacion)
    if texto:
        cambios["texto"] = texto

    resenas.update_one({"id_reserva": reserva_id, "id_cliente": cliente_id}, {"$set": cambios})
    return {"mensaje": "Reseña editada correctamente"}


# ─────────────────────────────────────────
# RF3 – ELIMINAR RESEÑA (cliente)
# ─────────────────────────────────────────
@app.delete("/resenas/{reserva_id}/cliente/{cliente_id}")
def eliminar_resena_cliente(reserva_id: int, cliente_id: int):
    resena = resenas.find_one({"id_reserva": reserva_id, "id_cliente": cliente_id, "estado": "publicada"})
    if not resena:
        raise HTTPException(status_code=404, detail="Reseña no encontrada")

    resenas.update_one(
        {"id_reserva": reserva_id, "id_cliente": cliente_id},
        {"$set": {"estado": "eliminada"}}
    )
    return {"mensaje": "Reseña eliminada correctamente"}


# ─────────────────────────────────────────
# RF4 – CONSULTAR RESEÑAS DE UN HOTEL
# ─────────────────────────────────────────
@app.get("/hoteles/{hotel_id}/resenas")
def get_resenas_hotel(hotel_id: int, orden: str = "fecha", pagina: int = 1, por_pagina: int = 10):
    skip = (pagina - 1) * por_pagina

    if orden == "utilidad":
        sort_field = "votos_util"
    else:
        sort_field = "fecha_creacion"

    pipeline = [
        {"$match": {"id_hotel": hotel_id, "estado": "publicada"}},
        {"$sort": {"destacada": -1, sort_field: -1}},
        {"$skip": skip},
        {"$limit": por_pagina},
        {"$project": {
            "_id": 0,
            "id_reserva": 1,
            "id_cliente": 1,
            "calificación": 1,
            "texto": 1,
            "fecha_creacion": 1,
            "fecha_edicion": 1,
            "votos_util": 1,
            "destacada": 1,
            "respuesta": 1
        }}
    ]

    resultado = list(resenas.aggregate(pipeline))
    total = resenas.count_documents({"id_hotel": hotel_id, "estado": "publicada"})

    resenas_formateadas = []
    for r in resultado:
        resenas_formateadas.append({
            "reserva_id": r.get("id_reserva"),
            "cliente_id": r.get("id_cliente"),
            "calificacion": r.get("calificación"),
            "texto": r.get("texto"),
            "fecha_creacion": r.get("fecha_creacion"),
            "fecha_edicion": r.get("fecha_edicion"),
            "votos_utilidad": r.get("votos_util", 0),
            "destacada": r.get("destacada", False),
            "respuesta_admin": r.get("respuesta")
        })

    return {
        "total": total,
        "pagina": pagina,
        "por_pagina": por_pagina,
        "resenas": resenas_formateadas
    }


# ─────────────────────────────────────────
# RF5 – MARCAR RESEÑA COMO ÚTIL
# ─────────────────────────────────────────
@app.post("/resenas/{reserva_id}/util")
def marcar_util(reserva_id: int, datos: dict):
    usuario_id = datos.get("usuario_id")
    if not usuario_id:
        raise HTTPException(status_code=400, detail="Se requiere usuario_id")

    resena = resenas.find_one({"id_reserva": reserva_id, "estado": "publicada"})
    if not resena:
        raise HTTPException(status_code=404, detail="Reseña no encontrada")

    if usuario_id in resena.get("votantes", []):
        raise HTTPException(status_code=409, detail="Ya votaste por esta reseña")

    resenas.update_one(
        {"id_reserva": reserva_id},
        {
            "$inc": {"votos_util": 1},
            "$push": {"votantes": usuario_id}
        }
    )
    return {"mensaje": "Voto registrado correctamente"}


# ─────────────────────────────────────────
# RF6 – HISTORIAL DE RESEÑAS PROPIAS
# ─────────────────────────────────────────
@app.get("/clientes/{cliente_id}/resenas")
def historial_resenas(cliente_id: int, orden: str = "fecha"):
    if orden == "fecha":
        sort_field = "fecha_creacion"
    else:
        sort_field = "id_hotel"

    pipeline = [
        {"$match": {"id_cliente": cliente_id}},
        {"$sort": {sort_field: -1}},
        {"$project": {
            "_id": 0,
            "id_hotel": 1,
            "id_reserva": 1,
            "calificación": 1,
            "texto": 1,
            "fecha_creacion": 1,
            "estado": 1,
            "votos_util": 1,
            "respuesta": 1
        }}
    ]

    resultado = list(resenas.aggregate(pipeline))
    
    resenas_formateadas = []
    for r in resultado:
        resenas_formateadas.append({
            "hotel_id": r.get("id_hotel"),
            "reserva_id": r.get("id_reserva"),
            "calificacion": r.get("calificación"),
            "texto": r.get("texto"),
            "fecha_creacion": r.get("fecha_creacion"),
            "eliminada": r.get("estado") == "eliminada",
            "votos_utilidad": r.get("votos_util", 0),
            "respuesta_admin": r.get("respuesta")
        })
    
    return resenas_formateadas


# ─────────────────────────────────────────
# RF7 – RESPONDER RESEÑA (admin)
# ─────────────────────────────────────────
@app.put("/resenas/{reserva_id}/respuesta")
def responder_resena(reserva_id: int, datos: dict):
    respuesta = datos.get("respuesta")
    if not respuesta:
        raise HTTPException(status_code=400, detail="Se requiere el campo respuesta")

    resena = resenas.find_one({"id_reserva": reserva_id, "estado": "publicada"})
    if not resena:
        raise HTTPException(status_code=404, detail="Reseña no encontrada")

    resenas.update_one(
        {"id_reserva": reserva_id},
        {"$set": {
            "respuesta": {
                "texto": respuesta,
                "fecha": datetime.now()
            }
        }}
    )
    return {"mensaje": "Respuesta registrada correctamente"}


# ─────────────────────────────────────────
# RF8 – ELIMINAR RESEÑA (admin)
# ─────────────────────────────────────────
@app.delete("/resenas/{reserva_id}/admin")
def eliminar_resena_admin(reserva_id: int):
    resena = resenas.find_one({"id_reserva": reserva_id, "estado": "publicada"})
    if not resena:
        raise HTTPException(status_code=404, detail="Reseña no encontrada")

    resenas.update_one(
        {"id_reserva": reserva_id},
        {"$set": {"estado": "eliminada"}}
    )
    return {"mensaje": "Reseña eliminada por administrador"}


# ─────────────────────────────────────────
# RF9 – DESTACAR RESEÑA (admin)
# ─────────────────────────────────────────
@app.put("/hoteles/{hotel_id}/resenas/{reserva_id}/destacar")
def destacar_resena(hotel_id: int, reserva_id: int):
    resena = resenas.find_one({"id_reserva": reserva_id, "id_hotel": hotel_id, "estado": "publicada"})
    if not resena:
        raise HTTPException(status_code=404, detail="Reseña no encontrada")

    # Quitar destacado de todas las reseñas del hotel
    resenas.update_many(
        {"id_hotel": hotel_id},
        {"$set": {"destacada": False}}
    )

    # Destacar la seleccionada
    resenas.update_one(
        {"id_reserva": reserva_id},
        {"$set": {"destacada": True}}
    )
    return {"mensaje": "Reseña destacada correctamente"}


# ─────────────────────────────────────────
# RFC1 – TOP 10 HOTELES POR CALIFICACIÓN
# ─────────────────────────────────────────
@app.get("/consultas/top-hoteles")
def top_hoteles(fecha_inicio: str, fecha_fin: str):
    try:
        fecha_inicio_dt = datetime.strptime(fecha_inicio, "%Y-%m-%d")
        fecha_fin_dt = datetime.strptime(fecha_fin, "%Y-%m-%d")
    except:
        raise HTTPException(status_code=400, detail="Formato de fecha debe ser YYYY-MM-DD")
    
    pipeline = [
        {"$match": {
            "estado": "publicada",
            "fecha_creacion": {"$gte": fecha_inicio_dt, "$lte": fecha_fin_dt}
        }},
        {"$group": {
            "_id": "$id_hotel",
            "calificacion_promedio": {"$avg": "$calificacion"},
            "total_resenas": {"$sum": 1}
        }},
        {"$sort": {"calificacion_promedio": -1}},
        {"$limit": 10},
        {"$project": {
            "_id": 0,
            "hotel_id": "$_id",
            "calificacion_promedio": {"$round": ["$calificacion_promedio", 2]},
            "total_resenas": 1
        }}
    ]
    return list(resenas.aggregate(pipeline))


# ─────────────────────────────────────────
# RFC2 – EVOLUCIÓN DE REPUTACIÓN MES A MES
# ─────────────────────────────────────────
@app.get("/hoteles/{hotel_id}/reputacion")
def evolucion_reputacion(hotel_id: int, anio: int):
    start_date = datetime(anio, 1, 1)
    end_date = datetime(anio, 12, 31, 23, 59, 59)
    
    pipeline = [
        {"$match": {
            "id_hotel": hotel_id,
            "estado": "publicada",
            "fecha_creacion": {
                "$gte": start_date,
                "$lte": end_date
            }
        }},
        {"$group": {
            "_id": {
                "year": {"$year": "$fecha_creacion"},
                "month": {"$month": "$fecha_creacion"}
            },
            "calificacion_promedio": {"$avg": "$calificacion"},
            "total_resenas": {"$sum": 1}
        }},
        {"$sort": {"_id.year": 1, "_id.month": 1}},
        {"$project": {
            "_id": 0,
            "mes": {
                "$concat": [
                    {"$toString": "$_id.year"},
                    "-",
                    {"$cond": [{"$lt": ["$_id.month", 10]}, {"$concat": ["0", {"$toString": "$_id.month"}]}, {"$toString": "$_id.month"}]}
                ]
            },
            "calificacion_promedio": {"$round": ["$calificacion_promedio", 2]},
            "total_resenas": 1
        }}
    ]
    
    resultado = list(resenas.aggregate(pipeline))
    return resultado

# ─────────────────────────────────────────
# RFC3 – PERFIL COMPARATIVO DE HOTELES POR CIUDAD
# ─────────────────────────────────────────

@app.get("/hoteles/por-ciudad")
def hoteles_por_ciudad(ciudad: str):
    # Conexión a Oracle
    import oracledb
    
    conn = oracledb.connect(
        user=os.environ["ORACLE_USER"],
        password=os.environ["ORACLE_PASSWORD"],
        dsn=os.environ["ORACLE_DSN"]
    )
    
    cursor = conn.cursor()
    cursor.execute("SELECT HOTEL_ID FROM HOTELES_CIUDAD WHERE CIUDAD = :ciudad", {"ciudad": ciudad})
    hoteles = [row[0] for row in cursor.fetchall()]
    
    cursor.close()
    conn.close()
    
    return {"hoteles": hoteles}