from fastapi import APIRouter, HTTPException, Depends
from auth import get_current_user
from database import supabase, s3_client, BUCKET_NAME
from pydantic import BaseModel
import uuid

router = APIRouter(
    tags=["files"]
)

class FileUploadRequest(BaseModel):
    filename: str
    file_size: int
    file_type: str

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

@router.post("/api/projects/{project_id}/files/upload-url")
def get_upload_url(
    project_id: str,
    file_request: FileUploadRequest,
    clerk_id: str = Depends(get_current_user)
):
    try:
        # verify project exist and belong to the user
        result = supabase.table("projects").select("id").eq("id", project_id).eq("clerk_id", clerk_id).execute()
        if not result.data :
            raise HTTPException(status_code=400, detail="Project not found or access denied")

        
        # General unique S3 key
        file_extension = file_request.filename.split('.')[-1] if '.' in file_request.filename else ''
        unique_id = str(uuid.uuid4())
        s3_key = f"projects/{project_id}/documents/{unique_id}.{file_extension}"

        # Generate presigned URL (expires in 1 hour)
        presigned_url = s3_client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": BUCKET_NAME,
                "Key": s3_key,
                "ContentType": file_request.file_type
            },
            ExpiresIn=3600  # 1 hour
        )
        # create database record with pending files
        document_result = supabase.table("project_documents").insert({
            "project_id": project_id,
            "filename": file_request.filename,
            "s3_key": s3_key,
            "file_size": file_request.file_size,
            "file_type": file_request.file_type,
            "processing_status": "uploading",
            "clerk_id": clerk_id
            }).execute()

        if not document_result.data:
            raise HTTPException(status_code=500, detail="Failed to create document record")
        
        return {
            "message": "Upload URL generated successfully",
            "data": {
                "upload_url": presigned_url,
                "s3_key": s3_key,
                "document": document_result.data[0]
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate presigned url: {str(e)}")

@router.post("/api/projects/{project_id}/files/confirm")
def confirm_file_upload(
    project_id: str,
    confirm_request: dict,
    clerk_id: str = Depends(get_current_user)
): 
    try:
        s3_key = confirm_request.get("s3_key")

        if not s3_key:
            raise HTTPException(status_code=400, detail="s3_key is required")
        
        # update document status
        result = supabase.table("project_documents").update({
            "processing_status": "queued"
            }).eq("s3_key", s3_key).eq("project_id", project_id).eq("clerk_id", clerk_id).execute()
        
        document = result.data[0]

        if not result.data:
            raise HTTPException(status_code=404, detail="Document not found or access denied.")
        
        # start background preprocessing of current file with celery


        # return Json
        return {
            "message": "upload confirmed, processing started with celery",
            "data": document 
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to confirm processing of files: {str(e)}")

class UrlAddRequest(BaseModel):
    url: str

@router.post("/api/projects/{project_id}/url")
def add_website_url(
    project_id: str,
    url_request: UrlAddRequest,
    clerk_id: str = Depends(get_current_user)
):
    try:

        url = url_request.url.strip()
        if not url.startswith(('http://', 'https://')):
            url = "http://"+url

        result = supabase.table("project_documents").insert({
            "project_id": project_id,
            "filename": url,
            "s3_key": "",
            "file_size": 0,
            "file_type": "text/html",
            "processing_status": "queued",
            "clerk_id": clerk_id,
            "source_type": "url",
            "source_url": url
        }).execute()

        if not result.data:
            raise HTTPException(status_code=500, detail=f"Failed to create url record")

        # start background process





        return {
            "message": "Url added successfully",
            "data": result.data[0]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to add url: {str(e)}")



@router.delete("/api/projects/{project_id}/files/{file_id}")
def delete_project(project_id: str, file_id: str, clerk_id: str = Depends(get_current_user)):
    try:
        # get the file verified
        result = supabase.table("project_documents").select("*").eq("id", file_id).eq("project_id", project_id).eq("clerk_id", clerk_id).execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="File not found or access denied.")
        
        file_record = result.data[0] 
        s3_key = file_record["s3_key"] # type: ignore

        # Delete from s3 (only for documents, not url)

        if s3_key:
            try:
                s3_client.delete_object(Bucket= BUCKET_NAME, Key= s3_key)
                print("Deleted from s3")
            except Exception as e:
                print(f"Failed to delete from s3: {e}")


        # Delete document record from DB

        deleted_result = supabase.table("project_documents").delete().eq("id", file_id).execute()

        if not deleted_result.data:
            raise HTTPException(status_code=500, detail="Failed to delete file")

        return{
            "message": "File deleted successfully",
            "data": deleted_result.data[0]
        }

        


    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete file: {str(e)}")
