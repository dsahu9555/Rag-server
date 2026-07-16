from fastapi import APIRouter, HTTPException, Depends
from auth import get_current_user
from database import supabase
from pydantic import BaseModel

router = APIRouter(
    tags=["chats"]
)

class ChatCreate(BaseModel):
    title: str
    project_id: str

@router.post("/api/chats")
def create_project_chat(
    chat: ChatCreate,
    clerk_id: str = Depends(get_current_user)
):
    try:
        chats_result =supabase.table("chats").insert({
            "title": chat.title,
            "project_id": chat.project_id,
            "clerk_id": clerk_id
        }).execute()

        
        return {
            "message": "Chat created successfully!",
            "data": chats_result.data[0]
        }     
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get project files: {str(e)}")


@router.delete("/api/chats/{chat_id}")
def get_project_chats(
    chat_id: str,
    clerk_id: str = Depends(get_current_user)
):
    try:
        deleted_result =supabase.table("chats").select("*").eq("id", chat_id).eq("clerk_id", clerk_id).execute()

        if not deleted_result.data:
            raise HTTPException(status_code=404, detail=f"Failed to delete chat or access denied")

        
        return {
            "message": "Chat deleted successfully!",
            "data": deleted_result.data[0]
        }     
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete chat: {str(e)}")
