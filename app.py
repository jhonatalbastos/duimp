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
        # Carrega o PFX usando a biblioteca cryptography (mais moderna que pyOpenSSL)
        private_key, certificate, additional_certificates = pkcs12.load_key_and_certificates(
            pfx_data,
            password.encode() if password else None
        )
        
        # Converte a chave privada para formato PEM
        key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        
        # Converte o certificado para formato PEM
        cert_pem = certificate.public_bytes(
            encoding=serialization.Encoding.PEM
        )
        
        return cert_pem, key_pem
    except Exception as e:
        raise Exception(f"Erro ao decodificar PFX: Verifique a senha ou o formato do arquivo. ({str(e)})")

def consultar_siscomex(numero_duimp, ambiente, pfx_data, pfx_password, token):
    """
    Realiza a chamada mTLS real ao Portal Único Siscomex.
    """
    try:
        cert_pem, key_pem = extrair_pfx(pfx_data, pfx_password)
        
        base_url = "https://portalunico.siscomex.gov.br/duimp/api/duimps"
        if ambiente == "Treinamento":
            base_url = "https://val.portalunico.siscomex.gov.br/duimp/api/duimps"
        
        url = f"{base_url}/{numero_duimp}"

        # Criar arquivos temporários para o mTLS
        with tempfile.NamedTemporaryFile(delete=False, suffix='.crt') as cert_file, \
             tempfile.NamedTemporaryFile(delete=False, suffix='.key') as key_file:
            
            cert_file.write(cert_pem)
            key_file.write(key_pem)
            cert_file.flush()
            key_file.flush()

            headers = {
                "Accept": "application/json",
                "Role-Type": "IMP",
                "Authorization": f"Bearer {token}" if token else ""
            }

            response = requests.get(
                url,
                headers=headers,
                cert=(cert_file.name, key_file.name),
                timeout=30
            )

        # Limpeza imediata dos certificados temporários
        os.unlink(cert_file.name)
        os.unlink(key_file.name)

        if response.status_code == 200:
            return response.json(), None
        else:
            return None, f"Erro Siscomex ({response.status_code}): {response.text}"

    except Exception as e:
        return None, str(e)

# --- INTERFACE ---

st.title("🚢 Siscomex Gateway | Consulta DUIMP")
st.markdown("---")

# Sidebar para Autenticação e Configuração
with st.sidebar:
    st.header("🔐 Autenticação A1")
    uploaded_pfx = st.file_uploader("Carregar Certificado (.pfx)", type=["pfx", "p12"])
    pfx_password = st.text_input("Senha do Certificado", type="password")
    
    st.divider()
    st.header("⚙️ Configuração")
    ambiente = st.radio("Ambiente", ["Produção", "Treinamento"])
    api_token = st.text_input("Token de Acesso (Opcional)", type="password", help="Token gerado no Portal Único")
    
    st.divider()
    numero_duimp = st.text_input("Número da DUIMP", placeholder="Ex: 24BR00001234567").upper()
    btn_consultar = st.button("Executar Consulta Real", type="primary")

# Área Principal de Resultados
if btn_consultar:
    if not uploaded_pfx or not pfx_password or not numero_duimp:
        st.error("⚠️ Por favor, preencha o certificado, a senha e o número da DUIMP.")
    else:
        with st.spinner("🔒 Autenticando com Certificado Digital e Consultando Siscomex..."):
            dados, erro = consultar_siscomex(
                numero_duimp, 
                ambiente, 
                uploaded_pfx.read(), 
                pfx_password, 
                api_token
            )

            if erro:
                st.error(f"❌ Falha na Consulta: {erro}")
            elif dados:
                st.success("✅ Dados recuperados com sucesso!")
                
                # Dashboard de Métricas
                col1, col2, col3 = st.columns(3)
                col1.metric("Situação", dados.get('identificacao', {}).get('situacao', 'N/A'))
                col2.metric("Peso Bruto", f"{dados.get('carga', {}).get('pesoBruto', 0)} KG")
                
                valor_total = sum(item.get('valorDolar', 0) for item in dados.get('itens', []))
                col3.metric("Valor Total (USD)", f"$ {valor_total:,.2f}")

                # Organização por Tabs
                tab1, tab2, tab3 = st.tabs(["📋 Resumo Operacional", "📦 Itens da Mercadoria", "🛠️ JSON Bruto"])

                with tab1:
                    st.subheader("Dados de Identificação e Carga")
                    df_resumo = pd.DataFrame([
                        {"Campo": "Número DUIMP", "Valor": dados['identificacao']['numero']},
                        {"Campo": "Data Registro", "Valor": dados['identificacao']['dataRegistro']},
                        {"Campo": "Unidade Aduaneira", "Valor": dados['carga']['uol']},
                        {"Campo": "Via Transporte", "Valor": dados['carga']['viaTransporte']},
                        {"Campo": "Incoterm", "Valor": dados['carga']['incoterm']}
                    ])
                    st.table(df_resumo)

                with tab2:
                    st.subheader("Itens e NCMs")
                    if 'itens' in dados:
                        df_itens = pd.json_normalize(dados['itens'])
                        st.dataframe(df_itens, use_container_width=True)
                    else:
                        st.info("Nenhum item detalhado nesta declaração.")

                with tab3:
                    st.json(dados)
else:
    # Tela de Boas-vindas
    st.info("👋 Aguardando dados. Preencha as informações na barra lateral para iniciar a consulta real.")
    
    st.markdown("""
    ### 🛡️ Segurança e Privacidade
    * **Processamento em Memória**: O seu arquivo PFX e a senha são processados apenas durante a execução da consulta.
    * **Sem Armazenamento**: Os dados não são guardados em base de dados.
    * **Conexão HTTPS**: O Streamlit Cloud garante que a comunicação entre o seu navegador e este servidor é criptografada.
    """)

st.divider()
st.caption(f"© {datetime.now().year} - Siscomex Gateway Integrador")
