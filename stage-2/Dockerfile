FROM python:3.12-slim
WORKDIR /app
COPY app.py index.html app.js style.css /app/
ENV PORT=8080
EXPOSE 8080
CMD ["python", "-u", "/app/app.py"]
