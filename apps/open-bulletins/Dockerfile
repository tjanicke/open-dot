FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY open_bulletins.py search_core.py web.py ./
USER 1000:1000
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 BULLETINS_DATA=/data
EXPOSE 8080
CMD ["gunicorn","web:app","--bind","0.0.0.0:8080","--workers","2","--threads","4","--timeout","60","--worker-tmp-dir","/tmp","--error-logfile","-"]
