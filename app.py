import streamlit as st
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
from streamlit_calendar import calendar

st.set_page_config(page_title='Bella - Gestión', layout='wide')

# --- CONFIGURACIÓN DE CONEXIÓN ---
DB_URL = "postgresql://bella:fibsr3wpR7abjxBBW4sKnuTQZIbeHUbZ@dpg-d9vhrkc9v7es73905ogg-a.virginia-postgres.render.com/belladb_d5of"

def get_connection():
    return psycopg2.connect(DB_URL)

def fetch_query(query, params=None):
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params)
                return cur.fetchall()
    except Exception as e:
        st.error(f"Error de base de datos: {e}")
        return []

def execute_query(query, params=None):
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                conn.commit()
    except Exception as e:
        st.error(f"Error al ejecutar: {e}")

# --- NAVEGACIÓN ---
with st.sidebar:
    st.title("✨ Bella")
    menu = st.radio("Menú", ["🏠 Inicio", "👥 Clientes", "📅 Turnos", "💄 Tratamientos"])

# --- SECCIÓN CLIENTES (CRUD CON TELÉFONO) ---
if menu == "👥 Clientes":
    st.title("Gestión de Clientes e Historias Clínicas")
    
    with st.expander("➕ Nuevo Cliente"):
        with st.form("form_nuevo_cliente"):
            c1, c2 = st.columns(2)
            nom = c1.text_input("Nombre *")
            ape = c2.text_input("Apellido *")
            edad = c1.number_input("Edad *", 0, 120, step=1)
            tel = c2.text_input("Teléfono / WhatsApp *")
            email = st.text_input("Email")
            
            if st.form_submit_button("Registrar"):
                if nom and ape and tel and edad > 0:
                    execute_query("""INSERT INTO clientes (nombre, apellido, edad, telefono, email) 
                                   VALUES (%s, %s, %s, %s, %s)""", 
                                (nom, ape, edad, tel, email))
                    st.success("Cliente registrado")
                    st.rerun()
                else:
                    st.error("Completa los campos obligatorios (*)")

    clientes = fetch_query("SELECT * FROM clientes ORDER BY id DESC")
    if clientes:
        st.subheader("Listado de Clientes")
        st.dataframe(pd.DataFrame(clientes), use_container_width=True)

# --- OTRAS SECCIONES (SIMPLIFICADAS PARA BREVEDAD) ---
elif menu == "🏠 Inicio":
    st.title("Agenda Bella")
    turnos = fetch_query("SELECT fecha_inicio as start, 'Turno' as title FROM turnos")
    calendar(events=turnos, options={"locale": "es", "initialView": "timeGridWeek"})
