from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.routes import router

app = FastAPI(
    title="Lightpanda Link Tree",
    description="Genera el arbol de enlaces de una URL usando Lightpanda.",
    version="0.1.0",
)
app.include_router(router)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    # Sin el valor recibido: un token invalido no debe volver en la respuesta.
    errors = [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
    return JSONResponse({"detail": errors}, status.HTTP_422_UNPROCESSABLE_CONTENT)
