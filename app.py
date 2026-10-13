import functools
import inspect
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from streamlit_calendar import calendar

import db

st.set_page_config(page_title="Bella · Gestión", page_icon="✨", layout="wide")

TZ = ZoneInfo("America/Argentina/Buenos_Aires")
ss = st.session_state
# Al cerrar un diálogo con la X se recarga la página para que el calendario quede listo para otro clic.
DIALOGO_KW = {"on_dismiss": "rerun"} if "on_dismiss" in inspect.signature(st.dialog).parameters else {}

ESTADOS = {
    "reservado": ("Reservado", "#5B7FE8"),
    "confirmado": ("Confirmado", "#1F9D6B"),
    "completado": ("Completado", "#8A63C9"),
    "ausente": ("Ausente", "#D9534F"),
    "cancelado": ("Cancelado", "#A3A3A3"),
}
OCUPAN_AGENDA = ("reservado", "confirmado", "completado")
PENDIENTES = ("reservado", "confirmado")
ORIGENES = ["Instagram", "Facebook", "TikTok", "Google", "Recomendación", "Pasó por el local", "Otro"]
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]

CONFIG_DEFAULT = {
    "negocio": "Bella",
    "link_resena": "",
    "tpl_recordatorio": (
        "¡Hola {nombre}! 💖 Te recordamos tu turno en {negocio} el {fecha} a las {hora} hs "
        "para {servicios}. ¿Nos confirmás? Si no podés venir avisanos así lo reprogramamos 🙌"
    ),
    "tpl_reactivacion": (
        "¡Hola {nombre}! ✨ Hace un tiempito que no te vemos por {negocio} y te extrañamos. "
        "Esta semana tenemos turnos disponibles, ¿te reservamos uno? 💅"
    ),
    "tpl_cumpleanos": (
        "¡Feliz cumpleaños, {nombre}! 🎂 En {negocio} queremos festejarte con un 10% OFF "
        "en tu próximo tratamiento durante este mes. ¡Te esperamos!"
    ),
    "tpl_segunda_visita": (
        "¡Hola {nombre}! Gracias por elegir {negocio} 💖 Para mantener los resultados de tu "
        "{servicios} te recomendamos volver en unas semanas. ¿Te reservamos un turno?"
    ),
    "tpl_resena": (
        "¡Hola {nombre}! Gracias por visitarnos hoy en {negocio} 💖 Si te gustó la atención, "
        "¿nos dejarías una reseña? Nos ayuda muchísimo 🙏 {link_resena}"
    ),
}
PLANTILLAS = {
    "tpl_recordatorio": "Recordatorio de turno",
    "tpl_reactivacion": "Reactivación (clientes que no vuelven)",
    "tpl_cumpleanos": "Cumpleaños",
    "tpl_segunda_visita": "Segunda visita",
    "tpl_resena": "Pedido de reseña",
}

st.markdown(
    """
    <style>
    [data-testid="stMetric"] {background: rgba(214,69,122,.06); border: 1px solid rgba(214,69,122,.18);
        border-radius: 14px; padding: 14px 16px;}
    .chip {display:inline-block; padding:2px 10px; border-radius:999px; color:#fff; font-size:.8rem;
        font-weight:600; margin-right:6px;}
    .muted {opacity:.7; font-size:.9rem;}
    </style>
    """,
    unsafe_allow_html=True,
)

CALENDAR_CSS = """
.fc { font-family: inherit; }
.fc-event { cursor: pointer; border-radius: 6px; padding: 1px 3px; font-size: .82rem; }
.fc-toolbar-title { font-size: 1.15rem !important; text-transform: capitalize; }
.fc-col-header-cell-cushion { text-transform: capitalize; }
.fc .fc-button-primary { background: #D6457A; border-color: #D6457A; }
.fc .fc-button-primary:not(:disabled).fc-button-active,
.fc .fc-button-primary:not(:disabled):active { background: #A8305C; border-color: #A8305C; }
.fc .fc-timegrid-now-indicator-line { border-color: #D6457A; }
"""


# --------------------------------------------------------------------------- utilidades

def ahora():
    return datetime.now(TZ).replace(tzinfo=None, microsecond=0)


def naive(dt):
    """Fecha 'de pared' sin zona horaria (las columnas pueden ser timestamp o timestamptz)."""
    if dt is None or pd.isna(dt):
        return None
    if isinstance(dt, pd.Timestamp):
        dt = dt.to_pydatetime()
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def parse_iso(value):
    """Fechas que devuelve el calendario (configurado en UTC = hora de pared)."""
    return naive(datetime.fromisoformat(value.replace("Z", "+00:00")))


def proximo_horario():
    t = ahora() + timedelta(minutes=30)
    t = t.replace(minute=0 if t.minute < 30 else 30, second=0)
    if t.hour >= 20:
        t = (t + timedelta(days=1)).replace(hour=10, minute=0)
    elif t.hour < 9:
        t = t.replace(hour=10, minute=0)
    return t


def money(value):
    return "$" + f"{float(value or 0):,.0f}".replace(",", ".")


def fecha_larga(dt):
    return f"{DIAS[dt.weekday()]} {dt.day} de {MESES[dt.month - 1]}"


def chip(estado):
    label, color = ESTADOS.get(estado, (estado, "#777"))
    return f'<span class="chip" style="background:{color}">{label}</span>'


def telefono_wa(telefono):
    digits = re.sub(r"\D", "", str(telefono or ""))
    if digits.startswith("00"):
        digits = digits[2:]
    if not digits:
        return None
    if not digits.startswith("54"):
        digits = digits.lstrip("0")
        digits = ("549" if len(digits) == 10 else "54") + digits
    return digits


def link_wa(telefono, texto):
    numero = telefono_wa(telefono)
    return f"https://wa.me/{numero}?text={quote(texto)}" if numero else None


class _SafeDict(dict):
    def __missing__(self, key):
        return ""


def mensaje(clave, **datos):
    cfg = q_config()
    datos.setdefault("negocio", cfg["negocio"])
    datos.setdefault("link_resena", cfg["link_resena"])
    return cfg[clave].format_map(_SafeDict(datos)).strip()


def datos_turno_msg(t):
    ini = naive(t["inicio"])
    servicios = t.get("servicios")
    return dict(nombre=t["nombre"], fecha=fecha_larga(ini), hora=ini.strftime("%H:%M"),
                servicios=servicios if isinstance(servicios, str) and servicios else "tu tratamiento")


def flash(texto, icono="✅"):
    ss.setdefault("flash", []).append((texto, icono))


def invalidar():
    st.cache_data.clear()
    ss.cal_key = ss.get("cal_key", 0) + 1


def abrir_dialogo(tipo, **kwargs):
    ss.dialogo = (tipo, kwargs)


def ir_a(pagina, cliente_id=None):
    ss.goto = (pagina, cliente_id)


def seguro(fn):
    """Muestra los errores de base de datos en pantalla en lugar de romper la página."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except db.DBError as e:
            st.error(f"⚠️ {e}")
    return wrapper


# --------------------------------------------------------------------------- lecturas

@st.cache_data(ttl=300, show_spinner=False)
def q_config():
    cfg = dict(CONFIG_DEFAULT)
    cfg.update({r["clave"]: r["valor"] for r in db.fetch("SELECT clave, valor FROM configuracion")})
    return cfg


@st.cache_data(ttl=120, show_spinner=False)
def q_clientes():
    return db.fetch(
        """SELECT id, nombre, apellido, edad, telefono, email, fecha_nacimiento, origen,
                  acepta_mensajes, creado_en, domicilio
           FROM clientes ORDER BY apellido, nombre"""
    )


@st.cache_data(ttl=300, show_spinner=False)
def q_tratamientos():
    rows = db.fetch(
        "SELECT id, nombre, precio, duracion_min, activo, descripcion FROM tratamientos ORDER BY nombre"
    )
    for r in rows:
        r["precio"] = float(r["precio"] or 0)
    return rows


TURNO_COLS = ["id", "cliente_id", "inicio", "fin", "servicios", "profesional", "estado", "notas",
              "total", "nombre", "apellido", "telefono", "acepta_mensajes"]


@st.cache_data(ttl=60, show_spinner=False)
def q_turnos():
    rows = db.fetch(
        """SELECT t.id, t.cliente_id, t.fecha_inicio AS inicio, t.fecha_fin AS fin, t.servicios,
                  t.profesional, t.estado, t.notas, t.total, c.nombre, c.apellido, c.telefono,
                  c.acepta_mensajes
           FROM turnos t JOIN clientes c ON c.id = t.cliente_id
           ORDER BY t.fecha_inicio"""
    )
    for r in rows:
        r["inicio"] = naive(r["inicio"])
        r["fin"] = naive(r["fin"]) or r["inicio"] + timedelta(hours=1)
        r["total"] = float(r["total"] or 0)
    return rows


def df_turnos():
    df = pd.DataFrame(q_turnos(), columns=TURNO_COLS)
    df["inicio"] = pd.to_datetime(df["inicio"])
    df["fin"] = pd.to_datetime(df["fin"])
    df["total"] = df["total"].astype(float)
    df["cliente"] = df["nombre"].fillna("") + " " + df["apellido"].fillna("")
    return df


def df_clientes():
    cl = pd.DataFrame(q_clientes(), columns=["id", "nombre", "apellido", "edad", "telefono", "email",
                                             "fecha_nacimiento", "origen", "acepta_mensajes", "creado_en",
                                             "domicilio"])
    t = df_turnos()
    now = pd.Timestamp(ahora())
    visitas = t[t["estado"].isin(OCUPAN_AGENDA) & (t["inicio"] <= now)]
    completados = t[t["estado"] == "completado"]
    futuros = t[t["estado"].isin(PENDIENTES) & (t["inicio"] > now)]

    def por_cliente(serie):
        # Se mapea con un dict: con Series vacías de fechas, pandas falla al alinear tipos.
        return cl["id"].map(serie.to_dict())

    cl["cliente"] = cl["nombre"] + " " + cl["apellido"]
    cl["visitas"] = por_cliente(visitas.groupby("cliente_id")["id"].count()).fillna(0).astype(int)
    cl["gastado"] = por_cliente(completados.groupby("cliente_id")["total"].sum()).fillna(0.0).astype(float)
    cl["ultima_visita"] = pd.to_datetime(por_cliente(visitas.groupby("cliente_id")["inicio"].max()))
    cl["proximo_turno"] = pd.to_datetime(por_cliente(futuros.groupby("cliente_id")["inicio"].min()))
    cl["ultimo_servicio"] = por_cliente(visitas.sort_values("inicio").groupby("cliente_id")["servicios"].last())
    cl["dias_sin_venir"] = (now - cl["ultima_visita"]).dt.days
    cl["fecha_nacimiento"] = pd.to_datetime(cl["fecha_nacimiento"], errors="coerce")
    cl["creado_en"] = pd.to_datetime(cl["creado_en"], errors="coerce")
    return cl


def superposiciones(inicio, fin, excluir_id=None):
    return db.fetch(
        """SELECT t.fecha_inicio, t.fecha_fin, c.nombre, c.apellido
           FROM turnos t JOIN clientes c ON c.id = t.cliente_id
           WHERE t.estado IN ('reservado', 'confirmado', 'completado')
             AND t.fecha_inicio < %s AND t.fecha_fin > %s AND t.id <> %s
           ORDER BY t.fecha_inicio""",
        (fin, inicio, excluir_id or -1),
    )


# --------------------------------------------------------------------------- escrituras

def _anotar_historia(cur, cliente_id, inicio, servicios):
    cur.execute(
        """INSERT INTO historias_clinicas (cliente_id, notas) VALUES (%s, %s)
           ON CONFLICT (cliente_id) DO UPDATE
           SET notas = COALESCE(NULLIF(historias_clinicas.notas, '') || E'\\n', '') || EXCLUDED.notas""",
        (cliente_id, f"[{naive(inicio):%d/%m/%Y %H:%M}] {servicios or 'Turno'}"),
    )


def cambiar_estado(ids, estado):
    """Cambia el estado; al completar un turno se deja registro en la historia clínica."""
    with db.transaction() as cur:
        cur.execute("SELECT id, cliente_id, fecha_inicio, servicios, estado FROM turnos WHERE id = ANY(%s)",
                    (list(ids),))
        for t in cur.fetchall():
            if estado == "completado" and t["estado"] != "completado":
                _anotar_historia(cur, t["cliente_id"], t["fecha_inicio"], t["servicios"])
        cur.execute("UPDATE turnos SET estado = %s WHERE id = ANY(%s)", (estado, list(ids)))


def guardar_config(valores):
    with db.transaction() as cur:
        for clave, valor in valores.items():
            cur.execute(
                """INSERT INTO configuracion (clave, valor) VALUES (%s, %s)
                   ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor""",
                (clave, valor),
            )


# --------------------------------------------------------------------------- diálogos

@st.dialog("Nuevo turno", width="large", **DIALOGO_KW)
@seguro
def dialogo_nuevo_turno(inicio=None, duracion=None, cliente_id=None):
    inicio = inicio or proximo_horario()
    tratamientos = [t for t in q_tratamientos() if t["activo"]]
    clientes = {c["id"]: c for c in q_clientes()}

    modo = st.radio("Cliente", ["Existente", "Nuevo"], horizontal=True,
                    index=0 if clientes else 1, label_visibility="collapsed")
    if modo == "Existente":
        ids = list(clientes)
        cli_id = st.selectbox(
            "Cliente", ids, index=ids.index(cliente_id) if cliente_id in clientes else None,
            format_func=lambda i: f"{clientes[i]['nombre']} {clientes[i]['apellido']} · {clientes[i]['telefono'] or 's/tel'}",
            placeholder="Buscá por nombre, apellido o teléfono…",
        )
        nuevo = None
    else:
        cli_id = None
        c1, c2, c3 = st.columns(3)
        nuevo = dict(nombre=c1.text_input("Nombre *").strip(), apellido=c2.text_input("Apellido *").strip(),
                     telefono=c3.text_input("WhatsApp *").strip())

    trat_ids = st.multiselect(
        "Tratamientos *", [t["id"] for t in tratamientos],
        format_func=lambda i: next(f"{t['nombre']} · {money(t['precio'])} · {t['duracion_min']} min"
                                   for t in tratamientos if t["id"] == i),
        placeholder="Elegí uno o más tratamientos",
    )
    elegidos = [t for t in tratamientos if t["id"] in trat_ids]
    duracion_sugerida = sum(t["duracion_min"] for t in elegidos) or duracion or 60
    precio_lista = sum(t["precio"] for t in elegidos)

    c1, c2, c3 = st.columns(3)
    fecha = c1.date_input("Fecha", inicio.date(), format="DD/MM/YYYY")
    hora = c2.time_input("Hora", inicio.time(), step=timedelta(minutes=15))
    minutos = c3.number_input("Duración (min)", 15, 720, min(720, int(duracion_sugerida)), step=15)
    c1, c2, c3 = st.columns(3)
    total = c1.number_input("Precio final ($)", 0.0, value=float(precio_lista), step=500.0,
                            help="Precio de lista: suma de los tratamientos. Podés aplicar un descuento.")
    estado = c2.selectbox("Estado", list(PENDIENTES), format_func=lambda e: ESTADOS[e][0])
    profesional = c3.text_input("Profesional (opcional)")
    notas = st.text_area("Notas del turno", placeholder="Ej.: trae su propio esmalte, alergia a…", height=80)

    ini = datetime.combine(fecha, hora).replace(second=0)
    fin = ini + timedelta(minutes=int(minutos))
    st.caption(f"🕒 {fecha_larga(ini).capitalize()} de {ini:%H:%M} a {fin:%H:%M} hs")
    if ini < ahora():
        st.info("La fecha elegida ya pasó: el turno quedará cargado como histórico.")

    forzar = True
    choques = superposiciones(ini, fin)
    if choques:
        detalle = ", ".join(f"{c['nombre']} {c['apellido']} ({naive(c['fecha_inicio']):%H:%M}–{naive(c['fecha_fin']):%H:%M})"
                            for c in choques)
        st.warning(f"Se superpone con: {detalle}")
        forzar = st.checkbox("Agendar igual (hay más de una profesional/camilla)")

    if st.button("Confirmar turno", type="primary", width="stretch", disabled=not forzar):
        if modo == "Existente" and not cli_id:
            st.error("Elegí un cliente.")
            return
        if nuevo is not None and not all(nuevo.values()):
            st.error("Completá nombre, apellido y WhatsApp del cliente nuevo.")
            return
        if not elegidos:
            st.error("Elegí al menos un tratamiento.")
            return
        servicios = ", ".join(t["nombre"] for t in elegidos)
        with db.transaction() as cur:
            if nuevo is not None:
                cur.execute("INSERT INTO clientes (nombre, apellido, telefono) VALUES (%s, %s, %s) RETURNING id",
                            (nuevo["nombre"], nuevo["apellido"], nuevo["telefono"]))
                cli_id = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO turnos (cliente_id, fecha_inicio, fecha_fin, servicios, profesional,
                                       estado, notas, total)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (cli_id, ini, fin, servicios, profesional or None, estado, notas or None, total),
            )
            turno_id = cur.fetchone()["id"]
            for t in elegidos:
                cur.execute("INSERT INTO turno_tratamientos (turno_id, tratamiento_id, precio) VALUES (%s, %s, %s)",
                            (turno_id, t["id"], t["precio"]))
        ss.cal_fecha = ini.date().isoformat()
        invalidar()
        flash(f"Turno agendado: {fecha_larga(ini)} {ini:%H:%M} hs")
        st.rerun()


@st.dialog("Detalle del turno", width="large", **DIALOGO_KW)
@seguro
def dialogo_turno(turno_id):
    t = db.fetch_one(
        """SELECT t.id, t.cliente_id, t.fecha_inicio AS inicio, t.fecha_fin AS fin, t.servicios,
                  t.profesional, t.estado, t.notas, t.total, c.nombre, c.apellido, c.telefono
           FROM turnos t JOIN clientes c ON c.id = t.cliente_id WHERE t.id = %s""",
        (turno_id,),
    )
    if not t:
        st.error("Este turno ya no existe.")
        return
    ini = naive(t["inicio"])
    fin = naive(t["fin"]) or ini + timedelta(hours=1)

    st.markdown(f"### {t['nombre']} {t['apellido']} {chip(t['estado'])}", unsafe_allow_html=True)
    st.markdown(f"**{fecha_larga(ini).capitalize()}**, {ini:%H:%M} a {fin:%H:%M} hs · {t['servicios'] or 'Turno'}"
                f" · {money(t['total'])}" + (f" · con {t['profesional']}" if t["profesional"] else ""))

    c1, c2, c3 = st.columns(3)
    url = link_wa(t["telefono"], mensaje("tpl_recordatorio", **datos_turno_msg(t)))
    if url:
        c1.link_button("💬 Recordatorio por WhatsApp", url, width="stretch")
    else:
        c1.caption("Sin teléfono cargado")
    if t["estado"] in PENDIENTES and c2.button("✅ Marcar completado", width="stretch"):
        cambiar_estado([turno_id], "completado")
        invalidar()
        flash("Turno completado y registrado en la historia clínica")
        st.rerun()
    if c3.button("👤 Ver ficha del cliente", width="stretch"):
        ir_a("👥 Clientes", t["cliente_id"])
        st.rerun()

    with st.form(f"editar_turno_{turno_id}", border=True):
        st.markdown("**Editar / reprogramar**")
        c1, c2, c3 = st.columns(3)
        fecha = c1.date_input("Fecha", ini.date(), format="DD/MM/YYYY")
        hora = c2.time_input("Hora", ini.time(), step=timedelta(minutes=15))
        minutos = c3.number_input("Duración (min)", 15, 720,
                                  min(720, max(15, int((fin - ini).total_seconds() // 60))), step=15)
        c1, c2, c3 = st.columns(3)
        estados = list(ESTADOS)
        estado = c1.selectbox("Estado", estados, index=estados.index(t["estado"]) if t["estado"] in ESTADOS else 0,
                              format_func=lambda e: ESTADOS[e][0])
        total = c2.number_input("Precio final ($)", 0.0, value=float(t["total"] or 0), step=500.0)
        profesional = c3.text_input("Profesional", t["profesional"] or "")
        servicios = st.text_input("Servicios", t["servicios"] or "")
        notas = st.text_area("Notas", t["notas"] or "", height=80)
        if st.form_submit_button("💾 Guardar cambios", type="primary", width="stretch"):
            nuevo_ini = datetime.combine(fecha, hora).replace(second=0)
            nuevo_fin = nuevo_ini + timedelta(minutes=int(minutos))
            with db.transaction() as cur:
                if estado == "completado" and t["estado"] != "completado":
                    _anotar_historia(cur, t["cliente_id"], nuevo_ini, servicios)
                cur.execute(
                    """UPDATE turnos SET fecha_inicio=%s, fecha_fin=%s, estado=%s, total=%s, profesional=%s,
                                         servicios=%s, notas=%s WHERE id=%s""",
                    (nuevo_ini, nuevo_fin, estado, total, profesional or None, servicios, notas or None, turno_id),
                )
            choques = superposiciones(nuevo_ini, nuevo_fin, turno_id) if estado in OCUPAN_AGENDA else []
            if choques:
                flash("Guardado, pero se superpone con otro turno", "⚠️")
            else:
                flash("Turno actualizado")
            ss.cal_fecha = nuevo_ini.date().isoformat()
            invalidar()
            st.rerun()

    with st.expander("🗑️ Eliminar turno"):
        st.caption("Si el cliente canceló, conviene marcarlo como **Cancelado** para conservar el historial.")
        confirmar = st.checkbox("Sí, quiero eliminarlo definitivamente", key=f"del_{turno_id}")
        if st.button("Eliminar", disabled=not confirmar, key=f"del_btn_{turno_id}"):
            db.execute("DELETE FROM turnos WHERE id = %s", (turno_id,))
            invalidar()
            flash("Turno eliminado", "🗑️")
            st.rerun()


def mostrar_dialogo_pendiente():
    tipo, kwargs = ss.pop("dialogo", (None, None))
    if tipo == "nuevo":
        dialogo_nuevo_turno(**kwargs)
    elif tipo == "turno":
        dialogo_turno(**kwargs)


# --------------------------------------------------------------------------- páginas

def fila_turno(t, prefijo, acciones=True, plantilla="tpl_recordatorio"):
    c1, c2, c3, c4 = st.columns([1.1, 3, 1.6, 2.4], vertical_alignment="center")
    c1.markdown(f"**{t['inicio']:%H:%M}**")
    c2.markdown(f"{t['cliente']}  \n<span class='muted'>{t['servicios'] or 'Turno'} · {money(t['total'])}</span>",
                unsafe_allow_html=True)
    c3.markdown(chip(t["estado"]), unsafe_allow_html=True)
    b1, b2, b3 = c4.columns(3)
    url = link_wa(t["telefono"], mensaje(plantilla, **datos_turno_msg(t)))
    if url:
        b1.link_button("💬", url, help="Enviar WhatsApp", width="stretch")
    if b2.button("🔍", key=f"{prefijo}_ver_{t['id']}", help="Ver detalle", width="stretch"):
        abrir_dialogo("turno", turno_id=int(t["id"]))
    if acciones and t["estado"] == "reservado":
        if b3.button("👍", key=f"{prefijo}_conf_{t['id']}", help="Marcar confirmado", width="stretch"):
            cambiar_estado([int(t["id"])], "confirmado")
            invalidar()
            st.rerun()


def pagina_inicio():
    hoy = ahora()
    st.title(f"Hola 👋, hoy es {fecha_larga(hoy)}")
    df = df_turnos()
    clientes = df_clientes()
    if df.empty:
        st.info("Todavía no hay turnos. Cargá tus **tratamientos** y agendá el primer turno desde **📅 Agenda**.")
        return

    dia = pd.Timestamp(hoy.date())
    activos = df[df["estado"].isin(OCUPAN_AGENDA)]
    de_hoy = activos[activos["inicio"].dt.normalize() == dia]
    semana_ini = dia - pd.Timedelta(days=hoy.weekday())
    de_semana = activos[(activos["inicio"] >= semana_ini) & (activos["inicio"] < semana_ini + pd.Timedelta(days=7))]
    mes_ini = dia.replace(day=1)
    del_mes = df[(df["inicio"] >= mes_ini) & (df["inicio"] < mes_ini + pd.offsets.MonthBegin(1))]
    facturado = del_mes.loc[del_mes["estado"] == "completado", "total"].sum()
    proyectado = del_mes.loc[del_mes["estado"].isin(PENDIENTES), "total"].sum()
    ult90 = df[(df["inicio"] >= dia - pd.Timedelta(days=90)) & (df["inicio"] < dia)]
    cerrados = ult90[ult90["estado"].isin(["completado", "ausente"])]
    ausentismo = (cerrados["estado"] == "ausente").mean() * 100 if len(cerrados) else 0
    nuevos = (clientes["creado_en"] >= mes_ini).sum()

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Turnos hoy", len(de_hoy))
    k2.metric("Turnos esta semana", len(de_semana))
    k3.metric("Facturado en el mes", money(facturado), f"+{money(proyectado)} agendado", delta_color="off")
    k4.metric("Clientes nuevos (mes)", int(nuevos))
    k5.metric("Ausentismo (90 días)", f"{ausentismo:.0f}%",
              help="Turnos marcados como ausente sobre el total de turnos cerrados. Los recordatorios por "
                   "WhatsApp 24 h antes son la forma más efectiva de bajarlo.")

    st.write("")
    izq, der = st.columns(2, gap="large")
    with izq:
        st.subheader("📋 Agenda de hoy")
        if de_hoy.empty:
            st.caption("No hay turnos para hoy.")
        for _, t in de_hoy.iterrows():
            fila_turno(t, "hoy", plantilla="tpl_resena" if t["estado"] == "completado" else "tpl_recordatorio")
    with der:
        manana = dia + pd.Timedelta(days=1)
        de_manana = df[(df["inicio"].dt.normalize() == manana) & df["estado"].isin(PENDIENTES)]
        st.subheader("🔔 Recordatorios para mañana")
        st.caption("Enviá el recordatorio y marcá 👍 cuando el cliente confirme.")
        if de_manana.empty:
            st.caption("No hay turnos para mañana.")
        for _, t in de_manana.iterrows():
            fila_turno(t, "man")

    sin_cerrar = df[df["estado"].isin(PENDIENTES) & (df["fin"] < pd.Timestamp(hoy))]
    if not sin_cerrar.empty:
        st.divider()
        st.subheader(f"🧾 Turnos pasados sin cerrar ({len(sin_cerrar)})")
        st.caption("Marcalos como completados o ausentes para que la facturación y el ausentismo sean reales.")
        tabla = sin_cerrar[["id", "inicio", "cliente", "servicios", "total"]].copy()
        tabla.insert(0, "elegir", True)
        editado = st.data_editor(
            tabla, hide_index=True, width="stretch", disabled=["inicio", "cliente", "servicios", "total"],
            column_config={"elegir": st.column_config.CheckboxColumn("✔"), "id": None,
                           "inicio": st.column_config.DatetimeColumn("Fecha", format="DD/MM/YYYY HH:mm"),
                           "total": st.column_config.NumberColumn("Total", format="$%.0f")},
            key="sin_cerrar",
        )
        ids = editado.loc[editado["elegir"], "id"].astype(int).tolist()
        c1, c2, _ = st.columns([1, 1, 3])
        if c1.button(f"✅ Completados ({len(ids)})", disabled=not ids, width="stretch"):
            cambiar_estado(ids, "completado")
            invalidar()
            flash(f"{len(ids)} turnos marcados como completados")
            st.rerun()
        if c2.button(f"🚫 Ausentes ({len(ids)})", disabled=not ids, width="stretch"):
            cambiar_estado(ids, "ausente")
            invalidar()
            flash(f"{len(ids)} turnos marcados como ausentes")
            st.rerun()

    st.divider()
    g1, g2 = st.columns(2, gap="large")
    hechos = df[df["estado"] == "completado"]
    with g1:
        st.subheader("💰 Facturación por semana")
        desde = semana_ini - pd.Timedelta(weeks=11)
        serie = (hechos[hechos["inicio"] >= desde]
                 .assign(semana=lambda d: d["inicio"].dt.to_period("W-SUN").dt.start_time)
                 .groupby("semana")["total"].sum())
        serie = serie.reindex(pd.date_range(desde, semana_ini, freq="7D"), fill_value=0)
        st.bar_chart(serie, color="#D6457A", y_label="$", x_label="Semana (desde el lunes)")
    with g2:
        st.subheader("⭐ Tratamientos más pedidos (90 días)")
        recientes = df[df["estado"].isin(OCUPAN_AGENDA) & (df["inicio"] >= dia - pd.Timedelta(days=90))]
        top = (recientes["servicios"].dropna().str.split(r",\s*").explode().str.strip()
               .loc[lambda s: s != ""].value_counts().head(8))
        if top.empty:
            st.caption("Sin datos todavía.")
        else:
            st.bar_chart(top, color="#8A63C9", horizontal=True, x_label="Turnos")


def pagina_agenda():
    st.title("📅 Agenda")
    ss.setdefault("cal_key", 0)
    ss.setdefault("cal_vista", "timeGridWeek")
    ss.setdefault("cal_fecha", ahora().date().isoformat())

    c1, c2, c3 = st.columns([1.3, 1.3, 4], vertical_alignment="center")
    if c1.button("➕ Nuevo turno", type="primary", width="stretch"):
        abrir_dialogo("nuevo")
    ver_cancelados = c2.toggle("Ver cancelados", value=False)
    c3.markdown(" ".join(chip(e) for e in ESTADOS), unsafe_allow_html=True)

    eventos = []
    for t in q_turnos():
        if t["estado"] == "cancelado" and not ver_cancelados:
            continue
        color = ESTADOS.get(t["estado"], ESTADOS["reservado"])[1]
        eventos.append({
            "id": str(t["id"]),
            "title": f"{t['nombre']} {t['apellido']} · {t['servicios'] or 'Turno'}",
            "start": t["inicio"].isoformat(),
            "end": t["fin"].isoformat(),
            "backgroundColor": color,
            "borderColor": color,
            "textColor": "#ffffff",
        })

    opciones = {
        "locale": "es",
        # El calendario trabaja en "UTC" para que las horas se muestren y devuelvan tal cual
        # están en la base (hora de Argentina), sin depender de la zona del navegador.
        "timeZone": "UTC",
        "now": ahora().replace(second=0).isoformat(),
        "initialView": ss.cal_vista,
        "initialDate": ss.cal_fecha,
        "headerToolbar": {"left": "prev,next today", "center": "title",
                          "right": "dayGridMonth,timeGridWeek,timeGridDay,listWeek"},
        "buttonText": {"today": "Hoy", "month": "Mes", "week": "Semana", "day": "Día", "list": "Lista"},
        "firstDay": 1,
        "slotMinTime": "08:00:00",
        "slotMaxTime": "21:00:00",
        "slotDuration": "00:30:00",
        "snapDuration": "00:15:00",
        "slotLabelFormat": {"hour": "2-digit", "minute": "2-digit", "hour12": False},
        "eventTimeFormat": {"hour": "2-digit", "minute": "2-digit", "hour12": False},
        "allDaySlot": False,
        "nowIndicator": True,
        "selectable": True,
        "selectMirror": True,
        "selectLongPressDelay": 300,
        "editable": True,
        "dayMaxEvents": True,
        "businessHours": {"daysOfWeek": [1, 2, 3, 4, 5, 6], "startTime": "09:00", "endTime": "20:00"},
        "height": 760,
    }
    estado = calendar(
        events=eventos,
        options=opciones,
        custom_css=CALENDAR_CSS,
        callbacks=["select", "eventClick", "eventChange"],
        key=f"agenda_{ss.cal_key}",
    ) or {}
    st.caption("Tip: arrastrá sobre un horario libre para crear un turno, hacé clic en un turno para verlo "
               "y arrastralo para reprogramarlo.")

    callback = estado.get("callback")
    # Cada callback trae la vista activa: se recuerda para que el calendario vuelva a la misma vista.
    vista = (estado.get(callback) or {}).get("view") or {} if callback else {}
    ss.cal_vista = vista.get("type", ss.cal_vista)

    # Cada acción se procesa una sola vez: se cambia la key del calendario para descartar el evento.
    if callback == "select":
        sel = estado["select"]
        ini, fin = parse_iso(sel["start"]), parse_iso(sel["end"])
        if sel.get("allDay"):
            ini = ini.replace(hour=10, minute=0)
            duracion = None
        else:
            minutos = int((fin - ini).total_seconds() // 60)
            duracion = minutos if minutos > 30 else None
        ss.cal_fecha = ini.date().isoformat()
        ss.cal_key += 1
        abrir_dialogo("nuevo", inicio=ini, duracion=duracion)
    elif callback == "eventClick":
        evento = estado["eventClick"]["event"]
        ss.cal_fecha = parse_iso(evento["start"]).date().isoformat()
        ss.cal_key += 1
        abrir_dialogo("turno", turno_id=int(evento["id"]))
    elif callback == "eventChange":
        evento = estado["eventChange"]["event"]
        ini = parse_iso(evento["start"])
        fin = parse_iso(evento["end"]) if evento.get("end") else ini + timedelta(hours=1)
        db.execute("UPDATE turnos SET fecha_inicio = %s, fecha_fin = %s WHERE id = %s", (ini, fin, int(evento["id"])))
        choques = superposiciones(ini, fin, int(evento["id"]))
        if choques:
            flash("Turno movido, pero se superpone con otro", "⚠️")
        else:
            flash(f"Turno movido a {fecha_larga(ini)} {ini:%H:%M} hs", "📅")
        ss.cal_fecha = ini.date().isoformat()
        invalidar()
        st.rerun()


def ficha_cliente(c, turnos):
    st.button("← Volver al listado", on_click=lambda: ss.update(cliente_sel=None))
    edad = c["edad"]
    if pd.notna(c["fecha_nacimiento"]):
        nac = c["fecha_nacimiento"].date()
        hoy = ahora().date()
        edad = hoy.year - nac.year - ((hoy.month, hoy.day) < (nac.month, nac.day))
    st.subheader(f"{c['nombre']} {c['apellido']}")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Visitas", int(c["visitas"]))
    k2.metric("Total gastado", money(c["gastado"]))
    k3.metric("Última visita", c["ultima_visita"].strftime("%d/%m/%Y") if pd.notna(c["ultima_visita"]) else "—")
    k4.metric("Próximo turno", c["proximo_turno"].strftime("%d/%m %H:%M") if pd.notna(c["proximo_turno"]) else "—")

    b1, b2, _ = st.columns([1, 1, 2])
    if b1.button("📅 Agendar turno", type="primary", width="stretch"):
        abrir_dialogo("nuevo", cliente_id=int(c["id"]))
    url = link_wa(c["telefono"], f"¡Hola {c['nombre']}! ")
    if url:
        b2.link_button("💬 Abrir WhatsApp", url, width="stretch")

    tab_datos, tab_hc, tab_turnos = st.tabs(["Datos", "Historia clínica", "Turnos"])
    with tab_datos, st.form(f"cliente_{c['id']}"):
        c1, c2 = st.columns(2)
        nombre = c1.text_input("Nombre *", c["nombre"])
        apellido = c2.text_input("Apellido *", c["apellido"])
        telefono = c1.text_input("WhatsApp", c["telefono"] if isinstance(c["telefono"], str) else "")
        email = c2.text_input("Email", c["email"] if isinstance(c["email"], str) else "")
        domicilio = st.text_input("Domicilio", c["domicilio"] if isinstance(c["domicilio"], str) else "")
        nacimiento = c1.date_input(
            "Fecha de nacimiento", c["fecha_nacimiento"].date() if pd.notna(c["fecha_nacimiento"]) else None,
            min_value=date(1920, 1, 1), max_value=ahora().date(), format="DD/MM/YYYY")
        edad_in = c2.number_input("Edad", 0, 120, int(edad) if pd.notna(edad) else 0,
                                  help="Se calcula sola si cargás la fecha de nacimiento.")
        origen_actual = c["origen"] if c["origen"] in ORIGENES else None
        origen = c1.selectbox("¿Cómo nos conoció?", ORIGENES,
                              index=ORIGENES.index(origen_actual) if origen_actual else None, placeholder="—")
        acepta = c2.checkbox("Acepta recibir promociones por WhatsApp", bool(c["acepta_mensajes"]))
        if st.form_submit_button("💾 Guardar datos", type="primary"):
            if not (nombre.strip() and apellido.strip()):
                st.error("Nombre y apellido son obligatorios.")
            else:
                db.execute(
                    """UPDATE clientes SET nombre=%s, apellido=%s, telefono=%s, email=%s, domicilio=%s,
                                           fecha_nacimiento=%s, edad=%s, origen=%s, acepta_mensajes=%s
                       WHERE id=%s""",
                    (nombre.strip(), apellido.strip(), telefono.strip() or None, email.strip() or None,
                     domicilio.strip() or None, nacimiento, edad_in or None, origen, acepta, int(c["id"])),
                )
                invalidar()
                flash("Datos del cliente actualizados")
                st.rerun()

    with tab_hc:
        hc = db.fetch_one("SELECT notas FROM historias_clinicas WHERE cliente_id = %s", (int(c["id"]),))
        with st.form(f"hc_{c['id']}"):
            notas = st.text_area("Historia clínica", hc["notas"] if hc else "", height=280,
                                 help="Al completar un turno se agrega automáticamente una línea con la fecha y el servicio.")
            if st.form_submit_button("💾 Guardar historia clínica", type="primary"):
                db.execute(
                    """INSERT INTO historias_clinicas (cliente_id, notas) VALUES (%s, %s)
                       ON CONFLICT (cliente_id) DO UPDATE SET notas = EXCLUDED.notas""",
                    (int(c["id"]), notas),
                )
                flash("Historia clínica guardada")
                st.rerun()

    with tab_turnos:
        propios = turnos[turnos["cliente_id"] == c["id"]].sort_values("inicio", ascending=False)
        if propios.empty:
            st.caption("Todavía no tiene turnos.")
        else:
            vista = propios[["inicio", "servicios", "estado", "total"]].copy()
            vista["estado"] = vista["estado"].map(lambda e: ESTADOS.get(e, (e,))[0])
            st.dataframe(vista, hide_index=True, width="stretch", column_config={
                "inicio": st.column_config.DatetimeColumn("Fecha", format="DD/MM/YYYY HH:mm"),
                "servicios": "Servicios", "estado": "Estado",
                "total": st.column_config.NumberColumn("Total", format="$%.0f")})


def pagina_clientes():
    st.title("👥 Clientes")
    clientes = df_clientes()

    with st.expander("➕ Registrar cliente nuevo", expanded=clientes.empty):
        with st.form("nuevo_cliente", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            nombre = c1.text_input("Nombre *")
            apellido = c2.text_input("Apellido *")
            telefono = c3.text_input("WhatsApp *", placeholder="11 2345 6789")
            email = c1.text_input("Email")
            nacimiento = c2.date_input("Fecha de nacimiento", None, min_value=date(1920, 1, 1),
                                       max_value=ahora().date(), format="DD/MM/YYYY")
            origen = c3.selectbox("¿Cómo nos conoció?", ORIGENES, index=None, placeholder="—")
            domicilio = st.text_input("Domicilio")
            acepta = st.checkbox("Acepta recibir promociones por WhatsApp", True)
            if st.form_submit_button("Registrar", type="primary"):
                tel = telefono_wa(telefono)
                repetido = clientes[clientes["telefono"].map(telefono_wa) == tel] if tel else clientes.iloc[0:0]
                if not (nombre.strip() and apellido.strip() and telefono.strip()):
                    st.error("Nombre, apellido y WhatsApp son obligatorios.")
                elif not repetido.empty:
                    st.error(f"Ya existe un cliente con ese teléfono: {repetido.iloc[0]['cliente']}.")
                else:
                    nuevo = db.execute(
                        """INSERT INTO clientes (nombre, apellido, telefono, email, domicilio, fecha_nacimiento,
                                                 origen, acepta_mensajes)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                        (nombre.strip(), apellido.strip(), telefono.strip(), email.strip() or None,
                         domicilio.strip() or None, nacimiento, origen, acepta),
                    )
                    invalidar()
                    flash(f"Cliente {nombre} {apellido} registrado")
                    ir_a("👥 Clientes", nuevo["id"])
                    st.rerun()

    if clientes.empty:
        return
    nombres = dict(zip(clientes["id"].astype(int).tolist(),
                       clientes["apellido"] + ", " + clientes["nombre"] + " · " + clientes["telefono"].fillna("s/tel")))
    if ss.get("cliente_sel") not in nombres:
        ss.cliente_sel = None
    st.selectbox("Abrir ficha", list(nombres), index=None, format_func=nombres.get, key="cliente_sel",
                 placeholder="🔎 Buscá por nombre, apellido o teléfono…", label_visibility="collapsed")

    if ss.cliente_sel is not None:
        ficha_cliente(clientes.set_index("id", drop=False).loc[ss.cliente_sel], df_turnos())
        return

    st.caption(f"{len(clientes)} clientes registrados")
    st.dataframe(
        clientes[["cliente", "telefono", "visitas", "gastado", "ultima_visita", "proximo_turno", "origen"]],
        hide_index=True, width="stretch",
        column_config={
            "cliente": "Cliente", "telefono": "WhatsApp", "visitas": "Visitas", "origen": "Origen",
            "gastado": st.column_config.NumberColumn("Gastado", format="$%.0f"),
            "ultima_visita": st.column_config.DateColumn("Última visita", format="DD/MM/YYYY"),
            "proximo_turno": st.column_config.DatetimeColumn("Próximo turno", format="DD/MM HH:mm"),
        },
    )


def pagina_tratamientos():
    st.title("💄 Tratamientos")
    st.caption("Editá directamente en la tabla. La **duración** se usa para calcular el fin del turno en la agenda. "
               "Para dejar de ofrecer un tratamiento desmarcá **Activo** (así se conserva el historial).")
    columnas = ["id", "nombre", "precio", "duracion_min", "activo", "descripcion"]
    original = pd.DataFrame(q_tratamientos(), columns=columnas)
    editado = st.data_editor(
        original, num_rows="dynamic", hide_index=True, width="stretch", key="editor_tratamientos",
        column_config={
            "id": None,
            "nombre": st.column_config.TextColumn("Tratamiento", required=True),
            "precio": st.column_config.NumberColumn("Precio", min_value=0, step=500, format="$%.0f", required=True),
            "duracion_min": st.column_config.NumberColumn("Duración (min)", min_value=15, max_value=720, step=15,
                                                          default=60, required=True),
            "activo": st.column_config.CheckboxColumn("Activo", default=True),
            "descripcion": st.column_config.TextColumn("Descripción"),
        },
    )
    if st.button("💾 Guardar cambios", type="primary"):
        orig = original.set_index("id")
        ids_editados = set()
        with db.transaction() as cur:
            for _, fila in editado.iterrows():
                nombre = fila["nombre"].strip() if isinstance(fila["nombre"], str) else ""
                if not nombre:
                    continue
                valores = (nombre,
                           float(fila["precio"]) if pd.notna(fila["precio"]) else 0.0,
                           int(fila["duracion_min"]) if pd.notna(fila["duracion_min"]) else 60,
                           bool(fila["activo"]) if pd.notna(fila["activo"]) else True,
                           fila["descripcion"] if isinstance(fila["descripcion"], str) and fila["descripcion"] else None)
                if pd.isna(fila["id"]):
                    cur.execute("""INSERT INTO tratamientos (nombre, precio, duracion_min, activo, descripcion)
                                   VALUES (%s, %s, %s, %s, %s)""", valores)
                else:
                    ids_editados.add(int(fila["id"]))
                    cur.execute("""UPDATE tratamientos SET nombre=%s, precio=%s, duracion_min=%s, activo=%s,
                                   descripcion=%s WHERE id=%s""", (*valores, int(fila["id"])))
            for borrado in set(orig.index.astype(int)) - ids_editados:
                cur.execute("SELECT 1 FROM turno_tratamientos WHERE tratamiento_id = %s LIMIT 1", (borrado,))
                if cur.fetchone():
                    cur.execute("UPDATE tratamientos SET activo = FALSE WHERE id = %s", (borrado,))
                else:
                    cur.execute("DELETE FROM tratamientos WHERE id = %s", (borrado,))
        invalidar()
        flash("Tratamientos guardados")
        st.rerun()


def pagina_marketing():
    st.title("📣 Marketing")
    st.caption("Segmentá tu base de clientes y enviá mensajes personalizados por WhatsApp con un clic. "
               "Solo se incluyen clientes que aceptan recibir promociones.")
    clientes = df_clientes()
    contactables = clientes[clientes["acepta_mensajes"].fillna(True).astype(bool) & clientes["telefono"].notna()]
    hoy = ahora()

    tab_seg, tab_origen, tab_conf = st.tabs(["🎯 Segmentos", "📈 Canales", "⚙️ Plantillas"])
    with tab_seg:
        segmentos = {
            "💤 Para reactivar": "Vinieron alguna vez, hace tiempo que no vuelven y no tienen turno agendado.",
            "🎂 Cumpleaños del mes": "Ideal para un beneficio especial: alta tasa de respuesta.",
            "🔁 Una sola visita": "Vinieron una vez y no volvieron: el momento clave para fidelizar.",
            "👑 Mejores clientes": "El 20% que más gasta. Cuidalos con beneficios exclusivos.",
            "🌱 Registrados sin turnos": "Están en la base pero nunca tuvieron un turno.",
        }
        segmento = st.radio("Segmento", list(segmentos), horizontal=True, label_visibility="collapsed")
        st.caption(segmentos[segmento])
        sin_proximo = contactables["proximo_turno"].isna()
        plantilla = "tpl_reactivacion"
        if segmento == "💤 Para reactivar":
            dias = st.slider("Días sin venir", 30, 365, 60, step=15)
            lista = contactables[sin_proximo & (contactables["dias_sin_venir"] >= dias)]
        elif segmento == "🎂 Cumpleaños del mes":
            lista = contactables[contactables["fecha_nacimiento"].dt.month == hoy.month]
            plantilla = "tpl_cumpleanos"
        elif segmento == "🔁 Una sola visita":
            lista = contactables[sin_proximo & (contactables["visitas"] == 1) & (contactables["dias_sin_venir"] >= 14)]
            plantilla = "tpl_segunda_visita"
        elif segmento == "👑 Mejores clientes":
            con_gasto = contactables[contactables["gastado"] > 0]
            umbral = con_gasto["gastado"].quantile(0.8) if not con_gasto.empty else 0
            lista = con_gasto[con_gasto["gastado"] >= umbral].sort_values("gastado", ascending=False)
        else:
            lista = contactables[contactables["visitas"] == 0]

        plantilla = st.selectbox("Mensaje", list(PLANTILLAS), index=list(PLANTILLAS).index(plantilla),
                                 format_func=PLANTILLAS.get)
        if lista.empty:
            st.info("No hay clientes en este segmento ahora mismo. 🎉")
        else:
            lista = lista.copy()
            lista["whatsapp"] = [
                link_wa(tel, mensaje(plantilla, nombre=nom, servicios=serv if isinstance(serv, str) else "tratamiento"))
                for tel, nom, serv in zip(lista["telefono"], lista["nombre"], lista["ultimo_servicio"])
            ]
            st.markdown(f"**{len(lista)} clientes**")
            st.dataframe(
                lista[["cliente", "telefono", "visitas", "gastado", "ultima_visita", "whatsapp"]],
                hide_index=True, width="stretch",
                column_config={
                    "cliente": "Cliente", "telefono": "Teléfono", "visitas": "Visitas",
                    "gastado": st.column_config.NumberColumn("Gastado", format="$%.0f"),
                    "ultima_visita": st.column_config.DateColumn("Última visita", format="DD/MM/YYYY"),
                    "whatsapp": st.column_config.LinkColumn("Enviar", display_text="💬 WhatsApp"),
                },
            )
            st.download_button("⬇️ Descargar lista (CSV)",
                               lista[["nombre", "apellido", "telefono", "email", "visitas", "gastado"]]
                               .to_csv(index=False).encode("utf-8-sig"),
                               file_name="segmento_bella.csv", mime="text/csv")

    with tab_origen:
        if clientes["origen"].notna().any():
            por_origen = (clientes.assign(origen=clientes["origen"].fillna("Sin dato"))
                          .groupby("origen").agg(clientes=("id", "count"), facturado=("gastado", "sum"))
                          .sort_values("facturado", ascending=False))
            c1, c2 = st.columns(2)
            c1.markdown("**Clientes por canal**")
            c1.bar_chart(por_origen["clientes"], color="#5B7FE8", horizontal=True)
            c2.markdown("**Facturación por canal**")
            c2.bar_chart(por_origen["facturado"], color="#D6457A", horizontal=True)
            st.caption("Usá esto para decidir dónde invertir en publicidad: priorizá los canales que traen "
                       "clientes que **gastan más**, no solo los que traen más clientes.")
        else:
            st.info("Cargá el campo **¿Cómo nos conoció?** en la ficha de cada cliente para ver qué canales funcionan mejor.")

    with tab_conf:
        cfg = q_config()
        with st.form("config_marketing"):
            c1, c2 = st.columns(2)
            negocio = c1.text_input("Nombre del negocio", cfg["negocio"])
            resena = c2.text_input("Link para dejar reseña en Google", cfg["link_resena"],
                                   placeholder="https://g.page/r/…")
            st.caption("Variables disponibles: {nombre}, {negocio}, {fecha}, {hora}, {servicios}, {link_resena}")
            textos = {clave: st.text_area(titulo, cfg[clave], height=90) for clave, titulo in PLANTILLAS.items()}
            if st.form_submit_button("💾 Guardar plantillas", type="primary"):
                guardar_config({"negocio": negocio.strip() or "Bella", "link_resena": resena.strip(), **textos})
                st.cache_data.clear()
                flash("Plantillas guardadas")
                st.rerun()


# --------------------------------------------------------------------------- arranque

PAGINAS = {
    "🏠 Inicio": pagina_inicio,
    "📅 Agenda": pagina_agenda,
    "👥 Clientes": pagina_clientes,
    "💄 Tratamientos": pagina_tratamientos,
    "📣 Marketing": pagina_marketing,
}

try:
    db.ensure_schema()
except db.DBError as e:
    st.title("✨ Bella")
    st.error(f"⚠️ {e}")
    with st.expander("¿Cómo lo soluciono?", expanded=True):
        st.markdown(
            "1. Entrá a **dashboard.render.com** → tu base PostgreSQL y verificá que esté *Available* "
            "(las bases gratuitas vencen a los 30 días y hay que actualizar el plan o crear otra).\n"
            "2. Copiá la **External Database URL** y cargala como `DATABASE_URL` en los *secrets* / "
            "variables de entorno del servicio donde corre la app.\n"
            "3. Si la app corre en Render, en la misma región que la base, podés usar la *Internal Database URL*."
        )
    if st.button("🔄 Reintentar"):
        st.rerun()
    st.stop()

if "goto" in ss:
    pagina_destino, cliente_destino = ss.pop("goto")
    ss.pagina = pagina_destino
    if cliente_destino is not None:
        ss.cliente_sel = cliente_destino

for texto, icono in ss.pop("flash", []):
    st.toast(texto, icon=icono)

try:
    negocio = q_config()["negocio"]
except db.DBError:
    negocio = CONFIG_DEFAULT["negocio"]

with st.sidebar:
    st.markdown(f"## ✨ {negocio}")
    pagina = st.radio("Menú", list(PAGINAS), key="pagina", label_visibility="collapsed")
    st.write("")
    if st.button("➕ Nuevo turno", type="primary", width="stretch", key="nuevo_turno_sidebar"):
        abrir_dialogo("nuevo")
    if st.button("🔄 Actualizar datos", width="stretch"):
        invalidar()
        st.rerun()

try:
    PAGINAS[pagina]()
    mostrar_dialogo_pendiente()
except db.DBError as e:
    st.error(f"⚠️ {e}")
