from bs4 import BeautifulSoup
from fastapi import FastAPI, UploadFile, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from arcgis.gis import GIS
from arcgis.geometry import Point

import firebase_admin

from dotenv import load_dotenv
from datetime import datetime, timedelta
import io
import json
import os
import pandas as pd
import requests
import holidays
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
#from config import get_firebase_user_from_token


app = FastAPI()

load_dotenv(".env")
origins = [os.getenv("FRONTEND_URL", "*")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

firebase_admin.initialize_app()

arcgis_user = os.getenv("ARCGIS_USER")
arcgis_password = os.getenv("ARCGIS_PASSWORD")

print("Current App Name:", firebase_admin.get_app().project_id)


def df_to_features(df):
    features_to_be_added = []
    for index, data in df.iterrows():
        attributes = {
            'iniciativa': data['iniciativa'],
            'llave': data['llave'],
            'ano': int(data['ano']),
            'localidad': data['localidad'],
            'estado': data['estado'],
        }
        if pd.notna(data['familia_iniciativa']):
            attributes['familia_iniciativa'] = data['familia_iniciativa']
        if pd.notna(data['tipo_iniciativa']):
            attributes['tipo_iniciativa'] = data['tipo_iniciativa']
        if pd.notna(data['fase']):
            attributes['fase'] = data['fase']
        if pd.notna(data['costo_total_usd']):
            attributes['costo_total_usd'] = float(data['costo_total_usd'].replace(",", "."))
        if pd.notna(data['FCT']):
            attributes['FCT'] = data['FCT']
            
        # Para el campo SOLPED, extraer sólo la parte antes de "/" (si existe)
        if pd.notna(data['SOLPED']):
            solped_str = str(data['SOLPED'])
            if "/" in solped_str:
                solped_str = solped_str.split("/")[0].strip()
            try:
                attributes['SOLPED'] = int(solped_str)
            except Exception as e:
                # Imprime en consola para depuración (y en logging, por ejemplo)
                print(f"Error al convertir SOLPED en la fila {index}: {data['SOLPED']} -> {e}")
                attributes['SOLPED'] = None  # O decide omitir este registro, según convenga

        if pd.notna(data['area_prioritaria']):
            attributes['area_prioritaria'] = data['area_prioritaria']

        new_feature = {"attributes": attributes}

        if pd.notna(data.get('Coor_x')) and pd.notna(data.get('Coor_y')):
            point = Point([data['Coor_x'], data['Coor_y']])
            new_feature['geometry'] = point

        features_to_be_added.append(new_feature)

    return features_to_be_added



@app.post("/")
async def read_root(file: UploadFile):
    today = datetime.today()
    
    gis = GIS("https://www.arcgis.com", "Rosita_Edwards", "Fuenzalida17")

    contents = io.BytesIO(await file.read())
    dfI = pd.read_excel(contents, sheet_name="aapp_amsa_1_iniciativas")
    dfH = pd.read_excel(contents, sheet_name="aapp_amsa_1_hitos")

    dfH['peso'] = dfH['peso'].str.replace(',', '.').astype(float)
    dfH['peso_ac'] = dfH['peso_ac'].str.replace(',', '.').astype(float)
    dfH['fecha_plan'] = pd.to_datetime(dfH['fecha_plan'])
    dfH['fecha_real'] = pd.to_datetime(dfH['fecha_real'])
    dfH['cumplimiento_plan'] = (dfH['fecha_plan'] < today)
    dfH['cumplimiento_real'] = (dfH['fecha_real'] < today) & (
        dfH['estado_avance'] == "COMPLETADO")

    dfI = dfI[(dfI['gerencia'] == "Minera Los Pelambres") &
              (dfI['esponsor'] == "GAAPP GMLP") & (dfI['estado'] != "ELIMINADO")]
    dfH = dfH[dfH['parent'].isin(dfI['llave'])]

    dfResumen = dfI[['iniciativa', 'llave', 'ano', 'familia_iniciativa', 'tipo_iniciativa',
                     'localidad', 'fase', 'estado', 'costo_total_usd', 'FCT', 'SOLPED', 'area_prioritaria']]

    def delta(sub_df):
        sub_df = sub_df[sub_df['linea_gestion'] == "Físico"]
        sum_pesos = sub_df['peso'].sum()
        if sum_pesos > 0:
            plan = (sub_df['peso'] * sub_df['cumplimiento_plan']
                    ).sum() / sum_pesos
        else:
            plan = 0

        sum_reales = sub_df['peso_ac'].sum()
        if sum_reales > 0:
            real = (sub_df['peso_ac'] * sub_df['cumplimiento_real']
                    ).sum() / sum_reales
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

    dfResumen.insert(len(dfResumen.columns), 'Coor_x',
                     dfResumen['localidad'].map(dictLocalitiesX))
    dfResumen.insert(len(dfResumen.columns), 'Coor_y',
                     dfResumen['localidad'].map(dictLocalitiesY))

    # Save initiatives without coords
    dfResumenNoGeo = dfResumen[dfResumen['Coor_x'].isna()]

    # Save initiatives with coords to arcgis feature layer
    dfResumenGeo = dfResumen.dropna(subset=['Coor_x'])
    item = gis.content.get("d462a6d805354d62a37fc6210c75664d")
    feature_layer = item.layers[0]
    features_to_be_added = df_to_features(dfResumenGeo)
    logger.info(features_to_be_added[0])
    feature_layer.delete_features(where="OBJECTID > 0")
    result = feature_layer.edit_features(adds=features_to_be_added)
    logger.info(result)
    # Save initiatives without coords to arcgis table
    dfToTable = dfResumenNoGeo.drop(columns=['Coor_x', 'Coor_y'])
    dfToTable['localidad'] = dfToTable['localidad'].fillna("")
    item2 = gis.content.get("707ed0b1b4ac424b947f5d07a4b243d3")
    table = item2.tables[0]
    table_new_features = df_to_features(dfToTable)
    table.delete_features(where="OBJECTID > 0")
    table.edit_features(adds=table_new_features)
    logger.info(table_new_features[0])

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
        if (year is not None):
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

        usd = float(soup.find("label", {"id": "lblValor1_3"}).text.replace(
            ".", "").replace(",", "."))
        eur = float(soup.find("label", {"id": "lblValor1_5"}).text.replace(
            ".", "").replace(",", "."))
        uf = float(soup.find("label", {"id": "lblValor1_5"}).text.replace(
            ".", "").replace(",", "."))

        return {"CLP": 1, "USD": usd, "EUR": eur, "UF": uf}
    except Exception as _:
        return HTTPException(status_code=500, detail="Scraper failed")