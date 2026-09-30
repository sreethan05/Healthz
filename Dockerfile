FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend ./backend
COPY memory ./memory
COPY frontend ./frontend
COPY cliniva ./cliniva
COPY data/demo_patient.json data/demo_patient_2.json ./data/
RUN useradd --system --uid 10001 --create-home cliniva \
    && mkdir -p /app/data/banks \
    && chown -R cliniva:cliniva /app/data
USER cliniva
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
