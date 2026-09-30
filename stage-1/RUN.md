# Tablekeeper Stage 1

Build and start the service from this directory:

```sh
docker build -t tablekeeper-stage-1 .
docker run --rm -p 8080:8080 -e PORT=8080 tablekeeper-stage-1
```

The service listens on `0.0.0.0` and stores all state in its container-local SQLite database. It uses only Python's standard library at runtime.
