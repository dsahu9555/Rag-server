from fastapi import Request, HTTPException
from clerk_backend_api import AuthenticateRequestOptions, Clerk
import os

clerk_client = Clerk(bearer_auth=os.getenv("CLERK_SECRET_KEY"))

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")

async def get_current_user(request: Request) -> str:
    try:

        request_state = clerk_client.authenticate_request(
            request, AuthenticateRequestOptions(
                authorized_parties=["http://localhost:3000"]
            )
        )
        if not request_state.is_signed_in:
            raise HTTPException(status_code=401, detail="Not Authenticated ")

        if not request_state.payload:
            raise HTTPException(status_code=401, detail="Not Authenticated")

        clerk_id = request_state.payload.get("sub")

        if not clerk_id:
            raise HTTPException(status_code=401, detail="Invalid Token")

        return clerk_id

    except Exception as e:
        raise HTTPException(status_code=401, detail="Authentication Failed")


