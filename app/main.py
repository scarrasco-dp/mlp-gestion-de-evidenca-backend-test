from fastapi import FastAPI, UploadFile, Depends, HTTPException, APIRouter, Response
from fastapi.middleware.cors import CORSMiddleware
from app_config import get_firebase_user_from_token
from arcgis.gis import GIS
from arcgis.geometry import Point

import firebase_admin
import uvicorn
from dotenv import load_dotenv
from datetime import datetime, timedelta
import io
import json
import os
import pandas as pd
import requests
import holidays
import re


app = FastAPI()
router = APIRouter() 
load_dotenv(".env")
origins = [os.getenv("FRONTEND_URL", "*")]
origins = [
    "https://dev-mlp-gestion-de-evidencia-preview.vercel.app",
    "http://localhost:3000"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # Ahora incluye localhost
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
firebase_admin.initialize_app()
load_dotenv(".env")

# Configuración para OAuth 2.0 Client Credentials
CLIENT_ID = os.getenv("ARCGIS_CLIENT_ID", "YaPnrAFP4tvZogSu")
CLIENT_SECRET = os.getenv("ARCGIS_CLIENT_SECRET", "f2d55ee0da364a6fa984c3ce31ba5a05")
TARGET_URL = "https://experience.arcgis.com/experience/3f2cb0aff56340c48cd79846f56f365d/"
def get_access_token():
    token_url = "https://www.arcgis.com/sharing/rest/oauth2/token"
    params = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "client_credentials",  # Flujo Client Credentials
        "f": "json"
    }
    response = requests.post(token_url, data=params)
    if response.ok:
        token_data = response.json()
        access_token = token_data.get("access_token")
        if not access_token:
            raise Exception("Token de acceso no recibido")
        return access_token
    else:
        raise Exception("Error al obtener el token de acceso")

@app.get("/arcgis/token")
def arcgis_token():
    try:
        token = get_access_token()
        return {"access_token": token}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=port)



# Creamos una sesión global para mantener las cookies de autenticación.
session = requests.Session()

# Función para iniciar sesión en la webapp de ArcGIS.
def login_arcgis():
    login_url = "https://experience.arcgis.com/login"  # AJUSTA esta URL según la API de login real
    payload = {
        "username": "invitado@dp.com",
        "password": "qwerty.123"
    }
    # Realiza el POST para autenticarte.
    resp = session.post(login_url, data=payload)
    if resp.ok:
        print("Login exitoso")
    else:
        raise Exception("Error en el login: " + resp.text)

# Ejecutar el login al iniciar el servidor.
@app.on_event("startup")
def startup_event():
    try:
        login_arcgis()
    except Exception as e:
        print(f"Error al iniciar sesión: {e}")


@app.get("/map-proxy")
def proxy_map():
    target_url = "https://experience.arcgis.com/experience/3f2cb0aff56340c48cd79846f56f365d/"
    try:
        r = session.get(target_url)
        # Reenviamos el contenido y el content-type original.
        return Response(content=r.content, media_type=r.headers.get("Content-Type", "text/html"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def df_to_features(df):
    features_to_be_added = []
    for row in df.iterrows():
        data = row[1]
        attributes = {
            'iniciativa': data['iniciativa'],
            'llave': data['llave'],
            'ano': int(data['ano']),
            'localidad': data['localidad'],
            'estado': data['estado'],
        }
        if str(data['familia_iniciativa']) != "nan":
            attributes['familia_iniciativa'] = data['familia_iniciativa']
        if str(data['tipo_iniciativa']) != "nan":
            attributes['tipo_iniciativa'] = data['tipo_iniciativa']
        if str(data['fase']) != "nan":
            attributes['fase'] = data['fase']
        if str(data['costo_total_usd']) != "nan":
            attributes['costo_total_usd'] = float(data['costo_total_usd'].replace(",", "."))
        if str(data['FCT']) != "nan":
            attributes['FCT'] = data['FCT']
        if str(data['SOLPED']) != "nan":
            attributes['SOLPED'] = data['SOLPED']

        new_feature = {
            "attributes": attributes
        }

        if 'Coor_x' in data.index:
            point = Point([data['Coor_x'], data['Coor_y']])
            new_feature['geometry'] = point

        features_to_be_added.append(new_feature)

    return features_to_be_added

@app.get("/")
def read_root():
    return {"message": "Hello World FastAPI"}


@app.post("/")
async def read_root(file: UploadFile, token: dict = Depends(get_firebase_user_from_token)):
    today = datetime.today()
    gis = GIS("https://www.arcgis.com", api_key=os.getenv("ARCGIS_API_KEY"))
    contents = io.BytesIO(await file.read())
    dfI = pd.read_excel(contents, sheet_name="aapp_amsa_1_iniciativas")
    dfH = pd.read_excel(contents, sheet_name="aapp_amsa_1_hitos")

    dfH['peso'] = dfH['peso'].str.replace(',', '.').astype(float)
    dfH['peso_ac'] = dfH['peso_ac'].str.replace(',', '.').astype(float)
    dfH['fecha_plan'] = pd.to_datetime(dfH['fecha_plan'])
    dfH['fecha_real'] = pd.to_datetime(dfH['fecha_real'])
    dfH['cumplimiento_plan'] = (dfH['fecha_plan'] < today)
    dfH['cumplimiento_real'] = (dfH['fecha_real'] < today) & (dfH['estado_avance'] == "COMPLETADO")

    dfI = dfI[(dfI['gerencia'] == "Minera Los Pelambres") &
              (dfI['esponsor'] == "GAAPP GMLP") & (dfI['estado'] != "ELIMINADO")]
    dfH = dfH[dfH['parent'].isin(dfI['llave'])]

    dfResumen = dfI[['iniciativa', 'llave', 'ano', 'familia_iniciativa', 'tipo_iniciativa',
                     'localidad', 'fase', 'estado', 'costo_total_usd', 'FCT', 'SOLPED']]
    
    def delta(sub_df):
        sub_df = sub_df[sub_df['linea_gestion'] == "Físico"]
        sum_pesos = sub_df['peso'].sum()
        if sum_pesos > 0:
            plan = (sub_df['peso'] * sub_df['cumplimiento_plan']).sum() / sum_pesos
        else:
            plan = 0
        sum_reales = sub_df['peso_ac'].sum()
        if sum_reales > 0:
            real = (sub_df['peso_ac'] * sub_df['cumplimiento_real']).sum() / sum_reales
        else:
            real = 0
        return abs(plan - real)

    dfH_delta = dfH.groupby('parent').apply(delta).reset_index(name='delta')
    dfH_delta = dfH_delta.rename(columns={'parent': 'llave'})
    dfResumen = dfResumen.merge(dfH_delta, on='llave', how='left')

    with open('localitiesX.json', 'r') as f:
        dictLocalitiesX = json.loads(f.read())
    with open('localitiesY.json', 'r') as f:
        dictLocalitiesY = json.loads(f.read())

    dfResumen.insert(len(dfResumen.columns), 'Coor_x', dfResumen['localidad'].map(dictLocalitiesX))
    dfResumen.insert(len(dfResumen.columns), 'Coor_y', dfResumen['localidad'].map(dictLocalitiesY))

    dfResumenNoGeo = dfResumen[dfResumen['Coor_x'].isna()]
    dfResumenGeo = dfResumen.dropna(subset=['Coor_x'])
    item = gis.content.get("d462a6d805354d62a37fc6210c75664d")
    feature_layer = item.layers[0]
    features_to_be_added = df_to_features(dfResumenGeo)
    feature_layer.delete_features(where="OBJECTID > 0")
    feature_layer.edit_features(adds=features_to_be_added)
    
    dfToTable = dfResumenNoGeo.drop(columns=['Coor_x', 'Coor_y'])
    dfToTable['localidad'] = dfToTable['localidad'].fillna("")
    item2 = gis.content.get("707ed0b1b4ac424b947f5d07a4b243d3")
    table = item2.tables[0]
    table_new_features = df_to_features(dfToTable)
    table.delete_features(where="OBJECTID > 0")
    table.edit_features(adds=table_new_features)

    return 'ok'

chilean_holidays = holidays.CL()

def get_previous_business_day(date):
    previous_date = date - timedelta(days=1)
    while (previous_date.weekday() >= 5) or (previous_date in chilean_holidays):
        previous_date -= timedelta(days=1)
    return previous_date

@app.get("/currencies")
def get_currencies(year: int = None):
    url = "https://si3.bcentral.cl/Indicadoressiete/secure/IndicadoresDiarios.aspx?Idioma=es-CL"
    ini_response = requests.post(url)
    soup = BeautifulSoup(ini_response.text, 'html.parser')
    view_state = soup.find('input', {'id': '__VIEWSTATE'})['value']

    try:
        if year is not None:
            yearDate = datetime(year, 1, 5)
            previousWeekDay = get_previous_business_day(yearDate)
            response = requests.post(
                url, data={
                    'h_calendario': '{}.{}.{};{}.1.1'.format(previousWeekDay.year, previousWeekDay.month, previousWeekDay.day, year),
                    '__EVENTTARGET': 'calendario',
                    '__VIEWSTATE': view_state
                })
        else:
            response = requests.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        usd = float(soup.find("label", {"id": "lblValor1_3"}).text.replace(".", "").replace(",", "."))
        eur = float(soup.find("label", {"id": "lblValor1_5"}).text.replace(".", "").replace(",", "."))
        uf = float(soup.find("label", {"id": "lblValor1_5"}).text.replace(".", "").replace(",", "."))
        return {"CLP": 1, "USD": usd, "EUR": eur, "UF": uf}
    except Exception as _:
        return HTTPException(status_code=500, detail="Scraper failed")
