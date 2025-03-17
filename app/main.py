from fastapi import FastAPI, Request, Response, HTTPException, UploadFile, Depends, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from app_config import get_firebase_user_from_token
from arcgis.gis import GIS
from arcgis.geometry import Point
from bs4 import BeautifulSoup
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
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import time
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import zipfile
import stat
import chromedriver_autoinstaller
from playwright.sync_api import sync_playwright

app = FastAPI()
router = APIRouter()
load_dotenv(".env")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def simulate_login():
    with sync_playwright() as p:
        # Lanzamos el navegador en modo headless
        browser = p.chromium.launch(headless=True)
        # Creamos un contexto (para gestionar cookies, etc.)
        context = browser.new_context()
        page = context.new_page()
        
        # URL de autenticación (actualiza según tu configuración)
        url = "https://www.arcgis.com/sharing/rest/oauth2/authorize?client_id=experienceBuilder&response_type=code&expiration=20160&redirect_uri=https://experience.arcgis.com/cdn/2978/jimu-core/oauth-callback.html?clientId%3DexperienceBuilder%26portal%3Dhttps://www.arcgis.com/sharing/rest%26popup%3Dfalse%26isInPortal%3Dfalse%26isDevEdition%3Dfalse%26isOutOfExb%3Dfalse%26mountPath%3D/%26enablePkce%3Dtrue%26fromUrl%3Dhttps%253A%252F%252Fexperience.arcgis.com%252Fexperience%252F3f2cb0aff56340c48cd79846f56f365d%252F%26redirectUri%3Dhttps%253A%252F%252Fexperience.arcgis.com%252Fcdn%252F2978%252Fjimu-core%252Foauth-callback.html%253FclientId%253DexperienceBuilder%2526portal%253Dhttps%253A%252F%252Fwww.arcgis.com%252Fsharing%252Frest%2526popup%253Dfalse%2526isInPortal%253Dfalse%2526isDevEdition%253Dfalse%2526isOutOfExb%253Dfalse%2526mountPath%253D%252F%2526enablePkce%253Dtrue%2526fromUrl%253Dhttps%25253A%25252F%25252Fexperience.arcgis.com%25252Fexperience%25252F3f2cb0aff56340c48cd79846f56f365d%25252F&state=%7B%22id%22:%22NYKo6EzQ-wZBnMSpyi6CoVgNoxIw4acAudg4VZH_hUU%22,%22originalUrl%22:%22https://experience.arcgis.com/experience/3f2cb0aff56340c48cd79846f56f365d/%22%7D&locale=&style=&code_challenge_method=S256&code_challenge=fszem4HTAWk9h812lOaOTvFop1cehvkBx2GZKY8Mkxo&showSignupOption=true&signupType=esri&force_login=false"
        page.goto(url)
        
        # Completa los campos de usuario y contraseña
        page.fill("#user_username", "invitado@dp.com")
        page.fill("#user_password", "qwerty.123")
        
        # Haz clic en el botón de iniciar sesión
        page.click("#signIn")
        
        # Espera para que se procese el login (ajusta el tiempo si es necesario)
        page.wait_for_timeout(2000)
        
        # Extrae la cookie 'esri_aopc'
        cookies = context.cookies()
        cookie_value = None
        for cookie in cookies:
            if cookie.get("name") == "esri_aopc":
                cookie_value = cookie.get("value")
                break
        
        browser.close()
        return cookie_value

@app.get("/arcgis-cookie")
def arcgis_cookie(response: Response):
    cookie = simulate_login()
    if not cookie:
        return {"error": "No se encontró la cookie 'esri_aopc'"}

    # Si 'expires' es -1, indicamos que es una cookie de sesión (no establecemos expires)
    expires = None if cookie.get("expires", -1) == -1 else cookie["expires"]

    response.set_cookie(
        key=cookie["name"],
        value=cookie["value"],
        domain=cookie.get("domain"),
        path=cookie.get("path", "/"),
        expires=expires,
        secure=cookie.get("secure", False),
        httponly=cookie.get("httpOnly", False),
        samesite=cookie.get("sameSite", "lax").capitalize()  # FastAPI espera "Lax", "Strict" o "None"
    )
    return {"message": "Cookie establecida correctamente"}


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

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
