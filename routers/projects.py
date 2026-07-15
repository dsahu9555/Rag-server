from fastapi import APIRouter, HTTPException, Depends
from auth import get_current_user
from database import supabase
from pydantic import BaseModel

router = APIRouter(
    tags=["projects"]
)

class ProjectCreate(BaseModel):
    name: str
    description: str


@router.get("/api/projects")
def get_projects(clerk_id: str = Depends(get_current_user)):
    try:
        result = supabase.table("projects").select("*").eq("clerk_id", clerk_id).execute()
        return {
            "message": "Projects retrieved successfully",
            "data": result.data
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get projects: {str(e)}")

@router.post("/api/projects")
def create_project(project: ProjectCreate, clerk_id: str = Depends(get_current_user)):
    try:
        project_result = supabase.table("projects").insert({
            "name": project.name,
            "description": project.description,
            "clerk_id" : clerk_id,
        }).execute()

        if not project_result.data:
            raise HTTPException(status_code=500, detail="Failed to create project")
        
        created_project = project_result.data[0]
       
        project_id = created_project["id"] # type: ignore

        # Creating default project settings
        project_setting_result = supabase.table("project_settings").insert({
            "project_id": project_id,
            "embedding_model": "text-embedding-3-small",
            "rag_strategy": "basic",
            "agent_type": "agentic",
            "chunks_per_search": 10,
            "final_context_size": 5,
            "similarity_threshold": 0.3,
            "number_of_queries": 5,
            "reranking_enabled": True,
            "reranking_model": "rerank-english-v3.0",
            "vector_weight": 0.7,
            "keyword_weight": 0.3, 
        }).execute()

        if not project_setting_result.data:
            supabase.table("projects").delete().eq("project_id",project_id).execute()
            raise HTTPException(status_code=500, detail="Failed to create project settings")

        return{
            "message": "Project created successfully",
            "data": created_project
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create project: {str(e)}")
    

@router.delete("/api/projects/{project_id}")
def delete_project(project_id: str, clerk_id: str = Depends(get_current_user)):

    try:
        # check project belongs to this user
        project_result = supabase.table("projects").select("*").eq("id", project_id).eq("clerk_id", clerk_id).execute()

        if not project_result.data:
            raise HTTPException(status_code=500, detail="Project not found or access denied")

        # Delete project( cascade handles all related data)
        deleted_project = supabase.table("projects").delete().eq("id", project_id).eq("clerk_id", clerk_id).execute()

        if not deleted_project.data:
            raise HTTPException(status_code=500, detail=f"Project not found or access denied")
        
        return {
            "message": "Project deleted successfully",
            "data": deleted_project.data[0]
        }
    

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete project: {str(e)}")
    
