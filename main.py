import os
import uvicorn
import google.generativeai as genai
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from datetime import datetime

# -------------------------
# CONFIGURAÇÃO INICIAL
# -------------------------

app = FastAPI()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MONGO_URI = os.getenv("MONGO_URI")

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY não configurada.")

if not MONGO_URI:
    raise RuntimeError("MONGO_URI não configurada.")

# Configura Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

# Conecta Mongo
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = client["lumen_studio"]

# Criar índices (seguro rodar sempre)
db.mensagens.create_index("chat_id")
db.mensagens.create_index([("chat_id", 1), ("timestamp", 1)])

# -------------------------
# CORS
# -------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------
# MODELS
# -------------------------

class MensagemRequest(BaseModel):
    projeto: str
    pasta: str
    chat_id: str
    prompt: str

class EstruturaRequest(BaseModel):
    arvore: dict

# -------------------------
# ROTAS
# -------------------------

@app.get("/")
def home():
    return {
        "status": "Lumen Studio Online 🍃",
        "db_conectado": db is not None
    }

# -------- Estrutura --------

@app.get("/estrutura")
def carregar_estrutura():
    try:
        doc = db.sistema.find_one({"_id": "estrutura_projetos"})
        return doc.get("arvore", {}) if doc else {}
    except PyMongoError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/estrutura")
def salvar_estrutura(req: EstruturaRequest):
    try:
        db.sistema.update_one(
            {"_id": "estrutura_projetos"},
            {"$set": {"arvore": req.arvore}},
            upsert=True
        )
        return {"status": "sucesso"}
    except PyMongoError as e:
        raise HTTPException(status_code=500, detail=str(e))

# -------- Histórico --------

@app.get("/historico/{projeto}/{pasta}/{chat_id}")
def obter_historico(projeto: str, pasta: str, chat_id: str):
    try:
        caminho_chat = f"{projeto}/{pasta}/{chat_id}"

        docs = list(
            db.mensagens
            .find({"chat_id": caminho_chat})
            .sort("timestamp", 1)
        )

        historico = [
            {"role": msg.get("role"), "texto": msg.get("texto")}
            for msg in docs
        ]

        return {"historico": historico}

    except PyMongoError as e:
        raise HTTPException(status_code=500, detail=str(e))

# -------- Chat --------

@app.post("/enviar_mensagem")
def enviar_mensagem(req: MensagemRequest):

    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt vazio.")

    caminho_chat = f"{req.projeto}/{req.pasta}/{req.chat_id}"

    try:
        # 🔥 Limita histórico para evitar estouro de token
        docs = list(
            db.mensagens
            .find({"chat_id": caminho_chat})
            .sort("timestamp", -1)
            .limit(20)
        )

        docs.reverse()

        historico_formatado = [
            {
                "role": msg.get("role"),
                "parts": [msg.get("texto", "")]
            }
            for msg in docs
        ]

        chat = model.start_chat(history=historico_formatado)
        resposta = chat.send_message(req.prompt)

        texto_resposta = getattr(resposta, "text", None)
        if not texto_resposta:
            texto_resposta = "Sem texto retornado pelo modelo."

        timestamp = datetime.utcnow()

        db.mensagens.insert_many([
            {
                "chat_id": caminho_chat,
                "role": "user",
                "texto": req.prompt,
                "timestamp": timestamp
            },
            {
                "chat_id": caminho_chat,
                "role": "model",
                "texto": texto_resposta,
                "timestamp": timestamp
            }
        ])

        return {"resposta": texto_resposta}

    except PyMongoError as mongo_err:
        raise HTTPException(status_code=500, detail=f"Erro MongoDB: {str(mongo_err)}")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro interno: {str(e)}")


# -------------------------
# MAIN
# -------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
