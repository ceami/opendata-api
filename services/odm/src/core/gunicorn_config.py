bind = "0.0.0.0:8000"
backlog = 2048

workers = 4
worker_class = "uvicorn.workers.UvicornWorker"
worker_conncetions = 1000
max_requests = 1000
max_requests_jitter = 50
preload_app = True
