import streamlit as st
import requests
import tempfile
import os
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.primitives import serialization
import pandas as pd
from datetime import datetime

# Configuração da Página do Streamlit
st.set_page_config(
    page_title="Siscomex Gateway - DUIMP",
    page_icon="🚢",
    layout="wide"
)

# Estilização CSS para um look profissional
st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .stMetric { background-color: #ffffff; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    div[data-testid="stExpander"] { background-color: white; border-radius: 10px; }
    </style>
    """, unsafe_allow_html=True)

def extrair_pfx(pfx_data, password):
    """
    Extrai certificado e chave privada de um arquivo PFX/P12 usando a biblioteca cryptography.
    """
    try:
        private_key, certificate, additional_certificates = pkcs12.load_key_and_certificates(
            pfx_data,
            password.encode() if password else None
        )
        
        key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        
        cert_pem = certificate.public_bytes(
            encoding=serialization.Encoding.PEM
        )
        
        return cert_pem, key_pem
    except Exception as e:
        raise Exception(f"Erro ao decodificar PFX: Verifique a senha ou o formato do arquivo. ({str(e)})")

def consultar_siscomex(numero_duimp, ambiente, pfx_data, pfx_password, token):
    """
    Realiza a chamada mTLS ao Portal Único Siscomex com URL e Headers corrigidos.
    """
    try:
        cert_pem, key_pem = extrair_pfx(pfx_data, pfx_password)
        
        # Formatação do Token: O Siscomex exige o prefixo 'Bearer ' antes do token
        auth_header = token if token.startswith("Bearer ") else f"Bearer {token}"
        
        # URL conforme manual de integração (sem o /v1/ que causou o 404 anterior)
        if ambiente == "Produção":
            base_url = "https://portalunico.siscomex.gov.br/duimp/api/duimps"
        else:
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
                "Authorization": auth_header
            }

            # Debug visual (opcional, ajuda a ver o que está sendo enviado)
            # st.write(f"DEBUG - Chamando URL: {url}")

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
        elif response.status_code == 401 or response.status_code == 403:
            return None, f"Autenticação Negada ({response.status_code}): O Token é inválido ou o certificado não tem permissão de Importador."
        elif response.status_code == 404:
            return None, f"Recurso não encontrado (404): A URL ou o número {numero_duimp} não foram localizados pelo Siscomex."
        else:
            try:
                error_data = response.json()
                msg = error_data.get('message', response.text)
            except:
                msg = response.text
            return None, f"Erro Siscomex ({response.status_code}): {msg}"

    except Exception as e:
        return None, str(e)

# --- INTERFACE ---

st.title("🚢 Siscomex Gateway | Consulta DUIMP")
st.markdown("---")

with st.sidebar:
    st.header("🔐 Autenticação A1")
    uploaded_pfx = st.file_uploader("1. Carregar Certificado (.pfx)", type=["pfx", "p12"])
    pfx_password = st.text_input("2. Senha do Certificado", type="password")
    
    st.divider()
    st.header("🔑 Acesso ao Portal")
    api_token = st.text_input("3. Token de Acesso", type="password", help="Obtenha no Portal Único em 'Gerar Token de Acesso'")
    
    if not api_token:
        st.warning("⚠️ O Token é obrigatório para evitar erros 404/403.")
    
    st.divider()
    st.header("⚙️ Configuração")
    ambiente = st.radio("Ambiente", ["Produção", "Treinamento"])
    
    st.divider()
    numero_duimp = st.text_input("Número da DUIMP", placeholder="Ex: 26BR00001720636").upper().strip()
    btn_consultar = st.button("Executar Consulta Real", type="primary")

if btn_consultar:
    if not uploaded_pfx or not pfx_password or not numero_duimp or not api_token:
        st.error("⚠️ Preencha todos os campos: Certificado, Senha, Token e Número DUIMP.")
    else:
        with st.spinner("🔒 Conectando ao Siscomex..."):
            dados, erro = consultar_siscomex(
                numero_duimp, 
                ambiente, 
                uploaded_pfx.read(), 
                pfx_password, 
                api_token
            )

            if erro:
                st.error(f"❌ Falha na Consulta: {erro}")
                st.info("Nota: Certifique-se de que a DUIMP foi registrada no ambiente de Produção antes de consultar.")
            elif dados:
                st.success("✅ Dados recuperados!")
                
                col1, col2, col3 = st.columns(3)
                ident = dados.get('identificacao', {})
                carga = dados.get('carga', {})
                
                col1.metric("Situação", ident.get('situacao', 'N/A'))
                col2.metric("Peso Bruto", f"{carga.get('pesoBruto', 0)} KG")
                
                valor_total = sum(item.get('valorDolar', 0) for item in dados.get('itens', []))
                col3.metric("Valor Total (USD)", f"$ {valor_total:,.2f}")

                tab1, tab2, tab3 = st.tabs(["📋 Resumo", "📦 Itens", "🛠️ JSON Bruto"])

                with tab1:
                    df_resumo = pd.DataFrame([
                        {"Campo": "Número DUIMP", "Valor": ident.get('numero', 'N/A')},
                        {"Campo": "Data Registro", "Valor": ident.get('dataRegistro', 'N/A')},
                        {"Campo": "Unidade Aduaneira", "Valor": carga.get('uol', 'N/A')},
                        {"Campo": "Via Transporte", "Valor": carga.get('viaTransporte', 'N/A')}
                    ])
                    st.table(df_resumo)

                with tab2:
                    if 'itens' in dados:
                        st.dataframe(pd.json_normalize(dados['itens']), use_container_width=True)
                    else:
                        st.info("Sem itens detalhados.")

                with tab3:
                    st.json(dados)
else:
    st.info("👋 Preencha os dados à esquerda para iniciar.")

st.divider()
st.caption(f"© {datetime.now().year} - Siscomex Gateway Integrador")
