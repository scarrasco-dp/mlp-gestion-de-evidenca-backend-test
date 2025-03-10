FROM ghcr.io/esri/arcgis-python-api-notebook:2.3.0

WORKDIR /app

ENV FRONTEND_URL="*"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

#COPY .env .

COPY ./app /app

# Verifica que imghdr se pueda importar (para depurar)
RUN python -c "import imghdr; print('imghdr importado correctamente')"

EXPOSE 8080

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
