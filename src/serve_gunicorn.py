import app

print("Server script is ready for Gunicorn to run.")

#gunicorn -w 4 -k uvicorn.workers.UvicornWorker app:app --bind 0.0.0.0:8500