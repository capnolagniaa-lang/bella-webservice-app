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

# --- SECCIÓN CLIENTES (CRUD COMPLETO) ---
if menu == "👥 Clientes":
    st.title("Gestión de Clientes e Historias Clínicas")
    
    with st.expander("➕ Nuevo Cliente"):
        with st.form("form_nuevo_cliente"):
            c1, c2 = st.columns(2)
            nom = c1.text_input("Nombre")
            ape = c2.text_input("Apellido")
            edad = c1.number_input("Edad", 0, 120)
            email = c2.text_input("Email")
            if st.form_submit_button("Registrar"):
                if nom and ape:
                    with get_connection() as conn:
                        with conn.cursor() as cur:
                            cur.execute("INSERT INTO clientes (nombre, apellido, edad, email) VALUES (%s, %s, %s, %s) RETURNING id", (nom, ape, edad, email))
                            new_id = cur.fetchone()[0]
                            cur.execute("INSERT INTO historias_clinicas (cliente_id, notas) VALUES (%s, %s)", (new_id, "Nueva historia creada."))
                            conn.commit()
                    st.success(f"Cliente {nom} registrado con éxito.")
                    st.rerun()

    clientes = fetch_query("SELECT * FROM clientes ORDER BY id DESC")
    if clientes:
        st.subheader("Listado de Clientes")
        df_c = pd.DataFrame(clientes)
        st.dataframe(df_c, use_container_width=True)

        sel_c = st.selectbox("Seleccionar Cliente para gestionar:", clientes, format_func=lambda x: f"{x['nombre']} {x['apellido']}")
        
        if sel_c:
            col_edit, col_del = st.columns(2)
            with col_edit:
                st.markdown("### 📝 Editar Datos / Historia")
                with st.form("edit_c"):
                    new_nom = st.text_input("Nombre", value=sel_c['nombre'])
                    new_email = st.text_input("Email", value=sel_c['email'])
                    historia = fetch_query("SELECT notas FROM historias_clinicas WHERE cliente_id = %s", (sel_c['id'],))
                    notas_val = historia[0]['notas'] if historia else ""
                    new_notas = st.text_area("Historia Clínica", value=notas_val)
                    if st.form_submit_button("Guardar Cambios"):
                        execute_query("UPDATE clientes SET nombre=%s, email=%s WHERE id=%s", (new_nom, new_email, sel_c['id']))
                        execute_query("UPDATE historias_clinicas SET notas=%s, fecha_actualizacion=NOW() WHERE cliente_id=%s", (new_notas, sel_c['id']))
                        st.success("Información actualizada correctamente")
                        st.rerun()
            with col_del:
                st.markdown("### ⚠️ Eliminar")
                if st.button("🗑️ Borrar Cliente Permanentemente"):
                    execute_query("DELETE FROM clientes WHERE id = %s", (sel_c['id'],))
                    st.warning("Cliente y su historia clínica eliminados")
                    st.rerun()

# --- SECCIÓN TRATAMIENTOS ---
elif menu == "💄 Tratamientos":
    st.title("Catálogo de Servicios")
    with st.form("n_t"):
        n = st.text_input("Servicio")
        p = st.number_input("Precio", min_value=0.0)
        if st.form_submit_button("Agregar"):
            execute_query("INSERT INTO tratamientos (nombre, precio) VALUES (%s, %s)", (n, p))
            st.rerun()
    t_data = fetch_query("SELECT * FROM tratamientos")
    if t_data: st.table(pd.DataFrame(t_data))

# --- SECCIÓN TURNOS ---
elif menu == "📅 Turnos":
    st.title("Gestión de Turnos")
    cl = fetch_query("SELECT id, nombre, apellido FROM clientes")
    tr = fetch_query("SELECT id, nombre FROM tratamientos")
    if cl and tr:
        with st.form("n_turno"):
            c = st.selectbox("Cliente", cl, format_func=lambda x: f"{x['nombre']} {x['apellido']}")
            t = st.selectbox("Tratamiento", tr, format_func=lambda x: x['nombre'])
            d = st.date_input("Día")
            h = st.time_input("Hora")
            if st.form_submit_button("Agendar"):
                f_inicio = datetime.combine(d, h).strftime('%Y-%m-%d %H:%M:%S')
                execute_query("INSERT INTO turnos (cliente_id, tratamiento_id, fecha_inicio) VALUES (%s, %s, %s)", (c['id'], t['id'], f_inicio))
                st.success("Turno agendado")

# --- INICIO (DASHBOARD & CALENDARIO) ---
elif menu == "🏠 Inicio":
    st.title("Agenda Bella")
    
    query = """
        SELECT 
            t.fecha_inicio::text as start, 
            concat(c.nombre, ' ', c.apellido, ' - ', tr.nombre) as title
        FROM turnos t 
        JOIN clientes c ON t.cliente_id = c.id 
        JOIN tratamientos tr ON t.tratamiento_id = tr.id
    """
    turnos_data = fetch_query(query)
    
    if turnos_data:
        calendar(events=turnos_data, options={
            "locale": "es", 
            "initialView": "timeGridWeek", 
            "slotMinTime": "07:00:00", 
            "slotMaxTime": "22:00:00",
            "headerToolbar": {"left": "prev,next today", "center": "title", "right": "dayGridMonth,timeGridWeek,timeGridDay"}
        })
    else:
        st.info("No hay turnos agendados en el sistema.")
