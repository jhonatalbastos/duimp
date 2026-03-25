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
# Chaves extraídas do seu print de geração com sucesso (image_a8bafd.png)
CLIENT_ID_SEC = "noQXPhAOi4Vc1J5Z-XAPCS9FmodtME5p"
CLIENT_SECRET_SEC = "ruV4-tybNVCG9g_-tjcVg3ifE--J1sBK"

# Configuração da Página do Streamlit
st.set_page_config(
    page_title="Siscomex Gateway - DUIMP",
    page_icon="🚢",
    layout="wide"
)

# Estilização CSS para um visual profissional
st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .stMetric { background-color: #ffffff; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    </style>
    """, unsafe_allow_html=True)

def extrair_pfx(pfx_data, password):
    """Extrai certificado e chave privada para mTLS usando a biblioteca cryptography."""
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

def obter_access_token(ambiente, cert_info=None):
    """Troca Client ID/Secret por um Access Token (OAUTH2) com mTLS."""
    # URLs de autenticação do Serpro para o Portal Único
    if ambiente == "Treinamento":
        url = "https://val.portalunico.siscomex.gov.br/portal/api/autenticacao/token"
    else:
        url = "https://portalunico.siscomex.gov.br/portal/api/autenticacao/token"
    
    # Credenciais codificadas em Base64
    auth_str = f"{CLIENT_ID_SEC}:{CLIENT_SECRET_SEC}"
    auth_b64 = base64.b64encode(auth_str.encode()).decode()
    
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": f"Basic {auth_b64}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) SiscomexGateway/1.0",
        "X-Origin-System": "SiscomexGateway"
    }
    
    # Payload específico para o Serpro Gateway
    payload = {
        "grant_type": "client_credentials",
        "scope": "openid"
    }
    
    try:
        # A requisição de token em Produção EXIGE o certificado A1 junto (mTLS)
        response = requests.post(
            url, 
            data=payload, 
            headers=headers, 
            cert=cert_info, 
            timeout=20,
            verify=True
        )
        
        if response.status_code == 200:
            return response.json().get("access_token"), None
        
        # Fallback para endpoint alternativo caso o principal falhe
        if response.status_code in [403, 404]:
            url_alt = url.replace("/portal/api/", "/api/")
            response_alt = requests.post(url_alt, data=payload, headers=headers, cert=cert_info, timeout=20)
            if response_alt.status_code == 200:
                return response_alt.json().get("access_token"), None

        return None, f"Erro na geração do Token ({response.status_code})."
    except Exception as e:
        return None, f"Falha de conexão para Token: {str(e)}"

def consultar_siscomex(numero_duimp, ambiente, pfx_data, pfx_password):
    """Realiza o fluxo completo: Autenticação -> Consulta DUIMP."""
    try:
        # Extração dos dados do certificado para arquivos temporários
        cert_pem, key_pem = extrair_pfx(pfx_data, pfx_password)
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.crt') as cert_file, \
             tempfile.NamedTemporaryFile(delete=False, suffix='.key') as key_file:
            
            cert_file.write(cert_pem)
            key_file.write(key_pem)
            cert_file.flush()
            key_file.flush()
            
            cert_info = (cert_file.name, key_file.name)

            # Etapa 1: Obtenção do Access Token
            token, erro_token = obter_access_token(ambiente, cert_info)
            if erro_token:
                os.unlink(cert_file.name)
                os.unlink(key_file.name)
                return None, erro_token

            # Etapa 2: Consulta à API da DUIMP
            if ambiente == "Treinamento":
                base_url = "https://val.portalunico.siscomex.gov.br/duimp/api/duimps"
            else:
                base_url = "https://portalunico.siscomex.gov.br/duimp/api/duimps"
            
            url = f"{base_url}/{numero_duimp}"
            headers = {
                "Accept": "application/json",
                "Role-Type": "IMP",
                "Authorization": f"Bearer {token}",
                "User-Agent": "Mozilla/5.0 SiscomexGateway/1.0"
            }

            response = requests.get(url, headers=headers, cert=cert_info, timeout=30)

        # Limpeza dos arquivos temporários
        os.unlink(cert_file.name)
        os.unlink(key_file.name)

        if response.status_code == 200:
            return response.json(), None
        
        return None, f"Erro Siscomex ({response.status_code}): {response.text[:300]}"

    except Exception as e:
        return None, str(e)

# --- INTERFACE DO USUÁRIO ---
st.title("🚢 Siscomex Gateway | Consulta Direta DUIMP")
st.markdown("---")

with st.sidebar:
    st.header("🔐 Credenciais A1")
    uploaded_pfx = st.file_uploader("Carregar Certificado (.pfx)", type=["pfx", "p12"])
    pfx_password = st.text_input("Senha do Certificado", type="password")
    
    st.divider()
    st.info("✅ **Chaves Ativas:** Credenciais Client ID e Secret vinculadas.")
    
    st.header("⚙️ Configuração")
    # Nota: Suas chaves são de PRODUÇÃO (conforme image_a8bafd.png)
    ambiente = st.radio("Ambiente", ["Produção", "Treinamento"])
    
    st.divider()
    numero_duimp = st.text_input("Número da DUIMP", placeholder="Ex: 26BR00001720636").upper().strip()
    btn_consultar = st.button("Executar Consulta", type="primary")

if btn_consultar:
    if not uploaded_pfx or not pfx_password or not numero_duimp:
        st.error("⚠️ Preencha todos os campos: Certificado, Senha e Número da DUIMP.")
    else:
        with st.spinner("🔒 Conectando ao Servidor Serpro..."):
            pfx_bytes = uploaded_pfx.read()
            dados, erro = consultar_siscomex(numero_duimp, ambiente, pfx_bytes, pfx_password)

            if erro:
                st.error(f"❌ Falha: {erro}")
                if "403" in erro:
                    st.warning("**Causa Comum:** Se você estiver em 'Produção', verifique se o certificado A1 carregado pertence ao mesmo CNPJ/CPF que gerou o par de chaves no Portal Único.")
            elif dados:
                st.success("✅ Consulta realizada com sucesso!")
                
                # Dashboard de resultados
                ident = dados.get('identificacao', {})
                carga = dados.get('carga', {})
                itens = dados.get('itens', [])
                
                col1, col2, col3 = st.columns(3)
                col1.metric("Situação", ident.get('situacao', 'N/A'))
                col2.metric("Peso Bruto", f"{carga.get('pesoBruto', 0)} KG")
                
                valor_total = sum(item.get('valorDolar', 0) for item in itens)
                col3.metric("Valor Total (USD)", f"$ {valor_total:,.2f}")

                tab1, tab2 = st.tabs(["📋 Detalhes Operacionais", "🛠️ Resposta Técnica (JSON)"])
                with tab1:
                    resumo_data = [
                        {"Campo": "Número DUIMP", "Value": ident.get('numero', 'N/A')},
                        {"Campo": "Data Registro", "Value": ident.get('dataRegistro', 'N/A')},
                        {"Campo": "Local", "Value": carga.get('uol', 'N/A')},
                        {"Campo": "Incoterm", "Value": carga.get('incoterm', 'N/A')}
                    ]
                    st.table(pd.DataFrame(resumo_data))
                with tab2:
                    st.json(dados)

st.divider()
st.caption(f"© {datetime.now().year} - Siscomex Gateway | Conexão Segura mTLS via Serpro")
