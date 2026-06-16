FROM python:3.11-slim

ENV TZ=America/Sao_Paulo \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir \
    "fastapi==0.115.*" \
    "uvicorn[standard]==0.30.*" \
    "requests==2.32.*" \
    "docker==7.1.*" \
    "python-multipart==0.0.*" \
    "ytmusicapi==1.*"

COPY app.py /app/app.py

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
