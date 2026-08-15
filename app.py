import streamlit as st
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
from streamlit_calendar import calendar

st.set_page_config(page_title='Bella - Gestión Real', layout='wide')

# --- CONFIGURACIÓN DE CONEXIÓN A POSTGRES ---
DB_URL = "postgresql://bella:fibsr3wpR7abjxBBW4sKnuTQZIbeHUbZ@dpg-d9vhrkc9v7es73905ogg-a.virginia-postgres.render.com/belladb_d5of"

def get_connection():
    return psycopg2.connect(DB_URL)

# --- FUNCIONES DE BASE DE DATOS ---
def fetch_query(query, params=None):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            return cur.fetchall()

def execute_query(query, params=None):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            conn.commit()

# --- NAVEGACIÓN ---
with st.sidebar:
    st.title("✨ Bella")
    menu = st.radio("Menú", ["🏠 Inicio", "👥 Clientes", "📅 Turnos", "💄 Tratamientos"])

# --- SECCIÓN TRATAMIENTOS ---
if menu == "💄 Tratamientos":
    st.title("Gestión de Tratamientos")
    with st.expander("➕ Agregar Nuevo Tratamiento"):
        with st.form("nuevo_t"):
            n = st.text_input("Nombre")
            p = st.number_input("Precio", min_value=0.0)
            if st.form_submit_button("Guardar"):
                execute_query("INSERT INTO tratamientos (nombre, precio) VALUES (%s, %s)", (n, p))
                st.success("Agregado")
    
    res = fetch_query("SELECT * FROM tratamientos")
    if res: st.table(pd.DataFrame(res))

# --- SECCIÓN CLIENTES ---
elif menu == "👥 Clientes":
    st.title("Gestión de Clientes")
    with st.expander("➕ Nuevo Cliente"):
        with st.form("n_c"):
            nom = st.text_input("Nombre")
            ape = st.text_input("Apellido")
            email = st.text_input("Email")
            if st.form_submit_button("Crear"):
                execute_query("INSERT INTO clientes (nombre, apellido, email) VALUES (%s, %s, %s)", (nom, ape, email))
                st.success("Cliente creado")
    
    clientes = fetch_query("SELECT * FROM clientes")
    if clientes: st.dataframe(pd.DataFrame(clientes))

# --- SECCIÓN TURNOS ---
elif menu == "📅 Turnos":
    st.title("Agendar Turno")
    clientes = fetch_query("SELECT id, nombre, apellido FROM clientes")
    trats = fetch_query("SELECT id, nombre FROM tratamientos")
    
    if not clientes or not trats:
        st.warning("Carga clientes y tratamientos primero.")
    else:
        with st.form("n_t"):
            c = st.selectbox("Cliente", clientes, format_func=lambda x: f"{x['nombre']} {x['apellido']}")
            t = st.selectbox("Tratamiento", trats, format_func=lambda x: x['nombre'])
            d = st.date_input("Fecha")
            h = st.time_input("Hora")
            p = st.text_input("Profesional")
            if st.form_submit_button("Agendar"):
                start_dt = f"{d} {h}"
                execute_query("INSERT INTO turnos (cliente_id, tratamiento_id, profesional, fecha_inicio) VALUES (%s, %s, %s, %s)", 
                              (c['id'], t['id'], p, start_dt))
                st.success("Turno agendado")

# --- INICIO ---
elif menu == "🏠 Inicio":
    st.title("Panel de Control - Bella")
    
    turnos_data = fetch_query("""
        SELECT t.profesional as resource, t.fecha_inicio as start, 
               concat(c.nombre, ' - ', tr.nombre) as title 
        FROM turnos t 
        JOIN clientes c ON t.cliente_id = c.id 
        JOIN tratamientos tr ON t.tratamiento_id = tr.id
    """)

    calendar_options = {
        "locale": "es",
        "initialView": "timeGridWeek",
        "slotMinTime": "07:00:00",
        "slotMaxTime": "22:00:00",
        "height": 600,
    }
    calendar(events=turnos_data, options=calendar_options)
