import os
import json
import uvicorn
import firebase_admin
from firebase_admin import credentials, firestore
import google.generativeai as genai
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

# --- 1. CONFIGURAÇÃO DO FIREBASE ---
firebase_json = os.environ.get("FIREBASE_CONFIG")
db = None

if firebase_json:
    try:
        # Limpeza robusta para garantir que o Railway leia o JSON perfeitamente
        firebase_json = firebase_json.strip().strip("'").strip('"')
        cred_dict = json.loads(firebase_json)
        
        if "private_key" in cred_dict:
            key = cred_dict["private_key"]
            key = key.replace("\\\\n", "\n").replace("\\n", "\n")
            cred_dict["private_key"] = key
            
        cred = credentials.Certificate(cred_dict)
        
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)
            
        db = firestore.client()
        print("🔥 Firebase Conectado com Sucesso!")
    except Exception as e:
        print(f"❌ Erro na autenticação do Firebase: {e}")

# --- 2. CONFIGURAÇÃO DO GEMINI ---
# Dica de segurança: coloquei a sua chave fixa aqui para não quebrar o seu teste,
# mas o ideal é colocar isso nas "Variables" do Railway no futuro.
GENAI_API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyDqr0dTxPmEpYe6u-dw8ZCIxWxgNo3vg0o") 
genai.configure(api_key=GENAI_API_KEY)
model = genai.GenerativeModel('gemini-3-flash-preview') # Modelo atualizado e mais rápido

# --- 3. CONFIGURAÇÃO DO FASTAPI (CORS) ---
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 4. MODELOS DE DADOS ---
class MensagemRequest(BaseModel):
    projeto: str
    pasta: str
    chat_id: str
    prompt: str

class EstruturaRequest(BaseModel):
    arvore: dict

# --- 5. ROTAS ---
@app.get("/")
def home():
    return {"status": "Lumen Studio Online no Railway 🚂"}

@app.get("/estrutura")
async def carregar_estrutura():
    try:
        if not db: raise Exception("Banco de dados não conectado.")
        doc = db.collection('sistema').document('estrutura').get()
        if doc.exists:
            return doc.to_dict().get("arvore", {})
        return {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao carregar: {str(e)}")

@app.post("/estrutura")
async def salvar_estrutura(req: EstruturaRequest):
    try:
        if not db: raise Exception("Banco de dados não conectado.")
        db.collection('sistema').document('estrutura').set({"arvore": req.arvore})
        return {"status": "sucesso"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/historico/{projeto}/{pasta}/{chat_id}")
async def obter_historico(projeto: str, pasta: str, chat_id: str):
    try:
        if not db: raise Exception("Banco de dados não conectado.")
        mensagens_ref = db.collection(f'projetos/{projeto}/pastas/{pasta}/conversas/{chat_id}/mensagens')
        docs = mensagens_ref.order_by('timestamp').stream()
        
        historico = [{"role": msg.get("role", "user"), "texto": msg.get("texto", "")} for msg in (doc.to_dict() for doc in docs)]
        return {"historico": historico}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/enviar_mensagem")
async def enviar_mensagem(req: MensagemRequest):
    try:
        if not db: raise Exception("Banco de dados não conectado.")
        mensagens_ref = db.collection(f'projetos/{req.projeto}/pastas/{req.pasta}/conversas/{req.chat_id}/mensagens')
        
        docs = mensagens_ref.order_by('timestamp').stream()
        historico_formatado = [{"role": msg.get("role", "user"), "parts": [msg.get("texto", "")]} for msg in (doc.to_dict() for doc in docs)]
            
        chat = model.start_chat(history=historico_formatado)
        resposta_gemini = chat.send_message(req.prompt)
        texto_resposta = resposta_gemini.text if resposta_gemini.text else "O modelo não retornou texto."

        mensagens_ref.add({"role": "user", "texto": req.prompt, "timestamp": firestore.SERVER_TIMESTAMP})
        mensagens_ref.add({"role": "model", "texto": texto_resposta, "timestamp": firestore.SERVER_TIMESTAMP})
        
        return {"resposta": texto_resposta}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- 6. INICIALIZAÇÃO DO SERVIDOR (DEVE FICAR NO FINAL) ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080)) # O Railway injeta essa porta automaticamente
    uvicorn.run(app, host="0.0.0.0", port=port)