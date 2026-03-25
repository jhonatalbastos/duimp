import streamlit as st
import requests
import tempfile
import os
import base64
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.primitives import serialization
import pandas as pd
from datetime import datetime

# --- CONFIGURAÇÕES DE ACESSO (PROTEGIDAS) ---
# Os códigos fornecidos foram embutidos diretamente para evitar exposição na interface
CLIENT_ID_SEC = "noQXPhAOi4Vc1J5Z-XAPCS9FmodtME5p"
CLIENT_SECRET_SEC = "ruV4-tybNVCG9g_-tjcVg3ifE--J1sBK"

# Configuração da Página do Streamlit
st.set_page_config(
    page_title="Siscomex Gateway - DUIMP",
    page_icon="🚢",
    layout="wide"
)

# Estilização CSS
st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .stMetric { background-color: #ffffff; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    </style>
    """, unsafe_allow_html=True)

def extrair_pfx(pfx_data, password):
    """Extrai certificado e chave privada para mTLS."""
    try:
        private_key, certificate, _ = pkcs12.load_key_and_certificates(
            pfx_data,
            password.encode() if password else None
        )
        key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        cert_pem = certificate.public_bytes(encoding=serialization.Encoding.PEM)
        return cert_pem, key_pem
    except Exception as e:
        raise Exception(f"Erro no Certificado: Verifique a senha. ({str(e)})")

def obter_access_token(ambiente):
    """Troca Client ID/Secret por um Access Token (OAUTH2)."""
    url = "https://portalunico.siscomex.gov.br/portal/api/autenticacao/token"
    if ambiente == "Treinamento":
        url = "https://val.portalunico.siscomex.gov.br/portal/api/autenticacao/token"
    
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": "Basic " + base64.b64encode(f"{CLIENT_ID_SEC}:{CLIENT_SECRET_SEC}".encode()).decode()
    }
    
    try:
        response = requests.post(url, data={"grant_type": "client_credentials"}, headers=headers, timeout=15)
        if response.status_code == 200:
            return response.json().get("access_token"), None
        return None, f"Erro na geração do Token (Status {response.status_code})"
    except Exception as e:
        return None, f"Falha de conexão para Token: {str(e)}"

def consultar_siscomex(numero_duimp, ambiente, pfx_data, pfx_password):
    """Consulta a DUIMP usando mTLS + Access Token obtido automaticamente."""
    try:
        # 1. Obter o Token dinamicamente
        token, erro_token = obter_access_token(ambiente)
        if erro_token:
            return None, erro_token

        # 2. Preparar mTLS
        cert_pem, key_pem = extrair_pfx(pfx_data, pfx_password)
        
        base_url = "https://portalunico.siscomex.gov.br/duimp/api/duimps"
        if ambiente == "Treinamento":
            base_url = "https://val.portalunico.siscomex.gov.br/duimp/api/duimps"
        
        url = f"{base_url}/{numero_duimp}"

        with tempfile.NamedTemporaryFile(delete=False, suffix='.crt') as cert_file, \
             tempfile.NamedTemporaryFile(delete=False, suffix='.key') as key_file:
            
            cert_file.write(cert_pem)
            key_file.write(key_pem)
            cert_file.flush()
            key_file.flush()

            headers = {
                "Accept": "application/json",
                "Role-Type": "IMP",
                "Authorization": f"Bearer {token}"
            }

            response = requests.get(
                url,
                headers=headers,
                cert=(cert_file.name, key_file.name),
                timeout=30
            )

        os.unlink(cert_file.name)
        os.unlink(key_file.name)

        if response.status_code == 200:
            return response.json(), None
        return None, f"Erro Siscomex ({response.status_code}): {response.text}"

    except Exception as e:
        return None, str(e)

# --- INTERFACE ---
st.title("🚢 Siscomex Gateway | Consulta Direta DUIMP")
st.markdown("---")

with st.sidebar:
    st.header("🔐 Credenciais A1")
    uploaded_pfx = st.file_uploader("Carregar Certificado (.pfx)", type=["pfx", "p12"])
    pfx_password = st.text_input("Senha do Certificado", type="password")
    
    st.divider()
    st.info("✅ **Autenticação API Ativa:** Client ID e Secret configurados internamente.")
    
    st.header("⚙️ Configuração")
    ambiente = st.radio("Ambiente", ["Produção", "Treinamento"])
    
    st.divider()
    numero_duimp = st.text_input("Número da DUIMP", placeholder="Ex: 26BR00001720636").upper().strip()
    btn_consultar = st.button("Executar Consulta", type="primary")

if btn_consultar:
    if not uploaded_pfx or not pfx_password or not numero_duimp:
        st.error("⚠️ Preencha o certificado, a senha e o número da DUIMP.")
    else:
        with st.spinner("🔒 Autenticando e Consultando..."):
            dados, erro = consultar_siscomex(numero_duimp, ambiente, uploaded_pfx.read(), pfx_password)

            if erro:
                st.error(f"❌ Falha: {erro}")
            elif dados:
                st.success("✅ Sucesso!")
                ident = dados.get('identificacao', {})
                carga = dados.get('carga', {})
                
                col1, col2, col3 = st.columns(3)
                col1.metric("Situação", ident.get('situacao', 'N/A'))
                col2.metric("Peso Bruto", f"{carga.get('pesoBruto', 0)} KG")
                
                valor_total = sum(item.get('valorDolar', 0) for item in dados.get('itens', []))
                col3.metric("Valor Total (USD)", f"$ {valor_total:,.2f}")

                tab1, tab2 = st.tabs(["📋 Resumo", "🛠️ JSON Bruto"])
                with tab1:
                    st.table(pd.DataFrame([
                        {"Campo": "Número", "Valor": ident.get('numero', 'N/A')},
                        {"Campo": "Data", "Valor": ident.get('dataRegistro', 'N/A')},
                        {"Campo": "UOL", "Valor": carga.get('uol', 'N/A')}
                    ]))
                with tab2:
                    st.json(dados)

st.divider()
st.caption(f"© {datetime.now().year} - Siscomex Gateway | Acesso Restrito")
