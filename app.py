import streamlit as st
import requests
import tempfile
import os
import base64
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.primitives import serialization
import pandas as pd
from datetime import datetime
import re

# --- CONFIGURAÇÕES DE ACESSO (VINCULADAS AO CNPJ DO PRINT a8bafd.png) ---
CLIENT_ID_SEC = "noQXPhAOi4Vc1J5Z-XAPCS9FmodtME5p"
CLIENT_SECRET_SEC = "ruV4-tybNVCG9g_-tjcVg3ifE--J1sBK"

# Configuração da Página
st.set_page_config(
    page_title="Siscomex Gateway - DUIMP",
    page_icon="🚢",
    layout="wide"
)

# Estilização
st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .stMetric { background-color: #ffffff; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    .status-card { padding: 20px; border-radius: 10px; margin-bottom: 20px; border-left: 5px solid #003366; background: white; }
    </style>
    """, unsafe_allow_html=True)

def limpar_erro_html(texto_erro):
    """Remove tags HTML de respostas de erro do servidor para facilitar a leitura."""
    return re.sub('<[^<]+?>', '', texto_erro).strip()

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
        raise Exception(f"Erro no Certificado: Senha incorreta ou arquivo inválido. ({str(e)})")

def obter_access_token(ambiente, cert_info=None):
    """Autenticação OAUTH2 via mTLS conforme image_a8cd43.png."""
    if ambiente == "Treinamento":
        url = "https://val.portalunico.siscomex.gov.br/api/autenticacao/token"
    else:
        url = "https://portalunico.siscomex.gov.br/api/autenticacao/token"
    
    auth_str = f"{CLIENT_ID_SEC}:{CLIENT_SECRET_SEC}"
    auth_b64 = base64.b64encode(auth_str.encode()).decode()
    
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": f"Basic {auth_b64}",
        "User-Agent": "SiscomexGateway/1.2",
        "X-Origin-System": "SiscomexGateway"
    }
    
    payload = {
        "grant_type": "client_credentials",
        "scope": "openid"
    }
    
    try:
        response = requests.post(
            url, 
            data=payload, 
            headers=headers, 
            cert=cert_info, 
            timeout=25
        )
        
        # Fallback para URL com /portal/ se houver 404
        if response.status_code == 404:
            url_alt = url.replace("/api/", "/portal/api/")
            response = requests.post(url_alt, data=payload, headers=headers, cert=cert_info, timeout=25)

        if response.status_code == 200:
            return response.json().get("access_token"), None
        
        erro_limpo = limpar_erro_html(response.text)
        return None, f"Erro {response.status_code}: {erro_limpo[:150]}"
    except Exception as e:
        return None, f"Falha de rede: {str(e)}"

def consultar_siscomex(numero_duimp, ambiente, pfx_data, pfx_password):
    """Fluxo principal de consulta."""
    try:
        cert_pem, key_pem = extrair_pfx(pfx_data, pfx_password)
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.crt') as cert_file, \
             tempfile.NamedTemporaryFile(delete=False, suffix='.key') as key_file:
            
            cert_file.write(cert_pem)
            key_file.write(key_pem)
            cert_file.flush()
            key_file.flush()
            
            cert_info = (cert_file.name, key_file.name)

            # 1. Token
            token, erro_token = obter_access_token(ambiente, cert_info)
            if erro_token:
                os.unlink(cert_file.name)
                os.unlink(key_file.name)
                return None, erro_token

            # 2. DUIMP
            base_url = "https://val.portalunico.siscomex.gov.br/duimp/api/duimps" if ambiente == "Treinamento" else "https://portalunico.siscomex.gov.br/duimp/api/duimps"
            
            url = f"{base_url}/{numero_duimp}"
            headers = {
                "Accept": "application/json",
                "Role-Type": "IMP",
                "Authorization": f"Bearer {token}",
                "User-Agent": "SiscomexGateway/1.2"
            }

            response = requests.get(url, headers=headers, cert=cert_info, timeout=30)

        os.unlink(cert_file.name)
        os.unlink(key_file.name)

        if response.status_code == 200:
            return response.json(), None
        
        return None, f"Erro Siscomex ({response.status_code}): {limpar_erro_html(response.text)[:200]}"

    except Exception as e:
        return None, str(e)

# --- UI ---
st.title("🚢 Siscomex Gateway | Dashboard DUIMP")
st.markdown("---")

with st.sidebar:
    st.header("🔐 Autenticação A1")
    uploaded_pfx = st.file_uploader("Arquivo (.pfx / .p12)", type=["pfx", "p12"])
    pfx_password = st.text_input("Senha", type="password")
    
    st.divider()
    st.markdown("**Status da API:**")
    st.success("Credenciais Vinculadas")
    
    ambiente = st.radio("Ambiente de Destino", ["Produção", "Treinamento"])
    st.divider()
    numero_duimp = st.text_input("Número da DUIMP", placeholder="Ex: 26BR00001720636").upper().strip()
    btn_consultar = st.button("Consultar Siscomex", type="primary", use_container_width=True)

if btn_consultar:
    if not uploaded_pfx or not pfx_password or not numero_duimp:
        st.error("Preencha as credenciais e o número da DUIMP.")
    else:
        with st.spinner("Conectando ao Serpro..."):
            pfx_bytes = uploaded_pfx.read()
            dados, erro = consultar_siscomex(numero_duimp, ambiente, pfx_bytes, pfx_password)

            if erro:
                st.error(f"⚠️ {erro}")
                if "403" in erro:
                    st.info("**Dica:** O erro 403 geralmente significa que o certificado A1 não pertence ao CNPJ que gerou as chaves de acesso no Portal Único.")
            elif dados:
                st.success("Dados recuperados!")
                
                # Layout de Resultados
                ident = dados.get('identificacao', {})
                carga = dados.get('carga', {})
                itens = dados.get('itens', [])
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Situação", ident.get('situacao', 'N/A'))
                with col2:
                    st.metric("Peso Bruto", f"{carga.get('pesoBruto', 0)} KG")
                with col3:
                    valor_usd = sum(item.get('valorDolar', 0) for item in itens)
                    st.metric("Valor Aduaneiro", f"USD {valor_usd:,.2f}")

                tab1, tab2 = st.tabs(["📋 Detalhamento", "🛠️ Resposta JSON"])
                with tab1:
                    st.write("### Informações Gerais")
                    df_resumo = pd.DataFrame([
                        {"Campo": "Número", "Valor": ident.get('numero')},
                        {"Campo": "Data Registro", "Valor": ident.get('dataRegistro')},
                        {"Campo": "Recinto", "Valor": carga.get('uol')},
                        {"Campo": "Incoterm", "Valor": carga.get('incoterm')}
                    ])
                    st.table(df_resumo)
                with tab2:
                    st.json(dados)

st.divider()
st.caption(f"© {datetime.now().year} - Siscomex Gateway | mTLS v1.2")
