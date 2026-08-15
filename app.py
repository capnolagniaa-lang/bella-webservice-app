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

# --- SECCIÓN CLIENTES ---
if menu == "👥 Clientes":
    st.title("Gestión de Clientes")
    
    with st.expander("➕ Nuevo Cliente"):
        with st.form("nuevo_c"):
            c1, c2 = st.columns(2)
            nom = c1.text_input("Nombre *")
            ape = c2.text_input("Apellido *")
            ed = c1.number_input("Edad", 0, 120)
            tel = c2.text_input("Teléfono / WhatsApp *")
            em = st.text_input("Email")
            if st.form_submit_button("Registrar"):
                if nom and ape and tel:
                    execute_query("INSERT INTO clientes (nombre, apellido, edad, telefono, email) VALUES (%s,%s,%s,%s,%s)", (nom, ape, ed, tel, em))
                    st.success("Cliente guardado")
                    st.rerun()

    clientes = fetch_query("SELECT * FROM clientes ORDER BY apellido ASC")
    if clientes:
        sel_c = st.selectbox("Buscar Cliente para editar/ver:", clientes, format_func=lambda x: f"{x['nombre']} {x['apellido']}")
        if sel_c:
            with st.form("edit_c"):
                st.subheader(f"Perfil de {sel_c['nombre']} {sel_c['apellido']}")
                c1, c2 = st.columns(2)
                u_nom = c1.text_input("Nombre", value=sel_c['nombre'])
                u_ape = c2.text_input("Apellido", value=sel_c['apellido'])
                u_ed = c1.number_input("Edad", 0, 120, value=int(sel_c['edad']) if sel_c['edad'] else 0)
                u_tel = c2.text_input("Teléfono", value=str(sel_c['telefono']) if sel_c['telefono'] else "")
                u_em = st.text_input("Email", value=sel_c['email'])
                
                # Historia Clínica
                hc_data = fetch_query("SELECT notas FROM historias_clinicas WHERE cliente_id = %s", (sel_c['id'],))
                u_notas = st.text_area("Historia Clínica / Notas de Salud", value=hc_data[0]['notas'] if hc_data else "")
                
                if st.form_submit_button("Guardar Cambios"):
                    execute_query("UPDATE clientes SET nombre=%s, apellido=%s, edad=%s, telefono=%s, email=%s WHERE id=%s", 
                                  (u_nom, u_ape, u_ed, u_tel, u_em, sel_c['id']))
                    # Upsert historia clínica
                    execute_query("INSERT INTO historias_clinicas (cliente_id, notas) VALUES (%s, %s) ON CONFLICT (cliente_id) DO UPDATE SET notas = EXCLUDED.notas", (sel_c['id'], u_notas))
                    st.success("Información actualizada")
                    st.rerun()

# --- SECCIÓN TURNOS ---
elif menu == "📅 Turnos":
    st.title("Agenda de Turnos")
    cls = fetch_query("SELECT id, nombre, apellido FROM clientes ORDER BY nombre")
    trats = fetch_query("SELECT id, nombre, precio FROM tratamientos ORDER BY nombre")
    
    if not cls: st.warning("Primero debes registrar clientes.")
    elif not trats: st.info("No hay tratamientos cargados en el catálogo.")
    else:
        with st.form("n_turno"):
            c = st.selectbox("Seleccionar Cliente", cls, format_func=lambda x: f"{x['nombre']} {x['apellido']}")
            ts = st.multiselect("Seleccionar Tratamiento(s)", trats, format_func=lambda x: f"{x['nombre']} (${x['precio']})")
            col1, col2 = st.columns(2)
            fecha = col1.date_input("Día")
            hora = col2.time_input("Hora")
            
            if st.form_submit_button("Confirmar Turno"):
                if ts:
                    f_iso = datetime.combine(fecha, hora).strftime('%Y-%m-%d %H:%M:%S')
                    trat_resumen = ", ".join([t['nombre'] for t in ts])
                    # Insertar Turno
                    execute_query("INSERT INTO turnos (cliente_id, fecha_inicio, profesional) VALUES (%s, %s, %s)", 
                                  (c['id'], f_iso, trat_resumen))
                    # Actualizar Historia Clínica automáticamente
                    nota_nueva = f"\n[{fecha}]: {trat_resumen}"
                    execute_query("INSERT INTO historias_clinicas (cliente_id, notas) VALUES (%s, %s) ON CONFLICT (cliente_id) DO UPDATE SET notas = historias_clinicas.notas || EXCLUDED.notas", 
                                  (c['id'], nota_nueva))
                    st.success("Turno agendado y registrado en historia clínica.")
                    st.rerun()
                else:
                    st.error("Selecciona al menos un tratamiento.")

# --- SECCIÓN TRATAMIENTOS ---
elif menu == "💄 Tratamientos":
    st.title("Catálogo de Tratamientos")
    with st.form("add_t"):
        n = st.text_input("Nombre del Servicio")
        p = st.number_input("Precio", min_value=0.0)
        if st.form_submit_button("Agregar"):
            execute_query("INSERT INTO tratamientos (nombre, precio) VALUES (%s, %s)", (n, p))
            st.success("Servicio agregado")
            st.rerun()
    t_df = fetch_query("SELECT * FROM tratamientos")
    if t_df: st.dataframe(pd.DataFrame(t_df), use_container_width=True)

# --- INICIO (CALENDARIO) ---
elif menu == "🏠 Inicio":
    st.title("Agenda Bella")
    data = fetch_query("""
        SELECT t.fecha_inicio::text as start, 
               concat(c.nombre, ' ', c.apellido, ' - ', t.profesional) as title
        FROM turnos t JOIN clientes c ON t.cliente_id = c.id
    """)
    calendar(events=data, options={"locale": "es", "initialView": "timeGridWeek", "slotMinTime": "07:00:00", "slotMaxTime": "22:00:00"})
