from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from routers import users
from database import supabase



# ==============================
# FastAPI App
# ==============================

app = FastAPI(
    title="My API",
    description="Production Ready FastAPI Boilerplate",
    version="1.0.0",
)


# ==============================
# Middleware
# ==============================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Change in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==============================
# Routes
# ==============================

@app.get("/")
async def root():
    return {
        "message": "Welcome to the API",
        "status": "running",
    }

@app.get("/all-users")
async def all_users():

    result = supabase.table("users").select("*").execute()

    return {
        "message": "Welcome to the API",
        "data": result.data,
    }


app.include_router(users.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)


# Example
#
# from app.api.router import api_router
#
# app.include_router(api_router, prefix="/api/v1")