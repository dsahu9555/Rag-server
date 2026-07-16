from fastapi import APIRouter, HTTPException, Depends
from auth import get_current_user
from database import supabase
from pydantic import BaseModel

router = APIRouter(
    tags=["files"]
)

@router.get("/api/projects/{project_id}/files")
def get_project_files(
    project_id: str,
    clerk_id: str = Depends(get_current_user)
):
    try:
        files_result =supabase.table("project_documents").select("*").eq("project_id", project_id).eq("clerk_id", clerk_id).execute()

        
        return {
            "message": "Project files retrieved successfully!",
            "data": files_result.data or []
        }     
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get project files: {str(e)}")
