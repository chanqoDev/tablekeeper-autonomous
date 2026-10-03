# Tablekeeper Stage 3

Build and start the service from this directory:

```sh
docker build -t tablekeeper-stage-3 .
docker run --rm -p 8080:8080 -e PORT=8080 tablekeeper-stage-3
```

The service listens on `0.0.0.0` and stores all state in its container-local SQLite database. Its HTML, JavaScript, and CSS are included in the image. It uses only Python's standard library at runtime and makes no outbound network requests.
