
import io
import time
from typing import Optional, Tuple, List

import pandas as pd
import requests
import streamlit as st

# =========================
# CONFIGURAÇÕES DO APP
# =========================
st.set_page_config(
    page_title="Sugestão do Vendedor",
    page_icon="🧾",
    layout="wide"
)

# =========================
# CONFIGURAÇÕES DA API LOCAL (WINDOWS)
# =========================
API_BASE = "http://127.0.0.1:8000"
API_TOKEN = "API_TOKEN_ACCESS_123456789"
API_TIMEOUT = 10

# =========================
# FUNÇÕES DE API
# =========================
def call_api(method: str, path: str, **kwargs):
    url = f"{API_BASE}{path}"
    headers = kwargs.pop("headers", {})
    headers["X-API-Key"] = API_TOKEN

    try:
        r = requests.request(
            method=method,
            url=url,
            headers=headers,
            timeout=API_TIMEOUT,
            **kwargs
        )
        r.raise_for_status()
        if r.content:
            return r.json()
        return None
    except requests.RequestException as ex:
        raise RuntimeError(f"Erro ao chamar API {path}: {ex}") from ex


@st.cache_data(ttl=10)
def api_status() -> bool:
    try:
        data = call_api("GET", "/health")
        return bool(data and data.get("ok"))
    except Exception:
        return False

# =========================
# FUNÇÕES DE NEGÓCIO
# =========================
def authenticate_user(login: str, senha: str) -> Tuple[bool, Optional[str]]:
    payload = {"login": login, "senha": senha}
    data = call_api("POST", "/login", json=payload)
    if not data:
        return False, None
    return data.get("ok", False), data.get("nome")


def insert_sugestao(
    referencia: str,
    quantidade: int,
    marca: str,
    tipo: str,
    comentario: str,
    codigo: Optional[str],
    descricao_codigo: Optional[str],
    vendedor: Optional[str]
):
    payload = {
        "referencia": referencia,
        "quantidade": quantidade,
        "marca": marca,
        "tipo": tipo,
        "comentario": comentario,
        "codigo": codigo,
        "descricao": descricao_codigo,
        "vendedor": vendedor,
    }
    call_api("POST", "/sugestao", json=payload)


@st.cache_data(ttl=30)
def carregar_sugestoes() -> pd.DataFrame:
    data = call_api("GET", "/sugestoes")
    return pd.DataFrame(data) if data else pd.DataFrame()


def carregar_itens_por_referencia(referencia: str) -> List[tuple]:
    data = call_api("GET", f"/itens/{referencia}")
    if not data:
        return []
    return [(str(x.get("codigo", "")), str(x.get("descricao", ""))) for x in data]

# =========================
# LOGIN
# =========================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.usuario = None

if not st.session_state.authenticated:
    st.title("🔐 Login")

    st.caption(f"Status da API: {'🟢 Online' if api_status() else '🔴 Offline'}")

    with st.form("login_form"):
        user = st.text_input("Usuário")
        pwd = st.text_input("Senha", type="password")
        entrar = st.form_submit_button("Entrar")

    if entrar:
        ok, nome = authenticate_user(user, pwd)
        if ok:
            st.session_state.authenticated = True
            st.session_state.usuario = nome or user
            st.success("Login realizado com sucesso!")
            time.sleep(0.5)
            st.rerun()
        else:
            st.error("Usuário ou senha inválidos")

    st.stop()

# =========================
# MENU
# =========================
st.sidebar.title("SOUZA E NETO")
st.sidebar.caption(f"👤 {st.session_state.usuario}")

pagina = st.sidebar.radio(
    "Menu",
    ["SUGESTÃO DO VENDEDOR", "CONSULTA SUGESTÃO"]
)

if st.sidebar.button("Sair"):
    st.session_state.authenticated = False
    st.rerun()

# =========================
# SUGESTÃO DO VENDEDOR
# =========================
if pagina == "SUGESTÃO DO VENDEDOR":
    st.title("🧾 Sugestão do Vendedor")

    referencia = st.text_input("Referência *")
    itens = carregar_itens_por_referencia(referencia) if referencia else []

    item_label = [f"{c} - {d}" for c, d in itens]
    item_escolhido = st.selectbox(
        "Código / Descrição *",
        item_label,
        index=None
    )

    quantidade = st.number_input("Quantidade *", min_value=1, step=1)
    marca = st.text_input("Marca *")
    tipo = st.selectbox(
        "Tipo Sugestão *",
        ["VENDA_CASADA", "VENDA_PERDIDA"]
    )
    comentario = st.text_area("Comentário")

    if st.button("💾 Salvar"):
        if not referencia or not item_escolhido or not marca:
            st.error("Preencha todos os campos obrigatórios.")
        else:
            codigo, descricao = item_escolhido.split(" - ", 1)
            insert_sugestao(
                referencia,
                quantidade,
                marca,
                tipo,
                comentario,
                codigo,
                descricao,
                st.session_state.usuario
            )
            st.success("✅ Sugestão salva com sucesso!")

# =========================
# CONSULTA SUGESTÃO
# =========================
else:
    st.title("🔎 Consulta Sugestões")

    df = carregar_sugestoes()
    st.dataframe(df, use_container_width=True)

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)

    st.download_button(
        "📥 Exportar Excel",
        buffer.getvalue(),
        file_name="sugestoes.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

