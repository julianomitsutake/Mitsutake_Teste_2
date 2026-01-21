

# -*- coding: utf-8 -*-
import os
import io
import time
from typing import Optional, Tuple, List

import pandas as pd
import requests
import streamlit as st

# =========================================================
# CONFIGURAÇÕES DO APLICATIVO
# =========================================================
st.set_page_config(
    page_title="Sugestão do Vendedor",
    page_icon="🧾",
    layout="wide"
)

# --- CSS para fixar o crédito no rodapé da sidebar ---
st.markdown(
    """
<style>
/* Contêiner fixo no rodapé da sidebar */
#sidebar-footer {
  position: fixed;
  bottom: 12px;
  left: 0;
  width: 100%;
  padding: 0 16px;
  box-sizing: border-box;
}
section[data-testid="stSidebar"] { position: relative; }
</style>
""",
    unsafe_allow_html=True
)

# =========================================================
# CONFIG DA API (segura: Secrets e/ou variáveis de ambiente)
# =========================================================
# Ordem de carregamento:
# 1) Variáveis de ambiente (útil p/ rodar como serviço no Windows)
# 2) st.secrets (local/Cloud)
# 3) Defaults locais (apenas base_url) — token segue obrigatório
_api_conf = st.secrets.get("api", {})
API_BASE = (os.getenv("API_BASE") or _api_conf.get("base_url") or "http://127.0.0.1:8000").rstrip("/")
API_TOKEN = os.getenv("API_TOKEN") or _api_conf.get("token") or ""
API_TIMEOUT = int(os.getenv("API_TIMEOUT") or _api_conf.get("timeout", 10))

def _require_api_config():
    if not API_BASE or not API_TOKEN:
        st.error(
            "⚠️ Configuração da API ausente.\n\n"
            "Defina via **variáveis de ambiente** (API_BASE, API_TOKEN, API_TIMEOUT)\n"
            "ou em **Settings → Segredos** com o bloco:\n\n"
            "```toml\n[api]\nbase_url = \"http://127.0.0.1:8000\"\ntoken = \"SEU_TOKEN\"\ntimeout = 10\n```"
        )
        st.stop()

_require_api_config()

def _rerun():
    """Compat para diferentes versões do Streamlit."""
    try:
        st.rerun()
    except Exception:
        if hasattr(st, "experimental_rerun"):
            st.experimental_rerun()

# =========================================================
# CLIENTE HTTP (API)
# =========================================================
def call_api(method: str, path: str, **kwargs):
    """Chama a API com cabeçalho X-API-Key e trata erros comuns."""
    url = f"{API_BASE}{path}"
    headers = kwargs.pop("headers", {}) or {}
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
        # Tenta JSON; se não for, retorna None
        if r.content and "application/json" in (r.headers.get("Content-Type") or ""):
            return r.json()
        return None
    except requests.HTTPError as ex:
        resp = ex.response
        status = resp.status_code if resp is not None else "?"
        body = ""
        if resp is not None:
            try:
                body = resp.text
            except Exception:
                body = ""
        if status == 401:
            raise RuntimeError("Não autorizado (401). Verifique o token em Settings → Segredos.") from ex
        raise RuntimeError(f"Falha HTTP {status} em {path}: {body}") from ex
    except requests.RequestException as ex:
        raise RuntimeError(f"Falha ao chamar API {path}: {ex}") from ex

@st.cache_data(ttl=15)
def api_status() -> bool:
    try:
        data = call_api("GET", "/health")
        return bool(data and data.get("ok"))
    except Exception:
        return False

# =========================================================
# FUNÇÕES DE NEGÓCIO (via API)
# =========================================================
def insert_sugestao(
    referencia: str,
    quantidade: int,
    marca: str,
    tipo: str,
    comentario: str,
    codigo: Optional[str],
    descricao: Optional[str],
    vendedor: Optional[str]
):
    payload = {
        "referencia": referencia,
        "quantidade": int(quantidade),
        "marca": marca,
        "tipo": tipo,
        "comentario": comentario,
        "codigo": codigo,
        "descricao": descricao,
        "vendedor": vendedor
    }
    call_api("POST", "/sugestao", json=payload)

def authenticate_user(login: str, senha: str) -> Tuple[bool, Optional[str]]:
    payload = {"login": login, "senha": senha}
    data = call_api("POST", "/login", json=payload)
    if not data:
        return False, None
    return (bool(data.get("ok")), data.get("nome"))

@st.cache_data(ttl=30)
def carregar_sugestoes() -> pd.DataFrame:
    data = call_api("GET", "/sugestoes")
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)

    # Renomear colunas para exibição amigável
    rename_map = {
        "REFERENCIA": "Referência",
        "QUANTIDADE": "Quantidade",
        "MARCA": "Marca",
        "TIPO_SUGESTAO": "Tipo Sugestão",
        "COMENTARIO_VENDEDOR": "Comentário Vendedor",
        "VENDEDOR": "Vendedor",
        "ACAO_COMPRADOR": "Ação Comprador",
        "COMENTARIO_COMPRADOR": "Comentário Comprador",
        "ORDEM_COMPRA": "Ordem Compra",
        "CODIGO": "Código",
        "DESCRICAO_CODIGO": "Descrição Código",
        "DATA_LANCAMENTO": "Data Lançamento"
    }
    df = df.rename(columns=rename_map)

    # Data/Hora pt-BR completa
    if "Data Lançamento" in df.columns:
        data_dt = pd.to_datetime(df["Data Lançamento"], errors="coerce", dayfirst=True, infer_datetime_format=True)
        df["Data Lançamento"] = data_dt.dt.strftime("%d/%m/%Y %H:%M:%S").fillna("")

    # Código sem separadores
    if "Código" in df.columns:
        def _clean_code(x):
            if pd.isna(x):
                return ""
            s = str(x)
            return s.replace(".", "").replace(",", "").strip()
        df["Código"] = df["Código"].apply(_clean_code)

    return df

def carregar_itens_por_referencia(referencia: str) -> List[tuple]:
    referencia = (referencia or "").strip()
    if not referencia:
        return []
    items = call_api("GET", f"/itens/{referencia}")
    if not items:
        return []
    out: List[tuple] = []
    for it in items:
        cod = "" if it.get("codigo") is None else str(it.get("codigo"))
        desc = "" if it.get("descricao") is None else str(it.get("descricao"))
        out.append((cod, desc))
    # remove duplicados preservando ordem
    seen = set()
    dedup = []
    for t in out:
        if t not in seen:
            seen.add(t)
            dedup.append(t)
    return dedup

# =========================================================
# ESTADO INICIAL, CALLBACKS E LIMPEZA
# =========================================================
def init_state_defaults():
    defaults = {
        # Autenticação
        "authenticated": False,
        "usuario": None,
        "login_user": "",
        "login_pass": "",

        # Formulário de cadastro
        "referencia": "",
        "quantidade": None,
        "marca": "",
        "tipo_sugestao": None,
        "comentario": "",
        # Itens por referência
        "itens_ref": [],              # [(codigo, descricao)]
        "item_escolhido": None,       # "CODIGO - DESCRIÇÃO"
        "codigo_item": None,
        "descricao_item": None,

        # Fluxos
        "_clear_after_save": False,
        "_clear_request": False,

        # Filtros da consulta
        "f_ref": "(Todos)", "f_marca": "(Todos)", "f_tipo": "(Todos)",
        "f_vendedor": "(Todos)", "f_acao": "(Todos)", "f_coment_comp": "(Todos)",
        "f_oc": "(Todos)", "f_codigo": "(Todos)", "f_desc": "(Todos)", "f_data": "(Todos)",
        "_clear_filters_request": False,

        # Mensagem pós-salvar
        "_pending_success": False
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

def on_change_referencia():
    """
    Callback disparado ao sair/confirmar o campo 'Referência'.
    Carrega itens para a referência e reseta seleção anterior.
    """
    ref = (st.session_state.get("referencia") or "").strip()
    st.session_state["itens_ref"] = []
    st.session_state["item_escolhido"] = None
    st.session_state["codigo_item"] = None
    st.session_state["descricao_item"] = None
    if ref:
        try:
            st.session_state["itens_ref"] = carregar_itens_por_referencia(ref)
        except Exception:
            st.session_state["itens_ref"] = []

def do_logout():
    st.session_state["authenticated"] = False
    st.session_state["usuario"] = None
    _rerun()

def apply_pending_clear():
    # Limpeza do FORM
    if st.session_state.get("_clear_after_save", False) or st.session_state.get("_clear_request", False):
        for key in ["referencia","quantidade","marca","tipo_sugestao","comentario",
                    "itens_ref","item_escolhido","codigo_item","descricao_item"]:
            st.session_state.pop(key, None)
        st.session_state["referencia"] = ""
        st.session_state["quantidade"] = None
        st.session_state["marca"] = ""
        st.session_state["tipo_sugestao"] = None
        st.session_state["comentario"] = ""
        st.session_state["itens_ref"] = []
        st.session_state["item_escolhido"] = None
        st.session_state["codigo_item"] = None
        st.session_state["descricao_item"] = None
        st.session_state["_clear_after_save"] = False
        st.session_state["_clear_request"] = False

    # Limpeza dos FILTROS
    if st.session_state.get("_clear_filters_request", False):
        for key in ["f_ref","f_marca","f_tipo","f_vendedor","f_acao","f_coment_comp","f_oc","f_codigo","f_desc","f_data"]:
            st.session_state.pop(key, None)
        st.session_state["f_ref"] = "(Todos)"; st.session_state["f_marca"] = "(Todos)"
        st.session_state["f_tipo"] = "(Todos)"; st.session_state["f_vendedor"] = "(Todos)"
        st.session_state["f_acao"] = "(Todos)"; st.session_state["f_coment_comp"] = "(Todos)"
        st.session_state["f_oc"] = "(Todos)"; st.session_state["f_codigo"] = "(Todos)"
        st.session_state["f_desc"] = "(Todos)"; st.session_state["f_data"] = "(Todos)"
        st.session_state["_clear_filters_request"] = False

# Inicializa / limpeza
init_state_defaults()
apply_pending_clear()

# =========================================================
# LOGIN (PORTA DE ENTRADA)
# =========================================================
if not st.session_state.get("authenticated", False):
    st.title("🔐 Acesso ao Sistema")

    # Status da API
    ok = api_status()
    st.caption(f"Status da API: {'🟢 Online' if ok else '🔴 Offline'}")
    if not ok:
        st.warning("A API local parece offline. Verifique o serviço do Uvicorn.")

    with st.form("form_login", clear_on_submit=False):
        st.text_input("Usuário", key="login_user")
        st.text_input("Senha", type="password", key="login_pass")
        entrar = st.form_submit_button("Entrar")

    if entrar:
        user = (st.session_state.login_user or "").strip()
        pwd = st.session_state.login_pass or ""
        if not user or not pwd:
            st.error("Informe **Usuário** e **Senha**.")
        else:
            try:
                ok, nome = authenticate_user(user, pwd)
                if ok:
                    st.session_state["authenticated"] = True
                    st.session_state["usuario"] = nome or user
                    st.success(f"Bem-vindo(a), {st.session_state['usuario']}!")
                    time.sleep(0.6)
                    _rerun()
                else:
                    st.error("Usuário ou senha inválidos.")
            except Exception as ex:
                st.error("Erro ao autenticar (API).")
                st.exception(ex)
    st.stop()

# >>> Exibe a mensagem de sucesso pós-salvar por 5 segundos (depois limpa)
if st.session_state.get("_pending_success", False):
    _msg = st.empty()
    _msg.success("✅ Sugestão salva com sucesso!")
    time.sleep(5)
    _msg.empty()
    st.session_state["_pending_success"] = False

# =========================================================
# SIDEBAR / MENU
# =========================================================
st.sidebar.title("TESTE APP")
st.sidebar.header("Menu Principal")
pagina = st.sidebar.radio(
    " ",
    options=["SUGESTÃO DO VENDEDOR", "CONSULTA SUGESTÃO"],
    index=0
)
st.sidebar.caption(f"👤 Usuário: **{st.session_state.get('usuario','')}**")
if st.sidebar.button("Sair"):
    do_logout()

st.sidebar.markdown(
    """
    <div id="sidebar-footer">
      <hr style="margin: 8px 0 6px 0; opacity:0.4;">
      <div style='font-size:12px; color:#6b6b6b;'>
        Desenvolvido por <b>Juliano Mitsutake</b>
      </div>
    </div>
    """,
    unsafe_allow_html=True
)

# =========================================================
# PÁGINA: SUGESTÃO DO VENDEDOR
# =========================================================
if pagina == "SUGESTÃO DO VENDEDOR":
    st.title("🧾 Sugestão do Vendedor")

    # Referência fora do form para disparar on_change ao sair do campo
    st.text_input("Referência *", key="referencia", on_change=on_change_referencia)
    # (Opcional) Mostrar contagem de itens retornados
    if st.session_state.get("referencia", "").strip():
        qtd_itens = len(st.session_state.get("itens_ref", []))
        st.caption(f"Itens encontrados para a referência: **{qtd_itens}**")

    with st.form("form_sugestao", clear_on_submit=False):
        col1, col2 = st.columns([1, 1])

        with col1:
            # Select de Código/Descrição (obrigatório)
            opcoes_itens = []
            for (cod, desc) in st.session_state.get("itens_ref", []):
                label = f"{cod} - {desc}" if desc else f"{cod}"
                opcoes_itens.append(label)

            idx_default = None if not opcoes_itens else None
            st.selectbox(
                "Código Item / Descrição do Item *",
                options=opcoes_itens if opcoes_itens else [],
                index=idx_default,
                placeholder="Selecione o item correspondente à referência",
                key="item_escolhido"
            )

            # Ao escolher, extrai código e descrição
            item_escolhido = st.session_state.get("item_escolhido")
            if item_escolhido:
                for (cod, desc) in st.session_state.get("itens_ref", []):
                    label = f"{cod} - {desc}" if desc else f"{cod}"
                    if label == item_escolhido:
                        st.session_state["codigo_item"] = cod
                        st.session_state["descricao_item"] = desc
                        break

            # Quantidade
            quantidades = list(range(1, 1001))
            st.selectbox(
                "Quantidade *",
                options=quantidades,
                index=None,
                placeholder="Selecione a quantidade",
                key="quantidade"
            )

            # Marca
            st.text_input("Marca *", key="marca")

        with col2:
            # Tipo Sugestão
            opcoes_tipo = ["VENDA_CASADA", "VENDA_PERDIDA"]
            st.selectbox(
                "Tipo Sugestão *",
                options=opcoes_tipo,
                index=None,
                placeholder="Selecione o tipo de sugestão",
                key="tipo_sugestao"
            )

            # Vendedor (apenas leitura)
            st.text_input("Vendedor (automático)", value=st.session_state.get("usuario", ""), disabled=True)

            st.text_area("Comentário", height=140, key="comentario")

        st.caption("Campos marcados com * são obrigatórios.")

        c1, c2, _ = st.columns([0.25, 0.25, 1])
        salvar = c1.form_submit_button("💾 Salvar")
        limpar = c2.form_submit_button("🧹 Limpar")

    # Lógica dos botões
    if limpar:
        st.session_state["_clear_request"] = True
        _rerun()

    if salvar:
        referencia = (st.session_state.referencia or "").strip()
        quantidade = st.session_state.quantidade
        marca = (st.session_state.marca or "").strip()
        tipo_sugestao = st.session_state.tipo_sugestao
        comentario = (st.session_state.comentario or "").strip()
        codigo_item = st.session_state.get("codigo_item", None)
        descricao_item = st.session_state.get("descricao_item", None)
        itens_ref = st.session_state.get("itens_ref", [])
        vendedor = st.session_state.get("usuario", "")

        erros = []
        if not referencia:
            erros.append("Informe a **Referência**.")
        if not itens_ref:
            erros.append("Nenhum **item** foi encontrado para esta **Referência**. Revise a referência.")
        if itens_ref and st.session_state.get("item_escolhido") is None:
            erros.append("Selecione o **Código Item / Descrição do Item**.")
        if quantidade is None:
            erros.append("Selecione a **Quantidade**.")
        if not marca:
            erros.append("Informe a **Marca**.")
        if tipo_sugestao is None:
            erros.append("Selecione o **Tipo Sugestão**.")

        if erros:
            for e in erros:
                st.error(e)
        else:
            try:
                insert_sugestao(
                    referencia=referencia,
                    quantidade=int(quantidade),
                    marca=marca,
                    tipo=tipo_sugestao,
                    comentario=comentario,
                    codigo=codigo_item,
                    descricao=descricao_item,
                    vendedor=vendedor
                )
                st.session_state["_pending_success"] = True
                st.session_state["_clear_after_save"] = True
                _rerun()
            except Exception as ex:
                st.error("Erro ao salvar (API).")
                st.exception(ex)

# =========================================================
# PÁGINA: CONSULTA SUGESTÃO
# =========================================================
else:
    st.title("🔎 Consulta Sugestão")

    try:
        df = carregar_sugestoes()

        # Opções dinâmicas
        def _uniq(dfcol):
            if dfcol not in df.columns:
                return []
            vals = [str(x) for x in df[dfcol].dropna().unique()]
            vals = [v.strip() for v in vals if v.strip() != ""]
            return sorted(vals, key=lambda s: s.lower())

        opcoes_ref    = ["(Todos)"] + _uniq("Referência")
        opcoes_marca  = ["(Todos)"] + _uniq("Marca")
        opcoes_tipo   = ["(Todos)"] + _uniq("Tipo Sugestão")
        opcoes_vend   = ["(Todos)"] + _uniq("Vendedor")
        opcoes_acao   = ["(Todos)"] + _uniq("Ação Comprador")
        opcoes_compr  = ["(Todos)"] + _uniq("Comentário Comprador")
        opcoes_oc     = ["(Todos)"] + _uniq("Ordem Compra")
        opcoes_cod    = ["(Todos)"] + _uniq("Código")
        opcoes_desc   = ["(Todos)"] + _uniq("Descrição Código")
        opcoes_data   = ["(Todos)"] + _uniq("Data Lançamento")

        with st.expander("Filtros", expanded=True):
            colf1, colf2, colf3 = st.columns(3)
            colf4, colf5, colf6 = st.columns(3)
            colf7, colf8, colf9 = st.columns(3)

            filtro_ref = colf1.selectbox("Filtrar por Referência", options=opcoes_ref, key="f_ref")
            filtro_marca = colf2.selectbox("Filtrar por Marca", options=opcoes_marca, key="f_marca")
            filtro_tipo = colf3.selectbox("Filtrar por Tipo Sugestão", options=opcoes_tipo, key="f_tipo")

            filtro_vendedor = colf4.selectbox("Filtrar por Vendedor", options=opcoes_vend, key="f_vendedor")
            filtro_acao = colf5.selectbox("Filtrar por Ação Comprador", options=opcoes_acao, key="f_acao")
            filtro_coment_comp = colf6.selectbox("Filtrar por Comentário Comprador", options=opcoes_compr, key="f_coment_comp")

            filtro_oc = colf7.selectbox("Filtrar por Ordem Compra", options=opcoes_oc, key="f_oc")
            filtro_codigo = colf8.selectbox("Filtrar por Código", options=opcoes_cod, key="f_codigo")
            filtro_data = colf9.selectbox("Filtrar por Data Lançamento", options=opcoes_data, key="f_data")

            # Aplica filtros
            df_filtrado = df.copy()
            if filtro_ref != "(Todos)":
                df_filtrado = df_filtrado[df_filtrado["Referência"] == filtro_ref]
            if filtro_marca != "(Todos)":
                df_filtrado = df_filtrado[df_filtrado["Marca"] == filtro_marca]
            if filtro_tipo != "(Todos)":
                df_filtrado = df_filtrado[df_filtrado["Tipo Sugestão"] == filtro_tipo]
            if filtro_vendedor != "(Todos)":
                df_filtrado = df_filtrado[df_filtrado["Vendedor"] == filtro_vendedor]
            if filtro_acao != "(Todos)":
                df_filtrado = df_filtrado[df_filtrado["Ação Comprador"] == filtro_acao]
            if filtro_coment_comp != "(Todos)":
                df_filtrado = df_filtrado[df_filtrado["Comentário Comprador"] == filtro_coment_comp]
            if filtro_oc != "(Todos)":
                df_filtrado = df_filtrado[df_filtrado["Ordem Compra"] == filtro_oc]
            if filtro_codigo != "(Todos)":
                df_filtrado = df_filtrado[df_filtrado["Código"] == filtro_codigo]
            if filtro_data != "(Todos)":
                df_filtrado = df_filtrado[df_filtrado["Data Lançamento"] == filtro_data]

            # Ordem e exibição
            colunas_ordem = [
                "Referência", "Quantidade", "Marca", "Tipo Sugestão", "Comentário Vendedor",
                "Vendedor", "Ação Comprador", "Comentário Comprador",
                "Ordem Compra", "Código", "Descrição Código", "Data Lançamento"
            ]
            colunas_existentes = [c for c in colunas_ordem if c in df_filtrado.columns]
            outras = [c for c in df_filtrado.columns if c not in colunas_existentes]
            df_exibir = df_filtrado[colunas_existentes + outras]
            if "Referência" in df_exibir.columns:
                df_exibir = df_exibir.sort_values(by=["Referência"], ascending=True)

            # Botões
            colb1, colb2, colb3 = st.columns([0.2, 0.2, 0.6])
            if colb1.button("🔄 Recarregar"):
                carregar_sugestoes.clear()
                _rerun()
            if colb2.button("🧽 Limpar filtros"):
                st.session_state["_clear_filters_request"] = True
                _rerun()

            # Exportar Excel
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                df_exibir.to_excel(writer, index=False, sheet_name="Consulta")
            buffer.seek(0)
            colb3.download_button(
                label="📥 Exportar Excel",
                data=buffer.getvalue(),
                file_name="consulta_sugestoes.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

        # Tabela
        st.dataframe(df_exibir, use_container_width=True, hide_index=True)
        st.caption(f"Total de registros: {len(df_exibir)}")

    except Exception as ex:
        st.error("Erro ao consultar (API).")
        st.exception(ex)
