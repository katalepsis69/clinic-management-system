import gunicorn_conf

def test_gunicorn_settings():
    assert gunicorn_conf.worker_class == "uvicorn.workers.UvicornWorker"
    assert gunicorn_conf.workers >= 2
    assert gunicorn_conf.keepalive == 120
