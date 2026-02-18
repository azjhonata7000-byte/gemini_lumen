import os
import uvicorn
import google.generativeai as genai
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from datetime import datetime

app = FastAPI()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MONGO_URI = os.getenv("MONGO_URI")

print("GEMINI_API_KEY:", GEMINI_API_KEY)
print("MONGO_URI:", MONGO_URI)

if not GEMINI_API_KEY:
    print("ERRO: GEMINI_API_KEY não carregada")

if not MONGO_URI:
    print("ERRO: MONGO_URI não carregada")

# Só configura se existir
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# Só conecta se existir
if MONGO_URI:
    client = MongoClient(MONGO_URI)
    db = client["lumen_studio"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class MensagemRequest(BaseModel):
    projeto: str
    pasta: str
    chat_id: str
    prompt: str

class EstruturaRequest(BaseModel):
    arvore: dict

# --- 4. ROTAS ---
@app.get("/")
def home():
    return {"status": "Lumen Studio Online com MongoDB 🍃", "db_conectado": db is not None}

@app.get("/estrutura")
def carregar_estrutura():
    try:
        if db is None: raise Exception("Banco não conectado.")
        doc = db.sistema.find_one({"_id": "estrutura_projetos"})
        return doc.get("arvore", {}) if doc else {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/estrutura")
def salvar_estrutura(req: EstruturaRequest):
    try:
        if db is None: raise Exception("Banco não conectado.")
        db.sistema.update_one(
            {"_id": "estrutura_projetos"}, 
            {"$set": {"arvore": req.arvore}}, 
            upsert=True
        )
        return {"status": "sucesso"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/historico/{projeto}/{pasta}/{chat_id}")
def obter_historico(projeto: str, pasta: str, chat_id: str):
    try:
        if db is None: raise Exception("Banco não conectado.")
        caminho_chat = f"{projeto}/{pasta}/{chat_id}"
        
        docs = db.mensagens.find({"chat_id": caminho_chat}).sort("timestamp", 1)
        historico = [{"role": msg["role"], "texto": msg["texto"]} for msg in docs]
        return {"historico": historico}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/enviar_mensagem")
def enviar_mensagem(req: MensagemRequest):
    try:
        if db is None: raise Exception("Banco não conectado.")
        caminho_chat = f"{req.projeto}/{req.pasta}/{req.chat_id}"

        docs = db.mensagens.find({"chat_id": caminho_chat}).sort("timestamp", 1)
        historico_formatado = [{"role": msg["role"], "parts": [msg["texto"]]} for msg in docs]
            
        chat = model.start_chat(history=historico_formatado)
        resposta_gemini = chat.send_message(req.prompt)
        texto_resposta = resposta_gemini.text if resposta_gemini.text else "Sem texto."

        db.mensagens.insert_many([
            {"chat_id": caminho_chat, "role": "user", "texto": req.prompt, "timestamp": datetime.utcnow()},
            {"chat_id": caminho_chat, "role": "model", "texto": texto_resposta, "timestamp": datetime.utcnow()}
        ])
        
        return {"resposta": texto_resposta}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)