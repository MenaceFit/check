FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 DASHBOARD_HOST=0.0.0.0
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY lbcsniper ./lbcsniper
VOLUME /app/data
EXPOSE 8080
CMD ["python", "-m", "lbcsniper"]
