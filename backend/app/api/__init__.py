"""API HTTP del backend (JAJ-49): expone el motor para que el editor en Nuxt pida simulaciones.

* ``main``: arma la app de FastAPI (CORS y manejo de errores) y registra las rutas.
* ``schemas``: lo que recibe y devuelve la API (``RunRequest``, proyectos, versiones, comparar).
* ``errors``: el error de la API (``ApiError``) y su respuesta JSON.
* ``store``: proyectos y versiones (en memoria hasta JAJ-56).
* ``routes/``: las rutas por tema (``health``, ``runs``, ``models``, ``projects``).
"""
