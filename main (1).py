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
# Un cliente solo puede reseñar si su reserva está "completada"
# y no ha reseñado esa estadía antes
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
    existente = resenas.find_one({"reserva_id": reserva_id, "cliente_id": cliente_id})
    if existente:
        raise HTTPException(status_code=409, detail="Ya existe una reseña para esta reserva")

    doc = {
        "hotel_id":     hotel_id,
        "cliente_id":   cliente_id,
        "reserva_id":   reserva_id,
        "calificacion": int(calificacion),
        "texto":        texto,
        "fecha_creacion": datetime.now().isoformat(),
        "fecha_edicion":  None,
        "eliminada":    False,
        "destacada":    False,
        "votos_utilidad": 0,
        "votantes":     [],
        "respuesta_admin": None
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

    resena = resenas.find_one({"reserva_id": reserva_id, "cliente_id": cliente_id, "eliminada": False})
    if not resena:
        raise HTTPException(status_code=404, detail="Reseña no encontrada")

    cambios = {"fecha_edicion": datetime.now().isoformat()}
    if calificacion:
        if not (1 <= int(calificacion) <= 5):
            raise HTTPException(status_code=400, detail="La calificacion debe estar entre 1 y 5")
        cambios["calificacion"] = int(calificacion)
    if texto:
        cambios["texto"] = texto

    resenas.update_one({"reserva_id": reserva_id, "cliente_id": cliente_id}, {"$set": cambios})
    return {"mensaje": "Reseña editada correctamente"}


# ─────────────────────────────────────────
# RF3 – ELIMINAR RESEÑA (cliente)
# ─────────────────────────────────────────
@app.delete("/resenas/{reserva_id}/cliente/{cliente_id}")
def eliminar_resena_cliente(reserva_id: int, cliente_id: int):
    resena = resenas.find_one({"reserva_id": reserva_id, "cliente_id": cliente_id, "eliminada": False})
    if not resena:
        raise HTTPException(status_code=404, detail="Reseña no encontrada")

    resenas.update_one(
        {"reserva_id": reserva_id, "cliente_id": cliente_id},
        {"$set": {"eliminada": True}}
    )
    return {"mensaje": "Reseña eliminada correctamente"}


# ─────────────────────────────────────────
# RF4 – CONSULTAR RESEÑAS DE UN HOTEL
# Ordenadas por fecha o utilidad, paginadas
# ─────────────────────────────────────────
@app.get("/hoteles/{hotel_id}/resenas")
def get_resenas_hotel(hotel_id: int, orden: str = "fecha", pagina: int = 1, por_pagina: int = 10):
    skip = (pagina - 1) * por_pagina

    if orden == "utilidad":
        sort_field = "votos_utilidad"
    else:
        sort_field = "fecha_creacion"

    # Destacadas primero, luego el orden solicitado
    pipeline = [
        {"$match": {"hotel_id": hotel_id, "eliminada": False}},
        {"$sort": {"destacada": -1, sort_field: -1}},
        {"$skip": skip},
        {"$limit": por_pagina},
        {"$project": {
            "_id": 0,
            "reserva_id": 1,
            "cliente_id": 1,
            "calificacion": 1,
            "texto": 1,
            "fecha_creacion": 1,
            "fecha_edicion": 1,
            "votos_utilidad": 1,
            "destacada": 1,
            "respuesta_admin": 1
        }}
    ]

    resultado = list(resenas.aggregate(pipeline))
    total = resenas.count_documents({"hotel_id": hotel_id, "eliminada": False})

    return {
        "total": total,
        "pagina": pagina,
        "por_pagina": por_pagina,
        "resenas": resultado
    }


# ─────────────────────────────────────────
# RF5 – MARCAR RESEÑA COMO ÚTIL
# Un usuario autenticado solo puede votar una vez
# ─────────────────────────────────────────
@app.post("/resenas/{reserva_id}/util")
def marcar_util(reserva_id: int, datos: dict):
    usuario_id = datos.get("usuario_id")
    if not usuario_id:
        raise HTTPException(status_code=400, detail="Se requiere usuario_id")

    resena = resenas.find_one({"reserva_id": reserva_id, "eliminada": False})
    if not resena:
        raise HTTPException(status_code=404, detail="Reseña no encontrada")

    if usuario_id in resena.get("votantes", []):
        raise HTTPException(status_code=409, detail="Ya votaste por esta reseña")

    resenas.update_one(
        {"reserva_id": reserva_id},
        {
            "$inc": {"votos_utilidad": 1},
            "$push": {"votantes": usuario_id}
        }
    )
    return {"mensaje": "Voto registrado correctamente"}


# ─────────────────────────────────────────
# RF6 – HISTORIAL DE RESEÑAS PROPIAS
# ─────────────────────────────────────────
@app.get("/clientes/{cliente_id}/resenas")
def historial_resenas(cliente_id: int, orden: str = "fecha"):
    sort_field = "fecha_creacion" if orden == "fecha" else "hotel_id"

    pipeline = [
        {"$match": {"cliente_id": cliente_id}},
        {"$sort": {sort_field: -1}},
        {"$project": {
            "_id": 0,
            "hotel_id": 1,
            "reserva_id": 1,
            "calificacion": 1,
            "texto": 1,
            "fecha_creacion": 1,
            "eliminada": 1,
            "votos_utilidad": 1,
            "respuesta_admin": 1
        }}
    ]

    resultado = list(resenas.aggregate(pipeline))
    return resultado


# ─────────────────────────────────────────
# RF7 – RESPONDER RESEÑA (admin)
# ─────────────────────────────────────────
@app.put("/resenas/{reserva_id}/respuesta")
def responder_resena(reserva_id: int, datos: dict):
    respuesta = datos.get("respuesta")
    if not respuesta:
        raise HTTPException(status_code=400, detail="Se requiere el campo respuesta")

    resena = resenas.find_one({"reserva_id": reserva_id, "eliminada": False})
    if not resena:
        raise HTTPException(status_code=404, detail="Reseña no encontrada")

    resenas.update_one(
        {"reserva_id": reserva_id},
        {"$set": {
            "respuesta_admin": {
                "texto": respuesta,
                "fecha": datetime.now().isoformat()
            }
        }}
    )
    return {"mensaje": "Respuesta registrada correctamente"}


# ─────────────────────────────────────────
# RF8 – ELIMINAR RESEÑA (admin)
# ─────────────────────────────────────────
@app.delete("/resenas/{reserva_id}/admin")
def eliminar_resena_admin(reserva_id: int):
    resena = resenas.find_one({"reserva_id": reserva_id, "eliminada": False})
    if not resena:
        raise HTTPException(status_code=404, detail="Reseña no encontrada")

    resenas.update_one(
        {"reserva_id": reserva_id},
        {"$set": {"eliminada": True}}
    )
    return {"mensaje": "Reseña eliminada por administrador"}


# ─────────────────────────────────────────
# RF9 – DESTACAR RESEÑA (admin)
# Solo una destacada por hotel a la vez
# ─────────────────────────────────────────
@app.put("/hoteles/{hotel_id}/resenas/{reserva_id}/destacar")
def destacar_resena(hotel_id: int, reserva_id: int):
    resena = resenas.find_one({"reserva_id": reserva_id, "hotel_id": hotel_id, "eliminada": False})
    if not resena:
        raise HTTPException(status_code=404, detail="Reseña no encontrada")

    # Quitar destacado de todas las reseñas del hotel
    resenas.update_many(
        {"hotel_id": hotel_id},
        {"$set": {"destacada": False}}
    )

    # Destacar la seleccionada
    resenas.update_one(
        {"reserva_id": reserva_id},
        {"$set": {"destacada": True}}
    )
    return {"mensaje": "Reseña destacada correctamente"}


# ─────────────────────────────────────────
# RFC1 – TOP 10 HOTELES POR CALIFICACIÓN
# En un período definido
# ─────────────────────────────────────────
@app.get("/consultas/top-hoteles")
def top_hoteles(fecha_inicio: str, fecha_fin: str):
    pipeline = [
        {"$match": {
            "eliminada": False,
            "fecha_creacion": {"$gte": fecha_inicio, "$lte": fecha_fin}
        }},
        {"$group": {
            "_id": "$hotel_id",
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
    pipeline = [
        {"$match": {
            "hotel_id": hotel_id,
            "eliminada": False,
            "fecha_creacion": {
                "$gte": f"{anio}-01-01",
                "$lte": f"{anio}-12-31"
            }
        }},
        {"$group": {
            "_id": {"$substr": ["$fecha_creacion", 0, 7]},  # YYYY-MM
            "calificacion_promedio": {"$avg": "$calificacion"},
            "total_resenas": {"$sum": 1}
        }},
        {"$sort": {"_id": 1}},
        {"$project": {
            "_id": 0,
            "mes": "$_id",
            "calificacion_promedio": {"$round": ["$calificacion_promedio", 2]},
            "total_resenas": 1
        }}
    ]
    return list(resenas.aggregate(pipeline))


# ─────────────────────────────────────────
# RFC3 – PERFIL COMPARATIVO DE HOTELES POR CIUDAD
# ─────────────────────────────────────────
@app.get("/consultas/comparativo-ciudad")
def comparativo_ciudad(ciudad: str):
    # Primero obtener hoteles de esa ciudad desde Oracle via parámetro
    # (los hotel_ids se pasan como query param separados por coma)
    # Ej: /consultas/comparativo-ciudad?ciudad=Bogota&hotel_ids=1,2,3
    pipeline = [
        {"$match": {"eliminada": False}},
        {"$group": {
            "_id": "$hotel_id",
            "calificacion_promedio": {"$avg": "$calificacion"},
            "total_resenas": {"$sum": 1},
            "con_respuesta": {
                "$sum": {"$cond": [{"$ne": ["$respuesta_admin", None]}, 1, 0]}
            },
            "destacadas": {
                "$sum": {"$cond": ["$destacada", 1, 0]}
            }
        }},
        {"$project": {
            "_id": 0,
            "hotel_id": "$_id",
            "calificacion_promedio": {"$round": ["$calificacion_promedio", 2]},
            "total_resenas": 1,
            "porcentaje_con_respuesta": {
                "$round": [
                    {"$multiply": [
                        {"$divide": ["$con_respuesta", "$total_resenas"]}, 100
                    ]}, 1
                ]
            },
            "porcentaje_destacadas": {
                "$round": [
                    {"$multiply": [
                        {"$divide": ["$destacadas", "$total_resenas"]}, 100
                    ]}, 1
                ]
            }
        }},
        {"$sort": {"calificacion_promedio": -1}}
    ]
    return list(resenas.aggregate(pipeline))

