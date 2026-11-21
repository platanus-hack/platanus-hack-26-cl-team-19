"""API HTTP del backend (JAJ-49): expone el motor para que el editor en Nuxt pida simulaciones.

* ``main``: arma la app de FastAPI (CORS y manejo de errores) y registra las rutas.
* ``schemas``: lo que recibe la API (``RunRequest``) y el formato de los errores.
* ``errors``: el error de la API (``ApiError``) y su respuesta JSON.
* ``routes/``: una ruta por archivo (``health``, ``runs``).
"""
