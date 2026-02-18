import firebase_admin
from firebase_admin import credentials, firestore
import google.generativeai as genai
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
import uvicorn
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


import os
import json


# Busca a chave que você configurou no painel da Vercel
# Busca a variável que você colou no painel da Vercel
firebase_json = os.environ.get("FIREBASE_CONFIG")
db = None
if firebase_json:
    try:
        # 1. Limpa espaços e aspas extras das pontas
        firebase_json = firebase_json.strip().strip("'").strip('"')
        
        cred_dict = json.loads(firebase_json)
        
        # 2. TRATAMENTO ULTRA-SEGURO DA CHAVE PRIVADA
        if "private_key" in cred_dict:
            # Remove escapes duplos e garante que \n seja uma quebra de linha real
            key = cred_dict["private_key"]
            key = key.replace("\\\\n", "\n").replace("\\n", "\n")
            cred_dict["private_key"] = key
            
        cred = credentials.Certificate(cred_dict)
        
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)
            
        db = firestore.client()
        print("Firebase Conectado com Sucesso!")
        
    except Exception as e:
        print(f"Erro na autenticação: {e}")

# 2. Configuração do Gemini
# DICA: Embora eu seja o Gemini 3 Flash, no SDK do Google o nome do modelo 
# para desenvolvedores geralmente é 'gemini-1.5-flash' ou 'gemini-1.5-pro'.
# Além disso, evite deixar sua API KEY exposta; use variáveis de ambiente no futuro.
GENAI_API_KEY = "AIzaSyDqr0dTxPmEpYe6u-dw8ZCIxWxgNo3vg0o" 
genai.configure(api_key=GENAI_API_KEY)
model = genai.GenerativeModel('gemini-3-flash-preview')


# O nome TEM que ser 'app' para a Vercel reconhecer automaticamente
app = FastAPI()

@app.get("/")
def home():
    return {"status": "Lumen Studio Online"}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- MODELOS DE DADOS ---
class MensagemRequest(BaseModel):
    projeto: str
    pasta: str
    chat_id: str
    prompt: str

class EstruturaRequest(BaseModel):
    arvore: dict

# --- ROTAS DA BARRA LATERAL (ESTRUTURA) ---
@app.get("/estrutura")
async def carregar_estrutura():
    try:
        doc = db.collection('sistema').document('estrutura').get()
        if doc.exists:
            # Retorna a árvore ou um dict vazio se não existir a chave
            return doc.to_dict().get("arvore", {})
        return {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao carregar: {str(e)}")

@app.post("/estrutura")
async def salvar_estrutura(req: EstruturaRequest):
    try:
        # Forçamos a estrutura a ser um dicionário para o Firestore
        db.collection('sistema').document('estrutura').set({"arvore": req.arvore})
        return {"status": "sucesso"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- ROTA PARA CARREGAR MENSAGENS ANTIGAS ---
@app.get("/historico/{projeto}/{pasta}/{chat_id}")
async def obter_historico(projeto: str, pasta: str, chat_id: str):
    try:
        mensagens_ref = db.collection(f'projetos/{projeto}/pastas/{pasta}/conversas/{chat_id}/mensagens')
        docs = mensagens_ref.order_by('timestamp').stream()
        
        historico = []
        for doc in docs:
            msg = doc.to_dict()
            historico.append({
                "role": msg.get("role", "user"),
                "texto": msg.get("texto", "")
            })
        return {"historico": historico}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- ROTA PARA ENVIAR MENSAGEM ---
@app.post("/enviar_mensagem")
async def enviar_mensagem(req: MensagemRequest):
    try:
        mensagens_ref = db.collection(f'projetos/{req.projeto}/pastas/{req.pasta}/conversas/{req.chat_id}/mensagens')
        
        # Recupera o histórico ordenado para manter o contexto
        docs = mensagens_ref.order_by('timestamp').stream()
        
        historico_formatado = []
        for doc in docs:
            msg = doc.to_dict()
            # O Gemini exige 'role' e 'parts' (uma lista de strings)
            historico_formatado.append({
                "role": msg.get("role", "user"),
                "parts": [msg.get("texto", "")]
            })
            
        # Inicia o chat com o histórico recuperado do Firebase
        chat = model.start_chat(history=historico_formatado)
        resposta_gemini = chat.send_message(req.prompt)
        
        # Garantimos que o texto não seja nulo antes de salvar
        texto_resposta = resposta_gemini.text if resposta_gemini.text else "O modelo não retornou texto."

        # Salva pergunta e resposta simultaneamente
        mensagens_ref.add({
            "role": "user", 
            "texto": req.prompt, 
            "timestamp": firestore.SERVER_TIMESTAMP
        })
        mensagens_ref.add({
            "role": "model", 
            "texto": texto_resposta, 
            "timestamp": firestore.SERVER_TIMESTAMP
        })
        
        return {"resposta": texto_resposta}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))