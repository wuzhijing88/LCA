FROM python:3.10-slim
WORKDIR /app
COPY sponsorship_server/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --uid 10001 --create-home sponsor \
    && mkdir /data && chown sponsor:sponsor /data
COPY sponsorship_server /app/sponsorship_server
COPY themes/sponsorship.css /app/themes/sponsorship.css
COPY resources/icon.ico /app/resources/icon.ico
USER sponsor
EXPOSE 8080
CMD ["uvicorn", "sponsorship_server.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--no-access-log", "--no-proxy-headers"]
