FROM ghcr.io/esri/arcgis-python-api-notebook:2.3.0

WORKDIR /app

ENV FRONTEND_URL="*"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

#COPY .env .

COPY ./app /app

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "${PORT}"]
