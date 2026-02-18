import os
import uvicorn
import google.generativeai as genai
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from datetime import datetime

app = FastAPI()

# --- 1. CONFIGURAÇÃO DO MONGODB ---
MONGO_URI = os.environ.get("MONGO_URI")


if MONGO_URI:
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        db = client["lumen_studio"]
        client.admin.command('ping')
        print("🍃 MongoDB Conectado com Sucesso!")
    except Exception as e:
        print(f"❌ Erro na conexão com MongoDB: {e}")
else:
    print("⚠️ MONGO_URI não encontrada nas variáveis de ambiente.")

# --- 2. CONFIGURAÇÃO DO GEMINI ---
GENAI_API_KEY = os.environ.get("GEMINI_API_KEY") 
if GENAI_API_KEY:
    genai.configure(api_key=GENAI_API_KEY)
model = genai.GenerativeModel('gemini-3-flash-preview')

# --- 3. FASTAPI ---



@app.get("/debug-env")
def debug_env():
    import os
    return {
        "gemini_is_none": os.getenv("GEMINI_API_KEY") is None,
        "mongo_is_none": os.getenv("MONGO_URI") is None,
        "mongo_length": len(os.getenv("MONGO_URI") or "")
    }

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